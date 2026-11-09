"""Core LLM-powered Balatro bot implementation."""

import asyncio
import contextvars
import dataclasses
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from openai.types.chat import ChatCompletion

from . import book, seeds
from .analysis import (
    BOSS_REROLL_MAX_PER_ANTE,
    DEADLINE_ANTE,
    deadline_commit,
    luna_reroll_refusal,
    main_commit,
    run_status,
    boss_reroll_reason,
    current_blind,
    estimate_play,
    discard_phase_order,
    joker_order,
    mark_view,
    play_estimate,
    round_record,
    summarize_outcome,
    swap_plan,
    shop_wrong_item_veto,
    validate_action,
)
from .client import BalatroClient, BalatroError
from .collector import (
    ChatCompletionError,
    ChatCompletionResponse,
    Collector,
    FinishReason,
    Stats,
    is_real_win,
)
from .config import Config, Task, get_model_config
from . import ledger
from .llm import LLMClient, LLMClientError, LLMTimeoutError
from .strategy import StrategyManager, StrategyManifest

logger = logging.getLogger(__name__)

# B0a (pass 4): the run a log record belongs to. Set per game inside its asyncio
# task (contextvars are task-local), so with parallel games every line, incl.
# llm.py / openai SDK lines made on the game's behalf, lands in its own run.log.
_RUN_LOG: contextvars.ContextVar[str | None] = contextvars.ContextVar("balatrollm_run_log", default=None)


class _RunFilter(logging.Filter):
    """Pass only records logged in the context of one run."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        return _RUN_LOG.get() == self.run_id

SHOP_STATES = ("SHOP", "SMODS_BOOSTER_OPENED")
# Refused calls in a row in one shop visit before the harness leaves the shop
SHOP_REFUSALS_TO_LEAVE = 3



SHOP_LOCK_MONEY = 10


def shop_lock_after(before: dict[str, Any], method: str, after: dict[str, Any]) -> bool:
    """P2-8 / owner F1: from Ante 4, one buy may take money below $10; after it
    the shop is over (no more buys or rerolls this visit)."""
    return (
        method == "buy"
        and before.get("state") == "SHOP"
        and int(before.get("ante_num") or 1) >= 4
        and int(after.get("money") or 0) < SHOP_LOCK_MONEY
    )

class BotError(Exception):
    """Base exception for bot errors."""

    pass


class Bot:
    """One-shot LLM-powered Balatro bot. Creates clients, plays a single game, returns stats."""

    # Pass 4 L defaults (class level, so bots built without __init__ in tests have them)
    _book: dict[str, Any] | None = None
    book_update_path: Path | None = None

    def __init__(self, task: Task, config: Config, port: int | None = None) -> None:
        self.task = task
        self.config = config
        self.port = port if port is not None else config.port
        self.model_config = get_model_config(config.model_config)
        self.strategy = StrategyManager(task.strategy)
        # Opt-in harness behaviour declared in the strategy manifest
        self.harness: dict[str, Any] = StrategyManifest.from_file(task.strategy).harness

        self._balatro: BalatroClient | None = None
        self._llm: LLMClient | None = None
        self._collector: Collector | None = None
        # B0c results ledger: the row being built for the current Luna call
        self._ledger_row: dict[str, Any] | None = None
        self._ledger_call: tuple[str, dict[str, Any]] | None = None
        self._ledger_out: dict[str, Any] = {}

        self._last_error_msg: str | None = None
        self._last_failed_msg: str | None = None
        self._history: list[dict[str, Any]] = []
        # One entry per finished blind (see analysis.round_record)
        self._rounds: list[dict[str, Any]] = []
        # Last SELECTING_HAND gamestate, used to summarise the blind at ROUND_EVAL
        self._last_hand_state: dict[str, Any] | None = None
        # Harness guards (only active when enabled in the strategy manifest)
        self._consecutive_vetoes: int = 0
        self._consecutive_rearranges: int = 0
        self._shop_rerolls: int = 0
        # One shop visit = SHOP plus any pack opened from it (SMODS_BOOSTER_OPENED)
        self._in_shop: bool = False
        self._shop_visits: int = 0
        self._shop_refusal_exits: int = 0
        # Committed MAIN_HAND, carried between decisions (P2-4)
        self._main_commit: dict[str, Any] | None = None
        self._deadline_deferred: int | None = None  # F5: round of the first deadline shop
        # After a buy took money below $10 from Ante 4, the shop is locked (F1)
        self._shop_locked: bool = False
        # Boss rerolls per ante, harness's and Luna's (decision C: at most 1)
        self._boss_rerolls: dict[int, int] = {}
        # C4: Luna's boss-reroll request from a shop {ante, boss}, run at the
        # next blind select of that ante
        self._boss_reroll_request: dict[str, Any] | None = None
        # Jokers were moved for a discard (P2-15): restore before the next play
        self._phase_moved: bool = False
        # Tags the harness skipped for that have not paid yet (M1)
        self._pending_tags: list[dict[str, Any]] = []

        # Pass 4 L: Luna's book (manifest ``book``); set up in play()
        self._book: dict[str, Any] | None = None
        self.book_update_path: Path | None = None

        # Finish reason tracking
        self._finish_reason: FinishReason | None = None
        # Separate counters for error calls vs failed calls
        self._consecutive_errors: int = 0
        self._consecutive_faileds: int = 0

    async def __aenter__(self) -> "Bot":
        """Initialize all clients."""
        self._balatro = BalatroClient(
            host=self.config.host,
            port=self.port,
        )
        await self._balatro.__aenter__()

        self._llm = LLMClient(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            api=self.config.api,
        )
        await self._llm.__aenter__()

        return self

    async def __aexit__(self, *_: Any) -> None:
        """Clean up all clients."""
        if self._llm is not None:
            await self._llm.__aexit__(None, None, None)
            self._llm = None
        if self._balatro is not None:
            await self._balatro.__aexit__(None, None, None)
            self._balatro = None

    def _setup_file_logging(self) -> None:
        """Send this game's log lines to its run directory's run.log.

        One FileHandler per game on the root logger, filtered by the game's
        context (B0a): parallel games no longer swap the root handlers.
        """
        if self._collector is None:
            return

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        log_file = self._collector.run_dir / "run.log"
        run_id = str(log_file)
        _RUN_LOG.set(run_id)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        file_handler.addFilter(_RunFilter(run_id))
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root_logger.addHandler(file_handler)
        self._file_handler = file_handler

    def _write_ledger(self, before: dict[str, Any], after: dict[str, Any] | None) -> None:
        """B0c: one decisions.jsonl row per Luna call (read-only for play)."""
        row = getattr(self, "_ledger_row", None)
        if row is None or self._collector is None:
            return
        self._ledger_row = None
        try:
            fn_name, fn_args = self._ledger_call or (None, None)
            ledger.finish_row(row, before, fn_args, fn_name, dict(self._ledger_out), after)
            self._collector.write_decision(row)
        except Exception as e:
            logger.warning(f"Ledger row failed: {e}")

    def _teardown_file_logging(self) -> None:
        handler = getattr(self, "_file_handler", None)
        if handler is None:
            return
        logging.getLogger().removeHandler(handler)
        handler.close()
        self._file_handler = None
        _RUN_LOG.set(None)

    async def _wait_for_menu(self, timeout: float = 10.0) -> None:
        """Wait for game to be in MENU state."""
        assert self._balatro is not None

        start = time.time()
        while time.time() - start < timeout:
            try:
                gamestate = await self._balatro.call("gamestate")
                if gamestate.get("state", "") == "MENU":
                    logger.debug("Confirmed MENU state")
                    return
            except Exception as e:
                logger.debug(f"Gamestate check failed: {e}")
            await asyncio.sleep(0.5)

        self._finish_reason = "connection_abort"
        raise BotError(f"Timeout waiting for MENU state after {timeout}s")

    async def play(self, runs_dir: Path = Path.cwd()) -> Stats:
        """Play a single game run. Returns final Stats."""
        if self._balatro is None or self._llm is None:
            raise RuntimeError(
                "Bot not initialized. Use 'async with Bot(config) as bot:'"
            )

        # Health check before initializing collector
        try:
            await self._balatro.call("gamestate")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            self._finish_reason = "connection_abort"
            raise BotError(
                f"Cannot connect to Balatro on {self.config.host}:{self.port}. "
                "Make sure Balatro instance started correctly."
            ) from e
        except Exception as e:
            self._finish_reason = "connection_abort"
            raise BotError(f"Failed to connect to Balatro: {e}") from e

        # RANDOM: generate a seed, record it under a private label, start on it;
        # SEED-<label>: replay a recorded seed (see seeds.py).
        start_args: dict[str, Any] = {"deck": self.task.deck, "stake": self.task.stake}
        random_start = seeds.is_random(self.task.seed)
        if random_start:
            label, start_args["seed"] = seeds.new_random()
            self.task = dataclasses.replace(self.task, seed=label)
        elif seeds.is_label(self.task.seed):
            start_args["seed"] = seeds.resolve(self.task.seed)
        else:
            start_args["seed"] = self.task.seed

        self._collector = Collector(self.task, runs_dir)
        self._setup_file_logging()

        logger.info("Starting game")
        logger.info(f"Run data will be saved to: {self._collector.run_dir}")
        if self.harness.get("book"):
            self._book_setup(runs_dir, start_args.get("seed"))

        try:
            await self._balatro.call("menu")
            await self._wait_for_menu()
            gamestate = await self._balatro.call("start", start_args)
            # RANDOM and SEED-<label> replays must both start on the recorded seed
            check_seed = random_start or seeds.is_label(self.task.seed)
            if check_seed and not seeds.started_on(start_args["seed"], gamestate):
                self._finish_reason = "unexpected_error"
                logger.error(f"Game did not start on the seed generated for {self.task.seed}")
                raise BotError(f"Game did not start on the seed generated for {self.task.seed}")
            await self._run_game_loop(gamestate)
            if self._book is not None and self._finish_reason in ("won", "lost"):
                await self._book_game_end()
        except BotError:
            logger.error("Game ended due to bot error")
            raise
        except Exception as e:
            self._finish_reason = "unexpected_error"
            logger.exception("Unexpected error occurred during gameplay")
            raise BotError(f"Unexpected error: {e}") from e
        finally:
            if self._collector:
                try:
                    reason: FinishReason = self._finish_reason or "unexpected_error"
                    self._collector.write_stats(reason)
                    logger.info("Stats written")
                except Exception as e:
                    logger.debug(
                        f"Could not write stats (normal if run failed early): {e}"
                    )
            self._teardown_file_logging()

        return self._collector._calculate_stats(
            self._finish_reason or "unexpected_error"
        )

    async def _run_game_loop(self, gamestate: dict[str, Any]) -> None:
        """Main game loop."""
        assert self._balatro is not None
        assert self._llm is not None
        assert self._collector is not None

        while True:
            if is_real_win(gamestate):
                if self._book is not None:
                    self._book["end_state"] = gamestate
                self._finish_reason = "won"
                logger.info("Game won! Waiting for GAME_OVER state...")
                break

            current_state = gamestate.get("state", "")
            logger.info(f"State: {current_state}")

            await asyncio.sleep(0.5)
            await self._balatro.call("gamestate")

            match current_state:
                case "SELECTING_HAND" | "SHOP" | "SMODS_BOOSTER_OPENED":
                    if current_state == "SELECTING_HAND":
                        self._last_hand_state = gamestate
                    self._track_shop_visit(gamestate)
                    self._annotate(gamestate)
                    decided_on = gamestate
                    self._ledger_call = None
                    self._ledger_out = {"result": "unknown"}
                    try:
                        response = await self._get_llm_response(gamestate)
                        gamestate = await self._execute_tool_call(response, gamestate)
                    except BaseException as e:
                        # B0c: the call that ends the run still gets its row (Sol g1 #1)
                        self._ledger_out.setdefault("abort", f"{type(e).__name__}: {e}")
                        self._write_ledger(decided_on, None)
                        raise
                    self._write_ledger(decided_on, gamestate)
                case "ROUND_EVAL":
                    if self._last_hand_state is not None:
                        self._rounds.append(
                            round_record(self._last_hand_state, gamestate)
                        )
                        if self._book is not None:
                            self._book["last_kind"] = (current_blind(self._last_hand_state) or {}).get("kind")
                        self._last_hand_state = None
                    gamestate = await self._balatro.call("cash_out")
                case "BLIND_SELECT":
                    # Rerolls a bad boss first (harness ``reroll_boss``), then
                    # selects every blind, except a skip for a tag the strategy
                    # opted into (harness ``skip_blind_tags``: tag -> last ante)
                    rerolled = await self._reroll_boss(gamestate)
                    if rerolled is not None:
                        gamestate = rerolled
                    elif self._skip_for_tag(gamestate):
                        gamestate = await self._balatro.call("skip")
                    else:
                        gamestate = await self._balatro.call("select")
                case "GAME_OVER":
                    if self._book is not None:
                        self._book["end_state"] = gamestate
                    self._finish_reason = "lost"
                    logger.info("Game over!")
                    break
                case _:
                    await asyncio.sleep(1)
                    gamestate = await self._balatro.call("gamestate")

    ############################################################################
    # Pass 4 L: Luna's book (only with manifest ``book``)
    ############################################################################

    def _book_setup(self, runs_dir: Path, own_seed: str | None) -> None:
        """Freeze the book version for this game and record its hash."""
        assert self._collector is not None
        store = book.store_dir(Path(runs_dir), self.task.strategy, self.harness)
        h, version = book.read_head(store)
        focus = str(self.harness.get("book_focus") or book.DEFAULT_FOCUS)
        if focus not in book.FOCUS:
            raise BotError(f"book_focus must be one of {book.FOCUS}")
        words = book.known_words(
            *((self.strategy.path / f).read_text()
              for f in ("STRATEGY.md.jinja", "GAMESTATE.md.jinja", "MEMORY.md.jinja", "BOOK.md.jinja")),
            (Path(__file__).parent / "knowledge.py").read_text(),
        )
        self._book = {
            "store": store, "hash": h, "version": version, "focus": focus,
            "seed": own_seed, "words": words, "notebook": [], "note_rounds": 0,
            "blocks": {}, "logged": set(), "shown": {}, "last_kind": None, "end_state": None,
        }
        self._collector.add_task_fields({"book": {
            "hash": h, "rules": len(version.get("rules") or []), "games": int(version.get("games") or 0),
            "focus": focus, "store": str(store),
        }})
        logger.info(f"Book version {h} ({len(version.get('rules') or [])} rules, focus {focus})")

    def _book_block(self, gamestate: dict[str, Any]) -> str:
        """The book text for this decision (same within an ante + phase) and
        the per-rule counters (rules shown per blind)."""
        b = self._book
        assert b is not None
        phase = book.phase_of(str(gamestate.get("state")))
        ante = int(gamestate.get("ante_num") or 1)
        boss = ((gamestate.get("blinds") or {}).get("boss") or {}).get("name")
        key = (phase, ante, boss)
        if key not in b["blocks"]:
            top, rules = book.select(b["version"], phase, ante, boss)
            summaries = (b["version"].get("summaries") or [])[-book.SUMMARIES_SHOWN:]
            text = self.strategy.env.get_template("BOOK.md.jinja").render(
                top=top, rules=rules, summaries=summaries, phase=phase, ante=ante, boss=boss,
                rule_line=book.rule_line,
            )
            b["blocks"][key] = (text, [r["id"] for r in top + rules])
        text, ids = b["blocks"][key]
        shown = b["shown"].setdefault(len(self._rounds), {})
        for rid in ids:
            shown[rid] = shown.get(rid, 0) + 1
        return text

    def _book_logged_request(self, request_data: dict[str, Any], book_part: dict[str, Any]) -> dict[str, Any]:
        """requests.jsonl keeps the book by hash; each block's text is written
        once per run to book_blocks.jsonl."""
        b = self._book
        assert b is not None and self._collector is not None
        text = book_part["text"]
        h = hashlib.sha256(text.encode()).hexdigest()[:16]
        if h not in b["logged"]:
            b["logged"].add(h)
            with (self._collector.run_dir / "book_blocks.jsonl").open("a") as f:
                f.write(json.dumps({"block": h, "book": b["hash"], "text": text}, ensure_ascii=False) + "\n")
        placeholder = {"type": "text", "text": f"[book block {h}: see book_blocks.jsonl]", "book_block": h,
                       "cache_control": book_part["cache_control"]}
        messages = [
            {**m, "content": [placeholder if part is book_part else part for part in m["content"]]}
            if isinstance(m.get("content"), list) else m
            for m in request_data["messages"]
        ]
        return {**request_data, "messages": messages}

    def _note_due(self, gamestate: dict[str, Any]) -> str | None:
        """A cue for the notebook: first decision (plan for Ante 1) and the
        first shop decision after each blind (one line; a plan after a boss)."""
        b = self._book
        assert b is not None
        if not self._rounds and not b["notebook"] and int(gamestate.get("ante_num") or 1) == 1:
            return "Write your plan for Ante 1 in one or two sentences."
        if gamestate.get("state") == "SHOP" and len(self._rounds) > b["note_rounds"]:
            r = self._rounds[-1]
            cue = f"You beat {r['blind']} (Ante {r['ante']}): one line on how it went."
            if b.get("last_kind") == "boss":
                cue += " A new ante starts next: add your plan for it."
            return cue
        return None

    def _take_note(self, note: Any, before: dict[str, Any]) -> None:
        b = self._book
        assert b is not None
        text = " ".join(str(note or "").split())[: book.MAX_NOTE_CHARS]
        if not text:
            return
        b["note_rounds"] = len(self._rounds)
        if b["notebook"] and b["notebook"][-1]["text"] == text:
            return
        b["notebook"].append({
            "ante": before.get("ante_num"), "round": before.get("round_num"),
            "phase": book.phase_of(str(before.get("state"))) or str(before.get("state") or "").lower(),
            "text": text,
        })
        b["notebook"] = b["notebook"][-book.MAX_NOTES:]

    def _book_game_report(self) -> tuple[str, str]:
        """(user message for the game-end call, code summary line). Built from
        harness records only (never the raw gamestate: it carries the seed)."""
        b = self._book
        assert b is not None
        last = self._last_hand_state or {}
        end = b.get("end_state") or {}
        won = self._finish_reason == "won"
        jokers = [str(j.get("label") or j.get("key") or "?") for j in ((end or last).get("jokers") or {}).get("cards") or []]
        mh = None
        try:
            from .analysis import main_hand
            mh = main_hand(last) if last else None
        except Exception:
            mh = None
        if won:
            result = "won the run (beat the Ante 8 boss)"
        else:
            cur = current_blind(last) or {}
            chips = int(((end or last).get("round") or {}).get("chips") or 0)
            result = (f"lost at Ante {last.get('ante_num')}, {cur.get('name') or 'blind'}: scored {chips:,} "
                      f"of {int(cur.get('score') or 0):,}")
        code_summary = f"{result}; main hand {mh or 'open'}; jokers: {', '.join(jokers) or 'none'}"
        lines = [f"# THIS GAME\n- Result: {result}", f"- Main hand: {mh or 'open'}",
                 f"- Jokers at the end: {', '.join(jokers) or 'none'}", "", "## Blinds (oldest first)"]
        for r in self._rounds:
            lines.append(f"- Ante {r['ante']} {r['blind']}: scored {r['scored']:,} / {r['target']:,}, "
                         f"{r['hands_left']} hands left{', most played ' + r['main_hand'] if r.get('main_hand') else ''}")
        if not self._rounds:
            lines.append("- (no blind beaten)")
        lines += ["", "## Your notebook"]
        lines += [f"- Ante {n['ante']}, round {n['round']} ({n['phase']}): {n['text']}" for n in b["notebook"]] or ["- (empty)"]
        lines += ["", "## Your last actions (oldest first)"]
        for e in self._history[-15:]:
            why = str(e.get("reasoning") or "")[:220]
            lines.append(f"- Ante {e.get('ante')} {e.get('method')} -> {e.get('result') or 'ok'}" + (f" | why: {why}" if why else ""))
        lines += ["", "Now call update_book."]
        return "\n".join(lines), code_summary

    async def _book_game_end(self) -> None:
        """One extra Luna call: proposes at most 3 book edits; the checked
        edits go to book_update.json (merged by the executor in task order).
        A failure here is logged and never changes the game's result."""
        b = self._book
        assert b is not None and self._llm is not None and self._collector is not None
        record: dict[str, Any] = {
            "label": self.task.seed, "store": str(b["store"]), "book_hash": b["hash"], "focus": b["focus"],
            "merged": False,
        }
        usage: dict[str, Any] = {}
        args: dict[str, Any] = {}
        started = time.time()
        try:
            version = b["version"]
            system = self.strategy.env.get_template("BOOK_UPDATE.md.jinja").render(
                rules=version.get("rules") or [], n_rules=len(version.get("rules") or []),
                max_rules=book.MAX_RULES, focus=b["focus"], max_edits=book.MAX_EDITS,
                max_chars=book.MAX_RULE_CHARS, max_summary=book.MAX_SUMMARY_CHARS, rule_line=book.rule_line,
            )
            user, code_summary = self._book_game_report()
            record["code_summary"] = code_summary
            messages = [
                {"role": "system", "content": [{"type": "text", "text": system}]},
                {"role": "user", "content": [{"type": "text", "text": user}]},
            ]
            tools = self.strategy.get_tools("BOOK_UPDATE")
            record["request"] = {"model": self.task.model, "messages": messages, "tools": tools}
            response = await self._llm.call(
                model=self.task.model, messages=messages, tools=tools, model_config=self.model_config
            )
            body = response.model_dump()
            record["response"] = body
            usage = body.get("usage") or {}
            calls = response.choices[0].message.tool_calls or []
            if calls:
                fn = getattr(calls[0], "function", calls[0])
                parsed = json.loads(getattr(fn, "arguments", "") or "{}")
                args = parsed if isinstance(parsed, dict) else {}
            else:
                record["error"] = "no tool call in the reply"
        except Exception as e:  # noqa: BLE001 - the game is over; never fail it here
            logger.warning(f"Book update call failed: {type(e).__name__}: {e}")
            record["error"] = f"{type(e).__name__}: {e}"
        record["time_ms"] = int((time.time() - started) * 1000)
        record["proposed"] = args.get("edits")
        kept, rejected = book.check_edits(args.get("edits"), b["version"], b["focus"], b["seed"], b["words"])
        record["kept"], record["rejected"] = kept, rejected
        summary = " ".join(str(args.get("summary") or "").split())[: book.MAX_SUMMARY_CHARS]
        if summary and book.text_problems(summary, b["seed"], b["words"]):
            record["summary_rejected"] = book.text_problems(summary, b["seed"], b["words"])
            summary = ""
        base = record.get("code_summary") or ""
        record["summary"] = f"{base}. Your note: {summary}" if summary else base
        record["rule_stats"] = book.rule_stats(b["shown"], len(self._rounds), self._finish_reason == "won")
        record["usage"] = usage
        path = self._collector.run_dir / "book_update.json"
        path.write_text(json.dumps(record, indent=1, ensure_ascii=False, default=str))
        self.book_update_path = path
        self._collector.extra_stats["book_update"] = {
            "cost": float(usage.get("cost") or 0),
            "tokens_in": int(usage.get("prompt_tokens") or 0),
            "tokens_out": int(usage.get("completion_tokens") or 0),
            "time_ms": record["time_ms"],
            "edits_kept": len(kept),
            "edits_rejected": len(rejected),
        }
        logger.info(f"Book update: {len(kept)} edits kept, {len(rejected)} rejected")

    async def _reroll_boss(self, gamestate: dict[str, Any]) -> dict[str, Any] | None:
        """Reroll the boss when the strategy opted in and the boss is a bad one.

        Returns the new gamestate, or None when no reroll was made.
        """
        assert self._balatro is not None
        auto = bool(self.harness.get("reroll_boss"))
        # Pass 4 A1: Luna's own request (``luna_reroll_boss``) runs even with
        # the automatic rerolls (``reroll_boss``) off
        if not auto and not self._luna_reroll_on():
            return None
        ante = int(gamestate.get("ante_num") or 1)
        self._clear_stale_request(gamestate)
        if getattr(self, "_boss_reroll_request", None) is not None and self._luna_reroll_on():
            done = await self._luna_reroll(gamestate)
            if done is not None:
                return done
        if not auto:
            return None
        if self._boss_rerolls.get(ante, 0) >= BOSS_REROLL_MAX_PER_ANTE:
            return None
        reason = boss_reroll_reason(gamestate)
        if reason is None:
            return None
        self._boss_rerolls[ante] = self._boss_rerolls.get(ante, 0) + 1
        old = ((gamestate.get("blinds") or {}).get("boss") or {}).get("name", "")
        try:
            after = await self._balatro.call("reroll_boss")
        except BalatroError as e:
            logger.warning(f"Boss reroll failed: {e}")
            return None
        new = ((after.get("blinds") or {}).get("boss") or {}).get("name", "")
        logger.info(f"Harness rerolled boss {old} -> {new} ({reason})")
        self._history.append(
            {
                "method": "reroll_boss",
                "params": {},
                "reasoning": f"harness: {reason}",
                "state": "BLIND_SELECT",
                "ante": gamestate.get("ante_num"),
                "round": gamestate.get("round_num"),
                "result": f"harness rerolled the boss for $10: {old} -> {new}",
                "score": None,
                "estimate": None,
            }
        )
        return after

    def _clear_stale_request(self, gamestate: dict[str, Any]) -> None:
        """C4: a request lapses when the ante moves on or its boss is beaten."""
        req = getattr(self, "_boss_reroll_request", None)
        if req is None:
            return
        boss = (gamestate.get("blinds") or {}).get("boss") or {}
        if int(gamestate.get("ante_num") or 1) != req["ante"] or boss.get("status") == "DEFEATED":
            logger.info(f"Luna's boss reroll request for {req['boss']} lapsed (ante {req['ante']} is over)")
            self._boss_reroll_request = None

    async def _luna_reroll(self, gamestate: dict[str, Any]) -> dict[str, Any] | None:
        """C4: run Luna's queued boss reroll at blind select, re-checked now
        (she may have spent below $10 after asking). A failure is logged and
        does not use the ante's reroll; the request stays for the next blind
        select of the ante."""
        assert self._balatro is not None
        req = self._boss_reroll_request
        assert req is not None
        ante = int(gamestate.get("ante_num") or 1)
        check = {**gamestate, "luna": {**(gamestate.get("luna") or {}), "boss_rerolls": self._boss_rerolls.get(ante, 0)}}
        if not self._advice_vetoes_on():  # pass 4 A1: BLIND_SELECT states are not annotated
            check["luna"]["advice_vetoes"] = False
        why = luna_reroll_refusal(check)
        old = ((gamestate.get("blinds") or {}).get("boss") or {}).get("name", "")
        if why is not None:
            logger.info(f"Luna's boss reroll could not run at blind select: {why}")
            return None
        try:
            after = await self._balatro.call("reroll_boss")
        except BalatroError as e:
            logger.warning(f"Luna's boss reroll could not run at blind select: {e}")
            return None
        self._boss_rerolls[ante] = self._boss_rerolls.get(ante, 0) + 1
        self._boss_reroll_request = None
        new = ((after.get("blinds") or {}).get("boss") or {}).get("name", "")
        logger.info(f"Luna asked for a boss reroll: {old} -> {new}")
        self._history.append(
            {
                "method": "reroll_boss",
                "params": {},
                "reasoning": f"your request ({req['boss']})",
                "state": "BLIND_SELECT",
                "ante": gamestate.get("ante_num"),
                "round": gamestate.get("round_num"),
                "result": f"boss rerolled for $10 as you asked: {old} -> {new}",
                "score": None,
                "estimate": None,
            }
        )
        return after

    async def _queue_boss_reroll(self, before: dict[str, Any], fn_args: dict[str, Any]) -> dict[str, Any]:
        self._ledger_out = {"result": "queued_boss_reroll"}
        """C4: Luna's reroll_boss in a shop is a harness intent, never sent to
        BalatroBot (the game rerolls only at blind select)."""
        assert self._balatro is not None
        assert self._collector is not None
        boss = ((before.get("blinds") or {}).get("boss") or {}).get("name", "")
        self._boss_reroll_request = {"ante": int(before.get("ante_num") or 1), "boss": boss}
        logger.info(f"Luna asked for a boss reroll of {boss} (queued for the next blind select)")
        self._collector.record_call("successful")
        self._consecutive_vetoes = 0
        self._consecutive_errors = 0
        self._consecutive_faileds = 0
        self._last_error_msg = None
        self._last_failed_msg = None
        self._history.append(
            {
                "method": "reroll_boss",
                "params": {},
                "reasoning": str(fn_args.get("reasoning", "")),
                "state": before.get("state", ""),
                "ante": before.get("ante_num"),
                "round": before.get("round_num"),
                "result": f"boss reroll queued for the next blind select ({boss}; $10 then)",
                "score": None,
                "estimate": None,
            }
        )
        return await self._balatro.call("gamestate")

    def _skip_for_tag(self, gamestate: dict[str, Any]) -> bool:
        """True when the blind on deck offers a tag the strategy skips for."""
        wanted = self.harness.get("skip_blind_tags") or {}
        ante = int(gamestate.get("ante_num") or 1)
        for blind in (gamestate.get("blinds") or {}).values():
            if blind.get("status") == "SELECT" and blind.get("type") != "BOSS":
                last_ante = wanted.get(blind.get("tag_name"))
                if last_ante is not None and ante <= int(last_ante):
                    logger.info(f"Skipping {blind.get('name')} for {blind.get('tag_name')}")
                    self._pending_tags.append({"tag": blind.get("tag_name"), "ante": ante})
                    return True
        return False

    async def _get_llm_response(self, gamestate: dict[str, Any]) -> ChatCompletion:
        """Get LLM response for current game state."""
        assert self._balatro is not None
        assert self._llm is not None
        assert self._collector is not None

        context: dict[str, Any] = {
            "rounds": self._rounds,
            "history": self._history,
            "flags": self.harness,
        }
        strategy_content = self.strategy.render_strategy(gamestate, **context)
        gamestate_content = self.strategy.render_gamestate(gamestate, **context)
        book_ctx: dict[str, Any] = {}
        if self._book is not None:
            book_ctx = {"notebook": self._book["notebook"], "note_due": self._note_due(gamestate)}
        memory_content = self.strategy.render_memory(
            history=self._history[-10:],
            last_error=self._last_error_msg,
            last_failure=self._last_failed_msg,
            G=gamestate,
            rounds=self._rounds,
            flags=self.harness,
            **book_ctx,
        )

        strategy_block = {
            "type": "text",
            "text": strategy_content,
            "cache_control": {"type": "ephemeral"},
        }
        system_parts: list[dict[str, Any]] = [strategy_block]
        book_part: dict[str, Any] | None = None
        if self._book is not None:
            # Pass 4 L: the book before the rulebook (cached prefix shared by phases)
            book_part = {"type": "text", "text": self._book_block(gamestate), "cache_control": {"type": "ephemeral"}}
            system_parts = [book_part, strategy_block]
        if self.harness.get("system_prompt"):
            # Static rulebook in the system role, dynamic state in the user turn
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_parts},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": gamestate_content},
                        {"type": "text", "text": memory_content},
                    ],
                },
            ]
        else:
            messages = [
                {
                    "role": "user",
                    "content": [
                        *system_parts,
                        {"type": "text", "text": gamestate_content},
                        {"type": "text", "text": memory_content},
                    ],
                }
            ]

        # B0c: what the harness computed for this decision (rendered or not)
        try:
            self._ledger_row = ledger.pre_row(gamestate, self._rounds, self._history, self.harness)
        except Exception as e:
            logger.warning(f"Ledger pre-row failed: {e}")
            self._ledger_row = None

        tools = self.strategy.get_tools(gamestate["state"])

        request_data = {
            "model": self.task.model,
            "messages": messages,
            "tools": tools,
            **self.model_config,
        }

        logged = request_data if book_part is None else self._book_logged_request(request_data, book_part)
        custom_id = self._collector.write_request(logged)
        if self._ledger_row is not None:
            self._ledger_row["custom_id"] = custom_id
        request_id = str(time.time_ns() // 1_000_000)

        try:
            response = await self._llm.call(
                model=self.task.model,
                messages=messages,
                tools=tools,
                model_config=self.model_config,
            )

            try:
                await self._balatro.call(
                    "screenshot",
                    {"path": str(self._collector.screenshot_dir / f"{custom_id}.png")},
                )
            except BalatroError as e:
                logger.warning(f"Screenshot failed: {e}")

            self._collector.write_response(
                id=str(time.time_ns() // 1_000_000),
                custom_id=custom_id,
                response=ChatCompletionResponse(
                    request_id=request_id,
                    status_code=200,
                    body=response.model_dump(),
                ),
            )

            return response

        except LLMTimeoutError as e:
            self._collector.write_response(
                id=str(time.time_ns() // 1_000_000),
                custom_id=custom_id,
                error=ChatCompletionError(code="timeout", message=str(e)),
            )
            self._finish_reason = "llm_abort"
            raise BotError("3 consecutive LLM timeouts") from e

        except LLMClientError as e:
            self._collector.write_response(
                id=str(time.time_ns() // 1_000_000),
                custom_id=custom_id,
                error=ChatCompletionError(code="error", message=str(e)),
            )
            self._finish_reason = "llm_abort"
            raise BotError(f"LLM error: {e}") from e

    async def _execute_tool_call(
        self, response: ChatCompletion, before: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute tool call from LLM response.

        Args:
            response: LLM response containing the tool call
            before: Gamestate the decision was made on (used to summarise the
                outcome of the action in the memory log)
        """
        assert self._balatro is not None
        assert self._collector is not None

        ################################################################################
        # Parse tool call from LLM response
        ################################################################################

        message = response.choices[0].message

        if not hasattr(message, "tool_calls") or not message.tool_calls:
            return await self._handle_error_call(
                f"No tool calls in LLM response: {message.content}"
            )

        tool_call = message.tool_calls[0]
        function_obj = getattr(tool_call, "function", tool_call)

        fn_name = getattr(function_obj, "name", None)
        if not fn_name:
            return await self._handle_error_call("Invalid tool call: missing name")

        fn_args_str = getattr(function_obj, "arguments", None)
        if not fn_args_str:
            return await self._handle_error_call("Invalid tool call: missing arguments")

        try:
            fn_args = json.loads(fn_args_str)
        except json.JSONDecodeError as e:
            return await self._handle_error_call(
                f"Invalid JSON in tool call arguments: {e}"
            )

        if not isinstance(fn_args, dict):
            return await self._handle_error_call("Tool arguments must be a JSON object")

        before = before or {}
        params = {k: v for k, v in fn_args.items() if k != "reasoning"}
        if self._book is not None:
            # Pass 4 L: the notebook field never reaches BalatroBot
            params.pop("note", None)
            self._take_note(fn_args.get("note"), before or {})
        self._ledger_call = (fn_name, fn_args)

        ################################################################################
        # Harness guards (opt-in via strategy manifest)
        ################################################################################

        veto: str | None = None
        self._track_shop_visit(before)
        if self.harness.get("validate_actions") and before:
            veto = validate_action(
                before, fn_name, params, self._shop_rerolls, advice=self._advice_vetoes_on()
            )
            if veto is None and fn_name == "buy":
                # pass 4 F1: wrong-item buy (repairs Luna's intent; on with advice vetoes off too)
                veto = shop_wrong_item_veto(before, params, str(fn_args.get("reasoning") or ""))
        max_rearranges = int(self.harness.get("max_consecutive_rearranges", 0) or 0)
        if fn_name == "rearrange":
            self._consecutive_rearranges += 1
            if max_rearranges and self._consecutive_rearranges > max_rearranges:
                veto = (
                    "You already rearranged; rearranging again changes nothing. "
                    "Choose a different action now."
                )
        else:
            self._consecutive_rearranges = 0
        if veto is not None:
            return await self._handle_veto(veto, before)
        if fn_name == "reroll_boss" and before.get("state") in SHOP_STATES:
            if not self._luna_reroll_on():
                return await self._handle_veto("Boss reroll refused: not available in this strategy.", before)
            if why := luna_reroll_refusal(before, legal_only=not self._advice_vetoes_on()):
                return await self._handle_veto(f"Boss reroll refused: {why}.", before)
            return await self._queue_boss_reroll(before, fn_args)
        if fn_name == "reroll":
            self._shop_rerolls += 1

        swap_note = ""
        if self.harness.get("auto_swap_jokers") and before:
            swap = swap_plan(before, fn_name, params)
            if isinstance(swap, str):
                return await self._handle_veto(swap, before)
            if swap:
                try:
                    await self._balatro.call("sell", {"joker": swap["sell"]})
                except BalatroError as e:
                    return await self._handle_failed_call(f"BalatroError: {e}")
                logger.info(f"Harness sold {swap['label']} to make room for {swap['buy']}")
                swap_note = f"harness sold {swap['label']} (WEAKEST) to make room; "

        if self.harness.get("joker_phase_order") and before.get("state") == "SELECTING_HAND":
            await self._phase_order(before, fn_name, params)

        if (
            fn_name == "next_round"
            and self.harness.get("auto_reorder_jokers")
            and before.get("state") == "SHOP"
        ):
            order = joker_order(before)
            if order is not None:
                try:
                    await self._balatro.call("rearrange", {"jokers": order})
                    logger.info(f"Harness re-ordered jokers: {order}")
                except BalatroError as e:
                    logger.warning(f"Auto joker reorder failed: {e}")

        estimate: int | None = None
        flush_suit: str | None = None
        if fn_name == "play" and before.get("state") == "SELECTING_HAND":
            try:
                # C3: under The Mark face-down cards are masked (the estimate
                # lands in MEMORY; it must not use their real ranks)
                seen = mark_view(before)
                hand = seen.get("hand", {}).get("cards", [])
                chosen = [int(i) for i in params.get("cards", [])]
                played = [hand[i] for i in sorted(chosen)]
                held = [c for i, c in enumerate(hand) if i not in chosen]
                est = estimate_play(seen, played, held)
                # the estimate Luna can know (face-down cards: the face-card average)
                estimate = play_estimate(before, chosen)
                if "Flush" in est["hand"]:  # C6: the suit of Flush plays (MAIN_SUIT at the deadline)
                    suits = [str((c.get("value") or {}).get("suit") or "") for c in played]
                    flush_suit = max(set(suits) - {""}, key=suits.count, default=None)
            except (IndexError, TypeError, ValueError):
                estimate = None

        ################################################################################
        # Execute tool call
        ################################################################################

        try:
            logger.info(f"Executing: {fn_name}({fn_args})")
            gamestate = await self._balatro.call(fn_name, params)

            self._collector.reset_failures()
            # Reset both consecutive counters on success
            self._consecutive_errors = 0
            self._consecutive_faileds = 0
            self._last_error_msg = None
            self._last_failed_msg = None
            self._collector.record_call("successful")
            self._collector.write_gamestate(gamestate)
            self._consecutive_vetoes = 0
            if self.harness.get("shop_lock", True) and shop_lock_after(before, fn_name, gamestate):
                self._shop_locked = True
                logger.info("Harness locked the shop: Ante 4+ buy left money below $10")
            result = swap_note + summarize_outcome(fn_name, params, before, gamestate)
            self._ledger_out = {"result": "ok", "summary": result, "harness_sold": swap_note or None}
            score: int | None = None
            if fn_name == "play":
                chips_before = int((before.get("round") or {}).get("chips") or 0)
                chips_after = int((gamestate.get("round") or {}).get("chips") or 0)
                if chips_after >= chips_before:
                    score = chips_after - chips_before
                if estimate is not None:
                    result += f" [estimate was {estimate:,}]"
                    logger.info(f"Score estimate vs actual: {estimate} vs {score}")
            self._history.append(
                {
                    "method": fn_name,
                    "params": params,
                    "reasoning": str(fn_args.get("reasoning", "")),
                    "state": before.get("state", ""),
                    "ante": before.get("ante_num"),
                    "round": before.get("round_num"),
                    "result": result,
                    "score": score,
                    "estimate": estimate,
                    **({"flush_suit": flush_suit} if flush_suit else {}),
                }
            )

            return gamestate

        except BalatroError as e:
            return await self._handle_failed_call(f"BalatroError: {e}")

        except httpx.TransportError as e:
            logger.warning(f"Game transport error during tool call: {e}")
            self._collector.record_call("failed")
            try:
                return await self._balatro.call("gamestate")
            except Exception:
                self._finish_reason = "connection_abort"
                raise BotError(f"Game unresponsive after transport error: {e}") from e

    async def _handle_error_call(self, msg: str) -> dict[str, Any]:
        """Handle invalid LLM response (no valid tool call)."""
        assert self._balatro is not None
        assert self._collector is not None

        logger.warning(f"Error call: {msg}")
        self._ledger_out = {"result": "error", "msg": msg}
        self._last_error_msg = msg
        self._collector.record_failure()
        self._collector.record_call("error")

        # Track consecutive error calls separately
        self._consecutive_errors += 1
        self._consecutive_faileds = 0

        if self._consecutive_errors >= Collector.MAX_CONSECUTIVE_FAILURES:
            self._finish_reason = "consecutive_error_calls"
            raise BotError("Too many consecutive error calls")

        return await self._balatro.call("gamestate")

    async def _phase_order(self, before: dict[str, Any], method: str, params: dict[str, Any]) -> None:
        """P2-15: before a discard that pays a discard joker, put Blueprint /
        Brainstorm onto it; before the next play, restore joker_order."""
        assert self._balatro is not None
        order: list[int] | None = None
        if method == "discard":
            order = discard_phase_order(before, params.get("cards") or [])
            moved = order is not None
        elif method == "play" and getattr(self, "_phase_moved", False):
            order = joker_order(before)
            moved = False
            self._phase_moved = False
        else:
            return
        if order is None:
            return
        try:
            await self._balatro.call("rearrange", {"jokers": order})
            self._phase_moved = moved
            logger.info(f"Harness joker phase order for {method}: {order}")
        except BalatroError as e:
            logger.warning(f"Joker phase order failed: {e}")

    def _track_shop_visit(self, before: dict[str, Any]) -> None:
        """Count shop visits; per-visit counters reset when the state leaves the shop."""
        in_shop = before.get("state") in SHOP_STATES
        if in_shop and not self._in_shop:
            self._shop_visits += 1
        if not in_shop:
            self._shop_rerolls = 0
            self._shop_locked = False
        self._in_shop = in_shop

    def _luna_reroll_on(self) -> bool:
        """Pass 4 A1: Luna's own reroll_boss requests (``luna_reroll_boss``;
        absent = follows ``reroll_boss`` as before)."""
        return bool(self.harness.get("luna_reroll_boss", self.harness.get("reroll_boss")))

    def _advice_vetoes_on(self) -> bool:
        """Pass 4 A1: validate_action's advice vetoes (``advice_vetoes``,
        absent = on); the legality checks follow ``validate_actions``."""
        return bool(self.harness.get("advice_vetoes", True))

    def _annotate(self, gamestate: dict[str, Any]) -> None:
        """Harness facts the templates and validate_action read from ``G["luna"]``."""
        self._main_commit = main_commit(gamestate, self._main_commit)
        ante = int(gamestate.get("ante_num") or 1)
        if (
            self._main_commit is None
            and gamestate.get("state") == "SHOP"
            and ante >= DEADLINE_ANTE
            and self.harness.get("deadline_commit", True)  # pass 4 A1
        ):
            # C6: still OPEN at the end of Ante 2 -> commit (sticky like a joker commit).
            # F5: no hand played twice -> stay OPEN for this shop, commit with the fallback at the next one
            rnd = int(gamestate.get("round_num") or 0)
            deferred = getattr(self, "_deadline_deferred", None)
            if deferred is None:
                deferred = self._deadline_deferred = rnd
            self._main_commit = deadline_commit(gamestate, self._history, final=rnd > deferred)
            if self._main_commit is not None:
                logger.info(f"Harness MAIN_HAND deadline commit: {self._main_commit['hand']} ({self._main_commit['trigger']})")
        self._clear_stale_request(gamestate)
        # Investment Tag pays at this ante's boss cash-out: gone once the ante moves on
        self._pending_tags = [t for t in getattr(self, "_pending_tags", []) if t["ante"] >= ante]
        gamestate["luna"] = {
            "pending_tags": list(self._pending_tags),
            "main_commit": self._main_commit,
            "first_shop": self._in_shop and self._shop_visits == 1,
            "shop_locked": self._shop_locked,
            "sell_in_pack": bool(self.harness.get("sell_in_pack")),
            # C4: Luna's boss reroll (harness flag reroll_boss runs it)
            "luna_reroll": self._luna_reroll_on(),
            "boss_rerolls": getattr(self, "_boss_rerolls", {}).get(ante, 0),
            "boss_reroll_request": getattr(self, "_boss_reroll_request", None),
        }
        if not self._advice_vetoes_on():
            # pass 4 A1: only added when off, so G["luna"] is unchanged for mastery
            gamestate["luna"]["advice_vetoes"] = False
        if gamestate.get("state") in SHOP_STATES:
            # The STATUS Luna sees (with the run's rounds: safety net, last
            # blind on its final hand); the validators use it too
            status = run_status(gamestate, self._rounds, self._history)["status"]
            gamestate["luna"]["status"] = status

    async def _handle_veto(
        self, msg: str, before: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle an action refused by the harness before reaching the game.

        In a shop, repeated refusals make the harness leave the shop for Luna
        (owner, pass 1 Seed P) instead of ending a live run.
        """
        assert self._balatro is not None
        assert self._collector is not None

        logger.warning(f"Vetoed call: {msg}")
        self._ledger_out = {"result": "vetoed", "msg": msg}
        self._last_failed_msg = f"Refused by harness: {msg}"
        self._collector.record_call("failed")
        self._consecutive_vetoes += 1
        state = (before or {}).get("state")
        if state in SHOP_STATES and self._consecutive_vetoes >= SHOP_REFUSALS_TO_LEAVE:
            return await self._leave_shop(before or {})
        if self._consecutive_vetoes >= 5:
            self._finish_reason = "consecutive_failed_calls"
            raise BotError("Too many consecutive refused calls")
        return await self._balatro.call("gamestate")

    async def _leave_shop(self, before: dict[str, Any]) -> dict[str, Any]:
        """Skip an open pack, then call next_round for Luna (logged)."""
        assert self._balatro is not None
        n = self._consecutive_vetoes
        self._consecutive_vetoes = 0
        self._shop_refusal_exits += 1
        money = before.get("money")
        forced = self._ledger_out.setdefault("harness_forced", [])  # B0c (Sol g1 #3)
        try:
            gamestate = before
            if before.get("state") == "SMODS_BOOSTER_OPENED":
                gamestate = await self._balatro.call("pack", {"skip": True})
                forced.append("pack(skip)")
            if gamestate.get("state") == "SHOP":
                gamestate = await self._balatro.call("next_round")
                forced.append("next_round")
        except BalatroError as e:
            logger.warning(f"Harness could not leave the shop: {e}")
            forced.append(f"failed: {e}")
            return await self._balatro.call("gamestate")
        logger.info(f"Harness left the shop after {n} refusals in a row (money ${money})")
        self._last_failed_msg = (
            f"The harness left the shop for you after {n} refused actions in a row."
        )
        self._history.append(
            {
                "method": "next_round",
                "params": {},
                "reasoning": f"harness: left the shop after {n} refusals",
                "state": before.get("state", ""),
                "ante": before.get("ante_num"),
                "round": before.get("round_num"),
                "result": f"harness left the shop after {n} refused actions (${money})",
                "score": None,
                "estimate": None,
            }
        )
        return gamestate

    async def _handle_failed_call(self, msg: str) -> dict[str, Any]:
        """Handle valid tool call that resulted in BalatroError."""
        assert self._balatro is not None
        assert self._collector is not None

        logger.warning(f"Failed call: {msg}")
        self._ledger_out = {"result": "failed", "msg": msg}
        self._last_failed_msg = msg
        self._collector.record_failure()
        self._collector.record_call("failed")

        # Track consecutive failed calls separately
        self._consecutive_faileds += 1
        self._consecutive_errors = 0

        if self._consecutive_faileds >= Collector.MAX_CONSECUTIVE_FAILURES:
            self._finish_reason = "consecutive_failed_calls"
            raise BotError("Too many consecutive failed calls")

        return await self._balatro.call("gamestate")

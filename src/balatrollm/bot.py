"""Core LLM-powered Balatro bot implementation."""

import asyncio
import contextvars
import dataclasses
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from openai.types.chat import ChatCompletion

from . import seeds
from .analysis import (
    BOSS_REROLL_MAX_PER_ANTE,
    DEADLINE_ANTE,
    deadline_commit,
    luna_reroll_refusal,
    main_commit,
    run_status,
    boss_reroll_reason,
    estimate_play,
    discard_phase_order,
    joker_order,
    mark_view,
    play_estimate,
    round_record,
    summarize_outcome,
    swap_plan,
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
                    response = await self._get_llm_response(gamestate)
                    gamestate = await self._execute_tool_call(response, gamestate)
                case "ROUND_EVAL":
                    if self._last_hand_state is not None:
                        self._rounds.append(
                            round_record(self._last_hand_state, gamestate)
                        )
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
                    self._finish_reason = "lost"
                    logger.info("Game over!")
                    break
                case _:
                    await asyncio.sleep(1)
                    gamestate = await self._balatro.call("gamestate")

    async def _reroll_boss(self, gamestate: dict[str, Any]) -> dict[str, Any] | None:
        """Reroll the boss when the strategy opted in and the boss is a bad one.

        Returns the new gamestate, or None when no reroll was made.
        """
        assert self._balatro is not None
        if not self.harness.get("reroll_boss"):
            return None
        ante = int(gamestate.get("ante_num") or 1)
        self._clear_stale_request(gamestate)
        if getattr(self, "_boss_reroll_request", None) is not None:
            done = await self._luna_reroll(gamestate)
            if done is not None:
                return done
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
        memory_content = self.strategy.render_memory(
            history=self._history[-10:],
            last_error=self._last_error_msg,
            last_failure=self._last_failed_msg,
            G=gamestate,
            rounds=self._rounds,
            flags=self.harness,
        )

        strategy_block = {
            "type": "text",
            "text": strategy_content,
            "cache_control": {"type": "ephemeral"},
        }
        if self.harness.get("system_prompt"):
            # Static rulebook in the system role, dynamic state in the user turn
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": [strategy_block]},
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
                        strategy_block,
                        {"type": "text", "text": gamestate_content},
                        {"type": "text", "text": memory_content},
                    ],
                }
            ]

        tools = self.strategy.get_tools(gamestate["state"])

        request_data = {
            "model": self.task.model,
            "messages": messages,
            "tools": tools,
            **self.model_config,
        }

        custom_id = self._collector.write_request(request_data)
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

        ################################################################################
        # Harness guards (opt-in via strategy manifest)
        ################################################################################

        veto: str | None = None
        self._track_shop_visit(before)
        if self.harness.get("validate_actions") and before:
            veto = validate_action(before, fn_name, params, self._shop_rerolls)
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
            if not self.harness.get("reroll_boss"):
                return await self._handle_veto("Boss reroll refused: not available in this strategy.", before)
            if why := luna_reroll_refusal(before):
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
            if shop_lock_after(before, fn_name, gamestate):
                self._shop_locked = True
                logger.info("Harness locked the shop: Ante 4+ buy left money below $10")
            result = swap_note + summarize_outcome(fn_name, params, before, gamestate)
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

    def _annotate(self, gamestate: dict[str, Any]) -> None:
        """Harness facts the templates and validate_action read from ``G["luna"]``."""
        self._main_commit = main_commit(gamestate, self._main_commit)
        ante = int(gamestate.get("ante_num") or 1)
        if self._main_commit is None and gamestate.get("state") == "SHOP" and ante >= DEADLINE_ANTE:
            # C6: still OPEN at the end of Ante 2 -> commit (sticky like a joker commit)
            self._main_commit = deadline_commit(gamestate, self._history)
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
            "luna_reroll": bool(self.harness.get("reroll_boss")),
            "boss_rerolls": getattr(self, "_boss_rerolls", {}).get(ante, 0),
            "boss_reroll_request": getattr(self, "_boss_reroll_request", None),
        }
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
        try:
            gamestate = before
            if before.get("state") == "SMODS_BOOSTER_OPENED":
                gamestate = await self._balatro.call("pack", {"skip": True})
            if gamestate.get("state") == "SHOP":
                gamestate = await self._balatro.call("next_round")
        except BalatroError as e:
            logger.warning(f"Harness could not leave the shop: {e}")
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

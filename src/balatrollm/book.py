"""Luna's write-only log book (pass 5, G2).

After every game that started (won, lost and every abnormal ending), one extra
LLM call OUTSIDE the game writes (i) a short write-up of the game and (ii) at
most 3 rule edits ("when <situation>, <action>, because <reason>"). Luna never
reads the book in a game: nothing here touches the game prompts, and the flag
(config ``book: {strategy: arm}``) lives outside the strategy folders, so the
strategy hash is the same with the book on or off.

The game history the call sees is built by code from the results ledger
(decisions.jsonl), the finished blinds and the end state: seed-free, cards
named, never hand positions. Every outgoing string is redacted (Redactor).

Store layout (``<runs_dir>/runs/book/<arm>/``, one store per arm)::

    HEAD                   hash of the current version
    versions/<hash>.json   immutable versions {"rules", "next_id", "games"}
    merge_log.jsonl        one line per merged game (labels only, never seeds)
    writeups.jsonl         one line per merged game: write-up, edits, merge result
    lock                   flock for HEAD / merges

Ported from the pass-4 book branch (ef4698e): the store, Redactor,
text_problems, the edit checks and the label-order merge. Not ported: rule
tags / selection, the in-game notebook, summaries in versions.
"""

import fcntl
import hashlib
import json
import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import seeds
from .analysis import _area_cards, card_name, current_blind

MAX_RULES = 300
MAX_EDITS = 3
MAX_RULE_CHARS = 300
MAX_WRITEUP_CHARS = 800
# Game history sent to the write-up call: ~3k tokens (3.5 characters a token,
# the ratio measured on logged Luna prompts in pass 4)
DIGEST_MAX_CHARS = 10_500
WRITEUP_TIMEOUT_S = 300
EMPTY: dict[str, Any] = {"rules": [], "next_id": 1, "games": 0}
ARM_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# "when <situation>, <action>, because <reason>": the action is any verb ("buy", "prioritize", "sell")
TEXT = re.compile(r"^when .+?, .+, because .+", re.IGNORECASE | re.DOTALL)
FORM = "when <situation>, <action>, because <reason>"
# An 8-character token of Balatro's seed alphabet (uppercase, no 0 / O)
SEED_TOKEN = re.compile(rf"(?<![A-Za-z0-9_])[{seeds.ALPHABET}]{{{seeds.SEED_LENGTH}}}(?![A-Za-z0-9_])")
HAND_POSITIONS = [
    re.compile(r"\[\s*\d+\s*(,\s*\d+\s*)*\]"),  # [0, 1, 3]
    re.compile(r"\b(index|indices|indexes|position|positions|slot|idx)\s*#?\s*\d", re.IGNORECASE),
    re.compile(r"\bcards?\s+#?\d+\s*(,|and|-)\s*\d", re.IGNORECASE),  # cards 0, 2
    re.compile(r"\b(leftmost|rightmost|left-most|right-most|first|second|third|fourth|fifth|last)\s+(card|cards)\s+in\s+(your\s+)?hand\b", re.IGNORECASE),
]
ONE_SEED = [
    re.compile(r"\bseed\b|\bSEED-", re.IGNORECASE),
    re.compile(r"\b(shop|pack|reroll|boss)\w*\b[^.;]{0,40}\b(will|always)\s+(has|have|offer|offers|show|shows|contain|contains|sell|sells)\b", re.IGNORECASE),
    re.compile(r"\b(ante|round)\s*\d+\b[^.;]{0,30}\b(shop|pack)\b[^.;]{0,30}\b(has|had|offers|offered|shows|showed|contains|contained|sells|sold)\b", re.IGNORECASE),
]


################################################################################
# Store
################################################################################


def store_dir(runs_dir: Path, arm: str) -> Path:
    """``<runs_dir>/runs/book/<arm>``: one store per arm (no env override)."""
    if not ARM_NAME.match(arm):
        raise ValueError(f"invalid book arm name: {arm!r}")
    return Path(runs_dir) / "runs" / "book" / arm


def version_hash(version: dict[str, Any]) -> str:
    canon = json.dumps(
        {k: version.get(k) for k in ("rules", "next_id", "games")},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


EMPTY_HASH = version_hash(EMPTY)


@contextmanager
def _locked(store: Path) -> Iterator[None]:
    store.mkdir(parents=True, exist_ok=True)
    with (store / "lock").open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _write_version(store: Path, version: dict[str, Any]) -> str:
    h = version_hash(version)
    path = store / "versions" / f"{h}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(version, indent=1, ensure_ascii=False))
        tmp.replace(path)
    return h


def _set_head(store: Path, h: str) -> None:
    tmp = store / "HEAD.tmp"
    tmp.write_text(h + "\n")
    tmp.replace(store / "HEAD")


def _read_head_unlocked(store: Path) -> tuple[str, dict[str, Any]]:
    head = store / "HEAD"
    if not head.exists():
        version = json.loads(json.dumps(EMPTY))
        h = _write_version(store, version)
        _set_head(store, h)
        return h, version
    h = head.read_text().strip()
    return h, json.loads((store / "versions" / f"{h}.json").read_text())


def read_head(store: Path) -> tuple[str, dict[str, Any]]:
    """The current version (created empty on first use)."""
    with _locked(store):
        return _read_head_unlocked(store)


def read_version(store: Path, h: str) -> dict[str, Any]:
    return json.loads((store / "versions" / f"{h}.json").read_text())


def rule_line(rule: dict[str, Any]) -> str:
    return f"- [{rule['id']}] {rule['text']}"


################################################################################
# Checks: no seed, no hand positions, the rule form
################################################################################


def known_words(*texts: str) -> set[str]:
    """8-letter words (stored uppercase) that occur in the given texts (the
    strategy's templates, knowledge.py: DISCARDS, STRAIGHT ...): not seeds when
    written in capitals, even though they fit the seed alphabet. Real seeds are
    still caught by the own-seed and private-map checks."""
    words: set[str] = set()
    for t in texts:
        words.update(w.upper() for w in re.findall(r"(?<![A-Za-z0-9_])[A-Za-z]{8}(?![A-Za-z0-9_])", t))
    return words


def _private_seeds() -> set[str]:
    try:
        data = json.loads(seeds.map_path().read_text())
    except (OSError, ValueError):
        return set()
    return {str(v.get("seed")).upper() for v in (data.get("labels") or {}).values() if v.get("seed")}


def text_problems(
    text: str,
    own_seed: str | None = None,
    words: set[str] | frozenset[str] = frozenset(),
    one_seed: bool = True,
) -> list[str]:
    """Why a text may not go into the book (never echoes a seed).

    ``one_seed`` False (the per-game write-up): only the seed and hand-position
    checks; a write-up may say what this game's shop offered.
    """
    out = []
    up = text.upper()
    if own_seed and own_seed.upper() in up:
        out.append("contains a seed")
    elif any(s and s in up for s in _private_seeds()):
        out.append("contains a seed")
    elif any(tok.group(0) not in words for tok in SEED_TOKEN.finditer(text)):
        out.append("contains a seed-like token (8 characters of the seed alphabet)")
    if any(p.search(text) for p in HAND_POSITIONS):
        out.append("names hand positions (name the cards or the hand type instead)")
    if one_seed and any(p.search(text) for p in ONE_SEED):
        out.append("states a one-game fact (a seed, a specific game or what a shop/pack/boss will offer)")
    return out


REDACTED = "[seed]"


class Redactor:
    """Replaces seeds in everything the book writes or sends: the game's own
    seed, every seed in the private map (any case) and any 8-character
    seed-alphabet token that is not a known word."""

    def __init__(self, own_seed: str | None = None, words: set[str] | frozenset[str] = frozenset()) -> None:
        secrets_ = {s for s in _private_seeds() | {str(own_seed or "").upper()} if s}
        self._exact = re.compile("|".join(re.escape(s) for s in sorted(secrets_)), re.IGNORECASE) if secrets_ else None
        self._words = words

    def __call__(self, text: str) -> str:
        if self._exact is not None:
            text = self._exact.sub(REDACTED, text)
        return SEED_TOKEN.sub(lambda m: m.group(0) if m.group(0) in self._words else REDACTED, text)

    def obj(self, value: Any) -> Any:
        """A deep copy with every string (and dict key) redacted."""
        if isinstance(value, str):
            return self(value)
        if isinstance(value, dict):
            return {self(str(k)) if isinstance(k, str) else k: self.obj(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.obj(v) for v in value]
        return value


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def check_edit(
    edit: Any,
    version: dict[str, Any],
    own_seed: str | None = None,
    words: set[str] | frozenset[str] = frozenset(),
) -> tuple[dict[str, Any] | None, list[str]]:
    """A proposed edit, checked against the version the write-up read.

    Returns (normalised edit, []) when kept, (None, reasons) when not. A
    change / drop carries ``base_text`` (the rule text the call saw), so a
    merge skips it when an earlier game changed that rule first.
    """
    if not isinstance(edit, dict):
        return None, ["not an object"]
    op = str(edit.get("op") or "").lower()
    if op not in ("add", "change", "drop"):
        return None, ['op must be "add", "change" or "drop"']
    by_id = {r["id"]: r for r in version.get("rules") or []}
    out: dict[str, Any] = {"op": op}
    why: list[str] = []
    if op in ("change", "drop"):
        rid = str(edit.get("id") or "")
        if rid not in by_id:
            return None, ["no rule with that id in the book"]
        out["id"] = rid
        out["base_text"] = by_id[rid]["text"]
    if op in ("add", "change"):
        text = re.sub(r"\s+", " ", str(edit.get("text") or "")).strip()
        if not TEXT.match(text):
            why.append(f'text must read "{FORM}"')
        if len(text) > MAX_RULE_CHARS:
            why.append(f"text longer than {MAX_RULE_CHARS} characters")
        why += text_problems(text, own_seed, words)
        out["text"] = text
        others = [r for r in version.get("rules") or [] if r["id"] != out.get("id")]
        if any(_norm(r["text"]) == _norm(text) for r in others):
            why.append("the same rule is already in the book")
        if op == "add" and len(version.get("rules") or []) >= MAX_RULES:
            why.append(f"the book is full ({MAX_RULES} rules): drop one first")
    return (None, why) if why else (out, [])


def check_edits(
    raw: Any, version: dict[str, Any], own_seed: str | None, words: set[str] | frozenset[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(kept, rejected) for a game's proposed edits; at most MAX_EDITS kept."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    edits = raw if isinstance(raw, list) else []
    for n, e in enumerate(edits):
        if n >= MAX_EDITS:
            rejected.append({"edit": e, "why": [f"more than {MAX_EDITS} edits"]})
            continue
        try:
            ok, why = check_edit(e, version, own_seed, words)
        except Exception as exc:  # a malformed edit never stops the others
            ok, why = None, [f"malformed edit ({type(exc).__name__})"]
        if ok is None:
            rejected.append({"edit": e, "why": why})
        else:
            kept.append(ok)
    return kept, rejected


def check_writeup(
    text: Any, own_seed: str | None, words: set[str] | frozenset[str]
) -> tuple[str, list[str]]:
    """(write-up cut to MAX_WRITEUP_CHARS, problems): seed and hand-position
    checks only (a write-up may say what this game's shop offered)."""
    clean = " ".join(str(text or "").split())
    problems = []
    if len(clean) > MAX_WRITEUP_CHARS:
        clean = clean[: MAX_WRITEUP_CHARS - 3].rstrip() + "..."
        problems.append(f"cut to {MAX_WRITEUP_CHARS} characters")
    if not clean:
        return "", ["empty"]
    bad = text_problems(clean, own_seed, words, one_seed=False)
    return clean, problems + bad


def writeup_ok(problems: list[str]) -> bool:
    """A write-up is kept unless a check other than the length cut failed."""
    return not [p for p in problems if not p.startswith("cut to")]


################################################################################
# Merge (never a rewrite)
################################################################################


def apply_edits(
    version: dict[str, Any], edits: list[dict[str, Any]], game_no: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply checked edits one by one onto ``version`` (a copy is returned).

    A change / drop whose rule is gone or whose text differs from what the
    write-up saw (``base_text``; an earlier game merged first) is skipped.
    Duplicate adds and adds past MAX_RULES are skipped.
    """
    new = json.loads(json.dumps(version))
    rules: list[dict[str, Any]] = new.setdefault("rules", [])
    log: list[dict[str, Any]] = []
    for e in edits:
        op = e.get("op")
        if op == "add":
            if any(_norm(r["text"]) == _norm(e["text"]) for r in rules):
                log.append({"op": op, "result": "skipped: duplicate"})
                continue
            if len(rules) >= MAX_RULES:
                log.append({"op": op, "result": "skipped: book full"})
                continue
            rid = f"R{int(new.get('next_id') or 1)}"
            new["next_id"] = int(new.get("next_id") or 1) + 1
            rules.append({"id": rid, "text": e["text"], "added_game": game_no, "changed_game": game_no})
            log.append({"op": op, "id": rid, "result": "added"})
            continue
        idx = next((i for i, r in enumerate(rules) if r["id"] == e.get("id")), None)
        if idx is None:
            log.append({"op": op, "id": e.get("id"), "result": "skipped: rule gone"})
            continue
        if rules[idx]["text"] != e.get("base_text"):
            log.append({"op": op, "id": e.get("id"), "result": "skipped: changed by an earlier game"})
            continue
        if op == "drop":
            rules.pop(idx)
            log.append({"op": op, "id": e["id"], "result": "dropped"})
        else:
            if any(_norm(r["text"]) == _norm(e["text"]) for j, r in enumerate(rules) if j != idx):
                log.append({"op": op, "id": e["id"], "result": "skipped: duplicate"})
                continue
            rules[idx] = {**rules[idx], "text": e["text"], "changed_game": game_no}
            log.append({"op": op, "id": e["id"], "result": "changed"})
    return new, log


def merge_update(update: dict[str, Any]) -> dict[str, Any]:
    """Merge one game's book_update record into its store (under the lock).

    Every game counts (also one whose call failed: no edits, the row says
    why). Appends the merge record to merge_log.jsonl and the game's
    write-up row to writeups.jsonl, both in merge (= label) order.
    """
    store = Path(update["store"])
    with _locked(store):
        head, version = _read_head_unlocked(store)
        game_no = int(version.get("games") or 0) + 1
        new, log = apply_edits(version, update.get("kept") or [], game_no)
        new["games"] = game_no
        h = _write_version(store, new)
        _set_head(store, h)
        record = {"label": update.get("label"), "game": game_no, "read": update.get("read"),
                  "base": head, "new": h, "edits": log}
        with (store / "merge_log.jsonl").open("a") as f:
            f.write(json.dumps(record) + "\n")
        row = {
            "label": update.get("label"), "game": game_no,
            "finish_reason": update.get("finish_reason"), "final_ante": update.get("final_ante"),
            "writeup": update.get("writeup"), "writeup_problems": update.get("writeup_problems") or [],
            "code_summary": update.get("code_summary"),
            "proposed": update.get("proposed"), "kept": update.get("kept") or [],
            "rejected": update.get("rejected") or [], "merge": log,
            "read": update.get("read"), "base": head, "new": h, "error": update.get("error"),
        }
        with (store / "writeups.jsonl").open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return record


def merge_file(path: Path) -> dict[str, Any] | None:
    """Merge a run's book_update.json once (marks it merged)."""
    data = json.loads(Path(path).read_text())
    if data.get("merged"):
        return None
    record = merge_update(data)
    data["merged"] = record
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    tmp.replace(path)
    return record


class MergeQueue:
    """Merges finished games' book updates in task (label) order.

    ``done(i, path)`` marks task i finished (path None: no update) and merges
    every update of the finished prefix 0..k in order. Each update carries its
    own store, so with interleaved arms each arm's merges are in label order.
    """

    def __init__(self, n: int) -> None:
        self._done: dict[int, Path | None] = {}
        self._next = 0
        self._n = n

    def done(self, i: int, path: Path | None) -> list[dict[str, Any]]:
        self._done[i] = path
        out = []
        while self._next in self._done:
            p = self._done.pop(self._next)
            self._next += 1
            rec = _merge_quietly(p)
            if rec:
                out.append(rec)
        return out

    def flush(self) -> list[dict[str, Any]]:
        """Merge whatever finished, in order, past any task that never finished."""
        out = []
        for i in sorted(self._done):
            rec = _merge_quietly(self._done.pop(i))
            if rec:
                out.append(rec)
        return out


def _merge_quietly(p: Path | None) -> dict[str, Any] | None:
    """One game's merge; a failure loses only that game's edits (logged, the
    file stays unmerged for merge_file) and never stalls later games."""
    if p is None or not Path(p).exists():
        return None
    try:
        return merge_file(Path(p))
    except Exception:
        logging.getLogger(__name__).exception(f"Book merge failed for {p}")
        return None


################################################################################
# The write-up call: prompt, tool, game history
################################################################################

WRITE_BOOK_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "write_book",
        "strict": False,
        "description": "Write the game's write-up and at most 3 edits to your rule book.",
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning": {
                    "type": "string",
                    "description": "Write this FIRST, 1-3 short sentences: what this game taught you.",
                },
                "writeup": {
                    "type": "string",
                    "description": f"The game's write-up, at most {MAX_WRITEUP_CHARS} characters.",
                },
                "edits": {
                    "type": "array",
                    "maxItems": MAX_EDITS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["add", "change", "drop"]},
                            "id": {"type": "string", "description": "Rule id (R12) for change or drop"},
                            "text": {"type": "string", "description": f"{FORM} (add or change)"},
                        },
                        "required": ["op"],
                    },
                },
            },
            "required": ["reasoning", "writeup", "edits"],
        },
    },
}


def writeup_system(version: dict[str, Any]) -> str:
    """The write-up call's system prompt, with the arm's current rules."""
    rules = version.get("rules") or []
    lines = [
        "You are Luna, a Balatro player. The game below has just ended. Call write_book once with two things.",
        "",
        "# 1. WRITE-UP",
        f"A short write-up of this game, at most {MAX_WRITEUP_CHARS} characters: the final ante, what lost it "
        "(or how it was won), the key buys and sells. Name the cards, jokers, hand types and bosses. Never write "
        "hand positions or card indices, never a seed.",
        "",
        "# 2. RULE EDITS",
        f"At most {MAX_EDITS} small edits to your rule book, using what this game taught you. add: a new rule. "
        "change: rewrite one rule by its id. drop: remove one rule by its id (wrong or useless). Fewer edits are "
        "fine; no edit is fine when the game taught nothing new.",
        f'- Every rule reads "{FORM}", at most {MAX_RULE_CHARS} characters.',
        "- Write general rules that help in OTHER games with other cards: name jokers, hand types, bosses, money "
        "levels. Never hand positions or card indices, never a seed, never what a particular shop or pack contained.",
        "- Edits that break these rules are thrown away.",
        "",
        f"# YOUR RULE BOOK NOW ({len(rules)} of {MAX_RULES} rules)",
    ]
    lines += [rule_line(r) for r in rules] or ["(empty)"]
    return "\n".join(lines)


FINISH_TEXT = {
    "won": "won the run (beat the Ante 8 boss)",
    "lost": "lost (game over)",
    "consecutive_error_calls": "stopped by the harness: 3 replies in a row without a valid action",
    "consecutive_failed_calls": "stopped by the harness: too many refused or rejected actions in a row",
    "llm_abort": "stopped: the model API failed (timeouts or errors)",
    "connection_abort": "stopped: the game stopped responding",
    "unexpected_error": "stopped: a harness error",
}


def _labels(G: dict[str, Any], area: str) -> list[str]:
    return [str(c.get("label") or c.get("key") or "?") for c in _area_cards(G, area)]


def _named(G: dict[str, Any], area: str, idx: Any) -> list[str]:
    if not isinstance(idx, list):
        return []
    cards = _area_cards(G, area)
    out = []
    for i in idx:
        try:
            out.append(card_name(cards[int(i)]))
        except (IndexError, TypeError, ValueError):
            out.append("?")
    return out


def _label_at(G: dict[str, Any], area: str, i: Any) -> str:
    try:
        c = _area_cards(G, area)[int(i)]
    except (IndexError, TypeError, ValueError):
        return "?"
    return str(c.get("label") or c.get("key") or "?")


def _boss(G: dict[str, Any]) -> str | None:
    return ((G.get("blinds") or {}).get("boss") or {}).get("name")


def _money_delta(row: dict[str, Any]) -> int | None:
    try:
        return int(row.get("money_after")) - int(row.get("money_before"))
    except (TypeError, ValueError):
        return None


def _best_play(row: dict[str, Any]) -> dict[str, Any] | None:
    plays = [p for p in ((row.get("advice") or {}).get("plays") or []) if isinstance(p, dict)]
    scored = [p for p in plays if isinstance(p.get("score"), (int, float))]
    return max(scored, key=lambda p: p["score"]) if scored else None


def _hand_line(row: dict[str, Any]) -> str | None:
    chosen = row.get("chosen") or {}
    out = row.get("outcome") or {}
    tool = chosen.get("tool")
    G = row.get("G") or {}
    res = out.get("result")
    if res != "ok":
        kind = {"error": "no valid action", "vetoed": "refused by the harness", "failed": "rejected by the game"}
        return f"  - {tool or 'reply'}: {kind.get(str(res), str(res))}" if res and res != "unknown" else None
    names = ", ".join(chosen.get("card_names") or [])
    if tool == "play":
        return f"  - play {names}: {out.get('summary') or ''}".rstrip(": ")
    if tool == "discard":
        return f"  - discard {names}"
    if tool == "use":
        params = chosen.get("params") or {}
        item = _label_at(G, "consumables", params.get("consumable"))
        targets = ", ".join(_named(G, "hand", params.get("cards")))
        return f"  - used {item}" + (f" on {targets}" if targets else "")
    if tool == "sell":
        return f"  - sold {chosen.get('item') or '?'}"
    return None


def _shop_line(rows: list[dict[str, Any]]) -> str | None:
    """One line for a shop visit (and packs opened from it)."""
    parts: list[str] = []
    rerolls = misses = 0
    left: Any = None
    for row in rows:
        chosen = row.get("chosen") or {}
        out = row.get("outcome") or {}
        tool = chosen.get("tool")
        G = row.get("G") or {}
        if out.get("harness_sold"):
            parts.append(str(out["harness_sold"]).replace(" (WEAKEST) to make room; ", "").strip("; "))
        if out.get("result") in ("error", "vetoed", "failed"):
            misses += 1
        elif out.get("result") == "ok":
            d = _money_delta(row)
            if tool == "buy":
                parts.append(f"bought {chosen.get('item') or '?'}" + (f" (${-d})" if d is not None and d < 0 else ""))
            elif tool == "sell":
                parts.append(f"sold {chosen.get('item') or '?'}" + (f" (+${d})" if d else ""))
            elif tool == "pack":
                params = chosen.get("params") or {}
                if params.get("skip"):
                    parts.append("skipped a pack")
                else:
                    targets = ", ".join(_named(G, "hand", params.get("targets") or params.get("cards")))
                    parts.append(f"took {chosen.get('item') or '?'} from a pack" + (f" on {targets}" if targets else ""))
            elif tool == "use":
                params = chosen.get("params") or {}
                item = _label_at(G, "consumables", params.get("consumable"))
                targets = ", ".join(_named(G, "hand", params.get("cards")))
                parts.append(f"used {item}" + (f" on {targets}" if targets else ""))
            elif tool == "reroll":
                rerolls += 1
            elif tool == "next_round":
                left = row.get("money_after")
        for forced in out.get("harness_forced") or []:
            if forced == "next_round":
                parts.append("the harness left the shop for you")
                left = row.get("money_after")
    if rerolls:
        parts.append(f"rerolled {rerolls}x")
    if misses:
        parts.append(f"{misses} refused or rejected action(s)")
    if left is not None:
        parts.append(f"left with ${left}")
    return ("  shop: " + "; ".join(parts)) if parts else None


def game_digest(
    rows: list[dict[str, Any]],
    rounds: list[dict[str, Any]],
    history: list[dict[str, Any]],
    end_state: dict[str, Any] | None,
    finish_reason: str | None,
    max_chars: int = DIGEST_MAX_CHARS,
) -> tuple[str, str, int | None]:
    """(user message, one-line code summary, final ante) for the write-up call.

    Built by code from the ledger rows (decisions.jsonl), the finished blinds
    and the end state: cards named, never positions, no seed, no label, and no
    harness suggestion (listed plays are facts; suggested actions are not).
    When too long, the oldest antes lose their hand-by-hand detail first.
    """
    end = {k: v for k, v in (end_state or {}).items() if k != "seed"}
    last_G = (rows[-1].get("G") or {}) if rows else {}
    final_G = end or last_G
    final_ante = final_G.get("ante_num") or (rows[-1].get("ante") if rows else None)
    final_ante = int(final_ante) if final_ante is not None else None
    done = {(r.get("ante"), r.get("round")): r for r in rounds}

    # Ante -> rounds -> rows, in play order
    antes: dict[int, dict[int, dict[str, list[dict[str, Any]]]]] = {}
    for row in rows:
        try:
            a, rn = int(row.get("ante") or 0), int(row.get("round") or 0)
        except (TypeError, ValueError):
            continue
        part = "hand" if row.get("state") == "SELECTING_HAND" else "shop"
        antes.setdefault(a, {}).setdefault(rn, {"hand": [], "shop": []})[part].append(row)
    for r in rounds:
        antes.setdefault(int(r.get("ante") or 0), {}).setdefault(int(r.get("round") or 0), {"hand": [], "shop": []})
    rerolls: dict[int, list[str]] = {}
    for h in history:
        if h.get("state") == "BLIND_SELECT" and h.get("method") == "reroll_boss":
            rerolls.setdefault(int(h.get("ante") or 0), []).append(str(h.get("result") or "boss rerolled"))

    blocks: list[tuple[list[str], list[str]]] = []  # (full lines, short lines) per ante
    for a in sorted(antes):
        boss = next((_boss(r.get("G") or {}) for rn in sorted(antes[a], reverse=True)
                     for r in antes[a][rn]["hand"] + antes[a][rn]["shop"] if _boss(r.get("G") or {})), None)
        head = f"## Ante {a}" + (f" (boss: {boss})" if boss else "")
        full, short = [head], [head]
        for note in rerolls.get(a, []):
            full.append(f"- {note}")
            short.append(f"- {note}")
        for rn in sorted(antes[a]):
            part = antes[a][rn]
            rec = done.get((a, rn))
            G = (part["hand"][-1].get("G") or {}) if part["hand"] else {}
            cur = current_blind(G) or {} if G else {}
            name = (rec or {}).get("blind") or cur.get("name") or "blind"
            target = int((rec or {}).get("target") or cur.get("score") or 0)
            if rec:
                line = (f"- {name} (target {target:,}): beaten, scored {int(rec.get('scored') or 0):,}, "
                        f"{rec.get('hands_left')} hands and {rec.get('discards_left')} discards left")
            elif part["hand"]:
                line = f"- {name} (target {target:,}): not beaten"
            else:
                line = None
            if line:
                full.append(line)
                short.append(line)
            for row in part["hand"]:
                if (hl := _hand_line(row)) is not None:
                    full.append(hl)
            if part["shop"] and (sl := _shop_line(part["shop"])):
                full.append(sl)
                short.append(sl)
        blocks.append((full, short))

    # The end
    finish = FINISH_TEXT.get(str(finish_reason), str(finish_reason or "ended"))
    jokers = _labels(final_G, "jokers")
    consumables = _labels(final_G, "consumables")
    tail = ["# THE END", f"- Result: {finish}; final ante {final_ante}",
            f"- Jokers at the end: {', '.join(jokers) or 'none'}",
            f"- Consumables at the end: {', '.join(consumables) or 'none'}",
            f"- Money at the end: ${final_G.get('money', '?')}"]
    last_hand = next((r for r in reversed(rows) if r.get("state") == "SELECTING_HAND"), None)
    if finish_reason != "won" and last_hand is not None:
        G = last_hand.get("G") or {}
        cur = current_blind(G) or {}
        rnd = G.get("round") or {}
        target, chips = int(cur.get("score") or 0), int(rnd.get("chips") or 0)
        what = (f"- What lost it: {cur.get('name') or 'the blind'} (Ante {last_hand.get('ante')}): at the last "
                f"decision {chips:,} of {target:,} scored, NEED {max(target - chips, 0):,}, "
                f"{rnd.get('hands_left')} hands and {rnd.get('discards_left')} discards left")
        best = _best_play(last_hand)
        if best:
            what += (f"; best listed play: {best.get('hand')} with {', '.join(best.get('card_names') or [])} "
                     f"for {int(best['score']):,}")
        tail.append(what)
    code_summary = f"{finish}; final ante {final_ante}; jokers: {', '.join(jokers) or 'none'}"

    head = ["# THIS GAME (oldest first)"]
    footer = ["", "Now call write_book."]

    def text(bs: list[list[str]]) -> str:
        return "\n".join(head + [ln for b in bs for ln in b] + [""] + tail + footer)

    chosen = [full for full, _ in blocks]
    for i, (_, short) in enumerate(blocks):  # oldest detail goes first
        if len(text(chosen)) <= max_chars:
            break
        chosen[i] = short
    for i in range(len(chosen)):
        if len(text(chosen)) <= max_chars:
            break
        chosen[i] = [chosen[i][0] + " (detail dropped)"]
    out = text(chosen)
    if len(out) > max_chars:
        out = out[: max_chars - 30] + "\n(cut)\n\nNow call write_book."
    return out, code_summary, final_ante

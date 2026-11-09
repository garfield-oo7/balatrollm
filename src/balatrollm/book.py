"""Luna's learning log book (pass 4, item L; arms W and L1).

Two parts, both only for strategies whose manifest sets ``"book": true``:

* In-game notebook: the optional ``note`` field on every tool (stripped before
  the BalatroBot call like ``reasoning``) collects her ante plans and one line
  after each blind; the whole notebook of the current game is shown in MEMORY.
* Cross-game book: rules "when X, do Y, because Z" in a store OUTSIDE the
  strategy folder. A game reads the version that is HEAD at its start (frozen
  for the whole game; its hash goes to task.json). At game end one extra Luna
  call proposes at most 3 small edits (add / change / drop one rule); the code
  checks them (no seed, no hand positions, no one-seed facts, the "when, do,
  because" form, size caps) and merges the kept ones onto the then-current
  HEAD (never a rewrite). With parallel games the executor merges finished
  games in task (label) order.

Store layout (``store/``)::

    HEAD                   hash of the current version
    versions/<hash>.json   immutable versions {"rules", "summaries", "next_id", "games"}
    stats.json             per-rule counters (audit only; not part of a version)
    merge_log.jsonl        one line per merged game (labels only, never seeds)
    lock                   flock for HEAD / merges (reruns in another process)

The version hash covers only what Luna is shown (rules, summaries), so the audit
counters never change the version a game reads.
"""

import fcntl
import hashlib
import json
import logging
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import knowledge, seeds

MAX_RULES = 300
MAX_EDITS = 3
MAX_RULE_CHARS = 300
MAX_TOP = 10
SUMMARIES_SHOWN = 8
SUMMARIES_KEPT = 50
MAX_SUMMARY_CHARS = 240
MAX_NOTE_CHARS = 280
MAX_NOTES = 80
# Prompt cap for the shown block (~40k tokens). Tokens are estimated from
# characters (no tokenizer installed); CHARS_PER_TOKEN is the ratio measured
# on logged Luna prompts (see the W5 report).
TOKEN_CAP = 40_000
CHARS_PER_TOKEN = 3.5
PHASES = ("shop", "hand", "pack")
FOCUS = ("shop", "shop_and_hand")
DEFAULT_FOCUS = "shop_and_hand"
EMPTY: dict[str, Any] = {"rules": [], "summaries": [], "next_id": 1, "games": 0}

TEXT = re.compile(r"^when .+, do .+, because .+", re.IGNORECASE | re.DOTALL)
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


def store_dir(runs_dir: Path, strategy: str, harness: dict[str, Any]) -> Path:
    """BALATROLLM_BOOK_STORE, else manifest ``book_store`` (relative to the run
    root), else ``<run root>/runs/book/<strategy>`` (outside the strategy folder)."""
    env = os.environ.get("BALATROLLM_BOOK_STORE")
    if env:
        return Path(env)
    conf = harness.get("book_store")
    if conf:
        p = Path(str(conf))
        return p if p.is_absolute() else Path(runs_dir) / p
    return Path(runs_dir) / "runs" / "book" / strategy


def version_hash(version: dict[str, Any]) -> str:
    canon = json.dumps(
        {k: version.get(k) for k in ("rules", "summaries", "next_id", "games")},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


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


################################################################################
# Showing the book
################################################################################


def phase_of(state: str) -> str:
    return {"SELECTING_HAND": "hand", "SHOP": "shop", "SMODS_BOOSTER_OPENED": "pack"}.get(state, "")


def rule_matches(rule: dict[str, Any], phase: str, ante: int, boss: str | None) -> bool:
    """Shop rules also show in packs (packs are opened from the shop)."""
    phases = rule.get("phase") or []
    if phases and phase not in phases and not (phase == "pack" and "shop" in phases):
        return False
    rng = rule.get("ante")
    if rng and not int(rng[0]) <= ante <= int(rng[1]):
        return False
    bosses = rule.get("boss") or []
    if bosses and boss not in bosses:
        return False
    return True


def _tags(rule: dict[str, Any]) -> str:
    out = []
    if rule.get("phase"):
        out.append("/".join(rule["phase"]))
    if rule.get("ante"):
        lo, hi = rule["ante"]
        out.append(f"ante {lo}" if lo == hi else f"ante {lo}-{hi}")
    if rule.get("boss"):
        out.append(", ".join(rule["boss"]))
    return f" ({'; '.join(out)})" if out else ""


def rule_line(rule: dict[str, Any], tags: bool = False) -> str:
    return f"- [{rule['id']}] {rule['text']}{_tags(rule) if tags else ''}"


def est_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def select(version: dict[str, Any], phase: str, ante: int, boss: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(top rules, matching other rules) for a situation, within TOKEN_CAP.

    Constant within one ante and phase (it depends on phase, ante and the ante's
    boss only), so the prompt cache holds it across the calls of an ante.
    """
    rules = version.get("rules") or []
    top = [r for r in rules if r.get("top")][:MAX_TOP]
    rest = [r for r in rules if not r.get("top") and rule_matches(r, phase, ante, boss)]
    budget = TOKEN_CAP * CHARS_PER_TOKEN - sum(len(rule_line(r)) + 1 for r in top)
    budget -= sum(len(s.get("text", "")) + 3 for s in (version.get("summaries") or [])[-SUMMARIES_SHOWN:])
    kept: list[dict[str, Any]] = []
    # Newest rules first when the cap bites (rules are kept in id order)
    for r in reversed(rest):
        size = len(rule_line(r)) + 1
        if size > budget:
            break
        budget -= size
        kept.append(r)
    kept.reverse()
    return top, kept


################################################################################
# Checks before an edit is kept
################################################################################


def known_words(*texts: str) -> set[str]:
    """8-letter words (any case, stored uppercase) that occur in the given texts
    (the strategy's templates, knowledge.py: DISCARDS, STRAIGHT, INTEREST ...):
    not seeds when written in capitals, even though they fit the seed alphabet.
    Real seeds are still caught by the own-seed and private-map checks."""
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


def text_problems(text: str, own_seed: str | None = None, words: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """Why a rule or summary text may not go into the book (never echoes a seed)."""
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
    if any(p.search(text) for p in ONE_SEED):
        out.append("states a one-game fact (a seed, a specific game or what a shop/pack/boss will offer)")
    return out


REDACTED = "[seed]"


class Redactor:
    """Replaces seeds in everything the book writes or sends (G4-1): the game's
    own seed, every seed in the private map (any case) and any 8-character
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


def canonical_boss(name: Any) -> str | None:
    """knowledge.py's name for a boss (G4-2: only real boss names are kept)."""
    return {knowledge._norm_name(k): k for k in knowledge.BOSSES}.get(knowledge._norm_name(name))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _tags_from(edit: dict[str, Any], focus: str) -> tuple[dict[str, Any], list[str]]:
    out: dict[str, Any] = {}
    why: list[str] = []
    phase = edit.get("phase") or []
    if isinstance(phase, str):
        phase = [phase]
    if not isinstance(phase, list):
        return out, ["phase must be a list"]
    phase = sorted({str(p).lower() for p in phase})
    if any(p not in PHASES for p in phase):
        why.append(f"phase must be from {PHASES}")
    if focus == "shop" and (not phase or not set(phase) <= {"shop", "pack"}):
        why.append("this book is for shop rules only: phase must be shop and/or pack")
    out["phase"] = phase
    ante = edit.get("ante")
    if ante:
        try:
            lo, hi = int(ante[0]), int(ante[1])
            if not 1 <= lo <= hi <= 8:
                raise ValueError
            out["ante"] = [lo, hi]
        except Exception:  # G4-3: any malformed value rejects only this edit
            why.append("ante must be [lo, hi] within 1-8")
    boss = edit.get("boss") or []
    if isinstance(boss, str):
        boss = [boss]
    if not isinstance(boss, list):
        return out, why + ["boss must be a list of boss names"]
    if boss:
        names = [canonical_boss(b) for b in boss]
        if None in names or len(names) > 5:
            why.append("boss must list at most 5 real boss names (e.g. The Wall)")
        else:
            out["boss"] = sorted(set(n for n in names if n))
    out["top"] = bool(edit.get("top"))
    return out, why


def check_edit(
    edit: Any,
    version: dict[str, Any],
    focus: str = DEFAULT_FOCUS,
    own_seed: str | None = None,
    words: set[str] | frozenset[str] = frozenset(),
) -> tuple[dict[str, Any] | None, list[str]]:
    """A proposed edit, checked against the version the game read.

    Returns (normalised edit, []) when kept, (None, reasons) when not.
    The normalised edit carries ``base_text`` (the rule text the game saw) for
    change / drop, so a merge can skip it when a parallel game changed it first.
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
            why.append('text must read "when ..., do ..., because ..."')
        if len(text) > MAX_RULE_CHARS:
            why.append(f"text longer than {MAX_RULE_CHARS} characters")
        why += text_problems(text, own_seed, words)
        if op == "change":
            # a change that leaves a tag out keeps the rule's tag
            old = by_id[out["id"]]
            edit = {**{k: old.get(k) for k in ("phase", "ante", "boss", "top")},
                    **{k: v for k, v in edit.items() if v is not None}}
        tags, tag_why = _tags_from(edit, focus)
        why += tag_why
        out.update(text=text, **tags)
        others = [r for r in version.get("rules") or [] if r["id"] != out.get("id")]
        if any(_norm(r["text"]) == _norm(text) for r in others):
            why.append("the same rule is already in the book")
        if op == "add" and len(version.get("rules") or []) >= MAX_RULES:
            why.append(f"the book is full ({MAX_RULES} rules): drop one first")
    return (None, why) if why else (out, [])


def check_edits(
    raw: Any, version: dict[str, Any], focus: str, own_seed: str | None, words: set[str]
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
            ok, why = check_edit(e, version, focus, own_seed, words)
        except Exception as exc:  # G4-3: a malformed edit never stops the others
            ok, why = None, [f"malformed edit ({type(exc).__name__})"]
        if ok is None:
            rejected.append({"edit": e, "why": why})
        else:
            kept.append(ok)
    return kept, rejected


################################################################################
# Merge (never a rewrite)
################################################################################


def apply_edits(
    version: dict[str, Any], edits: list[dict[str, Any]], game_no: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply checked edits one by one onto ``version`` (a copy is returned).

    Each edit touches one rule. A change / drop whose rule is gone or whose text
    differs from what the game saw (``base_text``; a parallel game merged
    first) is skipped. Duplicate adds and adds past MAX_RULES are skipped.
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
            top = bool(e.get("top")) and sum(1 for r in rules if r.get("top")) < MAX_TOP
            rule = {"id": rid, "text": e["text"], "phase": e.get("phase") or [], "top": top,
                    "added_game": game_no, "changed_game": game_no}
            for k in ("ante", "boss"):
                if e.get(k):
                    rule[k] = e[k]
            rules.append(rule)
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
            rule = dict(rules[idx])
            rule["text"] = e["text"]
            rule["phase"] = e.get("phase") or []
            for k in ("ante", "boss"):
                if e.get(k):
                    rule[k] = e[k]
                else:
                    rule.pop(k, None)
            others_top = sum(1 for j, r in enumerate(rules) if j != idx and r.get("top"))
            rule["top"] = bool(e.get("top")) and others_top < MAX_TOP
            rule["changed_game"] = game_no
            rules[idx] = rule
            log.append({"op": op, "id": e["id"], "result": "changed"})
    return new, log


def merge_update(update: dict[str, Any]) -> dict[str, Any]:
    """Merge one game's book_update record into its store (under the lock).

    Returns the merge record (also appended to merge_log.jsonl).
    """
    store = Path(update["store"])
    with _locked(store):
        head, version = _read_head_unlocked(store)
        game_no = int(version.get("games") or 0) + 1
        new, log = apply_edits(version, update.get("kept") or [], game_no)
        summary = update.get("summary")
        if summary:
            new.setdefault("summaries", []).append({"game": game_no, "text": f"Game {game_no}: {summary}"})
            new["summaries"] = new["summaries"][-SUMMARIES_KEPT:]
        new["games"] = game_no
        h = _write_version(store, new)
        _set_head(store, h)
        _add_stats(store, update.get("rule_stats") or {})
        record = {"label": update.get("label"), "game": game_no, "read": update.get("book_hash"),
                  "base": head, "new": h, "edits": log}
        with (store / "merge_log.jsonl").open("a") as f:
            f.write(json.dumps(record) + "\n")
        return record


def _add_stats(store: Path, rule_stats: dict[str, dict[str, int]]) -> None:
    path = store / "stats.json"
    stats = json.loads(path.read_text()) if path.exists() else {}
    for rid, s in rule_stats.items():
        cur = stats.setdefault(rid, {})
        for k, v in s.items():
            cur[k] = int(cur.get(k, 0)) + int(v)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(stats, indent=1, sort_keys=True))
    tmp.replace(path)


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

    ``done(i, path)`` marks task i finished (path None: no update, e.g. a crashed
    game) and merges every update of the finished prefix 0..k in order, so the
    book after k merges depends only on the first k games' edits.
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
    file stays unmerged for book.merge_file) and never stalls later games."""
    if p is None or not Path(p).exists():
        return None
    try:
        return merge_file(Path(p))
    except Exception:
        logging.getLogger(__name__).exception(f"Book merge failed for {p}")
        return None


################################################################################
# Per-game rule counters
################################################################################


def rule_stats(shown: dict[int, dict[str, int]], blinds_won: int, won_game: bool) -> dict[str, dict[str, int]]:
    """``shown``: blind index -> {rule id: calls shown}. Blind k (0-based) was won
    when k < blinds_won (or the game was won)."""
    out: dict[str, dict[str, int]] = {}
    for k, ids in shown.items():
        won = won_game or k < blinds_won
        for rid, calls in ids.items():
            s = out.setdefault(rid, {"calls_shown": 0, "blinds_shown": 0, "blinds_won": 0, "blinds_lost": 0})
            s["calls_shown"] += calls
            s["blinds_shown"] += 1
            s["blinds_won" if won else "blinds_lost"] += 1
    return out

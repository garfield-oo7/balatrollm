"""Lessons from past games (E4): load, match to the current situation, render.

A lesson (``lessons.json`` in the strategy folder) is::

    {"id": "L1", "status": "candidate" | "trial" | "kept" | "retired",
     "text": "when <situation>, do <action>, because <reason>",
     "situation": {"ante": [lo, hi], "situation": ["SHORT"], "phase": ["SHOP"],
                   "boss": ["The Wall"], "current_blind": ["The Mark"],
                   "jokers": ["j_card_sharp"]},
     "evidence": ["SEED-A", "SEED-K"],
     "check": {"action": "reroll", "expect": "avoid"}}

``boss`` is the ANTE's boss (it also matches the Small/Big rounds of that
ante); ``current_blind`` is the blind being played now (pass 3). A check may
name a card set: {"action": "discard", "expect": "avoid", "cards": "face_down"}
= the decision's discard must not include a face-down card.

Only ``trial`` and ``kept`` lessons are shown to Luna, at most ``LIMIT`` per
prompt, and only when the strategy's harness flag ``lessons`` is true (it is
false in pass 2). Every field of ``situation`` is optional; a lesson matches
when every given field matches. Evidence holds run labels only, never seeds.
"""

import json
import re
from pathlib import Path
from typing import Any

LIMIT = 2
SHOWN = ("trial", "kept")
STATUSES = ("candidate", "trial", "kept", "retired")
TEXT = re.compile(r"^when .+, do .+, because .+", re.IGNORECASE | re.DOTALL)
# SEED-A .. SEED-ZZZ (passes 1-3) and SEED-N01-style fresh-seed labels (pass 4, B0e); never an 8-char seed
LABEL = re.compile(r"^SEED-(?:[A-Z]{1,3}|[A-Z][0-9]{2})$")
CARD_SETS = ("face_down",)

_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def load(path: Path) -> list[dict[str, Any]]:
    """Lessons from ``path`` (empty when the file is missing); cached by mtime."""
    if not path.exists():
        return []
    mtime = path.stat().st_mtime
    hit = _CACHE.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    data = json.loads(path.read_text())
    lessons = data.get("lessons", []) if isinstance(data, dict) else data
    _CACHE[str(path)] = (mtime, lessons)
    return lessons


def problems(lesson: dict[str, Any]) -> list[str]:
    """Why a lesson is not well formed (empty: fine)."""
    out = []
    if not lesson.get("id"):
        out.append("no id")
    if lesson.get("status") not in STATUSES:
        out.append(f"status must be one of {STATUSES}")
    if not TEXT.match(str(lesson.get("text", ""))):
        out.append('text must read "when ..., do ..., because ..."')
    ev = lesson.get("evidence") or []
    if len(set(ev)) < 2:
        out.append("needs 2+ games of evidence")
    if any(not LABEL.match(str(e)) for e in ev):
        out.append("evidence must be run labels (SEED-A ...), never seeds")
    check = lesson.get("check") or {}
    if check and check.get("expect") not in ("do", "avoid"):
        out.append('check.expect must be "do" or "avoid"')
    if check and check.get("cards") not in (None, *CARD_SETS):
        out.append(f"check.cards must be one of {CARD_SETS}")
    return out


def _phase(G: dict[str, Any]) -> str:
    state = G.get("state")
    return {"SELECTING_HAND": "HAND", "SHOP": "SHOP", "SMODS_BOOSTER_OPENED": "PACK"}.get(str(state), str(state))


def matches(lesson: dict[str, Any], G: dict[str, Any], status: str | None) -> bool:
    sit = lesson.get("situation") or {}
    ante = int(G.get("ante_num") or 1)
    if "ante" in sit:
        lo, hi = sit["ante"]
        if not lo <= ante <= hi:
            return False
    if "situation" in sit and status not in sit["situation"]:
        return False
    if "phase" in sit and _phase(G) not in sit["phase"]:
        return False
    if "boss" in sit:
        boss = ((G.get("blinds") or {}).get("boss") or {}).get("name")
        if boss not in sit["boss"]:
            return False
    if "current_blind" in sit:
        cur = next((b.get("name") for b in (G.get("blinds") or {}).values() if (b or {}).get("status") == "CURRENT"), None)
        if cur not in sit["current_blind"]:
            return False
    if "jokers" in sit:
        owned = {j.get("key") for j in (G.get("jokers") or {}).get("cards") or []}
        if not owned & set(sit["jokers"]):
            return False
    return True


def match(G: dict[str, Any], status: str | None, lessons: list[dict[str, Any]], limit: int = LIMIT) -> list[dict[str, Any]]:
    """At most ``limit`` trial/kept lessons whose situation matches now."""
    out = [
        lesson
        for lesson in lessons
        if lesson.get("status") in SHOWN and not problems(lesson) and matches(lesson, G, status)
    ]
    return out[:limit]


def line(lesson: dict[str, Any]) -> str:
    """The prompt line (the digest reads the id back for the followed check)."""
    return f"[{lesson['id']}] {lesson['text']} ({', '.join(lesson['evidence'])})"

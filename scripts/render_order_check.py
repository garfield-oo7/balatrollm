"""Pass 7 B6 render check (iii): prompts and ledger rows in BOT ORDER.

For every decision state of the given gamestates.jsonl files, in file order (one
process = one game sequence, like the bot): render STRATEGY + GAMESTATE + MEMORY
with the strategy's manifest flags (+ overrides), THEN build the ledger pre-row
(``ledger.pre_row``) the way bot.py does after the render, then go on to the
next state. Prints per state: file index, line, state, prompt hash, hash of the
ledger row WITHOUT the logged line, hash of ``advice.dig_line`` (or "-").
Run it twice in SEPARATE processes (e.g. ``--flag dig_line_log=0`` and ``=1``)
and diff the columns: identical prompt hashes and stripped-row hashes = the
silent line changes nothing but its own field. Comparing the dig_line column of
G (dig_line_log on) and H shows the two arms log the same line.

Never prints a state's contents (logged states carry the real seed).

Usage: python3 -I scripts/render_order_check.py [--flag NAME=0|1 ...] <strategy> <gamestates.jsonl> [...]
"""

import hashlib
import json
import sys
from typing import Any

from balatrollm import ledger
from balatrollm.strategy import StrategyManager, StrategyManifest

DECISION_STATES = ("SELECTING_HAND", "SHOP", "SMODS_BOOSTER_OPENED")


def _h(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def main(argv: list[str]) -> None:
    overrides: dict[str, bool] = {}
    rest: list[str] = []
    it = iter(argv)
    for a in it:
        if a == "--flag":
            key, _, val = next(it).partition("=")
            if val not in ("0", "1"):
                raise SystemExit(f"--flag {key}={val}: use NAME=0 or NAME=1")
            overrides[key] = val == "1"
        else:
            rest.append(a)
    name, files = rest[0], rest[1:]
    sm = StrategyManager(name)
    flags = {**StrategyManifest.from_file(name).harness, **overrides}
    for fi, path in enumerate(files):
        with open(path) as f:
            for li, line in enumerate(f):
                G = json.loads(line)
                if G.get("state") not in DECISION_STATES:
                    continue
                G.pop("seed", None)
                ctx = {"rounds": [], "history": [], "flags": flags}
                text = "\x00".join(
                    [
                        sm.render_strategy(G, **ctx),
                        sm.render_gamestate(G, **ctx),
                        sm.render_memory(history=[], G=G, rounds=[], flags=flags),
                    ]
                )
                row = ledger.pre_row(G, [], [], flags)
                adv = row.get("advice") if isinstance(row.get("advice"), dict) else None
                dl = "-"
                if adv is not None and "dig_line" in adv:
                    adv = dict(adv)
                    dl = _h(adv.pop("dig_line"))
                    adv.pop("dig_line_logged_only", None)
                    row = {**row, "advice": adv}
                rendered = dict(row.get("rendered") or {})
                rendered.pop("dig_line_text", None)  # H-only field
                rendered.pop("dig_line", None)  # True in H, False in G
                row = {**row, "rendered": rendered}
                row.pop("G", None)
                print(fi, li, G["state"], hashlib.sha256(text.encode()).hexdigest()[:16], _h(row), dl)


if __name__ == "__main__":
    main(sys.argv[1:])

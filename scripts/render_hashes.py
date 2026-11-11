"""Byte-identity check for a strategy's rendered prompts (pass 4 A1, worker W1).

Renders STRATEGY + GAMESTATE + MEMORY for every decision state (SELECTING_HAND,
SHOP, SMODS_BOOSTER_OPENED) in the given gamestates.jsonl files with the
strategy's own manifest flags, and prints one sha256 per state. Run it at two
revisions and diff the output: identical lines = identical prompts.

Usage: python3 -I scripts/render_hashes.py [--flag NAME=0|1 ...] <strategy> <gamestates.jsonl> [...] > hashes.txt

``--flag NAME=1`` / ``NAME=0`` (pass 6) overrides one manifest harness flag,
e.g. ``--flag dig_line=0`` renders a ``harness.dig_line: true`` strategy with
the line off. The bot itself only reads the manifest (no run-config override).
``--dig-line`` is kept as an alias of ``--flag dig_line=1``.

Prints file index, line number, state and hash only (never the state's contents:
logged states carry the real seed).
"""

import hashlib
import json
import sys

from balatrollm.strategy import StrategyManager, StrategyManifest

DECISION_STATES = ("SELECTING_HAND", "SHOP", "SMODS_BOOSTER_OPENED")


def main(argv: list[str]) -> None:
    overrides: dict[str, bool] = {}
    rest: list[str] = []
    it = iter(argv)
    for a in it:
        if a == "--dig-line":
            overrides["dig_line"] = True
        elif a == "--flag":
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
                print(fi, li, G["state"], hashlib.sha256(text.encode()).hexdigest())


if __name__ == "__main__":
    main(sys.argv[1:])

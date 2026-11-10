"""Byte-identity check for a strategy's rendered prompts (pass 4 A1, worker W1).

Renders STRATEGY + GAMESTATE + MEMORY for every decision state (SELECTING_HAND,
SHOP, SMODS_BOOSTER_OPENED) in the given gamestates.jsonl files with the
strategy's own manifest flags, and prints one sha256 per state. Run it at two
revisions and diff the output: identical lines = identical prompts.

Usage: python3 -I scripts/render_hashes.py [--dig-line] <strategy> <gamestates.jsonl> [...] > hashes.txt

``--dig-line`` (pass 5 G3) adds the config flag ``dig_line`` to the manifest
flags, as the bot does when the run config sets ``dig_line: true``.

Prints file index, line number, state and hash only (never the state's contents:
logged states carry the real seed).
"""

import hashlib
import json
import sys

from balatrollm.strategy import StrategyManager, StrategyManifest

DECISION_STATES = ("SELECTING_HAND", "SHOP", "SMODS_BOOSTER_OPENED")


def main(argv: list[str]) -> None:
    dig = "--dig-line" in argv
    argv = [a for a in argv if a != "--dig-line"]
    name, files = argv[0], argv[1:]
    sm = StrategyManager(name)
    flags = StrategyManifest.from_file(name).harness
    if dig:
        flags = {**flags, "dig_line": True}
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

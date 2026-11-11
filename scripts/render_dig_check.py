"""Pass 5 G3: the dig-or-play line is the ONLY change with ``dig_line`` on.

Renders STRATEGY + GAMESTATE + MEMORY for every decision state in the given
gamestates.jsonl files twice (the strategy's manifest flags with ``dig_line``
off, then the same flags with it on) and classifies each state: identical, exactly one
added ``- Dig or play:`` line, that line plus changed ``- Suggested
discard/action:`` lines (advice on: the line decides the suggestion), or
other. Prints counts only (logged states
carry the real seed; nothing from a state is printed except the line number
of an "other" state).

Usage: python3 -I scripts/render_dig_check.py <strategy> <gamestates.jsonl> [...]
"""

import difflib
import json
import sys
from collections import Counter

from balatrollm.strategy import StrategyManager, StrategyManifest

DECISION_STATES = ("SELECTING_HAND", "SHOP", "SMODS_BOOSTER_OPENED")


def render(sm: StrategyManager, G: dict, flags: dict) -> list[str]:
    ctx = {"rounds": [], "history": [], "flags": flags}
    text = "\x00".join(
        [
            sm.render_strategy(G, **ctx),
            sm.render_gamestate(G, **ctx),
            sm.render_memory(history=[], G=G, rounds=[], flags=flags),
        ]
    )
    return text.split("\n")


def main(argv: list[str]) -> None:
    name, files = argv[0], argv[1:]
    sm = StrategyManager(name)
    off = {**StrategyManifest.from_file(name).harness, "dig_line": False}
    on = {**off, "dig_line": True}
    counts: Counter = Counter()
    for fi, path in enumerate(files):
        with open(path) as f:
            for li, line in enumerate(f):
                G = json.loads(line)
                if G.get("state") not in DECISION_STATES:
                    continue
                G.pop("seed", None)
                a, b = render(sm, G, off), render(sm, G, on)
                if a == b:
                    counts[f"{G['state']} identical"] += 1
                    continue
                ops = [op for op in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes() if op[0] != "equal"]
                removed = [x for op in ops for x in a[op[1]:op[2]]]
                added = [x for op in ops for x in b[op[3]:op[4]]]
                digs = [x for x in added if x.startswith("- Dig or play: play now: ")]
                sugg = ("- Suggested discard: ", "- Suggested action: ")
                if len(digs) == 1 and not removed and len(added) == 1:
                    counts[f"{G['state']} one dig line added"] += 1
                elif (
                    len(digs) == 1
                    and all(x.startswith(sugg) for x in removed)
                    and all(x.startswith(sugg) for x in added if x not in digs)
                    and len(removed) == len(added) - 1
                ):
                    counts[f"{G['state']} dig line added + suggestion changed"] += 1
                else:
                    counts[f"{G['state']} OTHER"] += 1
                    print("other:", fi, li, file=sys.stderr)
    for k in sorted(counts):
        print(k, counts[k])


if __name__ == "__main__":
    main(sys.argv[1:])

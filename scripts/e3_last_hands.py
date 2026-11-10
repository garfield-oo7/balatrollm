"""Pass 4 E3 (information only, decides nothing): on logged last-hand states,
how often the E3 suggested action differs from the pre-E3 one, with timing.

Reads SELECTING_HAND lines of gamestates.jsonl (the state after each action;
the first decision of a blind has no logged pre-state). Never prints a seed
or a raw line: only labels, cards named, numbers.

Usage: python scripts/e3_last_hands.py RUNS_DIR [RUNS_DIR ...] [--examples N]
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from pathlib import Path

from balatrollm import analysis as A


def label(path: Path) -> str:
    m = re.search(r"SEED-([A-Za-z0-9]+)", path.parent.name)
    return f"{path.parts[-6] if len(path.parts) >= 6 else '?'}/{m.group(1) if m else '?'}"


def names(G: dict, idx: list[int] | None) -> str:
    hand = A._area_cards(G, "hand")
    return ", ".join(A.card_name(hand[i]) for i in (idx or []))


def describe(G: dict, a: dict) -> str:
    if a.get("tool") == "use":
        return f"use consumable ({a.get('why')})"
    return f"{a.get('tool')} {names(G, a.get('cards'))}"


def main() -> None:
    args = sys.argv[1:]
    n_ex = 12
    if "--examples" in args:
        k = args.index("--examples")
        n_ex = int(args[k + 1])
        del args[k:k + 2]
    files = sorted(f for d in args for f in Path(d).rglob("gamestates.jsonl"))
    real_choice = A._e3_choice
    rows, times = [], []
    for f in files:
        for line in f.open():
            try:
                G = json.loads(line)
            except json.JSONDecodeError:
                continue
            if G.get("state") != "SELECTING_HAND":
                continue
            h = int((G.get("round") or {}).get("hands_left") or 0)
            if h not in (1, 2):
                continue
            G.pop("seed", None)
            A._CACHE.clear()
            A._e3_choice = lambda *a, **k: None
            try:
                old = A.play_advice(G)["action"]
            finally:
                A._e3_choice = real_choice
            A._CACHE.clear()
            t0 = time.perf_counter()
            adv = A.play_advice(G)
            dt = time.perf_counter() - t0
            new = adv["action"]
            e3 = adv.get("win_chance")
            if e3 is not None:
                times.append(dt)
            rows.append({"label": label(f), "h": h, "G": G, "old": old, "new": new, "e3": e3,
                         "progress": adv["progress"]})
    fired = [r for r in rows if r["e3"] is not None]
    changed = [r for r in fired if (r["old"].get("tool"), r["old"].get("cards")) != (r["new"].get("tool"), r["new"].get("cards"))]
    print(f"files {len(files)}; SELECTING_HAND states with hands_left 1-2: {len(rows)} "
          f"(h=1 {sum(r['h'] == 1 for r in rows)}, h=2 {sum(r['h'] == 2 for r in rows)})")
    print(f"E3 applies: {len(fired)} (h=1 {sum(r['h'] == 1 for r in fired)}, h=2 {sum(r['h'] == 2 for r in fired)})")
    print(f"suggested action changed: {len(changed)} of {len(fired)} "
          f"(h=1 {sum(r['h'] == 1 for r in changed)}, h=2 {sum(r['h'] == 2 for r in changed)})")
    kinds: dict[str, int] = {}
    for r in changed:
        k = f"{r['old'].get('tool')} -> {r['new'].get('tool')}"
        kinds[k] = kinds.get(k, 0) + 1
    print("changes by kind:", kinds)
    gain = []
    for r in fired:
        e3 = r["e3"]
        opt = {tuple(o["discard"]): o["chance"] for o in e3["options"]}
        p_play = e3["play"]["chance"] if e3["play"] else 0.0

        def chance(a: dict) -> float | None:
            if a.get("tool") == "discard":
                return opt.get(tuple(sorted(a.get("cards") or [])))
            if a.get("tool") == "play":
                for x in (e3.get("old_play"), e3["play"]):
                    if x and x["cards"] == sorted(a.get("cards") or []):
                        return x["chance"]
                return p_play
            return None

        o, n = chance(r["old"]), chance(r["new"])
        if o is not None and n is not None:
            gain.append((o, n))
    if gain:
        print(f"sampled win chance (same sampler), mean over {len(gain)} states: old {statistics.mean(g[0] for g in gain):.3f} "
              f"-> new {statistics.mean(g[1] for g in gain):.3f}")
    if times:
        ts = sorted(times)
        print(f"time per uncached play_advice call where E3 applies: median {statistics.median(ts) * 1000:.0f} ms, "
              f"p90 {ts[int(0.9 * (len(ts) - 1))] * 1000:.0f} ms, max {ts[-1] * 1000:.0f} ms (n={len(ts)})")
    print()
    for r in changed[:n_ex]:
        G, p = r["G"], r["progress"]
        hand = ", ".join(A.card_name(c) for c in A._area_cards(G, "hand"))
        print(f"- {r['label']} ante {G.get('ante_num')} {p.get('name')}: need {p['remaining']} with {r['h']} hand(s), "
              f"{p.get('discards_left')} discard(s); hand: {hand}")
        print(f"    old: {describe(G, r['old'])} ({r['old'].get('why')})")
        print(f"    new: {describe(G, r['new'])} ({r['new'].get('why')})")


if __name__ == "__main__":
    main()

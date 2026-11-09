"""Join a run's results ledger (decisions.jsonl, pass 4 B0c) with the result of
the blind each decision leads into, from gamestates.jsonl.

Next blind: in SELECTING_HAND the blind being played (round_num); in a shop or a
pack the next blind (round_num + 1). Result: "won" if a ROUND_EVAL state with that
round_num exists, "lost" if the game ended (GAME_OVER) on it, else "unknown"
(game ended earlier / aborted / still running). A won game (Ante 9) marks the
blinds after the last as "game_won".

Usage: python3 -I scripts/ledger_join.py <run_dir> [--out decisions_joined.jsonl]
Writes labels and results only; never prints a seed.
"""

import argparse
import json
from pathlib import Path


def results(run_dir: Path) -> tuple[set[int], int | None, bool]:
    won, lost, game_won = set(), None, False
    gs = run_dir / "gamestates.jsonl"
    if gs.exists():
        for line in gs.open():
            g = json.loads(line)
            if g.get("state") == "ROUND_EVAL":
                won.add(int(g.get("round_num") or 0))
            elif g.get("state") == "GAME_OVER":
                lost = int(g.get("round_num") or 0)
            if g.get("won"):
                game_won = True
    if game_won:
        lost = None
    return won, lost, game_won


def next_round(row: dict) -> int:
    r = int(row.get("round") or 0)
    return r if row.get("state") == "SELECTING_HAND" else r + 1


def join(run_dir: Path) -> list[dict]:
    won, lost, game_won = results(run_dir)
    out = []
    path = run_dir / "decisions.jsonl"
    if not path.exists():
        return out
    last_won = max(won) if won else 0
    for line in path.open():
        row = json.loads(line)
        row.pop("G", None)  # keep the joined file small; the full row stays in decisions.jsonl
        n = next_round(row)
        if n in won:
            res = "won"
        elif lost is not None and n == lost:
            res = "lost"
        elif game_won and n > last_won:
            res = "game_won"
        else:
            res = "unknown"
        row["next_blind"] = {"round": n, "result": res}
        out.append(row)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--out", default="decisions_joined.jsonl")
    a = ap.parse_args()
    rows = join(a.run_dir)
    with (a.run_dir / a.out).open("w") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["next_blind"]["result"]] = counts.get(r["next_blind"]["result"], 0) + 1
    print(f"{len(rows)} rows -> {a.out}: {counts}")


if __name__ == "__main__":
    main()

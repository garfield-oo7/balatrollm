"""E2a calibration fit (pass 4): the next blind's win chance for STATUS.

Replays logged blinds through today's sampler and fits analysis.WIN_FIT, a
logistic model of "won the blind" on the sampler's raw win chance (share of
sampled round totals >= target, boss rules inside), boss or not, ante and
hands needed - hands (K5 percentile).

Inputs per blind: the BLIND_SELECT gamestate logged just before it (logged
after next_round, so it carries the full deck, jokers, levels and money before
the blind). The boss name / score is patched from the first state of the blind
when a boss reroll at blind select changed it. Fallback when there is no such
snapshot (round 1) or it is for another blind (a skipped blind): the blind's
first logged state, judged as at its start (status_eval_p3.py's method).
Result: ROUND_EVAL = won, GAME_OVER = lost; a run that stopped mid-blind is
skipped.

Usage (prints labels and numbers only, never a seed):
  python3 -I scripts/fit_win_chance.py --fit DIR_GLOB [DIR_GLOB ...] [--test DIR_GLOB ...] [--jobs N] [--tsv OUT]
Each DIR_GLOB matches run folders (.../<date>_RED_WHITE_SEED-<label>); the
fit uses --fit folders only, --test folders are reported with the fitted (and
the stored) constants but never fitted on.
"""

from __future__ import annotations

import copy
import glob
import json
import math
import os
import sys
from multiprocessing import Pool

from balatrollm import analysis as A

FEATURES = ("intercept", "raw", "boss", "ante", "spare")


def _label(d: str) -> str:
    return "SEED-" + d.rsplit("SEED-", 1)[1]


def _pass(d: str) -> str:
    for part in d.split(os.sep):
        if part.startswith("v1."):
            return part
    return "?"


def blinds_of(d: str) -> list[dict]:
    """One row per played blind of one game (numbers and labels only)."""
    result: dict[int, dict] = {}
    first: dict[int, dict] = {}
    snap: dict[int, dict] = {}
    last_bs = None
    for line in open(os.path.join(d, "gamestates.jsonl")):
        g = json.loads(line)
        g.pop("seed", None)
        rn, st = g.get("round_num"), g.get("state")
        if st == "BLIND_SELECT":
            last_bs = g
            continue
        if st in ("SELECTING_HAND", "ROUND_EVAL", "GAME_OVER") and rn is not None and rn not in first:
            first[rn] = g
            if last_bs is not None and last_bs.get("round_num") == rn - 1:
                snap[rn] = last_bs
        if st in ("ROUND_EVAL", "GAME_OVER") and rn not in result:
            result[rn] = {"won": st == "ROUND_EVAL", "hands_left": int((g.get("round") or {}).get("hands_left") or 0)}
    rows, done = [], []
    for rn in sorted(first):
        res = result.get(rn)
        if not res:
            continue
        played = first[rn]
        pb = played.get("blinds") or {}
        kind = None
        for k, b in pb.items():
            if (b or {}).get("status") == "CURRENT":
                kind = k
        if kind is None:  # one-hand win / loss: the blind just DEFEATED in this state
            order = [k for k in ("boss", "big", "small") if (pb.get(k) or {}).get("status") == "DEFEATED"]
            kind = order[0] if order else None
        g = None
        source = "fallback"
        s = snap.get(rn)
        if s is not None:
            sel = next((k for k, b in (s.get("blinds") or {}).items() if (b or {}).get("status") == "SELECT"), None)
            if sel == kind or (kind is None and sel):
                g = copy.deepcopy(s)
                kind = sel
                source = "snapshot"
                boss_now = pb.get("boss") or {}
                boss_then = (g.get("blinds") or {}).get("boss") or {}
                if boss_now.get("name") and boss_now.get("name") != boss_then.get("name"):
                    boss_then["name"] = boss_now["name"]
                    boss_then["score"] = boss_now.get("score", boss_then.get("score"))
                    source = "snapshot+boss"
        if g is None:
            if played.get("state") != "SELECTING_HAND" or kind is None:
                done.append({"hands_left": res["hands_left"]})
                continue
            g = copy.deepcopy(played)
            g["state"] = "BLIND_SELECT"
            for k, b in (g.get("blinds") or {}).items():
                if k == kind:
                    b["status"] = "SELECT"
        S = A.run_status(g, list(done), [])
        nb = A.next_blind(g) or {}
        rows.append({
            "pass": _pass(d), "label": _label(d), "round": rn, "ante": int(g.get("ante_num") or 1),
            "kind": kind, "blind": nb.get("name") or kind, "target": S["sit_target"], "hands": S["next_hands"],
            "need": S["hands_needed"], "raw": S["win_raw"], "won": res["won"], "source": source,
        })
        done.append({"hands_left": res["hands_left"]})
    return rows


def x_of(r: dict) -> list[float]:
    eps = 0.5 / A.SAMPLES
    raw = min(max(r["raw"], eps), 1 - eps)
    return [1.0, math.log(raw / (1 - raw)), float(r["kind"] == "boss"), float(r["ante"]), float(r["need"] - r["hands"])]


def predict(w: list[float], r: dict) -> float:
    z = sum(a * b for a, b in zip(w, x_of(r)))
    return 1 / (1 + math.exp(-max(min(z, 40), -40)))


def solve(m: list[list[float]], v: list[float]) -> list[float]:
    n = len(v)
    a = [row[:] + [v[i]] for i, row in enumerate(m)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(a[r][c]))
        a[c], a[p] = a[p], a[c]
        for r in range(n):
            if r != c and a[c][c]:
                f = a[r][c] / a[c][c]
                a[r] = [x - f * y for x, y in zip(a[r], a[c])]
    return [a[i][n] / a[i][i] for i in range(n)]


def fit(rows: list[dict], ridge: float = 1e-3) -> list[float]:
    """Logistic regression by Newton / IRLS (a small ridge keeps it finite)."""
    k = len(FEATURES)
    w = [0.0, 1.0, 0.0, 0.0, 0.0]
    for _ in range(50):
        g = [0.0] * k
        h = [[0.0] * k for _ in range(k)]
        for r in rows:
            x = x_of(r)
            p = predict(w, r)
            y = 1.0 if r["won"] else 0.0
            for i in range(k):
                g[i] += (y - p) * x[i]
                for j in range(k):
                    h[i][j] += p * (1 - p) * x[i] * x[j]
        for i in range(1, k):
            g[i] -= ridge * w[i]
            h[i][i] += ridge
        step = solve(h, g)
        w = [a + b for a, b in zip(w, step)]
        if max(abs(s) for s in step) < 1e-8:
            break
    return w


def report(name: str, rows: list[dict], w: list[float]) -> None:
    print(f"\n## {name}: {len(rows)} blinds, {sum(not r['won'] for r in rows)} lost")
    bands = {"COMFORTABLE": [], "THIN": [], "SHORT": []}
    ll = 0.0
    for r in rows:
        p = predict(w, r)
        bands[A.win_band(p)].append((p, r["won"]))
        ll += math.log(max(p if r["won"] else 1 - p, 1e-12))
    print(f"log loss {-ll / max(len(rows), 1):.4f}")
    print("band | blinds | predicted win | actual win | lost")
    for b, v in bands.items():
        if v:
            print(f"{b} | {len(v)} | {sum(p for p, _ in v) / len(v):.1%} | {sum(y for _, y in v) / len(v):.1%} | {sum(not y for _, y in v)}")
        else:
            print(f"{b} | 0 | - | - | 0")
    print("boss blinds:", end=" ")
    for b in bands:
        v = [(predict(w, r), r["won"]) for r in rows if r["kind"] == "boss" and A.win_band(predict(w, r)) == b]
        print(f"{b} {len(v)} (lost {sum(not y for _, y in v)})", end="; ")
    print()


def main(argv: list[str]) -> None:
    jobs, tsv = 8, None
    groups: dict[str, list[str]] = {"fit": [], "test": []}
    cur = "fit"
    it = iter(argv)
    for a in it:
        if a in ("--fit", "--test"):
            cur = a[2:]
        elif a == "--jobs":
            jobs = int(next(it))
        elif a == "--tsv":
            tsv = next(it)
        else:
            groups[cur] += sorted(d for d in glob.glob(a) if os.path.exists(os.path.join(d, "stats.json")))
    data: dict[str, list[dict]] = {}
    with Pool(jobs) as pool:
        for k, dirs in groups.items():
            data[k] = [r for rs in pool.map(blinds_of, dirs) for r in rs]
    for k, rows in data.items():
        src = {}
        for r in rows:
            src[r["source"]] = src.get(r["source"], 0) + 1
        games = len({(r["pass"], r["label"]) for r in rows})
        print(f"{k}: {games} games, {len(rows)} blinds, sources {src}")
    use = [r for r in data["fit"] if r["raw"] is not None and r["need"] is not None]
    w = fit(use)
    print("\nWIN_FIT = {" + ", ".join(f'"{n}": {v:.4f}' for n, v in zip(FEATURES, w)) + "}")
    stored = [A.WIN_FIT[n] for n in FEATURES]
    for k, rows in data.items():
        ok = [r for r in rows if r["raw"] is not None and r["need"] is not None]
        report(f"{k} (fitted constants)", ok, w)
        report(f"{k} (stored constants)", ok, stored)
    if tsv:
        with open(tsv, "w") as f:
            keys = ["set", *data["fit"][0].keys()] if data["fit"] else []
            f.write("\t".join(keys) + "\n")
            for k, rows in data.items():
                for r in rows:
                    f.write("\t".join(str(x) for x in [k, *r.values()]) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])

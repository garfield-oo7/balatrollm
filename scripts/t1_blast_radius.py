"""Pass 8 T1 / T2 blast-radius replay (evidence, not a test).

Replays recorded SELECTING_HAND states (decisions.jsonl rows; ``G`` is the pre-decision gamestate
without the seed) through one revision of balatrollm and writes, per state, the dig-or-play line as
the ledger logs it (advice.dig_line via ledger._line_row: wording, counts, text, ...) plus the other
advice fields (plays, suggested action / discard). Run ``dump`` once per revision (one process per
revision: the old one from a ``git archive`` copy), then ``compare``.

    python -I scripts/t1_blast_radius.py dump --src <src dir> --root <runs root> --labels N181-N280 --out old.jsonl
    python -I scripts/t1_blast_radius.py dump --src src --root <runs root> --labels N181-N280 --out new.jsonl
    python -I scripts/t1_blast_radius.py compare old.jsonl new.jsonl
    python -I scripts/t1_blast_radius.py transitions --src src --root <runs root> --labels N181-N280

``compare`` splits rows by "holds a T1 joker" (Green Joker / Spare Trousers / Ice Cream held and not
debuffed; a copy needs a held source) and buckets each pair as identical, T2-only (old wording
``counts`` -> new ``counts_below_pace``, line 2 = old line 2 + "; play now is below pace", every other
field equal) or other. Outside T1 states "other" must be 0. It also reports sampler time per T1 state.
``transitions`` checks the sampler's per-step T1 rule against the game: for an executed play / discard
followed by the next SELECTING_HAND row of the same round, the predicted value vs the exported one.

Prints labels and counts only (run folders are resolved inside the script; never printed).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys
import time
from collections import Counter
from multiprocessing import Pool
from typing import Any

T1_KEYS = ("j_green_joker", "j_trousers", "j_ice_cream")
T2_TAIL = "; play now is below pace"


def _labels(spec: str) -> list[str]:
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        p = a.rstrip("0123456789")
        lo = int(a[len(p):])
        hi = int(b[len(p):]) if b else lo
        out += [f"{p}{i}" for i in range(lo, hi + 1)]
    return out


def _game_dir(root: str, lab: str) -> str | None:
    d = sorted(x for x in glob.glob(f"{root}/2026*_SEED-{lab}") if os.path.exists(f"{x}/stats.json"))
    return d[0] if len(d) == 1 else None


def _rows(root: str, lab: str) -> list[dict[str, Any]]:
    d = _game_dir(root, lab)
    if d is None:
        return []
    with open(os.path.join(d, "decisions.jsonl")) as f:
        return [json.loads(line) for line in f]


def _t1_held(G: dict[str, Any]) -> list[str]:
    return sorted({j.get("key") for j in ((G.get("jokers") or {}).get("cards") or [])
                   if j.get("key") in T1_KEYS and not (j.get("state") or {}).get("debuff")})


def _rt(x: Any) -> Any:
    return json.loads(json.dumps(x, sort_keys=True, default=str))


_ARGS: dict[str, Any] = {}


def _init(src: str, root: str) -> None:
    sys.path.insert(0, os.path.abspath(src))
    _ARGS["root"] = root


def _dump_game(lab: str) -> list[dict[str, Any]]:
    from balatrollm import analysis, ledger

    timer = {"s": 0.0}
    real = analysis._dig_sample

    def timed(*a: Any, **k: Any) -> Any:
        t0 = time.perf_counter()
        try:
            return real(*a, **k)
        finally:
            timer["s"] += time.perf_counter() - t0

    analysis._dig_sample = timed
    out = []
    for k, r in enumerate(_rows(_ARGS["root"], lab)):
        G = r.get("G") or {}
        if r.get("state") != "SELECTING_HAND" or G.get("state") != "SELECTING_HAND":
            continue
        analysis._CACHE.clear()
        timer["s"] = 0.0
        rec: dict[str, Any] = {"label": lab, "k": k, "t1": _t1_held(G)}
        try:
            adv = analysis.play_advice(G, dig=True)
            line = ledger._line_row(adv.get("line"), G)
            rec["line"] = _rt(line)
            rec["other"] = _rt({"plays": ledger._plays(adv, G), "action": ledger._action(adv.get("action"), G),
                                "discard": adv.get("discard"), "progress": adv.get("progress")})
            rec["recorded_same"] = _rt(line) == _rt((r.get("advice") or {}).get("dig_line"))
        except Exception as e:  # noqa: BLE001 - recorded as a difference, never a traceback
            rec["error"] = type(e).__name__
        rec["sampler_s"] = timer["s"]
        out.append(rec)
    analysis._dig_sample = real
    return out


def dump(a: argparse.Namespace) -> None:
    labs = _labels(a.labels)
    with Pool(a.jobs, initializer=_init, initargs=(a.src, a.root)) as pool:
        res = pool.map(_dump_game, labs, chunksize=1)
    n = 0
    with open(a.out, "w") as f:
        for recs in res:
            for rec in recs:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
                n += 1
    games = sum(1 for r in res if r)
    print(f"dump: {games} games, {n} SELECTING_HAND states, recorded line reproduced: "
          f"{sum(1 for r in res for x in r if x.get('recorded_same'))}")


def _bucket(o: dict[str, Any], n: dict[str, Any]) -> str:
    if "error" in o or "error" in n:
        return "error"
    if o["line"] == n["line"] and o["other"] == n["other"]:
        return "identical"
    if o["other"] != n["other"]:
        return "other"
    lo, ln = o["line"] or {}, n["line"] or {}
    if lo.get("wording") == "counts" and ln.get("wording") == "counts_below_pace":
        to, tn = list(lo.get("text") or []), list(ln.get("text") or [])
        if len(to) == len(tn) >= 2 and tn[1] == to[1] + T2_TAIL and tn[:1] + tn[2:] == to[:1] + to[2:]:
            rest_o = {k: v for k, v in lo.items() if k not in ("wording", "text")}
            rest_n = {k: v for k, v in ln.items() if k not in ("wording", "text")}
            if rest_o == rest_n:
                return "T2-only"
    return "other"


def compare(a: argparse.Namespace) -> None:
    def load(p: str) -> dict[tuple[str, int], dict[str, Any]]:
        with open(p) as f:
            return {(r["label"], r["k"]): r for r in map(json.loads, f)}

    old, new = load(a.old), load(a.new)
    assert old.keys() == new.keys(), "the two dumps cover different states"
    table: Counter = Counter()
    other_labels: dict[str, set[str]] = {"T1": set(), "no T1": set()}
    t1_detail: Counter = Counter()
    times = []
    for key in sorted(old):
        o, n = old[key], new[key]
        grp = "T1" if n["t1"] else "no T1"
        b = _bucket(o, n)
        table[(grp, b)] += 1
        if b in ("other", "error"):
            other_labels[grp].add(key[0])
        if n["t1"]:
            times.append(n["sampler_s"])
            lo, ln = o.get("line") or {}, n.get("line") or {}
            t1_detail[("old comparison", bool(lo.get("comparison")), "new comparison", bool(ln.get("comparison")))] += 1
            if ln.get("comparison"):
                t1_detail[("new trigger", bool(ln.get("trigger")))] += 1
                t1_detail[("new wording", ln.get("wording"))] += 1
    print("rows by group / bucket:")
    for (g, b), c in sorted(table.items()):
        print(f"  {g:6s} {b:10s} {c}")
    for g, labs in other_labels.items():
        if labs:
            print(f"  labels with 'other' / 'error' rows ({g}): {', '.join(sorted(labs))}")
    print("T1 states (new revision):")
    for k, c in sorted(t1_detail.items(), key=str):
        print(f"  {k}: {c}")
    sampled = [t for t in times if t > 0]
    if sampled:
        print(f"T1 sampler seconds (states where the sampler ran, n={len(sampled)}): median {statistics.median(sampled):.3f}, "
              f"max {max(sampled):.3f}")
    rec_old = sum(1 for r in old.values() if r.get("recorded_same"))
    print(f"old revision reproduces the recorded advice.dig_line on {rec_old}/{len(old)} states")


def _transitions_game(lab: str) -> Counter:
    from balatrollm import analysis

    c: Counter = Counter()
    rows = _rows(_ARGS["root"], lab)
    sh = [r for r in rows if r.get("state") == "SELECTING_HAND" and (r.get("G") or {}).get("state") == "SELECTING_HAND"]
    for r, nxt in zip(sh, sh[1:]):
        G, G2 = r["G"], nxt["G"]
        if (r.get("outcome") or {}).get("result") != "ok" or G.get("round_num") != G2.get("round_num"):
            continue
        ch = r.get("chosen") or {}
        tool, cards = ch.get("tool"), (ch.get("params") or {}).get("cards") or []
        if tool not in ("play", "discard"):
            continue
        rd, rd2 = G.get("round") or {}, G2.get("round") or {}
        dh = int(rd.get("hands_left", 0)) - int(rd2.get("hands_left", 0))
        dd = int(rd.get("discards_left", 0)) - int(rd2.get("discards_left", 0))
        if (tool, dh, dd) not in (("play", 1, 0), ("discard", 0, 1)):
            continue  # something else happened between the two rows
        j1 = (G.get("jokers") or {}).get("cards") or []
        j2 = (G2.get("jokers") or {}).get("cards") or []
        hand = (G.get("hand") or {}).get("cards") or []
        played = [hand[i] for i in cards if 0 <= i < len(hand)]
        if tool == "play":
            est = analysis.estimate_play(G, played, [c2 for i, c2 in enumerate(hand) if i not in cards])
            blocked = bool(est["blocked"])
        for j in j1:
            key = j.get("key")
            if key not in T1_KEYS or (j.get("state") or {}).get("debuff"):
                continue
            v = analysis._dig_joker_value(j)
            same = [x for x in j2 if x.get("key") == key]
            if v is None or len(same) > 1 or len([x for x in j1 if x.get("key") == key]) > 1:
                c[(key, "skipped (unreadable or duplicate)")] += 1
                continue
            if tool == "discard":
                pred = max(0.0, v - 1) if key == "j_green_joker" else v
            elif key == "j_green_joker":
                pred = v + (0 if blocked else 1)
            elif key == "j_trousers":
                pred = v + (2 if not blocked and analysis._contains_two_pair([analysis._norm(x) for x in played]) else 0)
            else:
                pred = None if v - 5 <= 0 else v - 5
            got = analysis._dig_joker_value(same[0]) if same else None
            c[(key, tool, "match" if pred == got else "MISMATCH")] += 1
    return c


def transitions(a: argparse.Namespace) -> None:
    with Pool(a.jobs, initializer=_init, initargs=(a.src, a.root)) as pool:
        res = pool.map(_transitions_game, _labels(a.labels), chunksize=1)
    tot: Counter = Counter()
    for c in res:
        tot.update(c)
    for k, v in sorted(tot.items(), key=str):
        print(f"  {k}: {v}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    t = sub.add_parser("transitions")
    for p in (d, t):
        p.add_argument("--src", required=True)
        p.add_argument("--root", required=True)
        p.add_argument("--labels", default="N181-N280")
        p.add_argument("--jobs", type=int, default=12)
    d.add_argument("--out", required=True)
    c = sub.add_parser("compare")
    c.add_argument("old")
    c.add_argument("new")
    a = ap.parse_args()
    {"dump": dump, "compare": compare, "transitions": transitions}[a.cmd](a)


if __name__ == "__main__":
    main()

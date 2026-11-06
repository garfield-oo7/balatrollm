"""After-game digest: facts per shop visit and per game, from a run's logged files.

Usage: python3 -I scripts/digest.py <run_dir> [<run_dir> ...] [--log <games_log.jsonl>]

Writes <run_dir>/digest.json and, with --log, appends one summary line per game.
Runs are identified by their task seed (a private label such as SEED-A); the real
game seed is never written.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

HEAD = re.compile(r"- Ante (\d+)/8, round (\d+), money \$(-?\d+)")
JOKERS = re.compile(r"- Jokers (\d+)/(\d+), SLOTS_FREE (\d+), XMULT_OWNED (\d+)")
STATUS = re.compile(r"- STATUS: (ON TRACK|TOO WEAK|UNKNOWN)(?: \(next blind [\d,]+ needs about (\d+) hands)?")
MAIN = re.compile(r"- MAIN_HAND: ([^-\n]+?) -")
BLIND = re.compile(r"- Ante (\d+) (.+?): scored ([\d,]+) / ([\d,]+), (\d+) hands left")
OFFER = re.compile(r"^- (\d+): (.+?) \$(\d+)(.*)$", re.M)
VETO = re.compile(r"Your last action FAILED\*\*: (?:Refused by harness: )?(.+)")
LESSON = re.compile(r"^- Past games: (.+)$", re.M)
LEVEL = re.compile(r"- ([A-Za-z ]+?) \(MAIN_HAND\): Lv(\d+)")


def _text(req: dict[str, Any]) -> str:
    u = req["body"]["messages"][-1]["content"] if "messages" in req["body"] else req["body"]["input"][-1]["content"]
    return "".join(c.get("text", "") for c in u) if isinstance(u, list) else u


def _call(resp: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    stack: list[Any] = [resp]
    while stack:
        o = stack.pop(0)
        if isinstance(o, dict):
            f = o.get("function")
            if isinstance(f, dict) and isinstance(f.get("name"), str):
                return f["name"], _args(f.get("arguments"))
            if o.get("type") == "function_call" and isinstance(o.get("name"), str):
                return o["name"], _args(o.get("arguments"))
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return "", {}


def _args(a: Any) -> dict[str, Any]:
    try:
        d = json.loads(a) if isinstance(a, str) else dict(a or {})
    except (ValueError, TypeError):
        return {}
    d.pop("reasoning", None)
    return d


def _num(s: str) -> int:
    return int(s.replace(",", ""))


def _section(u: str, title: str) -> str:
    i = u.find(title)
    if i < 0:
        return ""
    j = u.find("\n# ", i + len(title))
    return u[i : j if j > 0 else len(u)]


def decisions(run: Path) -> list[dict[str, Any]]:
    reqs = [json.loads(line) for line in (run / "requests.jsonl").open()]
    resps = [json.loads(line) for line in (run / "responses.jsonl").open()]
    out = []
    for rq, rs in zip(reqs, resps):
        u = _text(rq)
        m = HEAD.search(u)
        if not m:
            continue
        name, args = _call(rs)
        j = JOKERS.search(u)
        st = STATUS.search(u)
        mh = MAIN.search(u)
        lv = LEVEL.search(u)
        phase = "PACK" if "# OPEN PACK" in u else "HAND" if "# ROUND" in u else "SHOP"
        offers = []
        if phase == "SHOP":
            for o in OFFER.finditer(_section(u, "# SHOP")):
                tags = re.findall(r"\[([A-Z+\- ]+)\]", o.group(4))
                score = re.search(r"SCORE ([+\-][\d,]+)", o.group(4))
                offers.append({"label": o.group(2).strip(), "price": int(o.group(3)), "tags": tags,
                               "score": score.group(1) if score else None})
        veto = VETO.search(u)
        out.append({
            "ante": int(m.group(1)), "round": int(m.group(2)), "money": int(m.group(3)),
            "phase": phase,
            "jokers": int(j.group(1)) if j else None, "slots_free": int(j.group(3)) if j else None,
            "xmult": int(j.group(4)) if j else None,
            "status": st.group(1) if st else None, "hands_needed": int(st.group(2)) if st and st.group(2) else None,
            "main_hand": mh.group(1).strip() if mh else None,
            "main_level": int(lv.group(2)) if lv else None,
            "blinds": [(int(b[0]), b[1], _num(b[2]), _num(b[3]), int(b[4])) for b in BLIND.findall(u)],
            "offers": offers,
            "lessons": LESSON.findall(u),
            "veto_of_previous": veto.group(1).strip()[:200] if veto else None,
            "action": name, "args": args,
        })
    return out


def shop_visits(ds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    visits: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for k, d in enumerate(ds):
        if d["phase"] == "HAND":
            if cur:
                visits.append(cur)
                cur = None
            continue
        if cur is None:
            last = d["blinds"][-1] if d["blinds"] else None
            cur = {
                "ante": d["ante"], "round": d["round"], "money_in": d["money"],
                "status_in": d["status"], "hands_needed_in": d["hands_needed"],
                "jokers_in": d["jokers"], "slots_free_in": d["slots_free"],
                "last_blind": {"ante": last[0], "blind": last[1], "hands_left": last[4],
                               "margin": round(last[2] / max(last[3], 1), 2)} if last else None,
                "offers": d["offers"], "actions": [], "vetoes": [], "lessons": d["lessons"],
                "rerolls": 0, "jokers_bought": 0, "decision_index": k,
            }
        cur["money_out"] = d["money"]
        if d["phase"] == "SHOP" and d["offers"] and not cur["offers"]:
            cur["offers"] = d["offers"]
        nxt = ds[k + 1] if k + 1 < len(ds) else None
        vetoed = bool(nxt and nxt["veto_of_previous"])
        if vetoed:
            cur["vetoes"].append({"action": d["action"], "args": d["args"], "reason": nxt["veto_of_previous"]})
        else:
            cur["actions"].append({"action": d["action"], "args": d["args"]})
            if d["action"] == "reroll":
                cur["rerolls"] += 1
        if nxt and nxt["phase"] != "HAND" and nxt["jokers"] is not None and d["jokers"] is not None:
            cur["jokers_bought"] += max(nxt["jokers"] - d["jokers"], 0)
    if cur:
        visits.append(cur)
    # the blind played right after each visit
    for v in visits:
        later = [d for d in ds[v["decision_index"]:] if d["phase"] == "HAND"]
        known = set(ds[v["decision_index"]]["blinds"])  # MEMORY may show only the last few
        new = [b for d in ds[v["decision_index"]:] for b in d["blinds"] if b not in known]
        if new:
            b = new[0]
            v["next_blind"] = {"ante": b[0], "blind": b[1], "hands_left": b[4], "margin": round(b[2] / max(b[3], 1), 2)}
        elif later:
            v["next_blind"] = {"ante": later[-1]["ante"], "blind": "lost", "hands_left": 0, "margin": None}
    return visits


def hands_played(run: Path, upto_ante: int) -> dict[str, int]:
    last = None
    for line in (run / "gamestates.jsonl").open():
        g = json.loads(line)
        if (g.get("ante_num") or 0) <= upto_ante and g.get("hands"):
            last = g
    if not last:
        return {}
    return {k: v["played"] for k, v in last["hands"].items() if v.get("played")}


def digest(run: Path) -> dict[str, Any]:
    task = json.loads((run / "task.json").read_text())
    stats = json.loads((run / "stats.json").read_text()) if (run / "stats.json").exists() else {}
    ds = decisions(run)
    visits = shop_visits(ds)
    mains = []
    for d in ds:
        if d["main_hand"] and (not mains or mains[-1][2] != d["main_hand"]):
            mains.append((d["ante"], d["round"], d["main_hand"]))
    last = ds[-1] if ds else {}
    by_ante: dict[int, list[int]] = {}
    for v in visits:
        by_ante.setdefault(v["ante"], []).append(v["money_out"])
    early = [d for d in ds if d["ante"] <= 2 and d["phase"] == "SHOP" and d["status"]]
    blinds = last.get("blinds", [])
    return {
        "label": task.get("seed"), "code": task.get("code"), "model": task.get("model"),
        "won": stats.get("run_won"), "final_ante": stats.get("final_ante"),
        "final_round": stats.get("final_round"), "finish_reason": stats.get("finish_reason"),
        "cost": stats.get("cost_total"),
        "main_hand_changes": mains, "final_main_level": last.get("main_level"),
        "final_xmult": last.get("xmult"),
        "hands_played_ante1_2": hands_played(run, 2),
        "shop_exit_money_by_ante": by_ante,
        "too_weak_share_ante1_2": round(sum(d["status"] == "TOO WEAK" for d in early) / len(early), 2) if early else None,
        "blinds": [{"ante": b[0], "blind": b[1], "hands_left": b[4], "margin": round(b[2] / max(b[3], 1), 2)} for b in blinds],
        "vetoes": sum(len(v["vetoes"]) for v in visits),
        "rerolls": sum(v["rerolls"] for v in visits),
        "shop_visits": visits,
    }


def main(argv: list[str]) -> None:
    log = None
    if "--log" in argv:
        i = argv.index("--log")
        log = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2 :]
    for a in argv:
        run = Path(a)
        dg = digest(run)
        (run / "digest.json").write_text(json.dumps(dg, indent=1))
        line = {k: v for k, v in dg.items() if k != "shop_visits"}
        line["run_dir"] = run.name
        if log:
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a") as f:
                f.write(json.dumps(line) + "\n")
        print(f"{dg['label']}: {'won' if dg['won'] else 'lost'} ante {dg['final_ante']} round {dg['final_round']} | "
              f"shops {len(dg['shop_visits'])} | exit $ by ante { {a: sorted(m) for a, m in dg['shop_exit_money_by_ante'].items()} } | "
              f"TOO WEAK A1-2 {dg['too_weak_share_ante1_2']} | main {dg['main_hand_changes'][-1][2] if dg['main_hand_changes'] else '-'} "
              f"Lv{dg['final_main_level']} | xmult {dg['final_xmult']}")


if __name__ == "__main__":
    main(sys.argv[1:])

"""Lesson writer (E4): evidence from game digests -> at most 3 candidate lessons.

Usage:
  python3 -I scripts/lessons.py <run_dir> [<run_dir> ...] --out <candidates.json>
      [--model MODEL] [--base-url URL] [--pack <evidence.json>] [--dry-run]

Reads each run's digest.json (scripts/digest.py writes it), builds an evidence
pack keyed by run label (SEED-A ...; never a seed, never a run directory name),
asks a stronger model for at most 3 lessons ("when ..., do ..., because ...",
each backed by 2+ games) and writes the valid ones with status "candidate".
The owner approves a lesson (status "trial") before Luna sees it. The API key
comes from BALATROLLM_API_KEY and is never printed. --dry-run writes the
evidence pack only (no model call).
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from balatrollm import lessons as L  # noqa: E402

MAX_LESSONS = 3
VISIT_KEYS = ("ante", "round", "status_in", "money_in", "money_out", "jokers_in", "slots_free_in",
              "rerolls", "jokers_bought", "buys", "next_blind", "last_blind")
GAME_KEYS = ("won", "final_ante", "final_round", "main_hand_changes", "main_commit", "final_main_level",
             "final_xmult", "most_played", "shop_exit_money_by_ante", "situations_at_shop_entry",
             "first_shop", "rerolls_by_ante", "rerolls_below_25_ante2_3", "repeated_dips", "blinds",
             "vetoes", "harness")


def build_pack(runs: list[Path]) -> list[dict[str, Any]]:
    """One entry per game: labels and facts only."""
    pack = []
    for run in runs:
        dg = json.loads((run / "digest.json").read_text())
        label = str(dg.get("label"))
        if not L.LABEL.match(label):
            raise SystemExit("refused: a run without a SEED-<letters> label (no seeds leave this machine)")
        game = {"label": label, **{k: dg.get(k) for k in GAME_KEYS}}
        game["shops"] = [{k: v.get(k) for k in VISIT_KEYS} for v in dg.get("shop_visits", [])]
        pack.append(game)
    return pack


PROMPT = """You review Balatro games played by a small model ("Luna") with a harness.
Below are facts from {n} games, one JSON object per game, keyed by run label.
Write at most {k} lessons that would have changed results. Each lesson:
- "text": "when <situation>, do <action>, because <evidence>", naming the run labels;
- backed by 2 or more games ("evidence": list of run labels);
- "situation": optional fields ante [lo, hi], situation (COMFORTABLE/THIN/SHORT),
  phase (SHOP/HAND/PACK), boss (names), jokers (keys like j_card_sharp);
- "check": {{"action": <tool name: buy/sell/reroll/next_round/play/discard/pack>,
  "expect": "do" or "avoid"}} so a later digest can tell followed from ignored.
Facts only; no lesson from a single game. Reply with JSON: {{"lessons": [...]}}.

GAMES:
{games}"""


def parse(reply: str) -> list[dict[str, Any]]:
    m = re.search(r"\{.*\}", reply, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    return list(data.get("lessons") or [])[:MAX_LESSONS]


def validate(raw: list[dict[str, Any]], labels: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    good, bad = [], []
    for n, lesson in enumerate(raw, 1):
        lesson = {**lesson, "id": lesson.get("id") or f"C{n}", "status": "candidate"}
        why = L.problems(lesson)
        unknown = [e for e in lesson.get("evidence") or [] if e not in labels]
        if unknown:
            why.append(f"evidence names games not in the pack: {unknown}")
        if why:
            bad.append(f"{lesson['id']}: {'; '.join(why)}")
        else:
            good.append(lesson)
    return good, bad


def ask(prompt: str, model: str, base_url: str | None) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("BALATROLLM_API_KEY"), base_url=base_url or os.environ.get("BALATROLLM_BASE_URL"))
    resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}])
    return resp.choices[0].message.content or ""


def main(argv: list[str]) -> None:
    opts: dict[str, str] = {}
    runs: list[Path] = []
    flags = {"--dry-run"}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in flags:
            opts[a] = "1"
        elif a.startswith("--"):
            opts[a] = argv[i + 1]
            i += 1
        else:
            runs.append(Path(a))
        i += 1
    pack = build_pack(runs)
    if "--pack" in opts:
        Path(opts["--pack"]).write_text(json.dumps(pack, indent=1))
    if "--dry-run" in opts:
        print(f"evidence pack: {len(pack)} games")
        return
    if "--model" not in opts or "--out" not in opts:
        raise SystemExit("--model and --out are required (or use --dry-run)")
    prompt = PROMPT.format(n=len(pack), k=MAX_LESSONS, games="\n".join(json.dumps(g) for g in pack))
    good, bad = validate(parse(ask(prompt, opts["--model"], opts.get("--base-url"))), {g["label"] for g in pack})
    Path(opts["--out"]).write_text(json.dumps({"lessons": good}, indent=1))
    print(f"candidates written: {len(good)}; rejected: {len(bad)}")
    for b in bad:
        print("  rejected", b)


if __name__ == "__main__":
    main(sys.argv[1:])

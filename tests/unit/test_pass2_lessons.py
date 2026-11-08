"""E4 lesson machinery (off in pass 2)."""

import importlib.util
import json
from pathlib import Path
from typing import Any

from balatrollm import analysis, lessons
from balatrollm.strategy import StrategyManager

from .test_analysis import joker, make_state


def _lesson(**kw: Any) -> dict[str, Any]:
    base = {
        "id": "L1",
        "status": "trial",
        "text": "when SHORT in a shop at Ante 2-3, do buy a scoring joker, because SEED-A and SEED-K lost",
        "situation": {"ante": [2, 3], "situation": ["SHORT"], "phase": ["SHOP"]},
        "evidence": ["SEED-A", "SEED-K"],
        "check": {"action": "buy", "expect": "do"},
    }
    return {**base, **kw}


def _script(name: str):
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_problems() -> None:
    assert lessons.problems(_lesson()) == []
    assert "needs 2+ games of evidence" in lessons.problems(_lesson(evidence=["SEED-A"]))
    assert any("never seeds" in p for p in lessons.problems(_lesson(evidence=["SEED-A", "ABCD1234"])))
    assert any("when ..." in p for p in lessons.problems(_lesson(text="buy jokers")))


def test_match_fields_status_and_limit() -> None:
    G = make_state("H_2", [joker("j_card_sharp", "Card Sharp")], state="SHOP")
    G["ante_num"] = 2
    assert lessons.match(G, "SHORT", [_lesson()])
    assert not lessons.match(G, "COMFORTABLE", [_lesson()])
    assert not lessons.match(G, "SHORT", [_lesson(status="candidate")])
    assert not lessons.match(G, "SHORT", [_lesson(situation={"jokers": ["j_baron"]})])
    assert lessons.match(G, "SHORT", [_lesson(situation={"jokers": ["j_card_sharp"]})])
    many = [_lesson(id=f"L{i}") for i in range(5)]
    assert len(lessons.match(G, "SHORT", many)) == lessons.LIMIT


def test_template_shows_lessons_only_with_the_flag(tmp_path: Path) -> None:
    path = tmp_path / "lessons.json"
    path.write_text(json.dumps({"lessons": [_lesson(situation={})]}))
    G = make_state("H_2", state="SHOP")
    sm = StrategyManager("mastery")
    assert "Past games" not in sm.render_gamestate(G, rounds=[], history=[], flags={})
    text = sm.render_gamestate(G, rounds=[], history=[], flags={"lessons": str(path)})
    assert "- Past games: [L1] when SHORT" in text
    assert analysis.past_lessons(G, "SHORT", str(path))[0].startswith("[L1]")


def test_mastery_ships_lessons_on_with_p2_c1_only() -> None:
    """Pass 3 (C8): lessons on, one trial lesson (P2-C1, The Mark)."""
    root = Path(analysis.__file__).parent / "strategies" / "mastery"
    assert json.loads((root / "manifest.json").read_text())["harness"]["lessons"] is True
    shipped = json.loads((root / "lessons.json").read_text())["lessons"]
    assert [x["id"] for x in shipped] == ["P2-C1"] and shipped[0]["status"] == "trial"
    assert lessons.problems(shipped[0]) == []


def test_digest_followed_and_ignored(tmp_path: Path) -> None:
    digest = _script("digest")
    path = tmp_path / "lessons.json"
    path.write_text(json.dumps({"lessons": [_lesson()]}))
    shown = ["[L1] when SHORT ..."]
    ds = [
        {"lessons": shown, "action": "buy"},
        {"lessons": shown, "action": "next_round"},
        {"lessons": [], "action": "buy"},
    ]
    assert digest.lesson_follow(ds, path) == {"L1": {"shown": 2, "followed": 1, "ignored": 1}}


def test_writer_guards_labels_and_validates(tmp_path: Path) -> None:
    writer = _script("lessons")
    run = tmp_path / "r1"
    run.mkdir()
    (run / "digest.json").write_text(json.dumps({"label": "SEED-A", "won": False, "run_dir": "x", "shop_visits": []}))
    pack = writer.build_pack([run])
    assert pack[0]["label"] == "SEED-A" and "run_dir" not in pack[0]
    (run / "digest.json").write_text(json.dumps({"label": "ABCD1234", "shop_visits": []}))
    try:
        writer.build_pack([run])
        raise AssertionError("a seed-like label must be refused")
    except SystemExit as e:
        assert "refused" in str(e)
    reply = "Here: " + json.dumps({"lessons": [_lesson(), _lesson(id="L2", evidence=["SEED-A", "SEED-Z"]), _lesson(id="L3", evidence=["SEED-A"])]})
    good, bad = writer.validate(writer.parse(reply), {"SEED-A", "SEED-K"})
    assert [g["id"] for g in good] == ["L1"] and good[0]["status"] == "candidate"
    assert len(bad) == 2

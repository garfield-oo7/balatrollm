"""Pass 5 G3: the dig-or-play fact line (config ``dig_line``)."""

import json
from pathlib import Path
from typing import Any

import pytest

from balatrollm import analysis
from balatrollm.strategy import StrategyManager, StrategyManifest

from .test_analysis import make_state

FIXTURE = Path(__file__).parent / "fixtures_pass4" / "noadvice_states.jsonl"


def _render(name: str, G: dict[str, Any], flags: dict[str, Any]) -> str:
    sm = StrategyManager(name)
    ctx = {"rounds": [], "history": [], "flags": flags}
    return "\x00".join(
        [
            sm.render_strategy(G, **ctx),
            sm.render_gamestate(G, **ctx),
            sm.render_memory(history=[], G=G, rounds=[], flags=flags),
        ]
    )


@pytest.mark.parametrize("name", ["mastery", "mastery-noadvice"])
def test_flag_off_renders_nothing_new(name: str) -> None:
    if not FIXTURE.exists():
        pytest.skip("pass-4 noadvice fixture missing")
    states = [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]
    flags = StrategyManifest.from_file(name).harness
    for G in states:
        text = _render(name, G, flags)
        assert text == _render(name, G, {**flags, "dig_line": False})
        assert "Dig or play" not in text


def test_dig_or_play_returns_two_chances() -> None:
    G = make_state("H_2 D_7 C_9 S_J H_4 D_K C_5 S_8", hands_left=3, discards_left=3, chips=0)
    A = analysis.play_advice(G, dig=True)
    line = A["dig_line"]
    assert line is not None
    assert 0.0 <= line["play"]["chance"] <= 1.0 and 0.0 <= line["dig"]["chance"] <= 1.0
    assert line["dig"]["discard"]
    # the strict rule decides the suggestion
    assert A["action"]["tool"] == ("discard" if line["dig_better"] else "play")
    assert analysis.play_advice(G)["dig_line"] is None

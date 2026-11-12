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


def test_a_play_that_beats_need_counts_as_a_win_inside_the_wins_margin() -> None:
    """Sol g3 #1: the chance is to beat the blind (NEED), not the 110% WINS margin."""
    from .test_analysis import joker

    G = make_state("H_K D_K C_9 S_7 H_4 D_3 C_2 S_5", [joker("j_jolly", "Jolly Joker")], hands_left=1, discards_left=2, chips=0)
    A = analysis.play_advice(G)
    pair = next(p for p in A["plays"] if p["hand"] == "Pair")
    floor = pair.get("floor") or pair["score"]
    G["blinds"]["small"]["score"] = int(floor / 1.05)  # beaten, but under 110%: not WINS
    A = analysis.play_advice(G, dig=True)
    assert not any(p.get("wins") for p in A["plays"])
    line = A["dig_line"]
    assert line is not None and set(pair["cards"]) <= set(line["play"]["cards"])  # the Pair (padded) is the play
    assert line["play"]["chance"] == 1.0


def test_a_used_up_deck_does_not_raise() -> None:
    """Sol g3 #3: an empty simulated hand is a lost trajectory, not an exception."""
    G = make_state("H_2 D_7 C_9 S_J H_4", hands_left=4, discards_left=3, chips=0)
    G["cards"]["cards"] = G["cards"]["cards"][:2]
    G["cards"]["count"] = 2
    G["blinds"]["small"]["score"] = 10**9
    analysis.play_advice(G, dig=True)  # must not raise


def test_no_line_with_a_joker_the_sampler_cannot_follow() -> None:
    """Sol g3 #2: e.g. Green Joker changes with each discard: no line rather than a biased one
    (pass 7 L5: Blue Joker is now scored by the sampler, so this uses Green Joker)."""
    from .test_analysis import joker

    G = make_state("H_2 D_7 C_9 S_J H_4 D_K C_5 S_8", [joker("j_green_joker", "Green Joker")], hands_left=3, discards_left=3, chips=0)
    assert analysis.play_advice(G, dig=True)["dig_line"] is None

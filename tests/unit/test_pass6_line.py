"""Pass 6 H2: the reworked dig-or-play fact line (arm F, strategy mastery-noadvice-line)."""

import json
from pathlib import Path

STRATEGIES = Path(__file__).parents[2] / "src" / "balatrollm" / "strategies"
COPIED = ("GAMESTATE.md.jinja", "MEMORY.md.jinja", "STRATEGY.md.jinja", "TOOLS.json")


def test_line_strategy_is_a_byte_copy_of_noadvice() -> None:
    e, f = STRATEGIES / "mastery-noadvice", STRATEGIES / "mastery-noadvice-line"
    assert sorted(p.name for p in f.iterdir()) == sorted(p.name for p in e.iterdir())
    for name in COPIED:
        assert (e / name).read_bytes() == (f / name).read_bytes(), name
    me = json.loads((e / "manifest.json").read_text())
    mf = json.loads((f / "manifest.json").read_text())
    assert mf["harness"].pop("dig_line") is True
    assert "dig_line" not in me["harness"] or me["harness"]["dig_line"] is False
    me["harness"].pop("dig_line", None)
    assert me["harness"] == mf["harness"]
    for k in ("name", "description"):
        me.pop(k), mf.pop(k)
    assert me == mf


# --- R1: the modeled play is the complete selection, scored on its own remainder (N65)


def test_padded_modeled_play_is_scored_on_its_own_remainder() -> None:
    """N65 shape: Raised Fist; the padded Two Pair Q♥ Q♣ 4♣ 2♠ 2♣ moves the lowest held rank,
    so its floor is NOT the listed Two Pair's (Q♥ Q♣ 2♠ 2♣) score."""
    from balatrollm import analysis

    from .test_analysis import joker, make_state

    G = make_state("H_Q C_Q S_9 H_8 D_8 C_4 S_2 C_2", [joker("j_raised_fist", "Raised Fist")],
                   hands_left=1, discards_left=1, chips=0)
    A = analysis.play_advice(G, dig=True)
    play = A["line"]["play"]
    listed = next(p for p in A["plays"] if p["hand"] == "Two Pair")
    hand = G["hand"]["cards"]
    assert set(listed["cards"]) < set(play["cards"])  # padded
    est = analysis.estimate_play(G, [hand[i] for i in play["cards"]],
                                 [c for i, c in enumerate(hand) if i not in play["cards"]])
    assert play["floor"] == int(est["score"]) != listed["score"]
    assert A["line"]["sampled"]["play"]["cards"] == play["cards"]  # R2: the sampler plays the same cards
    assert A["line"]["sampled"]["play"]["floor"] == play["floor"]
    assert "Queen of Hearts Queen of Clubs 4 of Clubs 2 of Spades 2 of Clubs" in A["line"]["text"][0]
    assert analysis.play_advice(G)["line"] is None  # flag off: nothing computed


# --- R4 / R5 boundaries (frozen rules)


def test_near_tie_boundary() -> None:
    from balatrollm.analysis import line_near_tie

    assert line_near_tie(0, 2, 2)  # SE 0: |2| == max(2, 0)
    assert not line_near_tie(0, 3, 3)
    assert line_near_tie(32, 42, 64)  # 2 SE = 11.0
    assert not line_near_tie(32, 48, 64)  # 2 SE = 10.6


def test_dig_trigger_boundary() -> None:
    from balatrollm.analysis import line_trigger

    # NEED 1,000, 2 hands: floor 499 is below pace, 500 is on pace
    assert line_trigger(True, False, 499, 2, 1000, 10, 40, 64)
    assert not line_trigger(True, False, 500, 2, 1000, 10, 40, 64)  # (b)
    assert not line_trigger(True, True, 499, 2, 1000, 10, 40, 64)  # (a) owner exception
    assert not line_trigger(False, False, 499, 2, 1000, 10, 40, 64)  # (a) no comparison
    assert not line_trigger(True, False, 499, 2, 1000, 0, 0, 64)  # (c) Y = 0
    assert not line_trigger(True, False, 499, 2, 1000, 0, 2, 64)  # (d) near-tie
    assert line_trigger(True, False, 999, 1, 1000, 0, 3, 3)  # last hand: floor < NEED

"""Pass 7 L1-L6: the reworked dig-or-play fact line (arm H, strategy mastery-noadvice-line)."""

from typing import Any

from balatrollm import analysis
from balatrollm.analysis import dig_line_facts, line_near_tie, line_near_tie_narrow, line_wording

from .test_analysis import joker, make_state


def _facts(jokers: list[dict[str, Any]], x: int, y: int, n: int = 64, floor: int = 300, need: int = 1000,
           hands_left: int = 2) -> dict[str, Any]:
    """The line for a synthetic comparison (play Pair 9♠ 9♥, dig discards 2♣ 4♦)."""
    G = make_state("S_9 H_9 C_2 D_4 S_K", jokers, hands_left=hands_left, discards_left=2, chips=0)
    play = {"cards": [0, 1], "hand": "Pair", "floor": floor, "unknown": [], "blocked": None}
    cmp = {"samples": n, "play": {"hits": x, "hands_used": 1.5}, "dig": {"hits": y, "discard": [2, 3],
                                                                          "keep": [0, 1, 4], "hands_used": 1.8}}
    return dig_line_facts(G, {"remaining": need, "hands_left": hands_left}, play, cmp, None)


# --- L1-L3 wording (L6: the frozen band stays the trigger's)


def test_narrow_band_boundaries() -> None:
    # n = 64: the cap n/16 = 4 (2 SE is about 8 here)
    assert line_near_tie_narrow(52, 56, 64) and line_near_tie_narrow(56, 52, 64)
    assert not line_near_tie_narrow(52, 57, 64) and line_near_tie(52, 57, 64)  # old band, not the new one
    # n = 32: the cap 2
    assert line_near_tie_narrow(16, 18, 32)
    assert not line_near_tie_narrow(16, 19, 32) and line_near_tie(16, 19, 32)
    assert line_near_tie_narrow(0, 2, 64)  # the floor of 2 stays


def test_wording_classes_and_text() -> None:
    # old band, not the new one: counts only, no near-tie word, no action word
    f = _facts([], 52, 57)
    assert f["wording"] == "counts" and f["near_tie"] and not f["near_tie_narrow"] and not f["trigger"]
    assert f["text"][1].startswith("Sampled: play now 52/64 sampled clears; dig (")
    assert len(f["text"]) == 2 and "near-tie" not in " ".join(f["text"])
    # L2: below pace (300 * 2 < 1,000) -> no clear edge
    f = _facts([], 52, 55)
    assert f["wording"] == "near_tie_no_edge"
    assert f["text"][2].startswith("near-tie 52/55 of 64: no clear edge; play now is below pace; mean hands used")
    assert "$1 per unused hand at cash-out" in f["text"][2]
    # L2: on pace (500 * 2 >= 1,000) -> play now; last hand: floor >= NEED
    assert _facts([], 52, 55, floor=500)["text"][2].startswith("near-tie 52/55 of 64 -> play now; ")
    assert line_wording(52, 55, 64, 999, 1, 1000, False) == "near_tie_no_edge"
    assert line_wording(52, 55, 64, 1000, 1, 1000, False) == "near_tie_play"
    # L2: both n/n -> play now even below pace
    assert _facts([], 64, 64)["text"][2].startswith("near-tie 64/64 of 64 -> play now; ")
    # L3: 0/0 -> no action word, no near-tie word
    f = _facts([], 0, 0)
    assert f["wording"] == "zero_zero" and f["near_tie_narrow"] and len(f["text"]) == 2  # in the band, word not shown
    assert f["text"][1].startswith("Sampled: no sampled clear either way (0/64): the modeled play, or digging (")
    assert "play now" not in " ".join(f["text"]) and "near-tie" not in " ".join(f["text"])


# --- L5 Blue Joker


def test_blue_joker_chips_fall_by_two_per_card_drawn(monkeypatch: Any) -> None:
    hand = "S_9 H_9 C_2 D_4 S_K H_7 D_3 C_8"
    G = make_state(hand, [joker("j_blue_joker", "Blue Joker")], hands_left=1, discards_left=1, chips=0)
    G["blinds"]["small"]["score"] = 10**9  # never cleared: every sampled step is scored
    deck_ids = {c["key"] for c in G["cards"]["cards"]}
    total = len(deck_ids)
    seen: list[tuple[int, int]] = []
    real = analysis._best_play

    def spy(Gx: dict[str, Any], held: list[dict[str, Any]], *a: Any, **k: Any) -> Any:
        seen.append((Gx["luna"]["dig_deck_left"], sum(c["key"] in deck_ids for c in held)))
        return real(Gx, held, *a, **k)

    monkeypatch.setattr(analysis, "_best_play", spy)
    monkeypatch.setattr(analysis, "_CACHE", type(analysis._CACHE)())  # a fresh sampler run
    line = analysis.play_advice(G, dig=True)["line"]
    assert line["comparison"] and seen
    # after the dig draw: deck left = deck - cards drawn (each drawn card is in the held hand)
    assert all(left == total - drawn for left, drawn in seen)
    # +2 chips per card left: the play-now floor uses the current deck count
    played = [G["hand"]["cards"][i] for i in line["play"]["cards"]]
    held = [c for i, c in enumerate(G["hand"]["cards"]) if i not in line["play"]["cards"]]

    def chips(left: int, jokers: list[dict[str, Any]]) -> int:
        Gx = {**G, "jokers": {**G["jokers"], "cards": jokers}, "luna": {"dig_deck_left": left}}
        return analysis.estimate_play(Gx, played, held)["chips"]

    blue = [joker("j_blue_joker", "Blue Joker")]
    assert chips(total, blue) - chips(total - 5, blue) == 10
    assert chips(-3, blue) == chips(0, blue)  # never below an empty deck
    copied = [joker("j_blueprint", "Blueprint"), *blue]  # Blueprint copies the joker to its right
    assert chips(total, copied) - chips(total - 5, copied) == 20
    est = analysis.estimate_play({**G, "luna": {"dig_deck_left": total}}, played, held)
    assert line["sampled"]["play"]["floor"] == int(est["score"])


# --- L4 Banner, and the worst-case line count


def test_banner_line_has_no_play_now_and_worst_case_fits() -> None:
    banner = joker("j_banner", "Banner")
    for jokers in ([banner], [joker("j_blueprint", "Blueprint"), banner]):
        for x, y in ((52, 55), (64, 64), (0, 2), (0, 0), (52, 57), (10, 40)):
            f = _facts(jokers, x, y, floor=500)
            text = " ".join(f["text"])
            assert "play now" not in text and "playing now" not in text, (x, y, f["text"])
            assert "Banner: +30 chips per discard left (already in both counts)" in f["text"][1]
            assert f["wording"].startswith("banner_")
    # worst case: Banner and Blue Joker held, near-tie, owner line, Banner sentence
    f = _facts([banner, joker("j_blue_joker", "Blue Joker")], 52, 55)
    assert len(f["text"]) == analysis.LINE_MAX_LINES
    assert f["text"][2].startswith("near-tie 52/55 of 64; mean hands used on clearing samples: the modeled play")
    assert f["text"][3].startswith("No dig flag with Banner") and "Blue Joker: +2 chips per card left" in f["text"][3]
    # and a live render with both held (the sampler runs; no assertion error)
    G = make_state("S_9 H_9 C_2 D_4 S_K H_7 D_3 C_8", [banner, joker("j_blue_joker", "Blue Joker")],
                   hands_left=3, discards_left=2, chips=0)
    line = analysis.play_advice(G, dig=True)["line"]
    assert line["comparison"] and 2 <= len(line["text"]) <= analysis.LINE_MAX_LINES
    assert not line["trigger"] and "Blue Joker" in line["text"][-1]

"""Pass 5 harness fixes (one small test per fix that changes a score or could block a legal move)."""

from typing import Any

from balatrollm import analysis

from .test_analysis import card, joker, make_state


def _n05(two_debuffed: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """A1 N05 at The Pillar: Pair 8♥ 8♣ with K♣, Q♦ (debuffed), J♠, 9♥, 7♦, Steel 2♠ (debuffed) held."""
    jokers = [
        joker("j_mad", "Mad Joker"),
        joker("j_raised_fist", "Raised Fist"),
        joker("j_riff_raff", "Riff-raff", edition="FOIL"),
        joker("j_sly", "Sly Joker"),
        joker("j_gros_michel", "Gros Michel"),
    ]
    G = make_state("C_K D_Q S_J H_9 H_8 C_8 D_7 S_2", jokers, boss="The Pillar", boss_current=True,
                   hands_left=1, discards_left=0)
    cards = G["hand"]["cards"]
    cards[1]["state"] = {"debuff": True}
    cards[7]["modifier"] = {"enhancement": "STEEL"}
    cards[7]["set"] = "ENHANCED"
    if two_debuffed:
        cards[7]["state"] = {"debuff": True}
    played = [cards[4], cards[5]]
    held = [c for i, c in enumerate(cards) if i not in (4, 5)]
    return G, played, held


def test_raised_fist_picks_a_debuffed_lowest_card_and_adds_nothing() -> None:
    G, played, held = _n05()
    # chips 10 + 8 + 8 + 50 (Foil) + 50 (Sly) = 126; mult 2 + 0 (Raised Fist on the debuffed 2♠) + 15 = 17
    assert analysis.estimate_play(G, played, held)["score"] == 2142


def test_raised_fist_still_fires_on_a_live_lowest_card() -> None:
    G, played, held = _n05(two_debuffed=False)
    # Steel 2♠ live: mult (2 x 1.5) + 4 (Raised Fist) + 15 = 22 -> 126 x 22
    assert analysis.estimate_play(G, played, held)["score"] == 2772


def test_raised_fist_tie_goes_to_the_last_card_in_hand() -> None:
    G = make_state("H_A D_A H_7 D_7", [joker("j_raised_fist", "Raised Fist")])
    cards = G["hand"]["cards"]
    played = cards[:2]
    cards[3]["state"] = {"debuff": True}  # 7♦ debuffed and last: the game picks it -> +0
    base = analysis.estimate_play(G, played, [cards[2], cards[3]])["score"]
    flipped = analysis.estimate_play(G, played, [cards[3], cards[2]])["score"]  # 7♥ last -> +14
    assert base == (10 + 22) * 2
    assert flipped == (10 + 22) * (2 + 14)

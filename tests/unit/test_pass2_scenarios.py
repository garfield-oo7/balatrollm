"""Acceptance gate for the pass-2 strength check: the owner's scenarios S1-S4
(owner doc rev 467; answers.md "Section 6 follow-ups") must come out
COMFORTABLE / SHORT / COMFORTABLE / COMFORTABLE. Inputs not given by the
scenarios were fixed before any result was computed (pass2_build_plan.md):
standard Red Deck cards, S1 Two Pair Lv1, S3 = the shop after the Ante 3 boss
(the game shows Ante 4, next blind A4 Small 5,000, boss The Hook), S4 deck =
52 + 2 Death copies of Kings, one Steel King, one Gold King.
"""

from typing import Any

from balatrollm import analysis

from .test_analysis import card, joker, make_state

TROUSERS = "This Joker gains +2 Mult if played hand contains a Two Pair (Currently +{} Mult)"
CASTLE = "This Joker gains +3 Chips per discarded Club card, suit changes every round (Currently +{} Chips)"


def shop_state(
    ante: int,
    jokers: list[dict[str, Any]],
    money: int,
    blinds: dict[str, tuple[str, str, int]],
    levels: dict[str, int] | None = None,
) -> dict[str, Any]:
    G = make_state("H_2", jokers, state="SHOP")
    G["hand"] = {"count": 0, "limit": 8, "highlighted_limit": 5, "cards": []}
    G["cards"]["cards"].append(card("H_2"))
    G["cards"]["count"] = 52
    G["ante_num"] = ante
    G["money"] = money
    for name, lv in (levels or {}).items():
        dc, dm = analysis.LEVEL_UP[name]
        h = G["hands"][name]
        h.update(level=lv, chips=h["chips"] + dc * (lv - 1), mult=h["mult"] + dm * (lv - 1))
    G["blinds"] = {
        k: {"status": st, "name": nm, "score": sc, "effect": ""}
        for k, (st, nm, sc) in blinds.items()
    }
    return G


def rounds(*spare: int) -> list[dict[str, Any]]:
    return [{"hands_left": s} for s in spare]


def s1() -> tuple[dict[str, Any], list]:
    G = shop_state(
        2,
        [
            joker("j_trousers", "Spare Trousers", TROUSERS.format(4)),
            joker("j_castle", "Castle", CASTLE.format(21)),
        ],
        19,
        {
            "small": ("DEFEATED", "Small Blind", 800),
            "big": ("UPCOMING", "Big Blind", 1200),
            "boss": ("UPCOMING", "The Club", 1600),
        },
    )
    G["round_num"] = 4
    return G, rounds(2, 1, 1, 3)


def s2() -> tuple[dict[str, Any], list]:
    G = shop_state(
        2,
        [joker("j_joker", "Joker"), joker("j_greedy_joker", "Greedy Joker")],
        14,
        {
            "small": ("DEFEATED", "Small Blind", 800),
            "big": ("DEFEATED", "Big Blind", 1200),
            "boss": ("UPCOMING", "The Wall", 3200),
        },
    )
    G["round_num"] = 5
    return G, rounds(2, 1, 1, 1, 0)


def s3() -> tuple[dict[str, Any], list]:
    G = shop_state(
        4,
        [
            joker("j_card_sharp", "Card Sharp", "X3 Mult if played poker hand has already been played this round"),
            joker("j_misprint", "Misprint"),
            joker("j_space", "Space Joker", "1 in 4 chance to upgrade level of played poker hand"),
        ],
        31,
        {
            "small": ("UPCOMING", "Small Blind", 5000),
            "big": ("UPCOMING", "Big Blind", 7500),
            "boss": ("UPCOMING", "The Hook", 10000),
        },
        {"Pair": 3},
    )
    G["round_num"] = 9
    return G, rounds(2, 1, 2, 2, 1, 1, 2, 1)


def s4() -> tuple[dict[str, Any], list]:
    G = shop_state(
        4,
        [
            joker("j_baron", "Baron", "Each King held in hand gives X1.5 Mult"),
            joker("j_mime", "Mime"),
            joker("j_shoot_the_moon", "Shoot the Moon"),
            joker("j_golden", "Golden Joker"),
            joker("j_joker", "Joker"),
        ],
        42,
        {
            "small": ("DEFEATED", "Small Blind", 5000),
            "big": ("DEFEATED", "Big Blind", 7500),
            "boss": ("UPCOMING", "The Psychic", 10000),
        },
        {"Pair": 4},
    )
    deck = G["cards"]["cards"]
    deck += [card("S_K"), card("H_K")]  # two Death copies of Kings
    for c in deck:
        if c["key"] == "C_K":
            c["modifier"] = {"enhancement": "STEEL"}
        elif c["key"] == "D_K":
            c["modifier"] = {"enhancement": "GOLD"}
    G["cards"]["count"] = len(deck)
    G["round_num"] = 11
    return G, rounds(2, 1, 2, 2, 1, 1, 2, 1, 2, 2)


EXPECTED = {"S1": (s1, "COMFORTABLE"), "S2": (s2, "SHORT"), "S3": (s3, "COMFORTABLE"), "S4": (s4, "COMFORTABLE")}


def status(make: Any) -> dict[str, Any]:
    G, rnds = make()
    return analysis.run_status(G, rnds, [])


def test_s1_trousers_and_castle_carry_ante_2() -> None:
    assert status(s1)["status"] == "COMFORTABLE"


def test_s2_short_before_the_wall() -> None:
    assert status(s2)["status"] == "SHORT"


def test_s3_card_sharp_combo_is_enough() -> None:
    assert status(s3)["status"] == "COMFORTABLE"


def test_s4_baron_build_before_the_psychic() -> None:
    assert status(s4)["status"] == "COMFORTABLE"

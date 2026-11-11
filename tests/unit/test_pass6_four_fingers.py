"""Pass 6 H1b: with Four Fingers only the cards that make the Flush / Straight score (the game's get_flush /
get_straight; a Straight Flush scores the union). Pass-5 N95: J♦ 10♥ 7♦ 4♦ 2♦ counted the off-suit 10♥."""

from balatrollm import analysis

from .test_analysis import card


def _cls(hand: str, **kw):
    cards = [analysis._norm(card(k)) for k in hand.split()]
    htype, scoring = analysis.classify(cards, **kw)
    return htype, [hand.split()[i] for i in scoring]


def test_n95_off_suit_card_does_not_score():
    assert _cls("D_J H_T D_7 D_4 D_2", four_fingers=True) == (
        "Flush",
        ["D_J", "D_7", "D_4", "D_2"],
    )


def test_five_same_suit_with_four_fingers_all_score():
    assert _cls("D_J D_T D_7 D_4 D_2", four_fingers=True) == (
        "Flush",
        ["D_J", "D_T", "D_7", "D_4", "D_2"],
    )


def test_straight_off_run_card_does_not_score():
    # N97 Q♥ 10♥ 9♦ 8♠ 7♣: Q♥ is off the 7-10 run
    assert _cls("H_Q H_T D_9 S_8 C_7", four_fingers=True) == (
        "Straight",
        ["H_T", "D_9", "S_8", "C_7"],
    )


def test_straight_duplicate_rank_scores():
    htype, scoring = _cls("H_T D_9 S_9 S_8 C_7", four_fingers=True)
    assert htype == "Straight" and sorted(scoring) == sorted(
        ["H_T", "D_9", "S_9", "S_8", "C_7"]
    )


def test_ace_low_four_fingers():
    assert _cls("S_A H_2 D_3 C_4 H_9", four_fingers=True) == (
        "Straight",
        ["S_A", "H_2", "D_3", "C_4"],
    )


def test_straight_flush_union():
    # 9-Q run (Q♥ J♥ 10♥ 9♠) and a heart flush (Q♥ J♥ 10♥ 3♥): every card is in one of the two parts
    htype, scoring = _cls("H_Q H_J H_T S_9 H_3", four_fingers=True)
    assert htype == "Straight Flush" and len(scoring) == 5


def test_without_four_fingers_unchanged():
    assert _cls("D_J D_T D_7 D_4 D_2") == ("Flush", ["D_J", "D_T", "D_7", "D_4", "D_2"])
    assert _cls("H_J D_T S_9 S_8 C_7") == (
        "Straight",
        ["H_J", "D_T", "S_9", "S_8", "C_7"],
    )
    assert _cls("D_J H_T D_7 D_4 D_2")[0] == "High Card"


def test_wild_cards_follow_the_installed_suit_order():
    # Sol H1 blocker 1: 2♦ 5♣ 8♥ Wild + A♠ + 3♦ with Four Fingers: Diamonds qualify first (SMODS order D, C, H, S)
    cards = [
        analysis._norm(card("D_2", enhancement="WILD")),
        analysis._norm(card("C_5", enhancement="WILD")),
        analysis._norm(card("H_8", enhancement="WILD")),
        analysis._norm(card("S_A")),
        analysis._norm(card("D_3")),
    ]
    htype, scoring = analysis.classify(cards, four_fingers=True)
    assert htype == "Flush" and scoring == [0, 1, 2, 4]

"""Pass 3 (luna-notes/pass3_plan.md C1-C9): one test group per change."""

from typing import Any

import pytest

from balatrollm import analysis

from .test_analysis import blind_select, card, joker, make_state  # noqa: F401


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    analysis._CACHE.clear()
    yield
    analysis._CACHE.clear()


def shop(boss: str = "The Hook", **kw: Any) -> dict[str, Any]:
    G = make_state("H_2", state="SHOP", boss=boss, **kw)
    G["hand"]["cards"] = []
    G["blinds"]["small"]["status"] = "DEFEATED"
    G["blinds"]["big"]["status"] = "UPCOMING"
    return G


# ---------------------------------------------------------------------------
# C1 K5: low percentile for STATUS / boss check / boss reroll; shop SCORE mean
# ---------------------------------------------------------------------------
class TestK5:
    def test_nearest_rank_percentile(self) -> None:
        values = list(range(1, 101))  # 1..100
        assert analysis.percentile(values, 25) == 25
        assert analysis.percentile(values, 20) == 20
        assert analysis.percentile(values, 40) == 40
        assert analysis.percentile([5, 1, 3, 2, 4], 25) == 2  # ceil(1.25) = 2nd smallest
        assert analysis.percentile([7], 25) == 7
        assert analysis.percentile([], 25) == 0

    def test_low_is_at_most_the_mean(self) -> None:
        power = analysis.power_check(shop())
        assert 0 < power["per_hand_low"] <= power["per_hand"]
        assert 0 < power["boss_per_hand_low"] <= power["boss_per_hand"]

    def test_situation_reads_the_low_value(self) -> None:
        G = shop()
        power = analysis.power_check(G)
        assert power["per_hand_low"] < power["per_hand"]
        # a target the mean beats in 3 of 4 hands but the low value does not
        G["blinds"]["big"]["score"] = 3 * power["per_hand"]
        analysis._CACHE.clear()
        S = analysis.run_status(G, [], [])
        assert S["sit_per"] == power["per_hand_low"]
        assert S["status"] in ("THIN", "SHORT")

    def test_boss_check_reads_the_low_value(self) -> None:
        G = shop(boss="The Club")
        bc = analysis.boss_check(G, [])
        assert bc is not None
        analysis._CACHE.clear()
        analysis.K5_PERCENTILE, keep = 100, analysis.K5_PERCENTILE
        try:
            top = analysis.boss_check(G, [])
        finally:
            analysis.K5_PERCENTILE = keep
        assert bc["per_hand"] < top["per_hand"]

    def test_shop_score_stays_on_the_mean(self) -> None:
        G = shop()
        G["shop"] = {"cards": [joker("j_joker", "Joker", "+4 Mult")]}
        keep = analysis.K5_PERCENTILE
        out = []
        try:
            for p in (1, 25, 99):
                analysis.K5_PERCENTILE = p
                analysis._CACHE.clear()
                imp = analysis.shop_impact(G)
                out.append((imp["score"], imp["shop"]))
        finally:
            analysis.K5_PERCENTILE = keep
        assert out[0] == out[1] == out[2]


# ---------------------------------------------------------------------------
# C2: the safety net lifts THIN only, never SHORT
# ---------------------------------------------------------------------------
class TestSafetyNet:
    easy = [{"hands_left": 2}, {"hands_left": 3}]

    def test_short_stays_short(self) -> None:
        G = shop()
        G["blinds"]["big"]["score"] = 10_000_000
        S = analysis.run_status(G, self.easy, [])
        assert S["status"] == "SHORT" and not S["safety_net"]

    def test_thin_lifts(self) -> None:
        G = shop()
        G["blinds"]["big"]["score"] = 4 * analysis.power_check(G)["per_hand_low"]
        S = analysis.run_status(G, self.easy, [])
        assert S["status"] == "COMFORTABLE" and S["safety_net"]
        assert analysis.run_status(G, [{"hands_left": 1}, {"hands_left": 3}], [])["status"] == "THIN"


# ---------------------------------------------------------------------------
# C3: The Mark: face-down cards are face cards (masked; never discarded)
# ---------------------------------------------------------------------------
def mark_hand(faces: str = "S_K H_Q D_J C_K H_K", visible: str = "H_2 S_3 D_7", jokers: Any = None) -> dict[str, Any]:
    """The Mark current: ``faces`` dealt face down, ``visible`` face up."""
    G = make_state(f"{faces} {visible}", jokers=jokers, boss="The Mark", boss_current=True)
    G["blinds"]["boss"]["score"] = 100_000
    G["ante_num"] = 2
    for c in G["hand"]["cards"][: len(faces.split())]:
        c["state"] = {"hidden": True}
    for i, c in enumerate(G["hand"]["cards"]):
        c["id"] = 1000 + i
    return G


def render(G: dict[str, Any]) -> str:
    from balatrollm.strategy import StrategyManager

    flags = {"suggest_action": True, "lessons": False}
    return StrategyManager("mastery").render_gamestate(G, rounds=[], history=[], flags=flags)


class TestMark:
    def test_mask_hides_rank_suit_and_enhancement(self) -> None:
        G = mark_hand()
        G["hand"]["cards"][0]["modifier"] = {"enhancement": "GOLD"}
        V = analysis.mark_view(G)
        hidden = [c for c in V["hand"]["cards"] if c["state"].get("hidden")]
        assert len(hidden) == 5
        for c in hidden:
            n = analysis._norm(c)
            assert n["rank"] is None and n["suit"] is None and n["enh"] is None and n["face"]
        assert analysis.mark_view(make_state("H_2 S_3")) is not None  # other blinds: unchanged
        plain = make_state("H_2 S_3")
        assert analysis.mark_view(plain) is plain

    def test_suggested_discard_never_takes_a_face_down_card(self) -> None:
        for faces, visible in (("S_K H_Q D_J", "H_2 S_3 D_7 C_8 H_9"), ("S_K", "H_2 S_3 D_7 C_8 H_9 D_4 C_5"),
                               ("S_K H_Q D_J C_K H_K S_Q D_Q", "H_2")):
            G = mark_hand(faces, visible)
            hidden = set(range(len(faces.split())))
            A = analysis.play_advice(G)
            assert not hidden & set(A["discard"])
            if A["action"]["tool"] == "discard":
                assert not hidden & set(A["action"]["cards"])
            for d in A["draws"]:
                assert not hidden & set(d["discard"])

    def test_face_down_play_listed_with_its_minimum(self) -> None:
        for faces, minimum in (("S_K H_Q D_J C_K H_K", "Two Pair"), ("S_K H_Q D_J C_K", "Pair"), ("S_K H_Q D_J", None)):
            G = mark_hand(faces)
            mp = analysis.play_advice(G)["mark_play"]
            assert mp is not None and mp["n"] == len(faces.split())
            assert mp["cards"] == list(range(mp["n"]))
            # the plan's floors are a lower bound for the computed minimum
            if minimum is None:
                assert mp["minimum"] is None
            else:
                order = analysis.HAND_ORDER
                assert mp["minimum"] is not None and order.index(mp["minimum"]) <= order.index(minimum)
            assert mp["expected"] >= mp["low"] > 0
        text = render(mark_hand())
        assert "Face-down play [0, 1, 2, 3, 4]" in text and "at least Two Pair" in text

    def test_more_than_five_face_down_plays_five(self) -> None:
        mp = analysis.mark_play(mark_hand("S_K H_Q D_J C_K H_K S_Q D_Q", "H_2"))
        assert mp["n"] == 5 and len(mp["cards"]) == 5

    def test_face_jokers_score_face_down_cards(self) -> None:
        plain = analysis.mark_play(mark_hand())
        smiley = analysis.mark_play(mark_hand(jokers=[joker("j_smiley", "Smiley Face", "+5 Mult for face cards")]))
        photo = analysis.mark_play(mark_hand(jokers=[joker("j_photograph", "Photograph", "X2 first face card")]))
        assert smiley["expected"] > plain["expected"] and photo["expected"] > plain["expected"]

    def test_held_face_down_kings_count_for_baron_by_the_mix(self) -> None:
        baron = [joker("j_baron", "Baron", "Each King held in hand gives X1.5 Mult")]
        G = mark_hand("S_K H_K D_K", "H_2 H_3 S_3 D_7 C_8", jokers=baron)
        V = analysis.mark_view(G)
        hand = V["hand"]["cards"]
        with_held = analysis.estimate_play(V, [hand[4], hand[5]], [c for i, c in enumerate(hand) if i not in (4, 5)])
        no_baron = analysis.estimate_play(analysis.mark_view(mark_hand("S_K H_K D_K", "H_2 H_3 S_3 D_7 C_8")),
                                          [hand[4], hand[5]], [c for i, c in enumerate(hand) if i not in (4, 5)])
        assert with_held["score"] > no_baron["score"]

    def test_permuting_the_real_face_down_cards_changes_nothing(self) -> None:
        """Leak test: the advice and the prompt never depend on which face card is which."""
        a = mark_hand("S_K H_Q D_J C_K H_K", "H_2 S_3 D_7")
        b = mark_hand("H_K C_K D_J H_Q S_K", "H_2 S_3 D_7")
        a["hand"]["cards"][4]["modifier"] = {"enhancement": "GOLD"}  # Gold King of Hearts ...
        b["hand"]["cards"][0]["modifier"] = {"enhancement": "GOLD"}  # ... at another position
        for G in (a, b):
            G["round"]["discards_left"] = 3
        A1, A2 = analysis.play_advice(a), analysis.play_advice(b)
        for k in ("plays", "draws", "discard", "action", "mark_play"):
            assert A1[k] == A2[k], k
        assert render(a) == render(b)

    def test_memory_discard_line_never_names_a_face_down_card(self) -> None:
        before = mark_hand("S_K H_Q", "H_2 S_3 D_7")
        after = mark_hand("D_J", "S_3 D_7 C_9")
        after["hand"]["cards"][0]["id"] = 2000
        after["hand"]["cards"][3]["id"] = 2003
        before_ids = [c["id"] for c in before["hand"]["cards"]]
        after["hand"]["cards"][1]["id"], after["hand"]["cards"][2]["id"] = before_ids[3], before_ids[4]
        out = analysis.summarize_outcome("discard", {"cards": [0, 1, 2]}, before, after)
        assert "S_K" not in out and "H_Q" not in out and "D_J" not in out
        assert out.count("face-down card") == 3 and "H_2" in out and "C_9" in out

    def test_shop_boss_line(self) -> None:
        G = shop(boss="The Mark")
        assert "keep and play them" in analysis.boss_impact(G)["impact"]
        assert "The Mark: your face cards come face down" in render(G)

    def test_pareidolia_any_card_can_be_face_down(self) -> None:
        jk = [joker("j_pareidolia", "Pareidolia", "All cards are face cards")]
        mp = analysis.mark_play(mark_hand("S_K H_Q D_J C_K H_K", "H_2 S_3 D_7", jokers=jk))
        assert mp["any_rank"] and mp["minimum"] is None

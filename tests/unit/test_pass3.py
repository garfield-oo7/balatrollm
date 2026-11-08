"""Pass 3 (luna-notes/pass3_plan.md C1-C9): one test group per change."""

from typing import Any

import pytest

from balatrollm import analysis

from .test_analysis import blind_select, card, joker, make_state


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


def _unused() -> None:  # keep helper imports referenced for later groups
    _ = (blind_select, card)

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


# ---------------------------------------------------------------------------
# C4: Luna's own boss-reroll request; The Plant no longer automatic
# C5: The Wall rerolled in Antes 1-3; from Ante 4 only when the boss check fails
# ---------------------------------------------------------------------------
def boss_shop(boss: str = "The Plant", ante: int = 2, money: int = 20, rerolls: int = 0) -> dict[str, Any]:
    G = shop(boss=boss)
    G["ante_num"] = ante
    G["money"] = money
    G["used_vouchers"] = {"v_directors_cut": ""}
    G["round"]["boss_rerolled"] = False
    G["luna"] = {"luna_reroll": True, "boss_rerolls": rerolls, "boss_reroll_request": None}
    return G


def _call(name: str, **args: Any) -> Any:
    import json
    from types import SimpleNamespace

    call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps({"reasoning": "x", **args})))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])


def _bot() -> Any:
    from unittest.mock import AsyncMock

    from .test_bot_swap import _bot as make

    game = AsyncMock()
    bot = make(game)
    bot.harness = {"validate_actions": True, "reroll_boss": True}
    bot._boss_rerolls = {}
    bot._boss_reroll_request = None
    return bot, game


class TestLunaBossReroll:
    def test_allowed_and_refused_in_the_shop(self) -> None:
        assert analysis.validate_action(boss_shop(), "reroll_boss", {}) is None
        no_voucher = boss_shop()
        no_voucher["used_vouchers"] = {}
        assert "Director's Cut or Retcon" in analysis.validate_action(no_voucher, "reroll_boss", {})
        assert "costs $10" in analysis.validate_action(boss_shop(money=9), "reroll_boss", {})
        assert "must stay" in analysis.validate_action(boss_shop(ante=4, money=19), "reroll_boss", {})
        assert analysis.validate_action(boss_shop(ante=4, money=20), "reroll_boss", {}) is None
        assert "one per ante" in analysis.validate_action(boss_shop(rerolls=1), "reroll_boss", {})
        asked = boss_shop()
        asked["luna"]["boss_reroll_request"] = {"ante": 2, "boss": "The Plant"}
        assert "already asked" in analysis.validate_action(asked, "reroll_boss", {})
        beaten = boss_shop()
        beaten["blinds"]["boss"]["status"] = "DEFEATED"
        assert "already" in analysis.validate_action(beaten, "reroll_boss", {})

    def test_the_plant_is_not_rerolled_automatically(self) -> None:
        G = blind_select("The Plant", on_deck="boss")
        G["jokers"]["cards"] = [joker("j_photograph", "Photograph")]
        G["jokers"]["count"] = 1
        assert analysis.face_build(G) and analysis.boss_reroll_reason(G) is None

    def test_status_line_only_when_available(self) -> None:
        text = render(boss_shop())
        assert "BOSS REROLL available ($10, one per ante)" in text and "The Plant turns off your face-card jokers" in text
        assert "BOSS REROLL available" not in render(boss_shop(money=9))
        assert "BOSS REROLL available" not in render(boss_shop(rerolls=1))
        asked = boss_shop()
        asked["luna"]["boss_reroll_request"] = {"ante": 2, "boss": "The Plant"}
        assert "BOSS REROLL queued: The Plant" in render(asked)

    def test_tool_offered_in_the_shop(self) -> None:
        from balatrollm.strategy import StrategyManager

        names = [t["function"]["name"] for t in StrategyManager("mastery").get_tools("SHOP")]
        assert "reroll_boss" in names

    async def test_request_queued_then_run_at_blind_select(self) -> None:
        bot, game = _bot()
        game.call.return_value = {"state": "SHOP"}
        before = boss_shop()
        await bot._execute_tool_call(_call("reroll_boss"), before)
        assert [c.args[0] for c in game.call.call_args_list] == ["gamestate"]  # never sent to BalatroBot
        assert bot._boss_reroll_request == {"ante": 2, "boss": "The Plant"}
        assert "queued" in bot._history[-1]["result"]
        # next blind select of the ante: the harness runs it, before its own check
        game.call.reset_mock()
        sel = blind_select("The Plant")
        sel["ante_num"] = 2
        after = blind_select("The Hook")
        after["ante_num"] = 2
        game.call.return_value = after
        assert await bot._reroll_boss(sel) is after
        assert [c.args[0] for c in game.call.call_args_list] == ["reroll_boss"]
        assert bot._boss_reroll_request is None and bot._boss_rerolls == {2: 1}
        assert "The Plant -> The Hook" in bot._history[-1]["result"]

    async def test_execution_failure_keeps_the_ante_reroll(self) -> None:
        bot, game = _bot()
        bot._boss_reroll_request = {"ante": 2, "boss": "The Plant"}
        sel = blind_select("The Plant")
        sel["ante_num"] = 2
        sel["money"] = 5  # spent below $10 after asking
        assert await bot._reroll_boss(sel) is None
        game.call.assert_not_called()
        assert bot._boss_rerolls == {} and bot._boss_reroll_request is not None
        sel["money"] = 20  # the next blind select of the ante: runs now
        game.call.return_value = blind_select("The Hook")
        assert await bot._reroll_boss(sel) is not None
        assert bot._boss_rerolls == {2: 1}

    async def test_request_lapses_when_the_ante_moves_on(self) -> None:
        bot, game = _bot()
        bot._boss_reroll_request = {"ante": 2, "boss": "The Plant"}
        sel = blind_select("The Hook")
        sel["ante_num"] = 3
        await bot._reroll_boss(sel)
        assert bot._boss_reroll_request is None

    async def test_refused_request_is_a_veto(self) -> None:
        bot, game = _bot()
        game.call.return_value = {"state": "SHOP"}
        await bot._execute_tool_call(_call("reroll_boss"), boss_shop(money=9))
        assert bot._boss_reroll_request is None
        assert "Boss reroll refused" in bot._last_failed_msg


class TestWall:
    def wall(self, ante: int, money: int) -> dict[str, Any]:
        G = blind_select("The Wall")
        G["ante_num"] = ante
        G["money"] = money
        return G

    def test_antes_1_to_3_always(self) -> None:
        for ante in (1, 2, 3):
            assert "The Wall" in (analysis.boss_reroll_reason(self.wall(ante, 10)) or "")

    def test_ante_4_only_when_the_boss_check_fails(self) -> None:
        easy = self.wall(4, 20)
        easy["blinds"]["boss"]["score"] = 1
        assert analysis.boss_reroll_reason(easy) is None
        hard = self.wall(4, 20)
        hard["blinds"]["boss"]["score"] = 10_000_000
        assert analysis.boss_check(hard)["ok"] is False
        assert "hands" in (analysis.boss_reroll_reason(hard) or "")
        broke = self.wall(4, 19)  # $10 must stay
        broke["blinds"]["boss"]["score"] = 10_000_000
        assert analysis.boss_reroll_reason(broke) is None

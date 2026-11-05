"""Unit tests for the deterministic analysis helpers and the mastery strategy."""

from typing import Any

import pytest

from balatrollm import analysis, knowledge
from balatrollm.strategy import StrategyManager, StrategyManifest

BASE = {
    "Flush Five": (160, 16),
    "Flush House": (140, 14),
    "Five of a Kind": (120, 12),
    "Straight Flush": (100, 8),
    "Four of a Kind": (60, 7),
    "Full House": (40, 4),
    "Flush": (35, 4),
    "Straight": (30, 4),
    "Three of a Kind": (30, 3),
    "Two Pair": (20, 2),
    "Pair": (10, 2),
    "High Card": (5, 1),
}


def card(key: str, **mod: Any) -> dict[str, Any]:
    suit, rank = key.split("_")
    return {
        "key": key,
        "set": "ENHANCED" if mod.get("enhancement") else "DEFAULT",
        "label": "Base Card",
        "value": {"suit": suit, "rank": rank, "effect": ""},
        "modifier": mod,
        "state": {},
        "cost": {"buy": 1, "sell": 1},
    }


def joker(key: str, label: str, effect: str = "", cost: int = 5, **mod: Any):
    return {
        "key": key,
        "set": "JOKER",
        "label": label,
        "value": {"effect": effect},
        "modifier": mod,
        "state": {},
        "cost": {"buy": cost, "sell": cost // 2},
    }


def make_state(
    hand: str,
    jokers: list[dict[str, Any]] | None = None,
    state: str = "SELECTING_HAND",
    boss: str = "The Hook",
    boss_current: bool = False,
    **round_kw: Any,
) -> dict[str, Any]:
    hand_cards = [card(k) for k in hand.split()]
    keys = {c["key"] for c in hand_cards}
    deck = [
        card(f"{s}_{r}")
        for s in "HDCS"
        for r in "23456789TJQKA"
        if f"{s}_{r}" not in keys
    ]
    jokers = jokers or []
    rnd = {
        "hands_left": 4,
        "hands_played": 0,
        "discards_left": 4,
        "discards_used": 0,
        "reroll_cost": 5,
        "chips": 0,
    }
    rnd.update(round_kw)
    return {
        "state": state,
        "ante_num": 1,
        "round_num": 1,
        "money": 4,
        "hands": {
            n: {
                "chips": c,
                "mult": m,
                "level": 1,
                "played": 0,
                "played_this_round": 0,
                "order": i + 1,
            }
            for i, (n, (c, m)) in enumerate(BASE.items())
        },
        "hand": {"count": 8, "limit": 8, "highlighted_limit": 5, "cards": hand_cards},
        "cards": {"count": len(deck), "cards": deck},
        "jokers": {"count": len(jokers), "limit": 5, "cards": jokers},
        "consumables": {"count": 0, "limit": 2, "cards": []},
        "blinds": {
            "small": {
                "status": "DEFEATED" if boss_current else "CURRENT",
                "name": "Small Blind",
                "score": 300,
            },
            "big": {
                "status": "DEFEATED" if boss_current else "UPCOMING",
                "name": "Big Blind",
                "score": 450,
            },
            "boss": {
                "status": "CURRENT" if boss_current else "UPCOMING",
                "name": boss,
                "effect": "",
                "score": 600,
            },
        },
        "round": rnd,
        "used_vouchers": {},
    }


class TestClassify:
    def _cls(self, keys: str, **kw: bool) -> str:
        cards = [analysis._norm(card(k)) for k in keys.split()]
        return analysis.classify(cards, **kw)[0]

    @pytest.mark.parametrize(
        ("keys", "expected"),
        [
            ("H_A H_K H_T H_5 H_4", "Flush"),
            ("H_9 S_8 D_7 C_6 H_5", "Straight"),
            ("H_A S_2 D_3 C_4 H_5", "Straight"),
            ("H_Q S_K D_A C_2 H_3", "High Card"),
            ("H_9 H_8 H_7 H_6 H_5", "Straight Flush"),
            ("H_9 S_9 D_9 C_6 H_6", "Full House"),
            ("H_9 S_9 D_6 C_6", "Two Pair"),
            ("H_9 S_9 D_9 C_9", "Four of a Kind"),
            ("H_9 S_9", "Pair"),
        ],
    )
    def test_hand_types(self, keys: str, expected: str) -> None:
        assert self._cls(keys) == expected

    def test_four_fingers_flush(self) -> None:
        assert self._cls("H_A H_K H_T H_5", four_fingers=True) == "Flush"
        assert self._cls("H_A H_K H_T H_5") == "High Card"

    def test_smeared_flush(self) -> None:
        assert self._cls("H_A D_K H_T D_5 H_4", smeared=True) == "Flush"

    def test_pair_scores_only_pair_cards(self) -> None:
        cards = [analysis._norm(card(k)) for k in "H_9 S_9 D_2 C_4 H_K".split()]
        assert analysis.classify(cards)[1] == [0, 1]


class TestEstimate:
    def test_plain_flush(self) -> None:
        G = make_state("H_A H_K H_T H_5 H_4 S_4 C_4 D_9")
        played = G["hand"]["cards"][:5]
        est = analysis.estimate_play(G, played, G["hand"]["cards"][5:])
        assert est["hand"] == "Flush"
        assert est["score"] == (35 + 11 + 10 + 10 + 5 + 4) * 4

    def test_joker_stack_and_order(self) -> None:
        hand = [
            card("H_K", enhancement="GLASS"),
            card("H_Q"),
            card("H_9"),
            card("H_5"),
            card("H_3"),
            card("S_K", enhancement="STEEL"),
        ]
        G = make_state("C_2", [])
        G["hand"]["cards"] = hand
        G["jokers"]["cards"] = [
            joker("j_droll", "Droll Joker"),
            joker("j_blueprint", "Blueprint"),
            joker("j_cavendish", "Cavendish", edition="POLYCHROME"),
        ]
        est = analysis.estimate_play(G, hand[:5], hand[5:])
        # chips 35+10+10+9+5+3 = 72; mult ((4*2)*1.5 + 10) * 3 * 3 * 1.5 = 297
        assert est["chips"] == 72
        assert est["score"] == 72 * 297

    def test_currently_regex_and_floor(self) -> None:
        G = make_state(
            "H_6 S_6 D_2 C_4 H_K S_3 C_8 D_J",
            [
                joker("j_ride_the_bus", "Ride the Bus", "(Currently +3 Mult)"),
                joker("j_misprint", "Misprint", "+0-23 Mult"),
            ],
        )
        hand = G["hand"]["cards"]
        est = analysis.estimate_play(G, hand[:2], hand[2:])
        assert est["score"] == (10 + 12) * (2 + 3)  # Misprint counts 0 (floor)

    def test_psychic_blocks_short_plays(self) -> None:
        G = make_state("H_6 S_6 D_2 C_4 H_K", boss="The Psychic", boss_current=True)
        hand = G["hand"]["cards"]
        assert analysis.estimate_play(G, hand[:2], hand[2:])["score"] == 0


class TestLookAheadAndRefusals:
    def test_no_discards_left_is_refused(self) -> None:
        G = make_state("H_A H_K H_T H_5 H_4 S_4 C_4 D_9")
        G["round"]["discards_left"] = 0
        assert "No discards left" in analysis.validate_action(G, "discard", {"cards": [7]})

    def test_boss_look_ahead_turns_status_too_weak(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["ante_num"] = 3
        G["blinds"] = {
            "small": {"status": "DEFEATED", "score": 2000},
            "big": {"status": "UPCOMING", "score": 3000},
            "boss": {"status": "UPCOMING", "score": 4000, "name": "The Flint"},
        }
        history = [{"method": "play", "score": 1100}] * 3
        S = analysis.run_status(G, [], history)
        # Big Blind: 3 hands at 1,100. The Flint at 60% pace: 4000 / 660 = 7 hands
        assert S["hands_needed"] == 3 and S["boss_hands"] == 7
        assert S["status"] == "TOO WEAK"
        G["blinds"]["boss"]["name"] = "The Wall"  # 4000 / 1100 = 4 hands
        assert analysis.run_status(G, [], history)["status"] == "TOO WEAK"
        G["blinds"]["boss"]["score"] = 3000
        assert analysis.run_status(G, [], history)["status"] == "ON TRACK"
        assert "spend money" in analysis.boss_impact({**G, "blinds": {"boss": {"name": "The Ox"}}})["prep"]


class TestRetriggerSynergies:
    def test_hanging_chad_retriggers_photograph(self) -> None:
        photo = joker("j_photograph", "Photograph")
        chad = joker("j_hanging_chad", "Hanging Chad")
        G = make_state("H_K S_K D_2 C_3 H_5", [photo])
        pair = G["hand"]["cards"][:2]
        # Pair of Kings: (10 + 10 + 10) x (2 x2 Photograph) = 120
        assert analysis.estimate_play(G, pair, [])["score"] == 120
        G = make_state("H_K S_K D_2 C_3 H_5", [photo, chad])
        # first King scores 3 times and Photograph fires each time:
        # (10 + 3*10 + 10) x (2 x8) = 800
        assert analysis.estimate_play(G, pair, [])["score"] == 800

    def test_chad_and_photograph_are_kept_unless_the_plant(self) -> None:
        jokers = [
            joker("j_photograph", "Photograph"),
            joker("j_hanging_chad", "Hanging Chad"),
            joker("j_joker", "Joker", "+4 Mult"),
        ]
        G = make_state("H_K S_K D_2", jokers, state="SHOP")
        G["jokers"]["limit"] = 3  # full
        G["shop"] = {"cards": [joker("j_duo", "The Duo", cost=1)]}
        assert "Hanging Chad" in analysis.synergy_keep(G)
        assert "Photograph" in analysis.validate_action(G, "sell", {"joker": 1})
        assert analysis.shop_impact(G)["weakest"]["label"] == "Joker"
        G["blinds"] = {"boss": {"name": "The Plant"}}
        assert analysis.synergy_keep(G) == {}
        G["used_vouchers"] = {"v_directors_cut": ""}
        assert "Hanging Chad" in analysis.synergy_keep(G)

    def test_two_pair_averages_every_pair_of_ranks(self) -> None:
        G = make_state("H_2", state="SHOP")
        plays = analysis.typical_plays(G, {"hand": "Two Pair"})
        assert len(plays) == 78  # 13 ranks choose 2
        first = analysis._norm(plays[0][0])["rank"]
        assert first == max(
            (analysis._norm(c)["rank"] for c in plays[0]), key=analysis.RANKS.index
        )

    def test_lucky_cards_count_only_when_expected(self) -> None:
        chad = joker("j_hanging_chad", "Hanging Chad")
        G = make_state("H_7 S_7 D_2 C_3 H_5", [chad])
        G["hand"]["cards"][0]["modifier"] = {"enhancement": "LUCKY"}
        pair = G["hand"]["cards"][:2]
        floor = analysis.estimate_play(G, pair, [])["score"]
        expected = analysis.estimate_play(G, pair, [], expected=True)["score"]
        # (10 + 3*7 + 7) chips; the Lucky 7 scores 3 times: +4 Mult each on average
        assert floor == 38 * 2 and expected == 38 * (2 + 12)


class TestPlayAdvice:
    def test_wins_needs_margin(self) -> None:
        # With a joker the floor estimate needs a 10% margin to count as WINS.
        jok = [joker("j_joker", "Joker", "+4 Mult")]
        G = make_state("H_A H_K H_T H_5 H_4 S_4 C_4 D_9", jok, chips=-260)
        flush = next(
            p for p in analysis.play_advice(G)["plays"] if p["hand"] == "Flush"
        )
        assert flush["score"] == 600
        assert not flush["wins"]  # need 560: 600 < 1.10 * 560
        G["round"]["chips"] = -240  # need 540: 600 >= 594
        flush = next(
            p for p in analysis.play_advice(G)["plays"] if p["hand"] == "Flush"
        )
        assert flush["wins"]

    def test_strong_flush_draw_suggests_discard(self) -> None:
        G = make_state("S_K H_9 H_7 D_7 H_4 C_Q H_2 S_3")
        advice = analysis.play_advice(G)
        assert advice["action"]["tool"] == "discard"
        assert set(advice["action"]["cards"]) == {0, 3, 5, 7}

    def test_winning_play_is_suggested(self) -> None:
        G = make_state("H_A H_K H_T H_5 H_4 S_4 C_4 D_9", chips=200)
        action = analysis.play_advice(G)["action"]
        assert action == {"tool": "play", "cards": [0, 1, 2, 3, 4], "why": "Flush WINS"}

    def test_targeted_tarot_is_suggested_first(self) -> None:
        G = make_state("H_A H_K H_T H_5 H_4 S_4 C_4 D_9", chips=200)
        G["consumables"] = {
            "count": 1,
            "limit": 2,
            "cards": [{"key": "c_justice", "label": "Justice", "set": "TAROT"}],
        }
        action = analysis.play_advice(G)["action"]
        assert action["tool"] == "use" and action["consumable"] == 0
        assert action["cards"] == analysis.suggest_targets(G, G["consumables"]["cards"][0])

    def test_discard_of_winning_cards_is_vetoed(self) -> None:
        G = make_state("H_A H_K H_T H_5 H_4 S_4 C_4 D_9", chips=200)
        assert analysis.validate_action(G, "discard", {"cards": [0, 5]})
        assert analysis.validate_action(G, "discard", {"cards": [5, 6]}) is None
        assert analysis.validate_action(G, "play", {"cards": [0, 1, 2, 3, 4, 5]})


class TestPlanAndStatus:
    def test_default_main_hand_is_two_pair(self) -> None:
        plan = analysis.main_hand_plan(make_state("H_2"))
        assert plan["hand"] == "Pair"
        assert plan["open"] and plan["draw_kinds"] == {"Flush", "Straight"}

    def test_open_phase_ends_at_ante_two(self) -> None:
        G = make_state("H_2")
        G["ante_num"] = 2
        plan = analysis.main_hand_plan(G)
        assert not plan["open"] and plan["draw_kinds"] == {"Pair"}

    def test_flush_engine_switches_to_flush(self) -> None:
        G = make_state("H_2", [joker("j_four_fingers", "Four Fingers")])
        assert analysis.main_hand_plan(G)["hand"] == "Flush"

    def test_flush_jokers_without_pair_jokers(self) -> None:
        jokers = [joker("j_droll", "Droll Joker"), joker("j_crafty", "Crafty Joker")]
        assert analysis.main_hand_plan(make_state("H_2", jokers))["hand"] == "Flush"
        jokers.append(joker("j_jolly", "Jolly Joker"))
        assert analysis.main_hand_plan(make_state("H_2", jokers))["hand"] == "Pair"

    def test_two_pair_needs_a_two_pair_joker(self) -> None:
        G = make_state("H_2", [joker("j_trousers", "Spare Trousers")])
        assert analysis.main_hand_plan(G)["hand"] == "Two Pair"
        G = make_state("H_2", [joker("j_duo", "The Duo")])
        assert analysis.main_hand_plan(G)["hand"] == "Pair"

    def test_half_joker_and_trio(self) -> None:
        G = make_state("H_2", [joker("j_half", "Half Joker")])
        assert analysis.main_hand_plan(G)["hand"] == "Pair"
        G = make_state("H_2", [joker("j_trio", "The Trio")])
        assert analysis.main_hand_plan(G)["hand"] == "Three of a Kind"

    def test_flush_draw_not_chased_after_open_phase(self) -> None:
        G = make_state("S_K H_9 H_7 D_7 H_4 C_Q H_2 S_3")
        G["ante_num"] = 3
        advice = analysis.play_advice(G)
        assert advice["draws"] == []
        assert advice["action"]["tool"] == "discard"
        assert {2, 3} & set(advice["action"]["cards"]) == set()  # keeps the 7s

    def test_pair_tarot_targets(self) -> None:
        G = make_state("S_K H_K D_7 C_3 H_8 C_Q H_2 S_6")
        G["ante_num"] = 3
        assert analysis.suggest_targets(G, {"key": "c_strength"}) == [2, 5]
        assert analysis.suggest_targets(G, {"key": "c_hanged_man"}) == [3, 6]
        assert analysis.suggest_targets(G, {"key": "c_sun"}) == []
        assert analysis.suggest_targets(G, {"key": "c_death"}) == []  # nothing modified
        G["hand"]["cards"][5]["modifier"] = {"enhancement": "GLASS"}
        left, right = analysis.suggest_targets(G, {"key": "c_death"})
        assert left < right and right == 5  # copies the RIGHT card onto the LEFT one

    def test_death_copies_only_modified_cards(self) -> None:
        G = make_state("S_4 H_4 D_7 C_3 H_8 C_K H_2 S_6")
        G["ante_num"] = 3
        # a plain face card is no longer copied: Death waits for a modified card
        assert analysis.suggest_targets(G, {"key": "c_death"}) == []
        G["hand"]["cards"][6]["modifier"] = {"seal": "RED"}
        assert analysis.suggest_targets(G, {"key": "c_death"}) == [3, 6]
        G["hand"]["cards"][3]["modifier"] = {"enhancement": "BONUS"}  # keep upgrades
        assert analysis.suggest_targets(G, {"key": "c_death"}) == [2, 6]

    def test_death_flush_copies_main_suit_not_off_suit_face(self) -> None:
        jokers = [joker("j_droll", "Droll Joker"), joker("j_crafty", "Crafty Joker")]
        G = make_state("C_3 H_9 H_4 H_7 D_2 H_5 S_K H_8", jokers)
        G["ante_num"] = 3
        plan = analysis.main_hand_plan(G)
        assert plan["hand"] == "Flush"
        G["hand"]["cards"][6]["modifier"] = {"seal": "RED"}  # off-suit King
        assert analysis.suggest_targets(G, {"key": "c_death"}) == []
        G["hand"]["cards"][7]["modifier"] = {"enhancement": "BONUS"}  # Heart 8
        left, right = analysis.suggest_targets(G, {"key": "c_death"})
        suit = G["hand"]["cards"][right]["value"]["suit"]
        assert suit == plan["suit"] and left < right

    def test_grows_xmult_needs_a_source(self) -> None:
        G = make_state("S_4 H_4 D_7 C_3 H_8 C_K H_2 S_6", state="SHOP")
        glass = joker("j_glass", "Glass Joker")
        assert analysis.grows_xmult(G, glass).endswith("no source yet")
        G["shop"] = {"cards": [{"key": "c_justice", "label": "Justice", "set": "TAROT"}]}
        # Justice only makes more Glass cards: the source is a Glass card in the deck
        assert analysis.grows_xmult(G, glass).endswith(
            "(Justice available makes more) | no source yet"
        )
        G["shop"] = {"cards": []}
        G["hand"]["cards"][0]["modifier"] = {"enhancement": "GLASS"}
        assert "1 in your deck | SOURCE PRESENT" in analysis.grows_xmult(G, glass)
        holo = joker("j_hologram", "Hologram")
        assert analysis.grows_xmult(G, holo).endswith("SOURCE PRESENT")
        assert analysis.grows_xmult(G, joker("j_joker", "Joker")) == ""

    def test_magician_is_good(self) -> None:
        magician = {"key": "c_magician", "set": "TAROT", "label": "The Magician"}
        assert knowledge.consumable_tag(magician, "Pair").startswith("[GOOD]")

    def test_hermit_skipped_with_forty_dollars(self) -> None:
        hermit = {"key": "c_hermit", "set": "TAROT", "label": "The Hermit"}
        assert knowledge.consumable_tag(hermit, "Pair", 0, 39).startswith("[GOOD]")
        assert "Death" in knowledge.consumable_tag(hermit, "Pair", 0, 40)
        assert knowledge.consumable_tag(hermit, "Pair").startswith("[GOOD]")

    def test_interest_spare_and_hologram(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["money"] = 23
        status = analysis.run_status(G, [], [])
        assert status["interest_spare"] == 3 and not status["hologram"]
        G["money"] = 40
        G["jokers"]["cards"] = [joker("j_hologram", "Hologram")]
        status = analysis.run_status(G, [], [])
        assert status["interest_spare"] == 15 and status["hologram"]

    def test_goals_and_priority(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["ante_num"] = 4
        status = analysis.run_status(G, [], [])
        texts = [g["text"] for g in status["goals"]]
        assert texts[0].startswith("5 jokers")
        assert any("XMULT" in t for t in texts) and any("SCALE" in t for t in texts)
        assert status["priority"] == "fill empty joker slots with scoring jokers"

    def test_pair_boss_impact(self) -> None:
        G = make_state("H_2", boss="The Eye")
        assert "AFFECTS MAIN_HAND" in analysis.boss_impact(G)["impact"]

    def test_power_check_uses_recent_scores(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["blinds"]["small"]["status"] = "DEFEATED"
        G["blinds"]["big"]["status"] = "SELECT"
        history = [{"method": "play", "score": 100}] * 3
        status = analysis.run_status(G, [], history)
        assert status["hands_needed"] == 5
        assert status["status"] == "TOO WEAK"
        assert status["effective_floor"] == 0

    def test_joker_order_puts_xmult_right(self) -> None:
        G = make_state("H_2")
        G["jokers"]["cards"] = [
            joker("j_cavendish", "Cavendish"),
            joker("j_joker", "Joker"),
            joker("j_blueprint", "Blueprint"),
        ]
        order = analysis.joker_order(G)
        assert order is not None
        labels = [G["jokers"]["cards"][i]["label"] for i in order]
        assert labels == ["Joker", "Blueprint", "Cavendish"]


class TestKnowledge:
    def test_joker_tags_follow_main_hand(self) -> None:
        droll = joker("j_droll", "Droll Joker")
        assert "[MAIN]" in knowledge.joker_tag(droll, "Flush", 1)
        assert "[OFF-PLAN]" in knowledge.joker_tag(droll, "Two Pair", 1)

    def test_half_joker_is_pair_family(self) -> None:
        half = joker("j_half", "Half Joker")
        assert "[OFF-PLAN]" in knowledge.joker_tag(half, "Flush", 1)

    def test_boss_counter_is_full_sentence(self) -> None:
        assert knowledge.boss_counter("The Psychic").startswith("play EXACTLY 5")

    def test_planet_tag(self) -> None:
        jupiter = {"label": "Jupiter"}
        assert knowledge.consumable_tag(jupiter, "Flush").startswith("[MAIN]")

    def test_every_joker_has_valid_category(self) -> None:
        valid = {
            "XMULT",
            "MULT",
            "SCALE",
            "CHIPS",
            "ECON",
            "UTIL",
            "TRAP",
            "KEEP-DISCARDS",
        }
        assert len(knowledge.JOKERS) == 150
        assert all(v[0] in valid for v in knowledge.JOKERS.values())


class TestMasteryStrategy:
    def test_manifest_harness_flags(self) -> None:
        harness = StrategyManifest.from_file("mastery").harness
        assert harness["system_prompt"] is True
        assert StrategyManifest.from_file("default").harness == {}

    def test_tools_reasoning_first(self) -> None:
        sm = StrategyManager("mastery")
        for state in ("SELECTING_HAND", "SHOP", "SMODS_BOOSTER_OPENED"):
            for tool in sm.get_tools(state):
                params = tool["function"]["parameters"]
                assert next(iter(params["properties"])) == "reasoning"
                assert params["required"][0] == "reasoning"

    @pytest.mark.parametrize(
        "state", ["SELECTING_HAND", "SHOP", "SMODS_BOOSTER_OPENED"]
    )
    def test_renders_every_phase(self, state: str) -> None:
        sm = StrategyManager("mastery")
        G = make_state("S_K H_9 H_7 D_7 H_4 C_Q H_2 S_3", state=state)
        G["pack"] = {"cards": [{"key": "c_sun", "set": "TAROT", "label": "The Sun"}]}
        G["shop"] = {"cards": [joker("j_gros_michel", "Gros Michel")]}
        flags = StrategyManifest.from_file("mastery").harness
        ctx: dict[str, Any] = {"rounds": [], "history": [], "flags": flags}
        text = (
            sm.render_strategy(G, **ctx)
            + sm.render_gamestate(G, **ctx)
            + sm.render_memory([], G=G, rounds=[], flags=flags)
        )
        assert "# STATUS" in text and "# DECIDE NOW" in text
        assert "MAIN_HAND: Pair" in text and "GOALS for Ante 1" in text
        assert len(text) < 16000  # ~4k tokens budget

    def test_default_strategy_still_renders(self) -> None:
        sm = StrategyManager("default")
        G = make_state("S_K H_9 H_7 D_7 H_4 C_Q H_2 S_3")
        assert "Current Hand" in sm.render_gamestate(G)
        assert "Recent Decision History" in sm.render_memory(
            [{"method": "play", "params": {"cards": [0]}, "reasoning": "r"}]
        )


class TestPlanAwareConsumables:
    def test_suit_tarot_avoided_for_pairs(self) -> None:
        sun = {"key": "c_sun", "set": "TAROT", "label": "The Sun"}
        assert knowledge.consumable_tag(sun, "Two Pair").startswith("[AVOID]")
        assert knowledge.consumable_tag(sun, "Flush").startswith("[GOOD]")

    def test_strength_good_for_pairs(self) -> None:
        strength = {"key": "c_strength", "set": "TAROT", "label": "Strength"}
        assert knowledge.consumable_tag(strength, "Two Pair").startswith("[GOOD]")
        assert knowledge.consumable_tag(strength, "Flush").startswith("[SITUATIONAL]")


class TestAnteOneChase:
    JOKER = [joker("j_joker", "Joker", "+4 Mult")]

    def test_ante_one_chases_straight_over_pace_pair(self) -> None:
        # Pair of 4s reaches PER_HAND, but Ante 1 keeps digging for the Straight:
        # ~33% per discard, ~80% within 4 discards.
        G = make_state("S_J D_Q C_K H_A H_3 S_4 C_4 D_2", self.JOKER)
        advice = analysis.play_advice(G)
        straight = next(d for d in advice["draws"] if d["chance"] < 0.5)
        assert straight["chase"] and straight["within"] >= 0.5
        assert advice["action"]["tool"] == "discard"
        assert "chase" in advice["action"]["why"]
        assert {0, 1, 2, 3} & set(advice["action"]["cards"]) == set()

    def test_ante_one_chase_stops_without_discards(self) -> None:
        G = make_state("S_J D_Q C_K H_A H_3 S_4 C_4 D_2", self.JOKER, discards_left=0)
        advice = analysis.play_advice(G)
        assert advice["action"]["tool"] == "play"

    def test_no_chase_from_ante_two(self) -> None:
        G = make_state("S_J D_Q C_K H_A H_3 S_4 C_4 D_2", self.JOKER)
        G["ante_num"] = 2
        advice = analysis.play_advice(G)
        assert advice["draws"] == []
        assert "chase" not in advice["action"]["why"]

    def test_exact_win_without_jokers(self) -> None:
        # No jokers: the estimate is exact, so 300 vs 300 needed WINS.
        G = make_state("H_A H_K H_T H_5 H_4 S_4 C_4 D_9")
        flush = next(
            p for p in analysis.play_advice(G)["plays"] if p["hand"] == "Flush"
        )
        assert flush["score"] == 300 and flush["wins"]


class TestBlueSealAndEconomy:
    def test_winning_play_keeps_blue_seal_in_hand(self) -> None:
        G = make_state("H_K S_K D_K C_K H_2 S_3 D_7 C_9", chips=200)
        G["hand"]["cards"][0]["modifier"] = {"seal": "BLUE"}
        action = analysis.play_advice(G)["action"]
        assert action["tool"] == "play" and 0 not in action["cards"]
        assert "Blue Seal" in action["why"]

    def test_second_blue_seal_pick_is_vetoed(self) -> None:
        G = make_state("H_2", state="SMODS_BOOSTER_OPENED")
        sealed = card("S_9", seal="BLUE")
        G["pack"] = {"cards": [sealed]}
        assert analysis.validate_action(G, "pack", {"card": 0}) is None
        G["cards"]["cards"][0]["modifier"] = {"seal": "BLUE"}
        assert "Blue Seal" in analysis.validate_action(G, "pack", {"card": 0})
        G["jokers"]["cards"] = [joker("j_hologram", "Hologram")]
        assert analysis.validate_action(G, "pack", {"card": 0}) is None

    def test_trance_verdict_depends_on_blue_seals(self) -> None:
        trance = {"key": "c_trance", "set": "SPECTRAL", "label": "Trance"}
        assert knowledge.consumable_tag(trance, "Two Pair", 0).startswith("[GOOD]")
        assert "already own" in knowledge.consumable_tag(trance, "Two Pair", 1)

    def test_econ_ok_window(self) -> None:
        scoring = [joker("j_joker", "Joker"), joker("j_jolly", "Jolly Joker")]
        G = make_state("H_2", scoring, state="SHOP")
        assert analysis.run_status(G, [], [])["econ_ok"]
        G["ante_num"] = 4
        assert not analysis.run_status(G, [], [])["econ_ok"]
        G = make_state("H_2", scoring[:1], state="SHOP")
        assert not analysis.run_status(G, [], [])["econ_ok"]  # scoring first


class TestFableReviewFixes:
    def test_chase_never_breaks_a_made_flush(self) -> None:
        G = make_state("H_K H_5 H_4 H_3 H_2 C_J D_T S_9")
        action = analysis.play_advice(G)["action"]
        assert action["tool"] == "play" and set(action["cards"]) == {0, 1, 2, 3, 4}

    def test_no_chase_at_ante_one_boss_without_jokers(self) -> None:
        G = make_state("S_J D_Q C_K H_A H_3 S_4 C_4 D_2", boss_current=True)
        assert not any(d["chase"] for d in analysis.play_advice(G)["draws"])

    def test_strength_avoids_chains(self) -> None:
        G = make_state("H_6 S_7 D_8 C_T H_3 S_2 D_Q C_A")
        G["ante_num"] = 2
        targets = analysis.suggest_targets(G, {"key": "c_strength"})
        ranks = {G["hand"]["cards"][i]["value"]["rank"] for i in targets}
        assert len(targets) == 2 and not {"6", "7"} <= ranks

    def test_main_tag_needs_exact_hand(self) -> None:
        trio = joker("j_trio", "The Trio")
        half = joker("j_half", "Half Joker")
        assert "[OFF-PLAN]" in knowledge.joker_tag(trio, "Two Pair", 2)
        assert "[MAIN]" in knowledge.joker_tag(
            joker("j_mad", "Mad Joker"), "Two Pair", 2
        )
        assert "[OFF-PLAN]" in knowledge.joker_tag(half, "Two Pair", 2)
        assert "[MAIN]" in knowledge.joker_tag(half, "Pair", 2)

    def test_family_not_counted_as_xmult_for_two_pair(self) -> None:
        G = make_state("H_2", [joker("j_family", "The Family")], state="SHOP")
        assert analysis.run_status(G, [], [])["xmult_owned"] == 0

    def test_empty_discard_renders_none(self) -> None:
        sm = StrategyManager("mastery")
        G = make_state("H_K S_K H_9 S_9 D_5 C_5 H_3 S_3")
        G["ante_num"] = 2
        text = sm.render_gamestate(G, rounds=[], history=[], flags={})
        assert "Suggested discard: none: play instead" in text


class TestShopImpact:
    def _shop(self) -> dict[str, Any]:
        G = make_state(
            "H_2",
            [joker("j_jolly", "Jolly Joker"), joker("j_golden", "Golden Joker")],
            state="SHOP",
        )
        G["hand"]["cards"] = []
        G["shop"] = {
            "cards": [
                joker("j_duo", "The Duo"),
                joker("j_zany", "Zany Joker"),
                {"key": "c_uranus", "set": "PLANET", "label": "Uranus", "cost": {"buy": 3}},
                {"key": "c_mercury", "set": "PLANET", "label": "Mercury", "cost": {"buy": 3}},
            ]
        }
        return G

    def test_deltas_average_every_pair_in_the_deck(self) -> None:
        impact = analysis.shop_impact(self._shop())
        # 75 pairs (12 ranks x 6, plus 3 from the three 2s); mean card 7.52 chips:
        # (10 + 15.04) chips x (2 + 8 Jolly) mult = 250
        assert impact["hand"] == "Pair" and impact["plays"] == 75
        assert impact["score"] == 250
        assert impact["shop"][0].startswith("+250")  # The Duo doubles it
        assert impact["shop"][1].startswith("+0")  # Zany needs Three of a Kind
        assert 2 not in impact["shop"]  # Uranus levels another hand
        assert impact["shop"][3].startswith("+190")  # Mercury: 40.04 x 11 = 440
        assert impact["owned"][0] == "adds 200 per hand"  # Jolly: 250 - 25.04 x 2

    def test_face_jokers_count_face_pairs(self) -> None:
        G = self._shop()
        G["shop"]["cards"] = [joker("j_scary_face", "Scary Face")]
        # 3 of 13 ranks are faces: Scary Face (+30 chips per face) is not +0
        assert not analysis.shop_impact(G)["shop"][0].startswith("+0")

    def test_weakest_skips_econ_early(self) -> None:
        G = self._shop()
        assert analysis.shop_impact(G)["weakest"]["label"] == "Jolly Joker"
        G["ante_num"] = 5
        assert analysis.shop_impact(G)["weakest"]["label"] == "Golden Joker"

    def test_face_down_deck_cards_still_score(self) -> None:
        G = self._shop()
        base = analysis.shop_impact(G)
        for c in G["cards"]["cards"]:
            c["state"] = {"hidden": True}
        hidden = analysis.shop_impact(G)
        assert hidden["score"] == base["score"] > 0
        assert hidden["owned"] == base["owned"] and hidden["weakest"] == base["weakest"]
        assert "face-down card" not in hidden["cards"]

    def test_sell_guard(self) -> None:
        G = self._shop()  # Jolly Joker + Golden Joker, 3 slots free
        G["money"] = 4
        assert "slots are not full" in analysis.validate_action(G, "sell", {"joker": 0})
        G["jokers"]["limit"] = 2  # full: joker swaps go through swap_plan
        assert "just buy the new one" in analysis.validate_action(G, "sell", {"joker": 0})
        G["packs"] = {"cards": [{"label": "Buffoon Pack", "cost": {"buy": 4}}]}
        assert analysis.validate_action(G, "sell", {"joker": 0}) is None
        G["packs"] = {"cards": []}
        G["money"] = 0
        G["jokers"]["cards"][0] = joker("j_troubadour", "Troubadour")  # TRAP
        assert analysis.validate_action(G, "sell", {"joker": 0}) is None

    def test_swap_plan_sells_weakest_first(self) -> None:
        G = self._shop()  # owns Jolly Joker + Golden Joker; shop: The Duo, Zany
        G["money"] = 8
        for c in G["shop"]["cards"]:
            c["cost"] = {"buy": 8}
        assert analysis.swap_plan(G, "buy", {"card": 0}) is None  # slots free
        G["jokers"]["limit"] = 2
        G["jokers"]["cards"][0]["cost"] = {"sell": 1}
        plan = analysis.swap_plan(G, "buy", {"card": 0})  # The Duo is [XMULT]
        assert plan == {"sell": 0, "label": "Jolly Joker", "buy": "The Duo"}
        # Zany (+12 Mult with Three of a Kind) adds nothing to Pair: refused
        assert "would not raise" in analysis.swap_plan(G, "buy", {"card": 1})
        G["money"] = 6  # 6 + 1 < 8
        assert "not enough" in analysis.swap_plan(G, "buy", {"card": 0})

    def test_shop_render_shows_score(self) -> None:
        sm = StrategyManager("mastery")
        text = sm.render_gamestate(self._shop(), rounds=[], history=[], flags={})
        assert "TYPICAL Pair (average of the 75" in text and "SCORE +250 per hand" in text
        assert "WEAKEST:" not in text  # only named once slots are full
        G = self._shop()
        G["jokers"]["limit"] = len(G["jokers"]["cards"])
        text = sm.render_gamestate(G, rounds=[], history=[], flags={})
        assert "WEAKEST: 0 Jolly Joker" in text

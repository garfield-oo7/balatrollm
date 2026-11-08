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

    def test_status_looks_one_blind_ahead(self) -> None:
        """Owner (pass 1): STATUS judges the next blind only; the boss has its own line."""
        G = make_state("H_2", state="SHOP")
        G["ante_num"] = 3
        G["blinds"] = {
            "small": {"status": "DEFEATED", "score": 2000},
            "big": {"status": "UPCOMING", "score": 3000, "name": "Big Blind"},
            "boss": {"status": "UPCOMING", "score": 4000, "name": "The Flint"},
        }
        # Power comes from the deck, jokers and levels: big past scores do not help
        history = [{"method": "play", "score": 100000}] * 3
        S = analysis.run_status(G, [], history)
        assert S["status"] == "SHORT" and S["hands_needed"] > 4
        assert S["next_kind"] == "big"
        G["hands"]["Pair"].update(chips=600, mult=20, level=20)
        S = analysis.run_status(G, [], [])
        assert S["status"] == "COMFORTABLE" and S["hands_needed"] == 1
        # The Flint halves the base: the boss estimate is lower than the normal one
        assert S["boss_per_hand"] < S["per_hand"]
        assert S["boss_check"]["name"] == "The Flint"

    def test_boss_counts_only_when_it_is_next(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["blinds"]["small"]["status"] = "DEFEATED"
        G["blinds"]["big"]["status"] = "UPCOMING"
        G["blinds"]["boss"].update(name="The Needle", score=10_000_000)
        # an easy Big Blind: 2 hands at the K5 low per hand
        G["blinds"]["big"]["score"] = 2 * analysis.power_check(G)["per_hand_low"]
        analysis._CACHE.clear()
        S = analysis.run_status(G, [], [])
        assert S["status"] == "COMFORTABLE"
        assert not S["boss_check"]["ok"] and S["boss_check"]["allowed"] == 1
        G["blinds"]["big"]["status"] = "DEFEATED"
        assert analysis.run_status(G, [], [])["status"] == "SHORT"

    def test_safety_net_never_on_a_boss(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["blinds"]["small"]["status"] = "DEFEATED"
        G["blinds"]["big"].update(status="UPCOMING", score=10_000_000)
        easy = [{"hands_left": 2}, {"hands_left": 3}]
        # C2 (pass 3): the safety net never lifts SHORT ...
        S = analysis.run_status(G, easy, [])
        assert S["status"] == "SHORT" and not S["safety_net"]
        # ... it lifts THIN: a Big Blind that takes all 4 hands at the low per hand
        G["blinds"]["big"]["score"] = 4 * analysis.power_check(G)["per_hand_low"]
        S = analysis.run_status(G, easy, [])
        assert S["status"] == "COMFORTABLE" and S["safety_net"]
        assert analysis.run_status(G, [{"hands_left": 1}, {"hands_left": 3}], [])["status"] == "THIN"
        G["blinds"]["big"]["score"] = 10_000_000
        G["blinds"]["big"]["status"] = "DEFEATED"
        G["blinds"]["boss"]["score"] = 10_000_000
        assert analysis.run_status(G, easy, [])["status"] == "SHORT"

    def test_last_blind_won_on_its_final_hand_is_thin(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["blinds"]["small"]["status"] = "DEFEATED"
        G["blinds"]["big"]["status"] = "UPCOMING"
        G["hands"]["Pair"].update(chips=600, mult=20, level=20)
        assert analysis.run_status(G, [{"hands_left": 0}], [])["status"] == "THIN"

    def test_needle_boss_line_always_shown(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["blinds"]["small"]["status"] = "SELECT"
        G["blinds"]["boss"].update(name="The Needle", score=300)
        G["hands"]["Pair"].update(chips=600, mult=20, level=20)
        text = StrategyManager("mastery").render_gamestate(G, rounds=[], history=[], flags={})
        assert "BOSS CHECK: The Needle" in text and "ONE hand only" in text
        G["blinds"]["boss"]["name"] = "The Needle"
        assert analysis.run_status(G, [], [])["boss_hands_allowed"] == 1
        assert "spend money" in analysis.boss_impact({**G, "blinds": {"boss": {"name": "The Ox"}}})["prep"]

    def test_reroll_money_lines(self) -> None:
        """P2-9: from Ante 4, $25 while COMFORTABLE, $10 while THIN/SHORT."""
        G = make_state("H_2", state="SHOP")
        G["ante_num"] = 4
        G["round"]["reroll_cost"] = 5
        G["hands"]["Pair"].update(chips=500, mult=50, level=20)  # COMFORTABLE
        assert analysis.run_status(G, [], [])["status"] == "COMFORTABLE"
        G["money"] = 29
        assert "keep $25" in analysis.validate_action(G, "reroll", {})
        G["money"] = 30
        assert analysis.validate_action(G, "reroll", {}) is None
        G["hands"]["Pair"].update(chips=5, mult=1, level=1)
        G["blinds"]["small"]["score"] = 10_000_000
        assert analysis.run_status(G, [], [])["status"] == "SHORT"
        G["money"] = 14
        assert "at least $10" in analysis.validate_action(G, "reroll", {})
        G["money"] = 15
        assert analysis.validate_action(G, "reroll", {}) is None

    def test_reroll_line_ante_2_3(self) -> None:
        """Ante 2-3: $25 only while COMFORTABLE with a defining joker; else $10."""
        G = make_state("H_2", state="SHOP")
        G["ante_num"] = 2
        G["round"]["reroll_cost"] = 5
        G["money"] = 20
        G["hands"]["Pair"].update(chips=500, mult=50, level=20)
        assert analysis.validate_action(G, "reroll", {}) is None  # no defining joker
        G["luna"] = {"main_commit": {"hand": "Pair", "trigger": "The Duo", "ante": 1, "round": 2}}
        assert analysis.main_hand_plan(G).get("commit")
        assert "keep $25" in analysis.validate_action(G, "reroll", {})

    def test_first_shop_prefers_buffoon_over_a_zero_joker(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["money"] = 9
        G["shop"] = {"cards": [{**joker("j_ride_the_bus", "Ride the Bus", "(Currently +0 Mult)"), "cost": {"buy": 6}}]}
        G["packs"] = {"cards": [{"key": "p_buffoon_normal_1", "label": "Buffoon Pack", "set": "BOOSTER", "cost": {"buy": 4}}]}
        assert "Buffoon" in analysis.validate_action(G, "buy", {"card": 0})
        G["round_num"] = 2
        assert analysis.validate_action(G, "buy", {"card": 0}) is None
        # P2-6: the bot's first-shop flag wins over ante/round (whole first visit)
        G["luna"] = {"first_shop": True}
        assert "Buffoon" in analysis.validate_action(G, "buy", {"card": 0})
        G["luna"] = {"first_shop": False}
        G["round_num"] = 1
        assert analysis.validate_action(G, "buy", {"card": 0}) is None

    def test_first_shop_supernova_exception(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["luna"] = {"first_shop": True}
        G["shop"] = {"cards": [{**joker("j_supernova", "Supernova"), "cost": {"buy": 5}}]}
        G["packs"] = {"cards": [{"key": "p_buffoon_normal_1", "label": "Buffoon Pack", "set": "BOOSTER", "cost": {"buy": 4}}]}
        G["money"] = 8  # cannot afford both: Supernova first
        assert analysis.validate_action(G, "buy", {"card": 0}) is None
        G["money"] = 9  # can afford both: pack first
        assert "Buffoon" in analysis.validate_action(G, "buy", {"card": 0})

    def test_reserve_by_ante_and_status(self) -> None:
        G = make_state("H_2", state="SHOP")
        assert analysis.reserve(G) == 0
        G["ante_num"] = 2
        assert analysis.reserve(G, "COMFORTABLE") == 10
        assert analysis.reserve(G, "THIN") == 0 and analysis.reserve(G, "SHORT") == 0
        G["ante_num"] = 3
        assert analysis.reserve(G, "SHORT") == 10
        assert analysis.reserve(G, "SHORT", boss_short=True) == 0
        G["ante_num"] = 5
        assert analysis.reserve(G, "COMFORTABLE") == 0

    def test_locked_shop_refuses_buy_and_reroll(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["ante_num"] = 5
        G["money"] = 40
        G["luna"] = {"shop_locked": True}
        G["shop"] = {"cards": [{**joker("j_joker", "Joker"), "cost": {"buy": 2}}]}
        assert "next_round" in analysis.validate_action(G, "buy", {"card": 0})
        assert "next_round" in analysis.validate_action(G, "reroll", {})
        G["luna"] = {}
        assert analysis.validate_action(G, "buy", {"card": 0}) is None

    def test_buffoon_with_full_slots_needs_25_left(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["ante_num"] = 3
        G["jokers"] = {"count": 5, "limit": 5, "cards": [joker("j_joker", "Joker")] * 5}
        G["packs"] = {"cards": [{"key": "p_buffoon_normal_1", "label": "Buffoon Pack", "set": "BOOSTER", "cost": {"buy": 4}}]}
        G["money"] = 28
        assert "$25" in analysis.validate_action(G, "buy", {"pack": 0})
        G["money"] = 29
        assert analysis.validate_action(G, "buy", {"pack": 0}) is None

    def test_score_spendable_never_below_spendable(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["ante_num"] = 2
        G["money"] = 14
        S = analysis.run_status(G, [], [])
        assert S["spendable"] == 14 and S["score_spendable"] == 14

    def test_fortune_teller_baseball_and_flint_rounding(self) -> None:
        teller = joker("j_fortune_teller", "Fortune Teller", "+1 Mult per Tarot card used this run (Currently +3)")
        G = make_state("H_K S_K D_2 C_3 D_5 C_7 S_8 H_9", [teller])
        hand = G["hand"]["cards"]
        est = analysis.estimate_play(G, hand[:2], hand[2:])
        assert est["unknown"] == [] and est["mult"] == 5  # Pair x2 + 3
        base = analysis.estimate_play(make_state("H_K S_K D_2 C_3 D_5 C_7 S_8 H_9", [joker("j_cloud_9", "Cloud 9")]), hand[:2], hand[2:])
        G = make_state(
            "H_K S_K D_2 C_3 D_5 C_7 S_8 H_9",
            [joker("j_cloud_9", "Cloud 9"), joker("j_baseball", "Baseball Card")],
        )
        est = analysis.estimate_play(G, hand[:2], hand[2:])
        assert est["unknown"] == [] and est["score"] == int(base["score"] * 1.5)
        G = make_state("H_K S_K S_7 D_2 C_3 D_5 C_8 H_9", boss="The Flint", boss_current=True)
        G["hands"]["Three of a Kind"].update(chips=30, mult=3)
        assert analysis._hand_base(G, "Three of a Kind", "The Flint") == (15, 2)

    def test_the_water_lowers_the_score(self) -> None:
        """No discards against The Water: fewer dug hands, a lower estimate."""
        G = make_state("H_2", [joker("j_four_fingers", "Four Fingers")], state="SHOP")
        G["blinds"]["boss"]["name"] = "The Water"
        power = analysis.power_check(G)
        assert power["boss_per_hand"] < power["per_hand"]

    def test_reroll_cap_and_stencil(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["ante_num"] = 4
        G["money"] = 60
        G["hands"]["Pair"].update(chips=5, mult=1, level=1)
        G["blinds"]["small"]["score"] = 10_000_000  # SHORT: $10 line
        G["money"] = 20  # leaves $15 < $25: the cap counts
        assert analysis.validate_action(G, "reroll", {}, shop_rerolls=5) is None
        assert "at most 6" in analysis.validate_action(G, "reroll", {}, shop_rerolls=6)
        G["ante_num"] = 5
        assert analysis.validate_action(G, "reroll", {}, shop_rerolls=9) is None
        assert "at most 10" in analysis.validate_action(G, "reroll", {}, shop_rerolls=10)
        G["money"] = 60  # leaves $55: no cap, only the runaway guard
        assert analysis.validate_action(G, "reroll", {}, shop_rerolls=29) is None
        assert "too many" in analysis.validate_action(G, "reroll", {}, shop_rerolls=30)
        G["ante_num"] = 1
        assert "Ante 1" in analysis.validate_action(G, "reroll", {}, shop_rerolls=0)
        G["jokers"] = {"count": 5, "limit": 5, "cards": [joker("j_joker", "Joker")] * 5}
        G["shop"] = {"cards": [{**joker("j_stencil", "Joker Stencil"), "cost": {"buy": 8}}]}
        assert "Stencil" in analysis.validate_action(G, "buy", {"card": 0})

    def test_power_check_inside_the_psychic_is_not_zero(self) -> None:
        G = make_state("H_2", state="SELECTING_HAND")
        for k in ("small", "big"):
            G["blinds"][k]["status"] = "DEFEATED"
        G["blinds"]["boss"].update(name="The Psychic", status="CURRENT")
        power = analysis.power_check(G)
        assert power["typical"] > 0 and power["boss_per_hand"] > 0


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


class TestPaddingKeepsHandType:
    """Pass 1 Seeds Q and S: the suggested 'Pair' padded into a Full House /
    Two Pair / Four of a Kind with the lowest cards."""

    def _flags(self, G: dict[str, Any]) -> dict[str, bool]:
        return analysis._classify_flags(G)

    def test_filler_never_pairs_or_trips_the_play(self) -> None:
        # Seed Q hand 1: 10s + 2 2 2 = Full House
        G = make_state("H_T C_T S_2 C_2 D_2 H_9 S_8 D_6")
        hand = [analysis._norm(c) for c in G["hand"]["cards"]]
        plan = analysis.main_hand_plan(G)
        fill = analysis._filler(G, hand, [0, 1], plan, 3)
        played = [hand[i] for i in [0, 1, *fill]]
        assert analysis.classify(played, **self._flags(G))[0] == "Pair"
        assert len(fill) == 3

    def test_filler_never_makes_a_flush(self) -> None:
        G = make_state("H_K D_K H_2 H_3 H_4 C_9 S_7 H_6")
        hand = [analysis._norm(c) for c in G["hand"]["cards"]]
        plan = {**analysis.main_hand_plan(G), "suit": None}
        fill = analysis._filler(G, hand, [0, 1], plan, 3)
        played = [hand[i] for i in [0, 1, *fill]]
        assert analysis.classify(played, **self._flags(G))[0] == "Pair"

    def test_suggested_pair_stays_a_pair(self) -> None:
        # Seed S hand 2: 3 3 + 3 3 6 = Four of a Kind; keep the Pair of 3s alone
        G = make_state("H_3 S_3 C_3 D_3 H_6 S_Q D_9 C_7", hands_left=2)
        G["blinds"]["small"]["score"] = 100_000
        advice = analysis.play_advice(G)
        if advice["action"]["tool"] == "play":
            cards = [analysis._norm(G["hand"]["cards"][i]) for i in advice["action"]["cards"]]
            best = advice["plays"][0]["hand"]
            assert analysis.classify(cards, **self._flags(G))[0] == best

    def test_baron_keeps_kings_out_of_the_filler(self) -> None:
        G = make_state("H_9 C_9 S_K D_2 H_3 C_K S_5 D_7", [joker("j_baron", "Baron")])
        hand = [analysis._norm(c) for c in G["hand"]["cards"]]
        fill = analysis._filler(G, hand, [0, 1], analysis.main_hand_plan(G), 3)
        assert all(hand[i]["rank"] != "K" for i in fill)


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

    def test_discard_is_never_refused(self) -> None:
        """Owner (pass 1): the harness never refuses a discard; WINS is advice."""
        G = make_state("H_A H_K H_T H_5 H_4 S_4 C_4 D_9", chips=200)
        assert analysis.validate_action(G, "discard", {"cards": [0, 5]}) is None
        assert analysis.validate_action(G, "discard", {"cards": [5, 6]}) is None
        G["round"]["discards_left"] = 0
        assert analysis.validate_action(G, "discard", {"cards": [5, 6]})
        assert analysis.validate_action(G, "play", {"cards": [0, 1, 2, 3, 4, 5]})


class TestPlanAndStatus:
    def test_default_main_hand_is_two_pair(self) -> None:
        plan = analysis.main_hand_plan(make_state("H_2"))
        assert plan["hand"] == "Pair"
        assert plan["open"] and plan["draw_kinds"] == {"Flush", "Straight"}

    def test_open_until_a_joker_calls(self) -> None:
        """Owner (pass 1): no "Pair from hand 1"; MAIN_HAND stays OPEN with no deadline."""
        G = make_state("H_2")
        G["ante_num"] = 3
        plan = analysis.main_hand_plan(G)
        assert plan["open"] and plan["hand"] == "Pair" and plan["commit"] is None
        G["hands"]["Flush"].update(level=3)
        assert analysis.main_hand_plan(G)["hand"] == "Flush"  # leaning = levelled most
        G["jokers"]["cards"] = [joker("j_trousers", "Spare Trousers")]
        plan = analysis.main_hand_plan(G)
        assert not plan["open"] and plan["hand"] == "Two Pair" and "Spare Trousers" in plan["reason"]

    def test_commit_is_sticky_against_joker_loss_not_new_jokers(self) -> None:
        G = make_state("H_2", [joker("j_trousers", "Spare Trousers")])
        commit = analysis.main_commit(G, None)
        G["jokers"]["cards"] = []  # Trousers sold
        G["luna"] = {"main_commit": commit}
        assert analysis.main_hand_plan(G)["hand"] == "Two Pair"
        G["jokers"]["cards"] = [joker("j_baron", "Baron")]  # owner's Mars -> Baron run
        assert analysis.main_hand_plan(G)["hand"] == "Pair"

    def test_card_sharp_commits_to_the_leaning_hand(self) -> None:
        G = make_state("H_2", [joker("j_card_sharp", "Card Sharp")])
        G["hands"]["Two Pair"].update(level=2)
        assert analysis.main_hand_plan(G)["hand"] == "Two Pair"

    def test_open_main_hand_has_no_off_plan_tags(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["shop"] = {"cards": [{**joker("j_trousers", "Spare Trousers"), "cost": {"buy": 6}}]}
        text = StrategyManager("mastery").render_gamestate(G, rounds=[], history=[], flags={})
        line = next(x for x in text.splitlines() if "Spare Trousers $6" in x)
        assert "OFF-PLAN" not in line and "MAIN_HAND: OPEN" in text

    def test_flush_engine_switches_to_flush(self) -> None:
        G = make_state("H_2", [joker("j_four_fingers", "Four Fingers")])
        assert analysis.main_hand_plan(G)["hand"] == "Flush"

    def test_flush_jokers_without_pair_jokers(self) -> None:
        # Flush only with Smeared Joker / Four Fingers (owner); flush-joker cores,
        # a lone Tribe or mixed-suit Mult jokers stay on Pair
        jokers = [joker("j_droll", "Droll Joker"), joker("j_crafty", "Crafty Joker")]
        assert analysis.main_hand_plan(make_state("H_2", jokers))["hand"] == "Pair"
        mixed = [joker("j_greedy_joker", "Greedy Joker"), joker("j_gluttenous_joker", "Gluttonous Joker")]
        assert analysis.main_hand_plan(make_state("H_2", mixed))["hand"] == "Pair"
        # owner F5: The Tribe supports a Flush build
        assert analysis.main_hand_plan(make_state("H_2", [joker("j_tribe", "The Tribe")]))["hand"] == "Flush"
        jokers.append(joker("j_four_fingers", "Four Fingers"))
        assert analysis.main_hand_plan(make_state("H_2", jokers))["hand"] == "Flush"

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

    def test_flush_draw_not_chased_after_ante_one(self) -> None:
        """CHASE (keep discarding toward a draw) stays an Ante 1 rule; later the
        draw is only listed while MAIN_HAND is OPEN."""
        G = make_state("S_K H_9 H_7 D_7 H_4 C_Q H_2 S_3")
        G["ante_num"] = 3
        advice = analysis.play_advice(G)
        assert not any(d["chase"] for d in advice["draws"])
        assert "chase" not in advice["action"]["why"].lower()

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
        jokers = [joker("j_droll", "Droll Joker"), joker("j_smeared", "Smeared Joker")]
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
        G["ante_num"] = 5  # late: only while you own no xMult joker
        assert analysis.grows_xmult(G, holo).endswith("SOURCE PRESENT")
        G["jokers"]["cards"].append(joker("j_duo", "The Duo"))
        assert "too late to grow" in analysis.grows_xmult(G, holo)
        assert analysis.grows_xmult(G, joker("j_joker", "Joker")) == ""

    def test_magician_is_good(self) -> None:
        magician = {"key": "c_magician", "set": "TAROT", "label": "The Magician"}
        assert knowledge.consumable_tag(magician, "Pair").startswith("[GOOD]")

    def test_hermit_has_no_money_cap(self) -> None:
        hermit = {"key": "c_hermit", "set": "TAROT", "label": "The Hermit"}
        assert knowledge.consumable_tag(hermit, "Pair").startswith("[GOOD]")
        assert knowledge.consumable_tag(hermit, "Pair", 0, 52).startswith("[GOOD]")

    def test_constellation_feeds_on_any_planet(self) -> None:
        venus = {"key": "c_venus", "set": "PLANET", "label": "Venus"}
        assert "[FEED]" not in knowledge.consumable_tag(venus, "Pair")
        assert knowledge.consumable_tag(venus, "Pair", 0, 52, True).startswith("[FEED]")
        priestess = {"key": "c_high_priestess", "set": "TAROT", "label": "The High Priestess"}
        assert "Constellation" in knowledge.consumable_tag(priestess, "Pair", 0, 52, True)

    def test_magic_trick_only_with_hologram(self) -> None:
        trick = {"key": "v_magic_trick", "set": "VOUCHER", "label": "Magic Trick"}
        assert knowledge.voucher_tag(trick).startswith("[NEVER]")
        assert knowledge.voucher_tag(trick, True).startswith("[GOOD]")

    def test_loyalty_card_is_a_trap(self) -> None:
        loyalty = joker("j_loyalty_card", "Loyalty Card")
        assert "[TRAP]" in knowledge.joker_tag(loyalty, "Pair", 1)

    def test_misprint_and_bloodstone_count_their_average_in_the_shop(self) -> None:
        G = make_state("H_K H_K S_2 D_3 C_5 D_7 C_8 S_9", [joker("j_misprint", "Misprint")])
        hand = G["hand"]["cards"]
        floor = analysis.estimate_play(G, hand[:2], hand[2:])["score"]
        shop = analysis.estimate_play(G, hand[:2], hand[2:], expected=True)["score"]
        assert shop > floor
        G = make_state("H_K H_K S_2 D_3 C_5 D_7 C_8 S_9", [joker("j_bloodstone", "Bloodstone")])
        hand = G["hand"]["cards"]
        floor = analysis.estimate_play(G, hand[:2], hand[2:])["score"]
        avg = analysis.estimate_play(G, hand[:2], hand[2:], expected=True)["score"]
        assert avg > floor
        G["jokers"]["cards"].append(joker("j_oops", "Oops! All 6s"))
        oops = analysis.estimate_play(G, hand[:2], hand[2:], expected=True)["score"]
        assert oops > avg

    def test_mail_in_rank_is_discarded_first(self) -> None:
        mail = joker(
            "j_mail",
            "Mail-In Rebate",
            "Earn $5 for each discarded Jack, rank changes every round",
        )
        G = make_state("H_2 S_3 D_J C_7 D_8 C_9 S_Q H_4", [mail])
        assert analysis.mail_rank(G) == "J"
        plan = analysis.main_hand_plan(G)
        assert 2 in analysis.suggested_discard(G, plan)

    def test_square_joker_pads_the_play_to_four_cards(self) -> None:
        G = make_state(
            "H_K S_K D_2 C_3 D_5 C_7 S_8 H_9",
            [joker("j_square", "Square Joker", "+0 Chips")],
            discards_left=0,
        )
        action = analysis.play_advice(G)["action"]
        assert action["tool"] == "play" and len(action["cards"]) == 4
        assert {0, 1} <= set(action["cards"])

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
        assert not any("scoring jokers" in t for t in texts)  # owner C4
        assert any("XMULT" in t for t in texts) and any("SCALE" in t for t in texts)
        assert "fill empty joker slots" not in status["priority"]

    def test_pair_boss_impact(self) -> None:
        G = make_state("H_2", boss="The Eye")
        assert "AFFECTS MAIN_HAND" in analysis.boss_impact(G)["impact"]

    def test_power_check_ignores_recent_scores(self) -> None:
        G = make_state("H_2", state="SHOP")
        G["blinds"]["small"]["status"] = "DEFEATED"
        G["blinds"]["big"]["status"] = "SELECT"
        G["hands"]["Pair"].update(chips=200, mult=10, level=10)
        low = [{"method": "play", "score": 100}] * 3
        status = analysis.run_status(G, [], low)
        assert status["status"] == "COMFORTABLE"  # junk past hands do not count

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
        assert "MAIN_HAND: OPEN (leaning Pair)" in text and "GOALS for Ante 1" in text
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
        assert not any(d["chase"] for d in advice["draws"])
        assert "chase" not in advice["action"]["why"].lower()

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
        assert knowledge.consumable_tag(trance, "Pair", 0, 46).startswith("[GOOD]")
        assert "Immolate" in knowledge.consumable_tag(trance, "Pair", 0, 52)

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
        # P1: the Flush is on pace but does not win: dig with the other cards,
        # never with the Flush's own cards
        assert action["tool"] == "discard" and not set(action["cards"]) & {0, 1, 2, 3, 4}
        G["round"]["discards_left"] = 0
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

    def test_deltas_come_from_dealt_hands(self) -> None:
        """P2-1: SCORE = change of the mean best play over hands dealt from the deck."""
        impact = analysis.shop_impact(self._shop())
        assert impact["plays"] == analysis.SHOP_SAMPLES and impact["score"] > 0
        duo = int(impact["shop"][0].split()[0].replace(",", ""))
        zany = int(impact["shop"][1].split()[0].replace(",", ""))
        assert duo > zany >= 0  # The Duo X2 on any Pair; Zany only on Three of a Kind
        assert 2 not in impact["shop"]  # Uranus levels another hand
        assert impact["shop"][3].startswith("+")  # Mercury levels the leaning Pair
        assert int(impact["owned"][0].split()[1].replace(",", "")) > 0  # Jolly adds

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

    def test_sell_unwanted_zero_joker_from_a_free_slot(self) -> None:
        """F7: with free slots, a joker that adds nothing now may be sold."""
        G = self._shop()
        G["jokers"]["cards"][0] = joker("j_chaos", "Chaos the Clown")  # adds no score
        G["money"] = 4
        assert analysis.validate_action(G, "sell", {"joker": 0}) is None
        G["jokers"]["cards"][0] = joker("j_jolly", "Jolly Joker")  # Pair: adds
        assert "slots are not full" in analysis.validate_action(G, "sell", {"joker": 0})
        G["jokers"]["cards"][1] = joker("j_golden", "Golden Joker")  # ECON: kept
        assert "slots are not full" in analysis.validate_action(G, "sell", {"joker": 1})

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
        assert "TYPICAL: your best play scores about" in text and "SCORE +" in text
        assert "WEAKEST:" not in text  # only named once slots are full
        G = self._shop()
        G["jokers"]["limit"] = len(G["jokers"]["cards"])
        text = sm.render_gamestate(G, rounds=[], history=[], flags={})
        assert "WEAKEST: 0 Jolly Joker" in text


def blind_select(boss: str, on_deck: str = "small", **kw: Any) -> dict[str, Any]:
    """BLIND_SELECT state with Director's Cut owned and $20."""
    G = make_state("H_2", state="BLIND_SELECT", boss=boss, **kw)
    G["hand"]["cards"] = []
    order = ["small", "big", "boss"]
    for i, key in enumerate(order):
        here = order.index(on_deck)
        G["blinds"][key]["status"] = (
            "DEFEATED" if i < here else "SELECT" if i == here else "UPCOMING"
        )
    G["money"] = 20
    G["used_vouchers"] = {"v_directors_cut": ""}
    G["round"]["boss_rerolled"] = False
    return G


class TestBossReroll:
    @pytest.mark.parametrize("boss", ["Violet Vessel", "The Wall", "The Needle"])
    def test_always_reroll_bosses(self, boss: str) -> None:
        assert analysis.boss_reroll_reason(blind_select(boss)) is not None

    @pytest.mark.parametrize("boss", ["The Eye", "The Mouth", "The Psychic"])
    def test_bosses_that_shut_off_a_pair_main_hand(self, boss: str) -> None:
        G = blind_select(boss)
        assert analysis.main_hand_plan(G)["hand"] == "Pair"
        assert analysis.boss_reroll_reason(G) is not None

    def test_psychic_kept_for_a_five_card_main_hand(self) -> None:
        G = blind_select("The Psychic")
        G["jokers"] = {
            "count": 1,
            "limit": 5,
            "cards": [joker("j_smeared", "Smeared Joker")],
        }
        assert analysis.main_hand_plan(G)["hand"] == "Flush"
        assert analysis.boss_reroll_reason(G) is None

    def test_harmless_boss_is_kept(self) -> None:
        assert analysis.boss_reroll_reason(blind_select("The Hook")) is None

    def _flint_on_deck(self) -> dict[str, Any]:
        """The Flint halves the score: pick a target only a neutral boss allows."""
        G = blind_select("The Flint", on_deck="boss")
        power = analysis.power_check(G)
        assert power["boss_per_hand_low"] < power["per_hand_low"]
        G["blinds"]["boss"]["score"] = power["per_hand_low"] * 3  # K5: the trigger reads the low value
        return G

    def test_strength_check_only_when_boss_is_on_deck(self) -> None:
        on_deck = self._flint_on_deck()
        reason = analysis.boss_reroll_reason(on_deck)
        assert reason is not None and "hands" in reason
        early = self._flint_on_deck()
        early["blinds"]["big"]["status"] = "SELECT"
        early["blinds"]["boss"]["status"] = "UPCOMING"
        assert analysis.boss_reroll_reason(early) is None

    def test_too_weak_build_does_not_reroll(self) -> None:
        """A build too weak for ANY boss keeps the boss (Retcon would drain money)."""
        G = blind_select("The Hook", on_deck="boss")
        G["used_vouchers"] = {"v_directors_cut": "", "v_retcon": ""}
        G["blinds"]["boss"]["score"] = 10_000_000
        assert analysis.boss_reroll_reason(G) is None

    def test_strong_build_keeps_boss_on_deck(self) -> None:
        G = blind_select("The Hook", on_deck="boss")
        G["blinds"]["boss"]["score"] = 1
        assert analysis.boss_reroll_reason(G) is None

    def test_not_available_without_voucher_money_or_after_use(self) -> None:
        G = blind_select("The Wall")
        G["used_vouchers"] = {}
        assert analysis.boss_reroll_reason(G) is None
        G = blind_select("The Wall")
        G["money"] = 9
        assert analysis.boss_reroll_reason(G) is None
        G = blind_select("The Wall")
        G["round"]["boss_rerolled"] = True
        assert analysis.boss_reroll_reason(G) is None
        # Retcon ignores the once-per-ante flag
        G["used_vouchers"] = {"v_directors_cut": "", "v_retcon": ""}
        assert analysis.boss_reroll_reason(G) is not None

    def test_validate_reroll_boss(self) -> None:
        G = blind_select("The Hook")
        assert analysis.validate_action(G, "reroll_boss", {}) is None
        G["round"]["boss_rerolled"] = True
        assert "refused" in (analysis.validate_action(G, "reroll_boss", {}) or "")
        shop = blind_select("The Hook")
        shop["state"] = "SHOP"
        assert analysis.validate_action(shop, "reroll_boss", {}) is not None

    def test_vouchers_are_insurance_buys(self) -> None:
        for name in ("Director's Cut", "Retcon"):
            verdict, hint = knowledge.VOUCHERS[name]
            assert verdict == "BUY"
            assert "insurance" in hint


ANCIENT_HEARTS = "Each played card with Heart suit gives X1.5 Mult when scored, suit changes at end of round"


class TestSuitJokers:
    """Pass 1 Seed M: Ancient Joker (Hearts) was invisible; the advice discarded Hearts."""

    def _seed_m(self) -> dict[str, Any]:
        G = make_state(
            "H_6 C_5 H_A H_T H_9 C_8 D_8 C_T",
            [joker("j_ancient", "Ancient Joker", ANCIENT_HEARTS)],
        )
        G["ante_num"] = 2
        return G

    def test_ancient_joker_scores_its_suit(self) -> None:
        G = self._seed_m()
        hand = G["hand"]["cards"]
        hearts = analysis.estimate_play(G, [hand[4]], [])  # 9 of Hearts high card
        clubs = analysis.estimate_play(G, [hand[5]], [])  # 8 of Clubs high card
        assert analysis.ancient_suit(G) == "H"
        assert hearts["mult"] == 1.5 and clubs["mult"] == 1

    def test_discard_keeps_the_paid_suit(self) -> None:
        G = self._seed_m()
        advice = analysis.play_advice(G)
        hand = G["hand"]["cards"]
        assert all(hand[i]["value"]["suit"] != "H" for i in advice["discard"])
        assert any(d["kind"] == "Flush" and d.get("suit") == "H" for d in advice["draws"])

    def test_round_line_names_the_suit(self) -> None:
        sm = StrategyManager("mastery")
        text = sm.render_gamestate(self._seed_m(), rounds=[], history=[], flags={})
        assert "Ancient Joker: Hearts this round, X1.5 Mult per Heart scored" in text


class TestPass2Planets:
    def test_open_planets_are_ok_and_satellite_feeds(self) -> None:
        tag = knowledge.consumable_tag({"label": "Venus", "set": "PLANET"}, "Pair", ok_hands=["Three of a Kind"])
        assert tag.startswith("[OK]")
        assert knowledge.consumable_tag({"label": "Venus", "set": "PLANET"}, "Pair").startswith("levels")
        G = make_state("H_2", [joker("j_satellite", "Satellite")], state="SHOP")
        assert analysis.run_status(G, [], [])["constellation"]

    def test_committed_hand_has_no_ok_planets(self) -> None:
        G = make_state("H_2", [joker("j_trousers", "Spare Trousers")], state="SHOP")
        assert analysis.run_status(G, [], [])["ok_hands"] is None

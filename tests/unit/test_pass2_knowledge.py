"""Pass 2: knowledge tags (V1-V8), FEED tags, W4/W5 shop notes, F4 swap."""

from typing import Any

from balatrollm import analysis, knowledge
from balatrollm.strategy import StrategyManager

from .test_analysis import joker, make_state


def J(key: str, label: str) -> dict[str, Any]:
    return {"key": key, "label": label, "set": "JOKER", "value": {"effect": ""}}


def test_v1_idol_is_util_tier_c() -> None:
    assert knowledge.joker_tag(J("j_idol", "The Idol"), "Pair", 1).startswith("[UTIL] tier C")


def test_v4_acrobat_last_hand_only() -> None:
    assert "LAST hand" in knowledge.joker_tag(J("j_acrobat", "Acrobat"), "Pair", 3)


def test_v5_supernova_s_early_a_late() -> None:
    assert "tier S" in knowledge.joker_tag(J("j_supernova", "Supernova"), "Pair", 1)
    assert "tier A" in knowledge.joker_tag(J("j_supernova", "Supernova"), "Pair", 5)


def test_v8_blackboard_tag_and_not_xmult_owned() -> None:
    tag = knowledge.joker_tag(J("j_blackboard", "Blackboard"), "Pair", 2)
    assert tag.startswith("[XMULT IF ALL HELD")
    G = make_state("H_2", [joker("j_blackboard", "Blackboard")], state="SHOP")
    assert analysis.run_status(G, [], [])["xmult_owned"] == 0


def test_suit_jokers_not_after_ante_2() -> None:
    assert "NOT AFTER ANTE 2" not in knowledge.joker_tag(J("j_greedy_joker", "Greedy Joker"), "Pair", 2)
    assert "NOT AFTER ANTE 2" in knowledge.joker_tag(J("j_greedy_joker", "Greedy Joker"), "Pair", 3)


def test_feed_tags_for_vampire_and_blackboard() -> None:
    hiero = {"key": "c_heirophant", "label": "The Hierophant", "set": "TAROT"}
    moon = {"key": "c_moon", "label": "The Moon", "set": "TAROT"}
    assert "[FEED Vampire]" in knowledge.consumable_tag(hiero, "Pair", owned=["j_vampire"])
    assert "[FEED Vampire]" not in knowledge.consumable_tag(hiero, "Pair", owned=[])
    assert "[FEED Blackboard]" in knowledge.consumable_tag(moon, "Pair", owned=["j_blackboard"])


def _pack_state(jokers: list[dict[str, Any]], pack: str) -> dict[str, Any]:
    G = make_state("H_2", jokers, state="SHOP")
    G["packs"] = {"cards": [{"key": "p_x", "label": pack, "set": "BOOSTER", "cost": {"buy": 4}}]}
    return G


def test_v3_hologram_standard_pack_feed() -> None:
    G = _pack_state([joker("j_hologram", "Hologram", "(Currently X1)")], "Standard Pack")
    text = StrategyManager("mastery").render_gamestate(G, rounds=[], history=[], flags={})
    assert "[FEED Hologram]" in text


def test_v2_vampire_arcana_pack_feed() -> None:
    G = _pack_state([joker("j_vampire", "Vampire", "(Currently X1)")], "Arcana Pack")
    text = StrategyManager("mastery").render_gamestate(G, rounds=[], history=[], flags={})
    assert "[FEED Vampire]" in text


def _shop_with(card: dict[str, Any], owned: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    G = make_state("H_2", owned or [joker("j_jolly", "Jolly Joker")], state="SHOP")
    G["shop"] = {"cards": [{**card, "cost": {"buy": 6}}]}
    return G


def test_v4_acrobat_shop_line() -> None:
    impact = analysis.shop_impact(_shop_with(joker("j_acrobat", "Acrobat")))
    assert "LAST hand of a blind only" in impact["shop"][0]


def test_w5_discard_end_jokers_show_both_cases() -> None:
    impact = analysis.shop_impact(_shop_with(joker("j_banner", "Banner")))
    assert "keep all 4 discards" in impact["shop"][0] and "after using them" in impact["shop"][0]


def test_w4_chips_sources_counted_and_shown() -> None:
    G = _shop_with(joker("j_jolly", "Jolly Joker"), [joker("j_scary_face", "Scary Face"), joker("j_jolly", "Jolly Joker")])
    assert analysis.shop_impact(G)["chips_sources"] == 1
    text = StrategyManager("mastery").render_gamestate(G, rounds=[], history=[], flags={})
    assert "CHIPS sources owned: 1" in text


def test_growing_jokers_show_the_3_round_value() -> None:
    impact = analysis.shop_impact(_shop_with(joker("j_constellation", "Constellation", "(Currently X1)")))
    assert "in 3 rounds" in impact["shop"][0]


def test_f4_growing_xmult_while_short_keeps_main_sources() -> None:
    G = make_state(
        "H_2",
        [joker("j_jolly", "Jolly Joker"), joker("j_greedy_joker", "Greedy Joker"), joker("j_scary_face", "Scary Face")],
        state="SHOP",
    )
    G["jokers"].update(limit=3, count=3)
    G["money"] = 20
    G["blinds"]["small"]["score"] = 10_000_000
    G["shop"] = {"cards": [{**joker("j_constellation", "Constellation", "(Currently X1)"), "cost": {"buy": 6}}]}
    assert analysis.run_status(G, [], [])["status"] == "SHORT"
    plan = analysis.swap_plan(G, "buy", {"card": 0})
    assert plan == {"sell": 1, "label": "Greedy Joker", "buy": "Constellation"}

"""Pass 2 step 5: play advice (P1, P2, P4-P7, V4, V8, P2-13)."""

from typing import Any

from balatrollm import analysis
from balatrollm.strategy import StrategyManager

from .test_analysis import joker, make_state


def keys(G: dict[str, Any], idx: list[int]) -> list[str]:
    return [G["hand"]["cards"][i]["key"] for i in idx]


def render(G: dict[str, Any]) -> str:
    return StrategyManager("mastery").render_gamestate(G, rounds=[], history=[], flags={})


def test_p1_dig_keeps_the_on_pace_play() -> None:
    G = make_state("S_K H_K D_2 C_3 H_5 C_7 S_8 D_9")
    G["ante_num"] = 2
    G["blinds"]["small"]["score"] = 100  # Pair of Kings (60) on pace (25), does not win
    A = analysis.play_advice(G)
    pair = next(p for p in A["plays"] if p["hand"] == "Pair")
    assert pair["reaches_pace"] and not pair["wins"]
    assert A["action"]["tool"] == "discard"
    assert not set(A["action"]["cards"]) & set(pair["cards"])


def test_p2_discard_costs_listed_and_dig_not_suggested() -> None:
    G = make_state("S_K H_K D_2 C_3 H_5 C_7 S_8 D_9", [joker("j_banner", "Banner")])
    G["ante_num"] = 2
    G["blinds"]["small"]["score"] = 100
    A = analysis.play_advice(G)
    assert any("Banner" in c for c in A["discard_costs"])
    assert A["action"]["tool"] == "play"  # shown, not suggested
    assert "Discard costs: Banner" in render(G)


def test_p2_the_house_blind_play() -> None:
    G = make_state("S_K H_K D_2 C_3 H_5 C_7 S_8 D_9", boss="The House", boss_current=True)
    for c in G["hand"]["cards"]:
        c["state"] = {"hidden": True}
    A = analysis.play_advice(G)
    assert A["blind_play"] and A["blind_play"]["n"] == 5 and A["blind_play"]["typical"] > 0
    assert "Playing 5 face-down cards blind" in render(G)
    assert A["action"]["tool"] == "discard"  # no discard-cost joker: Luna's choice, dig suggested


def test_p2_the_house_blind_play_suggested_with_discard_costs() -> None:
    G = make_state("S_K H_K D_2 C_3 H_5 C_7 S_8 D_9", [joker("j_banner", "Banner")], boss="The House", boss_current=True)
    for c in G["hand"]["cards"]:
        c["state"] = {"hidden": True}
    A = analysis.play_advice(G)
    assert A["action"]["tool"] == "play" and A["action"]["cards"] == [0, 1, 2, 3, 4]
    assert "The House" in A["action"]["why"]


def test_p4_card_sharp_marks_repeats() -> None:
    G = make_state("S_K H_K D_2 C_3 H_5 C_7 S_8 D_9", [joker("j_card_sharp", "Card Sharp")])
    G["hands"]["Pair"]["played_this_round"] = 1
    A = analysis.play_advice(G)
    assert next(p for p in A["plays"] if p["hand"] == "Pair").get("repeat")
    assert "Card Sharp: X3 for Pair" in A["repeats"]
    assert "[REPEAT: Card Sharp X3]" in render(G)


def test_p5_blue_seal_yields_to_the_best_play() -> None:
    G = make_state("S_K H_K D_2 C_3 H_5 C_7 S_8 D_9")
    G["hand"]["cards"][0]["modifier"] = {"seal": "BLUE"}
    assert "unless it is part of your best play: then play it" in render(G)


def test_p6_mail_in_line_and_discard_first() -> None:
    mail = joker("j_mail", "Mail-In Rebate", "Earn $5 for each discarded 7, rank changes every round")
    G = make_state("S_K H_K D_2 C_3 H_5 C_7 S_8 D_9", [mail])
    G["ante_num"] = 2  # no Ante 1 Flush chase
    A = analysis.play_advice(G)
    assert A["mail_rank"] == "7"
    assert "C_7" in keys(G, A["discard"])
    assert "Mail-In Rebate: discard 7s for $5 each" in render(G)


def test_p7_hack_keeps_low_cards_and_faceless_discards_faces() -> None:
    hand = [analysis._norm(c) for c in make_state("S_K H_Q D_J C_3 H_5 C_7 S_8 D_9")["hand"]["cards"]]
    plain = analysis._discard_choice(hand, set(), 3)
    hack = analysis._discard_choice(hand, set(), 3, keys=["j_hack"])
    faceless = analysis._discard_choice(hand, set(), 3, keys=["j_faceless"])
    assert {3, 4} <= set(plain) and not {3, 4} & set(hack)
    assert set(faceless) == {0, 1, 2}


def test_p7_clash_note() -> None:
    G = make_state("H_2", [joker("j_faceless", "Faceless Joker")], state="SHOP")
    assert "CLASHES with Faceless Joker" in analysis.clash_note(G, joker("j_hack", "Hack"))
    assert analysis.clash_note(G, joker("j_jolly", "Jolly Joker")) == ""


def test_v4_acrobat_round_line() -> None:
    G = make_state("S_K H_K D_2 C_3 H_5 C_7 S_8 D_9", [joker("j_acrobat", "Acrobat")])
    assert "keep a strong play for your last hand" in render(G)
    G["round"]["hands_left"] = 1
    assert "this hand: listed scores include it" in render(G)


def test_v8_blackboard_pads_with_reds() -> None:
    G = make_state("S_K C_K H_7 D_4 S_2 C_3 S_9 C_8", [joker("j_blackboard", "Blackboard")])
    pair = next(p for p in analysis.play_advice(G)["plays"] if p["hand"] == "Pair")
    assert sorted(keys(G, pair["cards"])) == ["C_K", "D_4", "H_7", "S_K"]
    assert pair["padded"] and pair["score"] >= 3 * 60


def test_v8_blackboard_discards_reds_first() -> None:
    hand = [analysis._norm(c) for c in make_state("S_2 H_9 C_3 D_8 S_K C_K H_A D_Q")["hand"]["cards"]]
    out = analysis._discard_choice(hand, {4, 5}, 4, keys=["j_blackboard"])
    assert {hand[i]["suit"] for i in out} == {"H", "D"}


def test_p2_13_blueprint_left_of_the_hand_defining_joker() -> None:
    G = make_state(
        "H_2",
        [joker("j_blueprint", "Blueprint"), joker("j_baron", "Baron"), joker("j_cavendish", "Cavendish")],
    )
    G["luna"] = {"main_commit": {"hand": "Pair", "trigger": "Baron", "ante": 1, "round": 1}}
    order = analysis.joker_order(G)
    labels = [G["jokers"]["cards"][i]["label"] for i in (order or range(3))]
    assert labels.index("Blueprint") + 1 == labels.index("Baron")
    G["jokers"]["cards"][0] = joker("j_brainstorm", "Brainstorm")
    order = analysis.joker_order(G)
    labels = [G["jokers"]["cards"][i]["label"] for i in (order or range(3))]
    assert labels[0] == "Baron"


def _bp_state(hand: str, payer: dict[str, Any], **rnd: Any) -> dict[str, Any]:
    return make_state(
        hand,
        [joker("j_blueprint", "Blueprint"), joker("j_jolly", "Jolly Joker"), payer],
        **rnd,
    )


def test_p2_15_discard_payers() -> None:
    mail = joker("j_mail", "Mail-In Rebate", "Earn $5 for each discarded 7")
    G = _bp_state("S_K H_K D_2 C_3 H_5 C_7 S_8 D_9", mail)
    assert analysis.discard_payers(G, [5]) == [2]
    assert analysis.discard_payers(G, [2]) == []
    castle = joker("j_castle", "Castle", "This Joker gains +3 Chips per discarded Spade card (Currently +0 Chips)")
    G = _bp_state("S_K H_K D_2 C_3 H_5 C_7 S_8 D_9", castle)
    assert analysis.discard_payers(G, [6]) == [2] and analysis.discard_payers(G, [7]) == []
    G = _bp_state("S_K H_K D_2 C_3 H_5 C_7 S_8 D_9", joker("j_trading", "Trading Card"))
    assert analysis.discard_payers(G, [2]) == [2]
    assert analysis.discard_payers(G, [2, 3]) == []
    G["round"]["discards_used"] = 1
    assert analysis.discard_payers(G, [2]) == []


def test_p2_15_blueprint_and_brainstorm_orders() -> None:
    mail = joker("j_mail", "Mail-In Rebate", "Earn $5 for each discarded 7")
    G = _bp_state("S_K H_K D_2 C_3 H_5 C_7 S_8 D_9", mail)
    order = analysis.discard_phase_order(G, [5])
    assert order == [1, 0, 2]  # Jolly, Blueprint, Mail-In: Blueprint copies Mail-In
    assert analysis.discard_phase_order(G, [2]) is None
    G["jokers"]["cards"][0] = joker("j_brainstorm", "Brainstorm")
    assert analysis.discard_phase_order(G, [5]) == [2, 0, 1]  # Mail-In leftmost
    G["jokers"]["cards"][0] = joker("j_joker", "Joker")
    assert analysis.discard_phase_order(G, [5]) is None  # no copier owned


async def test_p2_15_bot_moves_then_restores() -> None:
    import json
    from unittest.mock import AsyncMock

    from .test_bot_swap import _bot

    mail = joker("j_mail", "Mail-In Rebate", "Earn $5 for each discarded 7")
    G = _bp_state("S_K H_K D_2 C_3 H_5 C_7 S_8 D_9", mail)
    game = AsyncMock()
    game.call.return_value = G
    bot = _bot(game)
    bot.harness = {"joker_phase_order": True}
    bot._phase_moved = False
    await bot._phase_order(G, "discard", {"cards": [5]})
    assert game.call.call_args_list[-1].args == ("rearrange", {"jokers": [1, 0, 2]})
    assert bot._phase_moved
    moved = json.loads(json.dumps(G))
    moved["jokers"]["cards"] = [G["jokers"]["cards"][i] for i in (1, 0, 2)]
    await bot._phase_order(moved, "play", {"cards": [0, 1]})
    assert game.call.call_args_list[-1].args[0] == "rearrange"
    assert not bot._phase_moved
    calls = len(game.call.call_args_list)
    await bot._phase_order(moved, "play", {"cards": [0, 1]})
    assert len(game.call.call_args_list) == calls  # nothing to restore twice


def _pack_full(flag: bool) -> dict[str, Any]:
    G = make_state("H_2", [joker("j_greedy_joker", "Greedy Joker"), joker("j_jolly", "Jolly Joker")], state="SMODS_BOOSTER_OPENED")
    G["jokers"].update(limit=2, count=2)
    G["hand"]["cards"] = []
    G["pack"] = {"cards": [joker("j_duo", "The Duo"), joker("j_chaos", "Chaos the Clown")]}
    G["luna"] = {"sell_in_pack": flag}
    return G


def test_p2_7_full_slot_pick_only_with_the_flag() -> None:
    assert "slots are full" in analysis.validate_action(_pack_full(False), "pack", {"card": 0})
    assert analysis.swap_plan(_pack_full(False), "pack", {"card": 0}) is None
    G = _pack_full(True)
    assert analysis.validate_action(G, "pack", {"card": 0}) is None
    plan = analysis.swap_plan(G, "pack", {"card": 0})
    assert isinstance(plan, dict) and plan["buy"] == "The Duo"
    assert "would not raise" in analysis.swap_plan(G, "pack", {"card": 1})
    assert analysis.swap_plan(G, "pack", {"skip": True}) is None


def test_p2_7_pack_line_and_rule_follow_the_flag() -> None:
    G = _pack_full(True)
    sm = StrategyManager("mastery")
    text = sm.render_gamestate(G, rounds=[], history=[], flags={"sell_in_pack": True})
    assert "(the harness sells it for you)" in text
    assert "the harness sells the joker named in the swap" in sm.render_strategy(G, rounds=[], history=[], flags={"sell_in_pack": True})
    assert "If SLOTS_FREE = 0: skip." in sm.render_strategy(G, rounds=[], history=[], flags={})


async def test_p2_7_bot_sells_weakest_then_picks() -> None:
    from unittest.mock import AsyncMock

    from .test_bot_swap import _bot

    G = _pack_full(True)
    game = AsyncMock()
    game.call.return_value = {"state": "SMODS_BOOSTER_OPENED"}
    bot = _bot(game)
    bot.harness = {"validate_actions": True, "auto_swap_jokers": True, "sell_in_pack": True}
    bot._phase_moved = False
    plan = analysis.swap_plan(G, "pack", {"card": 0})
    import json
    from types import SimpleNamespace

    call = SimpleNamespace(function=SimpleNamespace(name="pack", arguments=json.dumps({"card": 0, "reasoning": "x"})))
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=None))])
    await bot._execute_tool_call(response, G)
    names = [c.args[0] for c in game.call.call_args_list]
    assert names[:2] == ["sell", "pack"]
    assert game.call.call_args_list[0].args[1] == {"joker": plan["sell"]}

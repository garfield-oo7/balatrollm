"""Pass 4 arm A1 (mastery-noadvice): facts kept, advice off.

(a) the noadvice templates on logged states (fixture: 3 states from pass-4 A0
    games, "seed" removed): no advice marker, the fact lines (and digest's
    anchors) present;
(b) validate_action split: legality vetoes still fire, advice vetoes do not, a
    full-slot joker sell in the SHOP is allowed.
"""

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from balatrollm import analysis
from balatrollm.strategy import StrategyManager, StrategyManifest

from .test_analysis import blind_select, joker, make_state

FIXTURE = Path(__file__).parent / "fixtures_pass4" / "noadvice_states.jsonl"
DIGEST = Path(__file__).resolve().parents[2] / "scripts" / "digest.py"

# Strings that only the advice layer writes (mastery templates, knowledge tags, rules)
ADVICE_MARKERS = [
    "Suggested discard", "Suggested action", "Suggested targets", "No good targets",
    "PLAY RULES", "SHOP RULES", "PACK RULES", "DECIDE NOW", "# EXAMPLE", "Run plan",
    "PRIORITY", "GOALS", "Counter:", "Boss rule now: play", "Boss impact", "Boss prep",
    "FIRST SHOP, TIGHT MONEY", "SPENDABLE", "SCORE_SPENDABLE", "RESERVE", "FLOOR $", "ECON_OK",
    "MAIN_HAND", "Past games", "CHASE", "tier S", "tier A", "tier B", "tier C", "tier T",
    "[TRAP]", "[BUY]", "[NEVER]", "[OFF-PLAN]", "[SKIP", "[PICK", "[SELL NOW", "[GROWS-XMULT]",
    "[MAIN]", "[XMULT]", "[MULT]", "[CHIPS]", "[ECON]", "[SCALE]", "[UTIL]", "[GOOD]", "[OK",
    "[FEED", "[AVOID]", "[CASH ONLY", "[SITUATIONAL]", "[REPEAT", "[NOT AFTER ANTE 2]",
    "Do not sell jokers", "sells WEAKEST for you", "the harness sells", "harness rerolls",
    "buy jokers that build your run", "keep those cards", "Dig only when",
    # pass 5: E2b investment line and E3's suggestion text (advice; hidden under noadvice)
    "BUY vs SAVE", "to reach", "score buys may use",
]


def _states() -> list[dict[str, Any]]:
    if not FIXTURE.exists():
        pytest.skip("pass-4 noadvice fixture missing")
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


def _render(G: dict[str, Any]) -> str:
    sm = StrategyManager("mastery-noadvice")
    flags = StrategyManifest.from_file("mastery-noadvice").harness
    ctx = {"rounds": [], "history": [], "flags": flags}
    return "\n".join(
        [
            sm.render_strategy(G, **ctx),
            sm.render_gamestate(G, **ctx),
            sm.render_memory(history=[], G=G, rounds=[], flags=flags),
        ]
    )


def _digest_module() -> Any:
    spec = importlib.util.spec_from_file_location("digest_p4", DIGEST)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fixture_has_no_seed() -> None:
    assert all("seed" not in G for G in _states())


def test_noadvice_render_has_facts_and_no_advice() -> None:
    dg = _digest_module()
    states = _states()
    seen = set()
    for G in states:
        text = _render(G)
        found = [m for m in ADVICE_MARKERS if m in text]
        assert not found, (G["state"], found)
        # facts kept (and the anchors scripts/digest.py parses)
        assert dg.HEAD.search(text) and dg.JOKERS.search(text) and dg.STATUS.search(text)
        # pass 5: the calibrated STATUS chance (E2a) is a fact, shown with advice off too
        if analysis.run_status(G).get("win_pct") is not None:
            assert "win chance about " in text
        assert "INTEREST_SPARE $" in text and "# POKER HANDS" in text and "# JOKERS (left to right)" in text
        assert "To buy a joker with full slots, sell one first." in text or G["state"] != "SHOP"
        if G["state"] == "SELECTING_HAND":
            assert dg.ROUND_BLIND.search(text)
            assert "| PER_HAND " in text and "## Listed plays" in text
            assert any(w in text for w in (" WINS", "(reaches PER_HAND)", "(below PER_HAND)", "BLOCKED"))
        if G["state"] == "SHOP":
            assert "- TYPICAL: " in text
            if any(c.get("set") == "JOKER" for c in G["shop"]["cards"]):
                assert "| SCORE " in text
            if G["jokers"]["cards"]:
                assert "adds " in text
            if not analysis.run_status(G)["slots_free"]:
                assert "swap for " in text and "WEAKEST:" in text
        if G["state"] == "SMODS_BOOSTER_OPENED":
            assert "# OPEN PACK" in text and "| effect: " in text
        seen.add(G["state"])
    assert seen == {"SELECTING_HAND", "SHOP", "SMODS_BOOSTER_OPENED"}


def _full_shop() -> dict[str, Any]:
    G = make_state("H_2", [joker("j_jolly", "Jolly Joker"), joker("j_duo", "The Duo")], state="SHOP")
    G["hand"]["cards"] = []
    G["jokers"]["limit"] = 2
    G["ante_num"] = 2
    G["money"] = 8
    G["shop"] = {"cards": [{**joker("j_stencil", "Joker Stencil"), "cost": {"buy": 8}}]}
    G["packs"] = {"cards": []}
    return G


def test_validate_split_full_slot_sell_and_advice_vetoes() -> None:
    G = _full_shop()
    # advice vetoes on (mastery): the sale and Joker Stencil are refused
    assert analysis.validate_action(G, "sell", {"joker": 0}) is not None
    assert "Stencil" in analysis.validate_action(G, "buy", {"card": 0})
    assert analysis.validate_action(G, "reroll", {}) is not None  # money line ($8 - $5 < $10)
    # advice off: all three are legal moves
    assert analysis.validate_action(G, "sell", {"joker": 0}, advice=False) is None
    # a full-slot joker buy is illegal (the game rejects it): refused with "sell one first"
    assert "sell one first" in analysis.validate_action(G, "buy", {"card": 0}, advice=False)
    assert analysis.validate_action(G, "reroll", {}, advice=False) is None
    G["jokers"]["limit"] = 3  # a free slot: the buy is legal again, advice vetoes off
    G["luna"] = {"first_shop": True, "shop_locked": True}
    assert analysis.validate_action(G, "buy", {"card": 0}) is not None
    assert analysis.validate_action(G, "buy", {"card": 0}, advice=False) is None


def test_validate_split_legality_still_fires() -> None:
    G = make_state("H_2 H_3 H_4 H_5 H_6 H_7", discards_left=0)
    for advice in (True, False):
        assert "No discards left" in analysis.validate_action(G, "discard", {"cards": [0]}, advice=advice)
        assert "at least 1" in analysis.validate_action(G, "play", {"cards": []}, advice=advice)
        assert "maximum" in analysis.validate_action(G, "play", {"cards": [0, 1, 2, 3, 4, 5]}, advice=advice)
        assert "only once" in analysis.validate_action(G, "play", {"cards": [0, 0]}, advice=advice)
    # full-slot protection inside a pack, Death targets, Judgement with full slots
    P = _full_shop()
    P["state"] = "SMODS_BOOSTER_OPENED"
    P["pack"] = {"cards": [joker("j_joker", "Joker"), {"key": "c_death", "set": "TAROT", "label": "Death"}]}
    P["consumables"] = {"cards": [{"key": "c_judgement", "set": "TAROT", "label": "Judgement"}]}
    assert "slots are full" in analysis.validate_action(P, "pack", {"card": 0}, advice=False)
    assert "Death needs" in analysis.validate_action(P, "pack", {"card": 1, "targets": [0]}, advice=False)
    assert "either" in analysis.validate_action(P, "pack", {"card": 0, "skip": True}, advice=False)
    P["state"] = "SHOP"
    assert "sell a joker" in analysis.validate_action(P, "use", {"consumable": 0}, advice=False)
    # reroll_boss: illegal without a voucher; legal-only drops "one per ante"
    B = blind_select("The Hook")
    B["state"] = "SHOP"
    B["luna"] = {"boss_rerolls": 1}
    assert "one per ante" in analysis.validate_action(B, "reroll_boss", {})
    B["used_vouchers"] = {"v_retcon": ""}
    assert analysis.validate_action(B, "reroll_boss", {}, advice=False) is None
    B["used_vouchers"] = {}
    assert "Director's Cut or Retcon" in analysis.validate_action(B, "reroll_boss", {}, advice=False)


def test_f1_wrong_item_guard_never_refuses_a_buy_naming_its_item() -> None:
    # pass 4 F1: the guard repairs a wrong index; a buy whose reasoning names the chosen item is legal
    G = _full_shop()
    G["shop"]["cards"] = [{"key": "c_pluto", "set": "PLANET", "label": "Pluto"}, joker("j_scholar", "Scholar")]
    named_both = "Scholar is +80% but Pluto levels High Card: buy Pluto."
    assert analysis.shop_wrong_item_veto(G, {"card": 0}, named_both) is None
    assert analysis.shop_wrong_item_veto(G, {"card": 1}, "Scholar costs $4.") is None
    assert analysis.shop_wrong_item_veto(G, {"card": 0}, "Cheap level.") is None  # names nothing
    msg = analysis.shop_wrong_item_veto(G, {"card": 0}, "Scholar costs $4, buy it.")
    assert msg is not None and "Pluto" in msg and "Scholar" in msg and "card 1" in msg


def test_f4_consumable_slots_refuse_only_when_full() -> None:
    G = _full_shop()
    G["jokers"]["limit"] = 5
    G["shop"]["cards"] = [{"key": "c_pluto", "set": "PLANET", "label": "Pluto", "cost": {"buy": 3}}]
    G["consumables"] = {"count": 1, "limit": 2, "cards": [{"key": "c_mars", "set": "PLANET", "label": "Mars"}]}
    for advice in (True, False):
        assert analysis.validate_action(G, "buy", {"card": 0}, advice=advice) is None  # a free slot: legal
    G["consumables"]["count"] = 2
    for advice in (True, False):
        assert "consumable slots are full" in analysis.validate_action(G, "buy", {"card": 0}, advice=advice)

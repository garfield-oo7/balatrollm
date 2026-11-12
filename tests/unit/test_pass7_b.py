"""Pass 7 base fixes, builder B: B1 The Psychic five-card plays, B2 pack-pick summary parser, B3 full-slot veto."""

import json
from pathlib import Path

from .test_analysis import joker, make_state

FIXTURE = Path(__file__).parent / "fixtures_pass7" / "psychic_n164.json"  # F N164 Ante 4, seed-checked


def test_b1_psychic_lists_five_card_plays_and_models_one() -> None:
    from balatrollm import analysis

    G = json.loads(FIXTURE.read_text())["G"]
    A = analysis.play_advice(G, line_only=True)
    plays = A["plays"]
    assert plays and all(len(p["cards"]) == 5 and not p["blocked"] and p["score"] > 0 for p in plays)
    hand = analysis._area_cards(G, "hand")
    for p in plays:  # labelled by the actual type of the five cards
        est = analysis.estimate_play(G, [hand[i] for i in p["cards"]],
                                     [c for i, c in enumerate(hand) if i not in p["cards"]])
        assert p["hand"] == est["hand"] and p["score"] == est["score"]
    assert len({p["hand"] for p in plays}) == len(plays)
    play = A["line"]["play"]
    assert len(play["cards"]) == 5 and play["floor"] > 0
    # padding is not added a second time: the modeled play IS a listed entry with its score
    listed = next(p for p in plays if p["cards"] == play["cards"])
    assert play["floor"] == listed["score"] and play["hand"] == listed["hand"]
    assert A["line"]["suppressed"] == "The Psychic: sampled comparison not validated for five-card plays"


def test_b2_planet_summary_parser_accepts_three_forms() -> None:
    from balatrollm import analysis

    G = {"round_num": 1}
    for res in ("used Jupiter", "took Jupiter from pack", "took Jupiter from pack (used at once)"):
        assert analysis.planets_per_round({"round_num": 2}, [{"result": res}] * 4) == 2.0, res
    before = {"pack": {"cards": [{"label": "Jupiter", "set": "PLANET"}, {"label": "Joker", "set": "JOKER"}]}}
    assert analysis.summarize_outcome("pack", {"card": 0}, before, G) == "took Jupiter from pack (used at once)"
    assert analysis.summarize_outcome("pack", {"card": 1}, before, G) == "took Joker from pack"


def test_b3_full_slot_veto_names_the_fitting_offer() -> None:
    from balatrollm import analysis

    # F N121 Ante 4 row shape: 5/5 jokers, 0/2 consumables, $8; Driver's License $7 (card 0), The Hermit $3 (card 1)
    G = make_state("H_2", [joker("j_joker", "Joker")] * 5, state="SHOP")
    G["jokers"].update(count=5, limit=5)
    G["consumables"] = {"count": 0, "limit": 2, "cards": []}
    G["money"] = 8
    hermit = {"key": "c_hermit", "set": "TAROT", "label": "The Hermit", "value": {}, "modifier": {}, "state": {},
              "cost": {"buy": 3, "sell": 1}}
    G["shop"] = {"cards": [joker("j_drivers_license", "Driver's License", cost=7), hermit]}
    why = ("Driver’s License adds nothing with 0 enhanced cards, so I’ll buy The Hermit for $3 "
           "to improve the $8 bankroll before the boss.")
    params = {"card": 0}
    assert analysis.shop_buy_veto(G, params, why) is None  # both named: the wrong-item check passes (bot order)
    msg = analysis.validate_action(G, "buy", params, advice=False, reasoning=why)
    assert msg.startswith("Your joker slots are full (5/5).")
    assert msg.endswith("Your reasoning also names The Hermit (card 1); to buy it, use card 1.")
    G["consumables"]["count"] = 2  # no free consumable slot: nothing added
    assert "also names" not in analysis.validate_action(G, "buy", params, advice=False, reasoning=why)

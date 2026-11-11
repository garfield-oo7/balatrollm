"""Pass 6 H1a Verdant Leaf: keep-or-sell facts and the disabled boss (mod field blinds.boss.disabled).

Fixture: pass-5 C-off N85, first decision in the Verdant Leaf blind (all 8 cards debuffed, Constellation X4.9 only),
"seed" removed. Keep: 9♠ 9♣ 9♦ = 170 x 17 x 4.9 = 14,161; sell Constellation: (170 + 27) x 17 = 3,349 (what the game gave).
"""

import copy
import json
from pathlib import Path

from balatrollm import analysis
from balatrollm.strategy import StrategyManager, StrategyManifest

FIXTURE = Path(__file__).parent / "fixtures_pass6" / "verdant_n85.json"
NINES = "9 of Spades, 9 of Clubs, 9 of Diamonds"


def _g() -> dict:
    return json.loads(FIXTURE.read_text())["G"]


def _gamestate(G: dict) -> str:
    sm = StrategyManager("mastery-noadvice")
    flags = StrategyManifest.from_file("mastery-noadvice").harness
    return sm.render_gamestate(G, rounds=[], history=[], flags=flags)


def test_n85_keep_vs_sell_constellation():
    V = analysis.verdant_options(_g())
    assert V["keep"]["names"] == NINES and V["keep"]["score"] == 14161
    assert [(s["joker"], s["names"], s["score"]) for s in V["sells"]] == [("Constellation", NINES, 3349)]
    assert V["not_shown"] == 0
    txt = _gamestate(_g())
    assert f"- keep all jokers: cards debuffed, best play {NINES} = 14,161 (floor)" in txt
    assert f"- sell Constellation: best play {NINES} = 3,349 (floor)" in txt
    assert "- Selling is optional; you may win on jokers alone." in txt


def test_disabled_boss_renders_disabled_text_not_the_rule():
    G = _g()
    # the state after the sale: the mod reports the boss disabled, debuffs lifted, the joker gone
    G = analysis._verdant_sale(G, 0)
    assert G["blinds"]["boss"]["disabled"] is True
    assert analysis._active_boss(G) == "" and analysis.verdant_options(G) is None
    txt = _gamestate(G)
    assert "Boss disabled (a joker was sold): no boss rule now" in txt
    for rule in ("debuffed until", "All cards debuffed", "keep all jokers", "Boss rule now", "DEBUFFED"):
        assert rule not in txt, rule
    # a missing field = not disabled: the rule text is still shown
    G2 = copy.deepcopy(_g())
    G2["blinds"]["boss"].pop("disabled", None)
    assert "Boss rule now: all cards are debuffed until you sell 1 joker during this blind" in _gamestate(G2)

"""Pass 8 F1 guard: `use` of a consumable not held is refused (both arms)."""

from balatrollm.analysis import validate_action


def _G(cons: list[str]) -> dict:
    cards = [{"key": f"c_{n.lower()}", "label": n, "set": "TAROT"} for n in cons]
    return {"state": "SHOP", "consumables": {"count": len(cards), "limit": 2, "cards": cards},
            "jokers": {"count": 0, "limit": 5, "cards": []}}


def test_use_index_not_held() -> None:
    for advice in (True, False):
        assert validate_action(_G([]), "use", {"consumable": 0}, advice=advice) == "You hold no consumables."
        msg = validate_action(_G(["Neptune"]), "use", {"consumable": 1}, advice=advice)
        assert msg == "You hold no consumable at index 1. You hold: 0: Neptune (use consumable 0)."
        assert validate_action(_G(["Neptune", "Strength"]), "use", {"consumable": -1}, advice=advice).startswith(
            "You hold no consumable at index -1. You hold: 0: Neptune, 1: Strength (use consumable 0..1)")
        assert validate_action(_G(["Neptune"]), "use", {"consumable": 0}, advice=advice) is None


def test_shop_tally_fails_closed() -> None:
    """S2: counted once per round; an uncounted event omits the tally for the rest of the run."""
    from unittest.mock import AsyncMock

    from .test_bot_swap import _bot

    bot = _bot(AsyncMock())
    bot._note_reroll({"ante_num": 2, "money": 10}, {"money": 5})
    bot._accrue_interest(((1, 3), 4))
    bot._accrue_interest(((1, 3), 4))
    assert bot._shop_tally(2) == {"ante": 2, "ante_rerolls": 1, "ante_reroll_spend": 5, "run_rerolls": 1,
                                  "run_reroll_spend": 5, "run_interest": 4}
    bot._accrue_interest(bot._interest_owed({"money": object()}))  # owed interest not computable
    assert bot._shop_tally(2) is None
    bot._note_reroll({"ante_num": 2, "money": 10}, {"money": 5})
    assert bot._shop_tally(2) is None

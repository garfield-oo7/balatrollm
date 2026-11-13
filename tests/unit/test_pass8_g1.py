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

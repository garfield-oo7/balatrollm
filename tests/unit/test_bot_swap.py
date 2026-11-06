"""Harness auto-swap: buying a joker with full slots sells WEAKEST first."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from balatrollm.bot import Bot
from balatrollm.client import BalatroError

from .test_analysis import joker, make_state


def _bot(game: AsyncMock) -> Bot:
    bot = object.__new__(Bot)
    bot.harness = {"validate_actions": True, "auto_swap_jokers": True}
    bot._balatro = game
    bot._collector = MagicMock()
    bot._history = []
    bot._consecutive_rearranges = 0
    bot._shop_rerolls = 0
    bot._consecutive_vetoes = 0
    bot._consecutive_errors = 0
    bot._consecutive_faileds = 0
    bot._last_error_msg = None
    bot._last_failed_msg = None
    return bot


def _buy(card: int) -> Any:
    call = SimpleNamespace(
        function=SimpleNamespace(name="buy", arguments=json.dumps({"card": card}))
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])


def _full_shop() -> dict[str, Any]:
    G = make_state(
        "H_2",
        [joker("j_jolly", "Jolly Joker"), joker("j_golden", "Golden Joker")],
        state="SHOP",
    )
    G["hand"]["cards"] = []
    G["jokers"]["limit"] = 2
    G["jokers"]["cards"][0]["cost"] = {"sell": 1}
    G["money"] = 8
    G["shop"] = {"cards": [{**joker("j_duo", "The Duo"), "cost": {"buy": 8}}]}
    return G


async def test_buy_with_full_slots_sells_weakest_then_buys() -> None:
    game = AsyncMock()
    game.call.return_value = {"state": "SHOP"}
    await _bot(game)._execute_tool_call(_buy(0), _full_shop())
    calls = [(c.args[0], c.args[1]) for c in game.call.call_args_list]
    assert calls == [("sell", {"joker": 0}), ("buy", {"card": 0})]


async def test_unaffordable_swap_is_refused_without_selling() -> None:
    game = AsyncMock()
    game.call.return_value = {"state": "SHOP"}
    G = _full_shop()
    G["money"] = 6
    bot = _bot(game)
    await bot._execute_tool_call(_buy(0), G)
    assert [c.args[0] for c in game.call.call_args_list] == ["gamestate"]
    assert "not enough" in bot._last_failed_msg


async def test_failed_sell_does_not_buy() -> None:
    game = AsyncMock()
    game.call.side_effect = [BalatroError(400, "nope", {"name": "BAD_REQUEST"}), {"state": "SHOP"}]
    await _bot(game)._execute_tool_call(_buy(0), _full_shop())
    assert [c.args[0] for c in game.call.call_args_list] == ["sell", "gamestate"]


def _blind_select(ante: int, small_tag: str, small: str = "SELECT") -> dict[str, Any]:
    return {
        "state": "BLIND_SELECT",
        "ante_num": ante,
        "blinds": {
            "small": {"status": small, "type": "SMALL", "name": "Small Blind", "tag_name": small_tag},
            "big": {"status": "UPCOMING" if small == "SELECT" else "SELECT", "type": "BIG", "name": "Big Blind", "tag_name": "Juggle Tag"},
            "boss": {"status": "UPCOMING", "type": "BOSS", "name": "The Hook", "tag_name": ""},
        },
    }


def test_skip_only_for_investment_tag_in_ante_one() -> None:
    bot = _bot(AsyncMock())
    bot.harness = {"skip_blind_tags": {"Investment Tag": 1}}
    assert bot._skip_for_tag(_blind_select(1, "Investment Tag"))
    assert not bot._skip_for_tag(_blind_select(2, "Investment Tag"))
    assert not bot._skip_for_tag(_blind_select(1, "Juggle Tag"))
    # Small already skipped: the Big blind's own tag decides
    assert not bot._skip_for_tag(_blind_select(1, "Investment Tag", small="SKIPPED"))
    bot.harness = {}
    assert not bot._skip_for_tag(_blind_select(1, "Investment Tag"))


async def test_harness_rerolls_bad_boss_once() -> None:
    from .test_analysis import blind_select

    game = AsyncMock()
    after = blind_select("The Hook")
    after["round"]["boss_rerolled"] = True
    game.call.return_value = after
    bot = _bot(game)
    bot.harness = {"reroll_boss": True}
    bot._boss_rerolls = {}
    result = await bot._reroll_boss(blind_select("The Wall"))
    assert result is after
    assert [c.args[0] for c in game.call.call_args_list] == ["reroll_boss"]
    assert bot._history[-1]["method"] == "reroll_boss"
    assert "The Wall -> The Hook" in bot._history[-1]["result"]
    # The new boss is fine: no second reroll
    assert await bot._reroll_boss(after) is None


async def test_harness_boss_reroll_off_or_capped() -> None:
    from .test_analysis import blind_select

    game = AsyncMock()
    bot = _bot(game)
    bot.harness = {}
    bot._boss_rerolls = {}
    assert await bot._reroll_boss(blind_select("The Wall")) is None
    bot.harness = {"reroll_boss": True}
    bot._boss_rerolls = {1: 3}
    assert await bot._reroll_boss(blind_select("The Wall")) is None
    game.call.assert_not_called()


async def test_failed_boss_reroll_falls_back_to_select() -> None:
    from .test_analysis import blind_select

    game = AsyncMock()
    game.call.side_effect = BalatroError(-32003, "nope", {"name": "NOT_ALLOWED"})
    bot = _bot(game)
    bot.harness = {"reroll_boss": True}
    bot._boss_rerolls = {}
    assert await bot._reroll_boss(blind_select("The Wall")) is None

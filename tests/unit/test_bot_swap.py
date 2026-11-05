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

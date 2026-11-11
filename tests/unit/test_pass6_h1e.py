"""Pass 6 H1e (decision B2): buy field veto and recoverable shop misses."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from balatrollm.client import BalatroError

from .test_analysis import joker, make_state
from .test_bot_swap import _bot


def _call(name: str, args: dict[str, Any]) -> Any:
    call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(args)))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=None))])


def _shop() -> dict[str, Any]:
    G = make_state("H_2", [joker("j_jolly", "Jolly Joker")], state="SHOP")
    G["hand"]["cards"] = []
    G["money"] = 10
    G["shop"] = {"cards": [
        {**joker("j_hiker", "Hiker"), "cost": {"buy": 5, "sell": 2}},
        {"key": "c_venus", "set": "PLANET", "label": "Venus", "cost": {"buy": 3, "sell": 1}},
    ]}
    return G


async def test_buy_with_joker_field_is_vetoed_with_the_right_key_and_not_counted() -> None:
    game = AsyncMock()
    game.call.return_value = {"state": "SHOP"}
    bot = _bot(game)
    bot.harness = {"validate_actions": True, "advice_vetoes": False}
    for _ in range(5):  # 5 refusals in a row used to end the run
        await bot._execute_tool_call(_call("buy", {"joker": 0, "reasoning": "Hiker grows chips."}), _shop())
    assert [c.args[0] for c in game.call.call_args_list] == ["gamestate"] * 5  # never sent, never bought
    assert "`joker` is the sell field" in bot._last_failed_msg
    assert "Hiker is card 0 ($5): buy with `card` 0" in bot._last_failed_msg
    assert bot._consecutive_vetoes == 0 and bot._shop_item_misses == 5


async def test_three_recoverable_shop_misses_do_not_leave_the_shop() -> None:
    game = AsyncMock()

    def answer(method: str, *a: Any) -> dict[str, Any]:
        if method == "buy":
            raise BalatroError(1, "Card is not affordable. Cost: 5, Available money: 3", {"name": "BAD_REQUEST"})
        return {"state": "SHOP"}

    game.call.side_effect = answer
    bot = _bot(game)
    bot.harness = {}
    for _ in range(3):
        await bot._execute_tool_call(_call("buy", {"card": 0, "reasoning": "Hiker"}), _shop())
    methods = [c.args[0] for c in game.call.call_args_list]
    assert "next_round" not in methods and methods.count("buy") == 3
    assert bot._consecutive_faileds == 0 and bot._shop_refusal_exits == 0

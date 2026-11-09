"""B0c (pass 4): results ledger rows (decisions.jsonl)."""

import glob
import json
import os

import pytest

from balatrollm import ledger
from balatrollm.collector import Collector

from .test_bot_swap import _bot, _buy, _full_shop

A0 = os.path.expanduser(
    "~/personal_projects/balatrollm-mastery/runs/v1.3.0/mastery/openai/gpt-6-luna/2026*_SEED-N0[1-3]/gamestates.jsonl"
)


def _logged_states(state: str, n: int = 15):
    out = []
    for f in sorted(glob.glob(A0)):
        for line in open(f):
            g = json.loads(line)
            if g.get("state") == state:
                out.append(g)
                if len(out) >= n:
                    return out
    return out


def _sample_hand_states():
    states = _logged_states("SELECTING_HAND")
    if not states:
        pytest.skip("no logged A0 states on this machine")
    return states


def test_pre_row_on_logged_hand_states_is_json_and_seedless():
    flags = {"suggest_action": False}
    for G in _sample_hand_states():
        G = {**G, "luna": {}}
        row = ledger.pre_row(G, [], [], flags)
        text = json.dumps(row, default=str)
        assert "seed" not in row["G"]
        assert G["seed"] not in text  # the real seed never reaches the ledger
        assert "ledger_error" not in row["advice"], row["advice"]
        assert row["advice"]["plays"], "listed plays recorded"
        # computed although not rendered (suggest_action off)
        assert row["rendered"]["suggest_action"] is False
        assert "suggested_action" in row["advice"]
        for p in row["advice"]["plays"]:
            assert p["card_names"] and "?" not in p["card_names"]


def test_pre_row_on_logged_shop_states():
    states = _logged_states("SHOP")
    if not states:
        pytest.skip("no logged A0 states on this machine")
    for G in states:
        G = {**G, "luna": {"status": "THIN"}}
        row = ledger.pre_row(G, [], [], {})
        assert "ledger_error" not in row["status"], row["status"]
        assert isinstance(row["shop_impact"], dict) and "ledger_error" not in row["shop_impact"]
        json.dumps(row, default=str)


def test_computing_the_ledger_does_not_change_the_advice():
    """Pure functions: the advice after the ledger equals the advice before it."""
    from balatrollm.analysis import play_advice

    for G in _sample_hand_states()[:5]:
        G = {**G, "luna": {}}
        first = json.dumps(play_advice(G), sort_keys=True, default=str)
        ledger.pre_row(G, [], [], {})
        assert json.dumps(play_advice(G), sort_keys=True, default=str) == first


async def test_bot_writes_one_row_per_call_with_outcome(tmp_path):
    from unittest.mock import AsyncMock

    game = AsyncMock()
    game.call.return_value = {"state": "SHOP", "money": 0}
    bot = _bot(game)
    bot._collector = Collector.__new__(Collector)
    bot._collector.run_dir = tmp_path
    bot._collector.record_call = lambda *a: None
    bot._collector.record_failure = lambda *a: None
    bot._collector.reset_failures = lambda *a: None
    bot._collector.write_gamestate = lambda *a: None
    G = _full_shop()
    G["luna"] = {}
    # ok path: harness swap-sell then buy
    bot._ledger_row = ledger.pre_row(G, [], [], bot.harness)
    bot._ledger_call, bot._ledger_out = None, {"result": "unknown"}
    after = await bot._execute_tool_call(_buy(0), G)
    bot._write_ledger(G, after)
    # vetoed path: unaffordable swap
    G2 = _full_shop()
    G2["money"], G2["luna"] = 6, {}
    bot._ledger_row = ledger.pre_row(G2, [], [], bot.harness)
    bot._ledger_call, bot._ledger_out = None, {"result": "unknown"}
    after2 = await bot._execute_tool_call(_buy(0), G2)
    bot._write_ledger(G2, after2)
    rows = [json.loads(x) for x in (tmp_path / "decisions.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0]["outcome"]["result"] == "ok" and "harness sold" in rows[0]["outcome"]["harness_sold"]
    assert rows[0]["chosen"] == {"tool": "buy", "params": {"card": 0}, "item": "The Duo"}
    assert rows[0]["swap_plan"]["buy"] == "The Duo"
    assert rows[0]["money_before"] == 8 and rows[0]["money_after"] == 0
    assert rows[1]["outcome"]["result"] == "vetoed" and "not enough" in rows[1]["outcome"]["msg"]


def test_joiner_marks_next_blind(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("lj", os.path.join(os.path.dirname(__file__), "../../scripts/ledger_join.py"))
    lj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lj)
    gs = [{"state": "ROUND_EVAL", "round_num": 1}, {"state": "ROUND_EVAL", "round_num": 2}, {"state": "GAME_OVER", "round_num": 3}]
    (tmp_path / "gamestates.jsonl").write_text("".join(json.dumps(g) + "\n" for g in gs))
    rows = [
        {"state": "SELECTING_HAND", "round": 1, "G": {}},
        {"state": "SHOP", "round": 1},
        {"state": "SHOP", "round": 2},
        {"state": "SELECTING_HAND", "round": 3},
    ]
    (tmp_path / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = lj.join(tmp_path)
    assert [r["next_blind"]["result"] for r in out] == ["won", "won", "lost", "lost"]
    assert "G" not in out[0]

"""Pass-2 harness fixes: win detection (H6), digest."""

import importlib.util
import json
from pathlib import Path

from balatrollm.collector import is_real_win


def _boss(chips: int, status: str = "CURRENT") -> dict:
    return {
        "won": True,
        "ante_num": 8,
        "round": {"chips": chips},
        "blinds": {"boss": {"name": "Crimson Heart", "score": 100_000, "status": status}},
    }


def test_game_over_with_won_flag_is_a_loss() -> None:
    """Pass 1 Seed T: lost Crimson Heart 65,980 / 100,000, the game still set won = true."""
    assert not is_real_win({**_boss(65_980), "state": "GAME_OVER"})


def test_won_flag_below_target_is_a_loss() -> None:
    assert not is_real_win({**_boss(65_980), "state": "ROUND_EVAL"})


def test_real_win() -> None:
    assert is_real_win({**_boss(120_000), "state": "ROUND_EVAL"})
    assert is_real_win({**_boss(0, "DEFEATED"), "state": "ROUND_EVAL"})
    assert not is_real_win({"won": False, "state": "ROUND_EVAL"})


def _digest_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "digest.py"
    spec = importlib.util.spec_from_file_location("digest", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_digest_counts_game_over_as_loss(tmp_path: Path) -> None:
    digest = _digest_module()
    (tmp_path / "gamestates.jsonl").write_text(
        json.dumps({"state": "SELECTING_HAND"}) + "\n" + json.dumps({"state": "GAME_OVER", "won": True}) + "\n"
    )
    assert digest.ended_game_over(tmp_path)


def test_shop_lock_after_ante_4_buy_below_10() -> None:
    from balatrollm.bot import shop_lock_after

    shop = {"state": "SHOP", "ante_num": 4}
    assert shop_lock_after(shop, "buy", {"money": 9})
    assert not shop_lock_after(shop, "buy", {"money": 10})
    assert not shop_lock_after({**shop, "ante_num": 3}, "buy", {"money": 2})
    assert not shop_lock_after(shop, "reroll", {"money": 2})
    assert not shop_lock_after({**shop, "state": "SMODS_BOOSTER_OPENED"}, "buy", {"money": 2})


def _boss_select(name: str, ante: int, money: int, jokers: list[str] | None = None) -> dict:
    from .test_analysis import blind_select, joker

    G = blind_select(name)
    G["ante_num"] = ante
    G["money"] = money
    G["used_vouchers"] = {"v_directors_cut": ""}
    G["jokers"] = {"count": 0, "limit": 5, "cards": [joker(f"j_{j.lower()}", j) for j in jokers or []]}
    G["jokers"]["count"] = len(G["jokers"]["cards"])
    return G


def test_boss_reroll_keeps_10_from_ante_4_except_always_bosses() -> None:
    from balatrollm.analysis import boss_reroll_reason

    assert boss_reroll_reason(_boss_select("The Wall", 4, 12))  # always-reroll boss
    assert boss_reroll_reason(_boss_select("The Plant", 4, 19, ["Photograph"])) is None
    assert boss_reroll_reason(_boss_select("The Plant", 4, 20, ["Photograph"]))
    assert boss_reroll_reason(_boss_select("The Plant", 3, 12, ["Photograph"]))


def test_the_plant_only_for_face_builds() -> None:
    from balatrollm.analysis import boss_reroll_reason, face_build

    assert face_build(_boss_select("The Plant", 2, 30, ["Scary Face"]))
    assert not face_build(_boss_select("The Plant", 2, 30, ["Business Card"]))  # ECON
    assert boss_reroll_reason(_boss_select("The Plant", 2, 30, ["Joker"])) is None


def test_pending_investment_tag_line_until_the_ante_moves_on() -> None:
    from unittest.mock import AsyncMock

    from balatrollm.analysis import run_status
    from balatrollm.strategy import StrategyManager

    from .test_analysis import make_state
    from .test_bot_swap import _blind_select, _bot

    bot = _bot(AsyncMock())
    bot._pending_tags = []
    bot.harness = {"skip_blind_tags": {"Investment Tag": 1}}
    assert bot._skip_for_tag(_blind_select(1, "Investment Tag"))
    G = make_state("H_2", state="SHOP")
    G["money"] = 7
    bot._annotate(G)
    lines = run_status(G, [], [])["pending_tags"]
    assert lines and "+$25 after this ante's boss" in lines[0] and "$32" in lines[0]
    text = StrategyManager("mastery").render_gamestate(G, rounds=[], history=[], flags={})
    assert "PENDING TAG: Investment Tag" in text
    G2 = make_state("H_2", state="SHOP")
    G2["ante_num"] = 2
    bot._annotate(G2)
    assert run_status(G2, [], [])["pending_tags"] == []

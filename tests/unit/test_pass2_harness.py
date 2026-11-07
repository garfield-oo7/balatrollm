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

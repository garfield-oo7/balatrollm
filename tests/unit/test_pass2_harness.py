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


def _prompt(ante: int, rnd: int, money: int, status: str, main: str, shop: str = "", hand: bool = False) -> dict:
    body = (
        f"# STATUS\n- Ante {ante}/8, round {rnd}, money ${money}\n"
        f"- MAIN_HAND: {main}\n- Jokers 1/5, SLOTS_FREE 4, XMULT_OWNED 0\n"
        f"- STATUS: {status} for the next blind (Small Blind): 300 needs about 2 of 4 hands at about 150 per hand\n"
    )
    body += "# ROUND\n- Blind: Small\n" if hand else shop
    return {"body": {"messages": [{"role": "user", "content": body}]}}


def _resp(name: str, args: dict) -> dict:
    return {"response": {"body": {"choices": [{"message": {"tool_calls": [
        {"function": {"name": name, "arguments": json.dumps(args)}}]}}]}}}


def test_digest_pass2_fields(tmp_path: Path) -> None:
    digest = _digest_module()
    shop = (
        "# SHOP\n- 0: The Duo $8 [XMULT] tier S | SCORE +541 per hand\n- 1: Pluto (Planet) $3 [OK]\n"
        "- Reroll cost: $5\n\n## Packs (use buy with `pack`)\n- 0: Buffoon Pack $4\n\n- Next blind: x\n\n# JOKERS\n"
    )
    open_main = "OPEN (leaning Pair) - OPEN: no joker calls for a hand yet"
    committed = "Pair - committed: The Duo (round 2)"
    reqs = [
        _prompt(1, 1, 10, "COMFORTABLE", open_main, shop),
        _prompt(1, 1, 6, "COMFORTABLE", open_main, shop),
        _prompt(1, 1, 6, "COMFORTABLE", open_main, shop),
        _prompt(1, 2, 8, "THIN", committed, hand=True),
        _prompt(2, 3, 20, "SHORT", committed, shop),
        _prompt(2, 3, 15, "SHORT", committed, shop),
    ]
    resps = [
        _resp("buy", {"pack": 0}),
        _resp("buy", {"card": 0}),
        _resp("next_round", {}),
        _resp("play", {"cards": [0, 1]}),
        _resp("reroll", {}),
        _resp("next_round", {}),
    ]
    (tmp_path / "requests.jsonl").write_text("".join(json.dumps(r) + "\n" for r in reqs))
    (tmp_path / "responses.jsonl").write_text("".join(json.dumps(r) + "\n" for r in resps))
    (tmp_path / "task.json").write_text(json.dumps({"seed": "SEED-Z", "model": "m"}))
    (tmp_path / "stats.json").write_text(json.dumps({"run_won": False, "final_ante": 2}))
    (tmp_path / "gamestates.jsonl").write_text(json.dumps({"state": "GAME_OVER", "ante_num": 2, "hands": {
        "High Card": {"played": 9}, "Pair": {"played": 4}}}) + "\n")
    (tmp_path / "run.log").write_text(
        "x - INFO - Harness rerolled boss The Wall -> The Hook (The Wall is a boss to always reroll)\n"
        "x - WARNING - Vetoed call: Reroll refused\n"
        "x - INFO - Skipping Small Blind for Investment Tag\n"
    )
    d = digest.digest(tmp_path)
    assert d["situations_at_shop_entry"] == {"COMFORTABLE": 1, "SHORT": 1}
    assert d["first_shop"] == {"buys": ["pack:Buffoon Pack", "joker:The Duo"], "buffoon_offered": True, "buffoon_first": True}
    assert d["main_commit"] == {"ante": 1, "round": 2, "hand": "Pair", "trigger": "The Duo"}
    assert d["rerolls_by_ante"] == {1: 0, 2: 1} and d["rerolls_below_25_ante2_3"] == 1
    assert d["most_played"] == "Pair"  # High Card not counted (H4)
    assert d["too_weak_share_ante1_2"] == 0.4  # 2 of 5 shop decisions SHORT
    assert d["shop_visits"][0]["hands_needed_in"] == 2
    h = d["harness"]
    assert h["boss_rerolls"] == 1 and h["boss_reroll_cost"] == 10 and h["boss_reroll_list"] == [["The Wall", "The Hook"]]
    assert h["refusals"] == 1 and h["tag_skip_list"] == ["Investment Tag"]
    assert not d["won"]


def test_digest_dip_flag() -> None:
    digest = _digest_module()
    v = lambda a, m: {"ante": a, "money_in": m, "money_out": m}  # noqa: E731
    assert digest.dip_flag([v(2, 10), v(2, 5), v(3, 20)])
    assert not digest.dip_flag([v(2, 10), v(2, 30), v(3, 20)])
    assert digest.dip_flag([v(4, 10), v(4, 30), v(5, 5)])


def test_digest_status_reads_hands_needed_in_both_vocabularies() -> None:
    digest = _digest_module()
    old = "- STATUS: TOO WEAK (next blind 1,200 needs about 6 hands at 200 per hand)"
    new = "- STATUS: SHORT for the next blind (Big Blind): 1,200 needs about 5 of 4 hands at about 240 per hand"
    for line, word, n in ((old, "TOO WEAK", 6), (new, "SHORT", 5)):
        m = digest.STATUS.search("x\n" + line + "\ny")
        assert m.group(1) == word and int(digest.NEEDS.search(m.group(2)).group(1)) == n


def test_validators_use_the_displayed_status() -> None:
    """The reroll line follows the STATUS Luna sees (computed with the run's
    rounds), not a rounds-free recomputation."""
    from unittest.mock import AsyncMock

    from balatrollm import analysis

    from .test_analysis import make_state
    from .test_bot_swap import _bot

    G = make_state("H_2", state="SHOP")
    G["ante_num"] = 4
    G["money"] = 20
    G["hands"]["Pair"].update(chips=500, mult=50, level=20)
    bot = _bot(AsyncMock())
    bot._rounds = [{"hands_left": 0}]  # last blind won on its final hand: THIN
    bot._history = []
    bot._pending_tags = []
    bot._annotate(G)
    assert G["luna"]["status"] == "THIN"
    assert analysis.run_status(G, [], [])["status"] == "COMFORTABLE"  # without rounds
    assert analysis.validate_action(G, "reroll", {}) is None  # $10 line (THIN), not $25
    key_with = analysis._state_key(G, "x")
    G["luna"].pop("status")
    assert analysis._state_key(G, "x") == key_with

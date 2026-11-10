"""Pass 4 L: the checks that decide whether a book edit is kept, and the merge."""

import json

from balatrollm import book

GOOD = "when XMULT_OWNED is 0 from Ante 3, do buy an [XMULT] joker first, because without one Ante 5 is lost"
FAKE_SEED = "7K3QZ9WB"  # made up; not a real game seed


def _check(text, version=None, focus="shop_and_hand", seed=FAKE_SEED, words=frozenset({"DISCARDS", "STRAIGHT"}), **tags):
    return book.check_edit({"op": "add", "text": text, "phase": ["shop"], **tags}, version or dict(book.EMPTY), focus, seed, words)


def test_checks_keep_a_good_rule():
    kept, why = _check(GOOD)
    assert why == [] and kept["text"] == GOOD and kept["phase"] == ["shop"]
    # harness words that fit the seed alphabet are not seeds
    assert _check("when DISCARDS is 0 and a STRAIGHT is listed, do play it, because no dig is left")[1] == []


def test_checks_reject_seeds_positions_one_seed_facts_form_and_size():
    assert _check(GOOD + " " + FAKE_SEED.lower())[0] is None  # the game's own seed, any case
    assert _check(GOOD + " ABCDEFGH")[0] is None  # any 8-char seed-alphabet token
    assert _check(GOOD + " on SEED-N04")[0] is None
    assert _check("when the hand is weak, do discard [0, 2, 5], because it digs")[0] is None
    assert _check("when the hand is weak, do discard index 3, because it digs")[0] is None
    assert _check("when in Ante 2, do reroll, because the Ante 2 shop has Blueprint after one reroll")[0] is None
    assert _check("when the shop will have Blueprint, do keep $10, because it is strong")[0] is None
    assert _check("always buy xMult jokers because they are good")[0] is None  # form
    assert _check("when " + "x" * 300 + ", do y, because z")[0] is None  # size
    full = {**book.EMPTY, "rules": [{"id": f"R{i}", "text": f"when {i}, do {i}, because {i}", "phase": []} for i in range(book.MAX_RULES)]}
    assert _check(GOOD, version=full)[0] is None  # book full
    assert _check(GOOD, focus="shop", phase=["hand"])[0] is None  # shop-only focus
    dup = {**book.EMPTY, "rules": [{"id": "R1", "text": GOOD, "phase": []}]}
    assert _check(GOOD.upper().lower(), version=dup)[0] is None


def test_change_keeps_tags_it_leaves_out_and_bad_tags_are_rejected():
    v = {**book.EMPTY, "rules": [{"id": "R1", "text": GOOD, "phase": ["shop"], "ante": [3, 5], "top": True}]}
    new_text = GOOD.replace("first", "before planets")
    kept, why = book.check_edit({"op": "change", "id": "R1", "text": new_text}, v, "shop", FAKE_SEED, set())
    assert why == []
    merged, _ = book.apply_edits(v, [kept], 2)
    r = merged["rules"][0]
    assert (r["text"], r["phase"], r["ante"], r["top"]) == (new_text, ["shop"], [3, 5], True)
    assert book.check_edit({"op": "add", "text": GOOD, "phase": 3}, dict(book.EMPTY))[0] is None
    assert book.check_edit({"op": "add", "text": GOOD, "boss": 5}, dict(book.EMPTY))[0] is None


def test_at_most_three_edits_kept():
    edits = [{"op": "add", "text": GOOD.replace("Ante 5", f"Ante {n}"), "phase": ["shop"]} for n in range(4, 8)]
    kept, rejected = book.check_edits(edits, dict(book.EMPTY), "shop_and_hand", FAKE_SEED, set())
    assert len(kept) == 3 and len(rejected) == 1


def _update(store, label, read_hash, version, edits, summary="s"):
    kept, rejected = book.check_edits(edits, version, "shop_and_hand", FAKE_SEED, set())
    assert not rejected, rejected
    return {"label": label, "store": str(store), "book_hash": read_hash, "kept": kept, "summary": summary,
            "rule_stats": {}, "merged": False}


def test_merge_is_edit_by_edit_in_label_order(tmp_path):
    store = tmp_path / "store"
    h0, v0 = book.read_head(store)
    rule = lambda n: f"when rule {n} applies, do thing {n}, because reason {n}"  # noqa: E731
    first = _update(store, "SEED-A", h0, v0, [{"op": "add", "text": rule(1)}, {"op": "add", "text": rule(2)}])
    book.merge_update(first)
    h1, v1 = book.read_head(store)
    assert [r["id"] for r in v1["rules"]] == ["R1", "R2"]

    # Two parallel games both read v1; B changes R1 and drops R2, C changes R1 too and adds one
    b = _update(store, "SEED-B", h1, v1, [{"op": "change", "id": "R1", "text": rule(11)}, {"op": "drop", "id": "R2"}])
    c = _update(store, "SEED-C", h1, v1, [{"op": "change", "id": "R1", "text": rule(12)}, {"op": "add", "text": rule(3)}])
    paths = []
    for name, upd in (("b", b), ("c", c)):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(upd))
        paths.append(p)
    q = book.MergeQueue(2)
    assert q.done(1, paths[1]) == []  # C finished first: waits for B (label order)
    recs = q.done(0, paths[0])
    assert [r["label"] for r in recs] == ["SEED-B", "SEED-C"]
    _, v3 = book.read_head(store)
    # B's change and drop applied; C's change skipped (R1 was changed by B first); C's add applied
    assert [(r["id"], r["text"]) for r in v3["rules"]] == [("R1", rule(11)), ("R3", rule(3))]
    assert recs[1]["edits"][0]["result"].startswith("skipped")
    assert v3["games"] == 3 and len(v3["summaries"]) == 3
    # merging the same file again does nothing; old versions stay readable
    assert book.merge_file(paths[0]) is None
    assert book.read_version(store, h1)["rules"] == v1["rules"]


def test_rule_stats_count_blinds_won_and_lost():
    shown = {0: {"R1": 3}, 1: {"R1": 2, "R2": 1}, 2: {"R2": 4}}
    s = book.rule_stats(shown, blinds_won=2, won_game=False)
    assert s["R1"] == {"calls_shown": 5, "blinds_shown": 2, "blinds_won": 2, "blinds_lost": 0}
    assert s["R2"] == {"calls_shown": 5, "blinds_shown": 2, "blinds_won": 1, "blinds_lost": 1}


# --- Sol g4 review: seeds never written or sent by the book (G4-1, G4-2); cost always kept (G4-3)

import asyncio  # noqa: E402

import pytest  # noqa: E402
from openai.types.chat import ChatCompletion  # noqa: E402

from balatrollm import bot as botmod  # noqa: E402
from balatrollm.collector import Collector  # noqa: E402
from balatrollm.config import Task  # noqa: E402
from balatrollm.strategy import StrategyManager, StrategyManifest  # noqa: E402

MAP_SEED = "Q4R8T2WX"  # made up; stands for a seed in the private map


@pytest.fixture
def private_map(tmp_path, monkeypatch):
    p = tmp_path / "labels.json"
    p.write_text(json.dumps({"labels": {"ZZ": {"seed": MAP_SEED}}}))
    monkeypatch.setenv("BALATROLLM_SEED_LABELS", str(p))
    monkeypatch.setenv("BALATROLLM_BOOK_STORE", str(tmp_path / "store"))


def test_redactor_scrubs_own_private_and_seed_like_tokens(private_map):
    r = book.Redactor(FAKE_SEED, {"DISCARDS"})
    out = r(f"a {FAKE_SEED.lower()} b {MAP_SEED} c ABCDEFGH d DISCARDS")
    assert FAKE_SEED.lower() not in out.lower() and MAP_SEED not in out and "ABCDEFGH" not in out
    assert "DISCARDS" in out and out.count(book.REDACTED) == 3
    nested = r.obj({"edits": [{"boss": [MAP_SEED]}], MAP_SEED: 1})
    assert MAP_SEED not in json.dumps(nested)


def test_boss_tags_must_be_real_bosses():
    kept, why = _check(GOOD, boss=["the wall"])
    assert why == [] and kept["boss"] == ["The Wall"]
    assert _check(GOOD, boss=[FAKE_SEED])[0] is None
    assert _check(GOOD, boss=["The Nonsense"])[0] is None


def test_malformed_ante_rejects_only_that_edit():
    edits = [{"op": "add", "text": GOOD, "phase": ["shop"], "ante": {"lo": 1}}, {"op": "add", "text": GOOD, "phase": ["shop"]}]
    kept, rejected = book.check_edits(edits, dict(book.EMPTY), "shop_and_hand", FAKE_SEED, set())
    assert len(kept) == 1 and len(rejected) == 1


def _book_bot(tmp_path, reply_args):
    task = Task(model="openai/gpt-6-luna", seed="SEED-ZZ", deck="RED", stake="WHITE", strategy="mastery-book")
    b = botmod.Bot.__new__(botmod.Bot)
    b.task, b.strategy = task, StrategyManager("mastery-book")
    b.harness = StrategyManifest.from_file("mastery-book").harness
    b.model_config, b._history, b._rounds, b._last_hand_state = {}, [], [], None
    b._collector = Collector(task, tmp_path)
    b._finish_reason = "lost"

    class LLM:
        async def call(self, model, messages, tools, model_config=None):
            self.sent = json.dumps(messages)
            return ChatCompletion.model_validate({
                "id": "x", "object": "chat.completion", "created": 0, "model": model,
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                    "tool_calls": [{"id": "c", "type": "function", "function": {"name": "update_book", "arguments": json.dumps(reply_args)}}]}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110, "cost": 0.002}})

    b._llm = LLM()
    b._book_setup(tmp_path, FAKE_SEED)
    return b


def test_game_end_writes_no_seed_anywhere(tmp_path, private_map):
    reply = {"reasoning": f"seed {MAP_SEED}", "summary": f"lost {FAKE_SEED}",
             "edits": [{"op": "add", "text": GOOD + " " + FAKE_SEED, "phase": ["shop"]},
                       {"op": "add", "text": GOOD, "phase": ["shop"], "boss": [MAP_SEED]}]}
    b = _book_bot(tmp_path, reply)
    b._take_note(f"plan {MAP_SEED}", {"ante_num": 1, "round_num": 1, "state": "SHOP"})
    b._history.append({"method": "next_round", "params": {}, "reasoning": f"why {FAKE_SEED}", "ante": 1, "result": "ok"})
    asyncio.run(b._book_game_end())
    written = (b._collector.run_dir / "book_update.json").read_text()
    for secret in (FAKE_SEED, MAP_SEED):
        assert secret.lower() not in written.lower() and secret.lower() not in b._llm.sent.lower()
    upd = json.loads(written)
    assert upd["kept"] == [] and len(upd["rejected"]) == 2 and all(r["why"] for r in upd["rejected"])
    assert b._collector.extra_stats["book_update"]["cost"] == 0.002


def test_cost_and_file_kept_when_checks_fail(tmp_path, private_map, monkeypatch):
    b = _book_bot(tmp_path, {"reasoning": "r", "summary": "s", "edits": []})

    def boom(*a, **k):
        raise KeyError("x")

    monkeypatch.setattr(book, "check_edits", boom)
    asyncio.run(b._book_game_end())
    upd = json.loads((b._collector.run_dir / "book_update.json").read_text())
    assert upd["kept"] == [] and "checks failed" in upd["error"]
    assert b._collector.extra_stats["book_update"]["cost"] == 0.002


# --- Owner 2026-11-10: the book on the advice-off base (mastery-book-noadvice)


def test_book_noadvice_prompt_has_book_and_no_advice(tmp_path, monkeypatch):
    """The bot's real prompt for the new folder on 3 logged states: the book
    block comes first in the system message, the notebook is in MEMORY, and no
    advice marker appears anywhere (empty book, as at the start of W)."""
    from .test_pass4_noadvice import ADVICE_MARKERS, _states

    monkeypatch.setenv("BALATROLLM_BOOK_STORE", str(tmp_path / "store"))
    task = Task(model="openai/gpt-6-luna", seed="SEED-ZZ", deck="RED", stake="WHITE", strategy="mastery-book-noadvice")
    b = botmod.Bot.__new__(botmod.Bot)
    b.task, b.strategy = task, StrategyManager("mastery-book-noadvice")
    b.harness = StrategyManifest.from_file("mastery-book-noadvice").harness
    b.model_config, b._history, b._rounds, b._last_hand_state = {}, [], [], None
    b._last_error_msg = b._last_failed_msg = None
    b._collector = Collector(task, tmp_path)
    b._book_setup(tmp_path, FAKE_SEED)
    assert b._book["store"] == tmp_path / "store"

    class LLM:
        async def call(self, model, messages, tools, model_config=None):
            self.messages, self.tools = messages, tools
            return ChatCompletion.model_validate({
                "id": "x", "object": "chat.completion", "created": 0, "model": model,
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}]})

    class Game:
        async def call(self, method, params=None):
            return {}

    b._llm, b._balatro = LLM(), Game()
    for G in _states():
        asyncio.run(b._get_llm_response(G))
        system = b._llm.messages[0]["content"]
        assert system[0]["text"].startswith("# YOUR BOOK") and len(system) == 2
        text = "\n".join(p["text"] for m in b._llm.messages for p in m["content"])
        assert not [m for m in ADVICE_MARKERS if m in text], G["state"]
        assert "## Your notebook" in text
        assert all("note" in t["function"]["parameters"]["properties"] for t in b._llm.tools)


def test_book_stores_are_per_strategy(tmp_path, monkeypatch):
    monkeypatch.delenv("BALATROLLM_BOOK_STORE", raising=False)
    a = book.store_dir(tmp_path, "mastery-book", StrategyManifest.from_file("mastery-book").harness)
    n = book.store_dir(tmp_path, "mastery-book-noadvice", StrategyManifest.from_file("mastery-book-noadvice").harness)
    assert a != n and n == tmp_path / "runs" / "book" / "mastery-book-noadvice"

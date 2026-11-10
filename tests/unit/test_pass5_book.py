"""Pass 5 G2: the write-only log book (ported from pass-4 tests/unit/test_pass4_book.py, ef4698e).

Edit / write-up checks (seed-free, no hand positions, the rule form), the
label-order merge with one store per arm, and the write-up call at the end of
every game that started (incl. a consecutive_error_calls ending).
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from openai.types.chat import ChatCompletion

from balatrollm import book, ledger
from balatrollm import bot as botmod
from balatrollm.collector import Collector
from balatrollm.config import Config, Task

GOOD = "when XMULT_OWNED is 0 from Ante 3, buy an xMult joker first, because without one Ante 5 is lost"
FAKE_SEED = "7K3QZ9WB"  # made up; not a real game seed
MAP_SEED = "Q4R8T2WX"  # made up; stands for a seed in the private map
WORDS = frozenset({"DISCARDS", "STRAIGHT"})


@pytest.fixture(autouse=True)
def private_map(tmp_path, monkeypatch):
    """Never read the real private map: a made-up one for every test."""
    p = tmp_path / "labels.json"
    p.write_text(json.dumps({"labels": {"ZZ": {"seed": MAP_SEED}}}))
    monkeypatch.setenv("BALATROLLM_SEED_LABELS", str(p))


def _check(text, version=None):
    return book.check_edit({"op": "add", "text": text}, version or dict(book.EMPTY), FAKE_SEED, WORDS)


def test_checks_keep_a_good_rule():
    kept, why = _check(GOOD)
    assert why == [] and kept["text"] == GOOD
    assert _check("when DISCARDS is 0 and a STRAIGHT is listed, play it, because no dig is left")[1] == []


def test_checks_reject_seeds_positions_one_seed_facts_form_and_size():
    assert _check(GOOD + " " + FAKE_SEED.lower())[0] is None  # the game's own seed, any case
    assert _check(GOOD + " " + MAP_SEED)[0] is None  # a seed in the private map
    assert _check(GOOD + " ABCDEFGH")[0] is None  # any 8-char seed-alphabet token
    assert _check(GOOD + " on SEED-N04")[0] is None
    assert _check("when the hand is weak, discard [0, 2, 5], because it digs")[0] is None
    assert _check("when the hand is weak, discard index 3, because it digs")[0] is None
    assert _check("when in Ante 2, reroll, because the Ante 2 shop has Blueprint after one reroll")[0] is None
    _, why = _check("always buy xMult jokers because they are good")
    assert why == ['text must read "when <situation>, <action>, because <reason>"']
    assert _check("when " + "x" * 300 + ", do y, because z")[0] is None  # size
    full = {**book.EMPTY, "rules": [{"id": f"R{i}", "text": f"when {i}, do {i}, because {i}"} for i in range(book.MAX_RULES)]}
    assert _check(GOOD, version=full)[0] is None
    dup = {**book.EMPTY, "rules": [{"id": "R1", "text": GOOD}]}
    assert _check(GOOD.upper().lower(), version=dup)[0] is None


def test_at_most_three_edits_and_a_malformed_edit_rejects_only_itself():
    edits = [{"op": "add", "text": GOOD.replace("Ante 5", f"Ante {n}")} for n in range(4, 8)]
    kept, rejected = book.check_edits(edits, dict(book.EMPTY), FAKE_SEED, set())
    assert len(kept) == 3 and len(rejected) == 1
    kept, rejected = book.check_edits([{"op": "change", "id": "R9", "text": GOOD}, "x", {"op": "add", "text": GOOD}],
                                      dict(book.EMPTY), FAKE_SEED, set())
    assert len(kept) == 1 and len(rejected) == 2


def test_writeup_gets_seed_and_position_checks_only():
    ok = "Lost at Ante 3 to The Wall. The Ante 3 shop offered Blueprint; I bought it and sold Joker. SEED-N04 aside."
    text, problems = book.check_writeup(ok, FAKE_SEED, WORDS)
    assert book.writeup_ok(problems) and text == ok  # one-game facts and labels are fine in a write-up
    assert not book.writeup_ok(book.check_writeup(ok + " " + FAKE_SEED, FAKE_SEED, WORDS)[1])
    assert not book.writeup_ok(book.check_writeup(ok + " " + MAP_SEED.lower(), FAKE_SEED, WORDS)[1])
    assert not book.writeup_ok(book.check_writeup("I played cards 0, 2 and 4", FAKE_SEED, WORDS)[1])
    long_text, problems = book.check_writeup("x " * 600, FAKE_SEED, WORDS)
    assert len(long_text) == book.MAX_WRITEUP_CHARS and book.writeup_ok(problems) and problems


def test_redactor_scrubs_own_private_and_seed_like_tokens():
    r = book.Redactor(FAKE_SEED, {"DISCARDS"})
    out = r(f"a {FAKE_SEED.lower()} b {MAP_SEED} c ABCDEFGH d DISCARDS")
    assert FAKE_SEED.lower() not in out.lower() and MAP_SEED not in out and "ABCDEFGH" not in out
    assert "DISCARDS" in out and out.count(book.REDACTED) == 3
    assert MAP_SEED not in json.dumps(r.obj({"edits": [{"text": [MAP_SEED]}], MAP_SEED: 1}))


def test_store_is_per_arm_and_versions_hold_no_summaries(tmp_path):
    assert book.store_dir(tmp_path, "C-on") == tmp_path / "runs" / "book" / "C-on"
    assert book.store_dir(tmp_path, "C-on") != book.store_dir(tmp_path, "C-off")
    with pytest.raises(ValueError):
        book.store_dir(tmp_path, "../x")
    h, v = book.read_head(tmp_path / "s")
    assert h == book.EMPTY_HASH and set(v) == {"rules", "next_id", "games"}


def _update(store, label, read_hash, version, edits):
    kept, rejected = book.check_edits(edits, version, FAKE_SEED, set())
    assert not rejected, rejected
    return {"label": label, "store": str(store), "read": read_hash, "kept": kept, "finish_reason": "lost",
            "final_ante": 3, "writeup": f"write-up {label}", "merged": False}


def _rule(n):
    return f"when rule {n} applies, do thing {n}, because reason {n}"


def test_merge_is_edit_by_edit_in_label_order(tmp_path):
    store = tmp_path / "store"
    h0, v0 = book.read_head(store)
    book.merge_update(_update(store, "SEED-A", h0, v0, [{"op": "add", "text": _rule(1)}, {"op": "add", "text": _rule(2)}]))
    h1, v1 = book.read_head(store)
    assert [r["id"] for r in v1["rules"]] == ["R1", "R2"]

    # Two parallel games both read v1; B changes R1 and drops R2, C changes R1 too and adds one
    b = _update(store, "SEED-B", h1, v1, [{"op": "change", "id": "R1", "text": _rule(11)}, {"op": "drop", "id": "R2"}])
    c = _update(store, "SEED-C", h1, v1, [{"op": "change", "id": "R1", "text": _rule(12)}, {"op": "add", "text": _rule(3)}])
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
    assert [(r["id"], r["text"]) for r in v3["rules"]] == [("R1", _rule(11)), ("R3", _rule(3))]
    assert recs[1]["edits"][0]["result"].startswith("skipped")
    assert v3["games"] == 3 and "summaries" not in v3
    rows = [json.loads(x) for x in (store / "writeups.jsonl").read_text().splitlines()]
    assert [(r["label"], r["game"], r["writeup"]) for r in rows] == [
        ("SEED-A", 1, "write-up SEED-A"), ("SEED-B", 2, "write-up SEED-B"), ("SEED-C", 3, "write-up SEED-C")]
    assert rows[2]["merge"][0]["result"].startswith("skipped") and rows[1]["base"] == rows[0]["new"]
    assert book.merge_file(paths[0]) is None  # merging the same file again does nothing
    assert book.read_version(store, h1)["rules"] == v1["rules"]


def test_interleaved_arms_merge_in_label_order_per_store(tmp_path):
    """One queue over both arms (on, off, on, off): each store gets its own games in label order."""
    on, off = tmp_path / "C-on", tmp_path / "C-off"
    paths = []
    for i, (label, store) in enumerate([("SEED-N61", on), ("SEED-N61", off), ("SEED-N62", on), ("SEED-N62", off)]):
        h, v = book.read_head(store)
        p = tmp_path / f"{i}.json"
        p.write_text(json.dumps(_update(store, label, h, v, [{"op": "add", "text": _rule(i)}])))
        paths.append(p)
    q = book.MergeQueue(4)
    assert q.done(3, paths[3]) == [] and q.done(2, paths[2]) == []
    q.done(1, None)  # off N61 crashed before its game started: no update
    assert [r["label"] for r in q.done(0, paths[0])] == ["SEED-N61", "SEED-N62", "SEED-N62"]
    for store, labels in ((on, ["SEED-N61", "SEED-N62"]), (off, ["SEED-N62"])):
        rows = [json.loads(x) for x in (store / "writeups.jsonl").read_text().splitlines()]
        assert [r["label"] for r in rows] == labels and [r["game"] for r in rows] == list(range(1, len(labels) + 1))


################################################################################
# The game-end call
################################################################################


def _states() -> list[dict[str, Any]]:
    from .test_pass4_noadvice import _states as states

    return states()


def _rows() -> list[dict[str, Any]]:
    """Ledger rows as the bot writes them, on the logged fixture states."""
    rows = []
    for G in _states():
        G = {**G, "seed": FAKE_SEED}  # the ledger must drop it
        row = ledger.pre_row(G, [], [], {})
        if G["state"] == "SELECTING_HAND":
            n = min(3, len(G["hand"]["cards"]))
            ledger.finish_row(row, G, {"reasoning": "r", "cards": list(range(n))}, "play", {
                "result": "ok", "summary": "played Pair for 120 (now 120/300, 3 hands left)"}, G)
        else:
            ledger.finish_row(row, G, {"reasoning": "r"}, "next_round", {"result": "ok"}, G)
        rows.append(json.loads(json.dumps(row, default=str)))
    return rows


def _reply(args: dict[str, Any], usage_cost: float = 0.002) -> ChatCompletion:
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 0, "model": "gpt-6-luna",
        "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
            "tool_calls": [{"id": "c", "type": "function", "function": {"name": "write_book", "arguments": json.dumps(args)}}]}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110, "cost": usage_cost}})


class FakeLLM:
    def __init__(self, args: dict[str, Any]) -> None:
        self.args, self.calls, self.resets = args, [], 0

    def reset_timeout_counter(self) -> None:
        self.resets += 1

    async def call(self, model, messages, tools, model_config=None):
        self.calls.append({"messages": messages, "tools": tools})
        return _reply(self.args)


def _bot(tmp_path, args, strategy="mastery-noadvice", seed=FAKE_SEED) -> botmod.Bot:
    config = Config(model=["openai/gpt-6-luna"], seed=[seed], strategy=[strategy], book={strategy: "C-off"})
    task = config.generate_tasks()[0]
    b = botmod.Bot(task, config)
    b._llm = FakeLLM(args)
    return b


def _ready(b: botmod.Bot, tmp_path: Path, rows: list[dict[str, Any]]) -> None:
    """A bot that played (collector, store, ledger rows) without play()."""
    b._collector = Collector(b.task, tmp_path)
    b._book_store = book.store_dir(tmp_path, b._book_arm)
    b._book_seed = FAKE_SEED
    b._game_started = True
    for r in rows:
        b._collector.write_decision(r)


def test_digest_names_cards_and_has_no_seed_label_or_suggestion(tmp_path):
    rows = _rows()
    text, summary, ante = book.game_digest(rows, [], [], {**rows[-1]["G"], "seed": FAKE_SEED}, "lost")
    hand = next(r for r in rows if r["state"] == "SELECTING_HAND")
    names = hand["chosen"]["card_names"]
    assert names and all(n in text for n in names) and "played Pair for 120" in text
    assert FAKE_SEED not in text and "SEED-" not in text and "uggest" not in text
    assert not book.text_problems(text, FAKE_SEED, book.known_words(text.replace(FAKE_SEED, "")), one_seed=False)
    assert "# THE END" in text and "What lost it" in text and ante == rows[-1]["G"]["ante_num"]
    small, _, _ = book.game_digest(rows * 40, [], [], None, "lost", max_chars=3000)
    assert len(small) <= 3000 and "# THE END" in small


def test_writeup_on_consecutive_error_ending_through_play(tmp_path):
    """play()'s finally makes the write-up call on a consecutive_error_calls
    ending (BotError still propagates), and writes no seed anywhere."""
    reply = {"reasoning": f"seed {MAP_SEED}", "writeup": f"Lost at Ante 2 to The Hook; bought Blueprint. {FAKE_SEED}",
             "edits": [{"op": "add", "text": GOOD}, {"op": "add", "text": GOOD + " " + MAP_SEED}]}
    b = _bot(tmp_path, reply)
    rows = _rows()

    class Game:
        async def call(self, method, params=None):
            return {**rows[0]["G"], "seed": FAKE_SEED} if method == "start" else {"state": "MENU"}

    async def loop(gamestate):
        for r in rows:
            b._collector.write_decision(r)
        b._end_state = gamestate
        b._finish_reason = "consecutive_error_calls"
        raise botmod.BotError("Too many consecutive error calls")

    b._balatro = Game()
    b._run_game_loop = loop
    with pytest.raises(botmod.BotError):
        asyncio.run(b.play(tmp_path))
    assert b._llm.resets == 1 and len(b._llm.calls) == 1
    upd = json.loads(b.book_update_path.read_text())
    assert upd["finish_reason"] == "consecutive_error_calls" and upd["arm"] == "C-off"
    assert upd["cost"] == 0.002 and upd["tokens_in"] == 100 and upd["error"] is None
    assert upd["writeup"] is None and upd["writeup_problems"] == ["contains a seed"]
    assert len(upd["kept"]) == 1 and len(upd["rejected"]) == 1
    sent = json.dumps(b._llm.calls[0])
    written = upd and b.book_update_path.read_text()
    for secret in (FAKE_SEED, MAP_SEED):
        assert secret.lower() not in written.lower() and secret.lower() not in sent.lower()
    assert "SEED-" not in json.dumps(b._llm.calls[0]["messages"])
    task = json.loads((b._collector.run_dir / "task.json").read_text())
    assert task["book"] == {"arm": "C-off", "store": str(tmp_path / "runs" / "book" / "C-off")}
    log = (b._collector.run_dir / "run.log").read_text()
    assert log.index("WRITEUP begin") < log.index("WRITEUP end")
    assert not (b._collector.run_dir / "responses.jsonl").exists()  # never in the game's calls / stats
    # merged by the executor's queue into the arm's store
    book.MergeQueue(1).done(0, b.book_update_path)
    row = json.loads((tmp_path / "runs" / "book" / "C-off" / "writeups.jsonl").read_text())
    assert row["finish_reason"] == "consecutive_error_calls" and row["game"] == 1


def test_no_writeup_on_cancel_unstarted_game_or_book_off(tmp_path):
    b = _bot(tmp_path, {})
    b._collector, b._game_started = Collector(b.task, tmp_path), True
    assert b._writeup_due(botmod.BotError) and b._writeup_due(None)
    assert not b._writeup_due(asyncio.CancelledError) and not b._writeup_due(KeyboardInterrupt)
    b._game_started = False
    assert not b._writeup_due(None)
    off = botmod.Bot(Task(model="openai/gpt-6-luna", seed="SEED-ZZ", deck="RED", stake="WHITE", strategy="mastery"),
                     Config(model=["openai/gpt-6-luna"], strategy=["mastery"]))
    off._collector, off._game_started, off._llm = b._collector, True, b._llm
    assert not off._writeup_due(None)


def test_cost_and_file_kept_when_checks_fail(tmp_path, monkeypatch):
    b = _bot(tmp_path, {"reasoning": "r", "writeup": "w", "edits": []})
    _ready(b, tmp_path, _rows())
    b._finish_reason = "lost"

    def boom(*a, **k):
        raise KeyError("x")

    monkeypatch.setattr(book, "check_edits", boom)
    asyncio.run(b._book_writeup())
    upd = json.loads(b.book_update_path.read_text())
    assert upd["kept"] == [] and "checks failed" in upd["error"] and upd["cost"] == 0.002


def test_failed_call_still_writes_the_file_and_counts_the_game(tmp_path):
    b = _bot(tmp_path, {})

    async def fail(*a, **k):
        raise RuntimeError("api down")

    b._llm.call = fail
    _ready(b, tmp_path, _rows())
    b._finish_reason = "llm_abort"
    asyncio.run(b._book_writeup())
    upd = json.loads(b.book_update_path.read_text())
    assert "api down" in upd["error"] and upd["kept"] == []
    book.merge_file(b.book_update_path)
    assert book.read_head(b._book_store)[1]["games"] == 1


def test_config_book_key_is_loaded_and_validated(tmp_path):
    y = tmp_path / "c.yaml"
    y.write_text("model: m\nstrategy: [mastery, mastery-noadvice]\nbook: {mastery: C-on, mastery-noadvice: C-off}\n")
    c = Config.load(yaml_path=y)
    c.validate()
    assert c.book == {"mastery": "C-on", "mastery-noadvice": "C-off"}
    for bad in ("book: {default: C-on}", "book: {mastery: C-on, mastery-noadvice: C-on}", "book: [mastery]",
                "book: {mastery: ../x}"):
        y.write_text("model: m\nstrategy: [mastery, mastery-noadvice]\n" + bad + "\n")
        with pytest.raises(ValueError):
            Config.load(yaml_path=y).validate()

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

"""Tests for the private seed generator (seeds.py)."""

import json
from pathlib import Path

import pytest

from balatrollm import seeds


@pytest.fixture
def seed_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "seed_labels.json"
    monkeypatch.setenv("BALATROLLM_SEED_LABELS", str(path))
    return path


class TestGenerate:
    def test_alphabet_and_length(self) -> None:
        for _ in range(2000):
            seed = seeds.generate(set())
            assert len(seed) == 8
            assert set(seed) <= set(seeds.ALPHABET)

    def test_alphabet_matches_game(self) -> None:
        assert "0" not in seeds.ALPHABET and "O" not in seeds.ALPHABET
        assert len(seeds.ALPHABET) == 34

    def test_no_repeats_across_many_draws(self) -> None:
        drawn: set[str] = set()
        for _ in range(5000):
            seed = seeds.generate(drawn)
            assert seed not in drawn
            drawn.add(seed)

    def test_regenerates_on_collision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        picks = iter("A" * 8 + "B" * 8)
        monkeypatch.setattr(seeds.secrets, "choice", lambda _alphabet: next(picks))
        assert seeds.generate({"AAAAAAAA"}) == "BBBBBBBB"


class TestNewRandom:
    def test_records_seed_under_next_label(self, seed_map: Path) -> None:
        label_a, seed_a = seeds.new_random()
        label_b, seed_b = seeds.new_random()
        assert (label_a, label_b) == ("SEED-A", "SEED-B")
        assert seed_a != seed_b
        labels = json.loads(seed_map.read_text())["labels"]
        assert labels == {"A": {"seed": seed_a}, "B": {"seed": seed_b}}
        assert seeds.resolve(label_a) == seed_a

    def test_skips_seeds_already_in_map(
        self, seed_map: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed_map.write_text(json.dumps({"labels": {"A": {"seed": "AAAAAAAA"}}}))
        picks = iter("A" * 8 + "C" * 8)
        monkeypatch.setattr(seeds.secrets, "choice", lambda _alphabet: next(picks))
        assert seeds.new_random() == ("SEED-B", "CCCCCCCC")

    def test_started_on(self) -> None:
        assert seeds.started_on("ABCDEFGH", {"seed": "ABCDEFGH"})
        assert not seeds.started_on("ABCDEFGH", {"seed": "ABCDEFGZ"})
        assert not seeds.started_on("ABCDEFGH", {})

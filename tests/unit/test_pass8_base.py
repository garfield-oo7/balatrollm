"""Pass 8 seam: arm J (mastery-noadvice-line-shop) = arm I (mastery-noadvice-line) + harness.shop_facts."""

import json
from pathlib import Path

import pytest

STRATEGIES = Path(__file__).parents[2] / "src" / "balatrollm" / "strategies"
COPIED = ("GAMESTATE.md.jinja", "MEMORY.md.jinja", "STRATEGY.md.jinja", "TOOLS.json")


def test_shop_strategy_is_a_byte_copy_of_line() -> None:
    i, j = STRATEGIES / "mastery-noadvice-line", STRATEGIES / "mastery-noadvice-line-shop"
    assert sorted(p.name for p in j.iterdir()) == sorted(p.name for p in i.iterdir())
    for name in COPIED:
        assert (i / name).read_bytes() == (j / name).read_bytes(), name
    mi = json.loads((i / "manifest.json").read_text())
    mj = json.loads((j / "manifest.json").read_text())
    assert mj["harness"].pop("shop_facts") is True
    assert not mi["harness"].get("shop_facts")
    mi["harness"].pop("shop_facts", None)
    assert mi["harness"] == mj["harness"]
    for k in ("name", "description"):
        mi.pop(k), mj.pop(k)
    assert mi == mj


def test_shop_facts_is_not_a_run_config_key(tmp_path: Path) -> None:
    from balatrollm import config

    cfg = tmp_path / "c.yaml"
    cfg.write_text("shop_facts: true\n")
    with pytest.raises(ValueError, match="shop_facts"):
        config._load_from_yaml(cfg)

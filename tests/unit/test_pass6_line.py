"""Pass 6 H2: the reworked dig-or-play fact line (arm F, strategy mastery-noadvice-line)."""

import json
from pathlib import Path

STRATEGIES = Path(__file__).parents[2] / "src" / "balatrollm" / "strategies"
COPIED = ("GAMESTATE.md.jinja", "MEMORY.md.jinja", "STRATEGY.md.jinja", "TOOLS.json")


def test_line_strategy_is_a_byte_copy_of_noadvice() -> None:
    e, f = STRATEGIES / "mastery-noadvice", STRATEGIES / "mastery-noadvice-line"
    assert sorted(p.name for p in f.iterdir()) == sorted(p.name for p in e.iterdir())
    for name in COPIED:
        assert (e / name).read_bytes() == (f / name).read_bytes(), name
    me = json.loads((e / "manifest.json").read_text())
    mf = json.loads((f / "manifest.json").read_text())
    assert mf["harness"].pop("dig_line") is True
    assert "dig_line" not in me["harness"] or me["harness"]["dig_line"] is False
    me["harness"].pop("dig_line", None)
    assert me["harness"] == mf["harness"]
    for k in ("name", "description"):
        me.pop(k), mf.pop(k)
    assert me == mf

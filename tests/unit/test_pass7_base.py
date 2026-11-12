"""Pass 7 base fixes (both arms): B4 legacy G3 guard, B6 silent line logging (arm G)."""

from typing import Any

from .test_analysis import joker, make_state


def _strip(row: dict[str, Any]) -> dict[str, Any]:
    adv = dict(row.get("advice") or {})
    adv.pop("dig_line", None)
    adv.pop("dig_line_logged_only", None)
    return {**row, "advice": adv}


def test_b6_ledger_logs_line_silently_and_keeps_every_other_field() -> None:
    from balatrollm import ledger

    G = make_state("H_Q C_Q S_9 H_8 D_8 C_4 S_2 C_2", [joker("j_raised_fist", "Raised Fist")],
                   hands_left=2, discards_left=2, chips=0)
    off = ledger.pre_row(G, [], [], {})
    on = ledger.pre_row(G, [], [], {"dig_line_log": True})
    shown = ledger.pre_row(G, [], [], {"dig_line": True, "dig_line_log": True})
    assert "dig_line" not in off["advice"]
    assert _strip(on) == off  # B6: every field except the logged line equals flag-off
    assert on["rendered"] == off["rendered"] and on["rendered"]["dig_line"] is False
    assert "dig_line_text" not in on["rendered"]
    assert on["advice"]["dig_line_logged_only"] is True
    assert on["advice"]["dig_line"] == shown["advice"]["dig_line"]  # same fields as the line arm
    assert on["advice"]["dig_line"]["comparison"] is True


def test_b6_line_only_never_runs_legacy_g3() -> None:
    from balatrollm import analysis

    G = make_state("H_Q C_Q S_9 H_8 D_8 C_4 S_2 C_2", [joker("j_raised_fist", "Raised Fist")],
                   hands_left=2, discards_left=2, chips=0)
    off = analysis.play_advice(G)
    only = analysis.play_advice(G, line_only=True)
    assert only["dig_line"] is None and off["line"] is None and only["line"]["text"]
    assert only["action"] == off["action"] and only["discard"] == off["discard"]
    assert only["win_chance"] == off["win_chance"]


def test_b4_legacy_g3_error_keeps_the_rest(monkeypatch: Any) -> None:
    from balatrollm import analysis

    G = make_state("H_Q C_Q S_9 H_8 D_8 C_4 S_2 C_2", [joker("j_raised_fist", "Raised Fist")],
                   hands_left=2, discards_left=2, chips=0)

    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("x")

    monkeypatch.setattr(analysis, "dig_or_play", boom)
    A = analysis.play_advice(G, dig=True)
    assert A["dig_line"] is None and A["action"] and A["plays"]

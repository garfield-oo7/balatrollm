"""Results ledger (pass 4, B0c): one row per Luna call in ``decisions.jsonl``.

Read-only for play. Every row records what the harness computed for the
decision (STATUS / forecast, the listed plays, the suggested action and
discard, shop SCORE per offer, the swap plan for Luna's chosen buy) whether or
not the strategy renders it (advice-off arm: "what the harness would have
done" is a column, not a reconstruction), what Luna chose, what was executed
(harness swap-sell, veto, game rejection) and the money before / after. The
pre-decision gamestate (without its seed) is kept so analysers can be re-run.

All analysis functions used here are pure (state-seeded samplers, cached by a
hash of the state), so computing them again cannot change play.
"""

from __future__ import annotations

import logging
from typing import Any

from .analysis import _area_cards, card_name, play_advice, run_status, shop_impact, swap_plan

logger = logging.getLogger(__name__)

SHOP_STATES = ("SHOP", "SMODS_BOOSTER_OPENED")
LEDGER_VERSION = 1


def _safe(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # the ledger must never break a game
        return {"ledger_error": f"{type(e).__name__}: {e}"}


def _no_seed(G: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in G.items() if k != "seed"}


def _names(G: dict[str, Any], area: str, idx: Any) -> list[str] | None:
    """Card names for indices into an area (cards named, never positions)."""
    if not isinstance(idx, list):
        return None
    cards = _area_cards(G, area)
    out = []
    for i in idx:
        try:
            out.append(card_name(cards[int(i)]))
        except (IndexError, TypeError, ValueError):
            out.append("?")
    return out


def _label(G: dict[str, Any], area: str, i: Any) -> str | None:
    cards = _area_cards(G, area)
    try:
        c = cards[int(i)]
    except (IndexError, TypeError, ValueError):
        return None
    return str(c.get("label") or c.get("key"))


def _plays(advice: dict[str, Any], G: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for p in advice.get("plays") or []:
        if not isinstance(p, dict):
            continue
        row = {k: p.get(k) for k in ("hand", "score", "floor", "wins", "cards") if k in p}
        row["card_names"] = _names(G, "hand", p.get("cards"))
        out.append(row)
    return out


def _action(a: Any, G: dict[str, Any]) -> Any:
    if not isinstance(a, dict):
        return a
    out = dict(a)
    if isinstance(a.get("cards"), list):
        out["card_names"] = _names(G, "hand", a["cards"])
    return out


def pre_row(
    G: dict[str, Any],
    rounds: list[dict[str, Any]],
    history: list[dict[str, Any]],
    flags: dict[str, Any],
) -> dict[str, Any]:
    """The pre-decision part of a row (computed after the prompt is rendered)."""
    state = G.get("state")
    status = _safe(run_status, G, rounds, history)
    row: dict[str, Any] = {
        "v": LEDGER_VERSION,
        "state": state,
        "ante": G.get("ante_num"),
        "round": G.get("round_num"),
        "money_before": G.get("money"),
        "rendered": {
            "suggest_action": bool(flags.get("suggest_action")),
            "suggest_discard": bool(flags.get("suggest_discard", True)),
            "dig_line": bool(flags.get("dig_line")),
        },
        "status": status if "ledger_error" in status else {
            k: status.get(k)
            for k in (
                "status", "hands_needed", "next_kind", "next_name", "sit_target", "sit_per", "next_hands",
                "safety_net", "spendable", "effective_floor", "main_hand", "xmult_owned", "jokers", "joker_limit",
            )
        },
    }
    if state == "SELECTING_HAND":
        dig = bool(flags.get("dig_line"))
        adv = _safe(play_advice, G, dig=dig)
        line_error = None
        if dig and "ledger_error" in adv:
            # pass 6: a failure in the line's code never costs the row its
            # progress / plays (the measure): retry without the line
            line_error = adv
            adv = _safe(play_advice, G)
        if "ledger_error" in adv:
            row["advice"] = adv
        else:
            row["advice"] = {
                "progress": adv.get("progress"),
                "plays": _plays(adv, G),
                "suggested_action": _action(adv.get("action"), G),
                "suggested_discard": _action({"cards": adv.get("discard")} if adv.get("discard") else None, G),
            }
            if dig:
                row["advice"]["dig_line"] = line_error or _safe(_dig_fields, adv, G)
    elif state in SHOP_STATES:
        imp = _safe(shop_impact, G)
        row["shop_impact"] = imp
    row["G"] = _no_seed(G)
    return row


def _dig_fields(adv: dict[str, Any], G: dict[str, Any]) -> dict[str, Any] | None:
    """pass 5 G3: the fact line's ledger fields (None: no line for this state)."""
    line = adv.get("dig_line")
    return line and {
        "play_pct": line["x_pct"],
        "dig_pct": line["y_pct"],
        "play_chance": line["play"]["chance"],
        "dig_chance": line["dig"]["chance"],
        "play_hand": line["play"]["hand"],
        "play_cards": _names(G, "hand", line["play"]["cards"]),
        "dig_cards": _names(G, "hand", line["dig"]["discard"]),
        "dig_better": line["dig_better"],
        "samples": line["samples"],
        "hands_left": line["hands_left"],
        "discards_left": line["discards_left"],
    }


def finish_row(
    row: dict[str, Any],
    before: dict[str, Any],
    fn_args: dict[str, Any] | None,
    fn_name: str | None,
    outcome: dict[str, Any],
    after: dict[str, Any] | None,
) -> dict[str, Any]:
    """Luna's choice, what was executed and the money after."""
    params = {k: v for k, v in (fn_args or {}).items() if k != "reasoning"}
    chosen: dict[str, Any] = {"tool": fn_name, "params": params}
    if fn_name in ("play", "discard"):
        chosen["card_names"] = _names(before, "hand", params.get("cards"))
    elif fn_name == "buy":
        for area, key in (("shop", "card"), ("vouchers", "voucher"), ("packs", "pack")):
            if key in params:
                chosen["item"] = _label(before, area, params[key])
    elif fn_name == "sell":
        for area, key in (("jokers", "joker"), ("consumables", "consumable")):
            if key in params:
                chosen["item"] = _label(before, area, params[key])
    elif fn_name == "pack" and "card" in params:
        chosen["item"] = _label(before, "pack", params["card"])
    row["reasoning"] = str((fn_args or {}).get("reasoning", ""))
    row["chosen"] = chosen
    if fn_name and before.get("state") in SHOP_STATES:
        # computed for every shop decision, rendered / executed only under auto_swap_jokers
        # the advice-on counterfactual: computed as if pack swaps were allowed (A1 turns
        # sell_in_pack off for execution only; Sol g1 #2)
        luna = {**(before.get("luna") or {}), "sell_in_pack": True}
        row["swap_plan"] = _safe(swap_plan, {**before, "luna": luna}, fn_name, params)
    row["outcome"] = outcome
    row["money_after"] = (after or {}).get("money")
    row["state_after"] = (after or {}).get("state")
    return row

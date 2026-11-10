"""Deterministic game analysis helpers exposed to strategy templates.

Small LLMs are bad at combinatorics and arithmetic. These pure functions do that
work so a template can show the model enumerated options (best plays with
estimated scores, draw odds, money floors, ...) and let it pick among them.

All functions take the raw BalatroBot gamestate dict (``G``) and never mutate it.
They are registered as Jinja globals by :class:`balatrollm.strategy.StrategyManager`
and are only used by strategies whose templates call them.

Fairness: the remaining deck (``G.cards``) is only ever summarised as counts,
never in draw order, and face-down cards are never revealed.
"""

import hashlib
import json
import math
import random
import re
from collections import Counter, OrderedDict
from collections.abc import Iterable
from itertools import combinations, combinations_with_replacement, permutations
from math import comb, perm
from pathlib import Path
from typing import Any

from . import knowledge

################################################################################
# Static game data
################################################################################

RANKS = "23456789TJQKA"
RANK_VALUE = {r: i + 2 for i, r in enumerate(RANKS)}  # A = 14 (high)
CHIP_VALUE = {r: min(RANK_VALUE[r], 10) for r in RANKS} | {"A": 11}
RANK_NAME = {"T": "10", "J": "Jack", "Q": "Queen", "K": "King", "A": "Ace"}
SUIT_NAME = {"H": "Hearts", "D": "Diamonds", "C": "Clubs", "S": "Spades"}
FACE_RANKS = {"J", "Q", "K"}

# Regular poker hands, strongest first, with planet increments per level.
HAND_ORDER = [
    "Flush Five",
    "Flush House",
    "Five of a Kind",
    "Straight Flush",
    "Four of a Kind",
    "Full House",
    "Flush",
    "Straight",
    "Three of a Kind",
    "Two Pair",
    "Pair",
    "High Card",
]
SECRET_HANDS = {"Flush Five", "Flush House", "Five of a Kind"}
LEVEL_UP = {  # (chips, mult) gained per level
    "Flush Five": (50, 3),
    "Flush House": (40, 4),
    "Five of a Kind": (35, 3),
    "Straight Flush": (40, 4),
    "Four of a Kind": (30, 3),
    "Full House": (25, 2),
    "Flush": (15, 2),
    "Straight": (30, 3),
    "Three of a Kind": (20, 2),
    "Two Pair": (20, 1),
    "Pair": (15, 1),
    "High Card": (10, 1),
}

# Which hand types "contain" a given hand (for Jolly, The Duo, ...).
CONTAINS = {
    "Pair": {
        "Pair",
        "Two Pair",
        "Three of a Kind",
        "Full House",
        "Four of a Kind",
        "Five of a Kind",
        "Flush House",
        "Flush Five",
    },
    "Two Pair": {"Two Pair", "Full House", "Flush House"},
    "Three of a Kind": {
        "Three of a Kind",
        "Full House",
        "Four of a Kind",
        "Five of a Kind",
        "Flush House",
        "Flush Five",
    },
    "Four of a Kind": {"Four of a Kind", "Five of a Kind", "Flush Five"},
    "Straight": {"Straight", "Straight Flush"},
    "Flush": {"Flush", "Straight Flush", "Flush House", "Flush Five"},
}

# key -> (required hand type, +chips, +mult, xmult)
HAND_TYPE_JOKERS = {
    "j_jolly": ("Pair", 0, 8, 1.0),
    "j_zany": ("Three of a Kind", 0, 12, 1.0),
    "j_mad": ("Two Pair", 0, 10, 1.0),
    "j_crazy": ("Straight", 0, 12, 1.0),
    "j_droll": ("Flush", 0, 10, 1.0),
    "j_sly": ("Pair", 50, 0, 1.0),
    "j_wily": ("Three of a Kind", 100, 0, 1.0),
    "j_clever": ("Two Pair", 80, 0, 1.0),
    "j_devious": ("Straight", 100, 0, 1.0),
    "j_crafty": ("Flush", 80, 0, 1.0),
    "j_duo": ("Pair", 0, 0, 2.0),
    "j_trio": ("Three of a Kind", 0, 0, 3.0),
    "j_family": ("Four of a Kind", 0, 0, 4.0),
    "j_order": ("Straight", 0, 0, 3.0),
    "j_tribe": ("Flush", 0, 0, 2.0),
}
SUIT_MULT_JOKERS = {
    "j_greedy_joker": "D",
    "j_lusty_joker": "H",
    "j_wrathful_joker": "S",
    "j_gluttenous_joker": "C",
}
# Jokers whose effect is handled per scoring card (never via "Currently ...").
PER_CARD_JOKERS = {
    "j_scary_face",
    "j_smiley",
    "j_scholar",
    "j_fibonacci",
    "j_even_steven",
    "j_odd_todd",
    "j_walkie_talkie",
    "j_arrowhead",
    "j_onyx_agate",
    "j_photograph",
    "j_triboulet",
    "j_bloodstone",
    "j_ancient",
    "j_idol",
    "j_rough_gem",
    "j_business",
    "j_golden_ticket",
    "j_ticket",
}
# Jokers handled elsewhere (classification, retriggers, held cards) or with no
# effect on the score of the played hand.
STRUCTURAL_JOKERS = {
    "j_four_fingers",
    "j_shortcut",
    "j_smeared",
    "j_splash",
    "j_pareidolia",
    "j_hack",
    "j_sock_and_buskin",
    "j_hanging_chad",
    "j_dusk",
    "j_selzer",
    "j_mime",
    "j_baron",
    "j_shoot_the_moon",
    "j_raised_fist",
}
# Held-card jokers whose Blueprint / Brainstorm copies the scorer counts
HELD_COPIED = {"j_baron", "j_mime", "j_shoot_the_moon"}
NO_SCORE_JOKERS = {
    "j_credit_card",
    "j_chaos",
    "j_delayed_grat",
    "j_egg",
    "j_burglar",
    "j_sixth_sense",
    "j_superposition",
    "j_todo_list",
    "j_faceless",
    "j_marble",
    "j_8_ball",
    "j_space",
    "j_dna",
    "j_seance",
    "j_riff_raff",
    "j_vagabond",
    "j_cloud_9",
    "j_rocket",
    "j_midas_mask",
    "j_luchador",
    "j_gift",
    "j_turtle_bean",
    "j_reserved_parking",
    "j_mail",
    "j_to_the_moon",
    "j_hallucination",
    "j_juggler",
    "j_drunkard",
    "j_golden",
    "j_diet_cola",
    "j_trading",
    "j_mr_bones",
    "j_troubadour",
    "j_certificate",
    "j_ring_master",
    "j_merry_andy",
    "j_oops",
    "j_matador",
    "j_stuntman",
    "j_invisible",
    "j_satellite",
    "j_cartomancer",
    "j_astronomer",
    "j_burnt",
    "j_chicot",
    "j_perkeo",
    "j_ceremonial",
    "j_madness",
}
# Square Joker writes "(Currently 0 Chips)" with no sign: read it as "+"
CURRENTLY = re.compile(
    r"Currently\s*([+X×x]?)\s*\$?(\d+(?:\.\d+)?)\s*(Mult|Chips)", re.IGNORECASE
)
FIRST_PLUS = re.compile(r"\+(\d+(?:\.\d+)?)\s*(Mult|Chips)", re.IGNORECASE)

# Consumables that need hand-card targets: key -> (min, max)
CONSUMABLE_TARGETS = {
    "c_magician": (1, 2),
    "c_empress": (1, 2),
    "c_heirophant": (1, 2),
    "c_lovers": (1, 1),
    "c_chariot": (1, 1),
    "c_justice": (1, 1),
    "c_strength": (1, 2),
    "c_hanged_man": (1, 2),
    "c_death": (2, 2),
    "c_devil": (1, 1),
    "c_tower": (1, 1),
    "c_star": (1, 3),
    "c_moon": (1, 3),
    "c_sun": (1, 3),
    "c_world": (1, 3),
    "c_talisman": (1, 1),
    "c_aura": (1, 1),
    "c_deja_vu": (1, 1),
    "c_trance": (1, 1),
    "c_medium": (1, 1),
    "c_cryptid": (1, 1),
}

# Boss look-ahead: scoring pace under a boss that cuts it, and hands you can
# afford to need against it (Red Deck has 4; The Needle allows one).
BOSS_PACE = {"The Flint": 0.6}
BOSS_HANDS = {"The Needle": 1}
BOSS_HANDS_DEFAULT = 4

# White Stake base chips per ante (Small = 1x, Big = 1.5x, Boss = 2x).
ANTE_BASE = {1: 300, 2: 800, 3: 2000, 4: 5000, 5: 11000, 6: 20000, 7: 35000, 8: 50000}
# Money to keep after shopping, by ante (see research/03-economy-shop-tags.md).
MONEY_FLOOR = {1: 0, 2: 0, 3: 15, 4: 25, 5: 25, 6: 25, 7: 10, 8: 0}

################################################################################
# Small helpers
################################################################################


def _area_cards(G: dict[str, Any], area: str) -> list[dict[str, Any]]:
    value = G.get(area) or {}
    return list(value.get("cards") or []) if isinstance(value, dict) else []


def _joker_keys(G: dict[str, Any]) -> list[str]:
    return [
        j.get("key", "")
        for j in _area_cards(G, "jokers")
        if not (j.get("state") or {}).get("debuff")
    ]


def _norm(card: dict[str, Any]) -> dict[str, Any]:
    """Flatten a BalatroBot card into the fields the analyser needs."""
    value = card.get("value") or {}
    mod = card.get("modifier") or {}
    state = card.get("state") or {}
    stone = mod.get("enhancement") == "STONE"
    return {
        "rank": None if stone else value.get("rank"),
        "suit": None if stone else value.get("suit"),
        "enh": mod.get("enhancement"),
        "ed": mod.get("edition"),
        "seal": mod.get("seal"),
        "debuff": bool(state.get("debuff")),
        "hidden": bool(state.get("hidden")),
        "stone": stone,
        # C3: a face-down card under The Mark, masked by mark_view(): a face
        # card of unknown rank (J/Q/K mix of the unseen cards in ``mix``)
        "face": bool(state.get("mark_face")),
        "mix": state.get("mark_mix"),
    }


def card_name(card: dict[str, Any]) -> str:
    """Human readable card name, e.g. 'King of Hearts' or 'Stone card'."""
    c = _norm(card)
    if c["hidden"]:
        return "face-down card"
    if c["stone"]:
        return "Stone card"
    rank, suit = c["rank"], c["suit"]
    if rank is None or suit is None:
        return card.get("label") or card.get("key") or "card"
    return f"{RANK_NAME.get(rank, rank)} of {SUIT_NAME.get(suit, suit)}"


def card_chips(card: dict[str, Any]) -> int:
    """Base chip value of a playing card (A=11, faces=10, Stone=50)."""
    c = _norm(card)
    if c["stone"]:
        return 50
    return CHIP_VALUE.get(c["rank"] or "", 0)


def current_blind(G: dict[str, Any]) -> dict[str, Any] | None:
    """Return the blind currently being played (status CURRENT), if any."""
    blinds = G.get("blinds") or {}
    for key in ("small", "big", "boss"):
        b = blinds.get(key) or {}
        if b.get("status") == "CURRENT":
            return {"kind": key, **b}
    return None


def next_blind(G: dict[str, Any]) -> dict[str, Any] | None:
    """Return the next blind to be played (first not DEFEATED/SKIPPED)."""
    blinds = G.get("blinds") or {}
    for key in ("small", "big", "boss"):
        b = blinds.get(key) or {}
        if b.get("status") in ("SELECT", "UPCOMING", "CURRENT"):
            return {"kind": key, **b}
    return None


def _active_boss(G: dict[str, Any]) -> str:
    cur = current_blind(G)
    if cur and cur["kind"] == "boss":
        return str(cur.get("name") or "")
    return ""


################################################################################
# Hand classification
################################################################################


def _suit_groups(smeared: bool) -> dict[str, str]:
    if smeared:
        return {"H": "R", "D": "R", "S": "B", "C": "B"}
    return {s: s for s in "HDCS"}


def _is_flush(cards: list[dict[str, Any]], need: int, smeared: bool) -> bool:
    """True if at least ``need`` cards share a suit (Wild counts as any)."""
    if len(cards) < need:
        return False
    groups = _suit_groups(smeared)
    for g in set(groups.values()):
        n = sum(
            1
            for c in cards
            if c["enh"] == "WILD" or (c["suit"] and groups[c["suit"]] == g)
        )
        if n >= need:
            return True
    return False


def _is_straight(cards: list[dict[str, Any]], need: int, shortcut: bool) -> bool:
    """True if ``need`` distinct ranks form a run (gap of 1 allowed with Shortcut)."""
    vals = sorted({RANK_VALUE[c["rank"]] for c in cards if c["rank"]})
    if 14 in vals:
        vals = [1, *vals]
    if len(vals) < need:
        return False
    max_gap = 2 if shortcut else 1
    run = 1
    for a, b in zip(vals, vals[1:], strict=False):
        run = run + 1 if 0 < b - a <= max_gap else 1
        if run >= need:
            return True
    return run >= need


def classify(
    cards: list[dict[str, Any]],
    *,
    four_fingers: bool = False,
    shortcut: bool = False,
    smeared: bool = False,
    splash: bool = False,
) -> tuple[str, list[int]]:
    """Return (hand type, positions of scoring cards) for normalised cards."""
    n = len(cards)
    allidx = list(range(n))
    stones = [i for i, c in enumerate(cards) if c["stone"]]
    # a masked face-down card (rank unknown) pairs with nothing
    ranked = [(i, c) for i, c in enumerate(cards) if not c["stone"] and c["rank"] is not None]
    rc = Counter(c["rank"] for _, c in ranked)
    counts = sorted(rc.values(), reverse=True) + [0, 0]
    need = 4 if four_fingers else 5
    flush = n >= need and _is_flush([c for _, c in ranked], need, smeared)
    straight = n >= need and _is_straight([c for _, c in ranked], need, shortcut)

    def of(k: int) -> list[int]:
        return [i for i, c in ranked if rc[c["rank"]] >= k]

    if counts[0] >= 5:
        htype, scoring = ("Flush Five" if flush else "Five of a Kind"), allidx
    elif flush and counts[0] == 3 and counts[1] >= 2:
        htype, scoring = "Flush House", allidx
    elif straight and flush:
        htype, scoring = "Straight Flush", allidx
    elif counts[0] == 4:
        htype, scoring = "Four of a Kind", of(4)
    elif counts[0] == 3 and counts[1] >= 2:
        htype, scoring = "Full House", allidx
    elif flush:
        htype, scoring = "Flush", allidx
    elif straight:
        htype, scoring = "Straight", allidx
    elif counts[0] == 3:
        htype, scoring = "Three of a Kind", of(3)
    elif counts[0] == 2 and counts[1] == 2:
        htype, scoring = "Two Pair", of(2)
    elif counts[0] == 2:
        htype, scoring = "Pair", of(2)
    else:
        if ranked:
            hi = max(ranked, key=lambda ic: RANK_VALUE[ic[1]["rank"]])[0]
            scoring = [hi]
        else:
            scoring = []
        htype = "High Card"
    if splash:
        scoring = allidx
    return htype, sorted(set(scoring) | set(stones))


################################################################################
# Score estimation
################################################################################


def _hand_base(G: dict[str, Any], htype: str, boss: str) -> tuple[float, float]:
    hand = (G.get("hands") or {}).get(htype) or {}
    chips = float(hand.get("chips", 0))
    mult = float(hand.get("mult", 0))
    if boss == "The Arm" and int(hand.get("level", 1)) > 1:
        dc, dm = LEVEL_UP.get(htype, (0, 0))
        chips, mult = chips - dc, mult - dm
    if boss == "The Flint":  # halves, rounding half up
        chips, mult = max(int(chips / 2 + 0.5), 0), max(int(mult / 2 + 0.5), 1)
    return chips, mult


def _blocked_by_boss(
    G: dict[str, Any], boss: str, htype: str, n_played: int
) -> str | None:
    """Return a reason if the boss makes this play score 0."""
    hands = G.get("hands") or {}
    if boss == "The Psychic" and n_played < 5:
        return "The Psychic: must play 5 cards (pad with junk) or it scores 0"
    if boss == "The Eye" and (hands.get(htype) or {}).get("played_this_round", 0):
        return "The Eye: hand type already played this round, scores 0"
    if boss == "The Mouth":
        # The game locks the FIRST type played this round (blind.lua only_hand);
        # a blocked play still counts as played, so the hands table alone can
        # show two types. The harness stores the first one (pass 5 G1d, B2 N37).
        played = [n for n, h in hands.items() if (h or {}).get("played_this_round", 0)]
        lock = (G.get("luna") or {}).get("mouth_lock") or (played[0] if len(played) == 1 else None)
        if lock and htype != lock:
            return f"The Mouth: only {lock} is allowed this round, scores 0"
    return None


def _joker_effect(
    joker: dict[str, Any],
    ctx: dict[str, Any],
) -> tuple[float, float, float] | None:
    """Joker-level (independent) effect -> (+chips, +mult, xmult), or None if unknown."""
    key = joker.get("key", "")
    effect = (joker.get("value") or {}).get("effect", "") or ""
    htype = ctx["htype"]
    G = ctx["G"]
    rnd = G.get("round") or {}

    if key == "j_joker":
        return 0, 4, 1
    if key in HAND_TYPE_JOKERS:
        need, c, m, x = HAND_TYPE_JOKERS[key]
        if htype in CONTAINS.get(need, {need}):
            return c, m, x
        return 0, 0, 1
    if key == "j_half":
        return (0, 20, 1) if ctx["n_played"] <= 3 else (0, 0, 1)
    if key == "j_fortune_teller":  # "(Currently +N)" has no "Mult" after it
        m = re.search(r"Currently\s*\+(\d+)", effect)
        return (0, float(m.group(1)), 1) if m else (0, 0, 1)
    if key == "j_misprint":
        # random 0..23: the floor estimate counts 0, the shop its average
        return (0, 10, 1) if ctx.get("expected") else (0, 0, 1)
    if key == "j_gros_michel":
        return 0, 15, 1
    if key == "j_cavendish":
        return 0, 0, 3
    if key == "j_banner":
        return 30 * int(rnd.get("discards_left", 0)), 0, 1
    if key == "j_mystic_summit":
        return (0, 15, 1) if int(rnd.get("discards_left", 0)) == 0 else (0, 0, 1)
    if key == "j_card_sharp":
        played = ((G.get("hands") or {}).get(htype) or {}).get("played_this_round", 0)
        return (0, 0, 3) if played else (0, 0, 1)
    if key == "j_acrobat":
        return (0, 0, 3) if int(rnd.get("hands_left", 0)) == 1 else (0, 0, 1)
    if key == "j_blackboard":
        held = ctx["held"]
        ok = all(c["suit"] in ("S", "C") or c["enh"] == "WILD" for c in held) and not ctx.get("held_masked")
        return (0, 0, 3) if held and ok else (0, 0, 1)
    if key == "j_flower_pot":
        suits = {c["suit"] for c in ctx["scored"] if c["suit"]}
        wild = any(c["enh"] == "WILD" for c in ctx["scored"])
        return (0, 0, 3) if len(suits) == 4 or (wild and len(suits) >= 3) else (0, 0, 1)
    if key == "j_seeing_double":
        has_club = any(c["suit"] == "C" for c in ctx["scored"])
        has_other = any(c["suit"] and c["suit"] != "C" for c in ctx["scored"])
        return (0, 0, 2) if has_club and has_other else (0, 0, 1)
    if key == "j_supernova":
        played = ((G.get("hands") or {}).get(htype) or {}).get("played", 0)
        return 0, float(played) + 1, 1
    if key == "j_abstract":
        return 0, 3 * len(_area_cards(G, "jokers")), 1
    if key == "j_stencil":
        jokers = G.get("jokers") or {}
        free = int(jokers.get("limit", 5)) - int(jokers.get("count", 0))
        stencils = sum(1 for k in ctx["keys"] if k == "j_stencil")
        return 0, 0, float(max(1, free + stencils))
    if key in ("j_popcorn", "j_ice_cream", "j_swashbuckler", "j_bull", "j_bootstraps"):
        m = CURRENTLY.search(effect) or FIRST_PLUS.search(effect)
        if m:
            groups = m.groups()
            num = float(groups[-2])
            return (num, 0, 1) if groups[-1].lower() == "chips" else (0, num, 1)
        return None
    m = CURRENTLY.search(effect)
    if m:
        sign, num, kind = m.group(1), float(m.group(2)), m.group(3).lower()
        if sign in ("X", "x", "×"):
            return 0, 0, num
        return (num, 0, 1) if kind == "chips" else (0, num, 1)
    return None


SUIT_LETTER = {"heart": "H", "diamond": "D", "club": "C", "spade": "S"}


SUIT_PAY_JOKERS = {  # per-scored-card suit jokers besides Ancient Joker
    "j_greedy_joker": ("D", "+3 Mult"),
    "j_lusty_joker": ("H", "+3 Mult"),
    "j_wrathful_joker": ("S", "+3 Mult"),
    "j_gluttenous_joker": ("C", "+3 Mult"),
    "j_onyx_agate": ("C", "+7 Mult"),
    "j_arrowhead": ("S", "+50 Chips"),
    "j_bloodstone": ("H", "1 in 2 for X1.5 Mult"),
    "j_rough_gem": ("D", "$1"),
}


def suit_pays(G: dict[str, Any]) -> list[dict[str, str]]:
    """Owned jokers that pay per scored card of a suit: [{label, suit, gain}]."""
    out = []
    for j in _area_cards(G, "jokers"):
        key = j.get("key", "")
        if key == "j_ancient" and (suit := ancient_suit(G)):
            out.append({"label": "Ancient Joker", "suit": suit, "gain": "X1.5 Mult"})
        elif key in SUIT_PAY_JOKERS:
            suit, gain = SUIT_PAY_JOKERS[key]
            out.append({"label": str(j.get("label") or key), "suit": suit, "gain": gain})
    return out


def ancient_suit(G: dict[str, Any]) -> str | None:
    """Suit Ancient Joker pays X1.5 for this round (read live from its effect)."""
    for j in _area_cards(G, "jokers"):
        if j.get("key") == "j_ancient":
            effect = str((j.get("value") or {}).get("effect", ""))
            m = re.search(r"with (Heart|Diamond|Club|Spade)", effect, re.IGNORECASE)
            if m:
                return SUIT_LETTER[m.group(1).lower()]
    return None


def _joker_debuffed(j: dict[str, Any]) -> bool:
    return bool((j.get("state") or {}).get("debuff"))


def _copy_target(jokers: list[dict[str, Any]], idx: int) -> dict[str, Any]:
    """The joker Blueprint (right neighbour) / Brainstorm (leftmost) at
    ``idx`` copies, on the FULL joker list: a debuffed target copies nothing
    (pass 4 F6; the game does not skip to the next joker). Others: {}."""
    key = jokers[idx].get("key", "")
    if key == "j_blueprint":
        target = jokers[idx + 1] if idx + 1 < len(jokers) else {}
    elif key == "j_brainstorm":
        target = jokers[0] if jokers and jokers[0] is not jokers[idx] else {}
    else:
        return {}
    return {} if _joker_debuffed(target) else target


def copied_keys(G: dict[str, Any]) -> list[str]:
    """Keys of the jokers Blueprint (the joker to its right) and Brainstorm
    (the leftmost joker) copy, in joker order."""
    jokers = _area_cards(G, "jokers")  # F6: positions on the full list
    out = []
    for idx, j in enumerate(jokers):
        if _joker_debuffed(j):
            continue
        key = j.get("key", "")
        target = _copy_target(jokers, idx)
        if target.get("key") not in (None, "", "j_blueprint", "j_brainstorm"):
            out.append(str(target.get("key")))
    return out


def _estimate_ctx(G: dict[str, Any]) -> dict[str, Any]:
    """Per-G values estimate_play needs (computed once per _best_play call)."""
    keys = _joker_keys(G)
    return {
        "keys": keys,
        "keyset": set(keys),
        "boss": _active_boss(G),
        "ancient": ancient_suit(G),
        "copied": copied_keys(G),
    }


def estimate_play(
    G: dict[str, Any],
    played_raw: list[dict[str, Any]],
    held_raw: list[dict[str, Any]],
    expected: bool = False,
    _pre: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate the score of playing ``played_raw`` while holding ``held_raw``.

    Approximates Balatro's scoring order: hand base -> scoring cards left to
    right (with per-card jokers and retriggers) -> held cards -> jokers left to
    right. This is a FLOOR estimate: random effects (Misprint, Lucky cards,
    Bloodstone) count as zero and unknown jokers are skipped and listed in
    ``unknown``. ``expected=True`` counts them at their average (Lucky card
    +4 Mult per trigger, Misprint +10 Mult, Bloodstone x1.25 per Heart) for
    valuing jokers in the shop.

    ``_pre`` (sampler only) carries values the caller already has for this G
    and these cards: ``ctx`` from _estimate_ctx(G) and the normalised
    ``played`` / ``held`` cards.
    """
    ctx = _pre["ctx"] if _pre else _estimate_ctx(G)
    keys = ctx["keys"]
    keyset = ctx["keyset"]
    boss = ctx["boss"]
    played = _pre["played"] if _pre else [_norm(c) for c in played_raw]
    held = _pre["held"] if _pre else [_norm(c) for c in held_raw]
    htype, scoring = classify(
        played,
        four_fingers="j_four_fingers" in keyset,
        shortcut="j_shortcut" in keyset,
        smeared="j_smeared" in keyset,
        splash="j_splash" in keyset,
    )
    blocked = _blocked_by_boss(G, boss, htype, len(played))
    chips, mult = _hand_base(G, htype, boss)
    x_total = 1.0
    money = 0.0
    pareidolia = "j_pareidolia" in keyset
    smeared = "j_smeared" in keyset
    groups = _suit_groups(smeared)
    hands_left = int((G.get("round") or {}).get("hands_left", 0))
    scored_cards = [played[i] for i in scoring]
    ancient = ctx["ancient"]

    def is_face(c: dict[str, Any]) -> bool:
        return not c["stone"] and (pareidolia or c["face"] or (c["rank"] in FACE_RANKS))

    # Photograph fires on every trigger of the first scored face card, so
    # Hanging Chad / Sock and Buskin / Red Seal retriggers multiply it again.
    first_face_pos = next(
        (
            pos
            for pos, i in enumerate(scoring)
            if is_face(played[i]) and not played[i]["debuff"]
        ),
        None,
    )

    def suit_match(c: dict[str, Any], suit: str) -> bool:
        if c["enh"] == "WILD":
            return True
        return bool(c["suit"]) and groups[c["suit"]] == groups[suit]

    for pos, i in enumerate(scoring):
        c = played[i]
        if c["debuff"]:
            continue
        triggers = 1
        if c["seal"] == "RED":
            triggers += 1
        if "j_hack" in keyset and c["rank"] in ("2", "3", "4", "5"):
            triggers += keys.count("j_hack")
        if "j_sock_and_buskin" in keyset and is_face(c):
            triggers += keys.count("j_sock_and_buskin")
        if "j_hanging_chad" in keyset and pos == 0:
            triggers += 2 * keys.count("j_hanging_chad")
        if "j_dusk" in keyset and hands_left == 1:
            triggers += keys.count("j_dusk")
        if "j_selzer" in keyset:
            triggers += 1
        for _ in range(triggers):
            # a masked face-down card is a J, Q or K: 10 chips (C3)
            chips += 50 if c["stone"] else 10 if c["face"] else CHIP_VALUE.get(c["rank"] or "", 0)
            if c["enh"] == "BONUS":
                chips += 30
            elif c["enh"] == "MULT":
                mult += 4
            # LUCKY (1 in 5 for +20 Mult) counts 0 in the floor estimate
            elif c["enh"] == "LUCKY" and expected:
                mult += 4
            elif c["enh"] == "GLASS":
                mult *= 2
            if c["ed"] == "FOIL":
                chips += 50
            elif c["ed"] == "HOLO":
                mult += 10
            elif c["ed"] == "POLYCHROME":
                mult *= 1.5
            if c["seal"] == "GOLD":
                money += 3
            for k in keys:
                if k in SUIT_MULT_JOKERS and suit_match(c, SUIT_MULT_JOKERS[k]):
                    mult += 3
                elif k == "j_scary_face" and is_face(c):
                    chips += 30
                elif k == "j_smiley" and is_face(c):
                    mult += 5
                elif k == "j_scholar" and c["rank"] == "A":
                    chips += 20
                    mult += 4
                elif k == "j_fibonacci" and c["rank"] in ("A", "2", "3", "5", "8"):
                    mult += 8
                elif k == "j_even_steven" and c["rank"] in ("2", "4", "6", "8", "T"):
                    mult += 4
                elif k == "j_odd_todd" and c["rank"] in ("A", "3", "5", "7", "9"):
                    chips += 31
                elif k == "j_walkie_talkie" and c["rank"] in ("T", "4"):
                    chips += 10
                    mult += 4
                elif k == "j_arrowhead" and suit_match(c, "S"):
                    chips += 50
                elif k == "j_onyx_agate" and suit_match(c, "C"):
                    mult += 7
                elif k == "j_rough_gem" and suit_match(c, "D"):
                    money += 1
                # Bloodstone (1 in 2 for x1.5) counts x1 in the floor estimate;
                # the shop counts its average (always x1.5 with Oops! All 6s)
                elif k == "j_bloodstone" and expected and suit_match(c, "H"):
                    mult *= 1.5 if "j_oops" in keyset else 1.25
                elif k == "j_ancient" and ancient and suit_match(c, ancient):
                    mult *= 1.5
                elif k == "j_triboulet" and c["rank"] in ("K", "Q"):
                    mult *= 2
                elif k == "j_photograph" and pos == first_face_pos:
                    mult *= 2

    # Held-in-hand effects (Blueprint / Brainstorm copies of Baron, Mime and
    # Shoot the Moon count as extra copies)
    copied = ctx["copied"]
    mime = keys.count("j_mime") + copied.count("j_mime")
    barons = keys.count("j_baron") + copied.count("j_baron")
    moons = keys.count("j_shoot_the_moon") + copied.count("j_shoot_the_moon")
    for c in held:
        # a face-down card held under The Mark counts nothing here (a floor);
        # play_advice replaces the listed score by the exact floor over every
        # possible face-down set when held cards matter (review round 3)
        if c["debuff"] or c["hidden"]:
            continue
        triggers = 1 + mime + (1 if c["seal"] == "RED" else 0)
        for _ in range(triggers):
            if c["enh"] == "STEEL":
                mult *= 1.5
            if c["rank"] == "K":
                for _k in range(barons):
                    mult *= 1.5
            if c["rank"] == "Q":
                mult += 13 * moons
    if "j_raised_fist" in keyset:
        # The game's rule (card.lua Raised Fist): the lowest-ranked held card,
        # debuffed cards included (only Stone, no rank, is skipped), ties going
        # to the LAST such card in hand order; a debuffed pick adds nothing
        # (pass 5 G1b, A1 N05: debuffed Steel 2♠ held -> +0, not 7♦'s +14).
        ranks = [c for c in held if c["rank"] and not c["hidden"]]
        stand_ins: list[dict[str, Any]] = []
        # The Mark: a held face-down card is a J/Q/K (worth 10), or with
        # Pareidolia any card (counted as a 2): a lower bound (review r4 opus F2b)
        masked = [c for c in held if c["hidden"] and c["face"] and not c["debuff"]]
        # with Pareidolia a held face-down card may be a Stone card (no rank,
        # skipped): count it as a 2 only when a visible ranked card is held too
        # or fewer Stone cards are unseen than face-down cards are held, else it
        # may add nothing (review r8 codex R8-1 / opus R8-1, opus's fix 2)
        if masked and "j_pareidolia" not in keyset:
            stand_ins.append({"rank": "J"})
        elif masked:
            stones = (sum(1 for c in _area_cards(G, "cards") if _norm(c)["stone"]) if G.get("mark_unseen")
                      else len(masked))
            if ranks or stones < len(masked):
                stand_ins.append({"rank": "2"})
        # stand-ins first, so a visible card wins a tie (a debuffed one -> +0: stays a floor)
        pool = stand_ins + ranks
        if pool:
            lo = min(RANK_VALUE[c["rank"]] for c in pool)
            low = [c for c in pool if RANK_VALUE[c["rank"]] == lo][-1]
            if not low.get("debuff"):
                mult += 2 * CHIP_VALUE[low["rank"]]

    # Independent joker effects, left to right (with Blueprint/Brainstorm)
    jokers = _area_cards(G, "jokers")  # F6: full list; debuffed jokers skipped in the loop
    ctx = {
        "G": G,
        "htype": htype,
        "n_played": len(played),
        "held": [c for c in held if not c["hidden"]],
        # The Mark: a held face-down card may be red, so Blackboard does not count (review r4 opus F2b)
        "held_masked": any(c["hidden"] and c["face"] for c in held),
        "scored": scored_cards,
        "keys": keys,
        "expected": expected,
    }
    unknown: list[str] = []
    baseball = keys.count("j_baseball")
    for idx, j in enumerate(jokers):
        if _joker_debuffed(j):
            continue
        edition = (j.get("modifier") or {}).get("edition")
        if edition == "FOIL":
            chips += 50
        elif edition == "HOLO":
            mult += 10
        key = j.get("key", "")
        target = _copy_target(jokers, idx) if key in ("j_blueprint", "j_brainstorm") else j
        tkey = target.get("key", "")
        if tkey == "j_baseball":
            pass  # applied below, after each Uncommon joker
        elif target and tkey not in ("j_blueprint", "j_brainstorm"):
            if tkey in PER_CARD_JOKERS or tkey in STRUCTURAL_JOKERS:
                if target is not j and tkey not in HELD_COPIED:
                    unknown.append(f"{j.get('label', key)} (copy)")
            elif tkey in SUIT_MULT_JOKERS or tkey in NO_SCORE_JOKERS:
                pass
            else:
                eff = _joker_effect(target, ctx)
                if eff is None:
                    unknown.append(str(j.get("label") or key))
                else:
                    dc, dm, dx = eff
                    chips += dc
                    mult += dm
                    mult *= dx
        if edition == "POLYCHROME":
            mult *= 1.5
        # Baseball Card: X1.5 as each Uncommon joker is evaluated
        if baseball and key in knowledge.UNCOMMON_JOKERS:
            mult *= 1.5**baseball

    score = 0 if blocked else int(chips * mult * x_total)
    return {
        "hand": htype,
        "scoring": scoring,
        "score": score,
        "chips": int(chips),
        "mult": round(mult, 1),
        "money": int(money),
        "blocked": blocked,
        "unknown": sorted(set(unknown)),
    }


################################################################################
# Hand analysis (SELECTING_HAND)
################################################################################


def _hypergeom_at_least(total: int, outs: int, draws: int, need: int) -> float:
    if draws <= 0 or total <= 0 or need <= 0:
        return 1.0 if need <= 0 else 0.0
    draws = min(draws, total)
    good = sum(
        comb(outs, k) * comb(total - outs, draws - k)
        for k in range(need, min(outs, draws) + 1)
    )
    return good / comb(total, draws)


HACK_RANKS = {"2", "3", "4", "5"}


def _discard_choice(
    hand: list[dict[str, Any]],
    keep: Iterable[int],
    limit: int,
    first_rank: str | None = None,
    keys: Iterable[str] = (),
) -> list[int]:
    """Pick up to ``limit`` cards to discard, lowest value first, never ``keep``.

    Cards of ``first_rank`` (Mail-In Rebate pays $5 each) go first; with
    Faceless Joker, face cards go first when 3+ can go at once ($5); with
    Blackboard, red cards go first (held cards must all be black); with Hack,
    2-5s go last (Hack retriggers them when played) (P6, P7, V8).
    """
    keep = set(keep)
    keys = set(keys)
    candidates = [
        i
        for i, c in enumerate(hand)
        if i not in keep
        and c["enh"] not in ("STEEL", "GOLD")
        and c["seal"] != "BLUE"
        and not c.get("face")  # C3: a face-down card under The Mark is a face card: keep it
    ]
    faces_first = (
        "j_faceless" in keys
        and sum(1 for i in candidates if hand[i]["rank"] in FACE_RANKS) >= 3
    )
    candidates.sort(
        key=lambda i: (
            first_rank is None or hand[i]["rank"] != first_rank,
            not (faces_first and hand[i]["rank"] in FACE_RANKS),
            not ("j_blackboard" in keys and _red(hand[i])),
            "j_hack" in keys and hand[i]["rank"] in HACK_RANKS,
            hand[i]["enh"] is not None or hand[i]["ed"] is not None,
            CHIP_VALUE.get(hand[i]["rank"] or "", 0),
        )
    )
    return sorted(candidates[:limit])


def _mark_draw_odds(G: dict[str, Any], hand: list[dict[str, Any]], deck: list[dict[str, Any]],
                    draws: list[dict[str, Any]], need_flush: int) -> None:
    """Under The Mark the analysis deck is the unseen pile (deck + face-down
    cards). The face-down cards are in hand, so they cannot be drawn: each
    draw's chance = the average over the possible face-down cards (sampled
    from the unseen face cards) of the chance with those cards removed from
    the deck. Never uses which face card is which (review round 2)."""
    k = sum(1 for c in hand if c["face"])
    pareidolia = "j_pareidolia" in set(_joker_keys(G))
    faces = [i for i, c in enumerate(deck) if pareidolia or (not c["stone"] and c["rank"] in FACE_RANKS)]
    if not k or len(faces) < k:
        return
    ids = sorted(f"{c['rank']}{c['suit']}{c['enh']}{c['seal']}{c['ed']}" for c in deck)
    rng = random.Random(int(hashlib.md5(json.dumps([ids, k, "draws"]).encode()).hexdigest()[:12], 16))
    picks = [set(rng.sample(faces, k)) for _ in range(MARK_SAMPLES)]
    for d in draws:
        total = 0.0
        for pick in picks:
            rest = [c for i, c in enumerate(deck) if i not in pick]
            if d["kind"] == "Flush":
                outs = sum(1 for c in rest if c["suit"] == d["suit"])
                need = d["need"]
            else:
                outs = sum(1 for c in rest if c["rank"] in d["missing_ranks"])
                need = 1
            total += _hypergeom_at_least(len(rest), outs, len(d["discard"]), need)
        d["chance"] = total / len(picks)
        d["text"] = d["text"].replace(" left in deck", " among the unseen cards")


def _red(c: dict[str, Any]) -> bool:
    """A card that breaks Blackboard while held (not a Spade/Club, not Wild)."""
    return c["enh"] != "WILD" and (c["stone"] or c["suit"] not in ("S", "C"))


def _synthetic_card(suit: str, rank: str) -> dict[str, Any]:
    return {
        "key": f"{suit}_{rank}",
        "set": "DEFAULT",
        "value": {"suit": suit, "rank": rank},
        "modifier": {},
        "state": {},
    }


def _projected_score(
    G: dict[str, Any], hand_raw: list[dict[str, Any]], draw: dict[str, Any]
) -> int:
    """Typical score of a draw once it completes: the kept cards plus the
    median completing card left in the deck (or the missing rank)."""
    hand = [_norm(c) for c in hand_raw]
    keep = sorted(
        draw["keep"],
        key=lambda i: -CHIP_VALUE.get(hand[i]["rank"] or "", 0),
    )
    keyset = set(_joker_keys(G))
    if draw["kind"] == "Flush":
        need = 4 if "j_four_fingers" in keyset else 5
        played = [hand_raw[i] for i in keep[:need]]
        suit = draw.get("suit") or hand[keep[0]]["suit"] or "H"
        outs = sorted(
            (
                c["rank"]
                for c in (_norm(x) for x in _area_cards(G, "cards"))
                if c["suit"] == suit and c["rank"]
            ),
            key=lambda r: CHIP_VALUE[r],
        )
        median = outs[len(outs) // 2] if outs else "2"
        while len(played) < need:
            played.append(_synthetic_card(suit, median))
    else:
        played = [hand_raw[i] for i in keep]
        suits = Counter(hand[i]["suit"] for i in keep)
        filler_suit = min("HDCS", key=lambda x: suits.get(x, 0))
        played.append(_synthetic_card(filler_suit, draw.get("missing") or "2"))
    est = estimate_play(G, played, [])
    return int(est["score"]) if est["hand"] == draw["kind"] else 0


def analyze_hand(G: dict[str, Any], top: int = 6, real: dict[str, Any] | None = None) -> dict[str, Any]:
    """Enumerate the best play per hand type and the best draws.

    Returns a dict with:
      - ``plays``: best minimal play per hand type, sorted by estimated score
        (``cards`` are 0-based hand indices).
      - ``draws``: flush/straight draws with the chance to complete them by
        discarding the other cards once, plus suggested discard indices.
      - ``hand_suits`` / ``deck_size`` / ``deck_suits`` / ``deck_ranks``.
    """
    hand_raw = _area_cards(G, "hand")
    hand = [_norm(c) for c in hand_raw]
    limit = int((G.get("hand") or {}).get("highlighted_limit", 5) or 5)
    keyset = set(_joker_keys(G))

    best: dict[str, dict[str, Any]] = {}
    best_no_blue: dict[str, dict[str, Any]] = {}  # same, keeping Blue Seals held
    blue = {i for i, c in enumerate(hand) if c["seal"] == "BLUE"}
    visible = [i for i, c in enumerate(hand) if not c["hidden"]]
    # The Mark with held-card scoring: each face-up play is judged by its exact
    # floor over every filling of the face-down slots, BEFORE choosing the best
    # play of its hand type (review round 4, codex R4-1)
    fills = _mark_held_fills(real) if real is not None else None
    cands: dict[str, list[dict[str, Any]]] = {}
    for k in range(1, min(limit, len(visible)) + 1):
        for idx in combinations(visible, k):
            played = [hand_raw[i] for i in idx]
            held = [hand_raw[i] for i in range(len(hand_raw)) if i not in idx]
            est = estimate_play(G, played, held)
            if "j_splash" not in keyset and len(est["scoring"]) != k:
                continue  # keep minimal plays: every selected card scores
            if fills is not None:
                cands.setdefault(est["hand"], []).append({"cards": list(idx), **est})
                continue
            prev = best.get(est["hand"])
            if prev is None or est["score"] > prev["score"]:
                best[est["hand"]] = {"cards": list(idx), **est}
            if blue and not blue & set(idx):
                prev = best_no_blue.get(est["hand"])
                if prev is None or est["score"] > prev["score"]:
                    best_no_blue[est["hand"]] = {"cards": list(idx), **est}
    if fills is not None:
        for htype, group in cands.items():
            if fills == "unknown":
                # too many fillings: the masked score is a proven floor (held
                # face-down cards only add, or count as the worst case)
                pick = max(group, key=lambda p: p["score"])
                pick_nb = max((p for p in group if not blue & set(p["cards"])), key=lambda p: p["score"], default=None) if blue else None
            else:
                pick = _best_by_floor(real, fills, group)
                pick_nb = _best_by_floor(real, fills, [p for p in group if not blue & set(p["cards"])]) if blue else None
            # score = the mean Luna is told (and MEMORY records); floor = for WINS
            for q in {id(q): q for q in (pick, pick_nb) if q is not None}.values():
                q["floor"] = int(q["score"])
                q["score"] = max(q["floor"], _mark_about(real, q["cards"]))
            best[htype] = pick
            if blue and pick_nb is not None:
                best_no_blue[htype] = pick_nb
    for htype, play in best.items():
        alt = best_no_blue.get(htype)
        if alt is not None and blue & set(play["cards"]):
            play["no_blue"] = alt
    plays = sorted(best.values(), key=lambda p: -p["score"])[:top]

    deck = [_norm(c) for c in _area_cards(G, "cards")]
    deck_size = len(deck)
    deck_suits = Counter(c["suit"] for c in deck if c["suit"])
    deck_ranks = Counter(c["rank"] for c in deck if c["rank"])
    hand_suits = Counter(c["suit"] for c in hand if c["suit"] and not c["hidden"])
    discards_left = int((G.get("round") or {}).get("discards_left", 0))

    draws: list[dict[str, Any]] = []
    need_flush = 4 if "j_four_fingers" in keyset else 5
    if deck_size:
        for suit, have in hand_suits.most_common():
            wild = sum(1 for c in hand if c["enh"] == "WILD" and c["suit"] != suit)
            have_total = have + wild
            if not (need_flush - 2 <= have_total < need_flush):
                continue
            keep = [
                i
                for i, c in enumerate(hand)
                if (c["suit"] == suit or c["enh"] == "WILD") and not c["hidden"]
            ]
            n = min(limit, len(hand) - len(keep), deck_size)
            outs = deck_suits.get(suit, 0)
            discard = _discard_choice(hand, keep, n)
            # odds from the cards actually suggested (some are never discarded)
            p = _hypergeom_at_least(deck_size, outs, len(discard), need_flush - have_total)
            draws.append(
                {
                    "kind": "Flush",
                    "suit": suit,
                    "need": need_flush - have_total,
                    "text": f"Flush draw in {SUIT_NAME[suit]}: {have_total}/{need_flush} in hand, "
                    f"{outs} {SUIT_NAME[suit]} left in deck",
                    "keep": keep,
                    "discard": discard,
                    "chance": p,
                }
            )
        ranks_in_hand = {c["rank"] for c in hand if c["rank"] and not c["hidden"]}
        seen: dict[frozenset[str], set[str]] = {}
        for lo in range(1, 11):  # windows A-5 ... T-A
            window = ["A" if v in (1, 14) else RANKS[v - 2] for v in range(lo, lo + 5)]
            missing = [r for r in window if r not in ranks_in_hand]
            if len(missing) == 1:
                held_ranks = frozenset(r for r in window if r in ranks_in_hand)
                seen.setdefault(held_ranks, set()).add(missing[0])
        for held_ranks, missing in seen.items():
            if len(held_ranks) != 4:
                continue
            keep: list[int] = []
            for r in sorted(held_ranks, key=lambda r: RANK_VALUE[r]):
                keep.append(
                    next(
                        i
                        for i, c in enumerate(hand)
                        if c["rank"] == r and not c["hidden"]
                    )
                )
            n = min(limit, len(hand) - len(keep), deck_size)
            outs = sum(deck_ranks.get(r, 0) for r in missing)
            discard = _discard_choice(hand, keep, n)
            p = _hypergeom_at_least(deck_size, outs, len(discard), 1)
            need_txt = " or ".join(RANK_NAME.get(r, r) for r in sorted(missing))
            draws.append(
                {
                    "kind": "Straight",
                    "missing": min(missing, key=lambda r: CHIP_VALUE[r]),
                    "missing_ranks": sorted(missing),
                    "text": f"Straight draw: need a {need_txt} ({outs} left in deck)",
                    "keep": sorted(keep),
                    "discard": discard,
                    "chance": p,
                }
            )
    if G.get("mark_unseen") and draws:
        _mark_draw_odds(G, hand, deck, draws, need_flush)
    for d in draws:
        d["if_complete"] = _projected_score(G, hand_raw, d)
    draws.sort(key=lambda d: -d["chance"])
    return {
        "plays": plays,
        "draws": draws[:3],
        "hand_suits": dict(hand_suits),
        "deck_size": deck_size,
        "deck_suits": dict(deck_suits),
        "deck_ranks": dict(deck_ranks),
        "discards_left": discards_left,
    }


################################################################################
# Round / shop / deck context
################################################################################


def blind_progress(G: dict[str, Any]) -> dict[str, Any] | None:
    """Chips still needed for the current blind and per-hand pace."""
    cur = current_blind(G)
    if not cur:
        return None
    rnd = G.get("round") or {}
    target = int(cur.get("score") or 0)
    scored = int(rnd.get("chips") or 0)
    remaining = max(target - scored, 0)
    hands_left = int(rnd.get("hands_left") or 0)
    per_hand = -(-remaining // hands_left) if hands_left else remaining
    return {
        "name": cur.get("name") or cur["kind"].title(),
        "kind": cur["kind"],
        "effect": cur.get("effect") or "",
        "target": target,
        "scored": scored,
        "remaining": remaining,
        "hands_left": hands_left,
        "discards_left": int(rnd.get("discards_left") or 0),
        "per_hand": per_hand,
    }


def money_floor(G: dict[str, Any]) -> int:
    """Recommended minimum money to keep after shopping this ante."""
    ante = int(G.get("ante_num") or 1)
    return MONEY_FLOOR.get(min(max(ante, 1), 8), 0)


RESERVE = 10  # soft money reserve from Ante 2 (owner: "try to reserve $10")


TAG_MONEY = {"Investment Tag": 25}  # paid at the cash-out after this ante's boss


def pending_tag_lines(G: dict[str, Any]) -> list[str]:
    """M1: tags the harness skipped a blind for that have not paid yet (facts only)."""
    money = int(G.get("money") or 0)
    lines = []
    for t in (G.get("luna") or {}).get("pending_tags") or []:
        pay = TAG_MONEY.get(str(t.get("tag")))
        if pay:
            lines.append(
                f"{t['tag']} (harness skipped a blind for it): +${pay} after this ante's boss; "
                f"after the boss you will have about ${money} + ${pay} = ${money + pay} plus that round's payout"
            )
    return lines


def reserve(G: dict[str, Any], status: str | None = None, boss_short: bool = False) -> int:
    """Money a SCORE buy must leave (P2-8, owner S2/F1).

    Ante 1: $0. Ante 2 while THIN/SHORT: $0 (S2: spend to ~$0 for survival).
    Ante 3: $0 only when SHORT for the boss. From Ante 4: $0, because one buy
    may take money below $10 (F1) and the harness then locks the shop.
    Otherwise (Ante 2 COMFORTABLE, Ante 3 not SHORT for the boss) $10.
    """
    ante = int(G.get("ante_num") or 1)
    if ante <= 1:
        return 0
    if ante == 2 and status in ("THIN", "SHORT"):
        return 0
    if ante == 3 and boss_short:
        return 0
    if ante >= 4:
        return 0
    return RESERVE


def interest(money: int) -> int:
    """Interest earned at end of next round (vanilla cap $5)."""
    return max(0, min(int(money) // 5, 5))


def shop_context(
    G: dict[str, Any], rounds: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Money floor, interest, joker slots, next blind/boss and power check."""
    money = int(G.get("money") or 0)
    jokers = G.get("jokers") or {}
    floor = money_floor(G)
    last = rounds[-1] if rounds else None
    weak = bool(last) and int(last.get("hands_left", 0)) < 2
    blinds = G.get("blinds") or {}
    boss = blinds.get("boss") or {}
    nxt = next_blind(G)
    effective_floor = 0 if weak else floor
    return {
        "money": money,
        "interest": interest(money),
        "floor": floor,
        "effective_floor": effective_floor,
        "spendable": max(money - effective_floor, 0),
        "joker_count": int(jokers.get("count", 0)),
        "joker_limit": int(jokers.get("limit", 5)),
        "joker_slots_free": max(
            int(jokers.get("limit", 5)) - int(jokers.get("count", 0)), 0
        ),
        "next_blind": nxt,
        "boss_name": boss.get("name") or "",
        "boss_effect": boss.get("effect") or "",
        "boss_score": boss.get("score") or 0,
        "last_round": last,
        "weak": weak,
    }


def deck_summary(G: dict[str, Any], area: str = "cards") -> dict[str, Any]:
    """Aggregate counts (never order) of a card area, default the remaining deck."""
    cards = [_norm(c) for c in _area_cards(G, area)]
    return {
        "size": len(cards),
        "suits": dict(Counter(c["suit"] for c in cards if c["suit"])),
        "ranks": dict(Counter(c["rank"] for c in cards if c["rank"])),
        "enhancements": dict(Counter(c["enh"] for c in cards if c["enh"])),
        "seals": dict(Counter(c["seal"] for c in cards if c["seal"])),
        "editions": dict(Counter(c["ed"] for c in cards if c["ed"])),
    }


def hands_table(
    G: dict[str, Any], include_secret: bool = False
) -> list[dict[str, Any]]:
    """Poker hands strongest first; secret hands only if levelled or played."""
    hands = G.get("hands") or {}
    rows = []
    for name in HAND_ORDER:
        h = hands.get(name)
        if not h:
            continue
        if (
            name in SECRET_HANDS
            and not include_secret
            and int(h.get("level", 1)) <= 1
            and not int(h.get("played", 0))
        ):
            continue
        rows.append({"name": name, **h})
    return rows


def main_hand(G: dict[str, Any]) -> str | None:
    """Most played poker hand this run (ties broken by strength), if any."""
    hands = G.get("hands") or {}
    played = [(int((h or {}).get("played", 0)), n) for n, h in hands.items()]
    played = [(p, n) for p, n in played if p > 0]
    if not played:
        return None
    top = max(p for p, _ in played)
    for name in HAND_ORDER:
        if (top, name) in played:
            return name
    return None


def consumable_targets(key: str) -> tuple[int, int] | None:
    """(min, max) hand cards a consumable needs, or None if it needs none."""
    return CONSUMABLE_TARGETS.get(key)


def fmt_num(value: float | int) -> str:
    """Format a number with thousands separators."""
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return str(value)


def pct(value: float) -> str:
    """Format a probability as a percentage."""
    return f"{round(float(value) * 100):d}%"


################################################################################
# Main hand plan, play suggestions, consumable targets, status
################################################################################

STRONG_DRAW = 0.5  # discard toward a MAIN_HAND draw that completes this often
# Ante 1: keep discarding toward a Flush/Straight draw while the chance to hit
# it within the remaining discards is at least this.
CHASE_DRAW = 0.5
BIG_HANDS = {
    "Straight",
    "Flush",
    "Full House",
    "Four of a Kind",
    "Straight Flush",
    "Five of a Kind",
    "Flush House",
    "Flush Five",
}
DRAW_UPGRADE = 1.2  # a draw must beat the best made play by 20% to discard for it
WIN_MARGIN = 1.10  # a play is marked WINS only if its floor estimate >= 110% of NEED
PAIR_FAMILY = {"Pair", "Two Pair", "Three of a Kind", "Full House", "Four of a Kind"}


def xmult_owned(G: dict[str, Any], plan: dict[str, Any] | None = None) -> int:
    """Owned on-plan [XMULT] jokers (XMULT_OWNED)."""
    plan = plan or main_hand_plan(G)
    return sum(
        1
        for i in _owned_joker_infos(G)
        if i["category"] == "XMULT"
        and i["key"] not in ("j_loyalty_card", "j_stencil", "j_flower_pot", "j_blackboard")
        and knowledge.joker_fit(i["name"], plan["hand"]) != "OFF-PLAN"
    )


def _owned_joker_infos(G: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for j in _area_cards(G, "jokers"):
        info = knowledge.joker_info(j.get("label"))
        if info:
            out.append({**info, "key": j.get("key", "")})
    return out


def blue_seal_count(G: dict[str, Any]) -> int:
    """Blue Seal playing cards owned (deck + hand)."""
    return sum(
        1
        for area in ("cards", "hand")
        for c in _area_cards(G, area)
        if _norm(c)["seal"] == "BLUE"
    )


GROWS_LATE_ANTE = 5  # self-growing X1 jokers need an empty xMult role from here


# P7 / P2-8: jokers that work against each other (advice only)
CLASHES = {
    "j_hack": ({"j_faceless"}, "Hack wants 2-5s played; Faceless Joker wants face cards discarded"),
    "j_faceless": (
        {"j_hack", "j_photograph", "j_hanging_chad", "j_scary_face", "j_smiley"},
        "Faceless Joker wants face cards discarded; your face-card scorers want them played",
    ),
    "j_photograph": ({"j_faceless"}, "Photograph wants face cards played; Faceless Joker wants them discarded"),
    "j_scary_face": ({"j_faceless"}, "Scary Face wants face cards played; Faceless Joker wants them discarded"),
    "j_smiley": ({"j_faceless"}, "Smiley Face wants face cards played; Faceless Joker wants them discarded"),
}


def clash_note(G: dict[str, Any], card: dict[str, Any]) -> str:
    """'[CLASHES with X: why]' when a shop joker works against one you own."""
    hit = CLASHES.get(str(card.get("key")))
    if not hit:
        return ""
    others, why = hit
    owned = [j for j in _area_cards(G, "jokers") if j.get("key") in others]
    if not owned:
        return ""
    return f"[CLASHES with {', '.join(str(j.get('label')) for j in owned)}: {why}]"


def grows_xmult(G: dict[str, Any], card: dict[str, Any]) -> str:
    """``[GROWS-XMULT] ...`` for a joker that starts at X1 Mult and grows.

    Its SCORE reads +0 when bought, so the tag says whether the thing that
    grows it is present: a Glass/Lucky card in the deck (the game only offers
    Glass Joker / Lucky Cat once you own one) or nothing (it grows on its own).
    """
    grows = knowledge.GROWS_XMULT.get(str(card.get("label")))
    if not grows:
        return ""
    enhancement, tarot_key, source = grows
    if not enhancement:
        # From Ante 5 it has few antes left to grow: worth a slot only while you
        # own no xMult joker at all.
        if int(G.get("ante_num") or 1) >= GROWS_LATE_ANTE and xmult_owned(G):
            return (
                f"[GROWS-XMULT] starts at X1 | {source} | no source: too late to "
                "grow, and you already own an xMult joker"
            )
        return f"[GROWS-XMULT] starts at X1 | {source} | SOURCE PRESENT"
    count = sum(
        1
        for area in ("cards", "hand")
        for c in _area_cards(G, area)
        if _norm(c)["enh"] == enhancement
    )
    tarots = [
        str(c.get("label"))
        for area in ("consumables", "shop", "pack")
        for c in _area_cards(G, area)
        if c.get("key") == tarot_key
    ]
    text = f"[GROWS-XMULT] starts at X1 | {source}: {count} in your deck"
    if tarots:
        text += f" ({tarots[0]} available makes more)"
    return text + (" | SOURCE PRESENT" if count else " | no source yet")


def owns_joker(G: dict[str, Any], key: str) -> bool:
    """True when a joker with this key is in the joker area."""
    return any(j.get("key") == key for j in _area_cards(G, "jokers"))


def owns_hologram(G: dict[str, Any]) -> bool:
    """Hologram grows with every card added, so extra playing cards help."""
    return any(j.get("key") == "j_hologram" for j in _area_cards(G, "jokers"))


ECON_EARLY_MAX_ANTE = 3  # buy economy jokers only while they have time to pay back
ECON_MAX_OWNED = 2


def main_suit(G: dict[str, Any]) -> str:
    """Suit the deck (hand + remaining deck) holds most of; joker suit wins ties."""
    counts: Counter[str] = Counter()
    for area in ("hand", "cards"):
        for c in _area_cards(G, area):
            n = _norm(c)
            if n["suit"]:
                counts[n["suit"]] += 1
    for key, suit in SUIT_MULT_JOKERS.items():
        if key in set(_joker_keys(G)):
            counts[suit] += 3
    if not counts:
        return "H"
    return max("HDCS", key=lambda s: (counts[s], -"HDCS".index(s)))


TWO_PAIR_JOKERS = {"j_trousers", "j_mad", "j_clever"}
OPEN_ANTES = 1  # Ante 1: chase Flush/Straight draws (CHASE) while discards last
# Owner: Flush only when the jokers point there (Smeared Joker / Four Fingers);
# a lone Tribe or suit-Mult jokers of mixed suits do not make Flush reliable.
FLUSH_ENGINES = {"j_smeared", "j_four_fingers"}
SUIT_SHARE_FOR_FLUSH = 0.5  # deck this concentrated in one suit makes Flush reliable


def _suit_share(G: dict[str, Any], suit: str) -> float:
    cards = [_norm(c) for a in ("hand", "cards") for c in _area_cards(G, a)]
    suited = [c for c in cards if c["suit"]]
    if not suited:
        return 0.0
    return sum(1 for c in suited if c["suit"] == suit) / len(suited)


STRAIGHT_ENGINES = {"j_shortcut", "j_order"}


def joker_call(G: dict[str, Any]) -> tuple[str, str] | None:
    """(hand, trigger) when the jokers or the deck call for a hand type (P2-4).

    Owner (D2/F5/J4): commit by the jokers you have. Flush only with Four
    Fingers, Smeared Joker or The Tribe (or a deck half one suit); Straight only
    with Shortcut or The Order; Card Sharp repeats the hand levelled most.
    """
    jokers = {j.get("key", ""): str(j.get("label") or j.get("key")) for j in _area_cards(G, "jokers")}
    keys = set(jokers)

    def first(*ks: str) -> str:
        return next(jokers[k] for k in ks if k in jokers)

    if keys & (FLUSH_ENGINES | {"j_tribe"}):
        return "Flush", first("j_four_fingers", "j_smeared", "j_tribe")
    if _suit_share(G, main_suit(G)) >= SUIT_SHARE_FOR_FLUSH:
        return "Flush", "half your deck is one suit"
    if keys & STRAIGHT_ENGINES:
        return "Straight", first("j_shortcut", "j_order")
    if "j_trio" in keys:
        return "Three of a Kind", jokers["j_trio"]
    if {"j_zany", "j_wily"} <= keys:
        return "Three of a Kind", "Zany Joker + Wily Joker"
    if keys & TWO_PAIR_JOKERS:
        return "Two Pair", first("j_trousers", "j_mad", "j_clever")
    if keys & {"j_baron", "j_half", "j_duo"}:
        return "Pair", first("j_baron", "j_half", "j_duo")
    if "j_card_sharp" in keys:
        return leaning_hand(G), jokers["j_card_sharp"]
    return None


def leaning_hand(G: dict[str, Any]) -> str:
    """While MAIN_HAND is OPEN: the hand levelled most (ties: played most,
    then the more common hand), Pair when nothing is levelled (owner J4)."""
    hands = G.get("hands") or {}
    order = ["Pair", "Two Pair", "Three of a Kind", "Straight", "Flush", "Full House", "Four of a Kind", "High Card"]
    best = max(
        order,
        key=lambda n: (
            int((hands.get(n) or {}).get("level", 1)),
            int((hands.get(n) or {}).get("played", 0)),
            -order.index(n),
        ),
    )
    return best if int((hands.get(best) or {}).get("level", 1)) > 1 or int((hands.get(best) or {}).get("played", 0)) else "Pair"


def main_commit(G: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any] | None:
    """The committed MAIN_HAND after this gamestate (the bot keeps it between
    decisions). A new joker call re-commits; losing the joker does not
    un-commit (sticky only against joker loss)."""
    call = joker_call(G)
    sharp = next((str(j.get("label") or j.get("key")) for j in _area_cards(G, "jokers") if j.get("key") == "j_card_sharp"), None)
    if call and previous and previous.get("deadline") and call[1] == sharp:
        # review round 1: Card Sharp sets no hand type (X3 on any repeated hand),
        # so it does not replace the end-of-Ante-2 commit
        return previous
    if call and (not previous or previous.get("hand") != call[0]):
        return {
            "hand": call[0],
            "trigger": call[1],
            "ante": int(G.get("ante_num") or 1),
            "round": int(G.get("round_num") or 0),
        }
    return previous


DEADLINE_ANTE = 3  # C6: the first shop after the Ante 2 boss (the game shows Ante 3)
DEADLINE_TOP = 3
DEADLINE_NEAR = 0.10  # plays break a near-tie (within 10% of the best score)
DEADLINE_ORDER = ["Pair", "Two Pair", "Three of a Kind", "Straight", "Flush", "Full House", "Four of a Kind"]


def deadline_commit(
    G: dict[str, Any], history: list[dict[str, Any]] | None = None, final: bool = True
) -> dict[str, Any] | None:
    """C6 (owner, after pass 2 Q2 / before pass 3 Q4a): MAIN_HAND still OPEN at
    the end of Ante 2 -> commit to one of the 3 hands played most in Antes 1-2
    (not High Card; the game's own counts): the one scoring most per hand with
    the jokers Luna owns and her levels (mean over the sampled draws, one
    discard; 0 where the type is not made). Within 10%: played more, then
    levelled more, then Pair first. No plays: the leaning hand. Flush: MAIN_SUIT
    = the suit of most Flush plays (history ``flush_suit``), else main_suit.
    Pass 4 F5: a hand counts only when played 2+ times; with none and
    ``final`` False, None (stay OPEN one more shop), then the fallback."""
    hands = G.get("hands") or {}

    def played(t: str) -> int:
        return int((hands.get(t) or {}).get("played", 0))

    def level(t: str) -> int:
        return int((hands.get(t) or {}).get("level", 1))

    ante, rnd = int(G.get("ante_num") or 1), int(G.get("round_num") or 0)
    top = sorted((t for t in hands if t != "High Card" and played(t) >= 2), key=lambda t: (-played(t), DEADLINE_ORDER.index(t) if t in DEADLINE_ORDER else 99))[:DEADLINE_TOP]
    if not top and not final:
        return None
    if not top:
        # the hand levelled most (never High Card), else Pair
        hand = max(DEADLINE_ORDER, key=lambda t: (level(t), -DEADLINE_ORDER.index(t)))
        hand = hand if level(hand) > 1 else "Pair"
        return {"hand": hand, "trigger": f"end of Ante 2: no hand beyond High Card played twice; leaning {hand}",
                "ante": ante, "round": rnd, "deadline": True}
    G_owned = _with_jokers(G, _area_cards(G, "jokers"))
    G_owned["blinds"] = {
        k: {**v, "status": "UPCOMING"} if v.get("status") == "CURRENT" else v
        for k, v in (G.get("blinds") or {}).items()
    }
    dealt = _dealt_hands(G_owned, sample_draws(G))
    scores = {}
    for t in top:
        vals = [_best_play(G_owned, hand, 0, only=t, memo=dealt.memo[n])[0] for n, hand in enumerate(dealt)]
        scores[t] = int(sum(vals) / max(len(vals), 1))
    best = max(scores.values())
    near = [t for t in top if scores[t] >= (1 - DEADLINE_NEAR) * best]
    hand = max(near, key=lambda t: (played(t), level(t), t == "Pair"))
    out = {
        "hand": hand,
        "trigger": f"end of Ante 2: played {played(hand)} times, {fmt_num(scores[hand])} per hand with your jokers",
        "ante": ante,
        "round": rnd,
        "deadline": True,
        "scores": scores,
    }
    if hand == "Flush":
        suits = Counter(str(h.get("flush_suit")) for h in history or [] if h.get("flush_suit"))
        out["suit"] = suits.most_common(1)[0][0] if suits else main_suit(G)
    return out


def main_hand_plan(G: dict[str, Any]) -> dict[str, Any]:
    """MAIN_HAND: OPEN until jokers call for a hand, then committed (P2-4).

    OPEN: the hand shown is the one levelled most ("leaning"), nothing is
    [OFF-PLAN], and Luna plays the best hand dealt. Committed: from a joker
    call (or the deck), kept after the joker is sold (``G["luna"]
    ["main_commit"]``, carried by the bot), replaced by a new call.
    """
    commit = main_commit(G, (G.get("luna") or {}).get("main_commit"))
    suit = main_suit(G)
    ante = int(G.get("ante_num") or 1)
    if commit:
        hand = commit["hand"]
        reason = f"committed: {commit['trigger']}"
        if commit.get("round"):
            reason += f" (round {commit['round']})"
        is_open = False
    else:
        hand = leaning_hand(G)
        reason = "OPEN: no joker calls for a hand yet; play the best hand dealt"
        is_open = True
    if commit and commit.get("suit") and hand == "Flush":
        suit = commit["suit"]  # C6: the suit of most Flush plays
    return {
        "hand": hand,
        "family": knowledge.HAND_FAMILY.get(hand, "pair"),
        "suit": suit if hand == "Flush" else None,
        "reason": reason,
        "open": is_open,
        "commit": commit,
        # draws worth discarding toward (shown to the model and used for advice)
        "draw_kinds": {"Flush", "Straight"} if is_open or ante <= OPEN_ANTES else {hand},
    }


def _pad_allowed(G: dict[str, Any]) -> bool:
    keys = set(_joker_keys(G))
    return "j_half" not in keys and _active_boss(G) != "The Tooth"


def held_scoring_ranks(G: dict[str, Any]) -> set[str]:
    """Ranks that score while HELD: Kings with Baron, Queens with Shoot the Moon
    (copies by Blueprint / Brainstorm count)."""
    keys = set(_joker_keys(G)) | set(copied_keys(G))
    return ({"K"} if "j_baron" in keys else set()) | (
        {"Q"} if "j_shoot_the_moon" in keys else set()
    )


def _classify_flags(G: dict[str, Any]) -> dict[str, bool]:
    keyset = set(_joker_keys(G))
    return {
        "four_fingers": "j_four_fingers" in keyset,
        "shortcut": "j_shortcut" in keyset,
        "smeared": "j_smeared" in keyset,
    }


def _filler(
    G: dict[str, Any],
    hand: list[dict[str, Any]],
    play: list[int],
    plan: dict[str, Any],
    count: int,
) -> list[int]:
    """Up to ``count`` lowest-value cards outside ``play`` to pad it with.

    Never MAIN suit cards, Steel/Gold/Blue Seal cards or cards that score while
    held (Kings with Baron, Queens with Shoot the Moon), and never a card that
    changes the hand type of the play (a third 3 next to a Pair of 3s, a fifth
    Heart next to four Hearts): the play is re-classified after each filler.
    """
    suit = plan.get("suit")
    keep_ranks = held_scoring_ranks(G)
    pool = [
        i
        for i, c in enumerate(hand)
        if i not in play
        and not c["hidden"]
        and c["enh"] not in ("STEEL", "GOLD")
        and c["seal"] != "BLUE"
        and c["rank"] not in keep_ranks
        and not (suit and (c["suit"] == suit or c["enh"] == "WILD"))
    ]
    board = "j_blackboard" in set(_joker_keys(G)) | set(copied_keys(G))
    pool.sort(key=lambda i: (not (board and _red(hand[i])), CHIP_VALUE.get(hand[i]["rank"] or "", 0)))
    flags = _classify_flags(G)
    base = classify([hand[i] for i in play], **flags)[0]
    out: list[int] = []
    for i in pool:
        if len(out) >= count:
            break
        trial = [hand[j] for j in [*play, *out, i]]
        if classify(trial, **flags)[0] == base:
            out.append(i)
    return out


MAIL_RANK_NAMES = {
    "Ace": "A",
    "King": "K",
    "Queen": "Q",
    "Jack": "J",
    "10": "T",
    **{str(n): str(n) for n in range(2, 10)},
}


def mail_rank(G: dict[str, Any]) -> str | None:
    """Rank Mail-In Rebate pays $5 for when discarded this round, if owned."""
    for j in _area_cards(G, "jokers"):
        if j.get("key") == "j_mail":
            effect = (j.get("value") or {}).get("effect", "") or ""
            m = re.search(r"discarded (\w+)", effect)
            if m:
                return MAIL_RANK_NAMES.get(m.group(1))
    return None


def suggested_discard(
    G: dict[str, Any], plan: dict[str, Any], protect: Iterable[int] = ()
) -> list[int]:
    """Up to 5 indices to discard toward MAIN_HAND, never touching ``protect``."""
    hand = [_norm(c) for c in _area_cards(G, "hand")]
    limit = int((G.get("hand") or {}).get("highlighted_limit", 5) or 5)
    protect = set(protect)
    keyset = set(_joker_keys(G))
    groups = _suit_groups("j_smeared" in keyset)
    if plan["hand"] == "Flush":
        suit_counts = Counter(
            groups[c["suit"]] for c in hand if c["suit"] and not c["hidden"]
        )
        target = groups.get(plan.get("suit") or "H", "H")
        if suit_counts:
            best = max(suit_counts.values())
            # chase the main suit unless another suit is clearly ahead in hand
            if suit_counts.get(target, 0) + 1 < best:
                target = max(suit_counts, key=lambda g: suit_counts[g])
        keep = {
            i
            for i, c in enumerate(hand)
            if c["enh"] == "WILD" or (c["suit"] and groups[c["suit"]] == target)
        }
    else:
        rc = Counter(c["rank"] for c in hand if c["rank"] and not c["hidden"])
        keep = {i for i, c in enumerate(hand) if c["rank"] and rc[c["rank"]] >= 2}
        # Cards of a suit a joker pays for (Ancient Joker X1.5, suit Mult
        # jokers) are kept: they score more and build that suit's Flush
        paid = {p["suit"] for p in suit_pays(G)}
        keep |= {
            i
            for i, c in enumerate(hand)
            if not c["hidden"] and (c["enh"] == "WILD" or (c["suit"] and groups[c["suit"]] in {groups[x] for x in paid}))
        }
    keep |= protect
    keep |= {i for i, c in enumerate(hand) if c["stone"] and plan["hand"] != "Flush"}
    keep |= {i for i, c in enumerate(hand) if c["face"]}  # C3: never discard face-down cards under The Mark
    keys = set(_joker_keys(G)) | set(copied_keys(G))
    return _discard_choice(hand, keep, limit, mail_rank(G), keys)


# P2: what one discard costs with jokers that dislike discards (facts only;
# the harness never refuses a discard)
DISCARD_COSTS = {
    "j_banner": "Banner -30 Chips per discard used",
    "j_green_joker": "Green Joker -1 Mult per discard",
    "j_ramen": "Ramen -X0.01 per card discarded",
    "j_blue_joker": "Blue Joker -2 Chips per card drawn from the deck",
    "j_delayed_grat": "Delayed Gratification pays $2 per discard only if you use none this round",
}


def discard_costs(G: dict[str, Any]) -> list[str]:
    keys = set(_joker_keys(G)) | set(copied_keys(G))
    out = [text for key, text in DISCARD_COSTS.items() if key in keys]
    if "j_mystic_summit" in keys:
        out.append("Mystic Summit +15 Mult once DISCARDS reach 0 (a gain)")
    return out


def _discard_hurts(G: dict[str, Any]) -> bool:
    """A joker loses value with every discard: the on-pace dig is shown, not
    suggested (P2: do not dig when the cost may exceed the gain)."""
    keys = set(_joker_keys(G)) | set(copied_keys(G))
    return bool(keys & {"j_banner", "j_green_joker", "j_ramen", "j_blue_joker", "j_delayed_grat"})


def house_blind_play(G: dict[str, Any]) -> dict[str, Any] | None:
    """P2 / The House: every card is face down; estimate a blind play of the
    cards dealt (they still score). Facts only, Luna chooses."""
    if _active_boss(G) != "The House":
        return None
    hand = [_norm(c) for c in _area_cards(G, "hand")]
    if not hand or not all(c["hidden"] for c in hand):
        return None
    n = 5 if _pad_allowed(G) else 1
    draws = sample_draws(G)[:SHOP_SAMPLES]
    scores = [
        int(estimate_play(G, dealt[:n], dealt[n:])["score"]) for dealt, _ in draws if len(dealt) >= n
    ]
    if not scores:
        return None
    scores.sort()
    return {"cards": list(range(min(n, len(hand)))), "typical": scores[len(scores) // 2], "n": n}


def _mark_repeats(G: dict[str, Any], plays: list[dict[str, Any]]) -> None:
    """P4: Card Sharp X3 for a hand type already played this round."""
    if "j_card_sharp" not in set(_joker_keys(G)) | set(copied_keys(G)):
        return
    hands = G.get("hands") or {}
    for p in plays:
        if (hands.get(p["hand"]) or {}).get("played_this_round", 0):
            p["repeat"] = True


def repeat_note(G: dict[str, Any]) -> str | None:
    if "j_card_sharp" not in set(_joker_keys(G)) | set(copied_keys(G)):
        return None
    played = [n for n, h in (G.get("hands") or {}).items() if (h or {}).get("played_this_round", 0)]
    if played:
        return f"Card Sharp: X3 for {', '.join(played)} (already played this round): repeat it if you can"
    return "Card Sharp: X3 from the 2nd time a hand type is played this round: pick a type you can repeat"


def _blackboard_pad(
    G: dict[str, Any], hand_raw: list[dict[str, Any]], hand: list[dict[str, Any]], p: dict[str, Any]
) -> dict[str, Any]:
    """V8: with Blackboard, add the red cards to the play so every card held is
    black (X3), when that keeps the hand type and scores more."""
    if "j_blackboard" not in set(_joker_keys(G)) | set(copied_keys(G)) or p.get("blocked"):
        return p
    if not _pad_allowed(G) or _active_boss(G) == "The Psychic":
        return p
    limit = int((G.get("hand") or {}).get("highlighted_limit", 5) or 5)
    rest = [i for i in range(len(hand)) if i not in p["cards"]]
    if any(hand[i]["hidden"] for i in rest):
        return p
    reds = [i for i in rest if _red(hand[i])]
    if not reds or len(p["cards"]) + len(reds) > limit:
        return p
    cards = sorted([*p["cards"], *reds])
    flags = _classify_flags(G)
    if classify([hand[i] for i in cards], **flags)[0] != p["hand"]:
        return p
    est = estimate_play(G, [hand_raw[i] for i in cards], [hand_raw[i] for i in range(len(hand)) if i not in cards])
    if int(est["score"]) <= int(p["score"]):
        return p
    return {**p, "cards": cards, "score": int(est["score"]), "padded": "red cards added: every held card is black (Blackboard X3)"}


MARK = "The Mark"
MARK_SAMPLES = 60
MARK_PLAY_SAMPLES = 300  # the face-down play's "about" (review round 2: 60 draws were up to ~30% off)


def mark_active(G: dict[str, Any]) -> bool:
    """The Mark is the blind being played (its face cards come face down)."""
    return _active_boss(G) == MARK


def _mark_pool(G: dict[str, Any]) -> list[dict[str, Any]]:
    """Cards a face-down card under The Mark can be: the face cards (J, Q, K;
    every card with Pareidolia) among the unseen cards (deck + face-down hand),
    face up. A multiset Luna can know from her deck; never which is which."""
    pareidolia = "j_pareidolia" in set(_joker_keys(G))
    pool = []
    hand = [c for c in _area_cards(G, "hand") if (c.get("state") or {}).get("hidden")]
    for c in _area_cards(G, "cards") + hand:
        n = _norm(c)
        # with Pareidolia every card is a face card, Stone cards too (the game's
        # is_face; review r7 opus R7-1); without it a Stone card is never face down
        if not pareidolia and (n["stone"] or not n["rank"]):
            continue
        if pareidolia or n["rank"] in FACE_RANKS:
            up = _face_up(c)
            pool.append({**up, "state": {k: v for k, v in (up.get("state") or {}).items() if k != "debuff"}})
    return sorted(pool, key=_card_id)


def mark_view(G: dict[str, Any]) -> dict[str, Any]:
    """C3: G with each face-down hand card masked while The Mark is current:
    a face card (10 chips) of unknown rank, suit and enhancement. BalatroBot
    sends a face-down card's real rank and suit; Luna cannot see them, so the
    advice must not use them. Other blinds: G unchanged."""
    if not mark_active(G):
        return G
    cards = _area_cards(G, "hand")
    if not any((c.get("state") or {}).get("hidden") for c in cards):
        return G
    pool = _mark_pool(G)
    ranks = Counter(_norm(c)["rank"] for c in pool)
    total = max(len(pool), 1)
    mix = {r: ranks.get(r, 0) / total for r in ("J", "Q", "K")}
    masked = []
    for c in cards:
        if (c.get("state") or {}).get("hidden"):
            masked.append({
                "id": c.get("id"),
                "key": "",
                "set": "DEFAULT",
                "label": "face-down card",
                "value": {"rank": None, "suit": None, "effect": ""},
                "modifier": {},
                "state": {"hidden": True, "mark_face": True, "mark_mix": mix},
                "cost": c.get("cost"),
            })
        else:
            masked.append(c)
    # The deck counts Luna sees must not tell which face cards are in hand:
    # the face-down cards join the deck as one unseen pile (deck + face-down)
    unseen = _area_cards(G, "cards") + [_face_up(c) for c in cards if (c.get("state") or {}).get("hidden")]
    deck = {**(G.get("cards") or {}), "cards": sorted(unseen, key=_card_id)}
    deck["count"] = len(unseen)
    return {**G, "hand": {**(G.get("hand") or {}), "cards": masked}, "cards": deck, "mark_unseen": True}


def _mark_minimum(pool: list[dict[str, Any]], n: int) -> str | None:
    """The hand type ``n`` face-down cards make at the least, whatever their
    ranks (the pool's rank counts; suits ignored: a Flush only adds). None
    when no hand beyond High Card is sure."""
    counts = Counter(_norm(c)["rank"] for c in pool)  # rank None = a Stone card (Pareidolia)
    ranks = sorted(counts, key=lambda r: (r is None, r or ""))
    if n <= 0 or sum(counts.values()) < n:
        return None
    worst = None
    for combo in combinations_with_replacement(ranks, n):
        if any(combo.count(r) > counts[r] for r in set(combo)):
            continue
        # a Stone card adds no rank, so it only weakens the hand
        cards = [_norm(_synthetic_card("HDCS"[k % 4], r)) for k, r in enumerate(combo) if r is not None]
        if not cards:
            worst = "High Card"
            break
        htype = classify(cards)[0]
        if worst is None or HAND_ORDER.index(htype) > HAND_ORDER.index(worst):
            worst = htype
            if worst == "High Card":
                break
    return None if worst in (None, "High Card") else worst


MARK_FLOOR_MAX = 2000
MARK_FLOOR_RAW_MAX = 60000
MARK_HELD_FLOOR_MAX = 1000  # held face-down class sequences walked for face-up plays (review r5: was 300 card fillings)
HELD_KEYS = {"j_baron", "j_shoot_the_moon", "j_mime", "j_blackboard", "j_raised_fist"}  # raw slot fillings walked before de-duplication


def _mark_floor(G: dict[str, Any], pool: list[dict[str, Any]], hand: list[dict[str, Any]],
                hidden: list[int], played: list[int], cap: int | None = None) -> int | None:
    """The lowest FLOOR score of playing hand slots ``played`` over every
    distinct way the unseen face cards can fill the face-down slots ``hidden``
    (which card is where: played or held, in hand order, so the order of the
    played cards AND of the held cards next to the face-up ones is covered:
    Hanging Chad, Photograph, Glass, Steel + Shoot the Moon ...).
    None when there are too many ways: then no WINS claim (review rounds 1-3)."""
    k = len(hidden)
    if k > len(pool) or perm(len(pool), k) > MARK_FLOOR_RAW_MAX:
        return None
    seen: set[tuple[str, ...]] = set()
    low: int | None = None
    ids = [_card_id(c) for c in pool]
    for pick in permutations(range(len(pool)), k):
        key = tuple(ids[i] for i in pick)
        if key in seen:
            continue
        seen.add(key)
        if len(seen) > (cap or MARK_FLOOR_MAX):
            return None
        cards = list(hand)
        for slot, i in zip(hidden, pick):
            cards[slot] = pool[i]
        est = int(estimate_play(G, [cards[i] for i in played], [c for i, c in enumerate(cards) if i not in played])["score"])
        low = est if low is None else min(low, est)
    return low


def _mark_fill(hand: list[dict[str, Any]], hidden: list[int], pick: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``hand`` with the face-down slots filled by ``pick`` (in slot order)."""
    cards = list(hand)
    for slot, c in zip(hidden, pick):
        cards[slot] = c
    return cards


def play_estimate(G: dict[str, Any], chosen: list[int]) -> int:
    """The FLOOR estimate of playing hand indices ``chosen`` as Luna can know
    it (MEMORY "[estimate was X]"). Under The Mark, face-down cards are given
    identities from the unseen face-card pool and the score is the mean over
    the same kind of draws as the face-down play line, so it never depends on
    which face card is which (C3, review round 1)."""
    hand = _area_cards(G, "hand")
    chosen = sorted(set(chosen))
    hidden = [i for i, c in enumerate(hand) if (c.get("state") or {}).get("hidden")]
    if mark_active(G) and hidden and (mp := mark_play(G)) and chosen == sorted(mp["cards"]):
        return int(mp["expected"])  # the face-down play: exactly the number Luna was shown
    if not mark_active(G) or not hidden:
        seen = mark_view(G)
        cards = _area_cards(seen, "hand")
        return int(estimate_play(seen, [cards[i] for i in chosen], [c for i, c in enumerate(cards) if i not in chosen])["score"])
    return _mark_about(G, chosen)


def _mark_about(G: dict[str, Any], chosen: list[int]) -> int:
    """Under The Mark, the mean score of playing hand slots ``chosen`` over
    MARK_PLAY_SAMPLES draws of the face-down cards from the unseen face-card
    pool: the "about" of a listed face-up play and its MEMORY estimate."""
    hand = _area_cards(G, "hand")
    chosen = sorted(set(chosen))
    hidden = [i for i, c in enumerate(hand) if (c.get("state") or {}).get("hidden")]
    pool = _mark_pool(G)
    if len(pool) < len(hidden):
        return 0
    visible = {i: c for i, c in enumerate(hand) if i not in hidden}
    ids = sorted(_card_id(c) for c in pool)
    seen_ids = sorted(_card_id(c) for c in visible.values())
    n_chosen = sum(1 for i in chosen if i in hidden)
    seed = int(hashlib.md5(json.dumps([ids, seen_ids, len(hidden), n_chosen, "estimate"]).encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    scores = []
    for _ in range(MARK_PLAY_SAMPLES):
        cards = _mark_fill(hand, hidden, rng.sample(pool, len(hidden)))
        scores.append(int(estimate_play(G, [cards[i] for i in chosen], [c for i, c in enumerate(cards) if i not in chosen])["score"]))
    return int(sum(scores) / len(scores))


def _mark_held_fills(G: dict[str, Any]) -> list[list[dict[str, Any]]] | str | None:
    """Under The Mark, when cards held in hand can score (Baron, Shoot the
    Moon, Mime, Blackboard, Raised Fist, or a Steel face card unseen): every
    distinct way the unseen face cards fill the face-down slots, as full hands.
    "unknown" when there are more than MARK_HELD_FLOOR_MAX (then the masked
    score is the floor: it is a proven lower bound); None when held face-down cards cannot change a
    face-up play's score. Review rounds 3 (opus R1), 4 (codex R4-1) and 5 (opus R5-1)."""
    hand = _area_cards(G, "hand")
    hidden = [i for i, c in enumerate(hand) if (c.get("state") or {}).get("hidden")]
    if not hidden or not mark_active(G):
        return None
    pool = _mark_pool(G)
    keys = set(_joker_keys(G)) | set(copied_keys(G))
    if not (keys & HELD_KEYS or any(_norm(c)["enh"] == "STEEL" for c in pool)):
        return None
    k = len(hidden)
    if k > len(pool):
        return "unknown"
    # A held card changes a face-up play's score only through what
    # estimate_play reads of HELD cards, and only under the jokers that read
    # it: full rank for Raised Fist, "is a King" for Baron, "is a Queen" for
    # Shoot the Moon, black suit or Wild for Blackboard (own or copied);
    # Steel, Red Seal and debuff always. Fillings that agree on these, slot by
    # slot, score the same, so each such class sequence is walked once (exact;
    # review r5 opus R5-1, joker-aware r6 opus R6-1).
    fist, baron, moon, board = ("j_raised_fist" in keys, "j_baron" in keys, "j_shoot_the_moon" in keys,
                                "j_blackboard" in keys)
    classes: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for c in pool:
        n = _norm(c)
        rank = n["rank"] if fist else (baron and n["rank"] == "K", moon and n["rank"] == "Q")
        black = board and (n["suit"] in ("S", "C") or n["enh"] == "WILD")
        key = (rank, n["enh"] == "STEEL", n["seal"] == "RED", black, n["debuff"])
        classes.setdefault(key, []).append(c)
    reps = [v[0] for v in classes.values()]
    left = [len(v) for v in classes.values()]
    fills: list[list[dict[str, Any]]] = []
    pick: list[dict[str, Any]] = []

    def walk() -> bool:
        if len(pick) == k:
            fills.append(_mark_fill(hand, hidden, list(pick)))
            return len(fills) <= MARK_HELD_FLOOR_MAX
        for i, rep in enumerate(reps):
            if left[i]:
                left[i] -= 1
                pick.append(rep)
                ok = walk()
                pick.pop()
                left[i] += 1
                if not ok:
                    return False
        return True

    if not walk():
        return "unknown"
    return fills


def _fill_score(G: dict[str, Any], cards: list[dict[str, Any]], played: list[int]) -> int:
    return int(estimate_play(G, [cards[i] for i in played], [c for i, c in enumerate(cards) if i not in played])["score"])


def _best_by_floor(G: dict[str, Any], fills: list[list[dict[str, Any]]],
                   group: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The play in ``group`` (one hand type, face-up cards only) with the
    highest exact floor over ``fills``; its ``score`` becomes that floor.
    Exact: a play's score under the first filling bounds its floor from
    above, so plays are floored in that order until no bound can beat the best."""
    if not group:
        return None
    bounds = sorted(((_fill_score(G, fills[0], p["cards"]), n) for n, p in enumerate(group)), reverse=True)
    best_p, best_f = None, None
    for bound, n in bounds:
        if best_f is not None and bound <= best_f:
            break
        p = group[n]
        f = min(bound, min((_fill_score(G, cards, p["cards"]) for cards in fills[1:]), default=bound))
        if best_f is None or f > best_f:
            best_p, best_f = p, f
    assert best_p is not None and best_f is not None
    return {**best_p, "score": best_f}


def mark_play(G: dict[str, Any]) -> dict[str, Any] | None:
    """C3 (ii): "play the face-down cards" under The Mark: all of them, up to
    5. Expected (mean FLOOR estimate over the unseen J/Q/K mix), lowest seen,
    the hand type sure at the least, and the most likely type. Sampled from
    the unseen pool only (permutation-invariant: the real face-down cards are
    never used one by one)."""
    if not mark_active(G):
        return None
    hand = _area_cards(G, "hand")
    hidden = [i for i, c in enumerate(hand) if (c.get("state") or {}).get("hidden")]
    if not hidden:
        return None
    n = min(5, len(hidden))
    pool = _mark_pool(G)
    if len(pool) < len(hidden):
        return None
    visible = [c for c in hand if not (c.get("state") or {}).get("hidden")]
    ids = sorted(_card_id(c) for c in pool)
    seen = sorted(_card_id(c) for c in visible)
    seed = int(hashlib.md5(json.dumps([ids, seen, len(hidden)]).encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    played = hidden[:n]
    scores, types = [], Counter()
    for _ in range(MARK_PLAY_SAMPLES):
        cards = _mark_fill(hand, hidden, rng.sample(pool, len(hidden)))
        est = estimate_play(G, [cards[i] for i in played], [c for i, c in enumerate(cards) if i not in played])
        scores.append(int(est["score"]))
        types[est["hand"]] += 1
    floor = _mark_floor(G, pool, hand, hidden, played)
    return {
        "cards": hidden[:n],
        "n": n,
        "expected": int(sum(scores) / len(scores)),
        "low": min(scores),  # lowest of the sampled draws (not a guarantee)
        "floor": floor,  # lowest over every possible set of face cards (None: too many to check)
        "minimum": _mark_minimum(pool, n),
        "likely": types.most_common(1)[0][0],
        "any_rank": "j_pareidolia" in set(_joker_keys(G)),
    }


def _padding_holds(
    G: dict[str, Any], hand_raw: list[dict[str, Any]], base: list[int], padded: list[int], target: float | None
) -> bool:
    """Pass 4 F2: keep filler padding only if the padded play scores no less
    than the unpadded one (same estimate_play on the same view), is not newly
    blocked and, for a WINS play, still reaches ``target``."""
    if sorted(padded) == sorted(base):
        return True

    def est(sel: list[int]) -> dict[str, Any]:
        chosen = set(sel)
        return estimate_play(
            G, [hand_raw[i] for i in sorted(chosen)], [c for i, c in enumerate(hand_raw) if i not in chosen]
        )

    try:
        e0, e1 = est(base), est(padded)
    except (IndexError, TypeError, ValueError):
        return False
    if e1["blocked"] and not e0["blocked"]:
        return False
    if e1["score"] < e0["score"]:
        return False
    return target is None or e1["score"] >= target


# ---------------------------------------------------------------------------
# Pass 4 E3: play for the win. On the last hand (and the second-last when the
# best play cannot reach the remaining target in two hands) the suggested
# action is chosen by its chance to beat the blind, sampled over the REMAINING
# deck: each discard option = discard, draw back up, play the best play (FLOOR
# scores, the WINS threshold), and on the second-last hand one more hand after
# it. One discard is modelled (a lower bound when more discards are left).
# Deterministic: the RNG is seeded from the cards, the result is cached per G.
# ---------------------------------------------------------------------------
E3_SAMPLES = 96  # draws per finished option (common random numbers)
E3_SCREEN = 24  # every option is first screened on this many draws
E3_FINAL = 2  # the best screened options (plus the old choice) get all draws
E3_SWITCH = 0.04  # another option must beat the old choice by more than this
E3_MAX_OPTIONS = 10


def _e3_round(G: dict[str, Any], hands_left: int, discards_left: int) -> dict[str, Any]:
    rnd = dict(G.get("round") or {})
    rnd["hands_left"] = hands_left
    rnd["discards_left"] = max(discards_left, 0)
    return {**G, "round": rnd}


def _e3_after_play(G: dict[str, Any], htype: str) -> dict[str, Any]:
    """G after ``htype`` was played once more this round (Card Sharp, The Eye,
    The Mouth and Supernova read the hands table)."""
    hands = {k: dict(v or {}) for k, v in (G.get("hands") or {}).items()}
    row = hands.setdefault(htype, {})
    row["played_this_round"] = int(row.get("played_this_round", 0) or 0) + 1
    row["played"] = int(row.get("played", 0) or 0) + 1
    return {**G, "hands": hands}


def _e3_keep_sets(G: dict[str, Any], hand: list[dict[str, Any]], plays: list[dict[str, Any]]) -> list[set[int]]:
    """Cards worth keeping for one dig: each listed play, each suit, each
    Straight window with 3+ ranks, each rank held twice or more, nothing."""
    keeps: list[set[int]] = [set(p["cards"]) for p in plays if not p["blocked"]]
    smeared = _classify_flags(G)["smeared"]
    groups = _suit_groups(smeared)
    for g in sorted(set(groups.values())):
        ids = [i for i, c in enumerate(hand)
               if not c["stone"] and (c["enh"] == "WILD" or (c["suit"] and groups[c["suit"]] == g))]
        if len(ids) >= 2:
            ids.sort(key=lambda i: -CHIP_VALUE.get(hand[i]["rank"] or "", 0))
            keeps.append(set(ids[:5]))
    by_rank: dict[str, list[int]] = {}
    for i, c in enumerate(hand):
        if c["rank"] and not c["stone"]:
            by_rank.setdefault(c["rank"], []).append(i)
    for lo in range(1, 11):
        window = ["A" if v in (1, 14) else RANKS[v - 2] for v in range(lo, lo + 5)]
        have = [by_rank[r][0] for r in window if r in by_rank]
        if len(have) >= 3:
            keeps.append(set(have))
    for _r, ids in by_rank.items():
        if len(ids) >= 2:
            keeps.append(set(ids))
    keeps.append(set())
    return keeps


def _e3_choice(
    G: dict[str, Any],
    plays: list[dict[str, Any]],
    progress: dict[str, Any],
    discards: int,
    margin: float,
    old: dict[str, Any],
    suggested: list[int] | None,
) -> dict[str, Any] | None:
    """Chance to beat the blind of playing the best play now vs each discard
    option. None when E3 does not apply; else the options and the choice."""
    hand_raw = _area_cards(G, "hand")
    hand = [_norm(c) for c in hand_raw]
    deck_raw = _area_cards(G, "cards")
    remaining = int(progress.get("remaining") or 0)
    h = int(progress.get("hands_left") or 0)
    goal = margin * remaining
    live = [p for p in plays if not p["blocked"]]
    best = max(live, key=lambda p: p.get("floor", p["score"]), default=None)
    best_floor = best.get("floor", best["score"]) if best else 0
    if (
        remaining <= 0 or discards <= 0 or not deck_raw or not hand_raw
        or any(c["hidden"] for c in hand)
        or not (h == 1 or (h == 2 and best_floor * 2 < goal))
    ):
        return None
    key = _state_key(G, "e3", margin, old.get("tool"), old.get("cards"), suggested)

    def make() -> dict[str, Any]:
        return _e3_sample(G, hand_raw, hand, deck_raw, live, best, h, remaining, goal, discards, old, suggested)

    return _cached(key, make)


def _e3_sample(
    G: dict[str, Any],
    hand_raw: list[dict[str, Any]],
    hand: list[dict[str, Any]],
    deck_raw: list[dict[str, Any]],
    live: list[dict[str, Any]],
    best: dict[str, Any] | None,
    h: int,
    remaining: int,
    goal: float,
    discards: int,
    old: dict[str, Any],
    suggested: list[int] | None,
) -> dict[str, Any]:
    deck = sorted((_face_up(c) for c in deck_raw), key=_card_id)
    size = _hand_size(G)
    limit = int((G.get("hand") or {}).get("highlighted_limit", 5) or 5)
    boss = _active_boss(G)
    pad = 5 if boss == "The Psychic" else 0
    serpent = boss == "The Serpent"
    keys = _joker_keys(G)

    # Options: the old choice first (so it is compared on equal terms), then
    # the suggested discard, then one dig per keep set
    options: list[tuple[int, ...]] = []
    old_discard = tuple(sorted(old["cards"])) if old.get("tool") == "discard" and old.get("cards") else None
    for d in (old_discard, tuple(sorted(suggested)) if suggested else None):
        if d and d not in options:
            options.append(d)
    lim = min(limit, len(deck))
    for keep in _e3_keep_sets(G, hand, live):
        d = tuple(_discard_choice(hand, keep, lim, keys=keys))
        if d and d not in options:
            options.append(d)
    options = options[:E3_MAX_OPTIONS]

    ids = sorted(_card_id(c) for c in hand_raw)
    seed = int(hashlib.md5(json.dumps([ids, [_card_id(c) for c in deck], remaining, h, discards]).encode())
               .hexdigest()[:12], 16)
    rng = random.Random(seed)
    take = min(len(deck), 2 * max(limit, 5) + 3)
    # Deterministic cost cap: with held-card value (Baron, Shoot the Moon, Raised
    # Fist, Blackboard, Steel cards) every candidate play is also padded, so
    # those states get half the draws
    heavy = bool((set(keys) | set(copied_keys(G))) & HELD_CANDIDATE_KEYS) or any(c["enh"] == "STEEL" for c in hand)
    n_samples = E3_SAMPLES // 2 if heavy else E3_SAMPLES
    screen = E3_SCREEN // 2 if heavy else E3_SCREEN
    perms = [rng.sample(range(len(deck)), take) for _ in range(n_samples)]

    norms = {id(c): _norm(c) for c in [*hand_raw, *deck]}
    ctx = _estimate_ctx(G)

    def best_of(Gx: dict[str, Any], cards: list[dict[str, Any]], stop: float | None) -> tuple[int, str, list[int]]:
        memo = {"norm": [norms[id(c)] for c in cards]}
        return _best_play(Gx, cards, pad, memo=memo, ctx=ctx, expected=False, stop_at=stop)  # ctx does not depend on round

    def refill(n_held: int) -> int:
        return 3 if serpent else max(size - n_held, 0)

    G_last = _e3_round(G, 1, discards - 1)
    after: dict[tuple[int, str], dict[str, Any]] = {}

    def last_G(disc_left: int, htype: str) -> dict[str, Any]:
        # the final hand sees the first hand's type as played this round
        k = (disc_left, htype)
        if k not in after:
            after[k] = _e3_after_play(G_last if disc_left == discards - 1 else _e3_round(G, 1, disc_left), htype)
        return after[k]

    def second(rest: list[dict[str, Any]], perm: list[int], start: int, Gx: dict[str, Any], need: float) -> int:
        n = min(refill(len(rest)), len(perm) - start)
        nxt = rest + [deck[j] for j in perm[start:start + max(n, 0)]]
        return best_of(Gx, nxt, need)[0]

    def play_now(cards: list[int]) -> dict[str, Any]:
        """Chance of playing exactly ``cards`` now (FLOOR score, as WINS)."""
        chosen = set(cards)
        est = estimate_play(G, [hand_raw[i] for i in sorted(chosen)],
                            [c for i, c in enumerate(hand_raw) if i not in chosen])
        s0 = 0 if est["blocked"] else int(est["score"])
        if h == 1 or s0 >= goal:
            chance = 1.0 if s0 >= goal else 0.0
        else:
            rest = [c for i, c in enumerate(hand_raw) if i not in chosen]
            Gx = last_G(discards, est["hand"])
            chance = sum(1 for perm in perms if s0 + second(rest, perm, 0, Gx, goal - s0) >= goal) / len(perms)
        return {"hand": est["hand"], "cards": sorted(chosen), "chance": chance}

    # Play the best listed play now, and the exact old play (with its filler)
    # when the old action is a different play
    play = None
    if best is not None:
        play = play_now(list(best["cards"]))
        play["hand"] = best["hand"]
        if h == 1:  # the listed floor decides, as WINS does
            play["chance"] = 1.0 if best.get("floor", best["score"]) >= goal else 0.0
    old_play = None
    if old.get("tool") == "play" and old.get("cards"):
        if play is not None and sorted(old["cards"]) == play["cards"]:
            old_play = play
        else:
            old_play = play_now(list(old["cards"]))

    G1 = _e3_round(G, h, discards - 1)

    def hit(kept: list[dict[str, Any]], n_draw: int, perm: list[int]) -> bool:
        new = kept + [deck[j] for j in perm[:n_draw]]
        s1, t1, play1 = best_of(G1, new, goal)
        if s1 >= goal:
            return True
        if h == 2 and s1 > 0:
            rest = [c for i, c in enumerate(new) if i not in set(play1)]
            return s1 + second(rest, perm, n_draw, last_G(discards - 1, t1), goal - s1) >= goal
        return False

    # Screen every option on the first E3_SCREEN draws, then finish the old
    # choice and the E3_FINAL best on all E3_SAMPLES (same draws for all)
    stats = []
    for d in options:
        kept = [c for i, c in enumerate(hand_raw) if i not in d]
        n_draw = min(refill(len(kept)), take)
        hits = sum(hit(kept, n_draw, perm) for perm in perms[:screen])
        stats.append([d, kept, n_draw, hits, screen])
    order = sorted(range(len(stats)), key=lambda k: -stats[k][3])
    finish = set(order[:E3_FINAL]) | ({0} if old_discard and stats else set())
    for k in finish:
        d, kept, n_draw, hits, _n = stats[k]
        stats[k][3] = hits + sum(hit(kept, n_draw, perm) for perm in perms[screen:])
        stats[k][4] = len(perms)
    results = [{"discard": list(d), "chance": hits / n, "samples": n} for d, _k, _n, hits, n in stats]
    top = max((r for r in results if r["samples"] == len(perms)), key=lambda r: r["chance"], default=None)
    return {
        "hands_left": h,
        "remaining": remaining,
        "play": play,
        "old_play": old_play,
        "options": results,
        "best": top,
        "old_discard": list(old_discard) if old_discard else None,
    }


def _e3_action(G: dict[str, Any], e3: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    """The suggested action from the E3 chances (the old one unless another
    option beats it by more than E3_SWITCH); its why names the chance."""
    hand_raw = _area_cards(G, "hand")

    def names(idx: list[int]) -> str:
        return ", ".join(card_name(hand_raw[i]) for i in idx)

    play = e3["play"]
    old_play = e3.get("old_play")
    top = e3["best"]
    p_play = play["chance"] if play else 0.0
    p_top = top["chance"] if top else 0.0
    if p_top <= 0 and p_play <= 0 and not (old_play and old_play["chance"] > 0):
        return old
    if old.get("tool") == "discard" and e3["old_discard"]:
        p_old = next(r["chance"] for r in e3["options"] if r["discard"] == e3["old_discard"])
    elif old.get("tool") == "play" and old_play:
        p_old = old_play["chance"]
    else:
        p_old = -1.0
    reach = f"to reach {fmt_num(e3['remaining'])}" + (
        " over your last 2 hands" if e3["hands_left"] == 2 else " after this discard"
    )
    # The old choice stays unless another option beats it by more than
    # E3_SWITCH (the same margin for a new discard and for playing now); the
    # chance shown always belongs to the exact cards suggested
    alts = []
    if top and top["discard"] != e3["old_discard"]:
        alts.append((p_top, "discard"))
    if play and not (old_play is not None and old_play["cards"] == play["cards"]):
        alts.append((p_play, "play"))
    p_alt, kind = max(alts, default=(-1.0, None))
    chosen_play = play
    if kind is None or p_alt <= p_old + E3_SWITCH:
        if old.get("tool") == "discard" and e3["old_discard"]:
            kind, cards = "discard", e3["old_discard"]
        elif old.get("tool") == "play" and old_play:
            kind, chosen_play = "play", old_play
        else:
            return old
    elif kind == "discard":
        cards = top["discard"]
    if kind == "discard":
        p = next(r["chance"] for r in e3["options"] if r["discard"] == cards)
        best_now = max((x for x in (play, old_play) if x), key=lambda x: x["chance"], default=None)
        now = f"{pct(best_now['chance'])} playing {best_now['hand']} now" if best_now else "0% playing now"
        why = f"discard {names(cards)}: {pct(p)} {reach} vs {now}"
        return {"tool": "discard", "cards": list(cards), "why": why, "e3": "discard"}
    alt = f"{pct(p_top)} discarding {names(top['discard'])}" if top else "no discard helps"
    reach_p = f"to reach {fmt_num(e3['remaining'])}" + (" over your last 2 hands" if e3["hands_left"] == 2 else "")
    why = f"play {chosen_play['hand']} now: {pct(chosen_play['chance'])} {reach_p} vs {alt}"
    return {"tool": "play", "cards": list(chosen_play["cards"]), "why": why, "e3": "play"}


def play_advice(G: dict[str, Any], top: int = 5) -> dict[str, Any]:
    """Everything the PLAY phase needs: plays with WINS flags, discard, suggestion."""
    # C3: under The Mark the advice sees face-down cards as masked face cards
    mark = mark_play(G)
    G_real = G
    G = mark_view(G)
    plan = main_hand_plan(G)
    analysis_ = analyze_hand(G, top=top, real=G_real if mark else None)
    progress = blind_progress(G) or {"remaining": 0, "per_hand": 0, "hands_left": 0}
    remaining = progress["remaining"]
    per_hand = progress["per_hand"]
    discards = int((G.get("round") or {}).get("discards_left", 0))
    hand_raw = _area_cards(G, "hand")
    hand = [_norm(c) for c in hand_raw]
    boss = _active_boss(G)

    # Estimates are exact without jokers, so the safety margin only applies
    # once jokers (or effects the estimator skips) are involved.
    exact = not _joker_keys(G)
    plays = []
    for p in analysis_["plays"]:
        alt = p.pop("no_blue", None)
        margin = 1.0 if exact and not p["unknown"] else WIN_MARGIN
        # Prefer the version that keeps a Blue Seal card held if it still wins.
        if alt and alt.get("floor", alt["score"]) >= margin * remaining and not alt["blocked"]:
            p = alt
        p = _blackboard_pad(G, hand_raw, hand, p)
        # The Mark with held-card scoring: WINS from the floor, the rest from the mean (review r4 opus F1)
        wins = p.get("floor", p["score"]) >= margin * remaining and not p["blocked"]
        plays.append({**p, "wins": wins, "reaches_pace": p["score"] >= per_hand})
    plays.sort(key=lambda p: -p["score"])
    _mark_repeats(G, plays)
    winners = [p for p in plays if p["wins"]]
    if mark:
        margin_m = 1.0 if exact else WIN_MARGIN
        # WINS only from the exact floor (every possible set of face cards)
        mark["wins"] = remaining > 0 and mark["floor"] is not None and mark["floor"] >= margin_m * remaining
        mark["reaches_pace"] = mark["expected"] >= per_hand
    mark_pace = bool(mark and mark["reaches_pace"])
    # P1: with no winner, dig toward a winning play but keep the best play
    # that is on pace (it is still there if the dig misses)
    on_pace = next((p for p in plays if p["reaches_pace"] and not p["blocked"]), None)
    protect = set(winners[0]["cards"]) if winners else set(on_pace["cards"]) if on_pace else set()
    discard = suggested_discard(G, plan, protect)
    # Only draws the plan allows are shown (Flush/Straight only in the OPEN antes
    # or when MAIN_HAND is that hand); a strong one beats spending a weak hand.
    ante = int(G.get("ante_num") or 1)
    margin = 1.0 if exact else WIN_MARGIN
    best_listed = max((p["score"] for p in plays if not p["blocked"]), default=0)
    any_pace = any(p["reaches_pace"] for p in plays)
    # Already holding a Straight/Flush or better: that IS what Ante 1 chases.
    made_big = any(p["hand"] in BIG_HANDS and not p["blocked"] for p in plays)
    # Simulated: with no jokers, chasing at the Ante 1 boss loses ~10 points
    # of win rate, so the chase needs a joker there.
    chase_allowed = (
        ante <= OPEN_ANTES
        and discards > 0
        and (bool(_joker_keys(G)) or progress.get("kind") != "boss")
    )
    draws = []
    paid_suits = {p["suit"] for p in suit_pays(G)}
    for d in analysis_["draws"]:
        paid_flush = d["kind"] == "Flush" and d.get("suit") in paid_suits
        if d["kind"] not in plan["draw_kinds"] and not paid_flush:
            continue
        # chance to hit within ALL remaining discards (approximation)
        within = 1 - (1 - d["chance"]) ** max(discards, 1)
        # never break up a made hand for a draw that is not clearly bigger
        worth_it = d.get("if_complete", 0) > DRAW_UPGRADE * best_listed or not any_pace
        d = {**d, "worth_it": worth_it}
        chase = chase_allowed and within >= CHASE_DRAW and worth_it and not made_big
        draws.append(
            {
                **d,
                "within": within,
                "chase": chase,
                "one_shot": remaining > 0
                and d.get("if_complete", 0) >= margin * remaining,
            }
        )
    chase_draw = max(
        (d for d in draws if d["chase"] and d["discard"]),
        key=lambda d: (round(d["within"], 2), d["if_complete"]),
        default=None,
    )
    strong_draw = chase_draw or next(
        (
            d
            for d in draws
            if d["chance"] >= STRONG_DRAW and d["discard"] and d["worth_it"]
        ),
        None,
    )
    if strong_draw and not winners:
        discard = strong_draw["discard"]

    action: dict[str, Any]
    blue_in_hand = {i for i, c in enumerate(hand) if c["seal"] == "BLUE"}
    # Square Joker grows on exactly-4-card hands (not against The Psychic/Tooth)
    square = (
        "j_square" in _joker_keys(G)
        and _active_boss(G) not in ("The Psychic", "The Tooth")
        and "j_half" not in _joker_keys(G)
    )
    if winners:
        # A Blue Seal card makes the Planet of the LAST played hand only while
        # it is HELD: win without playing it, ideally with MAIN_HAND.
        best = max(
            winners,
            key=lambda p: (
                not (blue_in_hand & set(p["cards"])),
                bool(blue_in_hand) and p["hand"] == plan["hand"],
                p["score"],
            ),
        )
        why = f"{best['hand']} WINS"
        if blue_in_hand and not (blue_in_hand & set(best["cards"])):
            why += " and keeps the Blue Seal card in hand"
        cards = list(best["cards"])
        if square and len(cards) < 4:
            padded = sorted(cards + _filler(G, hand, cards, plan, 4 - len(cards)))
            win_margin = 1.0 if exact and not best["unknown"] else WIN_MARGIN
            if _padding_holds(G, hand_raw, cards, padded, win_margin * remaining):  # F2
                cards = padded
                why += "; 4 cards grow Square Joker"
        action = {"tool": "play", "cards": cards, "why": why}
    elif mark and mark["wins"]:
        action = {
            "tool": "play",
            "cards": mark["cards"],
            "why": "The Mark: the face-down cards WIN whichever face cards they are (they still score)",
        }
    elif discards > 0 and discard and chase_draw:
        action = {
            "tool": "discard",
            "cards": discard,
            "why": f"Ante 1: chase the {chase_draw['kind']} "
            f"({round(chase_draw['within'] * 100)}% to hit with your discards)",
        }
    elif discards > 0 and discard and strong_draw:
        action = {
            "tool": "discard",
            "cards": discard,
            "why": f"{strong_draw['kind']} draw completes {round(strong_draw['chance'] * 100)}% of the time",
        }
    elif discards > 0 and discard and not any(p["reaches_pace"] for p in plays) and not mark_pace:
        action = {
            "tool": "discard",
            "cards": discard,
            "why": "no play reaches PER_HAND; dig toward MAIN_HAND",
        }
    elif discards > 0 and discard and on_pace and not _discard_hurts(G):
        action = {
            "tool": "discard",
            "cards": discard,
            "why": f"no play wins yet: dig toward a winning play and keep your {on_pace['hand']} "
            "(play on pace only with no discards left)",
        }
    elif discards > 0 and discard and mark_pace and not _discard_hurts(G):
        action = {
            "tool": "discard",
            "cards": discard,
            "why": "no play wins yet: dig with the face-up cards and keep the face-down cards (The Mark: they score)",
        }
    elif mark and (not plays or mark["expected"] > max((p["score"] for p in plays if not p["blocked"]), default=0)):
        action = {
            "tool": "play",
            "cards": mark["cards"],
            "why": f"The Mark: play the face-down cards (about {fmt_num(mark['expected'])}, more than any face-up play)",
        }
    elif plays:
        # never suggest a BLOCKED play when an unblocked one exists (pass 5 G1d, The Mouth)
        best = next((p for p in plays if not p["blocked"]), plays[0])
        cards = list(best["cards"])
        need = 0
        if boss == "The Psychic":
            need = 5 - len(cards)
        elif square and len(cards) < 4:
            need = 4 - len(cards)  # Square Joker grows only on 4-card hands
        elif _pad_allowed(G) and len(cards) < 5 and not square:
            need = 5 - len(cards)
        if need > 0:
            cards = sorted(cards + _filler(G, hand, cards, plan, need))
        if boss == "The Psychic" and len(cards) < 5:
            # 5 cards or the play scores 0: pad with the lowest other cards
            # even if that changes the hand type (the analyser scores both)
            rest = sorted(
                (i for i, c in enumerate(hand) if i not in cards and not c["hidden"]),
                key=lambda i: (hand[i]["rank"] in held_scoring_ranks(G), CHIP_VALUE.get(hand[i]["rank"] or "", 0)),
            )
            cards = sorted(cards + rest[: 5 - len(cards)])
        if not _padding_holds(G, hand_raw, list(best["cards"]), cards, None):  # F2
            cards = list(best["cards"])
        action = {"tool": "play", "cards": cards, "why": f"best play ({best['hand']})"}
    elif discards <= 0:
        # no visible play and no discard left (The Fish: all face down): play
        # face-down cards; a discard suggestion here is illegal (pass 5 G1d)
        down = ([i for i, c in enumerate(hand) if c["hidden"]] or list(range(len(hand))))[:5]
        action = {"tool": "play", "cards": down, "why": "no visible play and no discards left: play face-down cards"}
    else:
        action = {"tool": "discard", "cards": discard, "why": "no visible play"}
    # Pass 4 E3: on the last hand(s) without a sure win, choose by the chance
    # to beat the blind (sampled over the remaining deck)
    e3 = None
    if not winners and not mark:
        e3 = _e3_choice(G, plays, progress, discards, margin, action, discard)
        if e3 is not None:
            action = _e3_action(G, e3, action)
            # "Suggested discard" (STRATEGY rule 2) names the same cards as the
            # E3 action; when E3 says play now it reads "none: play instead"
            kind = action.pop("e3", None)
            if kind == "discard":
                discard = list(action["cards"])
            elif kind == "play":
                discard = []
    # The House (P2, owner row 128): with jokers that lose value on every
    # discard, the suggestion is to play the face-down cards blind
    blind = house_blind_play(G)
    if blind and not winners and _discard_hurts(G):
        action = {
            "tool": "play",
            "cards": blind["cards"],
            "why": f"The House: your jokers lose value with every discard; play face-down cards blind "
            f"(they still score, typically about {fmt_num(blind['typical'])})",
        }
    # A Tarot with suggested targets costs no hand or discard: use it first
    for i, c in enumerate(_area_cards(G, "consumables")):
        if c.get("set") == "TAROT" and (targets := suggest_targets(G, c)):
            action = {
                "tool": "use",
                "consumable": i,
                "cards": targets,
                "why": f"use {c.get('label')} first: it costs no hand or discard",
            }
            break
    return {
        "plan": plan,
        "progress": progress,
        "plays": plays,
        "draws": draws,
        "discard": discard,
        "action": action,
        "strong_draw": strong_draw,
        "blue_in_hand": sorted(blue_in_hand),
        "suit_pays": suit_pays(G),
        "discard_costs": discard_costs(G),
        "mail_rank": mail_rank(G),
        "blind_play": blind,
        "mark_play": mark,
        "repeats": repeat_note(G),
        "acrobat": "j_acrobat" in (set(_joker_keys(G)) | set(copied_keys(G))),
        "hand_suits": analysis_["hand_suits"],
        "deck_size": analysis_["deck_size"],
        "deck_suits": analysis_["deck_suits"],
        "mark_unseen": bool(G.get("mark_unseen")),
        "win_chance": e3,
    }


def suggest_targets(G: dict[str, Any], consumable: dict[str, Any]) -> list[int]:
    """Suggested hand indices for a targeted Tarot/Spectral (may be empty)."""
    key = consumable.get("key", "")
    bounds = CONSUMABLE_TARGETS.get(key)
    if not bounds:
        return []
    lo, hi = bounds
    hand = [_norm(c) for c in _area_cards(G, "hand")]
    plan = main_hand_plan(G)
    suit = plan.get("suit")
    flush = plan["hand"] == "Flush"
    visible = [i for i, c in enumerate(hand) if not c["hidden"] and not c["stone"]]
    rc = Counter(hand[i]["rank"] for i in visible if hand[i]["rank"])
    # "core" = cards the MAIN_HAND is built from; "off" = cards that do not help it.
    if flush:
        on_suit = [i for i in visible if suit and hand[i]["suit"] == suit]
    else:  # Pair family: cards whose rank you already hold 2+ of
        on_suit = [i for i in visible if rc[hand[i]["rank"]] >= 2]
    off_suit = [i for i in visible if i not in on_suit]

    def by_chips(idx: list[int], reverse: bool) -> list[int]:
        return sorted(
            idx, key=lambda i: CHIP_VALUE.get(hand[i]["rank"] or "", 0), reverse=reverse
        )

    if not flush and key == "c_strength":
        # +1 rank: turn a card into a rank you already hold (makes pairs/trips).
        nxt = {r: RANKS[RANKS.index(r) + 1] for r in RANKS[:-1]}
        ups = [
            i
            for i in visible
            if hand[i]["rank"] in nxt
            and rc[hand[i]["rank"]] == 1  # never break an existing pair
            and rc[nxt[hand[i]["rank"]]] >= 1
        ]
        ups.sort(key=lambda i: -rc[nxt[hand[i]["rank"]]])  # trips first
        chosen: list[int] = []
        for i in ups:
            # skip chains (7->8 and 6->7): the 7 is gone when the 6 arrives
            r = hand[i]["rank"]
            if any(
                hand[j]["rank"] == nxt[r] or nxt[hand[j]["rank"]] == r for j in chosen
            ):
                continue
            chosen.append(i)
            if len(chosen) == hi:
                break
        return sorted(chosen)

    suit_tarot = {"c_star": "D", "c_moon": "C", "c_sun": "H", "c_world": "S"}
    if key in suit_tarot:
        if plan["hand"] != "Flush" or suit_tarot[key] != suit:
            return []
        return sorted(by_chips(off_suit, False)[:hi])
    if key in (
        "c_empress",
        "c_heirophant",
        "c_justice",
        "c_magician",
        "c_talisman",
        "c_deja_vu",
        "c_aura",
        "c_cryptid",
        "c_lovers",
        "c_strength",
    ):
        if key == "c_lovers":
            return (
                sorted(by_chips(off_suit, True)[:1]) if plan["hand"] == "Flush" else []
            )
        pool = on_suit if plan["hand"] == "Flush" and on_suit else visible
        unenhanced = [i for i in pool if not hand[i]["enh"]] or pool
        return sorted(by_chips(unenhanced, True)[:hi])
    if key in ("c_chariot", "c_devil", "c_trance"):
        return sorted(by_chips(off_suit or visible, True)[:1])
    if key in ("c_hanged_man", "c_medium"):
        junk = [i for i in off_suit if not hand[i]["enh"] and not hand[i]["seal"]]
        return sorted(by_chips(junk, False)[: (1 if key == "c_medium" else hi)])
    if key == "c_death":
        if len(visible) < 2:
            return []
        # Copy only a modified card (seal, enhancement or edition; Flush:
        # MAIN_SUIT only): sealed first, then what MAIN_HAND wants.
        modified = [
            i
            for i in visible
            if (hand[i]["seal"] or hand[i]["enh"] or hand[i]["ed"])
            and (not flush or i in on_suit)
        ]
        ranked = sorted(
            modified,
            key=lambda i: (
                hand[i]["seal"] is not None,
                0 if flush else rc[hand[i]["rank"]],
                hand[i]["enh"] is not None,
                i in on_suit,
                CHIP_VALUE.get(hand[i]["rank"] or "", 0),
            ),
            reverse=True,
        )
        # Death turns the LEFT selected card into a copy of the RIGHT one, so
        # the junk card must sit at a lower index than the card to copy.
        plain = [
            i
            for i in visible
            if not hand[i]["seal"] and not hand[i]["enh"] and not hand[i]["ed"]
        ]
        for best in ranked:
            junk = [
                i
                for i in (off_suit or visible)
                if i < best and i in plain and hand[i]["rank"] != hand[best]["rank"]
            ]
            if junk:
                worst = min(
                    junk, key=lambda i: CHIP_VALUE.get(hand[i]["rank"] or "", 0)
                )
                return [worst, best]
        return []
    return sorted(by_chips(visible, False)[:lo])


def _play_scores(history: list[dict[str, Any]] | None) -> list[int]:
    if not history:
        return []
    return [
        int(h["score"])
        for h in history
        if h.get("method") == "play"
        and isinstance(h.get("score"), int | float)
        and h["score"] > 0
    ]


PAIR_BOSS_IMPACT = {
    "The Eye": (
        "AFFECTS MAIN_HAND: no hand type twice this round. Order: biggest type first "
        "(Full House / Three of a Kind / Two Pair), then Pair, then High Card."
    ),
    "The Mouth": (
        "AFFECTS MAIN_HAND: your first play locks the hand type. Lock Pair (you can make "
        "it every hand) unless a bigger listed play WINS outright."
    ),
    "The Psychic": "AFFECTS MAIN_HAND: plays must be 5 cards. Your Pair + 3 filler cards.",
    "The Arm": "AFFECTS MAIN_HAND: each play lowers its level. Win in as few hands as possible.",
    "The Ox": (
        "AFFECTS MAIN_HAND: playing your most played hand sets money to $0. "
        "Play Two Pair or Three of a Kind instead if it still scores enough."
    ),
}


def boss_impact(
    G: dict[str, Any], plan: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Upcoming/active boss with filled effect text, counter and MAIN_HAND impact."""
    boss = (G.get("blinds") or {}).get("boss") or {}
    name = str(boss.get("name") or "")
    effect = str(boss.get("effect") or "")
    if "#1#" in effect:
        filler = (main_hand(G) or "your most played hand") if name == "The Ox" else "1"
        effect = effect.replace("#1#", filler)
    plan = plan or main_hand_plan(G)
    impact = ""
    if name in knowledge.SUIT_BOSSES and plan["hand"] == "Flush":
        bsuit = knowledge.SUIT_BOSSES[name]
        if bsuit == plan.get("suit"):
            impact = (
                f"AFFECTS MAIN_HAND: your Flush suit ({SUIT_NAME[bsuit]}) gives 0 chips. "
                "Prepare: +Mult/xMult jokers not tied to suit, or play Pairs/Two Pair from other suits."
            )
    elif plan["family"] == "pair" and name in PAIR_BOSS_IMPACT:
        impact = PAIR_BOSS_IMPACT[name]
    elif name == MARK:
        impact = "The Mark: your face cards come face down; they still score: keep and play them"
    elif name == "The Plant":
        faces = sum(
            1
            for c in _area_cards(G, "cards") + _area_cards(G, "hand")
            if (_norm(c)["rank"] or "") in FACE_RANKS
        )
        if faces >= 14 or "j_pareidolia" in set(_joker_keys(G)):
            impact = "AFFECTS YOU: many face cards (or Pareidolia) will give 0."
    elif name in ("The Wall", "Violet Vessel"):
        impact = "Score check: buy raw score (xMult/+Mult joker, MAIN_HAND planet) before it."
    elif name == "Verdant Leaf":
        impact = "Keep a cheap joker you can sell at the start of the round."
    prep = knowledge.BOSS_PREP.get(name, "")
    if name in knowledge.SUIT_BOSSES:
        suit = SUIT_NAME[knowledge.SUIT_BOSSES[name]]
        prep = f"{suit} score 0 against it: jokers that need {suit} do nothing this boss"
    return {
        "name": name,
        "effect": effect,
        "score": boss.get("score") or 0,
        "counter": knowledge.boss_counter(name),
        "impact": impact,
        "prep": prep,
    }


def ante_goals(
    G: dict[str, Any],
    plan: dict[str, Any],
    infos: list[dict[str, Any]],
    xmult: int,
    count: int,
    limit: int,
    money: int,
) -> list[dict[str, Any]]:
    """Per-ante checklist, most important first. Each goal: text, done, action.

    The arc: fill slots with flat scoring (Antes 1-3) -> first xMult and a
    scaling joker (Ante 4) -> replace economy/flat jokers with scaling and a
    second xMult (Antes 5-6) -> 2+ xMult and a high MAIN_HAND level (7-8).
    MAIN_HAND levels track the ante (level ante-1 from Ante 3).
    """
    ante = int(G.get("ante_num") or 1)
    hands = G.get("hands") or {}
    level = int((hands.get(plan["hand"]) or {}).get("level", 1))
    scale = sum(1 for i in infos if i["category"] == "SCALE")
    # WEAKEST (a full shop valuation) only matters for a [CHIPS] joker in full slots
    chips_owned = any(i["category"] == "CHIPS" for i in infos)
    weakest = (shop_impact(G).get("weakest") or {}).get("label") if chips_owned and count >= limit else None
    # A [CHIPS] joker is filler only when it is also WEAKEST (Blue Joker can carry a run).
    filler = sum(
        1
        for j in _area_cards(G, "jokers")
        if (cat := (knowledge.joker_info(j.get("label")) or {}).get("category"))
        in ("ECON", "TRAP")
        or (cat == "CHIPS" and j.get("label") == weakest)
    )
    useful = sum(1 for i in infos if i["category"] not in ("UTIL", "TRAP"))
    want_xmult = 0 if ante <= 3 else (1 if ante <= 5 else 2)
    want_level = max(1, ante - 1) if ante >= 3 else 1
    goals: list[dict[str, Any]] = []  # no joker-count goal (owner C4)
    if want_xmult or ante == 3:
        goals.append(
            {
                "text": f"{max(want_xmult, 1)} XMULT by Ante {max(ante, 4)} (have {xmult})",
                "done": xmult >= max(want_xmult, 1),
                "action": "buy an [XMULT] joker (sell your weakest joker if slots are full)",
            }
        )
    if ante >= 4:
        goals.append(
            {
                "text": f"1 SCALE joker that grows each round (have {scale})",
                "done": scale >= 1,
                "action": "buy a [SCALE] joker that fits MAIN_HAND",
            }
        )
    if want_level > 1:
        goals.append(
            {
                "text": f"{plan['hand']} level {want_level} (now {level})",
                "done": level >= want_level,
                "action": "level MAIN_HAND: buy its Planet or a Celestial pack",
            }
        )
    if ante >= 5:
        goals.append(
            {
                "text": f"no [ECON]/[CHIPS] filler jokers (have {filler})",
                "done": filler == 0 or count < limit,
                "action": "when the shop offers an [XMULT]/[SCALE] joker, buy it in place of an [ECON]/[CHIPS] joker; never sell a joker without a replacement",
            }
        )
    if 4 <= ante <= 6:
        goals.append(
            {
                "text": f"hold $25 for max interest (have ${money})",
                "done": money >= 25,
                "action": "save money: buy only what PRIORITY or [XMULT] needs",
            }
        )
    return goals


SITUATIONS = ("COMFORTABLE", "THIN", "SHORT")
# E2a (pass 4, owner Q4 a): STATUS bands on the calibrated win chance of the
# next blind, frozen 2026-11-09: COMFORTABLE >= 95%, THIN 80-95%, SHORT < 80%.
WIN_BANDS = (0.95, 0.80)
# E2a calibration: logistic fit of "won the blind" on the sampler's round
# totals for the blind's hands: logit(raw) (raw = share of totals >= target),
# margin = ln(median total / target) (clipped to +-MARGIN_CLIP), boss or not and
# the ante (capped at WIN_ANTE_CAP: few blinds beyond it), fitted on passes 1-3
# blinds (BLIND_SELECT snapshots) by scripts/fit_win_chance.py. The raw and
# margin weights are >= 0, so more sampled score never lowers the chance.
# Logit = intercept + raw * logit(raw) + margin * margin + boss * [boss] + ante * min(ante, cap)
# Fitted 2026-11-09 on 795 blinds (58 lost).
WIN_FIT = {"intercept": 3.7251, "raw": 0.1447, "margin": 2.2711, "boss": -1.1127, "ante": -0.6524}
WIN_ANTE_CAP = 6
MARGIN_CLIP = 3.0
# Every sampled round wins -> at least THIN at any ante (pooled Ante 5+ bosses
# with raw >= 99% in passes 1-3 + A0: 37 of 43 won = 86%)
ALL_WIN_FLOOR = 0.80


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


def win_inputs(rounds: dict[int, list[int]] | None, hands: int, target: int) -> dict[str, Any] | None:
    """E2a: from the sampled round totals of ``hands`` hands: ``raw`` = share
    that reach ``target``, ``margin`` = ln(median / target) (clipped) and
    ``per`` = the median round's score per hand; None without a distribution."""
    if not rounds or hands <= 0 or target <= 0:
        return None
    h = min(hands, max(rounds))
    totals = rounds.get(h)
    if not totals:
        return None
    med = sorted(totals)[len(totals) // 2]
    margin = math.log(med / target) if med > 0 else -MARGIN_CLIP
    return {
        "raw": sum(1 for v in totals if v >= target) / len(totals),
        "margin": max(min(margin, MARGIN_CLIP), -MARGIN_CLIP),
        "per": max(int(med / h), 1),
        "n": len(totals),
    }


def raw_win_chance(rounds: dict[int, list[int]] | None, hands: int, target: int) -> float | None:
    """Share of the sampled round totals of ``hands`` hands that reach
    ``target`` (E2a), or None without a distribution."""
    w = win_inputs(rounds, hands, target)
    return None if w is None else w["raw"]


def calibrated_win_chance(raw: float, *, margin: float, boss: bool, ante: int, n: int = 150) -> float:
    """E2a: the fitted chance of winning the blind (WIN_FIT); non-decreasing
    in ``raw`` and ``margin``; ALL_WIN_FLOOR when every sampled round wins."""
    eps = 0.5 / max(n, 1)
    x = _logit(min(max(raw, eps), 1 - eps))
    f = WIN_FIT
    z = (
        f["intercept"] + f["raw"] * x + f["margin"] * margin + f["boss"] * boss
        + f["ante"] * min(ante, WIN_ANTE_CAP)
    )
    p = 1 / (1 + math.exp(-max(min(z, 40), -40)))
    return max(p, ALL_WIN_FLOOR) if raw >= 1 else p


def win_band(chance: float) -> str:
    return SITUATIONS[0 if chance >= WIN_BANDS[0] else 1 if chance >= WIN_BANDS[1] else 2]


def situation(
    G: dict[str, Any],
    power: dict[str, Any],
    rounds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """COMFORTABLE / THIN / SHORT for the NEXT blind only (owner: "1 round
    ahead"); the boss counts only when it is that blind, against its hands.

    E2a (pass 4): the band is the calibrated win chance of that blind
    (WIN_BANDS) from the sampler's round totals (boss rules inside). The
    hands needed (shown) = ceil(target / per hand) at the median sampled
    round (the margin in the fit), never more than the hands when the band
    is not SHORT, so the line agrees with the band. Without a sampled distribution: per hand = the K5 low
    percentile and the pass-3 rule applies:
    <= hands - 1 COMFORTABLE, == hands THIN, > hands SHORT (K4); last blind
    won on its final hand -> at least THIN; safety net (fix 2, pass 3 C2):
    THIN (never SHORT) becomes COMFORTABLE when the last 2 blinds were each
    won with 2+ hands left, never for a boss. The calibrated band has no
    overrides (the fit is the test).
    """
    cur = current_blind(G) if G.get("state") == "SELECTING_HAND" else None
    nxt = cur or next_blind(G) or {}
    kind = nxt.get("kind")
    # K5: the strength check reads the low percentile, not the mean
    per = int(power["boss_per_hand_low"] if kind == "boss" else power["per_hand_low"])
    if cur:
        prog = blind_progress(G) or {}
        target, hands = int(prog.get("remaining") or 0), int(prog.get("hands_left") or 0)
    else:
        target = int(nxt.get("score") or 0)
        hands = int(power["boss_hands_allowed"]) if kind == "boss" else _hands_per_round(G)
    last = rounds[-1] if rounds else None
    last_spare = int(last.get("hands_left", 0)) if last else None
    status, need = "UNKNOWN", None
    raw = chance = None
    margin = None
    w = win_inputs(power.get("boss_rounds" if kind == "boss" else "rounds"), hands, target) if per else None
    if w is not None:
        raw, margin, per = w["raw"], w["margin"], w["per"]
        chance = calibrated_win_chance(
            raw, margin=margin, boss=kind == "boss", ante=int(G.get("ante_num") or 1), n=w["n"]
        )
        status = win_band(chance)
        need = -(-target // per)
        if status != "SHORT":  # the line agrees with the band: a likely win fits in the hands
            need = min(need, hands)
    elif per and target and hands:
        need = -(-target // per)
        status = SITUATIONS[0 if need <= hands - 1 else 1 if need == hands else 2]
    elif last is not None:
        status = "COMFORTABLE" if last_spare else "THIN"
    net = False
    if chance is None:
        if not cur and last_spare == 0 and status == "COMFORTABLE":
            status = "THIN"
        if (
            status == "THIN"  # C2: the safety net never lifts SHORT
            and kind != "boss"
            and rounds
            and len(rounds) >= 2
            and all(int(r.get("hands_left", 0)) >= 2 for r in rounds[-2:])
        ):
            status, net = "COMFORTABLE", True
    return {
        "status": status,
        "hands_needed": need,
        "hands": hands,
        "kind": kind,
        "name": nxt.get("name") or (kind or "").title(),
        "target": target,
        "per_hand": per,
        "net": net,
        "last_spare": last_spare,
        "win_raw": raw,
        "win_margin": margin,
        "win_chance": chance,
    }


INVEST_MIN_PCT = 25
INVEST_MIN_GAIN = 0.05  # pass 5 G1c: next-blind win chance gain the BUY line needs  # E2b: SCORE +25% per hand or more


def shop_investment(G: dict[str, Any], sit: dict[str, Any], score_spendable: int) -> dict[str, Any] | None:
    """E2b shop investment (pass 4, owner Q5 a / Q7 a): in a shop, when the
    next blind reads THIN or SHORT or needs hands - 1 or more (2+ hands), the
    shop joker with the best SCORE % per hand of +25% or more whose price is
    within SCORE_SPENDABLE (with full slots: its best swap) -> the PRIORITY
    text and one "buy vs save vs reroll" line: money after, interest lost and
    the next blind's win chance with and without it. Advice only (no veto)."""
    if G.get("state") != "SHOP":
        return None
    # pass 5 G1c: only while THIN or SHORT (the "needs hands - 1" leg fired at
    # COMFORTABLE for about +1 point: 49 of B2's 144 shop visits with the line)
    if sit.get("status") not in ("THIN", "SHORT"):
        return None
    imp = shop_impact(G)
    base = imp.get("score") or 0
    jokers = G.get("jokers") or {}
    full = int(jokers.get("count", 0)) >= int(jokers.get("limit", 5))
    shop = _area_cards(G, "shop")
    best = None
    for i, card in enumerate(shop):
        if card.get("set") != "JOKER" or (card.get("state") or {}).get("hidden"):
            continue
        cost = int((card.get("cost") or {}).get("buy", 0) or 0)
        if cost > score_spendable:
            continue
        swap = None
        if full and _norm(card)["ed"] != "NEGATIVE":
            swap = (imp.get("swaps") or {}).get(i)
            if not swap or not base:
                continue
            pct = round(swap["delta"] * 100 / base)
        else:
            pct = (imp.get("shop_pct") or {}).get(i)
        if pct is None or pct < INVEST_MIN_PCT:
            continue
        if best is None or pct > best["pct"]:
            best = {"index": i, "label": card.get("label"), "cost": cost, "pct": pct, "swap": swap}
    if best is None:
        return None
    money = int(G.get("money") or 0)
    after = money - best["cost"]
    card = shop[best["index"]]
    owned = _area_cards(G, "jokers")
    if best["swap"]:
        owned = [j for n, j in enumerate(owned) if n != best["swap"]["index"]]
        after += int((_area_cards(G, "jokers")[best["swap"]["index"]].get("cost") or {}).get("sell", 0) or 0)
    area = {**jokers, "cards": [*owned, card], "count": len(owned) + 1}
    G_buy = {**G, "jokers": area, "money": after}
    sit_buy = situation(G_buy, power_check(G_buy), None)
    now, then = sit.get("win_chance"), sit_buy.get("win_chance")
    if now is None or then is None or then - now < INVEST_MIN_GAIN:
        return None  # pass 5 G1c: the line shows only when buying adds 5+ points
    reroll = int((G.get("round") or {}).get("reroll_cost", 5) or 0)

    def chance(p: float | None) -> str:
        return "?" if p is None else f"{int(p * 100)}%"

    sell = f", selling {best['swap']['label']}" if best["swap"] else ""
    why = sit.get("status")
    line = (
        f"buy {best['label']} (${best['cost']}{sell}): ${after} left, interest next round ${interest(after)}"
        f" (loses ${interest(money) - interest(after)}), next blind win chance about {chance(then)}"
        f" | save: ${money} left, interest ${interest(money)}, win chance about {chance(now)}"
        f" | reroll (${reroll}): ${money - reroll} left, the joker it finds is not known"
    )
    return {
        **best,
        "money_after": after,
        "interest_lost": interest(money) - interest(after),
        "win_now": now,
        "win_with": then,
        "line": line,
        "priority": (
            f"buy {best['label']} (SCORE +{best['pct']}% per hand{sell}) before rerolling or saving for an"
            f" [XMULT] joker: the next blind is {why}"
        ),
    }


def run_status(
    G: dict[str, Any],
    rounds: list[dict[str, Any]] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The STATUS block: CAPS facts the rulebook references verbatim."""
    plan = main_hand_plan(G)
    ante = int(G.get("ante_num") or 1)
    money = int(G.get("money") or 0)
    jokers = G.get("jokers") or {}
    count = int(jokers.get("count", 0))
    limit = int(jokers.get("limit", 5))
    infos = _owned_joker_infos(G)
    xmult = xmult_owned(G, plan)
    floor = money_floor(G)

    # Strength check (P2-1/P2-2): the next blind only; the boss has its own line.
    scores = _play_scores(history)[-3:]
    nxt = next_blind(G) or current_blind(G) or {}
    nxt_target = int(nxt.get("score") or 0)
    boss = (G.get("blinds") or {}).get("boss") or {}
    boss_name = str(boss.get("name") or "")
    boss_target = int(boss.get("score") or 0)
    power = power_check(G, plan)
    sit = situation(G, power, rounds)
    status = sit["status"]
    hands_needed = sit["hands_needed"]
    boss_hands = (
        -(-boss_target // max(int(power["boss_per_hand_low"]), 1))
        if power["boss_per_hand_low"] and boss_target
        else None
    )
    bcheck = boss_check(G, history) if boss.get("status") in ("SELECT", "UPCOMING") else None
    boss_short = bool(bcheck and not bcheck["ok"]) or (status == "SHORT" and sit["kind"] == "boss")
    effective_floor = floor

    econ = sum(1 for i in infos if i["category"] == "ECON")
    scoring = sum(
        1 for i in infos if i["category"] in ("XMULT", "MULT", "CHIPS", "SCALE")
    )
    slots_free = max(limit - count, 0)
    econ_ok = (
        ante <= ECON_EARLY_MAX_ANTE
        and scoring >= 2
        and slots_free >= 1
        and (econ == 0 or (ante <= 2 and econ < ECON_MAX_OWNED and slots_free >= 2))
    )
    cons = G.get("consumables") or {}
    goals = ante_goals(G, plan, infos, xmult, count, limit, money)
    open_goals = [g for g in goals if not g["done"]]
    priority = (
        open_goals[0]["action"]
        if open_goals
        else "buy what builds your run (see STATUS); keep money and empty slots while COMFORTABLE"
    )
    score_spendable = max(money - reserve(G, status, boss_short), money - effective_floor, 0)
    invest = shop_investment(G, sit, score_spendable)
    if invest:
        # E2b: a +25% joker within SCORE_SPENDABLE goes ahead of the [XMULT] goal
        priority = invest["priority"]
    milestone = f"Ante {ante} goals met: {len(goals) - len(open_goals)}/{len(goals)}."
    return {
        "ante": ante,
        "money": money,
        "main_hand": plan["hand"],
        "main_suit": SUIT_NAME.get(plan.get("suit") or "", ""),
        "main_reason": plan["reason"],
        "floor": floor,
        "effective_floor": effective_floor,
        "spendable": max(money - effective_floor, 0),
        "interest": interest(money),
        "jokers": count,
        "joker_limit": limit,
        "slots_free": max(limit - count, 0),
        "xmult_owned": xmult,
        "status": status,
        "hands_needed": hands_needed,
        "next_kind": sit["kind"],
        "sit_target": sit["target"],
        "sit_per": sit["per_hand"],
        "next_name": sit["name"],
        "next_hands": sit["hands"],
        "safety_net": sit["net"],
        # E2a: calibrated chance to win the next blind (None = no distribution)
        "win_chance": sit["win_chance"],
        "win_pct": None if sit["win_chance"] is None else int(sit["win_chance"] * 100),
        "win_raw": sit["win_raw"],
        "win_margin": sit["win_margin"],
        "last_spare": sit["last_spare"],
        "boss_check": bcheck,
        "best_types": power.get("best_types", []),
        "boss_name": boss_name,
        "boss_target": boss_target,
        "boss_hands": boss_hands,
        "boss_halved": boss_name in BOSS_PACE,
        "boss_hands_allowed": power["boss_hands_allowed"],
        "typical": power["typical"],
        "per_hand": power["per_hand"],
        "make_rate": power["make_rate"],
        "boss_make_rate": power["boss_make_rate"],
        "boss_per_hand": power["boss_per_hand"],
        "reserve": reserve(G, status, boss_short),
        # money a score buy may use: a joker filling an empty slot (Antes 1-3),
        # a joker with SCORE +50% or more, an on-plan [XMULT] joker, a [MAIN]
        # planet, a Buffoon pack with a free slot, or a SCORE > 0 joker while TOO WEAK
        "score_spendable": score_spendable,
        # E2b: "buy vs save vs reroll" for the best +25% joker (None = no line)
        "invest": invest,
        "shop_locked": bool((G.get("luna") or {}).get("shop_locked")),
        # C4: Luna may ask for a boss reroll in this shop
        "boss_reroll_ok": G.get("state") == "SHOP"
        and bool((G.get("luna") or {}).get("luna_reroll"))
        and not (G.get("luna") or {}).get("boss_reroll_request")
        and luna_reroll_refusal(G) is None,
        "boss_reroll_request": (G.get("luna") or {}).get("boss_reroll_request"),
        "pending_tags": pending_tag_lines(G),
        "recent_scores": scores,
        "next_target": nxt_target,
        "milestone": milestone,
        "goals": goals,
        "econ_owned": econ,
        "econ_ok": econ_ok,
        "blue_seals": blue_seal_count(G),
        "hologram": owns_hologram(G),
        # [FEED] planets: Constellation grows, Satellite pays (owner J5)
        "constellation": owns_joker(G, "j_constellation") or owns_joker(G, "j_satellite"),
        "owned_keys": _joker_keys(G),
        "vampire": owns_joker(G, "j_vampire"),
        "main_open": plan["open"],
        "main_label": f"OPEN (leaning {plan['hand']})" if plan["open"] else plan["hand"],
        "tag_hand": None if plan["open"] else plan["hand"],
        "ok_hands": sorted(
            {n for n, h in (G.get("hands") or {}).items() if int((h or {}).get("played", 0))}
            | set(power.get("best_types") or [])
        )
        if plan["open"]
        else None,
        "square": owns_joker(G, "j_square"),
        "deck_total": len(_area_cards(G, "cards")) + len(_area_cards(G, "hand")),
        # most you can spend without lowering next round's interest
        "interest_spare": max(money - 5 * interest(money), 0),
        "consumable_slots_free": max(
            int(cons.get("limit", 2)) - int(cons.get("count", 0)), 0
        ),
        "priority": priority,
        "observatory": any(
            "observatory" in str(k).lower() for k in (G.get("used_vouchers") or {})
        ),
    }


def _castle_suit(j: dict[str, Any]) -> str | None:
    effect = str((j.get("value") or {}).get("effect", "") or "")
    m = re.search(r"discarded (heart|diamond|club|spade)", effect, re.IGNORECASE)
    return SUIT_LETTER.get(m.group(1).lower()) if m else None


def discard_payers(G: dict[str, Any], cards: Iterable[int]) -> list[int]:
    """Owned jokers this discard triggers (P2-15): Mail-In Rebate rank,
    Faceless Joker 3+ faces, Trading Card first single-card discard, Burnt
    Joker first discard, Castle suit, Hit the Road Jacks."""
    hand = [_norm(c) for c in _area_cards(G, "hand")]
    try:
        chosen = [hand[int(i)] for i in cards]
    except (IndexError, TypeError, ValueError):
        return []
    first = int((G.get("round") or {}).get("discards_used", 0) or 0) == 0
    ranks = [c["rank"] for c in chosen]
    out = []
    for i, j in enumerate(_area_cards(G, "jokers")):
        if _joker_debuffed(j):  # F6: a debuffed joker pays nothing (and is no copy target)
            continue
        key = j.get("key")
        hit = (
            (key == "j_mail" and (r := mail_rank(G)) is not None and r in ranks)
            or (key == "j_faceless" and sum(1 for r in ranks if r in FACE_RANKS) >= 3)
            or (key == "j_trading" and first and len(chosen) == 1)
            or (key == "j_burnt" and first)
            or (key == "j_castle" and (s := _castle_suit(j)) is not None and any(c["suit"] == s for c in chosen))
            or (key == "j_hit_the_road" and "J" in ranks)
        )
        if hit:
            out.append(i)
    return out


def discard_phase_order(G: dict[str, Any], cards: Iterable[int]) -> list[int] | None:
    """Joker order for this discard so Blueprint (copies the joker to its
    right) / Brainstorm (copies the leftmost joker) copy the joker the discard
    pays (P2-15). None: nothing to change."""
    jokers = _area_cards(G, "jokers")
    keys = [j.get("key", "") for j in jokers]
    if not {"j_blueprint", "j_brainstorm"} & set(keys):
        return None
    payers = discard_payers(G, cards)
    if not payers:
        return None
    target = payers[0]
    order = list(range(len(jokers)))
    if "j_blueprint" in keys and not _joker_debuffed(jokers[keys.index("j_blueprint")]):
        bp = keys.index("j_blueprint")
        order.remove(bp)
        order.insert(order.index(target), bp)
    if (
        "j_brainstorm" in keys
        and keys.index("j_brainstorm") != target
        and not _joker_debuffed(jokers[keys.index("j_brainstorm")])
    ):
        order.remove(target)
        order.insert(0, target)
    return None if order == list(range(len(jokers))) else order


def joker_order(G: dict[str, Any]) -> list[int] | None:
    """Ideal joker order (+Chips, +Mult, scaling, xMult, Polychrome right), or None.

    Blueprint is placed just left of the strongest xMult joker; Brainstorm's
    target (the best xMult) goes first. Returns None if already ordered.
    """
    jokers = _area_cards(G, "jokers")
    if len(jokers) < 2:
        return None
    rank_of = {
        "CHIPS": 0,
        "KEEP-DISCARDS": 0,
        "ECON": 1,
        "UTIL": 1,
        "TRAP": 1,
        "MULT": 2,
        "SCALE": 3,
        "XMULT": 5,
    }

    def weight(j: dict[str, Any]) -> float:
        info = knowledge.joker_info(j.get("label")) or {}
        w = float(rank_of.get(info.get("category", "UTIL"), 1))
        effect = str((j.get("value") or {}).get("effect", ""))
        m = CURRENTLY.search(effect)
        if m and m.group(1) in ("X", "x", "×"):
            w = 5
        if (j.get("modifier") or {}).get("edition") == "POLYCHROME":
            w += 0.5
        return w

    keys = [j.get("key", "") for j in jokers]
    if "j_ceremonial" in keys:  # order matters destructively, leave it to the player
        return None
    order = sorted(range(len(jokers)), key=lambda i: (weight(jokers[i]), i))
    # P2-13: the copy target is the hand-defining joker (MAIN_HAND commit
    # trigger, e.g. Baron), else the strongest xMult
    trigger = (main_hand_plan(G).get("commit") or {}).get("trigger")
    copiers = {"j_blueprint", "j_brainstorm"}
    defining = next(
        (i for i, j in enumerate(jokers)
         if trigger and j.get("label") == trigger and keys[i] not in copiers and not _joker_debuffed(j)),
        None,
    )
    if "j_blueprint" in keys:
        bp = keys.index("j_blueprint")
        order.remove(bp)
        # F6: a debuffed joker is no copy target (Blueprint would copy nothing)
        xs = [i for i in order if weight(jokers[i]) >= 5 and keys[i] not in copiers and not _joker_debuffed(jokers[i])]
        live = [i for i in order if not _joker_debuffed(jokers[i])]
        target = defining if defining is not None else xs[-1] if xs else live[-1] if live else order[-1]
        order.insert(order.index(target), bp)
    if "j_brainstorm" in keys:
        bs = keys.index("j_brainstorm")
        xs = [i for i in order if i != bs and weight(jokers[i]) >= 5 and keys[i] not in copiers
              and not _joker_debuffed(jokers[i])]
        target = defining if defining is not None else xs[-1] if xs else None
        if target is not None and target != bs:
            order.remove(target)
            order.insert(0, target)
    return None if order == list(range(len(jokers))) else order


################################################################################
# Shop impact: what each item adds to a typical MAIN_HAND play
################################################################################

PAIR_SHAPE = {
    "Pair": [2],
    "Two Pair": [2, 2],
    "Three of a Kind": [3],
    "Full House": [3, 2],
    "Four of a Kind": [4],
}


def _face_up(card: dict[str, Any]) -> dict[str, Any]:
    """Copy of ``card`` with its face-down flag cleared."""
    state = card.get("state")
    if isinstance(state, dict) and state.get("hidden"):
        return {**card, "state": {**state, "hidden": False}}
    return card


def typical_play(G: dict[str, Any], plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Real deck cards forming a typical MAIN_HAND play (empty if impossible).

    Pair family: the ranks you own most copies of (ties: higher chips).
    Flush: five middle-value cards of MAIN_SUIT.
    """
    plan = plan or main_hand_plan(G)
    # Deck cards are face-down in the shop but their rank and suit are known;
    # the typical play is hypothetical, so score them face-up.
    raw = [_face_up(c) for a in ("cards", "hand") for c in _area_cards(G, a)]
    cards = [(c, _norm(c)) for c in raw if not _norm(c)["stone"]]
    shape = PAIR_SHAPE.get(plan["hand"])
    if shape:
        by_rank: dict[str, list[dict[str, Any]]] = {}
        for c, n in cards:
            if n["rank"]:
                by_rank.setdefault(n["rank"], []).append(c)
        ranks = sorted(
            by_rank, key=lambda r: (len(by_rank[r]), CHIP_VALUE[r]), reverse=True
        )
        play: list[dict[str, Any]] = []
        used: set[str] = set()
        for need in shape:
            r = next((r for r in ranks if r not in used and len(by_rank[r]) >= need), None)
            if r is None:
                return []
            used.add(r)
            play += by_rank[r][:need]
        return play
    if plan["hand"] == "Flush":
        suit = plan.get("suit") or main_suit(G)
        same = sorted(
            (c for c, n in cards if n["suit"] == suit),
            key=lambda c: CHIP_VALUE.get(_norm(c)["rank"] or "", 0),
        )
        if len(same) < 5:
            return []
        mid = max(0, len(same) // 2 - 2)
        return same[mid : mid + 5]
    return []


def typical_plays(
    G: dict[str, Any], plan: dict[str, Any] | None = None
) -> list[list[dict[str, Any]]]:
    """MAIN_HAND plays from your deck to average joker value over.

    Pair / Three / Four of a Kind: every combination of that many cards of one
    rank, so ranks, suits and face cards count as often as they come up.
    Two Pair / Full House: one play per pair of ranks, higher rank first as in
    a sorted hand. Flush: the low, middle and high five cards of MAIN_SUIT.
    """
    plan = plan or main_hand_plan(G)
    raw = [_face_up(c) for a in ("cards", "hand") for c in _area_cards(G, a)]
    cards = [(c, _norm(c)) for c in raw if not _norm(c)["stone"]]
    shape = PAIR_SHAPE.get(plan["hand"])
    if shape and len(shape) == 1:
        by_rank: dict[str, list[dict[str, Any]]] = {}
        for c, n in cards:
            if n["rank"]:
                by_rank.setdefault(n["rank"], []).append(c)
        return [
            list(combo)
            for same in by_rank.values()
            for combo in combinations(same, shape[0])
        ]
    if shape:
        by_rank = {}
        for c, n in cards:
            if n["rank"]:
                by_rank.setdefault(n["rank"], []).append(c)
        first, second = shape
        plays = []
        for r1 in by_rank:
            for r2 in by_rank:
                if r1 == r2 or len(by_rank[r1]) < first or len(by_rank[r2]) < second:
                    continue
                if first == second and RANKS.index(r1) < RANKS.index(r2):
                    continue  # Two Pair: each pair of ranks once
                play = by_rank[r1][:first] + by_rank[r2][:second]
                plays.append(
                    sorted(play, key=lambda c: -RANKS.index(_norm(c)["rank"]))
                )
        return plays
    if plan["hand"] == "Flush":
        suit = plan.get("suit") or main_suit(G)
        same = sorted(
            (c for c, n in cards if n["suit"] == suit),
            key=lambda c: CHIP_VALUE.get(_norm(c)["rank"] or "", 0),
        )
        if len(same) < 5:
            return []
        starts = sorted({0, max(0, len(same) // 2 - 2), len(same) - 5})
        return [same[i : i + 5] for i in starts]
    play = typical_play(G, plan)
    return [play] if play else []


# Chance to make the hand in one hand with (0 discards, ~1 discard per hand):
# measured over 20,000 deals of an unmodified 52-card deck, 8 cards in hand
# (research/07). Four of a Kind and the Four Fingers/Smeared Flush rows are
# starting guesses, to calibrate.
MAKE_RATE = {
    "High Card": (1.0, 1.0),
    "Pair": (0.89, 0.99),
    "Two Pair": (0.44, 0.78),
    "Three of a Kind": (0.12, 0.35),
    "Full House": (0.06, 0.28),
    "Four of a Kind": (0.01, 0.05),
    "Flush": (0.07, 0.44),
    "Straight": (0.10, 0.30),
}
FLUSH_HELP_RATE = (0.25, 0.75)  # guess: Four Fingers or Smeared Joker owned
BOSS_DEBUFF_FACES = {"The Plant"}


def _hands_per_round(G: dict[str, Any]) -> int:
    vouchers = {str(v) for v in (G.get("used_vouchers") or {})}
    hands = 4 + ("v_grabber" in vouchers) + ("v_nacho_tong" in vouchers)
    return max(hands - ("v_hieroglyph" in vouchers), 1)


def _mean_score(G: dict[str, Any], plays: list[list[dict[str, Any]]], hand: str) -> int:
    scores = [
        est["score"]
        for p in plays
        if (est := estimate_play(G, p, [], expected=True))["hand"] == hand
    ]
    return int(sum(scores) / len(scores)) if scores else 0


def _debuffed(card: dict[str, Any]) -> dict[str, Any]:
    return {**card, "state": {**(card.get("state") or {}), "debuff": True}}


# ---------------------------------------------------------------------------
# P2-1 strength check: the hands Luna actually makes (sampled), not a typical
# MAIN_HAND play. Deterministic per deck (seeded from the cards), cached per
# gamestate. Knobs (pass2_build_plan.md "Pre-registered calibration knobs").
# ---------------------------------------------------------------------------
SAMPLES = 150  # K1
# K5 (pass 3, owner Q1): STATUS, the boss check / boss line and the boss-reroll
# strength trigger read this percentile of the sampled per-round scores (nearest
# rank); shop SCORE (shop_impact, swap_plan) stays on the mean.
K5_PERCENTILE = 40  # owner 2026-11-08: "Run the 40th percentile for now" (band 20-40 failed its targets)
SHOP_SAMPLES = 60  # shop variants reuse the first draws (common random numbers)
REFILL = 5
DISCARD_FROM = {"High Card", "Pair"}  # K2: one discard per hand from these
TWO_PAIR_TYPES = {"Two Pair", "Full House"}
_CACHE: "OrderedDict[str, Any]" = OrderedDict()
_CACHE_MAX = 64


def _state_key(G: dict[str, Any], *extra: Any) -> str:
    luna = G.get("luna")
    if isinstance(luna, dict) and "status" in luna:  # derived from G: not part of the key
        G = {**G, "luna": {k: v for k, v in luna.items() if k != "status"}}
    raw = json.dumps([G, extra], sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


def _cached(key: str, make: Any) -> Any:
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    value = make()
    _CACHE[key] = value
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return value


def _card_id(c: dict[str, Any]) -> str:
    n = _norm(c)
    return f"{n['rank']}{n['suit']}{n['enh']}{n['seal']}{n['ed']}{n['stone']}"


def _hand_size(G: dict[str, Any]) -> int:
    return int((G.get("hand") or {}).get("limit") or 8) or 8


def sample_draws(G: dict[str, Any], n: int = SAMPLES) -> list[tuple[list, list]]:
    """``n`` (hand, refill) draws of the full deck (deck + hand, face up)."""
    pool = [_face_up(c) for a in ("cards", "hand") for c in _area_cards(G, a)]
    size = _hand_size(G)
    ids = sorted(_card_id(c) for c in pool)
    key = _state_key({"ids": ids}, size, n, "draws")

    def make() -> list[tuple[list, list]]:
        seed = int(hashlib.md5(json.dumps([ids, size]).encode()).hexdigest()[:12], 16)
        rng = random.Random(seed)
        ordered = sorted(pool, key=_card_id)
        out = []
        for _ in range(n):
            pick = rng.sample(range(len(ordered)), min(len(ordered), size + REFILL))
            out.append(([ordered[i] for i in pick[:size]], [ordered[i] for i in pick[size:]]))
        return out

    return _cached(key, make)


def _candidates(G: dict[str, Any], norm: list[dict[str, Any]], pad_to: int) -> list[list[int]]:
    """Candidate plays (index lists) for one dealt hand: every pair-family
    play by rank, Two Pair / Full House combinations, a Flush per suit, a
    Straight, the high card. Padded to ``pad_to`` cards (The Psychic)."""
    flags = _classify_flags(G)
    by_rank: dict[str, list[int]] = {}
    for i, c in enumerate(norm):
        if c["rank"] and not c["stone"] and not c["hidden"]:
            by_rank.setdefault(c["rank"], []).append(i)
    cands: set[tuple[int, ...]] = set()
    ranked = [i for ids in by_rank.values() for i in ids]
    if ranked:
        cands.add((max(ranked, key=lambda i: RANK_VALUE[norm[i]["rank"]]),))
    multi = sorted(
        ((r, ids) for r, ids in by_rank.items() if len(ids) >= 2),
        key=lambda kv: (len(kv[1]), CHIP_VALUE[kv[0]]),
        reverse=True,
    )
    for _r, ids in multi:
        cands.add(tuple(ids[:2]))
        if len(ids) >= 3:
            cands.add(tuple(ids[:min(len(ids), 4)]))
    for (_r1, a), (_r2, b) in combinations(multi[:4], 2):
        cands.add(tuple(a[:2] + b[:2]))
        if len(a) >= 3:
            cands.add(tuple(a[:3] + b[:2]))
        if len(b) >= 3:
            cands.add(tuple(b[:3] + a[:2]))
    need = 4 if flags["four_fingers"] else 5
    groups = _suit_groups(flags["smeared"])
    for g in set(groups.values()):
        ids = [
            i for i, c in enumerate(norm)
            if not c["stone"] and not c["hidden"] and (c["enh"] == "WILD" or (c["suit"] and groups[c["suit"]] == g))
        ]
        if len(ids) >= need:
            ids.sort(key=lambda i: -CHIP_VALUE.get(norm[i]["rank"] or "", 0))
            cands.add(tuple(ids[:5]))
    for lo in range(1, 11):
        window = ["A" if v in (1, 14) else RANKS[v - 2] for v in range(lo, lo + 5)]
        for skip in ([None] if need == 5 else [None, *range(5)]):
            ranks = [r for k, r in enumerate(window) if k != skip][:need] if skip is not None else window
            if all(r in by_rank for r in ranks):
                cands.add(tuple(by_rank[r][0] for r in ranks))
    keyset = set(_joker_keys(G)) | set(copied_keys(G))
    held_value = keyset & {"j_blackboard", "j_baron", "j_shoot_the_moon", "j_raised_fist"} or any(
        c["enh"] == "STEEL" for c in norm
    )
    if held_value and not pad_to:
        # Pad a play to 5 with cards that are worth less HELD (Blackboard: red
        # cards first, owner V8; Baron/Shoot the Moon keep Kings/Queens held);
        # a filler may never change the hand type (H3)
        keep_ranks = held_scoring_ranks(G)

        def held_worth(i: int) -> tuple:
            c = norm[i]
            black = c["suit"] in ("S", "C") or c["enh"] == "WILD"
            return ("j_blackboard" in keyset and black, c["rank"] in keep_ranks or c["enh"] == "STEEL",
                    CHIP_VALUE.get(c["rank"] or "", 0))

        for c in list(cands):
            base = classify([norm[i] for i in c], **flags)[0]
            play = list(c)
            for i in sorted((i for i in range(len(norm)) if i not in play and not norm[i]["hidden"]), key=held_worth):
                if len(play) >= 5:
                    break
                if classify([norm[j] for j in [*play, i]], **flags)[0] == base:
                    play.append(i)
            cands.add(tuple(play))
    out = []
    for c in cands:
        play = list(c)
        if pad_to and len(play) < pad_to:
            rest = sorted(
                (i for i in range(len(norm)) if i not in play),
                key=lambda i: (norm[i]["rank"] in held_scoring_ranks(G) or norm[i]["enh"] == "STEEL",
                               CHIP_VALUE.get(norm[i]["rank"] or "", 0)),
            )
            play += rest[: pad_to - len(play)]
        out.append(play)
    return out


HELD_CANDIDATE_KEYS = frozenset({"j_blackboard", "j_baron", "j_shoot_the_moon", "j_raised_fist"})


def _best_play(
    G: dict[str, Any],
    hand: list[dict[str, Any]],
    pad_to: int,
    only: str | None = None,
    memo: dict[Any, Any] | None = None,
    by_type: dict[str, int] | None = None,
    expected: bool = True,
    stop_at: float | None = None,
    ctx: dict[str, Any] | None = None,
) -> tuple[int, str, list[int]]:
    """Best candidate play (score, hand type, indices); ``only`` = that type.

    ``expected=False`` scores the FLOOR (random effects at zero), as the
    listed plays and WINS do (pass 4 E3 last-hand sampler); ``stop_at``
    returns the first play scoring at least that much (E3 needs only hit/miss).

    ``memo`` (one dict per dealt hand, sampler only) keeps the normalised
    cards and the candidate plays, which depend only on the hand, the pad
    size, the classify flags and the held-card jokers owned. ``by_type``
    (E2a, The Eye / The Mouth) is filled with the best score per hand type.
    A face-down card (The Wheel, sampler only) is never picked for a play
    (Luna cannot see it) but still scores as the card it is.

    ``ctx`` (pass 5 merge of E2 + E3): a precomputed ``_estimate_ctx`` for a G
    with the same jokers and boss (E3 passes the original G's while scoring a
    copy with another round / hands table). ``by_type`` needs every candidate
    scored, so it cannot be combined with ``stop_at``.
    """
    if by_type is not None and stop_at is not None:
        raise ValueError("_best_play: by_type needs the full enumeration; stop_at would cut it short")
    if ctx is None:
        ctx = _estimate_ctx(G)
    if memo is None:
        norm = [_norm(c) for c in hand]
        cands = _candidates(G, norm, pad_to)
    else:
        norm = memo.get("norm") or memo.setdefault("norm", [_norm(c) for c in hand])
        flags = _classify_flags(G)
        sig = (pad_to, tuple(sorted(flags.items())), frozenset((ctx["keyset"] | set(ctx["copied"])) & HELD_CANDIDATE_KEYS))
        cands = memo.get(sig)
        if cands is None:
            cands = memo[sig] = _candidates(G, norm, pad_to)
    if any(c["hidden"] for c in norm):  # E2a The Wheel: a face-down card still scores
        hand = [_face_up(c) for c in hand]
        snorm = [_norm(c) for c in hand]
    else:
        snorm = norm
    best = (0, "High Card", [])
    for play in cands:
        rest = [i for i in range(len(hand)) if i not in play]
        pre = {"ctx": ctx, "played": [snorm[i] for i in play], "held": [snorm[i] for i in rest]}
        est = estimate_play(G, [hand[i] for i in play], [hand[i] for i in rest], expected=expected, _pre=pre)
        if est["blocked"] or (only is not None and est["hand"] != only):
            continue
        if by_type is not None and est["score"] > by_type.get(est["hand"], 0):
            by_type[est["hand"]] = int(est["score"])
        if est["score"] > best[0]:
            best = (int(est["score"]), est["hand"], play)
            if stop_at is not None and best[0] >= stop_at:
                break
    return best


def _after_discard(G: dict[str, Any], hand: list, refill: list, htype: str) -> list:
    """K2: one discard when the best play is High Card or Pair. Keeps pairs,
    cards that score held, paid-suit cards, else a 4-card Flush draw."""
    if htype not in DISCARD_FROM or not refill:
        return hand
    norm = [_norm(c) for c in hand]
    rc = Counter(c["rank"] for c in norm if c["rank"])
    keep_ranks = held_scoring_ranks(G)
    paid = {p["suit"] for p in suit_pays(G)}
    keep = {
        i for i, c in enumerate(norm)
        if (c["rank"] and rc[c["rank"]] >= 2) or c["rank"] in keep_ranks
        or c["enh"] in ("STEEL", "GOLD") or (c["suit"] in paid)
    }
    suits = Counter(c["suit"] for c in norm if c["suit"])
    if suits:
        top, cnt = suits.most_common(1)[0]
        need = 4 if "j_four_fingers" in set(_joker_keys(G)) else 5
        if cnt >= need - 1 and not any(rc[r] >= 2 for r in rc):
            keep |= {i for i, c in enumerate(norm) if c["suit"] == top}
    drop = sorted((i for i in range(len(hand)) if i not in keep),
                  key=lambda i: CHIP_VALUE.get(norm[i]["rank"] or "", 0))[:min(5, len(refill))]
    if not drop:
        return hand
    return [c for i, c in enumerate(hand) if i not in drop] + refill[: len(drop)]


def _with_effect(G: dict[str, Any], key: str, effect: str) -> dict[str, Any]:
    area = dict(G.get("jokers") or {})
    area["cards"] = [
        {**j, "value": {**(j.get("value") or {}), "effect": effect}} if j.get("key") == key else j
        for j in _area_cards(G, "jokers")
    ]
    return {**G, "jokers": area}


def _currently(j: dict[str, Any]) -> float:
    m = CURRENTLY.search(str((j.get("value") or {}).get("effect", "")))
    return float(m.group(2)) if m else 0.0


class _Dealt(list):
    """Dealt hands plus the first best play of each hand the discard left
    unchanged, valid only for the G object they were computed with."""

    def __init__(self, G: dict[str, Any], pad: int) -> None:
        super().__init__()
        self.G = G
        self.pad = pad
        self.first: dict[int, tuple] = {}
        self.memo: list[dict[Any, Any]] = []


def _dealt_hands(G: dict[str, Any], draws: list, *, boss: str = "", discards: bool = True) -> list[list]:
    """The hand Luna plays from each draw: after one discard (K2) when allowed."""
    pad = 5 if boss == "The Psychic" else 0
    out = _Dealt(G, pad)
    for hand, refill in draws:
        memo: dict[Any, Any] = {}
        if discards:
            first = _best_play(G, hand, pad, memo=memo)
            new = _after_discard(G, hand, refill, first[1])
            if new is hand:
                out.first[len(out)] = first
            else:
                memo = {}
            hand = new
        out.append(hand)
        out.memo.append(memo)
    return out


def _strength(
    G: dict[str, Any], draws: list, *, boss: str = "", discards: bool = True, rounds: bool = False
) -> dict[str, Any]:
    """Mean score per hand over ``draws`` under G (jokers, levels, boss)."""
    return _score_hands(G, _dealt_hands(G, draws, boss=boss, discards=discards), boss=boss, rounds=rounds)


RESTRICTED_TYPE_BOSSES = ("The Eye", "The Mouth")


def _round_totals(n: int, h: int, score: Any) -> list[int]:
    """E2a: ``n`` round totals of ``h`` hands, each hand from a different
    draw (draw j, j + n//h, j + 2n//h, ... mod n); ``score(i, k)`` = draw i's
    score as the round's hand k (k = 0 first, k = h - 1 last)."""
    off = max(n // max(h, 1), 1)
    return [int(sum(score((j + k * off) % n, k) for k in range(h))) for j in range(n)]


def _score_hands(
    G: dict[str, Any], dealt: list[list], *, boss: str = "", rounds: bool = False
) -> dict[str, Any]:
    """Best play per dealt hand under G, plus Spare Trousers growth inside the
    blind, Card Sharp repeats and Acrobat's last hand: mean score per hand.

    E2a boss rules inside the estimate: The Needle = one hand per round (Card
    Sharp never repeats, Acrobat's X3 is on that hand); The Eye = no hand type
    twice in a round, The Mouth = one hand type for the whole round (the type
    with the best mean; Card Sharp's X3 on its hands 2..), both judged on
    rounds built from different draws. ``rounds=True`` adds "rounds": {h: the
    sampled round totals of h hands} for h = 1..hands (the win chance).
    """
    pad = 5 if boss == "The Psychic" else 0
    hands = 1 if boss == "The Needle" else _hands_per_round(G)
    chosen = []
    reuse = dealt.first if isinstance(dealt, _Dealt) and dealt.G is G and dealt.pad == pad else {}
    memos = dealt.memo if isinstance(dealt, _Dealt) else None
    for n, hand in enumerate(dealt):
        s, t, play = reuse[n] if n in reuse else _best_play(G, hand, pad, memo=memos[n] if memos else None)
        chosen.append((s, t, hand, play))
    if not chosen:
        return {"per_hand": 0, "per_hand_low": 0, "types": Counter(), "chosen": [], "rounds": {}}
    types = Counter(t for _, t, _, _ in chosen)
    keys = set(_joker_keys(G)) | set(copied_keys(G))
    scores = [s for s, _, _, _ in chosen]

    def face_up(hand: list) -> list:
        return [_face_up(c) for c in hand]

    def rescore(Gv: dict[str, Any], only: str | None = None) -> list[int]:
        out = []
        for s, t, hand, play in chosen:
            if only is not None and t != only:
                out.append(s)
                continue
            hand = face_up(hand)
            est = estimate_play(Gv, [hand[i] for i in play],
                                [hand[i] for i in range(len(hand)) if i not in play], expected=True)
            out.append(int(est["score"]))
        return out

    # K6 Spare Trousers grows inside the blind: +2 Mult per Two Pair played
    if "j_trousers" in keys:
        p2 = sum(n for t, n in types.items() if t in TWO_PAIR_TYPES) / len(chosen)
        tr = next(j for j in _area_cards(G, "jokers") if j.get("key") == "j_trousers")
        grown = _currently(tr) + 2 * p2 * (hands + 1) / 2
        G = _with_effect(G, "j_trousers", f"(Currently +{grown:g} Mult)")
        scores = rescore(G)
    per_round = [s * hands for s in scores]
    rep = scores
    sharp = "j_card_sharp" in keys and boss != "The Eye" and hands > 1
    # Card Sharp: hands 2.. repeat the most common hand type for X3, played
    # from any draw that contains it when that beats the draw's best play
    # (owner S3: "play Pairs"; findings P4)
    if sharp and boss != "The Mouth":
        modal = types.most_common(1)[0][0]
        hands_tbl = {k: dict(v or {}) for k, v in (G.get("hands") or {}).items()}
        hands_tbl.setdefault(modal, {})["played_this_round"] = 1
        G_rep = {**G, "hands": hands_tbl}
        rep = [
            max(s, _best_play(G_rep, hand, pad, only=modal)[0])
            for s, (_, _, hand, _) in zip(scores, chosen)
        ]
        per_round = [s + (hands - 1) * r for s, r in zip(scores, rep)]
    # Acrobat: X3 on the final hand only (owner, pass 1)
    last = scores
    if "j_acrobat" in keys:
        rnd = dict(G.get("round") or {})
        last = rescore({**G, "round": {**rnd, "hands_left": 1}})
        per_round = [pr - s + l for pr, s, l in zip(per_round, scores, last)]
    # E2a round totals (Sol g3 finding 1): the final hand of a 2+ hand round is
    # a Card Sharp repeat too, with Acrobat's last-hand X3 on top
    last_rep = last
    if rounds and sharp and boss != "The Mouth":
        if "j_acrobat" in keys:
            rnd = dict(G_rep.get("round") or {})
            G_rep_last = {**G_rep, "round": {**rnd, "hands_left": 1}}
            last_rep = [
                max(l, _best_play(G_rep_last, hand, pad, only=modal)[0])
                for l, (_, _, hand, _) in zip(last, chosen)
            ]
        else:
            last_rep = rep
    n = len(chosen)
    if boss in RESTRICTED_TYPE_BOSSES:
        by_type: list[dict[str, int]] = []
        for k, (_, _, hand, _) in enumerate(chosen):
            d: dict[str, int] = {}
            _best_play(G, hand, pad, memo=memos[k] if memos else None, by_type=d)
            by_type.append(d)
        lift = [l / s if s else 1.0 for s, l in zip(scores, last)]  # Acrobat on the last hand
        if boss == "The Mouth":
            tot: Counter = Counter()
            for d in by_type:
                tot.update(d)
            only = tot.most_common(1)[0][0] if tot else "High Card"
            rep_only = [d.get(only, 0) for d in by_type]
            if sharp:
                hands_tbl = {k: dict(v or {}) for k, v in (G.get("hands") or {}).items()}
                hands_tbl.setdefault(only, {})["played_this_round"] = 1
                G_rep = {**G, "hands": hands_tbl}
                rep_only = [_best_play(G_rep, hand, pad, only=only)[0] for (_, _, hand, _) in chosen]

            def restricted(h: int) -> list[int]:
                def one(i: int, k: int) -> float:
                    v = by_type[i].get(only, 0) if k == 0 else rep_only[i]
                    return v * lift[i] if k == h - 1 else v
                return _round_totals(n, h, one)
        else:

            def restricted(h: int) -> list[int]:
                off = max(n // max(h, 1), 1)
                out = []
                for j in range(n):
                    used: set[str] = set()
                    total = 0.0
                    for k in range(h):
                        i = (j + k * off) % n
                        left = [(v, t) for t, v in by_type[i].items() if t not in used]
                        if not left:
                            continue
                        v, t = max(left)
                        used.add(t)
                        total += v * lift[i] if k == h - 1 else v
                    out.append(int(total))
                return out

        per_round = restricted(hands)
        totals = {h: restricted(h) for h in range(1, hands + 1)} if rounds else {}
    elif rounds:

        def one_hand(i: int, k: int, h: int) -> float:
            if k == 0:  # the first hand (a one-hand round: Acrobat, no repeat)
                return last[i] if h == 1 else scores[i]
            return last_rep[i] if k == h - 1 else rep[i]

        totals = {h: _round_totals(n, h, lambda i, k, h=h: one_hand(i, k, h)) for h in range(1, hands + 1)}
    else:
        totals = {}
    per_hand = int(sum(per_round) / len(per_round) / hands)
    per_hand_low = int(percentile(per_round, K5_PERCENTILE) / hands)
    return {"per_hand": per_hand, "per_hand_low": per_hand_low, "types": types, "chosen": chosen,
            "rounds": {h: sorted(v) for h, v in totals.items()}}


def percentile(values: list[float] | list[int], p: float) -> float:
    """Nearest-rank percentile: sorted(values)[ceil(p/100 * n) - 1] (K5)."""
    if not values:
        return 0
    ordered = sorted(values)
    k = max(int(-(-p * len(ordered) // 100)) - 1, 0)
    return ordered[min(k, len(ordered) - 1)]


def _boss_view(G: dict[str, Any], draws: list) -> tuple[dict[str, Any], list]:
    """G with the ante's boss CURRENT and the draws debuffed by it."""
    boss = (G.get("blinds") or {}).get("boss") or {}
    name = str(boss.get("name") or "")
    blinds = {k: dict(v or {}) for k, v in (G.get("blinds") or {}).items()}
    for k, v in blinds.items():
        v["status"] = "CURRENT" if k == "boss" else "DEFEATED"
    Gb = {**G, "blinds": blinds}
    if name in ("The Eye", "The Mouth"):
        Gb = G  # one hand type: the strongest repeated type keeps its score
    suit = knowledge.SUIT_BOSSES.get(name)

    def hit(c: dict[str, Any]) -> bool:
        n = _norm(c)
        return bool((suit and n["suit"] == suit and n["enh"] != "WILD")
                    or (name in BOSS_DEBUFF_FACES and n["rank"] in FACE_RANKS))

    def under(cards: list) -> list:
        return [_debuffed(c) if hit(c) else c for c in cards]

    if suit or name in BOSS_DEBUFF_FACES:
        draws = [(under(h), under(r)) for h, r in draws]
    if name == "The Manacle":  # E2a: hand size - 1 (the same draws minus their last card)
        draws = [(h[:-1], [h[-1], *r] if h else r) for h, r in draws]
    if name == "The Wheel":
        # E2a: 1 in 7 drawn cards face down (Luna cannot plan with them; they
        # still score as the card they are: a random card of the deck mix)
        rng = random.Random(7)

        def wheel(cards: list) -> list:
            return [
                {**c, "state": {**(c.get("state") or {}), "hidden": True}} if rng.random() < 1 / 7 else c
                for c in cards
            ]

        draws = [(wheel(h), wheel(r)) for h, r in draws]
    return Gb, draws


PLAYS_PER_BLIND = 3  # K8: plays per blind when growing jokers between blinds
STRAIGHT_TYPES = {"Straight", "Straight Flush"}


def planets_per_round(G: dict[str, Any], history: list[dict[str, Any]] | None) -> float:
    """Planets used per round so far this run (at least 0.5)."""
    n = 0
    for h in history or []:
        res = str(h.get("result") or "")
        m = re.match(r"(?:used|took) (.+?)(?: from pack)?$", res)
        if m and knowledge.planet_hand(m.group(1)):
            n += 1
    rounds = max(int(G.get("round_num") or 1), 1)
    return max(0.5, n / rounds)


def grown(
    G: dict[str, Any],
    blinds: int,
    types: Counter,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """G with growing / decaying jokers moved ``blinds`` blinds ahead (P2-3, K8).

    ``types`` = how often each hand type is the best play (from the sampler).
    Spare Trousers +2 Mult per Two Pair, Runner +15 Chips per Straight,
    Supernova +1 per play of the hand, Constellation X0.1 per planet,
    Popcorn -4 Mult per round, Ice Cream -5 Chips per hand.
    """
    if blinds <= 0:
        return G
    plays = PLAYS_PER_BLIND * blinds
    total = max(sum(types.values()), 1)
    share = {t: n / total for t, n in types.items()}
    two_pair = sum(v for t, v in share.items() if t in TWO_PAIR_TYPES)
    straight = sum(v for t, v in share.items() if t in STRAIGHT_TYPES)
    cards = []
    for j in _area_cards(G, "jokers"):
        key = j.get("key", "")
        cur = _currently(j)
        effect = None
        if key == "j_trousers":
            effect = f"(Currently +{cur + 2 * plays * two_pair:g} Mult)"
        elif key == "j_runner":
            effect = f"(Currently +{cur + 15 * plays * straight:g} Chips)"
        elif key == "j_constellation":
            x = cur or 1.0
            effect = f"(Currently X{x + 0.1 * planets_per_round(G, history) * blinds:.2f} Mult)"
        elif key == "j_popcorn":
            m = FIRST_PLUS.search(str((j.get("value") or {}).get("effect", "")))
            now = float(m.group(1)) if m else 20.0
            effect = f"+{max(now - 4 * blinds, 0):g} Mult"
        elif key == "j_ice_cream":
            m = FIRST_PLUS.search(str((j.get("value") or {}).get("effect", "")))
            now = float(m.group(1)) if m else 100.0
            effect = f"+{max(now - 5 * plays, 0):g} Chips"
        if effect is not None:
            j = {**j, "value": {**(j.get("value") or {}), "effect": effect}}
        cards.append(j)
    area = {**(G.get("jokers") or {}), "cards": cards}
    out = {**G, "jokers": area}
    if "j_supernova" in set(_joker_keys(G)):
        hands_tbl = {k: dict(v or {}) for k, v in (G.get("hands") or {}).items()}
        for t, v in share.items():
            if t in hands_tbl:
                hands_tbl[t]["played"] = int(hands_tbl[t].get("played", 0)) + round(plays * v)
        out["hands"] = hands_tbl
    return out


def power_check(G: dict[str, Any], plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Expected score per hand from the hands Luna actually makes (P2-1).

    Samples dealt hands from the whole deck, plays the best candidate (any
    hand type, held cards scored), with one discard per hand from High Card /
    Pair; Card Sharp, Acrobat and Spare Trousers growth inside the blind are
    counted. The boss version applies this ante's boss (debuffs, The Psychic
    padding, The Needle 1 hand, The Water no discards, The Flint halving).
    """
    plan = plan or main_hand_plan(G)
    return _cached(_state_key(G, plan["hand"], "power"), lambda: _power_check(G, plan))


def _power_check(G: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    G_owned = _with_jokers(G, _area_cards(G, "jokers"))
    G_owned["blinds"] = {
        k: {**v, "status": "UPCOMING"} if v.get("status") == "CURRENT" else v
        for k, v in (G.get("blinds") or {}).items()
    }
    draws = sample_draws(G)
    now = _strength(G_owned, draws, rounds=True)
    boss = (G.get("blinds") or {}).get("boss") or {}
    name = str(boss.get("name") or "")
    Gb, bdraws = _boss_view(G_owned, draws)
    # E2a: every boss's rules inside the estimate (The Eye / The Mouth too)
    bstr = _strength(Gb, bdraws, boss=name, discards=name != "The Water", rounds=True)
    total = max(sum(now["types"].values()), 1)
    made = now["types"].get(plan["hand"], 0) / total
    return {
        "typical": now["per_hand"],
        "per_hand": now["per_hand"],
        "per_hand_low": now["per_hand_low"],
        "make_rate": made,
        "best_types": [t for t, _ in now["types"].most_common(3)],
        "types": dict(now["types"]),
        "boss_make_rate": made,
        "boss_per_hand": bstr["per_hand"],
        "boss_per_hand_low": bstr["per_hand_low"],
        "boss_hands_allowed": 1 if name == "The Needle" else _hands_per_round(G),
        # E2a: sampled round totals (h hands -> sorted totals) for the win chance
        "rounds": now["rounds"],
        "boss_rounds": bstr["rounds"],
    }


def boss_check(
    G: dict[str, Any], history: list[dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    """Can the build beat this ante's boss (its rule, its hands)? (S2, K7)

    Judged from the ante's first shop with jokers grown through the blinds
    still to play before the boss. Returns None without a boss; else
    {name, target, per_hand, hands, allowed, ok, needs}.
    """
    blinds = G.get("blinds") or {}
    boss = blinds.get("boss") or {}
    target = int(boss.get("score") or 0)
    if not boss or not target or boss.get("status") == "DEFEATED":
        return None
    name = str(boss.get("name") or "")
    plan = main_hand_plan(G)

    def make() -> dict[str, Any]:
        before = sum(
            1
            for k in ("small", "big")
            if (blinds.get(k) or {}).get("status") in ("SELECT", "UPCOMING")
        )
        power = power_check(G, plan)
        Gg = grown(G, before, Counter(power.get("types") or {}), history)
        Gg = _with_jokers(Gg, _area_cards(Gg, "jokers"))
        Gb, bdraws = _boss_view(Gg, sample_draws(G))
        per = _strength(Gb, bdraws, boss=name, discards=name != "The Water")["per_hand_low"]
        allowed = 1 if name == "The Needle" else _hands_per_round(G)
        hands = -(-target // max(per, 1))
        return {
            "name": name,
            "target": target,
            "per_hand": per,
            "hands": hands,
            "allowed": allowed,
            "ok": per > 0 and hands <= allowed,
            "needs": max(-(-target // allowed) - per, 0),
            "grown_blinds": before,
        }

    return _cached(_state_key(G, len(history or []), "boss_check"), make)


# Boss reroll (Director's Cut / Retcon; $10 each). Owner rule: always reroll
# these bosses; also reroll a boss that shuts off MAIN_HAND, or one the
# current build cannot beat by the strength check. Pass 3: The Wall only in
# Antes 1-3, later when the boss check fails (C5); The Plant is Luna's call (C4).
BOSS_REROLL_COST = 10
BOSS_REROLL_ALWAYS = {"Violet Vessel", "The Needle"}
WALL_ALWAYS_TO_ANTE = 3
FIVE_CARD_HANDS = {"Flush", "Straight", "Full House"}
# Decision C: one reroll per ante for Director's Cut and Retcon alike; keep
# whatever boss comes next. From Ante 4, $10 must stay after the reroll,
# except for the always-reroll bosses.
BOSS_REROLL_MAX_PER_ANTE = 1
BOSS_REROLL_KEEP_FROM_ANTE = 4
BOSS_REROLL_KEEP = 10


def face_build(G: dict[str, Any]) -> bool:
    """True when an owned scoring joker works off face cards (The Plant hurts)."""
    for j in _area_cards(G, "jokers"):
        if j.get("key") in ("j_baron", "j_shoot_the_moon"):  # held Kings / Queens
            return True
        info = knowledge.joker_info(j.get("label") or j.get("key")) or {}
        if info.get("family") == "face" and info.get("category") != "ECON":
            return True
    return False


def boss_reroll_available(G: dict[str, Any]) -> bool:
    """True when the game would let you reroll the boss now (voucher, flag, $10)."""
    vouchers = set(G.get("used_vouchers") or {})
    rerolled = bool((G.get("round") or {}).get("boss_rerolled"))
    owned = "v_retcon" in vouchers or ("v_directors_cut" in vouchers and not rerolled)
    boss = (G.get("blinds") or {}).get("boss") or {}
    return (
        owned
        and int(G.get("money") or 0) >= BOSS_REROLL_COST
        and boss.get("status") in ("UPCOMING", "SELECT")
    )


def boss_reroll_reason(G: dict[str, Any]) -> str | None:
    """Why the upcoming boss should be rerolled (None: keep it or cannot reroll).

    The named bosses and the ones that shut off MAIN_HAND are rerolled at the
    first blind select of the ante, so the shops can still prepare for the new
    boss. The strength check waits until the boss is on deck (the build is final).
    """
    if not boss_reroll_available(G):
        return None
    boss = (G.get("blinds") or {}).get("boss") or {}
    name = str(boss.get("name") or "")
    plan = main_hand_plan(G)
    if name in BOSS_REROLL_ALWAYS:
        return f"{name} is a boss to always reroll"
    ante = int(G.get("ante_num") or 1)
    if ante >= BOSS_REROLL_KEEP_FROM_ANTE and int(G.get("money") or 0) - BOSS_REROLL_COST < BOSS_REROLL_KEEP:
        return None
    if name == "The Wall":  # C5 (owner, after pass 2 Q3)
        if ante <= WALL_ALWAYS_TO_ANTE:
            return f"The Wall in Ante {ante} (rerolled in Antes 1-{WALL_ALWAYS_TO_ANTE})"
        bc = boss_check(G)
        if bc and not bc["ok"]:
            return f"The Wall ({fmt_num(bc['target'])}) needs about {bc['hands']} hands at {fmt_num(bc['per_hand'])} per hand; you have {bc['allowed']}"
        return None
    # C4: The Plant is no longer rerolled automatically: Luna may ask (reroll_boss)
    if name in ("The Eye", "The Mouth"):
        return f"{name} shuts off your MAIN_HAND {plan['hand']}"
    if name == "The Psychic" and plan["hand"] not in FIVE_CARD_HANDS:
        return f"The Psychic needs 5-card plays and your MAIN_HAND is {plan['hand']}"
    suit = knowledge.SUIT_BOSSES.get(name)
    if suit and plan["hand"] == "Flush" and plan.get("suit") == suit:
        return f"{name} debuffs your Flush suit"
    if boss.get("status") == "SELECT":
        power = power_check(G, plan)
        target = int(boss.get("score") or 0)
        per_hand = int(power["boss_per_hand_low"] or 0)  # K5
        # Reroll only when THIS boss is the problem: with a boss that does not
        # cut the score, the same target must be beatable. Otherwise every new
        # boss fails too and Retcon would spend all the money for nothing.
        neutral_ok = -(-target // max(int(power["per_hand_low"] or 0), 1)) <= _hands_per_round(G)
        if target and per_hand and neutral_ok:
            hands = -(-target // per_hand)
            if hands > power["boss_hands_allowed"]:
                return (
                    f"{name} ({fmt_num(target)}) needs about {hands} hands at "
                    f"{fmt_num(per_hand)} per hand; you have {power['boss_hands_allowed']}"
                )
    return None


def luna_reroll_refusal(G: dict[str, Any], legal_only: bool | None = None) -> str | None:
    """C4: why Luna's boss-reroll request is refused now (None: allowed).

    Director's Cut (once per ante) or Retcon, $10, one reroll per ante (shared
    with the harness's, ``G["luna"]["boss_rerolls"]``), from Ante 4 $10 kept
    after it, boss not yet defeated. Checked when Luna asks (SHOP) and again
    at the blind select that runs it.

    Pass 4 A1: ``legal_only`` (default: ``G["luna"]["advice_vetoes"] is False``)
    keeps only the game's rules (voucher, Director's Cut once per ante, $10,
    boss not yet played) and drops the advice rules (one per ante, $10 kept
    from Ante 4)."""
    if legal_only is None:
        legal_only = (G.get("luna") or {}).get("advice_vetoes") is False
    vouchers = set(G.get("used_vouchers") or {})
    if not vouchers & {"v_directors_cut", "v_retcon"}:
        return "it needs Director's Cut or Retcon"
    boss = (G.get("blinds") or {}).get("boss") or {}
    if boss.get("status") not in ("UPCOMING", "SELECT"):
        return "this ante's boss is already being played or beaten"
    luna = G.get("luna") or {}
    if not legal_only and int(luna.get("boss_rerolls") or 0) >= BOSS_REROLL_MAX_PER_ANTE:
        return "the boss was already rerolled this ante (one per ante)"
    if "v_retcon" not in vouchers and (G.get("round") or {}).get("boss_rerolled"):
        return "Director's Cut was already used this ante"
    money = int(G.get("money") or 0)
    if money < BOSS_REROLL_COST:
        return f"it costs ${BOSS_REROLL_COST} and you have ${money}"
    if legal_only:
        return None
    if int(G.get("ante_num") or 1) >= BOSS_REROLL_KEEP_FROM_ANTE and money - BOSS_REROLL_COST < BOSS_REROLL_KEEP:
        return f"from Ante 4 ${BOSS_REROLL_KEEP} must stay after the ${BOSS_REROLL_COST} reroll (you have ${money})"
    return None


def _with_jokers(G: dict[str, Any], jokers: list[dict[str, Any]]) -> dict[str, Any]:
    area = dict(G.get("jokers") or {})
    area["cards"] = jokers
    area["count"] = len(jokers)
    G2 = {**G, "jokers": area}
    order = joker_order(G2)
    if order:
        area["cards"] = [jokers[i] for i in order]
    return G2


GROWING = {"j_trousers", "j_runner", "j_constellation", "j_supernova", "j_popcorn", "j_ice_cream"}
DISCARD_ENDS = {"j_banner", "j_mystic_summit"}  # SCORE depends on discards kept (W5)
GROWTH_BLINDS = 3  # P2-3: growing jokers valued over the next 3 rounds


def _neutral(G: dict[str, Any]) -> dict[str, Any]:
    """G with no blind CURRENT (shop valuation is boss-free)."""
    return {
        **G,
        "blinds": {
            k: {**v, "status": "UPCOMING"} if v.get("status") == "CURRENT" else v
            for k, v in (G.get("blinds") or {}).items()
        },
    }


def _carry(G: dict[str, Any], j: dict[str, Any]) -> str | None:
    """Why an owned joker is never a swap candidate (None: it can be swapped)."""
    plan = main_hand_plan(G)
    key = j.get("key", "")
    label = str(j.get("label") or key)
    if label in synergy_keep(G):
        return "synergy"
    commit = plan.get("commit") or {}
    if commit.get("trigger") == label:
        return "it sets MAIN_HAND"
    if key in GROWING - {"j_popcorn", "j_ice_cream"} or label in knowledge.GROWS_XMULT:
        return "it grows"
    info = knowledge.joker_info(label) or {}
    ante = int(G.get("ante_num") or 1)
    money = int(G.get("money") or 0)
    # [ECON] is kept through Ante 4 unless money is at the interest cap (G3)
    if info.get("category") == "ECON" and ante <= 4 and money < 25:
        return "economy"
    return None


def shop_impact(G: dict[str, Any]) -> dict[str, Any]:
    """Score change per hand for each shop/pack joker and MAIN_HAND planet, what
    each owned joker adds, WEAKEST, and the best swap per shop joker (P2-1 sampler)."""
    return _cached(_state_key(G, "shop_impact"), lambda: _shop_impact(G))


def _shop_impact(G: dict[str, Any]) -> dict[str, Any]:
    plan = main_hand_plan(G)
    out: dict[str, Any] = {
        "hand": plan["hand"],
        "cards": [],
        "plays": 0,
        "score": 0,
        "shop": {},
        "pack": {},
        # E2b: numeric SCORE % per hand of each shop / pack joker (now)
        "shop_pct": {},
        "pack_pct": {},
        "owned": {},
        "swaps": {},
        "pack_swaps": {},
        "weakest": None,
        "chips_sources": 0,
    }
    owned = _area_cards(G, "jokers")
    G0 = _neutral(G)
    draws = sample_draws(G)[:SHOP_SAMPLES]
    if not draws:
        return out
    G_owned = _with_jokers(G0, owned)
    dealt = _dealt_hands(G_owned, draws)

    def score(js: list[dict[str, Any]], Gx: dict[str, Any] | None = None) -> float:
        Gv = _with_jokers(Gx if Gx is not None else G0, js)
        return _score_hands(Gv, dealt)["per_hand"]

    base_run = _score_hands(G_owned, dealt)
    base = base_run["per_hand"]
    types = base_run["types"]
    out["score"] = base
    out["plays"] = len(dealt)
    out["mix"] = [t for t, _ in types.most_common(3)]

    def pct(delta: float) -> str:
        return f" ({round(delta * 100 / base)}%)" if base else ""

    def signed(v: float) -> str:
        return f"{'+' if v >= 0 else ''}{fmt_num(v)}"

    pct_now: dict[int, int] = {}

    def joker_text(card: dict[str, Any]) -> str:
        key = card.get("key", "")
        new = score([*owned, card])
        if base:
            pct_now[id(card)] = round((new - base) * 100 / base)
        txt = f"{signed(new - base)} per hand{pct(new - base)}"
        if key in GROWING or str(card.get("label")) in knowledge.GROWS_XMULT:
            Gg = grown(_with_jokers(G0, [*owned, card]), GROWTH_BLINDS, types)
            later = _score_hands(Gg, dealt)["per_hand"]
            txt += f" now, {signed(later - base)} in 3 rounds"
        if key == "j_acrobat":
            rnd = dict(G0.get("round") or {})
            Gl = {**G0, "round": {**rnd, "hands_left": 1}}
            last = score([*owned, card], Gl) - score(owned, Gl)
            txt += f" (X3 on the LAST hand of a blind only: {signed(last)} on that hand, X1 on the others)"
        if key in DISCARD_ENDS:
            rnd = dict(G0.get("round") or {})
            keep = score([*owned, card], {**G0, "round": {**rnd, "discards_left": 4}}) - score(owned, {**G0, "round": {**rnd, "discards_left": 4}})
            dig = score([*owned, card], {**G0, "round": {**rnd, "discards_left": 0}}) - score(owned, {**G0, "round": {**rnd, "discards_left": 0}})
            txt = f"{signed(keep)} per hand if you keep all 4 discards, {signed(dig)} after using them"
        return txt

    def item_delta(card: dict[str, Any]) -> str | None:
        if card.get("set") == "JOKER":
            if (card.get("state") or {}).get("hidden"):
                return None
            return joker_text(card)
        if card.get("set") == "PLANET":
            hand = knowledge.planet_hand(card.get("label"))
            if hand != plan["hand"]:
                return None
            levels = {k: dict(v or {}) for k, v in (G.get("hands") or {}).items()}
            cur = levels.setdefault(hand, {})
            dc, dm = LEVEL_UP.get(hand, (0, 0))
            cur["chips"] = float(cur.get("chips", 0)) + dc
            cur["mult"] = float(cur.get("mult", 0)) + dm
            new = score(owned, {**G0, "hands": levels})
            return f"{signed(new - base)} per hand{pct(new - base)}"
        return None

    for area in ("shop", "pack"):
        for i, card in enumerate(_area_cards(G, area)):
            d = item_delta(card)
            if d:
                out[area][i] = d
                if card.get("set") == "JOKER" and id(card) in pct_now:
                    out[area + "_pct"][i] = pct_now[id(card)]
    contrib = {}
    for i, j in enumerate(owned):
        rest = [x for k, x in enumerate(owned) if k != i]
        gain = int(base - score(rest))
        contrib[i] = gain
        out["owned"][i] = f"adds {fmt_num(gain)} per hand"
    out["gains"] = contrib
    out["chips_sources"] = sum(
        1 for j in owned if (knowledge.joker_info(j.get("label")) or {}).get("category") == "CHIPS"
    )
    candidates = [(gain, i) for i, gain in contrib.items() if _carry(G, owned[i]) is None]
    if candidates:
        gain, i = min(candidates)
        out["weakest"] = {"index": i, "label": owned[i].get("label"), "gain": gain}
    jokers_area = G.get("jokers") or {}
    if owned and int(jokers_area.get("count", len(owned))) >= int(jokers_area.get("limit", 5)):
        # W1/W2: with full slots, the best swap per shop joker over every owned
        # joker that can be swapped
        # P2-7: pack jokers too (picked with full slots when sell_in_pack is on)
        for area, slot in (("shop", "swaps"), ("pack", "pack_swaps")):
            for i, card in enumerate(_area_cards(G, area)):
                if card.get("set") != "JOKER" or _norm(card)["ed"] == "NEGATIVE":
                    continue
                best = None
                for _g, k in candidates:
                    rest = [x for n, x in enumerate(owned) if n != k]
                    delta = score([*rest, card]) - base
                    if best is None or delta > best[0]:
                        best = (delta, k)
                if best is not None:
                    out[slot][i] = {
                        "index": best[1],
                        "label": owned[best[1]].get("label"),
                        "delta": int(best[0]),
                        "text": f"swap for {owned[best[1]].get('label')}: {signed(best[0])} per hand{pct(best[0])}",
                    }
    return out


def live_xmult(G: dict[str, Any], card: dict[str, Any], score_text: str | None) -> bool:
    """An [XMULT] joker that fires on the hands Luna makes (its SCORE added now
    is above 0), or a growing xMult with its source: such a joker may replace
    another even when today's swap is not a gain (owner F8: "excellent joker ...
    buy it and replace another"). Blackboard and other xMult jokers with SCORE
    +0 are judged by SCORE alone (owner, V8 (b))."""
    label = str(card.get("label") or "")
    if "SOURCE PRESENT" in grows_xmult(G, card):
        return True
    if (knowledge.joker_info(label) or {}).get("category") != "XMULT":
        return False
    m = re.match(r"\s*([+-]?[\d,]+)", score_text or "")
    return bool(m) and int(m.group(1).replace(",", "")) > 0


def _pack_swap(G: dict[str, Any], params: dict[str, Any]) -> dict[str, Any] | str | None:
    """P2-7 (flag ``sell_in_pack``): a joker picked from a pack with full slots
    replaces the owned joker whose swap raises the score most; refused when no
    swap raises it (live xMult jokers excepted, F8)."""
    if not (G.get("luna") or {}).get("sell_in_pack") or G.get("state") != "SMODS_BOOSTER_OPENED":
        return None
    if params.get("skip") or params.get("card") is None:
        return None
    jokers = G.get("jokers") or {}
    if int(jokers.get("count", 0)) < int(jokers.get("limit", 5)):
        return None
    try:
        idx = int(params["card"])
        card = _area_cards(G, "pack")[idx]
    except (IndexError, TypeError, ValueError):
        return None
    if card.get("set") != "JOKER" or _norm(card)["ed"] == "NEGATIVE":
        return None
    label = str(card.get("label") or card.get("key"))
    impact = shop_impact(G)
    swap = impact["pack_swaps"].get(idx)
    if not swap:
        return (
            f"Your joker slots are full and every joker you own is kept (it sets MAIN_HAND, "
            f"grows, pays money or is a synergy pair), so there is no room for {label}. "
            "Pick another card or skip."
        )
    if swap["delta"] <= 0 and not live_xmult(G, card, impact["pack"].get(idx)):
        return (
            f"{label} would not raise your score over {swap['label']} "
            f"({swap['text']}). Pick another card or skip."
        )
    return {"sell": int(swap["index"]), "label": swap["label"], "buy": label}


def swap_plan(
    G: dict[str, Any], method: str, params: dict[str, Any]
) -> dict[str, Any] | str | None:
    """Sell-first plan for buying a shop joker while joker slots are full.

    Returns None when no swap is needed, a refusal message when the swap is
    bad, or ``{"sell": index, "label": ..., "buy": label}``. Every owned joker
    that can be swapped is tried and the best one is sold (pass 1 W1); the swap
    must raise the score (F3, no margin), or for a growing joker raise it within
    3 rounds. F4: while THIN/SHORT a growing xMult joker (Constellation, ...) is
    bought without that test and replaces the weakest joker that is not the main
    +Mult or +Chips source.
    """
    if method == "pack":
        return _pack_swap(G, params)
    if method != "buy" or "card" not in params or G.get("state") != "SHOP":
        return None
    jokers = G.get("jokers") or {}
    if int(jokers.get("count", 0)) < int(jokers.get("limit", 5)):
        return None
    try:
        idx = int(params["card"])
        card = _area_cards(G, "shop")[idx]
    except (IndexError, TypeError, ValueError):
        return None
    if card.get("set") != "JOKER" or _norm(card)["ed"] == "NEGATIVE":
        return None
    label = str(card.get("label") or card.get("key"))
    owned = _area_cards(G, "jokers")
    impact = shop_impact(G)
    swap = impact["swaps"].get(idx)
    if not swap:
        return (
            f"Your joker slots are full and every joker you own is kept (it sets MAIN_HAND, "
            f"grows, pays money or is a synergy pair), so there is no room for {label}. "
            "Buy something else or call next_round."
        )
    sell = int(swap["index"])
    grows = card.get("key") in GROWING or label in knowledge.GROWS_XMULT
    status = (G.get("luna") or {}).get("status") or run_status(G)["status"]
    if label in knowledge.GROWS_XMULT and status in ("THIN", "SHORT"):
        contrib = {
            i: int(str(t).split()[1].replace(",", ""))
            for i, t in impact["owned"].items()
            if str(t).startswith("adds")
        }
        main = set()
        for cat in ("MULT", "CHIPS"):
            of_cat = [i for i in contrib if (knowledge.joker_info(owned[i].get("label")) or {}).get("category") == cat]
            if of_cat:
                main.add(max(of_cat, key=lambda i: contrib[i]))
        pool = [i for i in contrib if i not in main and _carry(G, owned[i]) is None]
        if pool:
            sell = min(pool, key=lambda i: contrib[i])
    elif swap["delta"] <= 0 and not live_xmult(G, card, impact["shop"].get(idx)):
        later = None
        if grows:
            rest = [x for n, x in enumerate(owned) if n != sell]
            G0 = _neutral(G)
            G_owned = _with_jokers(G0, owned)
            dealt = _dealt_hands(G_owned, sample_draws(G)[:SHOP_SAMPLES])
            types = Counter(power_check(G).get("types") or {})
            now = _score_hands(G_owned, dealt)["per_hand"]
            later = _score_hands(grown(_with_jokers(G0, [*rest, card]), GROWTH_BLINDS, types), dealt)["per_hand"] - now
        if later is None or later <= 0:
            return (
                f"Refused: the best swap for {label} is {swap['text']} (now "
                f"{fmt_num(impact['score'])} per hand), so it would not raise your score. "
                "Buy something else or call next_round."
            )
    out = owned[sell]
    price = int((card.get("cost") or {}).get("buy") or 0)
    money = int(G.get("money") or 0) + int((out.get("cost") or {}).get("sell") or 0)
    if price > money:
        return (
            f"Even after selling {out.get('label')} you would have ${money}, not "
            f"enough for {label} (${price}). Buy something else or call next_round."
        )
    return {"sell": sell, "label": out.get("label"), "buy": label}


def synergy_keep(G: dict[str, Any]) -> dict[str, str]:
    """Owned jokers never to sell because of a partner joker: label -> reason.

    Hanging Chad + Photograph: the first face card scores three times, and
    Photograph's x2 fires each time (x8). Only The Plant (face cards debuffed)
    breaks it, and a boss reroll voucher (Director's Cut / Retcon) avoids that.
    """
    labels = {j.get("label") for j in _area_cards(G, "jokers")}
    if not {"Hanging Chad", "Photograph"} <= labels:
        return {}
    boss = str(((G.get("blinds") or {}).get("boss") or {}).get("name") or "")
    vouchers = {str(v) for v in (G.get("used_vouchers") or {})}
    reroll = bool(vouchers & {"v_directors_cut", "v_retcon"})
    if boss == "The Plant" and not reroll:
        return {}
    reason = "with Photograph it gives the first face card x2 three times (x8)"
    return {"Hanging Chad": reason, "Photograph": reason}


def _sell_veto(G: dict[str, Any], joker: dict[str, Any], full: bool) -> str | None:
    """Refuse selling a joker unless it hurts you or makes room you can use.

    A sale is fine for a [TRAP] / tier T joker, to make room for Judgement /
    The Soul / Wraith, or when slots are full and a Buffoon pack is affordable
    with the sale money. Joker-for-joker swaps go through swap_plan instead.
    """
    label = str(joker.get("label") or joker.get("key") or "this joker")
    info = knowledge.joker_info(label) or {}
    ante = int(G.get("ante_num") or 1)
    tier = info.get("early") if ante <= 3 else info.get("late")
    if info.get("category") == "TRAP" or tier == "T":
        return None
    if label in (keep := synergy_keep(G)):
        return f"Keep {label}: {keep[label]}. Sell a different joker."
    makes_joker = ("c_judgement", "c_soul", "c_wraith")
    if any(c.get("key") in makes_joker for c in _area_cards(G, "consumables")):
        return None
    if not full:
        # F7 / P2-7: with free slots, an unwanted joker that adds nothing now
        # (not XMULT/SCALE/ECON, does not grow, nothing depends on it) may go.
        owned = _area_cards(G, "jokers")
        idx = next((i for i, j in enumerate(owned) if j is joker), None)
        if (
            idx is not None
            and info.get("category") not in ("XMULT", "SCALE", "ECON")
            and _carry(G, joker) is None
            and int(shop_impact(G).get("gains", {}).get(idx, 1)) <= 0
        ):
            return None
        return (
            f"Keep {label}: your joker slots are not full and it adds to your score, "
            "so selling only loses a joker. Buy something else, use a card, or call next_round."
        )
    money = int(G.get("money") or 0) + int((joker.get("cost") or {}).get("sell") or 0)

    def price(c: dict[str, Any]) -> int:
        return int((c.get("cost") or {}).get("buy") or 0)

    buffoon = [
        p
        for p in _area_cards(G, "packs")
        if "buffoon" in str(p.get("label", "")).lower() and price(p) <= money
    ]
    if not buffoon:
        return (
            f"Keep {label}: to replace a joker, just buy the new one (the harness "
            "sells WEAKEST for you if the new joker is better). Otherwise buy "
            "something else, use a card, or call next_round."
        )
    return None


def _cheapest_buffoon(G: dict[str, Any]) -> dict[str, Any] | None:
    money = int(G.get("money") or 0)
    packs = [
        p
        for p in _area_cards(G, "packs")
        if "buffoon" in str(p.get("label", "")).lower() and int((p.get("cost") or {}).get("buy") or 0) <= money
    ]
    return min(packs, key=lambda p: int((p.get("cost") or {}).get("buy") or 0)) if packs else None


def first_shop_tight(G: dict[str, Any]) -> dict[str, Any] | None:
    """C7: first shop visit, money cannot cover the cheapest affordable Buffoon
    pack AND a shop joker: Luna's call (no refusal). None otherwise."""
    luna = G.get("luna") or {}
    if G.get("state") != "SHOP" or not luna.get("first_shop"):
        return None
    pack = _cheapest_buffoon(G)
    if pack is None:
        return None
    money = int(G.get("money") or 0)
    cost = int((pack.get("cost") or {}).get("buy") or 0)
    jokers = [
        str(c.get("label"))
        for c in _area_cards(G, "shop")
        if c.get("set") == "JOKER" and int((c.get("cost") or {}).get("buy") or 0) <= money
        and money < int((c.get("cost") or {}).get("buy") or 0) + cost
    ]
    if not jokers:
        return None
    return {"pack": str(pack.get("label")), "pack_cost": cost, "jokers": jokers, "money": money}


def _first_shop_veto(G: dict[str, Any], index: Any) -> str | None:
    """First shop VISIT of the run (owner C1, P2-6): open an affordable Buffoon
    pack before buying any shop joker. Pass 3 C7 (owner, after pass 2 Q4,
    before pass 3 Q5a): when money cannot cover both, any shop joker may come
    first (Luna's call; the prompt shows the trade-off)."""
    try:
        card = _area_cards(G, "shop")[int(index)]
    except (IndexError, TypeError, ValueError):
        return None
    if card.get("set") != "JOKER":
        return None
    money = int(G.get("money") or 0)
    buffoon = [
        p
        for p in _area_cards(G, "packs")
        if "buffoon" in str(p.get("label", "")).lower()
        and int((p.get("cost") or {}).get("buy") or 0) <= money
    ]
    if not buffoon:
        return None
    price = int((card.get("cost") or {}).get("buy") or 0)
    pack = min(int((p.get("cost") or {}).get("buy") or 0) for p in buffoon)
    if money < price + pack:  # C7: tight money: Luna's call
        return None
    return (
        f"First shop: open the Buffoon pack before buying {card.get('label')} "
        "(it offers a choice of jokers); then buy shop jokers that help."
    )


REROLL_CAP = {"low": 6, "high": 10}  # decision B: rerolls leaving < $25, per shop
REROLL_RUNAWAY = 30


def reroll_veto(G: dict[str, Any], rerolls: int) -> str | None:
    """Money lines for rerolls (P2-9, owner F6/G1/F1/F8, decision B)."""
    ante = int(G.get("ante_num") or 1)
    if ante <= 1:
        return "Reroll refused: no rerolls in Ante 1 (early economy)."
    money = int(G.get("money") or 0)
    cost = int((G.get("round") or {}).get("reroll_cost", 5) or 0)
    after = money - cost
    status = (G.get("luna") or {}).get("status") or run_status(G)["status"]
    defining = bool(main_hand_plan(G).get("commit"))
    if ante <= 3:
        line = 10 if status in ("THIN", "SHORT") or not defining else 25
    else:
        line = 25 if status == "COMFORTABLE" else 10
    if after < line:
        why = "you are COMFORTABLE, so keep $25 for interest" if line == 25 else "keep at least $10"
        return (
            f"Reroll refused: it costs ${cost} and would leave ${after}; {why}. "
            "Buy something useful or call next_round."
        )
    cap = REROLL_CAP["low"] if ante <= 4 else REROLL_CAP["high"]
    if after < 25 and rerolls >= cap:
        return (
            f"Reroll refused: {rerolls} rerolls in this shop already (at most {cap} that leave "
            "less than $25). Buy something useful or call next_round."
        )
    if rerolls >= REROLL_RUNAWAY:
        return "Reroll refused: too many rerolls in one shop. Call next_round."
    return None


def _consumable_full_veto(G: dict[str, Any], params: dict[str, Any]) -> str | None:
    """Pass 4 F4 (legality): the game rejects a shop consumable buy with full
    consumable slots ("Cannot purchase consumable card, consumable slots are
    full"); a Negative one brings its own slot."""
    if "card" not in params or G.get("state") != "SHOP":
        return None
    try:
        card = _area_cards(G, "shop")[int(params["card"])]
    except (IndexError, TypeError, ValueError):
        return None
    if card.get("set") not in ("TAROT", "PLANET", "SPECTRAL") or _norm(card)["ed"] == "NEGATIVE":
        return None
    cons = G.get("consumables") or {}
    count = int(cons.get("count", len(_area_cards(G, "consumables"))) or 0)
    if count < int(cons.get("limit", 2) or 2):
        return None
    return (
        f"Your consumable slots are full ({count}/{int(cons.get('limit', 2) or 2)}). "
        "To buy this card, use or sell one of your consumables first."
    )


# Pass 5 G1f (A2 N12): Balatro refuses Ankh with no free joker slot (card.lua
# check_use); the mod then waits 30 s for a pack close that never comes
ANKH_FULL_PACK = ("Ankh needs a free joker slot: the game refuses it while your joker slots are full "
                  "(and you cannot sell inside a pack). Pick another card or skip.")
ANKH_FULL_USE = "Ankh needs a free joker slot: the game refuses it while your joker slots are full. Sell a joker first."


def _legal_only_rest(
    G: dict[str, Any], method: str, params: dict[str, Any], shop_rerolls: int, full: bool
) -> str | None:
    """Pass 4 A1 (advice_vetoes off): the legality / protection checks of
    validate_action after the card-count checks, with the same messages."""
    if method == "reroll" and shop_rerolls >= REROLL_RUNAWAY:  # loop guard only
        return "Reroll refused: too many rerolls in one shop. Call next_round."
    if method == "buy" and (veto := _consumable_full_veto(G, params)):
        return veto
    if method == "buy" and "card" in params and G.get("state") == "SHOP" and full:
        # Legality (build thread, 2026-11-09): the game rejects a full-slot joker buy, and 3 game rejections in a row
        # end the run; a refusal here instead counts toward leaving the shop. Negative jokers bring their own slot.
        try:
            card = _area_cards(G, "shop")[int(params["card"])]
        except (IndexError, TypeError, ValueError):
            card = {}
        if card.get("set") == "JOKER" and _norm(card)["ed"] != "NEGATIVE":
            return "Your joker slots are full. To buy a joker with full slots, sell one first."
    if method == "pack":
        if params.get("skip") and params.get("card") is not None:
            return "Use either `card` or `skip`, not both."
        if params.get("card") is not None:
            pack = _area_cards(G, "pack")
            try:
                chosen = pack[int(params["card"])]
            except (IndexError, TypeError, ValueError):
                return None
            key = chosen.get("key", "")
            if key == "c_ankh" and full:
                return ANKH_FULL_PACK
            sell_in_pack = bool((G.get("luna") or {}).get("sell_in_pack"))
            if (
                (chosen.get("set") == "JOKER" and not sell_in_pack)
                or key in ("c_judgement", "c_soul", "c_wraith")
            ) and full:
                return (
                    "Your joker slots are full: this card would be wasted (you cannot sell inside a pack). "
                    "Skip the pack or pick another card."
                )
            if key == "c_death" and len(params.get("targets") or []) != 2:
                return "Death needs exactly 2 targets: [junk card, card to copy]."
    if method == "reroll_boss":
        if G.get("state") == "SHOP":
            if (G.get("luna") or {}).get("boss_reroll_request"):
                return "Boss reroll refused: you already asked for one; it runs at the next blind select."
            if why := luna_reroll_refusal(G, legal_only=True):
                return f"Boss reroll refused: {why}."
            return None
        if G.get("state") != "BLIND_SELECT":
            return "reroll_boss only works in the shop (request) or on the blind select screen."
        if not boss_reroll_available(G):
            return (
                "Boss reroll refused: it needs Director's Cut (once per ante) or "
                f"Retcon and ${BOSS_REROLL_COST}."
            )
    if method == "use":
        cons = _area_cards(G, "consumables")
        try:
            chosen = cons[int(params.get("consumable", -1))]
        except (IndexError, TypeError, ValueError):
            return None
        key = chosen.get("key", "")
        if key == "c_ankh" and full:
            return ANKH_FULL_USE
        if key in ("c_judgement", "c_soul", "c_wraith") and full:
            return "Your joker slots are full: sell a joker before using this card."
        if key == "c_death" and len(params.get("cards") or []) != 2:
            return "Death needs exactly 2 cards: [junk card, card to copy]."
    return None


WRONG_ITEM_SETS = ("JOKER", "TAROT", "PLANET", "SPECTRAL")


def _offer_core(label: str) -> str:
    """Lower-case item name without a leading "The " (pass 5 G1e)."""
    core = str(label).strip().lower()
    return core[4:] if core.startswith("the ") else core


def _named_in(core: str, text: str) -> bool:
    return bool(core) and re.search(r"\b" + re.escape(core) + r"\b", text) is not None


def wrong_item_veto(offers: dict[int, str], chosen: Any, reasoning: str) -> str | None:
    """Pass 4 F1: a shop card buy whose reasoning names another offered item
    and not the chosen one (pass 1 tool index_mismatch.py: 16 of 1069 logged
    shop card buys in passes 1-3 + A0, always index 0). ``offers``: shop index -> label. Not advice:
    it repairs Luna's own intent, so it stays on with advice vetoes off."""
    try:
        i = int(chosen)
    except (TypeError, ValueError):
        return None
    why = str(reasoning or "")
    if i not in offers or not why or not offers[i]:
        return None
    # pass 5 G1e: match a name without a leading "The" ("High Priestess" names
    # The High Priestess), case-insensitive, on word boundaries; a longer offer
    # name that contains another ("Shoot the Moon" / The Moon) is taken out
    # first so it cannot name the shorter one
    low = why.lower()
    cores = {j: _offer_core(label) for j, label in offers.items() if label}

    def names(j: int) -> bool:
        text = low
        for k, other in cores.items():
            if k != j and len(other) > len(cores[j]) and _named_in(cores[j], other):
                text = re.sub(r"\b" + re.escape(other) + r"\b", " ", text)
        return _named_in(cores[j], text)

    if names(i):
        return None
    named = [(j, offers[j]) for j in sorted(cores) if j != i and names(j)]
    if not named:
        return None
    j, label = named[0]
    return (
        f"Wrong item? You chose card {i} ({offers[i]}) but your reasoning names {label} (card {j}). "
        f"To buy {label}, use card {j}; to buy {offers[i]}, say so in your reasoning."
    )


def shop_wrong_item_veto(G: dict[str, Any], params: dict[str, Any], reasoning: str) -> str | None:
    """F1 on a live shop: offers are the shop cards' labels (jokers and
    consumables; playing cards show no label line in the prompt)."""
    if G.get("state") != "SHOP" or "card" not in params:
        return None
    cards = _area_cards(G, "shop")
    offers = {i: str(c.get("label") or "") for i, c in enumerate(cards) if c.get("set") in WRONG_ITEM_SETS}
    return wrong_item_veto(offers, params.get("card"), reasoning)


def validate_action(
    G: dict[str, Any], method: str, params: dict[str, Any], shop_rerolls: int = 0, advice: bool = True
) -> str | None:
    """Return an error message for illegal or strictly bad actions, else None.

    ``shop_rerolls`` is how many rerolls the bot already made in this shop visit.
    ``advice=False`` (pass 4 A1, harness flag ``advice_vetoes``) keeps only the
    legality / format / protection checks (card counts, duplicates, pack
    card+skip, full-slot pack joker / Judgement / Soul / Wraith, Death targets,
    reroll_boss legality, the runaway reroll loop guard) and drops the advice
    vetoes of legal choices (first-shop Buffoon, shop lock, reroll money lines,
    Joker Stencil, sell veto, Buffoon pack with full slots, second Blue Seal,
    reroll_boss advice rules, The Mark face-down targets).
    """
    jokers = G.get("jokers") or {}
    full = int(jokers.get("count", 0)) >= int(jokers.get("limit", 5))
    cards = params.get("cards")
    if method == "discard" and int((G.get("round") or {}).get("discards_left", 1)) <= 0:
        return "No discards left: play the best listed play instead."
    if method in ("play", "discard") and isinstance(cards, list):
        if not cards:
            return "Select at least 1 card."
        limit = int((G.get("hand") or {}).get("highlighted_limit", 5) or 5)
        if len(cards) > limit:
            return f"You selected {len(cards)} cards; the maximum is {limit}."
        if len(set(cards)) != len(cards):
            return "Each card index may appear only once."
        # Owner (pass 1): the harness never refuses a discard; WINS is advice.
    luna = G.get("luna") or {}
    first_shop = (
        luna["first_shop"]
        if "first_shop" in luna
        else int(G.get("ante_num") or 1) == 1 and int(G.get("round_num") or 1) == 1
    )
    if not advice:
        return _legal_only_rest(G, method, params, shop_rerolls, full)
    if (
        method == "buy"
        and "card" in params
        and G.get("state") == "SHOP"
        and first_shop
        and (veto := _first_shop_veto(G, params["card"]))
    ):
        return veto
    if (
        luna.get("shop_locked")
        and G.get("state") in ("SHOP", "SMODS_BOOSTER_OPENED")
        and (method == "reroll" or (method == "buy" and G.get("state") == "SHOP"))
    ):
        return (
            "From Ante 4, once a buy takes your money below $10 the shop is over "
            "(owner F1): call next_round."
        )
    if method == "reroll" and (veto := reroll_veto(G, shop_rerolls)):
        return veto
    if method == "buy" and (veto := _consumable_full_veto(G, params)):  # F4: legality
        return veto
    if method == "buy" and "card" in params and G.get("state") == "SHOP" and full:
        try:
            card = _area_cards(G, "shop")[int(params["card"])]
        except (IndexError, TypeError, ValueError):
            card = {}
        if card.get("key") == "j_stencil" and _norm(card)["ed"] != "NEGATIVE":
            return (
                "Joker Stencil refused: it gives X1 per EMPTY joker slot and yours are "
                "full, so it adds nothing. Buy something else or call next_round."
            )
    if method == "sell" and "joker" in params and G.get("state") == "SHOP":
        try:
            target = _area_cards(G, "jokers")[int(params["joker"])]
        except (IndexError, TypeError, ValueError):
            target = None
        if target is not None and (veto := _sell_veto(G, target, full)):
            return veto
    if method == "buy" and "pack" in params and full:
        packs = _area_cards(G, "packs")
        try:
            label = str(packs[int(params["pack"])].get("label", ""))
        except (IndexError, TypeError, ValueError):
            label = ""
        try:
            price = int((packs[int(params["pack"])].get("cost") or {}).get("buy") or 0)
        except (IndexError, TypeError, ValueError):
            price = 0
        if "buffoon" in label.lower() and int(G.get("money") or 0) - price < 25:
            return (
                "Buffoon Pack refused: your joker slots are full; with full slots open one "
                "only when $25 or more stays after buying it."
            )
    if method == "pack":
        if params.get("skip") and params.get("card") is not None:
            return "Use either `card` or `skip`, not both."
        if params.get("card") is not None:
            pack = _area_cards(G, "pack")
            try:
                chosen = pack[int(params["card"])]
            except (IndexError, TypeError, ValueError):
                return None
            key = chosen.get("key", "")
            if key == "c_ankh" and full:
                return ANKH_FULL_PACK
            sell_in_pack = bool((G.get("luna") or {}).get("sell_in_pack"))
            if (
                (chosen.get("set") == "JOKER" and not sell_in_pack)
                or key in ("c_judgement", "c_soul", "c_wraith")
            ) and full:
                return "Your joker slots are full: this card would be wasted. Skip the pack or pick another card."
            if key == "c_death" and len(params.get("targets") or []) != 2:
                return "Death needs exactly 2 targets: [junk card, card to copy]."
            if (
                chosen.get("set") not in ("JOKER", "TAROT", "PLANET", "SPECTRAL")
                and _norm(chosen)["seal"] == "BLUE"
                and blue_seal_count(G) >= 1
                and not owns_hologram(G)
            ):
                return (
                    "You already own a Blue Seal card: pick a different card or skip."
                )
    if method == "reroll_boss":
        if G.get("state") == "SHOP":  # C4: Luna asks; the harness runs it at blind select
            if (luna := G.get("luna") or {}).get("boss_reroll_request"):
                return "Boss reroll refused: you already asked for one; it runs at the next blind select."
            if why := luna_reroll_refusal(G):
                return f"Boss reroll refused: {why}. Buy something else or call next_round."
            return None
        if G.get("state") != "BLIND_SELECT":
            return "reroll_boss only works in the shop (request) or on the blind select screen."
        if not boss_reroll_available(G):
            return (
                "Boss reroll refused: it needs Director's Cut (once per ante) or "
                f"Retcon and ${BOSS_REROLL_COST}. Select the blind instead."
            )
    if method == "use" and mark_active(G) and isinstance(cards, list):
        # The Mark: a Tarot on a face-down card changes it but keeps it face
        # down, so the harness can no longer tell what it is (review r9 opus R9-1)
        hand = _area_cards(G, "hand")
        hidden = {i for i, c in enumerate(hand) if (c.get("state") or {}).get("hidden")}
        picked = set()
        for i in cards:  # each target on its own: a null or junk entry must not hide the others (review r10 codex R10-1)
            try:
                picked.add(int(i))
            except (TypeError, ValueError, OverflowError):
                continue
        if picked & hidden:
            return ("The Mark: you cannot see face-down cards, so do not target them. "
                    "Target face-up cards, or keep the card for later.")
    if method == "use":
        cons = _area_cards(G, "consumables")
        try:
            chosen = cons[int(params.get("consumable", -1))]
        except (IndexError, TypeError, ValueError):
            return None
        key = chosen.get("key", "")
        if key == "c_ankh" and full:
            return ANKH_FULL_USE
        if key in ("c_judgement", "c_soul", "c_wraith") and full:
            return "Your joker slots are full: sell a joker before using this card."
        if key == "c_death" and len(params.get("cards") or []) != 2:
            return "Death needs exactly 2 cards: [junk card, card to copy]."
    return None


################################################################################
# Action outcomes (memory)
################################################################################


def _hand_keys(G: dict[str, Any]) -> list[str]:
    return [str(c.get("key", "")) for c in _area_cards(G, "hand")]


def _label_at(G: dict[str, Any], area: str, index: Any) -> str:
    cards = _area_cards(G, area)
    try:
        return str(cards[int(index)].get("label") or cards[int(index)].get("key"))
    except (IndexError, TypeError, ValueError):
        return "?"


def summarize_outcome(
    method: str,
    params: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
) -> str:
    """One-line, human readable result of an action for the memory log."""
    try:
        if method == "play":
            hands_b = before.get("hands") or {}
            hands_a = after.get("hands") or {}
            htype = next(
                (
                    n
                    for n, h in hands_a.items()
                    if int((h or {}).get("played", 0))
                    > int((hands_b.get(n) or {}).get("played", 0))
                ),
                "hand",
            )
            cur = current_blind(before) or {}
            target = int(cur.get("score") or 0)
            chips_b = int((before.get("round") or {}).get("chips") or 0)
            chips_a = int((after.get("round") or {}).get("chips") or 0)
            state = after.get("state", "")
            if state == "GAME_OVER":
                return f"played {htype}: not enough, GAME OVER"
            if state in ("ROUND_EVAL", "SHOP", "BLIND_SELECT") or (
                target and chips_a >= target
            ):
                gained = chips_a - chips_b if chips_a >= chips_b else None
                gained_txt = f" for {gained:,}" if gained else ""
                return f"played {htype}{gained_txt}: blind beaten"
            hands_left = int((after.get("round") or {}).get("hands_left") or 0)
            return (
                f"played {htype} for {chips_a - chips_b:,} "
                f"(now {chips_a:,}/{target:,}, {hands_left} hands left)"
            )
        if method == "discard":
            # C3: a face-down card is never named (BalatroBot sends its real key)
            def ident(c: dict[str, Any]) -> Any:
                return c.get("id") if c.get("id") is not None else c.get("key")

            def name(c: dict[str, Any]) -> str:
                return "face-down card" if (c.get("state") or {}).get("hidden") else str(c.get("key", ""))

            hb, ha = _area_cards(before, "hand"), _area_cards(after, "hand")
            ib, ia = {ident(c) for c in hb}, {ident(c) for c in ha}
            gone = [name(c) for c in hb if ident(c) not in ia]
            new = [name(c) for c in ha if ident(c) not in ib]
            return f"discarded {', '.join(gone) or '-'}; drew {', '.join(new) or '-'}"
        if method == "buy":
            money = after.get("money", "?")
            if "card" in params:
                item = _label_at(before, "shop", params["card"])
            elif "voucher" in params:
                item = _label_at(before, "vouchers", params["voucher"])
            elif "pack" in params:
                item = _label_at(before, "packs", params["pack"])
            else:
                item = "item"
            return f"bought {item} (${money} left)"
        if method == "sell":
            if "joker" in params:
                item = _label_at(before, "jokers", params["joker"])
            else:
                item = _label_at(before, "consumables", params.get("consumable"))
            return f"sold {item} (${after.get('money', '?')} now)"
        if method == "use":
            item = _label_at(before, "consumables", params.get("consumable"))
            return f"used {item}"
        if method == "pack":
            if params.get("skip"):
                return "skipped the pack"
            return f"took {_label_at(before, 'pack', params.get('card'))} from pack"
        if method == "reroll":
            return f"rerolled shop (${after.get('money', '?')} left)"
        if method == "next_round":
            return "left the shop"
        if method == "rearrange":
            return "rearranged"
    except Exception:  # never let memory formatting break a run
        pass
    return "ok"


def round_record(
    last_hand_state: dict[str, Any], eval_state: dict[str, Any]
) -> dict[str, Any]:
    """Summarise a finished blind (called at ROUND_EVAL)."""
    cur = current_blind(last_hand_state) or {}
    rnd = eval_state.get("round") or last_hand_state.get("round") or {}
    return {
        "ante": int(last_hand_state.get("ante_num") or 0),
        "round": int(last_hand_state.get("round_num") or 0),
        "blind": cur.get("name") or str(cur.get("kind", "blind")).title(),
        "target": int(cur.get("score") or 0),
        "scored": int(rnd.get("chips") or 0),
        "hands_left": int(rnd.get("hands_left") or 0),
        "discards_left": int(rnd.get("discards_left") or 0),
        "main_hand": main_hand(eval_state) or main_hand(last_hand_state),
    }


LESSONS_FILE = Path(__file__).parent / "strategies" / "mastery" / "lessons.json"


def past_lessons(G: dict[str, Any], status: str | None, path: str | None = None) -> list[str]:
    """E4: prompt lines for at most 2 matching trial/kept lessons."""
    from . import lessons

    found = lessons.match(G, status, lessons.load(Path(path) if path else LESSONS_FILE))
    return [lessons.line(x) for x in found]


TEMPLATE_GLOBALS = {
    "suit_pays": suit_pays,
    "analyze_hand": analyze_hand,
    "blind_progress": blind_progress,
    "shop_context": shop_context,
    "deck_summary": deck_summary,
    "hands_table": hands_table,
    "main_hand": main_hand,
    "money_floor": money_floor,
    "interest": interest,
    "consumable_targets": consumable_targets,
    "current_blind": current_blind,
    "next_blind": next_blind,
    "play_advice": play_advice,
    "main_hand_plan": main_hand_plan,
    "run_status": run_status,
    "shop_impact": shop_impact,
    "boss_impact": boss_impact,
    "suggest_targets": suggest_targets,
    "joker_order": joker_order,
    "grows_xmult": grows_xmult,
    "past_lessons": past_lessons,
    "first_shop_tight": first_shop_tight,
    "play_estimate": play_estimate,
    "clash_note": clash_note,
    "joker_tag": knowledge.joker_tag,
    "consumable_tag": knowledge.consumable_tag,
    "voucher_tag": knowledge.voucher_tag,
    "boss_counter": knowledge.boss_counter,
    "boss_fact": knowledge.boss_fact,
    "ANTE_BASE": ANTE_BASE,
}
TEMPLATE_FILTERS = {
    "card_name": card_name,
    "card_chips": card_chips,
    "fmt_num": fmt_num,
    "blue_seal_count": blue_seal_count,
    "pct": pct,
}

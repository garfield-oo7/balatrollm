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

import re
from collections import Counter
from collections.abc import Iterable
from itertools import combinations
from math import comb
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
CURRENTLY = re.compile(
    r"Currently\s*([+X×x])\s*\$?(\d+(?:\.\d+)?)\s*(Mult|Chips)", re.IGNORECASE
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
    ranked = [(i, c) for i, c in enumerate(cards) if not c["stone"]]
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
    if boss == "The Flint":
        chips, mult = max(chips // 2, 0), max(mult // 2, 1)
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
        played = [n for n, h in hands.items() if (h or {}).get("played_this_round", 0)]
        if played and htype not in played:
            return f"The Mouth: only {played[0]} is allowed this round, scores 0"
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
    if key == "j_misprint":
        return 0, 0, 1  # random 0..23: floor estimate counts 0
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
        ok = all(c["suit"] in ("S", "C") or c["enh"] == "WILD" for c in held)
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


def estimate_play(
    G: dict[str, Any],
    played_raw: list[dict[str, Any]],
    held_raw: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estimate the score of playing ``played_raw`` while holding ``held_raw``.

    Approximates Balatro's scoring order: hand base -> scoring cards left to
    right (with per-card jokers and retriggers) -> held cards -> jokers left to
    right. This is a FLOOR estimate: random effects (Misprint, Lucky cards,
    Bloodstone) count as zero and unknown jokers are skipped and listed in
    ``unknown``.
    """
    keys = _joker_keys(G)
    keyset = set(keys)
    boss = _active_boss(G)
    played = [_norm(c) for c in played_raw]
    held = [_norm(c) for c in held_raw]
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
    first_face_done = False

    def is_face(c: dict[str, Any]) -> bool:
        return not c["stone"] and (pareidolia or (c["rank"] in FACE_RANKS))

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
            chips += 50 if c["stone"] else CHIP_VALUE.get(c["rank"] or "", 0)
            if c["enh"] == "BONUS":
                chips += 30
            elif c["enh"] == "MULT":
                mult += 4
            # LUCKY (1 in 5 for +20 Mult) counts 0 in the floor estimate
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
                # Bloodstone (1 in 2 for x1.5) counts x1 in the floor estimate
                elif k == "j_triboulet" and c["rank"] in ("K", "Q"):
                    mult *= 2
                elif k == "j_photograph" and is_face(c) and not first_face_done:
                    mult *= 2
            if is_face(c):
                first_face_done = True

    # Held-in-hand effects
    mime = keys.count("j_mime")
    for c in held:
        if c["debuff"] or c["hidden"]:
            continue
        triggers = 1 + mime + (1 if c["seal"] == "RED" else 0)
        for _ in range(triggers):
            if c["enh"] == "STEEL":
                mult *= 1.5
            if c["rank"] == "K":
                for _k in range(keys.count("j_baron")):
                    mult *= 1.5
            if c["rank"] == "Q":
                mult += 13 * keys.count("j_shoot_the_moon")
    if "j_raised_fist" in keyset:
        ranks = [c for c in held if c["rank"] and not c["debuff"] and not c["hidden"]]
        if ranks:
            low = min(ranks, key=lambda c: RANK_VALUE[c["rank"]])
            mult += 2 * CHIP_VALUE[low["rank"]]

    # Independent joker effects, left to right (with Blueprint/Brainstorm)
    jokers = [
        j for j in _area_cards(G, "jokers") if not (j.get("state") or {}).get("debuff")
    ]
    ctx = {
        "G": G,
        "htype": htype,
        "n_played": len(played),
        "held": [c for c in held if not c["hidden"]],
        "scored": scored_cards,
        "keys": keys,
    }
    unknown: list[str] = []
    for idx, j in enumerate(jokers):
        edition = (j.get("modifier") or {}).get("edition")
        if edition == "FOIL":
            chips += 50
        elif edition == "HOLO":
            mult += 10
        key = j.get("key", "")
        target = j
        if key == "j_blueprint":
            target = jokers[idx + 1] if idx + 1 < len(jokers) else {}
        elif key == "j_brainstorm":
            target = jokers[0] if jokers and jokers[0] is not j else {}
        tkey = target.get("key", "")
        if target and tkey not in ("j_blueprint", "j_brainstorm"):
            if tkey in PER_CARD_JOKERS or tkey in STRUCTURAL_JOKERS:
                if target is not j:
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


def _discard_choice(
    hand: list[dict[str, Any]], keep: Iterable[int], limit: int
) -> list[int]:
    """Pick up to ``limit`` cards to discard, lowest value first, never ``keep``."""
    keep = set(keep)
    candidates = [
        i
        for i, c in enumerate(hand)
        if i not in keep and c["enh"] not in ("STEEL", "GOLD") and c["seal"] != "BLUE"
    ]
    candidates.sort(
        key=lambda i: (
            hand[i]["enh"] is not None or hand[i]["ed"] is not None,
            CHIP_VALUE.get(hand[i]["rank"] or "", 0),
        )
    )
    return sorted(candidates[:limit])


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


def analyze_hand(G: dict[str, Any], top: int = 6) -> dict[str, Any]:
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
    for k in range(1, min(limit, len(visible)) + 1):
        for idx in combinations(visible, k):
            played = [hand_raw[i] for i in idx]
            held = [hand_raw[i] for i in range(len(hand_raw)) if i not in idx]
            est = estimate_play(G, played, held)
            if "j_splash" not in keyset and len(est["scoring"]) != k:
                continue  # keep minimal plays: every selected card scores
            prev = best.get(est["hand"])
            if prev is None or est["score"] > prev["score"]:
                best[est["hand"]] = {"cards": list(idx), **est}
            if blue and not blue & set(idx):
                prev = best_no_blue.get(est["hand"])
                if prev is None or est["score"] > prev["score"]:
                    best_no_blue[est["hand"]] = {"cards": list(idx), **est}
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
            p = _hypergeom_at_least(deck_size, outs, n, need_flush - have_total)
            draws.append(
                {
                    "kind": "Flush",
                    "suit": suit,
                    "text": f"Flush draw in {SUIT_NAME[suit]}: {have_total}/{need_flush} in hand, "
                    f"{outs} {SUIT_NAME[suit]} left in deck",
                    "keep": keep,
                    "discard": _discard_choice(hand, keep, n),
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
            p = _hypergeom_at_least(deck_size, outs, n, 1)
            need_txt = " or ".join(RANK_NAME.get(r, r) for r in sorted(missing))
            draws.append(
                {
                    "kind": "Straight",
                    "missing": min(missing, key=lambda r: CHIP_VALUE[r]),
                    "text": f"Straight draw: need a {need_txt} ({outs} left in deck)",
                    "keep": sorted(keep),
                    "discard": _discard_choice(hand, keep, n),
                    "chance": p,
                }
            )
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
OPEN_ANTES = 1  # Ante 1: chase Flush/Straight draws; from Ante 2 build MAIN_HAND
FLUSH_ENGINES = {"j_tribe", "j_smeared", "j_four_fingers"}
SUIT_SHARE_FOR_FLUSH = 0.5  # deck this concentrated in one suit makes Flush reliable


def _suit_share(G: dict[str, Any], suit: str) -> float:
    cards = [_norm(c) for a in ("hand", "cards") for c in _area_cards(G, a)]
    suited = [c for c in cards if c["suit"]]
    if not suited:
        return 0.0
    return sum(1 for c in suited if c["suit"] == suit) / len(suited)


def main_hand_plan(G: dict[str, Any]) -> dict[str, Any]:
    """Deterministic MAIN_HAND.

    Default is a plain Pair (owner decision): an unmodified 8-card hand holds
    a Pair ~89% of the time with no discard and ~99% with one, versus ~44% for
    a Flush with one discard. Two Pair only with a Two Pair joker. The
    hand never dies to suit bosses, and it grows into Full House. Flush is
    chosen only when the run has made it consistent (a Flush engine joker, a
    flush-joker core with no pair jokers, or a deck half one suit). In the
    OPEN antes, Flush/Straight are still taken when dealt (``open``).
    """
    infos = _owned_joker_infos(G)
    keys = set(_joker_keys(G))
    ante = int(G.get("ante_num") or 1)
    pair_jokers = sum(1 for i in infos if i["family"] == "pair")
    flush_jokers = sum(1 for i in infos if i["family"] == "flush")
    suit = main_suit(G)
    if keys & FLUSH_ENGINES:
        hand, reason = "Flush", "you own a Flush engine joker, so Flush is consistent"
    elif flush_jokers >= 2 and pair_jokers == 0:
        hand, reason = "Flush", "your jokers are flush jokers and none are pair jokers"
    elif _suit_share(G, suit) >= SUIT_SHARE_FOR_FLUSH:
        hand, reason = "Flush", "half your deck is one suit"
    elif "j_half" in keys:
        hand, reason = "Pair", "Half Joker needs plays of 3 or fewer cards"
    elif "j_trio" in keys or {"j_zany", "j_wily"} <= keys:
        hand, reason = "Three of a Kind", "your jokers pay for Three of a Kind"
    elif keys & TWO_PAIR_JOKERS:
        hand, reason = "Two Pair", "you own a Two Pair joker (Spare Trousers/Mad/Clever)"
    else:
        hand, reason = (
            "Pair",
            "most consistent hand (a Pair is in ~89% of hands, ~99% after 1 discard)",
        )
    is_open = ante <= OPEN_ANTES and hand != "Flush"
    if is_open:
        reason += "; Ante 1: chase Flush/Straight draws first"
    return {
        "hand": hand,
        "family": knowledge.HAND_FAMILY.get(hand, "pair"),
        "suit": suit if hand == "Flush" else None,
        "reason": reason,
        "open": is_open,
        # draws worth discarding toward (shown to the model and used for advice)
        "draw_kinds": {"Flush", "Straight"} if is_open else {hand},
    }


def _pad_allowed(G: dict[str, Any]) -> bool:
    keys = set(_joker_keys(G))
    return "j_half" not in keys and _active_boss(G) != "The Tooth"


def _filler(
    hand: list[dict[str, Any]],
    play: list[int],
    plan: dict[str, Any],
    count: int,
) -> list[int]:
    """Lowest-value cards outside ``play`` to add as filler (never MAIN suit cards)."""
    suit = plan.get("suit")
    pool = [
        i
        for i, c in enumerate(hand)
        if i not in play
        and not c["hidden"]
        and c["enh"] not in ("STEEL", "GOLD")
        and c["seal"] != "BLUE"
        and not (suit and (c["suit"] == suit or c["enh"] == "WILD"))
    ]
    pool.sort(key=lambda i: CHIP_VALUE.get(hand[i]["rank"] or "", 0))
    return pool[:count]


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
    keep |= protect
    keep |= {i for i, c in enumerate(hand) if c["stone"] and plan["hand"] != "Flush"}
    return _discard_choice(hand, keep, limit)


def play_advice(G: dict[str, Any], top: int = 5) -> dict[str, Any]:
    """Everything the PLAY phase needs: plays with WINS flags, discard, suggestion."""
    plan = main_hand_plan(G)
    analysis_ = analyze_hand(G, top=top)
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
        if alt and alt["score"] >= margin * remaining and not alt["blocked"]:
            p = alt
        wins = p["score"] >= margin * remaining and not p["blocked"]
        plays.append({**p, "wins": wins, "reaches_pace": p["score"] >= per_hand})
    winners = [p for p in plays if p["wins"]]
    protect = set(winners[0]["cards"]) if winners else set()
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
    for d in analysis_["draws"]:
        if d["kind"] not in plan["draw_kinds"]:
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
        action = {"tool": "play", "cards": best["cards"], "why": why}
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
    elif discards > 0 and discard and not any(p["reaches_pace"] for p in plays):
        action = {
            "tool": "discard",
            "cards": discard,
            "why": "no play reaches PER_HAND; dig toward MAIN_HAND",
        }
    elif plays:
        best = plays[0]
        cards = list(best["cards"])
        need = 0
        if boss == "The Psychic":
            need = 5 - len(cards)
        elif _pad_allowed(G) and len(cards) < 5:
            need = 5 - len(cards)
        if need > 0:
            cards = sorted(cards + _filler(hand, cards, plan, need))
        action = {"tool": "play", "cards": cards, "why": f"best play ({best['hand']})"}
    else:
        action = {"tool": "discard", "cards": discard, "why": "no visible play"}
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
        "hand_suits": analysis_["hand_suits"],
        "deck_size": analysis_["deck_size"],
        "deck_suits": analysis_["deck_suits"],
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
    return {
        "name": name,
        "effect": effect,
        "score": boss.get("score") or 0,
        "counter": knowledge.boss_counter(name),
        "impact": impact,
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
    filler = sum(1 for i in infos if i["category"] in ("ECON", "CHIPS", "TRAP"))
    want_jokers = {1: 2, 2: 4}.get(ante, limit)
    want_xmult = 0 if ante <= 3 else (1 if ante <= 5 else 2)
    want_level = max(1, ante - 1) if ante >= 3 else 1
    goals = [
        {
            "text": f"{want_jokers} jokers (have {count})",
            "done": count >= want_jokers,
            "action": "fill empty joker slots with scoring jokers",
        },
    ]
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
                "action": "sell an [ECON]/[CHIPS] joker to make room for [XMULT]/[SCALE]",
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
    xmult = sum(
        1
        for i in infos
        if i["category"] == "XMULT"
        and i["key"] not in ("j_loyalty_card", "j_stencil", "j_flower_pot")
        and knowledge.joker_fit(i["name"], plan["hand"]) != "OFF-PLAN"
    )
    floor = money_floor(G)

    # Power check: hands needed for the next blind at the recent scoring pace.
    scores = _play_scores(history)[-3:]
    nxt = next_blind(G) or current_blind(G) or {}
    nxt_target = int(nxt.get("score") or 0)
    hands_needed = None
    status = "UNKNOWN"
    if scores and nxt_target:
        avg = sum(scores) / len(scores)
        hands_needed = -(-nxt_target // max(int(avg), 1))
        status = "ON TRACK" if hands_needed <= 3 else "TOO WEAK"
    elif rounds:
        status = "ON TRACK" if int(rounds[-1].get("hands_left", 0)) >= 1 else "TOO WEAK"
    effective_floor = 0 if status == "TOO WEAK" else floor

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
        else "level MAIN_HAND with planets and upgrade your weakest joker"
    )
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
        "recent_scores": scores,
        "next_target": nxt_target,
        "milestone": milestone,
        "goals": goals,
        "econ_owned": econ,
        "econ_ok": econ_ok,
        "blue_seals": blue_seal_count(G),
        "hologram": owns_hologram(G),
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
    if "j_blueprint" in keys:
        bp = keys.index("j_blueprint")
        order.remove(bp)
        xs = [i for i in order if weight(jokers[i]) >= 5]
        target = xs[-1] if xs else order[-1]
        order.insert(order.index(target), bp)
    if "j_brainstorm" in keys:
        bs = keys.index("j_brainstorm")
        xs = [i for i in order if i != bs and weight(jokers[i]) >= 5]
        if xs:
            order.remove(xs[-1])
            order.insert(0, xs[-1])
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
    Flush: the low, middle and high five cards of MAIN_SUIT. Two Pair / Full
    House: the single typical play.
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


def _with_jokers(G: dict[str, Any], jokers: list[dict[str, Any]]) -> dict[str, Any]:
    area = dict(G.get("jokers") or {})
    area["cards"] = jokers
    area["count"] = len(jokers)
    G2 = {**G, "jokers": area}
    order = joker_order(G2)
    if order:
        area["cards"] = [jokers[i] for i in order]
    return G2


def shop_impact(G: dict[str, Any]) -> dict[str, Any]:
    """Score change per hand of an average MAIN_HAND play for each shop/pack
    joker and MAIN_HAND planet, and what each owned joker contributes.

    The average runs over every MAIN_HAND play your deck can make (see
    typical_plays), so face-card and suit jokers count as often as they fire.
    """
    plan = main_hand_plan(G)
    play = typical_play(G, plan)
    out: dict[str, Any] = {
        "hand": plan["hand"],
        "cards": [card_name(c) for c in play],
        "plays": 0,
        "score": 0,
        "shop": {},
        "pack": {},
        "owned": {},
        "weakest": None,
    }
    owned = _area_cards(G, "jokers")
    G_owned = _with_jokers(G, owned)
    plays = [
        p
        for p in typical_plays(G, plan)
        if estimate_play(G_owned, p, [])["hand"] == plan["hand"]
    ]
    if not plays:
        return out

    def average(G2: dict[str, Any]) -> tuple[float, set[str]]:
        total, unknown = 0.0, set()
        for p in plays:
            est = estimate_play(G2, p, [])
            total += est["score"]
            unknown |= set(est["unknown"])
        return total / len(plays), unknown

    base_score, base_unknown = average(G_owned)
    score = int(base_score)
    out["score"] = score
    out["plays"] = len(plays)

    def describe(new_score: float, unknown: bool) -> str:
        if unknown:
            return "effect not computed"
        delta = int(new_score) - score
        pct_txt = f" ({round(delta * 100 / score)}%)" if score else ""
        return f"{'+' if delta >= 0 else ''}{fmt_num(delta)} per hand{pct_txt}"

    def item_delta(card: dict[str, Any]) -> str | None:
        if card.get("set") == "JOKER":
            new_score, unknown = average(_with_jokers(G, [*owned, card]))
            label = str(card.get("label") or card.get("key"))
            return describe(new_score, label in unknown)
        if card.get("set") == "PLANET":
            hand = knowledge.planet_hand(card.get("label"))
            if hand != plan["hand"]:
                return None
            levels = dict(G.get("hands") or {})
            cur = dict(levels.get(hand) or {})
            dc, dm = LEVEL_UP.get(hand, (0, 0))
            cur["chips"] = float(cur.get("chips", 0)) + dc
            cur["mult"] = float(cur.get("mult", 0)) + dm
            levels[hand] = cur
            new_score, _ = average({**G_owned, "hands": levels})
            return describe(new_score, False)
        return None

    for area in ("shop", "pack"):
        for i, card in enumerate(_area_cards(G, area)):
            d = item_delta(card)
            if d:
                out[area][i] = d
    contrib = {}
    for i, j in enumerate(owned):
        info = knowledge.joker_info(j.get("label")) or {}
        rest = [x for k, x in enumerate(owned) if k != i]
        label = str(j.get("label") or j.get("key"))
        if label in base_unknown:
            out["owned"][i] = "effect not computed"
            continue
        rest_score, _ = average(_with_jokers(G, rest))
        gain = score - int(rest_score)
        contrib[i] = (gain, info.get("category"))
        out["owned"][i] = f"adds {fmt_num(gain)} per hand"
    # weakest = least score among jokers that do not grow or pay money
    ante = int(G.get("ante_num") or 1)
    protected = {"SCALE", "XMULT"} | ({"ECON"} if ante <= 4 else set())
    candidates = [(gain, i) for i, (gain, cat) in contrib.items() if cat not in protected]
    if candidates:
        gain, i = min(candidates)
        out["weakest"] = {
            "index": i,
            "label": owned[i].get("label"),
            "gain": gain,
        }
    return out


def _sell_veto(G: dict[str, Any], joker: dict[str, Any], full: bool) -> str | None:
    """Refuse selling a joker unless it hurts you or makes room you can use.

    A sale is fine for a [TRAP] / tier T joker, to make room for Judgement /
    The Soul / Wraith, or when slots are full and a shop joker or Buffoon
    pack is affordable with the sale money (an [XMULT] joker may use all of it).
    """
    label = str(joker.get("label") or joker.get("key") or "this joker")
    info = knowledge.joker_info(label) or {}
    ante = int(G.get("ante_num") or 1)
    tier = info.get("early") if ante <= 3 else info.get("late")
    if info.get("category") == "TRAP" or tier == "T":
        return None
    makes_joker = ("c_judgement", "c_soul", "c_wraith")
    if any(c.get("key") in makes_joker for c in _area_cards(G, "consumables")):
        return None
    if not full:
        return (
            f"Keep {label}: your joker slots are not full, so selling only loses "
            "a joker. Buy something else, use a card, or call next_round."
        )
    money = int(G.get("money") or 0) + int((joker.get("cost") or {}).get("sell") or 0)

    def price(c: dict[str, Any]) -> int:
        return int((c.get("cost") or {}).get("buy") or 0)

    room_for = [
        c for c in _area_cards(G, "shop") if c.get("set") == "JOKER" and price(c) <= money
    ] + [
        p
        for p in _area_cards(G, "packs")
        if "buffoon" in str(p.get("label", "")).lower() and price(p) <= money
    ]
    if not room_for:
        return (
            f"Keep {label}: even with its sell money (${money}) you cannot afford "
            "a joker or Buffoon pack in this shop. Buy something else, use a "
            "card, or call next_round."
        )
    return None


def validate_action(
    G: dict[str, Any], method: str, params: dict[str, Any]
) -> str | None:
    """Return an error message for illegal or strictly bad actions, else None."""
    jokers = G.get("jokers") or {}
    full = int(jokers.get("count", 0)) >= int(jokers.get("limit", 5))
    cards = params.get("cards")
    if method in ("play", "discard") and isinstance(cards, list):
        if not cards:
            return "Select at least 1 card."
        limit = int((G.get("hand") or {}).get("highlighted_limit", 5) or 5)
        if len(cards) > limit:
            return f"You selected {len(cards)} cards; the maximum is {limit}."
        if len(set(cards)) != len(cards):
            return "Each card index may appear only once."
        if method == "discard":
            advice = play_advice(G)
            winners = [p for p in advice["plays"] if p["wins"]]
            if winners and set(cards) & set(winners[0]["cards"]):
                return (
                    f"Discard refused: cards {winners[0]['cards']} already make a "
                    f"{winners[0]['hand']} that WINS the blind. Play it instead."
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
        if "buffoon" in label.lower():
            return (
                "Buffoon Pack refused: your joker slots are full (sell a joker first)."
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
            if (
                chosen.get("set") == "JOKER"
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
    if method == "use":
        cons = _area_cards(G, "consumables")
        try:
            chosen = cons[int(params.get("consumable", -1))]
        except (IndexError, TypeError, ValueError):
            return None
        key = chosen.get("key", "")
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
            gone = [k for k in _hand_keys(before) if k not in _hand_keys(after)]
            new = [k for k in _hand_keys(after) if k not in _hand_keys(before)]
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


TEMPLATE_GLOBALS = {
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
    "joker_tag": knowledge.joker_tag,
    "consumable_tag": knowledge.consumable_tag,
    "voucher_tag": knowledge.voucher_tag,
    "boss_counter": knowledge.boss_counter,
    "ANTE_BASE": ANTE_BASE,
}
TEMPLATE_FILTERS = {
    "card_name": card_name,
    "card_chips": card_chips,
    "fmt_num": fmt_num,
    "blue_seal_count": blue_seal_count,
    "pct": pct,
}

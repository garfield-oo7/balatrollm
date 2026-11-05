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
MONEY_FLOOR = {1: 0, 2: 5, 3: 15, 4: 25, 5: 25, 6: 25, 7: 10, 8: 0}

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
        return 0, 11.5, 1  # random 0..23, use the average
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
    right. Probabilistic effects use expected values. Unknown jokers are listed
    in ``unknown`` so the caller knows the estimate is a floor.
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
            elif c["enh"] == "LUCKY":
                mult += 4  # 1 in 5 for +20
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
                elif k == "j_bloodstone" and suit_match(c, "H"):
                    mult *= 1.25  # 1 in 2 for x1.5
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
                    "text": f"Straight draw: need a {need_txt} ({outs} left in deck)",
                    "keep": sorted(keep),
                    "discard": _discard_choice(hand, keep, n),
                    "chance": p,
                }
            )
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
    "ANTE_BASE": ANTE_BASE,
}
TEMPLATE_FILTERS = {
    "card_name": card_name,
    "card_chips": card_chips,
    "fmt_num": fmt_num,
    "pct": pct,
}

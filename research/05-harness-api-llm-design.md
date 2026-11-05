# 05 — Harness, BalatroBot API & LLM scaffolding design

Scope: what information/scaffolding the LLM receives and what harness changes (code + templates) would most
improve a Haiku-class model. Strategy *content* is out of scope except where it is a harness bug.

Sources read: `src/balatrollm/{bot,strategy,config,llm}.py`, all three strategy folders, BalatroBot source
(`coder/balatrobot`, `src/lua/utils/gamestate.lua`, `types.lua`, `endpoints/*.lua`, `docs/api.md`; gamestate.lua is
**byte-identical between tag v1.4.1 and HEAD v1.5.2**), a real BalatroLLM run fixture from `coder/balatrobench`
(`tests/balatrobench/fixtures/runs/v1.0.0/default/openai/gpt-oss-120b/...`: rendered prompts + responses), and prior-art
bots (JackPotts, Ballad). A working prototype of the hand analyser lives at
`/tmp/claude-0/-home-user-balatrollm/fb4dc26f-4735-5152-a338-15bd399d24e1/scratchpad/proto/analysis.py` (tested; condensed in §5.1).

---

## 0. TL;DR

1. **The remaining draw pile IS exposed**: `G.cards` = `extract_area(G.deck)` (gamestate.lua:787-789). In SHOP it is the
   whole deck; in SELECTING_HAND it is the undrawn pile. **No template uses it.** The discard pile is not exposed.
   `G.cards.cards` is in real draw order (top = last element), so the harness must show **aggregate counts only**
   (that is what the in-game deck viewer shows; exposing order would be cheating).
2. **Value formats**: rank `"2".."9","T","J","Q","K","A"`; suit `"H","D","C","S"`; card key `"<suit>_<rank>"` e.g.
   `"H_A"`, `"D_T"`. Modifiers are UPPERCASE: enhancement `BONUS|MULT|WILD|GLASS|STEEL|STONE|GOLD|LUCKY`,
   edition `FOIL|HOLO|POLYCHROME|NEGATIVE`, seal `RED|BLUE|GOLD|PURPLE`. Stone cards have no `rank`/`suit` keys.
   Current render is `A of C (C_A)` / `T of S` — opaque for a small model.
3. Joker scaling values **are** available, but only as text in `value.effect` (e.g. Hologram:
   `"... (Currently X1 Mult)"`). No numeric ability fields, no rarity, no blind $ reward, no `pack_choices`,
   no owned tags, no discard pile, no score preview.
4. Biggest harness gaps for a small model, in order: (a) no pre-computed hand options / score estimates / "need X per
   hand"; (b) `reasoning` is generated *after* `cards` (schema order) so it is post-hoc; (c) memory has no outcomes
   (score of each play, round results) and renders `entry.reasoning` which never exists; (d) a ~10.5k-token static
   strategy (42 KB) with no phase focus, plus ~2.5k chars of 12 verbose poker hands in random order each call;
   (e) several template fields that don't exist (pack modifiers, rarity, targets, voucher descriptions).

---

## 1. BalatroBot gamestate schema (v1.4.1 == v1.5.2)

Top level (`gamestate.get_gamestate`, gamestate.lua:720-815). Lua `pairs()` → **JSON object key order is arbitrary**
(observed: `hands` rendered starting with "Straight").

| Path | Type / values | Notes |
|---|---|---|
| `state` | `MENU, BLIND_SELECT, SELECTING_HAND, HAND_PLAYED, DRAW_TO_HAND, ROUND_EVAL, SHOP, SMODS_BOOSTER_OPENED, GAME_OVER, ...` | name of `G.STATE` |
| `round_num` | int | `G.GAME.round` (1..24 for a win at Ante 8) |
| `ante_num` | int | `G.GAME.round_resets.ante` |
| `money` | int | `G.GAME.dollars` |
| `won` | bool | |
| `deck` / `stake` / `seed` | `"RED"` / `"WHITE"` / `"AAAAAAA"` | |
| `used_vouchers` | `{voucher_key: description}` | description comes from `G.GAME.used_vouchers[k].description`; vanilla stores `true` there → **effect is always `""`** (keys like `v_overstock_norm`) |
| `hands[<name>]` | `{order, level, chips, mult, played, played_this_round, example}` | names: `High Card, Pair, Two Pair, Three of a Kind, Straight, Flush, Full House, Four of a Kind, Straight Flush, Five of a Kind, Flush House, Flush Five`; `chips/mult` are **current level values**; `order` 1 = Flush Five … 12 = High Card; `example` = `[[card_key, is_scored], ...]` |
| `round` | `{hands_left, hands_played, discards_left, discards_used, reroll_cost, chips}` | `chips` = score so far this blind (`G.GAME.chips`); `reroll_cost` current |
| `blinds.{small,big,boss}` | `{type: SMALL/BIG/BOSS, status: SELECT/CURRENT/UPCOMING/DEFEATED/SKIPPED, name, effect, score, tag_name, tag_effect}` | Present in **every** state incl. SHOP. Boss `name/effect/score` for the current ante are known as soon as the ante starts (so during the shop before the boss). Boss `effect` is raw localization text joined by spaces — blinds with variables (The Ox `#1#`, The Wheel `#1# in 7`) likely show unfilled `#1#`. Tags only for small/big. **No `$` reward field.** |
| `jokers` / `consumables` | Area | always present |
| `cards` | Area | **remaining deck** (`G.deck`) |
| `hand` | Area (+`highlighted_limit`, normally 5) | `count` 0 outside rounds; filled in Arcana/Spectral pack openings |
| `shop` / `vouchers` / `packs` | Area | `G.shop_jokers` / `G.shop_vouchers` / `G.shop_booster`; present only when those areas exist |
| `pack` | Area | open booster contents (`G.pack_cards`) |

Area = `{count, limit, highlighted_limit?, cards: Card[]}`. `jokers.limit` = slots, `hand.limit` = hand size.

Card (gamestate.lua:326-370):

```
{ id: sort_id, key: "H_A" | "j_hologram" | "c_magician" | "v_grabber" | "p_buffoon_normal_1",
  set: DEFAULT|ENHANCED|JOKER|TAROT|PLANET|SPECTRAL|VOUCHER|BOOSTER|EDITION,
  label: "Hologram" (display name; playing cards "Base Card"-ish, not useful),
  value: { suit?: H|D|C|S, rank?: 2-9|T|J|Q|K|A, effect: "<UI description text with live vars>" },
  modifier: { seal?: RED|BLUE|GOLD|PURPLE, edition?: FOIL|HOLO|POLYCHROME|NEGATIVE,
              enhancement?: BONUS|MULT|WILD|GLASS|STEEL|STONE|GOLD|LUCKY,
              eternal?: true, perishable?: <rounds left>, rental?: true },
  state: { debuff?: true, hidden?: true (facing back), highlight?: true },
  cost: { sell, buy } }
```

Absent keys are omitted (not `null`), so Jinja sees `Undefined` → renders as empty string silently.
Face-down hand cards (The House/Wheel/Mark/Fish) **still carry rank/suit in JSON**; current templates hide them —
keep it that way for fairness, and skip hidden cards in any analyser.

**Not exposed** (would need a BalatroBot change; JackPotts' fork + upstream PR #181 adds some): numeric joker abilities,
joker rarity, blind cash reward, `G.GAME.pack_choices` (Mega packs: pick 2), owned/pending tags, discard pile,
most-played hand (The Ox / To Do List target only via text), Idol/Ancient/Castle targets (only via effect text),
interest cap, score preview for a selection.

### 1.1 JSON-RPC methods used by the bot

Unknown params are **ignored** by the validator (validator.lua only checks declared fields), so the extra
`reasoning` argument is harmless.

| Method | Params | Valid states | Notable errors (`BalatroError` text fed back to LLM) |
|---|---|---|---|
| `play` | `cards: int[]` (0-based, 1..5) | SELECTING_HAND | "You can only play 5 cards", "Invalid card index: N" |
| `discard` | `cards: int[]` | SELECTING_HAND | "No discards left", "You can only discard 5 cards" |
| `rearrange` | exactly one of `hand / jokers / consumables: int[]` (full permutation) | SELECTING_HAND, SHOP, SMODS_BOOSTER_OPENED (hand only in hand/Arcana) | "Must provide exactly N indices" |
| `buy` | exactly one of `card / voucher / pack: int` | SHOP | "Card is not affordable...", "joker slots are full" |
| `sell` | exactly one of `joker / consumable: int` | SELECTING_HAND, SHOP | |
| `use` | `consumable: int`, `cards?: int[]` | SELECTING_HAND, SHOP | "requires card selection", min/max target errors, "cannot be used at this time" |
| `reroll` | – | SHOP | "Not enough dollars to reroll" |
| `next_round` | – | SHOP → BLIND_SELECT | |
| `pack` | `card?: int`, `targets?: int[]`, `skip?: bool` (card XOR skip) | SMODS_BOOSTER_OPENED | "joker slots are full", target range errors; Mega packs stay in SMODS_BOOSTER_OPENED for the 2nd pick |
| `select` / `skip` | – | BLIND_SELECT | skip on Boss → NOT_ALLOWED |
| `cash_out` | – | ROUND_EVAL | |

Target requirements used by `pack`/`use` come from `G.P_CENTERS[key].config.max_highlighted/min_highlighted`
(Aura = exactly 1, Ankh needs a joker) — **not exposed in the gamestate**; must be a static table in the harness.

---

## 2. What the LLM actually sees today (real run, gpt-oss-120b, default strategy)

Per call: `[STRATEGY 42,098 chars (cached), GAMESTATE ~3.7–5.2k chars, MEMORY 0.2–1.3k chars]`,
13.4k input tokens/call average (stats.json). Observations from the rendered prompts:

- Hand shown as `- 0: A of C (`C_A`)` … ranks/suits as single letters; no chip values; no suit/rank tallies.
- 12 poker hands, ~2.4k chars, unsorted, including 3 secret hands with base 120–160 chips that are unplayable
  on a vanilla deck, each with an "Example" line and a "played N times" sentence.
- Pack phase has **no header at all** (no money/ante/round): the `if/elif` at GAMESTATE.md.jinja:3-23 has no
  `SMODS_BOOSTER_OPENED` branch. Buffoon pack showed `Hologram … Rarity: Common` and `Certificate … Rarity: Common`
  (both are Uncommon; the value is the template's hard-coded default).
- Memory line: `**1.** `play({'cards': [4, 5, 6, 7, 2], 'reasoning': '…'})` - ` — Python dict repr, trailing empty
  `- ` because `entry.reasoning` is undefined. No result of the action is recorded.
- First decision of the run: model played a Pair of 6s **plus 3 filler cards "to discard them"** on hand 1 — directly
  following STRATEGY.md.jinja:551's rule of thumb (see I-14). A score/analysis block would have shown the Pair is
  44 points vs 300 needed.

---

## 3. Issue list (file:line)

Paths relative to `src/balatrollm/`. "D" = default strategy file (aggressive/conservative share most lines;
GAMESTATE is identical in default/aggressive, conservative only adds warnings).

### Bugs / wrong data

| # | Where | Issue |
|---|---|---|
| I-1 | `strategies/*/MEMORY.md.jinja:9` vs `bot.py:354` | Template renders `{{ entry.reasoning }}` but bot stores `{"method", "params"}`; reasoning lives in `params["reasoning"]`. Renders a dangling ` - `, and reasoning appears only inside the dict repr. (`tests/unit/test_strategy.py:194-207` tests the template with a top-level `reasoning` key, so tests and bot disagree.) |
| I-2 | D `GAMESTATE.md.jinja:3-23` | No header branch for `SMODS_BOOSTER_OPENED`: pack decisions are made without money, ante, round, joker-slot context (joker count is shown later, OK). |
| I-3 | D `GAMESTATE.md.jinja:218` | `card.value.rarity|default('Common')` — field never exists → every pack joker labelled "Common" (misinformation). |
| I-4 | D `GAMESTATE.md.jinja:222` | `card.value.min_highlighted/max_highlighted` never exist → target count never shown for Arcana/Spectral pack cards. |
| I-5 | D `GAMESTATE.md.jinja:225-227` | Standard-pack cards use `card.value.enhancement/edition/seal`; real path is `card.modifier.*` → Standard packs show **no** enhancements/seals/editions (the only reason to pick them). Also no edition shown for Buffoon-pack jokers (216-218 ignore `modifier.edition`, e.g. Negative/Polychrome). |
| I-6 | D `GAMESTATE.md.jinja:235` | Targeting hand uses `card.value.enhancement` (→ `()`), ignores stone (renders ` of `), seal, edition, hidden. |
| I-7 | D `GAMESTATE.md.jinja:73-80` | `used_vouchers` values are `""` in vanilla → renders `- v_grabber: ` with no effect. |
| I-8 | D `GAMESTATE.md.jinja:87-93` | `G.hands.items()` in arbitrary Lua order; all 12 hands incl. secret ones; ~600 tokens/call. Should `sort(attribute='order')` and filter. |
| I-9 | D `GAMESTATE.md.jinja:240-258, 304-312` + `bot.py:206-208` | BLIND_SELECT template/tools are dead code: bot always `select`s and never calls the LLM there. TOOLS.json `BLIND_SELECT` entries (all strategies) never used; conservative's skip guidance can never apply. |
| I-10 | D `GAMESTATE.md.jinja:260-335` | "Tools available" duplicates TOOLS.json (sent as `tools`) — ~700 tokens/call, and can drift (e.g. `pack.card` described as "omit if skipping" while API rejects card+skip). |
| I-11 | D `GAMESTATE.md.jinja:13-17` | SHOP header omits upcoming blinds (next blind score, **boss name/effect**), interest, joker slots; data is in `G.blinds` already. |
| I-12 | D `GAMESTATE.md.jinja:106` | `{{ rank }} of {{ suit }}` → `T of S`; no chip value; card enhancements rendered as separate bullet lines (verbose). |
| I-13 | D `STRATEGY.md.jinja:496` | "Negative: +1 Joker Slot when scored. This edition is only available to Jokers." Wrong: Negative is passive (+1 slot always), and also appears on consumables (+1 consumable slot). Line 256 is correct, so the prompt contradicts itself. |
| I-14 | D `STRATEGY.md.jinja:551` (+ 542-543) | "If you can score ANY points, play the hand with maximum cards rather than discarding" — harmful for a model that can't count: burns the scarce resource (hands) to "cycle". Example 542-543 says playing 4 cards draws 3. |
| I-15 | D `STRATEGY.md.jinja:124` | "There are 10 hand types (weakest to strongest)" then lists Straight Flush first; 12 hand types exist. |

### Design problems that hurt a small model

| # | Where | Issue |
|---|---|---|
| D-1 | TOOLS.json (all) `play/discard/use/pack` | `properties` order is `cards` then `reasoning`; models emit arguments in schema order, so indices are committed **before** any reasoning (CoT becomes post-hoc rationalisation). Matters most when extended thinking is off. |
| D-2 | `bot.py:217-244` | No computed facts: no "score needed / hands left / per hand", no candidate hands with indices and estimated score, no suit/rank counts, no draw odds, no deck composition. The model must do combinatorics + arithmetic in its head every call. |
| D-3 | `bot.py:354`, `bot.py:226` | History = last 10 successful `{method, params}`; no state, ante/round, outcome (score gained, hand type, money change), no failed attempts, no round summaries, no persistent build/plan. After 10 actions (≈ one round) the model forgets what it bought and why. |
| D-4 | `strategies/default/STRATEGY.md.jinja` (730 lines, 42 KB ≈ 10.5k tok) | Static (no `{{ }}`/`{% %}` at all even though `G` is passed, strategy.py:113). Shop/joker/voucher/spectral encyclopaedia is sent for every card play. Cached, so cost is OK, but attention dilution is high for Haiku; the decisive per-phase rules are buried mid-document. |
| D-5 | `bot.py:231-244` | Instruction order: strategy → state → memory. Nothing at the **end** of the prompt tells the model what to decide now. Small models weight the tail heavily. |
| D-6 | `config.py:18-26` | `tool_choice: "auto"` → text-only answers become error calls (3 in a row abort the run). |
| D-7 | `bot.py:304-356` | Only `tool_calls[0]`; `message.content` (free-text reasoning) discarded. No guard against non-progress loops: `rearrange`/`use`/`sell` successes reset failure counters (bot.py:347-351) and there is no max-calls cap, so a confused model can rearrange forever. |
| D-8 | `bot.py:197-198` | Extra `sleep(0.5)` + `gamestate` call per loop whose result is discarded (latency only). |
| D-9 | GAMESTATE pack section | Mega packs ("choose 2") — after the first pick the model gets the same screen with no "pick 1 more" hint (`pack_choices` not exposed; harness can infer from pack label/effect text). |
| D-10 | indices everywhere | Small models frequently mis-index after a reorder/draw. API is index-only; harness could accept card keys and translate. |

---

## 4. Ranked recommendations (expected impact for a Haiku-class model)

All recommendations are **strategy-agnostic**: new data is added as Jinja globals in `StrategyManager`, so existing
templates keep rendering unchanged until a strategy opts in; bot-side changes only add keys to `history` entries
(templates that ignore them keep working).

| Rank | Change | Impact | Effort |
|---|---|---|---|
| 1 | Hand analyser + blind progress globals, rendered in GAMESTATE (SELECTING_HAND) | ★★★★★ | M (≈200 LOC) |
| 2 | Reasoning-first tool schema (+ optional `card keys` echo/validation) | ★★★★ | S |
| 3 | Outcome-aware memory: action results, round log, build summary, persistent "plan" | ★★★★ | M |
| 4 | Phase-focused prompt: short per-state checklist at the end; trim/condition strategy | ★★★★ | S–M |
| 5 | Compact, correct GAMESTATE (sorted/filtered hands, readable cards, deck composition in SHOP, upcoming boss in SHOP, pack header) | ★★★ | S |
| 6 | Template bug fixes I-1…I-7 + static lookup tables (rarity, targets, voucher text) | ★★★ | S |
| 7 | Robustness: `tool_choice: required`, loop guard, max calls, record failed attempts | ★★ | S |
| 8 | Optional LLM blind-skip (manifest opt-in) | ★ (risky for Haiku) | S |

### 4.1 Hand analyser (rank 1)

Register in `strategy.py` `StrategyManager.__init__` (after line 97):

```python
from . import analysis

self.env.globals.update(
    analyze_hand=analysis.analyze_hand,  # SELECTING_HAND / Arcana pack targeting
    blind_progress=analysis.blind_progress,  # SELECTING_HAND
    deck_summary=analysis.deck_summary,  # any state (G.cards)
    card_name=analysis.card_name,  # "Ace of Clubs"
)
self.env.filters["card_name"] = analysis.card_name
```

Semantics (prototype tested: Pair of 6s + Joker + Ride the Bus(+3) → 198 = (10+12)×(2+4+3); Flush A-K-T-5-4 of
hearts → 300; flush/straight draw odds via hypergeometric over `G.cards`):

- Enumerate all subsets of size 1..`highlighted_limit` of visible hand cards (C(8,≤5)=218, trivial).
- Classify with Balatro rules (Five/Flush Five/Flush House/Straight Flush/4K/FH/Flush/Straight/3K/2P/Pair/High;
  A-low straight; WILD counts as any suit; STONE always scores, has no rank/suit; scoring cards only, no kickers;
  High Card scores only the top card). Keep the best **minimal** subset per hand type (every played card scores);
  fillers are left to the strategy.
- Estimate: `(hand.chips + Σ card chips [A=11, faces=10] + BONUS 30 + STONE 50 + FOIL 50) × (hand.mult + MULT 4 + HOLO 10)
  × GLASS 2 × POLY 1.5 × held STEEL 1.5`, RED seal retriggers, debuffed cards score 0, current hand-level chips/mult.
- Jokers: a small key table (`j_joker`, Jolly/Zany/Mad/Crazy/Droll, Sly/Wily/Clever/Devious/Crafty,
  Duo/Trio/Family/Order/Tribe with "contains" semantics, suit +3 jokers, Scary/Smiley/Scholar/Fibonacci/Even/Odd,
  Half) + a **generic `Currently ([+X])N (Mult|Chips)` regex over `value.effect`**, which covers most scaling
  jokers (Ride the Bus, Green, Ice Cream, Hologram, Constellation, Lucky Cat, Abstract, Blue Joker, Bull, Castle,
  Wee, Square, Runner, Madness, Vampire, Obelisk, Campfire, Throwback, Spare Trousers, ...). Unknown jokers are listed
  as "excl. X" so the model knows the estimate is a floor. Accuracy target: "right order of magnitude and right
  ranking", not JackPotts' 99.9%.
- Draws (uses `G.cards` counts only): flush draws with ≥3 of a suit; 4-of-5 straight windows (merge open-ended
  windows into one out-set in the final version); P(hit) when discarding the non-draw cards (≤5).

Condensed implementation (`src/balatrollm/analysis.py`):

```python
import re
from collections import Counter
from itertools import combinations
from math import comb

RANKS = "23456789TJQKA"
RANK_VAL = {r: i + 2 for i, r in enumerate(RANKS)}
CHIP_VAL = {r: min(RANK_VAL[r], 10) for r in RANKS} | {"A": 11}
RANK_NAME = {"T": "10", "J": "Jack", "Q": "Queen", "K": "King", "A": "Ace"}
SUIT_NAME = {"H": "Hearts", "D": "Diamonds", "C": "Clubs", "S": "Spades"}
HAND_JOKERS = {
    "j_jolly": ({"Pair"}, 0, 8, 1),
    "j_zany": ({"Three of a Kind"}, 0, 12, 1),
    "j_mad": ({"Two Pair"}, 0, 10, 1),
    "j_crazy": ({"Straight"}, 0, 12, 1),
    "j_droll": ({"Flush"}, 0, 10, 1),
    "j_sly": ({"Pair"}, 50, 0, 1),
    "j_wily": ({"Three of a Kind"}, 100, 0, 1),
    "j_clever": ({"Two Pair"}, 80, 0, 1),
    "j_devious": ({"Straight"}, 100, 0, 1),
    "j_crafty": ({"Flush"}, 80, 0, 1),
    "j_duo": ({"Pair"}, 0, 0, 2),
    "j_trio": ({"Three of a Kind"}, 0, 0, 3),
    "j_family": ({"Four of a Kind"}, 0, 0, 4),
    "j_order": ({"Straight"}, 0, 0, 3),
    "j_tribe": ({"Flush"}, 0, 0, 2),
}
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
SUIT_JOKERS = {
    "j_greedy_joker": "D",
    "j_lusty_joker": "H",
    "j_wrathful_joker": "S",
    "j_gluttenous_joker": "C",
}
CURRENTLY = re.compile(r"Currently ([+X])\s?(\d+(?:\.\d+)?) (Mult|Chips)", re.I)
PER_CARD_KEYS = {
    "j_scary_face",
    "j_smiley",
    "j_scholar",
    "j_fibonacci",
    "j_even_steven",
    "j_odd_todd",
}


def _card(c):
    v, m, s = c.get("value", {}), c.get("modifier", {}), c.get("state", {})
    stone = m.get("enhancement") == "STONE"
    return {
        "rank": None if stone else v.get("rank"),
        "suit": None if stone else v.get("suit"),
        "enh": m.get("enhancement"),
        "ed": m.get("edition"),
        "seal": m.get("seal"),
        "debuff": bool(s.get("debuff")),
        "hidden": bool(s.get("hidden")),
        "stone": stone,
    }


def classify(
    cards,
):  # -> (hand type, positions of scoring cards); ignores Four Fingers/Shortcut/Splash
    ranked = [(i, c) for i, c in enumerate(cards) if not c["stone"]]
    stones = [i for i, c in enumerate(cards) if c["stone"]]
    rc = Counter(c["rank"] for _, c in ranked)
    n = len(cards)
    allidx = list(range(n))
    flush = (
        n == 5
        and not stones
        and any(
            all(c["suit"] == s or c["enh"] == "WILD" for _, c in ranked) for s in "HDCS"
        )
    )
    vals = sorted({RANK_VAL[c["rank"]] for _, c in ranked})
    straight = (
        n == 5
        and len(vals) == 5
        and (vals[-1] - vals[0] == 4 or vals == [2, 3, 4, 5, 14])
    )
    cnt = sorted(rc.values(), reverse=True)
    of = lambda k: [i for i, c in ranked if rc[c["rank"]] >= k]
    if cnt and cnt[0] == 5:
        t, sc = ("Flush Five" if flush else "Five of a Kind"), allidx
    elif flush and cnt[:2] == [3, 2]:
        t, sc = "Flush House", allidx
    elif straight and flush:
        t, sc = "Straight Flush", allidx
    elif cnt and cnt[0] == 4:
        t, sc = "Four of a Kind", of(4)
    elif cnt[:2] == [3, 2]:
        t, sc = "Full House", allidx
    elif flush:
        t, sc = "Flush", allidx
    elif straight:
        t, sc = "Straight", allidx
    elif cnt and cnt[0] == 3:
        t, sc = "Three of a Kind", of(3)
    elif cnt[:2] == [2, 2]:
        t, sc = "Two Pair", of(2)
    elif cnt and cnt[0] == 2:
        t, sc = "Pair", of(2)
    else:
        hi = max(ranked, key=lambda ic: RANK_VAL[ic[1]["rank"]])[0] if ranked else None
        t, sc = "High Card", ([hi] if hi is not None else [])
    return t, sorted(set(sc) | set(stones))


def estimate(G, played, held):  # -> (type, scoring positions, est. score, note)
    htype, scoring = classify(played)
    base = G.get("hands", {}).get(htype, {})
    chips, mult, x = base.get("chips", 0), base.get("mult", 0), 1.0
    jokers = [
        j
        for j in G.get("jokers", {}).get("cards", [])
        if not j.get("state", {}).get("debuff")
    ]
    keys = [j.get("key") for j in jokers]
    for i in scoring:
        c = played[i]
        if c["debuff"]:
            continue
        for _ in range(2 if c["seal"] == "RED" else 1):
            chips += (
                (50 if c["stone"] else CHIP_VAL[c["rank"]])
                + (30 if c["enh"] == "BONUS" else 0)
                + (50 if c["ed"] == "FOIL" else 0)
            )
            mult += (4 if c["enh"] == "MULT" else 0) + (10 if c["ed"] == "HOLO" else 0)
            for k in keys:  # per-card jokers
                if SUIT_JOKERS.get(k) and (
                    c["suit"] == SUIT_JOKERS[k] or c["enh"] == "WILD"
                ):
                    mult += 3
                if k == "j_scary_face" and c["rank"] in "JQK":
                    chips += 30
                if k == "j_smiley" and c["rank"] in "JQK":
                    mult += 5
                if k == "j_scholar" and c["rank"] == "A":
                    chips += 20
                    mult += 4
                if k == "j_fibonacci" and c["rank"] in ("A", "2", "3", "5", "8"):
                    mult += 8
                if k == "j_even_steven" and c["rank"] in ("2", "4", "6", "8", "T"):
                    mult += 4
                if k == "j_odd_todd" and c["rank"] in ("A", "3", "5", "7", "9"):
                    chips += 31
            x *= (2 if c["enh"] == "GLASS" else 1) * (
                1.5 if c["ed"] == "POLYCHROME" else 1
            )
    for c in held:
        if c["enh"] == "STEEL" and not c["debuff"]:
            x *= 1.5 * (1.5 if c["seal"] == "RED" else 1)
    unknown = []
    for j in jokers:  # joker-level effects, left to right
        k, eff = j.get("key"), j.get("value", {}).get("effect", "")
        if k == "j_joker":
            mult += 4
        elif k in HAND_JOKERS:
            trig, c_, m_, x_ = HAND_JOKERS[k]
            if any(htype in CONTAINS.get(t, {t}) for t in trig):
                chips += c_
                mult += m_
                x *= x_
        elif k == "j_half":
            if len(played) <= 3:
                mult += 20
        elif k in SUIT_JOKERS or k in PER_CARD_KEYS:
            pass
        elif m := CURRENTLY.search(eff):
            num = float(m.group(2))
            if m.group(1) == "X":
                x *= num
            elif m.group(3).lower() == "mult":
                mult += num
            else:
                chips += num
        else:
            unknown.append(j.get("label", k))
    return (
        htype,
        scoring,
        int(chips * mult * x),
        (f"excl. {', '.join(unknown)}" if unknown else ""),
    )


def analyze_hand(G, top=6):
    hand = [_card(c) for c in G.get("hand", {}).get("cards", [])]
    limit = G.get("hand", {}).get("highlighted_limit", 5)
    best = {}
    for k in range(1, min(limit, len(hand)) + 1):
        for idx in combinations(range(len(hand)), k):
            if any(hand[i]["hidden"] for i in idx):
                continue
            played = [hand[i] for i in idx]
            held = [hand[i] for i in range(len(hand)) if i not in idx]
            t, sc, score, note = estimate(G, played, held)
            if len(sc) != k:
                continue  # minimal core only
            if t not in best or score > best[t]["score"]:
                best[t] = {"hand": t, "cards": list(idx), "score": score, "note": note}
    deck = [
        _card(c) for c in G.get("cards", {}).get("cards", [])
    ]  # aggregate only, never order
    suits = Counter(c["suit"] for c in deck if c["suit"])
    ranks = Counter(c["rank"] for c in deck if c["rank"])
    hs = Counter(c["suit"] for c in hand if c["suit"] and not c["hidden"])
    D = len(deck)
    draws = []
    for s, have in hs.most_common():
        if 3 <= have < 5 and D:
            need, outs, n = 5 - have, suits.get(s, 0), min(5, len(hand) - have, D)
            p = sum(
                comb(outs, x) * comb(D - outs, n - x)
                for x in range(need, min(outs, n) + 1)
            ) / comb(D, n)
            draws.append(
                f"Flush draw {SUIT_NAME[s]}: {have}/5 held, {outs} in deck; discard {n} others -> {p:.0%}"
            )
    hr = {c["rank"] for c in hand if c["rank"] and not c["hidden"]}
    for lo in range(1, 11):  # A-5 ... T-A
        win = ["A" if v in (1, 14) else RANKS[v - 2] for v in range(lo, lo + 5)]
        miss = [r for r in win if r not in hr]
        if len(miss) == 1 and D:
            outs, n = ranks.get(miss[0], 0), min(5, len(hand) - 4, D)
            draws.append(
                f"Straight draw {win[0]}-{win[-1]}: need {miss[0]} ({outs} in deck); discard {n} -> {1 - comb(D - outs, n) / comb(D, n):.0%}"
            )
    return {
        "plays": sorted(best.values(), key=lambda p: -p["score"])[:top],
        "draws": draws,
        "deck_size": D,
        "deck_suits": dict(suits),
        "deck_ranks": dict(ranks),
        "hand_suits": dict(hs),
    }


def blind_progress(G):
    cur = next(
        (b for b in G.get("blinds", {}).values() if b.get("status") == "CURRENT"), None
    )
    if not cur:
        return None
    r = G.get("round", {})
    left = max(cur["score"] - r.get("chips", 0), 0)
    hl = r.get("hands_left", 0)
    return {
        "name": cur["name"],
        "target": cur["score"],
        "scored": r.get("chips", 0),
        "remaining": left,
        "hands_left": hl,
        "per_hand": -(-left // hl) if hl else left,
    }
```

Template usage (new block in GAMESTATE SELECTING_HAND, before the hand list):

```jinja
{% set bp = blind_progress(G) %}{% set A = analyze_hand(G) %}
## Round Status
- Need **{{ bp.remaining }}** more chips ({{ bp.scored }}/{{ bp.target }}) with {{ bp.hands_left }} hands
  and {{ G.round.discards_left }} discards left → about **{{ bp.per_hand }} per hand**.

## Best plays available now (estimated score; jokers approximated)
{% for p in A.plays -%}
- {{ p.hand }}: cards {{ p.cards }} ({% for i in p.cards %}{{ G.hand.cards[i] | card_name }}{% if not loop.last %}, {% endif %}{% endfor %}) ≈ **{{ p.score }}**{% if p.score >= bp.remaining %} ✅ wins the blind{% endif %}{% if p.note %} ({{ p.note }}){% endif %}
{% endfor %}
{% for d in A.draws %}- {{ d }}
{% endfor %}
- Suits in hand: {{ A.hand_suits }} | Deck ({{ A.deck_size }} cards left): {{ A.deck_suits }}
```

Why it is #1: the observed failure modes (Pair+fillers on hand 1, miscounted flushes, "scoring (40+35)*4 = 300"
hand arithmetic in every response, ~1.2k output tokens/decision) are all arithmetic/combinatorics the harness can
do exactly. It also lets the model notice "✅ wins the blind" → stop discarding.

Extra (cheap): also emit a **"suggested discard"** line only when no play reaches `per_hand` — e.g. keep the best
draw's cards, discard up to 5 of the rest — labelled as a suggestion so strategies can ignore it.

### 4.2 Reasoning-first tools + card-key echo (rank 2)

In every TOOLS.json, put `reasoning` **first** in `properties` (and in `required`), and tighten its description:

```json
"properties": {
  "reasoning": {"type": "string", "description": "BEFORE choosing cards: state chips needed, the hand you will make, which card indices, and the estimated score. 1-3 sentences."},
  "cards": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 5, "description": "0-based indices from 'Current Hand'"}
}
```

Optional harness feature (strategy-agnostic, off unless the tool schema declares it): accept `card_keys`
(e.g. `["H_A","D_A"]`) alongside/instead of `cards`; in `bot._execute_tool_call` map keys → indices against the
current `gamestate["hand"]["cards"]` (first unused match), and if both are given and disagree, return a failed call
"indices [..] are X,Y but you named A,B" instead of executing. This catches the most common small-model error
(off-by-one / stale indices) before it costs a hand. Requires passing the pre-action gamestate into
`_execute_tool_call` (also needed for 4.3). Also strip `reasoning` from `fn_args` before sending to BalatroBot and
store it separately.

### 4.3 Outcome-aware memory (rank 3)

`bot.py` changes (sketch):

```python
# _run_game_loop
case "SELECTING_HAND" | "SHOP" | "SMODS_BOOSTER_OPENED":
    response = await self._get_llm_response(gamestate)
    gamestate = await self._execute_tool_call(response, before=gamestate)
case "ROUND_EVAL":
    self._record_round(gamestate)          # before cash_out: blind, target, chips, hands/discards used
    gamestate = await self._balatro.call("cash_out")

# _execute_tool_call, on success
reasoning = fn_args.pop("reasoning", "")
after = await self._balatro.call(fn_name, fn_args)
self._history.append({
    "method": fn_name, "params": fn_args, "reasoning": reasoning,
    "state": before["state"], "ante": before.get("ante_num"), "round": before.get("round_num"),
    "result": summarize_outcome(fn_name, fn_args, before, after),
})
```

`summarize_outcome` (pure function, `analysis.py`), examples:
- play → `"Flush scored 420 (720/800, 2 hands left)"` — hand type = the `hands[*].played_this_round` key that
  incremented; score = `after.round.chips - before.round.chips` (if `after.state` is ROUND_EVAL/SHOP: "blind beaten").
- discard → `"discarded 5♣ 3♦; drew K♥ Q♥"` (diff of hand keys).
- buy → `"bought Hologram for $6 ($14 left)"`; for vouchers also remember `label: effect` in
  `self._vouchers` to fix I-7.
- pack/use → label + target cards.

Round log `self._rounds: list[dict]` appended at ROUND_EVAL:
`{"ante": 2, "blind": "Big Blind", "target": 1200, "scored": 1460, "hands_used": 3, "discards_used": 2, "main_hand": "Flush"}`.
Pass to `render_memory(history=..., rounds=self._rounds[-4:], build=build_summary(gamestate, self._rounds))`
(extra kwargs are ignored by templates that don't use them, so other strategies keep working).

`build_summary(G)`: most-played hand type (`max(hands, key=played)`), hands with level>1, joker list one-liners,
plus a trend line "last 3 blinds won with margin 1.2× / 1.1× / 0.95× target — scaling is falling behind" (score
margin vs target is the single best signal to tell a small model "buy mult now").

New MEMORY template (replace D `MEMORY.md.jinja`):

```jinja
# Memory
{% if build %}## Run so far
- Main hand: {{ build.main_hand }} (played {{ build.main_count }}×){% for h in build.levels %}; {{ h.name }} Lv{{ h.level }}{% endfor %}
- Recent blinds: {% for r in rounds %}A{{ r.ante }} {{ r.blind }} {{ r.scored }}/{{ r.target }}{% if not loop.last %} · {% endif %}{% endfor %}
{% endif %}
{% if history %}## Last actions (oldest → newest)
{% for e in history %}{{ loop.index }}. [A{{ e.ante }} {{ e.state }}] {{ e.method }} {{ e.params | tojson }} → {{ e.result }}{% if e.reasoning %} — "{{ e.reasoning | truncate(160) }}"{% endif %}
{% endfor %}{% endif %}
{% if last_failed_call_msg %}**Your last action FAILED**: {{ last_failed_call_msg }} — do not repeat it.{% endif %}
```

Keep 10–15 entries but scope them to the **current round/shop** plus the round log; drop the generic "Strategic
Context" boilerplate (D `MEMORY.md.jinja:13-24`). Optionally add a `plan` string parameter to `next_round`
(the model writes its build plan when leaving the shop; harness stores it and shows it under "Run so far" until the
next shop) — gives a persistent intent at almost zero cost.

### 4.4 Phase-focused prompt (rank 4)

- Keep STRATEGY as the cached prefix (prompt caching needs an identical prefix; `cache_control` is on block 0,
  bot.py:238) but split it: `{% if G.state == "SELECTING_HAND" %}{% include "strategy/play.md" %}{% elif ... %}`.
  Three or four variants are each cached independently (calls arrive seconds apart, well within the 5-min TTL).
  Jinja `include` already works with the `FileSystemLoader(self.path)` in strategy.py:96. Target ≤2.5k tokens per
  phase for the Haiku strategy; the encyclopaedia parts (all 22 tarots, 18 spectrals, 32 vouchers, editions) belong
  only in SHOP/pack variants, and only the boss blinds of the current ante need describing (the effect text is
  already in `G.blinds.boss.effect`).
- Append a **final "Decide now" block** (end of GAMESTATE or MEMORY, i.e. the last thing the model reads), e.g. for
  SELECTING_HAND: "1) If a listed play scores ≥ remaining → play it. 2) Else if discards left and a draw ≥ 35% →
  discard the non-draw cards (≤5). 3) Else play the highest-scoring option. Never play filler cards unless …".
  For SHOP: "1) Joker slots free and affordable mult/xmult joker? 2) Planet for main hand? 3) Keep ≥ $X for
  interest? 4) next_round." Strategies own the text; the harness just guarantees the slot exists.
- Put the role/system text in a `system` message (static) and only the dynamic parts in the user message. Small
  models follow system instructions more consistently.

### 4.5 Compact, correct GAMESTATE (rank 5)

- Poker hands: add a global `hands_table(G)` returning
  `sorted(({"name": n, **h} for n, h in G["hands"].items()), key=lambda h: h["order"])` (strongest first;
  reverse for weakest first); render one line per hand:
  `- Flush Lv2: 50 chips × 6 mult (played 4)`; show only hands with `level > 1 or played > 0` plus the 9 regular
  hands in compact form; hide Five of a Kind / Flush House / Flush Five unless levelled or played. Drop "Example".
  Saves ~500 tokens/call and removes the bait of 160-chip secret hands.
- Cards: `- 3: King of Hearts [H_K] (10 chips) · GLASS · RED seal` on one line (use `card_name` filter).
- SHOP header: money, interest next round `min(money//5, 5)` (vanilla cap; vouchers raise it), joker slots
  `{{G.jokers.count}}/{{G.jokers.limit}}`, **next blind and score**, and **upcoming boss name + effect**
  (`G.blinds.boss`), deck summary `52 cards: ♠13 ♥13 ♦13 ♣13; enhanced: 2 GLASS`.
- Pack header: same as shop + "Choose {{1 or 2}}" parsed from `G.pack`/pack effect text ("Choose 1 of up to…").
- Remove the duplicated "Tools available" section (I-10) or reduce it to one line listing tool names.

### 4.6 Template bug fixes + static tables (rank 6)

- I-1: render `e.reasoning or e.params.reasoning`.
- I-2: add `{%- elif G.state == "SMODS_BOOSTER_OPENED" %}` header.
- I-3: replace rarity default with `JOKER_RARITY.get(card.key)` (static dict of 150 jokers; source: game
  `G.P_CENTERS` or the joker table in balatrobot `docs/api.md`) or delete the line.
- I-4: `CONSUMABLE_TARGETS = {"c_magician": (1,2), "c_empress": (1,2), "c_heirophant": (1,2), "c_lovers": (1,1),
  "c_chariot": (1,1), "c_justice": (1,1), "c_strength": (1,2), "c_hanged_man": (1,2), "c_death": (2,2),
  "c_devil": (1,1), "c_tower": (1,1), "c_star": (1,3), "c_moon": (1,3), "c_sun": (1,3), "c_world": (1,3),
  "c_talisman": (1,1), "c_aura": (1,1), "c_deja_vu": (1,1), "c_trance": (1,1), "c_medium": (1,1),
  "c_cryptid": (1,1)}` as a Jinja global; show "Targets: select 1–3 hand cards" on consumables (owned, shop, pack).
- I-5/I-6: use `card.modifier.enhancement/edition/seal`, handle STONE and hidden; render pack-joker editions.
- I-7: `VOUCHER_EFFECTS` static dict (32 entries, in balatrobot `docs/api.md` ~l.1160-1200) or the
  harness-remembered text from the shop.
- I-13/I-14/I-15: fix strategy text (Negative passive and also on consumables; drop or heavily qualify "play
  max cards to cycle"; 12 hand types).

### 4.7 Robustness (rank 7)

- `DEFAULT_MODEL_CONFIG["tool_choice"] = "required"` (OpenRouter maps to Anthropic `any`). Caveat: Anthropic
  forbids forced tool choice with extended thinking — make it conditional on `reasoning` not being enabled in
  `extra_body`.
- Loop guard: count consecutive non-progress successes (`rearrange`, `sell`, `use`, failed-then-retried); after
  3, drop `rearrange` from `tools` for that decision and add "You already rearranged; now play/discard." to memory.
- Global cap (e.g. 600 LLM calls/run) → `finish_reason = "max_calls"` to avoid runaway cost.
- Record failed attempts in history (`result: "FAILED: <msg>"`) so the model sees *what* failed, not only the
  last message; this also stops alternating error/failed patterns that reset each other's counters
  (bot.py:381-382, 401-402).
- Remove the per-loop extra `gamestate` call and 0.5 s sleep (bot.py:197-198) — screenshots already add latency.

### 4.8 Blind skipping (rank 8, optional)

Gate with `manifest.json` `"llm_blind_select": true` (default false, so default/aggressive/conservative behave
as today). When enabled, render BLIND_SELECT (already templated) with tag name/effect and call the LLM using the
existing BLIND_SELECT tools. For Haiku the expected value is negative unless the strategy is very explicit
(skipping forfeits ~$3–4 and a shop); leave off for benchmarks.

---

## 5. Prior art (what worked)

- **BalatroBench** (coder; same harness): ranks models by average final round on Red/White fixed seeds, 3 runs ×
  5 seeds. Reported Feb 2026: gemini-3-pro-preview best (won 9/15), creator said Opus 4.6 comparable; weakest models
  lose round 1. Leaderboard emphasises tool-call validity (valid / invalid-in-state / no tool call) — i.e. the
  harness cares about error calls, supporting `tool_choice=required` and fewer index errors.
- **JackPotts** (DrLatBC, rule-based, BalatroBot API, no LLM): enumerates candidate hands and runs a full scoring
  simulation (99.89% accurate vs real chips); discard decisions via Monte-Carlo draws **from `state["cards"]`**
  (its `state_adapter.py` reads `cards.cards` as `deck_cards` — confirms the deck pile is usable); shop via EV-delta
  of each joker with live "Currently X" anchors parsed from effect text. Results (1,238 White-stake games): avg ante
  4.6, median ante 5, **Red deck 1.5% wins, median ante 4**; 60% of deaths on boss blinds. ⇒ Haiku's best of
  round 12 (Ante 4 boss) ≈ a strong rule-based bot's median; an exact scorer alone does not win runs — shop/build
  decisions dominate later antes. JackPotts needed a BalatroBot fork for joker ability data, The Ox locked hand,
  Ancient Joker suit, Idol target, edition values (upstream PR #181 open).
- **Ballad** (polina4096, Rust, BalatroBot, Claude): short 7 KB prompt; "ABSOLUTE LIMITS" section; "use ONLY the
  latest state"; explicit phase semantics ("SHOP means you already WON the round"); "play ONLY the cards that form
  your combination"; author reports even Sonnet 4.5 "hallucinates about the current game state" → argues for
  computed summaries over raw state.
- **BlindDeck** (FFFishes7): JSON-RPC mod with CLI helpers incl. a hand-type chips/mult command for agents —
  same idea as §4.1. **balatro-rs** (Rust sim + gym, move generator) and HF dataset `makemake/5k-balatro-games`
  exist for RL; claimed "GPT-6 Astra" bot (Reddit, unverified) used Python numerical tools for scoring with the
  LLM choosing moves.
- Common lesson: **let code do arithmetic/combinatorics, let the LLM pick among enumerated options**, keep the
  prompt short and phase-specific, and track the run state outside the model.

---

## 6. Integration notes / compatibility checklist

- New module `src/balatrollm/analysis.py` (pure functions, no I/O) + `env.globals`/`env.filters` registration in
  `StrategyManager.__init__` (strategy.py:96-97). Templates that don't call them are unaffected.
- `render_memory(**extra)` → pass `rounds`, `build`, `vouchers` as additional kwargs (Jinja ignores unused vars).
- History entries gain keys (`reasoning`, `result`, `state`, `ante`, `round`); `params` stays, so
  existing `{{ entry.params }}` renders still work (minus reasoning once stripped — keep a copy in `params` if you
  want byte-identical old behaviour).
- Unit fixtures `tests/unit/fixtures/**.gamestate.json` referenced by `tests/unit/conftest.py:15,36` are **not in
  the repo** (generated by a live game); golden tests will need regeneration after template edits. A synthetic
  gamestate (like the prototype test) is enough to unit-test `analysis.py`.
- Always guard `G.cards` / `G.hand` / `G.blinds` with `.get()`; areas can be missing in transient states.
- Never surface the order of `G.cards.cards` or ranks of face-down (`state.hidden`) hand cards.

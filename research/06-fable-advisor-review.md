# 06 — Advisor review of the master plan (Balatro v1.0.1, Red Deck / White Stake, Haiku-class model)

Reviewer stance: independent and critical. I read 00–05 in full, the `default` strategy, `bot.py`, `strategy.py`.
Facts below are checked against my own knowledge of the v1.0.1 game data (`game.lua`, `card.lua`, `functions/state_events.lua`);
the research agents had no wiki access, so I re-verified the numbers they relied on (§4).

**Verdict in one line:** the plan's principle is right (code does arithmetic, the LLM picks among enumerated options) and its
ranking of harness work is right, but (a) the "universal early joker" list contradicts its own discard-first policy, (b) the
curriculum keeps too much in prose that belongs as *annotations in the state*, (c) the pivot/main-hand decision is left to the model
when it should be a harness fact, and (d) the analyser as specified can mislead (optimistic estimates marked "wins").

---

## 1. Early game (Antes 1–3): which plan scales for a small model?

### 1.1 The three candidates, honestly

| Plan | Pro | Con for a Haiku-class model |
|---|---|---|
| **Flush by default** | Highest base of any reliably-made hand (35×4 + ~42 card chips ≈ 300 at L1). +Mult jokers are worth more on high-chip hands. Suit counting and flush-draw odds are trivial for the harness to compute and render. Deck shaping is easy: 4 suit tarots (Star/Moon/Sun/World), Lovers, Sigil, Smeared, Four Fingers. Immune to Plant/Mark/Psychic; Mouth/Eye fine. ~2.5 flushes/round on Red Deck (report 02 Monte Carlo is sound). | Needs discards every round, which conflicts with Banner/Green/Ramen/Delayed Gratification (see §4). A Flush never "contains a Pair" (same suit ⇒ distinct ranks, barring Wilds/copies), so pair jokers are dead on it. 4 of 23 bosses debuff a suit. P(≥3 flushes in a round) ≈ 50%, so from Ante 4 one flush must clear ≥ target/2 ⇒ xMult by Ante 4 is mandatory, not optional. |
| **Pair/Two Pair + universal +Mult, then pivot** | Two Pair is made 3.5×/round with almost no discard logic; the pair-family payoffs are the cheapest and most frequent commons (Jolly $3, Sly $3, Mad, Clever, Zany, Wily, Half, + The Duo). Robust to suit bosses. | Base is tiny (20×2 + ~30 chips ≈ 100). Planets are weak (+20/+1). The "pivot" is exactly the kind of multi-factor judgement a small model gets wrong. Uranus levels do not carry to Full House. |
| **Follow the jokers** | What strong humans do. | Requires evaluating 150 jokers × hand types × deck state. The failure mode is a run with 5 jokers across 3 plans. Not for Haiku. |

### 1.2 My recommendation: Flush-by-default with a **harness-set MAIN_HAND**, and "play the top listed score" in Antes 1–2

1. **MAIN_HAND is a fact computed by the harness and printed in every prompt**, not a decision the model makes.
   Rule (deterministic, in `analysis.py`): `MAIN_HAND = Flush`, except: own The Duo → Two Pair family; own ≥2 pair-family jokers
   and 0 flush jokers at the start of Ante 3 → Two Pair; own The Tribe/Smeared/Four Fingers → Flush (locked). After Ante 3 starts,
   never changes except via Duo/Tribe. This removes the whole "when to pivot" paragraph from the prompt.
2. **In Antes 1–2 there is no hand loyalty for *plays*.** Rule: "play the highest-scoring listed play that WINS, else discard toward
   MAIN_HAND, else play the highest-scoring listed play." Loyalty matters only for planets, Supernova/Card Sharp, Telescope and
   The Ox — all of which are Ante 2+ concerns. This is simpler and strictly better than "Flush, fallback Pair/Two Pair padded".
3. **Discard rule is one line and index-free for the model**: the harness prints `Suggested discard: [i, j, k]` = the ≤5 cards
   outside the largest suit group (or outside a listed play that reaches PER_HAND). The model copies indices.
4. **Shop rule in Antes 1–2 is "fill slots with the highest-tier affordable joker"**; tiers come from a static table rendered next to
   each item (§3.3). Flush-specific jokers (Droll, Crafty, Smeared, Four Fingers, Tribe, suit +3 jokers) get an `[MAIN]` tag only when
   MAIN_HAND is Flush, so the model never has to remember which joker fits.
5. **Why not Two Pair as default:** it caps lower per hand and its planet is bad; the only thing it buys is less discard logic, and the
   analyser removes that cost. Keep it as the *pivot target*, not the default.

### 1.3 Early-game prompt block (≤25 lines, verbatim)

```
EARLY GAME (Antes 1-3). Tokens in CAPS are printed in the STATUS block; never compute them yourself.
PLAY
1. If any listed play is marked WINS: play exactly those indices. Do not discard first.
2. Else if DISCARDS > 0 and no listed play reaches PER_HAND: discard the "Suggested discard" indices (max 5).
   Discards are free. Every hand left unused when the blind ends pays $1, so never spend a hand just to draw cards.
3. Else play the highest-scoring listed play. Add filler only if: the play has fewer than 5 cards, the filler is not
   in your MAIN_HAND suit, you do not own Half Joker, and the boss is not The Tooth. Under The Psychic play exactly 5.
4. HANDS = 1: use remaining discards first (rule 2), then play the best listed play.
SHOP (floor: Ante 1 $0, Ante 2 $5, Ante 3 $15; ignore the floor for an [XMULT] joker, a $0 item, or STATUS = TOO WEAK)
5. Goal: 2 scoring jokers by the Ante 1 boss, 3 by Ante 2, 4-5 by Ante 3. An empty slot loses more than any purchase.
6. Buy the best joker you can afford: [XMULT] > [MAIN] > [MULT] > [SCALE] > [CHIPS] > [ECON]. Never buy [TRAP]. Never a
   second [ECON]. If slots are full, sell your lowest-tagged joker only to buy an [XMULT] or a [MAIN] over a [CHIPS]/[ECON].
7. First shop of the run: buy a scoring joker AND the Buffoon pack if you can afford both.
8. Planet for MAIN_HAND in the shop: buy ($3) and use it now. Celestial pack: take MAIN_HAND's planet, else Black Hole.
9. Arcana pack: Judgement (free slot) > suit tarot on the "Suggested targets" > Empress/Justice on scored MAIN cards >
   Hermit if money >= $10 > skip. Never Tower or Hanged Man on MAIN_HAND-suit cards.
10. Max 1 pack per shop; skip Standard and Spectral packs. Rerolls: none in Ante 1-2; in Ante 3 at most 1, only with an
    empty slot and money >= floor + $5. Then next_round. Never more than 6 actions in one shop.
11. After any joker purchase the harness re-orders jokers (+Chips, +Mult, scaling, xMult rightmost). Do not rearrange.
MILESTONE: own 1 [XMULT] by the end of Ante 4 and 2 by Ante 6. From Ante 3 an [XMULT] outranks everything else.
```

---

## 2. Teaching the model: curriculum structure, length, phrasing

**Structure.** The four layers are the right idea, but two of them should not be prose:
- *Layer 1 (core facts, "~40 lines")* → cut to ≤15 lines. If the harness prints scores, the model does not need the scoring formula,
  the blind table or chip values. It needs: chips × mult; +Mult left, ×Mult right; hands pay $1, discards pay $0; interest $1/$5 up to
  $5; "SHOP means you already won"; indices are 0-based and max 5.
- *Layer 2 (ante plan table)* → replace the table with a **harness-rendered status line**: `MILESTONE Ante 3: 4-5 jokers, 1 xMult by Ante
  4. You have 3 jokers, 0 xMult → PRIORITY: xMult or +Mult joker.` A small model indexes a table badly; it reads a sentence well.
- *Layer 3 (phase rulebook)* → keep; ≤40 numbered lines per phase, one condition per line (§1.3 is the PLAY/SHOP core).
- *Layer 4 (reference cards)* → **move out of prose into the state renderer.** Joker tier/category tags, tarot/spectral verdicts, the
  active boss counter and consumable target counts should appear *next to the item they describe*. Prose that says "Cavendish is S-tier"
  requires name-matching; `- 1: Cavendish [XMULT, S] $4` does not.
- *Final "decide now" block* → keep, ≤6 lines, last thing in the prompt, phase-specific, and it must use the same CAPS tokens as the
  status block (NEED, PER_HAND, HANDS, DISCARDS, MAIN_HAND, FLOOR, SLOTS_FREE, XMULT_OWNED). Lexical anchoring between state and rule is
  the single most effective small-model technique here.

**Order.** `system` = role + core facts + phase rulebook + one worked example (static, cached, 3–4 variants by phase). `user` = STATUS
block → analyser block → state detail → memory (≤12 lines) → DECIDE NOW. Move the static text to the system role (caching still works).

**Length targets (Haiku-class).** Static prefix ≤2,000 tokens; PLAY prompt ≤3,500 tokens total; SHOP/PACK ≤5,000. Today's 13.4k
average is 3× too long, and most of it is never relevant to the decision. Reasoning output: cap the `reasoning` field description at
"1–3 sentences"; long free-form reasoning from small models drifts into invented state.

**Phrasing rules that matter for small models.**
- Imperative, numbered, ordered: "If X → do Y" with the stop condition first (WINS before discard). Avoid "consider", "generally",
  "often", "usually". Avoid stacked negations ("don't pad unless not Psychic"); state the positive case.
- Never hedge a number. Thresholds live in the state as concrete values, never as formulas in the rulebook.
- Whitelists over blacklists for exceptions (e.g. "ignore the floor only for: XMULT, $0 item, TOO WEAK").
- One worked example per phase showing the exact tool call JSON, placed in the static prefix, with a hand that is obviously different
  from any real hand (small models copy example indices).
- Vocabulary must match the renderer: if the rule says "[XMULT]", the state must print "[XMULT]". Use the same card naming everywhere
  ("King of Hearts", never `H_K` alone).
- Lists, not wide tables, for rules. Tables only for ≤6-row data the harness renders.
- Put the failure message of the last action in memory verbatim with "do not repeat" — the current counters reset each other, so a model
  can alternate two bad actions forever.

---

## 3. Harness changes: ranking, gaps, and what the harness should decide itself

### 3.1 Plan §4 items ranked by lift ÷ risk

| Rank | Item | Lift | Risk | Note |
|---|---|---|---|---|
| 1 | §4.1 analyser: NEED/PER_HAND, best play per type with indices, draw odds, **suggested discard** | ★★★★★ | Medium | Risk is a *wrong* estimate marked WINS. Mitigation in §3.2. |
| 2 | §4.5 phase-specific prompt + DECIDE NOW tail + system role | ★★★★ | Low | Pure text; do it in the same PR as the analyser so the prompt references its tokens. |
| 3 | §4.4 GAMESTATE rewrite (upcoming boss in SHOP, sorted hands, compact cards, pack header, deck suits) + **inline tier tags** | ★★★★ | Low | Add the static `JOKER_NOTES` table (tier, category tag, one-line hint, trap flag). |
| 4 | §4.3 memory: outcomes per action, round log, build summary | ★★★★ | Low | Add "estimate vs actual" per play (see 3.2). Drop the "Strategic Context" boilerplate. |
| 5 | §4.2 reasoning-first tools, maxItems 5 | ★★★ | None | 20 minutes of work. Do it first. |
| 6 | §4.6 `tool_choice: required` (when thinking is off), loop guard, max calls, failed attempts in history | ★★ | Low | Reliability, not strength. Also strip `reasoning` from `fn_args` before the RPC. |
| 7 | Rule-based Small-Blind skip | ★ | Medium | Agree with deferral. |

### 3.2 Missing items that matter most (in order)

1. **MAIN_HAND + milestone status computed by the harness** (§1.2). Cheapest, largest reduction in model judgement.
2. **Estimate safety.** The analyser's `✅ wins the blind` must use a *floor* estimate: exclude probabilistic effects (Misprint → 0,
   Lucky → 0, Bloodstone → ×1, Loyalty Card unless the counter says "next hand"), count only jokers it knows, and require
   `estimate ≥ 1.10 × remaining` before printing WINS. Print `≈ N (floor; excl. Hologram)` so the model knows the direction of error.
3. **Estimate calibration loop.** On every `play`, `after.round.chips − before.round.chips` is the truth. Log `(estimate, actual)` to
   `gamestates.jsonl`, print the last ratio in memory ("recent estimates ran 0.9× of actual"), and turn the recorded runs into unit tests
   for `analysis.py`. This is the test harness the plan lacks, and it is free.
4. **Target suggestions for consumables.** Suit tarot → the 3 lowest off-MAIN-suit cards; Empress/Hierophant/Justice → the highest-chip
   MAIN-suit cards; Hanged Man → lowest off-suit; Death → `[junk_idx, best_idx]` with the *higher* index as the template. Validate Death
   targets (exactly 2) and Judgement/Soul/Wraith (needs a free slot) before sending.
5. **Shop annotations before shop EV.** A static per-joker tag + tier + hint table (150 rows, from report 01 §2) rendered inline is more
   robust than a computed "if bought, Flush goes 1,400 → 2,800" line, because unknown/scaling jokers would show +0 and be undervalued.
   Add the EV delta later for jokers the estimator understands, labelled "(now)".
6. **Boss impact line in SHOP and during Small/Big**: `Upcoming boss: The Head — Hearts debuffed. MAIN_HAND Flush uses Hearts (18 cards):
   AFFECTED. Prep: level/buy for Two Pair or convert suits.` Fill The Ox's `#1#` with the most-played hand from `G.hands`.
7. **Deck composition** (suit counts, enhanced-card counts) in SHOP, PACK and PLAY — it is already in `G.cards`, aggregate only.
8. **Mega-pack "pick 1 more" hint** and consumable target counts (I-4) from a static table.
9. **Model-written run plan**: lower priority than the harness-derived build summary. A wrong self-written plan is followed
   persistently. If added, cap it at 120 characters on `next_round` and show it under "Run so far".

### 3.3 Should the harness pre-decide?

Yes, for three categories; no for the fourth.
- **Mechanical, strategy-free** → do it in code, gated by `manifest.json` flags so `default` is unchanged: blind select (already),
  cash out (already), **joker reorder at `next_round`** (+Chips → +Mult → scaling → xMult → Polychrome rightmost; Blueprint immediately
  left of the best xMult; Brainstorm's target in slot 1), **auto-use a bought planet when it matches MAIN_HAND**. Rearranging is pure
  arithmetic and today costs LLM calls that can loop.
- **Illegal or strictly dominated** → veto with a failed-call message the model sees once: Buffoon pack with full slots (the pack state
  cannot sell), `pack` with both `card` and `skip`, Death with ≠2 targets, >5 cards, discarding cards that belong to a listed WINS play.
- **Tactical suggestion in PLAY** → print `Suggested action: play [1,3,4,6,7] (Flush ≈ 1,250, WINS)` and let the model confirm or
  deviate. Make this a manifest toggle and benchmark both settings. Expect most of the Ante 1–4 lift to come from here.
- **Shop and pack choices** → LLM decides, with annotations. This is where a rule-based bot plateaus (JackPotts: median Ante 4 on Red
  Deck with an exact scorer) and where model knowledge can add value. Do not rule-base it yet.

---

## 4. Errors and misleading rules (checked against v1.0.1)

Confirmed correct in the reports: all 150 joker effects and prices I spot-checked (≈60), the 1.0.1 blind table (300/800/2000/5000/
11000/20000/35000/50000; Wall ×4, Needle ×1, Violet Vessel ×6), rewards $3/$4/$5/$8, interest, Red Deck 4 discards, High Card 5×1, the
12 hand bases, all 12 planet increments, rarity weights 70/25/5 with Legendary only from The Soul, Smiley +5, Hanging Chad ×2 extra,
Invisible Joker 2 rounds, Erosion +4, suit jokers +3, edition surcharges, Death = other selected cards copy the rightmost (highest
index), Wild debuffed by suit bosses, The Arm permanent, boss minimum antes, first-shop Buffoon pack, report 01 §1.4 scoring order
(Foil/Holo before a joker's own effect, Polychrome after — correct), scoring order of played cards = left-to-right hand position
(the game sorts highlighted cards by x before playing; the index order in `play` is irrelevant).

Problems, most damaging first:

1. **Half Joker listed as "S-tier universal early" (plan §3.3, report 01 §0/§4) while the default main hand is a 5-card Flush and
   the play rule pads to 5.** Half Joker is +20 only with ≤3 cards: it is dead on Flush and on every padded play. Tag it `[PAIR]`,
   S-tier only when MAIN_HAND is the pair family and padding is off.
2. **Ride the Bus as "universal".** It resets on any *scoring* face card; a Flush scores all 5 cards and ~80% of flushes contain a
   J/Q/K. Dead with Flush. Tag `[PAIR, no-face]`.
3. **Green Joker, Banner, Delayed Gratification as S/A universal picks next to a "discard first" rule.** Green nets ≈ +1 Mult per round
   on a discard-heavy Red Deck plan (+4 hands − ~3 discards). Banner's "+120" exists only at 4 discards *remaining*, i.e. only when you never
   discard; under discard-first it is +0…+60. Delayed Gratification pays $0 if you discard once. Either demote all three to B with the
   tag `[KEEP-DISCARDS]` or drop them from the early list. Ramen (×2 − 0.01/card) survives discard-first for ~4 antes; keep it A.
4. **"✅ wins the blind" from an optimistic estimate** (plan §4.1): a model will trust the mark and play a losing hand with discards
   in hand. Floor estimate + 10% margin (§3.2 item 2).
5. **Power check "won with ≥2 hands left" (plan §3.1/§3.4, report 03 rule 6).** From Ante 4 normal good play uses 3 hands, so the
   check reads TOO WEAK almost always and the $25 floor evaporates. Replace with `hands_needed = ceil(next_target / mean(last 3 play
   scores))`; ON TRACK if ≤3, TOO WEAK if ≥4. The harness has both numbers.
6. **Reroll rule allows rerolling in Ante 1** ("money stays ≥ floor", floor $0). Forbid rerolls in Antes 1–2; a $5 reroll is a joker.
7. **Pivot rule left to the model** ("switch … if holding ≥2 pair-family jokers and no flush jokers by end of Ante 2–3"). Compute it (§1.2).
8. **Baron and Loyalty Card in "reliable xMult" (plan §3.3).** Baron needs held Kings; a Flush plan holds 3 cards. Loyalty Card fires on 1
   hand in 6, unpredictable for the blind you must win now. Both B. Also add **Smeared Joker and Four Fingers as S for a Flush plan**; they
   are missing from the early list although they are the two biggest consistency enablers.
9. **Hieroglyph/Petroglyph** are not in the plan's "never" list (report 03 rates Hieroglyph C, "A with Grabber"). For a 4-hand bot −1 hand
   is −25% of plays, −$1/round and +33% required score per hand. Never buy. Also warn the owner: Hieroglyph *inflates the round-reached
   metric* without helping a win.
10. **"Leave holding a multiple of $5"** (plan §3.4 item 7) invites junk $3 purchases to "spend the remainder". Interest is computed on
    money at cash-out, so the principle is right, but drop the rule for a small model; the floor already does the work.
11. **Report 02 "a Flush that has a duplicate rank (unverified)"**: impossible without Wild cards or copied cards. Delete; and state
    plainly in the rulebook that pair jokers never fire on a Flush and flush jokers never fire on pairs — this is the real cost of a
    "Flush + Pair fallback" plan and the reason the shop rule needs `[MAIN]` tags.
12. **Plan §3.2 step 4 wording** "padded … only if not Psychic-forbidden (Psychic *requires* 5)" is a double negative a small model will
    invert. Write: "Under The Psychic play exactly 5 cards."
13. **Plan §3.5 Hook counter** ("play 5-card hands; don't rely on held cards") is fine; report 04's "so only 3 cards are held" reasoning is
    irrelevant (Hook discards 2 random *after* the play regardless). Keep the one-liner, drop the reasoning.
14. **Ante 1 shop advice** "Buffoon pack if no good joker": with ~$10 after the first blind, buy the best joker *and* the $4 pack. The
    milestone "2 jokers by the Ante 1 boss" is usually reachable in shop 1 alone.
15. **Plan §3.6 "Hermit at ≥$20"** is the max-value threshold, not a minimum; $10–$19 is still +$10–$19 and usually better than any
    other Arcana pick. Use "≥$10".
16. **Planet "use now" vs Observatory** is correct, but the shop header should print `Observatory: HOLD planets` so the exception lives
    in the state, not the prose.
17. Report 01 lists Supernova as S early; it is +1 per play of the type, ≈ +3 by the Ante 1 boss. A (fine), not S.
18. The Ox effect text from BalatroBot likely renders an unfilled `#1#`; the Wheel shows `#1# in 7`. The renderer must substitute.
19. Report 04's Fish behaviour after discards is marked unverified; keep the counter to "hidden cards still score; use them as filler".

---

## 5. Top 10 concrete changes to the master plan, in order

1. **Add `main_hand(G, history)` to `analysis.py`** and print `MAIN_HAND`, `SLOTS_FREE`, `XMULT_OWNED`, `FLOOR`, `STATUS (ON TRACK /
   TOO WEAK via hands_needed)` and the milestone sentence in a STATUS block at the top of every user message. Delete the pivot prose.
2. **Rewrite §3.3's early list with category tags** and remove the contradictions: Half Joker → `[PAIR]`; Ride the Bus → `[PAIR, no-face]`;
   Green/Banner/Delayed Gratification → `[KEEP-DISCARDS]` B-tier; add Smeared, Four Fingers, Droll, Crafty, Tribe, suit +3 jokers as
   `[MAIN]` for Flush; Baron/Loyalty out of "reliable xMult".
3. **Make the analyser conservative**: floor estimates, WINS only at ≥1.10× remaining, suggested-discard indices, suggested consumable
   targets, Death/Judgement/Soul validation, and the estimate-vs-actual log that doubles as the unit-test corpus.
4. **Move reference material into the renderer**: a static `JOKER_NOTES` (150 rows: tag, tier, hint, trap), `CONSUMABLE_NOTES` (tarot/
   spectral verdict + target count), `BOSS_NOTES` (one-line counter + which builds it hits). Prose rulebook ≤40 lines per phase.
5. **Prompt layout**: static text to `system` (3–4 cached phase variants, ≤2,000 tokens), STATUS → analyser → state → memory → DECIDE NOW
   (≤6 lines, same tokens). Budget ≤3,500 tokens for PLAY, ≤5,000 for SHOP/PACK. One worked example per phase in the static part.
6. **Memory**: outcome per action (`Flush scored 1,420 (est 1,300) → 2,100/4,000, 2 hands left`), round log (blind, target, scored,
   hands used), build summary, last failure verbatim with "do not repeat". Drop the generic "Strategic Context" text.
7. **Harness pre-decisions behind manifest flags**: auto joker reorder at `next_round`, auto-use MAIN_HAND planets, vetoes for Buffoon-
   with-full-slots / card+skip / bad Death targets / discarding a WINS play, loop guard on `rearrange`, max 600 calls, `tool_choice:
   required` when thinking is off, `reasoning` first in every schema and stripped before the RPC.
8. **PLAY-phase "Suggested action" line as a manifest toggle**, and an evaluation protocol: 5 seeds × 3 runs for {analyser only, analyser
   + suggestion}, reporting death ante/blind, hands used per blind, xMult count at death, estimate error. Without this you cannot tell
   which change helped.
9. **Economy simplification**: three lines (Ante 1–2 no floor; Ante 3 $15; Ante 4–6 $25; Ante 7 $10; Ante 8 $0) + whitelist of floor
   exceptions (XMULT, $0 item, Grabber/Paint Brush/Antimatter, STATUS = TOO WEAK). No rerolls in Antes 1–2; max 1 in Ante 3, max 2 later.
   Drop "multiple of $5". Add Hieroglyph/Petroglyph and Director's Cut/Retcon to "never".
10. **Boss preparation as state, not rules**: SHOP header shows the upcoming boss, whether it hits MAIN_HAND/deck (computed), and the
    one-line counter; fill The Ox/Wheel variables. Keep only the *active* boss's counter in the PLAY prompt.

---

## 6. Two things the plan should say out loud

- **The ceiling of this plan is Ante 6–7, not a reliable win.** With Flush L4, three flat jokers (+30) and one ×2, a hand is ≈ (80+42)
  × 40 × 2 ≈ 9,800: Ante 5 boss in 3 hands, Ante 6 boss (40k) in 4 hands with no margin. Winning needs the second xMult by Ante 6 *and*
  a levelled hand; the shop rule "[XMULT] outranks everything from Ante 3" is the lever, and the model must be willing to sell a +Mult
  joker to make room (the current "never sell" culture is the opposite of what wins).
- **Measure before adding prose.** Every added rule costs attention. The analyser + STATUS block + tags will fix most of the observed
  deaths (arithmetic, hand burning, no xMult). Add strategy text only for failure modes visible in the recorded runs.

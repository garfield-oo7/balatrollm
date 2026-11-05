# 00 — MASTER PLAN: Teaching a small LLM to beat Balatro (Red Deck / White Stake)

> **Revision 3 (community-consensus review, `07-community-consensus.md`).** It overrides R1 and the milestone
> sentence in R5.
>
> **R1″ (owner decision, supersedes R1′'s default): MAIN_HAND defaults to a plain Pair.** Two Pair only with
> Spare Trousers, Mad Joker or Clever Joker. A Pair is in ~89% of 8-card hands with no discard and ~99% after
> one. Pair jokers (Jolly, Sly, The Duo) still fire on Two Pair, Three of a Kind and Full House when dealt.
>
> **R1′. MAIN_HAND defaults to the Pair family (Two Pair), not Flush.** Measured on an unmodified deck with
> one discard per hand: Two Pair is made about 78% of the time and Flush about 44%. Pair-family hands are immune
> to suit bosses and grow into Full House. Flush is chosen only with Four Fingers, Smeared Joker or The Tribe;
> with 2+ flush jokers and 0 pair jokers; or when half the deck is one suit. Half Joker → Pair;
> The Trio (or Zany + Wily) → Three of a Kind.
>
> **R2′. Only Ante 1 is "open" (owner decision).** In Ante 1, Flush and Straight draws are chased. The bot keeps
> discarding toward a draw marked CHASE while the chance to hit it within the remaining discards,
> 1−(1−p)^discards, is ≥50% and no listed play WINS. This holds even if a Pair keeps pace and even if the draw
> would not win the blind in one hand. When discards run out, it plays the best listed play and tries again
> next hand. From Ante 2, Flush and Straight are not chased: MAIN_HAND is the Pair family, and the shop focuses
> on jokers (4 jokers by the end of Ante 2, 1 reroll allowed in Antes 2–3). Without jokers the estimate is
> exact, so WINS needs 100% of NEED; the 110% margin applies once jokers are involved.
>
> **R5′. GOALS checklist instead of a milestone sentence:**
> - Ante 1: 2 jokers; Ante 2: 3 jokers; Ante 3+: all slots full.
> - 1 xMult by Ante 4, 2 by Ante 6.
> - 1 SCALE joker from Ante 4.
> - MAIN_HAND at level ante−1 from Ante 3.
> - No ECON/CHIPS filler from Ante 5.
> - Hold $25 in Antes 3–6.
>
> PRIORITY is the first unmet goal.
>
> **R12. Pair deck fixing.** Strength, Death and The Hanged Man target ranks. Suit tarots and Lovers are
> [AVOID] for pair plans. Death keeps the junk card on the LEFT, since Death copies right → left.

> **Revision 2 (after the Fable advisor review, `06-fable-advisor-review.md`).** The review is accepted with the
> changes below. They **override** the corresponding parts of the v1 plan (kept underneath for traceability).
>
> **R1. MAIN_HAND is a harness fact, not a model decision.** `analysis.main_hand_plan(G)`: Flush by default;
> own The Duo → Two Pair family; Ante ≥ 3 with ≥ 2 pair-family jokers and 0 flush jokers → Two Pair family;
> own The Tribe / Smeared Joker / Four Fingers → Flush (locked). The pivot prose is deleted from the prompt.
>
> **R2. Antes 1–2 play rule has no hand loyalty:** "play the listed play marked WINS; else discard the
> `Suggested discard` indices; else play the highest listed play". Loyalty (planets, Supernova, Card Sharp, Ox)
> only matters from Ante 2+ and is carried by MAIN_HAND.
>
> **R3. Joker list fixed and moved into the state as tags.** A static `JOKER_NOTES` table (tag, tier, family,
> hint) is rendered next to every joker (owned, shop, Buffoon pack). Tags: `[XMULT] [MAIN] [MULT] [SCALE]
> [CHIPS] [ECON] [UTIL] [TRAP] [OFF-PLAN] [KEEP-DISCARDS]`. Corrections: Half Joker = pair family (dead on
> 5-card plays); Ride the Bus = pair family, no faces; Green Joker / Banner / Delayed Gratification =
> `[KEEP-DISCARDS]` B-tier; Smeared Joker, Four Fingers, Droll, Crafty, The Tribe, suit +3 jokers = `[MAIN]`
> for Flush; Baron and Loyalty Card are not "reliable xMult"; Supernova A not S.
>
> **R4. Conservative analyser.** Floor estimates (Misprint → 0, Lucky → 0, Bloodstone → ×1); `WINS` only when
> floor ≥ 1.10 × remaining; unknown jokers printed as exclusions; `Suggested discard` indices toward
> MAIN_HAND; suggested consumable targets; estimate-vs-actual logged per play (memory feedback + calibration data).
>
> **R5. STATUS block with CAPS tokens** at the top of every user message (NEED, PER_HAND, HANDS, DISCARDS,
> MAIN_HAND, FLOOR, SPENDABLE, SLOTS_FREE, XMULT_OWNED, STATUS) plus a computed milestone sentence; the rulebook
> and the final DECIDE NOW block (≤ 6 lines) reference the same tokens verbatim.
>
> **R6. Power check redefined:** `hands_needed = ceil(next target / mean of last 3 play scores)`;
> ON TRACK if ≤ 3, TOO WEAK if ≥ 4 (the "won with ≥ 2 hands left" rule would read TOO WEAK at every Ante 4+).
>
> **R7. Prompt layout & budget:** static rulebook in the `system` role (one cached variant per phase, ≤ ~2k
> tokens); user message = STATUS → analyser → state → memory → DECIDE NOW. PLAY ≤ ~3.5k tokens total, SHOP/PACK
> ≤ ~5k. One worked example per phase. Imperative, numbered rules; whitelists; no double negatives.
>
> **R8. Harness pre-decides mechanical things, behind manifest flags** (so `default` is unchanged): joker
> re-order before leaving the shop; vetoes for strictly bad/illegal moves (Buffoon pack with full slots,
> `card`+`skip`, >5 cards, wrong Death/Judgement/Soul usage, discarding a WINS play); loop guard on repeated
> `rearrange`. A PLAY-phase `Suggested action` line is a manifest toggle so it can be A/B tested.
>
> **R9. Economy simplified:** floor Ante 1–2 $0, Ante 3 $15, Ante 4–6 $25, Ante 7 $10, Ante 8 $0; floor
> exceptions are a whitelist (XMULT joker, $0 item, Grabber / Paint Brush / Antimatter, STATUS = TOO WEAK).
> No rerolls in Antes 1–2; max 1 in Ante 3; max 2 later. "Multiple of $5" dropped. Never buy: Hieroglyph,
> Petroglyph, Director's Cut, Retcon (and the Merchant/Tycoon/Magic Trick/Illusion/Omen Globe/Hone/Glow Up set).
> First shop: buy a scoring joker **and** the Buffoon pack if affordable. Hermit at ≥ $10.
>
> **R10. Bosses as state:** SHOP and Small/Big headers show the upcoming boss, whether it hits MAIN_HAND or the
> deck (computed: suit bosses vs flush suit, Plant vs face cards), and its one-line counter; The Ox `#1#` is filled.
> Only the active boss's counter is shown in PLAY.
>
> **R11. Evaluation protocol:** 5 seeds × 3 runs for {analyser only, analyser + suggested action}; report death
> ante/blind, hands used per blind, xMult count at death and estimate error. Add rules only for failure modes seen
> in recorded runs.
>
> **Expectation (stated plainly):** this plan's realistic ceiling for a Haiku-class model is Ante 6–7; winning
> needs a second xMult by Ante 6 plus a levelled main hand, which is why `[XMULT]` outranks everything from Ante 3
> and selling a flat joker to make room is encouraged.

Inputs: research reports 01–05 in this folder (jokers, hand play, economy, bosses/consumables, harness audit).
Baseline: `default` strategy + Claude Haiku → best run reached **round 12 / 24 (Ante 4 Boss, 10,000 chips)**.
A strong rule-based bot with an exact scorer (JackPotts) has a *median* of Ante 4 on Red Deck, so Haiku is
currently playing like a decent heuristic bot. To go further we must fix **information** (what the model sees)
and **decision rules** (what it is told to do), not just add more prose.

---

## 1. Diagnosis — why runs die around Ante 4

| # | Root cause | Evidence | Fix (section) |
|---|---|---|---|
| 1 | **The model does all arithmetic/combinatorics in its head** (best hand, score estimate, flush odds, chips still needed). Small models get this wrong constantly. | Harness audit: real run plays Pair of 6s + 3 fillers on hand 1 (44 pts vs 300 needed). No score/odds info in the prompt. | Hand analyser (§4.1) |
| 2 | **Harmful rule in the prompt**: "if you can score ANY points, play max cards rather than discarding". Burns the scarce resource (hands, $1 each) instead of free discards. | STRATEGY.md.jinja:551; observed in run fixtures | New play procedure (§3.2) |
| 3 | **No xMult transition.** Targets double per ante (A4 boss 10k, A5 22k, A6 40k). Flat +Mult jokers grow linearly. Nothing in the prompt says "you need ≥1 xMult by Ante 4, ≥2 by Ante 6" or which jokers are xMult. | Reports 01 §1.2, 02 §2 (levels alone top out at 1–3k) | Joker policy (§3.3) |
| 4 | **Boss blind blindness.** The upcoming boss is in the gamestate during SHOP but the template doesn't render it → no preparation. Several boss counters in the prompt are wrong (Psychic "incompatible with pairs"). | Reports 04, 05 (I-11) | Boss prep (§3.5, §4.4) |
| 5 | **No memory of outcomes.** History = last 10 `{method, params}`; no scores, no round results, no build summary; template renders a field that doesn't exist (`entry.reasoning`). After ~1 round the model forgets its plan. | Report 05 I-1, D-3 | Memory (§4.3) |
| 6 | **Reasoning after commitment.** Tool schema puts `cards` before `reasoning`, so indices are emitted before any thinking. | Report 05 D-1 | Tools (§4.2) |
| 7 | **~45 factual errors** in the current strategy (High Card 5 chips not 4; Red Deck has 4 discards not 3; Negative is passive; Black Hole "save for Ante 7"; Smiley +5; Four Fingers; Legendary in shop; Death "drag"…). | Error tables in 02, 03, 04 | Rewrite (§3) |
| 8 | **Attention dilution.** 42 KB / ~10.5k-token static encyclopedia sent for every card play; decisive rules buried mid-document; nothing at the end says "decide now". | Report 05 D-4, D-5 | Phase-specific prompt (§4.5) |
| 9 | **Economy without a policy.** "Reach $25" + "never sell jokers" + "don't hoard" contradict each other; no money floor by ante; no power check. | Report 03 | Economy policy (§3.4) |
| 10 | Template data bugs: pack phase has no header, all pack jokers labelled "Common", Standard-pack modifiers never shown, voucher effects empty, poker hands in random order incl. unplayable secret hands. | Report 05 I-2…I-8 | GAMESTATE rewrite (§4.4) |

**Principle for everything below: let code do arithmetic and enumeration; let the LLM choose among enumerated
options using a short, ranked rulebook; keep the rulebook phase-specific and put a "decide now" checklist last.**

---

## 2. The plan — "curriculum" for the model

The game is taught in four layers. Each layer is a short block of rules, and only the layers relevant to the
current phase are rendered.

1. **Core facts** (always, ~40 lines): scoring = Chips × Mult, scoring order, Red Deck resources (4 hands, 4 discards,
   8 hand size), blind table, money rules, card notation.
2. **Game plan by ante** (always, ~25 lines): what "on track" means, the 3 milestones (scorers by Ante 1 boss →
   main hand locked by Ante 2–3 → xMult by Ante 4 / 2× xMult by Ante 6).
3. **Phase rulebook** (only the current phase): PLAY procedure / SHOP procedure / PACK procedure.
4. **Reference cards** (only where needed): joker tiers in SHOP/Buffoon packs, tarot/spectral verdicts in packs
   and when holding consumables, boss counter for the *current/upcoming* boss only (from `G.blinds.boss`).

---

## 3. Strategy content (what the new STRATEGY teaches)

### 3.1 Game plan & milestones (Red Deck, White Stake)

| Ante | Boss target | Goal by end of ante | Money floor in shop |
|---|---|---|---|
| 1 | 600 | 2 scoring jokers (≥1 +Mult). Buy Buffoon pack in first shop if no good joker. | $0 |
| 2 | 1,600 | 3 jokers; main hand chosen (default **Flush**); planets on it | $5 |
| 3 | 4,000 | 4–5 jokers; main hand Lv3+; first xMult or strong scaler | $15 |
| 4 | 10,000 | **≥1 xMult joker**; $25 bank | $25 |
| 5 | 22,000 | xMult #2 hunted; weakest flat joker replaced | $25 |
| 6 | 40,000 | **≥2 xMult**; main hand Lv5+ | $25 |
| 7 | 70,000 | Max power; interest irrelevant | $10 |
| 8 | 100,000 (Violet Vessel 300k) | Spend everything on score; keep 1 cheap joker for Verdant Leaf | $0 |

Floor is waived when: item is free, item is a fitting xMult, Grabber/Paint Brush/Antimatter, or **power check
failed** (last blind won with <2 hands left → "TOO WEAK, spend now").

### 3.2 Playing a hand (SELECTING_HAND procedure)

1. Read the harness line: `Need R more, H hands, D discards → ~R/H per hand`.
2. If any listed play has `✅ wins the blind` → play it (minimal cards unless padding is free and safe).
3. Else if D > 0: discard up to 5 cards not part of the best draw (flush draw ≥4 suited, open-ended straight,
   two pair→full house) or not part of the main-hand plan. **Discards are free; hands are $1 each.**
4. Else play the highest-scoring listed option, padded to 5 with junk **only** if not Psychic-forbidden
   (Psychic *requires* 5), not The Tooth, not Half Joker/Square Joker, and not throwing away suited/held-value cards.
5. Last hand: use all discards first, then play the best option.
6. Order: +Mult cards left of ×Mult (Glass/Poly) cards; jokers `+Chips → +Mult → ×Mult` left→right; Blueprint left of
   its target; Brainstorm copies slot 1.

**Default main hand: FLUSH** (Red Deck: 93% to make within 3 discards, ~2.5 flushes/round; suits are easy to count).
Fallback: Pair/Two Pair padded. Switch to Pair/Two-Pair/Full-House family only if holding ≥2 pair-family jokers and
no flush jokers by end of Ante 2–3.

### 3.3 Joker policy

- **Ante 1–2: buy the first 2–3 scoring jokers you can afford** (any universal +Mult/+Chips).
  S-tier universal early: Gros Michel, Popcorn, Half Joker, Supernova, Joker, Jolly/Droll/Mad, Misprint, Abstract,
  Green Joker, Ride the Bus, Ice Cream, Blue Joker, Banner (Red Deck +120 chips).
- **From Ante 3: xMult first.** Reliable xMult: Cavendish, The Duo/Trio/Tribe (if hand fits), Card Sharp,
  Blueprint/Brainstorm (with target), Acrobat, Ramen, Loyalty Card, Baron (Kings+Steel), Constellation/Hologram (if early).
- **Replacing is correct** when the new joker is clearly stronger (xMult over flat; +15 over +4). Never sell your only
  xMult; never swap for a sidegrade. Sell order: expiring decay → off-plan conditional → economy (Ante 5+) → flat chips →
  flat mult → scaling → xMult.
- **Traps:** Ceremonial Dagger, Madness, Obelisk, Mr. Bones, Burglar, Stuntman, Merry Andy, Erosion, Driver's License,
  conditional jokers whose condition you can't meet (count your deck).
- Economy jokers (Golden, Rocket, To the Moon, Egg, Cloud 9) only as joker #2–#4 in Antes 1–3; sell by Ante 5.

### 3.4 Economy & shop procedure (≤ ~6 actions, then `next_round`)

1. Free item → take. 2. Best joker above floor (ranking above). 3. Main-hand planet → buy + use now.
4. Voucher: Grabber / Paint Brush / Antimatter (always), Clearance Sale / Overstock / Telescope / Nacho Tong / Palette
   (above floor). Never: Merchants/Tycoons, Magic Trick, Illusion, Omen Globe, Hone, Glow Up, Seed Money,
   **Director's Cut/Retcon (no API to reroll the boss)**.
5. Max 1 pack: Buffoon (only with a free slot) > Celestial (main hand) > Arcana; skip Standard/Spectral early.
6. Reroll only if a slot is empty (or no xMult at Ante 4+), nothing worth buying, money stays ≥ floor; ≤2 rerolls.
7. Leave holding a multiple of $5 when near the interest steps.

### 3.5 Bosses — prepare in the shop before, counter in the round

The boss name/effect is shown in every SHOP header. One-line counters (only the active boss is rendered):
Psychic → always 5 cards (pad). Needle → all discards, then 1 best hand. Water → pad every play to cycle.
Mouth → first hand locks the type: make it the main hand. Eye → each type once; plan the sequence. Tooth → play only
scoring cards. Hook → play 5-card hands; don't rely on held cards. Suit bosses → debuffed suit gives 0 chips;
build with other suits or check if base Flush + jokers is enough. Plant → number cards only. Arm → permanent level
loss; win in few hands. Ox → avoid the named hand if money matters and score allows. Wall → 4× target (prep raw score).
Verdant Leaf → sell weakest joker first. Violet Vessel → 6× target.

### 3.6 Consumables

- Planets: use immediately on the main hand (hold only with Observatory). Black Hole: use immediately.
- Tarots S-tier: Empress/Justice/Death/suit converters (flush), Hermit at ≥$20, Temperance ≥$4.
  Targeting: scored-value enhancements on cards you play; Steel/Gold/Blue Seal on cards you hold; Hanged Man on junk.
- Spectrals: safe = Black Hole, The Soul (free slot), Talisman, Deja Vu, Trance, Medium, Aura, Cryptid,
  Grim/Familiar/Incantation. Avoid Ankh/Hex (unless exactly 1 joker), Ouija, Ectoplasm, Wraith (unless broke + slot).
  "If you can't explain why the downside doesn't matter right now, skip."

---

## 4. Harness changes (code) — ranked by expected impact

All changes are additive and strategy-agnostic: new Jinja globals and extra memory kwargs. Existing
`default`/`aggressive`/`conservative` templates keep rendering unchanged.

### 4.1 `src/balatrollm/analysis.py` (new) — ★★★★★
Pure functions registered as Jinja globals in `StrategyManager`:
- `analyze_hand(G)` → best play per hand type with card indices, scoring cards, estimated score (hand level + card
  chips/enhancements/editions/seals + held Steel + common jokers + generic "Currently +X/XN" parsing; unknown jokers
  flagged so the estimate is a floor); flush/straight draws with hit probability from the remaining deck counts
  (`G.cards`, aggregate only — never order); suit/rank tallies.
- `blind_progress(G)` → target, scored, remaining, hands/discards left, per-hand needed.
- `shop_context(G)` → money floor for the ante, interest next round, joker slots free, upcoming blind + boss.
- `deck_summary(G)` → deck size and suit counts (useful for flush commitment and suit tarots).
- `card_name` filter → "King of Hearts".
Unit-tested on synthetic gamestates.

### 4.2 Tools (new strategy's TOOLS.json) — ★★★★
`reasoning` first in every schema and in `required`, with a description that forces "chips needed → hand → indices →
estimate" before choosing cards. maxItems 5 on card arrays.

### 4.3 Memory (bot.py) — ★★★★
- Store `reasoning` separately and an outcome per action (play → hand type + score gained + progress; discard;
  buy → item + money left), plus ante/state.
- Round log at ROUND_EVAL (blind, target, scored, hands left) → used for "power check" and trend line.
- New kwargs to `render_memory`: `rounds`, `build` (most-played hand, levelled hands). Old templates ignore them.
- Fix I-1 (`entry.reasoning`).

### 4.4 GAMESTATE rewrite (new strategy) — ★★★
- Headers for every phase incl. pack; SHOP header shows money floor, interest, slots, **upcoming blind and boss**,
  power check.
- Compact hand list `- 3: King of Hearts (10 chips) · GLASS · RED seal`.
- Poker hands sorted by strength, only the 9 regular + levelled/played secret ones, one line each.
- Pack fixes (modifier paths, no fake rarity, targets table, edition on jokers).
- Remove the duplicated "Tools available" section (tools are already passed as `tools`).

### 4.5 Phase-specific STRATEGY + "Decide now" block — ★★★★
STRATEGY.md.jinja branches on `G.state` (each variant is a stable cached prefix). The final lines of the prompt
(end of MEMORY) contain the phase checklist.

### 4.6 Optional / later
- Rule-based Small-Blind skip (report 03 §6.2), gated per strategy via manifest — **deferred** (small EV, adds risk).
- `tool_choice: required` when extended thinking is off; loop guard on repeated `rearrange`; max-calls cap.

---

## 5. Implementation steps

1. `analysis.py` + register globals in `strategy.py` + unit tests.
2. `bot.py` memory upgrade (backwards compatible).
3. New strategy folder `src/balatrollm/strategies/mastery/` (manifest, STRATEGY, GAMESTATE, MEMORY, TOOLS); keep
   `default` untouched as the A/B baseline.
4. Point `config/example.yaml` at `mastery`; document in docs/strategies.md.
5. Verify: render all templates against synthetic gamestates for each phase; run unit tests.

## 6. Questions for the Fable advisor

1. What should the **early game (Antes 1–3)** strategy be so that a Haiku-class model reliably reaches Ante 5+ with a
   scaling engine? Is "Flush by default" right, or is "Pair/Two-Pair with universal jokers then pivot" safer?
2. Which of the harness changes give the most lift per unit of risk? Anything missing (e.g. per-joker hints, a
   recommended action line)?
3. Is the prompt structure (core facts + ante plan + phase rulebook + reference + decide-now) the right way to
   teach a small model? What would you cut?
4. Any facts in the research that are wrong or any rule that would mislead a small model?

---

## 7. Implementation status (v2)

| Plan item | Where | Status |
|---|---|---|
| Hand analyser, floor estimates, WINS ≥ 1.10×, draws + odds, suggested discard/action (R1, R2, R4) | `src/balatrollm/analysis.py` (`play_advice`, `estimate_play`, `main_hand_plan`) | Done, unit-tested |
| STATUS block with CAPS tokens, milestone + priority, new power check (R5, R6) | `analysis.run_status`, `mastery/GAMESTATE.md.jinja` | Done |
| Inline joker / consumable / voucher / boss annotations with corrected tiers (R3, R10) | `src/balatrollm/knowledge.py` (all 150 jokers) | Done |
| Phase-specific rulebook in the `system` role, worked example per phase, DECIDE NOW tail (R7) | `mastery/STRATEGY.md.jinja`, `mastery/MEMORY.md.jinja`, manifest `harness.system_prompt` | Done (~1.1–1.4k tokens per decision vs ~13.4k for `default`) |
| Reasoning-first tool schemas, max 5 cards | `mastery/TOOLS.json` | Done |
| Outcome memory: per-action result, estimate vs actual, round log (R4 calibration) | `bot.py`, `analysis.summarize_outcome`, `analysis.round_record` | Done (estimate vs actual also logged in `run.log`) |
| Harness pre-decisions behind manifest flags: veto bad moves, auto joker reorder, rearrange loop guard (R8) | `bot.py` + `analysis.validate_action`, `analysis.joker_order` | Done |
| Economy simplification, never-buy list, first-shop Buffoon, no early rerolls (R9) | `mastery/STRATEGY.md.jinja`, `knowledge.VOUCHERS`, `analysis.MONEY_FLOOR` | Done |
| Evaluation protocol (R11) | `config/mastery.yaml` (5 seeds × 3 runs) | Ready to run; needs a live Balatro + API key |
| Rule-based Small-Blind skip, `tool_choice: required`, max-calls cap | — | Deferred (low lift / provider-dependent) |

Not changed on purpose: the `default`, `aggressive` and `conservative` strategies render exactly as before
(except the `default` memory line now shows the reasoning text that it previously tried and failed to render),
so they remain a clean A/B baseline.

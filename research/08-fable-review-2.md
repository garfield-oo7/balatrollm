# 08 — Fable advisor review #2 (Revision 3 checkpoints)

Read-only review of the `mastery` strategy at `d0f8293`. The claims were probed
with `play_advice` and `suggest_targets` and checked with two Monte Carlo
simulations. Status: **applied** means fixed in `fix(mastery): apply Fable review fixes`.

## 1. Bugs and wrong facts

| # | Finding | Status |
| --- | --- | --- |
| 1 | The Ante 1 CHASE rule could discard a made Flush (236 points, at pace) to chase a 220-point Straight. | Applied. No chase when the best play is already a Straight or Flush or better. A draw must beat the best made play by 20%, unless no play reaches pace. |
| 2 | Strength picked chains (6→7 and 7→8): the 7 is upgraded away before the 6 arrives. | Applied. Chains are skipped in both directions, and targets that make trips are preferred. |
| 3 | `[MAIN]` was too coarse. The Trio and The Family were tagged MAIN under Two Pair, and The Family counted toward XMULT_OWNED. | Applied. `knowledge.REQUIRED_HAND` and `MAIN_CONTAINS` mark a joker MAIN only if MAIN_HAND contains the hand it needs. Half Joker is MAIN only for Pair, Three of a Kind or High Card. |
| 4 | An empty "Suggested discard" rendered as `[]`, so the model could send `discard []` and get vetoed. | Applied. It now renders "none: play instead", and the rules say to go to rule 3. |
| 5 | Death's direction is correct. The hand is sorted by rank, high to low, so Death can only turn a higher card into a lower one. The candidate search was capped at 3. | Applied. All candidates are searched. |
| 6 | The $25 goal at Ante 3 conflicted with the $15 money floor; DECIDE NOW left out the ECON rule; reroll limits are prose only. | The goal and DECIDE NOW are applied. Reroll counting with a veto is **open**. |

Mechanics spot-checked as correct: blind table, interest, Red Deck counts,
hand bases, joker and consumable facts, and Blue Seal timing (held at the end
of the round, needs a free consumable slot, creates the planet of the last
played hand).

## 2. Pair default and the Ante 1 chase

The pair default is right. Simulation of the real advisor loop, 250 games per
cell, with the hand kept sorted by rank:

| | no jokers: 300 / 450 / 600 | +4 Joker: 300 / 450 / 600 |
| --- | --- | --- |
| CHASE win rate | 1.00 / 0.94 / **0.72** | 1.00 / 1.00 / 1.00 |
| PAIRS win rate | 1.00 / 0.93 / **0.82** | 1.00 / 1.00 / 1.00 |
| Unused hands, CHASE vs PAIRS | 2.5 vs 1.6, 1.5 vs 1.1, 1.2 vs 1.0 | 3.0 vs 2.4, 2.9 vs 2.1, 2.3 vs 1.8 |

Verdict: keep the chase. With one joker it costs nothing and earns about
$1.5–2.5 per ante. With no jokers at the Ante 1 boss it loses about 10 points
of win rate, so that case is now gated (applied). The 50% cumulative
threshold works out to "always chase with 4 discards", which is acceptable
only because fix #1 protects made hands.

## 3. Blue Seal and economy jokers

**Blue Seal: Fable recommends a downgrade. The owner's rule is kept pending a decision.**
- A held Blue Seal card is a dead card. Two Pair with 1 discard falls from 78%
  to 57% with 7 usable cards (91% to 75% with 2 discards).
- The card is in hand at the end of about 69% of rounds, which gives about 0.6
  planets per round, and only the right planet when the last play was MAIN_HAND.
- Finding one: about 5% per card in a Standard pack, about 14% per $4 pack,
  roughly $28 expected per seal.
- Suggested instead:
  - Drop Standard packs from the pack ranking.
  - Still take a Blue Seal card if one appears in a pack opened for another reason.
  - Prefer the seal on a Steel or Gold card (which are held anyway).
  - Hunt with Standard packs only when hand size is 9+ or Hologram is owned.

**Economy jokers: approved with tighter thresholds** (applied).
- `ECON_OK` = Ante ≤ 3, 2+ scoring jokers, a free slot, and either no economy
  joker yet or (Ante ≤ 2 and 2 free slots). Price must be $7 or less.
- Golden Joker returns about $48 over Antes 1–4. Rocket returns about the same
  and then $9–11 per round, so it is sold last.
- Cloud 9 is tier A only with 4+ nines. To the Moon only when holding $20+.
- Egg, Business Card, Mail-In Rebate, Trading Card, Faceless Joker and Delayed
  Gratification conflict with the discard advisor, so they are skipped.

## 4. Top 5 missing concepts (priority order, open)

1. **Score change per shop item.** Run `estimate_play` on a representative
   MAIN_HAND with each shop joker or planet added, and with each owned joker
   removed. Render "+X per hand" and "WEAKEST: name (−Y)", plus a real score
   gap against the next boss.
2. **Hand size and deck shaping as numbers.** Two Pair odds by hand size are
   57% at 7 cards, 78% at 8 and about 88% at 9. That makes Paint Brush,
   Palette, Juggler and Turtle Bean must-buys for pair plans. Discards should
   keep the unpaired cards with the most copies left in the deck. Hanged Man
   should target thin ranks.
3. **Feed the scaling jokers.** Add a "NEEDS" line per owned scaling or xMult
   joker (Ride the Bus, Supernova, Spare Trousers, Constellation, Hologram,
   Castle) and wire it into the play and discard suggestions.
4. **MAIN_HAND ladder to Full House.** Switch to Full House when its level is
   at least Two Pair's, or when 3+ ranks have 4+ copies. Add a Two Pair →
   Full House draw line.
5. **Tags and in-round boss state.** Allow skipping Small blinds in Antes 1–3
   for a whitelist of tags when ON TRACK. Include the Cerulean Bell forced
   card in plays. Show The Needle as "NEED in ONE hand". Track cards already
   played this ante for The Pillar.

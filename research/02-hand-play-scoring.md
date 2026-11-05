# 02 — Hand Selection, Scoring Math, Play-vs-Discard, Hand Leveling, Blind Requirements

Scope: vanilla Balatro v1.0.1 rules. Benchmark: **Red Deck (4 hands, 4 discards, hand size 8), White Stake**.

Where the facts come from: balatrowiki.org and balatrogame.fandom.com were **blocked** in this sandbox (DNS refused), so WebFetch did not work. Facts were checked against WebSearch snippets (sources at the end) and my own knowledge of the game. The probability tables were computed with exact hypergeometric formulas and a Monte Carlo script (40k trials, simple greedy policy, unmodified 52-card deck). Anything not confirmed is marked **(unverified)**.

---

## 0. TOP 15 RULES FOR A SMALL LLM

1. **Do the math before every action.** `remaining = target − current_score`, then `need_per_hand = remaining / hands_left`. If your best playable hand scores at least `remaining`, play it now and win the round.
2. **Hands are scarce; discards are free.** A discard costs no money and gives no money. Each hand left unused when you win pays **$1**. Use discards to improve the hand *before* you spend a hand. Never spend a hand on a weak play only to cycle cards while you still have discards.
3. **Always discard the maximum allowed (5 cards)**, unless a card is part of the hand you are building. More cards drawn means better odds.
4. **Never break a hand that already wins.** If the made hand beats `remaining`, play it, even when a "better" draw exists.
5. **Commit to one main hand type (default: FLUSH).** Level only that hand with Planets. Buy jokers that boost it. Pick a fallback hand that fits it (Pair or Two Pair).
6. **Play 5 cards when it is free.** Pad a Pair, Two Pair, Trips or Quads with junk cards you don't need. Unscored cards are a free discard. Don't pad with The Tooth, Half Joker, Square Joker, or with cards you want to keep (suited cards for a flush, Steel cards, Kings for Baron).
7. **Hard limit: 1–5 cards per play or discard.** Indices are 0-based. Before you call the tool, list each chosen card as rank+suit, name the hand type, and count the cards.
8. **The game always scores the BEST hand in the played cards.** Five hearts that include a pair score as a Flush. Only the cards that form the hand score (Pair = 2 cards, Two Pair = 4, Trips = 3, Quads = 4, everything else = all 5, High Card = 1). Stone cards always score. With Splash, every played card scores.
9. **Card chips: A = 11, K/Q/J = 10, 2–10 = face value, Stone = 50.** Hand-type base chips and mult come from the **current level shown in the game state**. Read those numbers; don't compute them from memory.
10. **Scoring order:** hand base, then each scoring card left to right (its chips, +mult, xmult, then per-card jokers), then cards held in hand (Steel, Baron), then jokers left to right. Mult changes one step at a time, so **put +Mult before xMult**: +Mult jokers on the left, xMult jokers on the right. Chip order never matters.
11. **Flush draw math:** 4 cards of one suit plus 1 discard of 4 cards hits about **60%**, 2 discards about **85%**, 3 discards about **95%**. Open-ended straight draw: about 57% per 4-card discard. Gutshot: about 33%. Pair to trips: only about 20%. Don't chase it.
12. **On track?** At the start of each ante, your normal main hand should score at least **1/3 of that ante's Boss target** (A1 200, A2 530, A3 1.3k, A4 3.3k, A5 7.3k, A6 13k, A7 23k, A8 33k). If it can't, spend money on scoring now (jokers first, then planets for the main hand) instead of saving for interest.
13. **Debuffed cards** (red X) still count toward the hand type, but they add 0 chips and trigger nothing. Don't count them in your score estimate.
14. **Use every planet for your main hand right away. Use Black Hole right away.** Levels are permanent and pay off every round. With Observatory, *hold* main-hand planets instead (each one held gives x1.5 Mult).
15. **Boss quick rules:** Psychic: pad to 5 cards. Needle: one hand only, so use all discards first. Water: 0 discards, so pad plays. Hook: 2 random held cards are discarded after each play. Eye: no hand type twice. Mouth: only your first hand type scores, so play your main type first. Tooth: play only the scoring cards. Ox: avoid your most-played hand if money matters. Wall: 4x target. Violet Vessel: 6x target.

---

## 1. ERRORS FOUND IN CURRENT STRATEGY.md (my area, plus a few nearby)

| # | Location / claim in STRATEGY.md.jinja | Problem | Correction |
|---|---|---|---|
| 1 | High Card "Base Chips: 4" | Wrong, and its own example uses 5 | **High Card = 5 chips × 1 mult** |
| 2 | "There are 10 hand types" (only 9 listed) | Count wrong; secret hands missing | 9 regular hands (Royal Flush is a Straight Flush) + 3 secret: **Five of a Kind 120×12, Flush House 140×14, Flush Five 160×16** |
| 3 | "There are 9 Planet Cards" | Missing secret planets | 12 planets: add **Planet X** (5oak +35/+3), **Ceres** (Flush House +40/+4), **Eris** (Flush Five +50/+3). These appear only after you play the hand that run |
| 4 | Score formula `(…)×(Base Mult + Mult Additions)×Mult Multipliers` | Wrong in general. xMult multiplies the running mult *at its point in the sequence*; +Mult added after an xMult is not multiplied. The prompt itself contradicts this later | Use the ordered procedure in §4. The formula holds only when every +Mult comes before every xMult |
| 5 | "Order of Operations: Boss Blind effects first, then Jokers and card effects trigger as cards are scored" | Imprecise. Jokers' independent effects run **after all scoring cards and held cards**, not interleaved with them | Order: base → scoring cards (with per-card jokers) → held cards → jokers left to right (§4) |
| 6 | "place cards with multiplicative effects (Glass, Polychrome) rightmost in your played hand" | Direction is right, but it leaves out that (a) scoring order is the cards' **left-to-right position in hand** (use `rearrange`), (b) a Glass x2 does **not** multiply any joker +Mult (jokers come later), and (c) it only matters if other scoring cards add +Mult | See §7 |
| 7 | Hidden-discard example: play `S_K, D_K, H_3, S_7` then "draw 3 new cards" | Arithmetic error | Playing 4 cards draws **4** |
| 8 | "Rule of thumb: If you can score ANY points, play the hand with maximum cards rather than discarding" | **Harmful.** You get only 4 hands and every unused hand pays $1. Discards are free. Following this wastes hands and loses blinds | Discard first to build a strong hand. Pad a hand with junk only when you were going to play it anyway |
| 9 | "The Psychic: Must play 5 cards — incompatible with Pair/Two Pair/Trips strategies" | Wrong. Unscored filler cards satisfy the rule | Play Pair + 3 junk (Psychic is only a problem with Half Joker, Square Joker or The Tooth) |
| 10 | "Black Hole: Save for Ante 7+" | Wrong. Holding it uses a slot and wastes every round it could have helped | Use immediately |
| 11 | "Smiley Face (+4 Mult for face cards)" | Value wrong | **+5 Mult** per scored face card |
| 12 | "Four Fingers (all 4-card hands count as Flushes)" | Wrong | **Flushes and Straights** can be made with 4 cards |
| 13 | Initial Setup: "4 hands and 3 discards"; gives only the Ante 1 targets | Benchmark is Red Deck = **4 discards**; full blind table missing | Add the §3 table and "Red Deck: 4 hands, 4 discards" |
| 14 | "The Wall: Extra large blind", "Violet Vessel: Very large blind" | Size not given | Wall = **4× base**, Violet Vessel = **6× base** (300,000 at Ante 8), The Needle = **1× base** |
| 15 | Joker/card edition "Negative: +1 Joker Slot when scored" | Negative is passive, not "when scored" | Negative joker = +1 joker slot (always on) |
| 16 | "Mime (retriggers all cards held in hand)" | Imprecise | Retriggers the **held-in-hand abilities** (Steel, Baron, Shoot the Moon, Gold end-of-round, etc.) |
| 17 | "Maintain at least two viable hand types by Ante 3" vs "commit fully … skip Jokers that boost other hand types" | Contradictory advice for a small model | Main type + one fallback *in the same family* (Flush, with Pair/Two Pair as fallback) |

Planet increments for the 9 regular planets in STRATEGY.md are **all correct** (Pluto +10/+1, Mercury +15/+1, Uranus +20/+1, Venus +20/+2, Saturn +30/+3, Jupiter +15/+2, Earth +25/+2, Mars +30/+3, Neptune +40/+4). The worked examples for the 9 hands also check out arithmetically.

---

## 2. Hand types: base values, per-level gains, scoring cards

Hand priority, from strongest to weakest. The game always picks the highest hand the played cards contain.

| Hand | L1 Chips × Mult | Planet | +Chips / +Mult per level | Cards that score |
|---|---|---|---|---|
| Flush Five (secret) | 160 × 16 | Eris | +50 / +3 | all 5 |
| Flush House (secret) | 140 × 14 | Ceres | +40 / +4 | all 5 |
| Five of a Kind (secret) | 120 × 12 | Planet X | +35 / +3 | all 5 |
| Straight Flush (incl. Royal) | 100 × 8 | Neptune | +40 / +4 | all 5 |
| Four of a Kind | 60 × 7 | Mars | +30 / +3 | the 4 matching |
| Full House | 40 × 4 | Earth | +25 / +2 | all 5 |
| Flush | 35 × 4 | Jupiter | +15 / +2 | all 5 |
| Straight | 30 × 4 | Saturn | +30 / +3 | all 5 |
| Three of a Kind | 30 × 3 | Venus | +20 / +2 | the 3 matching |
| Two Pair | 20 × 2 | Uranus | +20 / +1 | the 4 paired |
| Pair | 10 × 2 | Mercury | +15 / +1 | the 2 paired |
| High Card | 5 × 1 | Pluto | +10 / +1 | the 1 highest |

Level N value = L1 + (N−1) × increment. The game state shows current chips and mult per hand, so use those numbers.

**Scoring-card rules**
- Kickers don't exist. Unscored played cards add nothing, but they are removed and replaced, so they act like a free discard.
- **Stone cards** always score (+50 chips, no rank or suit) and don't change the hand type.
- **Splash** (joker): every played card scores, so padding cards add their chips.
- **Four Fingers**: Flush and Straight need only 4 cards. In a 5-card play, the off-suit or out-of-sequence 5th card does not score (unverified).
- **Shortcut**: straights may skip one rank (e.g. 2-4-5-7-8; unverified exact gap rule: gaps of 1 rank).
- Straights: Ace is high (10-J-Q-K-A) or low (A-2-3-4-5). **No wrap-around** (Q-K-A-2-3 is not a straight).
- **Wild Card** counts as every suit (helps flushes). A debuffed Wild card reverts to its own suit.
- **"Contains"** for jokers: a hand "contains a Pair" if any two played cards share a rank. That includes Two Pair, Trips, Full House and Quads, and also a Flush that has a duplicate rank (unverified for the Flush case). This is how Jolly (+8 Mult), Zany, Mad, Crazy, Droll, Sly, Wily, Clever, Devious, Crafty, The Duo, Trio, Family, Order, Tribe and Spare Trousers trigger.

**Typical L1 score, no jokers** (average scoring-card chips in brackets):

| Hand | L1 | L2 | L3 | L5 |
|---|---|---|---|---|
| High Card (A) | 16 | 52 | 108 | 280 |
| Pair (~20) | 60 | 135 | 240 | 540 |
| Two Pair (~30) | 100 | 210 | 360 | 780 |
| Three of a Kind (~27) | 171 | 385 | 679 | 1,507 |
| Straight (~40) | 280 | 700 | 1,300 | 3,040 |
| Flush (~42) | 308 | 552 | 856 | 1,644 |
| Full House (~40) | 320 | 630 | 1,040 | 2,160 |
| Four of a Kind (~36) | 672 | 1,260 | 2,028 | 4,104 |

Takeaway: hand levels alone top out around 1–3k. **Ante 4+ (Boss 10k) needs jokers.** +Mult jokers by Ante 2–3, xMult jokers by Ante 4–5.

---

## 3. Blind score requirements (White Stake)

Small = 1× base, Big = 1.5×, Boss = 2× (exceptions: **The Wall 4×**, **The Needle 1×**, **Violet Vessel 6×**). Base per ante: 300, 800, 2000, 5000, 11000, 20000, 35000, 50000 (Ante 3/4 values set by the 1.0.1-era rebalance from 2800/6000). The win is beating the **Ante 8 Boss (Showdown)**. Rewards: Small **$3**, Big **$4**, Boss **$5**, plus **$1 per unused hand** and interest of $1 per $5 held (max $5).

| Ante | Small | Big | Boss (2×) | Boss/4 hands | Boss/3 hands | Wall (4×) | Needle (1×, 1 hand) |
|---|---|---|---|---|---|---|---|
| 1 | 300 | 450 | 600 | 150 | 200 | – | – |
| 2 | 800 | 1,200 | 1,600 | 400 | 533 | 3,200 | 800 |
| 3 | 2,000 | 3,000 | 4,000 | 1,000 | 1,333 | 8,000 | 2,000 |
| 4 | 5,000 | 7,500 | 10,000 | 2,500 | 3,333 | 20,000 | 5,000 |
| 5 | 11,000 | 16,500 | 22,000 | 5,500 | 7,333 | 44,000 | 11,000 |
| 6 | 20,000 | 30,000 | 40,000 | 10,000 | 13,333 | 80,000 | 20,000 |
| 7 | 35,000 | 52,500 | 70,000 | 17,500 | 23,333 | 140,000 | 35,000 |
| 8 | 50,000 | 75,000 | 100,000 | 25,000 | 33,333 | – (Showdown) | – |
| 8 Violet Vessel | | | **300,000** | 75,000 | 100,000 | | |

Average per hand for Small/Big with 4 hands: A1 75/113 · A2 200/300 · A3 500/750 · A4 1,250/1,875 · A5 2,750/4,125 · A6 5,000/7,500 · A7 8,750/13,125 · A8 12,500/18,750.

Minimum boss ante (unverified): Wall and Needle appear from Ante 2, Eye and Tooth from 3, Plant from 4, Serpent from 5, Ox from 6. Ante 8's boss is always a Showdown boss.

**Gauge rule:** plan to clear each blind in **3 hands** (keep 1 spare hand for a bad draw, which also pays $1). If your main hand can't reach `target/3` with average draws, you are behind. Prioritize score over interest in the next shop.

---

## 4. Step-by-step scoring procedure (the LLM can follow this)

Two running numbers, **CHIPS** and **MULT**. Final score = CHIPS × MULT (rounded down). Every "+chips" adds to CHIPS, every "+mult" adds to MULT, and every "xmult" sets MULT = MULT × x **at that moment**.

0. **Boss adjustments**: The Arm lowers the hand level by 1 first. The Flint halves base chips and mult. Debuffed cards are skipped in steps 2–3. If a restriction boss (Eye, Mouth, Psychic) is violated, the hand scores 0.
1. **Base**: CHIPS = hand-level chips, MULT = hand-level mult (from game state). "Before-scoring" jokers update here (e.g. Spare Trousers, Ride the Bus, Green Joker, Square Joker, Runner, Obelisk grow; Space Joker may level the hand).
2. **Each scoring card, left to right in its on-screen order:**
   a. +rank chips (A 11, K/Q/J 10, number = value; Stone = 50 instead) plus permanent bonus chips (Hiker).
   b. Enhancement: Bonus +30 chips · Mult +4 mult · Lucky (1 in 5) +20 mult · Glass ×2 mult.
   c. Edition: Foil +50 chips · Holographic +10 mult · Polychrome ×1.5 mult.
   d. Gold Seal: +$3 (money only).
   e. Per-card ("when scored") jokers, in joker order: e.g. Greedy/Lusty/Wrathful/Gluttonous +3 mult per suit card, Smiley +5 mult per face card, Scary Face +30 chips per face card, Fibonacci +8, Even Steven +4, Odd Todd +31 chips, Scholar (Ace +20 chips +4 mult), Walkie Talkie (10/4 +10 chips +4 mult), Arrowhead (Spade +50 chips), Onyx Agate (Club +7 mult), Photograph (first face card ×2), Triboulet (K/Q ×2), The Idol, Ancient Joker (×1.5 per suit card), Bloodstone (Heart 1 in 2 ×1.5).
   f. Retriggers (Red Seal, Hack on 2–5, Sock and Buskin on faces, Hanging Chad on the first card, Dusk on the last hand, Seltzer) repeat a–e for that card.
   (The exact order inside a–c may differ, e.g. edition before or after Glass. Unverified, and it rarely matters.)
3. **Cards held in hand, left to right**: Steel ×1.5 mult each. Baron ×1.5 per King held. Shoot the Moon +13 mult per Queen held. Raised Fist +2× the rank of the lowest held card. Mime / Red Seal retrigger these. Gold cards and Blue Seals pay out at **end of round**, not now.
4. **Jokers, left to right**: each joker's Foil (+50 chips) or Holographic (+10 mult) edition applies *before* its own effect; its Polychrome (×1.5) applies *after* (community consensus). Then the joker effect: flat +Mult (Joker +4, Jolly +8 …), +Chips (Banner, Blue Joker, Stuntman …), ×Mult (Cavendish ×3, The Duo ×2, The Tribe ×2, Card Sharp ×3 …). Blueprint copies the joker to its right; Brainstorm copies the leftmost joker. Baseball Card triggers per Uncommon joker.
5. **Score = floor(CHIPS × MULT)**. Add it to the round score. After scoring, Glass cards have a 1 in 4 chance to break.

**Quick estimate** (valid when every +Mult sits before every xMult):
`(hand_chips + Σ scoring-card chips + Σ +chips) × (hand_mult + Σ +mult) × Π xmult`

**Worked example** (Flush L2 = 50 × 6). Played hearts in order: 9 (Mult card), 5, 3, A, K (Glass). Holding 1 Steel card. Jokers in order: Lusty Joker (+3 per Heart scored, per card), Joker (+4), Droll (+10 if Flush), Cavendish (×3).
- H9: chips 59, mult 6+4 = 10, then Lusty +3 = 13 · H5: 64 / 16 · H3: 67 / 19 · HA: 78 / 22 · HK Glass: 88 / 22×2 = 44, then Lusty +3 = 47
- Steel held: 47 × 1.5 = 70.5 · Joker +4 = 74.5 · Droll +10 = 84.5 · Cavendish ×3 = 253.5
- **Score = 88 × 253.5 = 22,308.** With the Glass K played *first*: 15,972 (−28%). With Cavendish moved leftmost: 19,844.

---

## 5. Play vs discard: probability and rules

### 5a. Single-discard odds (deck of 44 unseen cards after the first 8 are dealt)

P(at least one out) when drawing n cards:

| Draw situation | Outs | 1 card | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| 4-card flush → Flush | 9 | 20% | 37% | 51% | **61%** | 70% |
| Open-ended straight (e.g. 5-6-7-8) | 8 | 18% | 33% | 46% | **57%** | 65% |
| Gutshot / one-ended straight | 4 | 9% | 18% | 25% | 33% | 39% |
| Two Pair → Full House | 4 | 9% | 18% | 25% | **33%** | – |
| Pair → Trips | 2 | 5% | 9% | 13% | 18% | 22% |
| Trips → Quads | 1 | 2% | 5% | 7% | 9% | 11% |
| 3-card flush → Flush (need 2) | 10 | 0% | 5% | 12% | 22% | 32% |

Cumulative cards seen across several discards (same deck): 4-flush hits **87% within 8 cards, 93% within 10**. Open-ended straight: 83% within 8, 90% within 10. 3-flush: 59% within 8, 74% within 10, 93% within 15.

Quick formula: P(hit) ≈ 1 − (1 − outs/deck_left)^cards_drawn. Flush outs = 13 − (cards of that suit already seen this round: in hand, played or discarded). The deck resets to the full deck every round.

### 5b. Making each hand type from 8 cards (Monte Carlo, greedy keep, discard up to 5)

P(hand is made with at most k discards):

| Target | k=0 | 1 | 2 | 3 | 4 (Red Deck max) |
|---|---|---|---|---|---|
| Pair (or better) | 89% | 99% | 100% | 100% | 100% |
| Two Pair | 44% | 77% | 91% | 96% | 98% |
| Three of a Kind | 12% | 33% | 51% | 65% | 76% |
| Straight | 10% | 38% | 62% | 78% | 88% |
| **Flush** | 7% | 45% | 77% | **93%** | 98% |
| Full House | 6% | 29% | 52% | 70% | 82% |
| Four of a Kind | 0% | 3% | 7% | 14% | 23% |

Times you can play the type in one round (4 hands, 4 discards; discard when not made, otherwise play it padded with junk):

| Type | Avg plays/round | P(≥1) | P(≥2) | P(≥3) | Avg with 3 discards (other decks) |
|---|---|---|---|---|---|
| Two Pair | 3.5 | 100% | 97% | 89% | 3.3 |
| **Flush** | **2.5** | 100% | 89% | 50% | 2.1 |
| Straight | 2.05 | 96% | 71% | 32% | 1.7 |
| Three of a Kind | 1.9 | 94% | 63% | 25% | – |
| Full House | 1.7 | 91% | 57% | 20% | – |

Red Deck's extra discard is worth about +0.4 flushes per round.

### 5c. Decision procedure for each SELECTING_HAND turn

1. `R = target − current_score`, `H = hands_left`, `D = discards_left`.
2. List what the 8 cards can make (main type first) and estimate each score (§4).
3. **If the best hand scores ≥ R, play it** (win now and bank the unused hands as $).
4. Else, if D > 0 and the best hand is below `R/H` (or you hold a good draw: 4-flush, open-ended straight, two pair aiming for a full house), **discard** up to 5 cards that are not part of the draw.
5. Else, **play the best hand**, padded to 5 cards with junk (see 5d).
6. Last hand (H = 1): first use **all** remaining discards to improve, then play the highest-scoring hand.
7. Budget: with H hands and D discards, use about D/H discards before each play. Spend more early when you hold a strong draw.

### 5d. The "junk padding" nuance

Playing Pair + 3 unneeded cards replaces 5 cards instead of 2, for the same score. Do it whenever you play a sub-5-card hand, **except**:
- **The Tooth**: −$1 per card played, so play only the scoring cards.
- **Half Joker**: +20 Mult only if the hand has ≤3 cards. **Square Joker**: grows only on exactly 4 cards.
- **The Psychic** *requires* 5 cards. Pad, or the hand scores 0.
- Don't throw away cards you are building toward (same-suit cards for the flush, straight connectors), or cards that work while held (Steel, Kings with Baron, Queens with Shoot the Moon, Gold cards until round end, Blue Seal cards on your final hand).
- **Ride the Bus** resets only if a face card *scores*. Unscored junk faces are fine.
- **Splash**: padding cards score too, so pad with your highest chip cards.
- Padding is not a reason to spend a hand. Spend hands only when the score is needed, or when D = 0.

### 5e. Discards and money

- In vanilla, discards neither cost nor pay money. **Only unused hands pay ($1 each).** So use discards freely and finish in as few hands as possible. Extra score beyond the target ("overkill") is worthless.
- Exceptions that make you *keep* discards: **Banner** (+30 chips per remaining discard), **Delayed Gratification** ($2 per discard if none used by round end), **Green Joker** (−1 mult per discard), **Ramen** (loses ×0.01 per card discarded).
- Exceptions that reward *using* them: **Mystic Summit** (+15 mult when 0 discards left), Hit the Road, Castle, Yorick, Faceless Joker, Mail-in Rebate, Trading Card, Burnt Joker, Purple Seal (Tarot when discarded).

---

## 6. Which hand type to commit to (Red Deck, White Stake, small LLM)

| Hand | Consistency (avg/round) | L1 base | Scaling per planet | Ease for an LLM | Verdict |
|---|---|---|---|---|---|
| Pair | always | 10×2 | +15/+1 (weak) | trivial | Fallback only; good with The Duo, Jolly, Sly, Spare Trousers |
| Two Pair | 3.5 | 20×2 | +20/+1 (weak) | easy | Strong *with* jokers (Mad, Spare Trousers, Jolly, Zany via contains); weak base |
| Three of a Kind | 1.9 | 30×3 | +20/+2 | easy | Inconsistent without deck thinning |
| Straight | 2.0 | 30×4 | **+30/+3 (best)** | **hard** (LLMs misread gaps) | Only with Four Fingers / Shortcut / Runner |
| **Flush** | **2.5** | 35×4 | +15/+2 | **easy (count suits)** | **DEFAULT** |
| Full House | 1.7 | 40×4 | +25/+2 | medium | Late-game with Pair/Trips jokers and a thinned deck |

**Default plan: FLUSH.**
- Ante 1–2: play the best hand you can make. Use discards to hunt flushes: keep the most common suit, discard everything else (up to 5).
- Level **Jupiter** only. Buy flush/suit jokers: Droll (+10 Mult), Crafty (+80 chips), The Tribe (×2), Smeared, Four Fingers, Greedy/Lusty/Wrathful/Gluttonous, Bloodstone, Arrowhead, Onyx Agate. Use **The Star/Moon/Sun/World** to convert cards to your dominant suit; pick the suit you already have most of.
- Fallback when no flush comes: Pair or Two Pair padded with junk, plus generic +Mult jokers.

**When to switch to the Pair / Two Pair / Full House family** (decide by the end of Ante 2–3): you own 2+ pair-family jokers (Jolly, Zany, Mad, Sly, Clever, Spare Trousers, The Duo, The Trio, The Family) and no flush jokers, *or* a Suit Boss blind threatens a one-suit deck. Then level Uranus (Two Pair) or Earth (Full House) instead.

**Suit boss caution:** if you converted most cards to one suit, The Club, Goad, Window or Head debuffs it. Then play Pair, Two Pair or Trips from the debuffed suit: they still form hands, but the debuffed cards give 0 chips and joker effects. Keep at least one +Mult joker that doesn't depend on suit.

---

## 7. Hand ordering inside a play (precise rule)

- Scoring order is the **left-to-right position of the played cards** (the order they hold in hand), not the order you list the indices. Use `rearrange` on the hand first if order matters. (Unverified for BalatroBot whether `play` index order is ignored; assume hand position decides.)
- **Chips never depend on order.** Only MULT does, because ×Mult multiplies whatever MULT is at that moment.
- **All card effects (step 2) and held effects (step 3) happen before any joker's independent effect (step 4).** So:
  - a Glass, Polychrome, Photograph or Ancient ×Mult on a card multiplies only the base mult plus +Mult from **earlier cards**. It never multiplies joker +Mult.
  - **Joker order is the big lever**: +Chips/+Mult jokers left, ×Mult jokers right. Polychrome jokers act as ×1.5 at their slot, so place them right too.
- Card order matters only if the play includes **both** +Mult-producing scoring cards (Mult card, Holo card, cards that trigger Smiley/Greedy/Fibonacci/Even Steven/Onyx Agate) **and** ×Mult-producing scoring cards (Glass, Polychrome card, Photograph's first face card, Triboulet K/Q, Ancient suit card, The Idol card, Bloodstone heart). In that case put **+Mult cards left and ×Mult cards right**.
- **Photograph** affects the *first scoring face card*. Hanging Chad retriggers the *first scoring card*: put your best card (Glass, Polychrome or Mult) leftmost when you have Hanging Chad (unverified: 1.0.1 Hanging Chad retriggers 2 extra times).
- **Held cards** are evaluated left to right too. With Shoot the Moon (+13 per Queen) and Baron (×1.5 per King) or Steel, put **Queens left of Kings/Steel**.

---

## 8. Hand leveling economics

- **One planet early is about a joker.** Flush L1→L2 alone is 308→552 (+80%). A +4 Mult Joker gives 308→616. Planets cost $3 and use no joker slot, but their *relative* value drops as joker +Mult grows, because base mult becomes a small share. ×Mult jokers multiply the level's mult, so levels stay useful late.
- **Saturn (Straight) gives the most per level** (+30/+3). Jupiter gives +15/+2. Venus, Earth and Mars are mid. Mercury, Uranus and Pluto are weak per level.
- **Never spread planets.** Five levels on one hand (Flush L6 ≈ 110×14) beat five hands at L2. You play one hand type about 80% of the time.
- **Celestial packs:** an opened pack's planet is free once bought. Always take the main-hand planet. If it's absent, take the fallback hand's planet (taking one costs nothing extra). Buy individual off-type planets only with **Constellation** (×0.1 Mult per planet used) or **Satellite**.
- **Black Hole** (Spectral): +1 level to every hand. Use immediately.
- **Blue Seal**: a Blue Seal card **held** at end of round creates the planet for the **last hand you played**. Keep it in hand (don't play it), and make your final winning hand your main type.
- **Telescope** voucher: Celestial packs always contain the planet for your *most played* hand. That's why playing your main hand most often matters (game state shows "played N times"). **Observatory**: each planet *held* in a consumable slot gives ×1.5 Mult when its hand is played, so hold main-hand planets.
- **Most-played hand** anchors Telescope, The Ox (sets money to $0 when played), Obelisk (resets on it) and Supernova. Pad-play and fallback hands also count toward "played", so don't let a fallback become your most-played hand by accident.
- **Space Joker** (1 in 4 to level the played hand) and **Burnt Joker** (levels the first discarded hand each round) reinforce focus.

---

## 9. Don't over-score, but don't under-use discards

- The round ends immediately when `current_score ≥ target`. Every unused hand = **+$1**. Overkill gives nothing.
- So: build the **one biggest hand** with free discards, rather than several medium hands. Two discards plus one flush usually beats two padded pairs.
- Discards left at round end give nothing (unless Banner or Delayed Gratification). Use them whenever they improve the next play.
- Don't hold back your best hand "for later". The deck resets each round, and only hands-left matters for money.
- Exception: **The Mouth** (only the first-played hand type counts) and **The Eye** (no repeats). Plan the sequence first: under The Eye, play the *weaker* hand types when they suffice and save the main type for the hand that must score big.

---

## 10. Boss blinds affecting hand play (quick table)

| Boss | Play rule |
|---|---|
| The Psychic | Must play 5 cards. Pad with junk |
| The Needle (1×) | 1 hand. Use all 4 discards to build the best hand, then play |
| The Water | 0 discards. Dig by padding played hands |
| The Hook | After each play, 2 random held cards are discarded. Don't count on held draws; Red Deck discards still work |
| The Serpent | Always draw 3 after a play or discard. Discarding 1–2 cards *grows* the hand; discarding 5 shrinks it (unverified nuance) |
| The Manacle | Hand size 7. Flush and straight odds drop, so lean on fallback hands |
| The Eye | No hand type twice this round |
| The Mouth | Only the first hand type played is allowed. Play your main type first |
| The Arm | Lowers the played hand's level by 1 each play. Consider a fallback type for some hands |
| The Flint | Base chips and mult halved. Joker-heavy builds barely care |
| The Ox | Most-played hand sets $ to 0. Play another type if money matters and the score allows |
| The Tooth | −$1 per card played. Play minimal scoring cards |
| Club / Goad / Window / Head | That suit is debuffed: forms hands but gives 0 chips and no effects |
| The Plant | Face cards debuffed |
| The Pillar | Cards played earlier this ante are debuffed |
| House / Wheel / Fish / Mark | Face-down cards. Type shows "???" but scores normally. Discard face-down unknowns if you need specific cards |
| The Wall (4×) | Twice the normal Boss target. Use all discards and plan for all 4 hands |
| Violet Vessel (6×, Ante 8) | 300,000. Requires a ×Mult engine (≈75k per hand) |

---

## 11. Common small-LLM mistakes and fixes

| Mistake | Fix / self-check |
|---|---|
| Miscounting suits (claims a Flush with 4 hearts) | Write out the suits of the 5 chosen cards and confirm all match, or enough match with Wild cards or Smeared |
| Selecting 6+ cards / wrong 0-based index | Count the indices (1–5), and map index → card name before calling |
| Playing High Card when a Pair exists | Check pairs first: any repeated rank among the 8 cards? |
| Playing a "straight" with a gap or a K-A-2 wrap | Sort the ranks and check 5 consecutive values (A low only as A-2-3-4-5) |
| Discarding cards that form the current best or winning hand | Before discarding, compute the best made hand's score vs R. If it's ≥ R, play it |
| Spending all 4 hands on small plays | Use discards first. Aim for 3 or fewer hands per blind |
| Not checking the score gap | Always compute R and R/H first |
| Counting debuffed cards' chips or joker triggers | Debuffed = 0 chips, no enhancement, no joker trigger |
| Expecting kicker chips from unscored cards | Only hand-forming cards score (except Stone and Splash) |
| Thinking you can play a Flush "as a Pair" | The game picks the best hand automatically (matters for The Eye, The Mouth, The Ox, Card Sharp) |
| Ignoring card-count jokers or bosses | Check Half Joker, Square Joker, Psychic, Tooth before padding |
| Spreading planets / buying off-type planets | One main hand. Off-type only from free pack picks |
| Holding Black Hole or planets without Observatory | Use them immediately |
| Joker order: ×Mult left of +Mult | Rearrange: chips/+mult jokers left, ×mult jokers right (Blueprint left of its target) |

---

## Sources

- WebSearch snippets: [Balatro Wiki: Planet Cards (fandom)](https://balatrogame.fandom.com/wiki/Planet_Cards), [Sportskeeda: 12 planet cards](https://sportskeeda.com/mobile-games/planet-cards-balatro-details-get), [Jetpunk consumables](https://www.jetpunk.com/user-quizzes/272286/balatro-all-consumable-cards), [Dot Esports: all planet cards](https://dotesports.com/indies/news/all-balatro-planet-cards-explained), [dood.gg Mars](https://dood.gg/balatro/planets/mars), [dood.gg Pluto](https://dood.gg/balatro/planets/pluto), [saschb2b poker scoring](https://saschb2b.github.io/game-mechanics/games/balatro/poker-scoring), [Prima Games hands](https://primagames.com/gaming/all-poker-hands-and-their-chips-and-mults-in-balatro), [mp1st: 1.0.1 ante rebalance notes](https://mp1st.com/news/balatro-update-1-07-shuffles-out-this-may-16), [Steam discussion on scoring order](https://steamcommunity.com/app/2379780/discussions/0/4634862878162187094), [West Games score calculator](https://west-games.com/balatro-score-calculator/), [ProGameGuides joker order](https://progameguides.com/balatro/best-joker-order-in-balatro/).
- Blocked in sandbox (couldn't fetch directly): balatrowiki.org and balatrogame.fandom.com.
- Probability tables: exact hypergeometric calculation and Monte Carlo (40k and 20k trials), computed for this file.

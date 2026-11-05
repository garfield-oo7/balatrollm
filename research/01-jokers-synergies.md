# 01 — Jokers & Joker Synergies (Balatro v1.0.1, Red Deck / White Stake)

> Research note for the BalatroLLM strategy prompt. Target model: Claude Haiku.
> Sources: the web fetch tools were **blocked** in this session (balatrowiki.org, balatrogame.fandom.com and
> other hosts did not resolve). WebSearch worked, and it confirmed only the 1.0.1 patch changes (Hanging Chad now
> retriggers 2x, Smiley Face +5 Mult). Everything else comes from **model knowledge** of the 1.0.1 game data
> and community consensus (r/balatro guides, tier lists). Items marked **(unverified)** are ones I am unsure of.
> The bot reads exact effect text from the game, so this file focuses on **value judgements**.
>
> Note: the existing `STRATEGY.md.jinja` says Smiley Face gives "+4 Mult". That is pre-1.0.1. It is **+5** now.

---

## 0. TOP 15 RULES FOR A SMALL LLM (jokers)

1. **Score = Chips × Mult.** Early on, a joker that gives **+Mult** is usually worth more than one giving +Chips. Late on, only **xMult** keeps up with the targets.
2. **Ante 1-2: buy the first 2-3 scoring jokers you can afford.** Any +Mult or +Chips joker beats saving money. With no scoring joker you die at the Ante 2-3 boss.
3. **Fill all 5 slots with scoring jokers by Ante 3.** An empty slot is a wasted slot. The exception is Joker Stencil.
4. **By the end of Ante 4 you need at least 1 xMult joker, and by Ante 6 you need 2 or more.** Otherwise the Ante 5-6 targets (11k-40k) kill you. If a reliable xMult joker (§3, tiers S/A) shows up from Ante 3 on, buy it even if you must sell a flat-bonus joker to make room.
5. **Order jokers left to right: +Chips → +Mult → xMult.** Put xMult jokers in the rightmost slots and re-order after every purchase.
6. **Blueprint copies the joker to its RIGHT. Brainstorm copies the LEFTMOST joker.** Put the joker you want copied in that spot. Never put Blueprint in the last slot.
7. **Choose ONE main hand type by Ante 2-3,** based on your jokers. Pair, Two Pair and Flush are the most reliable. Then buy jokers and planets for that hand.
8. **Hand-type jokers (Jolly, Zany, Mad, Crazy, Droll, Sly, Wily, Clever, Devious, Crafty, Duo/Trio/Family/Order/Tribe) only trigger when the played hand CONTAINS that hand.** A Full House contains a Pair and Three of a Kind. Two Pair contains a Pair. A Straight Flush contains both a Straight and a Flush.
9. **Hold a joker if it fits your hand, skip it if it's off-plan. The exception is "universal" jokers,** which work with any hand. Take these even off-plan: Joker, Gros Michel, Cavendish, Misprint, Abstract, Supernova, Green Joker, Ride the Bus, Popcorn, Ice Cream, Banner, Blue Joker, Swashbuckler, Card Sharp, Acrobat, Loyalty Card, Ramen, Blueprint, Brainstorm, Baseball Card, Stencil (alone).
10. **Replacing a joker is correct when the new one is clearly stronger,** for example xMult over a flat +4, or +15 over +4. The sell loss is only a few dollars. Never sell your only xMult joker, and never sell to buy a sidegrade.
11. **Economy jokers (Golden Joker, Rocket, To the Moon, Egg, Cloud 9) are good only in Antes 1-4,** and only once you can already beat blinds. Sell them for scoring jokers by Ante 5-6.
12. **Decaying jokers (Ice Cream, Popcorn, Seltzer, Turtle Bean, Ramen, Gros Michel) are temporary.** Plan their replacement before they expire. Never pay extra to keep one.
13. **Read the destroy and drawback text.** Ceremonial Dagger destroys the joker to its right. Madness destroys a random joker. Stuntman and Merry Andy reduce hand size. Burglar removes all discards. Obelisk resets when you play your most-played hand. Ride the Bus resets on scoring face cards.
14. **Don't buy conditional jokers you can't trigger.** Examples are Blackboard in a mixed-suit deck, Driver's License with fewer than 16 enhanced cards, Flower Pot with a Flush build, Shoot the Moon without Queens, and Hit the Road without Jacks. Count your deck first.
15. **Red Deck has 4 discards.** Discard-scaling jokers get better: Banner (+120 Chips with 4 discards left), Delayed Gratification ($8 per round), Hit the Road, Yorick, Castle, Faceless and Mail-In Rebate. Mystic Summit conflicts with Banner and Delayed Gratification, so don't run them together.

---

## 1. Core math and context

### 1.1 White Stake score targets (base, Antes 1-8)

| Ante | Small (×1) | Big (×1.5) | Boss (×2) | What you need per hand (4 hands, boss) |
| ---- | ---------- | ---------- | --------- | --------------------------------------- |
| 1    | 300        | 450        | 600       | ~150-300 — 1 joker is enough            |
| 2    | 800        | 1,200      | 1,600     | ~400-800                                |
| 3    | 2,000      | 3,000      | 4,000     | ~1,000-2,000 — 3+ flat jokers           |
| 4    | 5,000      | 7,500      | 10,000    | ~2,500-5,000 — first xMult needed       |
| 5    | 11,000     | 16,500     | 22,000    | ~5,500-11,000                           |
| 6    | 20,000     | 30,000     | 40,000    | ~10,000-20,000 — 2 xMult                |
| 7    | 35,000     | 52,500     | 70,000    | ~17,500-35,000                          |
| 8    | 50,000     | 75,000     | 100,000   | ~25,000-50,000 — 2-3 xMult + leveled hand |

The Wall boss is ×4 base. Violet Vessel (Ante 8 showdown) is ×6, which means 300,000 at Ante 8.

### 1.2 Why flat bonuses stop working (the "Ante 5 wall")

Example: a Pair at level 3 is 40 Chips / 4 Mult before cards. Add a pair of Kings (+20) and you get 60 chips.

- Ante 2, with Joker (+4) and Jolly (+8): 60 × 16 = **960**. That's fine.
- Ante 5, with five flat +Mult jokers (+4, +8, +10, +12, +15 = +49): 60 × 53 ≈ **3,200**. That is not enough for 16,500.
- Swap one flat joker for The Duo (×2) at the right end: 60 × (4+37) × 2 ≈ **4,900**. Add Cavendish (×3): ≈ **14,700**.
  Two xMult jokers turn a dying run into a winning one.

**Rule:** targets grow about ×2 per ante, while flat bonuses grow linearly. **You must transition to xMult by Ante 4-5 or you die at Ante 5-6.**

### 1.3 +Chips vs +Mult — which to add

- A typical early hand is about 40-80 chips × 2-8 mult. Mult is the smaller number, so **+Mult has the bigger relative effect**.
- Quick check: gain% = added / current. +30 chips on 60 chips is +50%. +4 mult on 4 mult is +100%. Pick whichever has the bigger percentage.
- Flush and Straight hands have high base chips (30-35 + 5 cards), so they want **+Mult**. Pair and High Card hands have low chips, so +Chips jokers (Sly, Scary Face, Banner) are not bad either.
- Once you have xMult, +Mult gets multiplied, so +Mult remains valuable.

### 1.4 Scoring order (affects ordering)

1. Each **played scoring card**, left to right. It adds its chips, its enhancement, its edition and its seal. Then the "on-scored" joker effects for that card trigger, in joker order. Examples: Greedy/Lusty/Wrathful/Gluttonous, Fibonacci, Scholar, Even Steven, Odd Todd, Scary/Smiley Face, Walkie Talkie, Photograph, Bloodstone, Arrowhead, Onyx Agate, Ancient Joker, The Idol, Triboulet, Hiker, Wee Joker. Retriggers (Red Seal, Hack, Sock and Buskin, Dusk, Seltzer, Hanging Chad) repeat that card's whole step.
2. **Cards held in hand**: Steel ×1.5, Baron, Shoot the Moon, Raised Fist (Mime retriggers these).
3. **Independent joker effects**, left to right by slot. Examples: Joker, Jolly, Duo, Cavendish, Blackboard, Supernova, Abstract, Stencil. Joker editions apply here: Foil/Holo **before** that joker's effect, Polychrome ×1.5 **after**.

Consequence: card-triggered xMult (Photograph, Triboulet, Bloodstone, Ancient, Idol, Glass cards) **always happens before** every independent +Mult joker, whatever the slot order. These are weaker than they look unless most of your +Mult also comes from cards. Slot ordering only matters within step 3.

### 1.5 Rarity, cost, appearance (White Stake)

- Shop joker rarity weights: Common 70%, Uncommon 25%, Rare 5%. **Legendary jokers never appear in the shop.** They come only from The Soul spectral card.
- Base costs: most Commons $4-6, Uncommons $5-8, Rares $7-10, Legendaries $20 (only via The Soul, so cost is moot).
- Edition surcharges: Foil +$2, Holo +$3, Polychrome +$5, Negative +$5 (unverified exact). **Sell value = half the buy price, rounded down, minimum $1.**
- **White Stake has no Eternal, Perishable or Rental stickers.** Those start at Black, Orange and Gold stake. Ignore sticker logic.
- Red Deck: +1 discard per round (4 total). Everything else is standard: $4 start, 5 joker slots, 4 hands, hand size 8.
- Buffoon Pack (joker pack): Normal $4, choose 1 of 2. Jumbo $6, choose 1 of 4. Mega $8, choose 2 of 4. **Buy it in Antes 1-3 whenever you have an open slot and at least $4 above your reserve.**

---

## 2. Complete joker reference (all 150)

Columns: **#** = collection number. **R** = rarity (C/U/R/L). **$** = base cost. **Tag** = category. **Early** = grade for
picking it up in Antes 1-3 on Red/White (S = buy instantly, A = strong, B = OK if on-plan, C = weak/niche, T = trap
for an LLM). **Late** = value in Antes 5-8.

Tags: `+C` +Chips, `+M` +Mult, `xM` xMult, `scale` grows over time, `econ` money, `retrig` retrigger, `util` hand
size / rules / consumables, `copy` copy jokers.

| #   | Joker | R | $ | Effect (v1.0.1) | Tag | Early | Late |
| --- | ----- | - | - | --------------- | --- | ----- | ---- |
| 1 | Joker | C | 2 | +4 Mult | +M | A | C |
| 2 | Greedy Joker | C | 5 | Played ♦ cards give +3 Mult when scored | +M | B | C |
| 3 | Lusty Joker | C | 5 | Played ♥ give +3 Mult when scored | +M | B | C |
| 4 | Wrathful Joker | C | 5 | Played ♠ give +3 Mult when scored | +M | B | C |
| 5 | Gluttonous Joker | C | 5 | Played ♣ give +3 Mult when scored | +M | B | C |
| 6 | Jolly Joker | C | 3 | +8 Mult if hand contains a Pair | +M | A | C |
| 7 | Zany Joker | C | 4 | +12 Mult if hand contains Three of a Kind | +M | B | C |
| 8 | Mad Joker | C | 4 | +10 Mult if hand contains Two Pair | +M | A | C |
| 9 | Crazy Joker | C | 4 | +12 Mult if hand contains a Straight | +M | B | C |
| 10 | Droll Joker | C | 4 | +10 Mult if hand contains a Flush | +M | A | B |
| 11 | Sly Joker | C | 3 | +50 Chips if hand contains a Pair | +C | B | D |
| 12 | Wily Joker | C | 4 | +100 Chips if hand contains Three of a Kind | +C | B | C |
| 13 | Clever Joker | C | 4 | +80 Chips if hand contains Two Pair | +C | B | C |
| 14 | Devious Joker | C | 4 | +100 Chips if hand contains a Straight | +C | B | C |
| 15 | Crafty Joker | C | 4 | +80 Chips if hand contains a Flush | +C | B | C |
| 16 | Half Joker | C | 5 | +20 Mult if played hand has ≤3 cards | +M | S | B |
| 17 | Joker Stencil | U | 8 | ×1 Mult per empty joker slot (counts itself) | xM | C | B (alone/negatives) |
| 18 | Four Fingers | U | 7 | Flushes & Straights can be made with 4 cards | util | B | A (flush/straight) |
| 19 | Mime | U | 5 | Retrigger all held-in-hand card abilities | retrig | C | A (Baron/steel) |
| 20 | Credit Card | C | 1 | Can go to -$20 debt | econ | C | D |
| 21 | Ceremonial Dagger | U | 6 | On blind select: destroy joker to the RIGHT, add 2× its sell value to this Mult | scale | T | B (expert) |
| 22 | Banner | C | 5 | +30 Chips per remaining discard | +C | A (Red Deck: +120) | C |
| 23 | Mystic Summit | C | 5 | +15 Mult when 0 discards remaining | +M | B | C |
| 24 | Marble Joker | U | 6 | On blind select: add a Stone card to deck | util | C | C |
| 25 | Loyalty Card | U | 5 | ×4 Mult every 6 hands played (counter) | xM | B | B |
| 26 | 8 Ball | C | 5 | 1 in 4 per scored 8: create a Tarot | util | C | D |
| 27 | Misprint | C | 4 | +0 to +23 Mult (random, avg ~11.5) | +M | A | C |
| 28 | Dusk | U | 5 | Retrigger all played cards in FINAL hand of round | retrig | C | B |
| 29 | Raised Fist | C | 5 | Adds 2× rank of LOWEST held card to Mult | +M | B | C |
| 30 | Chaos the Clown | C | 4 | 1 free reroll per shop | util | C | C |
| 31 | Fibonacci | U | 8 | Played A, 2, 3, 5, 8 each give +8 Mult when scored | +M | A | B |
| 32 | Steel Joker | U | 7 | ×0.2 Mult per Steel card in full deck | xM | C | B (steel) |
| 33 | Scary Face | C | 4 | Played face cards +30 Chips when scored | +C | B | C |
| 34 | Abstract Joker | C | 4 | +3 Mult per joker owned (incl. itself; 5 jokers = +15) | +M | A | C |
| 35 | Delayed Gratification | C | 4 | $2 per discard if NO discards used this round (Red: $8) | econ | B | C |
| 36 | Hack | U | 6 | Retrigger each played 2, 3, 4, 5 | retrig | C | B (low cards) |
| 37 | Pareidolia | U | 5 | All cards count as face cards | util | C | B (face) |
| 38 | Gros Michel | C | 5 | +15 Mult; 1 in 6 chance destroyed at end of round | +M | S | C |
| 39 | Even Steven | C | 4 | Played even cards (10,8,6,4,2) +4 Mult when scored | +M | B | C |
| 40 | Odd Todd | C | 4 | Played odd cards (A,9,7,5,3) +31 Chips when scored | +C | B | C |
| 41 | Scholar | C | 4 | Played Aces +20 Chips and +4 Mult when scored | +C+M | B | C |
| 42 | Business Card | C | 4 | Played face cards: 1 in 2 to give $2 when scored | econ | B | C |
| 43 | Supernova | C | 5 | Adds # times this hand type was played this run to Mult | scale +M | S | B |
| 44 | Ride the Bus | C | 6 | +1 Mult per consecutive hand with NO scoring face card (resets) | scale +M | A (no faces) | B |
| 45 | Space Joker | U | 5 | 1 in 4: upgrade level of played hand | scale | B | B |
| 46 | Egg | C | 4 | +$3 sell value at end of round | econ | B | D |
| 47 | Burglar | U | 6 | On blind select: +3 hands, lose ALL discards | util | T | C |
| 48 | Blackboard | U | 6 | ×3 Mult if ALL cards held in hand are ♠/♣ | xM | B (if dark-suit) | A |
| 49 | Runner | C | 5 | +15 Chips (scaling) each time hand contains a Straight | scale +C | B (straight) | C |
| 50 | Ice Cream | C | 5 | +100 Chips, −5 Chips per hand played (20 hands) | +C | A | D |
| 51 | DNA | R | 8 | If first hand of round is 1 card, add a permanent copy to deck + hand | util | C | B |
| 52 | Splash | C | 3 | Every played card counts in scoring | util | C | C |
| 53 | Blue Joker | C | 5 | +2 Chips per card remaining in deck (~+80 early) | +C | A | C |
| 54 | Sixth Sense | U | 6 | First hand is a single 6: destroy it, create Spectral | util | C | C |
| 55 | Constellation | U | 6 | Gains ×0.1 Mult per Planet card used | scale xM | B | A |
| 56 | Hiker | U | 5 | Every played scoring card permanently +5 Chips | scale +C | C | C |
| 57 | Faceless Joker | C | 4 | $5 if 3+ face cards discarded at once | econ | B | C |
| 58 | Green Joker | C | 4 | +1 Mult per hand played, −1 Mult per discard used | scale +M | A | C |
| 59 | Superposition | C | 4 | Create Tarot if hand has an Ace AND a Straight | util | C | D |
| 60 | To Do List | C | 4 | $4 if hand is [named hand]; changes each round | econ | C | D |
| 61 | Cavendish | C | 4 | ×3 Mult; 1 in 1000 destroyed per round. Shop-only AFTER Gros Michel dies | xM | S | S |
| 62 | Card Sharp | U | 6 | ×3 Mult if this hand type was already played THIS ROUND | xM | A | A |
| 63 | Red Card | C | 5 | +3 Mult each time a Booster Pack is skipped | scale +M | C | C |
| 64 | Madness | U | 7 | On Small/Big blind select: +×0.5 Mult, destroy a random OTHER joker | scale xM | T | B (expert) |
| 65 | Square Joker | C | 4 | +4 Chips (scaling) per hand with exactly 4 cards | scale +C | C | C |
| 66 | Séance | U | 6 | Straight Flush: create random Spectral | util | D | D |
| 67 | Riff-Raff | C | 6 | On blind select: create 2 Common jokers (needs room) | util | B | C |
| 68 | Vampire | U | 7 | +×0.1 Mult per scoring ENHANCED card; removes its enhancement | scale xM | C | B |
| 69 | Shortcut | U | 7 | Straights may have gaps of 1 rank | util | B (straight) | B |
| 70 | Hologram | U | 7 | +×0.25 Mult per playing card added to deck | scale xM | B | A |
| 71 | Vagabond | R | 8 | Create a Tarot if hand played with ≤$4 | util | D | C |
| 72 | Baron | R | 8 | Each King HELD in hand ×1.5 Mult | xM | B | S (kings) |
| 73 | Cloud 9 | U | 7 | $1 per 9 in full deck at end of round (~$4) | econ | B | D |
| 74 | Rocket | U | 6 | $1 end of round; +$2 per Boss defeated | econ | A | C |
| 75 | Obelisk | R | 8 | +×0.2 Mult per consecutive hand NOT your most-played hand; resets | scale xM | T | B |
| 76 | Midas Mask | U | 7 | Played face cards become Gold when scored | econ | C | C |
| 77 | Luchador | U | 5 | SELL during a boss blind to disable the boss | util | B (insurance) | B |
| 78 | Photograph | C | 5 | First played face card ×2 Mult when scored | xM | A (face) | B |
| 79 | Gift Card | U | 6 | +$1 sell value to every joker & consumable each round | econ | C | C |
| 80 | Turtle Bean | U | 6 | +5 hand size, −1 per round | util | B | D |
| 81 | Erosion | U | 6 | +4 Mult per card below starting deck size (52) | +M | T | B (thin deck) |
| 82 | Reserved Parking | C | 6 | Each face card HELD: 1 in 2 to give $1 | econ | C | C |
| 83 | Mail-In Rebate | C | 4 | $5 per discarded card of [rank]; rank changes each round | econ | B | C |
| 84 | To the Moon | U | 5 | +$1 extra interest per $5 held (doubles interest) | econ | B | C |
| 85 | Hallucination | C | 4 | 1 in 2 per opened Booster Pack: create Tarot | util | C | D |
| 86 | Fortune Teller | C | 6 | +1 Mult per Tarot used this run | scale +M | C | C |
| 87 | Juggler | C | 4 | +1 hand size | util | B | B |
| 88 | Drunkard | C | 4 | +1 discard per round | util | B | C |
| 89 | Stone Joker | U | 6 | +25 Chips per Stone card in full deck | +C | C | C |
| 90 | Golden Joker | C | 6 | $4 at end of round | econ | A | C |
| 91 | Lucky Cat | U | 6 | +×0.25 Mult each time a Lucky card triggers | scale xM | C | B (lucky) |
| 92 | Baseball Card | R | 8 | Each Uncommon joker gives ×1.5 Mult | xM | B | A |
| 93 | Bull | U | 6 | +2 Chips per $1 held | +C | B | C |
| 94 | Diet Cola | U | 6 | Sell: create free Double Tag | util | D | D |
| 95 | Trading Card | U | 6 | First discard of round is 1 card: destroy it, +$3 | econ | B | C |
| 96 | Flash Card | U | 5 | +2 Mult per shop reroll (scaling) | scale +M | C | C |
| 97 | Popcorn | C | 5 | +20 Mult, −4 Mult per round (5 rounds) | +M | S | D |
| 98 | Spare Trousers | U | 6 | +2 Mult (scaling) each hand containing Two Pair | scale +M | A (2-pair) | B |
| 99 | Ancient Joker | R | 8 | Played cards of [suit] ×1.5 Mult when scored; suit changes per round | xM | B | A |
| 100 | Ramen | U | 6 | ×2 Mult, loses ×0.01 per card discarded | xM | A | B |
| 101 | Walkie Talkie | C | 4 | Played 10s and 4s +10 Chips & +4 Mult when scored | +C+M | B | C |
| 102 | Seltzer | U | 6 | Retrigger all played cards for next 10 hands | retrig | A | D |
| 103 | Castle | U | 6 | +3 Chips (scaling) per discarded [suit] card; suit changes | scale +C | B | C |
| 104 | Smiley Face | C | 4 | Played face cards +5 Mult when scored | +M | B | C |
| 105 | Campfire | R | 9 | +×0.25 Mult per card SOLD; resets on boss defeat | scale xM | C | B |
| 106 | Golden Ticket | C | 5 | Played Gold cards earn $4 when scored | econ | D | D |
| 107 | Mr. Bones | U | 5 | Prevents death if score ≥25% of target; then self-destructs | util | T | C |
| 108 | Acrobat | U | 6 | ×3 Mult on FINAL hand of round | xM | A | A |
| 109 | Sock and Buskin | U | 6 | Retrigger all played face cards | retrig | B (face) | A (face) |
| 110 | Swashbuckler | C | 4 | Adds total sell value of other jokers to Mult | +M | B | C |
| 111 | Troubadour | U | 6 | +2 hand size, −1 hand per round | util | C | C |
| 112 | Certificate | U | 6 | Round start: add random card with random seal to hand | util | C | B (Hologram) |
| 113 | Smeared Joker | U | 7 | ♥=♦ and ♠=♣ for suits | util | A (flush) | A |
| 114 | Throwback | U | 6 | ×0.25 Mult per blind skipped this run | scale xM | T | C |
| 115 | Hanging Chad | C | 4 | Retrigger FIRST scoring card 2 extra times (1.0.1 buff) | retrig | B | B |
| 116 | Rough Gem | U | 7 | Played ♦ earn $1 when scored | econ | B (♦ flush) | C |
| 117 | Bloodstone | U | 7 | Played ♥: 1 in 2 for ×1.5 Mult when scored | xM | B (♥) | A (♥ flush) |
| 118 | Arrowhead | U | 7 | Played ♠ +50 Chips when scored | +C | B (♠) | C |
| 119 | Onyx Agate | U | 7 | Played ♣ +7 Mult when scored | +M | B (♣) | B |
| 120 | Glass Joker | U | 6 | +×0.75 Mult per Glass card destroyed | scale xM | C | B |
| 121 | Showman | U | 5 | Same jokers/consumables can appear again | util | D | D |
| 122 | Flower Pot | U | 6 | ×3 Mult if scoring hand has a ♦, ♣, ♥ and ♠ | xM | C | B (wilds) |
| 123 | Blueprint | R | 10 | Copies ability of joker to its RIGHT | copy | A | S |
| 124 | Wee Joker | R | 8 | +8 Chips (scaling) per scored 2 | scale +C | C | C |
| 125 | Merry Andy | U | 7 | +3 discards, −1 hand size | util | T | D |
| 126 | Oops! All 6s | U | 4 | Doubles all listed probabilities | util | C | B (Bloodstone/Lucky) |
| 127 | The Idol | U | 6 | Played [rank] of [suit] ×2 Mult when scored; changes per round | xM | C | B |
| 128 | Seeing Double | U | 6 | ×2 Mult if scoring hand has a ♣ AND a card of another suit | xM | B | B |
| 129 | Matador | U | 7 | $8 if played hand triggers the boss ability | econ | D | D |
| 130 | Hit the Road | R | 8 | +×0.5 Mult per Jack discarded this round (resets) | scale xM | B (Red Deck) | A |
| 131 | The Duo | R | 8 | ×2 Mult if hand contains a Pair | xM | S | S |
| 132 | The Trio | R | 8 | ×3 Mult if hand contains Three of a Kind | xM | A | A |
| 133 | The Family | R | 8 | ×4 Mult if hand contains Four of a Kind | xM | B | A (4oak build) |
| 134 | The Order | R | 8 | ×3 Mult if hand contains a Straight | xM | B | A (straight) |
| 135 | The Tribe | R | 8 | ×2 Mult if hand contains a Flush | xM | A | S (flush) |
| 136 | Stuntman | R | 7 | +250 Chips, −2 hand size | +C | T | C |
| 137 | Invisible Joker | R | 8 | After 2 rounds: sell to duplicate a random joker | copy | C | B |
| 138 | Brainstorm | R | 10 | Copies ability of the LEFTMOST joker | copy | A | S |
| 139 | Satellite | U | 6 | $1 per unique Planet used this run, at end of round | econ | C | C |
| 140 | Shoot the Moon | C | 5 | +13 Mult per Queen HELD in hand | +M | C | B (queens) |
| 141 | Driver's License | R | 7 | ×3 Mult if ≥16 Enhanced cards in full deck | xM | T | B |
| 142 | Cartomancer | U | 6 | On blind select: create a Tarot (needs room) | util | B | C |
| 143 | Astronomer | U | 8 | Planets & Celestial Packs in shop are free | util/econ | B | B |
| 144 | Burnt Joker | R | 8 | Upgrade level of first DISCARDED hand each round | scale | B | B |
| 145 | Bootstraps | U | 7 | +2 Mult per $5 held | +M | B | C |
| 146 | Canio ("Caino") | L | 20 | +×1 Mult per face card destroyed | scale xM | — | B |
| 147 | Triboulet | L | 20 | Played Kings & Queens ×2 Mult each when scored | xM | — | S |
| 148 | Yorick | L | 20 | +×1 Mult every 23 cards discarded (starts ×1) | scale xM | — | A |
| 149 | Chicot | L | 20 | Disables every Boss Blind effect | util | — | A |
| 150 | Perkeo | L | 20 | End of shop: Negative copy of 1 random consumable | util | — | B |

Notes on the table:

- Costs are from memory of the 1.0.1 game data. A ±$1 error is possible on a few, notably Fibonacci, whose price was cut in 1.0.1 (unverified exact value).
  Shop price includes the edition surcharge.
- Count: 61 Common, 64 Uncommon, 20 Rare, 5 Legendary (= 150).
- Cavendish only enters the shop pool after a Gros Michel has been destroyed this run. Gros Michel leaves the pool after that.
- Legendaries come only from The Soul (Spectral/Arcana packs). Any Legendary is worth taking if you have room.

---

## 3. xMult jokers ranked by RELIABILITY

Each step multiplies. **Reliability ranks above peak value**: an ×3 that always triggers beats an ×5 that triggers half the time.

### Tier S — always or almost always on, take them instantly

| Joker | Mult | Condition | Notes |
| ----- | ---- | --------- | ----- |
| Cavendish | ×3 | None | 1/1000 death only. Best common in the game. |
| The Duo | ×2 | Hand contains Pair | Pair, Two Pair, Trips, Full House and Four of a Kind all trigger it. Fits almost any non-flush build. |
| The Tribe | ×2 | Hand contains Flush | Core of flush builds. Triggers every hand in a flush build. |
| Blueprint / Brainstorm | copy | Copies an xMult joker | Only as good as the target. Copying Cavendish = ×3 more. |
| Triboulet (L) | ×2 per K/Q scored | Play Kings/Queens | Two K + two Q in a hand is ×16. |
| Baron | ×1.5 per King held | Hold Kings | 4 Kings held is ×5. With Mime it is ×25. Needs King density. |

### Tier A — strong, small conditions

| Joker | Mult | Condition / caveat |
| ----- | ---- | ------------------ |
| Card Sharp | ×3 | Play the same hand type twice in a round. With one main hand type it is on for hands 2-4. |
| The Trio | ×3 | Contains Three of a Kind (Trips, Full House, Four of a Kind). |
| The Order | ×3 | Contains Straight. Needs a straight build. |
| Acrobat | ×3 | Final hand of the round only. Plan to win on the last hand; useless if you clear the blind early. A good closer. |
| Blackboard | ×3 | Every held card must be ♠/♣. Great with Smeared plus a dark-suit flush, or by playing all red cards. Inconsistent in a mixed deck. |
| Ramen | ×2 → decays | Loses ×0.01 per card discarded. Red Deck discards ~10-15 cards per round, so it is ×2 for a few antes. Discard less. |
| Constellation | ×1 + 0.1/planet | Grows to ×2-3 with planet use. Pairs well with Celestial packs and Astronomer. |
| Hologram | ×1 + 0.25/card added | Grows with Standard packs, Certificate, Marble, DNA, Cryptid. |
| Hit the Road | ×0.5/Jack discarded | Resets each round. Red Deck's 4 discards make ×2-3 common if you hold/discard Jacks. |
| Yorick (L) | +×1 per 23 discards | Red Deck reaches ×3-4 by Ante 6. |
| Baseball Card | ×1.5 per Uncommon | With 2-3 Uncommons it is ×2.25-×3.4. |
| Bloodstone | ×1.5 (50% per ♥) | Heart flush: ~5 scored hearts gives about ×2.8 on average. Oops! All 6s makes it guaranteed. |
| Ancient Joker | ×1.5 per [suit] scored | Suit rotates each round. Strong with Smeared or a Flush that can switch suits. |
| Glass Joker | +×0.75/glass broken | Needs Justice tarots. Slow but permanent. |
| Loyalty Card | ×4 every 6th hand | Fires about once every 1.5 rounds. Reliable over time, but unpredictable for a given blind. Check the counter. |

### Tier B — conditional or slow, take only when the condition is already met

| Joker | Mult | Why B |
| ----- | ---- | ----- |
| Photograph | ×2 first face card | Card-timed, so it triggers before independent +Mult jokers (§1.4). Fine with face builds. |
| Seeing Double | ×2 | Needs a scoring ♣ plus another suit. Anti-flush. Decent with Pair/Full House. |
| Flower Pot | ×3 | Needs all 4 suits scoring, so 5-card hands only. Anti-flush. Good with Wild cards. |
| Steel Joker | ×0.2/steel | Needs 5+ Steel cards via Chariot. Pairs with Baron and Mime. |
| Vampire | +×0.1/enhanced scored | Eats enhancements. Anti-synergy with Glass/Steel/Lucky/Gold builds. |
| Lucky Cat | +×0.25/lucky trigger | Needs Magician tarots. Slow. |
| Campfire | +×0.25/card sold | Resets every boss. Needs constant selling (Riff-Raff, Cartomancer + sell tarots). |
| Madness | +×0.5/blind | Destroys a random joker each Small/Big blind. Only for an empty-slot or Riff-Raff setup. **Trap.** |
| Obelisk | +×0.2/streak | Resets when you play your most-played hand, which fights a focused build. **Trap.** |
| The Family | ×4 | Four of a Kind is hard without deck shaping. |
| The Idol | ×2 | One specific card that changes each round. |
| Joker Stencil | ×(empty slots + 1) | ×1 when slots are full. Good only with negative jokers or a tiny joker lineup. |
| Throwback | ×0.25/skip | Requires skipping blinds, which is risky for the LLM. Skipping loses shop visits. |
| Driver's License | ×3 | 16 enhanced cards is rarely reached by an LLM. |
| Canio (L) | +×1/face destroyed | Needs Hanged Man or Familiar. Fine if obtained. |

### Polychrome edition

Any joker with **Polychrome is also ×1.5**. A Polychrome flat joker is effectively an xMult joker. Place it in the right group.

---

## 4. Early-game tier list (Antes 1-3, Red Deck, White Stake)

The concept: in Ante 1-3 you need points **this round**. Flat +Mult/+Chips jokers that trigger on nearly every
hand carry you to Ante 4. Scaling and xMult jokers are a bonus. Economy jokers come only after you have 1-2 scorers.

### S — buy immediately, even off-plan (if affordable)

| Joker | Why |
| ----- | --- |
| Gros Michel ($5) | +15 Mult flat, any hand. Expect ~6 rounds of life. When it dies, Cavendish (×3) can appear. |
| Popcorn ($5) | +20 Mult now, decays by 4 per round. Carries Antes 1-2 easily. Replace it by about Ante 3. |
| Half Joker ($5) | +20 Mult on Pair, Trips, High Card or 3-card hands. Huge early. Pairs well with Duo/Trio. |
| Supernova ($5) | +1 Mult per time a hand type has been played. Spamming one hand reaches +20-40 by Ante 4. Pairs with a focused build. |
| Cavendish ($4) | ×3, never decays. Rarely seen early. |
| The Duo / The Tribe ($8) | ×2 on a common hand. Rare but worth it if you can afford one. |

### A — strong early, buy if a slot is open

- **Joker** (+4 for $2). Cheap filler; replace it later.
- **Jolly / Mad / Droll** (+8/+10/+10). Pair and Two Pair come up constantly. Droll if flushing.
- **Misprint** (avg +11.5). Universal.
- **Abstract Joker** (+3 per joker, +15 at 5 jokers). Universal.
- **Green Joker** (+1 per hand, −1 per discard). Universal. Discard less, often by playing junk as part of hands.
- **Ride the Bus.** Universal unless face cards score. Avoid it with face builds.
- **Ice Cream** (+100 Chips, decaying). Good on Pair builds.
- **Blue Joker** (~+80 Chips early). Universal.
- **Banner** (Red Deck: +120 Chips at 4 discards). Strong if you play without discarding. Combine with Delayed Gratification.
- **Fibonacci** (+8 per A/2/3/5/8 scored). About 5 of 13 ranks, very frequent.
- **Card Sharp** (×3 on repeat hand). Excellent from day 1 with a focused hand.
- **Acrobat** (×3 last hand). Good if you usually need 2-4 hands.
- **Ramen** (×2). Strong immediately; discard sparingly.
- **Spare Trousers** (Two Pair build). Scales to +20-30.
- **Seltzer** (retrigger all for 10 hands). Big burst for about 3 rounds.
- **Smeared Joker** (flush enabler) and **Photograph** (face).
- **Blueprint / Brainstorm.** Only once a good target exists, but cheap at $10 for that much power.
- **Golden Joker / Rocket.** Best economy jokers, but only as joker #2-#4, never #1.

### B — on-plan only

- Hand-type chip jokers: Sly, Wily, Clever, Devious, Crafty.
- Zany and Crazy: Three of a Kind and Straight are rarer.
- Suit +Mult jokers: Greedy, Lusty, Wrathful, Gluttonous (with a flush of that suit, or Smeared).
- Even Steven, Odd Todd, Scholar, Walkie Talkie, Scary Face, Smiley Face.
- Mystic Summit: +15 at 0 discards. Conflicts with Banner and Delayed Gratification on Red Deck.
- Raised Fist, Swashbuckler, Bull, Bootstraps.
- Hanging Chad (great with a Pair of Aces/face cards, or a single high card).
- Blackboard (dark-suit flush with Smeared).
- Four Fingers, Shortcut, Runner (straight or flush builds).
- Constellation, Hologram, Space Joker, Burnt Joker (slow scalers; good if bought by Ante 2).
- Economy: To the Moon, Egg, Cloud 9, Delayed Gratification, Business Card, Faceless, Mail-In Rebate, Trading Card, Rough Gem.

### C / D — usually skip early

Credit Card, 8 Ball, Chaos the Clown, Marble, Splash, Sixth Sense, Superposition, To Do List, Séance, Vagabond,
Hallucination, Fortune Teller, Golden Ticket, Diet Cola, Showman, Matador, Satellite, Gift Card, Reserved Parking,
Midas Mask, Wee Joker, Square Joker, Red Card, Flash Card, Hiker, Steel Joker, Vampire, Lucky Cat, Glass Joker,
Stone Joker, Stencil (when you have other jokers), Mime (without Baron/Steel), Dusk, Hack (without low-card build).

### T — traps (see §6)

Ceremonial Dagger, Madness, Obelisk, Mr. Bones, Burglar, Stuntman, Merry Andy, Erosion (early), Throwback,
Driver's License, Troubadour, Turtle Bean (late).

---

## 5. Economy jokers — value and when to sell

Interest: $1 per $5 held, max $5 at $25. Each unused hand pays $1. Blind rewards: Small $3, Big $4, Boss $5.

| Joker | ~Income per round | Take when | Sell when |
| ----- | ----------------- | --------- | --------- |
| Golden Joker ($6) | $4 | Ante 1-3, as the 2nd-4th joker | You need the slot for a scorer (Ante 4-6). Pays back in 2 rounds. |
| Rocket ($6) | $1, +$2 per boss (≈$3-9) | Ante 1-2 (it grows) | Ante 6+ when slots are tight |
| To the Moon ($5) | +$1 per $5 held (up to +$5 at $25) (unverified: cap interaction) | You already hold $15-25 | You stop holding money |
| Cloud 9 ($7) | $1 per 9 in deck (≈$4) | Ante 1-2 | Slot needed |
| Egg ($4) | +$3 sell value per round | Ante 1-2 with spare slot | Any time you need the slot or cash. It's a piggy bank; sell it for its accumulated value. Pairs with Swashbuckler. |
| Gift Card ($6) | +$1 sell value on each joker & consumable (~+$5-7) | Rarely. With Swashbuckler or Campfire. | Slot needed |
| Delayed Gratification ($4) | $2 × discards (Red Deck: $8) if NO discards used | You can beat blinds without discarding | You need discards to make hands |
| Business Card ($4) | ~$1 per face card scored | Face builds | Slot needed |
| Faceless Joker ($4) | $5 per 3-face discard | Red Deck has many discards | Slot needed |
| Mail-In Rebate ($4) | $5 per discarded rank-X card | Easy with 4 discards | Slot needed |
| Bull ($6) / Bootstraps ($7) | Scoring from money | You keep $25+ banked | You start spending your bank |
| Satellite ($6) | $1 per unique planet used | Lots of planets | Usually skip |
| Trading Card ($6) | $3/round and thins deck | Early, if you discard 1 card first | Slot needed |
| Reserved Parking ($6) | ~$1-2 | Face-heavy hands held | Usually skip |
| Rough Gem ($7) | $1 per ♦ scored | Diamond flush (~$5/hand) | Slot needed |
| Golden Ticket / Matador / To Do List | $0-8 random | Skip | — |
| Credit Card | debt | Skip | — |

Rules:

- **Economy jokers only when the run is safe.** If the last blind took 3+ hands, buy a scoring joker instead.
- **No more than 1-2 economy jokers at a time.** By Ante 5 have at most 1. By Ante 7 have none, unless you have spare slots.
- **Selling an economy joker for a scoring joker is not "the sell-buy trap."** That is the planned exit.

---

## 6. Traps and anti-synergies (for an LLM)

| Joker | Trap | Rule |
| ----- | ---- | ---- |
| Ceremonial Dagger | When you SELECT a blind it destroys the joker to its RIGHT, even if that joker is good | Only buy it if you can keep it in the rightmost slot, or put an Egg or junk joker to its right. Otherwise skip. |
| Madness | Destroys a random joker on every Small/Big blind | Skip unless you only own expendable jokers. |
| Obelisk | Resets whenever you play your MOST played hand, which you do in a focused build | Skip with a focused build. Conflicts with Supernova, Card Sharp and Spare Trousers. |
| Mr. Bones | Only saves you if you reach 25% of the target, then it is gone. Gives 0 score | Not insurance for a weak build. Skip. A scoring joker prevents more deaths. |
| Gros Michel | 1/6 death each round | Still buy it. Keep the other 4 slots scoring so its loss doesn't kill the run. |
| Ice Cream / Popcorn / Seltzer / Turtle Bean | Decay to 0 | Temporary carries. Replace by Ante 3-4. Don't count on them for the boss after next. |
| Ramen | Discards shrink it | Play junk inside played hands instead of discarding. |
| Green Joker | −1 per discard | Same as Ramen. |
| Ride the Bus | Resets on any SCORING face card (J/Q/K; with Pareidolia, every card) | Conflicts with face builds, Pareidolia, Photograph, Triboulet and Sock and Buskin. Keep face cards unscored (Pair of non-faces). |
| Mystic Summit | Needs 0 discards left | On Red Deck you must burn 4 discards first. Conflicts with Banner, Delayed Gratification, Green Joker and Ramen. |
| Burglar | +3 hands but 0 discards | Kills discard-based digging, Hit the Road and Yorick. Skip. |
| Stuntman | −2 hand size (8→6) | +250 Chips is huge, but 6 cards wrecks flushes and straights. Skip unless building High Card/Pair. |
| Merry Andy / Troubadour | −1 hand size / −1 hand | Skip. |
| Hiker | +5 chips per card scored, slowly | Too slow for Ante 1-4. |
| Erosion | Needs deck <52 cards | Zero value until you destroy cards. Skip early. |
| Joker Stencil | ×1 with full slots | Don't buy as your 4th or 5th joker. |
| Luchador | Must be SOLD during the boss round to disable it | Use it during a scary boss (The Wall, The Needle, The Psychic, Violet Vessel, Crimson Heart...). Don't sell it in the shop. |
| Throwback | Rewards skipping blinds | Skipping loses shops and money. Skip it. |
| Driver's License | Needs 16 enhanced cards | Skip unless you already have 12+. |
| Vampire | Removes enhancements | Conflicts with Glass/Steel/Lucky/Gold/Bonus/Mult cards and Driver's License. |
| Midas Mask | Turns face cards Gold (which removes Steel/Glass/etc.) | Conflicts with Steel-King Baron and Vampire. |
| Flower Pot / Seeing Double | Need mixed suits | Anti-synergy with flush builds. |
| Blackboard | Breaks with one red card held | Only with dark-suit decks or Smeared. |
| Splash | Every card scores | Fine, but it makes the hand-type logic confusing. Low value. |
| Credit Card | Debt | Skip. |
| Pareidolia | Every card is a face card | Great with Scary/Smiley/Sock/Photograph/Business Card. Breaks Ride the Bus. |
| Diet Cola / Invisible Joker | No immediate score | Low priority for the LLM. |
| Four Fingers + Shortcut | Easier hands, no score | Enablers. Buy them only alongside a payoff joker (Droll/Tribe/Crazy/Order) you already own or will own. |

Joker-on-joker anti-synergies to avoid owning together:

- Obelisk with Supernova, Card Sharp or Spare Trousers: you can't both focus and avoid your top hand.
- Mystic Summit with Banner, Delayed Gratification or Ramen.
- Ride the Bus with any face-card joker.
- Ceremonial Dagger with a valuable joker to its right.
- Madness with anything you care about.
- Stencil with 4+ other jokers.
- Burglar with discard jokers (Hit the Road, Yorick, Castle, Faceless, Mail-In, Trading Card, Burnt).

---

## 7. Build archetypes

Each archetype lists the hand type it wants, its core jokers (☆ = key payoff), its support, and the planet to level.

### 7.1 FLUSH (most consistent for an LLM)

- **Hand:** Flush. Planet: **Jupiter**.
- **Payoff (☆):** The Tribe (×2), Droll (+10), Crafty (+80c).
- **Enablers:** Smeared Joker (2 suit groups, so flushes are trivial), Four Fingers (4-card flush), Wild cards (The Lovers).
- **Suit jokers:** Lusty ♥, Greedy ♦, Wrathful ♠, Gluttonous ♣ (+3 Mult per scored card, ×5 cards = +15). Bloodstone ♥ (×1.5 per heart, 50%). Arrowhead ♠ (+50c per card). Onyx Agate ♣ (+7 per card). Rough Gem ♦ ($).
- **Bonus:** Blackboard ×3 with a ♠/♣ flush when the cards held are also dark. Smeared plus The Moon/World tarots help.
  Ancient Joker when its suit matches. Seltzer and Hanging Chad add retriggers.
- **Avoid:** Flower Pot, Seeing Double, Half Joker, Square Joker.
- **Tarots:** The Star/Moon/Sun/World (3 cards to one suit) toward one suit.
- **Discard rule:** discard off-suit cards. With 4 discards on Red Deck you hit a flush most rounds.

### 7.2 PAIR / TWO PAIR / FULL HOUSE (most common hands; easy to trigger)

- **Hand:** Pair (also reached inside Two Pair, Trips, Full House). Planets: **Mercury** (Pair) or **Uranus** (Two Pair).
  For Full House, **Earth**.
- **Payoff (☆):** The Duo (×2, any hand containing a pair), The Trio (×3 for Trips/Full House), The Family (×4).
- **Flat:** Jolly (+8), Sly (+50c), Mad (+10, Two Pair), Clever (+80c), Zany (+12), Wily (+100c).
- **Scaling:** Spare Trousers (+2 per Two Pair), Supernova, Card Sharp (×3, repeat the same hand type).
- **Small-hand:** Half Joker (+20) is on for Pair/Trips (≤3 cards). It does **not** trigger on Two Pair (4 cards) or Full House (5).
- **Bonus:** Seeing Double and Flower Pot (with mixed suits), Hanging Chad (pair of Aces), Scholar.
- **Rule:** pair-based builds are flexible and beat most bosses (Psychic: play the pair plus 3 junk cards).
  The Duo is the one joker that makes it scale.

### 7.3 HIGH CARD / ONE-CARD

- **Hand:** High Card (a single Ace). Planet: **Pluto**.
- **Core:** Supernova (High Card is played very often), Space Joker (levels it), Half Joker (+20), Hanging Chad (Ace scored 3×),
  Scholar (Ace +20c +4 per trigger), Photograph (with a face card), Blackboard (play the reds), Raised Fist, Baron (hold Kings), DNA.
- **Payoff:** Card Sharp (×3, every hand after the first) and Acrobat. Note: The Duo does NOT trigger on High Card.
- **Use:** simple to execute (one card per hand, the rest of the hand cycles junk). Weaker base, so it needs Card Sharp, Acrobat or Baron to scale.
  Fails vs The Psychic (must play 5 cards; the extra cards may still not score) and The Eye (no repeats).

### 7.4 FACE CARDS

- **Hand:** any. Pair or Full House of faces is natural.
- **Core:** Scary Face (+30c per face), Smiley Face (+5 per face), Photograph (×2 first face), Sock and Buskin (retrigger faces),
  Pareidolia (all cards are faces), Business Card ($), Midas Mask ($), Reserved Parking ($ held), Faceless Joker ($).
- **Legendaries:** Triboulet (K/Q ×2 each), Canio.
- **Conflicts:** Ride the Bus. **The Plant** (faces debuffed) and **The Mark** (faces face-down) bosses hurt. Keep Luchador or a backup.

### 7.5 BARON / MIME (STEEL KINGS)

- **Hand:** play anything small (Pair, High Card) while **holding** Kings.
- **Core:** Baron (×1.5 per King held). Mime retriggers held cards. Steel Kings via The Chariot (×1.5 each and Steel Joker).
  Red Seals on held Kings retrigger them too. Shoot the Moon (Queens held, +13 each). Raised Fist.
- **Deck:** add Kings (Death tarot copies a King, Cryptid), keep the hand small, thin the rest.
- **Late game:** 4 Steel Kings with Baron and Mime ≈ (1.5×1.5)^(2×4) ≈ ×656. That is the strongest scaling in the game, but slow to set up. B-tier for an LLM unless Baron appears early.
- **Conflicts:** Midas Mask, Vampire. Blackboard (Kings of red suits).

### 7.6 STRAIGHT

- **Hand:** Straight. Planet: **Saturn** (+3 Mult, +30 per level; strong).
- **Core:** The Order (×3), Crazy (+12), Devious (+100c), Runner (+15c per straight, scaling).
  Shortcut (gaps allowed) and Four Fingers (4-card) are almost required.
- **Bonus:** Superposition (Ace straight → tarot), Fibonacci (A-2-3-5-8), Hack (2-5), Even Steven or Odd Todd.
- **Rule:** without Shortcut or Four Fingers, straights are too inconsistent for an LLM. Don't commit before getting an enabler.

### 7.7 RETRIGGER

- **Core:** Hack (2-5), Sock and Buskin (faces), Dusk (last hand), Seltzer (all, 10 hands), Hanging Chad (first card ×2 more),
  Mime (held), Red Seals (Deja Vu spectral).
- **Pays off with:** per-card jokers (suit jokers, Fibonacci, Scholar, Even Steven, Odd Todd, Walkie, Scary/Smiley, Photograph,
  Triboulet, Bloodstone, Ancient, Idol, Wee Joker, Hiker) and Glass/Mult/Bonus cards.
- **Classic combos:** Hack + Wee Joker + Fibonacci (low cards). Sock and Buskin + Triboulet. Hanging Chad + Photograph
  (first face ×2 three times = ×8).

### 7.8 COPY: Blueprint / Brainstorm placement

- **Blueprint** copies the joker immediately to its **RIGHT**. Rule: Blueprint goes directly left of your best joker.
- **Brainstorm** copies the **LEFTMOST** joker (slot 1).
- Best combo: `[Blueprint][BEST xMult][...+Mult...][Brainstorm]`. Brainstorm copies Blueprint, which copies BEST. That's ×3 of the best joker.
  The trade-off: the best xMult joker sits left of the +Mult jokers. That is fine when the best joker is card-triggered (Triboulet, Photograph, Bloodstone).
  Fine when the xMult total is large anyway. Otherwise prefer `[+Mult...][Blueprint][BEST xMult]` and leave Brainstorm copying a +Mult joker.
- Copyable: score effects, retriggers (Hack, Sock, Mime...), on-blind-select creation (Cartomancer, Riff-Raff, Certificate, Marble).
- **Not copyable** (shows "incompatible"): rule changers (Four Fingers, Shortcut, Smeared, Pareidolia, Splash, Oops! All 6s, Showman,
  Chaos, Credit Card, Astronomer), hand-size/discard jokers (Juggler, Drunkard, Troubadour, Merry Andy, Turtle Bean), and most end-of-round
  money jokers (Golden Joker, Rocket, Cloud 9, Satellite, Delayed Gratification, Egg, Gift Card) (unverified for the money ones).
- Never leave Blueprint in the rightmost slot (nothing to copy). Never leave Brainstorm in slot 1 (it copies itself, so nothing).

### 7.9 Suggested default for the bot (Red Deck)

1. Antes 1-2: buy flat universal jokers (Gros Michel, Popcorn, Half, Jolly, Misprint, Supernova, Green, Abstract) and play **Pair/Two Pair** or **Flush**, whichever the jokers point to.
2. Ante 2-3: lock the hand type. Use planets only on it. Take The Duo or The Tribe instantly, plus Card Sharp, Cavendish and Blueprint.
3. Ante 4+: every shop, look for xMult first, then replace the weakest flat joker or decaying joker.

---

## 8. Joker ordering rules

1. **Slot order matters only for independent effects** (§1.4 step 3). Card-triggered effects happen during card scoring regardless of slot.
2. Order: **+Chips → +Mult (flat and scaling) → xMult → Polychrome jokers (their ×1.5 applies after their own effect) at the far right**.
   Inside the xMult group, order doesn't matter (multiplication commutes).
3. **Blueprint** sits immediately LEFT of the joker it should copy, usually the strongest xMult. **Brainstorm**: whatever is in slot 1 gets copied.
4. Economy and utility jokers have no scoring order. Put them anywhere, ideally left so the right side is clean for xMult.
5. **Ceremonial Dagger**: the joker to its RIGHT dies on blind select. Put it rightmost, or put a sacrificial joker to its right.
6. **Swashbuckler / Abstract / Bull / Bootstraps / Stencil** are independent: +Mult ones go left, Stencil goes right.
7. **Amber Acorn** (Ante 8 showdown) shuffles jokers face-down. You can't control order that round, so expect a lower score.
   **Crimson Heart** disables one random joker each hand.
8. After every purchase, sale or copy, re-check the order. The API has a joker re-order action (if available). Use it before the next round.

Order example: `[Banner +120c] [Jolly +8] [Supernova +N] [The Duo ×2] [Cavendish ×3]`.

---

## 9. How much is a joker worth vs money?

### 9.1 Spending rules by ante

| Phase | Rule |
| ----- | ---- |
| Ante 1 (start $4) | Buy the **first scoring joker** you can afford, even the $2 Joker. A Buffoon Pack ($4) is a good alternative. No reserve; interest doesn't matter yet. |
| Ante 1-2 | Buy any **A/S-tier** joker (§4) you can afford while slots are open. Keep **$0-5** reserve. |
| Ante 2-3 | Aim for 4-5 scoring jokers. Keep a reserve of **$10-15** after purchases, unless the item is S-tier xMult (always buy). |
| Ante 3-5 | Target a **$25 bank** (max interest). Spend only the money above $25, except to grab S/A-tier xMult or Blueprint/Brainstorm. Never pass up The Duo/Tribe/Cavendish/Card Sharp for interest. |
| Ante 6-8 | Interest matters less (few rounds left). Spend freely on xMult, planets for the main hand and rerolls to find xMult. Keep ~$5-10 for an emergency. |

Rough value of a slot: an S/A joker in Ante 1-3 is worth more than $25 of banked money. Interest compounds only $1-5 per round, while a scoring joker prevents a game over.

### 9.2 Reroll rule

Rerolls cost $5, +$1 each. Reroll only when **(a)** you have $25+ AND **(b)** you lack an xMult joker past Ante 3, or a slot is open.
Stop after 2-3 rerolls or when money drops to $20.

### 9.3 When to REPLACE (all 5 slots full)

Replace the weakest joker if the new one is clearly better:

- **Always:** a reliable xMult (Cavendish, Duo/Tribe/Trio for your hand, Card Sharp, Blueprint/Brainstorm with a good target) replaces any flat +Mult ≤ +10, any decaying joker near expiry, or any economy joker.
- **Usually:** +15 or better flat replaces +4 Joker, an off-plan hand-type joker, or a joker whose condition you rarely meet.
- **Never:** replace your only xMult with a flat joker, swap between near-identical jokers, or sell a scaling joker that has already grown big (Supernova at +20, Spare Trousers at +16, Constellation ×2) for a fresh flat joker.
- **Sell order (first to go):** dead or expiring decay jokers → off-plan conditional jokers → economy jokers (after Ante 4) → +Chips flat → +Mult flat → scaling → xMult (last).
- The sell loss is half the buy price, about $2-4. That is small compared with a joker that doubles your score.
  The existing prompt's "never sell" rule should be relaxed to "never sell to buy a sidegrade."

### 9.4 Quick scoring heuristic for comparing jokers

Estimate the new score of your main hand with the candidate in place: (chips + addChips) × (mult + addMult) × xMults.
Buy the joker with the larger relative gain. Rough equivalents with a typical Ante 3-4 lineup (~80 chips, ~20 mult):

- +4 Mult ≈ +20% · +10 Mult ≈ +50% · +15 Mult ≈ +75% · +50 Chips ≈ +60% · +100 Chips ≈ +125% (on Pair builds; less on Flush)
- ×1.5 = +50% · ×2 = +100% · ×3 = +200%. xMult wins once your mult is already ≥20.

---

## 10. Boss-blind interactions with jokers

| Boss | Joker impact | Response |
| ---- | ------------ | -------- |
| The Plant / The Mark | Face jokers dead | Play non-face hands. Sell Luchador to disable it. |
| The Club / Goad / Window / Head | Suit flush builds dead for that suit | Smeared helps (♣ debuffed but ♠ fine). Play other suits. |
| The Psychic | Must play 5 cards | Half Joker is off. Pair plus 3 junk still triggers Duo/Jolly. |
| The Eye | No repeated hand types | Card Sharp is off, Supernova weaker. Plan 4 different hands. |
| The Mouth | One hand type only | Fine for focused builds. |
| The Needle | 1 hand | Acrobat triggers (final hand). Card Sharp is off. Dusk triggers. |
| The Arm | Lowers hand level | Planet investment hurts. Play a different hand. |
| The Flint | Base halved | Flat +Mult jokers and xMult unaffected. Just score more. |
| The Ox | Most-played hand sets money to $0 | Cash out first, or play a different hand. Bad for Bull/Bootstraps. |
| The Water | 0 discards | Banner = 0 chips, Mystic Summit = +15 immediately, Hit the Road dead. |
| The Manacle | −1 hand size | Pairs with Stuntman/Merry Andy for misery. |
| The Pillar | Played cards debuffed | Scaling jokers fine. Card-triggered jokers weaker. |
| Verdant Leaf (A8) | All cards debuffed until you sell a joker | Sell your weakest (economy) joker on hand 1. |
| Crimson Heart (A8) | Random joker disabled each hand | Redundant xMult helps. |
| Amber Acorn (A8) | Jokers flipped and shuffled | Ordering is lost. |
| Cerulean Bell (A8) | One card forced selected | Minor. |
| Violet Vessel (A8) | 6× blind (300k) | Need a real xMult engine. Chicot or Luchador disables it. |

---

## 11. Compact prompt snippet (candidate text for STRATEGY.md.jinja)

```
JOKER RULES
- Score = chips x mult. Early: +Mult/+Chips. By Ante 4: own >=1 xMult. By Ante 6: >=2 xMult.
- Ante 1-2: buy any affordable scoring joker; fill 5 slots by Ante 3.
- Universal early picks: Gros Michel, Popcorn, Half Joker, Supernova, Joker, Misprint, Abstract,
  Green Joker, Ride the Bus, Ice Cream, Blue Joker, Banner (+30 chips per discard left).
- Always buy if affordable: Cavendish, The Duo (pair), The Tribe (flush), Card Sharp, Blueprint, Brainstorm,
  and The Trio/Order/Family if they match your hand.
- Hand jokers trigger if the hand CONTAINS the type (Full House contains Pair and Three of a Kind).
- Order: +Chips, +Mult, then xMult rightmost. Blueprint copies RIGHT neighbour; Brainstorm copies slot 1.
- Pick ONE hand type (Pair/Two Pair or Flush) by Ante 3; level it with planets; buy jokers for it.
- Economy jokers (Golden Joker, Rocket, Egg, To the Moon) only after 2 scoring jokers; sell them by Ante 5 for xMult.
- Replace weakest joker when new one is xMult or clearly stronger. Never sell your only xMult.
- Decaying jokers (Ice Cream, Popcorn, Seltzer, Ramen, Gros Michel) are temporary: plan replacements.
- Avoid: Ceremonial Dagger, Madness, Obelisk, Mr. Bones, Burglar, Stuntman, Merry Andy, Throwback,
  Driver's License, Stencil when slots are full, conditional jokers you cannot trigger.
- Luchador: sell it DURING a dangerous boss blind to disable it.
- Keep $25 for interest from Ante 3, but never skip an xMult joker to save money.
```

---

## 12. Uncertainties / things to verify against the live game

- Exact base costs for a few jokers (±$1), especially Fibonacci (repriced in 1.0.1), Stuntman, Driver's License and Matador (unverified).
- Whether Blueprint/Brainstorm copy end-of-round money jokers (Golden Joker, Rocket, Cloud 9, Satellite). I believe they do NOT (unverified).
- To the Moon's interaction with the $5 interest cap. I believe it adds $1 per $5 within the same cap of five $5-steps, so +$5 max (unverified).
- Blackboard triggers when no cards are held in hand (believed true; unverified).
- Edition surcharges for Polychrome and Negative jokers (unverified exact).
- Confirmed by web search: Hanging Chad retriggers the first card 2 times and Smiley Face gives +5 Mult (1.0.1 changes).
- Fetch access needed for full verification: balatrowiki.org and balatrogame.fandom.com were blocked by the session network policy.

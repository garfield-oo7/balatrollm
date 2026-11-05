# 03 — Economy, Shop Decisions, Rerolls, Booster Packs, Vouchers, Skip Tags

Scope: vanilla Balatro v1.0.1 rules, **Red Deck, White Stake**, small-LLM bot (Claude Haiku).

**Sourcing note.** WebFetch could not reach balatrowiki.org, balatrogame.fandom.com, gameplay.tips or
github.io from this session, because those hosts are not on the session's network allowlist.
WebSearch did work, and its snippets confirmed several facts:
- the $3/$4/$5 blind rewards and the $8 Showdown reward
- Red Stake removing the Small Blind reward
- the first-shop Buffoon Pack guarantee from 1.0.1
- the Investment Tag paying $25 and the Economy Tag cap of $40
- the Speed, Handy, Garbage, Juggle, D6 and Orbital tag values
- which stakes add the Eternal, Perishable and Rental stickers

Everything else comes from the author's own knowledge of the game. Facts the author is less sure of are
marked **(unverified)**.

---

## TOP 15 RULES FOR A SMALL LLM

1. **Interest:** at the end of each round you earn $1 for every $5 you hold, up to $5 (reached at $25).
   It is counted on the money you hold when the blind is beaten, before that round's payout.
   **Leave the shop holding a multiple of $5.** $24 earns the same as $20.
2. **Every unused hand pays $1. Discards pay $0** (only Green Deck pays for discards). Use your 4 Red Deck
   discards to dig for cards before you spend a hand as a discard.
3. **Ante 1: spend everything on scoring.** Interest does not matter yet. The goal is 2 Jokers by the
   Ante 1 Boss, and at least one of them must add Mult.
4. **Ante 2–3: build toward $25.** Buy only Jokers or vouchers that raise your score. Reach $25 by the end
   of Ante 3.
5. **Ante 4–6: keep $25 as a floor.** Spend only the money above $25. There are three exceptions:
   - an xMult Joker that fits your hand
   - Grabber, Paint Brush or Antimatter
   - you **failed the power check** (rule 6). Survival beats interest.
6. **Power check (do it every shop):** if you beat the last blind with **2 or more hands left**, you are on
   track, so save. If you used every hand or nearly lost, **spend now**, even below $25. The next blind is
   about 1.5× to 2.5× harder.
7. **Ante 7–8: interest is nearly worthless now.** Spend down to $0 on anything that adds score. From the
   Ante 8 shops onward, spend everything.
8. **A $0 item is free. Always take it** (from Coupon or a Joker tag). Sell your weakest Joker if you need
   the slot.
9. **Joker buy order:**
   1. xMult that fits your hand
   2. +Mult that fits your hand, or generic +Mult
   3. scaling Jokers
   4. +Chips
   5. economy Jokers (Ante 1–2 only)

   Never fill your 5th slot with something weak. If the slots are full, replace your weakest Joker only
   when the new one is clearly better. The real cost is the price minus the old Joker's sell value.
10. **Planet card in the shop for your main hand: buy it ($3) and use it now.** Use every Planet and every
    Black Hole immediately. Do not hold them, unless you own Observatory.
11. **Packs:**
    - A Buffoon Pack is the best early buy, but only if you have a free Joker slot.
    - A Celestial Pack is good once you have a main hand.
    - Arcana is okay.
    - Standard and Spectral are skips.
    - Never open a pack you cannot use. A Buffoon Pack with full Joker slots is wasted.
12. **Reroll ($5, then +$1 each) only when all of these are true:** a Joker slot is empty, nothing in the
    shop is worth buying, and you will still meet your money floor afterward. The floor is $5 in Ante 1–2
    and $25 + the reroll cost from Ante 4 on. Make at most 2 rerolls per shop (3 if you have no +Mult Joker
    yet).
13. **Must-buy vouchers ($10)**, if you are above your floor or the voucher is critical: Grabber, Paint
    Brush, Antimatter, Clearance Sale (early), and Nacho Tong or Palette.
    **Never buy** Tarot/Planet Merchant or Tycoon, Magic Trick, Illusion, Omen Globe, Money Tree, Hone or
    Glow Up. Buy Blank only when you have $35 or more, because it exists only to unlock Antimatter.
14. **Skipping:**
    - Never skip in Ante 1.
    - Never skip a Big Blind.
    - From Ante 2 on, skip the **Small Blind** only when the tag is Investment, Negative, Rare,
      Polychrome, Holographic, Uncommon, Coupon or Buffoon, **and** you beat the last blind with 2 or more
      hands left.
    - Economy Tag counts only if you hold $20 or more.
    - Handy Tag counts only in Ante 4 or later.
15. **Keep shop visits short:** about 6 actions at most, then `next_round`. If you have bought nothing and
    the shop has nothing useful, leave right away.

---

## ERRORS FOUND IN CURRENT STRATEGY.md

Only the economy and shop areas were checked carefully. A few obvious errors in other areas are listed at
the end.

| # | Current text | Problem | Fix |
|---|---|---|---|
| E1 | "Common – 70%, Uncommon – 25%, Rare – 5%, Legendary – only a 0.3%" | Legendary Jokers **never** appear in the shop or in Buffoon Packs. They come only from **The Soul** (Spectral). | "Shop/Buffoon Joker rarity: Common 70%, Uncommon 25%, Rare 5%. Legendary only via The Soul." |
| E2 | "Each round provides 4 hands and 3 discards" | The bot plays the **Red Deck**, which has **4 discards**. | Template it from the deck, or state "Red Deck: 4 hands, 4 discards." |
| E3 | Blind rewards are not mentioned | The bot cannot weigh skips or plan its economy without them. | "Rewards: Small $3, Big $4, Boss $5, Ante 8 Showdown $8. Plus $1 per unused hand, plus interest. Discards pay $0." |
| E4 | "Black Hole … Save for Ante 7+" | Wrong. Levels apply to every later hand, so holding Black Hole wastes value and a consumable slot. | "Use Planets and Black Hole immediately (unless you own Observatory)." |
| E5 | "For Arcana/Spectral packs, cards are used immediately … Buffoon/Standard packs add cards" | Celestial is not mentioned. Planets picked from a Celestial pack are also used immediately. Pack sizes and prices are missing. | Add the pack table (section 4). |
| E6 | "Hoarding Money: Interest caps at $5 – spending … often yields better returns" next to "Reach $25 as quickly as possible" | The two lines contradict each other, and a small model cannot resolve that. | Replace both with the ante-by-ante economy plan (section 2). |
| E7 | "NEVER SELL JOKERS UNLESS ABSOLUTELY NECESSARY", with the example "you have Flush Five but switched to pairs" | Flush Five is a hand, not a Joker. The rule is also too absolute: with 5 slots full the bot can never upgrade. | "Sell only to (a) take a $0/free Joker, (b) replace your weakest Joker with a clearly stronger one, (c) cash out Egg or economy Jokers in late antes." |
| E8 | "Smiley Face (+4 Mult for face cards)" | Smiley Face gives **+5 Mult** per scored face card. | Change to +5. |
| E9 | No skip tags and no skip guidance at all | The TOOLS for BLIND_SELECT include `skip`, but bot.py hard-codes `select`. | Add the tag table and the skip rule (section 6). |
| E10 | "Vouchers … refresh or restock after the players first completed round, or after defeating the boss blind" | Unclear. There is **one voucher per Ante**. It stays in every shop of that Ante until you buy it, and a new one appears after the Boss is beaten. Upgraded vouchers (Nacho Tong, Antimatter, …) appear only after you own the base voucher. | Reword as stated. |
| E11 | Voucher, pack and reroll prices are missing | The bot cannot budget. | Voucher $10; packs $4/$6/$8; Tarot/Planet $3; reroll $5 +$1. |
| E12 | "Strategic Discarding Through Playing … If you can score ANY points, play the hand with maximum cards rather than discarding" | This is an economy error. Every hand you play is $1 you don't get, and with 4 Red Deck discards you rarely need to burn a hand to dig. | "Use discards first to dig. Play a weak hand as a discard only when discards are 0." |
| E13 (other area) | Poker hand list says "weakest to strongest" but lists strongest first. Five of a Kind, Flush House and Flush Five are missing. | — | Fix the ordering note. |
| E14 (other area) | Editions: "Negative: +1 Joker Slot when scored" | Negative is not triggered by scoring. It simply adds a Joker slot. | Change the wording. |

The voucher list in the prompt was verified against the author's knowledge and is **correct**. That covers
all 32 vouchers in 16 pairs, including Blank → Antimatter, Grabber → Nacho Tong, Wasteful → Recyclomancy,
Hieroglyph → Petroglyph, Paint Brush → Palette, Director's Cut → Retcon, and Crystal Ball → Omen Globe.
The Tarot list, the Planet chip and Mult values, The Hermit (max $20) and Temperance (max $50) are also
correct.

---

## 1. Money mechanics (exact numbers)

### 1.1 Income

| Source | Amount (White Stake) | Notes |
|---|---|---|
| Starting money | **$4** | Some decks change this (Yellow Deck: +$10). Red Deck does not. |
| Small Blind reward | **$3** | Red Stake and above: $0. Not relevant here. |
| Big Blind reward | **$4** | |
| Boss Blind reward | **$5** | |
| Showdown Boss (Ante 8) | **$8** | |
| Each unused hand | **$1** | Paid at cash-out. |
| Each unused discard | **$0** | Only Green Deck pays ($1 per discard, $2 per hand, but no interest). |
| Interest | **$1 per $5 held, max $5** | The cap is $10 with Seed Money ($50 held) and $20 with Money Tree ($100 held). It is computed on money held when the blind is beaten, before that round's payout. |
| Skipping a blind | **$0**, no shop, no interest that round | You get only the tag. |

### 1.2 Typical income per Ante

Assumes you win each blind with about 2 hands left.

| Situation | Blinds | Hands | Interest | **Total per Ante** |
|---|---|---|---|---|
| Broke (bank under $5) | 3+4+5 = 12 | ~6 | 0 | **~$18** |
| Bank $10 | 12 | ~6 | 6 | **~$24** |
| Bank $25 | 12 | ~6 | 15 | **~$33** |

**Result: holding $25 is worth about $15 per Ante, or about 45% of your income.** Each $5 below $25 costs
$1 per round, which is $3 per Ante.

### 1.3 Prices

| Item | Price | Notes |
|---|---|---|
| Common Joker | ~$1–$6 (most $4–$5) | Each Joker has its own base price. Trust the shop's displayed price. |
| Uncommon Joker | ~$5–$8 (most $6–$7) | |
| Rare Joker | ~$7–$10 (most $8) | |
| Legendary Joker | $20 (sell value only; never sold in the shop) | Only from The Soul. |
| Edition surcharge on Jokers | Foil +$2, Holo +$3, Polychrome +$5, Negative +$5 **(unverified)** | |
| Tarot card | $3 | |
| Planet card | $3 | |
| Spectral card | $4 | Not sold in the shop on the Red Deck (Ghost Deck only). |
| Playing card (needs Magic Trick) | ~$1–$3 | |
| Booster Pack | Normal **$4**, Jumbo **$6**, Mega **$8** | |
| Voucher | **$10** | Clearance Sale and Liquidation probably also discount vouchers ($7/$5) **(unverified)**. |
| Reroll | **$5**, +$1 per reroll in the same shop, reset each shop | Reroll Surplus makes it $3 and Reroll Glut $1. D6 Tag starts it at $0. Chaos the Clown gives 1 free reroll per shop. |
| Discounts | Clearance Sale −25%, Liquidation −50% | Applies to cards and packs. Price = max($1, floor((base + edition + 0.5) × (1 − discount))) **(formula unverified)**. |

### 1.4 Sell value

- **Sell value = max($1, floor(buy cost / 2))**, using the price you actually paid (including the
  edition surcharge). A $5 Joker sells for $2 and a $6 Joker for $3.
- Some effects add to the sell value: Egg gives +$3 per round, and Gift Card gives +$1 per round to every
  Joker and consumable. Temperance pays out the total sell value of your Jokers (max $50).
- Consumables sell for floor($3 / 2) = $1.
- The loss on a buy-then-sell round trip is about half the price, so avoid churn.

### 1.5 Stickers (Eternal, Perishable, Rental)

**These do not exist on White Stake. Ignore them.**
- **Eternal** (cannot be sold or destroyed) starts at **Black Stake**.
- **Perishable** (debuffed after 5 rounds) starts at **Orange Stake**.
- **Rental** ($3 per round, buy price $1) starts at **Gold Stake**.

All of these were confirmed by search. Lower stakes on the way: Red Stake removes the Small Blind reward,
Green Stake makes required scores scale faster, Blue Stake gives −1 discard, Purple Stake scales scores
faster again. The GAMESTATE template can keep its sticker branches; they will just never render.

### 1.6 Blind score targets, White Stake (for the power check)

Base score per Ante. Small = ×1, Big = ×1.5, Boss = ×2. The Wall is ×4, The Needle ×1, and Violet Vessel
×6 at Ante 8.

| Ante | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Small | 300 | 800 | 2,000 | 5,000 | 11,000 | 20,000 | 35,000 | 50,000 |
| Big | 450 | 1,200 | 3,000 | 7,500 | 16,500 | 30,000 | 52,500 | 75,000 |
| Boss | 600 | 1,600 | 4,000 | 10,000 | 22,000 | 40,000 | 70,000 | 100,000 |

Score targets roughly **double or triple every Ante**. Flat +Mult and +Chips carry you to about Ante 4.
Beyond that you need **xMult** and **hand levels**. This is why the bot stalls at the Ante 4 Boss
(10,000).

---

## 2. Economy plan by Ante (Red Deck, White Stake)

| Ante | Money goal | Spending policy | Joker goal by the Boss |
|---|---|---|---|
| **1** | Ignore interest | The first shop always has a **Buffoon Pack** (patch 1.0.1). Buy the best +Mult Joker in the shop, or the Buffoon Pack if no good Joker is there. Spend down to $0 if it buys score. | 2 Jokers, at least one +Mult |
| **2** | End the Ante with ≥ $10 | Buy Jokers that add Mult or Chips for your main hand. Make 1–2 rerolls only if a Joker slot is empty and money is ≥ $10. Buy a Planet for your main hand. | 3 Jokers |
| **3** | **Reach $25** by the end of the Ante | Buy only above $15, except for xMult or must-buy vouchers. | 4 Jokers, ideally 1 xMult or a scaling Joker |
| **4–6** | **Keep a $25 floor** | Spend only the surplus. Break the floor for: an xMult Joker that fits, Grabber, Paint Brush, Antimatter, or a failed power check. Upgrade from 4 to 5 Jokers. Replace your weakest flat Joker with xMult. | 5 Jokers, ≥ 2 xMult, main hand Lv 4+ |
| **7** | Floor $10–$15 | Interest is worth ≤ $5 × the remaining rounds (~6). Buying power is now worth more than that. | Maximize score |
| **8** | **$0** | Spend everything on score. Sell economy Jokers (Egg, Golden Joker, Rocket, To the Moon, Cloud 9) to replace them with score. | — |

**When to break the bank, in priority order:**
1. You nearly lost or lost hands last blind (failed power check).
2. A fitting **xMult Joker** is in the shop.
3. Grabber, Paint Brush, Antimatter, or Clearance Sale in Ante 1–3.
4. A $0 or free item needs a slot. Selling a Joker is fine here.

**Compounding math.** Interest does not compound past the cap. Going from $20 to $25 adds +$1 per round.
Dipping $10 below the cap costs $2 per round until you recover, about $6 per Ante. One good Joker bought
in Ante 2–3 usually lets you win with 1–2 extra hands left, which is +$1–$2 per round. That partly pays the
interest back, and the extra power keeps you alive. **Below Ante 3, power > interest. From Ante 3 to 6,
interest wins unless power is lacking.**

**Economy Jokers.** Golden Joker ($4 per round), Egg, Rocket, To the Moon (+$1 interest per $5), Delayed
Gratification, Cloud 9 and Business Card are worth buying only in Ante 1–2, and only if they cost ≤ $6 and
a slot is free. Sell them from Ante 5 on when you need the slot. **Avoid Credit Card.**

Delayed Gratification gives $2 per discard but only if you use **no** discards that round. Red Deck's 4
discards make that $8, but it fights your digging, so skip it for a small LLM.

---

## 3. Shop decision algorithm (every visit)

The bot's shop tools are `buy(card|voucher|pack)`, `reroll`, `sell`, `use`, `rearrange` and `next_round`.
Follow these steps in order. **Budget: about 6 actions per shop.**

```
STEP 0  Read: money M, ante A, joker count J/limit, the last blind's hands_left H.
        Floor F = 0 (Ante 1) | 5 (Ante 2) | 15 (Ante 3) | 25 (Ante 4-6) | 10 (Ante 7) | 0 (Ante 8)
        Power OK = (H >= 2). If not OK: F = 0 for this shop (spend to survive).

STEP 1  FREE STUFF: any shop item with cost $0 -> buy it (sell your weakest Joker first if slots are full).

STEP 2  JOKERS (look at both shop cards):
        Buy if (M - price >= F, or it is a fitting xMult) and it ranks highly:
          xMult for your hand > +Mult for your hand > generic +Mult > scaling > +Chips > economy (Ante 1-2)
        Slots full? Replace your weakest Joker only if the new one is clearly stronger
          (an xMult replacing a flat Joker, or a hand-matching Joker replacing an off-plan one).

STEP 3  PLANETS in the shop: a Planet for your main hand -> buy ($3) and `use` it immediately.
        Tarots: buy only with an immediate clear use (Hermit if M is $8-$20; Temperance if Joker
        sell values total >= $8; a suit changer for a Flush build). Otherwise skip.

STEP 4  VOUCHER: buy if it is Tier S, or Tier A and M - 10 >= F (see section 5).

STEP 5  PACKS: buy at most 1 pack per shop (2 only in Ante 1-2 if rich), if M - price >= F:
          Buffoon (needs a free slot) > Celestial (once you have a main hand) > Arcana > skip Standard/Spectral.

STEP 6  REROLL only if ALL are true:
          - a Joker slot is empty, or you own no xMult Joker in Ante 4+
          - nothing in the current shop passed Step 2
          - M - reroll_cost >= F (Ante 1-2: M - cost >= 5)
          - rerolls this shop < 2 (or < 3 if you own no +Mult Joker)
        After the reroll, go back to Step 1.

STEP 7  `next_round`. Before leaving, check: is M just above a multiple of 5? Then the extra $1-$4 is
        "free" to spend (e.g., a $3 Planet), but never drop below a multiple of 5 you had reached.
```

**Joker ordering reminder:** +Chips and +Mult on the left, xMult on the right. Rearrange after every Joker
purchase.

**Reroll expectations.** Each reroll gives 2 new shop cards. Each card is about 71% likely to be a Joker
(shop weights roughly Joker 20 : Tarot 4 : Planet 4) **(weights unverified)**, and each Joker is 5% likely
to be Rare. Expect about 1.4 Jokers per reroll. A reroll is worth it when any decent +Mult Joker would
help a lot, which is true early. It is a poor deal for hunting one specific Joker.

**Tarot/Planet Merchant warning.** These vouchers raise the Tarot or Planet share of the shop, so you see
**fewer Jokers**. That is bad for this bot.

---

## 4. Booster packs

### 4.1 Sizes and prices

| Pack | Normal ($4) | Jumbo ($6) | Mega ($8) | Contents are… |
|---|---|---|---|---|
| **Arcana** | choose 1 of 3 | 1 of 5 | 2 of 5 | Tarots, used immediately. Your hand is drawn so you can pick targets. |
| **Celestial** | 1 of 3 | 1 of 5 | 2 of 5 | Planets, used immediately. Black Hole can rarely appear. |
| **Standard** | 1 of 3 | 1 of 5 | 2 of 5 | Playing cards (often enhanced or sealed), added to the deck. |
| **Buffoon** | 1 of 2 | 1 of 4 | 2 of 4 | Jokers. **Needs a free Joker slot.** |
| **Spectral** | 1 of 2 | 1 of 4 | 2 of 4 | Spectrals, used immediately. Hand is drawn. |

- You may skip inside a pack, but the money is already spent.
- Buffoon and Spectral packs appear less often in the shop than Arcana, Celestial and Standard **(rates
  unverified)**. When you see a Buffoon Pack early with a free slot, take it.
- The bot cannot `sell` while a pack is open; the pack state has only the `pack` tool. **So do not open a
  Buffoon Pack with full Joker slots.**

### 4.2 Value by stage

| Stage | Best pack | Why |
|---|---|---|
| Ante 1–2 | **Buffoon** > Celestial (if you have a main hand) > Arcana | Jokers are the run's engine. |
| Ante 3–5 | Celestial (main hand) ≈ Buffoon (free slot) > Arcana | Hand levels scale your base chips and Mult. |
| Ante 6–8 | Celestial (Mega, main hand) > Buffoon (only for xMult) | Each level adds +2 to +3 Mult and ~+15 to +30 Chips. |
| Never | Standard (weak), Spectral (too swingy for a small LLM unless it is a Mega pack and you have one empty slot for The Soul) | |

### 4.3 What to pick inside each pack

**Buffoon:** use the same order as the shop, xMult > +Mult for your hand > generic +Mult > scaling >
chips > economy. Take a Negative edition Joker almost always (it adds +1 slot).

**Celestial:**
1. The Planet for your **main hand**. With Telescope, it is always in the pack.
2. **Black Hole**, which levels every hand +1.
3. The Planet for your second hand (e.g., Pair Planet for a Two Pair or Full House build).
4. Otherwise pick any Planet. It is free value, but prefer the hands you play.

Planet values per level:

| Planet | Hand | Per level |
|---|---|---|
| Pluto | High Card | +1 Mult, +10 Chips |
| Mercury | Pair | +1 Mult, +15 Chips |
| Uranus | Two Pair | +1 Mult, +20 Chips |
| Venus | Three of a Kind | +2 Mult, +20 Chips |
| Saturn | Straight | +3 Mult, +30 Chips |
| Jupiter | Flush | +2 Mult, +15 Chips |
| Earth | Full House | +2 Mult, +25 Chips |
| Mars | Four of a Kind | +3 Mult, +30 Chips |
| Neptune | Straight Flush | +4 Mult, +40 Chips |

**Arcana**, a simple priority list:
1. **Judgement**: a random Joker, if a slot is free.
2. **The Hermit**: doubles money, up to +$20. Great when you hold $10–$20.
3. **Temperance**: pays your Jokers' total sell value (max $50).
4. A **suit changer** for a Flush build (Star/Moon/Sun/World, 3 cards). Change off-suit cards to your
   main suit.
5. **Enhancers on cards you play:** Empress (2 Mult cards), Hierophant (2 Bonus), Chariot (Steel, held),
   Justice (Glass), Lovers (Wild), Magician (Lucky), Devil (Gold, $3 per round when held).
6. **The Hanged Man** (destroy 2 junk cards) or **Death** (copy a good card onto a junk card).
7. **High Priestess** (2 Planets, needs consumable slots) or **Wheel of Fortune** (25% chance of a Joker
   edition).
8. Skip **The Fool** or **Emperor** unless you have nothing better. Use **Strength** only for Straight
   builds.

**Spectral** (only when forced, e.g. by an Ethereal Tag):
- Take: **The Soul** (Legendary, needs a slot), **Black Hole**, **Wraith** (Rare Joker, but sets money to
  $0, so take it only when broke), **Cryptid**, **Aura**, **Talisman**, **Deja Vu**, **Immolate** (+$20,
  destroys 5 cards), **Grim**, **Familiar**, **Incantation**.
- Avoid **Hex** and **Ankh** unless you have only 1 good Joker.
- Avoid **Ectoplasm** and **Ouija**, which cost −1 hand size.
- **Sigil** is situational: good for a Flush build when your hand has many cards.

**Standard:** pick a card with a **Red Seal**, a **Glass** or **Steel** enhancement, or a **Polychrome**
edition, of your main suit or rank. Otherwise skip the pick; adding junk cards thins out your good draws.

---

## 5. Vouchers (16 pairs, 32 total; $10 each; one per Ante)

An upgraded voucher appears only after you own its base voucher.

| Tier | Voucher | Effect | Rule for the bot |
|---|---|---|---|
| **S** | **Grabber** | +1 hand per round | Buy even below the floor. It is +1 scoring attempt and +$1 per round. |
| **S** | **Paint Brush** | +1 hand size | Buy even below the floor. Better hands and better digging. |
| **S** | **Antimatter** (needs Blank) | +1 Joker slot | Buy whenever you can. |
| **A** | **Nacho Tong** (needs Grabber) | +1 hand again | Buy above the floor. |
| **A** | **Palette** (needs Paint Brush) | +1 hand size again | Buy above the floor. |
| **A** | **Clearance Sale** | −25% on cards and packs | Buy in Ante 1–3. It pays for itself after about $40 of spending. Skip it in Ante 7+. |
| **A** | **Overstock** | 3 shop card slots | More Jokers per visit. Buy in Ante 1–5. |
| **A** | **Telescope** | Celestial packs always contain the Planet for your most played hand | Buy if you are committed to one hand. |
| **A** | **Observatory** (needs Telescope) | Planets held in consumable slots give ×1.5 Mult to their hand | Strong late. Hold 2 copies of your main Planet for ×2.25. Needs a rule: "do not use Planets once you own Observatory, keep 1–2." |
| **B** | **Wasteful** | +1 discard | Red Deck already has 4, so this is a lower priority. Buy only above the floor. |
| **B** | **Reroll Surplus** | Rerolls −$2 | Only for a reroll-heavy plan or Flash Card. |
| **B** | **Crystal Ball** | +1 consumable slot | Okay with Observatory or many Planets. |
| **B** | **Liquidation** (needs Clearance) | −50% total | Buy above the floor in Ante 3–5. |
| **B** | **Blank** | Does nothing; unlocks Antimatter | Buy only when you hold $35+ in Ante 2–5 (total cost $20 for +1 Joker slot). |
| **B/C** | **Director's Cut** | Reroll the Boss once per Ante ($10 per roll) | Useful against hard-counter bosses, but needs extra logic. Skip by default. |
| **C** | **Seed Money** | Interest cap $10 ($50 held) | A small LLM rarely holds $50. Skip. |
| **C** | **Hieroglyph** | −1 Ante, −1 hand per round | See the note below. Skip unless you own Grabber and are winning in 1–2 hands. |
| **C** | **Petroglyph** (needs Hieroglyph) | −1 Ante again, −1 discard | Same conditions as Hieroglyph. The −1 discard costs less on the Red Deck. |
| **C** | **Planet Merchant** | Planets 2× more often in the shop | Fewer Jokers per visit. Skip. |
| **C** | Reroll Glut, Recyclomancy, Retcon | — | Skip. |
| **D** | Tarot Merchant, Tarot Tycoon, Planet Tycoon, Magic Trick, Illusion, Omen Globe, Hone, Glow Up, Money Tree | They dilute the Joker pool or have no effect on scoring | **Never buy.** |

**Hieroglyph note.** −1 Ante drops the current requirement by about half (Ante 6 Boss 40,000 → Ante 5 Boss
22,000), and you replay an Ante, which means 3 more shops and about $30 more income. The cost is −25% of
your hands for the rest of the run.
- For a struggling bot it buys time, but it also stretches the run.
- For the benchmark metric (round reached), it adds rounds.
- For actually **winning Ante 8**, it is mainly good when your build scales (scaling Jokers keep growing
  during the extra Ante).
- Recommendation: Tier C, except Tier A if you own Grabber and Ante ≥ 4.
- **(Judgment call; community opinion is mixed.)**

---

## 6. Skip tags (24 in v1.0.1)

Tag shown on the Small and Big Blind at BLIND_SELECT. The template already renders
`G.blinds.small.tag_name` and `tag_effect`. Tags marked ≥A2 cannot appear in Ante 1 **(min-ante list from
the author's knowledge, unverified)**.

| Tag | Effect | Min Ante | Value (White Stake, small LLM) |
|---|---|---|---|
| **Investment** | Gain **$25** after defeating the next Boss | 1 | **S**: net about +$15 after the skip cost. |
| **Negative** | Next base-edition shop Joker is **free and Negative** (+1 slot) | ≥A2 | **S** |
| **Rare** | Next shop has a **free Rare Joker** | 1 | **S** (random, but often strong) |
| **Polychrome** | Next base-edition shop Joker is **free and Polychrome** (×1.5) | 1 | **S** |
| **Holographic** | … free and Holographic (+10 Mult) | 1 | **A** |
| **Uncommon** | Next shop has a **free Uncommon Joker** | 1 | **A** |
| **Foil** | … free and Foil (+50 Chips) | 1 | **B+** (still a free Joker) |
| **Coupon** | Initial cards and packs in the next shop are free | 1 | **A** (~$10–$20 of value) |
| **Buffoon** | Free **Mega Buffoon Pack** (2 of 4 Jokers) | ≥A2 | **A** if you have 2 free slots, **B** if 1 |
| **Economy** | Doubles your money (max **+$40**) | 1 | **A** if money ≥ $20, **C** if money < $10 |
| **Handy** | $1 per hand played this run | ≥A2 | **C** in Ante 2 (~$8–$12), **A** in Ante 4+ (~$25+) |
| **Garbage** | $1 per unused discard this run | ≥A2 | **B/C** (Red Deck means more unused discards) |
| **Meteor** | Free **Mega Celestial Pack** (2 of 5) | ≥A2 | **B+** once you have a main hand |
| **Orbital** | Upgrades the hand named on the tag by **3 levels** | ≥A2 | **A** if the named hand is your main hand, **C** otherwise |
| **Charm** | Free **Mega Arcana Pack** (2 of 5) | 1 | **B** |
| **Top-up** | Creates up to 2 Common Jokers (needs room) | ≥A2 | **B** in Ante 2–3 with 2+ free slots |
| **Voucher** | Adds 1 extra Voucher to the next shop (you still pay $10) | 1 | **B** |
| **D6** | Rerolls in the next shop start at $0 | 1 | **C** (good only with spare money) |
| **Speed** | $5 per blind skipped this run | 1 | **C** (only $5 on your first skip) |
| **Double** | Copies the next tag you gain | 1 | **C** (too complex; treat as skip-worthy only if the Big Blind tag is S) |
| **Boss** | Rerolls the upcoming Boss Blind | 1 | **C**. Situational: only if the shown Boss hard-counters your build. |
| **Juggle** | +3 hand size next round | 1 | **D** (lasts one round only) |
| **Standard** | Free Mega Standard Pack | ≥A2 | **D** |
| **Ethereal** | Free Spectral Pack | ≥A2 | **D** (swingy) |

(Free-Joker tags trigger in the **next shop you enter**. The Joker shows a price of $0, and the LLM must
still `buy` it. Tell it so.)

### 6.1 Cost of skipping

Skipping a Small Blind forfeits:
- the $3 reward
- about $1–$3 for unused hands
- that round's interest (up to $5)
- **one shop visit** (2 cards, 2 packs, a chance at a Joker)

Total: **$5–$11 plus a shop.** Scaling Jokers (Green Joker, Ride the Bus, Supernova, Runner, …) also miss
a round of growth. You then face the Big Blind (1.5× the Small) with no new purchases. Only tags worth
more than about $10 plus a shop should be taken. In practice that means **free Jokers, Investment,
Coupon, or Economy with a full bank.**

Skipping the **Big Blind** costs the same and sends you into the Boss with no shop since the Small Blind.
**Never do it with this bot.**

### 6.2 Recommended rule

This is **simple, conservative and deterministic. Better in Python than by the LLM.**

```
At BLIND_SELECT:
  if current blind is Big or Boss            -> select
  if ante == 1                               -> select
  tag = G.blinds.small.tag_name
  strong = {Investment, Negative, Rare, Polychrome, Holographic, Uncommon, Coupon}
  if jokers_free_slots >= 2: strong += {Buffoon}
  if money >= 20:            strong += {Economy}
  if ante >= 4:              strong += {Handy}
  comfortable = (last blind won with hands_left >= 2) and (joker_count >= min(ante, 4))
  if tag in strong and comfortable           -> skip
  else                                       -> select
```

- Free-Joker tags need a slot in the next shop. If slots are full, the bot should sell its weakest Joker
  (allowed by rule 8).
- **Expected impact: small but positive.** Free Jokers and Investment are about the best value per skip
  in the game. The current bottleneck, though, is shop and Joker quality plus hand play, not skips.
  Implement this after the shop rules.
- If skip is left to the LLM instead, put a 3-line version of this rule in the prompt. The bot must call
  the LLM at BLIND_SELECT, which costs one extra call per Small Blind.

---

## 7. Red Deck specifics (+1 discard → 4 discards per round)

- **Digging is cheap.** With 4 discards (up to 20 cards cycled), **Flush** is the most reliable hand to
  build. Pursue it more aggressively than on other decks.
- **Discards pay nothing; hands pay $1.** Always use discards to dig before throwing a weak hand away.
  This fixes E12.
- **Synergy Jokers become better:**
  - **Banner** (+30 Chips per remaining discard, up to +120)
  - **Green Joker** (penalizes discards, so be careful)
  - **Hit the Road**, **Castle**, **Yorick**, **Faceless Joker**, **Trading Card** and **Burnt Joker** (the
    first discard levels that hand)
  - **Ramen** gets worse, because it loses ×Mult per card discarded.
  - **Mystic Summit** (+15 Mult at 0 discards) is harder to trigger, since you have more discards to spend.
- **Wasteful drops in value** (Tier B), because you already have the extra discard.
- **Garbage Tag** gets slightly better.
- **The Water** (0 discards) hurts more because you rely on discards.
- Petroglyph's −1 discard still leaves 3.

---

## 8. Compact prompt block (suggested drop-in, ~40 lines)

```
## Money
- Blind rewards: Small $3, Big $4, Boss $5 (Ante 8 Boss $8). +$1 per unused HAND. Discards pay $0.
- Interest: +$1 per $5 held when the blind is won, max $5 at $25. Leave shops at a multiple of $5.
- Prices: Jokers ~$4-$8 (Rare ~$8-$10), Tarot/Planet $3, packs $4/$6/$8, voucher $10, reroll $5 (+$1 each).
- Sell value = half the price, rounded down. Selling loses half: only sell to replace your weakest Joker or to take a free one.

## Money floor by Ante (do not spend below it unless noted)
- Ante 1: $0 (buy 2 Jokers, one adding Mult). Ante 2: $5. Ante 3: $15. Ante 4-6: $25. Ante 7: $10. Ante 8: $0.
- Ignore the floor for: a $0 item, a fitting xMult Joker, Grabber, Paint Brush, Antimatter,
  or if you won the last blind with fewer than 2 hands left (you are too weak, so spend to get stronger).

## Shop, in order (max ~6 actions, then next_round)
1. Buy anything that costs $0.
2. Buy the best Joker you can afford above the floor: xMult (fits your hand) > +Mult (fits) > +Mult > scaling > +Chips.
   Slots full: sell your weakest Joker only if the new one is clearly stronger. Keep +Mult left, xMult right.
3. Planet for your main hand: buy and use now. Use every Planet and Black Hole immediately.
4. Voucher: Grabber / Paint Brush / Antimatter always; Nacho Tong / Palette / Clearance Sale / Overstock /
   Telescope if above the floor. Never: Merchant/Tycoon, Magic Trick, Illusion, Omen Globe, Hone, Glow Up, Seed Money.
5. Packs (max 1): Buffoon (only with a free Joker slot) > Celestial (main hand) > Arcana. Skip Standard and Spectral.
6. Reroll only if a Joker slot is empty, nothing is worth buying, and you stay above the floor. Max 2 rerolls.

## Inside packs
- Buffoon: same Joker order as the shop. Celestial: main-hand Planet > Black Hole > second-hand Planet.
- Arcana: Judgement (free slot) > Hermit ($10-$20 held) > Temperance > suit changer to your Flush suit >
  Empress/Hierophant/Chariot/Justice/Lovers on cards you play > Hanged Man on junk cards.

## Skipping (Small Blind only, Ante 2+)
Skip only if the tag is Investment, Negative, Rare, Polychrome, Holographic, Uncommon or Coupon
(also Economy if you hold $20+), AND you won the last blind with 2+ hands left. Otherwise select.
```

---

## 9. Implementation notes for bot.py (economy and skip)

1. **Skip:** replace the hard-coded `select` in `BLIND_SELECT` with a Python helper that implements
   section 6.2. Read `G.blinds.small.status == "CURRENT"`, `G.blinds.small.tag_name`, `G.ante_num`,
   `G.money` and `G.jokers.count/limit`.
   - "Won last blind with ≥ 2 hands left" needs `hands_left` saved at `ROUND_EVAL`, before `cash_out`.
   - Match tag names by substring ("Investment", "Negative", …), because the exact strings are unknown
     **(verify the tag_name format from a gamestate dump)**.
2. **Money floor in GAMESTATE:** render one line in the SHOP state:
   `Money floor this ante: $F (you may spend $M-F)`. Computing it in Jinja saves the small model from doing
   the arithmetic.
3. **Power check in GAMESTATE:** render `Last blind won with H hands left → ON TRACK / TOO WEAK, spend`.
4. **Shop action cap:** after about 8 shop actions, nudge the LLM with "leave the shop now" in memory, or
   force `next_round`. This prevents reroll loops that drain money.
5. **Pack guard:** if a Buffoon pack is chosen while `jokers.count == jokers.limit`, refuse it (return a
   failed call with a reason). The pack state cannot sell to make room.

---

## Sources (WebSearch snippets; the wiki pages themselves could not be fetched)

- Blind rewards, Showdown $8, Red Stake: [vgkami](https://vgkami.com/?p=51252),
  [Wikipedia: Balatro](https://en.wikipedia.org/wiki/Balatro),
  [saschb2b mechanics: decks & stakes](https://saschb2b.github.io/game-mechanics/games/balatro/decks-and-stakes),
  [saschb2b: blinds & bosses](https://saschb2b.github.io/game-mechanics/games/balatro/blinds-and-bosses)
- First-shop Buffoon Pack (1.0.1): [Nintendo Life](https://www.nintendolife.com/news/2024/04/balatro-is-getting-its-first-major-update),
  [Gameranx 1.0.0f patch notes](https://gameranx.com/features/id/497453/article/baltro-1-0-0f-patch-notes)
- Tags: [Dot Esports](https://dotesports.com/?p=1157226), [Escapist](https://www.escapistmagazine.com/?p=184813),
  [Gameranx: every tag](https://gameranx.com/features/id/495210/article/balatro-every-tag-explained/),
  [vgkami](https://vgkami.com/?p=51216), [games.gg economy guide](https://games.gg/balatro/guides/balatro-economy-guide/)
- Stickers by stake: [Fandom: Stickers](https://balatrogame.fandom.com/wiki/Stickers),
  [dood.gg Black Stake](https://dood.gg/en/balatro/stakes/black-stake),
  [dood.gg Orange Stake](https://dood.gg/en/balatro/stakes/orange-stake),
  [dood.gg Gold Stake](https://dood.gg/en/balatro/stakes/gold-stake)
- Vouchers: [games.gg voucher tier list](https://games.gg/balatro/guides/balatro-vouchers-tier-list/),
  [thetoptens](https://www.thetoptens.com/games/balatro-vouchers/) (one snippet wrongly claimed Antimatter
  adds a discard; it adds +1 Joker slot), [dood.gg voucher guide](https://dood.gg/en/balatro/guides/voucher-guide)

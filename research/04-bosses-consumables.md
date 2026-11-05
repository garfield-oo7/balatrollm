# 04 – Boss Blinds, Consumables, Modifiers & Deck Manipulation

Scope: vanilla Balatro v1.0.1, Red Deck (4 hands, **4 discards**, 8 hand size), White Stake.
Sources: WebFetch could not reach any wiki (balatrowiki.org, balatrogame.fandom.com, dood.gg and the
IGN mirror all failed DNS in this sandbox; they have to be allowed in the session's network settings).
WebSearch summaries (Steam forums, Fandom snippets, guides) were used to check the less certain points.
Everything else comes from my own knowledge of the v1.0.1 game data (`game.lua` P_BLINDS / P_CENTERS)
and from reading the BalatroBot Lua source (`src/lua/utils/gamestate.lua`, `endpoints/play.lua`, `openrpc.json`).
Facts marked **(unverified)** need a check against the game files.

---

## TOP 15 RULES FOR A SMALL LLM

1. **Read the Boss at the start of every Ante.** The BLIND_SELECT screen shows the Boss name and effect before the Small Blind. Write it into your reasoning and prepare for it in both shops of that Ante. You cannot reroll the Boss through the API, so **never buy Director's Cut or Retcon**.
2. **Psychic: always select exactly 5 cards.** Unscored filler is fine. A Pair plus 3 junk cards is legal and scores normally.
3. **Mouth: your first hand locks the hand type for the round.** Make that first hand your main/strongest type, and use discards first to build it.
4. **Eye: every hand must be a new type.** Play your main type once, at its strongest. Spend the other hands on different types (Pair, Two Pair, Three of a Kind, High Card, Straight, Flush…).
5. **Needle: you get 1 hand, against a 1× target.** Use all discards first to build the single best hand, then play it.
6. **Water: you have 0 discards.** Play 5-card hands every time so the unscored cards cycle.
7. **Tooth: you lose $1 per card played.** Play only the scoring cards and cycle with discards.
8. **Hook / Serpent / Manacle / Fish / House / Mark / Wheel change what is in your hand.** Re-read the hand after every action and never assume a card is still there. Face-down cards still score normally.
9. **Suit bosses (Club, Goad, Window, Head) debuff one suit, Wild Cards included.** Debuffed cards still form hand types but add 0 chips and their enhancements do nothing. Build hands from the other suits, or play a Flush anyway if its base value plus your Jokers is enough.
10. **Plant: face cards are debuffed** (with Pareidolia, every card is debuffed). Play number cards and Aces.
11. **Verdant Leaf (Ante 8): sell your cheapest/weakest Joker before the first hand.** All cards stay debuffed until you do.
12. **Ox: the boss text names a hand type.** Playing it sets money to $0. If you have ≥$10 and another hand type can win, avoid it. Otherwise winning comes first.
13. **Use Planets on your main hand type, and use Black Hole at once.** Never "save Black Hole for Ante 7". Its levels pay off on every hand from now on.
14. **Enhance cards you will actually score** (Mult, Bonus, Glass, Lucky, Wild, Foil/Holo/Poly, Red Seal, Gold Seal). **Put Steel, Gold and Blue Seal on cards you will HOLD**, not play. Suit tarots go on off-suit cards, converting them into your flush suit.
15. **Avoid these Spectrals:** Ankh/Hex (they destroy Jokers; safe only with exactly 1 Joker), Ouija and Ectoplasm (they lose hand size), and Wraith (money to $0; take it only when broke and a Joker slot is free). Always safe: Black Hole, The Soul (with an empty Joker slot), Talisman, Deja Vu, Trance, Medium, Aura, Cryptid, Grim/Familiar/Incantation.

---

## ERRORS FOUND IN CURRENT STRATEGY.md

| # | Location / claim | Problem | Fix |
|---|---|---|---|
| 1 | Editions: "**Negative**: +1 Joker Slot when scored. This edition is only available to Jokers." | Wrong. Negative is passive and is not tied to scoring. On a Joker it gives +1 Joker slot; on a consumable, +1 consumable slot; on a playing card, **+1 hand size**. Negative playing cards are almost never obtainable in vanilla (unverified: Standard packs roll editions with `no_neg`). | "Negative: +1 Joker slot (Jokers) / +1 consumable slot / +1 hand size (playing card)." |
| 2 | Restriction blinds: "The Psychic: Must play 5 cards – **incompatible with Pair/Two Pair/Trips strategies**" | Wrong. Unscored cards are allowed, so Pair + 3 filler scores as a Pair. Psychic barely hurts any build. | "Always select exactly 5 cards (filler is fine)." |
| 3 | "Showdown Blinds … are **identical** to regular Boss Blinds" | Misleading. They appear only at Ante 8 (and 16, 24… in endless), pay $8 instead of $5, and include **Violet Vessel at 6×** (300,000 at Ante 8 White). | State the 6× and the Ante 8 timing. |
| 4 | "The Wall: Extra large blind" / "The Needle: Play only 1 hand" / "Violet Vessel: Very large blind" | The multipliers are missing. Wall = **4×**, Needle = **1×** (lower target), Vessel = **6×**; every other boss = 2×. | Add the multipliers. |
| 5 | "Boss Blinds are randomly selected." | Incomplete. The boss is chosen when the Ante starts and is **visible during BLIND_SELECT before the Small Blind**. Bosses have minimum antes (see table), and the game avoids repeating a boss until the others in its pool have appeared. | Tell the model to plan around the known boss. |
| 6 | Spectral timing: "**Black Hole**: Save for Ante 7+" | Bad advice. +1 level to every hand is worth the same or more when used early, and holding it wastes a consumable slot. | "Use Black Hole immediately." |
| 7 | "**Ankh** (copies a Joker, destroys others): Use when you have one exceptional Joker worth duplicating" | Ankh copies a **random** Joker, so the player cannot choose which. With 2+ Jokers it can wipe the build. | "Use Ankh only if you own exactly 1 Joker (and have a free slot)." Same rule for Hex. |
| 8 | Tarot: "Death: … convert the left card into the right card (**Drag to rearrange**)" | The bot cannot drag. In code, the selected card with the larger x-position (rightmost = higher hand index) is the template, and the other selected card becomes a copy of it (unverified that T.x always follows index after a `rearrange`). | "Death: of the 2 selected cards, the one with the LOWER hand index becomes a copy of the one with the HIGHER index. Use `rearrange` first if needed." |
| 9 | "Tarot Card Priority" puts Hermit last and has no targeting rules | Weak. Hermit is economy-critical at ≥$20 (+$20). There are no rules for which cards to target. | Use the ranked guide below. |
| 10 | Modifiers intro: "There are **4 types** of Modifiers: Editions, Enhancements, and Seals." | Lists 3 types. | "3 types". |
| 11 | "Editions are permanent and cannot be overwritten." | Partly inconsistent. Aura and Wheel of Fortune only apply to items **without** an edition (unverified for Aura). Editions are not removed except by Ankh (removes Negative from its copy). | Minor wording fix. |
| 12 | Spectral cards: "They can be find only in Booster Packs." | Also from Seance, Sixth Sense, Ethereal Tag and Ghost Deck. The Soul can also appear in Arcana packs, and Black Hole in Celestial packs. | Minor. |
| 13 | Planet Cards: "obtained through … **two specific Tarot cards**" | Only The High Priestess creates Planets. The Fool can repeat the last Planet used. | Minor. |
| 14 | Planet list: only 9 Planets | The 3 secret Planets are missing: **Planet X** (Five of a Kind +3 Mult/+35 Chips), **Ceres** (Flush House +4/+40), **Eris** (Flush Five +3/+50). Each appears only after you have played that hand type this run. | Add them as a one-line note. |
| 15 | Debuff Blinds: "The Pillar: Debuffs previously played cards – save best cards for Boss" | The debuff covers cards played **earlier this Ante** (Small, Big and the boss round itself), not the whole run. | Clarify the "this Ante" scope. |
| 16 | Preparation: "Keep one 'emergency' consumable for Boss Blind adaptation" | Too vague to act on, and few consumables counter a boss. | Replace with the concrete prep rules below. |
| 17 | (Outside my area, noted in passing) High Card "Base Chips: 4" | Base is **5 chips × 1 Mult**. The example's "(11 + 5)" is correct and contradicts the stated value. The list is labelled "weakest to strongest" but runs strongest-first. Initial setup says 3 discards, but the benchmark **Red Deck has 4**. | Fix. |
| 18 | Boss list: "The Arm: Decrease level of played poker hand by 1" | It omits that the level loss is **permanent for the run**, not just this round (community-confirmed). Hands already at level 1 lose nothing. | Add "permanent". |

**Template/infra gaps (not text errors, but they hurt boss play):**
- `GAMESTATE.md.jinja` shows the boss name and effect only in BLIND_SELECT and while the boss is the current blind. **In SHOP it shows nothing.** BalatroBot sends `G.blinds.boss.name/effect/score` in every state (`get_blinds_info()`), so the template should print "Upcoming Boss: {{name}} – {{effect}} (target {{score}})" in SHOP and during Small/Big rounds. This change matters most: the shop before the boss is where you prepare.
- BalatroBot has **no reroll-boss endpoint** (methods: add, buy, cash_out, discard, gamestate, health, load, menu, next_round, play, rearrange, reroll (shop), save, screenshot, select, sell, set, skip, start, use). So Director's Cut and Retcon ($10 each) do nothing for the bot. Tell it never to buy them.
- **Cerulean Bell:** `play.lua` calls `G.hand:unhighlight_all()` before clicking the requested cards (the code comments that this "could interfere with … Cerulean Bell"). The template also never renders `state.highlight`, so the bot cannot see which card is forced. Render "FORCED (always selected)" and tell the bot to include that card among its ≤5 selections (exact API behaviour unverified).
- Hidden cards render as "the card is face down" with no identity, which is correct. The bot just needs to be told that hidden cards still score.

---

## 1. Blind scores (White Stake, Red Deck)

| Ante | Base (Small 1×) | Big 1.5× | Boss 2× | The Wall 4× | The Needle 1× | Showdown 2× / Violet Vessel 6× |
|---|---|---|---|---|---|---|
| 1 | 300 | 450 | 600 | – (min ante 2) | – | |
| 2 | 800 | 1,200 | 1,600 | 3,200 | 800 | |
| 3 | 2,000 | 3,000 | 4,000 | 8,000 | 2,000 | |
| 4 | 5,000 | 7,500 | 10,000 | 20,000 | 5,000 | |
| 5 | 11,000 | 16,500 | 22,000 | 44,000 | 11,000 | |
| 6 | 20,000 | 30,000 | 40,000 | 80,000 | 20,000 | |
| 7 | 35,000 | 52,500 | 70,000 | 140,000 | 35,000 | |
| 8 | 50,000 | 75,000 | – | – | – | **100,000 / 300,000** |

Rewards: Small $3, Big $4, Boss $5, Showdown $8, plus $1 per unused hand plus interest. Boss blinds cannot be skipped.
Boss selection: each Ante picks a boss whose min ante ≤ current ante. The game prefers bosses used least so far, so repeats are rare. Ante 8 always picks a Showdown boss.

---

## 2. Boss Blinds: effect, min ante, multiplier, counter-play

Only these **8 bosses can appear in Ante 1**: Hook, Club, Psychic, Goad, Window, Manacle, Pillar, Head. All 23 are possible from Ante 6.
Min antes are from game data as I remember it; Ox = 6 and Needle = 2 are confirmed by search; the others are **(unverified)** but high-confidence.

| Boss | Effect (exact) | Min Ante | Mult | One-line counter-play for the LLM |
|---|---|---|---|---|
| **The Hook** | Discards 2 random cards held in hand after every hand played | 1 | 2× | Play 5-card hands so only 3 cards are held. Don't hold pieces for a later combo; build and play the best hand now. Use normal discards freely; Hook's discards are a free cycle. |
| **The Club** | All Club cards are debuffed | 1 | 2× | Score with non-Club cards. A Club flush still counts as Flush (base + hand-type Jokers) but Club cards add 0 chips. |
| **The Goad** | All Spade cards are debuffed | 1 | 2× | Same as The Club, for Spades. |
| **The Window** | All Diamond cards are debuffed | 1 | 2× | Same as The Club, for Diamonds. |
| **The Head** | All Heart cards are debuffed | 1 | 2× | Same as The Club, for Hearts. |
| **The Psychic** | Must play 5 cards | 1 | 2× | Always select exactly 5 cards and pad with junk. Hands with <5 cards score **0**. |
| **The Manacle** | −1 hand size (7 cards) | 1 | 2× | Discard more aggressively. Prefer hand types that need fewer specific cards (Pair/Two Pair/Trips over Straight). |
| **The Pillar** | Cards played previously this Ante are debuffed | 1 | 2× | In Small/Big of a Pillar ante, play your key/enhanced cards as little as possible (plain cards or discards instead). In the boss round, build from cards not marked Debuff. Discarded cards are NOT affected. |
| **The Wall** | Extra large blind | 2 | **4×** | Pure score check. In the prior shop buy scoring (Joker, Planet for main hand), not economy. Use every hand at maximum score. |
| **The Needle** | Play only 1 hand | 2 | **1×** | Use ALL discards first to build your single best hand, then play once. A Pair is often enough early (target = 1× base). |
| **The Water** | Start with 0 discards | 2 | 2× | Play 5 cards every hand (scoring + junk) to cycle. Don't start a combo you can't finish in 4 draws. |
| **The Mouth** | Play only 1 hand type this round | 2 | 2× | The first hand locks the type. Discard until you hold your main type, then play it. Later hands must be that type or they score 0. |
| **The Fish** | Cards drawn face down after each hand played | 2 | 2× | The first hand is normal. After that, a discard draws face-up cards (unverified, community reports). Hidden cards still score, so use them as filler in 5-card plays. |
| **The House** | First hand is drawn face down | 2 | 2× | The whole first 8-card hand is hidden. Discard 5 hidden cards to see 5 new ones (you have 4 discards) instead of playing blind. |
| **The Mark** | All face cards are drawn face down | 2 | 2× | Every hidden card is a J, Q or K (10 chips). Build visible hands. Hidden cards are good filler/kickers and still trigger face-card Jokers. |
| **The Wheel** | 1 in 7 cards drawn face down | 2 | 2× | Mostly ignore it. Treat hidden cards as unknown filler, or discard them if you need specific cards. |
| **The Arm** | Decrease level of played poker hand by 1 (before scoring) | 2 | 2× | The level loss is **permanent**. Win in as few hands as possible. If a level-1 hand type you don't care about scores enough, play that instead of your main hand. |
| **The Flint** | Base Chips and Mult of played poker hands are halved | 2 | 2× | Joker and card bonuses are not halved. Play your biggest-hand-type hands, and use every hand for score. |
| **The Tooth** | Lose $1 per card played | 3 | 2× | Play only the scoring cards (Pair = 2 cards). Cycle with discards, which are free. |
| **The Eye** | No repeat hand types this round | 3 | 2× | Play each type once. Save your main type for when you hold its strongest version. Plan 4 distinct types (main, Pair, Two Pair, Trips/High Card). |
| **The Plant** | All face cards are debuffed | 4 | 2× | Score with A and 2–10. With **Pareidolia every card is debuffed**, so sell Pareidolia if it doesn't beat the boss anyway. Face-card builds need a backup plan. |
| **The Serpent** | After play or discard, always draw exactly 3 cards | 5 | 2× | Discard 1–2 cards at a time to GROW your hand (draw 3). Playing 5 cards shrinks the hand by 2, so make every 5-card play count. |
| **The Ox** | Playing a #(most played hand) sets money to $0 | **6** | 2× | The text names the hand. If you have money and another type can win, avoid it. If it's needed to survive, play it (losing money beats losing the run). |
| **Amber Acorn** (Showdown) | Flips and shuffles all Joker cards | 8 | 2× | Joker order is randomised and hidden, and effects still work. You may lose ×Mult ordering, so bring margin. Nothing else to do. |
| **Verdant Leaf** (Showdown) | All cards debuffed until 1 Joker sold | 8 | 2× | Before the first play, SELL your cheapest/weakest Joker. Prepare by keeping a cheap spare Joker in the last shop of Ante 7/8. |
| **Violet Vessel** (Showdown) | Very large blind | 8 | **6×** | 300,000 at White. Only a fully scaled build wins, so every hand must be max score. |
| **Crimson Heart** (Showdown) | One random Joker disabled every hand | 8 | 2× | No control. Redundant Jokers help, and if one hand is weak the next may roll differently. |
| **Cerulean Bell** (Showdown) | Forces 1 card to always be selected | 8 | 2× | Build each play or discard around the forced card. Discarding it forces a new random card (community). API: include the forced card in your selection (unverified). |

Hard counters to know: **Chicot** (Legendary) disables every boss. **Luchador**: sell it during a boss round to disable that boss. **Matador** pays $8 when a hand triggers the boss ability. Boss Tag (from skipping) rerolls the boss.

### 2a. Which bosses kill which builds, and how to prep in the shop before

The bot sees the boss in BLIND_SELECT at the start of the Ante, so it can prep across 2 shops. Prep rules:

| Build | Dangerous bosses | Prep in the prior shop |
|---|---|---|
| **Flush (mono-suit)** | Suit boss on YOUR suit (Club/Goad/Window/Head); Water, Needle (fewer draws); Tooth ($5/hand); Psychic is harmless | Keep some unconverted cards of a 2nd suit and level a backup hand (Pair/Two Pair). For a suit boss on your suit, a Flush still gets base Flush chips×mult plus hand-type Jokers (Droll/Crafty/Tribe); check whether that's enough. Buy a +chips/+mult Joker not tied to suit. |
| **Pair / Two Pair / Trips / Full House** | Eye (needs variety), Mouth (fine if first hand right), Arm (permanent level loss), Plant if face-heavy | Have a 2nd leveled hand for the Eye. Psychic: pad to 5. Tooth: play only scoring cards. |
| **Face-card (Scary Face, Smiley, Photograph, Sock and Buskin, Pareidolia)** | **Plant** (deadly), Mark (hidden but still score) | When the ante's boss is Plant, buy a generic +Mult/×Mult Joker or Planet for a number-card hand. Sell Pareidolia if it would debuff the whole deck. |
| **Straight** | Water, Needle, Manacle, Serpent (draw dependent), Hook | Prefer Four Fingers/Shortcut. Keep Pair/Two Pair levels as backup. |
| **Held-in-hand (Steel, Baron, Mime, Gold cards, Shoot the Moon)** | Hook (discards held cards), Manacle, Serpent | Accept it. Play 5 cards per hand to keep steel cards held. |
| **Economy (high $, interest)** | Ox ($0), Tooth | Under the Ox, spend money in the shop before the boss if a good buy exists (money can't be lost if already spent). |
| **Any build** | Wall (4×), Flint, Needle, Violet Vessel (6×), Crimson Heart, Amber Acorn, Verdant Leaf | Before the Wall/Vessel, prioritise raw scoring buys: Planet for the main hand, ×Mult Joker. Before Ante 8, keep a cheap Joker to sell for Verdant Leaf. |

**Director's Cut / Retcon:** in vanilla these let you pay $10 to reroll the boss during blind select. **BalatroBot exposes no endpoint for it**, so for this bot they are a wasted $10 and must be skipped. (If the API adds one later: reroll Wall, Plant (face build), your-suit boss (flush build), Arm, Ox, Needle and Water when you have ≥$10 above your interest threshold.)

**Skipping Small/Big blinds before a nasty boss:** skipping gives a Tag but also skips that blind's shop and reward. Not recommended for a small LLM, except that a Boss Tag (reroll boss) is strong.

---

## 3. Tarot cards (22), exact effects and usage

| Tarot | Exact effect (v1.0.1) | Targets | Tier | When / which targets |
|---|---|---|---|---|
| **The Fool** | Creates a copy of the last Tarot or Planet used this run (not The Fool) | 0 | B | Good if the last used was a Planet for your main hand or a strong Tarot. Check the effect text, which names the card. |
| **The Magician** | Enhances up to 2 cards → **Lucky** | 1–2 | B | Lucky: 1 in 5 +20 Mult, 1 in 15 $20 when scored. Put it on cards you score often. |
| **The High Priestess** | Creates up to 2 random Planet cards (needs room) | 0 | A | Use with ≥1 empty consumable slot, then use the planets that match your hand type. |
| **The Empress** | Enhances up to 2 cards → **Mult** (+4 Mult when scored) | 1–2 | **S** early | Best early enhancement. Target the cards of your main suit/rank. |
| **The Emperor** | Creates up to 2 random Tarot cards (needs room) | 0 | A | Use with empty slots. |
| **The Hierophant** | Enhances up to 2 cards → **Bonus** (+30 Chips when scored) | 1–2 | A | Same targeting as Empress. |
| **The Lovers** | Enhances 1 card → **Wild** (counts as every suit) | 1 | A (flush) / C | Flush builds: convert an off-suit card. Wild is debuffed by ALL suit bosses. |
| **The Chariot** | Enhances 1 card → **Steel** (×1.5 Mult while HELD in hand) | 1 | A | Target a card you won't play (off-suit or off-rank). Huge with Baron (Kings) and Mime. Each held Steel card = ×1.5. |
| **Justice** | Enhances 1 card → **Glass** (×2 Mult when scored, 1 in 4 destroyed after scoring) | 1 | **S** | Target a card you score every hand (main suit/rank). Put it rightmost among scoring cards. |
| **The Hermit** | Doubles money, gaining at most $20 | 0 | **S** at ≥$20 / A otherwise | Use at money ≥$20 (+$20 = 4 interest steps). At <$10, hold it if you have a slot. |
| **The Wheel of Fortune** | 1 in 4 chance to add Foil, Holo or Polychrome to a random Joker without an edition | 0 | C | Free gamble with no downside. Use it if you have a Joker with no edition. |
| **Strength** | Increases rank of up to 2 cards by 1 (K→A, A→2) | 1–2 | B | Pair builds: bump a 9 into a 10 you have several of. Face builds: 10→J. |
| **The Hanged Man** | Destroys up to 2 selected cards | 1–2 | A (thin) | Destroy off-suit (flush) or lonely low ranks (pairs). Never destroy enhanced, sealed, Aces or main-suit cards. |
| **Death** | Select 2 cards: the LEFT card becomes a copy of the RIGHT card (suit, rank, enhancement, seal, edition) | exactly 2 | **S** | Put your best card (e.g. Glass/Mult card of main rank/suit) at the HIGHER index and junk at the lower index. Great for both pair and flush builds. |
| **Temperance** | Gives the total sell value of current Jokers (max $50) | 0 | A | Use at once if it gives ≥$4. Better later as Joker sell values grow. |
| **The Devil** | Enhances 1 card → **Gold** ($3 if held in hand at end of round) | 1 | A early | Target an off-suit/off-rank card you'll hold. |
| **The Tower** | Enhances 1 card → **Stone** (+50 Chips, no rank/suit, always scores) | 1 | C | Breaks flushes and pairs. Only use it on a junk card, as a chip filler in 5-card plays. Usually skip. |
| **The Star** | Converts up to 3 cards → **Diamonds** | 1–3 | **S** (flush) | Off-suit cards → your main suit only. |
| **The Moon** | Converts up to 3 cards → **Clubs** | 1–3 | **S** (flush) | Same. |
| **The Sun** | Converts up to 3 cards → **Hearts** | 1–3 | **S** (flush) | Same. |
| **The World** | Converts up to 3 cards → **Spades** | 1–3 | **S** (flush) | Same. |
| **Judgement** | Creates a random Joker (needs an empty Joker slot) | 0 | A early / C late | Free Joker early. Late, you may get a weak Joker; you can sell it. |

**Tarot rules for the LLM:**
- If a Tarot needs targets and nothing in the shown hand is a good target, **skip** it (in packs) or hold it.
- Priority with no build yet: Empress, Justice, Death, Hierophant, Hermit, Temperance, Judgement and High Priestess are always useful.
- Suit tarots commit you to Flush. Pick the suit you already have most of, or the suit your Jokers want (Lusty: Hearts, Greedy: Diamonds, Wrathful: Spades, Gluttonous: Clubs).
- **Scored vs held:** Mult/Bonus/Glass/Lucky/Wild/Foil/Holo/Poly/Red Seal/Gold Seal go on cards you SCORE. Steel/Gold/Blue Seal go on cards you HOLD. Purple Seal goes on junk you DISCARD.

---

## 4. Planet cards

| Planet | Hand | Base Chips×Mult (L1) | Per level |
|---|---|---|---|
| Pluto | High Card | 5 × 1 | +10 Chips, +1 Mult |
| Mercury | Pair | 10 × 2 | +15, +1 |
| Uranus | Two Pair | 20 × 2 | +20, +1 |
| Venus | Three of a Kind | 30 × 3 | +20, +2 |
| Saturn | Straight | 30 × 4 | +30, +3 |
| Jupiter | Flush | 35 × 4 | +15, +2 |
| Earth | Full House | 40 × 4 | +25, +2 |
| Mars | Four of a Kind | 60 × 7 | +30, +3 |
| Neptune | Straight Flush | 100 × 8 | +40, +4 |
| **Planet X** (secret) | Five of a Kind | 120 × 12 | +35, +3 |
| **Ceres** (secret) | Flush House | 140 × 14 | +40, +4 |
| **Eris** (secret) | Flush Five | 160 × 16 | +50, +3 |

- Secret planets only appear (shop and Celestial packs) after you've played that hand type this run.
- **Black Hole** (Spectral, also rare in Celestial packs) gives +1 level to every hand. **Use it immediately.**
- Rules: in a Celestial pack, take the Planet for your main hand. If none matches, take your backup hand's planet (Pair/Two Pair are good backups for Eye/Mouth bosses). Planets for hands you never play are worthless.
- Blue Seal: if the card is held at end of round, it creates the Planet for the last hand played that round (needs a free consumable slot).
- Observatory voucher: each Planet held gives ×1.5 Mult to its hand. Telescope: Celestial packs always include your most-played hand's Planet.

---

## 5. Spectral cards (18): exact effects and accept/skip

| Spectral | Exact effect | Verdict for a small LLM |
|---|---|---|
| **Familiar** | Destroy 1 random card in hand, add 3 random Enhanced face cards to hand | SAFE (good for face builds; slightly dilutes a flush deck) |
| **Grim** | Destroy 1 random card in hand, add 2 random Enhanced Aces | SAFE (good) |
| **Incantation** | Destroy 1 random card in hand, add 4 random Enhanced numbered cards (2–10) | SAFE |
| **Talisman** | Add a Gold Seal to 1 selected card ($3 when it scores) | SAFE. Put it on a card you score often. |
| **Aura** | Add Foil, Holographic or Polychrome (random) to 1 selected card in hand | SAFE. Put it on your best scored card (Poly ×1.5, Holo +10 Mult, Foil +50 Chips). |
| **Wraith** | Creates a random Rare Joker, sets money to $0 | CONDITIONAL: only if money ≤ $5 and a Joker slot is free |
| **Sigil** | Converts all cards in hand to a single random suit | CONDITIONAL: good for flush builds (more cards of one suit), neutral otherwise. Skip if you've built a different suit and the random suit could fight it. |
| **Ouija** | Converts all cards in hand to a single random rank, **−1 hand size** | SKIP (hand size is critical). Exception: a pure Four/Five of a Kind build. |
| **Ectoplasm** | Add Negative to a random Joker, **−1 hand size** (penalty grows by 1 each use, per community) | SKIP |
| **Immolate** | Destroys 5 random cards in hand, gain $20 | CONDITIONAL: take it if the shown hand has ≤2 cards you care about (no enhanced or main-suit cards). +$20 and 5-card thinning is strong. |
| **Ankh** | Create a copy of a random Joker, destroy all other Jokers (removes Negative from the copy) | SKIP, unless you own **exactly 1 Joker** and have a free slot (then it's a free duplicate) |
| **Deja Vu** | Add a Red Seal to 1 selected card (retrigger) | SAFE. Best on a Glass/Mult/Steel card or main-rank card. |
| **Hex** | Add Polychrome to a random Joker, destroy all other Jokers | SKIP, unless you own **exactly 1 Joker** |
| **Trance** | Add a Blue Seal to 1 selected card | SAFE. Put it on a card you'll usually HOLD (off-suit). |
| **Medium** | Add a Purple Seal to 1 selected card (Tarot when discarded) | SAFE. Put it on a junk card you'll discard. |
| **Cryptid** | Create 2 copies of 1 selected card in hand | SAFE. Copy your best enhanced/main-rank card (great for pairs/trips; Glass/Steel copies are strong). |
| **The Soul** | Creates a Legendary Joker (needs room) | SAFE. Must-take if a Joker slot is empty. Sell your weakest Joker first if needed. |
| **Black Hole** | Upgrade every poker hand by 1 level | SAFE. Use immediately. |

Simple rule: **if you can't explain why the downside doesn't matter right now, skip the Spectral.** Skipping a pack card is always legal.

---

## 6. Enhancements, Seals, Editions (verified numbers)

**Enhancements** (1 per card; a new one replaces the old):
| Enhancement | Effect | Applied by |
|---|---|---|
| Bonus | +30 Chips when scored | Hierophant |
| Mult | +4 Mult when scored | Empress |
| Wild | Counts as every suit (debuffed by every suit boss; reverts to base suit when debuffed) | Lovers |
| Glass | ×2 Mult when scored; 1 in 4 chance destroyed after scoring | Justice |
| Steel | ×1.5 Mult while held in hand (not when played) | Chariot |
| Stone | +50 Chips, no rank or suit, always scores (unless debuffed) | Tower |
| Gold | $3 if held in hand at end of round | Devil |
| Lucky | 1 in 5: +20 Mult; 1 in 15: $20 (when scored) | Magician |

**Seals** (1 per card):
| Seal | Effect | From |
|---|---|---|
| Gold | +$3 when played and scored | Talisman |
| Red | Retrigger the card once (scored effects, and held effects like Steel/Gold) | Deja Vu |
| Blue | Creates the Planet of the final hand played this round, if held in hand at end of round (needs room) | Trance |
| Purple | Creates a Tarot when discarded (needs room) | Medium |

**Editions:**
| Edition | Joker | Playing card |
|---|---|---|
| Foil | +50 Chips | +50 Chips when scored |
| Holographic | +10 Mult | +10 Mult when scored |
| Polychrome | ×1.5 Mult | ×1.5 Mult when scored |
| Negative | **+1 Joker slot** (passive) | **+1 hand size** (rare in vanilla) |
(Negative on a consumable = +1 consumable slot, e.g. via Perkeo.)

Debuffed cards (from bosses) lose rank/suit contribution, enhancement, seal and edition effects for scoring. They still count toward forming the hand type.

Ordering: within a played hand, cards score left to right. Put ×Mult cards (Glass, Polychrome) **rightmost** among scoring cards so the +Mult cards come first.

---

## 7. Deck manipulation strategy for a small LLM

**Why it works:** the bot sees 8 of ~52 cards per draw. Probability of drawing what you need depends on its share of the deck.
- Flush: 13/52 = 25% of the deck is your suit. Converting 9 off-suit cards (3 suit tarots) → 22/52 = 42%. Also destroying 4 off-suit cards (2 Hanged Man) → 22/48 = 46%. With 8 cards in hand, you expect 3.4 vs 2 suited cards. Flushes go from occasional to almost every hand.
- Pairs/trips: each Death or Cryptid on your main rank adds a copy. Each Hanged Man on an off-rank raises every remaining rank's share.

**Rules:**
1. **Pick one target by Ante 2:** a suit (flush) or 1–2 ranks (pairs/trips/full house). Every deck-changing consumable must push toward it.
2. **Flush:** suit tarots (Star/Moon/Sun/World) on off-suit cards. Lovers (Wild) on off-suit. Hanged Man destroys low off-suit cards. Sigil is OK. Death: off-suit card (lower index) → copy of a main-suit card (higher index).
3. **Pairs/Two Pair/Full House:** Death and Cryptid copy your main rank. Strength bumps adjacent ranks into it. Hanged Man destroys singletons. Grim adds Aces.
4. **Thinning beats adding.** Prefer removing junk over adding random cards. Standard packs: take a card only if it matches your suit/rank OR has a strong modifier (Glass, Steel, Red Seal, Polychrome, Mult). Otherwise skip the pack card.
5. Never destroy or convert cards that carry enhancements, seals or editions you want.
6. **Boss safety:** a deck of all one suit dies to that suit's debuff boss. Keep a backup hand type leveled (Pair/Two Pair, via Mercury/Uranus) once your deck is >60% one suit.
7. Hand size is precious (more cards seen = more consistency). Avoid Ouija/Ectoplasm. Paint Brush/Palette are good if offered.

---

## 8. Quick reference: boss checklist the LLM should run each Ante

1. In BLIND_SELECT, note the Boss name, effect and target.
2. Does the boss hit my build? (See §2a.) If yes, buy toward a backup in the next two shops (a generic Joker or a Planet for the backup hand). Under the Ox, spend money first. Before Ante 8, keep a spare cheap Joker for Verdant Leaf.
3. In the boss round, apply the one-line counter from the §2 table to **every** action: card count (Psychic 5, Tooth minimal), first hand type (Mouth), distinct types (Eye), discards before the single hand (Needle).
4. Re-read the hand after each action: Hook, Serpent, Fish and House change it.

---

## Sources (via WebSearch; page fetches were blocked)
- [Steam: boss minimum antes / Wall not at ante 1](https://steamcommunity.com/app/2379780/discussions/0/596263931969820687)
- [TV Tropes – Balatro (only 8 bosses at Ante 1)](https://www.tvtropes.org/pmwiki/pmwiki.php/VideoGame/Balatro)
- [Steam: Ectoplasm stacking hand size](https://steamcommunity.com/app/2379780/discussions/0/4294818244843879497)
- [GameSkinny: how to beat The Arm (permanent level loss)](https://gameskinny.com/tips/how-to-beat-the-arm-boss-blind-in-balatro)
- [Fandom (search snippet): Matador / Wild debuffed by suit bosses](https://balatrogame.fandom.com/wiki/Matador)
- [Insider Gaming: how to beat The Plant](https://insider-gaming.com/how-to-beat-plant-boss-blind-balatro/)
- [Gameranx: every boss blind explained](https://gameranx.com/features/id/495212/article/balatro-every-boss-blind-explained/)
- [dood.gg: Cerulean Bell](https://dood.gg/en/balatro/blinds/cerulean-bell) · [dood.gg: The Fish](https://dood.gg/en/balatro/blinds/the-fish)
- BalatroBot source (local clone): `src/lua/utils/gamestate.lua` (`get_blinds_info`, `extract_card_state`), `src/lua/endpoints/play.lua`, `src/lua/utils/openrpc.json`.

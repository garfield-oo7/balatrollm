# 07 — Community consensus review (Revision 3)

**Question:** is "Flush by default" the right MAIN_HAND for a small model, or
should the bot build around Pairs? The user's own experience: Flush and
Straight are fine in the first antes, but Pair-family hands can be played far
more consistently once you have good jokers.

**Sources.** Reddit (r/balatro) could not be read from this environment. The
network policy rejects `reddit.com` and the search provider excludes it. The
review therefore uses the community discussion that is indexed elsewhere: Steam
forum threads, guide sites and tier-list writers, which mostly repeat r/balatro
consensus. Treat everything below as player opinion unless it is marked
*measured*. To rerun this against Reddit directly, allow `reddit.com` in the
environment's network settings.

## 1. Measured: how often each hand can be made

Monte Carlo over 20,000 deals: unmodified 52-card deck, 8-card hand, up to 5
cards per discard. A blind gives 4 hands and 4 discards, so about one discard
per hand.

| Hand made | 0 discards | 1 discard | 2 discards |
| --- | --- | --- | --- |
| Pair (discarding unpaired cards) | 89% | 99% | 100% |
| Two Pair (discarding unpaired cards) | 44% | **78%** | 92% |
| Three of a Kind | 12% | 35% | 56% |
| Full House | 6% | 28% | 50% |
| Flush (discarding off-suit cards) | 7% | **44%** | 77% |
| Straight (incidental) | 10% | 4% | 2% |

With one discard per hand, Two Pair is made almost twice as often as Flush.
Pair is effectively guaranteed. Chasing a Flush also makes pairs less likely:
Pair falls from 99% to 85%, because good pairs get thrown away. Flush only
becomes reliable with deck fixing (suit tarots) or with Four Fingers or Smeared
Joker.

## 2. What the community says

1. **Flush is the easy early hand but falls off.** It is easy early, but "not
   very consistent with smaller hand size and fewer discards", and suit bosses
   (The Club, The Goad, The Window, The Head) shut it down. "Flushes only
   matter early game … late game it's whatever your deck is strongest with."
2. **Pair, Two Pair and High Card are the consistency picks.** "The best hand
   is the one you can draw repeatedly while improving it faster than the blind
   score grows. Pair, High Card and Two Pair builds … need few cards." One
   player: "a simple two pairs strategy combined with whatever scaling joker
   you can find, a simple multiplier and 3 other jokers … will get you through
   ante 8 more often than not."
3. **Pair family grows into Full House.** "2 Pairs are easy in early game but
   you can easily transition to Full House after enough deck fixing." Pair
   jokers (Jolly, Sly, The Duo) also trigger on Two Pair, Full House and Three
   of a Kind, so they stay useful.
4. **Deck fixing for pairs is done by rank, not suit.** Strength, Death (copy a
   card) and The Hanged Man (remove singletons) concentrate ranks.
5. **The scaling trio.** Aim for one scaling +Chips joker, one scaling +Mult
   joker and one xMult joker. Celestial packs are "the primary way you're
   going to get higher scores" without a special engine.
6. **The economy arc.** Before Ante 3, buy what makes you stronger now. After
   Ante 3, protect the $25 interest cap. Reroll only once the build has a
   direction and the reroll keeps you above the interest tiers.
7. **When to transition.** Around Antes 5–6, sell economy and flat jokers that
   aren't pulling their weight, and replace them with scaling options. Jokers
   tied to a hand type that don't scale are rarely worth it past Ante 4.
8. **Plan for the boss.** Check the next boss right after beating one; there
   are three shops to prepare.
9. **Skipping blinds** is "worse than selecting 95% of the time", apart from a
   few Ante 1 tags. The bot never skips, which is the right default.
10. **Joker order:** +Mult jokers left of xMult jokers. This was already
    automated.

## 3. Changes made to the `mastery` strategy

| Change | Where |
| --- | --- |
| MAIN_HAND defaults to **Two Pair**. Flush only with Four Fingers, Smeared Joker or The Tribe; with 2+ flush jokers and no pair jokers; or when half the deck is one suit. Pair with Half Joker; Three of a Kind with The Trio, or Zany + Wily. | `analysis.main_hand_plan` |
| **Antes 1–2 are open:** Flush and Straight draws of 50%+ are still chased, and a dealt Flush or Straight is still played. From Ante 3, only MAIN_HAND draws are shown or chased. | `plan["open"]`, `plan["draw_kinds"]`, `play_advice` |
| **GOALS checklist per ante**, with PRIORITY set to the first unmet goal. Goals cover joker slots, xMult (1 by Ante 4, 2 by Ante 6), one SCALE joker from Ante 4, MAIN_HAND level of ante−1 from Ante 3, no ECON/CHIPS filler from Ante 5, and $25 interest in Antes 3–6. | `analysis.ante_goals`, STATUS block |
| **Pair deck fixing:** Strength raises a singleton into a rank you hold, Death copies your most common rank, Hanged Man removes singletons, Empress-type tarots enhance paired cards. Suit tarots and Lovers are tagged [AVOID] for pair plans. | `suggest_targets`, `knowledge.consumable_tag` |
| **Death target order fixed.** Death turns the LEFT card into the RIGHT one, so the junk card must have the lower index. The old code sorted the two indices and could copy the junk card onto the good one. | `suggest_targets` |
| Boss impact for pair plans: The Eye, The Mouth, The Psychic, The Arm, The Ox. | `PAIR_BOSS_IMPACT` |
| Re-tiered jokers: Clever Joker early A; Spare Trousers A/A. | `knowledge.JOKERS` |
| Rulebook: the measured odds explain why pairs are the default, plus the run-plan arc, a "never chase draws not listed" rule, and Two Pair and Strength worked examples. | `STRATEGY.md.jinja` |

## Sources

- [Steam: Tips on beating the game on White Stake](https://steamcommunity.com/app/2379780/discussions/0/764059330564756729/)
- [Steam: "19 hours for first win" (flush vs full house discussion)](https://steamcommunity.com/app/2379780/discussions/0/4294818016875108108/)
- [Steam: hand-type build discussion](https://steamcommunity.com/app/2379780/discussions/0/604143633269024644)
- [Balatro Poker Hands Guide (balatrocalculator.blog)](https://balatrocalculator.blog/blog/balatro-poker-hands-guide/)
- [A guide to Gold Stake Balatro (The Mancunion)](https://mancunion.com/2025/09/01/a-guide-to-gold-stake-balatro/)
- [Balatro Advanced Strategy: scaling math and deck thinning (Switchblade Gaming)](https://www.switchbladegaming.com/balatro/advanced-strategy-guide-2/)
- [How should you spend money and rerolls each ante (casualgameguides)](https://casualgameguides.com/walkthroughs/balatro/money-interest-reroll-strategy)
- [Joker combos that actually win runs (Two Average Gamers)](https://www.twoaveragegamers.com/balatro-strategy-guide-the-joker-combos-that-actually-win-runs/)
- [19 essential Balatro tips (PC Gamer)](https://pcgamer.com/balatro-tips)
- [10 beginner tips (Turn Based Lovers)](https://turnbasedlovers.com/guides/10-beginner-tips-to-develop-better-strategies-in-balatro/)
- [Should you skip blinds in Balatro (Twinfinite)](https://twinfinite.net/guides/should-you-skip-blinds-in-balatro/)
- [Steam: skip-blind discussion](https://steamcommunity.com/app/2379780/discussions/0/4756452715167149899)

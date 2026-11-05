"""Static Balatro knowledge rendered next to game items as short annotations.

Small models index long reference prose badly; a tag printed next to the item
("Cavendish [XMULT] tier S") needs no name matching. Sources and corrections:
research/01-06 (see research/06-fable-advisor-review.md for the fixes applied).

Lookups are by display name (the ``label`` BalatroBot sends), normalised to
lowercase alphanumerics, so "Driver's License" == "drivers license".
"""

import re
from typing import Any

################################################################################
# Jokers: name -> (category, early tier, late tier, family, hint)
#   category: XMULT | MULT | CHIPS | SCALE | ECON | UTIL | TRAP | KEEP-DISCARDS
#   tier: S (buy now) > A > B > C > T (trap/skip)
#   family: None (works with any hand) | flush | pair | straight | face
################################################################################

JOKERS: dict[str, tuple[str, str, str, str | None, str]] = {
    "Joker": ("MULT", "A", "C", None, "+4 Mult, cheap filler"),
    "Greedy Joker": ("MULT", "B", "C", "flush", "+3 Mult per Diamond scored"),
    "Lusty Joker": ("MULT", "B", "C", "flush", "+3 Mult per Heart scored"),
    "Wrathful Joker": ("MULT", "B", "C", "flush", "+3 Mult per Spade scored"),
    "Gluttonous Joker": ("MULT", "B", "C", "flush", "+3 Mult per Club scored"),
    "Jolly Joker": ("MULT", "A", "C", "pair", "+8 Mult if hand contains a Pair"),
    "Zany Joker": ("MULT", "B", "C", "pair", "+12 Mult with Three of a Kind"),
    "Mad Joker": ("MULT", "A", "C", "pair", "+10 Mult with Two Pair"),
    "Crazy Joker": ("MULT", "B", "C", "straight", "+12 Mult with a Straight"),
    "Droll Joker": ("MULT", "A", "B", "flush", "+10 Mult with a Flush"),
    "Sly Joker": ("CHIPS", "B", "C", "pair", "+50 Chips with a Pair"),
    "Wily Joker": ("CHIPS", "B", "C", "pair", "+100 Chips with Three of a Kind"),
    "Clever Joker": ("CHIPS", "A", "C", "pair", "+80 Chips with Two Pair"),
    "Devious Joker": ("CHIPS", "B", "C", "straight", "+100 Chips with a Straight"),
    "Crafty Joker": ("CHIPS", "A", "C", "flush", "+80 Chips with a Flush"),
    "Half Joker": (
        "MULT",
        "A",
        "B",
        "pair",
        "+20 Mult only if 3 or fewer cards played; dead on Flush/padded plays",
    ),
    "Joker Stencil": (
        "XMULT",
        "C",
        "B",
        None,
        "x1 per EMPTY joker slot; weak when slots are full",
    ),
    "Four Fingers": (
        "UTIL",
        "S",
        "A",
        "flush",
        "Flush/Straight with 4 cards: big consistency boost",
    ),
    "Mime": (
        "UTIL",
        "C",
        "B",
        None,
        "retriggers held cards; only with Steel cards or Baron",
    ),
    "Credit Card": ("ECON", "C", "C", None, "allows debt; skip"),
    "Ceremonial Dagger": ("TRAP", "T", "B", None, "destroys the joker to its right"),
    "Banner": (
        "KEEP-DISCARDS",
        "B",
        "C",
        None,
        "+30 Chips per discard REMAINING; ~0 if you discard",
    ),
    "Mystic Summit": ("MULT", "B", "C", None, "+15 Mult only when 0 discards left"),
    "Marble Joker": ("UTIL", "C", "C", None, "adds Stone cards; hurts flushes"),
    "Loyalty Card": ("XMULT", "B", "B", None, "x4 only every 6th hand; unreliable"),
    "8 Ball": ("UTIL", "C", "C", None, "Tarot from scored 8s; skip"),
    "Misprint": ("MULT", "A", "C", None, "+0..23 Mult random (avg 11)"),
    "Dusk": ("UTIL", "C", "B", None, "retrigger cards on last hand"),
    "Raised Fist": ("MULT", "B", "C", None, "+2x rank of lowest held card"),
    "Chaos the Clown": ("UTIL", "C", "C", None, "1 free reroll per shop"),
    "Fibonacci": ("MULT", "A", "B", None, "+8 Mult per scored A,2,3,5,8"),
    "Steel Joker": (
        "XMULT",
        "C",
        "B",
        None,
        "x0.2 per Steel card in deck; needs Steel cards",
    ),
    "Scary Face": ("CHIPS", "B", "C", "face", "+30 Chips per scored face card"),
    "Abstract Joker": ("MULT", "A", "C", None, "+3 Mult per joker owned"),
    "Delayed Gratification": (
        "KEEP-DISCARDS",
        "C",
        "C",
        None,
        "$2/discard only if you use NO discards",
    ),
    "Hack": ("UTIL", "C", "B", None, "retrigger scored 2-5"),
    "Pareidolia": ("UTIL", "C", "B", "face", "all cards are face cards"),
    "Gros Michel": (
        "MULT",
        "S",
        "C",
        None,
        "+15 Mult; may die (then Cavendish can appear)",
    ),
    "Even Steven": ("MULT", "B", "C", None, "+4 Mult per scored even card"),
    "Odd Todd": ("CHIPS", "B", "C", None, "+31 Chips per scored odd card"),
    "Scholar": ("MULT", "B", "C", None, "+20 Chips +4 Mult per scored Ace"),
    "Business Card": ("ECON", "C", "C", "face", "$2 sometimes from face cards; skip"),
    "Supernova": (
        "SCALE",
        "A",
        "B",
        None,
        "+Mult = times this hand type was played; loves MAIN_HAND",
    ),
    "Ride the Bus": (
        "SCALE",
        "B",
        "C",
        "pair",
        "+1 Mult per hand with NO scoring face card; resets; bad with Flush",
    ),
    "Space Joker": ("SCALE", "B", "B", None, "1 in 4 to level the played hand"),
    "Egg": ("ECON", "C", "C", None, "+$3 sell value per round; skip"),
    "Burglar": ("TRAP", "T", "C", None, "+3 hands but lose ALL discards"),
    "Blackboard": ("XMULT", "B", "A", None, "x3 if ALL held cards are Spades/Clubs"),
    "Runner": ("SCALE", "B", "C", "straight", "grows with Straights"),
    "Ice Cream": ("CHIPS", "A", "C", None, "+100 Chips, -5 per hand played"),
    "DNA": ("UTIL", "C", "B", None, "copies a 1-card first hand into deck"),
    "Splash": ("UTIL", "C", "C", None, "every played card scores"),
    "Blue Joker": ("CHIPS", "A", "C", None, "+2 Chips per card left in deck"),
    "Sixth Sense": ("UTIL", "C", "C", None, "skip"),
    "Constellation": ("SCALE", "B", "A", None, "x0.1 Mult per Planet used; buy early"),
    "Hiker": ("SCALE", "C", "C", None, "slow chip scaling"),
    "Faceless Joker": (
        "ECON",
        "B",
        "C",
        None,
        "$5 for discarding 3+ face cards at once",
    ),
    "Green Joker": (
        "KEEP-DISCARDS",
        "B",
        "C",
        None,
        "+1 Mult per hand, -1 per discard; small with discard play",
    ),
    "Superposition": ("UTIL", "C", "C", "straight", "skip"),
    "To Do List": ("ECON", "C", "C", None, "skip"),
    "Cavendish": ("XMULT", "S", "S", None, "x3 Mult always"),
    "Card Sharp": (
        "XMULT",
        "A",
        "A",
        None,
        "x3 if this hand type was already played this round",
    ),
    "Red Card": ("SCALE", "C", "C", None, "grows when skipping packs"),
    "Madness": ("TRAP", "T", "B", None, "destroys a random joker each blind"),
    "Square Joker": ("SCALE", "C", "C", None, "grows on exactly-4-card hands"),
    "Seance": ("UTIL", "C", "C", None, "skip"),
    "Riff-raff": ("UTIL", "B", "C", None, "creates 2 Common jokers if slots free"),
    "Vampire": ("SCALE", "C", "B", None, "eats enhancements for xMult"),
    "Shortcut": ("UTIL", "B", "B", "straight", "straights may skip 1 rank"),
    "Hologram": ("SCALE", "B", "A", None, "x0.25 per card added to deck"),
    "Vagabond": ("UTIL", "C", "C", None, "skip"),
    "Baron": ("XMULT", "B", "A", None, "x1.5 per King HELD; needs many Kings"),
    "Cloud 9": ("ECON", "B", "C", None, "$1 per 9 in your deck each round; tier A only with 4+ nines"),
    "Rocket": ("ECON", "A", "C", None, "$1 per round, +$2 more after every boss; sell it last"),
    "Obelisk": ("TRAP", "T", "B", None, "resets when you play your main hand"),
    "Midas Mask": ("ECON", "C", "C", "face", "skip"),
    "Luchador": (
        "UTIL",
        "B",
        "B",
        None,
        "SELL during a boss blind to disable the boss",
    ),
    "Photograph": ("XMULT", "B", "B", "face", "x2 on first scored face card"),
    "Gift Card": ("ECON", "C", "C", None, "skip"),
    "Turtle Bean": ("UTIL", "B", "C", None, "+5 hand size, shrinks each round"),
    "Erosion": ("TRAP", "T", "B", None, "only with a thinned deck"),
    "Reserved Parking": ("ECON", "C", "C", "face", "skip"),
    "Mail-In Rebate": ("ECON", "C", "C", None, "$5 per discarded card of a named rank; skip"),
    "To the Moon": ("ECON", "B", "C", None, "+$1 interest per $5 held; only if you hold $20+"),
    "Hallucination": ("UTIL", "C", "C", None, "skip"),
    "Fortune Teller": ("SCALE", "C", "C", None, "+1 Mult per Tarot used"),
    "Juggler": ("UTIL", "B", "B", None, "+1 hand size"),
    "Drunkard": ("UTIL", "B", "C", None, "+1 discard"),
    "Stone Joker": ("CHIPS", "C", "C", None, "needs Stone cards"),
    "Golden Joker": ("ECON", "A", "C", None, "$4 every round, pays for itself in 2 rounds"),
    "Lucky Cat": ("SCALE", "C", "B", None, "needs Lucky cards"),
    "Baseball Card": ("XMULT", "B", "A", None, "x1.5 per Uncommon joker"),
    "Bull": ("CHIPS", "B", "C", None, "+2 Chips per $1 held"),
    "Diet Cola": ("UTIL", "C", "C", None, "skip"),
    "Trading Card": ("ECON", "C", "C", None, "$3 for a 1-card first discard; conflicts with discards"),
    "Flash Card": ("SCALE", "C", "C", None, "grows on rerolls"),
    "Popcorn": ("MULT", "S", "C", None, "+20 Mult, -4 per round; replace by Ante 3"),
    "Spare Trousers": (
        "SCALE",
        "A",
        "A",
        "pair",
        "+2 Mult per Two Pair played, forever",
    ),
    "Ancient Joker": (
        "XMULT",
        "B",
        "A",
        None,
        "x1.5 per scored card of a rotating suit",
    ),
    "Ramen": ("XMULT", "A", "B", None, "x2, loses x0.01 per card discarded"),
    "Walkie Talkie": ("MULT", "B", "C", None, "+10 Chips +4 Mult per scored 10 or 4"),
    "Seltzer": ("UTIL", "A", "C", None, "retrigger all played cards for 10 hands"),
    "Castle": ("SCALE", "B", "C", None, "grows with discards of a suit"),
    "Smiley Face": ("MULT", "B", "C", "face", "+5 Mult per scored face card"),
    "Campfire": ("SCALE", "C", "B", None, "grows when selling cards"),
    "Golden Ticket": ("ECON", "C", "C", None, "skip"),
    "Mr. Bones": ("TRAP", "T", "C", None, "one-time save; wastes a slot"),
    "Acrobat": ("XMULT", "A", "A", None, "x3 on the LAST hand of the round"),
    "Sock and Buskin": ("UTIL", "B", "A", "face", "retrigger face cards"),
    "Swashbuckler": ("MULT", "B", "C", None, "+Mult = sell value of other jokers"),
    "Troubadour": ("TRAP", "C", "C", None, "-1 hand per round"),
    "Certificate": ("UTIL", "C", "B", None, "adds sealed cards"),
    "Smeared Joker": (
        "UTIL",
        "S",
        "A",
        "flush",
        "Hearts=Diamonds, Spades=Clubs: flushes much easier",
    ),
    "Throwback": ("TRAP", "T", "C", None, "needs blind skips"),
    "Hanging Chad": ("UTIL", "B", "B", None, "retrigger first scored card twice"),
    "Rough Gem": ("ECON", "B", "C", "flush", "$1 per scored Diamond"),
    "Bloodstone": ("XMULT", "B", "A", "flush", "Hearts: 1 in 2 for x1.5 each; random"),
    "Arrowhead": ("CHIPS", "B", "C", "flush", "+50 Chips per scored Spade"),
    "Onyx Agate": ("MULT", "B", "B", "flush", "+7 Mult per scored Club"),
    "Glass Joker": ("SCALE", "C", "B", None, "needs Glass cards breaking"),
    "Showman": ("UTIL", "C", "C", None, "skip"),
    "Flower Pot": (
        "XMULT",
        "C",
        "B",
        None,
        "x3 needs all 4 suits scored; bad with Flush",
    ),
    "Blueprint": (
        "XMULT",
        "A",
        "S",
        None,
        "copies the joker to its RIGHT; place left of your best xMult",
    ),
    "Wee Joker": ("SCALE", "C", "C", None, "grows on scored 2s"),
    "Merry Andy": ("TRAP", "T", "C", None, "-1 hand size"),
    "Oops! All 6s": ("UTIL", "C", "B", None, "doubles probabilities"),
    "The Idol": ("XMULT", "C", "B", None, "x2 for one specific card"),
    "Seeing Double": ("XMULT", "B", "B", None, "x2 if a Club and another suit score"),
    "Matador": ("ECON", "C", "C", None, "skip"),
    "Hit the Road": ("SCALE", "B", "A", None, "x0.5 per Jack discarded this round"),
    "The Duo": ("XMULT", "S", "S", "pair", "x2 if hand contains a Pair"),
    "The Trio": ("XMULT", "A", "A", "pair", "x3 with Three of a Kind"),
    "The Family": ("XMULT", "B", "A", "pair", "x4 with Four of a Kind"),
    "The Order": ("XMULT", "B", "A", "straight", "x3 with a Straight"),
    "The Tribe": ("XMULT", "S", "S", "flush", "x2 with a Flush"),
    "Stuntman": ("TRAP", "T", "C", None, "-2 hand size"),
    "Invisible Joker": ("UTIL", "C", "B", None, "sell after 2 rounds to copy a joker"),
    "Brainstorm": ("XMULT", "A", "S", None, "copies the LEFTMOST joker"),
    "Satellite": ("ECON", "C", "C", None, "skip"),
    "Shoot the Moon": ("MULT", "C", "B", None, "+13 per Queen held"),
    "Driver's License": ("TRAP", "T", "B", None, "needs 16 enhanced cards"),
    "Cartomancer": ("UTIL", "B", "C", None, "free Tarot each blind"),
    "Astronomer": ("UTIL", "B", "B", None, "free Planets in shop"),
    "Burnt Joker": ("SCALE", "B", "B", None, "levels the first discarded hand type"),
    "Bootstraps": ("MULT", "B", "C", None, "+2 Mult per $5 held"),
    "Canio": ("SCALE", "B", "B", "face", "legendary"),
    "Triboulet": ("XMULT", "S", "S", "face", "legendary: x2 per scored King/Queen"),
    "Yorick": ("SCALE", "A", "A", None, "legendary"),
    "Chicot": ("UTIL", "S", "S", None, "legendary: disables all boss effects"),
    "Perkeo": ("UTIL", "A", "A", None, "legendary"),
}

# Hand family for MAIN_HAND matching.
HAND_FAMILY = {
    "Flush": "flush",
    "Straight": "straight",
    "Two Pair": "pair",
    "Pair": "pair",
    "Three of a Kind": "pair",
    "Full House": "pair",
    "Four of a Kind": "pair",
}

PLANET_HAND = {
    "Pluto": "High Card",
    "Mercury": "Pair",
    "Uranus": "Two Pair",
    "Venus": "Three of a Kind",
    "Saturn": "Straight",
    "Jupiter": "Flush",
    "Earth": "Full House",
    "Mars": "Four of a Kind",
    "Neptune": "Straight Flush",
    "Planet X": "Five of a Kind",
    "Ceres": "Flush House",
    "Eris": "Flush Five",
}

# Tarot / Spectral: name -> (verdict, hint)
#   verdict: GOOD | SITUATIONAL | AVOID
CONSUMABLES: dict[str, tuple[str, str]] = {
    "The Fool": ("SITUATIONAL", "copies the last Tarot/Planet used"),
    "The Magician": ("SITUATIONAL", "Lucky on 2 cards you play"),
    "The High Priestess": ("GOOD", "2 random Planets (needs empty slots)"),
    "The Empress": ("GOOD", "Mult (+4) on 2 cards you play"),
    "The Emperor": ("GOOD", "2 random Tarots (needs empty slots)"),
    "The Hierophant": ("GOOD", "Bonus (+30 chips) on 2 cards you play"),
    "The Lovers": ("SITUATIONAL", "Wild on 1 off-suit card (Flush)"),
    "The Chariot": ("SITUATIONAL", "Steel on 1 card you HOLD (not play)"),
    "Justice": ("GOOD", "Glass (x2) on 1 card you play"),
    "The Hermit": ("GOOD", "doubles money (max +$20); use at $10+"),
    "The Wheel of Fortune": ("SITUATIONAL", "1 in 4 edition on a joker; free gamble"),
    "Strength": ("SITUATIONAL", "+1 rank on up to 2 cards (makes pairs)"),
    "The Hanged Man": ("SITUATIONAL", "destroy up to 2 junk cards (thins the deck)"),
    "Death": ("GOOD", "2 cards: LEFT card becomes copy of RIGHT card"),
    "Temperance": ("GOOD", "money = jokers' sell value (max $50)"),
    "The Devil": ("SITUATIONAL", "Gold on 1 card you HOLD"),
    "The Tower": ("AVOID", "Stone card; breaks flushes/pairs"),
    "The Star": ("GOOD", "3 cards -> Diamonds (use if MAIN_SUIT is Diamonds)"),
    "The Moon": ("GOOD", "3 cards -> Clubs (use if MAIN_SUIT is Clubs)"),
    "The Sun": ("GOOD", "3 cards -> Hearts (use if MAIN_SUIT is Hearts)"),
    "The World": ("GOOD", "3 cards -> Spades (use if MAIN_SUIT is Spades)"),
    "Judgement": ("GOOD", "free random joker (needs an empty joker slot)"),
    "Familiar": ("GOOD", "adds 3 enhanced face cards"),
    "Grim": ("GOOD", "adds 2 enhanced Aces"),
    "Incantation": ("GOOD", "adds 4 enhanced number cards"),
    "Talisman": ("GOOD", "Gold Seal on a card you play"),
    "Aura": ("GOOD", "edition on your best played card"),
    "Wraith": ("AVOID", "rare joker but money -> $0; only if broke"),
    "Sigil": ("SITUATIONAL", "hand -> one random suit"),
    "Ouija": ("AVOID", "-1 hand size"),
    "Ectoplasm": ("AVOID", "-1 hand size"),
    "Immolate": ("SITUATIONAL", "destroy 5 cards in hand, +$20"),
    "Ankh": ("AVOID", "destroys all other jokers"),
    "Deja Vu": ("GOOD", "Red Seal (retrigger) on a card you play"),
    "Hex": ("AVOID", "destroys all other jokers"),
    "Trance": ("GOOD", "Blue Seal on a card: a free Planet every round"),
    "Medium": ("GOOD", "Purple Seal on a junk card you discard"),
    "Cryptid": ("GOOD", "2 copies of your best card"),
    "The Soul": ("GOOD", "LEGENDARY joker (needs an empty joker slot)"),
    "Black Hole": ("GOOD", "+1 level to every hand; use now"),
}

# Vouchers: name -> (verdict, hint). BUY = buy even below FLOOR; GOOD = above FLOOR; NEVER.
VOUCHERS: dict[str, tuple[str, str]] = {
    "Grabber": ("BUY", "+1 hand per round"),
    "Nacho Tong": ("GOOD", "+1 hand per round"),
    "Paint Brush": ("BUY", "+1 hand size"),
    "Palette": ("GOOD", "+1 hand size"),
    "Antimatter": ("BUY", "+1 joker slot"),
    "Blank": ("GOOD", "does nothing but unlocks Antimatter; only with $35+"),
    "Clearance Sale": ("GOOD", "25% off (Antes 1-4)"),
    "Liquidation": ("GOOD", "50% off"),
    "Overstock": ("GOOD", "3 shop slots, more jokers"),
    "Overstock Plus": ("GOOD", "4 shop slots"),
    "Telescope": ("GOOD", "Celestial packs give MAIN_HAND planet"),
    "Observatory": (
        "GOOD",
        "held planets give x1.5 to their hand: HOLD MAIN_HAND planets",
    ),
    "Wasteful": ("GOOD", "+1 discard"),
    "Recyclomancy": ("GOOD", "+1 discard"),
    "Crystal Ball": ("GOOD", "+1 consumable slot"),
    "Reroll Surplus": ("GOOD", "rerolls $2 cheaper"),
    "Reroll Glut": ("GOOD", "rerolls $2 cheaper"),
    "Seed Money": ("NEVER", "interest cap $10; rarely reached"),
    "Money Tree": ("NEVER", "interest cap $20"),
    "Hieroglyph": ("NEVER", "-1 hand per round"),
    "Petroglyph": ("NEVER", "-1 discard per round"),
    "Director's Cut": ("NEVER", "boss reroll is not available to you"),
    "Retcon": ("NEVER", "boss reroll is not available to you"),
    "Tarot Merchant": ("NEVER", "fewer jokers in shop"),
    "Tarot Tycoon": ("NEVER", "fewer jokers in shop"),
    "Planet Merchant": ("NEVER", "fewer jokers in shop"),
    "Planet Tycoon": ("NEVER", "fewer jokers in shop"),
    "Magic Trick": ("NEVER", "playing cards in shop"),
    "Illusion": ("NEVER", "playing cards in shop"),
    "Omen Globe": ("NEVER", "no scoring value"),
    "Hone": ("NEVER", "no scoring value"),
    "Glow Up": ("NEVER", "no scoring value"),
}

# Boss blinds: name -> one-line counter.
BOSSES: dict[str, str] = {
    "The Hook": "2 random held cards are discarded after each hand: play your best hand now, do not save cards",
    "The Ox": "playing the named (most played) hand sets money to $0: play another hand type if it still wins",
    "The House": "first hand is face down: discard face-down cards to see new ones",
    "The Wall": "target is 4x: use every hand at maximum score",
    "The Wheel": "some cards face down: they still score normally",
    "The Arm": "played hand loses 1 level permanently: win in as few hands as possible",
    "The Club": "Clubs give 0 chips and trigger nothing: score with other suits",
    "The Fish": "cards drawn after a play are face down: they still score",
    "The Psychic": "play EXACTLY 5 cards every hand (add filler cards)",
    "The Goad": "Spades give 0 chips and trigger nothing: score with other suits",
    "The Water": "0 discards: play 5-card hands so filler cards cycle",
    "The Window": "Diamonds give 0 chips and trigger nothing: score with other suits",
    "The Manacle": "hand size -1: take the best listed play",
    "The Eye": "each hand type only once this round: play your strongest type when it scores most",
    "The Mouth": "only ONE hand type this round: your first play locks it, make it MAIN_HAND",
    "The Plant": "face cards (J,Q,K) give 0: score with A and 2-10",
    "The Serpent": "always draw 3 after play/discard: small discards grow your hand",
    "The Pillar": "cards already played this ante give 0",
    "The Needle": "only ONE hand: use all discards first, then play the best listed play",
    "The Head": "Hearts give 0 chips and trigger nothing: score with other suits",
    "The Tooth": "lose $1 per card played: play only the scoring cards, no filler",
    "The Flint": "hand base chips/mult halved: jokers matter more",
    "The Mark": "face cards drawn face down: they still score",
    "Amber Acorn": "jokers flipped and shuffled: nothing to do, play normally",
    "Verdant Leaf": "all cards give 0 until you SELL 1 joker: sell your weakest joker first",
    "Violet Vessel": "target is 6x: every hand must be maximum score",
    "Crimson Heart": "a random joker is disabled each hand: play normally",
    "Cerulean Bell": "one card is always forced into your selection: build around it",
}
# Jokers that only fire when the played hand CONTAINS a specific hand type.
REQUIRED_HAND = {
    "Jolly Joker": "Pair",
    "Sly Joker": "Pair",
    "The Duo": "Pair",
    "Zany Joker": "Three of a Kind",
    "Wily Joker": "Three of a Kind",
    "The Trio": "Three of a Kind",
    "Mad Joker": "Two Pair",
    "Clever Joker": "Two Pair",
    "Spare Trousers": "Two Pair",
    "The Family": "Four of a Kind",
    "Droll Joker": "Flush",
    "Crafty Joker": "Flush",
    "The Tribe": "Flush",
    "Crazy Joker": "Straight",
    "Devious Joker": "Straight",
    "The Order": "Straight",
    "Runner": "Straight",
}
# Hand types each MAIN_HAND contains (Four of a Kind does NOT count as Two Pair).
MAIN_CONTAINS = {
    "High Card": {"High Card"},
    "Pair": {"Pair"},
    "Two Pair": {"Pair", "Two Pair"},
    "Three of a Kind": {"Pair", "Three of a Kind"},
    "Full House": {"Pair", "Two Pair", "Three of a Kind", "Full House"},
    "Four of a Kind": {"Pair", "Three of a Kind", "Four of a Kind"},
    "Flush": {"Flush"},
    "Straight": {"Straight"},
}
SMALL_PLAY_MAINS = {"High Card", "Pair", "Three of a Kind"}  # Half Joker: <= 3 cards

FLUSH_ONLY_TAROTS = {"The Star", "The Moon", "The Sun", "The World", "The Lovers"}
PAIR_FIXER_TAROTS = {"Strength", "The Hanged Man", "Death", "Cryptid"}
SUIT_BOSSES = {"The Club": "C", "The Goad": "S", "The Window": "D", "The Head": "H"}


def _norm_name(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


_JOKERS_N = {_norm_name(k): (k, v) for k, v in JOKERS.items()}
_CONS_N = {_norm_name(k): (k, v) for k, v in CONSUMABLES.items()}
_VOUCH_N = {_norm_name(k): (k, v) for k, v in VOUCHERS.items()}
_PLANET_N = {_norm_name(k): v for k, v in PLANET_HAND.items()}
_BOSS_N = {_norm_name(k): (k, v) for k, v in BOSSES.items()}
_ALIASES = {"caino": "canio", "seance": "seance", "riffraff": "riffraff"}


def joker_info(name: Any) -> dict[str, Any] | None:
    """Static notes for a joker by display name, or None if unknown."""
    n = _norm_name(name)
    n = _ALIASES.get(n, n)
    hit = _JOKERS_N.get(n)
    if not hit:
        return None
    label, (cat, early, late, family, hint) = hit
    return {
        "name": label,
        "category": cat,
        "early": early,
        "late": late,
        "family": family,
        "hint": hint,
    }


def joker_fit(label: Any, main_hand: str | None) -> str | None:
    """"MAIN" / "OFF-PLAN" for jokers tied to a hand, None for generic ones."""
    info = joker_info(label)
    if not info or not main_hand:
        return None
    name = info["name"]
    if name == "Half Joker":
        return "MAIN" if main_hand in SMALL_PLAY_MAINS else "OFF-PLAN"
    required = REQUIRED_HAND.get(name)
    if required:
        return "MAIN" if required in MAIN_CONTAINS.get(main_hand, set()) else "OFF-PLAN"
    family, main_family = info["family"], HAND_FAMILY.get(main_hand)
    if family in ("pair", "flush", "straight") and main_family:
        return "MAIN" if family == main_family else "OFF-PLAN"
    return None


def joker_tag(card: dict[str, Any], main_hand: str | None, ante: int) -> str:
    """Render ``[TAGS] tier X: hint`` for a joker card dict."""
    info = joker_info(card.get("label"))
    if not info:
        return ""
    tags = [info["category"]]
    family = info["family"]
    fit = joker_fit(card.get("label"), main_hand)
    if fit:
        tags.append(fit)
    elif family == "face":
        tags.append("FACE")
    tier = info["early"] if ante <= 3 else info["late"]
    if "OFF-PLAN" in tags and tier in ("S", "A"):
        tier = "B"
    return f"[{'] ['.join(tags)}] tier {tier}: {info['hint']}"


def consumable_tag(
    card: dict[str, Any], main_hand: str | None, blue_seals: int | None = None
) -> str:
    """Render a short verdict for a Tarot / Planet / Spectral card dict."""
    label = card.get("label")
    n = _norm_name(label)
    if n == "trance" and blue_seals:
        return "[SITUATIONAL] you already own a Blue Seal card: skip"
    if n in _PLANET_N:
        hand = _PLANET_N[n]
        if main_hand and hand == main_hand:
            return f"[MAIN] levels {hand} (your MAIN_HAND): use now"
        return f"levels {hand} (not MAIN_HAND)"
    hit = _CONS_N.get(n)
    if not hit:
        return ""
    verdict, hint = hit[1]
    if HAND_FAMILY.get(main_hand or "") == "pair":
        if hit[0] in FLUSH_ONLY_TAROTS:
            return "[AVOID] changes suits; useless for a Pair-family MAIN_HAND"
        if hit[0] in PAIR_FIXER_TAROTS:
            verdict = "GOOD"
    return f"[{verdict}] {hint}"


def voucher_tag(card: dict[str, Any]) -> str:
    """Render a short verdict for a voucher card dict."""
    hit = _VOUCH_N.get(_norm_name(card.get("label")))
    if not hit:
        return ""
    verdict, hint = hit[1]
    return f"[{verdict}] {hint}"


def boss_counter(name: Any) -> str:
    """One-line counter-play instruction for a boss blind."""
    hit = _BOSS_N.get(_norm_name(name))
    return hit[1] if hit else ""


def planet_hand(name: Any) -> str | None:
    """Poker hand levelled by a planet card name."""
    return _PLANET_N.get(_norm_name(name))

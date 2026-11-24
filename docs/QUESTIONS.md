# Open questions on the rules and the Meta

My current assumption is in *italics*. Engine questions (A) are already config
flags, so they block nothing. B–F block the convention layer.

## A. Variants and rules (engine, already flags)

A1. Short rainbow: does it have its own "rainbow" hint, and is it touched by every
color hint (like variant 2)? *Yes to both.*

A2. Can you give a hint that touches no cards ("you have no blue")? *No.*

A3. Can you discard when all 8 hint tokens are available? *No.*

A4. Three strikes: does the score become 0, or do you keep the stacks? *0.*

## B. Baseline hint meaning (the Meta lists only the special conventions)

B1. Plain hints: what does a hint on a playable card mean? *Play it. If several touched
cards are playable, play them from newest to oldest.*

B2. When a hint touches several cards and only some are playable, which card is
"the hinted card" for the skip-level/shotgun test? Is it the newest touched card, a
newly touched card, or each touched card on its own?

B3. Saves: apart from the 5 safety hint, are there saves? For example, is a hint on
the oldest (left-most) card that is a critical non-5 a save, or always a skip-level?
How does a player tell a save from a skip-level?

B4. When hints are available and nothing is playable, must you hint, or may you
discard your oldest card? Is the discard slot the oldest card overall or the oldest
*untouched* card? *The oldest untouched card.*

## C. Skip-level

C1. "Play on the information you already have first": does this mean (a) if you hold
any card you already know is playable, play it, even if it isn't the unlock; or (b)
if your existing info shows you hold the unlocking card, play that?

C2. Who acts: if the unlock is in player X's newest slot, is X meant to play it blindly
on X's next turn? Does the hint receiver just wait, holding the hinted card until it
becomes playable?

C3. Multi-level (hinted 3 with the stack at 1): the 2 must be in someone's newest
slot or in a slot with known info. Do the unlocks have to be played in turn order,
or can they be played in any order as long as each is playable when played?

C4. "If two players have the unlock in their newest slot and the first doesn't play
it": does "first" mean the first in turn order after the hinter?

C5. What if a player who is expected to play an unlock gives a hint or discards
instead? *The next candidate takes over, as in your two-player rule.*

## D. Shotgun

D1. How does a player know the shotgun is about *them* and not a skip-level to the
receiver (self skip-level)? *If no visible newest-or-known slot unlocks the card, the
next player in turn order assumes they hold several playable cards and starts from
their newest.*

D2. Over several turns, does the shotgunned player play newest, then the next newest,
and so on, one card per turn until the unlock is played? Can teammates hint in between?

D3. When the shotgunned player plays a card from their newest slot, slots shift. Is
"down the line" counted on the hand as it was when the hint was given? *Yes, the
cards are tracked as physical cards.*

## E. Safety swap

E1. Who reverses: every player, or everyone except the hinted player, or everyone
except the hinter? *Every player except the hinter, who already sees all other hands.*

E2. "Cards they have no information on": is a card that has only negative info (a
hint that didn't touch it) uninformed? *Yes. Only cards touched by a hint keep their
place.*

E3. Mechanics: do the touched cards keep their slots while the untouched cards reverse
among the remaining slots? Example: hand `a [b] c d e` with b touched becomes
`e [b] d c a`?

E4. Is any "5" rank hint a safety hint, including one on a playable 5? Is a color
hint on a 5 never a safety hint?

E5. Do people physically reorder their cards? Does a second 5 hint reverse again?

## F. Inferring a playable 5

F1. Trigger: the color-hinted card is already dead (that card was already played) and
the receiver discards it on their next turn. Must it be the receiver's very next
action? Does it count if the hinted card was dead for another reason (an earlier
rank is gone)?

F2. "The hinter and receiver see all remaining ranks of that color on the board": does
this mean those players see the remaining cards of that color in other players' hands,
so whoever cannot see the 5 (or the next needed card) assumes it is in their own newest
slot?

F3. Who is expected to play: everyone other than the hinter and receiver, in turn
order, first one who can't see the card? Can the hinter or receiver themselves hold it?

F4. Stack at 2 or lower: does the chain continue (you see 4 and 5 in newest slots, so
you hold the 3)?

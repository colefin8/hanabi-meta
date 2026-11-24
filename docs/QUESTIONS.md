# Rules and Meta: decisions and open questions

Decisions are what the convention modules implement. Each one should get at least
one test case in `tests/cases/` built from a concrete table situation.

## Decided

### D1. Which card a hint is about
A hint is "about" every touched card that is either playable now or will become
playable through a skip-level (or shotgun). There is no single focus card.

> Example: the yellow stack is at 1. Player A gets a yellow hint on an unplayable Y3.
> Player B's newest card is Y2. The hint tells B that the Y2 is playable. B plays it,
> which unlocks A's Y3.

### D2. Skip-level: who plays the unlock
- The player expected to play the unlock is whoever looks around the table, sees that
  nobody else visibly holds it, and so infers they hold it. They play it from their
  "playable slot": the newest slot for a skip-level, or the line for a shotgun (D3).
- "Play on the information you already have first" covers both readings. Play a card
  you already know is playable, and play a card your existing info shows is the unlock.
- If a player already had info showing that a card of theirs unlocks another player's
  hinted card, they still play it. That is NOT a skip-level, because the info was
  already there. The convention layer must not draw skip-level inferences from it.

### D3. Shotgun
- You recognize it the same way as a skip-level: the hint doesn't make sense given what
  you can see, so you infer a skip-level or a shotgun aimed at you.
- A shotgun is a multi-card skip-level. The player plays cards from newest to oldest
  until they play the card that makes the triggering hint make sense.
- *Assumption: one card per turn, and cards are tracked as physical cards, so "the
  line" survives slots shifting as cards are played.*

### D4. Safety swap (on a "5" rank hint)
- Everyone except the hint giver reverses their hand, including the hinted player.
- Cards with positive info (touched by any hint) stay in place. Cards with only
  negative info count as "no information" and are reversed. Their negative info goes
  with them.
- *Assumed mechanics (please confirm, see O1):* the untouched cards reverse among the
  slots they occupy, e.g. `a [b] c d e` becomes `e [b] d c a`.

## Still open

O1. Your answer said "everyone swaps all cards with positive information" and also
"hinted cards stay in place." I've read it as swapping all cards *without* positive
information. Is that right?

O2. Engine rules. The linked PDF is scanned images I can't read here, so these use the
standard rules and are config flags:
- a hint must touch at least one card;
- no discarding with all 8 hint tokens available;
- three strikes scores 0;
- playing a 5 returns a token;
- after the last draw, everyone, including the drawer, gets one more turn.

Tell me if your table plays any of these differently.

O3. Short rainbow: does it have its own "rainbow" hint, and is it touched by every
color hint? *Assumed yes to both.*

O4. Safety swap: is every "5" rank hint a safety hint, even on a playable 5? Is a color
hint on a 5 never one? Does a second 5 hint reverse hands again?

O5. Saves: apart from the 5 safety hint, are any hints saves (e.g. a 2, or the last copy
of a card on someone's oldest slot)? Or is every hint on an unplayable card a skip-level
or shotgun?

O6. Discard slot: when you discard with no info, is it the oldest card overall or the
oldest card with no hint on it?

O7. Inferring a playable 5, as a worked example. Five players A-E. The red stack is at
4 (R1-R4 played). A gives B a red hint on a card that is clearly dead, say a red 2. On
B's next turn, B discards it. The convention says: assume A and B see all remaining red
ranks on the board, so if the stack is at 4, assume your newest card is R5 and play it.
- (a) Who plays the R5: C, D and E, in turn order? Is it the first of them who doesn't
  see R5 in anyone else's hand? Could A or B themselves hold it?
- (b) Does B have to discard it on their very next turn, or just at some point?
- (c) With the stack at 3: if C sees D's newest card is R5, C infers C holds R4 in
  their newest slot and plays it. Does that chain go further? For example, stack at 2,
  C sees R4 and R5 in newest slots, so C holds R3?

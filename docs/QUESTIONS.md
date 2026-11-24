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

### D3b. Skip-level reading rules
Confirmed: collateral, save beats self-skip, several unexplained cards. The rest are
my choices, to confirm with real examples. Each is one small, commented rule in
`conventions/skip_level.py`.
- **Collateral:** if a hint already has a meaning (some touched card is playable or
  visibly unlocked), other touched cards are collateral, and nobody infers anything
  about their own hand from them.
- **Save beats self-skip:** if a touched card is critical and no unlock is visible, it
  is read as a save, not as "I hold the unlock".
- **Several unexplained touched cards:** read the hint as about the newest of them.
- **Hint to me:** my hinted card is narrowed to "playable now", "unlocked by a card I
  can see in a teammate's playable slot", or a critical non-5 (a save). If none of
  those is possible, it's a self skip-level and my newest untouched card is narrowed
  to the first missing unlock. 5s are left out because they are saved with rank hints.
- **Who plays, in what order:** visible holders, in turn order after the hinter. I'm
  always the last fallback, because a holder who declines can see my hand. A holder
  only "declines" if the card was playable on their turn and they did something other
  than play it, or than play a card they already knew was playable.
- **Playable slot:** the newest card, a card the player's own info already identifies,
  or a card below a run of cards that would each play in turn (the shotgun line).
- **The hinter's own hand never holds the intended unlock,** since the hinter can't
  see it.

### D3c. Don't give misleading hints
Any hint on an unplayable card carries meaning under the Meta: teammates will infer
an unlock in their own hands. A hint that doesn't mean that (e.g. "green" on a G4
with nothing played) must not be given. **Advisor requirement:** before recommending
a hint, run each teammate's interpretation of it and reject hints that would lead
anyone to a wrong inference.

### D4. Safety swap (on a "5" rank hint)
- Everyone except the hint giver reverses their hand, including the hinted player.
- Cards with positive info (touched by any hint) stay in place. Cards with only
  negative info count as "no information" and are reversed. Their negative info goes
  with them.
- Mechanics (confirmed): only cards without hints reverse, among the slots they
  occupy. Hinted cards stay where they are: `a [b] c d e` becomes `e [b] d c a`.

- Every "5" rank hint is a safety hint and triggers a swap, even on a playable 5 and
  even when it touches several 5s. Each new 5 hint triggers another swap.

### D5. Saves (no swap)
- Short rainbow (one copy each of rainbow 2, 3, 4): a hint on any of those can be a
  save. It does not cause a swap.
- Last copy of a card (every other copy discarded or misplayed): a save hint is
  allowed. The hinter must make sure it can't be read as "playable" or as a skip-level.
- *Implication for the advisor: a hint on a critical, non-playable card is read as a
  save when no visible unlock exists and the card is critical. Skip-level wins when an
  unlock is visible.* (to confirm with real examples)

### D6. Discarding
- Discard your oldest card unless you can infer it is unsafe.
- Protective discard (a signal to the NEXT player, P):
  - The player directly before P in turn order could give a hint but discards instead.
    Giving the hint would have left P with no hint token, and P would then have had to
    discard their next-oldest card by convention. So the discard tells P that card is
    unsafe too: P's oldest and second-oldest cards are both unsafe to discard.
  - If the same thing happens again on the next round, P assumes their third-oldest
    card is also unsafe, and so on.
  - It only counts for a discard (never a play) by the player directly before P.
  - *Open detail: does "could give a hint" mean any hint token was available, or that a
    useful hint was visible? I'll assume a token was available and refine it with
    examples.*

### D7. Inferring a playable 5 (dead color hint, then a discard)
- Trigger: a player is color-hinted on a card that is clearly dead, and discards it,
  usually on their very next turn. The discard is the signal. It says the discarder is
  sure the card is safe: ranks 1-4 of that color are played, and they can see the 5.
- Who plays: the player who most recently drew a new card and does not see that 5
  anywhere else. They play their newest card.
- Chain: stack at 3, you see another player's newest card is that 5, so you hold the 4
  in your newest slot. Deeper chains (stack at 2, you see the 4 and 5) follow the same
  logic. They haven't come up in practice, but this is the assumption.

### D8. Trash hints ("safe to discard")
- Sometimes the best hint tells a player which cards they can safely discard. Only
  give it when the intent is unmistakable.
- Examples:
  - white when white is complete;
  - 1s when every stack has its 1;
  - yellow with yellow at 4 when the receiver can see Y5 in another hand.
- Rule in code (`conventions/trash_hint.py`): a hint is a trash hint when, from the
  receiver's view, every card it could touch is already trash.
- Every "5" rank hint is still a safety hint first.
- In the rainbow variants, a color hint also touches rainbow cards, so "white is
  done" is only a trash hint if the rainbow cards it could touch are dead too.
- The yellow example is also the playable-5 trigger (D7). If I can't see the Y5, I
  can't be sure the receiver sees it, so I read the hint as DEAD (not obvious trash).
  The playable-5 inference then waits for the receiver's discard.

### D9. Look ahead before spending hints
- Especially when hints are low, check what the next players would do after your
  move. If you use the last hint and the next player would have to play or discard,
  make sure what they'll do is safe. Then check the following two players the same
  way.
- Expected teammate policy: play if they can, else hint if a token exists, else
  discard.
- In code (`advisor.lookahead`): this simulates the next 3 players with that policy
  and penalises actions that leave someone discarding a critical card or playing a
  card that misses.
- Approximation: stacks aren't advanced during the lookahead.

## Still open

O2. Engine rules. The linked PDF is scanned images I can't read here, so these use the
standard rules and are config flags:
- a hint must touch at least one card;
- no discarding with all 8 hint tokens available;
- three strikes scores 0;
- playing a 5 returns a token;
- after the last draw, everyone, including the drawer, gets one more turn.

Tell me if your table plays any of these differently.

O3. Resolved. "Short rainbow" is variant 4 from the brief: a 6th suit with only six
cards (two 1s, one each of 2-5). It matches "rainbow with only one 2, 3, and 4" from D5.
*Assumed: it has its own rainbow hint and is touched by every color hint.* Tell me if
it should be hinted only through colors, like variant 3.

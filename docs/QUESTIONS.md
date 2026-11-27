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
  - *Superseded by D15 (who is protected, and when) and D16 (only game-ending cards).*

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

### D10. How the later conventions are modelled (confirm with real examples)
- **Safety swap:** the tool reverses hands itself right after any 5 hint. In the CLI,
  `show` displays teammates' hands in their new order, and later `play`/`discard` slot
  numbers refer to that new order. Expectations follow the card, not the slot. So if
  a skip-level expected p3's newest card and a 5 hint then reverses p3's hand, the
  tool still expects that same card, which is now somewhere else.
- **Playable 5:** a color hint read as trash/dead, then the receiver discards that
  card (at any later point, not only on their next turn). Remaining ranks are
  expected in order. Visible holders are ordered by who drew most recently. I'm the
  fallback only if I can't see the card anywhere.
- **Protective discard:** triggers only when exactly 1 hint token was available
  before the discard, and only for the player directly after the discarder. It marks
  that player's chop (oldest card with no hint and no flag) as unsafe. The advisor
  skips flagged cards when choosing a discard. The lookahead does the same for
  teammates.

### D11. Adjustments found by self-play (please sanity-check)
- **No re-hint that carries a meaning:** hinting an already-hinted card again (e.g.
  "green" on a saved G5) is rejected unless it reads as a plain play or trash hint.
  Otherwise teammates read a skip-level into it.
- **Check the receiver's reading:** before suggesting a hint, the advisor also reads
  it from the receiver's side. If the receiver would conclude "self skip-level" and
  blind-play a newest card that isn't playable, the hint is rejected.
- **Hint to me (superseded by D18):** my hinted card is only narrowed to "not trash". It can still be
  waiting on a self skip-level. A hinted card that might be waiting on a teammate's
  unlock is never blind-played.
- **Playable 5:** needs the stack at 2+. With more than one card missing from my
  view, I don't infer which I hold.
- **Last strike:** only play what the hints prove. Convention-only inferences wait.

### D12. Second pass on interpretation edge cases (2026-11-26)
Decided at the table:
- **An urgent save delays a play; it isn't a decline.** If the player expected to
  play an unlock spends their turn on a save (a hint read as a save, or a 5 hint),
  the expectation stays with them. The next turn they don't play it counts as
  declining as usual.
- **An unlock can sit in an already-hinted newest card.** The holder is still
  expected to play it, but that's inefficient, so the advisor avoids it when a
  cleaner hint exists (small score penalty).
- **Endgame: prefer a direct hint.** Once the deck is empty, the advisor rejects a
  skip-level if the unlock holder has no turn left or acts after the target's last
  turn. It also rejects any hint to a player with no turn left.

Fixed:
- When a skip-level falls back to me, "my newest card" means my newest card *when
  the hint was given*, not a card I drew afterwards.
- The playable-5 inference (D7) only fires when the color can still be completed.
  A color that's dead because a lower card is discarded says nothing about where
  the rest of it is.
- A self shotgun keeps going: after my newest card plays as the unlock, my hinted
  card is narrowed to that suit. If the hint still doesn't make sense, my next card
  down the line is the next unlock.
- The advisor rejects a play or skip-level hint on a second copy of a card already
  hinted or expected elsewhere.

### D13. Multi-card hints play newest -> oldest (2026-11-26)
- Unless you have other identifying info, the newest touched card is the one to
  play first; then the next newest, and so on.
- Info can override the order. Example: "2" on three cards with only yellow at 1.
  At most one is playable, so play the newest (as Y2); the others aren't playable.
- In code: on a multi-card hint to me, the newest touched card that could be
  playable is narrowed to "playable now, or unlocked by a card a teammate visibly
  holds". Older touched cards aren't narrowed.
- *Superseded by D19:* the next touched card is the next play, not a probability call.
- (Old) Not Meta, just odds: after the first card plays, holding the next one until it's
  more certain is often right early in the game (fewer cards played or discarded,
  so the hinted cards are less likely to line up). The advisor plays it only when
  its probability clears the risky-play threshold, which reflects this.
- The advisor rejects a multi-card hint if the receiver's newest touched card isn't
  actually the one that plays first.

### D14. Hinting a second copy on purpose (2026-11-26)
- Only when p1 holds a copy (e.g. Y2) they're relatively sure of, has other
  playable cards so they won't play it right away, and p2's hint has its own
  purpose: newest -> oldest, p2's touched cards play in order starting with the
  copy (e.g. Y2 then Y3).
- p1 then discards their Y2. That tells p2 that their newest hinted card that could
  be a Y2 is the other copy. Without it, p2 would read their yellows as Y3/Y4
  waiting on p1's Y2.
- "Relatively certain" matters: if p1 discards a card they only guessed was Y2
  (e.g. it was hinted "2" and was really B2), p2 is misled into holding both
  yellows. In code, the signal only counts if the discarder knew the card's
  identity from their own info.
- If p1 plays their Y2 instead, p2 plays as they think they should and misplays.
  That's a hinting error by the hinter or p1, and the advisor avoids it: when I
  hold a known card that a teammate also holds hinted, I discard mine rather than
  play it.

### D15. Protective discard looks ahead (2026-11-26)
- Consider one when, if you used the last token, a player ahead would have a
  discard as their best move and it would throw away a needed last copy.
- That player can be 1, 2 or 3 seats ahead of you, depending on tokens and hinted
  playables. Example: the next player has a playable, but the one after has a
  last copy on their oldest slot.
- With more than 1 token, never: a protective hint (a save) is better, or a play
  hint, leaving the call to someone later with fewer options.
- It counts at 0 tokens too: that's the main case. The discarder had a play they
  knew about and discarded instead, getting a token back for whoever would be
  forced. 1 token is the edge case (they could have hinted), but it's read the
  same way.
- In code (`conventions/protective_discard.py`): a discard is read as protective at
  0 tokens if the discarder had a known or expected play, or at exactly 1 token.
  Walk forward from the discarder (up to 3 seats) as if they had played or hinted
  instead (0 tokens left): players with a known or expected play play
  it (a 5 returns the token), players with a token hint. The first who'd be forced
  to discard has their chop flagged unsafe. If nobody would be forced, the discard
  is ordinary.
- The advisor reads my own discard the same way. At 0 tokens it favours the
  protective discard over my known play when the protected card is a last copy,
  since my play only waits a round. Its lookahead shows
  that spending the last token would force the critical discard.
- Confirmed: at 0 tokens with no known play, the discard is forced, so it isn't
  read as protective.
- Confirmed: the protective discard beats a save hint, since it gains a token
  instead of spending one. A save hint is the backup for when the discard signal
  would still lose a needed card. In code: the advisor gives the protective discard
  a bonus only when the card it protects is the last copy. Otherwise, or if the
  lookahead still sees a needed card discarded, the save hint wins.

### D16. "Unsafe" means game-ending (2026-11-26)
Decided: a protective discard flags a card only if discarding it would **end the
game**, meaning it's a last copy of a card still needed. Losing a card we'd rather
keep is part of the game and is never signalled. Self-play found flags piling up
until every unhinted card was flagged, which forced discards of saved 5s (involved
in 221 of 307 losing discards; see docs/SELFPLAY_FINDINGS.md).
- The protected player treats the flagged card as a last copy when choosing a
  discard, so it's effectively saved. Its identity is not narrowed: a first
  version did narrow it, and wrong flags turned into confident misplays (40 of 53
  "certain" misplays in self-play).
- A chop that can't be critical from the protected player's own view isn't flagged.
  A flag drops once the holder's info shows it can't be critical.
- The discarder only gives the signal when the card really is a last copy. The
  advisor penalises a discard that would flag anything else as misleading
  (`Weights.misleading_protective`), so it plays or hints instead.
- If every card is hinted or flagged, discard the card least likely to be a last
  copy (then least likely playable, then oldest), not slot 1.

### D17. A multi-card hint that touches a chop last copy is still newest-first (2026-11-26)
Confirmed: a color hint touching a last copy on chop (e.g. Y2) plus other cards of
that color (e.g. Y4, newest), none known to be playable, is still read by D13: the
newest touched card plays first. There's no chop focus. So a save has to be a hint
that doesn't read as a play on another card (often a rank hint), or wait. Self-play:
about half the missed saves were multi-card color saves rejected for this reason.

### D18. Receivers read by the Meta; givers own the ambiguity (2026-11-27)
Decided: the receiver knows the Meta and takes its reading. It doesn't hedge
against readings a giver following the Meta would avoid. The giver tries never
to give a hint that can be read more than one way. When every option carries
some risk, the giver picks the hint whose wrong readings are least bad: ending
the game is worse than a strike, and a strike is worse than a wasted turn.
- **Hint to me (replaces the D11 bullet):** back to D3b. A single hinted card is
  narrowed to "playable now", "unlocked by a card I can see in a teammate's
  playable slot", or a critical non-5 with no visible unlock (a save). Self
  skip-level only when none of those is possible. So a plain play hint is a
  certain play. A "play or save" card (e.g. B1 or the last B2) stays open, and the
  receiver holds it, since a risky play that could lose a last copy is charged
  for it.
- **The giver reads its hint as each teammate will.** Each seat keeps a model of
  every teammate, fed the same events, with their inferences so far. It's exact
  except for the giver's own hand, which the model can't see (the teammate can).
- **What counts as a harmful reading,** checked against the real cards: a blind
  play that misses (self skip-level newest card, a multi-card lead, a card now
  "certainly playable"); a narrowing that leaves out the real card; a self
  skip-level whose unlock is another suit; a risky blind play the receiver
  would take that misses (half cost); a bystander concluding they hold an
  unlock and blind-playing a card that misses.
- **Cost:** a strike costs `misread_strike` (100), more than any hint is worth, so
  a clean option always wins. A misread that loses a last copy, or happens on
  the last strike, costs `game_loss` (300). An ambiguous hint is kept at that
  cost rather than rejected, so it can still beat a discard that risks the game.
  Structural D3c rejections (dead or unclear readings, re-hints read as
  skip-levels) stay, with the last-resort fallback.
- **Plays only count if the receiver can see them.** A hinted playable card the
  receiver can't tell from a non-playable one gets held, so it isn't credited as
  a play (`unclear_play` instead of `per_new_play`).
- **Stall:** a harmless hint that achieves nothing is always on the list
  (`stall_hint`, -20). It's chosen only over options that risk the game, e.g. a
  blind play that could lose a last copy. Without it, bots gambled with 3 tokens.
- **Plays first (2026-11-27):** each play a hint produces is worth `per_new_play`
  (25, was 10). A skip-level also counts the hinted card that plays once it's
  unlocked. A chop save, or a 5 save, can wait (`save_can_wait`, 40, below a
  play hint) when the target already knows a play (so they won't discard next
  turn) and at least 2 tokens will be left. An urgent save (110, 5s 100) still
  beats any play hint.

### D19. Every touched card of a multi-card hint plays, newest -> oldest (2026-11-27)
Decided: after the first card of a multi-card hint plays, the next touched card is
the next play. It isn't a probability call any more. Examples are with two 3s.
- **Read right after the card before it plays.** It's narrowed to "playable now"
  or "waiting on an unlock a teammate visibly holds". It's played once every card
  it could be is playable. So the second 3 plays only if some stack is at 2.
- **Hedge:** if it could also be a 3 whose 2 a teammate holds (e.g. hinted to
  them), wait until that 2 is played.
- **Nowhere to go means the chain ends.** If nothing it could be is playable at
  that moment, hold it. A play elsewhere later doesn't make it a play: the hint
  meant "next", not "some day". Self-play found a second 4 read as B4 turns later,
  once someone played a B3.
- A miss or a discard of a chain card ends the chain.
- **Only newly touched cards join the chain.** A card that was already hinted keeps
  its meaning (D3b collateral). Self-play: a saved M2 was touched again by a later
  "2", and after the new card played it read as "the next 2" (G2).
- **Giver:** plays the whole chain forward through the receiver's model. Every
  card that really plays in a row counts as a play. If the receiver would play
  one that misses (e.g. R2 then a G2 they'd read as B2), that's a strike (D18).
- **The giver also checks what its hint sets off.** If the first card waits on a
  teammate's visible unlock, the simulation plays that unlock first. After each
  simulated play, every card the receiver would now think is certainly playable
  is checked. Making someone play a card can move an *older* multi-card hint of
  theirs on, and the next card is then read on the new board. Self-play found a
  "2" hint whose B2 play turned an old blue B4 into "certainly B3".

### D20. A rank hint on the chop with nowhere to play is a last-copy save (2026-11-27)
Decided: a rank hint touching my chop, where that rank can't be a play (no stack
one below it, no card one below it in a teammate's playable slot), is a save. The
card is narrowed to the last copies it could be. It isn't a self skip-level.
- Example: stacks at 1, 2 or 4, no 3 in a playable slot, one Y4 gone. "4" on my
  oldest card means it's the other Y4 (in short rainbow, M4 too: one copy).
- Color saves on a last copy usually need two hints. The color reads as a play
  first ("B1 or the last B2"), and the giver's D18 checks treat it that way.

### D21. Protective discards come first; a watched chop is presumed safe (2026-11-27)
Decided: last copies are normally protected by protective discards (D15, D16).
Save hints are the last resort. The other side of that, by D6 ("discard your
oldest card unless you can infer it is unsafe"): if my chop was already my chop
when the previous player acted, and they didn't protect it, I treat it as safe.
- In code: the discard's last-copy risk counts at `watched_chop_risk` (25%)
  instead of my own odds in full. A chop that's new since then (I just drew into
  it, or a card in front of it left) counts in full.
- Self-play: 33 of 46 losses on a hinted last-copy misplay were risky blind
  plays at 0 tokens. The bot judged its chop discard as risky as the blind play,
  because it ignored that teammates had watched the chop.
- So with 1 token, a protective discard now beats a save hint, even under our
  rules, when my own chop was watched.

### D22. Never risky-play a card that could be a last copy (2026-11-27)
Decided: at our table almost nobody risky-plays a hinted last copy. Under our rules
(perfect game or bust), a risky play whose miss could lose a last copy isn't an
option. Hold the card, and discard the presumed-safe chop (D21) or stall instead.
A risky play where every miss is a card with another copy left is still allowed.
- Self-play (v13): 29 of 40 games lost to a hinted last-copy misplay were risky
  plays like "B3 or G3, 67% playable". The advisor took them because every other
  option already scored badly.
- Under official rules the play is still allowed, but charged for the chance.

### Table setup (2026-11-27)
We usually play 3-5 players, short rainbow (rainbow suit 2/1/1/1/1), perfect game
or bust, and restart a deal with few opening plays. We win about 5% of games.
Self-play mirrors this with `--variant short_rainbow --players 3 4 5
--min-opening-plays 3`, which redeals when fewer than 3 different 1s are dealt.

### Fixed along the way (2026-11-27)
- **A play known only by convention isn't a decline (D2).** A card known from a
  plain play hint (D18 narrowing) played before an expected unlock used to count
  as declining the unlock. Every seat then passed the unlock on, and the next
  candidate blind-played a wrong card (about half the bystander skip-level misses).
- **A protective discard isn't a decline either (D2, D12).** If the player
  expected to play an unlock makes a protective discard instead, the play is only
  delayed, like an urgent save. Only an action with no such reason passes it on:
  then the next candidate (possibly me) takes it as theirs and plays the card
  that was inferred at the time of the hint (its slot then, not a later draw).
- **The unlock holder must read the hint the same way.** If the giver counts on
  a visible holder to play an unlock, the holder's own reading must expect it too.
  Example: red on M2 + R2 in short rainbow. The giver sees the holder's R1. The
  holder doesn't, and M2 is a single copy, so the holder reads a save. That's a
  strike (D18): the others see a decline, and the next one blind-plays.
- **Bystanders are checked for every hint kind.** A card that's critical to the
  giver may not be to a bystander who sees another copy, so the giver's save
  becomes their skip-level.

### Self-play baseline (10-20 games each, so treat as rough)
After D12-D14 (15-30 games, seeds 7/11): regular 3p ~19, rainbow 3p ~22, 5p ~14.
Convention plays now hit ~86-97% (was ~30-60%). Older numbers below.

- Regular 3p: ~16-17 mean, 0 strikeouts.
- Rainbow 3p: ~16.
- 5p: ~15 after the last-strike guard.
- Certain plays never miss.
- Plays made on a convention hit only ~30-60%: the clearest area for real-game
  examples.

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

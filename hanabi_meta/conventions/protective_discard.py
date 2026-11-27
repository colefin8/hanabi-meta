"""Protective discard (docs/QUESTIONS.md D6, D15).

With exactly one hint token left, a player who discards instead of hinting is
protecting someone ahead: had they spent the last token, the first player
after them with nothing to play and no token to hint with would have had to
discard their chop. That player's chop is the card being protected.

The protected player isn't always the next one. Walk forward up to three
seats from the discarder, as if they had spent the last token (0 left):
* a player with a play they know about (hinted or expected by convention)
  plays it, and a 5 gives the token back;
* a player with a token hints, using it up;
* the first player with neither would have been forced to discard: their chop
  is unsafe.
If nobody in those seats would have been forced, the discard is ordinary.

With two or more tokens a discard is never protective: a hint (a save, or a
play hint that leaves the call to someone with fewer options) is better.

"Chop" = the oldest card that has no hint on it and isn't already flagged as
unsafe. Each repeat of the signal on the same player flags the next card along.
Only discards count, never plays.
"""
from __future__ import annotations

from ..belief.bookkeeping import is_playable
from ..engine.actions import DiscardEvent

DEPTH = 3


def is_protective(bs, ev: DiscardEvent, hints_before: int) -> bool:
    return hints_before == 1


def forced_discarder(ms, discarder: int, hints: int = 0, depth: int = DEPTH) -> int | None:
    """First player after `discarder` who'd have to discard with `hints` tokens left."""
    bs, n = ms.bs, ms.variant.num_players
    for k in range(1, min(depth, n - 1) + 1):
        q = (discarder + k) % n
        expected = {e.expected.uid for e in ms.expected_of(q)
                    if e.expected and e.expected.uid is not None
                    and (e.card is None or is_playable(e.card, bs.stacks))}
        play = next((sv for sv in ms.view(q)
                     if sv.certainly_playable or sv.uid in expected), None)
        if play is not None:
            if play.known is not None and play.known.rank == 5 and ms.variant.five_returns_hint:
                hints = min(hints + 1, ms.variant.max_hints)
            continue
        if hints > 0:
            hints -= 1
            continue
        return q
    return None


def chop_uid(bs, player: int, unsafe: set[int]) -> int | None:
    for s in bs.public.hands[player]:
        if not s.touched and s.uid not in unsafe:
            return s.uid
    return None


def flag(ms, ev: DiscardEvent, unsafe: set[int]) -> tuple[int, int] | None:
    """Mark the protected player's chop unsafe; return (player, uid), or None."""
    p = forced_discarder(ms, ev.player)
    if p is None:
        return None
    uid = chop_uid(ms.bs, p, unsafe)
    if uid is None:
        return None
    unsafe.add(uid)
    return p, uid

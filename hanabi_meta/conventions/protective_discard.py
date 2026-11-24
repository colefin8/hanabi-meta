"""Protective discard (docs/QUESTIONS.md D6).

With exactly one hint token left, the player directly before P could spend it,
but then P would have no hint to give and would discard their chop. If that
player discards instead, the discard tells P their chop is unsafe too. Each
time it happens again, the next card along is also unsafe.

"Chop" = P's oldest card that has no hint on it and isn't already flagged as
unsafe. Only discards count, never plays, and only by the player directly
before P.
"""
from __future__ import annotations

from ..belief.tracker import BeliefState
from ..engine.actions import DiscardEvent


def is_protective(bs: BeliefState, ev: DiscardEvent, hints_before: int) -> bool:
    return hints_before == 1


def flag(bs: BeliefState, ev: DiscardEvent, unsafe: set[int]) -> int | None:
    """Mark the next player's chop unsafe; return its uid (None if no chop)."""
    p = (ev.player + 1) % bs.variant.num_players
    for s in bs.public.hands[p]:
        if not s.touched and s.uid not in unsafe:
            unsafe.add(s.uid)
            return s.uid
    return None

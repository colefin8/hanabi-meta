"""Trash hints: "these cards are safe to discard" (docs/QUESTIONS.md D8).

Only given when the meaning is unmistakable. The test: from the receiver's own
point of view, every card the hint could be touching is already trash.
Examples:
* white hint when the white stack is complete;
* "1" hint when every stack has its 1;
* yellow hint with yellow at 4 when the receiver can see Y5 in another hand.

When the observer is a bystander, the receiver's view is a lower bound (the
receiver also sees the observer's hand). So a hint whose obviousness depends on
a card in the observer's hand won't be read here. That case is the
playable-5 convention's trigger (a dead color hint followed by a discard).
"""
from __future__ import annotations

from ..belief.bookkeeping import is_trash
from ..belief.tracker import BeliefState
from ..engine.actions import HintEvent
from .base import HintKind, Interpretation


def interpret_hint(bs: BeliefState, hint: HintEvent, hint_index: int) -> Interpretation | None:
    """Return a TRASH interpretation if the hint is unmistakably a discard hint."""
    if not hint.touched:
        return None
    v = bs.variant
    views = bs.view(hint.target)
    hand = bs.public.hands[hint.target]
    for i in hint.touched:
        if not all(is_trash(v, c, bs.stacks, bs.discards) for c in views[i].candidates):
            return None
    uids = [hand[i].uid for i in hint.touched]
    interp = Interpretation(
        hint_index=hint_index, giver=hint.giver, target=hint.target, kind=HintKind.TRASH,
        focus=uids, reason="every card this hint could touch is already trash: "
                           "safe to discard")
    if hint.target == bs.observer:
        interp.constraints = {hand[i].uid: set(views[i].candidates) for i in hint.touched}
    return interp

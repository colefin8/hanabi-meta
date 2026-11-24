"""Safety swap (docs/QUESTIONS.md D4).

Every "5" rank hint is a safety hint. Right after it, every player except the
hint giver reverses the cards in their hand that have no positive information.
Hinted cards keep their slots, and cards with only negative information count
as un-hinted (their negative info moves with them).

    a [b] c d e   ->   e [b] d c a

The swap is a physical rearrangement, so it is modelled as ReorderEvents that
move both the cards and their SlotInfo. Anything tracked by card (uid), such as
expectations and unsafe flags, follows the card to its new slot.
"""
from __future__ import annotations

from ..belief.slots import SlotInfo
from ..belief.tracker import BeliefState
from ..engine.actions import HintEvent, ReorderEvent


def is_safety_hint(hint: HintEvent) -> bool:
    return hint.kind == "rank" and hint.value == 5


def swap_order(slots: list[SlotInfo]) -> tuple[int, ...]:
    """new_hand[i] = old_hand[order[i]]: un-hinted slots reversed in place."""
    free = [i for i, s in enumerate(slots) if not s.touched]
    order = list(range(len(slots)))
    for k, i in enumerate(free):
        order[i] = free[-1 - k]
    return tuple(order)


def reorders(bs: BeliefState, hint: HintEvent) -> list[ReorderEvent]:
    """The ReorderEvents a safety hint causes (apply after the hint itself)."""
    out = []
    for p in range(bs.variant.num_players):
        if p == hint.giver:
            continue
        order = swap_order(bs.public.hands[p])
        if order != tuple(range(len(order))):
            out.append(ReorderEvent(p, order))
    return out

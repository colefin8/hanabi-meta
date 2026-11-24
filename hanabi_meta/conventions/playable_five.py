"""Inferring a playable 5 (docs/QUESTIONS.md D7).

Trigger: a color hint touches a card that is already dead (read as TRASH or
DEAD), and the receiver then discards that card. The discard is the signal:
the receiver is sure it is safe, so the hinter and receiver both see every
remaining card of that color in other players' hands.

Then, for each remaining rank of that color in order (stack+1 .. 5):
* visible holders are candidates (newest slot, known slot, or a playable line),
  ordered by who drew most recently;
* if nobody visible holds it, and the observer is neither the hinter nor the
  receiver, the observer holds it: their newest card, then the next newest.

Example: red at 4, nobody visibly holds R5 -> my newest card is R5.
Example: red at 3, another player's newest is R5 -> my newest is R4.

Limits (D10): only fires with the stack at MIN_STACK or higher (confirmed for
4, 3 and 2). I only infer my own card if exactly one needed card is missing
from what I can see.
"""
from __future__ import annotations

from ..belief.bookkeeping import unseen_counts
from ..belief.tracker import BeliefState
from ..engine.actions import DiscardEvent, DrawEvent, HintEvent
from ..engine.variant import Card
from .base import (Candidate, Expectation, HintKind, Interpretation, playable_position,
                   stacks_after)

MIN_STACK = 2


def draw_recency(bs: BeliefState) -> list[int]:
    """Players ordered by how recently they drew (most recent first)."""
    order: list[int] = []
    for e in reversed(bs.history):
        if isinstance(e, DrawEvent) and e.player not in order:
            order.append(e.player)
    return order + [p for p in range(bs.variant.num_players) if p not in order]


def on_discard(bs: BeliefState, interps: list[Interpretation], hints: list[HintEvent],
               ev: DiscardEvent, uid: int, index: int) -> Interpretation | None:
    """Call after `ev` is applied. `uid` is the discarded card's slot uid."""
    for interp, hint in zip(reversed(interps), reversed(hints)):
        if (hint is None or hint.kind != "color" or interp.target != ev.player
                or interp.kind not in (HintKind.TRASH, HintKind.DEAD)
                or uid not in interp.focus):
            continue
        return _infer(bs, hint, index)
    return None


def _infer(bs: BeliefState, hint: HintEvent, index: int) -> Interpretation:
    v, cs = bs.variant, bs.variant.card_str
    suit = hint.value
    height = bs.stacks[suit]
    needed = [Card(suit, r) for r in range(height + 1, 6)]
    if height < MIN_STACK or not needed:
        return Interpretation(
            hint_index=index, giver=hint.giver, target=hint.target,
            kind=HintKind.PLAYABLE_FIVE, focus=[],
            reason=f"dead {v.suits[suit].name} hint discarded, but the stack is too low "
                   f"for a playable-5 signal")
    excluded = {hint.giver, hint.target}
    recency = draw_recency(bs)
    can_hold = unseen_counts(v, bs.seen_by(bs.observer))
    exps = []
    for k, need in enumerate(needed):
        board = stacks_after(bs.stacks, needed[:k])
        cands = []
        visible_anywhere = False
        for p in recency:
            if p in excluded or p == bs.observer:
                continue
            for slot, c in enumerate(bs.hands[p]):
                if c != need:
                    continue
                visible_anywhere = True
                how = playable_position(bs, p, slot, need, board)
                if how:
                    cands.append(Candidate(p, bs.public.hands[p][slot].uid, how))
                    break
        if (not visible_anywhere and bs.observer not in excluded and can_hold[need] > 0):
            cands.append(Candidate(bs.observer, None, "inferred"))
        exps.append(Expectation(need, cands, f"playable-5 signal: {cs(need)}", index))
    mine = [e for e in exps if e.candidates and e.candidates[-1].how == "inferred"
            and len(e.candidates) == 1]
    if len(mine) > 1:  # I'd need to hold several of them: too ambiguous to act on
        for e in mine:
            e.candidates = []
    name = v.suits[suit].name
    return Interpretation(
        hint_index=index, giver=hint.giver, target=hint.target, kind=HintKind.PLAYABLE_FIVE,
        focus=[], expectations=exps,
        reason=f"p{hint.target} discarded the dead {name} card: the rest of {name} "
               f"({', '.join(cs(n) for n in needed)}) is in other hands")

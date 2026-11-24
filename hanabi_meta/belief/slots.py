"""Layer 2: per-slot candidate sets from public (hint) information.

A SlotInfo is a mutable object that follows one physical card through the
hand. Plays/discards remove it and everything to its right slides left; draws
append a fresh one on the right. Because slots are objects, a hand can also be
permuted (needed later for the safety-swap convention) without losing the hint
history attached to each card.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count

from ..engine.actions import HintEvent
from ..engine.variant import Card, Variant

_uid = count()


@dataclass
class SlotInfo:
    possible: set[Card]
    drawn_turn: int
    uid: int = field(default_factory=lambda: next(_uid))
    #: Positive hints that touched this card, e.g. [("color", 0), ("rank", 3)].
    positive: list[tuple[str, int]] = field(default_factory=list)
    #: Hints that did NOT touch it (negative information).
    negative: list[tuple[str, int]] = field(default_factory=list)

    @property
    def touched(self) -> bool:
        return bool(self.positive)

    def copy(self) -> "SlotInfo":
        return SlotInfo(set(self.possible), self.drawn_turn, self.uid,
                        list(self.positive), list(self.negative))


class PublicKnowledge:
    """Everything any table member can deduce from the hint history alone."""

    def __init__(self, variant: Variant) -> None:
        self.variant = variant
        self.hands: list[list[SlotInfo]] = [[] for _ in range(variant.num_players)]

    def add_slot(self, player: int, turn: int) -> SlotInfo:
        s = SlotInfo(set(self.variant.all_cards()), turn)
        self.hands[player].append(s)
        return s

    def remove_slot(self, player: int, slot: int) -> SlotInfo:
        return self.hands[player].pop(slot)

    def apply_hint(self, hint: HintEvent) -> None:
        v = self.variant
        touching = {c for c in v.all_cards() if v.touches(hint.kind, hint.value, c)}
        for i, s in enumerate(self.hands[hint.target]):
            if i in hint.touched:
                s.possible &= touching
                s.positive.append((hint.kind, hint.value))
            else:
                s.possible -= touching
                s.negative.append((hint.kind, hint.value))
            if not s.possible:
                raise ValueError(
                    f"hint left player {hint.target} slot {i} with no possible card")

    def permute(self, player: int, order: list[int]) -> None:
        """Reorder a hand: new_hand[i] = old_hand[order[i]]."""
        old = self.hands[player]
        if sorted(order) != list(range(len(old))):
            raise ValueError("order must be a permutation of slot indices")
        self.hands[player] = [old[i] for i in order]

"""Layer 1: card bookkeeping and per-card status (playable / trash / critical)."""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Sequence

from ..engine.variant import Card, Variant


def unseen_counts(variant: Variant, seen: Iterable[Card]) -> Counter[Card]:
    """Copies of each card identity not accounted for by `seen`.

    `seen` should be everything the viewer can locate: played cards, discards,
    and cards visible in other players' hands.
    """
    counts: Counter[Card] = Counter({c: variant.copies(c) for c in variant.all_cards()})
    counts.subtract(Counter(seen))
    if any(v < 0 for v in counts.values()):
        bad = [variant.card_str(c) for c, v in counts.items() if v < 0]
        raise ValueError(f"more copies seen than exist: {bad}")
    return counts


def played_cards(stacks: Sequence[int]) -> list[Card]:
    return [Card(s, r) for s, h in enumerate(stacks) for r in range(1, h + 1)]


def is_playable(card: Card, stacks: Sequence[int]) -> bool:
    return stacks[card.suit] == card.rank - 1


def max_reachable(variant: Variant, suit: int, stacks: Sequence[int],
                  discarded: Counter[Card]) -> int:
    """Highest rank this suit's stack can still reach given the discard pile."""
    for r in range(stacks[suit] + 1, 6):
        if discarded[Card(suit, r)] >= variant.copies(Card(suit, r)):
            return r - 1
    return 5


def is_trash(variant: Variant, card: Card, stacks: Sequence[int],
             discarded: Counter[Card]) -> bool:
    """Already played, or can never be played because a lower card is gone."""
    return card.rank > max_reachable(variant, card.suit, stacks, discarded) or \
        card.rank <= stacks[card.suit]


def is_critical(variant: Variant, card: Card, stacks: Sequence[int],
                discarded: Counter[Card]) -> bool:
    """Last remaining copy of a card that is still needed."""
    if is_trash(variant, card, stacks, discarded):
        return False
    return variant.copies(card) - discarded[card] == 1

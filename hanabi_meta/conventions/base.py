"""Shared building blocks for conventions.

Conventions turn events into first-class objects:

* `Interpretation`: what a hint means under the Meta (one per hint).
* `Expectation`: "player X is expected to play the card in slot <uid>". It stays
  pending until X does it (fulfilled) or visibly declines (passed on to the next
  candidate). Inferences about the observer's own cards come from expectations
  that land on the observer.

Every object carries a plain-English `reason` so the advisor can explain itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from ..belief.bookkeeping import is_playable
from ..belief.tracker import BeliefState
from ..engine.variant import Card


class HintKind(str, Enum):
    PLAY = "play"              # a touched card is playable now
    SKIP_LEVEL = "skip_level"  # unlocks sit in newest / known slots
    SHOTGUN = "shotgun"        # an unlock sits further down a playable line
    SAVE = "save"              # critical card, no visible unlock
    SAFETY_FIVE = "safety_five"
    TRASH = "trash"            # unmistakable "safe to discard" hint
    PLAYABLE_FIVE = "playable_five"  # dead color hint + discard (not a hint itself)
    DEAD = "dead"              # touched card is trash, but not obviously to the receiver
    UNCLEAR = "unclear"


class ExpStatus(str, Enum):
    PENDING = "pending"
    FULFILLED = "fulfilled"
    FAILED = "failed"  # the play was attempted and missed


@dataclass
class Candidate:
    """One player who might hold an expected card, and where."""

    player: int
    #: uid of the slot holding it; None means "observer's own playable slot,
    #: resolved when the expectation reaches the observer".
    uid: int | None
    how: str  # "newest" | "known" | "line" | "inferred"
    #: For uid=None: the observer's untouched cards (uids, newest first) when
    #: the signal was given. The playable slot is picked from these, so a card
    #: drawn after the hint is never mistaken for the one the hinter meant.
    line: tuple[int, ...] | None = None


@dataclass
class Expectation:
    #: The card expected to be played. None when it depends on which hypothesis
    #: about the observer's hand is true; then `possible` lists the options.
    card: Card | None
    candidates: list[Candidate]
    reason: str
    source_hint: int  # index into MetaState.interpretations
    status: ExpStatus = ExpStatus.PENDING
    #: Index into `candidates` of who is currently expected to act.
    current: int = 0
    possible: set[Card] = field(default_factory=set)
    log: list[str] = field(default_factory=list)
    #: Self skip-level only: uids of my hinted cards this unlock explains. When
    #: the play succeeds, the shotgun continues down my line (D3).
    self_hint: list[int] = field(default_factory=list)
    #: The expected player gave an urgent save instead of playing; that turn
    #: does not count as declining (one turn per save).
    excused: int = 0

    def options(self) -> set[Card]:
        return {self.card} if self.card is not None else set(self.possible)

    @property
    def expected(self) -> Candidate | None:
        if self.status is not ExpStatus.PENDING or self.current >= len(self.candidates):
            return None
        return self.candidates[self.current]


@dataclass
class Interpretation:
    hint_index: int
    giver: int
    target: int
    kind: HintKind
    #: uids of touched cards the hint is "about" (playable or skip-unlocked).
    focus: list[int]
    reason: str
    expectations: list[Expectation] = field(default_factory=list)
    #: Narrowing of the observer's own slots implied by this reading (uid -> cards).
    constraints: dict[int, set[Card]] = field(default_factory=dict)


# ---- helpers shared by conventions -------------------------------------------

def turn_order_after(giver: int, n: int) -> list[int]:
    """Players in the order they act after `giver` (giver last)."""
    return [(giver + k) % n for k in range(1, n + 1)]


def observer_line(bs: BeliefState) -> tuple[int, ...]:
    """The observer's untouched cards, newest first (their shotgun line)."""
    return tuple(s.uid for s in reversed(bs.public.hands[bs.observer]) if not s.touched)


def needed_unlocks(card: Card, stacks: Sequence[int]) -> list[Card]:
    """Cards that must be played before `card` becomes playable, in order."""
    return [Card(card.suit, r) for r in range(stacks[card.suit] + 1, card.rank)]


def stacks_after(stacks: Sequence[int], played: Sequence[Card]) -> list[int]:
    s = list(stacks)
    for c in played:
        if s[c.suit] == c.rank - 1:
            s[c.suit] = c.rank
    return s


def playable_position(bs: BeliefState, player: int, slot: int, card: Card,
                      stacks: Sequence[int]) -> str | None:
    """How `player` would come to play `card` in `slot`, or None.

    `stacks` is the board at the time the card is expected to be played
    (earlier unlocks in the chain already on it).

    * "known": the player's own info already says the card is playable/known.
    * "newest": it is the player's newest (right-most) card.
    * "line": every newer card in that hand would play in order before it
      (the shotgun condition).
    """
    hand = bs.hands[player]
    if hand[slot] != card:
        return None
    sv = bs.view(player)[slot]
    if sv.known == card or sv.certainly_playable:
        return "known"
    if slot == len(hand) - 1:
        return "newest"
    s = list(stacks)
    for j in range(len(hand) - 1, slot, -1):
        c = hand[j]
        if c is None or not is_playable(c, s):
            return None
        s[c.suit] = c.rank
    if is_playable(card, s):
        return "line"
    return None

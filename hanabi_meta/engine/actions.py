"""Actions a player can take, and the public events the engine emits.

Slot convention (our Meta, basics 2-3): slot 0 is the OLDEST, left-most card.
Playing/discarding removes a slot, everything to its right slides left, and
the newly drawn card is appended at the right (highest index = newest).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Union

from .variant import Card


class ActionType(str, Enum):
    PLAY = "play"
    DISCARD = "discard"
    HINT_COLOR = "hint_color"
    HINT_RANK = "hint_rank"


@dataclass(frozen=True)
class Action:
    type: ActionType
    slot: int | None = None  # for play / discard
    target: int | None = None  # for hints: absolute player index
    value: int | None = None  # for hints: color (suit index) or rank

    @staticmethod
    def play(slot: int) -> "Action":
        return Action(ActionType.PLAY, slot=slot)

    @staticmethod
    def discard(slot: int) -> "Action":
        return Action(ActionType.DISCARD, slot=slot)

    @staticmethod
    def hint_color(target: int, color: int) -> "Action":
        return Action(ActionType.HINT_COLOR, target=target, value=color)

    @staticmethod
    def hint_rank(target: int, rank: int) -> "Action":
        return Action(ActionType.HINT_RANK, target=target, value=rank)

    @property
    def is_hint(self) -> bool:
        return self.type in (ActionType.HINT_COLOR, ActionType.HINT_RANK)

    @property
    def hint_kind(self) -> str:
        return "color" if self.type is ActionType.HINT_COLOR else "rank"

    def to_dict(self) -> dict:
        return {k: v for k, v in
                {"type": self.type.value, "slot": self.slot, "target": self.target,
                 "value": self.value}.items() if v is not None}

    @staticmethod
    def from_dict(d: dict) -> "Action":
        return Action(ActionType(d["type"]), d.get("slot"), d.get("target"), d.get("value"))


# ---- public events ---------------------------------------------------------
# These are what a belief tracker consumes. They are also what a human enters
# during a live game, so they never contain anything a player could not know,
# except DrawEvent.card, which is None for draws the observer cannot see.


@dataclass(frozen=True)
class HintEvent:
    giver: int
    target: int
    kind: str  # "color" | "rank"
    value: int
    touched: tuple[int, ...]  # slot indices in target's hand at hint time


@dataclass(frozen=True)
class PlayEvent:
    player: int
    slot: int
    card: Card
    success: bool


@dataclass(frozen=True)
class DiscardEvent:
    player: int
    slot: int
    card: Card


@dataclass(frozen=True)
class DrawEvent:
    player: int
    card: Card | None  # None when the observer cannot see it (their own draw)


@dataclass(frozen=True)
class ReorderEvent:
    """A player physically rearranges their hand: new_hand[i] = old_hand[order[i]].

    Not a turn. Our Meta's safety swap (reverse your un-hinted cards after a 5
    hint) is the only source of these.
    """
    player: int
    order: tuple[int, ...]


Event = Union[HintEvent, PlayEvent, DiscardEvent, DrawEvent, ReorderEvent]


def mask_for(observer: int, event: Event) -> Event:
    """Return the event as `observer` sees it (hides their own draws)."""
    if isinstance(event, DrawEvent) and event.player == observer:
        return DrawEvent(event.player, None)
    return event

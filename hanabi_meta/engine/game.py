"""Pure-Python Hanabi rules engine for any Variant and 2-5 players."""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence

from .actions import (Action, ActionType, DiscardEvent, DrawEvent, Event, HintEvent,
                      PlayEvent, ReorderEvent, mask_for)
from .variant import Card, Variant


class IllegalAction(ValueError):
    pass


@dataclass
class TurnRecord:
    turn: int
    player: int
    action: Action
    events: list[Event] = field(default_factory=list)


class Game:
    """Full (omniscient) game state.

    The deck is a list whose index 0 is the next card to be drawn. Dealing is
    player-major: player 0 receives the first `hand_size` cards, and so on. A
    fixed `deck` order can be passed for reproducible tests and replays.
    """

    def __init__(self, variant: Variant, seed: int | None = None,
                 deck: Sequence[Card] | None = None) -> None:
        self.variant = variant
        self.seed = seed
        if deck is None:
            cards = variant.deck()
            random.Random(seed).shuffle(cards)
        else:
            cards = list(deck)
            if Counter(cards) != Counter(variant.deck()):
                raise ValueError("deck does not match variant composition")
        self.initial_deck: tuple[Card, ...] = tuple(cards)
        self.deck: list[Card] = list(cards)
        n = variant.num_players
        self.hands: list[list[Card]] = [[] for _ in range(n)]
        self.stacks: list[int] = [0] * variant.num_suits
        self.discards: list[Card] = []
        self.hints = variant.max_hints
        self.strikes = 0
        self.current = 0
        self.turn = 0
        #: Turns remaining once the deck is empty (None while cards remain).
        self.turns_left: int | None = None
        self.history: list[TurnRecord] = []
        self.deal_events: list[Event] = []
        for p in range(n):
            for _ in range(variant.hand_size):
                self.deal_events.append(self._draw(p))

    # ---- queries -----------------------------------------------------------
    @property
    def num_players(self) -> int:
        return self.variant.num_players

    @property
    def is_over(self) -> bool:
        return self.end_reason is not None

    @property
    def is_perfect(self) -> bool:
        return sum(self.stacks) == self.variant.max_score

    @property
    def perfect_lost(self) -> str | None:
        """Why a perfect game can no longer happen (None while it still can)."""
        from ..belief.bookkeeping import max_plays_left, perfect_lost  # (import cycle)
        if self.strikes >= self.variant.max_strikes:
            return "struck out"
        return perfect_lost(self.variant, self.stacks, Counter(self.discards),
                            max_plays_left(self.num_players, len(self.deck), self.turns_left))

    @property
    def end_reason(self) -> str | None:
        """Why the game is over, or None while it continues."""
        v = self.variant
        if self.strikes >= v.max_strikes:
            return "struck out"
        if self.is_perfect:
            return "perfect game"
        if v.end_when_perfect_lost:
            lost = self.perfect_lost
            if lost:
                return f"perfect game lost: {lost}"
        if self.turns_left == 0:
            return "final round over"
        return None

    @property
    def score(self) -> int:
        if self.strikes >= self.variant.max_strikes and self.variant.zero_score_on_strikeout:
            return 0
        return sum(self.stacks)

    def is_playable(self, card: Card) -> bool:
        return self.stacks[card.suit] == card.rank - 1

    def hint_touches(self, target: int, kind: str, value: int) -> tuple[int, ...]:
        return tuple(i for i, c in enumerate(self.hands[target])
                     if self.variant.touches(kind, value, c))

    def check_legal(self, action: Action, player: int | None = None) -> str | None:
        """Return None if legal, else a reason string."""
        p = self.current if player is None else player
        if self.is_over:
            return "game is over"
        if action.type in (ActionType.PLAY, ActionType.DISCARD):
            if action.slot is None or not 0 <= action.slot < len(self.hands[p]):
                return "bad slot"
            if (action.type is ActionType.DISCARD and self.hints >= self.variant.max_hints
                    and not self.variant.allow_discard_at_max_hints):
                return "cannot discard with all hint tokens available"
            return None
        if self.hints <= 0:
            return "no hint tokens"
        if action.target is None or action.target == p or not 0 <= action.target < self.num_players:
            return "bad hint target"
        if action.type is ActionType.HINT_COLOR:
            if action.value not in self.variant.hint_colors:
                return "color cannot be hinted in this variant"
        elif action.value not in (1, 2, 3, 4, 5):
            return "bad rank"
        if not self.variant.allow_empty_hints and not self.hint_touches(
                action.target, action.hint_kind, action.value):
            return "hint touches no cards"
        return None

    def legal_actions(self, player: int | None = None) -> list[Action]:
        p = self.current if player is None else player
        cands: list[Action] = []
        for s in range(len(self.hands[p])):
            cands += [Action.play(s), Action.discard(s)]
        for t in range(self.num_players):
            if t == p:
                continue
            cands += [Action.hint_color(t, c) for c in self.variant.hint_colors]
            cands += [Action.hint_rank(t, r) for r in (1, 2, 3, 4, 5)]
        return [a for a in cands if self.check_legal(a, p) is None]

    # ---- transitions ----------------------------------------------------------
    def _draw(self, player: int) -> DrawEvent:
        card = self.deck.pop(0)
        self.hands[player].append(card)
        return DrawEvent(player, card)

    def step(self, action: Action) -> TurnRecord:
        reason = self.check_legal(action)
        if reason:
            raise IllegalAction(reason)
        p, v = self.current, self.variant
        rec = TurnRecord(self.turn, p, action)
        if action.is_hint:
            assert action.target is not None and action.value is not None
            touched = self.hint_touches(action.target, action.hint_kind, action.value)
            self.hints -= 1
            rec.events.append(HintEvent(p, action.target, action.hint_kind, action.value, touched))
        else:
            assert action.slot is not None
            card = self.hands[p].pop(action.slot)
            if action.type is ActionType.PLAY:
                ok = self.is_playable(card)
                if ok:
                    self.stacks[card.suit] += 1
                    if card.rank == 5 and v.five_returns_hint:
                        self.hints = min(self.hints + 1, v.max_hints)
                else:
                    self.strikes += 1
                    self.discards.append(card)
                rec.events.append(PlayEvent(p, action.slot, card, ok))
            else:
                self.discards.append(card)
                self.hints = min(self.hints + 1, v.max_hints)
                rec.events.append(DiscardEvent(p, action.slot, card))
            if self.deck:
                rec.events.append(self._draw(p))
                if not self.deck:
                    # Everyone, including the player who drew the last card,
                    # gets exactly one more turn.
                    self.turns_left = self.num_players + 1  # decremented below
        if self.turns_left is not None:
            self.turns_left -= 1
        self.history.append(rec)
        self.turn += 1
        self.current = (p + 1) % self.num_players
        return rec

    def reorder(self, player: int, order: tuple[int, ...]) -> ReorderEvent:
        """Physically rearrange a hand (between turns). Recorded in the last turn."""
        hand = self.hands[player]
        if sorted(order) != list(range(len(hand))):
            raise IllegalAction("order must be a permutation of the hand")
        self.hands[player] = [hand[i] for i in order]
        ev = ReorderEvent(player, tuple(order))
        if self.history:
            self.history[-1].events.append(ev)
        return ev

    # ---- observer helpers -----------------------------------------------------
    def events_for(self, observer: int) -> list[Event]:
        """The full public event stream (deal + all turns) as `observer` sees it."""
        evs = [mask_for(observer, e) for e in self.deal_events]
        for rec in self.history:
            evs += [mask_for(observer, e) for e in rec.events]
        return evs

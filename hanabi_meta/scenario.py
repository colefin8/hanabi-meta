"""Build table situations from short text, for tests and (later) the CLI.

    t = Scenario("regular", observer=0, hands=[
            "? ? ? ? ?",          # me (always unknown)
            "R1 B4 W3 G2 Y2",     # player 1, oldest -> newest
            "R3 B1 Y3 G4 W4",     # player 2
        ], stacks="Y1")           # stack heights; omitted suits are 0
    t.hint(2, 1, "Y")             # player 2 hints player 1 "yellow"
    t.ms.explain()

Hints to the observer need `touched=[slots]`, because the observer can't see
which cards match. Plays and discards name the card revealed; draws by others
name the card drawn, draws by the observer don't.
"""
from __future__ import annotations

from .belief.tracker import BeliefState
from .conventions.meta_state import MetaState
from .engine.actions import DiscardEvent, DrawEvent, HintEvent, PlayEvent
from .engine.variant import Card, make_variant


class Scenario:
    def __init__(self, variant: str, hands: list[str], observer: int = 0,
                 stacks: str = "", discards: str = "", hints: int | None = None,
                 strikes: int = 0, **variant_overrides) -> None:
        self.variant = make_variant(variant, len(hands), **variant_overrides)
        v = self.variant
        parsed: list[list[Card | None]] = [
            [None if t == "?" else v.parse_card(t) for t in h.split()] for h in hands]
        heights = [0] * v.num_suits
        for tok in stacks.split():
            c = v.parse_card(tok)
            heights[c.suit] = c.rank
        disc = [v.parse_card(t) for t in discards.split()]
        self.ms = MetaState(BeliefState.from_snapshot(
            v, observer, parsed, heights, disc, hints, strikes))

    @property
    def bs(self) -> BeliefState:
        return self.ms.bs

    def _hint_value(self, value: str | int) -> tuple[str, int]:
        if isinstance(value, int) or str(value).isdigit():
            return "rank", int(value)
        return "color", self.variant.color_index(str(value))

    def hint(self, giver: int, target: int, value: str | int,
             touched: list[int] | None = None) -> "Scenario":
        kind, val = self._hint_value(value)
        if touched is None:
            if target == self.bs.observer:
                raise ValueError("hints to the observer need touched=[...]")
            touched = [i for i, c in enumerate(self.bs.hands[target])
                       if c is not None and self.variant.touches(kind, val, c)]
        self.ms.apply(HintEvent(giver, target, kind, val, tuple(touched)))
        return self

    def play(self, player: int, slot: int, card: str, draw: str | None = None) -> "Scenario":
        c = self.variant.parse_card(card)
        ok = self.bs.stacks[c.suit] == c.rank - 1
        self.ms.apply(PlayEvent(player, slot, c, ok))
        return self._draw(player, draw)

    def discard(self, player: int, slot: int, card: str, draw: str | None = None) -> "Scenario":
        self.ms.apply(DiscardEvent(player, slot, self.variant.parse_card(card)))
        return self._draw(player, draw)

    def _draw(self, player: int, draw: str | None) -> "Scenario":
        if self.bs.deck_size <= 0:
            return self
        if player == self.bs.observer:
            self.ms.apply(DrawEvent(player, None))
        else:
            if draw is None:
                raise ValueError(f"say what player {player} drew (draw='..')")
            self.ms.apply(DrawEvent(player, self.variant.parse_card(draw)))
        return self

    # ---- convenience for assertions ------------------------------------------------
    def last(self):
        return self.ms.interpretations[-1]

    def my_slot(self, slot: int) -> set[str]:
        sv = self.ms.view(self.bs.observer)[slot]
        return {self.variant.card_str(c) for c in sv.candidates}

    def expected(self, player: int) -> list[str]:
        cs = self.variant.card_str
        return [cs(e.card) if e.card else "/".join(sorted(cs(c) for c in e.possible))
                for e in self.ms.expected_of(player)]

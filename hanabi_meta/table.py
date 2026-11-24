"""A full game plus every seat's point of view.

`Table` wraps the engine `Game` and keeps one MetaState per seat, each fed the
events masked for that seat. Safety-swap reorders are computed by the
MetaStates and mirrored onto the engine's hands (see the MetaState docstring:
they must not be fed back in).

Used by self-play (bots choose the actions) and by spectator mode (an outside
observer types the real game's actions).
"""
from __future__ import annotations

from typing import Sequence

from .conventions.meta_state import MetaState
from .engine.actions import Action, mask_for
from .engine.game import Game, TurnRecord
from .engine.variant import Card, Variant
from .gamelog import view_to_json


class Table:
    def __init__(self, variant: Variant, seed: int | None = None,
                 deck: Sequence[Card] | None = None) -> None:
        self.variant = variant
        self.game = Game(variant, seed=seed, deck=deck)
        self.seats = [MetaState.new(variant, p) for p in range(variant.num_players)]
        for e in self.game.deal_events:
            for p, ms in enumerate(self.seats):
                ms.apply(mask_for(p, e))

    @property
    def current(self) -> int:
        return self.game.current

    def step(self, action: Action) -> TurnRecord:
        """Apply an action to the engine and every seat; mirror safety swaps."""
        rec = self.game.step(action)
        for e in list(rec.events):  # copy: reorder() appends to rec.events
            reorders = []
            for q, ms in enumerate(self.seats):
                ms.apply(mask_for(q, e))
                if q == 0:
                    reorders = list(ms.last_reorders)
            for r in reorders:
                self.game.reorder(r.player, r.order)
        return rec

    def views(self) -> dict[int, dict]:
        """Every seat's observation, for logging."""
        return {q: view_to_json(ms.bs, ms.constraints()) for q, ms in enumerate(self.seats)}

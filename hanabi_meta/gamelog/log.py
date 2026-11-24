"""JSONL game log: every game, simulated or real, in one documented format.

One JSON object per line. A file can hold many games; each game is a
`game_start` record, then `turn` records, then a `game_end` record. The full
spec, with examples, is in docs/LOG_FORMAT.md. Keep the two in sync.

Cards are strings like "R3" (suit letter + rank). Players are 0-based. Slots
are 0-based here (the CLI shows them 1-based).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..belief.tracker import BeliefState
from ..engine.actions import (Action, DiscardEvent, DrawEvent, Event, HintEvent, PlayEvent,
                              ReorderEvent)
from ..engine.game import Game
from ..engine.variant import Variant

FORMAT_VERSION = 1


# ---- events <-> JSON ---------------------------------------------------------------

def event_to_json(v: Variant, e: Event) -> dict[str, Any]:
    cs = v.card_str
    if isinstance(e, HintEvent):
        return {"kind": "hint", "giver": e.giver, "target": e.target, "hint_kind": e.kind,
                "value": e.value, "touched": list(e.touched)}
    if isinstance(e, PlayEvent):
        return {"kind": "play", "player": e.player, "slot": e.slot, "card": cs(e.card),
                "success": e.success}
    if isinstance(e, DiscardEvent):
        return {"kind": "discard", "player": e.player, "slot": e.slot, "card": cs(e.card)}
    if isinstance(e, DrawEvent):
        return {"kind": "draw", "player": e.player,
                "card": cs(e.card) if e.card is not None else None}
    if isinstance(e, ReorderEvent):
        return {"kind": "reorder", "player": e.player, "order": list(e.order)}
    raise TypeError(e)


def event_from_json(v: Variant, d: dict[str, Any]) -> Event:
    k = d["kind"]
    card = (lambda s: v.parse_card(s) if s is not None else None)
    if k == "hint":
        return HintEvent(d["giver"], d["target"], d["hint_kind"], d["value"],
                         tuple(d["touched"]))
    if k == "play":
        return PlayEvent(d["player"], d["slot"], card(d["card"]), d["success"])
    if k == "discard":
        return DiscardEvent(d["player"], d["slot"], card(d["card"]))
    if k == "draw":
        return DrawEvent(d["player"], card(d["card"]))
    if k == "reorder":
        return ReorderEvent(d["player"], tuple(d["order"]))
    raise ValueError(f"unknown event kind {k!r}")


def view_to_json(bs: BeliefState, constraints: dict | None = None) -> dict[str, Any]:
    """One player's observation: board, others' hands, own-slot knowledge."""
    v, cs = bs.variant, bs.variant.card_str
    me = bs.observer
    return {
        "player": me,
        "stacks": list(bs.stacks),
        "hints": bs.hints,
        "strikes": bs.strikes,
        "deck_size": bs.deck_size,
        "discards": sorted(cs(c) for c in bs.discards.elements()),
        "hands": {str(p): [cs(c) for c in h] for p, h in enumerate(bs.hands) if p != me},
        "touched": {str(p): [s.touched for s in h] for p, h in enumerate(bs.public.hands)},
        "own_candidates": [sorted(cs(c) for c in sv.candidates)
                           for sv in bs.view(me, constraints)],
    }


# ---- writing ---------------------------------------------------------------------

@dataclass
class GameRecorder:
    """Collects one game's records; `records()` gives them in file order."""

    variant: Variant
    source: str                       # "selfplay" | "live" | "spectator"
    deck: list[str] | None = None     # full deck order, index 0 drawn first
    seed: int | None = None
    observer: int | None = None       # live games: whose point of view
    players: list[str] | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    game_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    _records: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._records.append({
            "type": "game_start", "format_version": FORMAT_VERSION, "game_id": self.game_id,
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": self.source, "variant": self.variant.to_dict(), "deck": self.deck,
            "seed": self.seed, "observer": self.observer, "players": self.players,
            **self.meta,
        })

    def deal(self, events: Iterable[Event]) -> None:
        self._records.append({"type": "deal",
                              "events": [event_to_json(self.variant, e) for e in events]})

    def turn(self, turn: int, player: int, action: Action | None, events: Iterable[Event],
             views: dict[int, dict] | None = None, advice: list[dict] | None = None,
             note: str | None = None, **extra: Any) -> None:
        rec: dict[str, Any] = {
            "type": "turn", "game_id": self.game_id, "turn": turn, "player": player,
            "action": action.to_dict() if action else None,
            "events": [event_to_json(self.variant, e) for e in events],
        }
        if views:
            rec["views_before"] = {str(p): vw for p, vw in views.items()}
        if advice is not None:
            rec["advice"] = advice
        if note:
            rec["note"] = note
        rec.update(extra)
        self._records.append(rec)

    def end(self, score: int, strikes: int, turns: int, **extra: Any) -> None:
        self._records.append({"type": "game_end", "game_id": self.game_id, "score": score,
                              "strikes": strikes, "turns": turns, **extra})

    def records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def append_to(self, path: Path | str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            for r in self._records:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")


# ---- reading ---------------------------------------------------------------------

@dataclass
class LoggedGame:
    start: dict[str, Any]
    deal: list[dict[str, Any]]
    turns: list[dict[str, Any]]
    end: dict[str, Any] | None

    @property
    def variant(self) -> Variant:
        return Variant.from_dict(self.start["variant"])


def read_games(path: Path | str) -> Iterator[LoggedGame]:
    cur: LoggedGame | None = None
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            r = json.loads(line)
            t = r.get("type")
            if t == "game_start":
                if r.get("format_version") != FORMAT_VERSION:
                    raise ValueError(f"line {n}: unsupported format_version")
                if cur:
                    yield cur
                cur = LoggedGame(r, [], [], None)
            elif cur is None:
                raise ValueError(f"line {n}: record before game_start")
            elif t == "deal":
                cur.deal = r["events"]
            elif t == "turn":
                cur.turns.append(r)
            elif t == "game_end":
                cur.end = r
            else:
                raise ValueError(f"line {n}: unknown record type {t!r}")
    if cur:
        yield cur


def replay(g: LoggedGame) -> Game:
    """Re-run a logged game with a known deck through the engine and check it."""
    if not g.start.get("deck"):
        raise ValueError("replay needs the deck order (live games don't have it)")
    v = g.variant
    game = Game(v, deck=[v.parse_card(c) for c in g.start["deck"]])
    for t in g.turns:
        rec = game.step(Action.from_dict(t["action"]))
        for e in t["events"]:
            if e["kind"] == "reorder":
                game.reorder(e["player"], tuple(e["order"]))
        got = [event_to_json(v, e) for e in rec.events]
        if got != t["events"]:
            raise ValueError(f"turn {t['turn']}: replay diverged: {got} != {t['events']}")
    if g.end and game.score != g.end["score"]:
        raise ValueError(f"score {game.score} != logged {g.end['score']}")
    return game

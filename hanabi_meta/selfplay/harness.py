"""Self-play: Meta agents that use the advisor play full games.

Each seat has its own MetaState (its own point of view) fed the masked public
events. On its turn an agent takes the advisor's top recommendation. Safety-swap
reorders are computed by the MetaStates and mirrored onto the engine's hands
(see MetaState docstring: they must not be fed back in).

Statistics are collected so convention regressions show up as numbers:
score, strikes, which convention readings fired, how plays of each kind
(certain / convention / risky) turned out, and how expectations resolved.
"""
from __future__ import annotations

import argparse
import random
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ..advisor import Weights, advise
from ..conventions.base import ExpStatus
from ..conventions.meta_state import MetaState
from ..engine.actions import Action, ActionType, PlayEvent, mask_for
from ..engine.game import Game
from ..engine.variant import VARIANT_KINDS, Variant, make_variant
from ..gamelog import GameRecorder, view_to_json


@dataclass
class GameResult:
    score: int
    strikes: int
    turns: int
    #: Counter of interpretation kinds, as read by the hint receivers.
    readings: Counter = field(default_factory=Counter)
    #: (play kind, "hit"/"miss") -> count. Kind: certain / convention / risky.
    plays: Counter = field(default_factory=Counter)
    #: Expectation outcomes across all seats' MetaStates.
    expectations: Counter = field(default_factory=Counter)
    fallbacks: int = 0  # turns where the advisor had no legal suggestion


def _play_kind(reasons: list[str]) -> str:
    if any(r.startswith("convention:") for r in reasons):
        return "convention"
    if any(r.startswith("certainly playable") for r in reasons):
        return "certain"
    return "risky"


def play_game(variant: Variant, seed: int, weights: Weights | None = None,
              recorder_path: Path | None = None, log_views: bool = False) -> GameResult:
    game = Game(variant, seed=seed)
    n = variant.num_players
    seats = [MetaState.new(variant, p) for p in range(n)]
    for e in game.deal_events:
        for p, ms in enumerate(seats):
            ms.apply(mask_for(p, e))
    rec = None
    if recorder_path:
        rec = GameRecorder(variant, "selfplay", deck=[variant.card_str(c)
                                                      for c in game.initial_deck],
                           seed=seed)
        rec.deal(game.deal_events)
    result = GameResult(0, 0, 0)
    rng = random.Random(seed)
    while not game.is_over:
        p = game.current
        ms = seats[p]
        views = ({q: view_to_json(seats[q].bs, seats[q].constraints()) for q in range(n)}
                 if (rec and log_views) else None)
        recs = [r for r in advise(ms, weights) if game.check_legal(r.action) is None]
        if recs:
            choice = recs[0]
            action = choice.action
        else:
            result.fallbacks += 1
            choice = None
            action = rng.choice(game.legal_actions())
        turn = game.turn
        tr = game.step(action)
        for e in list(tr.events):  # copy: reorder() appends to tr.events
            reorders = []
            for q, s in enumerate(seats):
                s.apply(mask_for(q, e))
                if q == 0:
                    reorders = list(s.last_reorders)
            for r in reorders:
                game.reorder(r.player, r.order)
        if action.type is ActionType.PLAY and choice is not None:
            ev = next(e for e in tr.events if isinstance(e, PlayEvent))
            result.plays[(_play_kind(choice.reasons), "hit" if ev.success else "miss")] += 1
        if action.is_hint:
            target_ms = seats[action.target]
            result.readings[target_ms.interpretations[-1].kind.value] += 1
        if rec:
            advice = ([{"action": r.action.to_dict(), "score": round(r.score, 2),
                        "reasons": r.reasons} for r in recs[:3]])
            rec.turn(turn, p, action, tr.events, views=views, advice=advice)
    for s in seats:
        for e in s.expectations:
            result.expectations[e.status.value if e.status is not ExpStatus.PENDING
                                else ("pending" if e.expected else "no_candidate")] += 1
    result.score, result.strikes, result.turns = game.score, game.strikes, game.turn
    if rec:
        rec.end(game.score, game.strikes, game.turn)
        rec.append_to(recorder_path)
    return result


@dataclass
class BatchSummary:
    variant: str
    players: int
    results: list[GameResult]

    def text(self) -> str:
        rs = self.results
        scores = [r.score for r in rs]
        plays, readings, exps = Counter(), Counter(), Counter()
        for r in rs:
            plays.update(r.plays)
            readings.update(r.readings)
            exps.update(r.expectations)
        lines = [f"{self.variant}, {self.players} players, {len(rs)} games",
                 f"  score: mean {sum(scores) / len(scores):.1f}, min {min(scores)}, "
                 f"max {max(scores)}, strikeouts {sum(r.strikes >= 3 for r in rs)}",
                 "  plays (hit/miss):"]
        for kind in ("certain", "convention", "risky"):
            h, m = plays[(kind, "hit")], plays[(kind, "miss")]
            if h or m:
                lines.append(f"    {kind:<11} {h:>4} / {m:<4} ({h / (h + m):.0%} hit)")
        lines.append("  hint readings: " + ", ".join(f"{k} {v}" for k, v in
                                                     readings.most_common()))
        lines.append("  expectations: " + ", ".join(f"{k} {v}" for k, v in
                                                    exps.most_common()))
        fb = sum(r.fallbacks for r in rs)
        if fb:
            lines.append(f"  advisor fallbacks (random legal move): {fb}")
        return "\n".join(lines)


def run_batch(kind: str, players: int, games: int, seed: int = 0,
              log: Path | None = None, log_views: bool = False) -> BatchSummary:
    v = make_variant(kind, players)
    results = [play_game(v, seed + i, recorder_path=log, log_views=log_views)
               for i in range(games)]
    return BatchSummary(kind, players, results)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hanabi_meta.selfplay",
                                 description="Meta agents play full games")
    ap.add_argument("--variant", choices=VARIANT_KINDS + ("all",), default="regular")
    ap.add_argument("--players", type=int, nargs="+", default=[3])
    ap.add_argument("--games", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--log", type=Path, help="append games to this JSONL file")
    ap.add_argument("--views", action="store_true",
                    help="log every seat's view before each turn (bigger logs)")
    args = ap.parse_args(argv)
    kinds = VARIANT_KINDS if args.variant == "all" else (args.variant,)
    for kind in kinds:
        for n in args.players:
            t0 = time.perf_counter()
            s = run_batch(kind, n, args.games, args.seed, args.log, args.views)
            print(s.text())
            print(f"  ({time.perf_counter() - t0:.1f}s)\n")
    return 0

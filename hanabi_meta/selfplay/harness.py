"""Self-play: Meta agents that use the advisor play full games.

Each seat has its own MetaState (its own point of view; see table.Table). On
its turn an agent takes the advisor's top recommendation.

Statistics are collected so convention regressions show up as numbers.
The goal is a perfect game (our rules end the game as soon as one is
impossible), so the perfect-game rate comes first; score, strikes, which convention readings fired, how plays of each kind
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
from ..engine.actions import ActionType, PlayEvent
from ..engine.variant import VARIANT_KINDS, Variant, make_variant
from ..gamelog import GameRecorder
from ..table import Table


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
    perfect: bool = False
    end_reason: str | None = None


def _play_kind(reasons: list[str]) -> str:
    if any(r.startswith("convention:") for r in reasons):
        return "convention"
    if any(r.startswith("certainly playable") for r in reasons):
        return "certain"
    return "risky"


def play_game(variant: Variant, seed: int, weights: Weights | None = None,
              recorder_path: Path | None = None, log_views: bool = False) -> GameResult:
    table = Table(variant, seed=seed)
    game, seats = table.game, table.seats
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
        views = table.views() if (rec and log_views) else None
        recs = [r for r in advise(ms, weights) if game.check_legal(r.action) is None]
        if recs:
            choice = recs[0]
            action = choice.action
        else:
            result.fallbacks += 1
            choice = None
            action = rng.choice(game.legal_actions())
        turn = game.turn
        tr = table.step(action)
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
    result.perfect, result.end_reason = game.is_perfect, game.end_reason
    if rec:
        rec.end(game.score, game.strikes, game.turn, perfect=game.is_perfect,
                end_reason=game.end_reason)
        rec.append_to(recorder_path)
    return result


@dataclass
class BatchSummary:
    variant: str
    players: int
    results: list[GameResult]
    restarts: int = 0

    def text(self) -> str:
        rs = self.results
        scores = [r.score for r in rs]
        plays, readings, exps = Counter(), Counter(), Counter()
        for r in rs:
            plays.update(r.plays)
            readings.update(r.readings)
            exps.update(r.expectations)
        perfect = sum(r.perfect for r in rs)
        reasons = Counter((r.end_reason or "?").split(":")[0] for r in rs)
        lines = [f"{self.variant}, {self.players} players, {len(rs)} games"
                 + (f" ({self.restarts} deals restarted)" if self.restarts else ""),
                 f"  perfect games: {perfect}/{len(rs)} ({perfect / len(rs):.0%})",
                 "  ended by: " + ", ".join(f"{k} {v}" for k, v in reasons.most_common()),
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


def opening_plays(variant: Variant, seed: int) -> int:
    """Distinct playable cards dealt (one per suit with a 1 in some hand)."""
    from ..engine.game import Game
    g = Game(variant, seed=seed)
    return len({c.suit for h in g.hands for c in h if c.rank == 1})


def run_batch(kind: str, players: int, games: int, seed: int = 0,
              log: Path | None = None, log_views: bool = False,
              min_opening_plays: int = 0) -> BatchSummary:
    """Play `games` games. With `min_opening_plays`, a deal with fewer distinct
    opening plays is restarted, as our table does (the next seed tried is
    +100000, so results stay reproducible)."""
    v = make_variant(kind, players)
    results, restarts = [], 0
    for i in range(games):
        s = seed + i
        while min_opening_plays and opening_plays(v, s) < min_opening_plays:
            s += 100000
            restarts += 1
        results.append(play_game(v, s, recorder_path=log, log_views=log_views))
    out = BatchSummary(kind, players, results)
    out.restarts = restarts
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hanabi_meta.selfplay",
                                 description="Meta agents play full games")
    ap.add_argument("--variant", choices=VARIANT_KINDS + ("all",), default="regular")
    ap.add_argument("--players", type=int, nargs="+", default=[3])
    ap.add_argument("--games", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--log", type=Path, help="append games to this JSONL file")
    ap.add_argument("--min-opening-plays", type=int, default=0,
                    help="restart deals with fewer distinct playable 1s dealt")
    ap.add_argument("--views", action="store_true",
                    help="log every seat's view before each turn (bigger logs)")
    args = ap.parse_args(argv)
    kinds = VARIANT_KINDS if args.variant == "all" else (args.variant,)
    for kind in kinds:
        for n in args.players:
            t0 = time.perf_counter()
            s = run_batch(kind, n, args.games, args.seed, args.log, args.views,
                          args.min_opening_plays)
            print(s.text())
            print(f"  ({time.perf_counter() - t0:.1f}s)\n")
    return 0

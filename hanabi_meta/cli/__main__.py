"""Command-line advisor.

    python -m hanabi_meta.cli                  # start an empty game interactively
    python -m hanabi_meta.cli game.txt         # load a game file, then interactive
    python -m hanabi_meta.cli game.txt --advise  # print the advice and exit

Playing? Use `me N` in the game file. Watching from outside the game and seeing
every hand? Use `spectator` instead (cli/spectator.py): then each turn shows,
and logs, the acting player's view and the advice for them.

Interactive commands: any game-file line (see game_file.py), plus
    advise [all]   ranked suggestions ("all" also lists rejected hints)
    show           the table and what I know about my hand
    undo           drop the last action
    save PATH      write the game file
    log PATH       append this game to a JSONL log (docs/LOG_FORMAT.md)
    help, quit
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..advisor import advise
from ..belief.tracker import SlotView
from ..conventions.meta_state import MetaState
from ..engine.actions import PlayEvent
from ..engine.variant import Card, Variant
from . import game_file
from .game_file import GameFile, GameFileError

HELP = f"{__doc__}\n{game_file.__doc__}"


def _slot_text(v: Variant, sv: SlotView, actual: Card | None = None) -> str:
    cards = sorted(v.card_str(c) for c in sv.candidates)
    body = "/".join(cards) if len(cards) <= 6 else f"unknown ({len(cards)} options)"
    flags = []
    if sv.certainly_playable:
        flags.append("PLAYABLE")
    elif sv.p_playable:
        flags.append(f"play {sv.p_playable:.0%}")
    if sv.certainly_trash:
        flags.append("TRASH")
    elif sv.p_critical:
        flags.append(f"critical {sv.p_critical:.0%}")
    if sv.touched:
        flags.append("hinted")
    real = f"{v.card_str(actual)} = " if actual is not None else ""
    return f"[{sv.slot + 1}] {real}{body}" + (f"  ({', '.join(flags)})" if flags else "")


def render(ms: MetaState, actual: list[Card] | None = None) -> str:
    """The table from `ms`'s seat. `actual`: that seat's real cards (spectator mode)."""
    bs, v = ms.bs, ms.variant
    me = bs.observer
    who = f"p{me} to act" if actual is not None else f"I am p{me}"
    lines = [f"{v.name}, {v.num_players} players, {who} | "
             f"hints {bs.hints}/{v.max_hints} | strikes {bs.strikes}/{v.max_strikes} | "
             f"deck {bs.deck_size}"]
    stacks = " ".join(f"{s.letter}{h}" for s, h in zip(v.suits, bs.stacks))
    disc = " ".join(sorted(v.card_str(c) for c in bs.discards.elements())) or "-"
    lines += [f"stacks: {stacks}    discards: {disc}"]
    for p in range(v.num_players):
        if p == me:
            continue
        cards = [v.card_str(c) + ("*" if s.touched else "")
                 for c, s in zip(bs.hands[p], bs.public.hands[p])]
        lines.append(f"p{p}: {' '.join(cards)}")
    lines.append("my hand (oldest -> newest):" if actual is None
                 else f"p{me}'s hand (real card = what p{me} knows):")
    views = ms.view(me)
    real = actual if actual is not None else [None] * len(views)
    lines += ["  " + _slot_text(v, sv, c) for sv, c in zip(views, real)]
    conv = ms.explain()
    if conv:
        lines.append(f"conventions (as p{me} reads them):" if actual is not None
                     else "conventions:")
        lines += ["  " + c for c in conv]
    return "\n".join(lines)


def render_spectator(sg) -> str:
    game = sg.table.game
    if game.is_over:
        return f"game over: score {game.score}, strikes {game.strikes}, {game.turn} turns"
    p = game.current
    return render(sg.table.seats[p], actual=game.hands[p])


def render_advice(ms: MetaState, show_rejected: bool = False, top: int = 5) -> str:
    recs = advise(ms, include_rejected=show_rejected)
    shown = [r for r in recs if not r.rejected][:top] + \
        ([r for r in recs if r.rejected] if show_rejected else [])
    if not shown:
        return "no legal suggestion"
    out = ["advice:"]
    for i, r in enumerate(shown, 1):
        tag = "REJECTED" if r.rejected else f"{r.score:5.1f}"
        out.append(f" {i}. {r.summary:<22} [{tag}]")
        out += [f"      - {x}" for x in r.reasons]
    return "\n".join(out)


class _View:
    """What the REPL shows, in either mode."""

    def __init__(self, gf: GameFile) -> None:
        self.spectator = gf.spectator
        self.obj = gf.build_spectator() if self.spectator else gf.build()

    def render(self) -> str:
        return render_spectator(self.obj) if self.spectator else render(self.obj.ms)

    def advice(self, show_rejected: bool) -> str:
        if self.spectator:
            game = self.obj.table.game
            if game.is_over:
                return "game over"
            return f"advice for p{game.current}:\n" + render_advice(
                self.obj.table.seats[game.current], show_rejected)
        return render_advice(self.obj.ms, show_rejected)

    def last_note(self, cmd: str) -> str:
        if self.spectator:
            return self.obj.notes[-1] if self.obj.notes else ""
        t = self.obj
        if cmd == "hint" and t.ms.interpretations:
            return t.ms.explain()[-1 - len(t.ms.interpretations[-1].expectations)].strip()
        if cmd == "play":
            last_play = next(e for e in reversed(t.bs.history) if isinstance(e, PlayEvent))
            if not last_play.success:
                return "misplay: strike"
        return ""


def repl(gf: GameFile, path: Path | None) -> None:
    t: _View | None = None

    def rebuild() -> _View | None:
        try:
            return _View(gf)
        except (GameFileError, ValueError) as e:
            print(f"  (not ready: {e})")
            return None

    if gf.header:
        t = rebuild()
        if t:
            print(t.render())
    print("type 'help' for commands")
    while True:
        try:
            line = input("> ").split("#", 1)[0].strip()
        except EOFError:
            return
        if not line:
            continue
        cmd = line.split()[0].lower()
        if cmd in ("quit", "exit"):
            return
        if cmd == "help":
            print(HELP)
        elif cmd == "show":
            t = rebuild()
            if t:
                print(t.render())
        elif cmd == "advise":
            t = rebuild()
            if t:
                print(t.advice(show_rejected="all" in line))
        elif cmd == "undo":
            if gf.actions:
                print(f"  undid: {gf.actions.pop()}")
            elif gf.header:
                print(f"  undid: {gf.header.pop()}")
        elif cmd == "log":
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                print("  usage: log PATH")
                continue
            try:
                gf.to_log().append_to(Path(parts[1]))
                print(f"  appended to {parts[1]}")
            except (GameFileError, ValueError) as e:
                print(f"  {e}")
        elif cmd == "save":
            parts = line.split(maxsplit=1)
            target = Path(parts[1]) if len(parts) > 1 else path
            if not target:
                print("  usage: save PATH")
                continue
            target.write_text(gf.text(), encoding="utf-8")
            print(f"  saved to {target}")
        else:
            try:
                gf.add(line)
            except GameFileError as e:
                print(f"  {e}")
                continue
            if cmd not in ("hint", "play", "discard"):
                continue  # header lines are checked when the first action arrives
            new = rebuild()
            if new is None:
                print(f"  rejected, undoing: {gf.actions.pop()}")
                continue
            t = new
            print(f"  ok. {t.last_note(cmd)}".rstrip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hanabi_meta.cli",
                                 description="Hanabi advisor for our Meta")
    ap.add_argument("game", nargs="?", type=Path, help="game file to load")
    ap.add_argument("--advise", action="store_true", help="print advice and exit")
    ap.add_argument("--all", action="store_true", help="also list rejected hints")
    args = ap.parse_args(argv)
    gf = GameFile.parse(args.game.read_text(encoding="utf-8")) if args.game else GameFile()
    if args.advise:
        try:
            t = _View(gf)
        except GameFileError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(t.render())
        print()
        print(t.advice(show_rejected=args.all))
        return 0
    repl(gf, args.game)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

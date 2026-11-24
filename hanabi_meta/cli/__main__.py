"""Command-line advisor.

    python -m hanabi_meta.cli                  # start an empty game interactively
    python -m hanabi_meta.cli game.txt         # load a game file, then interactive
    python -m hanabi_meta.cli game.txt --advise  # print the advice and exit

Interactive commands: any game-file line (see game_file.py), plus
    advise [all]   ranked suggestions ("all" also lists rejected hints)
    show           the table and what I know about my hand
    undo           drop the last action
    save PATH      write the game file
    help, quit
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..advisor import advise
from ..belief.tracker import SlotView
from ..engine.actions import PlayEvent
from ..scenario import Scenario
from . import game_file
from .game_file import GameFile, GameFileError

HELP = f"{__doc__}\n{game_file.__doc__}"


def _slot_text(t: Scenario, sv: SlotView) -> str:
    v = t.variant
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
    return f"[{sv.slot + 1}] {body}" + (f"  ({', '.join(flags)})" if flags else "")


def render(t: Scenario) -> str:
    bs, v = t.bs, t.variant
    lines = [f"{v.name}, {v.num_players} players, I am p{bs.observer} | "
             f"hints {bs.hints}/{v.max_hints} | strikes {bs.strikes}/{v.max_strikes} | "
             f"deck {bs.deck_size}"]
    stacks = " ".join(f"{s.letter}{h}" for s, h in zip(v.suits, bs.stacks))
    disc = " ".join(sorted(v.card_str(c) for c in bs.discards.elements())) or "-"
    lines += [f"stacks: {stacks}    discards: {disc}"]
    for p in range(v.num_players):
        if p == bs.observer:
            continue
        cards = [v.card_str(c) + ("*" if s.touched else "")
                 for c, s in zip(bs.hands[p], bs.public.hands[p])]
        lines.append(f"p{p}: {' '.join(cards)}")
    lines.append("my hand (oldest -> newest):")
    lines += ["  " + _slot_text(t, sv) for sv in t.ms.view(bs.observer)]
    conv = t.ms.explain()
    if conv:
        lines.append("conventions:")
        lines += ["  " + c for c in conv]
    return "\n".join(lines)


def render_advice(t: Scenario, show_rejected: bool = False, top: int = 5) -> str:
    recs = advise(t.ms, include_rejected=show_rejected)
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


def repl(gf: GameFile, path: Path | None) -> None:
    t: Scenario | None = None

    def rebuild() -> Scenario | None:
        try:
            return gf.build()
        except (GameFileError, ValueError) as e:
            print(f"  (not ready: {e})")
            return None

    if gf.header:
        t = rebuild()
        if t:
            print(render(t))
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
                print(render(t))
        elif cmd == "advise":
            t = rebuild()
            if t:
                print(render_advice(t, show_rejected="all" in line))
        elif cmd == "undo":
            if gf.actions:
                print(f"  undid: {gf.actions.pop()}")
            elif gf.header:
                print(f"  undid: {gf.header.pop()}")
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
            note = ""
            if cmd == "hint" and t.ms.interpretations:
                note = t.ms.explain()[-1 - len(t.ms.interpretations[-1].expectations)].strip()
            elif cmd == "play":
                last_play = next(e for e in reversed(t.bs.history) if isinstance(e, PlayEvent))
                if not last_play.success:
                    note = "misplay: strike"
            print(f"  ok. {note}".rstrip())


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
            t = gf.build()
        except GameFileError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(render(t))
        print()
        print(render_advice(t, show_rejected=args.all))
        return 0
    repl(gf, args.game)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

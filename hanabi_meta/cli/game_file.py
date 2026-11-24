"""The game-file format: a table snapshot plus an action log, one command per line.

It is what you type into the CLI, line by line, and what `save` writes, so a
saved game can be reloaded, shared, or turned into a test case.

    variant regular          # regular | rainbow | rainbow_all_colors | short_rainbow
    players 4
    me 0                     # which player you are (default 0)
    stacks Y1                # optional: stack heights, omitted suits are 0
    discards B2 R1           # optional
    hints 7                  # optional (default 8)
    strikes 0                # optional
    hand 1 R4 B4 W3 Y3       # every other player's hand, oldest -> newest
    hand 2 G4 B3 R3 W4
    hand 3 G3 W5 B5 Y2

    hint 2 1 yellow          # giver target value
    hint 1 me 3 @1,4         # hints to you: list the touched slots
    play 3 4 Y2 G1           # player slot card-played [card-drawn]
    discard me 1 G2          # your own draws are unknown, so none given

Slots are numbered 1..N from the oldest (left-most) card. Players are 0..N-1,
and "me" works as a player name. Anything after "#" is a comment.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..engine.variant import make_variant
from ..scenario import Scenario

HEADER_KEYS = {"variant", "players", "me", "stacks", "discards", "hints", "strikes", "hand"}
ACTION_KEYS = {"hint", "play", "discard"}


class GameFileError(ValueError):
    pass


@dataclass
class GameFile:
    header: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    @staticmethod
    def parse(text: str) -> "GameFile":
        gf = GameFile()
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            gf.add(line)
        return gf

    def add(self, line: str) -> None:
        key = line.split()[0].lower()
        if key in HEADER_KEYS:
            if self.actions:
                raise GameFileError(f"'{key}' must come before the first action")
            self.header.append(line)
        elif key in ACTION_KEYS:
            self.actions.append(line)
        else:
            raise GameFileError(f"unknown command {key!r}")

    def text(self) -> str:
        return "\n".join(self.header + [""] + self.actions) + "\n"

    def build(self) -> Scenario:
        """Create the Scenario and replay every action."""
        return self._build(None)

    def to_log(self, players: list[str] | None = None):
        """A GameRecorder holding this live game, from my point of view.

        Each turn records the action, its events, my view before acting, and,
        on my own turns, what the advisor suggested (so later we can compare
        what we actually did with the advice, which is imitation-learning data).
        """
        from ..gamelog import GameRecorder
        holder: dict = {}
        self._build(holder, players)
        return holder["rec"]

    def _build(self, log: dict | None, players: list[str] | None = None) -> Scenario:
        opts: dict[str, str] = {}
        hands: dict[int, str] = {}
        for line in self.header:
            key, _, rest = line.partition(" ")
            key = key.lower()
            if key == "hand":
                who, _, cards = rest.strip().partition(" ")
                hands[self._player(who, opts)] = cards.strip()
            else:
                opts[key] = rest.strip()
        try:
            n = int(opts["players"])
        except KeyError:
            raise GameFileError("missing 'players N'") from None
        me = int(opts.get("me", "0"))
        rows = []
        for p in range(n):
            if p == me:
                rows.append(hands.get(p, ""))
            elif p not in hands:
                raise GameFileError(f"missing 'hand {p} ...'")
            else:
                rows.append(hands[p])
        if not rows[me]:
            hand_size = make_variant(opts.get("variant", "regular"), n).hand_size
            rows[me] = " ".join(["?"] * hand_size)
        t = Scenario(opts.get("variant", "regular"), hands=rows, observer=me,
                     stacks=opts.get("stacks", ""), discards=opts.get("discards", ""),
                     hints=int(opts["hints"]) if "hints" in opts else None,
                     strikes=int(opts.get("strikes", "0")))
        rec = None
        if log is not None:
            from ..advisor import advise
            from ..gamelog import GameRecorder, view_to_json
            rec = GameRecorder(t.variant, "live", observer=me, players=players,
                               meta={"snapshot": list(self.header)})
            log["rec"] = rec
        for i, line in enumerate(self.actions, 1):
            try:
                if rec is not None:
                    actor = self._player(line.split()[1], opts)
                    before = len(t.bs.history)
                    view = view_to_json(t.bs, t.ms.constraints())
                    advice = None
                    if actor == me:
                        advice = [{"summary": r.summary, "action": r.action.to_dict(),
                                   "score": round(r.score, 2)} for r in advise(t.ms)[:3]]
                self._apply(t, line, opts)
                if rec is not None:
                    rec.turn(i - 1, actor, None, t.bs.history[before:],
                             views={me: view}, advice=advice, note=line)
            except (ValueError, IndexError) as e:
                raise GameFileError(f"action {i} '{line}': {e}") from e
        if rec is not None:
            rec.end(sum(t.bs.stacks), t.bs.strikes, len(self.actions), finished=False)
        return t

    @staticmethod
    def _player(token: str, opts: dict[str, str]) -> int:
        if token.lower() == "me":
            return int(opts.get("me", "0"))
        return int(token.lower().lstrip("p"))

    def _apply(self, t: Scenario, line: str, opts: dict[str, str]) -> None:
        parts = line.split()
        key = parts[0].lower()
        if key == "hint":
            if len(parts) < 4:
                raise GameFileError("usage: hint GIVER TARGET VALUE [@slots]")
            giver, target = self._player(parts[1], opts), self._player(parts[2], opts)
            touched = None
            if len(parts) > 4 and parts[4].startswith("@"):
                touched = [int(x) - 1 for x in parts[4][1:].split(",") if x]
            t.hint(giver, target, parts[3], touched=touched)
        else:
            if len(parts) < 4:
                raise GameFileError(f"usage: {key} PLAYER SLOT CARD [DRAWN]")
            player, slot, card = self._player(parts[1], opts), int(parts[2]) - 1, parts[3]
            drawn = parts[4] if len(parts) > 4 else None
            if not 0 <= slot < len(t.bs.hands[player]):
                raise GameFileError(f"player {player} has no slot {slot + 1}")
            getattr(t, key)(player, slot, card, draw=drawn)

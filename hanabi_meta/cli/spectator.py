"""Spectator mode: an outside observer who sees every hand logs the real game.

The game file starts with `spectator` instead of `me`, lists every player's
hand, and gives the drawn card on every play and discard. It must start from
the deal (no stacks/discards/hints/strikes lines) and player 0 is the one who
takes the first turn:

    variant regular
    players 3
    spectator
    hand 0 R1 B2 G3 W4 Y5      # every hand, oldest -> newest, as dealt
    hand 1 ...
    hand 2 ...

    hint 0 1 red               # no @slots needed: touched cards are worked out
    play 1 2 R1 G4             # the drawn card is always given (until the deck runs out)

Because every card is known, the whole game runs through the engine, which
checks each line (turn order, legality, that the card named is really in that
slot). One point of view is kept per seat, so every turn logs what the acting
player could see, what the advisor would do in their place, and what they did.
The deck order is known up to the last draw, so spectator logs can be replayed.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..advisor import advise
from ..engine.actions import Action, ActionType, HintEvent, PlayEvent
from ..engine.game import IllegalAction
from ..engine.variant import Card, Variant, make_variant
from ..table import Table
from .game_file import GameFileError

SNAPSHOT_KEYS = {"stacks", "discards", "hints", "strikes", "me"}


class SpectatorError(GameFileError):
    pass


@dataclass
class SpectatorGame:
    table: Table
    #: One line per action: how the hint receiver read a hint, misplays, etc.
    notes: list[str] = field(default_factory=list)

    @property
    def variant(self) -> Variant:
        return self.table.variant


def _player(token: str, n: int) -> int:
    try:
        p = int(token.lower().lstrip("p"))
    except ValueError:
        raise SpectatorError(f"bad player {token!r} (spectator mode has no 'me')") from None
    if not 0 <= p < n:
        raise SpectatorError(f"no player {p}")
    return p


def build(header: list[str], actions: list[str], log: dict | None = None,
          players: list[str] | None = None) -> SpectatorGame:
    opts: dict[str, str] = {}
    hand_lines: dict[int, str] = {}
    for line in header:
        key, _, rest = line.partition(" ")
        key = key.lower()
        if key in SNAPSHOT_KEYS:
            raise SpectatorError(f"'{key}' can't be used in spectator mode: start from the deal")
        if key == "hand":
            who, _, cards = rest.strip().partition(" ")
            hand_lines[int(who.lower().lstrip("p"))] = cards.strip()
        elif key != "spectator":
            opts[key] = rest.strip()
    try:
        n = int(opts["players"])
    except KeyError:
        raise SpectatorError("missing 'players N'") from None
    v = make_variant(opts.get("variant", "regular"), n)

    hands: list[list[Card]] = []
    for p in range(n):
        if p not in hand_lines:
            raise SpectatorError(f"missing 'hand {p} ...'")
        cards = [v.parse_card(t) for t in hand_lines[p].split()]
        if len(cards) != v.hand_size:
            raise SpectatorError(f"hand {p} has {len(cards)} cards; deal is {v.hand_size}")
        hands.append(cards)

    # Deck order: the deal, then each drawn card in order, then the rest (unknown).
    drawn: list[Card | None] = []
    for line in actions:
        parts = line.split()
        if parts[0].lower() in ("play", "discard"):
            drawn.append(v.parse_card(parts[4]) if len(parts) > 4 else None)
    known = [c for h in hands for c in h] + [c for c in drawn if c is not None]
    rest = Counter(v.deck())
    rest.subtract(known)
    over = sorted(v.card_str(c) for c, k in rest.items() if k < 0)
    if over:
        raise SpectatorError(f"more copies than exist of: {', '.join(over)}")
    deck = known + sorted(rest.elements())

    table = Table(v, deck=deck)
    game = table.game
    sg = SpectatorGame(table)
    rec = None
    if log is not None:
        from ..gamelog import GameRecorder
        rec = GameRecorder(v, "spectator", deck=[v.card_str(c) for c in deck],
                           players=players,
                           meta={"snapshot": list(header), "deck_known": len(known)})
        rec.deal(game.deal_events)
        log["rec"] = rec

    for i, line in enumerate(actions, 1):
        try:
            sg.notes.append(_step(sg, line, rec))
        except (ValueError, IndexError) as e:  # IllegalAction is a ValueError
            raise SpectatorError(f"action {i} '{line}': {e}") from e
    if rec is not None:
        rec.end(game.score, game.strikes, game.turn, finished=game.is_over)
    return sg


def _step(sg: SpectatorGame, line: str, rec) -> str:
    table, game, v = sg.table, sg.table.game, sg.variant
    n = v.num_players
    parts = line.split()
    key = parts[0].lower()
    if game.is_over:
        raise SpectatorError("the game is already over")
    if len(parts) < 4:
        raise SpectatorError("usage: hint GIVER TARGET VALUE  |  "
                             f"{key} PLAYER SLOT CARD [DRAWN]")
    actor = _player(parts[1], n)
    if actor != game.current:
        raise SpectatorError(f"it's p{game.current}'s turn, not p{actor} "
                             "(a turn missing or out of order?)")
    drawn: Card | None = None
    if key == "hint":
        target = _player(parts[2], n)
        value = parts[3]
        action = (Action.hint_rank(target, int(value)) if value.isdigit()
                  else Action.hint_color(target, v.color_index(value)))
        if action.type is ActionType.HINT_COLOR and action.value not in v.hint_colors:
            raise SpectatorError(f"{v.suits[action.value].name} cannot be hinted in "
                                 f"{v.name}: use a color it is touched by")
        if len(parts) > 4 and parts[4].startswith("@"):
            said = tuple(int(x) - 1 for x in parts[4][1:].split(",") if x)
            got = game.hint_touches(target, action.hint_kind, action.value)
            if said != got:
                raise SpectatorError(f"that hint touches slots "
                                     f"{','.join(str(s + 1) for s in got) or 'none'}")
    else:
        slot = int(parts[2]) - 1
        card = v.parse_card(parts[3])
        hand = game.hands[actor]
        if not 0 <= slot < len(hand):
            raise SpectatorError(f"p{actor} has no slot {slot + 1}")
        if hand[slot] != card:
            raise SpectatorError(f"p{actor}'s slot {slot + 1} is {v.card_str(hand[slot])}, "
                                 f"not {v.card_str(card)}")
        if len(parts) > 4:
            drawn = v.parse_card(parts[4])
        if game.deck and drawn is None:
            raise SpectatorError(f"say what p{actor} drew ({len(game.deck)} cards left)")
        if not game.deck and drawn is not None:
            raise SpectatorError("the deck is empty: no card is drawn")
        action = Action.play(slot) if key == "play" else Action.discard(slot)

    reason = game.check_legal(action)
    if reason:
        raise IllegalAction(reason)
    turn = game.turn
    if rec is not None:
        views = table.views()
        recs = advise(table.seats[actor])
        followed = next((k for k, r in enumerate(recs) if r.action == action), None)
        advice = [{"summary": r.summary, "action": r.action.to_dict(),
                   "score": round(r.score, 2), "reasons": r.reasons} for r in recs[:3]]
    tr = table.step(action)
    if rec is not None:
        rec.turn(turn, actor, action, tr.events, views=views, advice=advice, note=line,
                 advice_rank=followed)

    for e in tr.events:
        if isinstance(e, HintEvent):
            interp = table.seats[e.target].interpretations[-1]
            return f"p{e.target} reads it as {interp.kind.value}: {interp.reason}"
        if isinstance(e, PlayEvent) and not e.success:
            return "misplay: strike"
    return ""

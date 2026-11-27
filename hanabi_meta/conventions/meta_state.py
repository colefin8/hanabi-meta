"""MetaState: a BeliefState plus the convention layer (layer 4).

It keeps every hint's Interpretation and every pending Expectation, and updates
them from what players did *and did not do* on their turns:

* The expected player plays the expected slot: FULFILLED (or FAILED on a miss).
* The expected player plays a different card their own info already said was
  playable: still pending ("play on the information you already have first").
* The expected player gives an urgent save (a hint read as a save or a 5
  safety hint) or makes a protective discard: the play is only delayed. That turn doesn't count as
  declining; the next turn they don't play it does.
* The expected player does anything else while the expected card is playable:
  they declined, so the next candidate is expected. When it reaches the
  observer, the observer's playable slot is narrowed to that card.
* Anyone successfully playing the expected card fulfils it.

`constraints()` turns pending expectations and interpretations into narrowing
of the observer's own slots, which `view()` applies.

Other conventions handled here:
* safety swap: after every 5 hint, MetaState itself reverses the un-hinted
  cards of everyone but the giver. A harness driving the engine must reorder the
  engine's hands too (Game.reorder) but must NOT also feed those ReorderEvents
  back in, or the swap would happen twice.
* playable 5: after the receiver of a dead color hint discards that card.
* protective discard: at 0 tokens with a known play, or at 1 token, flags the
  chop of the first player (up to 3 seats ahead) who'd have been forced to
  discard (`unsafe`). Unsafe = game-ending: the flagged card is treated as a last
  copy when choosing a discard (its identity isn't narrowed).
* duplicate signal (O4): a player discards a card they knew from their own info,
  while it is still needed. Another player's newest hinted card that could be
  that card is it, and they are expected to play it.

Teammate models (D18): with `models=True`, a MetaState also keeps, for every
teammate, a MetaState from that teammate's point of view (`models[p]`), fed the
same events. The giver uses it to read a hint the way each teammate will, with
everything they've inferred so far. It is exact except for the observer's own
hand, which the model can't see either: the teammate sees it, so the model is a
lower bound on what they know. A hint to the observer is read, in the models,
the way the observer read it (that is the reading everyone shares when the
giver follows the Meta), with the teammate's own cards turned back into
"maybe me" (they can't see them).
"""
from __future__ import annotations

import copy

from ..belief.bookkeeping import is_playable, is_trash, unseen_counts
from ..belief.tracker import BeliefState, SlotView
from ..engine.actions import (DiscardEvent, DrawEvent, Event, HintEvent, PlayEvent,
                              ReorderEvent)
from ..engine.variant import Card, Variant
from . import playable_five, protective_discard, safety_swap, skip_level, trash_hint
from .base import (Candidate, ExpStatus, Expectation, HintKind, Interpretation,
                   observer_line)


class MetaState:
    def __init__(self, bs: BeliefState, models: bool = False) -> None:
        self.bs = bs
        self.interpretations: list[Interpretation] = []
        #: The hint behind each interpretation (None for non-hint signals).
        self.hint_events: list[HintEvent | None] = []
        #: uids of cards known (by convention) to be game-ending to discard.
        self.unsafe: set[int] = set()
        self.notes: list[str] = []
        #: Safety-swap reorders caused by the last event (for engine harnesses).
        self.last_reorders: list[ReorderEvent] = []
        #: The last player to act, and every player's chop uid just before they
        #: acted (for chop_watched).
        self.last_actor: int | None = None
        self.chops_before_last: dict[int, int | None] = {}
        #: Teammate models (see module docstring), or None.
        self.models: dict[int, MetaState] | None = None
        if models:
            self.models = {p: MetaState(bs.model_for(p))
                           for p in range(bs.variant.num_players) if p != bs.observer}
            for m in self.models.values():
                m.unsafe = set(self.unsafe)

    @classmethod
    def new(cls, variant: Variant, observer: int, models: bool = False) -> "MetaState":
        return cls(BeliefState(variant, observer), models=models)

    def __deepcopy__(self, memo):
        """Copies leave the teammate models out: simulations don't need them, and
        copying n states per simulated action would be slow."""
        out = MetaState.__new__(MetaState)
        memo[id(self)] = out
        for k, val in self.__dict__.items():
            setattr(out, k, None if k == "models" else copy.deepcopy(val, memo))
        return out

    def chop_watched(self, player: int) -> bool:
        """D6/D21: `player`'s chop was already their chop when the previous
        player acted, and that player did nothing to protect it. Under the Meta
        protecting a last copy on someone's chop is the teammates' job (a
        protective discard, or a save as a last resort), so the chop is
        presumed safe to discard."""
        uid = protective_discard.chop_uid(self.bs, player, self.unsafe)
        return (uid is not None and self.last_actor is not None
                and self.last_actor != player
                and self.chops_before_last.get(player) == uid)

    def model(self, player: int) -> "MetaState | None":
        """A fresh copy of `player`'s model, to simulate on (None without models)."""
        if not self.models or player not in self.models:
            return None
        return copy.deepcopy(self.models[player])

    @property
    def variant(self) -> Variant:
        return self.bs.variant

    @property
    def observer(self) -> int:
        return self.bs.observer

    @property
    def expectations(self) -> list[Expectation]:
        return [e for i in self.interpretations for e in i.expectations]

    def pending(self) -> list[Expectation]:
        return [e for e in self.expectations if e.status is ExpStatus.PENDING]

    # ---- events ------------------------------------------------------------------
    def apply(self, event: Event, reading: Interpretation | None = None) -> None:
        """Apply one event. `reading`: for a hint to a player this state can't
        see (a model's builder), how that player read it."""
        self._apply(event, reading)
        if self.models:
            for p, m in self.models.items():
                ev, r = event, None
                if isinstance(event, DrawEvent) and event.player == p:
                    ev = DrawEvent(p, None)
                elif isinstance(event, HintEvent) and event.target == self.observer:
                    r = _shared_reading(self.interpretations[-1], m)
                m.apply(ev, r)

    def _apply(self, event: Event, reading: Interpretation | None) -> None:
        bs = self.bs
        self.last_reorders = []
        if isinstance(event, (HintEvent, PlayEvent, DiscardEvent)):
            # Every chop as the actor saw it before acting (see chop_watched).
            self.last_actor = event.giver if isinstance(event, HintEvent) else event.player
            self.chops_before_last = {
                p: protective_discard.chop_uid(bs, p, self.unsafe)
                for p in range(self.variant.num_players)}
        if isinstance(event, HintEvent):
            stacks_before = list(bs.stacks)
            bs.apply(event)
            idx = len(self.interpretations)
            interp = None
            if reading is not None:
                interp = reading
                interp.hint_index = idx
                for e in interp.expectations:
                    e.source_hint = idx
            elif not (event.kind == "rank" and event.value == 5):  # every 5 hint = safety
                interp = trash_hint.interpret_hint(bs, event, idx)
            interp = interp or skip_level.interpret_hint(bs, event, idx)
            urgent = interp.kind in (HintKind.SAVE, HintKind.SAFETY_FIVE)
            self._actor_did_not_play(event.giver, stacks_before, excuse=urgent)
            self.interpretations.append(interp)
            self.hint_events.append(event)
            if safety_swap.is_safety_hint(event):
                for r in safety_swap.reorders(bs, event):
                    bs.apply(r)
                    self.last_reorders.append(r)
                interp.reason += (f"; everyone but p{event.giver} reversed their "
                                  f"un-hinted cards")
        elif isinstance(event, (PlayEvent, DiscardEvent)):
            uid = bs.public.hands[event.player][event.slot].uid
            # "Known" = their own info says playable, or a convention told them to
            # play this exact card (e.g. a plain play hint).
            was_known_playable = self._knew_playable(event.player, event.slot, uid)
            stacks_before = list(bs.stacks)
            hints_before = bs.hints
            knew = self.view(event.player)[event.slot].known
            had_play = self._has_known_play(event.player, skip=uid)
            bs.apply(event)
            if isinstance(event, PlayEvent):
                self._on_play(event, uid, was_known_playable, stacks_before)
            else:
                # A protective discard (D15) is a sensible reason to put off an
                # expected play, like an urgent save: not a decline.
                protective = protective_discard.is_protective(bs, event, hints_before,
                                                              had_play)
                self._actor_did_not_play(event.player, stacks_before, excuse=protective,
                                         why="made a protective discard")
                self._on_discard(event, uid, hints_before, knew, had_play)
        elif isinstance(event, (DrawEvent, ReorderEvent)):
            bs.apply(event)
        else:
            raise TypeError(event)
        if self.unsafe:
            protective_discard.prune(self, self.unsafe)
        self._settle()

    def apply_all(self, events: list[Event]) -> "MetaState":
        for e in events:
            self.apply(e)
        return self

    def _on_play(self, ev: PlayEvent, uid: int, was_known: bool,
                 stacks_before: list[int]) -> None:
        self._advance_chains(uid, ev.success)
        for e in self.pending():
            cand = e.expected
            if cand and cand.player == ev.player and cand.uid == uid:
                ok = ev.success and ev.card in e.options()
                e.status = ExpStatus.FULFILLED if ok else ExpStatus.FAILED
                e.log.append(f"player {ev.player} played {self.variant.card_str(ev.card)}")
                if ok and e.self_hint:
                    interp = self.interpretations[e.source_hint]
                    interp.expectations += skip_level.continue_self_shotgun(
                        self.bs, interp, e, ev.card)
            elif ev.success and e.card == ev.card:
                e.status = ExpStatus.FULFILLED
                e.log.append(f"{self.variant.card_str(ev.card)} played by player {ev.player}")
            elif cand and cand.player == ev.player:
                if was_known:
                    e.log.append(f"player {ev.player} played known card first; still pending")
                else:
                    self._decline(e, ev.player, stacks_before)

    def _on_discard(self, ev: DiscardEvent, uid: int, hints_before: int,
                    knew=None, had_play: bool = False) -> None:
        self._advance_chains(uid, False)
        self.unsafe.discard(uid)
        if knew == ev.card:
            self._duplicate_signal(ev)
        interp = playable_five.on_discard(self.bs, self.interpretations, self.hint_events,
                                          ev, uid, len(self.interpretations))
        if interp:
            self.interpretations.append(interp)
            self.hint_events.append(None)
        if protective_discard.is_protective(self.bs, ev, hints_before, had_play):
            flagged = protective_discard.flag(self, ev, self.unsafe)
            if flagged is not None:
                p, uid = flagged
                slot = next(i for i, s in enumerate(self.bs.public.hands[p])
                            if s.uid == uid)
                self.notes.append(f"protective discard by p{ev.player}: p{p}'s slot "
                                  f"{slot + 1} is unsafe to discard")

    def _advance_chains(self, uid: int, played: bool) -> None:
        """A chain card (D19) left my hand.

        After a successful play, the next touched card is read right away, on
        the board as it is now: playable now, or waiting on an unlock a
        teammate visibly holds. That reading is fixed; if nothing it could be
        has somewhere to go now, the chain ends (a later play elsewhere doesn't
        revive it). A miss or a discard also ends it.
        """
        for i in self.interpretations:
            if uid not in i.chain:
                continue
            if not played or i.target != self.observer:
                i.chain = []
                continue
            mine = {sl.uid for sl in self.bs.public.hands[self.observer]}
            rest = [u for u in i.chain[i.chain.index(uid) + 1:] if u in mine]
            i.chain = []
            if not rest:
                continue
            sv = next(x for x in self.view(self.observer) if x.uid == rest[0])
            opts = skip_level.chain_options(self.bs, sv.candidates, i.giver)
            if opts:
                i.constraints[rest[0]] = opts
                i.chain = rest

    def _knew_playable(self, player: int, slot: int, uid: int) -> bool:
        """Did `player` know this card was playable before playing it: by their
        hint info, by a convention narrowing (their model, or my own view of my
        hand), as the focus of a play hint to them, or as an expected play?
        A known play is never a decline of another expected card (D2)."""
        if self.view(player)[slot].certainly_playable:
            return True
        if self.models and player in self.models and                 self.models[player].view(player)[slot].certainly_playable:
            return True
        if any(i.kind is HintKind.PLAY and i.target == player and uid in i.focus
               for i in self.interpretations):
            return True
        return any(e.expected and e.expected.player == player and e.expected.uid == uid
                   for e in self.pending())

    def _has_known_play(self, player: int, skip: int | None = None) -> bool:
        """Does `player` know of a card they could play (by info or convention)?"""
        expected = {e.expected.uid for e in self.expected_of(player)
                    if e.expected and e.expected.uid is not None
                    and (e.card is None or is_playable(e.card, self.bs.stacks))}
        return any((sv.certainly_playable or sv.uid in expected) and sv.uid != skip
                   for sv in self.view(player))

    def _duplicate_signal(self, ev: DiscardEvent) -> None:
        """O4: a known, still-needed card was discarded on purpose."""
        bs, v, card = self.bs, self.variant, ev.card
        if is_trash(v, card, bs.stacks, bs.discards):
            return
        n = v.num_players
        for k in range(1, n):
            q = (ev.player + k) % n
            views = self.view(q)
            slots = [i for i, s in enumerate(bs.public.hands[q])
                     if s.touched and card in views[i].candidates]
            if not slots:
                continue
            uid = bs.public.hands[q][slots[-1]].uid  # newest hinted candidate
            cand = Candidate(q, uid, "known")
            idx = len(self.interpretations)
            interp = Interpretation(
                hint_index=idx, giver=ev.player, target=q, kind=HintKind.DUPLICATE,
                focus=[uid],
                reason=f"p{ev.player} discarded their known {v.card_str(card)}: "
                       f"p{q}'s newest hinted card that could be it is the other copy")
            redirected = False
            for e in self.pending():
                if e.card == card:
                    e.candidates.insert(e.current, Candidate(q, uid, "known"))
                    e.log.append(f"duplicate signal: now p{q}'s hinted card")
                    redirected = True
            if not redirected:
                interp.expectations.append(Expectation(card, [cand], interp.reason, idx))
            if q == self.observer:
                interp.constraints[uid] = {card}
            self.interpretations.append(interp)
            self.hint_events.append(None)
            return

    def _actor_did_not_play(self, player: int, stacks: list[int] | None = None,
                            excuse: bool = False, why: str = "gave an urgent save") -> None:
        stacks = self.bs.stacks if stacks is None else stacks
        for e in self.pending():
            cand = e.expected
            if cand and cand.player == player:
                if excuse and (e.card is None or is_playable(e.card, stacks)):
                    e.excused += 1
                    e.log.append(f"player {player} {why}; play delayed")
                    continue
                self._decline(e, player, stacks)

    def _decline(self, e: Expectation, player: int, stacks: list[int]) -> None:
        # Not playing a card that isn't playable yet is not a decline.
        if e.card is not None and not is_playable(e.card, stacks):
            return
        e.current += 1
        e.log.append(f"player {player} did not play it")

    def _settle(self) -> None:
        """Close expectations already satisfied; resolve the observer's slots."""
        claimed: set[int] = set()
        for e in self.pending():
            if e.card is not None and self.bs.stacks[e.card.suit] >= e.card.rank:
                e.status = ExpStatus.FULFILLED
                continue
            cand = e.expected
            if cand is None:
                continue
            if cand.player == self.observer:
                if cand.uid is None:
                    cand.uid = self._observer_playable_slot(claimed, cand.line)
                    if cand.uid is not None:
                        e.log.append("now expected of me")
                if cand.uid is not None:
                    claimed.add(cand.uid)
            if cand.uid is not None and not any(
                    s.uid == cand.uid for s in self.bs.public.hands[cand.player]):
                e.current += 1  # the card left the hand some other way

    def _observer_playable_slot(self, claimed: set[int],
                                line: tuple[int, ...] | None = None) -> int | None:
        """Observer's newest untouched card not already claimed (shotgun line).

        With `line` (the untouched cards when the signal was given, newest
        first), only those cards count: a card drawn since then can't be the
        one the hinter meant.
        """
        hand = self.bs.public.hands[self.observer]
        if line is not None:
            free = {s.uid for s in hand if not s.touched}
            return next((u for u in line if u in free and u not in claimed), None)
        for s in reversed(hand):
            if not s.touched and s.uid not in claimed:
                return s.uid
        return None

    # ---- outputs -------------------------------------------------------------------
    def constraints(self) -> dict[int, set[Card]]:
        out: dict[int, set[Card]] = {}

        def add(uid: int, cards: set[Card]) -> None:
            out[uid] = out[uid] & cards if uid in out and out[uid] & cards else set(cards)

        for i in self.interpretations:
            for uid, cards in i.constraints.items():
                add(uid, cards)
        for e in self.pending():
            cand = e.expected
            if cand and cand.player == self.observer and cand.uid is not None:
                add(cand.uid, e.options())
        # A protective-discard flag ("discarding this ends the game") is NOT a
        # constraint on the card's identity: narrowing it to the critical cards
        # turned wrong flags into confident misplays. It only affects discards
        # (chop_index skips it; the last resort treats it as critical).
        return out

    def view(self, player: int) -> list[SlotView]:
        return self.bs.view(player, self.constraints() if player == self.observer else None)

    def expected_of(self, player: int) -> list[Expectation]:
        return [e for e in self.pending() if e.expected and e.expected.player == player]

    def explain(self) -> list[str]:
        cs = self.variant.card_str
        lines = []
        for i in self.interpretations:
            label = "signal" if i.kind.value in ("playable_five", "duplicate") else "hint"
            lines.append(f"{label} #{i.hint_index} (p{i.giver}->p{i.target}): "
                         f"{i.kind.value}: {i.reason}")
            for e in i.expectations:
                who = e.expected
                want = cs(e.card) if e.card else "/".join(sorted(cs(c) for c in e.possible))
                state = e.status.value if who is None or e.status is not ExpStatus.PENDING \
                    else f"expected of p{who.player} ({who.how})"
                lines.append(f"    {want}: {state}")
        lines += self.notes
        return lines


def _shared_reading(mine: Interpretation, model: MetaState) -> Interpretation:
    """My reading of a hint to me, as a teammate (`model`'s observer) holds it.

    They can see my cards and I can't, so my reading is the best guess of
    theirs. Narrowings of my own cards are dropped (they don't change how the
    teammate reads later hints), and candidates in the teammate's own hand
    (which I could see and they can't) become their "maybe me" fallback.
    """
    r = copy.deepcopy(mine)
    r.constraints = {}
    t, bs = model.observer, model.bs
    can_hold = unseen_counts(bs.variant, bs.seen_by(t))
    for e in r.expectations:
        if not any(c.player == t for c in e.candidates):
            continue
        cur = e.expected
        keep = [c for c in e.candidates if c.player != t]
        if any(can_hold[c] > 0 for c in e.options()):
            keep.append(Candidate(t, None, "inferred", line=observer_line(bs)))
        e.current = keep.index(cur) if cur in keep else min(e.current, len(keep) - 1)             if keep else 0
        e.candidates = keep
    return r

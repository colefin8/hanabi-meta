"""MetaState: a BeliefState plus the convention layer (layer 4).

It keeps every hint's Interpretation and every pending Expectation, and updates
them from what players did *and did not do* on their turns:

* The expected player plays the expected slot: FULFILLED (or FAILED on a miss).
* The expected player plays a different card their own info already said was
  playable: still pending ("play on the information you already have first").
* The expected player gives an urgent save (a hint read as a save or a 5
  safety hint): the play is only delayed. That turn doesn't count as
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
* protective discard: with 1 token left, flags the chop of the first player
  (up to 3 seats ahead) who'd have been forced to discard (`unsafe`).
* duplicate signal (O4): a player discards a card they knew from their own info,
  while it is still needed. Another player's newest hinted card that could be
  that card is it, and they are expected to play it.
"""
from __future__ import annotations

from ..belief.bookkeeping import is_playable, is_trash
from ..belief.tracker import BeliefState, SlotView
from ..engine.actions import (DiscardEvent, DrawEvent, Event, HintEvent, PlayEvent,
                              ReorderEvent)
from ..engine.variant import Card, Variant
from . import playable_five, protective_discard, safety_swap, skip_level, trash_hint
from .base import Candidate, ExpStatus, Expectation, HintKind, Interpretation


class MetaState:
    def __init__(self, bs: BeliefState) -> None:
        self.bs = bs
        self.interpretations: list[Interpretation] = []
        #: The hint behind each interpretation (None for non-hint signals).
        self.hint_events: list[HintEvent | None] = []
        #: uids of cards known (by convention) to be unsafe to discard.
        self.unsafe: set[int] = set()
        self.notes: list[str] = []
        #: Safety-swap reorders caused by the last event (for engine harnesses).
        self.last_reorders: list[ReorderEvent] = []

    @classmethod
    def new(cls, variant: Variant, observer: int) -> "MetaState":
        return cls(BeliefState(variant, observer))

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
    def apply(self, event: Event) -> None:
        bs = self.bs
        self.last_reorders = []
        if isinstance(event, HintEvent):
            stacks_before = list(bs.stacks)
            bs.apply(event)
            idx = len(self.interpretations)
            interp = None
            if not (event.kind == "rank" and event.value == 5):  # every 5 hint = safety
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
            was_known_playable = bs.view(event.player)[event.slot].certainly_playable or any(
                e.expected and e.expected.player == event.player and e.expected.uid == uid
                for e in self.pending())
            stacks_before = list(bs.stacks)
            hints_before = bs.hints
            knew = self.view(event.player)[event.slot].known
            bs.apply(event)
            if isinstance(event, PlayEvent):
                self._on_play(event, uid, was_known_playable, stacks_before)
            else:
                self._actor_did_not_play(event.player, stacks_before)
                self._on_discard(event, uid, hints_before, knew)
        elif isinstance(event, (DrawEvent, ReorderEvent)):
            bs.apply(event)
        else:
            raise TypeError(event)
        self._settle()

    def apply_all(self, events: list[Event]) -> "MetaState":
        for e in events:
            self.apply(e)
        return self

    def _on_play(self, ev: PlayEvent, uid: int, was_known: bool,
                 stacks_before: list[int]) -> None:
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
                    knew=None) -> None:
        self.unsafe.discard(uid)
        if knew == ev.card:
            self._duplicate_signal(ev)
        interp = playable_five.on_discard(self.bs, self.interpretations, self.hint_events,
                                          ev, uid, len(self.interpretations))
        if interp:
            self.interpretations.append(interp)
            self.hint_events.append(None)
        if protective_discard.is_protective(self.bs, ev, hints_before):
            flagged = protective_discard.flag(self, ev, self.unsafe)
            if flagged is not None:
                p, uid = flagged
                slot = next(i for i, s in enumerate(self.bs.public.hands[p])
                            if s.uid == uid)
                self.notes.append(f"protective discard by p{ev.player}: p{p}'s slot "
                                  f"{slot + 1} is unsafe to discard")

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
                            excuse: bool = False) -> None:
        stacks = self.bs.stacks if stacks is None else stacks
        for e in self.pending():
            cand = e.expected
            if cand and cand.player == player:
                if excuse and (e.card is None or is_playable(e.card, stacks)):
                    e.excused += 1
                    e.log.append(f"player {player} gave an urgent save; play delayed")
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

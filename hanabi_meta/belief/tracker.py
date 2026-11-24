"""Layer 3: the belief state of one observer, including theory-of-mind views.

`BeliefState` consumes the public event stream as seen by `observer` (the
person using the advisor). From it, it can answer two kinds of question:

* `view(observer)`: what the observer can deduce about their own hand, using
  everything they can see.
* `view(p)` for another player p: what p can deduce about p's own hand, as far
  as the observer can tell. p sees the observer's hand but the observer does
  not, so this is a LOWER BOUND on p's knowledge: it uses public info plus the
  hands that both p and the observer can see. (Layer 4, hypothesis
  enumeration, will refine this by trying each possible observer hand.)
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..engine.actions import DiscardEvent, DrawEvent, Event, HintEvent, PlayEvent
from ..engine.variant import Card, Variant
from .bookkeeping import is_critical, is_playable, is_trash, played_cards, unseen_counts
from .slots import PublicKnowledge


@dataclass
class SlotView:
    """One player's deduction about one slot of their own hand."""

    slot: int
    uid: int
    #: Candidate identities with their weight (number of unseen copies).
    weights: dict[Card, int]
    touched: bool
    p_playable: float
    p_trash: float
    p_critical: float

    @property
    def candidates(self) -> set[Card]:
        return set(self.weights)

    @property
    def known(self) -> Card | None:
        return next(iter(self.weights)) if len(self.weights) == 1 else None

    @property
    def certainly_playable(self) -> bool:
        return self.p_playable == 1.0

    @property
    def certainly_trash(self) -> bool:
        return self.p_trash == 1.0

    @property
    def maybe_critical(self) -> bool:
        return self.p_critical > 0.0

    def probability(self, card: Card) -> float:
        total = sum(self.weights.values())
        return self.weights.get(card, 0) / total if total else 0.0


class BeliefState:
    def __init__(self, variant: Variant, observer: int) -> None:
        self.variant = variant
        self.observer = observer
        self.public = PublicKnowledge(variant)
        n = variant.num_players
        #: Actual cards in each hand where the observer can see them, else None.
        self.hands: list[list[Card | None]] = [[] for _ in range(n)]
        self.stacks: list[int] = [0] * variant.num_suits
        self.discards: Counter[Card] = Counter()
        self.hints = variant.max_hints
        self.strikes = 0
        self.turn = 0
        self.deck_size = len(variant.deck())
        self.history: list[Event] = []

    @classmethod
    def from_snapshot(cls, variant: Variant, observer: int,
                      hands: list[list[Card | None]], stacks: list[int],
                      discards: list[Card] = (), hints: int | None = None,
                      strikes: int = 0, deck_size: int | None = None) -> "BeliefState":
        """Start mid-game from a table snapshot (for live use and test cases).

        Slot info starts empty: hints given before the snapshot are not known.
        The observer's own hand must be all None.
        """
        if any(c is not None for c in hands[observer]):
            raise ValueError("observer's own cards must be unknown (None)")
        bs = cls(variant, observer)
        bs.stacks = list(stacks)
        bs.discards = Counter(discards)
        bs.hints = variant.max_hints if hints is None else hints
        bs.strikes = strikes
        for p, hand in enumerate(hands):
            if p != observer and any(c is None for c in hand):
                raise ValueError(f"player {p}'s cards must all be given")
            for c in hand:
                bs.hands[p].append(c)
                bs.public.add_slot(p, 0)
        if deck_size is None:
            seen = played_cards(bs.stacks) + list(bs.discards.elements()) + \
                [c for h in hands for c in h if c is not None]
            deck_size = len(variant.deck()) - len(seen) - len(hands[observer])
        bs.deck_size = deck_size
        unseen_counts(variant, bs.seen_by(observer))  # raises if impossible
        return bs

    # ---- event application --------------------------------------------------
    def apply(self, event: Event) -> None:
        v = self.variant
        if isinstance(event, DrawEvent):
            if event.player != self.observer and event.card is None:
                raise ValueError("observer must be told the cards other players draw")
            self.hands[event.player].append(
                None if event.player == self.observer else event.card)
            self.public.add_slot(event.player, self.turn)
            self.deck_size -= 1
        elif isinstance(event, HintEvent):
            self.public.apply_hint(event)
            self.hints -= 1
            self.turn += 1
        elif isinstance(event, (PlayEvent, DiscardEvent)):
            self.hands[event.player].pop(event.slot)
            self.public.remove_slot(event.player, event.slot)
            if isinstance(event, PlayEvent) and event.success:
                self.stacks[event.card.suit] += 1
                if event.card.rank == 5 and v.five_returns_hint:
                    self.hints = min(self.hints + 1, v.max_hints)
            else:
                self.discards[event.card] += 1
                if isinstance(event, PlayEvent):
                    self.strikes += 1
                else:
                    self.hints = min(self.hints + 1, v.max_hints)
            self.turn += 1
        else:
            raise TypeError(f"unknown event {event!r}")
        self.history.append(event)

    def apply_all(self, events: list[Event]) -> "BeliefState":
        for e in events:
            self.apply(e)
        return self

    # ---- layer 1 -------------------------------------------------------------
    def common_seen(self) -> list[Card]:
        """Cards whose location everyone knows: the stacks and the discard pile."""
        return played_cards(self.stacks) + list(self.discards.elements())

    def seen_by(self, player: int) -> list[Card]:
        """Cards `player` can locate, restricted to what the observer also sees."""
        seen = self.common_seen()
        for q, hand in enumerate(self.hands):
            if q in (player, self.observer):
                continue
            seen += [c for c in hand if c is not None]
        return seen

    # ---- layer 3 -------------------------------------------------------------
    def view(self, player: int,
             constraints: dict[int, set[Card]] | None = None) -> list[SlotView]:
        """What `player` can deduce about each slot of their own hand.

        `constraints` maps a slot uid to the identities a convention says it can
        be (layer 4 inferences). A constraint that would leave no candidate is
        ignored, since the hard information wins over convention guesses.
        """
        v = self.variant
        unseen = unseen_counts(v, self.seen_by(player))
        slots = self.public.hands[player]
        cands = [{c for c in s.possible if unseen[c] > 0} for s in slots]
        for i, s in enumerate(slots):
            if constraints and s.uid in constraints:
                narrowed = cands[i] & constraints[s.uid]
                if narrowed:
                    cands[i] = narrowed
        # Known-card elimination: if k slots are each certainly card X and only
        # k copies of X are unseen, X cannot be anywhere else in this hand.
        # Repeat until nothing changes (each pass can create new known cards).
        changed = True
        while changed:
            changed = False
            known = Counter(next(iter(c)) for c in cands if len(c) == 1)
            for i, c in enumerate(cands):
                if len(c) == 1:
                    continue
                drop = {x for x in c if known[x] >= unseen[x]}
                if drop and drop != c:
                    cands[i] = c - drop
                    changed = True
        out = []
        for i, (s, c) in enumerate(zip(slots, cands)):
            known = Counter(next(iter(o)) for j, o in enumerate(cands) if j != i and len(o) == 1)
            weights = {x: unseen[x] - known[x] for x in c if unseen[x] - known[x] > 0} or \
                {x: 1 for x in c}
            total = sum(weights.values())

            def p(pred) -> float:
                return sum(w for x, w in weights.items() if pred(x)) / total if total else 0.0

            out.append(SlotView(
                slot=i, uid=s.uid, weights=weights, touched=s.touched,
                p_playable=p(lambda x: is_playable(x, self.stacks)),
                p_trash=p(lambda x: is_trash(v, x, self.stacks, self.discards)),
                p_critical=p(lambda x: is_critical(v, x, self.stacks, self.discards)),
            ))
        return out

    # ---- display -------------------------------------------------------------
    def describe_slot(self, sv: SlotView) -> str:
        cs = ",".join(sorted(self.variant.card_str(c) for c in sv.weights))
        flags = []
        if sv.certainly_playable:
            flags.append("PLAYABLE")
        elif sv.p_playable:
            flags.append(f"play {sv.p_playable:.0%}")
        if sv.certainly_trash:
            flags.append("TRASH")
        if sv.maybe_critical:
            flags.append(f"crit {sv.p_critical:.0%}")
        return f"[{sv.slot}] {cs} {' '.join(flags)}".rstrip()

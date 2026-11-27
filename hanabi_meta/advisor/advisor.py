"""Rank the observer's possible actions under the Meta, with reasons.

Scoring is deliberately simple and readable: every number comes from `Weights`,
and every score is built from named parts that end up in the explanation.

Plays     certain (by info or by a convention expectation) > risky (only above a
          probability threshold, and never on the last strike).

House rule: the game ends once a perfect game is impossible, so losing the last
copy of a needed card (by a discard or a misplay) costs `game_loss`, far more
than any points. A risky play is charged for the chance its miss is such a card.
Hints     each candidate hint is *simulated*: we apply it to a copy of the
          MetaState and read the Interpretation the conventions produce. A hint
          whose reading would be dead or unclear is rejected as misleading
          (docs/QUESTIONS.md D3c). Otherwise it is valued by what it achieves:
          new plays (only those the receiver can see), unlocks via skip-level,
          saves of a critical chop card, trash marking. Each hint is also read
          the way the receiver and bystanders will (their teammate models, D18);
          a harmful reading is charged a strike or the game, not rejected. A play/skip hint on a second copy of a card that is
          already hinted or expected elsewhere is rejected (it wastes a card or
          a strike). In the endgame, a skip-level whose unlock holder or target
          has no turn left is rejected: a direct hint is better.
Discards  the oldest untouched card (D6), penalised by the chance it is critical
          or playable; a card known to be trash is preferred.
Lookahead after each candidate action, the next few players are simulated
          with the simple Meta policy: play a card you know is playable (or are
          expected to play), else hint if a token exists, else discard your
          oldest untouched card. An action that leaves a teammate discarding a
          critical card, or playing a card that misses, is penalised (D9).
          Approximation: stacks are not advanced during the lookahead.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from ..belief.bookkeeping import is_critical, is_playable, is_trash
from ..conventions.base import HintKind
from ..conventions.meta_state import MetaState
from ..engine.actions import Action, ActionType, DrawEvent, HintEvent, PlayEvent
from ..engine.variant import Variant


@dataclass
class Weights:
    play_certain: float = 100
    play_five_bonus: float = 3          # a 5 also returns a hint token (official rules)
    risky_min_p: float = 0.6            # never suggest a blind play below this
    risky_scale: float = 50             # score = risky_scale * p(playable)
    save_chop: float = 110              # saving a critical card on someone's chop
    #: A chop save that can wait: the target has a known play (they won't
    #: discard next turn) and tokens remain for a later save. Below a play hint,
    #: so plays come first.
    save_can_wait: float = 40
    save_not_chop: float = 15
    play_hint_base: float = 50
    per_new_play: float = 25           # each play a hint produces (>2/hint wins games)
    skip_hint_base: float = 45
    trash_hint_per_card: float = 12
    safety_five_chop: float = 100
    safety_five_other: float = 5
    discard_base: float = 25
    discard_trash_bonus: float = 15
    discard_crit_penalty: float = 120
    discard_playable_penalty: float = 30
    discard_token_bonus: float = 10     # scaled by missing hint tokens
    last_token_penalty: float = 10      # spending the last hint token
    collateral_penalty: float = 1       # per touched card the hint isn't about
    info_only: float = 5                # re-hinting already-hinted cards
    info_tiebreak: float = 0.5          # per focus card, scaled by how much it narrows
    touched_unlock_penalty: float = 10  # an unlock expected from an already-hinted card
    duplicate_signal_discard: float = 102  # O4: discard my known copy (unblocks their run)
    protective_crit_bonus: float = 110  # a protective discard that saves a last copy
                                        # (beats a save hint; see D15)
    #: My discard would be read as protective (= "your chop is game-ending") but
    #: the card isn't a last copy: misleading, and it piles up flags.
    misleading_protective: float = 40
    #: A misleading hint (normally rejected, D3c) as a last resort when every
    #: other option scores below -game_loss/2 (likely loses the game). The
    #: lookahead still charges for any misplay the misreading would cause.
    misleading_hint_fallback: float = 150
    #: A reading of my hint (by the receiver or a bystander) that would cost a
    #: strike (D18). More than any hint is worth, so an unambiguous option always
    #: wins; an ambiguous hint still beats risking the game.
    misread_strike: float = 150
    #: D21: my chop sat there through the previous player's turn and they didn't
    #: protect it, so it's presumed safe. Only this share of its last-copy risk
    #: counts (the Meta's safety net is the teammates, not my own odds).
    watched_chop_risk: float = 0.25
    #: A harmless hint that achieves nothing: only chosen over options that
    #: risk the game (a blind play that could lose a last copy, a risky discard).
    stall_hint: float = -20
    #: A hinted card the receiver can't tell is playable: they hold it, so it
    #: isn't a play from this hint (only a small credit for marking it).
    unclear_play: float = 3
    lookahead_depth: int = 3            # how many following players to simulate
    lookahead_crit: float = 80          # a teammate would be forced to discard a critical
    lookahead_misplay: float = 50       # a teammate would play a card that misses
    #: A teammate with no known play and a last copy on chop, while tokens are
    #: left: they may discard instead of hinting (D21). Share of the loss charged.
    lookahead_may_discard: float = 0.5
    #: Losing the last copy of a needed card. With `end_when_perfect_lost` this
    #: ends the game, so it replaces the smaller crit penalties above.
    game_loss: float = 300


def _crit_cost(v: Variant, w: Weights, base: float) -> float:
    """Cost of losing a critical card: the game itself under the house rule."""
    return max(base, w.game_loss) if v.end_when_perfect_lost else base


@dataclass
class Recommendation:
    action: Action
    score: float
    summary: str
    reasons: list[str] = field(default_factory=list)
    rejected: bool = False
    #: State after this action (hints only), used by the lookahead.
    after: MetaState | None = field(default=None, repr=False, compare=False)
    #: Hints only: what the harmful readings cost (D18), also for rejected
    #: hints, so the last-resort fallback picks the least harmful one.
    risk_cost: float = 0.0


def describe(v: Variant, a: Action, me: int | None = None) -> str:
    if a.type is ActionType.PLAY:
        return f"play slot {a.slot + 1}"
    if a.type is ActionType.DISCARD:
        return f"discard slot {a.slot + 1}"
    what = v.suits[a.value].name if a.type is ActionType.HINT_COLOR else f"{a.value}s"
    return f"hint p{a.target} {what}"


def chop_index(ms: MetaState, player: int) -> int | None:
    """The card this player discards next (D6): their oldest card with no hint
    on it that no convention has flagged as unsafe (protective discard)."""
    for i, s in enumerate(ms.bs.public.hands[player]):
        if not s.touched and s.uid not in ms.unsafe:
            return i
    return None


def last_resort_index(ms: MetaState, player: int) -> int:
    """No chop (every card hinted or flagged): the card least likely to end the
    game, from `player`'s own view. Then least likely playable, then oldest."""
    views = ms.view(player)
    flagged = {s.uid for s in ms.bs.public.hands[player] if s.uid in ms.unsafe}
    return min(range(len(views)),
               key=lambda i: (1.0 if views[i].uid in flagged else views[i].p_critical,
                              views[i].p_playable, i))


def discard_index(ms: MetaState, player: int) -> int:
    """Where `player` discards: chop, else the last resort."""
    chop = chop_index(ms, player)
    return chop if chop is not None else last_resort_index(ms, player)


def advise(ms: MetaState, w: Weights | None = None,
           include_rejected: bool = False) -> list[Recommendation]:
    w = w or Weights()
    recs = _plays(ms, w) + _discards(ms, w) + _hints(ms, w)
    v = ms.variant
    for r in recs:
        if r.rejected:
            continue
        if r.after is not None:
            after, hints = r.after, r.after.bs.hints
        elif r.action.type is ActionType.DISCARD:
            after, hints = ms, min(ms.bs.hints + 1, v.max_hints)
            if ms.bs.hints == 1 or (ms.bs.hints == 0 and ms._has_known_play(ms.observer)):
                after = _as_protective(ms, r, w)
        else:
            after, hints = ms, ms.bs.hints
        penalty, notes = lookahead(after, hints, w)
        r.score -= penalty
        r.reasons += notes
    best = max((r.score for r in recs if not r.rejected), default=None)
    if best is None or best < -w.game_loss / 2:
        # Everything left risks ending the game: a misleading hint (at worst a
        # misplay or a wasted turn) beats a near-certain loss.
        for r in recs:
            if r.rejected and r.action.is_hint and r.after is not None:
                penalty, notes = lookahead(r.after, r.after.bs.hints, w)
                r.rejected = False
                r.score = -w.misleading_hint_fallback - penalty - r.risk_cost
                r.reasons += ["last resort: misleading, but every other option "
                              "risks ending the game"] + notes
    if not include_rejected:
        recs = [r for r in recs if not r.rejected]
    return sorted(recs, key=lambda r: -r.score)


# ---- lookahead (D9) ---------------------------------------------------------------

def _as_protective(ms: MetaState, r: Recommendation, w: Weights) -> MetaState:
    """My discard is read as protective (D15): show what it protects.

    Applies at 1 token, or at 0 tokens when I have a known play I'm skipping.

    Returns a copy where the protected player's chop is flagged unsafe, so the
    lookahead has them discard the next card instead.
    """
    from ..conventions import protective_discard
    bs, v = ms.bs, ms.variant
    p = protective_discard.forced_discarder(ms, ms.observer)
    if p is None:
        return ms
    uid = protective_discard.chop_uid(bs, p, ms.unsafe)
    if uid is None:
        return ms
    if not protective_discard.could_be_critical(ms, p, uid):
        return ms  # they can't read it as "game-ending": an ordinary discard
    after = copy.deepcopy(ms)
    after.unsafe.add(uid)
    slot = next(i for i, s in enumerate(bs.public.hands[p]) if s.uid == uid)
    card = bs.hands[p][slot]
    crit = card is not None and is_critical(v, card, bs.stacks, bs.discards)
    if card is not None and not crit:
        r.score -= w.misleading_protective
        r.reasons.append(f"misleading: p{p} would read their slot {slot + 1} "
                         f"({v.card_str(card)}) as a last copy and hold it")
        return after
    r.reasons.append(f"protective discard: tells p{p} their slot {slot + 1}"
                     + (f" ({v.card_str(card)}) " if card else " ")
                     + "is a last copy (discarding it ends the game)")
    if crit:
        # The signal protects the last copy itself. At 0 tokens no save hint is
        # possible and my known play only waits a round; at 1 token it beats a
        # save hint because it gets a token back instead of spending one. If the
        # signal would protect some other card, there's no bonus and a save hint
        # wins. If a needed card would still be discarded, the lookahead penalty
        # cancels it.
        r.score += w.protective_crit_bonus
        r.reasons.append("my known play can wait a round; the last copy can't be replaced"
                         if bs.hints == 0 else
                         "more hint-efficient than a save hint: gains a token instead "
                         "of spending one")
    return after


def lookahead(ms: MetaState, hints: int, w: Weights) -> tuple[float, list[str]]:
    """Simulate the next players' Meta moves; return (penalty, notes)."""
    bs, v, cs = ms.bs, ms.variant, ms.variant.card_str
    penalty, notes = 0.0, []
    for k in range(1, w.lookahead_depth + 1):
        p = (ms.observer + k) % v.num_players
        if p == ms.observer:
            break
        views = ms.view(p)
        expected = {e.expected.uid for e in ms.expected_of(p)
                    if e.expected and e.expected.uid is not None
                    and (e.card is None or is_playable(e.card, bs.stacks))}
        play = next((sv for sv in views if sv.certainly_playable or sv.uid in expected), None)
        if play is not None:
            card = bs.hands[p][play.slot]
            if not is_playable(card, bs.stacks):
                penalty += w.lookahead_misplay
                if is_critical(v, card, bs.stacks, bs.discards):
                    penalty += _crit_cost(v, w, 0)
                    notes.append(f"lookahead: p{p} would play {cs(card)} and miss, "
                                 f"losing the last copy")
                else:
                    notes.append(f"lookahead: p{p} would play {cs(card)} and miss")
            elif card.rank == 5 and v.five_returns_hint:
                hints = min(hints + 1, v.max_hints)
            continue
        if hints > 0:
            # No known play: they may well discard rather than hint, and under
            # D21 they'll trust a chop nobody protected. A last copy there is
            # at risk even with tokens left.
            chop = chop_index(ms, p)
            card = bs.hands[p][chop] if chop is not None else None
            if card is not None and is_critical(v, card, bs.stacks, bs.discards):
                penalty += _crit_cost(v, w, w.lookahead_crit) * w.lookahead_may_discard
                notes.append(f"lookahead: p{p} has no known play and might discard "
                             f"{cs(card)} (critical) from their chop")
            hints -= 1
            continue
        card = bs.hands[p][discard_index(ms, p)]
        if is_critical(v, card, bs.stacks, bs.discards):
            penalty += _crit_cost(v, w, w.lookahead_crit)
            notes.append(f"lookahead: p{p} would have no hint and discard {cs(card)} "
                         f"(critical)")
        hints = min(hints + 1, v.max_hints)
    return penalty, notes


# ---- plays -------------------------------------------------------------------------

def _plays(ms: MetaState, w: Weights) -> list[Recommendation]:
    bs, v, me = ms.bs, ms.variant, ms.observer
    expected = {e.expected.uid: e for e in ms.expected_of(me) if e.expected.uid is not None}
    out = []
    hard = bs.view(me)  # hint information only, no convention inferences
    last_strike = bs.strikes >= v.max_strikes - 1
    for sv in ms.view(me):
        a = Action.play(sv.slot)
        if last_strike and not hard[sv.slot].certainly_playable:
            continue  # on the last strike, only play what the hints prove
        if sv.known and _hinted_copy_elsewhere(ms, sv.known) is not None:
            continue  # O4: they'll play their copy; see _discards
        cands = "/".join(sorted(v.card_str(c) for c in sv.candidates))
        reasons = []
        if sv.uid in expected:
            reasons.append(f"convention: {expected[sv.uid].reason}")
        if sv.certainly_playable:
            score = w.play_certain
            reasons.append(f"certainly playable ({cands})")
            if v.five_returns_hint and all(c.rank == 5 for c in sv.candidates):
                score += w.play_five_bonus
                reasons.append("a 5 returns a hint token")
        elif sv.touched and _maybe_waiting(ms, sv):
            continue  # a hinted card that may be waiting on a teammate's unlock
        elif sv.p_playable >= w.risky_min_p and bs.strikes < v.max_strikes - 1:
            score = w.risky_scale * sv.p_playable
            reasons.append(f"{sv.p_playable:.0%} playable ({cands}); risks a strike")
            p_loss = sv.p_where(lambda c: not is_playable(c, bs.stacks)
                                and is_critical(v, c, bs.stacks, bs.discards))
            if p_loss and v.end_when_perfect_lost:
                # D22: under our rules a miss that loses a last copy ends the
                # game. Nobody gambles on that: hold it (discard a presumed-
                # safe chop or stall instead).
                continue
            if p_loss:
                score -= _crit_cost(v, w, w.discard_crit_penalty) * p_loss
                reasons.append(f"{p_loss:.0%} chance a miss loses the last copy"
                               + (" (ends the game)" if v.end_when_perfect_lost else ""))
        else:
            continue
        out.append(Recommendation(a, score, describe(v, a), reasons))
    return out


def _hinted_copy_elsewhere(ms: MetaState, card) -> int | None:
    """A teammate holding a hinted copy of `card` (they'll play theirs), if any."""
    bs = ms.bs
    if is_trash(ms.variant, card, bs.stacks, bs.discards):
        return None
    for q, hand in enumerate(bs.hands):
        if q == ms.observer:
            continue
        for c, s in zip(hand, bs.public.hands[q]):
            if c == card and s.touched:
                return q
    return None


def _maybe_waiting(ms: MetaState, sv) -> bool:
    """True if some candidate is unplayable but its unlocks are visibly coming."""
    from ..belief.bookkeeping import is_trash
    from ..conventions.skip_level import locate_unlocks
    bs = ms.bs
    for c in sv.candidates:
        if is_playable(c, bs.stacks) or is_trash(ms.variant, c, bs.stacks, bs.discards):
            continue
        _, missing = locate_unlocks(bs, c, giver=ms.observer)
        if not missing:
            return True
    return False


@dataclass
class Risk:
    """One way a reading of my hint goes wrong (D18)."""

    game_end: bool          # else it costs a strike
    text: str
    maybe: bool = False     # only if they take a risky blind play: half the cost

    def cost(self, w: Weights) -> float:
        c = w.game_loss if self.game_end else w.misread_strike
        return c / 2 if self.maybe else c


def _reader(ms: MetaState, player: int) -> MetaState:
    """`player`'s point of view to simulate on: their model if this MetaState
    keeps one (everything they've inferred so far), else rebuilt from scratch
    (public info only, no earlier convention inferences)."""
    m = ms.model(player)
    if m is None:
        m = MetaState(ms.bs.model_for(player))
        m.unsafe = set(ms.unsafe)
    return m


def _read_hint(ms: MetaState, player: int, hint: HintEvent) -> MetaState:
    m = _reader(ms, player)
    m.apply(hint)
    return m


def _miss_ends_game(ms: MetaState, card) -> bool:
    bs, v = ms.bs, ms.variant
    return is_critical(v, card, bs.stacks, bs.discards) or bs.strikes >= v.max_strikes - 1


def _slot_of(m: MetaState, player: int, uid: int) -> int | None:
    return next((i for i, s in enumerate(m.bs.public.hands[player]) if s.uid == uid), None)


def _hint_risks(ms: MetaState, w: Weights, tms: MetaState, hint: HintEvent,
                my_reading) -> list[Risk]:
    """Every harmful reading of my hint (D18): the receiver's, and bystanders'.

    The receiver reads by the Meta; the giver owns the ambiguity. `tms` is the
    receiver's state after the hint. For each reader, what they would now do
    or "know" is checked against the real cards:

    * a blind play they'd make (self skip-level newest card, multi-card lead,
      a card they now think is certainly playable) must really play;
    * after a self skip-level unlock plays, they narrow the hinted card to its
      suit, so the unlock must be the hinted card's real unlock;
    * every narrowing of their own cards must keep the real card;
    * a hinted card they'd now blind-play on odds (risky play) that misses
      counts at half cost.
    Bystanders: when a hint asks a teammate for an unlock, a bystander who
    can't see it may conclude it's in their own hand and blind-play.
    """
    bs, v, me, cs = ms.bs, ms.variant, ms.observer, ms.variant.card_str
    target = hint.target
    real = bs.hands[target]
    risks: list[Risk] = []
    explained: set[int] = set()  # uids already covered by a risk

    def miss(card, uid, text, maybe=False):
        risks.append(Risk(_miss_ends_game(ms, card), text, maybe))
        explained.add(uid)

    interp = tms.interpretations[-1]
    for e in interp.expectations:
        cand = e.expected
        if cand is None or cand.player != target or cand.how not in ("newest", "lead"):
            continue
        slot = _slot_of(tms, target, cand.uid)
        card = real[slot] if slot is not None else None
        if card is None:
            continue
        if not is_playable(card, bs.stacks) or card not in e.options():
            what = ("a self skip-level and blind-play their newest card" if cand.how == "newest"
                    else "the newest hinted card as the one to play first")
            miss(card, cand.uid, f"p{target} would read {what} ({cs(card)})")
            continue
        # After the unlock plays, they narrow each hinted card to the unlock's
        # suit (continue_self_shotgun): e.g. play W3, conclude the hinted B4 is W4.
        for uid in e.self_hint or ():
            hs = _slot_of(tms, target, uid)
            hinted = real[hs] if hs is not None else None
            if hinted is not None and hinted.suit != card.suit:
                miss(hinted, uid, f"p{target} would play {cs(card)} as the unlock and "
                                  f"then read their hinted {cs(hinted)} as "
                                  f"{v.suits[card.suit].name}")
    for r, uid in _narrowing_risks(ms, tms, target, interp):
        if uid not in explained:
            risks.append(r)
            explained.add(uid)
    # The receiver's own play options after the hint, scored the way they'd
    # score them (a risky play that could lose a last copy is already charged
    # there, so they'd hold a "play or save" card rather than gamble).
    views = tms.view(target)
    for r in _plays(tms, w):
        sv = views[r.action.slot]
        card = real[sv.slot]
        if card is None or is_playable(card, bs.stacks) or sv.uid in explained \
                or sv.slot not in hint.touched:
            continue
        if sv.certainly_playable:
            miss(card, sv.uid, f"p{target} would think their {cs(card)} is playable")
        elif r.score > 0:
            miss(card, sv.uid, f"p{target} might blind-play their {cs(card)} "
                               f"({sv.p_playable:.0%} playable to them)", maybe=True)
    # Bystanders read the hint from their own view: they see the target's
    # cards but not their own, so e.g. a card that's critical to me may not
    # be to them, and my save becomes their skip-level. Only a hint whose
    # touched cards are all playable (or a 5 / trash hint) can't be misread.
    all_play = all(real[i] is not None and is_playable(real[i], bs.stacks)
                   for i in hint.touched)
    if not all_play and my_reading.kind not in (HintKind.SAFETY_FIVE, HintKind.TRASH):
        for q in range(v.num_players):
            if q in (me, target):
                continue
            qms = _read_hint(ms, q, hint)
            qi = qms.interpretations[-1]
            seen: set[int] = set()
            for e in qi.expectations:
                cand = e.expected
                if cand is None or cand.player != q or cand.uid is None:
                    continue
                slot = _slot_of(qms, q, cand.uid)
                card = bs.hands[q][slot] if slot is not None else None
                # A different card that still plays (e.g. the top of a shotgun
                # line) costs nothing; one that misses is a strike.
                if card is not None and card not in e.options() \
                        and not is_playable(card, bs.stacks):
                    seen.add(cand.uid)
                    risks.append(Risk(
                        _miss_ends_game(ms, card),
                        f"p{q} would think they hold the unlock "
                        f"({'/'.join(sorted(cs(c) for c in e.options()))}) and "
                        f"blind-play their {cs(card)}"))
            risks += [r for r, uid in _narrowing_risks(ms, qms, q, qi) if uid not in seen]
            # A holder I'm counting on to play an unlock must read it that way
            # too. If they read the hint as something else (e.g. a save, when
            # they can't see the unlock in their own hand), they won't play it;
            # the others see a decline and the next one blind-plays.
            for e in my_reading.expectations:
                if e.card is None or not any(c.player == q for c in e.candidates):
                    continue
                if not any(x.card == e.card and any(c.player == q for c in x.candidates)
                           for x in qi.expectations):
                    risks.append(Risk(False, f"p{q} wouldn't know to play {cs(e.card)}: "
                                             f"they'd read the hint as {qi.kind.value}"))
    return risks


def _narrowing_risks(ms: MetaState, rms: MetaState, player: int, interp):
    """Narrowings of `player`'s own cards that leave out the real card: they'd
    later "know" a wrong card (e.g. a save of G4 read newest-first as G2).
    Yields (risk, uid)."""
    cs = ms.variant.card_str
    for uid, cards in interp.constraints.items():
        slot = _slot_of(rms, player, uid)
        card = ms.bs.hands[player][slot] if slot is not None else None
        if card is not None and card not in cards:
            yield (Risk(_miss_ends_game(ms, card),
                        f"p{player} would narrow their {cs(card)} to "
                        f"{'/'.join(sorted(cs(c) for c in cards))}"), uid)


def _chain_plays(ms: MetaState, tms: MetaState, hint: HintEvent
                 ) -> tuple[list[int], Risk | None]:
    """Play my hint forward through the receiver's eyes (D19).

    The receiver plays each touched card, newest -> oldest, as soon as they'd
    know it's playable. If the first one waits on a teammate's visible unlock,
    the unlock is played first. After every play, every card the receiver
    would now think is certainly playable is checked: a play can move on an
    older multi-card hint of theirs, which then reads its next card on the new
    board. Returns the touched uids that really play in a row, and the risk if
    the receiver would play a card that misses. A card they'd hold ends the run.
    """
    target, cs = hint.target, ms.variant.card_str
    interp = tms.interpretations[-1]
    hand = tms.bs.public.hands[target]
    order = interp.chain or [hand[i].uid for i in sorted(hint.touched, reverse=True)]
    real = {s.uid: c for s, c in zip(ms.bs.public.hands[target], ms.bs.hands[target])}
    sim = copy.deepcopy(tms)
    sure_before = {sv.uid for sv in sim.view(target) if sv.certainly_playable}
    played: list[int] = []

    def wrong_belief() -> Risk | None:
        for sv in sim.view(target):
            card = real.get(sv.uid)
            if sv.certainly_playable and sv.uid not in sure_before and card is not None                     and not is_playable(card, sim.bs.stacks):
                return Risk(_miss_ends_game(ms, card),
                            f"p{target} would then read their {cs(card)} as playable and miss")
        return None

    for uid in order:
        slot = _slot_of(sim, target, uid)
        card = real.get(uid)
        if slot is None or card is None:
            break
        if not sim.view(target)[slot].certainly_playable:
            if played or not _will_play(sim, target, uid, hint.giver)                     or not _play_unlocks(sim, card, target):
                break
            if not sim.view(target)[slot].certainly_playable:
                break
            risk = wrong_belief()
            if risk:
                return played, risk
        if not is_playable(card, sim.bs.stacks):
            return played, Risk(_miss_ends_game(ms, card),
                                f"p{target} would play their {cs(card)} next in line and miss")
        sim.apply(PlayEvent(target, slot, card, True))
        if sim.bs.deck_size > 0:
            sim.apply(DrawEvent(target, None))
        played.append(uid)
        risk = wrong_belief()
        if risk:
            return played, risk
        if len(interp.chain) < 2:
            break
    return played, None


def _play_unlocks(sim: MetaState, card, target: int) -> bool:
    """Simulate teammates playing the cards `card` waits on (visible in their
    hands). No draws: only the board matters here. False if one isn't visible."""
    bs = sim.bs
    for r in range(bs.stacks[card.suit] + 1, card.rank):
        need = type(card)(card.suit, r)
        where = next(((q, i) for q, h in enumerate(bs.hands) if q != target
                      for i, c in enumerate(h) if c == need), None)
        if where is None:
            return False
        sim.apply(PlayEvent(where[0], where[1], need, True))
    return True


def _save_can_wait(ms: MetaState, target: int) -> bool:
    """A chop save can wait a round: the target knows of a play (so they play
    rather than discard on their next turn), and at least 2 tokens will be
    left after my hint for someone to save it later."""
    if ms.bs.hints - 1 < 2:
        return False
    m = ms.models.get(target) if ms.models else None
    m = m or ms
    return m._has_known_play(target)


def _will_play(tms: MetaState, target: int, uid: int, giver: int) -> bool:
    """Will the receiver act on this hinted card: they know it's playable, are
    expected to play it, or know it waits on a teammate's visible unlock."""
    from ..conventions.skip_level import locate_unlocks
    slot = _slot_of(tms, target, uid)
    if slot is None:
        return False
    sv = tms.view(target)[slot]
    if sv.certainly_playable or any(e.expected and e.expected.uid == uid
                                    for e in tms.expected_of(target)):
        return True
    bs = tms.bs
    return all(is_playable(c, bs.stacks) or not locate_unlocks(bs, c, giver)[1]
               for c in sv.candidates)


def _o4_ok(ms: MetaState, holder: int, holder_uid: int, card, target: int,
           touched: tuple[int, ...]) -> bool:
    """O4: may I hint a second copy of `card` to `target` while `holder` has one?

    Only when the holder is sure of their copy (they'll discard it as the
    signal rather than misread it), has another playable card to get on with,
    and the hint to the target has its own purpose: newest -> oldest, the
    touched cards play in order, starting with this copy.
    """
    bs = ms.bs
    views = ms.view(holder)
    mine = next((sv for sv in views if sv.uid == holder_uid), None)
    if mine is None or mine.known != card:
        return False
    if not any(sv.certainly_playable and sv.uid != holder_uid for sv in views):
        return False
    run = [bs.hands[target][i] for i in sorted(touched, reverse=True)]
    if len(run) < 2 or run[0] != card:
        return False
    stacks = list(bs.stacks)
    for c in run[:2]:
        if c is None or not is_playable(c, stacks):
            return False
        stacks[c.suit] = c.rank
    return True


def _duplicate_of(ms: MetaState, card, target: int, uid: int,
                  touched: tuple[int, ...] = ()) -> tuple[str | None, str | None]:
    """(problem, note): where another copy of `card` is already hinted or expected.

    The O4 exception turns a problem into a note: the holder should discard
    their copy, which tells the target their newest hinted card is it.
    """
    bs, me = ms.bs, ms.observer
    holders: list[tuple[int, int, str]] = []
    for e in ms.pending():
        cand = e.expected
        if e.card == card and cand and not (cand.player == target and cand.uid == uid):
            holders.append((cand.player, cand.uid, f"p{cand.player} is already expected "
                                                   f"to play it"))
    for q, hand in enumerate(bs.hands):
        if q in (target, me):
            continue
        for c, s in zip(hand, bs.public.hands[q]):
            if c == card and s.touched:
                holders.append((q, s.uid, f"p{q} already has a hinted copy"))
    for sv in ms.view(me):
        if sv.known == card:
            holders.append((me, sv.uid, "I already hold a known copy"))
    if not holders:
        return None, None
    for q, huid, why in holders:
        if huid is None or not _o4_ok(ms, q, huid, card, target, touched):
            return why, None
    q = holders[0][0]
    who = "I" if q == me else f"p{q}"
    return None, (f"duplicate on purpose (O4): {who} should discard their "
                  f"{ms.variant.card_str(card)}, telling p{target} which hinted card it is")


def _endgame_problem(sim: MetaState, target: int, interp) -> str | None:
    """A hint whose plays can't all happen before the game ends."""
    bs, me = sim.bs, sim.observer
    if bs.turns_left is None:
        return None
    n = sim.variant.num_players
    if not bs.has_turn(target, me):
        return f"endgame: p{target} has no turn left"
    if interp.kind not in (HintKind.SKIP_LEVEL, HintKind.SHOTGUN):
        return None
    t_off = (target - me) % n
    for e in interp.expectations:
        cand = e.expected
        if cand is None:
            continue
        if not bs.has_turn(cand.player, me) or (cand.player - me) % n > t_off:
            return (f"endgame: p{cand.player} can't play {sim.variant.card_str(e.card)} "
                    f"before p{target}'s last turn; give a direct hint instead")
    return None


# ---- discards -------------------------------------------------------------------

def _discards(ms: MetaState, w: Weights) -> list[Recommendation]:
    bs, v, me = ms.bs, ms.variant, ms.observer
    if bs.hints >= v.max_hints and not v.allow_discard_at_max_hints:
        return []
    views = ms.view(me)
    token_bonus = w.discard_token_bonus * (v.max_hints - bs.hints) / v.max_hints
    out = []
    for sv in views:
        q = _hinted_copy_elsewhere(ms, sv.known) if sv.known else None
        if q is not None:
            a = Action.discard(sv.slot)
            out.append(Recommendation(
                a, w.duplicate_signal_discard, describe(v, a),
                [f"p{q} holds a hinted {v.card_str(sv.known)} too: discarding mine "
                 f"tells them which hinted card it is (O4)",
                 "playing mine would leave their copy to misplay"]))
            break
    trash = [sv for sv in views if sv.certainly_trash]
    for sv in trash[:1]:
        a = Action.discard(sv.slot)
        out.append(Recommendation(a, w.discard_base + w.discard_trash_bonus + token_bonus,
                                  describe(v, a), ["known trash: safe discard",
                                                   f"regains a hint ({bs.hints} now)"]))
    chop = chop_index(ms, me)
    if chop is None and not trash:
        k = last_resort_index(ms, me)
        sv = views[k]
        p_crit = 1.0 if sv.uid in ms.unsafe else sv.p_critical
        a = Action.discard(k)
        out.append(Recommendation(
            a, w.discard_base + token_bonus
            - _crit_cost(v, w, w.discard_crit_penalty) * p_crit
            - w.discard_playable_penalty * sv.p_playable,
            describe(v, a),
            ["every card is hinted or flagged game-ending: discarding the one least "
             f"likely to be a last copy ({p_crit:.0%} critical)"]))
    if chop is not None and not (trash and trash[0].slot == chop):
        sv = views[chop]
        a = Action.discard(chop)
        crit_cost = _crit_cost(v, w, w.discard_crit_penalty)
        watched = ms.chop_watched(me)
        if watched:
            crit_cost *= w.watched_chop_risk
        score = (w.discard_base + token_bonus - crit_cost * sv.p_critical
                 - w.discard_playable_penalty * sv.p_playable)
        reasons = ["oldest un-hinted card (default discard)",
                   f"regains a hint ({bs.hints} now)"]
        skipped = [s for s in bs.public.hands[me][:chop] if s.uid in ms.unsafe]
        if skipped:
            reasons.append(f"skips {len(skipped)} card(s) flagged game-ending by a "
                           f"protective discard")
        if sv.p_critical:
            reasons.append(f"{sv.p_critical:.0%} chance it is critical"
                           + (" (losing it ends the game)" if v.end_when_perfect_lost else ""))
            if watched:
                reasons.append(f"p{ms.last_actor} saw it on my chop and didn't protect "
                               f"it: presumed safe (D21)")
        if sv.p_playable:
            reasons.append(f"{sv.p_playable:.0%} chance it is playable")
        out.append(Recommendation(a, score, describe(v, a), reasons))
    return out


# ---- hints ------------------------------------------------------------------------

def _hints(ms: MetaState, w: Weights) -> list[Recommendation]:
    bs, v, me = ms.bs, ms.variant, ms.observer
    if bs.hints <= 0:
        return []
    out = []
    for t in range(v.num_players):
        if t == me:
            continue
        options = [("color", c) for c in v.hint_colors] + [("rank", r) for r in range(1, 6)]
        for kind, value in options:
            rec = _evaluate_hint(ms, w, t, kind, value)
            if rec:
                out.append(rec)
    return out


def _evaluate_hint(ms: MetaState, w: Weights, target: int, kind: str, value: int
                   ) -> Recommendation | None:
    bs, v, me = ms.bs, ms.variant, ms.observer
    hand = bs.hands[target]
    touched = tuple(i for i, c in enumerate(hand) if c is not None and v.touches(kind, value, c))
    if not touched and not v.allow_empty_hints:
        return None
    a = Action.hint_color(target, value) if kind == "color" else Action.hint_rank(target, value)
    cs = v.card_str
    hint = HintEvent(me, target, kind, value, touched)
    sim = copy.deepcopy(ms)
    sim.apply(hint)
    interp = sim.interpretations[-1]
    tms = _read_hint(ms, target, hint)  # how the receiver will read it
    before = ms.view(target)
    already = {e.expected.uid for e in ms.expected_of(target) if e.expected}
    touched_str = " ".join(cs(hand[i]) for i in touched) or "nothing"
    reasons = [f"touches {touched_str}", f"read as {interp.kind.value}: {interp.reason}"]
    uid_to_slot = {s.uid: i for i, s in enumerate(bs.public.hands[target])}
    score = 0.0
    rejected = False
    after = sim.view(target)
    if all(after[i].candidates == before[i].candidates for i in touched) and \
            interp.kind is not HintKind.SAFETY_FIVE:
        return None  # the target learns nothing new about the touched cards

    was_touched = {s.uid for s in bs.public.hands[target] if s.touched}
    rehint = bool(interp.focus) and set(interp.focus) <= was_touched and         interp.kind is not HintKind.SAFETY_FIVE
    if rehint:
        # Re-hinting cards that already carry a meaning only fills in detail.
        # Teammates would still read a skip-level into it (e.g. "green" on a
        # saved G5), so only a plain play or trash reading is acceptable.
        if interp.kind in (HintKind.PLAY, HintKind.TRASH):
            score = w.info_only
            reasons.append("only adds detail to already-hinted cards")
        else:
            rejected = True
            reasons.append("misleading: re-hinting an already-hinted card would be read "
                           f"as {interp.kind.value} (D3c)")
    if not rejected and interp.kind in (HintKind.PLAY, HintKind.SKIP_LEVEL, HintKind.SHOTGUN):
        for u in interp.focus:
            if u in uid_to_slot and u not in already:
                dup, note = _duplicate_of(ms, hand[uid_to_slot[u]], target, u, touched)
                if note:
                    reasons.append(note)
                if dup:
                    rejected = True
                    reasons.append(f"duplicate: {cs(hand[uid_to_slot[u]])} "
                                   f"is covered ({dup})")
                    break
    if not rejected:
        problem = _endgame_problem(sim, target, interp)
        if problem:
            rejected = True
            reasons.append(problem)

    chain, chain_risk = _chain_plays(ms, tms, hint)
    if rejected or rehint:
        pass
    elif interp.kind is HintKind.PLAY:
        new = [u for u in interp.focus
               if u not in already and not before[uid_to_slot[u]].certainly_playable]
        # Only plays the receiver can see count (D18): a playable card they
        # can't tell from a non-playable one just gets held.
        acted = [u for u in new if _will_play(tms, target, u, me) or u in chain]
        unclear = [u for u in new if u not in acted]
        if acted:
            score = w.play_hint_base + w.per_new_play * len(acted)
            reasons.append(f"{len(acted)} new playable card(s)")
        elif new:
            score = w.info_only
        else:
            reasons.append("adds nothing: already known")
        if unclear:
            score += w.unclear_play * len(unclear)
            reasons.append(f"p{target} can't tell " + ", ".join(
                cs(hand[uid_to_slot[u]]) for u in unclear) + " is playable: they'd hold it")
    elif interp.kind in (HintKind.SKIP_LEVEL, HintKind.SHOTGUN):
        new_exps = [e for e in interp.expectations if e.card is not None]
        # The hinted cards play too, once unlocked, if the receiver can tell.
        then = [u for u in interp.focus if u in uid_to_slot and u not in already
                and _will_play(tms, target, u, me)]
        score = w.skip_hint_base + w.per_new_play * (len(new_exps) + len(then))
        for u in then:
            reasons.append(f"p{target} then plays {cs(hand[uid_to_slot[u]])}")
        for e in new_exps:
            if e.expected:
                reasons.append(f"p{e.expected.player} should play {cs(e.card)} "
                               f"({e.expected.how})")
                slot = next((sl for sl in bs.public.hands[e.expected.player]
                             if sl.uid == e.expected.uid), None)
                if slot is not None and slot.touched:
                    # Allowed under the Meta, but it asks them to play a card
                    # that already carries a hint: avoid when there's a cleaner way.
                    score -= w.touched_unlock_penalty
                    reasons.append(f"unlock sits in an already-hinted card of "
                                   f"p{e.expected.player}")
    elif interp.kind is HintKind.SAVE:
        chop = chop_index(ms, target)
        on_chop = chop is not None and bs.public.hands[target][chop].uid in interp.focus
        score = w.save_chop if on_chop else w.save_not_chop
        reasons.append("saves a critical card on their chop" if on_chop
                       else "saves a critical card (not on chop yet)")
        if on_chop and _save_can_wait(ms, target):
            score = w.save_can_wait
            reasons.append(f"can wait: p{target} has a play first")
    elif interp.kind is HintKind.SAFETY_FIVE:
        chop = chop_index(ms, target)
        on_chop = chop is not None and chop in touched
        score = w.safety_five_chop if on_chop else w.safety_five_other
        reasons.append("protects a 5 on their chop" if on_chop else "5 not on chop yet")
        if on_chop and _save_can_wait(ms, target):
            score = w.save_can_wait
            reasons.append(f"can wait: p{target} has a play first")
        reasons.append("everyone but you reverses their untouched cards (safety swap)")
    elif interp.kind is HintKind.TRASH:
        fresh = [i for i in touched if not before[i].certainly_trash]
        score = w.trash_hint_per_card * len(fresh)
        reasons.append(f"marks {len(fresh)} card(s) as safe to discard")
    else:
        rejected = True
        reasons.append("misleading: teammates would draw wrong conclusions (D3c)")

    risks = _hint_risks(ms, w, tms, hint, interp)
    if chain_risk and not any(r.text == chain_risk.text for r in risks):
        risks.append(chain_risk)

    # A hint also makes non-focus cards collateral; flag a critical chop card that
    # stays unprotected only via the save branch above.
    focus_slots = {uid_to_slot[u] for u in interp.focus if u in uid_to_slot}
    if not rejected and score > 0:
        # Tie-break between hints with the same meaning: prefer the one that
        # tells the receiver more (e.g. "rainbow" over "red" on a rainbow card).
        score += w.info_tiebreak * sum(
            1 - len(after[i].candidates) / max(1, len(before[i].candidates))
            for i in focus_slots)
    extra = [i for i in touched if i not in focus_slots]
    if not rejected and extra and score > 0:
        score -= w.collateral_penalty * len(extra)  # prefer the cleaner hint
        reasons.append(f"{len(extra)} collateral card(s)")
    if not rejected and bs.hints == 1:
        score -= w.last_token_penalty
        reasons.append("spends the last hint token")
    if not rejected and score <= 0 and not risks:
        # Worth nothing, but harmless: a stall. It ranks below every option that
        # does something, and above a gamble on a last copy or a discard that
        # risks the game (D18: the least bad lead).
        score = w.stall_hint - (w.last_token_penalty if bs.hints == 1 else 0)
        reasons.append("stall: harmless, but achieves nothing")
    risk_cost = sum(r.cost(w) for r in risks)
    for r in risks if not rejected else ():
        # Ambiguous (D18): kept, but below any clean option, so it's only
        # chosen when every alternative risks more.
        score -= r.cost(w)
        reasons.append(f"ambiguous: {r.text}" + (" (ends the game)" if r.game_end
                                                 else " (a strike)")
                       + (", if they take the risk" if r.maybe else ""))
    crit_touched = [i for i in touched if is_critical(v, hand[i], bs.stacks, bs.discards)]
    if crit_touched and interp.kind is not HintKind.SAVE and not rejected:
        reasons.append("also marks a critical card")
    if rejected:
        reasons += [f"if given anyway: {r.text}" for r in risks]
    return Recommendation(a, score if not rejected else -1000, describe(v, a), reasons,
                          rejected, after=sim, risk_cost=risk_cost)

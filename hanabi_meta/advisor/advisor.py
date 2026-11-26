"""Rank the observer's possible actions under the Meta, with reasons.

Scoring is deliberately simple and readable: every number comes from `Weights`,
and every score is built from named parts that end up in the explanation.

Plays     certain (by info or by a convention expectation) > risky (only above a
          probability threshold, and never on the last strike).
Hints     each candidate hint is *simulated*: we apply it to a copy of the
          MetaState and read the Interpretation the conventions produce. A hint
          whose reading would be dead or unclear is rejected as misleading
          (docs/QUESTIONS.md D3c). Otherwise it is valued by what it achieves:
          new plays, unlocks via skip-level, saves of a critical chop card,
          trash marking. A play/skip hint on a second copy of a card that is
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

from ..belief.bookkeeping import is_critical, is_playable
from ..conventions.base import HintKind
from ..conventions.meta_state import MetaState
from ..engine.actions import Action, ActionType, HintEvent
from ..engine.variant import Variant


@dataclass
class Weights:
    play_certain: float = 100
    play_five_bonus: float = 3          # a 5 also returns a hint token
    risky_min_p: float = 0.6            # never suggest a blind play below this
    risky_scale: float = 50             # score = risky_scale * p(playable)
    save_chop: float = 85               # saving a critical card on someone's chop
    save_not_chop: float = 15
    play_hint_base: float = 50
    per_new_play: float = 10
    skip_hint_base: float = 45
    trash_hint_per_card: float = 12
    safety_five_chop: float = 70
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
    lookahead_depth: int = 3            # how many following players to simulate
    lookahead_crit: float = 80          # a teammate would be forced to discard a critical
    lookahead_misplay: float = 50       # a teammate would play a card that misses


@dataclass
class Recommendation:
    action: Action
    score: float
    summary: str
    reasons: list[str] = field(default_factory=list)
    rejected: bool = False
    #: State after this action (hints only), used by the lookahead.
    after: MetaState | None = field(default=None, repr=False, compare=False)


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
        else:
            after, hints = ms, ms.bs.hints
        penalty, notes = lookahead(after, hints, w)
        r.score -= penalty
        r.reasons += notes
    if not include_rejected:
        recs = [r for r in recs if not r.rejected]
    return sorted(recs, key=lambda r: -r.score)


# ---- lookahead (D9) ---------------------------------------------------------------

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
                notes.append(f"lookahead: p{p} would play {cs(card)} and miss")
            elif card.rank == 5:
                hints = min(hints + 1, v.max_hints)
            continue
        if hints > 0:
            hints -= 1
            continue
        chop = chop_index(ms, p)
        card = bs.hands[p][chop if chop is not None else 0]
        if is_critical(v, card, bs.stacks, bs.discards):
            penalty += w.lookahead_crit
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
        cands = "/".join(sorted(v.card_str(c) for c in sv.candidates))
        reasons = []
        if sv.uid in expected:
            reasons.append(f"convention: {expected[sv.uid].reason}")
        if sv.certainly_playable:
            score = w.play_certain
            reasons.append(f"certainly playable ({cands})")
            if all(c.rank == 5 for c in sv.candidates):
                score += w.play_five_bonus
                reasons.append("a 5 returns a hint token")
        elif sv.touched and _maybe_waiting(ms, sv):
            continue  # a hinted card that may be waiting on a teammate's unlock
        elif sv.p_playable >= w.risky_min_p and bs.strikes < v.max_strikes - 1:
            score = w.risky_scale * sv.p_playable
            reasons.append(f"{sv.p_playable:.0%} playable ({cands}); risks a strike")
        else:
            continue
        out.append(Recommendation(a, score, describe(v, a), reasons))
    return out


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


def _receiver_misreads(ms: MetaState, target: int, kind: str, value: int,
                      touched: tuple[int, ...]) -> str | None:
    """Read the hint from the receiver's side; describe a harmful misreading.

    The receiver can't see their own hand but can see mine, which I can't. So
    their view is approximated with both hands hidden (an unlock in my hand
    can't be intended anyway). Earlier convention inferences aren't carried
    over. If they would conclude "self skip-level" and blind-play their newest
    card, that card must actually be playable.
    """
    from ..conventions.base import Expectation  # noqa: F401  (type context)
    bs, v, me = ms.bs, ms.variant, ms.observer
    tb = copy.deepcopy(bs)
    tb.observer = target
    tb.hands[target] = [None] * len(tb.hands[target])
    tb.hands[me] = [None] * len(tb.hands[me])
    tms = MetaState(tb)
    tms.apply(HintEvent(me, target, kind, value, touched))
    interp = tms.interpretations[-1]
    real = bs.hands[target]
    for e in interp.expectations:
        cand = e.expected
        if cand is None or cand.player != target or cand.how != "newest":
            continue
        slot = next(i for i, s in enumerate(tb.public.hands[target]) if s.uid == cand.uid)
        card = real[slot]
        if card is None or not is_playable(card, bs.stacks) or card not in e.options():
            return (f"p{target} would read a self skip-level and blind-play their "
                    f"newest card ({v.card_str(card) if card else '?'})")
    return None


def _duplicate_of(ms: MetaState, card, target: int, uid: int) -> str | None:
    """Where another copy of `card` is already hinted or expected, if anywhere."""
    bs, me = ms.bs, ms.observer
    for e in ms.pending():
        cand = e.expected
        if e.card == card and cand and not (cand.player == target and cand.uid == uid):
            return f"p{cand.player} is already expected to play it"
    for q, hand in enumerate(bs.hands):
        if q in (target, me):
            continue
        for c, s in zip(hand, bs.public.hands[q]):
            if c == card and s.touched:
                return f"p{q} already has a hinted copy"
    if any(sv.known == card for sv in ms.view(me)):
        return "I already hold a known copy"
    return None


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
    trash = [sv for sv in views if sv.certainly_trash]
    for sv in trash[:1]:
        a = Action.discard(sv.slot)
        out.append(Recommendation(a, w.discard_base + w.discard_trash_bonus + token_bonus,
                                  describe(v, a), ["known trash: safe discard",
                                                   f"regains a hint ({bs.hints} now)"]))
    chop = chop_index(ms, me)
    if chop is None and not trash:
        a = Action.discard(0)
        out.append(Recommendation(a, w.discard_base + token_bonus - w.discard_crit_penalty,
                                  describe(v, a), ["every card is hinted or flagged "
                                                   "unsafe: oldest card as a last resort"]))
    if chop is not None and not (trash and trash[0].slot == chop):
        sv = views[chop]
        a = Action.discard(chop)
        score = (w.discard_base + token_bonus - w.discard_crit_penalty * sv.p_critical
                 - w.discard_playable_penalty * sv.p_playable)
        reasons = ["oldest un-hinted card (default discard)",
                   f"regains a hint ({bs.hints} now)"]
        skipped = [s for s in bs.public.hands[me][:chop] if s.uid in ms.unsafe]
        if skipped:
            reasons.append(f"skips {len(skipped)} card(s) flagged unsafe by a "
                           f"protective discard")
        if sv.p_critical:
            reasons.append(f"{sv.p_critical:.0%} chance it is critical")
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
    sim = copy.deepcopy(ms)
    sim.apply(HintEvent(me, target, kind, value, touched))
    interp = sim.interpretations[-1]
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
                dup = _duplicate_of(ms, hand[uid_to_slot[u]], target, u)
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

    if rejected or rehint:
        pass
    elif interp.kind is HintKind.PLAY:
        new = [u for u in interp.focus
               if u not in already and not before[uid_to_slot[u]].certainly_playable]
        if new:
            score = w.play_hint_base + w.per_new_play * len(new)
            reasons.append(f"{len(new)} new playable card(s)")
        else:
            reasons.append("adds nothing: already known")
    elif interp.kind in (HintKind.SKIP_LEVEL, HintKind.SHOTGUN):
        new_exps = [e for e in interp.expectations if e.card is not None]
        score = w.skip_hint_base + w.per_new_play * len(new_exps)
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
    elif interp.kind is HintKind.SAFETY_FIVE:
        chop = chop_index(ms, target)
        on_chop = chop is not None and chop in touched
        score = w.safety_five_chop if on_chop else w.safety_five_other
        reasons.append("protects a 5 on their chop" if on_chop else "5 not on chop yet")
        reasons.append("everyone but you reverses their untouched cards (safety swap)")
    elif interp.kind is HintKind.TRASH:
        fresh = [i for i in touched if not before[i].certainly_trash]
        score = w.trash_hint_per_card * len(fresh)
        reasons.append(f"marks {len(fresh)} card(s) as safe to discard")
    else:
        rejected = True
        reasons.append("misleading: teammates would draw wrong conclusions (D3c)")

    if not rejected:
        problem = _receiver_misreads(ms, target, kind, value, touched)
        if problem:
            rejected = True
            reasons.append(f"misleading: {problem} (D3c)")

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
    if not rejected and score <= 0:
        return None
    crit_touched = [i for i in touched if is_critical(v, hand[i], bs.stacks, bs.discards)]
    if crit_touched and interp.kind is not HintKind.SAVE and not rejected:
        reasons.append("also marks a critical card")
    return Recommendation(a, score if not rejected else -1000, describe(v, a), reasons,
                          rejected, after=sim)

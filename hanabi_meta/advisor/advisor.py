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
          trash marking.
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
    """Oldest untouched slot: the card this player discards next (D6)."""
    for i, s in enumerate(ms.bs.public.hands[player]):
        if not s.touched:
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
    for sv in ms.view(me):
        a = Action.play(sv.slot)
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
        elif sv.p_playable >= w.risky_min_p and bs.strikes < v.max_strikes - 1:
            score = w.risky_scale * sv.p_playable
            reasons.append(f"{sv.p_playable:.0%} playable ({cands}); risks a strike")
        else:
            continue
        out.append(Recommendation(a, score, describe(v, a), reasons))
    return out


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
    if chop is not None and not (trash and trash[0].slot == chop):
        sv = views[chop]
        a = Action.discard(chop)
        score = (w.discard_base + token_bonus - w.discard_crit_penalty * sv.p_critical
                 - w.discard_playable_penalty * sv.p_playable)
        reasons = ["oldest untouched card (default discard)",
                   f"regains a hint ({bs.hints} now)"]
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
    if interp.focus and set(interp.focus) <= was_touched and             interp.kind is not HintKind.SAFETY_FIVE:
        # Re-hinting cards that already carry a meaning only fills in detail;
        # it does not start a new skip-level.
        score = w.info_only
        reasons.append("only adds detail to already-hinted cards")
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

    # A hint also makes non-focus cards collateral; flag a critical chop card that
    # stays unprotected only via the save branch above.
    focus_slots = {uid_to_slot[u] for u in interp.focus if u in uid_to_slot}
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

"""Skip-level and shotgun hints (docs/QUESTIONS.md D1-D3).

Reading a hint, as the observer:

1. A rank-5 hint is a safety hint (see safety_swap), not a skip-level.
2. A hint is "about" every touched card that is playable now (PLAY), or whose
   missing lower cards (the unlocks) all sit somewhere a teammate will play them
   (SKIP_LEVEL, or SHOTGUN when one sits further down a playable line).
   "Somewhere they will play them" means the player's newest slot, a slot
   their own info already identifies, or a slot below a run of playable cards.
3. Other touched cards are collateral when the hint already has a meaning.
4. If no touched card is explained by what the observer sees, the observer
   must hold the missing unlock(s): in their newest slot, then the next newest
   (shotgun). A critical card with no visible unlock is read as a SAVE instead
   (D5), since the hinter must avoid a save that looks like a play.
5. Who plays an unlock: visible holders in turn order after the hinter. If one
   declines (acts without playing it while it is playable), the next candidate
   is expected. The observer is always the last fallback, because a teammate who
   declines can see the observer's hand.

When the observer is the hint target they cannot see the touched card, so each
candidate identity is classified (playable / visibly unlocked / would need an
unlock from the observer) and the slot is narrowed accordingly.
"""
from __future__ import annotations

from ..belief.bookkeeping import is_critical, is_playable, is_trash, unseen_counts
from ..belief.tracker import BeliefState
from ..engine.actions import HintEvent
from ..engine.variant import Card
from .base import (Candidate, Expectation, HintKind, Interpretation, needed_unlocks,
                   observer_line, playable_position, stacks_after, turn_order_after)

_PREF = {"known": 0, "newest": 1, "line": 2}


def locate_unlocks(bs: BeliefState, card: Card, giver: int
                   ) -> tuple[list[tuple[Card, list[Candidate]]], list[Card]]:
    """For each card needed before `card`, the visible players who will play it.

    Returns (plan, missing): plan pairs each needed card with its candidates in
    turn order after the giver; missing lists needed cards nobody visibly holds
    in a playable position.
    """
    n = bs.variant.num_players
    plan: list[tuple[Card, list[Candidate]]] = []
    missing: list[Card] = []
    needed = needed_unlocks(card, bs.stacks)
    for k, need in enumerate(needed):
        board = stacks_after(bs.stacks, needed[:k])
        cands: list[Candidate] = []
        for p in turn_order_after(giver, n):
            if p in (giver, bs.observer):
                continue
            best: Candidate | None = None
            for slot in range(len(bs.hands[p])):
                how = playable_position(bs, p, slot, need, board)
                if how and (best is None or _PREF[how] < _PREF[best.how]):
                    best = Candidate(p, bs.public.hands[p][slot].uid, how)
            if best:
                cands.append(best)
        plan.append((need, cands))
        if not cands:
            missing.append(need)
    return plan, missing


def _expectations(bs: BeliefState, plan, hint_index: int, giver: int, reason: str
                  ) -> list[Expectation]:
    out = []
    observer_can_hold = unseen_counts(bs.variant, bs.seen_by(bs.observer))
    line = observer_line(bs)
    for need, cands in plan:
        cands = list(cands)
        if bs.observer != giver and observer_can_hold[need] > 0:
            cands.append(Candidate(bs.observer, None, "inferred", line=line))
        out.append(Expectation(need, cands, f"{reason}: unlock {bs.variant.card_str(need)}",
                               hint_index))
    return out


def interpret_hint(bs: BeliefState, hint: HintEvent, hint_index: int) -> Interpretation:
    """Interpret `hint` (already applied to `bs`) under the skip-level rules."""
    v = bs.variant
    base = dict(hint_index=hint_index, giver=hint.giver, target=hint.target)
    uids = [bs.public.hands[hint.target][i].uid for i in hint.touched]
    if hint.kind == "rank" and hint.value == 5:
        return Interpretation(**base, kind=HintKind.SAFETY_FIVE, focus=uids,
                              reason="a 5 hint is a safety hint")
    if hint.target == bs.observer:
        return _interpret_own(bs, hint, hint_index)

    cs = v.card_str
    plays, skips, unexplained, dead = [], [], [], []
    for i, uid in zip(hint.touched, uids):
        card = bs.hands[hint.target][i]
        assert card is not None
        if is_playable(card, bs.stacks):
            plays.append((uid, card))
        elif is_trash(v, card, bs.stacks, bs.discards):
            dead.append((uid, card))
        else:
            plan, missing = locate_unlocks(bs, card, hint.giver)
            (unexplained if missing else skips).append((uid, card, plan, missing))

    exps: list[Expectation] = []
    if plays or skips:
        for uid, card in plays:
            exps.append(Expectation(card, [Candidate(hint.target, uid, "known")],
                                    f"{cs(card)} was hinted as playable", hint_index))
        shotgun = False
        for uid, card, plan, _ in skips:
            shotgun |= any(c.how == "line" for _, cands in plan for c in cands)
            for e in _expectations(bs, plan, hint_index, hint.giver,
                                   f"skip-level on {cs(card)}"):
                if all(e.card != x.card for x in exps):  # unlock also hinted directly
                    exps.append(e)
        kind = HintKind.PLAY if not skips else (HintKind.SHOTGUN if shotgun
                                                else HintKind.SKIP_LEVEL)
        focus = [u for u, _ in plays] + [s[0] for s in skips]
        names = ", ".join([cs(c) for _, c in plays] + [cs(s[1]) for s in skips])
        return Interpretation(**base, kind=kind, focus=focus, expectations=exps,
                              reason=f"hint is about {names}")

    if unexplained:
        # 5s are saved with a rank hint (safety hint), never with a color hint.
        saves = [u for u in unexplained if u[1].rank != 5
                 and is_critical(v, u[1], bs.stacks, bs.discards)]
        if saves:
            return Interpretation(
                **base, kind=HintKind.SAVE, focus=[u[0] for u in saves],
                reason=f"{', '.join(cs(u[1]) for u in saves)} critical with no visible "
                       f"unlock: save")
        # Several unexplained touched cards: read it as about the newest one.
        uid, card, plan, missing = unexplained[-1]
        if bs.observer == hint.giver:
            return Interpretation(**base, kind=HintKind.UNCLEAR, focus=[uid],
                                  reason="unlock not visible to the hinter")
        exps = _expectations(bs, plan, hint_index, hint.giver, f"skip-level on {cs(card)}")
        kind = HintKind.SHOTGUN if len(missing) > 1 else HintKind.SKIP_LEVEL
        return Interpretation(
            **base, kind=kind, focus=[uid], expectations=exps,
            reason=f"{cs(card)} is not playable and nobody else visibly holds "
                   f"{', '.join(cs(m) for m in missing)}, so I must hold it")
    if dead:
        return Interpretation(**base, kind=HintKind.DEAD, focus=[u for u, _ in dead],
                              reason="touched card is already dead (see playable_five)")
    return Interpretation(**base, kind=HintKind.UNCLEAR, focus=uids, reason="no reading")


def _interpret_own(bs: BeliefState, hint: HintEvent, hint_index: int) -> Interpretation:
    """The observer received the hint and can't see the touched card(s)."""
    v = bs.variant
    views = bs.view(bs.observer)
    hand = bs.public.hands[bs.observer]
    base = dict(hint_index=hint_index, giver=hint.giver, target=hint.target)
    explained: dict[int, set[Card]] = {}     # uid -> playable or visibly unlocked
    self_needed: dict[int, set[Card]] = {}   # uid -> first unlock observer would hold
    all_critical = True
    for i in hint.touched:
        uid = hand[i].uid
        for c in views[i].candidates:
            if is_trash(v, c, bs.stacks, bs.discards):
                continue
            if is_playable(c, bs.stacks):
                explained.setdefault(uid, set()).add(c)
                all_critical = False
                continue
            _, missing = locate_unlocks(bs, c, hint.giver)
            if not missing:
                explained.setdefault(uid, set()).add(c)
            else:
                self_needed.setdefault(uid, set()).add(missing[0])
            if not is_critical(v, c, bs.stacks, bs.discards):
                all_critical = False
    uids = [hand[i].uid for i in hint.touched]
    if explained:
        ambiguous = any(uid in self_needed for uid in explained)
        interp = Interpretation(
            **base, kind=HintKind.PLAY, focus=list(explained),
            reason="my hinted card is playable now or once a teammate plays a visible "
                   "unlock" + (", or a self skip-level (unlock in my own newest card)"
                               if ambiguous else ""))
        if len(hint.touched) == 1:
            # Pruning: a hint never points at a trash card (that would be a
            # trash hint). Self skip-level stays possible: the unlock may sit
            # in my own newest card, which the hinter sees and I don't.
            i = hint.touched[0]
            interp.constraints[uids[0]] = {
                c for c in views[i].candidates if not is_trash(v, c, bs.stacks, bs.discards)}
        return interp
    if self_needed and not all_critical:
        newest = [s for s in hand if not s.touched]
        if not newest:
            return Interpretation(**base, kind=HintKind.UNCLEAR, focus=uids,
                                  reason="no untouched slot to hold the unlock")
        options = set().union(*self_needed.values())
        exp = Expectation(None, [Candidate(bs.observer, newest[-1].uid, "newest",
                                           line=observer_line(bs))],
                          "self skip-level: nobody else holds the unlock, so it is my "
                          "newest card", hint_index, possible=options,
                          self_hint=list(self_needed))
        return Interpretation(**base, kind=HintKind.SKIP_LEVEL, focus=uids,
                              expectations=[exp], reason=exp.reason)
    return Interpretation(**base, kind=HintKind.SAVE, focus=uids,
                          reason="hinted card can only be a critical card: save")


def continue_self_shotgun(bs: BeliefState, interp: Interpretation, done: Expectation,
                          played: Card) -> list[Expectation]:
    """After I successfully play the unlock of a self skip-level, keep going (D3).

    A shotgun is played newest to oldest until the hint makes sense. My played
    card tells me the suit of the hinted card(s) it was unlocking, so narrow
    them to that suit. If one is still not explained by what I can see, the
    next unlock is my next card down the line (from the hint-time snapshot).
    Returns new expectations (already-visible unlocks become ordinary ones).
    """
    v = bs.variant
    views = {sv.uid: sv for sv in bs.view(bs.observer)}
    line = list(done.candidates[0].line or ())
    if done.candidates[0].uid in line:
        line = line[line.index(done.candidates[0].uid) + 1:]
    line = [u for u in line if u in views]
    out: list[Expectation] = []
    for uid in done.self_hint:
        sv = views.get(uid)
        if sv is None:
            continue
        same = {c for c in sv.candidates if c.suit == played.suit
                and not is_trash(v, c, bs.stacks, bs.discards)}
        if not same:
            continue
        interp.constraints[uid] = same
        if any(is_playable(c, bs.stacks) for c in same):
            continue  # the hint now makes sense: it was about a playable card
        needs: set[Card] = set()
        for c in same:
            plan, missing = locate_unlocks(bs, c, interp.giver)
            if missing:
                needs.add(missing[0])
            else:
                out += [e for e in _expectations(bs, plan, interp.hint_index, interp.giver,
                                                 f"shotgun on my hinted card")
                        if e.candidates and e.candidates[0].player != bs.observer]
        if needs and line:
            nxt = line.pop(0)
            out.append(Expectation(
                None, [Candidate(bs.observer, nxt, "line", line=tuple(line))],
                "self shotgun: the hint still doesn't make sense, so the next unlock "
                "is my next card down the line", interp.hint_index, possible=needs,
                self_hint=[uid]))
    return out

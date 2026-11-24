import random
from collections import Counter

import pytest

from hanabi_meta.belief import (BeliefState, is_critical, is_trash, max_reachable,
                                unseen_counts)
from hanabi_meta.engine import Action, Card, Game, VARIANT_KINDS, make_variant

R, Y, G, B, W, M = range(6)


def stacked(v, first):
    rest = v.deck()
    head = [v.parse_card(t) for t in first]
    for c in head:
        rest.remove(c)
    return head + rest


def tracker_for(g: Game, observer: int) -> BeliefState:
    return BeliefState(g.variant, observer).apply_all(g.events_for(observer))


# ---- layer 1 -------------------------------------------------------------------

def test_unseen_counts_and_overflow():
    v = make_variant("short_rainbow", 2)
    u = unseen_counts(v, [Card(M, 1)])
    assert u[Card(M, 1)] == 1 and u[Card(R, 1)] == 3
    with pytest.raises(ValueError):
        unseen_counts(v, [Card(M, 5), Card(M, 5)])


def test_trash_and_critical():
    v = make_variant("regular", 2)
    stacks = [2, 0, 0, 0, 0]
    disc = Counter({Card(Y, 2): 2, Card(G, 3): 1})
    assert is_trash(v, Card(R, 1), stacks, disc)          # already played
    assert is_trash(v, Card(Y, 4), stacks, disc)          # both Y2 gone
    assert max_reachable(v, Y, stacks, disc) == 1
    assert not is_trash(v, Card(Y, 1), stacks, disc)
    assert is_critical(v, Card(G, 3), stacks, disc)       # last G3
    assert is_critical(v, Card(B, 5), stacks, disc)       # fives always critical
    assert not is_critical(v, Card(Y, 5), stacks, disc)   # Y5 is dead, not critical


def test_short_rainbow_ones_are_critical_after_one_discard():
    v = make_variant("short_rainbow", 2)
    assert is_critical(v, Card(M, 2), [0] * 6, Counter())
    assert not is_critical(v, Card(M, 1), [0] * 6, Counter())
    assert is_critical(v, Card(M, 1), [0] * 6, Counter({Card(M, 1): 1}))


# ---- layer 2: hints and rainbow -------------------------------------------------

def test_two_color_hints_on_one_card_means_rainbow():
    v = make_variant("rainbow_all_colors", 2)
    # p0 hand: R1 Y1 G1 B1 W1 ; p1 hand: M3 R2 B2 G2 Y3
    deck = stacked(v, ["R1", "Y1", "G1", "B1", "W1", "M3", "R2", "B2", "G2", "Y3"])
    g = Game(v, deck=deck)
    g.step(Action.hint_color(1, R))   # touches M3, R2
    g.step(Action.hint_rank(0, 1))
    g.step(Action.hint_color(1, B))   # touches M3, B2
    bs = tracker_for(g, observer=1)
    slot0 = bs.public.hands[1][0]
    assert slot0.possible == {Card(M, r) for r in range(1, 6)}
    slot1 = bs.public.hands[1][1]                     # touched by red, not blue
    assert slot1.possible == {Card(R, r) for r in range(1, 6)}
    slot4 = bs.public.hands[1][4]                     # untouched by both
    assert all(c.suit not in (R, B, M) for c in slot4.possible)


def test_negative_color_hint_rules_out_rainbow():
    v = make_variant("rainbow", 2)
    deck = stacked(v, ["R1", "Y1", "G1", "B1", "W1", "R2", "Y2", "G2", "B2", "W2"])
    g = Game(v, deck=deck)
    g.step(Action.hint_color(1, R))
    bs = tracker_for(g, observer=1)
    for s in bs.public.hands[1][1:]:
        assert not any(c.suit in (R, M) for c in s.possible)
    assert bs.public.hands[1][0].possible == {Card(s, r) for s in (R, M) for r in range(1, 6)}


def test_rainbow_hint_in_rainbow_variant():
    v = make_variant("rainbow", 2)
    deck = stacked(v, ["R1", "Y1", "G1", "B1", "W1", "M2", "Y2", "G2", "B2", "W2"])
    g = Game(v, deck=deck)
    g.step(Action.hint_color(1, M))
    bs = tracker_for(g, observer=1)
    assert bs.public.hands[1][0].possible == {Card(M, r) for r in range(1, 6)}
    assert all(c.suit != M for s in bs.public.hands[1][1:] for c in s.possible)


def test_slots_follow_cards_when_hand_shifts():
    v = make_variant("regular", 2)
    deck = stacked(v, ["R1", "Y1", "G1", "B1", "W5", "R2", "Y2", "G2", "B2", "W2", "Y4"])
    g = Game(v, deck=deck)
    g.step(Action.hint_rank(1, 2))
    g.step(Action.hint_rank(0, 5))       # p0's slot 4 is a 5
    g.step(Action.play(0))               # p0 plays R1, W5 slides to slot 3
    bs = tracker_for(g, observer=0)
    hand = bs.public.hands[0]
    assert len(hand) == 5
    assert all(c.rank == 5 for c in hand[3].possible)
    assert len(hand[4].possible) == 25 and not hand[4].touched


# ---- layer 3: views -------------------------------------------------------------

def test_visible_cards_eliminate_from_own_candidates():
    v = make_variant("regular", 2)
    # p1 holds the only B5; p0 got a "5" hint on slot 0. p0 knows it's not B5.
    deck = stacked(v, ["R5", "Y1", "G1", "B1", "W1", "B5", "Y2", "G2", "B2", "W2"])
    g = Game(v, deck=deck)
    g.step(Action.hint_rank(1, 2))
    g.step(Action.hint_rank(0, 5))
    sv = tracker_for(g, observer=0).view(0)[0]
    assert sv.candidates == {Card(R, 5), Card(Y, 5), Card(G, 5), Card(W, 5)}
    assert sv.p_critical == 1.0 and sv.p_playable == 0.0


def test_certainly_playable_after_rank_hint_on_ones():
    v = make_variant("regular", 3)
    g = Game(v, deck=stacked(v, ["R1", "Y1", "G3", "B4", "W4"]))
    g.current = 1
    g.step(Action.hint_rank(0, 1))
    bs = tracker_for(g, observer=0)
    views = bs.view(0)
    assert views[0].certainly_playable and views[1].certainly_playable
    assert not views[2].touched


def test_known_card_elimination_within_hand():
    v = make_variant("short_rainbow", 2)
    # p0: M5 M4 ...; hint rainbow then 5 -> slot0 = M5. slot1 rainbow, not 5.
    deck = stacked(v, ["M5", "M4", "G1", "B1", "W1", "R2", "Y2", "G2", "B2", "W2"])
    g = Game(v, deck=deck)
    g.current = 1
    g.step(Action.hint_color(0, M))
    g.step(Action.hint_rank(1, 2))
    g.step(Action.hint_rank(0, 5))
    views = tracker_for(g, observer=0).view(0)
    assert views[0].known == Card(M, 5)
    assert views[1].candidates == {Card(M, r) for r in (1, 2, 3, 4)}


def test_other_player_view_is_lower_bound_excluding_observer_hand():
    v = make_variant("regular", 3)
    # p1 has a 5 hint on R5. Observer is p0, who holds... we don't use p0's cards.
    deck = stacked(v, ["Y5", "Y1", "G1", "B1", "W1",
                       "R5", "R2", "G2", "B2", "W2",
                       "G5", "R3", "G3", "B3", "W3"])
    g = Game(v, deck=deck)
    g.step(Action.hint_rank(1, 5))
    bs = tracker_for(g, observer=0)
    p1_slot0 = bs.view(1)[0]
    # p1 sees p2's G5 (observer sees it too) so G5 is eliminated, but Y5 is in
    # the observer's own hand, which the observer can't see -> stays a candidate.
    assert Card(G, 5) not in p1_slot0.candidates
    assert Card(Y, 5) in p1_slot0.candidates


@pytest.mark.parametrize("kind", VARIANT_KINDS)
@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_true_card_is_always_a_candidate(kind, n):
    """Soundness: across random games, no slot ever excludes its real card."""
    v = make_variant(kind, n)
    for seed in range(4):
        g = Game(v, seed=seed)
        rng = random.Random(seed)
        while not g.is_over:
            g.step(rng.choice(g.legal_actions()))
            if g.turn % 3:
                continue
            for obs in range(n):
                bs = tracker_for(g, obs)
                assert bs.stacks == g.stacks and bs.hints == g.hints
                assert bs.deck_size == len(g.deck)
                for p in range(n):
                    for sv, real in zip(bs.view(p), g.hands[p]):
                        assert real in sv.candidates, (kind, n, seed, obs, p, sv.slot)

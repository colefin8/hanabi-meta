"""Skip-level and shotgun situations. One test per table situation.

To add a real game situation: copy a test, write the hands (oldest -> newest),
replay the actions, and assert what the advisor should conclude. Player 0 is
"me" unless `observer=` says otherwise.
"""
from hanabi_meta.conventions import ExpStatus, HintKind
from hanabi_meta.scenario import Scenario


def test_your_example_y3_hint_unlocked_by_y2_in_newest_slot():
    # Yellow at 1. p2 hints p1 yellow on Y3. p3's newest card is Y2.
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R4 B4 W3 Y3",
        "G4 B3 R3 W4",
        "G3 W5 B5 Y2",
    ], stacks="Y1")
    t.hint(2, 1, "Y")
    assert t.last().kind is HintKind.SKIP_LEVEL
    assert t.expected(3) == ["Y2"]
    assert t.expected(0) == []
    assert len(t.my_slot(3)) > 1          # nothing inferred about my cards


def test_nobody_else_has_the_unlock_so_it_is_my_newest():
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R4 B4 W3 Y3",
        "G4 B3 R3 W4",
        "G3 W5 B5 R2",
    ], stacks="Y1")
    t.hint(2, 1, "Y")
    assert t.last().kind is HintKind.SKIP_LEVEL
    assert t.expected(0) == ["Y2"]
    assert t.my_slot(3) == {"Y2"}


def test_holder_declines_so_i_must_have_it():
    # p3 has Y2 newest but gives a hint instead: p3 must see Y2 in my hand.
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R4 B4 W3 Y3",
        "G4 B3 R1 W4",
        "G3 W5 B5 Y2",
    ], stacks="Y1")
    t.hint(2, 1, "Y")
    t.hint(3, 2, "R")                     # a plain play hint on p2's R1
    assert t.expected(3) == []
    assert t.expected(0) == ["Y2"]
    assert t.my_slot(3) == {"Y2"}


def test_multi_level_skip_one_unlock_visible_one_mine():
    # Hinted Y4 with yellow at 1: Y2 is p3's newest, Y3 is nowhere visible.
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R4 B4 W3 Y4",
        "G4 B3 R3 W4",
        "G3 W5 B5 Y2",
    ], stacks="Y1")
    t.hint(2, 1, "Y")
    assert t.last().kind is HintKind.SKIP_LEVEL
    assert t.expected(3) == ["Y2"]
    assert t.expected(0) == ["Y3"]
    assert t.my_slot(3) == {"Y3"}


def test_shotgun_unlock_below_a_playable_line():
    # p3: G3 Y2 R1 B1. R1 and B1 are playable and newer than Y2.
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R4 B4 W3 Y3",
        "G4 B3 R3 W4",
        "G3 Y2 R1 B1",
    ], stacks="Y1")
    t.hint(2, 1, "Y")
    assert t.last().kind is HintKind.SHOTGUN
    exp = t.ms.expected_of(3)[0]
    assert exp.expected.how == "line"
    assert t.expected(0) == []


def test_play_on_known_info_first_keeps_expectation():
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R4 B4 W3 Y3",
        "G4 B3 R3 W4",
        "G3 R1 B5 Y2",
    ], stacks="Y1")
    t.hint(1, 3, "R")                     # p3's R1 is known playable
    t.hint(2, 1, "Y")                     # skip-level: p3's Y2
    t.play(3, 1, "R1", draw="W2")         # p3 plays the known card first
    assert t.expected(3) == ["Y2"]
    assert t.expected(0) == []
    t.discard(0, 0, "G2")                 # my turn passes
    t.hint(1, 2, "B")
    t.hint(2, 1, "W")
    t.play(3, 2, "Y2", draw="G1")         # Y2 is now in slot 2 after the shift
    y2 = [e for e in t.ms.expectations if e.card and t.variant.card_str(e.card) == "Y2"]
    assert y2[0].status is ExpStatus.FULFILLED


def test_waiting_on_an_earlier_unlock_is_not_declining():
    # Hinted Y4, yellow at 1. p3 (acts first) holds Y3, p1 holds Y2.
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R4 B4 Y4 Y2",
        "G4 B3 R1 W4",
        "G3 W5 B5 Y3",
    ], stacks="Y1")
    t.hint(2, 1, "Y")
    assert t.expected(1) == ["Y2"] and t.expected(3) == ["Y3"]
    t.hint(3, 2, "R")                     # p3 can't play Y3 yet: not a decline
    assert t.expected(3) == ["Y3"]
    assert t.expected(0) == []


def test_hint_to_me_narrowed_to_playable_or_visibly_unlocked():
    # p1 hints me yellow on slot 1. Yellow at 1. p2's newest is Y2.
    t = Scenario("regular", hands=[
        "? ? ? ? ?",
        "R4 B4 W3 G3 R3",
        "G4 B3 R2 W4 Y2",
    ], stacks="Y1")
    t.hint(1, 0, "Y", touched=[1])
    assert t.last().kind is HintKind.PLAY
    assert t.my_slot(1) == {"Y2", "Y3"}


def test_self_skip_level_on_my_own_hint():
    # p1 hints me "3" on slot 0. Red at 1, nothing else played, no visible
    # unlocks anywhere: my newest card must be the first missing unlock.
    t = Scenario("regular", hands=[
        "? ? ? ? ?",
        "R4 B4 W3 G4 R5",
        "G4 B3 W4 Y4 B5",
    ], stacks="R1")
    t.hint(1, 0, 3, touched=[0])
    assert t.last().kind is HintKind.SKIP_LEVEL
    assert t.my_slot(4) == {"R2", "Y1", "G1", "B1", "W1"}


def test_critical_card_without_visible_unlock_is_a_save():
    # Other B2 is discarded; B1 not visible. Hint on B2 is a save, not a skip.
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R4 B4 W3 B2",
        "G4 B3 R3 W4",
        "G3 W5 B5 R4",
    ], discards="B2")
    t.hint(2, 1, "B")
    assert t.last().kind is HintKind.SAVE
    assert t.expected(0) == []


def test_collateral_card_does_not_trigger_inference():
    # "2" touches R2 (playable) and B2 (not): the hint is about R2 only.
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R2 B4 W3 B2",
        "G4 B3 R3 W4",
        "G3 W5 B5 R4",
    ], stacks="R1")
    t.hint(2, 1, 2)
    assert t.last().kind is HintKind.PLAY
    assert t.expected(1) == ["R2"]
    assert t.ms.constraints() == {}


def test_rainbow_card_touched_by_red_is_skip_level_target():
    # Rainbow-as-every-color: red touches M3. Rainbow at 1; p3's newest is M2.
    t = Scenario("rainbow_all_colors", hands=[
        "? ? ? ?",
        "R4 B4 W3 M3",
        "G4 B3 R3 W4",
        "G3 W5 B5 M2",
    ], stacks="M1")
    t.hint(2, 1, "R")
    interp = t.last()
    assert interp.kind is HintKind.SKIP_LEVEL
    assert t.expected(3) == ["M2"]


def test_five_rank_hint_is_not_a_skip_level():
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R4 B4 W3 Y5",
        "G4 B3 R3 W4",
        "G3 W5 B5 Y2",
    ], stacks="Y1")
    t.hint(2, 1, 5)
    assert t.last().kind is HintKind.SAFETY_FIVE


def test_meta_state_survives_random_games_in_every_variant():
    """Random (non-Meta) play must never crash the convention layer."""
    import random

    from hanabi_meta.conventions import MetaState
    from hanabi_meta.engine import VARIANT_KINDS, Game, make_variant, mask_for

    for kind in VARIANT_KINDS:
        for n in (2, 3, 4, 5):
            g = Game(make_variant(kind, n), seed=n)
            rng = random.Random(n)
            ms = MetaState.new(g.variant, observer=0)
            ms.apply_all([mask_for(0, e) for e in g.deal_events])
            while not g.is_over:
                rec = g.step(rng.choice(g.legal_actions()))
                for e in list(rec.events):       # copy: reorder() appends to it
                    ms.apply(mask_for(0, e))
                    for r in ms.last_reorders:   # keep the engine's hands in step
                        g.reorder(r.player, r.order)
                ms.view(0)
                ms.explain()

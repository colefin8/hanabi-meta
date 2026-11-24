"""Trash ("safe to discard") hints. See docs/QUESTIONS.md D8."""
from hanabi_meta.conventions import HintKind
from hanabi_meta.scenario import Scenario


def test_hint_white_when_white_is_done_is_trash():
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R4 W1 B4 W2",
        "G4 B3 R3 Y4",
        "G3 Y5 B5 R4",
    ], stacks="W5")
    t.hint(2, 1, "W")
    assert t.last().kind is HintKind.TRASH
    assert t.expected(0) == []


def test_ones_hint_to_me_when_every_stack_has_its_one():
    t = Scenario("regular", hands=[
        "? ? ? ? ?",
        "R4 B4 W3 G3 R3",
        "G4 B3 R2 W4 Y2",
    ], stacks="R1 Y1 G1 B1 W1")
    t.hint(1, 0, 1, touched=[0, 3])
    assert t.last().kind is HintKind.TRASH
    views = t.ms.view(0)
    assert views[0].certainly_trash and views[3].certainly_trash


def test_yellow_hint_to_me_with_yellow_at_4_and_y5_visible():
    t = Scenario("regular", hands=[
        "? ? ? ? ?",
        "R4 B4 W3 G3 R3",
        "G4 B3 Y5 W4 R2",
    ], stacks="Y4")
    t.hint(1, 0, "Y", touched=[2])
    assert t.last().kind is HintKind.TRASH
    assert t.ms.view(0)[2].certainly_trash


def test_dead_yellow_not_obvious_to_receiver_is_not_a_trash_hint():
    # Yellow at 4 and I can't see Y5 anywhere: it may be in my hand, which p1
    # can see. So p1 can't be sure, and it isn't an obvious trash hint. That's
    # the playable-5 trigger instead.
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R4 B4 W3 Y2",
        "G4 B3 R3 W4",
        "G3 W5 B5 R4",
    ], stacks="Y4")
    t.hint(2, 1, "Y")
    assert t.last().kind is HintKind.DEAD


def test_rainbow_variant_white_hint_also_touches_rainbow_so_not_trash():
    # White is complete, but a white hint may also touch a live rainbow card.
    t = Scenario("rainbow", hands=[
        "? ? ? ? ?",
        "R4 B4 W3 G3 R3",
        "G4 B3 Y5 W4 R2",
    ], stacks="W5")
    t.hint(1, 0, "W", touched=[2])
    assert t.last().kind is not HintKind.TRASH

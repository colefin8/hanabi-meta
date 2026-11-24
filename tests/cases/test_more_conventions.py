"""Safety swap (D4), playable 5 (D7) and protective discard (D6)."""
from hanabi_meta.advisor import advise
from hanabi_meta.conventions import HintKind
from hanabi_meta.engine import ActionType
from hanabi_meta.scenario import Scenario


def cards(t: Scenario, p: int) -> str:
    return " ".join(t.variant.card_str(c) for c in t.bs.hands[p])


def uids(t: Scenario, p: int) -> list[int]:
    return [s.uid for s in t.bs.public.hands[p]]


# ---- safety swap --------------------------------------------------------------

def test_five_hint_reverses_unhinted_cards_of_everyone_but_giver():
    t = Scenario("regular", hands=[
        "? ? ? ? ?",
        "R4 B4 W5 G3 Y3",
        "G4 B3 R3 W4 Y2",
    ])
    t.hint(2, 0, 1, touched=[1])          # my slot 2 has a hint and must stay put
    mine = uids(t, 0)
    t.hint(2, 1, 5)
    assert t.last().kind is HintKind.SAFETY_FIVE
    assert cards(t, 1) == "Y3 G3 W5 B4 R4"           # W5 hinted, stays in slot 3
    assert cards(t, 2) == "G4 B3 R3 W4 Y2"           # the giver doesn't swap
    assert uids(t, 0) == [mine[4], mine[1], mine[3], mine[2], mine[0]]


def test_five_hint_to_me_keeps_my_hinted_slot():
    t = Scenario("regular", hands=["? ? ? ? ?", "R4 B4 W3 G3 Y3", "G4 B3 R3 W4 Y2"])
    mine = uids(t, 0)
    t.hint(1, 0, 5, touched=[4])
    assert uids(t, 0) == [mine[3], mine[2], mine[1], mine[0], mine[4]]
    assert all(c.rank == 5 for c in t.ms.view(0)[4].candidates)


def test_i_give_the_five_hint_so_my_hand_stays():
    t = Scenario("regular", hands=["? ? ? ? ?", "R4 B4 W5 G3 Y3", "G4 B3 R3 W4 Y2"])
    mine = uids(t, 0)
    t.hint(0, 1, 5)
    assert uids(t, 0) == mine
    assert cards(t, 2) == "Y2 W4 R3 B3 G4"


def test_negative_info_travels_with_the_card():
    t = Scenario("regular", hands=["? ? ? ? ?", "R4 B4 W5 G3 Y3", "G4 B3 R3 W4 Y2"])
    t.hint(1, 0, "R", touched=[0])        # slots 2-5 learn "not red"
    t.hint(2, 1, 5)                       # slots 2-5 reverse among themselves
    views = t.ms.view(0)
    assert all(c.suit == 0 for c in views[0].candidates)
    assert all(c.suit != 0 for sv in views[1:] for c in sv.candidates)


# ---- playable 5 -----------------------------------------------------------------

def test_dead_red_hint_then_discard_means_my_newest_is_r5():
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "G4 B3 Y3 W4",
        "Y4 B4 R2 W3",
        "G3 W5 B5 Y2",
    ], stacks="R4")
    t.hint(1, 2, "R")                     # R2 is already played: a dead hint
    assert t.expected(0) == []            # no inference until the discard
    t.discard(2, 2, "R2", draw="G2")
    assert t.last().kind is HintKind.PLAYABLE_FIVE
    assert t.expected(0) == ["R5"]
    assert t.my_slot(3) == {"R5"}
    assert advise(t.ms)[0].summary == "play slot 4"


def test_chain_stack_at_three_and_r5_visible_means_i_hold_r4():
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "G4 B3 Y3 W4",
        "Y4 B4 R2 W3",
        "G3 W5 B5 R5",
    ], stacks="R3")
    t.hint(1, 2, "R")                     # touches R2 only (dead)
    t.discard(2, 2, "R2", draw="G2")
    assert t.expected(0) == ["R4"]
    assert t.expected(3) == ["R5"]
    assert t.my_slot(3) == {"R4"}


def test_r5_visible_elsewhere_so_not_me():
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "G4 B3 Y3 W4",
        "Y4 B4 R2 W3",
        "G3 W5 B5 R5",
    ], stacks="R4")
    t.hint(1, 2, "R")
    t.discard(2, 2, "R2", draw="G2")
    assert t.expected(3) == ["R5"]
    assert t.expected(0) == []


def test_no_discard_no_signal():
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "G4 B3 Y3 W4",
        "Y4 B4 R2 W3",
        "G3 W5 B5 Y2",
    ], stacks="R4")
    t.hint(1, 2, "R")
    t.discard(2, 0, "Y4", draw="G2")      # discards something else
    assert not any(i.kind is HintKind.PLAYABLE_FIVE for i in t.ms.interpretations)


# ---- protective discard ----------------------------------------------------------

def test_protective_discard_flags_my_chop():
    # p2 acts directly before me. With 1 hint left, p2 discards instead of hinting.
    t = Scenario("regular", hands=["? ? ? ? ?", "R4 B4 W3 G3 Y3", "G4 B3 R3 W4 Y2"],
                 hints=1)
    t.discard(2, 0, "G4", draw="B1")
    assert any("p0's slot 1 is unsafe" in n for n in t.ms.notes)
    discard = next(r for r in advise(t.ms) if r.action.type is ActionType.DISCARD)
    assert discard.summary == "discard slot 2"


def test_repeated_protective_discard_flags_the_next_card():
    t = Scenario("regular", hands=["? ? ? ? ?", "R4 B4 W3 G3 Y3", "G4 B3 R3 W4 Y2"],
                 hints=1)
    t.discard(2, 0, "G4", draw="B1")      # hints -> 2
    t.hint(0, 1, "R")                     # hints -> 1
    t.hint(1, 2, "B")                     # hints -> 0 ... give one back:
    t.ms.bs.hints = 1
    t.discard(2, 0, "B3", draw="Y1")
    assert any("p0's slot 2 is unsafe" in n for n in t.ms.notes)


def test_no_signal_with_two_hints_or_from_further_away():
    t = Scenario("regular", hands=["? ? ? ? ?", "R4 B4 W3 G3 Y3", "G4 B3 R3 W4 Y2"],
                 hints=2)
    t.discard(2, 0, "G4", draw="B1")
    assert t.ms.notes == []
    t2 = Scenario("regular", hands=["? ? ? ? ?", "R4 B4 W3 G3 Y3", "G4 B3 R3 W4 Y2"],
                  hints=1)
    t2.discard(1, 0, "R4", draw="B1")     # p1 is before p2, not me
    assert all("p0" not in n for n in t2.ms.notes)

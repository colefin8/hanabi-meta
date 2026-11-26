"""Interpretation edge cases found on a second pass (docs/QUESTIONS.md D12)."""
from hanabi_meta.advisor.advisor import advise
from hanabi_meta.conventions import HintKind
from hanabi_meta.scenario import Scenario


def _hints(t):
    return {r.summary: r for r in advise(t.ms, include_rejected=True)
            if r.summary.startswith("hint")}


def test_my_unlock_is_my_newest_card_at_hint_time_not_a_later_draw():
    # p3 hints p1 Y3; p2 holds Y2. I act (and draw) before p2 declines.
    t = Scenario("regular", hands=["? ? ? ?", "R4 B4 W3 Y3", "G3 W5 B5 Y2",
                                   "G4 B3 R1 W4"], stacks="Y1")
    meant = t.bs.public.hands[0][-1].uid
    t.hint(3, 1, "Y")
    t.discard(0, 0, "G2")                 # my new card is drawn after the hint
    t.hint(1, 3, "R")
    t.hint(2, 3, "1")                     # p2 declines
    assert t.expected(0) == ["Y2"]
    assert t.ms.expected_of(0)[0].expected.uid == meant
    assert t.my_slot(2) == {"Y2"}         # the old newest, now one from the end
    assert len(t.my_slot(3)) > 1          # the fresh draw is untouched by it


def test_no_playable_five_signal_when_color_is_dead_from_discards():
    # Both Y3s are gone: a dead yellow hint + discard says nothing about Y4/Y5.
    t = Scenario("regular", hands=["? ? ? ?", "R4 B4 W3 Y4", "G3 W4 B5 R2",
                                   "G4 B3 R1 Y4"], stacks="Y2", discards="Y3 Y3")
    t.hint(2, 1, "Y")
    t.discard(3, 0, "G4", draw="W1")
    t.discard(0, 0, "G1")
    t.discard(1, 3, "Y4", draw="B1")
    assert t.last().kind is HintKind.PLAYABLE_FIVE
    assert t.last().expectations == []
    assert t.expected(3) == [] and t.expected(0) == []
    assert len(t.my_slot(3)) > 1


def test_self_shotgun_keeps_going_down_my_line():
    # Every stack at 1, I'm hinted "4" and nobody shows a 2 or 3: my newest is
    # a 2. Once it plays as Y2, my next card down is Y3 and the hinted card Y4.
    t = Scenario("regular", hands=["? ? ? ? ?", "R1 B1 W1 G5 Y5", "G1 W5 B5 R5 Y1"],
                 stacks="Y1 R1 B1 G1 W1")
    t.hint(1, 0, "4", touched=[0])
    assert t.last().kind is HintKind.SKIP_LEVEL
    t.play(0, 4, "Y2")
    assert t.expected(0) == ["Y3"]
    assert t.my_slot(3) == {"Y3"}         # old second-newest (a new card is slot 4)
    assert t.my_slot(0) == {"Y4"}
    t.discard(1, 0, "R1", draw="G2")
    t.discard(2, 0, "G1", draw="W2")
    t.play(0, 3, "Y3")
    assert t.expected(0) == []
    assert t.my_slot(0) == {"Y4"}         # now plainly playable


def test_advisor_rejects_play_hint_on_a_duplicate():
    # p1's Y2 is already hinted; hinting p2's Y2 would waste a card or a strike.
    t = Scenario("regular", hands=["? ? ? ?", "R4 B4 W3 Y2", "G3 W4 B5 Y2",
                                   "G4 B3 R3 W4"], stacks="Y1")
    t.hint(3, 1, "Y")
    h = _hints(t)
    assert h["hint p2 yellow"].rejected
    assert any("duplicate" in r for r in h["hint p2 yellow"].reasons)


def test_urgent_save_delays_the_unlock_instead_of_declining():
    # p3 holds Y2 for p1's Y3 but first saves p2's last B2 on chop.
    t = Scenario("regular", hands=["? ? ? ?", "R4 B4 W3 Y3", "B2 W4 G3 R3",
                                   "G4 B3 R4 Y2"], stacks="Y1", discards="B2")
    t.hint(2, 1, "Y")
    assert t.expected(3) == ["Y2"]
    t.hint(3, 2, "B")                     # urgent save, not a decline
    assert t.ms.interpretations[-1].kind is HintKind.SAVE
    assert t.expected(3) == ["Y2"]
    assert t.expected(0) == []
    t.discard(0, 0, "G1")
    t.discard(1, 0, "R4", draw="W1")
    t.discard(2, 3, "R3", draw="W2")
    t.hint(3, 1, "1")                     # no excuse this time: declined
    assert t.expected(3) == []
    assert t.expected(0) == ["Y2"]


def test_endgame_skip_level_rejected_when_holder_plays_too_late():
    # Deck is empty and everyone gets one last turn. p3's Y2 would only be
    # played after p1's last turn, so the skip-level on p1's Y3 can't finish:
    # a direct hint on p3's Y2 is the right move.
    t = Scenario("regular", hands=["? ? ? ?", "R4 B4 W3 Y3", "G4 B3 R3 W4",
                                   "G3 W5 B5 Y2"], stacks="Y1", deck_size=0, turns_left=4)
    h = _hints(t)
    assert h["hint p1 yellow"].rejected
    assert any("endgame" in r for r in h["hint p1 yellow"].reasons)
    assert not h["hint p3 yellow"].rejected


def test_endgame_hint_to_a_player_with_no_turn_left_is_rejected():
    t = Scenario("regular", hands=["? ? ? ?", "R4 B4 W3 Y3", "G4 B3 R3 W4",
                                   "G3 W5 B5 Y2"], stacks="Y1", deck_size=0, turns_left=2)
    assert any("no turn left" in r for r in _hints(t)["hint p3 yellow"].reasons)


def test_unlock_in_an_already_hinted_card_is_allowed_but_penalised():
    def score(touched_first: bool) -> float:
        t = Scenario("regular", hands=["? ? ? ?", "R4 B4 W3 Y3", "G4 B3 R3 W4",
                                       "G3 W5 B5 Y2"], stacks="Y1")
        if touched_first:
            t.hint(2, 3, "2")             # p3's Y2 now carries a hint
        return _hints(t)["hint p1 yellow"].score
    assert score(True) < score(False)

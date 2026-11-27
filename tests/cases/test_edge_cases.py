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


# ---- multi-card hints: newest -> oldest (D13) -------------------------------------

def test_multi_card_hint_to_me_plays_newest_first():
    t = Scenario("regular", hands=["? ? ? ?", "R4 B4 W3 G3", "G4 B3 R3 W4"], stacks="Y1")
    t.hint(1, 0, "Y", touched=[2, 3])
    assert t.my_slot(3) == {"Y2"}         # newest touched yellow plays first
    assert len(t.my_slot(2)) > 1          # the older one waits
    assert advise(t.ms)[0].summary == "play slot 4"


def test_three_twos_with_one_playable_pile_newest_is_the_two():
    # Only yellow has its 1: at most one of my 2s is playable, and it's the newest.
    t = Scenario("regular", hands=["? ? ? ?", "R4 B4 W3 G3", "G4 B3 R3 W4"], stacks="Y1")
    t.hint(1, 0, "2", touched=[0, 1, 3])
    assert t.my_slot(3) == {"Y2"}
    assert "Y2" in t.my_slot(1) and len(t.my_slot(1)) > 1


def test_advisor_rejects_multi_card_hint_whose_newest_card_is_not_playable():
    bad = Scenario("regular", hands=["? ? ? ?", "R4 Y2 B4 Y3", "G4 B3 R3 W4",
                                     "G3 W5 B5 R2"], stacks="Y1")
    h = _hints(bad)["hint p1 yellow"]
    assert h.rejected and any("first" in r for r in h.reasons)
    good = Scenario("regular", hands=["? ? ? ?", "R4 Y3 B4 Y2", "G4 B3 R3 W4",
                                      "G3 W5 B5 R2"], stacks="Y1")
    assert not _hints(good)["hint p1 yellow"].rejected


# ---- duplicate-hint convention (O4) -----------------------------------------------

def _p1_knows_y2_and_r1(t):
    t.hint(2, 1, "Y")                     # touches only Y2
    t.hint(3, 1, "2")                     # Y2 is now known exactly
    t.hint(2, 1, "1")                     # R1 known playable too


def test_known_copy_discarded_tells_me_my_newest_hinted_card_is_it():
    t = Scenario("regular", hands=["? ? ? ?", "R1 B4 W3 Y2", "G4 B3 R3 W4",
                                   "G3 W5 B4 R4"], stacks="Y1")
    _p1_knows_y2_and_r1(t)
    t.hint(3, 0, "Y", touched=[2, 3])     # my Y3 + the second Y2
    t.discard(1, 3, "Y2", draw="G1")      # p1 discards their known Y2: the signal
    assert t.ms.interpretations[-1].kind is HintKind.DUPLICATE
    assert t.my_slot(3) == {"Y2"}
    assert set(t.expected(0)) == {"Y2"}   # p1's play and the unlock both move to me
    assert t.expected(1) == []


def test_discarding_a_card_you_only_guessed_is_not_the_signal():
    # p1 was only hinted "2": discarding it says nothing about my yellows.
    t = Scenario("regular", hands=["? ? ? ?", "R1 B4 W3 Y2", "G4 B3 R3 W4",
                                   "G3 W5 B4 R4"], stacks="Y1")
    t.hint(3, 1, "2")
    t.hint(3, 0, "Y", touched=[2, 3])
    t.discard(1, 3, "Y2", draw="G1")
    assert all(i.kind is not HintKind.DUPLICATE for i in t.ms.interpretations)


def test_advisor_allows_duplicate_hint_only_in_the_o4_setup():
    hands = ["? ? ? ?", "R1 B4 W3 Y2", "G4 B3 Y3 Y2", "G3 W5 B4 R4"]
    t = Scenario("regular", hands=hands, stacks="Y1")
    _p1_knows_y2_and_r1(t)
    h = _hints(t)["hint p2 yellow"]
    assert not h.rejected and any("O4" in r for r in h.reasons)
    # Without another playable card, p1 would just play their Y2: no duplicate.
    t = Scenario("regular", hands=hands, stacks="Y1")
    t.hint(2, 1, "Y")
    t.hint(3, 1, "2")
    assert _hints(t)["hint p2 yellow"].rejected


def test_i_discard_my_known_copy_instead_of_playing_it():
    t = Scenario("regular", hands=["? ? ? ?", "R4 B4 W3 G3", "G4 B3 Y3 Y2",
                                   "G3 W5 B5 R4"], stacks="Y1")
    t.hint(1, 0, "Y", touched=[3])
    t.hint(3, 0, "2", touched=[3])        # my slot 4 is Y2, known
    t.hint(1, 2, "Y")                     # p2's Y3 + Y2 (the O4 hint)
    recs = advise(t.ms)
    assert recs[0].summary == "discard slot 4"
    assert all(r.summary != "play slot 4" for r in recs)


# ---- protective discard (D15) ------------------------------------------------------

def _protect_table(hints):
    # p1 has a hinted, playable R1; p2's chop is the last B2 (other one discarded).
    t = Scenario("regular", hands=["? ? ? ? ?", "R1 B4 W1 G3 Y3", "B2 W4 R3 G4 Y4"],
                 discards="B2", hints=hints + 1)
    t.hint(2, 1, "R")                     # p1's R1 is a known play (W1 unhinted)
    return t


def test_protective_discard_protects_the_first_player_who_would_be_forced():
    # p0 discards with 1 token. p1 would play R1, so p2 is the one protected.
    t = _protect_table(1)
    t.discard(0, 0, "G1")
    assert any("p2's slot 1 is unsafe" in n for n in t.ms.notes)
    assert all("p1's" not in n for n in t.ms.notes)


def test_discard_with_one_token_is_ordinary_if_nobody_would_be_forced():
    # Every player within reach has a known play: nobody is protected.
    t = Scenario("regular", hands=["? ? ? ? ?", "R1 B4 W3 G3 Y3", "G1 W4 R3 G4 Y4"],
                 hints=3)
    t.hint(2, 1, "1")
    t.hint(1, 2, "1")
    t.discard(0, 0, "W1")
    assert t.ms.notes == []


def test_advisor_sees_protective_discard_vs_spending_the_last_token():
    t = _protect_table(1)
    recs = {r.summary: r for r in advise(t.ms)}
    discard = recs["discard slot 1"]
    assert any("protective discard: tells p2" in r for r in discard.reasons)
    assert not any("lookahead" in r for r in discard.reasons)
    # A hint that doesn't save B2 leaves p2 with no token and B2 on chop.
    other = recs["hint p1 white"]         # a real play hint, but the last token
    assert any("B2 (critical)" in r for r in other.reasons)
    assert other.score < discard.score
    # A direct save on B2 is also fine (see D15); it's ranked by its own value.
    assert "hint p2 blue" in recs


def test_no_protective_reading_with_two_tokens():
    t = _protect_table(2)
    t.discard(0, 0, "G1")
    assert t.ms.notes == []

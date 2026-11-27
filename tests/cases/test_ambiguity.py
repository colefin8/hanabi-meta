"""D18: receivers read by the Meta; givers own the ambiguity.

* A hint to me is read strictly by the Meta (no hedging for readings the giver
  would have avoided), so a plain play hint is a certain play.
* Each seat keeps a model of every teammate, fed the same events, so the giver
  reads a hint the way the receiver will, with what they've inferred so far.
* A hint with a harmful reading isn't rejected outright: it's charged by how
  bad that reading is (a strike, or the game), so it's only chosen when every
  clean option is worse.
* Only plays the receiver can actually see count toward a play hint's value.
"""
from hanabi_meta.advisor.advisor import Risk, Weights, advise
from hanabi_meta.conventions import HintKind
from hanabi_meta.scenario import Scenario


def _hints(t):
    return {r.summary: r for r in advise(t.ms, include_rejected=True)
            if r.summary.startswith("hint")}


def test_plain_color_hint_on_a_playable_card_is_a_certain_play():
    # Red at 1; p1 hints me red on one card. No R2 visible, so R3+ would need an
    # unlock in my own hand: a self skip-level, which the giver must not give
    # when "it's R2" is a reading. So it's R2.
    t = Scenario("regular", hands=["? ? ? ? ?", "B3 G1 B4 Y4 W3", "R4 Y1 G5 B5 Y5"],
                 stacks="R1")
    t.hint(1, 0, "R", touched=[2])
    assert t.last().kind is HintKind.PLAY
    assert t.my_slot(2) == {"R2"}
    best = advise(t.ms)[0]
    assert best.summary == "play slot 3"


def test_save_reading_keeps_a_play_or_save_card_open():
    # Blue on my chop, nothing played, one B2 discarded: B1 (play) or B2 (the
    # last copy, a save). Both stay open; I don't gamble the last copy.
    t = Scenario("regular", hands=["? ? ? ?", "R4 W3 Y4 G3", "Y4 B3 R3 W4"],
                 discards="B2")
    t.hint(1, 0, "B", touched=[0])
    assert t.my_slot(0) == {"B1", "B2"}
    assert not any(r.summary == "play slot 1" and r.score > 0 for r in advise(t.ms))


def test_teammate_models_follow_the_game_with_matching_slots():
    t = Scenario("regular", hands=["? ? ? ?", "G4 B4 W3 Y2", "R4 B3 R3 W4"],
                 stacks="Y1")
    t.hint(2, 1, "Y")
    m = t.ms.models[1]
    assert [s.uid for s in m.bs.public.hands[1]] == [s.uid for s in t.bs.public.hands[1]]
    assert m.bs.hands[1] == [None] * 4 and m.bs.hands[0] == [None] * 4
    assert m.view(1)[3].known == t.variant.parse_card("Y2")   # p1 knows their Y2
    t.play(1, 3, "Y2", draw="G1")
    t.discard(2, 0, "R4", draw="B1")
    assert [s.uid for s in m.bs.public.hands[2]] == [s.uid for s in t.bs.public.hands[2]]
    assert m.bs.stacks == t.bs.stacks and m.bs.hands[2] == t.bs.hands[2]


def test_a_hint_to_me_is_shared_with_the_models_without_my_narrowings():
    t = Scenario("regular", hands=["? ? ? ? ?", "B3 G1 B4 Y4 W3", "R4 Y1 G5 B5 Y5"],
                 stacks="R1")
    t.hint(1, 0, "R", touched=[2])
    for p in (1, 2):
        theirs = t.ms.models[p].interpretations[-1]
        assert theirs.kind is HintKind.PLAY and theirs.constraints == {}


def test_play_hint_the_receiver_cant_read_as_playable_is_worth_little():
    # p1's newest is R2 (red at 1). "Red" makes it certain (R3+ would need an
    # unlock nobody shows). "2" leaves R2 or the last Y2 (a save): p1 holds it.
    t = Scenario("regular", hands=["? ? ? ?", "G4 B4 W3 R2", "R4 B3 R3 W4"],
                 stacks="R1", discards="Y2")
    h = _hints(t)
    red, two = h["hint p1 red"], h["hint p1 2s"]
    assert "1 new playable card(s)" in red.reasons
    assert any("can't tell R2 is playable" in r for r in two.reasons)
    assert red.score > two.score + 40


def test_risk_costs_rank_game_over_strike_and_maybe():
    w = Weights()
    assert Risk(True, "").cost(w) > Risk(False, "").cost(w) > Risk(False, "", True).cost(w)
    assert Risk(False, "").cost(w) > w.save_chop  # a clean save always wins


def test_models_survive_simulated_copies_without_being_copied():
    import copy
    t = Scenario("regular", hands=["? ? ? ?", "G4 B4 W3 Y2", "R4 B3 R3 W4"])
    c = copy.deepcopy(t.ms)
    assert c.models is None and t.ms.models is not None
    assert t.ms.model(1) is not t.ms.models[1] and t.ms.model(1).models is None


def test_a_chop_save_waits_while_the_target_has_a_play():
    # p1's chop is the last B2 (nothing played), and p1 already knows their Y1
    # is playable: they'll play it, not discard, so the save can wait a round.
    def save(known_play):
        t = Scenario("regular", hands=["? ? ? ?", "B2 R4 W3 Y1", "Y4 B3 R3 W4"],
                     discards="B2", hints=6)
        if known_play:
            t.hint(2, 1, "Y")
        return t, _hints(t)["hint p1 blue"]
    _, urgent = save(False)
    t, waits = save(True)
    assert not any("can wait" in r for r in urgent.reasons)
    assert any("can wait: p1 has a play first" in r for r in waits.reasons)
    assert waits.score < urgent.score - 50


def test_skip_level_counts_the_hinted_card_too():
    # Red at 1. p2's newest is R2, p1 holds R3: "red" to p1 is a skip-level that
    # makes two plays (p2's R2, then p1's R3). "2s" on p3's Y2 (yellow at 1)
    # makes one.
    t = Scenario("regular", hands=["? ? ? ?", "G4 B4 W3 R3", "W4 B3 G3 R2",
                                   "G1 W1 B1 Y2"], stacks="R1 Y1")
    h = _hints(t)
    skip, one = h["hint p1 red"], h["hint p3 2s"]
    assert any("p2 should play R2" in r for r in skip.reasons)
    assert any("p1 then plays R3" in r for r in skip.reasons)
    assert skip.score > one.score + 15, (skip.reasons, one.reasons)


# ---- D19: multi-card hints play newest -> oldest ------------------------------------

def _three_twos():
    # "2" on three of my cards, red and blue at 1: newest plays first.
    t = Scenario("regular", hands=["? ? ? ?", "G4 W4 W3 G3", "Y4 B3 R3 W4"],
                 stacks="R1 B1")
    t.hint(1, 0, "2", touched=[0, 2, 3])
    return t


def test_after_the_newest_plays_the_next_touched_card_is_the_next_play():
    t = _three_twos()
    t.play(0, 3, "R2")
    assert t.my_slot(2) == {"B2"}            # the only 2 with somewhere to go
    assert advise(t.ms)[0].summary == "play slot 3"


def test_chain_stops_when_the_next_card_has_nowhere_to_go_and_stays_stopped():
    t = _three_twos()
    t.play(0, 3, "R2")
    t.play(0, 2, "B2")
    assert len(t.my_slot(0)) > 1             # no 2 is playable: hold it
    t.play(1, 0, "Y1", draw="R5")            # now Y2 could go, but the moment passed
    assert len(t.my_slot(0)) > 1
    assert not any(r.summary == "play slot 1" and r.score >= 100 for r in advise(t.ms))


def test_next_card_waits_on_a_teammates_visible_unlock():
    # "3" on two of my cards; red and green at 2, blue at 1, p2's newest is B2.
    # After R3 plays, my other 3 is G3 (playable) or B3 (waiting on p2's B2):
    # I wait for the B2 before playing it.
    t = Scenario("regular", hands=["? ? ? ?", "G4 W4 W1 Y4", "Y5 R4 W4 B2"],
                 stacks="R2 G2 B1")
    t.hint(1, 0, "3", touched=[1, 3])
    t.play(0, 3, "R3")
    assert t.my_slot(1) == {"G3", "B3"}
    assert not any(r.summary == "play slot 2" for r in advise(t.ms))
    t.play(2, 3, "B2", draw="G1")
    assert t.ms.view(0)[1].certainly_playable


def test_giver_counts_every_play_in_the_chain():
    # Red and blue at 1; p1's newest two are R2, B2: "2" plays both in a row.
    t = Scenario("regular", hands=["? ? ? ?", "G4 W4 B2 R2", "Y4 B3 R3 W4"],
                 stacks="R1 B1")
    two = _hints(t)["hint p1 2s"]
    assert "2 new playable card(s)" in two.reasons, two.reasons
    assert not any(r.startswith("ambiguous") for r in two.reasons)


def test_giver_sees_a_chain_card_that_would_play_wrong():
    # Red and blue at 1; p1's newest is R2, then a G2. After R2 plays, p1 reads
    # the next 2 as B2 (the only 2 with somewhere to go): it's G2, a strike.
    t = Scenario("regular", hands=["? ? ? ?", "G4 W4 G2 R2", "Y4 B3 R3 W4"],
                 stacks="R1 B1")
    two = _hints(t)["hint p1 2s"]
    assert any("G2" in r and "miss" in r and r.startswith("ambiguous") for r in two.reasons),         two.reasons
    assert two.score < 0


def test_giver_sees_its_hint_move_an_older_chain_on():
    # From self-play (regular 3p seed 8): p1 holds an old blue hint on B4 and B2
    # (newest), given while blue was empty. Now blue is at 1. My "2" makes p1
    # play the B2, which moves the old chain on: p1 reads the next blue as B3.
    # It's B4: a strike.
    t = Scenario("regular", hands=["? ? ? ?", "G4 B4 W3 B2", "R4 Y3 W4 B1"])
    t.hint(2, 1, "B")
    t.play(2, 3, "B1", draw="G1")
    two = _hints(t)["hint p1 2s"]
    assert any("B4 as playable and miss" in r for r in two.reasons), two.reasons
    assert two.score < 0


def test_a_play_known_by_convention_is_not_a_decline():
    # From self-play (regular 4p seed 4). p3's blue hint on p2's B4 makes p1's
    # newest card (B3) the unlock. I hint p1 green on a G2: a plain play hint
    # (D18). p1 plays the G2 first: "play what you know first", not a decline,
    # so the B3 stays expected of p1 (nobody else takes it over).
    t = Scenario("regular", hands=["? ? ? ?", "W5 G2 R1 B3", "W1 R5 G4 B4",
                                   "G5 B1 W4 G3"], stacks="R1 Y3 G1 B2 W2")
    t.hint(3, 2, "B")
    assert t.expected(1) == ["B3"]
    t.hint(0, 1, "G")
    t.play(1, 1, "G2", draw="Y1")
    assert t.expected(1) == ["B3"]


# ---- D20: a rank hint on the chop with nowhere to play is a last-copy save -------

def test_rank_hint_on_my_chop_with_nowhere_to_play_is_a_save():
    # No stack at 3, no 3 in anyone's playable slot, one Y4 discarded: "4" on
    # my oldest card is the other Y4 (a save), not a self skip-level.
    t = Scenario("short_rainbow", hands=["? ? ? ?", "R5 W1 G1 B4", "Y5 B2 R2 M1"],
                 stacks="R1 Y2 G4 B1 W2 M1", discards="Y4")
    t.hint(1, 0, "4", touched=[0])
    assert t.last().kind is HintKind.SAVE
    assert t.my_slot(0) == {"Y4", "M4"}      # M4 is a single copy in short rainbow
    assert not t.expected(0)                 # no blind play of my newest card


def test_rank_hint_on_my_chop_that_could_play_is_still_a_play():
    # Same, but red is at 3: "4" can be R4, a play.
    t = Scenario("short_rainbow", hands=["? ? ? ?", "R5 W1 G1 B4", "Y5 B2 R2 M1"],
                 stacks="R3 Y2 G4 B1 W2 M1", discards="Y4")
    t.hint(1, 0, "4", touched=[0])
    assert t.last().kind is HintKind.PLAY


def test_unlock_holder_must_read_the_hint_the_same_way():
    # From self-play (short rainbow 5p seed 5). Red on p2's M2 and R2: I see
    # p1's newest R1, so to me it's a skip-level on R2. p1 can't see their R1,
    # and M2 is a single copy, so to p1 it's a save of M2: p1 never plays the
    # R1, the others see a decline, and the next one blind-plays.
    t = Scenario("short_rainbow", hands=["? ? ? ?", "W5 W2 B3 R1", "G4 B4 M2 R2",
                                         "Y4 G3 W3 B2"], stacks="Y2 G1 W1")
    red = _hints(t)["hint p2 red"]
    assert any("p1 wouldn't know to play R1" in r for r in red.reasons), red.reasons
    assert red.score < 0


def test_lookahead_sees_a_last_copy_on_a_chop_even_with_tokens_left():
    # p1 has no known play and the last B2 on chop. With 5 tokens they might
    # still discard it (D21: nobody protected it), so anything that doesn't
    # protect it is charged.
    t = Scenario("regular", hands=["? ? ? ?", "B2 R4 W3 Y4", "Y1 B3 R3 W4"],
                 discards="B2", hints=5)
    recs = {r.summary: r for r in advise(t.ms)}
    other = recs["hint p2 1s"]
    assert any("might discard B2 (critical)" in r for r in other.reasons)
    assert advise(t.ms)[0].action.target == 1


def test_an_already_saved_card_does_not_join_a_later_chain():
    # From self-play (short rainbow 4p seed 36): "2" on my chop with no 2 able
    # to play saves it as a last-copy 2: G2 (one gone) or M2 (D20). Later G1
    # and W1 play, and another "2" touches it again plus a newly drawn card
    # (newest). After that plays, the saved card keeps its meaning: it isn't
    # "the next 2" (read as G2). It was M2.
    t = Scenario("short_rainbow", hands=["? ? ? ?", "R4 W3 Y4 G3", "Y3 B4 G1 R5",
                                         "G4 W1 Y4 R3"], discards="G2")
    t.hint(1, 0, "2", touched=[0])
    assert t.my_slot(0) == {"G2", "M2"}
    t.discard(0, 1, "G4")
    t.play(3, 1, "W1", draw="Y2")
    t.play(2, 2, "G1", draw="B1")
    t.hint(1, 0, "2", touched=[0, 3])
    t.play(0, 3, "W2")
    assert t.my_slot(0) == {"G2", "M2"}
    assert not any(r.summary == "play slot 1" for r in advise(t.ms))


def test_protective_discard_by_the_unlock_holder_is_not_a_decline():
    # p3 hints p1 yellow on Y3; p2's newest is Y2, and I might hold one too.
    # p2 has 1 token left and discards (a protective discard): that's a reason
    # to put the Y2 off, not a decline, so it doesn't fall to me yet. If p2
    # then does something else for no such reason, I take it as mine.
    t = Scenario("regular", hands=["? ? ? ?", "R4 B4 W3 Y3", "G3 W5 B5 Y2",
                                   "G4 B3 R1 W4"], stacks="Y1", hints=2)
    t.hint(3, 1, "Y")                     # tokens: 1
    assert t.ms.expected_of(2)
    t.discard(0, 0, "G2")                 # me
    t.hint(1, 3, "R")                     # p1 (tokens 0)
    t.discard(2, 0, "G3", draw="B1")      # p2 at 1 token: a protective discard
    assert t.ms.expected_of(2) and not t.ms.expected_of(0)
    assert any("protective discard; play delayed" in x for e in t.ms.expectations
               for x in e.log)

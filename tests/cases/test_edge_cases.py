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


def _ambiguous(r):
    """D18: a hint with a harmful reading is kept but scored below zero."""
    return r.rejected or (r.score < 0 and any(x.startswith("ambiguous:") for x in r.reasons))


def test_advisor_rejects_multi_card_hint_whose_newest_card_is_not_playable():
    bad = Scenario("regular", hands=["? ? ? ?", "R4 Y2 B4 Y3", "G4 B3 R3 W4",
                                     "G3 W5 B5 R2"], stacks="Y1")
    h = _hints(bad)["hint p1 yellow"]
    assert _ambiguous(h) and any("first" in r for r in h.reasons)
    good = Scenario("regular", hands=["? ? ? ?", "R4 Y3 B4 Y2", "G4 B3 R3 W4",
                                      "G3 W5 B5 R2"], stacks="Y1")
    assert not _ambiguous(_hints(good)["hint p1 yellow"])


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

def _protect_table(hints, **rules):
    # p1 has a hinted, playable R1; p2's chop is the last B2 (other one discarded).
    t = Scenario("regular", hands=["? ? ? ? ?", "R1 B4 W1 G3 Y3", "B2 W4 R3 G4 Y4"],
                 discards="B2", hints=hints + 1, **rules)
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
    # Official rules (play on after a last copy is lost): the protective
    # discard wins because it gains a token instead of spending one.
    t = _protect_table(1, end_when_perfect_lost=False)
    recs = {r.summary: r for r in advise(t.ms)}
    discard = recs["discard slot 1"]
    assert any("protective discard: tells p2" in r for r in discard.reasons)
    assert not any("lookahead" in r for r in discard.reasons)
    # A hint that doesn't save B2 leaves p2 with no token and B2 on chop.
    other = recs["hint p1 white"]         # a real play hint, but the last token
    assert any("B2 (critical)" in r for r in other.reasons)
    assert other.score < discard.score
    # The discard beats a direct save on B2: it gains a token instead (D15).
    assert discard.score > recs["hint p2 blue"].score
    assert advise(t.ms)[0].summary == "discard slot 1"


def test_house_rule_protective_discard_beats_the_save_when_my_chop_was_watched():
    # Our rules: losing a last copy ends the game. My blind chop might be one
    # (13%), but p2 just acted and saw it on my chop without protecting it, so
    # it's presumed safe (D21). Protective discards come first; the save hint
    # is the last resort.
    t = _protect_table(1)
    recs = advise(t.ms)
    assert recs[0].summary == "discard slot 1"
    discard = recs[0]
    assert any("protective discard: tells p2" in r for r in discard.reasons)
    assert any("presumed safe (D21)" in r for r in discard.reasons)


def test_house_rule_prefers_the_save_when_my_chop_wasnt_watched():
    # Same table, but my chop is new since p2 acted (I'd drawn and nobody had
    # looked at it as my chop yet): my own 13% risk counts in full, so the safe
    # save hint wins.
    t = _protect_table(1)
    t.ms.chops_before_last[0] = None
    recs = advise(t.ms)
    assert recs[0].summary == "hint p2 blue"


def test_save_hint_wins_when_the_signal_would_protect_the_wrong_card():
    # p1 has nothing to play, so a protective discard would protect p1's chop
    # (a G3, not needed). That reading is misleading (unsafe = game-ending), and
    # p2's last B2 is only saved by a direct hint.
    t = Scenario("regular", hands=["? ? ? ? ?", "G3 B4 W3 R3 Y3", "B2 W4 R3 G4 Y4"],
                 discards="B2", hints=1)
    recs = advise(t.ms)
    disc = next(r for r in recs if r.summary == "discard slot 1")
    assert any("misleading: p1 would read" in r for r in disc.reasons)
    assert recs[0].summary in ("hint p2 blue", "hint p2 2s")


def test_no_protective_reading_with_two_tokens():
    t = _protect_table(2)
    t.discard(0, 0, "G1")
    assert t.ms.notes == []


def test_zero_tokens_discarding_instead_of_a_known_play_is_protective():
    # p1 knows R1 is playable but discards at 0 tokens: p2's last B2 is protected.
    t = Scenario("regular", hands=["? ? ? ? ?", "R1 B4 W1 G3 Y3", "B2 W4 R3 G4 Y4",
                                   "G2 W2 R2 Y2 B3"], discards="B2", hints=1)
    t.hint(3, 1, "R")                     # hints -> 0; R1 expected of p1
    t.discard(1, 1, "B4", draw="G1")
    assert any("p2's slot 1 is unsafe" in n for n in t.ms.notes)


def test_zero_tokens_forced_discard_is_not_protective():
    # p1 has nothing to play: discarding is the default, not a signal.
    t = Scenario("regular", hands=["? ? ? ? ?", "R4 B4 W3 G3 Y3", "B2 W4 R3 G4 Y4",
                                   "G2 W2 R2 Y2 B3"], discards="B2", hints=0)
    t.discard(1, 0, "R4", draw="G1")
    assert t.ms.notes == []


def test_advisor_at_zero_tokens_discards_over_a_play_to_protect():
    # I know my newest is R1, but playing it leaves p1 with no token and their
    # last B2 on chop. Discarding gets a token back for them.
    t = Scenario("regular", hands=["? ? ? ?", "B2 W4 R3 G4", "G3 W3 R4 Y4"],
                 discards="B2", hints=1)
    t.hint(2, 0, "1", touched=[3])        # hints -> 0
    recs = {r.summary: r for r in advise(t.ms)}
    play, disc = recs["play slot 4"], recs["discard slot 1"]
    assert any("B2 (critical)" in r for r in play.reasons)
    assert any("protective discard: tells p1" in r for r in disc.reasons)
    assert disc.score > play.score


# ---- unsafe = game-ending (2026-11-26) ---------------------------------------------

def test_flag_on_my_chop_moves_my_chop_without_narrowing_it():
    # p2 discards with 1 token; p0 (me) has nothing known to play, so I'm the one
    # protected: my chop is treated as a last copy.
    t = Scenario("regular", hands=["? ? ? ? ?", "R3 B4 W3 G3 Y3", "B2 W4 R3 G4 Y4"],
                 hints=1)
    t.discard(2, 0, "B2", draw="G2")
    assert t.bs.public.hands[0][0].uid in t.ms.unsafe
    # The flag doesn't narrow what the card is (that caused confident misplays
    # when a flag was wrong); it only moves my chop to the next card.
    assert t.ms.view(0)[0].p_critical < 1.0
    from hanabi_meta.advisor.advisor import chop_index
    assert chop_index(t.ms, 0) == 1


def test_flag_drops_once_the_holder_knows_it_is_not_a_last_copy():
    # p0 discards at 1 token and p1 (nothing to play) reads their chop as a last
    # copy. It's really a G3 with both copies alive. Once hints show p1 it's G3,
    # it can't be critical, and the flag goes.
    t = Scenario("regular", hands=["? ? ? ? ?", "G3 B4 W4 R4 Y4", "B3 W1 R1 G4 Y2"],
                 hints=1)
    t.discard(0, 0, "G1")
    g3 = t.bs.public.hands[1][0].uid
    assert g3 in t.ms.unsafe
    t.hint(2, 1, "G")
    assert g3 in t.ms.unsafe                 # could still be G5
    t.hint(2, 1, "3")
    assert g3 not in t.ms.unsafe


def test_last_resort_discards_the_card_least_likely_to_end_the_game():
    # Every card of mine is hinted: two 4s (R4 and G4 each have a copy gone)
    # and three 1s. The "4" on my chop reads as a save (D20): it's the last R4
    # (p2 shows the last G4), so my other 4 isn't a last copy. The last resort
    # is never the saved R4, my oldest card.
    t = Scenario("regular", hands=["? ? ? ? ?", "R3 B4 W3 G3 Y3", "B3 W4 R3 G4 Y4"],
                 discards="R4 G4", hints=3)
    t.hint(1, 0, "4", touched=[0, 1])
    t.hint(2, 0, "1", touched=[2, 3, 4])
    disc = [r for r in advise(t.ms) if r.action.type.name == "DISCARD"]
    assert disc and all(r.action.slot != 0 for r in disc)


def test_misleading_hint_beats_a_certain_game_loss():
    # My hand is five hinted 5s. I have 1 token and no play, and every hint to
    # p1 is misleading. Discarding a 5 ends the game, so a misleading hint is
    # the last resort.
    t = Scenario("regular", hands=["? ? ? ? ?", "G4 R4 B2 B2 G3"], hints=2)
    t.hint(1, 0, "5", touched=[0, 1, 2, 3, 4])
    normal = advise(t.ms)
    assert all(r.score < -150 or r.action.is_hint for r in normal)
    assert normal[0].action.is_hint
    assert any("last resort: misleading" in r for r in normal[0].reasons)


def test_self_skip_hint_rejected_when_the_unlock_is_another_suit():
    # From self-play (rainbow 3p seed 5): "4" on p1's last B4 with blue at 1 and
    # no B2 visible. I mean a save, but p1 can't tell it's a last copy: they read
    # a self skip-level and play their newest card, W3, which plays. Then they
    # narrow the hinted 4 to white ("W4") and later blind-play the B4 as
    # certain. The hint is ambiguous: it costs a strike (D18).
    t = Scenario("regular", hands=["? ? ? ? ?", "B3 G1 B4 R5 W3", "R1 Y1 G5 B5 Y5"],
                 stacks="R2 Y2 G1 B1 W2", discards="B1 B4 R4", hints=5)
    recs = advise(t.ms, include_rejected=True)
    four = next(r for r in recs if r.summary == "hint p1 4s")
    assert _ambiguous(four) and four is not recs[0]
    assert any("read their hinted B4 as white" in x for x in four.reasons)


def test_hint_rejected_when_the_receiver_would_narrow_out_the_real_card():
    # From self-play (rainbow 4p seed 8): "green" on p1's G4 and G3 (newest),
    # green at 1, no G2 visible. I'd mean a save of the last G4, but p1 reads
    # newest-first (D13, D17): the G3 is "playable now" and narrows to G2, then
    # gets played as certain.
    # The M2 in p3's newest slot makes "M3, visibly unlocked" a reading too, so
    # the newest card isn't blind-played: it's narrowed, wrongly.
    t = Scenario("rainbow", hands=["? ? ? ?", "R5 W1 G4 G3", "Y3 Y4 B1 Y4", "W5 B4 R4 M2"],
                 stacks="R2 Y1 G1 B2 W1 M1", discards="G4", hints=3)
    recs = advise(t.ms, include_rejected=True)
    green = next(r for r in recs if r.summary == "hint p1 green")
    assert _ambiguous(green) and green is not recs[0]
    assert any("would narrow their G3" in x for x in green.reasons)

from pathlib import Path

import pytest

from hanabi_meta.advisor import advise
from hanabi_meta.cli.__main__ import main
from hanabi_meta.cli.game_file import GameFile, GameFileError
from hanabi_meta.engine import ActionType
from hanabi_meta.scenario import Scenario

EXAMPLE = Path(__file__).parent.parent / "examples" / "skip_level.txt"


def top(t: Scenario, **kw):
    return advise(t.ms, **kw)[0]


def by_summary(t: Scenario, summary: str, include_rejected=False):
    return next(r for r in advise(t.ms, include_rejected=include_rejected)
                if r.summary == summary)


def test_convention_play_is_top_advice():
    t = GameFile.parse(EXAMPLE.read_text()).build()
    best = top(t)
    assert best.summary == "play slot 4"
    assert any("skip-level" in r for r in best.reasons)


def test_misleading_skip_hint_is_rejected():
    # Nothing played, G4 in p1's hand, no G1-G3 visible: "green" would make
    # teammates think they hold the unlocks.
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R4 B4 W3 G4",
        "Y4 B3 R3 W4",
        "Y3 W5 B5 R4",
    ], hints=7)
    r = by_summary(t, "hint p1 green", include_rejected=True)
    assert r.rejected and "misleading" in r.reasons[-1]
    assert all(x.summary != "hint p1 green" for x in advise(t.ms))


def test_save_critical_card_on_chop():
    # p1's chop (oldest untouched) is the last B2. No B1 visible: a save.
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "B2 R4 W3 Y4",
        "Y4 B3 R3 W4",
        "Y3 W5 G5 R4",
    ], discards="B2", hints=5)
    best = top(t)
    assert best.action.type is ActionType.HINT_COLOR or best.action.type is ActionType.HINT_RANK
    assert best.action.target == 1
    assert any("chop" in r for r in best.reasons)


def test_safety_five_on_chop():
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R5 B4 W3 Y4",
        "Y4 B3 R3 W4",
        "Y3 W4 G4 R4",
    ], hints=5)
    r = by_summary(t, "hint p1 5s")
    assert any("protects a 5 on their chop" in x for x in r.reasons)
    assert r.score >= 70


def test_no_discard_at_max_hints():
    t = Scenario("regular", hands=["? ? ? ? ?", "R4 B4 W3 Y4 G4", "Y4 B3 R3 W4 G3"])
    assert all(r.action.type is not ActionType.DISCARD for r in advise(t.ms))


def test_discard_oldest_untouched_when_nothing_better():
    t = Scenario("regular", hands=["? ? ? ? ?", "R4 B4 W3 Y4 G4", "Y4 B3 R3 W4 G3"],
                 hints=0)
    best = top(t)
    assert best.summary == "discard slot 1"


def test_known_playable_beats_hints():
    t = Scenario("regular", hands=["? ? ? ? ?", "R4 B4 W3 Y4 G1", "Y4 B3 R3 W4 G3"],
                 hints=6)
    t.hint(1, 0, 1, touched=[2])
    assert top(t).summary == "play slot 3"


# ---- CLI / game file -----------------------------------------------------------

def test_cli_advise_prints_recommendation(capsys):
    assert main([str(EXAMPLE), "--advise"]) == 0
    out = capsys.readouterr().out
    assert "play slot 4" in out and "Y2" in out


def test_game_file_hint_to_me_and_roundtrip():
    gf = GameFile.parse("""
        variant rainbow
        players 3
        me 0
        hand 1 R4 B4 W3 G3 M1
        hand 2 G4 B3 R2 W4 Y2
        hint 1 me 1 @2,5   # p1 tells me slots 2 and 5 are 1s
    """)
    t = gf.build()
    views = t.ms.view(0)
    assert views[1].certainly_playable and views[4].certainly_playable
    assert GameFile.parse(gf.text()).build().bs.hints == t.bs.hints


def test_game_file_errors_are_clear():
    with pytest.raises(GameFileError, match="missing 'hand 2"):
        GameFile.parse("players 3\nhand 1 R1 R2 R3 R4 R5").build()
    with pytest.raises(GameFileError, match="action 1"):
        GameFile.parse("players 2\nhand 1 R1 R2 R3 R4 R5\nplay 1 9 R1 G1").build()


# ---- lookahead (D9) ------------------------------------------------------------

def test_last_hint_not_spent_when_next_player_must_discard_a_critical():
    # 1 hint left. p1 has nothing to play and a critical R5 on chop. If I spend
    # the last hint, p1 must discard R5. Discarding keeps a token for p1.
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R5 B4 W3 Y4",
        "G1 B3 R3 W4",
    ], hints=1)
    recs = advise(t.ms)
    green = next(r for r in recs if r.summary == "hint p2 green")
    assert any("would have no hint and discard R5" in x for x in green.reasons)
    assert recs[0].action.type is not ActionType.HINT_COLOR or recs[0].action.target == 1


def test_lookahead_quiet_when_next_player_can_play():
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "R5 B4 W3 Y1",
        "G1 B3 R3 W4",
    ], hints=2)
    t.hint(2, 1, 1)                          # p1 now knows Y1 is playable
    t.ms.bs.hints = 1
    recs = advise(t.ms)
    green = next(r for r in recs if r.summary == "hint p2 green")
    assert not any("lookahead" in x for x in green.reasons)

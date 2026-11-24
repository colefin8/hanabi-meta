from pathlib import Path

import pytest

from hanabi_meta.advisor import advise
from hanabi_meta.cli.__main__ import main as cli_main
from hanabi_meta.cli.game_file import GameFile
from hanabi_meta.conventions import HintKind
from hanabi_meta.engine import make_variant
from hanabi_meta.gamelog import read_games, replay
from hanabi_meta.scenario import Scenario
from hanabi_meta.selfplay import play_game

EXAMPLE = Path(__file__).parent.parent / "examples" / "skip_level.txt"


@pytest.mark.parametrize("kind", ["regular", "rainbow"])
def test_selfplay_game_logs_and_replays_exactly(tmp_path, kind):
    log = tmp_path / "games.jsonl"
    res = play_game(make_variant(kind, 2), seed=3, recorder_path=log, log_views=True)
    [g] = list(read_games(log))
    assert g.start["source"] == "selfplay" and g.end["score"] == res.score
    assert len(g.turns) == res.turns
    assert set(g.turns[0]["views_before"]) == {"0", "1"}
    assert g.turns[0]["advice"]
    game = replay(g)                       # raises if anything diverges
    assert game.score == res.score


def test_selfplay_never_misplays_a_certain_card():
    res = play_game(make_variant("regular", 3), seed=11)
    assert res.plays[("certain", "miss")] == 0
    assert res.score > 0


def test_live_game_log_roundtrip(tmp_path):
    log = tmp_path / "live.jsonl"
    GameFile.parse(EXAMPLE.read_text()).to_log().append_to(log)
    [g] = list(read_games(log))
    assert g.start["source"] == "live" and g.start["observer"] == 0
    assert g.start["snapshot"][0].startswith("variant")
    assert [t["note"] for t in g.turns] == ["hint 2 1 yellow", "hint 3 2 red"]
    assert g.turns[0]["events"][0]["kind"] == "hint"
    assert "0" in g.turns[0]["views_before"]
    with pytest.raises(ValueError, match="deck order"):
        replay(g)


def test_cli_log_command(tmp_path, monkeypatch, capsys):
    log = tmp_path / "x.jsonl"
    lines = iter([f"log {log}", "quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(lines))
    cli_main([str(EXAMPLE)])
    assert len(list(read_games(log))) == 1


# ---- regressions found by self-play ----------------------------------------------

def test_rehinting_a_saved_five_with_its_color_is_rejected():
    # Found in self-play: "green" on an already-hinted G5 made teammates read a
    # multi-level skip and blind-play their newest cards.
    t = Scenario("regular", hands=["? ? ? ? ?", "R4 B4 W3 Y3 G5", "Y4 B3 R3 W4 Y2"],
                 stacks="G2", hints=6)
    t.hint(2, 1, 5)                       # safety hint on G5
    r = next(x for x in advise(t.ms, include_rejected=True)
             if x.summary == "hint p1 green")
    assert r.rejected


def test_playable_five_signal_needs_a_high_enough_stack():
    t = Scenario("regular", hands=[
        "? ? ? ?",
        "G4 B3 Y3 W4",
        "Y4 B4 R1 W3",
        "G3 W5 B5 Y2",
    ], stacks="R1")
    t.hint(1, 2, "R")
    t.discard(2, 2, "R1", draw="G2")
    assert t.last().kind is HintKind.PLAYABLE_FIVE
    assert t.last().expectations == []
    assert t.expected(0) == []

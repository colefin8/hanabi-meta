import pytest

from hanabi_meta.cli.__main__ import main as cli_main
from hanabi_meta.cli.game_file import GameFile, GameFileError
from hanabi_meta.engine import make_variant
from hanabi_meta.gamelog import read_games, replay
from hanabi_meta.selfplay import play_game

HEAD = """variant regular
players 3
spectator
hand 0 R1 Y1 G1 B1 W1
hand 1 R2 Y2 G2 B2 W2
hand 2 R3 Y3 G3 B3 W3
"""


def selfplay_as_spectator_file(tmp_path, kind: str, players: int, seed: int):
    """Play a bot game, then write it out the way a spectator would type it."""
    log = tmp_path / "bots.jsonl"
    res = play_game(make_variant(kind, players), seed=seed, recorder_path=log)
    [g] = list(read_games(log))
    v = g.variant
    hands: dict[int, list[str]] = {}
    for e in g.deal:
        hands.setdefault(e["player"], []).append(e["card"])
    lines = [f"variant {kind}", f"players {players}", "spectator"]
    lines += [f"hand {p} {' '.join(cs)}" for p, cs in sorted(hands.items())]
    for t in g.turns:
        a, evs = t["action"], t["events"]
        if a["type"].startswith("hint"):
            val = a["value"] if a["type"] == "hint_rank" else v.suits[a["value"]].name
            lines.append(f"hint {t['player']} {a['target']} {val}")
        else:
            card = next(e["card"] for e in evs if e["kind"] in ("play", "discard"))
            drawn = next((e["card"] for e in evs if e["kind"] == "draw"), "")
            lines.append(f"{a['type']} {t['player']} {a['slot'] + 1} {card} {drawn}".rstrip())
    return res, "\n".join(lines) + "\n"


@pytest.mark.parametrize("kind,players,seed", [("regular", 3, 5), ("rainbow", 4, 2),
                                               ("rainbow_all_colors", 2, 7)])
def test_full_game_typed_by_a_spectator_matches_the_engine(tmp_path, kind, players, seed):
    res, text = selfplay_as_spectator_file(tmp_path, kind, players, seed)
    gf = GameFile.parse(text)
    sg = gf.build_spectator()
    assert sg.table.game.score == res.score and sg.table.game.is_over

    out = tmp_path / "spectator.jsonl"
    gf.to_log().append_to(out)
    [g] = list(read_games(out))
    assert g.start["source"] == "spectator" and g.end["finished"] is True
    t0 = g.turns[0]
    assert set(t0["views_before"]) == {str(p) for p in range(players)}
    assert t0["advice"] and "advice_rank" in t0
    # the bots always follow the advisor's first choice
    assert all(t["advice_rank"] == 0 for t in g.turns)
    assert replay(g).score == res.score          # deck known: exact replay


def test_spectator_reports_how_the_receiver_read_a_hint():
    head = HEAD.replace("hand 1 R2 Y2 G2 B2 W2", "hand 1 R2 Y2 G2 B2 R1")
    head = head.replace("hand 0 R1 Y1", "hand 0 R4 Y1")
    sg = GameFile.parse(head + "hint 0 1 1\n").build_spectator()
    assert sg.notes[-1].startswith("p1 reads it as play")


@pytest.mark.parametrize("line,msg", [
    ("hint 1 2 red", "p0's turn, not p1"),
    ("play 0 1 R2 G4", "slot 1 is R1, not R2"),
    ("play 0 1 R1", "say what p0 drew"),
    ("hint 0 1 red @1,2", "touches slots 1"),
    ("discard 0 1 R1 R1 extra", "cannot discard with all hint tokens"),
])
def test_spectator_catches_typos_and_missed_turns(line, msg):
    with pytest.raises(GameFileError, match=msg):
        GameFile.parse(HEAD + line + "\n").build_spectator()


def test_spectator_must_start_from_the_deal():
    with pytest.raises(GameFileError, match="start from the deal"):
        GameFile.parse(HEAD + "stacks R1\n").build_spectator()


def test_spectator_refuses_impossible_card_counts():
    with pytest.raises(GameFileError, match="more copies than exist of: R5"):
        GameFile.parse(HEAD + "play 0 1 R1 R5\nplay 1 1 R2 R5\n").build_spectator()


def test_cli_spectator_advise(tmp_path, capsys):
    f = tmp_path / "s.txt"
    f.write_text(HEAD + "play 0 1 R1 R4\n")
    assert cli_main([str(f), "--advise"]) == 0
    out = capsys.readouterr().out
    assert "p1 to act" in out and "advice for p1" in out
    assert "[1] R2 = " in out                     # real card shown beside p1's knowledge

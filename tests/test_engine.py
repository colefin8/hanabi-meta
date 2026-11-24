import pytest

from hanabi_meta.engine import (Action, Card, DiscardEvent, DrawEvent, Game, HintEvent,
                                IllegalAction, PlayEvent, Variant, VARIANT_KINDS,
                                make_variant)

R, Y, G, B, W, M = range(6)


def stacked_deck(variant: Variant, first: list[str]) -> list[Card]:
    """A legal deck whose first cards are `first` (in order), rest arbitrary."""
    rest = variant.deck()
    head = [variant.parse_card(t) for t in first]
    for c in head:
        rest.remove(c)
    return head + rest


# ---- variant composition -----------------------------------------------------

@pytest.mark.parametrize("kind,size,suits", [
    ("regular", 50, 5), ("rainbow", 60, 6), ("rainbow_all_colors", 60, 6),
    ("short_rainbow", 56, 6)])
def test_deck_sizes(kind, size, suits):
    v = make_variant(kind, 3)
    assert len(v.deck()) == size
    assert v.num_suits == suits
    assert v.max_score == 5 * suits


@pytest.mark.parametrize("n,hand", [(2, 5), (3, 5), (4, 4), (5, 4)])
def test_hand_sizes(n, hand):
    for kind in VARIANT_KINDS:
        g = Game(make_variant(kind, n), seed=1)
        assert all(len(h) == hand for h in g.hands)


def test_hint_colors_per_variant():
    assert make_variant("regular", 2).hint_colors == (R, Y, G, B, W)
    assert make_variant("rainbow", 2).hint_colors == (R, Y, G, B, W, M)
    assert make_variant("short_rainbow", 2).hint_colors == (R, Y, G, B, W, M)
    assert make_variant("rainbow_all_colors", 2).hint_colors == (R, Y, G, B, W)


def test_variant_roundtrip():
    v = make_variant("short_rainbow", 4)
    assert Variant.from_dict(v.to_dict()) == v


# ---- rainbow touching ------------------------------------------------------------

@pytest.mark.parametrize("kind", ["rainbow", "rainbow_all_colors", "short_rainbow"])
def test_every_color_touches_rainbow(kind):
    v = make_variant(kind, 2)
    m3 = Card(M, 3)
    for c in (R, Y, G, B, W):
        assert v.color_touches(c, m3)
    assert not v.color_touches(R, Card(B, 3))


def test_rainbow_hint_touches_only_rainbow():
    v = make_variant("rainbow", 2)
    assert v.color_touches(M, Card(M, 1))
    assert not v.color_touches(M, Card(R, 1))


def test_hint_resolution_with_rainbow_in_hand():
    v = make_variant("rainbow", 2)
    # player 0: R1 Y1 G1 B1 W1 ; player 1: M1 R2 B2 M2 G3
    deck = stacked_deck(v, ["R1", "Y1", "G1", "B1", "W1", "M1", "R2", "B2", "M2", "G3"])
    g = Game(v, deck=deck)
    rec = g.step(Action.hint_color(1, R))
    assert rec.events == [HintEvent(0, 1, "color", R, (0, 1, 3))]
    assert g.hints == 7
    # Now player 1 to act. Player 0 holds no rainbow, so a rainbow hint is empty.
    assert g.check_legal(Action.hint_color(0, M)) == "hint touches no cards"
    rec = g.step(Action.hint_color(0, R))
    assert rec.events == [HintEvent(1, 0, "color", R, (0,))]


def test_rainbow_hint_illegal_in_all_colors_variant():
    v = make_variant("rainbow_all_colors", 2)
    g = Game(v, seed=3)
    assert g.check_legal(Action.hint_color(1, M)) == "color cannot be hinted in this variant"


# ---- legality ----------------------------------------------------------------------

def test_empty_hint_illegal_by_default_and_flag():
    v = make_variant("regular", 2)
    deck = stacked_deck(v, ["R1"] * 3 + ["R2"] * 2 + ["Y1"] * 3 + ["Y2"] * 2)
    g = Game(v, deck=deck)
    assert g.check_legal(Action.hint_color(1, B)) == "hint touches no cards"
    g2 = Game(make_variant("regular", 2, allow_empty_hints=True), deck=deck)
    assert g2.check_legal(Action.hint_color(1, B)) is None


def test_cannot_discard_at_max_hints():
    g = Game(make_variant("regular", 3), seed=0)
    assert g.check_legal(Action.discard(0)) is not None
    assert all(a.type.value != "discard" for a in g.legal_actions())


def test_no_self_hint_and_no_tokens():
    g = Game(make_variant("regular", 3), seed=0)
    assert g.check_legal(Action.hint_rank(0, 1)) == "bad hint target"
    g.hints = 0
    assert g.check_legal(Action.hint_rank(1, 1)) == "no hint tokens"
    with pytest.raises(IllegalAction):
        g.step(Action.hint_rank(1, 1))


# ---- play / discard / draw / slot shifting ------------------------------------------

def test_play_shift_and_draw_to_newest_slot():
    v = make_variant("regular", 2)
    deck = stacked_deck(v, ["Y3", "R1", "G4", "B2", "W5",  # p0
                            "R2", "R3", "R4", "R5", "Y1",  # p1
                            "G1"])                         # next draw
    g = Game(v, deck=deck)
    rec = g.step(Action.play(1))  # R1 from slot 1
    assert rec.events[0] == PlayEvent(0, 1, Card(R, 1), True)
    assert rec.events[1] == DrawEvent(0, Card(G, 1))
    assert [v.card_str(c) for c in g.hands[0]] == ["Y3", "G4", "B2", "W5", "G1"]
    assert g.stacks[R] == 1


def test_misplay_strikes_and_discards():
    v = make_variant("regular", 2)
    deck = stacked_deck(v, ["Y3", "R1", "G4", "B2", "W5"])
    g = Game(v, deck=deck)
    rec = g.step(Action.play(0))
    assert rec.events[0] == PlayEvent(0, 0, Card(Y, 3), False)
    assert g.strikes == 1 and g.discards == [Card(Y, 3)]


def test_discard_regains_hint():
    g = Game(make_variant("regular", 2), seed=5)
    g.step(Action.hint_rank(1, g.hands[1][0].rank))
    assert g.hints == 7
    rec = g.step(Action.discard(0))
    assert isinstance(rec.events[0], DiscardEvent)
    assert g.hints == 8


def test_playing_five_returns_hint():
    v = make_variant("regular", 2)
    g = Game(v, seed=0)
    g.hands[0][0] = Card(R, 5)
    g.stacks[R] = 4
    g.hints = 5
    g.step(Action.play(0))
    assert g.hints == 6 and g.stacks[R] == 5


def test_strikeout_scores_zero():
    v = make_variant("regular", 2)
    g = Game(v, seed=0)
    g.stacks[R] = 3
    g.hands[0][0] = Card(B, 5)
    g.strikes = 2
    g.step(Action.play(0))
    assert g.is_over and g.score == 0
    g2 = Game(make_variant("regular", 2, zero_score_on_strikeout=False), seed=0)
    g2.stacks[R] = 3
    g2.hands[0][0] = Card(B, 5)
    g2.strikes = 2
    g2.step(Action.play(0))
    assert g2.score == 3


@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_final_round_each_player_gets_one_turn(n):
    v = make_variant("regular", n)
    g = Game(v, seed=11)
    g.hints = 0
    # Burn the deck down to one card by misplaying is unsafe (strikes); instead
    # shrink the deck directly and keep discarding.
    while len(g.deck) > 1:
        g.deck.pop()
    last_drawer = g.current
    g.step(Action.discard(0))
    assert not g.deck and g.turns_left == n
    for _ in range(n - 1):
        assert not g.is_over
        g.hints = 0
        g.step(Action.discard(0))
    assert not g.is_over and g.current == last_drawer
    g.hints = 0
    g.step(Action.discard(0))
    assert g.is_over


@pytest.mark.parametrize("kind", VARIANT_KINDS)
@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_random_games_terminate_and_conserve_cards(kind, n):
    import random
    v = make_variant(kind, n)
    for seed in range(5):
        g = Game(v, seed=seed)
        rng = random.Random(seed)
        while not g.is_over:
            g.step(rng.choice(g.legal_actions()))
        in_hands = sum(len(h) for h in g.hands)
        assert in_hands + len(g.deck) + len(g.discards) + sum(g.stacks) == len(v.deck())
        assert 0 <= g.score <= v.max_score


def test_seeded_deck_is_reproducible():
    v = make_variant("rainbow", 3)
    assert Game(v, seed=42).initial_deck == Game(v, seed=42).initial_deck
    assert Game(v, seed=42).initial_deck != Game(v, seed=43).initial_deck


def test_scenario_and_cli_refuse_rainbow_hint_in_all_colors_variant():
    from hanabi_meta.cli.game_file import GameFile, GameFileError
    gf = GameFile.parse("variant rainbow_all_colors\nplayers 2\nhand 1 M1 R2 Y3 G4 B5\n"
                        "hint 0 1 rainbow\n")
    with pytest.raises(GameFileError, match="cannot be hinted"):
        gf.build()
    # any color hint touches the rainbow card instead
    t = GameFile.parse("variant rainbow_all_colors\nplayers 2\nhand 1 M1 R2 Y3 G4 B5\n"
                       "hint 0 1 yellow\n").build()
    assert t.bs.public.hands[1][0].touched and t.bs.public.hands[1][2].touched

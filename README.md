## VERY MUCH A WORK IN PROGRESS
# hanabi-meta

A live Hanabi advisor that reasons under **our group's conventions ("Meta")**,
not generic AI conventions. Pure Python 3.10+, no runtime dependencies.

## Setup

```powershell
git clone https://github.com/colefin8/hanabi-meta.git
cd hanabi-meta
python -m venv .venv
.venv\Scripts\python -m pip install pytest
.venv\Scripts\python -m pytest -q
```

(On macOS/Linux use `.venv/bin/python` instead of `.venv\Scripts\python`.)

## Status

| Milestone | Status |
|---|---|
| M1 Engine + variant config (all 4 variants, 2–5 players) | done, tested |
| M2 Belief tracker layers 1–3 (bookkeeping, slot candidates, per-player views) | done, tested |
| M3 Skip-level + shotgun convention, convention layer (layer 4) | done, tested |
| M4 Advisor (scoring, explanations, lookahead) and CLI | done, tested |
| M5 Trash-hint, safety-swap, playable-5, protective-discard conventions | done, tested |
| M6 JSONL logging + self-play harness | done, tested |
| M7 (optional) HLE cross-check test for the regular variant | not started |

## Running it during a real game

The advisor only knows what you type, so one person keeps it up to date as the
game goes. Try it first on the example game:

```powershell
.venv\Scripts\python -m hanabi_meta.cli examples\skip_level.txt
```

### 1. Start it

```powershell
.venv\Scripts\python -m hanabi_meta.cli
```

### 2. Set up the table (once, after the deal)

Number the players 0, 1, 2, … in turn order. Type each hand **oldest to newest**
(left to right). Card letters: R Y G B W, and M for rainbow. Don't type your own
hand; it's unknown.

```
variant regular          # regular | rainbow | rainbow_all_colors | short_rainbow
players 4
me 0
hand 1 R4 B4 W3 Y3
hand 2 G4 B3 R1 W4
hand 3 G3 W5 B5 Y2
```

Joining mid-game? Also add `stacks Y1 R2`, `discards B2 R1`, `hints 5` and
`strikes 1` as needed (defaults: empty stacks, 8 hints, 0 strikes).

### 3. Type every action, in turn order

Slots are numbered 1..N from the oldest card.

| What happened | Type | Notes |
|---|---|---|
| Hint between other players | `hint 2 1 yellow` | giver, target, value; touched cards are worked out |
| Number hint | `hint 2 1 3` | |
| Hint to you | `hint 1 me 3 @1,4` | list which of your slots were touched |
| Someone else plays / discards | `play 3 4 Y2 G1`, `discard 2 1 B2 R5` | player, slot, card, then the card they drew |
| You play / discard | `play me 5 Y2`, `discard me 1 G2` | no drawn card: you can't see it |

In `rainbow_all_colors` you can't hint rainbow; hint a color, which also touches
rainbow cards. After each line it prints `ok` and how it read a hint, so you can
check it against how the table read it.

### 4. On your turn

Type `advise` for ranked suggestions with reasons. `advise all` also lists the
hints it rejected as misleading, and why.

### Other commands

| Command | Does |
|---|---|
| `show` | the table, what you know about each of your slots, pending convention plays |
| `undo` | drop the last line (mistypes, or to fix a missed turn) |
| `save game.txt` | save the game; reload with `.venv\Scripts\python -m hanabi_meta.cli game.txt` |
| `log games.jsonl` | append the game to a JSONL log ([docs/LOG_FORMAT.md](docs/LOG_FORMAT.md)) |
| `help`, `quit` | |

Tips: turn order matters, since conventions read meaning from who acted when. If
you miss a turn, `undo` back to it and retype. Typing each action together with
the card drawn, right after the draw, keeps up best. Saved games where it misread
a hint make good test cases.

## Watching as a spectator

Someone outside the game who can see every hand (standing behind the table, or
watching an online game) can log it instead. That gives the best data: every
turn records what the acting player could see, what the advisor would have done
in their place, and what they actually did. Nobody playing has to type anything.

Put `spectator` where `me` would go, list **every** hand as dealt, and give the
drawn card on every play and discard. Number the players from whoever takes the
first turn (player 0), in turn order. It must start from the deal.

```
variant regular
players 3
spectator
hand 0 R4 Y1 G1 B1 W1
hand 1 R2 Y2 G2 B2 R1
hand 2 R3 Y3 G3 B3 W3

hint 0 1 1                # no @slots: it works out which cards were touched
play 1 5 R1 G4            # player, slot, card played, card drawn
```

Each line is checked against the full game, so typos and missed turns are caught
right away ("it's p2's turn, not p0", "p1's slot 3 is G2, not B2"). After each
hint it shows how the receiver reads it. `show` gives the table from the next
player's seat, with each real card beside what that player knows about it;
`advise` gives the advice for them. When the game ends, `log games.jsonl`. These
logs include the deck order, so they can be replayed exactly.

Full syntax is in `hanabi_meta/cli/game_file.py`. Scoring weights live in
`advisor.Weights`, and each recommendation lists the reasons behind its score.


## Self-play

```powershell
.venv\Scripts\python -m hanabi_meta.selfplay --variant all --players 2 3 4 5 --games 10
.venv\Scripts\python -m hanabi_meta.selfplay --games 20 --log selfplay.jsonl --views
```

Every seat is a Meta agent that follows the advisor. The summary shows:
- score and strikeouts;
- hit/miss rates for plays that were certain, convention-inferred or risky;
- which hint readings fired;
- how expectations resolved.

Run it after changing a convention or a weight, to catch regressions.

## Layout

```
hanabi_meta/
  engine/        variant.py (config), actions.py (actions + public events), game.py (rules)
  belief/        bookkeeping.py (L1), slots.py (L2), tracker.py (L3 views)
                 hypotheses.py (L4, planned): enumerate own-hand hypotheses, prune by conventions
  conventions/   base.py (Interpretation, Expectation), skip_level.py (skip-level + shotgun),
                 meta_state.py (MetaState: belief + interpretations + expectations, updated
                 by what players did and did not do), trash_hint.py, safety_swap.py,
                 playable_five.py, protective_discard.py
  scenario.py    build a table situation from text, e.g. hands=["? ? ? ?", "R4 B4 W3 Y3"]
  table.py       engine game + one MetaState per seat (self-play and spectator mode)
  advisor/       advisor.py: enumerate + score actions, simulate hints through the
                 conventions, reject misleading hints, look ahead at the next players
  cli/           game_file.py (text format), spectator.py (outside observer mode),
                 __main__.py (REPL and --advise)
  gamelog/       JSONL recorder/reader/replay (named to avoid shadowing stdlib `logging`)
  selfplay/      Meta agents that use the advisor; regression + convention stats
tests/
  test_engine.py, test_belief.py
  cases/         one file per convention of concrete table situations (see
                 test_skip_level.py; copy a test to add a real game situation)
```

### Key design points

* **Slots:** slot 0 = oldest (left-most). Plays/discards slide everything left; the
  new card goes on the right. Slot knowledge is stored on `SlotInfo` objects that
  follow the physical card, so the safety-swap reorder is just `PublicKnowledge.permute`.
* **Events are the interface.** The engine emits `HintEvent / PlayEvent / DiscardEvent /
  DrawEvent`. The belief tracker consumes them from one observer's point of view (own draws
  masked). A human entering a live game produces exactly the same events, so the advisor
  never needs an omniscient `Game`.
* **Theory of mind:** `BeliefState.view(p)` gives what player p can deduce about their own
  hand. For p ≠ observer this is a *lower bound*: p sees the observer's hand, the observer
  doesn't. Layer 4 will fix that by enumerating observer-hand hypotheses.
* **Probabilities** are per-slot marginals weighted by unseen copies (not a full joint
  distribution). Good enough for scoring; layer 4 hypotheses give the joint when needed.
* **Soundness test:** across random games in all variants and player counts, the real card
  is always in every observer's candidate set for every slot.

## Variant assumptions (all are config flags in `engine/variant.py`)

| Variant (`make_variant(kind, n)`) | Suits | Rainbow copies | Own "rainbow" hint | Touched by every color |
|---|---|---|---|---|
| `regular` | 5 | – | – | – |
| `rainbow` | 6 | 3/2/2/2/1 (10 cards) | yes | yes |
| `rainbow_all_colors` | 6 | 3/2/2/2/1 (10 cards) | **no** | yes |
| `short_rainbow` | 6 | 2/1/1/1/1 (6 cards) | yes | yes |

* A "rainbow" hint (where it exists) touches only rainbow cards.
* Rank hints work normally; rainbow cards are not special for rank.
* Max score is 30 in every rainbow variant.
* **Our table's rules** (the defaults; they differ from the official rules):
  * The game ends as soon as a perfect game (every suit to 5) is impossible: every copy
    of a still-needed card has been discarded or misplayed, or more cards are still
    needed than turns remain. `end_when_perfect_lost=True` (official: `False`).
  * Playing a 5 does **not** return a hint token. `five_returns_hint=False` (official: `True`).
  * The score when the game ends is still recorded (useful for training), but the goal
    is a perfect game. The advisor charges `Weights.game_loss` for losing a last copy, so
    a safe move beats a risky one that could end the game (e.g. a blind play that might
    be the 5 while the stack is on 3).
* Other rules flags with their defaults (official rules as I understand them):
  `allow_empty_hints=False` (a hint must touch ≥1 card), `allow_discard_at_max_hints=False`,
  `zero_score_on_strikeout=True`, `max_hints=8`, `max_strikes=3`.
* Final round: when the last card is drawn, every player including the one who drew it
  gets exactly one more turn.
* Dealing is player-major (player 0 gets the first cards). Only matters for replaying a
  known deck order.

## Open questions

See [docs/QUESTIONS.md](docs/QUESTIONS.md). Answers will be recorded there and folded into
the convention modules as they come in.

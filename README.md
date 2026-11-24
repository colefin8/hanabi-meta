# hanabi-meta

A live Hanabi advisor that reasons under **our group's conventions ("Meta")**,
not generic AI conventions. Pure Python 3.10+, no runtime dependencies.

```powershell
python -m venv .venv; .venv\Scripts\python -m pip install pytest
.venv\Scripts\python -m pytest -q
```

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

## Using the advisor

```powershell
.venv\Scripts\python -m hanabi_meta.cli examples\skip_level.txt --advise
.venv\Scripts\python -m hanabi_meta.cli            # interactive: type the game as it happens
```

In interactive mode, type game-file lines (`players 4`, `hand 1 R4 B4 W3 Y3`,
`hint 2 1 yellow`, `hint 1 me 3 @1,4`, `play 3 4 Y2 G1`, `discard me 1 G2`). You can
also use `show`, `advise`, `advise all` (also lists rejected misleading hints), `undo`
and `save game.txt`. Slots are numbered 1..N from the oldest card. Full syntax is in
`hanabi_meta/cli/game_file.py`. A saved game file can be reloaded later or turned
into a test case.

Scoring weights live in `advisor.Weights`, and each recommendation lists the reasons
behind its score.

To record a live game, type `log games.jsonl` in the CLI. It appends the game, with
your view and the advisor's suggestions on each of your turns. The format is in
[docs/LOG_FORMAT.md](docs/LOG_FORMAT.md).

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
  advisor/       advisor.py: enumerate + score actions, simulate hints through the
                 conventions, reject misleading hints, look ahead at the next players
  cli/           game_file.py (text format), __main__.py (REPL and --advise)
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
* Rules flags with their defaults (official rules as I understand them):
  `allow_empty_hints=False` (a hint must touch ≥1 card), `allow_discard_at_max_hints=False`,
  `zero_score_on_strikeout=True`, `five_returns_hint=True`, `max_hints=8`, `max_strikes=3`.
* Final round: when the last card is drawn, every player including the one who drew it
  gets exactly one more turn.
* Dealing is player-major (player 0 gets the first cards). Only matters for replaying a
  known deck order.

## Open questions

See [docs/QUESTIONS.md](docs/QUESTIONS.md). Answers will be recorded there and folded into
the convention modules as they come in.

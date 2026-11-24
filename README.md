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
| M3 Skip-level convention + hypothesis pruning (layer 4) | **blocked on the questions below** |
| M4 Advisor (scoring + explanations) and CLI | not started |
| M5 Shotgun, safety-swap, playable-5 conventions | blocked on questions |
| M6 JSONL logging + self-play harness | not started |
| M7 (optional) HLE cross-check test for the regular variant | not started |

## Layout

```
hanabi_meta/
  engine/        variant.py (config), actions.py (actions + public events), game.py (rules)
  belief/        bookkeeping.py (L1), slots.py (L2), tracker.py (L3 views)
                 hypotheses.py (L4, planned): enumerate own-hand hypotheses, prune by conventions
  conventions/   (planned) one module per convention: skip_level.py, shotgun.py,
                 safety_swap.py, playable_five.py. Each exposes
                   expected_actions(state, player) -> set of actions a Meta player would take
                   on_action(state, event) -> updated expectations / inferences
  advisor/       (planned) enumerate + score actions, human-readable explanation per action
  cli/           (planned) enter a state or an incremental action log, print recommendation
  gamelog/       (planned) JSONL writer/reader (named to avoid shadowing stdlib `logging`)
  selfplay/      (planned) Meta agents that use the advisor; regression + convention stats
tests/
  test_engine.py, test_belief.py
  cases/         (planned) one file per convention of concrete table situations, in a
                 short text format, so adding a real game situation is a few lines
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

# Self-play findings: why games aren't perfect (2026-11-26)

400 games: 4 variants × 2–5 players × 25 seeds (0–24), our table rules (the game
ends as soon as a perfect game is impossible). Reproduce:

```powershell
.venv\Scripts\python -m hanabi_meta.selfplay --variant all --players 2 3 4 5 --games 25 --log logs\selfplay.jsonl --views
.venv\Scripts\python -m hanabi_meta.selfplay.analyze logs\selfplay.jsonl --examples 2 --json logs\analysis.json
```

**Result: 0/400 perfect.** Median loss on turn 29 at score 7 (mean 7.6, max 25).
In 307 games a needed last copy was discarded, 56 ran out of pace, and 37 misplayed
a last copy. There were no strikeouts.

## Loss patterns (count / 400)

| # | Pattern | Count | Notes |
|---|---|---|---|
| 1 | **Discarded a hinted last copy** | 141 | 112 of them are 5s. Advisor reason: "every card is hinted or flagged unsafe: oldest card as a last resort". Only 49 hands were genuinely fully hinted; in **92** the hand still had unhinted cards, but every one was flagged unsafe by protective discards. The fallback then discards slot 1, usually a saved 5. |
| 2 | **Pace**: more cards needed than turns left | 56 | Mostly at 0 tokens (42). Top in regular 3p/5p. Too many discards per play (hints aren't efficient enough). Cards discarded on the losing turn were often 1s (23). |
| 3 | **Discarded an unhinted card that wasn't the plain chop** | 41 (5s) + 38 (others) | The advisor's chop skipped cards flagged unsafe and landed on a 5 or last copy. Teammates never saw it on chop, so nobody saved it. |
| 4 | **Missed save**: unhinted last copy on chop, a teammate had a token | 40 + 9 (5s) | The teammate played or hinted something else instead of saving. |
| 5 | **Unhinted last copy discarded, moved/drawn late** | 21 + 8 (5s) | Arrived on chop after teammates had acted (e.g. after a safety swap or a play). |
| 6 | **Misplay of a hinted last copy** | 28 | **13 were "certainly playable" plays that missed, all in rainbow variants.** The actor's candidates had collapsed to one wrong card (e.g. thought B3, was R3). That's a belief/convention-narrowing bug, not bad luck. The rest were risky 60–80% plays at 0–1 tokens. |
| 7 | Blind-play misplay of a last 5 / copy | 6 | |
| 8 | Unhinted last copy on chop, teammates at 0 tokens | 8 | |

Hint tokens before the losing discard: 0 → 104, 1 → 161, 2+ → 42. Almost every
discard loss happens at 0–1 tokens, the protective-discard regime.

**Protective-discard flags are involved in 221 of the 307 losing discards** (patterns
1 and 3). The flags seem to accumulate until they cover the whole unhinted part of
the hand, after which the chop / last-resort logic picks something worse.

## Most common pattern per table

| | 2p | 3p | 4p | 5p |
|---|---|---|---|---|
| regular | hinted last copy 16/25 | pace 12/25 | hinted last copy 9/25 | pace 11/25 |
| rainbow | hinted last copy 11/25 | unhinted 5, not chop 8/25 | hinted last copy 11/25 | hinted last copy 8/25 |
| rainbow_all_colors | hinted last copy 11/25 | unhinted 5, not chop 7/25 | hinted last copy 9/25 | hinted last copy 9/25 |
| short_rainbow | hinted last copy 12/25 | hinted last copy 9/25 | hinted last copy 7/25 | pace 7/25 |

## Example games (variant, players, seed, loss turn)

- Hinted last copy: regular 2p seed 0 (t30), seed 1 (t23), seed 5 (t22)
- Unhinted 5 not on chop: regular 5p seed 1 (t21), seed 5 (t10), seed 13 (t8)
- Missed save: regular 2p seed 4 (t22), seed 13 (t25), seed 14 (t21)
- Pace: regular 3p seed 4 (t48), seed 5 (t41), seed 7 (t48)
- Hinted misplay: regular 2p seed 19 (t36), regular 3p seed 6 (t21), regular 4p seed 0 (t34)
- "Certain" misplay (rainbow): rainbow 2p seed 10 (t18), rainbow 3p seed 5 (t27), seed 19 (t42)

## Where to start (suggested order)

1. **Unsafe-flag pileup** (patterns 1, 3; ~220 games). When do protective-discard
   flags expire? Should a flag clear once the protected card is saved, or once the
   moment has passed? And the last-resort discard should pick the least-bad card
   (an unsafe-flagged unhinted card over a known 5), not slot 1.
2. **"Certainly playable" misses in rainbow** (13 games). Find where candidates
   collapse to a single wrong card; the soundness test should catch it if it runs
   with convention constraints.
3. **Missed saves** (~50 games). Teammate had a token and the last copy was on
   chop. Check the save weight against what they did instead, and whether lookahead
   sees it.
4. **Pace / efficiency** (56 games). Fewer wasted discards, more multi-card plays.
5. **Too many 5 saves early** locking 2p hands (the 49 truly full hands).

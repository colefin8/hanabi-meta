# Game log format (JSONL, version 1)

Every game, simulated or real, can be appended to a `.jsonl` file: one JSON
object per line, many games per file. Code: `hanabi_meta/gamelog/log.py`. Keep
this file in sync with it, and bump `format_version` when a field changes meaning.

The aim is to have training data for imitation learning later: what each player
could see, what the advisor suggested, and what was actually done.

## Conventions

- Cards are strings: suit letter + rank, e.g. `"R3"`, `"M5"` (rainbow).
- Players are 0-based seat numbers in turn order.
- Slots are 0-based from the **oldest** (left-most) card. The CLI shows them 1-based.
- Hint `value` is a suit index (color hints) or a rank 1-5 (rank hints).

## Record types

A game is `game_start`, then optionally `deal`, then `turn` records in order, then
`game_end`.

### `game_start`
| field | meaning |
|---|---|
| `format_version` | `1` |
| `game_id` | random id, repeated on every record of the game |
| `time` | UTC ISO timestamp |
| `source` | `"selfplay"` or `"live"` |
| `variant` | full variant config (`Variant.to_dict()`): suits with copies and hint rules, players, hand size, rule flags |
| `deck` | full deck order, index 0 drawn first (`null` for live games) |
| `seed` | shuffle seed if known |
| `observer` | live games: whose point of view this is (`null` in self-play, which is omniscient) |
| `players` | optional names |
| `snapshot` | live games: the game-file header lines (starting table) |

### `deal` (self-play only)
`events`: the initial draws, as `draw` events.

### `turn`
| field | meaning |
|---|---|
| `turn`, `player` | turn number and who acted |
| `action` | `{"type": "play"/"discard", "slot": n}` or `{"type": "hint_color"/"hint_rank", "target": p, "value": v}` (live games: `null`, see `note`) |
| `events` | what happened, in order (below) |
| `views_before` | `{seat: view}`: each seat's observation **before** the action (self-play with `--views`: every seat; live: the observer) |
| `advice` | the advisor's top suggestions for the acting player (live games: only on the observer's own turns) |
| `note` | live games: the line that was typed |

Events:
```json
{"kind":"hint","giver":2,"target":1,"hint_kind":"color","value":1,"touched":[3]}
{"kind":"play","player":3,"slot":3,"card":"Y2","success":true}
{"kind":"discard","player":0,"slot":0,"card":"G2"}
{"kind":"draw","player":3,"card":"G1"}          // card null when the observer can't see it
{"kind":"reorder","player":1,"order":[4,1,3,2,0]} // safety swap: new[i] = old[order[i]]
```

A view:
```json
{"player":0,"stacks":[0,1,0,0,0],"hints":7,"strikes":0,"deck_size":33,
 "discards":[],"hands":{"1":["R4","B4","W3","Y3"],"2":["G4","B3","R1","W4"]},
 "touched":{"0":[false,false,false,false],"1":[false,false,false,true]},
 "own_candidates":[["B1","B2"],["..."]]}
```
`own_candidates` already includes the convention inferences the player had made.

### `game_end`
`score`, `strikes`, `turns`. Live games also have `"finished": false`, because a log
can be written mid-game.

## Replaying

`gamelog.replay(game)` re-runs a self-play game through the engine from its
`deck` and checks every event and the final score. Live games can't be replayed
(the deck order is unknown). Their action log rebuilds the observer's view instead.

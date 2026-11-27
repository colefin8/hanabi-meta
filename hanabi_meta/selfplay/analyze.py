"""Why self-play games weren't perfect: find the losing turn and classify it.

    python -m hanabi_meta.selfplay.analyze logs/selfplay.jsonl [--examples 3] [--json out.json]

Needs logs written with `--views` (the analysis reads what each seat could see).
For each game that wasn't perfect it reports:

- the losing action (discard / misplay of a last copy, strikeout, or pace);
- the card, whether it was hinted, whether it was the actor's chop, what the actor
  thought it could be, and how many hint tokens there were;
- how the earlier copies of the card were lost (for cards with 2+ copies);
- missed saves: teammates who acted while the card sat on the actor's chop, had a
  hint token, and did something else;
- the advisor's top alternatives on the losing turn.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..gamelog import read_games


def _chop(touched: list[bool]) -> int | None:
    for i, t in enumerate(touched):
        if not t:
            return i
    return None


def _act_str(t: dict) -> str:
    a = t.get("action") or {}
    k = a.get("type")
    evs = t["events"]
    if k in ("play", "discard"):
        ev = next(e for e in evs if e["kind"] in ("play", "discard"))
        tag = "" if k == "discard" or ev.get("success") else " (MISS)"
        return f"{k} slot {a['slot'] + 1} = {ev['card']}{tag}"
    if k in ("hint_color", "hint_rank"):
        ev = next(e for e in evs if e["kind"] == "hint")
        return f"hint p{a['target']} {ev['hint_kind']} {ev['value']} -> slots " + \
            ",".join(str(s + 1) for s in ev["touched"])
    return str(a)


def analyze_game(g) -> dict[str, Any] | None:
    end = g.end or {}
    if end.get("perfect") or not end or end.get("finished") is False:
        return None  # perfect, or a live game logged mid-way
    v = g.start["variant"]
    turns = g.turns
    if not turns:
        return None
    last = turns[-1]
    reason = end.get("end_reason") or "?"
    out: dict[str, Any] = {
        "game_id": g.start["game_id"], "seed": g.start.get("seed"),
        "variant": v.get("kind") or v.get("name"), "players": v.get("num_players"),
        "score": end.get("score"), "turns": end.get("turns"), "end_reason": reason,
        "loss_turn": last["turn"], "actor": last["player"], "action": _act_str(last),
    }
    a = last.get("action") or {}
    views = last.get("views_before") or {}
    me = str(last["player"])
    myview = views.get(me, {})
    out["hints_before"] = myview.get("hints")
    out["deck_size"] = myview.get("deck_size")
    out["advice"] = [{"action": r.get("action"), "score": r.get("score"),
                      "reasons": r.get("reasons")} for r in last.get("advice", [])]
    if reason.startswith("struck out"):
        out["kind"] = "strikeout"
    elif "turns left" in reason:
        out["kind"] = "pace"
    elif a.get("type") == "discard":
        out["kind"] = "discard_last_copy"
    elif a.get("type") == "play":
        out["kind"] = "misplay_last_copy"
    else:
        out["kind"] = "other"

    if a.get("type") in ("play", "discard"):
        slot = a["slot"]
        ev = next(e for e in last["events"] if e["kind"] in ("play", "discard"))
        card = ev["card"]
        out["card"] = card
        touched = (myview.get("touched") or {}).get(me) or []
        out["card_touched"] = bool(touched and touched[slot])
        out["was_chop"] = _chop(touched) == slot if touched else None
        cands = myview.get("own_candidates") or []
        out["actor_candidates"] = cands[slot] if slot < len(cands) else None
        out["hand_size"] = len(touched)
        out["hand_touched"] = sum(touched)
        # Earlier copies of this card.
        prior = []
        for t in turns[:-1]:
            for e in t["events"]:
                if e["kind"] in ("discard", "play") and e["card"] == card and \
                        not (e["kind"] == "play" and e["success"]):
                    tv = (t.get("views_before") or {}).get(str(t["player"]), {})
                    tt = (tv.get("touched") or {}).get(str(t["player"])) or []
                    prior.append({"turn": t["turn"], "player": t["player"],
                                  "how": "misplay" if e["kind"] == "play" else "discard",
                                  "touched": bool(tt and tt[e["slot"]]),
                                  "hints_before": tv.get("hints")})
        out["prior_copies_lost"] = prior
        # Missed saves: since the actor's previous turn, who saw the card on chop.
        missed = []
        n = v.get("num_players") or len(views)
        window = turns[max(0, len(turns) - n):-1]
        for t in window:
            q = str(t["player"])
            qv = (t.get("views_before") or {}).get(q, {})
            hand = (qv.get("hands") or {}).get(me)
            ttch = (qv.get("touched") or {}).get(me)
            if not hand or not ttch:
                continue
            c = _chop(ttch)
            on_chop = c is not None and hand[c] == card
            if card in hand:
                missed.append({"turn": t["turn"], "player": t["player"],
                               "hints": qv.get("hints"), "on_chop": on_chop,
                               "card_slot": hand.index(card) + 1,
                               "did": _act_str(t)})
        out["seen_by"] = missed
    return out


def classify(r: dict) -> str:
    """One label per loss, for counting patterns."""
    k = r["kind"]
    if k in ("pace", "strikeout", "other"):
        return k
    card = r.get("card", "??")
    rank = card[1:]
    if k == "misplay_last_copy":
        return f"misplay of last {('5' if rank == '5' else 'copy')}" + \
            (" (hinted)" if r.get("card_touched") else " (unhinted blind play)")
    # discard
    if r.get("card_touched"):
        return "discarded a hinted last copy"
    saved_possible = [s for s in r.get("seen_by", []) if s["hints"] and s["on_chop"]]
    base = "discarded unhinted 5" if rank == "5" else "discarded unhinted last copy"
    if not r.get("was_chop"):
        base += " (not chop)"
    if saved_possible:
        return base + ": teammate had a token and it was on chop"
    if any(s["on_chop"] for s in r.get("seen_by", [])):
        return base + ": on chop but teammates had 0 tokens"
    return base + ": not on chop when teammates acted (drawn/moved late)"


def summarize(results: list[dict], total: int, perfect: int) -> str:
    lines = [f"{total} games, {perfect} perfect ({perfect / max(total, 1):.0%}), "
             f"{len(results)} lost", ""]
    by = Counter(classify(r) for r in results)
    lines.append("Loss patterns:")
    for k, c in by.most_common():
        lines.append(f"  {c:>4}  {k}")
    lines.append("")
    kinds = Counter(r["kind"] for r in results)
    lines.append("By kind: " + ", ".join(f"{k} {c}" for k, c in kinds.most_common()))
    disc = [r for r in results if r["kind"] == "discard_last_copy"]
    if disc:
        lines.append("Discard losses by rank: " + ", ".join(
            f"{k} {c}" for k, c in sorted(Counter(r["card"][1:] for r in disc).items())))
        lines.append("Hint tokens before the losing discard: " + ", ".join(
            f"{k}: {c}" for k, c in sorted(Counter(r["hints_before"] for r in disc).items())))
        lines.append("Hand fully hinted when discarding (forced): "
                     f"{sum(r['hand_touched'] == r['hand_size'] for r in disc)}")
        prior = Counter()
        for r in disc:
            for p in r["prior_copies_lost"]:
                prior[(p["how"], "hinted" if p["touched"] else "unhinted")] += 1
        if prior:
            lines.append("Earlier copies of the lost card went by: " + ", ".join(
                f"{a} {b} {c}" for (a, b), c in prior.most_common()))
    lines.append("Loss turn: " + _hist([r["loss_turn"] for r in results]))
    lines.append("Score at loss: " + _hist([r["score"] for r in results]))
    by_var = defaultdict(list)
    for r in results:
        by_var[(r["variant"], r["players"])].append(r)
    lines.append("")
    lines.append("Most common pattern per variant/players:")
    for key in sorted(by_var, key=str):
        c = Counter(classify(r) for r in by_var[key]).most_common(1)[0]
        lines.append(f"  {key[0]} {key[1]}p: {c[1]}/{len(by_var[key])} {c[0]}")
    return "\n".join(lines)


def _hist(xs: list[int]) -> str:
    if not xs:
        return "-"
    xs = sorted(xs)
    return (f"min {xs[0]}, median {xs[len(xs) // 2]}, max {xs[-1]}, "
            f"mean {sum(xs) / len(xs):.1f}")


def example_text(r: dict) -> str:
    lines = [f"[{r['variant']} {r['players']}p seed {r['seed']} id {r['game_id']}] "
             f"turn {r['loss_turn']}, score {r['score']}: {r['end_reason']}",
             f"  p{r['actor']} {r['action']} with {r['hints_before']} hints, "
             f"deck {r['deck_size']}"]
    if "card" in r:
        lines.append(f"  hinted={r['card_touched']} chop={r['was_chop']} "
                     f"actor thought: {r['actor_candidates']}")
        for p in r["prior_copies_lost"]:
            lines.append(f"  earlier copy: turn {p['turn']} p{p['player']} {p['how']} "
                         f"(hinted={p['touched']}, hints {p['hints_before']})")
        for s in r["seen_by"]:
            lines.append(f"  turn {s['turn']} p{s['player']} saw it in slot "
                         f"{s['card_slot']} (chop={s['on_chop']}, hints {s['hints']}) "
                         f"and did: {s['did']}")
    for i, ad in enumerate(r["advice"][:3]):
        lines.append(f"  advice {i}: {ad['action']} {ad['score']} {ad['reasons']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hanabi_meta.selfplay.analyze")
    ap.add_argument("log", type=Path)
    ap.add_argument("--examples", type=int, default=2,
                    help="example games to print per loss pattern")
    ap.add_argument("--json", type=Path, help="write per-game results here")
    args = ap.parse_args(argv)
    games = list(read_games(args.log))
    results = [r for g in games if (r := analyze_game(g))]
    perfect = sum(1 for g in games if (g.end or {}).get("perfect"))
    print(summarize(results, len(games), perfect))
    if args.examples:
        print("\nExamples:")
        seen = Counter()
        for r in results:
            k = classify(r)
            if seen[k] < args.examples:
                seen[k] += 1
                print(f"\n== {k}")
                print(example_text(r))
    if args.json:
        args.json.write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

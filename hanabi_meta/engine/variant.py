"""Variant configuration: suits, copy counts, hint-touching rules, player count.

Every rule that differs between our four variants is an explicit field here, so
a new variant (or a different reading of an existing one) is a config change,
not a code change. See README.md "Variant assumptions".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, NamedTuple

RANKS: tuple[int, ...] = (1, 2, 3, 4, 5)
STANDARD_COPIES: tuple[int, int, int, int, int] = (3, 2, 2, 2, 1)
SHORT_COPIES: tuple[int, int, int, int, int] = (2, 1, 1, 1, 1)


class Card(NamedTuple):
    """A card identity. `suit` is an index into Variant.suits, `rank` is 1-5."""

    suit: int
    rank: int


@dataclass(frozen=True)
class SuitSpec:
    name: str
    letter: str
    copies: tuple[int, int, int, int, int] = STANDARD_COPIES
    #: True if this suit can be named in a color hint ("you have rainbow cards").
    has_own_hint: bool = True
    #: True if every color hint also touches this suit's cards.
    touched_by_all_colors: bool = False


BASE_SUITS: tuple[SuitSpec, ...] = (
    SuitSpec("red", "R"),
    SuitSpec("yellow", "Y"),
    SuitSpec("green", "G"),
    SuitSpec("blue", "B"),
    SuitSpec("white", "W"),
)


def default_hand_size(num_players: int) -> int:
    return 5 if num_players <= 3 else 4


@dataclass(frozen=True)
class Variant:
    name: str
    suits: tuple[SuitSpec, ...]
    num_players: int
    hand_size: int = 0  # 0 means "use the standard size for the player count"
    max_hints: int = 8
    max_strikes: int = 3
    #: Official rules: losing the third fuse ends the game with 0 points.
    zero_score_on_strikeout: bool = True
    #: Official rules: a hint must touch at least one card.
    allow_empty_hints: bool = False
    #: Official rules: you may not discard while all 8 hint tokens are available.
    allow_discard_at_max_hints: bool = False
    #: Playing a 5 returns a hint token (if not already at max). Official rules
    #: say yes; our table plays that it does not.
    five_returns_hint: bool = False
    #: House rule: the game ends as soon as a perfect game (every suit to 5) is
    #: impossible: every copy of a needed card is gone, or too few turns remain.
    #: The score at that point is still recorded (useful for training), but the
    #: goal is a perfect game. Official rules: False (play on for points).
    end_when_perfect_lost: bool = True
    _hint_colors: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not 2 <= self.num_players <= 5:
            raise ValueError("num_players must be 2-5")
        if self.hand_size == 0:
            object.__setattr__(self, "hand_size", default_hand_size(self.num_players))
        letters = [s.letter for s in self.suits]
        if len(set(letters)) != len(letters):
            raise ValueError("suit letters must be unique")
        object.__setattr__(
            self, "_hint_colors", tuple(i for i, s in enumerate(self.suits) if s.has_own_hint)
        )

    # ---- card universe -------------------------------------------------
    @property
    def num_suits(self) -> int:
        return len(self.suits)

    @property
    def max_score(self) -> int:
        return 5 * self.num_suits

    def copies(self, card: Card) -> int:
        return self.suits[card.suit].copies[card.rank - 1]

    def all_cards(self) -> list[Card]:
        """Every distinct card identity, suit-major."""
        return [Card(s, r) for s in range(self.num_suits) for r in RANKS]

    def deck(self) -> list[Card]:
        """The full deck with multiplicity, unshuffled."""
        return [c for c in self.all_cards() for _ in range(self.copies(c))]

    # ---- hints -----------------------------------------------------------
    @property
    def hint_colors(self) -> tuple[int, ...]:
        """Suit indices that can be named in a color hint."""
        return self._hint_colors

    def color_touches(self, color: int, card: Card) -> bool:
        return card.suit == color or self.suits[card.suit].touched_by_all_colors

    @staticmethod
    def rank_touches(rank: int, card: Card) -> bool:
        return card.rank == rank

    def touches(self, kind: str, value: int, card: Card) -> bool:
        if kind == "color":
            return self.color_touches(value, card)
        if kind == "rank":
            return self.rank_touches(value, card)
        raise ValueError(f"unknown hint kind {kind!r}")

    # ---- text ------------------------------------------------------------
    def card_str(self, card: Card) -> str:
        return f"{self.suits[card.suit].letter}{card.rank}"

    def parse_card(self, text: str) -> Card:
        text = text.strip().upper()
        letter, rank = text[:-1], int(text[-1])
        for i, s in enumerate(self.suits):
            if s.letter == letter:
                return Card(i, rank)
        raise ValueError(f"unknown suit in {text!r}")

    def color_index(self, text: str) -> int:
        t = text.strip().lower()
        for i, s in enumerate(self.suits):
            if t in (s.letter.lower(), s.name):
                return i
        raise ValueError(f"unknown color {text!r}")

    # ---- serialisation (for the JSONL log) --------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("_hint_colors", None)
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Variant":
        d = dict(d)
        d["suits"] = tuple(
            SuitSpec(**{**s, "copies": tuple(s["copies"])}) for s in d["suits"]
        )
        return Variant(**d)


VARIANT_KINDS = ("regular", "rainbow", "rainbow_all_colors", "short_rainbow")


def make_variant(kind: str, num_players: int, **overrides: Any) -> Variant:
    """Build one of our four named variants. `overrides` replaces any Variant field.

    regular            5 suits, 50 cards.
    rainbow            + rainbow suit (3/2/2/2/1), own "rainbow" hint, touched by every color.
    rainbow_all_colors + rainbow suit (3/2/2/2/1), NO own hint, touched by every color.
    short_rainbow      + rainbow suit (2/1/1/1/1), own hint, touched by every color.
    """
    rainbow = {
        "regular": None,
        "rainbow": SuitSpec("rainbow", "M", STANDARD_COPIES, True, True),
        "rainbow_all_colors": SuitSpec("rainbow", "M", STANDARD_COPIES, False, True),
        "short_rainbow": SuitSpec("rainbow", "M", SHORT_COPIES, True, True),
    }
    if kind not in rainbow:
        raise ValueError(f"unknown variant kind {kind!r}; choose from {VARIANT_KINDS}")
    extra = rainbow[kind]
    suits = BASE_SUITS + ((extra,) if extra else ())
    return Variant(name=kind, suits=suits, num_players=num_players, **overrides)

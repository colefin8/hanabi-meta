"""Our conventions ("Meta"), one module each. See docs/QUESTIONS.md for the rules.

Implemented: skip_level (skip-level + shotgun), trash_hint. Planned: safety_swap,
playable_five, protective_discard.
"""
from .base import (Candidate, ExpStatus, Expectation, HintKind, Interpretation)
from .meta_state import MetaState

__all__ = ["Candidate", "ExpStatus", "Expectation", "HintKind", "Interpretation",
           "MetaState"]

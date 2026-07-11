"""Token vocabulary shared by the decoder and the pure rewrite engine.

The engine operates purely on these tokens (never on raw evdev events), which is
what makes it hardware-free and fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Letter:
    """A cased letter keypress, ``'a'..'z'`` or ``'A'..'Z'``."""

    char: str


@dataclass(frozen=True)
class WordBoundary:
    """A word-ending keypress (space, tab, enter, punctuation, digit)."""


@dataclass(frozen=True)
class Backspace:
    """A backspace keypress — pops the last buffered letter."""


@dataclass(frozen=True)
class Reset:
    """Buffer-invalidating event (navigation, shortcut, mouse click, idle)."""


# A discriminated union over the four token kinds.
Token = Letter | WordBoundary | Backspace | Reset


@dataclass(frozen=True)
class Correction:
    """A rewrite to apply: delete ``delete_count`` chars, then type ``text``."""

    delete_count: int
    text: str

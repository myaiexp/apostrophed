"""The pure rewrite engine — the heart of apostrophed.

A shadow buffer accumulates the current word's letters. On a word boundary the
buffer is matched (case-insensitively) against the rule set; a match yields a
``Correction`` describing how many chars to delete and what to type instead. No
evdev imports live here: ``feed`` is a pure token -> optional-correction function,
so every branch below is exercised by ``tests/test_engine.py`` without hardware.
"""

from __future__ import annotations

from .tokens import Backspace, Correction, Letter, Reset, Token, WordBoundary


def _recase(typed: str, replacement: str) -> str | None:
    """Project the casing of ``typed`` onto ``replacement``.

    Three accepted patterns mirror how the user typed the trigger:
    all-lower -> replacement as-defined (intrinsic capitals preserved, e.g.
    ``im`` -> ``I'm``); first-upper -> capitalize only the first char
    (``Didnt`` -> ``Didn't``); all-upper -> ``.upper()`` (``DIDNT`` ->
    ``DIDN'T``). Any other (mixed) casing returns ``None`` — a typo we refuse to
    guess at.
    """
    if typed.islower():
        return replacement
    if typed.isupper():
        return replacement.upper()
    if typed[0].isupper() and typed[1:].islower():
        return replacement[:1].upper() + replacement[1:]
    return None


class Engine:
    """Stateful word-buffer that turns a token stream into corrections."""

    def __init__(self, rules: dict[str, str]) -> None:
        self._rules = rules
        self._buffer: list[str] = []
        # Pre-baked revert, armed the instant a correction fires and disarmed by the
        # very next token: a single Backspace right after a correction "rewinds" it.
        self._undo: Correction | None = None

    def feed(self, token: Token) -> Correction | None:
        """Advance the buffer by one token; return a ``Correction`` when a
        ``WordBoundary`` completes a matching, case-consistent, non-no-op word, or
        when a ``Backspace`` reverts the correction that just fired."""
        if isinstance(token, Letter):
            self._undo = None
            self._buffer.append(token.char)
            return None
        if isinstance(token, Backspace):
            # One Backspace right after a correction reverts it (the undo window);
            # otherwise Backspace just syncs the buffer with the user's edit.
            if self._undo is not None:
                undo, self._undo = self._undo, None
                self._buffer.clear()  # already empty post-correction; defensive
                return undo
            if self._buffer:
                self._buffer.pop()
            return None
        if isinstance(token, Reset):
            self._undo = None
            self._buffer.clear()
            return None
        if isinstance(token, WordBoundary):
            return self._evaluate()
        return None

    def _evaluate(self) -> Correction | None:
        typed = "".join(self._buffer)
        self._buffer.clear()  # a boundary always ends the word, match or not
        self._undo = None  # a new boundary supersedes any pending undo window
        replacement = self._rules.get(typed.lower())
        if replacement is None:
            return None
        result = _recase(typed, replacement)
        if result is None or result == typed:  # mixed case, or already correct
            return None
        # Arm the revert: undo deletes the corrected word + the one boundary char
        # emitted after it, then retypes the original literal word (rewind model).
        self._undo = Correction(delete_count=len(result) + 1, text=typed)
        return Correction(delete_count=len(typed), text=result)

"""Classify evdev key events into engine tokens, tracking modifier state.

Pure and hardware-free: ``decode`` takes an event plus the current ``ModState``
and returns a ``Token`` or ``None``. The daemon calls ``ModState.update`` on every
key event (so held/locked modifiers stay current) and then ``decode``.

Design choice: only word-ending keys are enumerated (``_WORD_BOUNDARY``). Every
other non-letter, non-backspace key — arrows, Home/End, F-keys, media — falls
through to ``Reset``, i.e. we invalidate the buffer rather than risk a wrong edit
against a cursor we can't track. That keeps the "safe" set small and explicit and
makes unknown keys fail safe by default.
"""

from __future__ import annotations

from evdev import ecodes

from .tokens import Backspace, Letter, Reset, Token, WordBoundary

# --- keycode sets, derived from ecodes rather than hand-listed ----------------

_LETTERS: dict[int, str] = {
    getattr(ecodes, f"KEY_{c.upper()}"): c for c in "abcdefghijklmnopqrstuvwxyz"
}

_SHIFT_KEYS = frozenset({ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT})
# Ctrl/Alt/Meta => a command chord. RIGHTALT (AltGr) is included deliberately:
# with AltGr held a letter key produces a symbol, not its base letter, so we must
# not buffer it — resetting is the safe interpretation.
_SHORTCUT_KEYS = frozenset(
    {
        ecodes.KEY_LEFTCTRL,
        ecodes.KEY_RIGHTCTRL,
        ecodes.KEY_LEFTALT,
        ecodes.KEY_RIGHTALT,
        ecodes.KEY_LEFTMETA,
        ecodes.KEY_RIGHTMETA,
    }
)
_MODIFIER_KEYS = _SHIFT_KEYS | _SHORTCUT_KEYS | {ecodes.KEY_CAPSLOCK}
# Public: the daemon skips these when releasing held keys before a rewrite (their
# down-state is meaningful, not a stuck letter to clear).
MODIFIER_KEYS = _MODIFIER_KEYS

# Keys that produce a visible non-letter and thus END a word.
_PUNCTUATION = {
    ecodes.KEY_MINUS,
    ecodes.KEY_EQUAL,
    ecodes.KEY_LEFTBRACE,
    ecodes.KEY_RIGHTBRACE,
    ecodes.KEY_SEMICOLON,
    ecodes.KEY_APOSTROPHE,
    ecodes.KEY_GRAVE,
    ecodes.KEY_BACKSLASH,
    ecodes.KEY_COMMA,
    ecodes.KEY_DOT,
    ecodes.KEY_SLASH,
    ecodes.KEY_102ND,
    ecodes.KEY_KPASTERISK,
    ecodes.KEY_KPMINUS,
    ecodes.KEY_KPPLUS,
    ecodes.KEY_KPDOT,
    ecodes.KEY_KPSLASH,
    ecodes.KEY_KPCOMMA,
    ecodes.KEY_KPEQUAL,
}
_DIGITS = {getattr(ecodes, f"KEY_{d}") for d in "1234567890"}
_KP_DIGITS = {getattr(ecodes, f"KEY_KP{d}") for d in "0123456789"}
_WHITESPACE = {ecodes.KEY_SPACE, ecodes.KEY_TAB, ecodes.KEY_ENTER, ecodes.KEY_KPENTER}
_WORD_BOUNDARY = frozenset(_PUNCTUATION | _DIGITS | _KP_DIGITS | _WHITESPACE)


class ModState:
    """Tracks currently-held shift/ctrl/alt/meta keys and the CapsLock latch."""

    def __init__(self) -> None:
        self._held: set[int] = set()
        self._caps = False

    def update(self, event) -> None:
        """Fold one event into modifier state. Call for every key event."""
        if event.type != ecodes.EV_KEY:
            return
        code, value = event.code, event.value
        if code == ecodes.KEY_CAPSLOCK:
            if value == 1:  # toggle on press only; ignore release/repeat
                self._caps = not self._caps
            return
        if code in _MODIFIER_KEYS:
            if value == 0:
                self._held.discard(code)
            else:  # 1 down or 2 repeat
                self._held.add(code)

    @property
    def shift_active(self) -> bool:
        """Effective case for letters: physical shift XOR CapsLock."""
        return bool(self._held & _SHIFT_KEYS) ^ self._caps

    @property
    def shortcut_active(self) -> bool:
        """Ctrl/Alt/Meta held — the keypress is a command, not typing."""
        return bool(self._held & _SHORTCUT_KEYS)

    @property
    def capslock_active(self) -> bool:
        return self._caps


def decode(event, mods: ModState) -> Token | None:
    """Map one EV_KEY press/repeat to a ``Token`` (or ``None`` if not relevant).

    ``None`` for non-key events, key releases, and modifier keys themselves —
    those carry no buffer content (``ModState.update`` handles their effect).
    """
    if event.type != ecodes.EV_KEY:
        return None
    if event.value not in (1, 2):  # presses and autorepeats only
        return None
    code = event.code
    if code in _MODIFIER_KEYS:
        return None
    if mods.shortcut_active:
        return Reset()
    letter = _LETTERS.get(code)
    if letter is not None:
        return Letter(letter.upper() if mods.shift_active else letter)
    if code in _WORD_BOUNDARY:
        return WordBoundary()
    if code == ecodes.KEY_BACKSPACE:
        return Backspace()
    return Reset()  # arrows, Home/End, F-keys, media, anything unknown

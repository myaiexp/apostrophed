"""Derive emit keystrokes from the active XKB layout — no hardcoded keycodes.

This is the module espanso effectively got wrong: it assumed a US layout and
emitted the apostrophe keycode's US binding, producing ``ä`` under ``fi``. Here we
build the layout's keymap with ``xkbcommon`` and look up, for each character we
emit (``a``-``z``, ``A``-``Z``, ``'``), the exact keycode + modifier level that
produces it. The whole table is computed once at startup.

Matching is exact: every character we emit is ASCII, and for ASCII the XKB keysym
equals the Unicode codepoint (``ord(ch)``). Matching on ``ord(ch)`` means the
apostrophe only ever binds to keysym U+0027 — never the look-alike acute accent
U+00B4 (a dead key on some layouts).
"""

from __future__ import annotations

from dataclasses import dataclass

from xkbcommon import xkb

_XKB_MOD_INVALID = 0xFFFFFFFF
# evdev keycodes are XKB keycodes minus the historical X11 offset of 8.
_XKB_EVDEV_OFFSET = 8

EMIT_CHARS = "abcdefghijklmnopqrstuvwxyz" "ABCDEFGHIJKLMNOPQRSTUVWXYZ" "'"


@dataclass(frozen=True)
class Keystroke:
    """The evdev keycode + modifier level that types a character."""

    keycode: int
    shift: bool
    altgr: bool


class KeyMap:
    """Layout-derived char -> :class:`Keystroke` table for our emit set."""

    def __init__(self, layout: str, variant: str = "") -> None:
        km = xkb.Context().keymap_new_from_names(
            layout=layout, variant=variant or None
        )

        def mod_idx(name: str) -> int | None:
            try:
                idx = km.mod_get_index(name)
            except Exception:
                return None
            if idx is None or idx < 0 or idx == _XKB_MOD_INVALID:
                return None
            return idx

        shift_idx = mod_idx("Shift")
        lock_idx = mod_idx("Lock")  # CapsLock — a lock we never press
        level3_mask = 0
        for name in ("LevelThree", "Mod5"):  # AltGr binds to one of these
            idx = mod_idx(name)
            if idx is not None:
                level3_mask |= 1 << idx

        # First-wins reverse index: keysym -> (keycode, layout, level). Ascending
        # keycodes means letters resolve to their main-block key.
        sym_location: dict[int, tuple[int, int, int]] = {}
        for keycode in range(km.min_keycode(), km.max_keycode() + 1):
            if km.num_layouts_for_key(keycode) == 0:
                continue
            layout_idx = 0  # single configured layout -> primary group
            for level in range(km.num_levels_for_key(keycode, layout_idx)):
                for sym in km.key_get_syms_by_level(keycode, layout_idx, level):
                    sym_location.setdefault(sym, (keycode, layout_idx, level))

        self._table: dict[str, Keystroke] = {}
        for ch in EMIT_CHARS:
            location = sym_location.get(ord(ch))
            if location is None:
                continue  # unreachable in this layout -> stroke() raises KeyError
            keycode, layout_idx, level = location
            masks = km.key_get_mods_for_level(keycode, layout_idx, level) or [0]
            # Prefer a mask that doesn't rely on CapsLock, then the simplest one.
            usable = [m for m in masks if not (lock_idx is not None and m & (1 << lock_idx))]
            chosen = min(usable or masks, key=lambda m: bin(m).count("1"))
            shift = bool(shift_idx is not None and chosen & (1 << shift_idx))
            altgr = bool(chosen & level3_mask)
            self._table[ch] = Keystroke(keycode - _XKB_EVDEV_OFFSET, shift, altgr)

    def stroke(self, ch: str) -> Keystroke:
        """Return the :class:`Keystroke` for ``ch``; raise ``KeyError`` if ``ch``
        is outside the emit set or unreachable in this layout."""
        try:
            return self._table[ch]
        except KeyError:
            raise KeyError(f"char {ch!r} is not emittable under this layout") from None

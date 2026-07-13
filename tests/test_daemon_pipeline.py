"""Headless integration test of the full daemon dispatch.

Drives ``Daemon._handle_kbd_event`` with synthetic keyd events and a fake uinput
sink, exercising decode -> engine -> keymap emission end to end without hardware.
This is where the project's whole reason for existing is proven: on a correction
the boundary key is forwarded AFTER the backspaces + rewrite, never before (the
espanso reorder bug is structurally impossible here).
"""

import pytest
from evdev import InputEvent, ecodes

from apostrophed.daemon import Daemon
from apostrophed.engine import Engine
from apostrophed.decode import ModState
from apostrophed.keymap import KeyMap
from apostrophed.rules import load_rules

RULES = load_rules("data/rules.tsv")
EV_KEY = ecodes.EV_KEY
KEY_BACKSPACE = ecodes.KEY_BACKSPACE
KEY_LEFTSHIFT = ecodes.KEY_LEFTSHIFT
KEY_RIGHTSHIFT = ecodes.KEY_RIGHTSHIFT
KEY_RIGHTALT = ecodes.KEY_RIGHTALT
KEY_SPACE = ecodes.KEY_SPACE
KEY_CAPSLOCK = ecodes.KEY_CAPSLOCK
_EMIT_MODS = {KEY_LEFTSHIFT, KEY_RIGHTALT}
_SHIFT_KEYS = {KEY_LEFTSHIFT, KEY_RIGHTSHIFT}


class FakeUInput:
    def __init__(self):
        self.log = []  # ("EMIT"|"FWD"|"SYN", type, code, value)

    def write(self, etype, code, value):
        self.log.append(("EMIT", etype, code, value))

    def write_event(self, ev):
        self.log.append(("FWD", ev.type, ev.code, ev.value))

    def syn(self):
        self.log.append(("SYN", None, None, None))


def key_for_char(ch):
    return getattr(ecodes, f"KEY_{ch.upper()}")


def make_daemon():
    """Return (daemon, fake_uinput, keymap) with concrete refs so tests don't
    reach through the daemon's Optional attributes."""
    d = Daemon("full")
    ui = FakeUInput()
    km = KeyMap("fi")
    d.ui = ui  # type: ignore[assignment]  # test double for the uinput sink
    d.engine = Engine(RULES)
    d.keymap = km
    d.mods = ModState()
    return d, ui, km


def _ev(d, code, value):
    d._handle_kbd_event(InputEvent(0, 0, EV_KEY, code, value))


def type_word(d, word, boundary=KEY_SPACE, caps=False):
    """Feed key events for each letter then the boundary, all through the real
    dispatch. Uppercase input letters are sent with Shift held (so decode sees the
    intended case); `caps` toggles CapsLock first."""
    if caps:
        _ev(d, KEY_CAPSLOCK, 1)
        _ev(d, KEY_CAPSLOCK, 0)
    for ch in word:
        if ch.isupper():
            _ev(d, KEY_LEFTSHIFT, 1)
            _ev(d, key_for_char(ch), 1)
            _ev(d, key_for_char(ch), 0)
            _ev(d, KEY_LEFTSHIFT, 0)
        else:
            _ev(d, key_for_char(ch), 1)
            _ev(d, key_for_char(ch), 0)
    _ev(d, boundary, 1)


def emitted_char_keycodes(log):
    return [c for (k, t, c, v) in log if k == "EMIT" and t == EV_KEY and v == 1
            and c != KEY_BACKSPACE and c not in _EMIT_MODS]


def count_emit_down(log, code):
    return sum(1 for (k, t, c, v) in log if k == "EMIT" and t == EV_KEY and c == code and v == 1)


def test_correction_and_ordering():
    d, ui, km = make_daemon()
    type_word(d, "wouldnt")
    log = ui.log

    assert count_emit_down(log, KEY_BACKSPACE) == 7  # len("wouldnt")
    assert emitted_char_keycodes(log) == [km.stroke(c).keycode for c in "wouldn't"]

    # THE anti-reorder guarantee: the space is forwarded strictly AFTER every
    # emitted correction keystroke.
    space_idx = next(i for i, e in enumerate(log) if e == ("FWD", EV_KEY, KEY_SPACE, 1))
    last_emit = max(i for i, (k, *_ ) in enumerate(log) if k == "EMIT")
    assert space_idx > last_emit


def test_first_upper_emits_one_shift():
    d, ui, km = make_daemon()
    type_word(d, "Didnt")  # first-upper: only the leading D is emitted shifted
    log = ui.log
    assert count_emit_down(log, KEY_BACKSPACE) == 5
    assert emitted_char_keycodes(log) == [km.stroke(c).keycode for c in "Didn't"]
    # exactly one injected Shift — for the capital D; the apostrophe and the rest
    # are unshifted.
    assert count_emit_down(log, KEY_LEFTSHIFT) == 1


def test_capslock_uppercases_without_shift():
    d, ui, km = make_daemon()
    type_word(d, "wouldnt", caps=True)
    log = ui.log
    assert count_emit_down(log, KEY_BACKSPACE) == 7
    # all-caps correction, same physical keys as lowercase...
    assert emitted_char_keycodes(log) == [km.stroke(c).keycode for c in "WOULDN'T"]
    # ...but emitted WITHOUT Shift, because the device's CapsLock is locked.
    assert count_emit_down(log, KEY_LEFTSHIFT) == 0


def test_rollover_releases_held_letter_before_rewrite():
    # Fast typing: space is pressed before the final 't' of "dont" is released, so
    # 't' is still held when the correction fires. The daemon must release it
    # before the rewrite, else the rewrite's own 't'-press is a no-op downstream
    # and the letter is lost (the reported "last letter dropped" bug).
    d, ui, km = make_daemon()
    for ch in "don":
        _ev(d, key_for_char(ch), 1)
        _ev(d, key_for_char(ch), 0)
    _ev(d, ecodes.KEY_T, 1)  # 't' pressed and HELD (no release)
    _ev(d, KEY_SPACE, 1)  # boundary fires while 't' is down
    log = ui.log

    first_bksp = next(
        i for i, (k, t, c, v) in enumerate(log)
        if k == "EMIT" and t == EV_KEY and c == KEY_BACKSPACE and v == 1
    )
    # a KEY_T release is injected BEFORE the backspaces (the held-key release)
    held_release = [
        i for i, (k, t, c, v) in enumerate(log)
        if k == "EMIT" and t == EV_KEY and c == ecodes.KEY_T and v == 0 and i < first_bksp
    ]
    assert held_release, "held 't' was not released before the rewrite"
    # and the rewrite still emits every char including the final 't'
    assert emitted_char_keycodes(log) == [km.stroke(c).keycode for c in "don't"]


def test_non_trigger_passes_through_untouched():
    d, ui, _km = make_daemon()
    type_word(d, "hello")
    log = ui.log
    assert count_emit_down(log, KEY_BACKSPACE) == 0
    assert emitted_char_keycodes(log) == []  # nothing injected


def hold_shift_type(d, word, shift_key=KEY_LEFTSHIFT, boundary=KEY_SPACE):
    """Physically hold ``shift_key`` for the entire word AND the boundary — the
    all-caps "never let go of Shift" scenario. Shift is left held on return."""
    _ev(d, shift_key, 1)
    for ch in word:
        _ev(d, key_for_char(ch), 1)
        _ev(d, key_for_char(ch), 0)
    _ev(d, boundary, 1)  # correction fires here, still under held Shift


def emitted_chars_with_shift(log):
    """Replay the log in order tracking the app-visible Shift state (from BOTH
    forwarded physical events and injected taps — they share one keycode), and
    for each injected char key-down return ``(keycode, shift_active_at_emit)``."""
    down = set()
    out = []
    for k, t, c, v in log:
        if t != EV_KEY:
            continue
        if c in _SHIFT_KEYS:
            down.add(c) if v == 1 else down.discard(c)
        elif k == "EMIT" and v == 1 and c != KEY_BACKSPACE:
            out.append((c, bool(down)))
    return out


def final_shift_down(log):
    """The app-visible Shift state after the whole sequence has been replayed."""
    down = set()
    for _k, t, c, v in log:
        if t == EV_KEY and c in _SHIFT_KEYS:
            down.add(c) if v == 1 else down.discard(c)
    return bool(down)


@pytest.mark.parametrize("shift_key", [KEY_LEFTSHIFT, KEY_RIGHTSHIFT])
def test_shift_held_across_correction(shift_key):
    # Holding Shift through a whole word makes an all-caps correction fire while
    # Shift is still physically down. The rewrite's per-char taps drive Shift
    # themselves, which must not collide with the held physical key:
    #   - Left-Shift: taps leave it released -> following letters go lowercase.
    #   - Right-Shift: taps use a *different* keycode, so it stays latched and
    #     leaks into the unshifted apostrophe tap -> "WOULDN'T" becomes "WOULDN*T".
    d, ui, km = make_daemon()
    hold_shift_type(d, "wouldnt", shift_key=shift_key)
    log = ui.log
    chars = emitted_chars_with_shift(log)

    # The rewrite is un-corrupted: right keys, and each char carries the correct
    # app-side Shift (letters shifted, the injected apostrophe NOT — even though
    # the user is holding Shift).
    assert [c for c, _ in chars] == [km.stroke(c).keycode for c in "WOULDN'T"]
    assert [s for _, s in chars] == [ch != "'" for ch in "WOULDN'T"]

    # ...and Shift is still down afterwards, so the next letters stay uppercase.
    assert final_shift_down(log)

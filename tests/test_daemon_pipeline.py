"""Headless integration test of the full daemon dispatch.

Drives ``Daemon._handle_kbd_event`` with synthetic keyd events and a fake uinput
sink, exercising decode -> engine -> keymap emission end to end without hardware.
This is where the project's whole reason for existing is proven: on a correction
the boundary key is forwarded AFTER the backspaces + rewrite, never before (the
espanso reorder bug is structurally impossible here).
"""

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
KEY_RIGHTALT = ecodes.KEY_RIGHTALT
KEY_SPACE = ecodes.KEY_SPACE
KEY_CAPSLOCK = ecodes.KEY_CAPSLOCK
_EMIT_MODS = {KEY_LEFTSHIFT, KEY_RIGHTALT}


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
            _ev(d, KEY_LEFTSHIFT, 0)
        else:
            _ev(d, key_for_char(ch), 1)
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


def test_non_trigger_passes_through_untouched():
    d, ui, _km = make_daemon()
    type_word(d, "hello")
    log = ui.log
    assert count_emit_down(log, KEY_BACKSPACE) == 0
    assert emitted_char_keycodes(log) == []  # nothing injected

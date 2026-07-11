import pytest
from evdev import ecodes
from xkbcommon import xkb

from apostrophed.keymap import KeyMap, Keystroke


def test_lowercase_letter():
    k = KeyMap("fi").stroke("d")
    assert k.keycode == ecodes.KEY_D and not k.shift


def test_uppercase_letter_needs_shift():
    assert KeyMap("fi").stroke("D") == Keystroke(ecodes.KEY_D, True, False)


def test_apostrophe_resolves():
    # the espanso bug: must NOT be the US KEY_APOSTROPHE position under fi
    k = KeyMap("fi").stroke("'")
    assert k.keycode != ecodes.KEY_APOSTROPHE

    # and the keycode+level really round-trips to U+0027 (not acute U+00B4)
    km = xkb.Context().keymap_new_from_names(layout="fi")
    xkb_kc = k.keycode + 8
    level = 1 if k.shift else 0  # apostrophe on fi is level 0, unmodified
    syms = km.key_get_syms_by_level(xkb_kc, 0, level)
    assert xkb.keysym_from_name("apostrophe") in syms


def test_all_letters_reachable_under_fi():
    km = KeyMap("fi")
    for ch in "abcdefghijklmnopqrstuvwxyz":
        assert km.stroke(ch).keycode
        assert km.stroke(ch.upper()).shift


def test_unreachable_char_raises():
    with pytest.raises(KeyError):
        KeyMap("fi").stroke("€")  # outside the emit set


def test_non_emit_char_raises():
    with pytest.raises(KeyError):
        KeyMap("fi").stroke("5")  # digits are never emitted

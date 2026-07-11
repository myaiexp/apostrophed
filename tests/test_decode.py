from evdev import InputEvent, ecodes

from apostrophed.decode import ModState, decode
from apostrophed.tokens import Backspace, Letter, Reset, WordBoundary

KEY_D = ecodes.KEY_D
KEY_A = ecodes.KEY_A
KEY_1 = ecodes.KEY_1
KEY_SPACE = ecodes.KEY_SPACE
KEY_LEFT = ecodes.KEY_LEFT
KEY_LEFTSHIFT = ecodes.KEY_LEFTSHIFT
KEY_LEFTCTRL = ecodes.KEY_LEFTCTRL
KEY_CAPSLOCK = ecodes.KEY_CAPSLOCK
KEY_BACKSPACE = ecodes.KEY_BACKSPACE


def key_press(code):
    return InputEvent(0, 0, ecodes.EV_KEY, code, 1)


def key_release(code):
    return InputEvent(0, 0, ecodes.EV_KEY, code, 0)


def key_repeat(code):
    return InputEvent(0, 0, ecodes.EV_KEY, code, 2)


def test_letter_lowercase():
    m = ModState()
    assert decode(key_press(KEY_D), m) == Letter("d")


def test_letter_shifted_uppercase():
    m = ModState()
    m.update(key_press(KEY_LEFTSHIFT))
    assert decode(key_press(KEY_D), m) == Letter("D")


def test_capslock_uppercases_letters():
    m = ModState()
    m.update(key_press(KEY_CAPSLOCK))
    m.update(key_release(KEY_CAPSLOCK))
    assert decode(key_press(KEY_D), m) == Letter("D")


def test_shift_and_capslock_cancel():
    m = ModState()
    m.update(key_press(KEY_CAPSLOCK))
    m.update(key_release(KEY_CAPSLOCK))
    m.update(key_press(KEY_LEFTSHIFT))
    assert decode(key_press(KEY_D), m) == Letter("d")


def test_ctrl_shortcut_is_reset():
    m = ModState()
    m.update(key_press(KEY_LEFTCTRL))
    assert isinstance(decode(key_press(KEY_A), m), Reset)


def test_space_is_word_boundary():
    assert isinstance(decode(key_press(KEY_SPACE), ModState()), WordBoundary)


def test_digit_is_word_boundary():
    assert isinstance(decode(key_press(KEY_1), ModState()), WordBoundary)


def test_arrow_is_reset():
    assert isinstance(decode(key_press(KEY_LEFT), ModState()), Reset)


def test_backspace_token():
    assert isinstance(decode(key_press(KEY_BACKSPACE), ModState()), Backspace)


def test_key_release_ignored():
    assert decode(key_release(KEY_D), ModState()) is None


def test_modifier_key_itself_ignored():
    assert decode(key_press(KEY_LEFTSHIFT), ModState()) is None


def test_letter_repeat_is_letter():
    assert decode(key_repeat(KEY_D), ModState()) == Letter("d")

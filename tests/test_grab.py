"""Startup grab handoff: ``Daemon._grab_when_idle`` must never leave the compositor
holding an upstream key (a press it saw before the grab whose release then reaches
only us), and must not let the run loop re-forward events the compositor already
got. Driven with fake readers; the real-device reproduction is in the design doc.
"""

import pytest
from evdev import InputEvent, ecodes

import apostrophed.daemon as daemon_mod
from apostrophed.daemon import Daemon

KEY_SPACE = ecodes.KEY_SPACE


class FakeQueue:
    """An evdev reader's queue: ``read`` returns what's pending, or raises
    BlockingIOError when empty (python-evdev's non-blocking behaviour)."""

    def __init__(self):
        self.pending = []
        self.closed = False

    def read(self):
        if not self.pending:
            raise BlockingIOError
        out, self.pending = self.pending, []
        return out

    def close(self):
        self.closed = True


class FakeKbd(FakeQueue):
    """Upstream keyboard. ``active_keys`` walks a script of kernel key states
    (repeating the last); ``on_grab(n)`` runs at the n-th grab, so a test can land
    events in the mirror between the idle check and the grab."""

    path = "/dev/input/fake"

    def __init__(self, active_script, on_grab=None):
        super().__init__()
        self.active_script = list(active_script)
        self.on_grab = on_grab or (lambda n: None)
        self.calls = []

    def active_keys(self):
        if len(self.active_script) > 1:
            return self.active_script.pop(0)
        return self.active_script[0]

    def grab(self):
        self.calls.append("grab")
        self.on_grab(self.calls.count("grab"))

    def ungrab(self):
        self.calls.append("ungrab")


@pytest.fixture
def mirror(monkeypatch):
    m = FakeQueue()
    monkeypatch.setattr(daemon_mod.evdev, "InputDevice", lambda path: m)
    monkeypatch.setattr(daemon_mod.time, "sleep", lambda s: None)
    return m


def grab(kbd):
    d = Daemon("full")
    d.kbd = kbd  # type: ignore[assignment]
    d._grab_when_idle()
    return d


def test_grabs_immediately_when_nothing_held(mirror):
    kbd = FakeKbd([[]])
    grab(kbd)
    assert kbd.calls == ["grab"]
    assert mirror.closed


def test_waits_for_held_key_release(mirror):
    # Space is down when the daemon starts: grabbing now would strand it. No grab
    # until the kernel reports it released.
    kbd = FakeKbd([[KEY_SPACE], [KEY_SPACE], []])
    grab(kbd)
    assert kbd.calls == ["grab"]
    assert kbd.active_script == [[]]  # polled through both held states first


def test_retries_when_key_lands_between_check_and_grab(mirror):
    # The never-grabbed mirror received a press after the idle check, so the
    # compositor got it too: release the grab and retry.
    def on_grab(n):
        if n == 1:
            mirror.pending.append(InputEvent(0, 0, ecodes.EV_KEY, KEY_SPACE, 1))

    kbd = FakeKbd([[]], on_grab=on_grab)
    grab(kbd)
    assert kbd.calls == ["grab", "ungrab", "grab"]


def test_non_key_events_in_mirror_dont_force_retry(mirror):
    # The compositor writes LED state to the device; that isn't a keystroke.
    kbd = FakeKbd([[]], on_grab=lambda n: mirror.pending.append(
        InputEvent(0, 0, ecodes.EV_LED, ecodes.LED_NUML, 1)))
    grab(kbd)
    assert kbd.calls == ["grab"]


def test_pre_grab_queue_is_discarded(mirror):
    # Events queued on our fd before the grab already reached the compositor;
    # the run loop must not forward them a second time.
    kbd = FakeKbd([[]])
    kbd.pending.append(InputEvent(0, 0, ecodes.EV_KEY, KEY_SPACE, 1))
    grab(kbd)
    assert kbd.pending == []


def test_sigterm_while_waiting_returns_without_grab(mirror, monkeypatch):
    d = Daemon("full")
    kbd = FakeKbd([[KEY_SPACE]])
    monkeypatch.setattr(daemon_mod.time, "sleep", lambda s: setattr(d, "stop", True))
    d.kbd = kbd  # type: ignore[assignment]
    d._grab_when_idle()
    assert kbd.calls == []
    assert mirror.closed

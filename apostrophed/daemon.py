"""The evdev/uinput shell around the pure engine.

Grabs keyd's virtual keyboard (by name), forwards every event verbatim to our own
uinput device (which Hyprland reads), and — on a word boundary that the engine
turns into a ``Correction`` — injects backspaces + the corrected text *before*
forwarding the held boundary key. Because we own output ordering, the boundary key
always lands after the correction: the espanso reorder race is structurally
impossible.

Safety properties (see the design doc):
- ``EVIOCGRAB`` is released on any exit, so a crash falls back to Hyprland reading
  keyd directly — corrections stop, the keyboard never dies.
- Per-event work is trivial and non-blocking (a hang, not a crash, would stall
  input).
- Signals only set flags (delivered via ``set_wakeup_fd``), checked at loop
  boundaries — never interrupting an emission mid-keystroke.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import select
import signal
import sys
import time

import evdev
from evdev import UInput, ecodes

from . import config
from .decode import MODIFIER_KEYS, ModState, decode
from .engine import Engine
from .rules import load_rules
from .tokens import Correction, Reset

# Shift keycodes a physically-held Shift can arrive on. Suspended around a rewrite
# (see ``Daemon._suspend_shift``) so the correction's own per-char Shift taps don't
# collide with a Shift the user is holding across the word.
_SHIFT_KEYS = (ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT)


def log(msg: str) -> None:
    print(f"apostrophed: {msg}", flush=True)


def _set_proc_name(name: str = "apostrophed") -> None:
    """Set /proc/self/comm so ``pkill -USR1 apostrophed`` matches (otherwise comm
    would be the interpreter basename, e.g. ``python3``)."""
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(15, name.encode()[:15], 0, 0, 0)  # PR_SET_NAME = 15
    except Exception as exc:  # non-fatal; toggle-by-name just won't work
        log(f"could not set process name: {exc}")


def find_device(name: str, timeout: float = 30.0) -> evdev.InputDevice:
    """Return the InputDevice whose ``.name == name``, retrying every 0.2s until
    ``timeout`` (keyd's virtual device may not exist yet at boot)."""
    deadline = time.monotonic() + timeout
    while True:
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            if dev.name == name:
                return dev
            dev.close()
        if time.monotonic() >= deadline:
            raise RuntimeError(f"device {name!r} not found within {timeout:.0f}s")
        time.sleep(0.2)


def _open_pointer(name: str) -> evdev.InputDevice | None:
    """Open the keyd pointer read-only (never grabbed) for click-reset. Optional:
    a missing pointer just means the idle timer is the only buffer-reset backstop."""
    try:
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            if dev.name == name:
                return dev
            dev.close()
    except Exception as exc:
        log(f"pointer scan failed ({exc}); click-reset disabled")
    return None


class Daemon:
    """Owns the grab/emit loop and per-event dispatch."""

    def __init__(self, mode: str) -> None:
        self.mode = mode  # "passthrough" | "dry-run" | "full"
        self.paused = False
        self.stop = False
        self.mods = ModState()
        self.engine: Engine | None = None
        self.keymap = None  # built lazily; only "full" mode emits chars
        self.ui: UInput | None = None
        self.kbd: evdev.InputDevice | None = None
        self.pointer: evdev.InputDevice | None = None
        self._wake_r = -1
        # Keycodes currently held down on the OUTPUT side (mirrors what the app
        # sees via forwarded events). Used to release fast-typing rollover keys
        # before a rewrite so a re-emitted press isn't a no-op on an already-down
        # key — the "last letter swallowed when typing fast" bug.
        self._held: set[int] = set()

    # --- emission helpers (full mode only) -----------------------------------

    def _tap(self, code: int, shift: bool = False, altgr: bool = False) -> None:
        ui = self.ui
        assert ui is not None
        # Press frame: modifiers + key down, committed with a SYN.
        if shift:
            ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1)
        if altgr:
            ui.write(ecodes.EV_KEY, ecodes.KEY_RIGHTALT, 1)
        ui.write(ecodes.EV_KEY, code, 1)
        ui.syn()
        # Release frame: key + modifiers up, committed separately. Splitting press
        # and release into distinct SYN reports mirrors a real keyboard; a
        # same-frame down+up is non-physical and libinput can drop the transition
        # (notably the last char right before the forwarded boundary key).
        ui.write(ecodes.EV_KEY, code, 0)
        if altgr:
            ui.write(ecodes.EV_KEY, ecodes.KEY_RIGHTALT, 0)
        if shift:
            ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0)
        ui.syn()

    def _apply_correction(self, corr: Correction) -> None:
        for _ in range(corr.delete_count):
            self._tap(ecodes.KEY_BACKSPACE)
        for ch in corr.text:
            ks = self.keymap.stroke(ch)  # type: ignore[union-attr]
            if ch.isalpha():
                # We forward CapsLock to our device, so its xkb state has Caps
                # locked; compensate so the emitted case is what we intend.
                shift = ch.isupper() ^ self.mods.capslock_active
            else:
                shift = ks.shift  # apostrophe: unaffected by CapsLock
            self._tap(ks.keycode, shift=shift, altgr=ks.altgr)

    def _forward(self, event) -> None:
        # Mirror the output-side key state so we know what's physically held.
        if event.type == ecodes.EV_KEY:
            if event.value == 1:
                self._held.add(event.code)
            elif event.value == 0:
                self._held.discard(event.code)
        self.ui.write_event(event)  # type: ignore[union-attr]

    def _release_held(self, keep: int) -> None:
        """Release every held non-modifier key (except ``keep``) so the imminent
        rewrite's key-downs aren't swallowed as no-ops on already-down keys."""
        for code in list(self._held):
            if code == keep or code in MODIFIER_KEYS:
                continue
            self.ui.write(ecodes.EV_KEY, code, 0)  # type: ignore[union-attr]
            self._held.discard(code)
        self.ui.syn()  # type: ignore[union-attr]

    def _suspend_shift(self) -> list[int]:
        """Lift any physically-held Shift on the output side so the rewrite's
        per-char taps run against a clean baseline, and return the codes to
        re-press afterwards.

        A correction's taps drive ``KEY_LEFTSHIFT`` themselves. If the user is
        still holding Shift across the word (an all-caps correction), that collides
        two ways: a held *Left*-Shift is left released by the final tap (so the
        next letters go lowercase), and a held *Right*-Shift — a different keycode
        the taps never touch — stays latched and leaks into the unshifted
        apostrophe tap (``didn't`` -> ``didn*t`` on layouts where ``'`` is
        unshifted). Both vanish if we drop Shift for the duration of the rewrite.

        ``self._held`` is left untouched: the physical key is still down and its
        eventual release event must still find it there to be discarded."""
        held = [c for c in _SHIFT_KEYS if c in self._held]
        for code in held:
            self.ui.write(ecodes.EV_KEY, code, 0)  # type: ignore[union-attr]
        if held:
            self.ui.syn()  # type: ignore[union-attr]
        return held

    def _restore_shift(self, codes: list[int]) -> None:
        """Re-press the Shift keys suspended for the rewrite, matching the app-side
        state back to the still-held physical keys so following letters keep their
        case."""
        for code in codes:
            self.ui.write(ecodes.EV_KEY, code, 1)  # type: ignore[union-attr]
        if codes:
            self.ui.syn()  # type: ignore[union-attr]

    # --- per-event dispatch ---------------------------------------------------

    def _handle_kbd_event(self, event) -> None:
        if self.paused or self.mode == "passthrough":
            self._forward(event)
            return
        if event.type != ecodes.EV_KEY:
            self._forward(event)  # EV_SYN / EV_MSC / EV_LED / EV_REP verbatim
            return

        self.mods.update(event)
        token = decode(event, self.mods)
        if token is None:
            self._forward(event)
            return

        assert self.engine is not None
        corr = self.engine.feed(token)
        if corr is None:
            self._forward(event)
            return

        # A Correction only ever comes back on a WordBoundary key-down. Inject the
        # rewrite, THEN forward the held boundary — never the other way around.
        if self.mode == "dry-run":
            log(f"[dry-run] correct: -{corr.delete_count} +{corr.text!r}")
            self._forward(event)
            return
        if config.DEBUG:
            log(f"correct: -{corr.delete_count} +{corr.text!r}")
        # Release any rollover keys still held from fast typing (else the rewrite's
        # re-emitted press of that same letter is a no-op), and drop any Shift the
        # user is holding across the word (else it collides with the taps' own Shift
        # — see `_suspend_shift`). Inject the rewrite, restore the held Shift, then
        # forward the boundary in its own frame. `keep=event.code` guards the
        # boundary key, which we forward ourselves below.
        self._release_held(keep=event.code)
        shift = self._suspend_shift()
        self._apply_correction(corr)
        self._restore_shift(shift)
        self._forward(event)
        self.ui.syn()  # type: ignore[union-attr]

    def _write_state(self) -> None:
        """Publish "active"/"paused" to the state file so external indicators
        (e.g. a waybar module) can reflect the toggle. Best-effort: a missing
        runtime dir (not installed as the systemd service) just means no
        indicator — never a reason to disrupt input."""
        try:
            with open(config.STATE_PATH, "w") as fh:
                fh.write("paused\n" if self.paused else "active\n")
        except OSError as exc:
            log(f"could not write state file {config.STATE_PATH!r}: {exc}")

    def _handle_pointer(self) -> None:
        try:
            for event in self.pointer.read():  # type: ignore[union-attr]
                if event.type == ecodes.EV_KEY and event.value == 1:
                    # any button press may reposition the caret -> invalidate
                    if self.engine is not None:
                        self.engine.feed(Reset())
        except BlockingIOError:
            pass

    # --- lifecycle ------------------------------------------------------------

    def _install_signals(self) -> None:
        self._wake_r, wake_w = os.pipe()
        os.set_blocking(wake_w, False)
        os.set_blocking(self._wake_r, False)
        signal.set_wakeup_fd(wake_w)

        def on_term(_sig, _frame):
            self.stop = True

        def on_usr1(_sig, _frame):
            self.paused = not self.paused
            self._write_state()
            log(f"{'paused (passthrough)' if self.paused else 'resumed'}")

        signal.signal(signal.SIGTERM, on_term)
        signal.signal(signal.SIGINT, on_term)
        signal.signal(signal.SIGUSR1, on_usr1)

    def setup(self) -> None:
        _set_proc_name()
        self._install_signals()
        self.kbd = find_device(config.DEVICE_NAME)
        log(f"found {config.DEVICE_NAME!r} at {self.kbd.path}")
        self.kbd.grab()
        self.ui = UInput.from_device(self.kbd, name="apostrophed")
        log("grabbed keyboard; emitting via uinput 'apostrophed'")

        if self.mode != "passthrough":
            rules = load_rules(config.RULES_PATH)
            self.engine = Engine(rules)
            log(f"loaded {len(rules)} rules from {config.RULES_PATH}")
            self.pointer = _open_pointer(config.POINTER_NAME)
            if self.pointer:
                log(f"watching pointer {self.pointer.path} for click-reset")

        if self.mode == "full":
            from .keymap import KeyMap  # lazy: only full mode needs xkbcommon

            self.keymap = KeyMap(config.LAYOUT, config.VARIANT)
            log(f"keymap ready for layout {config.LAYOUT!r}")
        self._write_state()  # publish initial "active" for indicators
        log(f"running in {self.mode} mode")

    def run_loop(self) -> None:
        assert self.kbd is not None
        fds = [self.kbd.fd, self._wake_r]
        if self.pointer:
            fds.append(self.pointer.fd)
        while not self.stop:
            timeout = config.IDLE_RESET_SECONDS if self.mode != "passthrough" else None
            try:
                ready, _, _ = select.select(fds, [], [], timeout)
            except InterruptedError:
                continue
            if not ready:  # idle timeout -> reset buffer (caret may have moved)
                if self.engine is not None:
                    self.engine.feed(Reset())
                continue
            if self._wake_r in ready:
                try:
                    os.read(self._wake_r, 64)  # drain wakeup bytes
                except BlockingIOError:
                    pass
                if self.stop:
                    break
            if self.pointer and self.pointer.fd in ready:
                self._handle_pointer()
            if self.kbd.fd in ready:
                try:
                    for event in self.kbd.read():
                        self._handle_kbd_event(event)
                except BlockingIOError:
                    pass

    def cleanup(self) -> None:
        # Order matters: ungrab first (Hyprland falls back to keyd), then destroy
        # our uinput device (releases any keys left pressed).
        if self.kbd is not None:
            try:
                self.kbd.ungrab()
            except Exception:
                pass
            self.kbd.close()
        if self.ui is not None:
            self.ui.close()
        if self.pointer is not None:
            self.pointer.close()
        log("stopped; keyboard restored to keyd passthrough")


def run(mode: str) -> int:
    daemon = Daemon(mode)
    try:
        daemon.setup()
        daemon.run_loop()
        return 0
    except OSError as exc:
        # Device vanished (e.g. keyd restart) -> non-zero so systemd restarts us
        # and we re-grab the fresh virtual keyboard.
        log(f"device error: {exc}; exiting for restart")
        return 1
    finally:
        daemon.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apostrophed", description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--passthrough",
        action="store_true",
        help="grab + forward only, no correction (grab-chain spike)",
    )
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="run the full pipeline but log corrections instead of emitting them",
    )
    args = parser.parse_args(argv)
    mode = "passthrough" if args.passthrough else "dry-run" if args.dry_run else "full"
    return run(mode)


if __name__ == "__main__":
    sys.exit(main())

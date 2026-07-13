"""Static configuration + environment overrides.

Deliberately tiny: the only things worth tweaking are the layout (for keymap
derivation), the rules path (so tests can point at the repo copy), the idle-reset
window, and an escape-hatch apostrophe keycode if xkbcommon derivation ever fails.
"""

from __future__ import annotations

import os


def _env_bool(name: str) -> bool:
    """True unless the var is unset/empty or an explicit falsy token.

    ``bool(os.environ.get(...))`` is the classic trap — it makes *any* non-empty
    string truthy, so ``APOSTROPHED_DEBUG=0`` (or ``false``/``off``) would wrongly
    turn the flag on. Treat the usual falsy strings as off; anything else set is on.
    """
    return os.environ.get(name, "").strip().lower() not in ("", "0", "false", "no", "off")


# XKB layout/variant used to derive emit keycodes. Must match the layout the
# compositor applies to our uinput device, or the emitted apostrophe (and any AltGr
# char) lands on the wrong keycode → wrong character, silently. Resolution order:
# explicit APOSTROPHED_* → the standard libxkbcommon XKB_DEFAULT_* vars → "us"
# (libxkbcommon's own default, the plurality choice). `install.sh` detects the
# active layout (localectl) and pins it into a systemd drop-in, so a fresh install
# is correct without any env fiddling — the "us" fallback is a last resort.
LAYOUT = os.environ.get("APOSTROPHED_LAYOUT") or os.environ.get("XKB_DEFAULT_LAYOUT") or "us"
VARIANT = os.environ.get("APOSTROPHED_VARIANT") or os.environ.get("XKB_DEFAULT_VARIANT") or ""

# Match the upstream virtual keyboard by NAME — the /dev/input/eventN node is not
# stable. Defaults to keyd's output; override to chain after a different virtual
# keyboard (the single most setup-specific value, hence an env var like the rest).
DEVICE_NAME = os.environ.get("APOSTROPHED_DEVICE_NAME", "keyd virtual keyboard")
POINTER_NAME = os.environ.get("APOSTROPHED_POINTER_NAME", "keyd virtual pointer")

# Source of truth for rules. Installed under the user's data dir by default; tests
# set the env to the repo copy.
_DATA_HOME = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
RULES_PATH = os.environ.get("APOSTROPHED_RULES", f"{_DATA_HOME}/apostrophed/rules.tsv")

# Reset the word buffer after this many seconds of keyboard silence — a backstop
# for cursor moves we can't observe (e.g. a touchpad tap, which isn't the keyd
# pointer we watch).
IDLE_RESET_SECONDS = float(os.environ.get("APOSTROPHED_IDLE_RESET", "4.0"))

# Where the daemon publishes its enabled/paused state ("active"|"paused") for
# external indicators to read (e.g. a waybar module). The user unit provides
# $XDG_RUNTIME_DIR/apostrophed via RuntimeDirectory; tests point this at a tmp file.
_RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", "/run")
STATE_PATH = os.environ.get("APOSTROPHED_STATE", f"{_RUNTIME_DIR}/apostrophed/state")

# Escape hatch: set to an int evdev keycode to override xkbcommon's apostrophe
# derivation. `None` means derive from the layout (the correct default).
_apos = os.environ.get("APOSTROPHED_APOSTROPHE_KEYCODE")
APOSTROPHE_KEYCODE: int | None = int(_apos) if _apos else None

# When set, log each applied correction in real mode (diagnostic; off by default
# to keep the journal quiet). Falsy strings ("0", "false", "no", "off") stay off.
DEBUG = _env_bool("APOSTROPHED_DEBUG")

"""Static configuration + environment overrides.

Deliberately tiny: the only things worth tweaking are the layout (for keymap
derivation), the rules path (so tests can point at the repo copy), the idle-reset
window, and an escape-hatch apostrophe keycode if xkbcommon derivation ever fails.
"""

from __future__ import annotations

import os

# XKB layout/variant used to derive emit keycodes. `fi` on this machine; override
# via env so a layout change doesn't need a code edit.
LAYOUT = os.environ.get("APOSTROPHED_LAYOUT", "fi")
VARIANT = os.environ.get("APOSTROPHED_VARIANT", "")

# Match keyd's virtual output by NAME — the /dev/input/eventN node is not stable.
DEVICE_NAME = "keyd virtual keyboard"
POINTER_NAME = "keyd virtual pointer"

# Source of truth for rules. Installed copy by default; tests set the env to the
# repo copy.
RULES_PATH = os.environ.get("APOSTROPHED_RULES", "/usr/local/share/apostrophed/rules.tsv")

# Reset the word buffer after this many seconds of keyboard silence — a backstop
# for cursor moves we can't observe (e.g. a touchpad tap, which isn't the keyd
# pointer we watch).
IDLE_RESET_SECONDS = float(os.environ.get("APOSTROPHED_IDLE_RESET", "4.0"))

# Escape hatch: set to an int evdev keycode to override xkbcommon's apostrophe
# derivation. `None` means derive from the layout (the correct default).
_apos = os.environ.get("APOSTROPHED_APOSTROPHE_KEYCODE")
APOSTROPHE_KEYCODE: int | None = int(_apos) if _apos else None

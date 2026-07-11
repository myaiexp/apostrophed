# apostrophed

> A root evdev daemon that fixes missing apostrophes in contractions (`didnt` →
> `didn't`) and capitalizes standalone `i` → `I` as you type, on Wayland/Hyprland
> — race-free, by owning the keystroke stream instead of injecting like espanso.

## Stack

- **Language**: Python (`python-evdev`), mirroring the existing `/usr/local/bin/g915-gkeys` daemon pattern on this machine.
- **Runtime**: root systemd system service, binary in `/usr/local/bin/`.
- **Platform**: Wayland / Hyprland, keyboard layout `fi`.

## Project Structure

```
~/Projects/apostrophed/
├── CLAUDE.md
├── docs/
│   ├── ideas.md
│   └── plans/
│       └── apostrophed-design.md   # architecture + rationale (start here)
├── src/                            # daemon + rewrite engine (added in impl)
└── install.sh                      # deploys binary + systemd unit (added in impl)
```

## Key Patterns

- **Chains after keyd.** keyd grabs the physical Logitech devices (`046d:*`) and
  emits `keyd-virtual-keyboard`; apostrophed `EVIOCGRAB`s *that* virtual output and
  re-emits through its own `uinput` device. Never grab the physical keyboard.
- **Race-free by construction.** We own output ordering, so the word-ending key
  always lands after the correction — the espanso reorder bug is impossible. See
  the design doc for why espanso fails.
- **Safe-crash.** `EVIOCGRAB` releases on process death → Hyprland falls back to
  reading `keyd-virtual-keyboard`. A crash stops corrections, never the keyboard.
  Keep per-event processing trivial and non-blocking (a hang *would* stall input).
- **Rewrite logic is pure functions** (event sequence → emitted events), unit-
  tested with synthetic keystrokes. The evdev loop is a thin shell around it.
- **Rules are data**, not code — the ~43 safe contractions + `i`→`I` live in a
  data file. Only "safe" forms (apostrophe-less spelling isn't a real word).
- **Layout derived, not hardcoded.** The apostrophe keystroke is resolved from the
  active XKB keymap at startup (espanso's bug was assuming US → produced `ä`).
- **Toggle:** `pkill -USR1 apostrophed` pauses/resumes (paused = passthrough).

## Pointers

- **`docs/plans/apostrophed-design.md`** — full architecture, data flow, rationale,
  alternatives considered. Read first.
- **`docs/ideas.md`** — deferred / future work.

---

## Doc Management

Follows the global doc convention (`~/.claude/CLAUDE.md` "Per-Project Doc
Convention"). Not a web deploy — no VPS remotes; deployment is the local
`install.sh` + systemd unit.

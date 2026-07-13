# apostrophed

> An unprivileged evdev daemon that fixes missing apostrophes in contractions
> (`didnt` → `didn't`) and capitalizes standalone `i` → `I` as you type, on
> Wayland/Hyprland — race-free, by owning the keystroke stream instead of injecting
> like espanso.

## Stack

- **Language**: Python (`python-evdev`), mirroring the `g915-gkeys` daemon's evdev
  approach (but unprivileged — root turned out to be unnecessary, see below).
- **Runtime**: systemd **user** service, installed under `~/.local`. Runs as the
  logged-in user via `input`-group access to keyd's virtual devices + the logind
  `uaccess` ACL on `/dev/uinput`. **No root** (the toggle is a plain signal to your
  own process — that's what makes the keybind/waybar wiring privilege-free).
- **Platform**: Wayland / Hyprland, keyboard layout `fi`.

## Project Structure

```
~/Projects/apostrophed/
├── CLAUDE.md
├── docs/
│   ├── ideas.md
│   └── plans/
│       ├── apostrophed-design.md   # architecture + rationale (start here)
│       └── apostrophed-plan.md     # implementation plan (executed)
├── apostrophed/                    # the package
│   ├── config.py    rules.py    tokens.py    engine.py   # pure core
│   ├── keymap.py    # xkbcommon: char -> Keystroke (layout-derived)
│   ├── decode.py    # evdev event -> Token + modifier/capslock tracking
│   └── daemon.py    # grab/emit loop, signals, --passthrough/--dry-run
├── data/rules.tsv                  # 45 rules (source of truth)
├── tests/                          # pytest: rules, engine, decode, keymap, pipeline
├── bin/apostrophed                 # installed launcher (sys.path shim -> main)
├── bin/apostrophed-waybar          # waybar module: reads state file, inotify-driven
├── apostrophed.service             # systemd USER unit (WantedBy=default.target)
├── install.sh                      # user-space deploy (no sudo); systemctl --user
└── uninstall.sh                    # reverse of install.sh: stop/disable + rm files
```

Run tests: `python -m pytest -q` from the repo root (pyproject sets pythonpath).

## Key Patterns

- **Chains after keyd.** keyd grabs the physical Logitech devices (`046d:*`) and
  emits `keyd-virtual-keyboard`; apostrophed `EVIOCGRAB`s *that* virtual output and
  re-emits through its own `uinput` device. Never grab the physical keyboard. The
  upstream device name is env-overridable (`APOSTROPHED_DEVICE_NAME`), and
  `install.sh` preflights that keyd is installed + its virtual device is present
  (else the daemon would restart-loop with no hint). Grabbing the *physical* keyboard
  when keyd is absent is deferred future work — see `docs/ideas.md`.
- **Race-free by construction.** We own output ordering, so the word-ending key
  always lands after the correction — the espanso reorder bug is impossible. See
  the design doc for why espanso fails.
- **Safe-crash.** `EVIOCGRAB` releases on process death → Hyprland falls back to
  reading `keyd-virtual-keyboard`. A crash stops corrections, never the keyboard.
  Keep per-event processing trivial and non-blocking (a hang *would* stall input).
- **Startup key-reset.** A grab handoff (the service restarting *mid-keystroke*) can
  drop a key-up, stranding a key "down" in the compositor (seen once as a stuck
  space + an inverted `i` from a stranded modifier). `Daemon._release_all_keys`
  blanket-emits an up for every key on startup (ups only — a down would flip a lock
  like CapsLock), so any stranded key self-heals on restart. The dispatch logic
  itself never strands a key from balanced input (verified by ~210k fuzzed
  rollover sequences); the imbalance only comes from the handoff.
- **Rewrite logic is pure functions** (event sequence → emitted events), unit-
  tested with synthetic keystrokes. The evdev loop is a thin shell around it.
- **Undo-on-backspace** lives in the pure engine as `_undo` (a pre-baked revert
  `Correction`): armed when a correction fires, disarmed by the next token. A
  Backspace while armed rewinds the correction; the daemon consumes that Backspace
  (doesn't forward it). See `docs/plans/undo-on-backspace-design.md`.
- **Rules are data**, not code — 44 safe contractions + `i`→`I` (45 total) live in
  `data/rules.tsv`. Only "safe" forms (apostrophe-less spelling isn't a real word).
- **Layout derived, not hardcoded.** The apostrophe keystroke is resolved from the
  active XKB keymap at startup (espanso's bug was assuming US → produced `ä`). The
  layout *name* is auto-detected by `install.sh` (`localectl` → pinned into a systemd
  drop-in), falling back at runtime to `XKB_DEFAULT_LAYOUT` → `us`. The old `fi`
  code-default silently mistyped for every non-`fi` user.
- **Toggle:** `pkill -USR1 apostrophed` pauses/resumes (paused = passthrough).
  Works as your user (the daemon is yours), so the Hyprland keybind (`Alt+Shift+A`)
  and waybar click need no sudo. On each toggle the daemon writes `active`/`paused`
  to `$XDG_RUNTIME_DIR/apostrophed/state`; `bin/apostrophed-waybar` watches that file
  via `inotify` (event-driven, race-free) to drive the status module.

## Pointers

- **`docs/plans/apostrophed-design.md`** — full architecture, data flow, rationale,
  alternatives considered. Read first.
- **`docs/ideas.md`** — deferred / future work.

---

## Versioning

Single source of truth: `__version__` in `apostrophed/__init__.py`, surfaced by
`apostrophed --version`. SemVer, pre-1.0 (`0.x` — behavior may still shift):

- **MINOR** (`0.x+1.0`) — any user-facing change: a new/changed rule, a new feature,
  or a behavior change (pre-1.0, breaking changes bump MINOR too, not MAJOR).
- **PATCH** (`0.x.y+1`) — a bug fix with no new behavior.
- **No bump** — docs, tests, refactors, or cleanups with no user-visible effect.

Bump in the same commit that ships the change. Tag `vX.Y.Z` to mark a release.

---

## Doc Management

Follows the global doc convention (`~/.claude/CLAUDE.md` "Per-Project Doc
Convention"). Not a web deploy — deployment is the local `install.sh` + systemd
unit.

**Public repo:** https://github.com/myaiexp/apostrophed (MIT). `README.md` is the
user-facing entry point; this `CLAUDE.md` and `docs/` are dev-internal but public.
No sensitive content — keep it that way (no machine secrets, VPS paths, creds).

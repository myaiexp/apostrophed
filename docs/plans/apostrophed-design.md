# apostrophed — Design

A keystroke-level daemon that fixes missing apostrophes in contractions as you
type (`didnt` → `didn't`) and capitalizes the standalone pronoun `i` → `I`, on
Wayland/Hyprland, **without** the character-reordering that makes injection-based
tools unusable at real typing speed.

## Problem & why not espanso

The natural first tool is espanso (text expander). On Wayland it fails for this
use case with a **fixed ~1-keystroke injection latency**: espanso detects the
word-ending space, then backspaces and re-types the correction through a separate
virtual device while the user keeps typing. The next letter reliably lands inside
espanso's re-injected trailing space, producing `wouldn'tk now` instead of
`wouldn't know`. Zero-ing every injection delay does not fix it — the latency is
in espanso's evdev path and is not exposed as a tunable. Firing on the word
instead of the space doesn't help either (the racing keystroke is still one gap
away). The clipboard backend avoids the char-race but adds latency, needs a paste
shortcut that can't be correct everywhere on Wayland (Ctrl+V fails in Alacritty,
Ctrl+Shift+V breaks vim/readline), and pollutes clipboard history.

**Root cause:** espanso is an *external injector* racing the user's real
keystrokes. The fix is to *own the keystroke stream* — intercept at the evdev
layer, so our output ordering is deterministic and the race is structurally
impossible.

## Architecture

A single Python daemon (`python-evdev`) that sits **after keyd** in the input
chain:

```
physical kbd → keyd (grabs 046d:*, empty [main]) → keyd-virtual-keyboard
             → [apostrophed grabs this] → apostrophed uinput device → Hyprland
```

- **Grab** `keyd-virtual-keyboard` with `EVIOCGRAB` (exclusive). We grab keyd's
  *virtual output*, not the physical device, so keyd is untouched and keeps doing
  its job.
- **Emit** through our own `uinput` device, which Hyprland reads. Hyprland applies
  `kb_layout=fi` to it (as it does to all keyboards), so emitted keycodes are
  interpreted under the Finnish keymap.

**No feedback loop:** apostrophed only ever *reads* `keyd-virtual-keyboard` and
*writes* its own separate uinput device; it never reads its own output, so emitted
corrections can't re-enter the buffer.

**Safe-crash property:** `EVIOCGRAB` is released by the kernel if the process
dies, and Hyprland falls back to reading `keyd-virtual-keyboard` directly. So a
crash means "contractions stop being fixed," never "keyboard dead." (A *hang*
could stall input, so per-event processing must stay trivial and non-blocking.)

## Event pipeline / data flow

Every event is **forwarded through** to the output unchanged (normal typing is
never delayed), while a **shadow buffer** tracks the current word in parallel:

- **Letter key (a–z) press:** append `(keycode, shifted)` to the buffer; forward.
- **Word-ending key press** (space, tab, enter, punctuation, digits — anything
  non-letter): check the buffer against the rule set *before* forwarding this key.
  - **Match:** emit `N` backspaces (`N` = typed word length), emit the corrected
    character sequence, then forward the ending key. Clear buffer.
  - **No match:** forward the ending key. Clear buffer.
  - Because we emit synchronously and control ordering, the ending key always
    lands *after* the correction. No race.
- **Backspace:** forward; pop one char from the buffer (stays in sync with screen).
- **Cursor navigation** (arrows, Home/End, PgUp/Dn, mouse click) or **modifier
  shortcut** (Ctrl/Alt/Super + key): forward; **reset** the buffer. We can't track
  the cursor, so we refuse to rewrite rather than risk a wrong edit.
- **Shift:** tracked for case detection; forwarded.
- **Key repeat** (autorepeat) of a letter: append too, so backspace count stays
  correct (a repeated letter breaks any match anyway).

## Behavior

- **Rules:** 44 curated "safe" contractions (only forms whose apostrophe-less
  spelling is not itself a real English word — excludes `its`, `were`, `well`,
  `ill`, `id`, `wed`, `shed`, `hell`, `shell`, `lets`, `cant`, `wont`), plus
  standalone `i` → `I` — **45 rules total**. Stored as a **data file**
  (`<trigger>\t<replacement>`), not code — they are irreducible data (`want`/`front`
  prove the `-n't` rule can't be derived, so a curated list is correct, not lazy).
  **Source of truth: `data/rules.tsv` in this repo** — captured from the espanso
  YAML this session so it survives the Milestone 5 espanso teardown.
- **Case-matching:** the buffer records shift-state per letter, so the correction
  mirrors what was typed:
  - all-lowercase trigger → replacement as-defined (`didnt` → `didn't`; `im` →
    `I'm`; `i` → `I` — intrinsic capitals preserved).
  - first-letter-uppercase → capitalize first letter (`Didnt` → `Didn't`).
  - all-uppercase → uppercase all (`DIDNT` → `DIDN'T`).
  - **irregular/mixed case** that fits none of the three patterns (`dIdnt`,
    `DidNT`) → **no correction**, pass through unchanged. These are typos/accidents;
    not worth guessing an output.
  - **no-op skip:** if the typed word already equals the corrected form, emit
    nothing — no backspace/re-emit cycle on the hot path.
- **No sentence-start auto-capitalization** — deliberately excluded. It's a
  false-positive minefield (`etc. the`, `v1.2`, `google.com/x`, ellipses) and the
  user does not want auto-capitalization at all beyond `i`→`I`.

## Layout-aware emission

Triggers are all letters; letter keycodes are layout-stable on `fi` (QWERTY base).
The only special character we *emit* is the apostrophe (plus Shift for capitals).
At startup, determine how to type `'` (U+0027) under the **active XKB keymap**
rather than hardcoding `fi`, so it's correct now and survives a layout change —
this is exactly what espanso got wrong (it assumed US and produced `ä`). If a
clean xkb binding isn't trivially available in Python, fall back to a documented
config value (`apostrophe_keycode`, defaulting to the `fi` value). The plan pins
the exact mechanism.

## Permissions & lifecycle

Matches the machine's existing pattern (keyd and `g915-gkeys` are both root system
services with binaries in `/usr/local/bin`):

- **Root system service:** unit at `/etc/systemd/system/apostrophed.service`,
  binary at `/usr/local/bin/apostrophed`, enabled at boot. Root sidesteps
  `/dev/uinput` + evdev-grab permission faff. This adds **no new trust boundary** —
  keyd and g915-gkeys already have full keystroke access as root on this box.
- **Startup ordering (do NOT copy g915-gkeys verbatim):** g915-gkeys has no keyd
  dependency, but apostrophed grabs `keyd-virtual-keyboard` *by name*, which only
  exists once keyd is up. The unit must declare `After=keyd.service`, **and** the
  daemon must wait/retry for the device to appear before grabbing (defensive
  against ordering gaps and keyd restarts) rather than assuming it's present.
- **Source repo** at `~/Projects/apostrophed/` with an **install script** that
  deploys the binary + unit (and any udev rule) and enables the service.

## Config & toggle

- **Config:** one data file for the rules, editable without touching code.
- **Toggle:** `SIGUSR1` flips a pause flag (paused = pure passthrough, no
  buffering/rewriting). `pkill -USR1 apostrophed` toggles instantly — no sudo, no
  restart. Wiring it to a Hyprland keybind is an optional later add.

## Testing

- **Unit tests (bulk of correctness):** the buffer / match / case-rewrite logic is
  written as **pure functions** (event sequence in → emitted events out), tested
  with synthetic keystroke sequences — no hardware needed. TDD the rewrite engine,
  covering every rule, all three case patterns, backspace sync, and the
  navigation/shortcut reset paths.
- **`--dry-run` mode:** reads real input but *logs* intended corrections instead of
  emitting — safe live testing before it touches real typing.
- **Functional verification:** run the daemon, type in a real field, confirm
  corrections and the absence of the espanso reorder.

## Milestones (de-risking order)

0. **Spike the grab-chain first:** prove apostrophed can grab
   `keyd-virtual-keyboard` (with device-wait/retry + `After=keyd.service`), forward
   transparently, and have Hyprland read our uinput device — before building the
   engine. This is the core technical risk.
1. Pure-function rewrite engine + unit tests.
2. Wire engine to the live evdev loop; `--dry-run`.
3. Layout-aware apostrophe emission.
4. Packaging (install script, systemd unit), SIGUSR1 toggle.
5. Espanso teardown.

## Espanso teardown (cleanup during implementation)

`espanso service unregister` + `espanso stop`; `yay -R --noconfirm espanso-wayland`
(needs sudo — hand to user); remove `~/.config/espanso` and `~/.cache/espanso`
(created this session).

## Alternatives considered

- **espanso Inject backend** — the race described above; not fixable via config.
- **espanso Clipboard backend** — atomic paste avoids the char-race but adds
  latency, needs an impossible-to-get-right paste shortcut on Wayland
  (Alacritty vs vim vs browsers), and spams clipboard history. Net-worse.
- **interception-tools + custom plugin** — same race-free result, but adds a
  dependency, a C/C++ plugin, and `udevmon` config to coexist with keyd: more
  moving parts than a small Python daemon that mirrors the proven `g915-gkeys`
  pattern already on this machine.
- **Patch keyd** — keyd has no word-buffer concept; would mean forking C. Rejected.
- **Sentence-start auto-capitalization** — false-positive minefield and unwanted.
- **General text-expander (espanso replacement)** — deliberately out of scope;
  keeping the code small and provably correct matters more in the keystroke hot
  path. Could evolve later (see `docs/ideas.md`).
```

# apostrophed

> A race-free evdev daemon that fixes missing apostrophes in contractions
> (`didnt` → `didn't`) and capitalizes the standalone pronoun `i` → `I` as you
> type — on Wayland, by **owning the keystroke stream** instead of injecting like a
> text expander. Runs unprivileged as a systemd user service.

## Why not a text expander?

The obvious tool is a text expander like [espanso](https://espanso.org/). On
Wayland it fails for this use case with a fixed, un-tunable injection latency:
espanso detects the word-ending space, then backspaces and re-types the correction
through a _separate_ virtual device while you keep typing. The next letter reliably
lands inside espanso's re-injected trailing space, producing `wouldn'tk now`
instead of `wouldn't know`. Zeroing every configurable delay doesn't fix it — the
latency is in the evdev path, and the tool is racing your real keystrokes.

**apostrophed removes the race by construction.** It intercepts at the evdev layer
and _owns_ output ordering, so the word-ending key is always emitted _after_ the
correction. There is no second device racing you.

## How it works

```
physical kbd → keyd (grabs it, emits "keyd virtual keyboard")
             → [apostrophed grabs that] → apostrophed uinput device → compositor
```

- **Grabs** `keyd virtual keyboard` with `EVIOCGRAB` (keyd's _virtual output_, never
  your physical keyboard), and **re-emits** through its own `uinput` device.
- Every event is forwarded verbatim, while a shadow buffer tracks the current word.
  On a word boundary, if the buffer matches a rule, it emits backspaces + the
  correction **before** forwarding the boundary key.
- **Layout-aware:** the apostrophe keystroke is derived from the active XKB keymap
  at startup (not hardcoded), so it's correct on non-US layouts.
- **Safe-crash:** `EVIOCGRAB` is released by the kernel on process death, so the
  compositor falls back to reading keyd directly. A crash stops _corrections_, never
  the keyboard.
- **Fast-typing safe:** when key rollover leaves a letter still held as the boundary
  fires, the daemon releases it before re-emitting, so nothing is dropped.
- **Undo on Backspace:** hitting Backspace immediately after a correction rewinds
  it — the corrected word and the space that triggered it are removed and your
  literal word is retyped. Any other keystroke first cancels the window.

The correction logic is a set of **pure functions** (token stream → correction),
fully unit-tested without hardware; the evdev/uinput loop is a thin shell around it.

## Privacy

apostrophed sits in your keystroke path and grabs every key — structurally the same
shape as a keylogger. That deserves a straight answer, and the code backs every
claim below (it's all in [`engine.py`](apostrophed/engine.py) and
[`decode.py`](apostrophed/decode.py)):

- **In memory, one word at a time.** The only thing it retains is the word you're
  currently typing, in a plain list in RAM (`Engine._buffer`). It's cleared on every
  word boundary (space, punctuation, digit, Enter), every cursor move (arrows,
  Home/End, mouse click), any Ctrl/Alt/Meta chord, and after a few seconds idle.
  Nothing accumulates — there is no history and no full-stream buffer.
- **Never written to disk.** The buffer is never serialized. The one file apostrophed
  writes holds exactly `active` or `paused` — no keystrokes — and lives in a
  RAM-backed runtime dir (`$XDG_RUNTIME_DIR`), not on disk.
- **No network. At all.** There is no socket, HTTP, or subprocess code anywhere in
  the package — the entire import list is the Python standard library plus `evdev`
  and `xkbcommon`. It is structurally incapable of sending your keystrokes anywhere.
- **Nothing you type is logged in normal use.** The service logs only lifecycle
  status (device found, rules loaded, layout, paused/resumed). The lone exception is
  opt-in: the diagnostic `--dry-run` flag and `APOSTROPHED_DEBUG=1` log each
  *corrected word* (e.g. `didn't`) — not the raw stream — to the journal for
  troubleshooting. Both are off by default.

In short: it has to see every key to own output ordering (that's what makes it
race-free), but it only ever holds the current word in memory, matches it against a
fixed [rule list](data/rules.tsv), and forgets it. The buffer and every reset live
in one small, pure, unit-tested module — don't take my word for it, read it.

## Requirements

- Linux with `/dev/uinput` and evdev
- [**keyd**](https://github.com/rvaiya/keyd) — apostrophed chains after it, grabbing
  `keyd virtual keyboard` by name; `install.sh` checks it's installed and running.
  (To chain after a different virtual keyboard, set `APOSTROPHED_DEVICE_NAME`.)
- A Wayland compositor (developed on Hyprland)
- Python 3.11+, [`python-evdev`](https://python-evdev.readthedocs.io/),
  [`python-xkbcommon`](https://github.com/sde1000/python-xkbcommon)
- **No root.** Runs as your user via a systemd **user** service. Needs only
  membership in the `input` group (to grab keyd's virtual devices) and the logind
  `uaccess` ACL on `/dev/uinput` (present in a normal graphical session).

## Install

```sh
git clone https://github.com/myaiexp/apostrophed
cd apostrophed
./install.sh          # NOT sudo — this is a user service
```

`install.sh` is idempotent and fully user-space: it preflights that keyd is
installed and its virtual keyboard is present, **auto-detects your keyboard layout**
(via `localectl`) and pins it into the unit, then deploys the package to
`~/.local/lib`, rules to `~/.local/share`, launchers to `~/.local/bin`, and a user
unit to `~/.config/systemd/user`, and enables and starts it. Check it:

```sh
systemctl --user is-active apostrophed
journalctl --user -u apostrophed -f
```

> If you're not in the `input` group yet: `sudo usermod -aG input $USER`, then log
> out and back in. That is the only privileged step, and it's a one-time account
> change — the daemon itself never runs as root.

## Uninstall

```sh
./uninstall.sh        # stops + disables the service, removes installed files
```

The exact inverse of `install.sh`, no root. Your keyboard is unaffected (Hyprland
falls back to reading keyd directly). It leaves `evdev`/`xkbcommon` and keyd in
place (installed separately), and any Hyprland keybind or waybar module you added —
remove those by hand.

## Usage

Once installed it just runs. To pause/resume (paused = pure passthrough):

```sh
pkill -USR1 apostrophed   # works as your user — no sudo, since the daemon is yours
```

Run modes (for testing, before installing — point it at the repo rules; stop the
service first so the grab is free):

```sh
# grab-chain spike: forward only, no correction
APOSTROPHED_RULES=data/rules.tsv python -m apostrophed.daemon --passthrough

# dry-run: log intended corrections, emit nothing
APOSTROPHED_RULES=data/rules.tsv python -m apostrophed.daemon --dry-run
```

### Desktop integration (optional)

Because the toggle is a plain signal to _your_ process, wiring it up needs no
privilege bridge.

**Hyprland keybind** — in `~/.config/hypr/bindings.conf`:

```
bindd = ALT SHIFT, A, Toggle apostrophed, exec, pkill -USR1 apostrophed
```

**Waybar status indicator** — the daemon publishes its state to
`$XDG_RUNTIME_DIR/apostrophed/state`, and the installed `apostrophed-waybar` helper
turns that into a live module (event-driven via `inotify`, so it needs no polling
and can't race the toggle). Add to `~/.config/waybar/config.jsonc`:

```jsonc
"custom/apostrophed": {
  "exec": "~/.local/bin/apostrophed-waybar",
  "return-type": "json",
  "on-click": "pkill -USR1 apostrophed"
}
```

and place `"custom/apostrophed"` in one of the `modules-*` arrays. Style the
`.active` / `.paused` / `.off` classes in `style.css` to taste.

### Configuration (environment variables)

| Variable                         | Default                                 | Purpose                                                                        |
| -------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------ |
| `APOSTROPHED_LAYOUT`             | detected → `XKB_DEFAULT_LAYOUT` → `us`  | XKB layout used to derive emit keycodes (`install.sh` pins the detected value) |
| `APOSTROPHED_VARIANT`            | detected → `XKB_DEFAULT_VARIANT` → `""` | XKB variant                                                                    |
| `APOSTROPHED_DEVICE_NAME`        | `keyd virtual keyboard`                 | name of the upstream virtual keyboard to grab                                  |
| `APOSTROPHED_POINTER_NAME`       | `keyd virtual pointer`                  | name of the pointer watched for click-reset                                    |
| `APOSTROPHED_RULES`              | `~/.local/share/apostrophed/rules.tsv`  | rule file path                                                                 |
| `APOSTROPHED_IDLE_RESET`         | `4.0`                                   | seconds of silence before the word buffer resets                               |
| `APOSTROPHED_STATE`              | `$XDG_RUNTIME_DIR/apostrophed/state`    | enabled/paused state file for indicators                                       |
| `APOSTROPHED_APOSTROPHE_KEYCODE` | _(derived)_                             | escape hatch: force an evdev keycode for `'`                                   |
| `APOSTROPHED_DEBUG`              | _(off)_                                 | log each applied correction                                                    |

## Rules

Rules live in [`data/rules.tsv`](data/rules.tsv) as `<trigger>\t<replacement>`, one
per line — pure data, editable without touching code. The set is **44 curated
"safe" contractions plus `i` → `I`** (45 total). "Safe" means the apostrophe-less
spelling is not itself a real word, so there are **zero false positives** — words
like `its`, `were`, `well`, `cant`, `wont`, `lets` are deliberately excluded because
they collide with real words. Casing is mirrored: `didnt` → `didn't`, `Didnt` →
`Didn't`, `DIDNT` → `DIDN'T`; mixed case is left untouched.

## Testing

```sh
python -m pytest -q
```

The suite covers rule loading, the rewrite engine (every rule + all case patterns),
event decoding, layout-aware keymap derivation, and a headless end-to-end pipeline
test that asserts the anti-reorder guarantee and the fast-typing rollover fix — all
without hardware.

## Caveats

- Built and tested for a **keyd + Hyprland + `fi`** setup; the layout is auto-
  detected at install (override with `APOSTROPHED_LAYOUT`), and a non-keyd virtual
  keyboard works via `APOSTROPHED_DEVICE_NAME`.
- Remaining known edge cases are tracked in [`docs/ideas.md`](docs/ideas.md).

Design rationale, data flow, and alternatives considered:
[`docs/plans/apostrophed-design.md`](docs/plans/apostrophed-design.md).

## License

[MIT](LICENSE)

# apostrophed

> A race-free root evdev daemon that fixes missing apostrophes in contractions
> (`didnt` → `didn't`) and capitalizes the standalone pronoun `i` → `I` as you
> type — on Wayland, by **owning the keystroke stream** instead of injecting like a
> text expander.

## Why not a text expander?

The obvious tool is a text expander like [espanso](https://espanso.org/). On
Wayland it fails for this use case with a fixed, un-tunable injection latency:
espanso detects the word-ending space, then backspaces and re-types the correction
through a *separate* virtual device while you keep typing. The next letter reliably
lands inside espanso's re-injected trailing space, producing `wouldn'tk now`
instead of `wouldn't know`. Zeroing every configurable delay doesn't fix it — the
latency is in the evdev path, and the tool is racing your real keystrokes.

**apostrophed removes the race by construction.** It intercepts at the evdev layer
and *owns* output ordering, so the word-ending key is always emitted *after* the
correction. There is no second device racing you.

## How it works

```
physical kbd → keyd (grabs it, emits "keyd virtual keyboard")
             → [apostrophed grabs that] → apostrophed uinput device → compositor
```

- **Grabs** `keyd virtual keyboard` with `EVIOCGRAB` (keyd's *virtual output*, never
  your physical keyboard), and **re-emits** through its own `uinput` device.
- Every event is forwarded verbatim, while a shadow buffer tracks the current word.
  On a word boundary, if the buffer matches a rule, it emits backspaces + the
  correction **before** forwarding the boundary key.
- **Layout-aware:** the apostrophe keystroke is derived from the active XKB keymap
  at startup (not hardcoded), so it's correct on non-US layouts.
- **Safe-crash:** `EVIOCGRAB` is released by the kernel on process death, so the
  compositor falls back to reading keyd directly. A crash stops *corrections*, never
  the keyboard.
- **Fast-typing safe:** when key rollover leaves a letter still held as the boundary
  fires, the daemon releases it before re-emitting, so nothing is dropped.

The correction logic is a set of **pure functions** (token stream → correction),
fully unit-tested without hardware; the evdev/uinput loop is a thin shell around it.

## Requirements

- Linux with `/dev/uinput` and evdev
- [**keyd**](https://github.com/rvaiya/keyd) — apostrophed chains after it, grabbing
  `keyd virtual keyboard` by name. (Targeting a different virtual keyboard means
  editing `DEVICE_NAME` in `apostrophed/config.py`.)
- A Wayland compositor (developed on Hyprland)
- Python 3.11+, [`python-evdev`](https://python-evdev.readthedocs.io/),
  [`python-xkbcommon`](https://github.com/sde1000/python-xkbcommon)
- Runs as **root** (for evdev grab + uinput), as a systemd system service

## Install

```sh
git clone https://github.com/myaiexp/apostrophed
cd apostrophed
sudo ./install.sh
```

`install.sh` is idempotent: it deploys the package to `/usr/local/lib`, rules to
`/usr/local/share`, a launcher to `/usr/local/bin`, and a `After=keyd.service` unit
to `/etc/systemd/system`, then enables and starts it. Check it:

```sh
systemctl is-active apostrophed
journalctl -u apostrophed -f
```

## Usage

Once installed it just runs. To pause/resume (paused = pure passthrough):

```sh
pkill -USR1 apostrophed
```

Run modes (for testing, before installing — point it at the repo rules):

```sh
# grab-chain spike: forward only, no correction
sudo APOSTROPHED_RULES=data/rules.tsv python -m apostrophed.daemon --passthrough

# dry-run: log intended corrections, emit nothing
sudo APOSTROPHED_RULES=data/rules.tsv python -m apostrophed.daemon --dry-run
```

### Configuration (environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `APOSTROPHED_LAYOUT` | `fi` | XKB layout used to derive emit keycodes |
| `APOSTROPHED_VARIANT` | `""` | XKB variant |
| `APOSTROPHED_RULES` | `/usr/local/share/apostrophed/rules.tsv` | rule file path |
| `APOSTROPHED_IDLE_RESET` | `4.0` | seconds of silence before the word buffer resets |
| `APOSTROPHED_APOSTROPHE_KEYCODE` | *(derived)* | escape hatch: force an evdev keycode for `'` |
| `APOSTROPHED_DEBUG` | *(off)* | log each applied correction |

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

- Built and tested for a **keyd + Hyprland + `fi`** setup; other layouts work via
  `APOSTROPHED_LAYOUT`, other virtual keyboards via `DEVICE_NAME`.
- Known edge cases are tracked in [`docs/ideas.md`](docs/ideas.md) (e.g. holding
  Shift *continuously across* a corrected word).

Design rationale, data flow, and alternatives considered:
[`docs/plans/apostrophed-design.md`](docs/plans/apostrophed-design.md).

## License

[MIT](LICENSE)

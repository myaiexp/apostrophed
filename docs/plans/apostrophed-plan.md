# apostrophed Implementation Plan

> **Historical (executed) plan.** It describes the original **root system service**
> install. That was later dropped: the daemon now runs as an unprivileged systemd
> **user** service (`~/.local` + `~/.config/systemd/user`, no sudo). References
> below to root / `/usr/local` / `/etc/systemd` are superseded — see
> [`apostrophed-design.md`](apostrophed-design.md) "Permissions & lifecycle" for the
> current model and why root was unnecessary.

**Goal:** A race-free evdev daemon that fixes 44 "safe" contractions + `i`→`I`
as you type on Wayland/Hyprland, by grabbing the post-keyd keyboard stream and
re-emitting corrections in deterministic order.

**Architecture:** Grab `keyd virtual keyboard` (`EVIOCGRAB`, matched by name),
forward every event through our own `uinput` device (which Hyprland reads), while a
shadow buffer tracks the current word. On a word-ending key, if the buffer matches
a rule, emit backspaces + the corrected text *before* forwarding the ending key.
The rewrite logic is a pure `Engine` (event tokens in → `Correction` out), unit-
tested without hardware; the daemon is a thin evdev/uinput shell around it.

**Tech Stack:** Python 3.11+, `python-evdev` (grab/emit — installed),
`python-xkbcommon` (layout→keycode derivation — in `extra`, to install), systemd
system service (root), `tomllib` (stdlib) for config.

**Reference pattern:** `/usr/local/bin/g915-gkeys` (root evdev-adjacent daemon on
this machine) — reuse its device-wait retry, `SIGTERM`/`SIGINT` uinput-destroy
cleanup, and `print(..., flush=True)` journald logging. Do **not** copy its raw
ioctl style; use python-evdev.

**Key facts (verified this session):**
- Target device name: `keyd virtual keyboard` (currently `/dev/input/event20`, but
  match by **name** — nodes aren't stable). Pointer is a separate device
  (`keyd virtual pointer`), not grabbed.
- `python-evdev` importable; `python-xkbcommon 1.5.1-3` available in `extra`.
- Rule set: `data/rules.tsv` (45 lines: 44 contractions + `i`→`I`).

---

## File Structure

```
apostrophed/
├── __init__.py
├── config.py      # LAYOUT, paths, idle-reset seconds; env overrides
├── rules.py       # load rules.tsv -> dict[str,str]
├── tokens.py      # Token dataclasses: Letter/WordBoundary/Backspace/Reset; Correction
├── engine.py      # pure Engine: feed(token) -> Optional[Correction] (the heart)
├── keymap.py      # xkbcommon: char -> Keystroke(keycode, shift, altgr)
├── decode.py      # evdev event -> Token (+ modifier/capslock state tracking)
└── daemon.py      # grab/emit loop, signals (SIGTERM/SIGINT/SIGUSR1), --dry-run, main()
data/rules.tsv                 # source of truth (exists)
tests/
├── test_rules.py
├── test_engine.py             # bulk of correctness
├── test_decode.py
└── test_keymap.py             # runs against installed xkbcommon
bin/apostrophed                # launcher: sys.path shim -> daemon.main()
apostrophed.service            # systemd unit template (After=keyd.service)
install.sh                     # deploy lib + data + unit + launcher; enable service
uninstall-espanso.sh           # teardown of the espanso experiment
```

Split rationale: `engine.py` is pure and holds all the tricky logic (fully
testable); `decode.py` and `daemon.py` isolate the evdev/uinput I/O; `keymap.py`
isolates the one external-lib dependency. Each file has one responsibility and is
small enough to hold in context.

---

## Task 1: Rule loading  [Mode: Direct]

**Files:** Create `apostrophed/rules.py`; Test `tests/test_rules.py`

**Contracts:**
```python
def load_rules(path: str | Path) -> dict[str, str]:
    """Parse rules.tsv into {trigger: replacement}. Skips blank lines and
    lines starting with '#'. Triggers are lowercase; raises ValueError on a
    malformed line (not exactly one tab) or a duplicate/non-lowercase trigger."""
```

**Test Cases:**
```python
def test_loads_all_rules():
    rules = load_rules("data/rules.tsv")
    assert len(rules) == 45
    assert rules["didnt"] == "didn't"
    assert rules["im"] == "I'm"
    assert rules["i"] == "I"

def test_excluded_collision_words_absent():
    rules = load_rules("data/rules.tsv")
    for w in ["its", "were", "well", "ill", "id", "wed", "shed", "cant", "wont", "lets"]:
        assert w not in rules

def test_comments_and_blanks_skipped(tmp_path):
    f = tmp_path / "r.tsv"; f.write_text("# c\n\ndidnt\tdidn't\n")
    assert load_rules(f) == {"didnt": "didn't"}

def test_malformed_line_raises(tmp_path):
    f = tmp_path / "r.tsv"; f.write_text("didnt didn't\n")  # space, no tab
    with pytest.raises(ValueError):
        load_rules(f)
```

**Verification:** `pytest tests/test_rules.py -v` → all pass. **Commit after passing.**

---

## Task 2: Grab-chain spike — minimal passthrough daemon  [Mode: Delegated]

De-risks the core technical risk (Milestone 0) *before* any rewrite logic: prove we
can insert ourselves after keyd and type normally.

**Files:** Create `apostrophed/daemon.py` (skeleton), `apostrophed/config.py`

**Contracts:**
```python
# config.py
LAYOUT = os.environ.get("APOSTROPHED_LAYOUT", "fi")
DEVICE_NAME = "keyd virtual keyboard"
RULES_PATH = os.environ.get("APOSTROPHED_RULES", "/usr/local/share/apostrophed/rules.tsv")
IDLE_RESET_SECONDS = 4.0
APOSTROPHE_KEYCODE = None   # escape hatch: int evdev keycode to override xkbcommon derivation

# daemon.py
def find_device(name: str, timeout: float = 30.0) -> evdev.InputDevice:
    """Return the InputDevice whose .name == name, retrying every 0.2s until
    timeout (keyd's virtual device may not exist yet at boot). Raise on timeout."""

def run_passthrough() -> None:
    """Grab the device, create UInput.from_device(dev), forward every event
    unchanged (write_event + syn). SIGTERM/SIGINT -> ungrab, close uinput, exit 0."""
```

**Constraints:**
- Match by **name**, never a hardcoded `event*` node.
- `dev.grab()` must be released on any exit path (finally / signal handler), so a
  crash leaves Hyprland reading `keyd virtual keyboard` directly (safe-crash).
- Per-event work must be trivial/non-blocking (a hang stalls the keyboard).
- Use `select`/`read_loop` such that signals are handled promptly.
- Provide a minimal `main()` under `if __name__ == "__main__"` that dispatches
  `--passthrough` (and later `--dry-run`), so `python -m apostrophed.daemon` runs as
  the verification command shows.

**Verification (functional — no unit test for the I/O shell):**
Run `sudo APOSTROPHED_RULES=data/rules.tsv python -m apostrophed.daemon --passthrough`
in a scratch terminal, then type in another window. Expected: typing works exactly
as normal (every key passes through), and `Ctrl+C` restores direct input with no
stuck keys. This validates the grab→uinput→Hyprland chain.

**Commit after the chain is confirmed working.**

---

## Task 3: Rewrite engine (pure)  [Mode: Direct]

The heart. No evdev imports — operates on tokens, fully unit-tested.

**Files:** Create `apostrophed/tokens.py`, `apostrophed/engine.py`; Test `tests/test_engine.py`

**Contracts:**
```python
# tokens.py
@dataclass(frozen=True)
class Letter:      char: str          # single cased letter, 'a'..'z' or 'A'..'Z'
@dataclass(frozen=True)
class WordBoundary: pass              # space/tab/enter/punct/digit typed
@dataclass(frozen=True)
class Backspace:   pass
@dataclass(frozen=True)
class Reset:       pass               # nav key, shortcut, mouse click, idle
Token = Letter | WordBoundary | Backspace | Reset

@dataclass(frozen=True)
class Correction:
    delete_count: int                 # backspaces to emit (== len typed word)
    text: str                         # corrected text to type, e.g. "didn't"

# engine.py
class Engine:
    def __init__(self, rules: dict[str, str]): ...
    def feed(self, token: Token) -> Correction | None:
        """Letter -> append; Backspace -> pop (no-op if empty); Reset -> clear; WordBoundary ->
        evaluate current buffer then clear. Returns a Correction only on a
        matching WordBoundary, else None."""
```

**Case-mapping rules (evaluate on WordBoundary):**
- `key = ''.join(buffer).lower()`; if `key not in rules` → None.
- pattern from typed letters: all-lower / first-upper (only first is upper) /
  all-upper. **Anything else (mixed, e.g. `dIdnt`) → None.**
- apply pattern to `rules[key]`: all-lower→as-is; first-upper→capitalize first
  char; all-upper→`.upper()`.
- **no-op skip:** if resulting text == typed word → None.
- else → `Correction(delete_count=len(buffer), text=result)`.

**Test Cases:**
```python
def feed_word(engine, s):            # helper: feed letters then a WordBoundary
    out = [engine.feed(Letter(c)) for c in s]
    return engine.feed(WordBoundary())

def test_basic_contraction():
    e = Engine(RULES)
    assert feed_word(e, "didnt") == Correction(5, "didn't")

def test_first_upper_preserved():
    assert feed_word(Engine(RULES), "Didnt") == Correction(5, "Didn't")

def test_all_upper():
    assert feed_word(Engine(RULES), "DIDNT") == Correction(5, "DIDN'T")

def test_intrinsic_capital_lowercase_typed():
    assert feed_word(Engine(RULES), "im") == Correction(2, "I'm")

def test_standalone_i():
    assert feed_word(Engine(RULES), "i") == Correction(1, "I")

def test_noop_skip_when_already_correct():
    # typing capital "I" already: key 'i', result 'I' == typed -> no rewrite
    e = Engine(RULES); e.feed(Letter("I"))
    assert e.feed(WordBoundary()) is None

def test_mixed_case_no_correction():
    assert feed_word(Engine(RULES), "dIdnt") is None

def test_non_trigger_word():
    assert feed_word(Engine(RULES), "hello") is None

def test_backspace_syncs_buffer():
    e = Engine(RULES)
    for c in "dont": e.feed(Letter(c))
    e.feed(Backspace())                       # buffer now "don"
    for c in "e": e.feed(Letter(c))           # "done"
    assert e.feed(WordBoundary()) is None

def test_backspace_on_empty_is_noop():
    e = Engine(RULES); e.feed(Backspace())    # must not underflow/raise
    assert feed_word(e, "dont") == Correction(4, "don't")

def test_reset_clears_buffer():
    e = Engine(RULES)
    for c in "dont": e.feed(Letter(c))
    e.feed(Reset())
    assert e.feed(WordBoundary()) is None

def test_boundary_clears_between_words():
    e = Engine(RULES)
    assert feed_word(e, "hello") is None
    assert feed_word(e, "dont") == Correction(4, "don't")

def test_every_rule_roundtrips():
    e = Engine(RULES)
    for trig, repl in RULES.items():
        assert feed_word(e, trig) == Correction(len(trig), repl)
```

**Verification:** `pytest tests/test_engine.py -v` → all pass. **Commit after passing.**

---

## Task 4: Layout-aware keymap  [Mode: Delegated]

Isolate the one external-lib dependency. Derive keycodes from the layout name via
`python-xkbcommon` — no hardcoded apostrophe keycode.

**Files:** Create `apostrophed/keymap.py`; Test `tests/test_keymap.py`

**Contracts:**
```python
@dataclass(frozen=True)
class Keystroke:
    keycode: int      # evdev keycode (ecodes.KEY_*)
    shift: bool
    altgr: bool       # AltGr / ISO_Level3_Shift needed

class KeyMap:
    def __init__(self, layout: str, variant: str = ""): ...
    def stroke(self, ch: str) -> Keystroke:
        """Return the keycode + modifier level that produces `ch` under the
        layout. Supports 'a'..'z', 'A'..'Z', and "'". Raises KeyError if the
        char is unreachable in this layout."""
```

**Implementation notes (for the implementer to verify against the installed lib):**
- Build a keymap with `xkbcommon` from names (rules/model/`layout`/`variant`).
- For the target chars, scan keycodes × levels; match the level's keysym to the
  desired char (letters via `char_to_keysym`/unicode; apostrophe = U+0027).
- Convert xkb keycode → evdev keycode (`evdev = xkb - 8`).
- Determine `shift`/`altgr` from which level produced the char (level 0 none,
  level 1 shift, level 2 altgr, level 3 shift+altgr — verify against the lib).
- Prefer the lib's mods-for-level query over the level→modifier assumption above
  (it's layout-dependent). Assert the matched keysym is exactly **U+0027**
  (apostrophe), not the look-alike **U+00B4** (acute accent / dead key).

**Test Cases (run against installed xkbcommon, layout="fi"):**
```python
def test_lowercase_letter():
    k = KeyMap("fi").stroke("d")
    assert k.keycode == ecodes.KEY_D and not k.shift

def test_uppercase_letter_needs_shift():
    assert KeyMap("fi").stroke("D") == Keystroke(ecodes.KEY_D, True, False)

def test_apostrophe_resolves():
    # the espanso bug: must NOT be the KEY_APOSTROPHE (ä) position under fi
    k = KeyMap("fi").stroke("'")
    assert k.keycode != ecodes.KEY_APOSTROPHE   # fi apostrophe is elsewhere
    # and round-trips to U+0027 under fi (asserted via xkbcommon in the test)

def test_unreachable_char_raises():
    with pytest.raises(KeyError):
        KeyMap("fi").stroke("€")   # not in our emit set / example unreachable
```

**Constraints:** No hardcoded fi keycodes in the module — everything derived from
the layout. Build once at startup (not per-keystroke).

**Verification:** `pytest tests/test_keymap.py -v` → all pass. **Commit after passing.**

---

## Task 5: Decode + wire engine/keymap into the daemon  [Mode: Delegated]

Turn the passthrough spike into the full corrector.

**Files:** Create `apostrophed/decode.py`; Modify `apostrophed/daemon.py`;
Test `tests/test_decode.py`

**Contracts:**
```python
# decode.py — pure classification given current modifier state
class ModState:                       # tracks held shift/ctrl/alt/meta + capslock
    def update(self, event) -> None: ...
    @property
    def shift_active(self) -> bool: ...      # shift XOR capslock, for letters
    @property
    def shortcut_active(self) -> bool: ...   # ctrl/alt/meta held

def decode(event, mods: ModState) -> Token | None:
    """Map an EV_KEY press/repeat (value 1 or 2) to a Token, using mods:
      - ctrl/alt/meta held        -> Reset (it's a shortcut)
      - letter a-z                -> Letter(cased via mods.shift_active)
      - space/tab/enter/punct/digit -> WordBoundary
      - backspace                 -> Backspace
      - arrows/home/end/pgup/pgdn/ins/del -> Reset
      - anything else (F-keys, media, ...) -> Reset
    Return None for events that aren't buffer-relevant (releases, modifier
    keys themselves, EV_SYN)."""
```

**Daemon integration (`daemon.py`):**
- Main loop `select`s over the keyboard fd **and** the `keyd virtual pointer` fd
  (opened read-only, not grabbed): any pointer button press → `engine.feed(Reset())`
  (cursor may have moved). Also reset on `IDLE_RESET_SECONDS` of no keyboard input.
  (Only the keyd pointer is watched — a touchpad or other non-keyd pointer won't
  trigger the click-reset; the idle-reset is the backstop for those.)
- For each keyboard event, **decode and feed the engine FIRST, then forward** — the
  forward order depends on the result:
  - No token, or `engine.feed` returns `None` (Letter/Backspace/Reset, and a
    non-matching WordBoundary): forward the event immediately (`ui.write_event`; syn).
  - `engine.feed` returns a `Correction` (only possible on a WordBoundary): **hold**
    the boundary event, emit `delete_count` × Backspace, then each char of
    `corr.text`, and **only then** forward the held boundary event.
  - ⚠️ Do **NOT** forward the boundary before the backspaces — that deletes the
    boundary + letters and rebuilds the exact reorder bug this project exists to
    kill (`didnt ` → forward space → 5 backspaces → `di`). "Always forward first" is
    correct for every token *except* the boundary key, which is the whole point.
  - (Releases, modifier keys, EV_SYN forward as-is; they never yield a correction.)
- Emission of one char = optional Shift/AltGr down → key down → key up → modifiers
  up → syn. **CapsLock compensation:** we forward CapsLock through to our uinput
  device, so Hyprland's xkb state for that device has Caps *locked*; a naive
  Shift+letter would then resolve inverted (`DIDNT` under Caps → `didn't`). For
  **letters**, use `effective_shift = char.isupper() XOR mods.capslock_active`; the
  apostrophe is unaffected by CapsLock. (Depends on Hyprland's per-device xkb lock
  behavior — confirm during the spike/wiring; if it differs, treat Caps-active as
  pass-through instead.)
- `SIGUSR1` toggles a `paused` flag; while paused, forward events but skip
  decode/engine entirely (pure passthrough). Log the new state.
- `--dry-run`: run the full pipeline but **log** intended corrections instead of
  emitting backspaces/chars (still forwards real keys). For safe live testing.

**Test Cases (decode is pure; the emission loop is verified functionally):**
```python
def test_letter_lowercase():
    m = ModState(); assert decode(key_press(KEY_D), m) == Letter("d")

def test_letter_shifted_uppercase():
    m = ModState(); m.update(key_press(KEY_LEFTSHIFT))
    assert decode(key_press(KEY_D), m) == Letter("D")

def test_capslock_uppercases_letters():
    m = ModState(); m.update(key_press(KEY_CAPSLOCK)); m.update(key_release(KEY_CAPSLOCK))
    assert decode(key_press(KEY_D), m) == Letter("D")

def test_ctrl_shortcut_is_reset():
    m = ModState(); m.update(key_press(KEY_LEFTCTRL))
    assert isinstance(decode(key_press(KEY_A), m), Reset)

def test_space_is_word_boundary():
    assert isinstance(decode(key_press(KEY_SPACE), ModState()), WordBoundary)

def test_digit_is_word_boundary():
    assert isinstance(decode(key_press(KEY_1), ModState()), WordBoundary)

def test_arrow_is_reset():
    assert isinstance(decode(key_press(KEY_LEFT), ModState()), Reset)

def test_key_release_ignored():
    assert decode(key_release(KEY_D), ModState()) is None
```

**Verification:**
1. `pytest tests/test_decode.py -v` → all pass.
2. Functional: run with `--dry-run`, type `i wouldnt know if youre sure thats what im saying`,
   confirm the log shows the right corrections and **no reorder**. Then run for real
   and confirm on-screen output is `i wouldn't know if you're sure that's what I'm saying`.
3. CapsLock case: with CapsLock on, type `wouldnt ` → expect `WOULDN'T ` (guards the
   emission-compensation item above).
4. Confirm `pkill -USR1 apostrophed` pauses/resumes.

**Commit after tests pass and the functional check is clean.**

---

## Task 6: Packaging & service  [Mode: Direct]

**Files:** Create `apostrophed.service`, `install.sh`, `bin/apostrophed`

**`apostrophed.service` (key lines):**
```ini
[Unit]
Description=apostrophed contraction fixer
After=keyd.service systemd-udevd.service
Wants=keyd.service

[Service]
ExecStart=/usr/local/bin/apostrophed
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
```
(Runs as root — no `User=`. `After=keyd.service` + the daemon's own device-wait
retry together prevent the boot race against `keyd virtual keyboard`.)

**`install.sh`:** copy `apostrophed/` → `/usr/local/lib/apostrophed/`,
`data/rules.tsv` → `/usr/local/share/apostrophed/rules.tsv`, `bin/apostrophed` →
`/usr/local/bin/` (launcher adds lib dir to `sys.path`, calls `daemon.main()`),
`apostrophed.service` → `/etc/systemd/system/`; `systemctl daemon-reload`;
`systemctl enable --now apostrophed`. Must be run with sudo; check `python-xkbcommon`
+ `python-evdev` are installed and fail with a clear message if not.

**Constraints:** idempotent (re-runnable). Print the `journalctl -u apostrophed -f`
hint on success.

**Verification:** `sudo ./install.sh`; `systemctl is-active apostrophed` → active;
type in any app and confirm live corrections; `systemctl status` shows it started
after keyd. **Commit after passing.**

---

## Task 7: Espanso teardown  [Mode: Direct]

**Files:** Create `uninstall-espanso.sh` (documents the cleanup; parts need sudo).

Steps: `espanso service unregister`; `espanso stop`; remove
`~/.config/systemd/user/espanso.service` if left; `rm -rf ~/.config/espanso
~/.cache/espanso`; then (hand the sudo line to the user)
`yay -R --noconfirm espanso-wayland`. Confirm `espanso` gone and no user service
lingering.

**Verification:** `command -v espanso` → not found; `ls ~/.config/espanso` → gone;
apostrophed still handling corrections. **Commit.**

---

## Execution
**Skill:** superpowers:subagent-driven-development
- Mode A (Direct) tasks: 1, 3, 6, 7 — Opus implements directly.
- Mode B (Delegated) tasks: 2, 4, 5 — dispatched to subagents (grab-chain spike,
  xkbcommon keymap, live daemon wiring — each needs hardware/lib exploration).

**Order:** 1 → 2 (spike, de-risk) → 3 → 4 → 5 → 6 → 7. Tasks 3 and 4 are
independent and may run in parallel; both are prerequisites of 5.

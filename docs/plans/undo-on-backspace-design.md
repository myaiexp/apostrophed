# Undo-on-backspace — design

> Pressing **Backspace immediately after a correction** reverts it: the corrected
> word and the boundary that triggered it are removed and your original literal
> word is retyped, cursor at its end. One keystroke wide — anything else disarms it.

## Behavior (the "rewind" model)

A correction fires *on the word boundary* (`didnt` + space → `didn't `). Undo
rewinds to the instant *before* the boundary committed the correction:

```
didnt␣  →(autocorrect)→  didn't␣  →[Backspace]→  didnt
                                                  ^cursor, no space
```

- Only the **first** keystroke after a correction is a candidate. If it's
  Backspace → revert. Any other token (letter, another boundary, navigation/click/
  idle → `Reset`) disarms the window.
- After a revert the buffer is **empty**, so pressing space again does **not**
  re-correct the restored word — no suppression flag needed.
- Applies uniformly to all rules, including `i` → `I`.

**Accepted tradeoff:** the first Backspace after *any* correction becomes undo, so
a Backspace wanted there for another reason reverts instead (a second Backspace
then behaves normally). Same tradeoff espanso makes; corrections only fire on the
45 safe triggers, so collisions are rare.

## Where the logic lives

The revert is just another `Correction` (delete N, type M), so the daemon's emit
path is reused unchanged and all the logic stays in the **pure engine** (fully
unit-testable, no hardware).

### Engine (`engine.py`)

One new field: `_undo: Correction | None`, the pre-baked revert.

- **Arm** — in `_evaluate()`, when a real correction is produced for typed word
  `W` → corrected text `C`:
  `self._undo = Correction(delete_count=len(C) + 1, text=W)`.
  The `+1` deletes the single boundary char emitted after `C`. (Every boundary —
  space, punctuation, Tab, Enter — is one char, so `+1` always holds.)
- **Fire** — `feed(Backspace)` while `_undo` is set returns that `Correction` and
  clears `_undo` (the buffer is already empty from the correction). When *not*
  armed, Backspace keeps today's behavior (pop the buffer).
- **Disarm** — `Letter`, `WordBoundary`, and `Reset` all clear `_undo`. A new
  boundary supersedes any pending undo (it re-arms or clears in `_evaluate`);
  everything else just clears it.

Undo is never re-armed by its own firing, so a second Backspace is a normal delete.

### Daemon (`daemon.py`)

Corrections can now arrive on a **Backspace** key-down as well as a WordBoundary.
The only behavioral difference: the triggering **Backspace is consumed, not
forwarded** — forwarding it would delete an extra char. A real boundary is still
forwarded after the rewrite (unchanged). Everything else — `_release_held`,
`_suspend_shift` / `_restore_shift`, `_apply_correction` — is reused as-is, so
held-Shift and fast-typing rollover are handled for free.

`--dry-run` logs the intended undo and lets the Backspace behave normally (dry-run
never emits).

## Testing

- **Engine (pure):** arm→Backspace returns `Correction(delete=len(C)+1, text=W)`;
  `Letter` / `WordBoundary` / `Reset` each disarm (a following Backspace pops
  normally); Backspace with no prior correction still pops the buffer; undo not
  re-armed after firing (second Backspace pops).
- **Pipeline (headless daemon):** after `didnt␣` the revert emits
  `len("didn't")+1` backspaces then retypes `didnt`, and the triggering Backspace
  is **not** forwarded (net: the space is gone). Case is preserved via the existing
  emit path (`DIDNT` restores `DIDNT`).

## Why this shape

- **Rewind (drop the boundary) over swap-back (keep it):** cleaner mental model
  ("Backspace undoes the autocorrect *and* the keystroke that triggered it") and it
  keeps the entire feature in the pure engine as one `Correction`. Keeping the
  boundary would force the daemon to re-emit the exact boundary key *with* its shift
  state (for punctuation like `?`), splitting the logic across engine and daemon for
  no real UX gain.
- **Empty buffer after undo over restoring `W` + a suppress flag:** an empty buffer
  makes re-correction structurally impossible instead of guarded, and the cost
  (continuing to type letters directly onto the restored word won't reconsider the
  whole word) is a rare edge already inherent to not seeing on-screen text.
- **Always-on, no config flag:** YAGNI. Trivial to gate later if the stolen-first-
  Backspace proves annoying in practice.

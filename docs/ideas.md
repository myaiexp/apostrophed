# Ideas — apostrophed

Future work, tech debt, and deferred capabilities. WHAT, not HOW.

## 2026-07-11 — initial (deferred from design)

- **Grow the rule set.** The rules are a data file — more contractions or a few
  personal apostrophe/typo fixes can be added without code changes. Keep to the
  "safe form" rule (apostrophe-less spelling must not be a real word). Now that
  undo-on-backspace has shipped, a mildly ambiguous entry is recoverable with one
  keystroke — but the bar stays "safe form" unless there's a good reason.
- **General text-expander evolution.** If the need for arbitrary triggers →
  replacements ever appears, the race-free evdev core could grow into a small
  espanso replacement. Explicitly out of scope for now — keeping the hot-path code
  small and provably correct is the priority.

## 2026-07-13 — shipped (removed from this list)

- **Hyprland keybind for the toggle** — `Alt+Shift+A` → `pkill -USR1 apostrophed`.
- **Status indicator** — waybar module reading the daemon's state file, inotify-
  driven. Both landed once the daemon moved off root to a user service (a user can
  signal its own process, so no privilege bridge was needed).
- **Undo-on-backspace** — Backspace right after a correction rewinds it (delete
  corrected word + boundary, retype the literal word). Pure-engine `_undo`; see
  [`plans/undo-on-backspace-design.md`](plans/undo-on-backspace-design.md).

## 2026-07-14 — deferred from repo audit

- **Physical-keyboard fallback (no keyd).** Grab the physical keyboard directly when
  keyd is absent — most people don't run keyd, so this multiplies the addressable
  audience. Safe-crash still holds (`EVIOCGRAB` releases on death → the compositor
  reads the physical device directly). Deferred because it's a real feature, not a
  small fallback: it re-solves what keyd hands us for free — selecting the *right*
  device among many `EV_KEY` devices (mice, power buttons, consumer-control all look
  like keyboards), grabbing *multiple* keyboards (laptop + external), and handling
  **hotplug** in the input hot path. Needs its own design pass (device-selection +
  hotplug model) before implementation. Contradicts today's "never grab the physical
  keyboard" invariant, so it's a deliberate architecture change, not a tweak.

## 2026-07-13 — known limitations (post-implementation)

- **CapsLock is remapped to Esc on this machine (keyd),** so `KEY_CAPSLOCK` never
  reaches the daemon and the CapsLock-compensation emission path is inert here —
  it's kept for layout/portability correctness but is untested live on this box.

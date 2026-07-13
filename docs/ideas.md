# Ideas — apostrophed

Future work, tech debt, and deferred capabilities. WHAT, not HOW.

## 2026-07-11 — initial (deferred from design)

- **Undo-on-backspace.** espanso-style: pressing Backspace immediately after a
  correction restores the original typed word (so a rare unwanted fix is one key
  to revert). Low value with the zero-false-positive safe set, so deferred — but
  cheap to add on top of the buffer we already maintain.
- **Grow the rule set.** The rules are a data file — more contractions or a few
  personal apostrophe/typo fixes can be added without code changes. Keep to the
  "safe form" rule (apostrophe-less spelling must not be a real word) unless
  undo-on-backspace lands first to make ambiguous entries recoverable.
- **General text-expander evolution.** If the need for arbitrary triggers →
  replacements ever appears, the race-free evdev core could grow into a small
  espanso replacement. Explicitly out of scope for now — keeping the hot-path code
  small and provably correct is the priority.

## 2026-07-13 — shipped (removed from this list)

- **Hyprland keybind for the toggle** — `Alt+Shift+A` → `pkill -USR1 apostrophed`.
- **Status indicator** — waybar module reading the daemon's state file, inotify-
  driven. Both landed once the daemon moved off root to a user service (a user can
  signal its own process, so no privilege bridge was needed).

## 2026-07-13 — known limitations (post-implementation)

- **CapsLock is remapped to Esc on this machine (keyd),** so `KEY_CAPSLOCK` never
  reaches the daemon and the CapsLock-compensation emission path is inert here —
  it's kept for layout/portability correctness but is untested live on this box.

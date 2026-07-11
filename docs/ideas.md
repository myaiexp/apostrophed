# Ideas — apostrophed

Future work, tech debt, and deferred capabilities. WHAT, not HOW.

## 2026-07-11 — initial (deferred from design)

- **Undo-on-backspace.** espanso-style: pressing Backspace immediately after a
  correction restores the original typed word (so a rare unwanted fix is one key
  to revert). Low value with the zero-false-positive safe set, so deferred — but
  cheap to add on top of the buffer we already maintain.
- **Hyprland keybind for the toggle.** Bind a key to `pkill -USR1 apostrophed` so
  pause/resume is one chord instead of a terminal command. Trivial once the signal
  handler exists.
- **Status indicator.** Optional waybar/mako signal of enabled vs paused state, if
  the toggle ever gets used enough to want visible feedback.
- **Grow the rule set.** The rules are a data file — more contractions or a few
  personal apostrophe/typo fixes can be added without code changes. Keep to the
  "safe form" rule (apostrophe-less spelling must not be a real word) unless
  undo-on-backspace lands first to make ambiguous entries recoverable.
- **General text-expander evolution.** If the need for arbitrary triggers →
  replacements ever appears, the race-free evdev core could grow into a small
  espanso replacement. Explicitly out of scope for now — keeping the hot-path code
  small and provably correct is the priority.

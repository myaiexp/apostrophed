#!/usr/bin/env bash
# Tear down the espanso experiment that apostrophed replaces.
# Run this ONLY after apostrophed is confirmed working, so corrections never stop.
#
# The package removal needs sudo and is left to you (last line). Everything else
# runs as your user.
set -uo pipefail

echo "==> unregistering espanso autostart"
espanso service unregister 2>/dev/null || echo "   (already unregistered)"

echo "==> stopping espanso if running"
espanso stop 2>/dev/null || echo "   (not running)"

# A stray user-copied unit (the package ships its own under /usr/lib); remove only
# a hand-placed override, never the packaged unit.
USER_UNIT="$HOME/.config/systemd/user/espanso.service"
if [[ -f "$USER_UNIT" ]]; then
    echo "==> removing user unit override $USER_UNIT"
    rm -f "$USER_UNIT"
    systemctl --user daemon-reload 2>/dev/null || true
fi

echo "==> removing espanso config + cache (created for the experiment)"
rm -rf "$HOME/.config/espanso" "$HOME/.cache/espanso"

echo
echo "Now remove the package (needs sudo):"
echo "    yay -R --noconfirm espanso-wayland"
echo
echo "Verify afterwards:  command -v espanso   (should be not found)"

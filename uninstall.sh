#!/usr/bin/env bash
# Remove apostrophed: stop + disable the user service and delete everything
# install.sh deployed. The exact inverse of install.sh — same PREFIX/
# XDG_CONFIG_HOME overrides, so a custom-prefix install is removed by running this
# with the same PREFIX. Idempotent: safe to run when nothing (or only part) is
# installed. Runs entirely as your user; no root.
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
    echo "error: run as your normal user, NOT root — this is a user service" >&2
    exit 1
fi

PREFIX="${PREFIX:-$HOME/.local}"
LIB_DIR="$PREFIX/lib/apostrophed"
SHARE_DIR="$PREFIX/share/apostrophed"
BIN="$PREFIX/bin/apostrophed"
WAYBAR_BIN="$PREFIX/bin/apostrophed-waybar"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/apostrophed.service"
DROPIN_DIR="$UNIT_DIR/apostrophed.service.d"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/apostrophed"

# Stop (--now) and drop the default.target want (disable). Non-fatal: the unit may
# already be gone or never enabled, and on a headless/no-user-bus invocation
# systemctl --user can't reach the manager — neither should block file removal.
echo "==> stopping + disabling user service"
systemctl --user disable --now apostrophed.service 2>/dev/null \
    || echo "   (service not active/enabled)"

echo "==> removing user unit + layout drop-in"
rm -f "$UNIT"
rm -rf "$DROPIN_DIR"
# Reload so systemd forgets the removed unit; clear any lingering failed state.
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user reset-failed apostrophed.service 2>/dev/null || true

echo "==> removing installed files"
rm -rf "$LIB_DIR" "$SHARE_DIR"
rm -f "$BIN" "$WAYBAR_BIN"
# The service's RuntimeDirectory is auto-removed on stop; this also clears state
# left behind by a manual (non-service) run.
rm -rf "$RUNTIME_DIR"

echo
echo "apostrophed removed. Your keyboard is unaffected — Hyprland falls back to"
echo "reading keyd's virtual keyboard directly."
echo
echo "Left in place (installed separately / edited by you):"
echo "  - the evdev / xkbcommon Python modules and keyd"
echo "  - any Hyprland keybind or waybar module you added (remove by hand)"

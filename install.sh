#!/usr/bin/env bash
# Deploy apostrophed as a systemd *user* service. No root required: the daemon
# runs as you, using input-group access to keyd's virtual devices and the logind
# uaccess ACL on /dev/uinput. Idempotent: re-runnable.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PREFIX="${PREFIX:-$HOME/.local}"
LIB_DIR="$PREFIX/lib/apostrophed"
SHARE_DIR="$PREFIX/share/apostrophed"
BIN="$PREFIX/bin/apostrophed"
WAYBAR_BIN="$PREFIX/bin/apostrophed-waybar"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/apostrophed.service"

if [[ $EUID -eq 0 ]]; then
    echo "error: run as your normal user, NOT root — this is a user service" >&2
    exit 1
fi

# You must be able to grab keyd's virtual devices (input group) and open
# /dev/uinput (logind uaccess ACL, present in a graphical session).
if ! id -nG | tr ' ' '\n' | grep -qx input; then
    echo "error: $USER is not in the 'input' group (needed to grab keyd devices)" >&2
    echo "       fix with: sudo usermod -aG input $USER   (then log out/in)" >&2
    exit 1
fi

# Runtime deps are system packages (system python runs the service).
missing=()
python3 -c "import evdev" 2>/dev/null || missing+=(python-evdev)
python3 -c "from xkbcommon import xkb" 2>/dev/null || missing+=(python-xkbcommon)
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "error: missing Python deps: ${missing[*]}" >&2
    echo "       install with: sudo pacman -S --noconfirm ${missing[*]}" >&2
    exit 1
fi

echo "==> installing package -> $LIB_DIR"
install -d "$LIB_DIR" "$SHARE_DIR" "$(dirname "$BIN")" "$UNIT_DIR"
rm -f "$LIB_DIR"/*.py  # clear stale modules before recopying
install -m 0644 "$SCRIPT_DIR"/apostrophed/*.py "$LIB_DIR"/

echo "==> installing rules -> $SHARE_DIR/rules.tsv"
install -m 0644 "$SCRIPT_DIR/data/rules.tsv" "$SHARE_DIR/rules.tsv"

echo "==> installing launcher -> $BIN"
install -m 0755 "$SCRIPT_DIR/bin/apostrophed" "$BIN"

echo "==> installing waybar helper -> $WAYBAR_BIN"
install -m 0755 "$SCRIPT_DIR/bin/apostrophed-waybar" "$WAYBAR_BIN"

echo "==> installing user unit -> $UNIT"
install -m 0644 "$SCRIPT_DIR/apostrophed.service" "$UNIT"

echo "==> reloading + (re)starting user service"
systemctl --user daemon-reload
systemctl --user enable apostrophed.service
# restart (not `enable --now`): on a re-run the service is already active, and
# `--now` would NOT reload the new code — the long-running process keeps the old
# modules in memory. restart starts it fresh whether stopped or running.
systemctl --user restart apostrophed.service

echo
echo "apostrophed installed and started (user service)."
echo "  status: systemctl --user status apostrophed"
echo "  logs:   journalctl --user -u apostrophed -f"
echo "  toggle: pkill -USR1 apostrophed   (pause/resume)"

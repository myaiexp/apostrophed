#!/usr/bin/env bash
# Deploy apostrophed as a root systemd system service. Idempotent: re-runnable.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LIB_DIR=/usr/local/lib/apostrophed
SHARE_DIR=/usr/local/share/apostrophed
BIN=/usr/local/bin/apostrophed
UNIT=/etc/systemd/system/apostrophed.service

if [[ $EUID -ne 0 ]]; then
    echo "error: run with sudo (installs to /usr/local and /etc/systemd)" >&2
    exit 1
fi

# Runtime deps are system packages (the service runs under system python).
missing=()
python3 -c "import evdev" 2>/dev/null || missing+=(python-evdev)
python3 -c "from xkbcommon import xkb" 2>/dev/null || missing+=(python-xkbcommon)
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "error: missing Python deps: ${missing[*]}" >&2
    echo "       install with: sudo pacman -S --noconfirm ${missing[*]}" >&2
    exit 1
fi

echo "==> installing package -> $LIB_DIR"
install -d "$LIB_DIR" "$SHARE_DIR"
# Copy only source .py (skip __pycache__); --delete-ish via clean of stale .py.
rm -f "$LIB_DIR"/*.py
install -m 0644 "$SCRIPT_DIR"/apostrophed/*.py "$LIB_DIR"/

echo "==> installing rules -> $SHARE_DIR/rules.tsv"
install -m 0644 "$SCRIPT_DIR/data/rules.tsv" "$SHARE_DIR/rules.tsv"

echo "==> installing launcher -> $BIN"
install -m 0755 "$SCRIPT_DIR/bin/apostrophed" "$BIN"

echo "==> installing unit -> $UNIT"
install -m 0644 "$SCRIPT_DIR/apostrophed.service" "$UNIT"

echo "==> reloading systemd + enabling service"
systemctl daemon-reload
systemctl enable --now apostrophed.service

echo
echo "apostrophed installed and started."
echo "  status: systemctl status apostrophed"
echo "  logs:   journalctl -u apostrophed -f"
echo "  toggle: pkill -USR1 apostrophed   (pause/resume)"

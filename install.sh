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

# Detect the package manager once, so dependency guidance isn't Arch-only. Sets
# PM_CMD (the install command) and PM_PYPFX (the distro's Python-package prefix:
# python- on Arch, python3- everywhere else). Both stay empty on an unknown distro,
# and callers fall back to a distro-agnostic hint.
PM_CMD=""; PM_PYPFX=""
if command -v pacman >/dev/null 2>&1; then PM_CMD="sudo pacman -S --noconfirm"; PM_PYPFX="python-"
elif command -v apt-get >/dev/null 2>&1; then PM_CMD="sudo apt install"; PM_PYPFX="python3-"
elif command -v dnf >/dev/null 2>&1; then PM_CMD="sudo dnf install"; PM_PYPFX="python3-"
elif command -v zypper >/dev/null 2>&1; then PM_CMD="sudo zypper install"; PM_PYPFX="python3-"
fi

# Runtime deps are the `evdev` and `xkbcommon` Python modules (system python runs
# the service). Distro package names follow the PM_PYPFX convention, so we derive
# them from the module name rather than hardcode a per-distro table. The tracked
# module names double as the PyPI names, so the pip line — printed always, since
# some distros don't package xkbcommon (e.g. Fedora) — needs no separate mapping.
missing=()
python3 -c "import evdev" 2>/dev/null || missing+=(evdev)
python3 -c "from xkbcommon import xkb" 2>/dev/null || missing+=(xkbcommon)
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "error: missing Python modules: ${missing[*]}" >&2
    if [[ -n "$PM_CMD" ]]; then
        pkgs=(); for m in "${missing[@]}"; do pkgs+=("${PM_PYPFX}${m}"); done
        echo "       install with: $PM_CMD ${pkgs[*]}" >&2
    fi
    echo "       or via pip (any distro; needs a C compiler + libxkbcommon dev headers):" >&2
    echo "         pip install --user ${missing[*]}" >&2
    exit 1
fi

# keyd must be installed AND its virtual keyboard present — apostrophed grabs that
# device by name. Without this, the daemon waits 30s for a device that never shows,
# raises, and lands in a systemd restart-loop with no hint why. Fail early instead.
DEVICE_NAME="${APOSTROPHED_DEVICE_NAME:-keyd virtual keyboard}"
if ! command -v keyd >/dev/null 2>&1; then
    echo "error: keyd not found — apostrophed grabs keyd's virtual keyboard." >&2
    echo "       install it (https://github.com/rvaiya/keyd) and enable it:" >&2
    if [[ -n "$PM_CMD" ]]; then
        echo "         $PM_CMD keyd && sudo systemctl enable --now keyd" >&2
    else
        echo "         (build per the keyd README), then: sudo systemctl enable --now keyd" >&2
    fi
    echo "       (or chain after another virtual keyboard: APOSTROPHED_DEVICE_NAME=...)" >&2
    exit 1
fi
# Device names are world-readable in sysfs, so this needs no input-group privilege.
if ! grep -qixF "$DEVICE_NAME" /sys/class/input/*/name 2>/dev/null; then
    echo "error: virtual keyboard '$DEVICE_NAME' not present — is keyd running?" >&2
    echo "       start it: sudo systemctl enable --now keyd" >&2
    echo "       check:    systemctl status keyd" >&2
    echo "       (override the expected name with APOSTROPHED_DEVICE_NAME=...)" >&2
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

# Pin the active keyboard layout into a drop-in so emitted keycodes match what the
# compositor applies (the base unit stays layout-agnostic; this carries the machine-
# specific value). Detected from an explicit APOSTROPHED_* override, else the
# standard XKB_DEFAULT_* vars, else localectl's system X11 layout. Most compositors
# don't export XKB_DEFAULT_LAYOUT to the user manager, so localectl is the reliable
# source — without this the runtime default would wrongly fall to "us".
DROPIN_DIR="$UNIT_DIR/apostrophed.service.d"
DROPIN="$DROPIN_DIR/layout.conf"
_localectl() { localectl status 2>/dev/null | sed -n "s/^ *X11 $1: *//p"; }
DETECTED_LAYOUT="${APOSTROPHED_LAYOUT:-${XKB_DEFAULT_LAYOUT:-$(_localectl Layout)}}"
DETECTED_VARIANT="${APOSTROPHED_VARIANT:-${XKB_DEFAULT_VARIANT:-$(_localectl Variant)}}"
install -d "$DROPIN_DIR"
if [[ -n "$DETECTED_LAYOUT" ]]; then
    echo "==> pinning layout '$DETECTED_LAYOUT${DETECTED_VARIANT:+/$DETECTED_VARIANT}' -> $DROPIN"
    {
        echo "# Auto-generated by install.sh: the active keyboard layout at install"
        echo "# time, pinned so apostrophed's emitted keycodes match the compositor."
        echo "# Re-run install.sh after a layout change, or set APOSTROPHED_LAYOUT."
        echo "[Service]"
        echo "Environment=APOSTROPHED_LAYOUT=$DETECTED_LAYOUT"
        [[ -n "$DETECTED_VARIANT" ]] && echo "Environment=APOSTROPHED_VARIANT=$DETECTED_VARIANT"
    } > "$DROPIN"
else
    echo "==> could not detect layout; daemon falls back to XKB_DEFAULT_LAYOUT or 'us'"
    echo "    (set APOSTROPHED_LAYOUT if that's wrong — see README)"
    rm -f "$DROPIN"  # clear any stale pin so the runtime fallback applies
fi

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

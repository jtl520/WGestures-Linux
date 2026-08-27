#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "usage: wayland-acceptance.sh PACKAGE OUTPUT_DIR" >&2
    exit 2
fi

package=$1
output_dir=$2
work_dir=${TMPDIR:-/tmp}/wgestures-wayland-$$
mkdir -p "$output_dir" "$work_dir"
trap 'rm -rf "$work_dir"' EXIT HUP INT TERM

package_version=$(dpkg-deb -f "$package" Version)
if sudo -n apt-get install --reinstall -y "$package" >"$output_dir/install.log" 2>&1; then
    :
else
    installed_version=$(dpkg-query -W -f='${Version}' wgestures 2>/dev/null || true)
    if [ "$installed_version" = "$package_version" ]; then
        printf 'Exact package version %s was already installed; continuing without sudo.\n' \
            "$installed_version" >>"$output_dir/install.log"
    else
        echo "Package installation needs passwordless sudo or an exact pre-installed version." >&2
        exit 10
    fi
fi

session_pid=$(pgrep -u "$(id -u)" -n gnome-shell 2>/dev/null || true)
if [ -z "$session_pid" ] || [ ! -r "/proc/$session_pid/environ" ]; then
    echo "No active GNOME Shell session belongs to SSH user $(id -un)." >&2
    exit 13
fi
if [ -r "/proc/$session_pid/environ" ]; then
    tr '\000' '\n' <"/proc/$session_pid/environ" >"$work_dir/session-environment"
    DBUS_SESSION_BUS_ADDRESS=$(sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p' "$work_dir/session-environment" | head -n 1)
    XDG_RUNTIME_DIR=$(sed -n 's/^XDG_RUNTIME_DIR=//p' "$work_dir/session-environment" | head -n 1)
    XDG_SESSION_TYPE=$(sed -n 's/^XDG_SESSION_TYPE=//p' "$work_dir/session-environment" | head -n 1)
    XDG_CURRENT_DESKTOP=$(sed -n 's/^XDG_CURRENT_DESKTOP=//p' "$work_dir/session-environment" | head -n 1)
    DISPLAY=$(sed -n 's/^DISPLAY=//p' "$work_dir/session-environment" | head -n 1)
    WAYLAND_DISPLAY=$(sed -n 's/^WAYLAND_DISPLAY=//p' "$work_dir/session-environment" | head -n 1)
    export DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR XDG_SESSION_TYPE XDG_CURRENT_DESKTOP DISPLAY WAYLAND_DISPLAY
fi

wgestures --diagnose --json >"$output_dir/diagnostics.json" || true
gnome-shell --version >"$output_dir/gnome-shell-version.txt"
gnome-extensions list >"$output_dir/extensions.txt"
if ! grep -Fxq 'wgestures@yingdev.com' "$output_dir/extensions.txt"; then
    echo 'The system extension is not discovered; log out and back in once.' >&2
    exit 20
fi
gnome-extensions enable 'wgestures@yingdev.com'
gnome-extensions info 'wgestures@yingdev.com' >"$output_dir/extension-info.txt"
gnome-extensions list --enabled >"$output_dir/extensions-enabled.txt"
gsettings list-recursively org.gnome.shell.extensions.wgestures \
    >"$output_dir/gsettings.txt"
journalctl --user --since '-10 minutes' --no-pager 2>/dev/null | \
    grep -i 'wgestures' >"$output_dir/journal-wgestures.txt" || true

python3 - "$output_dir" <<'PY'
from __future__ import print_function
import json
import os
import re
import sys

directory = sys.argv[1]
with open(os.path.join(directory, "diagnostics.json"), "r") as stream:
    diagnostics = json.load(stream)
with open(os.path.join(directory, "gnome-shell-version.txt"), "r") as stream:
    version = stream.read().strip()
with open(os.path.join(directory, "extensions-enabled.txt"), "r") as stream:
    enabled_extensions = set(line.strip() for line in stream if line.strip())
static_gates = {
    "gnomeShell46": bool(re.search(r"\b46(?:\.|\b)", version)),
    "waylandSession": diagnostics.get("sessionType") == "wayland",
    "selectedGnomeBackend": diagnostics.get("backend") == "gnome46-wayland",
    "extensionEnabled": "wgestures@yingdev.com" in enabled_extensions,
    "configurationValid": diagnostics.get("configuration", {}).get("status") in ("primary", "defaults"),
}
result = {
    "staticGates": static_gates,
    "staticPassed": all(static_gates.values()),
    "manualGatesPending": [
        "short right click opens exactly one native context menu",
        "valid gesture never opens the context menu",
        "invalid effective gesture is swallowed",
        "native Wayland and XWayland shortcuts/window actions",
        "multi-monitor mixed scaling and hot-plug",
        "lock, suspend and extension-disable cleanup",
    ],
}
with open(os.path.join(directory, "summary.json"), "w") as stream:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write("\n")
print(json.dumps(result, indent=2, sort_keys=True))
if not result["staticPassed"]:
    raise SystemExit(21)
PY

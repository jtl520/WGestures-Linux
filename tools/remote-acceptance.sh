#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
    echo "usage: remote-acceptance.sh PACKAGE HARNESS DRIVER OUTPUT_DIR" >&2
    exit 2
fi

package=$1
harness=$2
driver=$3
output_dir=$4
work_dir=${TMPDIR:-/tmp}/wgestures-acceptance-$$

mkdir -p "$work_dir" "$output_dir"

backend_pid=
harness_pid=
settings_monitor_pid=
had_existing_daemon=false
if pgrep -u "$(id -u)" -f '/usr/lib/wgestures/main.py --daemon' >/dev/null 2>&1; then
    had_existing_daemon=true
fi
cleanup() {
    if [ -n "$backend_pid" ]; then
        kill -TERM "$backend_pid" 2>/dev/null || true
        wait "$backend_pid" 2>/dev/null || true
    fi
    if [ -n "$harness_pid" ]; then
        kill -TERM "$harness_pid" 2>/dev/null || true
        wait "$harness_pid" 2>/dev/null || true
    fi
    if [ -n "$settings_monitor_pid" ]; then
        kill -TERM "$settings_monitor_pid" 2>/dev/null || true
        wait "$settings_monitor_pid" 2>/dev/null || true
    fi
    if [ "$had_existing_daemon" = true ]; then
        unset XDG_CONFIG_HOME XDG_DATA_HOME GSETTINGS_BACKEND WGESTURES_METRICS_PATH
        nohup wgestures --daemon >/dev/null 2>&1 &
    fi
    rm -rf "$work_dir"
}
trap cleanup EXIT HUP INT TERM

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
        echo "Run once in the VM: sudo apt-get install --reinstall -y $package" >&2
        cat "$output_dir/install.log" >&2
        exit 10
    fi
fi

# SSH does not inherit the active graphical session environment. Read only the
# selected variables from the current user's desktop session process.
session_pid=$(pgrep -u "$(id -u)" -n xfce4-session 2>/dev/null || \
              pgrep -u "$(id -u)" -n gnome-session-binary 2>/dev/null || true)
if [ -z "$session_pid" ] || [ ! -r "/proc/$session_pid/environ" ]; then
    echo "No active X11 desktop session belongs to SSH user $(id -un)." >&2
    echo "Log into the target desktop as this user, then retry." >&2
    exit 13
fi
if [ -r "/proc/$session_pid/environ" ]; then
    session_environment="$work_dir/session-environment"
    tr '\000' '\n' <"/proc/$session_pid/environ" >"$session_environment"
    DISPLAY=$(sed -n 's/^DISPLAY=//p' "$session_environment" | head -n 1)
    XAUTHORITY=$(sed -n 's/^XAUTHORITY=//p' "$session_environment" | head -n 1)
    DBUS_SESSION_BUS_ADDRESS=$(sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p' "$session_environment" | head -n 1)
    XDG_RUNTIME_DIR=$(sed -n 's/^XDG_RUNTIME_DIR=//p' "$session_environment" | head -n 1)
    XDG_SESSION_TYPE=$(sed -n 's/^XDG_SESSION_TYPE=//p' "$session_environment" | head -n 1)
    XDG_CURRENT_DESKTOP=$(sed -n 's/^XDG_CURRENT_DESKTOP=//p' "$session_environment" | head -n 1)
    export DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR XDG_SESSION_TYPE XDG_CURRENT_DESKTOP
fi
export DISPLAY=${DISPLAY:-:0}
export XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-x11}
export XDG_CONFIG_HOME="$work_dir/config"
export XDG_DATA_HOME="$work_dir/data"
export GSETTINGS_BACKEND=keyfile
export WGESTURES_METRICS_PATH="$output_dir/backend-metrics.json"

wgestures --diagnose --json >"$output_dir/diagnostics.json"

python3 - "$output_dir" <<'PY'
from __future__ import print_function
import os
import sys

sys.path.insert(0, "/usr/lib/wgestures")
from wgestures.config import create_default_config
from wgestures.storage import ConfigStore

output = os.path.abspath(sys.argv[1])
desktop_id = "wgestures-acceptance.desktop"
applications = os.path.join(os.environ["XDG_DATA_HOME"], "applications")
if not os.path.isdir(applications):
    os.makedirs(applications)
with open(os.path.join(applications, desktop_id), "w") as stream:
    stream.write("[Desktop Entry]\n")
    stream.write("Type=Application\n")
    stream.write("Name=WGestures acceptance launcher\n")
    stream.write("Exec=/usr/bin/touch {0}\n".format(
        os.path.join(output, "launch-marker")))

config = create_default_config()
config["actions"].extend([
    {"id": "test-noop", "name": "Noop", "type": "NoopAction", "enabled": True},
    {"id": "test-fullscreen", "name": "Fullscreen", "type": "WindowAction",
     "operation": "toggle-fullscreen", "enabled": True},
    {"id": "test-above", "name": "Above", "type": "WindowAction",
     "operation": "toggle-above", "enabled": True},
    {"id": "test-close", "name": "Close", "type": "WindowAction",
     "operation": "close", "enabled": True},
    {"id": "test-command", "name": "Command", "type": "CommandAction",
     "command": "/usr/bin/touch '{0}'".format(
         os.path.join(output, "command-marker")), "enabled": True},
    {"id": "test-launch", "name": "Launch", "type": "LaunchAction",
     "target": desktop_id, "enabled": True},
    {"id": "test-pause", "name": "Pause", "type": "PauseAction", "enabled": True},
])
specs = [
    ("right", ["right"], "shortcut-forward"),
    ("left", ["left"], "test-noop"),
    ("up", ["up"], "window-maximize"),
    ("up-right", ["up-right"], "test-fullscreen"),
    ("down-right", ["down-right"], "test-above"),
    ("down-left", ["down-left"], "test-command"),
    ("up-left", ["up-left"], "test-launch"),
    ("pause", ["right", "down"], "test-pause"),
    ("minimize", ["left", "down"], "window-minimize"),
    ("close", ["right", "up"], "test-close"),
]
config["globalProfile"]["gestures"] = [{
    "id": "test-gesture-{0}".format(name), "name": name, "enabled": True,
    "button": "right", "directions": directions, "actionId": action_id,
} for name, directions, action_id in specs]
ConfigStore().save(config, create_backup=False)
PY

gsettings set org.gnome.shell.extensions.wgestures enabled true
gsettings set org.gnome.shell.extensions.wgestures paused false
gsettings set org.gnome.shell.extensions.wgestures trigger-buttons "['right']"
gsettings set org.gnome.shell.extensions.wgestures direction-mode 8
gsettings set org.gnome.shell.extensions.wgestures start-threshold 8
gsettings set org.gnome.shell.extensions.wgestures segment-threshold 12
gsettings monitor org.gnome.shell.extensions.wgestures paused \
    >"$output_dir/gsettings-monitor.log" 2>&1 &
settings_monitor_pid=$!

pkill -u "$(id -u)" -f '/usr/lib/wgestures/main.py --daemon' 2>/dev/null || true
sleep 1

python3 "$harness" "$output_dir/harness-events.jsonl" \
    >"$output_dir/harness.log" 2>&1 &
harness_pid=$!
sleep 2
wgestures --daemon >"$output_dir/backend.log" 2>&1 &
backend_pid=$!
sleep 3
if ! kill -0 "$backend_pid" 2>/dev/null; then
    cat "$output_dir/backend.log" >&2
    exit 11
fi

python3 - "$backend_pid" "$output_dir/process.txt" <<'PY'
from __future__ import print_function
import os
import sys
import time

pid = int(sys.argv[1])
output = sys.argv[2]
def ticks():
    with open("/proc/{0}/stat".format(pid), "r") as stream:
        fields = stream.read().split()
    return int(fields[13]) + int(fields[14])
start = ticks()
started = time.monotonic()
time.sleep(5.0)
elapsed = time.monotonic() - started
used = ticks() - start
cpu = used * 100.0 / (os.sysconf("SC_CLK_TCK") * elapsed)
with open("/proc/{0}/status".format(pid), "r") as stream:
    lines = stream.readlines()
rss = next(int(line.split()[1]) for line in lines if line.startswith("VmRSS:"))
with open(output, "w") as stream:
    stream.write("{0:.4f} {1}\n".format(cpu, rss))
PY
python3 "$driver" "$output_dir/harness-events.jsonl" \
    >"$output_dir/gui-acceptance.json" 2>"$output_dir/gui-acceptance.err"

kill -TERM "$backend_pid"
wait "$backend_pid" || true
backend_pid=

python3 - "$output_dir" <<'PY'
from __future__ import print_function
import json
import os
import sys

directory = sys.argv[1]
with open(os.path.join(directory, "gui-acceptance.json"), "r") as stream:
    gui = json.load(stream)
with open(os.path.join(directory, "backend-metrics.json"), "r") as stream:
    metrics = json.load(stream)
with open(os.path.join(directory, "process.txt"), "r") as stream:
    fields = stream.read().split()
cpu = float(fields[0])
rss_kib = int(fields[1])
result = {
    "gui": gui,
    "backend": metrics,
    "idleCpuPercent": cpu,
    "rssKiB": rss_kib,
    "gates": {
        "idleCpuBelow1Percent": cpu < 1.0,
        "rssBelow80MiB": rss_kib < 80 * 1024,
        "eventToFrameP95Below33Ms": metrics.get("eventToFrameP95Ms") is not None and metrics["eventToFrameP95Ms"] <= 33.0,
        "shortClickP95Below50Ms": gui["shortClickP95Ms"] <= 50.0,
    },
}
result["passed"] = all(result["gates"].values())
with open(os.path.join(directory, "summary.json"), "w") as stream:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write("\n")
print(json.dumps(result, indent=2, sort_keys=True))
if not result["passed"]:
    raise SystemExit(12)
PY

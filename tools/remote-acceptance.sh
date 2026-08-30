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
runtime_libdir=${WGESTURES_LIBDIR:-/usr/lib/wgestures}

# apt treats a bare relative path containing slashes as a package name.  Keep
# command-line paths usable from the repository root as documented.
case "$package" in
    /*|./*|../*) ;;
    *) package=./$package ;;
esac

mkdir -p "$work_dir" "$output_dir"

backend_pid=
harness_pid=
settings_monitor_pid=
had_existing_daemon=false
if pgrep -u "$(id -u)" -f "$runtime_libdir/main.py --daemon" >/dev/null 2>&1; then
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

if [ "${WGESTURES_SKIP_PACKAGE_INSTALL:-0}" = 1 ]; then
    printf '%s\n' 'Package installation skipped; testing the caller-provided runtime.' \
        >"$output_dir/install.log"
else
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
fi

# SSH does not inherit the active graphical session environment. Read only the
# selected variables from the current user's desktop session process. Tests in
# an isolated Xvfb session can explicitly retain their prepared environment.
if [ "${WGESTURES_USE_CURRENT_DISPLAY:-0}" != 1 ]; then
    session_pid=$(pgrep -u "$(id -u)" -n xfce4-session 2>/dev/null || \
                  pgrep -u "$(id -u)" -n -f '(^|/)gnome-session-binary([[:space:]]|$)' 2>/dev/null || true)
    if [ -z "$session_pid" ] || [ ! -r "/proc/$session_pid/environ" ]; then
        echo "No active X11 desktop session belongs to SSH user $(id -un)." >&2
        echo "Log into the target desktop as this user, then retry." >&2
        exit 13
    fi
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

# Diagnostics are acceptance evidence, not a gate: an unsupported-environment
# report still gets collected, and the driver below decides pass or fail.
wgestures --diagnose --json >"$output_dir/diagnostics.json" || true

python3 - "$output_dir" <<'PY'
from __future__ import print_function
import os
import sys

sys.path.insert(0, os.environ.get("WGESTURES_LIBDIR", "/usr/lib/wgestures"))
from wgestures.config import create_default_config
from wgestures.storage import ConfigStore
from wgestures.panel import PanelStore, create_default_panel

output = os.path.abspath(sys.argv[1])
desktop_id = "wgestures-acceptance.desktop"
panel_desktop_id = "wgestures-panel-application.desktop"
uri_desktop_id = "wgestures-panel-uri.desktop"
applications = os.path.join(os.environ["XDG_DATA_HOME"], "applications")
if not os.path.isdir(applications):
    os.makedirs(applications)
with open(os.path.join(applications, desktop_id), "w") as stream:
    stream.write("[Desktop Entry]\n")
    stream.write("Type=Application\n")
    stream.write("Name=WGestures acceptance launcher\n")
    stream.write("Exec=/usr/bin/touch {0}\n".format(
        os.path.join(output, "launch-marker")))
with open(os.path.join(applications, panel_desktop_id), "w") as stream:
    stream.write("[Desktop Entry]\n")
    stream.write("Type=Application\n")
    stream.write("Name=WGestures panel application\n")
    stream.write("Exec=/usr/bin/touch {0}\n".format(
        os.path.join(output, "panel-application-marker")))

panel_file = os.path.join(output, "panel-file.txt")
panel_folder = os.path.join(output, "panel-folder")
with open(panel_file, "w") as stream:
    stream.write("panel acceptance\n")
if not os.path.isdir(panel_folder):
    os.makedirs(panel_folder)
uri_handler = os.path.join(output, "panel-uri-handler.sh")
with open(uri_handler, "w") as stream:
    stream.write("#!/bin/sh\n")
    stream.write("case \"$1\" in\n")
    stream.write("  *panel-file.txt) /usr/bin/touch {0} ;;\n".format(
        os.path.join(output, "panel-file-marker")))
    stream.write("  *panel-folder*) /usr/bin/touch {0} ;;\n".format(
        os.path.join(output, "panel-folder-marker")))
    stream.write("  *panel-dropped.txt) /usr/bin/touch {0} ;;\n".format(
        os.path.join(output, "panel-drop-marker")))
    stream.write("  http://*|https://*) /usr/bin/touch {0} ;;\n".format(
        os.path.join(output, "panel-url-marker")))
    stream.write("  *) exit 7 ;;\n")
    stream.write("esac\n")
os.chmod(uri_handler, 0o755)
with open(os.path.join(applications, uri_desktop_id), "w") as stream:
    stream.write("[Desktop Entry]\n")
    stream.write("Type=Application\n")
    stream.write("Name=WGestures panel URI handler\n")
    stream.write("Exec=/bin/sh {0} %u\n".format(uri_handler))
    stream.write("MimeType=text/plain;inode/directory;x-scheme-handler/http;"
                 "x-scheme-handler/https;\n")
config_directory = os.path.join(os.environ["XDG_CONFIG_HOME"])
if not os.path.isdir(config_directory):
    os.makedirs(config_directory)
with open(os.path.join(config_directory, "mimeapps.list"), "w") as stream:
    stream.write("[Default Applications]\n")
    for mime_type in ("text/plain", "inode/directory",
                      "x-scheme-handler/http", "x-scheme-handler/https"):
        stream.write("{0}={1};\n".format(mime_type, uri_desktop_id))

config = create_default_config()
config["actions"].extend([
    {"id": "test-forward", "name": "Forward", "type": "ShortcutAction",
     "accelerator": "<Alt>Right", "enabled": True},
    {"id": "test-maximize", "name": "Maximize", "type": "WindowAction",
     "operation": "toggle-maximized", "enabled": True},
    {"id": "test-minimize", "name": "Minimize", "type": "WindowAction",
     "operation": "minimize", "enabled": True},
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
    ("right", ["right"], "test-forward"),
    ("left", ["left"], "test-noop"),
    ("up", ["up"], "test-maximize"),
    ("up-right", ["up-right"], "test-fullscreen"),
    ("down-right", ["down-right"], "test-above"),
    ("down-left", ["down-left"], "test-command"),
    ("up-left", ["up-left"], "test-launch"),
    ("pause", ["right", "down"], "test-pause"),
    ("minimize", ["left", "down"], "test-minimize"),
    ("close", ["right", "up"], "test-close"),
]
config["globalProfile"]["gestures"] = [{
    "id": "test-gesture-{0}".format(name), "name": name, "enabled": True,
    "button": "right", "directions": directions, "actionId": action_id,
} for name, directions, action_id in specs]
ConfigStore().save(config, create_backup=False)

panel = create_default_panel()
panel["slots"][0] = {"id": "acceptance-application", "label": "App",
                     "type": "application", "target": panel_desktop_id}
panel["slots"][1] = {"id": "acceptance-file", "label": "File",
                     "type": "file", "target": panel_file}
panel["slots"][2] = {"id": "acceptance-folder", "label": "Folder",
                     "type": "folder", "target": panel_folder}
panel["slots"][3] = {"id": "acceptance-url", "label": "Example",
                     "type": "url", "target": "https://example.com"}
PanelStore().save(panel, create_backup=False)
PY

# Folder panel items deliberately bypass a potentially wrong
# inode/directory association and launch a real file-manager command. Put a
# deterministic Thunar stand-in first on PATH so the acceptance run records
# that direct command without opening the host's installed file manager.
mkdir -p "$output_dir/test-bin"
ln -sf "$output_dir/panel-uri-handler.sh" "$output_dir/test-bin/thunar"
export PATH="$output_dir/test-bin:$PATH"

gsettings set org.gnome.shell.extensions.wgestures enabled true
gsettings set org.gnome.shell.extensions.wgestures paused false
gsettings set org.gnome.shell.extensions.wgestures trigger-buttons "['right']"
gsettings set org.gnome.shell.extensions.wgestures middle-panel-enabled true
gsettings set org.gnome.shell.extensions.wgestures direction-mode 8
gsettings set org.gnome.shell.extensions.wgestures start-threshold 8
gsettings set org.gnome.shell.extensions.wgestures segment-threshold 12
gsettings monitor org.gnome.shell.extensions.wgestures paused \
    >"$output_dir/gsettings-monitor.log" 2>&1 &
settings_monitor_pid=$!

pkill -u "$(id -u)" -f "$runtime_libdir/main.py --daemon" 2>/dev/null || true
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
    gui_text = stream.read()
# python-xlib can print a harmless Xauthority warning to stdout before the
# driver's JSON when an unauthenticated Xvfb server is used.
json_start = gui_text.find("{")
if json_start < 0:
    raise ValueError("GUI acceptance output did not contain JSON")
gui = json.loads(gui_text[json_start:])
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
        "eventToFrameP95Below33Ms": (
            metrics.get("eventToFrameP95Ms") is not None and
            metrics["eventToFrameP95Ms"] <= 33.0) or
            os.environ.get("WGESTURES_ALLOW_NO_FRAME_METRICS") == "1",
        "shortClickP95Below50Ms": gui["shortClickP95Ms"] <= 50.0,
    },
}
result["frameMetricSkipped"] = (
    metrics.get("eventToFrameP95Ms") is None and
    os.environ.get("WGESTURES_ALLOW_NO_FRAME_METRICS") == "1")
result["passed"] = all(result["gates"].values())
with open(os.path.join(directory, "summary.json"), "w") as stream:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write("\n")
print(json.dumps(result, indent=2, sort_keys=True))
if not result["passed"]:
    raise SystemExit(12)
PY

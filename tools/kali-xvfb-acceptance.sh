#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
    echo "usage: kali-xvfb-acceptance.sh PACKAGE REPOSITORY OUTPUT_DIR" >&2
    exit 2
fi

package=$(readlink -f "$1")
repository=$(readlink -f "$2")
output_dir=$(readlink -m "$3")
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/crossgestures-xvfb.XXXXXX")
xvfb_pid=

cleanup() {
    if [ -n "$xvfb_pid" ]; then
        kill -TERM "$xvfb_pid" 2>/dev/null || true
        wait "$xvfb_pid" 2>/dev/null || true
    fi
    # GTK may leave a transient gvfs FUSE mount under XDG_RUNTIME_DIR after the
    # session bus exits.  The acceptance result is already persisted; cleanup
    # must not turn a passing run into a failure solely because that mount is
    # still winding down.
    rm -rf "$work_dir" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$output_dir" "$work_dir/runtime"
chmod 700 "$work_dir/runtime"
dpkg-deb -x "$package" "$work_dir/root"
schema_dir="$work_dir/root/usr/share/glib-2.0/schemas"
glib-compile-schemas "$schema_dir"

export XDG_RUNTIME_DIR="$work_dir/runtime"
export GSETTINGS_SCHEMA_DIR="$schema_dir"
# The isolated session is always X11; without this the diagnostics CLI would
# classify the SSH-invoked session as tty and refuse to run.
export XDG_SESSION_TYPE=x11
export WGESTURES_LIBDIR="$work_dir/root/usr/lib/wgestures"
export WGESTURES_SKIP_PACKAGE_INSTALL=1
export WGESTURES_USE_CURRENT_DISPLAY=1
export WGESTURES_DEBUG_INPUT=1
export WGESTURES_ALLOW_NO_FRAME_METRICS=1
export PATH="$work_dir/root/usr/bin:$PATH"
export PACKAGE="$package"
export REPOSITORY="$repository"
export OUTPUT_DIR="$output_dir"

display_number_file="$work_dir/display-number"
Xvfb -displayfd 3 -screen 0 1440x900x24 -nolisten tcp \
    >"$output_dir/xvfb.log" 2>&1 3>"$display_number_file" &
xvfb_pid=$!
attempt=0
while [ ! -s "$display_number_file" ] && kill -0 "$xvfb_pid" 2>/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 50 ]; then
        echo "Xvfb did not publish a display number." >&2
        exit 3
    fi
    sleep 0.1
done
if [ ! -s "$display_number_file" ]; then
    cat "$output_dir/xvfb.log" >&2
    exit 3
fi
DISPLAY=":$(cat "$display_number_file")"
export DISPLAY

dbus-run-session -- sh -c '
    xfwm4 --replace --compositor=off >"$OUTPUT_DIR/xfwm4.log" 2>&1 &
    window_manager_pid=$!
    trap "kill -TERM $window_manager_pid 2>/dev/null || true" EXIT HUP INT TERM
    sleep 2
    "$REPOSITORY/tools/remote-acceptance.sh" "$PACKAGE" \
        "$REPOSITORY/linux/tests/x11_harness.py" \
        "$REPOSITORY/linux/tests/x11_driver.py" "$OUTPUT_DIR"
'

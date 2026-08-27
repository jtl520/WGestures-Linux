#!/usr/bin/python3
from __future__ import print_function, unicode_literals

import json
import os
import statistics
import subprocess
import sys
import time

from Xlib import X, Xatom, display
from Xlib.ext import xtest


TITLE = "WGestures Acceptance Harness"


def _text_property(window, connection, name):
    prop = window.get_full_property(connection.intern_atom(name), X.AnyPropertyType)
    if prop is None:
        return ""
    value = prop.value
    if isinstance(value, bytes):
        return value.split(b"\0", 1)[0].decode("utf-8", "replace")
    if hasattr(value, "tobytes"):
        return value.tobytes().split(b"\0", 1)[0].decode("utf-8", "replace")
    return str(value)


def _find_window(connection):
    root = connection.screen().root
    for property_name in ("_NET_CLIENT_LIST_STACKING", "_NET_CLIENT_LIST"):
        prop = root.get_full_property(connection.intern_atom(property_name), Xatom.WINDOW)
        if prop is None:
            continue
        for window_id in reversed(prop.value):
            window = connection.create_resource_object("window", int(window_id))
            if _text_property(window, connection, "_NET_WM_NAME") == TITLE or \
                    (window.get_wm_name() or "") == TITLE:
                return window
    raise RuntimeError("acceptance harness window was not found")


def _center(window, root):
    geometry = window.get_geometry()
    translated = root.translate_coords(window, 0, 0)
    x = getattr(translated, "dst_x", getattr(translated, "x", 0))
    y = getattr(translated, "dst_y", getattr(translated, "y", 0))
    return int(x + geometry.width / 2), int(y + geometry.height / 2)


def _read_events(path):
    events = []
    try:
        with open(path, "r") as stream:
            for line in stream:
                if line.strip():
                    events.append(json.loads(line))
    except OSError:
        pass
    return events


def _clear(path):
    open(path, "w").close()


def _move(connection, x, y):
    xtest.fake_input(connection, X.MotionNotify, x=x, y=y)
    connection.sync()


def _click(connection, button=3):
    xtest.fake_input(connection, X.ButtonPress, button)
    xtest.fake_input(connection, X.ButtonRelease, button)
    connection.sync()


def _gesture(connection, points, button=3):
    _move(connection, points[0][0], points[0][1])
    xtest.fake_input(connection, X.ButtonPress, button)
    for x, y in points[1:]:
        xtest.fake_input(connection, X.MotionNotify, x=x, y=y)
        connection.sync()
        time.sleep(0.02)
    xtest.fake_input(connection, X.ButtonRelease, button)
    connection.sync()


DIRECTION_DELTAS = {
    "right": (55, 0), "down-right": (45, 45), "down": (0, 55),
    "down-left": (-45, 45), "left": (-55, 0), "up-left": (-45, -45),
    "up": (0, -55), "up-right": (45, -45),
}


def _gesture_directions(connection, window, root, directions):
    x, y = _center(window, root)
    points = [(x, y)]
    for direction in directions:
        dx, dy = DIRECTION_DELTAS[direction]
        x += dx
        y += dy
        points.append((x, y))
    _gesture(connection, points)


def _wait_for(predicate, message, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(message)


def _window_states(connection, window):
    prop = window.get_full_property(
        connection.intern_atom("_NET_WM_STATE"), Xatom.ATOM)
    return set(int(value) for value in (prop.value if prop is not None else []))


def _assert_no_click(log_path):
    time.sleep(0.25)
    _assert_button_pair(_read_events(log_path), 0)


def _toggle_window_state(connection, window, root, log_path, directions, atoms):
    expected = set(connection.intern_atom(name) for name in atoms)
    _clear(log_path)
    _gesture_directions(connection, window, root, directions)
    _assert_no_click(log_path)
    _wait_for(lambda: expected.issubset(_window_states(connection, window)),
              "window state was not enabled: {0}".format(atoms))
    _clear(log_path)
    _gesture_directions(connection, window, root, directions)
    _assert_no_click(log_path)
    _wait_for(lambda: not expected.intersection(_window_states(connection, window)),
              "window state was not disabled: {0}".format(atoms))


def _activate_window(connection, window, root):
    event = __import__("Xlib.protocol.event", fromlist=["ClientMessage"]).ClientMessage(
        window=window, client_type=connection.intern_atom("_NET_ACTIVE_WINDOW"),
        data=(32, [2, X.CurrentTime, 0, 0, 0]))
    root.send_event(event, event_mask=X.SubstructureRedirectMask |
                    X.SubstructureNotifyMask)
    connection.flush()


def _assert_button_pair(events, expected):
    button_events = [item for item in events if item["type"].startswith("button-")]
    if len(button_events) != expected:
        raise AssertionError("expected {0} button events, got {1}: {2}".format(
            expected, len(button_events), button_events))


def main():
    if len(sys.argv) != 2:
        print("usage: x11_driver.py LOG_PATH", file=sys.stderr)
        return 2
    log_path = sys.argv[1]
    connection = display.Display()
    root = connection.screen().root
    window = _find_window(connection)
    window.configure(stack_mode=X.Above)
    _activate_window(connection, window, root)
    connection.sync()
    _wait_for(lambda: window.get_attributes().map_state == X.IsViewable,
              "acceptance harness window is not viewable")
    x, y = _center(window, root)
    _move(connection, x, y)
    time.sleep(0.2)
    latencies = []
    for _index in range(12):
        _clear(log_path)
        released_at = time.monotonic()
        _click(connection)
        deadline = time.monotonic() + 1.0
        events = []
        while time.monotonic() < deadline:
            events = _read_events(log_path)
            if len([item for item in events if item["type"].startswith("button-")]) >= 2:
                break
            time.sleep(0.005)
        _assert_button_pair(events, 2)
        first = next(item for item in events if item["type"] == "button-press")
        latencies.append(max(0.0, (first["time"] - released_at) * 1000.0))

    _clear(log_path)
    _gesture_directions(connection, window, root, ["right"])
    time.sleep(0.3)
    valid_events = _read_events(log_path)
    _assert_button_pair(valid_events, 0)
    if not any(item["type"] == "key-press" and item.get("key") == "Right"
               for item in valid_events):
        raise AssertionError("valid right gesture did not emit Alt+Right: {0}".format(valid_events))

    _clear(log_path)
    _gesture_directions(connection, window, root, ["left"])
    _assert_no_click(log_path)

    _toggle_window_state(connection, window, root, log_path, ["up"], [
        "_NET_WM_STATE_MAXIMIZED_HORZ", "_NET_WM_STATE_MAXIMIZED_VERT"])
    _toggle_window_state(connection, window, root, log_path, ["up-right"], [
        "_NET_WM_STATE_FULLSCREEN"])
    _toggle_window_state(connection, window, root, log_path, ["down-right"], [
        "_NET_WM_STATE_ABOVE"])

    output_dir = os.path.dirname(os.path.abspath(log_path))
    command_marker = os.path.join(output_dir, "command-marker")
    launch_marker = os.path.join(output_dir, "launch-marker")
    _clear(log_path)
    _gesture_directions(connection, window, root, ["down-left"])
    _assert_no_click(log_path)
    _wait_for(lambda: os.path.exists(command_marker), "CommandAction did not run")
    _clear(log_path)
    _gesture_directions(connection, window, root, ["up-left"])
    _assert_no_click(log_path)
    _wait_for(lambda: os.path.exists(launch_marker), "LaunchAction did not launch desktop ID")

    _clear(log_path)
    _gesture_directions(connection, window, root, ["right", "down"])
    _assert_no_click(log_path)
    time.sleep(0.15)
    paused_value = subprocess.check_output([
        "gsettings", "get", "org.gnome.shell.extensions.wgestures", "paused"],
        universal_newlines=True).strip()
    if paused_value != "true":
        raise AssertionError("PauseAction did not pause (value={0!r})".format(
            paused_value))
    subprocess.check_call([
        "gsettings", "set", "org.gnome.shell.extensions.wgestures", "paused", "false"])
    time.sleep(0.2)

    _clear(log_path)
    _gesture_directions(connection, window, root, ["right", "left"])
    _assert_no_click(log_path)

    _clear(log_path)
    _move(connection, x, y)
    xtest.fake_input(connection, X.ButtonPress, 3)
    xtest.fake_input(connection, X.MotionNotify, x=x + 40, y=y + 20)
    escape = connection.keysym_to_keycode(0xff1b)
    xtest.fake_input(connection, X.KeyPress, escape)
    xtest.fake_input(connection, X.KeyRelease, escape)
    xtest.fake_input(connection, X.ButtonRelease, 3)
    connection.sync()
    time.sleep(0.3)
    _assert_button_pair(_read_events(log_path), 0)

    _clear(log_path)
    _gesture_directions(connection, window, root, ["left", "down"])
    _assert_no_click(log_path)
    _wait_for(lambda: window.get_attributes().map_state != X.IsViewable,
              "WindowAction minimize did not unmap the target")
    window.map()
    _activate_window(connection, window, root)
    connection.sync()
    _wait_for(lambda: window.get_attributes().map_state == X.IsViewable,
              "minimized test window could not be restored")

    # Stress the motion path and verify that a following short click still works.
    _clear(log_path)
    _move(connection, x, y)
    xtest.fake_input(connection, X.ButtonPress, 3)
    for index in range(1000):
        xtest.fake_input(connection, X.MotionNotify,
                         x=x + (index % 100), y=y + ((index // 100) % 10))
    xtest.fake_input(connection, X.ButtonRelease, 3)
    connection.sync()
    time.sleep(0.6)
    _clear(log_path)
    _click(connection)
    time.sleep(0.3)
    _assert_button_pair(_read_events(log_path), 2)

    _clear(log_path)
    _gesture_directions(connection, window, root, ["right", "up"])
    _assert_no_click(log_path)
    _wait_for(lambda: not _window_exists(window),
              "WindowAction close did not close the target")

    ordered = sorted(latencies)
    p95 = ordered[int(round((len(ordered) - 1) * 0.95))]
    result = {
        "shortClickSamples": len(latencies),
        "shortClickP95Ms": p95,
        "shortClickMedianMs": statistics.median(latencies),
        "validGestureNoClickLeak": True,
        "invalidGestureNoClickLeak": True,
        "escapeCancellationNoClickLeak": True,
        "stressEvents": 1000,
        "queueRecoveredAfterStress": True,
        "shortcutAction": True,
        "allWindowActions": True,
        "commandAction": True,
        "launchDesktopAction": True,
        "pauseResumeAction": True,
        "noopAction": True,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if p95 <= 50.0 else 6


def _window_exists(window):
    try:
        window.get_attributes()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as failure:
        print("X11 acceptance failed: {0}".format(failure), file=sys.stderr)
        sys.exit(5)

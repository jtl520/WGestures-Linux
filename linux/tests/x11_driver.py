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
from Xlib.protocol import event as xevent


TITLE = "CrossGestures Acceptance Harness"


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


def _mapped_root_windows(root):
    result = set()
    for child in root.query_tree().children:
        try:
            attributes = child.get_attributes()
            geometry = child.get_geometry()
            if attributes.map_state == X.IsViewable and geometry.width >= 300 and \
                    geometry.height >= 250:
                result.add(int(child.id))
        except Exception:
            pass
    return result


def _mapped_popup_windows(root):
    result = set()
    for child in root.query_tree().children:
        try:
            attributes = child.get_attributes()
            geometry = child.get_geometry()
            if attributes.map_state == X.IsViewable and geometry.width >= 8 and \
                    geometry.height >= 8:
                result.add(int(child.id))
        except Exception:
            pass
    return result


def _middle_panel_window(connection, root, before):
    candidates = _mapped_root_windows(root) - before
    if not candidates:
        return None
    return connection.create_resource_object("window", next(iter(candidates)))


def _window_is_viewable(window):
    try:
        return window.get_attributes().map_state == X.IsViewable
    except Exception:
        return False


def _panel_tile_center(window, root, column, row=0):
    geometry = window.get_geometry()
    translated = root.translate_coords(window, 0, 0)
    left = getattr(translated, "dst_x", getattr(translated, "x", 0))
    top = getattr(translated, "dst_y", getattr(translated, "y", 0))
    # QuickPanel has four equal columns and rows. Keeping the calculation
    # proportional makes the probe independent from GTK theme padding.
    return (int(left + geometry.width * (column + 0.5) / 4.0),
            int(top + geometry.height * (row + 0.5) / 4.0))


def _client_message_values(event):
    data = event.data
    if isinstance(data, tuple):
        return data[1]
    return data.l


def _wait_for_event(connection, source_window, event_type, message_atom,
                    deadline, stage):
    while time.monotonic() < deadline:
        if connection.pending_events():
            event = connection.next_event()
            if event_type is xevent.ClientMessage:
                if isinstance(event, xevent.ClientMessage) and \
                        event.client_type == message_atom:
                    return event
            elif isinstance(event, event_type):
                return event
            continue
        time.sleep(0.02)
        connection.flush()
    raise AssertionError(
        "XDND protocol reply did not arrive in time at stage: " + stage)


def _xdnd_drop_file(connection, root, target_window, x, y, path):
    # Minimal XDND version 5 initiator: announce one text/uri-list type over
    # the empty quick-panel tile and answer the selection transfer with the
    # dropped file URI, exactly like a file manager would.
    atoms = {}
    for name in ("XdndAware", "XdndEnter", "XdndPosition", "XdndStatus",
                 "XdndDrop", "XdndFinished", "XdndSelection",
                 "XdndActionCopy", "text/uri-list"):
        atoms[name] = connection.intern_atom(name)
    aware = target_window.get_full_property(atoms["XdndAware"], X.AnyPropertyType)
    if not aware or aware.value is None or len(aware.value) == 0:
        raise AssertionError("quick panel window has no XdndAware property")
    version = min(int(aware.value[0]), 5)
    screen = connection.screen()
    source = root.create_window(
        x - 4000, y - 4000, 1, 1, 0, screen.root_depth, X.InputOutput,
        X.CopyFromParent, override_redirect=1,
        background_pixel=screen.black_pixel)
    source.set_wm_name("crossgestures-acceptance-drag-source")
    # Without owning the XdndSelection the target's XConvertSelection fails
    # silently and no SelectionRequest ever reaches the drag source.
    source.set_selection_owner(atoms["XdndSelection"], X.CurrentTime)
    connection.flush()
    connection.sync()
    owner = connection.get_selection_owner(atoms["XdndSelection"])
    if owner is None or owner.id != source.id:
        raise AssertionError("could not acquire the XdndSelection ownership")

    def send(message_name, values):
        # X ClientMessage events always carry five longs; XDND messages pad
        # their unused trailing fields with zeros.
        values = list(values) + [0] * (5 - len(values))
        target_window.send_event(xevent.ClientMessage(
            window=target_window.id, client_type=atoms[message_name],
            data=(32, values)))
        connection.flush()
        connection.sync()

    deadline = time.monotonic() + 5.0
    send("XdndEnter", [source.id, version << 24, atoms["text/uri-list"], 0, 0])
    send("XdndPosition", [source.id, 0, ((x & 0xFFFF) << 16) | (y & 0xFFFF),
                          X.CurrentTime, atoms["XdndActionCopy"]])
    status = _wait_for_event(
        connection, source, xevent.ClientMessage, atoms["XdndStatus"],
        deadline, "XdndStatus")
    if not (_client_message_values(status)[1] & 1):
        raise AssertionError("quick panel rejected the XDND position")
    send("XdndDrop", [source.id, 0, X.CurrentTime])

    request = _wait_for_event(
        connection, source, xevent.SelectionRequest, None,
        time.monotonic() + 5.0, "SelectionRequest")
    uri_bytes = ("file://{0}\r\n".format(path)).encode("utf-8")
    request.requestor.change_property(
        request.property, request.target, 8, uri_bytes)
    request.requestor.send_event(xevent.SelectionNotify(
        window=request.requestor.id, requestor=request.requestor.id,
        selection=atoms["XdndSelection"], target=request.target,
        property=request.property, time=X.CurrentTime))
    connection.flush()
    connection.sync()
    _wait_for_event(
        connection, source, xevent.ClientMessage, atoms["XdndFinished"],
        time.monotonic() + 5.0, "XdndFinished")


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


def _wait_for(predicate, message, timeout=2.0, detail=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    if detail is not None:
        message = message + " | " + detail()
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

    # Middle click is exclusive while enabled: it opens the GTK panel and does
    # not leak a native click into the target. A second middle click closes it.
    before_panel = _mapped_root_windows(root)
    _clear(log_path)
    _click(connection, 2)
    panel_holder = {"window": None}
    def panel_opened():
        panel_holder["window"] = _middle_panel_window(connection, root, before_panel)
        return panel_holder["window"] is not None
    _wait_for(panel_opened, "middle click did not open the quick panel")
    _assert_no_click(log_path)
    panel_window = panel_holder["window"]
    _click(connection, 2)
    _wait_for(lambda: not _window_is_viewable(panel_window),
              "second middle click did not close the quick panel")

    # A plain left click outside the override-redirect panel must close it,
    # even when Xfwm does not emit focus-out, and the original click must still
    # reach the harness window underneath.
    _activate_window(connection, window, root)
    _move(connection, x, y)
    before_panel = _mapped_root_windows(root)
    _click(connection, 2)
    outside_panel = {"window": None}

    def outside_panel_opened():
        outside_panel["window"] = _middle_panel_window(
            connection, root, before_panel)
        return outside_panel["window"] is not None

    _wait_for(outside_panel_opened,
              "quick panel did not open for outside-left-click test")
    panel_geometry = outside_panel["window"].get_geometry()
    panel_translated = root.translate_coords(
        outside_panel["window"], 0, 0)
    panel_left = getattr(
        panel_translated, "dst_x", getattr(panel_translated, "x", 0))
    window_translated = root.translate_coords(window, 0, 0)
    window_left = getattr(
        window_translated, "dst_x", getattr(window_translated, "x", 0))
    outside_x = max(window_left + 8, panel_left - 12)
    if panel_left <= outside_x < panel_left + panel_geometry.width:
        raise AssertionError("could not find a harness point outside panel")
    _clear(log_path)
    _move(connection, outside_x, y)
    _click(connection, 1)
    _wait_for(lambda: not _window_is_viewable(outside_panel["window"]),
              "outside left click did not close the quick panel")
    _wait_for(lambda: len([
        item for item in _read_events(log_path)
        if item["type"].startswith("button-") and item.get("button") == 1
    ]) >= 2, "outside left click was swallowed instead of replayed")
    outside_left_events = [
        item for item in _read_events(log_path)
        if item["type"].startswith("button-") and item.get("button") == 1
    ]
    if [item["type"] for item in outside_left_events[:2]] != [
            "button-press", "button-release"]:
        raise AssertionError(
            "outside left click replay was not balanced: {0}".format(
                outside_left_events))

    # Exercise each of the four configured panel item types through the real
    # GTK window and package runtime, not only through model unit tests.
    output_dir = os.path.dirname(os.path.abspath(log_path))
    panel_markers = [
        "panel-application-marker", "panel-file-marker",
        "panel-folder-marker", "panel-url-marker",
    ]
    for column, marker_name in enumerate(panel_markers):
        _activate_window(connection, window, root)
        _move(connection, x, y)
        before_panel = _mapped_root_windows(root)
        _click(connection, 2)
        holder = {"window": None}

        def item_panel_opened():
            holder["window"] = _middle_panel_window(
                connection, root, before_panel)
            return holder["window"] is not None

        _wait_for(item_panel_opened,
                  "quick panel did not open for item {0}".format(column))
        tile_x, tile_y = _panel_tile_center(holder["window"], root, column)
        _move(connection, tile_x, tile_y)
        _click(connection, 1)
        _wait_for(lambda: not _window_is_viewable(holder["window"]),
                  "panel item {0} did not close the panel".format(column))
        marker = os.path.join(output_dir, marker_name)
        _wait_for(lambda: os.path.exists(marker),
                  "panel item {0} did not launch".format(column), timeout=3.0)

    # Right-clicking an empty tile must reach GTK and expose the four direct
    # creation actions while gesture capture is suspended for the panel.
    _activate_window(connection, window, root)
    _move(connection, x, y)
    before_panel = _mapped_root_windows(root)
    _click(connection, 2)
    menu_panel = {"window": None}

    def menu_panel_opened():
        menu_panel["window"] = _middle_panel_window(
            connection, root, before_panel)
        return menu_panel["window"] is not None

    _wait_for(menu_panel_opened, "quick panel did not open for right-click menu")
    before_menu = _mapped_popup_windows(root)
    tile_x, tile_y = _panel_tile_center(menu_panel["window"], root, 0, row=1)
    _move(connection, tile_x, tile_y)
    # Hold the right button while the menu maps. Releasing immediately races
    # the popup: if the menu wins, the release lands on its first item and
    # activates the editor instead of exposing the menu under test.
    xtest.fake_input(connection, X.ButtonPress, 3)
    connection.sync()
    new_menu = {"window": None}

    def direct_action_menu_opened():
        # 新弹窗里可能混有 GTK 的 10x10 辅助窗口，必须遍历找到真正的菜单。
        for candidate in _mapped_popup_windows(root) - before_menu:
            candidate_window = connection.create_resource_object(
                "window", candidate)
            if candidate_window.get_geometry().height >= 100:
                new_menu["window"] = candidate_window
                return True
        return False

    def menu_failure_detail():
        popups = []
        for child in root.query_tree().children:
            try:
                attributes = child.get_attributes()
                geometry = child.get_geometry()
                if attributes.map_state == X.IsViewable and                         geometry.width >= 8 and geometry.height >= 8:
                    popups.append((int(child.id), geometry.width,
                                   geometry.height))
            except Exception:
                pass
        return "popups={0}".format(popups)

    _wait_for(direct_action_menu_opened,
              "right-click did not open the four-action creation menu",
              timeout=5.0, detail=menu_failure_detail)
    # Park the pointer outside the popup, then release so no item activates.
    # GTK keeps such a menu open until the next outside press, which also
    # closes the panel itself.
    _move(connection, x, y)
    xtest.fake_input(connection, X.ButtonRelease, 3)
    connection.sync()
    time.sleep(0.3)
    _click(connection, 1)
    _wait_for(lambda: not _window_is_viewable(menu_panel["window"]) and
              not _window_is_viewable(new_menu["window"]),
              "outside click did not close the menu and panel", timeout=5.0)

    # A real XDND conversation drops a file URI on an empty tile, which must
    # configure the slot and then launch the new entry when clicked.
    _activate_window(connection, window, root)
    _move(connection, x, y)
    before_panel = _mapped_root_windows(root)
    _click(connection, 2)
    drop_panel = {"window": None}

    def drop_panel_opened():
        drop_panel["window"] = _middle_panel_window(
            connection, root, before_panel)
        return drop_panel["window"] is not None

    _wait_for(drop_panel_opened, "quick panel did not open for the drop test")
    time.sleep(0.3)
    output_dir = os.path.dirname(os.path.abspath(log_path))
    dropped_path = os.path.join(output_dir, "panel-dropped.txt")
    with open(dropped_path, "w") as stream:
        stream.write("xdnd acceptance")
    tile_x, tile_y = _panel_tile_center(drop_panel["window"], root, 1, row=1)
    _move(connection, tile_x, tile_y)
    time.sleep(0.2)
    _xdnd_drop_file(connection, root, drop_panel["window"],
                    tile_x, tile_y, dropped_path)
    time.sleep(0.5)
    # The X11 GTK panel closes on focus loss or a second middle click; plain
    # outside clicks are not reliable for an override-redirect popup, so use
    # the deterministic middle-click toggle.
    _move(connection, x, y)
    _click(connection, 2)
    _wait_for(lambda: not _window_is_viewable(drop_panel["window"]),
              "second middle click did not close the panel after the drop")

    _activate_window(connection, window, root)
    _move(connection, x, y)
    before_panel = _mapped_root_windows(root)
    _click(connection, 2)
    launch_panel = {"window": None}

    def launch_panel_opened():
        launch_panel["window"] = _middle_panel_window(
            connection, root, before_panel)
        return launch_panel["window"] is not None

    _wait_for(launch_panel_opened,
              "quick panel did not reopen after the drop")
    tile_x, tile_y = _panel_tile_center(launch_panel["window"], root, 1, row=1)
    _move(connection, tile_x, tile_y)
    _click(connection, 1)
    drop_marker = os.path.join(output_dir, "panel-drop-marker")
    _wait_for(lambda: os.path.exists(drop_marker),
              "dropped tile did not launch", timeout=5.0)
    _wait_for(lambda: not _window_is_viewable(launch_panel["window"]),
              "dropped tile did not close the panel")
    panelUriDropLaunched = True

    # Right-button gestures must keep working outside the open panel: a
    # right-up drag toggles maximize on the harness window.
    _activate_window(connection, window, root)
    _move(connection, x, y)
    before_panel = _mapped_root_windows(root)
    _click(connection, 2)
    coexist_panel = {"window": None}

    def coexist_panel_opened():
        coexist_panel["window"] = _middle_panel_window(
            connection, root, before_panel)
        return coexist_panel["window"] is not None

    _wait_for(coexist_panel_opened,
              "quick panel did not open for the gesture coexistence test")
    geometry = coexist_panel["window"].get_geometry()
    translated = root.translate_coords(coexist_panel["window"], 0, 0)
    panel_left = getattr(translated, "dst_x", getattr(translated, "x", 0))
    panel_top = getattr(translated, "dst_y", getattr(translated, "y", 0))
    panel_right = panel_left + geometry.width
    screen_width = connection.screen().width_in_pixels
    gesture_x = min(panel_right + 60, screen_width - 120)
    gesture_y = max(panel_top + 40, 120)
    maximize_atom = connection.intern_atom("_NET_WM_STATE_MAXIMIZED_VERT")
    _clear(log_path)
    _gesture(connection, [
        (gesture_x, gesture_y), (gesture_x, gesture_y - 55)], button=3)
    _assert_no_click(log_path)
    _wait_for(lambda: maximize_atom in _window_states(connection, window),
              "right-up gesture did not maximize with the panel open",
              timeout=4.0)
    _clear(log_path)
    _gesture(connection, [
        (gesture_x, gesture_y), (gesture_x, gesture_y - 55)], button=3)
    _assert_no_click(log_path)
    _wait_for(lambda: maximize_atom not in _window_states(connection, window),
              "right-up gesture did not restore with the panel open",
              timeout=4.0)
    _move(connection, x, y)
    _click(connection, 2)
    _wait_for(lambda: not _window_is_viewable(coexist_panel["window"]),
              "second middle click did not close the panel after the "
              "coexistence test")
    rightGestureWorkedWhilePanelOpen = True

    # While the slot editor dialog is open, right gestures must still work
    # (the user asked for usable gestures while typing in dialog inputs).
    def menu_failure_detail():
        popups = []
        for child in root.query_tree().children:
            try:
                attributes = child.get_attributes()
                geometry = child.get_geometry()
                if attributes.map_state == X.IsViewable and                         geometry.width >= 8 and geometry.height >= 8:
                    popups.append((int(child.id), geometry.width,
                                   geometry.height))
            except Exception:
                pass
        return "popups={0}".format(popups)

    _activate_window(connection, window, root)
    _move(connection, x, y)
    before_panel = _mapped_root_windows(root)
    _click(connection, 2)
    editor_panel = {"window": None}

    def editor_panel_opened():
        editor_panel["window"] = _middle_panel_window(
            connection, root, before_panel)
        return editor_panel["window"] is not None

    _wait_for(editor_panel_opened, "quick panel did not open for the editor test")
    before_menu = _mapped_popup_windows(root)
    tile_x, tile_y = _panel_tile_center(editor_panel["window"], root, 0, row=1)
    _move(connection, tile_x, tile_y)
    xtest.fake_input(connection, X.ButtonPress, 3)
    connection.sync()
    editor_menu = {"window": None}

    def editor_menu_opened():
        for candidate in _mapped_popup_windows(root) - before_menu:
            candidate_window = connection.create_resource_object(
                "window", candidate)
            if candidate_window.get_geometry().height >= 100:
                editor_menu["window"] = candidate_window
                return True
        return False

    _wait_for(editor_menu_opened,
              "right-click did not open the creation menu for the editor test",
              timeout=5.0, detail=menu_failure_detail)
    menu_geometry = editor_menu["window"].get_geometry()
    menu_translated = root.translate_coords(editor_menu["window"], 0, 0)
    menu_left = getattr(menu_translated, "dst_x",
                        getattr(menu_translated, "x", 0))
    menu_top = getattr(menu_translated, "dst_y",
                       getattr(menu_translated, "y", 0))
    # 打开网址（第四项，无子对话框）。
    item_y = int(menu_top + menu_geometry.height * 3.5 / 4.0)
    _move(connection, int(menu_left + menu_geometry.width / 2), item_y)
    xtest.fake_input(connection, X.ButtonRelease, 3)
    connection.sync()
    time.sleep(0.2)
    _click(connection, 1)

    before_editor = _mapped_root_windows(root)
    editor = {"window": None}

    def editor_opened():
        candidates = _mapped_root_windows(root) - before_editor
        if not candidates:
            return False
        editor["window"] = connection.create_resource_object(
            "window", next(iter(candidates)))
        return editor["window"].get_geometry().width >= 400

    _wait_for(editor_opened,
              "slot editor dialog did not open from the creation menu",
              timeout=5.0)
    editor_geometry = editor["window"].get_geometry()
    editor_translated = root.translate_coords(editor["window"], 0, 0)
    editor_left = getattr(editor_translated, "dst_x",
                          getattr(editor_translated, "x", 0))
    editor_top = getattr(editor_translated, "dst_y",
                         getattr(editor_translated, "y", 0))
    screen_width = connection.screen().width_in_pixels
    gesture_x = min(editor_left + editor_geometry.width + 60,
                    screen_width - 120)
    gesture_y = max(editor_top + 40, 120)
    # 编辑器比 harness 窗口大，手势落点在其外的桌面窗口上；用目标无关的
    # 命令动作（下左滑 → touch 标记文件）作为手势生效的证据。
    command_marker = os.path.join(output_dir, "command-marker")
    if os.path.exists(command_marker):
        os.remove(command_marker)
    _clear(log_path)
    _gesture(connection, [
        (gesture_x, gesture_y), (gesture_x - 45, gesture_y + 45)], button=3)
    _assert_no_click(log_path)
    _wait_for(lambda: os.path.exists(command_marker),
              "down-left gesture did not run with the editor open",
              timeout=4.0)
    escape_keycode = connection.keysym_to_keycode(0xFF1B) or 9
    xtest.fake_input(connection, X.KeyPress, escape_keycode)
    xtest.fake_input(connection, X.KeyRelease, escape_keycode)
    connection.sync()
    _wait_for(lambda: not _window_is_viewable(editor["window"]),
              "escape did not close the slot editor", timeout=4.0)
    _move(connection, x, y)
    _click(connection, 2)
    _wait_for(lambda: not _window_is_viewable(editor_panel["window"]),
              "middle click did not close the panel after the editor test")
    gestureWorkedWhileEditorOpen = True

    # Moving beyond the drag threshold cancels the candidate without opening a
    # panel or replaying a middle click.
    before_panel = _mapped_root_windows(root)
    _clear(log_path)
    _move(connection, x, y)
    xtest.fake_input(connection, X.ButtonPress, 2)
    xtest.fake_input(connection, X.MotionNotify, x=x + 80, y=y + 30)
    xtest.fake_input(connection, X.ButtonRelease, 2)
    connection.sync()
    time.sleep(0.25)
    _assert_button_pair(_read_events(log_path), 0)
    if _mapped_root_windows(root) - before_panel:
        raise AssertionError("middle drag unexpectedly opened the quick panel")

    # Disabling the feature removes the passive middle grab, restoring exactly
    # one native press/release pair to the target application.
    subprocess.check_call([
        "gsettings", "set", "org.gnome.shell.extensions.wgestures",
        "middle-panel-enabled", "false"])
    time.sleep(0.2)
    _activate_window(connection, window, root)
    _move(connection, x, y)
    _clear(log_path)
    _click(connection, 2)
    time.sleep(0.2)
    middle_events = [item for item in _read_events(log_path)
                     if item["type"].startswith("button-") and item.get("button") == 2]
    if [item["type"] for item in middle_events] != ["button-press", "button-release"]:
        raise AssertionError("disabled panel did not restore native middle click: {0}".format(
            middle_events))
    subprocess.check_call([
        "gsettings", "set", "org.gnome.shell.extensions.wgestures",
        "middle-panel-enabled", "true"])
    time.sleep(0.8)
    _activate_window(connection, window, root)
    _move(connection, x, y)
    _clear(log_path)
    _click(connection, 1)
    time.sleep(0.2)
    try:
        _assert_button_pair(_read_events(log_path), 2)
    except AssertionError as error:
        raise AssertionError("harness did not regain pointer focus after panel close: {0}".format(
            error))

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
        try:
            _assert_button_pair(events, 2)
        except AssertionError as error:
            raise AssertionError("short right click was not replayed after panel use: {0}".format(
                error))
        first = next(item for item in events if item["type"] == "button-press")
        latencies.append(max(0.0, (first["time"] - released_at) * 1000.0))
        # The backend restores passive grabs just after the replayed release.
        # A real double-click naturally has a longer interval; keep the
        # automated loop from racing that final GLib callback.
        time.sleep(0.01)

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
        "middlePanelOpened": True,
        "middlePanelSecondClickClosed": True,
        "outsideLeftClickClosedPanelAndReplayed": True,
        "middlePanelDragCancelled": True,
        "disabledPanelRestoredNativeMiddle": True,
        "panelApplicationItem": True,
        "panelFileItem": True,
        "panelFolderItem": True,
        "panelUrlItem": True,
        "panelRightClickMenu": True,
        "panelDirectFourActionMenu": True,
        "panelUriDropLaunched": panelUriDropLaunched,
        "rightGestureWorkedWhilePanelOpen": rightGestureWorkedWhilePanelOpen,
        "gestureWorkedWhileEditorOpen": gestureWorkedWhileEditorOpen,
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

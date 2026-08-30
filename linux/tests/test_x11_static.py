from __future__ import unicode_literals

import os
import sys
import unittest
from unittest import mock

import gi
gi.require_version("Gtk", "3.0")


LINUX_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LINUX_ROOT)

try:
    from gi.repository import Gtk
    from Xlib import X, XK
    from wgestures.x11_actions import X11ActionExecutor, parse_accelerator
    from wgestures import x11_backend as backend_module
    from wgestures.x11_backend import REPLAY_REGRAB_DELAY_MS, REPLAY_SETTLE_MS, X11Backend
    from wgestures.x11_overlay import GestureOverlay
    from wgestures.prefs import (GENERAL_TRIGGER_BUTTONS, _compact_control,
                                 present_preferences_window)
    X11_IMPORT_ERROR = None
except (ImportError, ValueError) as error:
    X11_IMPORT_ERROR = error


@unittest.skipIf(X11_IMPORT_ERROR is not None,
                 "X11/PyGObject dependencies unavailable: {0}".format(X11_IMPORT_ERROR))
class X11StaticTests(unittest.TestCase):
    def test_tray_has_middle_button_fallback_panel_entry(self):
        tray_path = os.path.join(LINUX_ROOT, "wgestures", "tray.py")
        with open(tray_path, encoding="utf-8") as stream:
            tray_source = stream.read()
        with open(backend_module.__file__, encoding="utf-8") as stream:
            backend_source = stream.read()
        self.assertIn('Gtk.MenuItem.new_with_label("弹出快捷面板")', tray_source)
        self.assertIn("self._show_panel_from_tray", backend_source)

    def test_tray_panel_callback_uses_current_pointer(self):
        calls = []

        class FakeRoot(object):
            @staticmethod
            def query_pointer():
                return type("Pointer", (object,), {
                    "root_x": 321, "root_y": 654,
                })()

        class FakePanel(object):
            @staticmethod
            def show_at(x, y):
                calls.append(("show", x, y))

        backend = X11Backend.__new__(X11Backend)
        backend._cleaned = False
        backend.root = FakeRoot()
        backend.panel = FakePanel()
        backend._ungrab_all = lambda: calls.append("ungrab")
        backend._grab_configured = lambda: calls.append("grab")
        self.assertEqual(backend._show_panel_from_tray_idle(),
                         backend_module.GLib.SOURCE_REMOVE)
        self.assertEqual(calls, ["ungrab", ("show", 321, 654), "grab"])

    def test_general_trigger_row_includes_middle_panel_in_visual_order(self):
        self.assertEqual(
            GENERAL_TRIGGER_BUTTONS, ("right", "middle", "x1", "x2"))

    def test_overlay_renders_unicode_labels_with_pango_font_fallback(self):
        calls = []

        class FakeSettings(object):
            @staticmethod
            def get(key):
                return {
                    "path-color": "#27ae60", "path-width": 4,
                    "show-command-name": True,
                }[key]

        class FakeColor(object):
            red, green, blue, alpha = 0.15, 0.68, 0.38, 1.0

        class FakeRect(object):
            x, y, width, height = 0, 0, 42, 22

        class FakeLayout(object):
            def set_font_description(self, _font):
                calls.append("font")

            def set_text(self, text, length):
                calls.append(("text", text, length))

            @staticmethod
            def get_pixel_extents():
                return FakeRect(), FakeRect()

        class FakeContext(object):
            def __getattr__(self, name):
                return lambda *args: calls.append((name, args))

        overlay = GestureOverlay.__new__(GestureOverlay)
        overlay.settings = FakeSettings()
        overlay.points = [(10, 10), (40, 40)]
        overlay.valid = True
        overlay.label = "智能复制"
        overlay.opacity = 1.0
        overlay.origin_x = 0
        overlay.origin_y = 0
        layout = FakeLayout()
        context = FakeContext()
        with mock.patch.object(GestureOverlay, "_parse_color",
                               return_value=FakeColor()), \
                mock.patch("wgestures.x11_overlay.PangoCairo.create_layout",
                           return_value=layout), \
                mock.patch("wgestures.x11_overlay.PangoCairo.show_layout") as show:
            overlay._draw(None, context)
        self.assertIn(("text", "智能复制", -1), calls)
        show.assert_called_once_with(context, layout)

    def test_compact_controls_keep_their_theme_natural_width(self):
        alignments = []

        class FakeControl(object):
            def set_halign(self, alignment):
                alignments.append(alignment)

        control = FakeControl()
        self.assertIs(_compact_control(control), control)
        self.assertEqual(alignments, [Gtk.Align.START])

    def test_hidden_preferences_window_is_remapped_on_activation(self):
        calls = []

        class FakeWindow(object):
            def show_all(self):
                calls.append("show")

            def deiconify(self):
                calls.append("deiconify")

            def present(self):
                calls.append("present")

        present_preferences_window(FakeWindow())
        self.assertEqual(calls, ["deiconify", "show", "present"])

    def test_missing_gi_cairo_bridge_fails_before_opening_x11(self):
        with mock.patch("wgestures.x11_backend.gi.require_foreign",
                        side_effect=ImportError("missing bridge")), \
                mock.patch("wgestures.x11_backend.display.Display") as open_display:
            with self.assertRaisesRegex(RuntimeError, "python3-gi-cairo"):
                X11Backend()
        open_display.assert_not_called()

    def test_accelerator_parser_includes_xf86_audio_keysyms(self):
        self.assertEqual(parse_accelerator("<Control><Shift>t"),
                         (["Control_L", "Shift_L"], "t"))
        self.assertEqual(parse_accelerator("Ctrl+Shift+T"),
                         (["Control_L", "Shift_L"], "t"))
        self.assertEqual(parse_accelerator("control c"),
                         (["Control_L"], "c"))
        _modifiers, audio = parse_accelerator("AudioMute")
        self.assertNotEqual(XK.string_to_keysym(audio), 0)

    def test_replay_removes_grabs_before_injection_and_restores_after_sync(self):
        backend = X11Backend.__new__(X11Backend)
        calls = []

        class FakeDisplay(object):
            def ungrab_pointer(self, timestamp):
                calls.append(("pointer", timestamp))

            def sync(self):
                calls.append("capture-sync")

        class FakeInjectDisplay(object):
            def sync(self):
                calls.append("inject-sync")

        backend.display = FakeDisplay()
        backend.inject_display = FakeInjectDisplay()
        backend._cleaned = False
        backend._replay_source = None
        backend._restore_grabs_source = None
        backend._ungrab_all = lambda: calls.append("ungrab")
        backend._grab_configured = lambda: calls.append("regrab")
        scheduled = []
        with mock.patch("wgestures.x11_backend.xtest.fake_input",
                        side_effect=lambda _display, event_type, button, **kwargs:
                        calls.append(("inject", event_type, button,
                                      kwargs.get("time")))), \
                mock.patch("wgestures.x11_backend.GLib.timeout_add",
                           side_effect=lambda delay, callback, *args:
                           scheduled.append((delay, callback, args)) or
                           (77 + len(scheduled) - 1)):
            backend._replay_click(3)
            self.assertEqual(calls, [
                ("pointer", X.CurrentTime), "ungrab",
            ])
            self.assertEqual(backend._replay_source, 77)
            self.assertEqual(scheduled[0][0], 30)
            scheduled[0][1](*scheduled[0][2])
            self.assertEqual(calls, [
                ("pointer", X.CurrentTime), "ungrab",
                ("inject", X.ButtonPress, 3, None),
                ("inject", X.ButtonRelease, 3, 24),
                "inject-sync",
            ])
            self.assertEqual(scheduled[1][0], 4)
            scheduled[1][1](*scheduled[1][2])
        self.assertEqual(calls, [
            ("pointer", X.CurrentTime), "ungrab",
            ("inject", X.ButtonPress, 3, None),
            ("inject", X.ButtonRelease, 3, 24),
            "inject-sync", "regrab",
        ])
        self.assertIsNone(backend._replay_source)
        self.assertIsNone(backend._restore_grabs_source)

    def test_panel_visible_replays_surface_clicks_and_asyncs_gesture_presses(self):
        backend = X11Backend.__new__(X11Backend)

        class FakeSettings(object):
            def __init__(self):
                self.values = {
                    "trigger-buttons": ["right"], "enabled": True,
                    "paused": False, "middle-panel-enabled": True,
                    "start-threshold": 8,
                }

            def get(self, key):
                return self.values[key]

        class FakePanelWindow(object):
            def get_geometry(self):
                return (100, 100, 400, 400)

        class FakePanel(object):
            def __init__(self):
                self.window = FakePanelWindow()
                self.editing = False
                self.closed = 0
                self.shown = 0

            def get_visible(self):
                return True

            def get_window(self):
                return self.window

            def close_panel(self):
                self.closed += 1

            def show_at(self, _x, _y):
                self.shown += 1

        class FakeSession(object):
            def __init__(self):
                self.begins = []
                self.active = None

            def begin(self, _context, x, y):
                self.begins.append((x, y))
                return False

            def release(self, _detail):
                return {"handled": False}

        class FakeDisplay(object):
            def __init__(self):
                self.allowed = []

            def allow_events(self, mode, time):
                self.allowed.append((mode, time))

            def flush(self):
                pass

        display = FakeDisplay()
        backend.settings = FakeSettings()
        backend.panel = FakePanel()
        backend.session = FakeSession()
        backend.display = display
        backend._panel_candidate = None
        backend._configure_recognizer = lambda: None
        backend._window_at = lambda x, y: None
        backend._identity_for_window = lambda window: {}

        # 面板可见时除手势按钮 + 中键外临时抓取左键，用于外部点击关闭。
        self.assertEqual(
            backend._grab_button_names(), ["right", "middle", "left"])

        def press(x, y, timestamp):
            backend._button_press(type("Event", (object,), {
                "detail": 3, "root_x": x, "root_y": y, "time": timestamp})())

        # 面板表面上的右键按下：ReplayPointer 原样交给格子，不进手势。
        press(200, 200, 500)
        self.assertEqual(backend.session.begins, [])
        self.assertEqual(display.allowed, [(X.ReplayPointer, 500)])

        # 面板表面的左键同样原样交给格子；桌面上的左键关闭面板但仍回放，
        # 不能吞掉桌面选择/目标窗口激活。
        backend._button_press(type("Event", (object,), {
            "detail": 1, "root_x": 200, "root_y": 200, "time": 510})())
        self.assertEqual(display.allowed[-1], (X.ReplayPointer, 510))
        self.assertEqual(backend.panel.closed, 0)
        backend._button_press(type("Event", (object,), {
            "detail": 1, "root_x": 900, "root_y": 200, "time": 515})())
        self.assertEqual(display.allowed[-1], (X.ReplayPointer, 515))
        self.assertEqual(backend.panel.closed, 1)
        self.assertEqual(backend.session.begins, [])

        # 编辑对话框打开时（editing=True），面板表面上的右键也进入手势，
        # 输入框中的手势不再被格子交互吞掉。
        backend.panel.editing = True
        backend._button_press(type("Event", (object,), {
            "detail": 2, "root_x": 200, "root_y": 200, "time": 525})())
        self.assertEqual(display.allowed[-1], (X.AsyncPointer, 525))
        self.assertIsNone(backend._panel_candidate)
        self.assertEqual(backend.panel.closed, 1)
        self.assertEqual(backend.panel.shown, 0)
        press(200, 200, 550)
        self.assertEqual(backend.session.begins[-1], (200.0, 200.0))
        backend.panel.editing = False
        backend.session.begins = []

        # 面板之外的右键：解冻指针并进入手势会话。
        press(900, 200, 600)
        self.assertEqual(backend.session.begins, [(900.0, 200.0)])
        self.assertEqual(display.allowed[-1], (X.AsyncPointer, 600))

        # 释放与后续事件不再需要放行，正常返回。
        backend._button_release(type("Event", (object,), {
            "detail": 3, "root_x": 900, "root_y": 200, "time": 700})())

    def test_sync_grab_presses_are_always_unfrozen(self):
        backend = X11Backend.__new__(X11Backend)

        class FakeSession(object):
            def __init__(self):
                self.active = object()

        class FakeDisplay(object):
            def __init__(self):
                self.allowed = []

            def allow_events(self, mode, time):
                self.allowed.append(mode)

            def flush(self):
                pass

        class FakePanelWindow(object):
            def get_geometry(self):
                return (100, 100, 400, 400)

        class FakePanel(object):
            def get_visible(self):
                return True

            def get_window(self):
                return FakePanelWindow()

        backend.session = FakeSession()
        backend.display = FakeDisplay()
        backend.panel = FakePanel()
        backend.settings = type("Settings", (object,), {
            "get": lambda self, key: {
                "trigger-buttons": ["right"], "enabled": True,
                "paused": False, "middle-panel-enabled": True,
                "start-threshold": 8}[key]})()
        backend._panel_candidate = None
        # 会话进行中的重复按下也必须解冻，否则指针被同步抓取永久冻结。
        backend._button_press(type("Event", (object,), {
            "detail": 3, "root_x": 50, "root_y": 50, "time": 800})())
        self.assertEqual(backend.display.allowed, [X.AsyncPointer])

        # 未映射的按钮同样解冻。
        backend.session.active = None
        backend._button_press(type("Event", (object,), {
            "detail": 6, "root_x": 50, "root_y": 50, "time": 900})())
        self.assertEqual(backend.display.allowed, [X.AsyncPointer, X.AsyncPointer])

    def test_cancel_releases_active_pointer_and_keyboard(self):
        backend = X11Backend.__new__(X11Backend)
        calls = []

        class FakeSession(object):
            @staticmethod
            def cancel():
                return True

        class FakeDisplay(object):
            @staticmethod
            def ungrab_pointer(timestamp):
                calls.append(("pointer", timestamp))

            @staticmethod
            def flush():
                calls.append("flush")

        class FakeOverlay(object):
            @staticmethod
            def cancel():
                calls.append("overlay")

        backend.session = FakeSession()
        backend.display = FakeDisplay()
        backend.overlay = FakeOverlay()
        backend._ungrab_keyboard = lambda: calls.append("keyboard")
        backend.cancel("test")
        self.assertEqual(calls, [
            ("pointer", X.CurrentTime), "flush", "keyboard", "overlay",
        ])

    def test_session_and_monitor_changes_close_panel_before_cancel(self):
        backend = X11Backend.__new__(X11Backend)
        calls = []

        class FakePanel(object):
            @staticmethod
            def close_panel():
                calls.append("panel")

        class FakeParameters(object):
            def __init__(self, active):
                self.active = active

            def unpack(self):
                return (self.active,)

        backend.panel = FakePanel()
        backend.cancel = lambda message=None: calls.append(("cancel", message))

        backend._screen_saver_changed(
            None, None, None, None, None, FakeParameters(True))
        backend._prepare_for_sleep(
            None, None, None, None, None, FakeParameters(True))
        backend._cancel_for_monitor_change()
        self.assertEqual(calls, [
            "panel", ("cancel", "会话已锁定"),
            "panel", ("cancel", "系统准备休眠"),
            "panel", ("cancel", "显示器配置已变化"),
        ])

    def test_action_model_dispatches_every_supported_type(self):
        calls = []

        class FakeSettings(object):
            @staticmethod
            def set(key, value):
                calls.append(("setting", key, value))

        executor = X11ActionExecutor.__new__(X11ActionExecutor)
        executor.settings = FakeSettings()
        executor._shortcut = lambda value: calls.append(("shortcut", value))
        executor._window = lambda operation, window: calls.append(
            ("window", operation, window))
        executor._command = lambda value: calls.append(("command", value))
        executor._launch = lambda value: calls.append(("launch", value))
        context = {"window": "target", "identity": {"wmClass": "xfce4-terminal"}}
        executor.execute({"type": "ShortcutAction", "accelerator": "<Alt>Left"}, context)
        executor.execute({"type": "CopyAction"}, context)
        executor.execute({"type": "PasteAction"}, context)
        executor.execute({"type": "WindowAction", "operation": "close"}, context)
        executor.execute({"type": "CommandAction", "command": "true"}, context)
        executor.execute({"type": "LaunchAction", "target": "org.example.App.desktop"}, context)
        executor.execute({"type": "PauseAction"}, context)
        executor.execute({"type": "NoopAction"}, context)
        self.assertEqual(calls, [
            ("shortcut", "<Alt>Left"),
            ("shortcut", "<Control><Shift>c"),
            ("shortcut", "<Control><Shift>v"),
            ("window", "close", "target"),
            ("command", "true"),
            ("launch", "org.example.App.desktop"),
            ("setting", "paused", True),
        ])

    def test_shortcut_injects_balanced_keys_in_order(self):
        calls = []

        class FakeDisplay(object):
            @staticmethod
            def keysym_to_keycode(keysym):
                return keysym & 0xff

            @staticmethod
            def sync():
                calls.append("sync")

        executor = X11ActionExecutor.__new__(X11ActionExecutor)
        executor.display = FakeDisplay()
        with mock.patch("wgestures.x11_actions.xtest.fake_input",
                        side_effect=lambda _display, event_type, keycode:
                        calls.append((event_type, keycode))):
            executor._shortcut("<Control><Alt>Left")
        self.assertEqual([item[0] for item in calls[:-1]], [
            X.KeyPress, X.KeyPress, X.KeyPress,
            X.KeyRelease, X.KeyRelease, X.KeyRelease,
        ])
        self.assertEqual(calls[-1], "sync")

    def test_all_ewmh_window_operations_are_routed(self):
        calls = []

        class FakeRoot(object):
            @staticmethod
            def send_event(event, event_mask=None):
                calls.append(("minimize", event_mask, event))

        class FakeDisplay(object):
            @staticmethod
            def intern_atom(name):
                return name

            @staticmethod
            def flush():
                calls.append("flush")

        executor = X11ActionExecutor.__new__(X11ActionExecutor)
        executor.root = FakeRoot()
        executor.display = FakeDisplay()
        executor._toggle_states = lambda _window, atoms: calls.append(
            ("toggle", tuple(atoms)))
        executor._client_message = lambda _window, message, data: calls.append(
            ("client", message, tuple(data)))
        window = 123
        with mock.patch("wgestures.x11_actions.xevent.ClientMessage",
                        return_value="minimize-event"):
            for operation in ("toggle-maximized", "toggle-fullscreen", "toggle-above",
                              "close", "minimize"):
                executor._window(operation, window)
        self.assertIn(("toggle", ("_NET_WM_STATE_MAXIMIZED_HORZ",
                                  "_NET_WM_STATE_MAXIMIZED_VERT")), calls)
        self.assertIn(("toggle", ("_NET_WM_STATE_FULLSCREEN",)), calls)
        self.assertIn(("toggle", ("_NET_WM_STATE_ABOVE",)), calls)
        self.assertTrue(any(item[0:2] == ("client", "_NET_CLOSE_WINDOW")
                            for item in calls if isinstance(item, tuple)))
        self.assertTrue(any(item[0] == "minimize" for item in calls
                            if isinstance(item, tuple)))


if __name__ == "__main__":
    unittest.main(verbosity=2)

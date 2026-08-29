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
    from wgestures.x11_backend import X11Backend
    from wgestures.x11_overlay import GestureOverlay
    from wgestures.prefs import _compact_control, present_preferences_window
    X11_IMPORT_ERROR = None
except (ImportError, ValueError) as error:
    X11_IMPORT_ERROR = error


@unittest.skipIf(X11_IMPORT_ERROR is not None,
                 "X11/PyGObject dependencies unavailable: {0}".format(X11_IMPORT_ERROR))
class X11StaticTests(unittest.TestCase):
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
        backend._ungrab_all = lambda: calls.append("ungrab")
        backend._grab_configured = lambda: calls.append("regrab")
        scheduled = []
        with mock.patch("wgestures.x11_backend.xtest.fake_input",
                        side_effect=lambda _display, event_type, button, **kwargs:
                        calls.append(("inject", event_type, button,
                                      kwargs.get("time")))), \
                mock.patch("wgestures.x11_backend.GLib.timeout_add",
                           side_effect=lambda delay, callback, button:
                           scheduled.append((delay, callback, button)) or 77):
            backend._replay_click(3)
            self.assertEqual(calls, [
                ("pointer", X.CurrentTime), "ungrab",
            ])
            self.assertEqual(backend._replay_source, 77)
            self.assertEqual(scheduled[0][0], 12)
            scheduled[0][1](scheduled[0][2])
        self.assertEqual(calls, [
            ("pointer", X.CurrentTime), "ungrab",
            ("inject", X.ButtonPress, 3, None),
            ("inject", X.ButtonRelease, 3, 24),
            "inject-sync", "regrab",
        ])
        self.assertIsNone(backend._replay_source)

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

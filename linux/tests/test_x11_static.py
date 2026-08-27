from __future__ import unicode_literals

import os
import sys
import unittest
from unittest import mock


LINUX_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LINUX_ROOT)

try:
    from Xlib import X, XK
    from wgestures.x11_actions import X11ActionExecutor, parse_accelerator
    from wgestures.x11_backend import X11Backend
    X11_IMPORT_ERROR = None
except (ImportError, ValueError) as error:
    X11_IMPORT_ERROR = error


@unittest.skipIf(X11_IMPORT_ERROR is not None,
                 "X11/PyGObject dependencies unavailable: {0}".format(X11_IMPORT_ERROR))
class X11StaticTests(unittest.TestCase):
    def test_accelerator_parser_includes_xf86_audio_keysyms(self):
        self.assertEqual(parse_accelerator("<Control><Shift>t"),
                         (["Control_L", "Shift_L"], "t"))
        _modifiers, audio = parse_accelerator("AudioMute")
        self.assertNotEqual(XK.string_to_keysym(audio), 0)

    def test_replay_removes_grabs_before_injection_and_restores_after_sync(self):
        backend = X11Backend.__new__(X11Backend)
        calls = []

        class FakeDisplay(object):
            def sync(self):
                calls.append("sync")

        backend.display = FakeDisplay()
        backend._ungrab_all = lambda: calls.append("ungrab")
        backend._grab_configured = lambda: calls.append("regrab")
        with mock.patch("wgestures.x11_backend.xtest.fake_input",
                        side_effect=lambda _display, event_type, button:
                        calls.append((event_type, button))):
            backend._replay_click(3)
        self.assertEqual(calls, [
            "ungrab", (X.ButtonPress, 3), (X.ButtonRelease, 3),
            "sync", "regrab",
        ])

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
        context = {"window": "target"}
        executor.execute({"type": "ShortcutAction", "accelerator": "<Alt>Left"}, context)
        executor.execute({"type": "WindowAction", "operation": "close"}, context)
        executor.execute({"type": "CommandAction", "command": "true"}, context)
        executor.execute({"type": "LaunchAction", "target": "org.example.App.desktop"}, context)
        executor.execute({"type": "PauseAction"}, context)
        executor.execute({"type": "NoopAction"}, context)
        self.assertEqual(calls, [
            ("shortcut", "<Alt>Left"),
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

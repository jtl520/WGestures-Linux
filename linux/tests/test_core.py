from __future__ import unicode_literals

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock


LINUX_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPOSITORY_ROOT = os.path.dirname(LINUX_ROOT)
sys.path.insert(0, LINUX_ROOT)

from wgestures.autostart import (session_autostart_enabled,
                                 set_session_autostart)
from wgestures.config import (create_default_config, find_matching_profile,
                              normalize_config, resolve_gesture)
from wgestures.diagnostics import dependency_status, select_backend
from wgestures.gesture import (GestureRecognizer, GestureSession,
                               direction_error_degrees, direction_from_delta,
                               gesture_key, simplify_corner_transitions)
from wgestures.importer import import_legacy_config
from wgestures.portable import export_portable_config, import_config
from wgestures.settings import DEFAULTS
from wgestures.storage import ConfigStore
from wgestures.shortcut import (action_display_name, copy_accelerator,
                                display_accelerator, is_terminal_identity,
                                normalize_accelerator, paste_accelerator)


class ConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(REPOSITORY_ROOT, "tests", "fixtures",
                            "core-conformance.json")
        with open(path, "r", encoding="utf-8") as stream:
            cls.fixtures = json.load(stream)

    def test_direction_vectors_match_shared_fixtures(self):
        for case in self.fixtures["directionCases"]:
            self.assertEqual(
                direction_from_delta(case["dx"], case["dy"], case["mode"]),
                case["expected"])
        for case in self.fixtures["directionToleranceCases"]:
            error = direction_error_degrees(
                case["direction"], case["dx"], case["dy"])
            self.assertEqual(error <= case["maximumError"], case["matches"])
        for case in self.fixtures["cornerSimplificationCases"]:
            self.assertEqual(simplify_corner_transitions(case["actual"]),
                             case["expected"])

    def test_recognizer_matches_shared_fixtures(self):
        for case in self.fixtures["recognizerCases"]:
            options = case["options"]
            recognizer = GestureRecognizer(
                options["directionMode"], options["startThreshold"],
                options["segmentThreshold"])
            recognizer.begin(*case["points"][0])
            for point in case["points"][1:]:
                recognizer.add_point(*point)
            result = recognizer.finish()
            self.assertEqual(result["effective"], case["effective"])
            self.assertEqual(result["directions"], case["directions"])

    def test_session_short_click_gesture_mismatch_and_cancel(self):
        session = GestureSession(GestureRecognizer(start_threshold=5,
                                                    segment_threshold=5))
        self.assertTrue(session.begin({"button_number": 3}, 0, 0))
        self.assertTrue(session.release(2)["mismatched"])
        self.assertFalse(session.release(3)["result"]["effective"])
        session.begin({"button_number": 3}, 0, 0)
        session.motion(10, 0)
        self.assertEqual(session.release(3)["result"]["directions"], ["right"])
        session.begin({"button_number": 3}, 0, 0)
        self.assertTrue(session.cancel())
        self.assertIsNone(session.active)


class ConfigurationTests(unittest.TestCase):
    def test_defaults_are_the_same_four_gestures_as_windows(self):
        config = create_default_config()
        self.assertEqual([item["type"] for item in config["actions"]],
                         ["ShortcutAction", "ShortcutAction", "ShortcutAction",
                          "WindowAction"])
        self.assertEqual([
            (item["button"], item["directions"], item["actionId"])
            for item in config["globalProfile"]["gestures"]
        ], [
            ("right", ["up"], "smart-copy"),
            ("right", ["down"], "smart-paste"),
            ("right", ["down", "right", "down"], "press-enter"),
            ("right", ["up", "right", "up"], "window-toggle-above"),
        ])
        self.assertEqual([item.get("accelerator") for item in config["actions"][:3]],
                         ["<Control>c", "<Control>v", "Return"])

    def test_shortcuts_accept_friendly_and_legacy_formats(self):
        for value in ("Ctrl+C", "Control+C", "Ctrl C", "control c",
                      "<Control>c"):
            self.assertEqual(normalize_accelerator(value), "<Control>c")
            self.assertEqual(display_accelerator(value), "Ctrl+C")
        self.assertEqual(normalize_accelerator("Ctrl+Shift+T"),
                         "<Control><Shift>t")
        self.assertEqual(display_accelerator("<Alt>Left"), "Alt+Left")
        with self.assertRaises(ValueError):
            normalize_accelerator("Ctrl+")

    def test_smart_clipboard_actions_use_terminal_specific_shortcuts(self):
        terminals = (
            {"desktopId": "org.gnome.Terminal.desktop"},
            {"wmClass": "xfce4-terminal"},
            {"gtkApplicationId": "org.gnome.Ptyxis"},
            {"desktopId": "org.kde.konsole.desktop"},
        )
        for identity in terminals:
            self.assertTrue(is_terminal_identity(identity))
            self.assertEqual(copy_accelerator(identity), "<Control><Shift>c")
            self.assertEqual(paste_accelerator(identity), "<Control><Shift>v")
        self.assertFalse(is_terminal_identity({"desktopId": "firefox.desktop"}))
        self.assertEqual(copy_accelerator({"wmClass": "libreoffice-writer"}),
                         "<Control>c")
        self.assertEqual(paste_accelerator({"wmClass": "libreoffice-writer"}),
                         "<Control>v")
        self.assertEqual(action_display_name(
            {"name": "动作名称", "type": "CopyAction"},
            {"name": "我的复制手势"}), "我的复制手势")
        self.assertEqual(action_display_name(
            {"name": "粘贴", "type": "PasteAction"}), "粘贴")
        self.assertTrue(DEFAULTS["show-command-name"])
        self.assertEqual(DEFAULTS["fade-duration"], 300)
        self.assertTrue(DEFAULTS["autostart-enabled"])
        self.assertTrue(DEFAULTS["minimize-to-tray"])

    def test_packaged_default_matches_python_default(self):
        path = os.path.join(REPOSITORY_ROOT, "gnome-extension", "defaults",
                            "gestures-v1.json")
        with open(path, "r", encoding="utf-8") as stream:
            packaged = json.load(stream)
        self.assertEqual(normalize_config(packaged)["config"],
                         create_default_config())

    def test_matching_precedence_inheritance_and_conflicts(self):
        config = create_default_config()
        config["profiles"].append({
            "id": "firefox", "name": "Firefox", "enabled": True,
            "inheritGlobal": True,
            "matchers": [{"type": "desktopId", "value": "firefox.desktop"}],
            "gestures": [],
        })
        self.assertEqual(find_matching_profile(
            config, {"desktopId": "FIREFOX.DESKTOP"})["id"], "firefox")
        self.assertEqual(resolve_gesture(
            config, {"desktopId": "firefox.desktop"}, "right", ["up"]
        )["action"]["id"], "smart-copy")
        config["actions"].append({"id": "bad", "name": "Bad",
                                  "type": "UnknownAction"})
        config["globalProfile"]["gestures"].append(dict(
            config["globalProfile"]["gestures"][0], id="duplicate"))
        normalized = normalize_config(config)
        self.assertGreaterEqual(len(normalized["warnings"]), 2)
        self.assertFalse(any(item["id"] == "bad"
                             for item in normalized["config"]["actions"]))

    def test_single_direction_gestures_allow_moderate_drawing_error(self):
        config = create_default_config()
        upward = resolve_gesture(
            config, {}, "right", ["up-right", "up"],
            {"origin": (0, 0), "end": (60, -100)})
        self.assertEqual(upward["action"]["id"], "smart-copy")
        downward = resolve_gesture(
            config, {}, "right", ["down-left", "down"],
            {"origin": (0, 0), "end": (-50, 100)})
        self.assertEqual(downward["action"]["id"], "smart-paste")
        diagonal = resolve_gesture(
            config, {}, "right", ["up-right"],
            {"origin": (0, 0), "end": (100, -100)})
        self.assertIsNone(diagonal)
        wrong_button = resolve_gesture(
            config, {}, "middle", ["up-right", "up"],
            {"origin": (0, 0), "end": (60, -100)})
        self.assertIsNone(wrong_button)

    def test_rounded_corners_match_window_above_gesture(self):
        config = create_default_config()
        exact = resolve_gesture(
            config, {}, "right", ["up", "right", "up"])
        self.assertEqual(exact["action"]["operation"], "toggle-above")
        rounded = resolve_gesture(config, {}, "right", [
            "up", "up-right", "right", "up-right", "up",
        ])
        self.assertEqual(rounded["action"]["id"], "window-toggle-above")
        self.assertEqual(rounded["gesture"]["name"], "窗口置顶")

    def test_invalid_schema_fails_closed(self):
        with self.assertRaises(ValueError):
            normalize_config({"schemaVersion": 999})
        with self.assertRaises(ValueError):
            gesture_key("left-button", ["left"])

    def test_atomic_storage_recovers_last_valid_backup(self):
        directory = tempfile.mkdtemp(prefix="wgestures-test-")
        try:
            path = os.path.join(directory, "gestures-v1.json")
            store = ConfigStore(path)
            original = create_default_config()
            store.save(original, create_backup=False)
            changed = create_default_config()
            changed["actions"][0]["name"] = "Changed"
            store.save(changed)
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("{broken")
            recovered = store.load()
            self.assertEqual(recovered["source"], "backup")
            self.assertEqual(recovered["config"], original)
            self.assertTrue(recovered["warnings"])
        finally:
            shutil.rmtree(directory)


class ImporterTests(unittest.TestCase):
    def _legacy(self, command):
        return {
            "Global": {"GestureIntents": [{
                "Name": "Imported", "Gesture": {
                    "GestureButton": 1, "Dirs": [6], "Modifier": 0},
                "Command": command,
            }]},
            "Apps": {},
        }

    def test_safe_hotkey_is_converted(self):
        legacy = self._legacy({
            "$type": "WGestures.Core.Commands.Impl.HotKeyCommand, WGestures.Core",
            "Modifiers": [164], "Keys": [37],
        })
        result = import_legacy_config(json.dumps(legacy))
        self.assertEqual(result["report"]["imported"], 1)
        self.assertEqual(result["config"]["actions"][0]["accelerator"],
                         "<Alt>Left")

    def test_type_metadata_and_script_are_never_executed(self):
        legacy = self._legacy({
            "$type": "WGestures.Core.Commands.Impl.ScriptCommand, WGestures.Core",
            "Code": "raise SystemExit('must not run')",
            "__reduce__": ["os.system", "touch /tmp/wgestures-pwned"],
        })
        result = import_legacy_config(json.dumps(legacy))
        self.assertEqual(result["report"]["imported"], 0)
        self.assertEqual(len(result["report"]["unsupported"]), 1)

    def test_malformed_json_and_windows_path_fail_closed(self):
        with self.assertRaises(ValueError):
            import_legacy_config('{"Global":')
        legacy = self._legacy({
            "$type": "WGestures.Core.Commands.Impl.OpenFileCommand, WGestures.Core",
            "FilePath": "C:\\Windows\\cmd.exe",
        })
        result = import_legacy_config(json.dumps(legacy))
        self.assertEqual(result["report"]["imported"], 0)

    def test_repository_default_wg2_has_stable_conversion_report(self):
        path = os.path.join(REPOSITORY_ROOT, "WGestures.App", "defaults",
                            "gestures.wg2")
        with open(path, "r", encoding="utf-8") as stream:
            result = import_legacy_config(stream.read())
        self.assertEqual(result["report"]["imported"], 4)
        self.assertEqual(result["report"]["unsupported"], [])
        self.assertEqual(result["report"]["unboundProfiles"], [])

    def test_portable_round_trip_preserves_all_native_gestures(self):
        source = create_default_config()
        text = export_portable_config(source)
        document = json.loads(text)
        self.assertEqual(document["portableFormat"], "crossgestures-portable")
        result = import_config(text)
        self.assertTrue(result["report"]["portable"])
        self.assertEqual(result["report"]["imported"], 4)
        self.assertEqual(result["report"]["unsupported"], [])
        self.assertEqual(result["config"], source)

    def test_portable_import_rejects_unknown_version(self):
        document = json.loads(export_portable_config(create_default_config()))
        document["schemaVersion"] = 999
        with self.assertRaises(ValueError):
            import_config(json.dumps(document))

    def test_generic_import_still_accepts_legacy_wg2(self):
        result = import_config(json.dumps(self._legacy({
            "$type": "WGestures.Core.Commands.Impl.HotKeyCommand, WGestures.Core",
            "Modifiers": [164], "Keys": [37],
        })))
        self.assertEqual(result["report"]["imported"], 1)


class EnvironmentTests(unittest.TestCase):
    def test_diagnostics_probe_the_gi_cairo_bridge(self):
        with mock.patch("wgestures.diagnostics._gi_cairo_available",
                        return_value=False):
            self.assertFalse(dependency_status()["giCairo"])
        with mock.patch("wgestures.diagnostics._gi_cairo_available",
                        return_value=True):
            self.assertTrue(dependency_status()["giCairo"])

    def test_gi_cairo_bridge_is_a_hard_package_dependency(self):
        path = os.path.join(REPOSITORY_ROOT, "debian", "control")
        with open(path, "r", encoding="utf-8") as stream:
            paragraphs = stream.read().split("\n\n")
        source = paragraphs[0]
        package = next(item for item in paragraphs[1:]
                       if item.startswith("Package: wgestures\n"))
        self.assertIn("python3-gi-cairo", source)
        self.assertIn("python3-gi-cairo", package)

    def test_user_can_enable_and_disable_session_autostart(self):
        directory = tempfile.mkdtemp(prefix="wgestures-autostart-test-")
        try:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}):
                self.assertTrue(session_autostart_enabled())
                disabled_path = set_session_autostart(False)
                self.assertFalse(session_autostart_enabled())
                with open(disabled_path, "r", encoding="utf-8") as stream:
                    self.assertIn("Hidden=true", stream.read())
                enabled_path = set_session_autostart(True)
                self.assertEqual(enabled_path, disabled_path)
                self.assertTrue(session_autostart_enabled())
                with open(enabled_path, "r", encoding="utf-8") as stream:
                    self.assertIn("Hidden=false", stream.read())
        finally:
            shutil.rmtree(directory)

    def test_packaged_session_autostart_is_desktop_independent(self):
        path = os.path.join(REPOSITORY_ROOT, "packaging",
                            "wgestures-autostart.desktop")
        with open(path, "r", encoding="utf-8") as stream:
            desktop = stream.read()
        self.assertIn("Exec=wgestures --daemon", desktop)
        self.assertIn("TryExec=wgestures", desktop)
        self.assertIn("X-GNOME-Autostart-enabled=true", desktop)
        self.assertNotIn("OnlyShowIn=", desktop)

    def test_backend_selection_is_explicit(self):
        self.assertEqual(select_backend("x11", "XFCE", None)[0], "x11")
        self.assertEqual(select_backend("wayland", "ubuntu:GNOME", 46)[0],
                         "gnome46-wayland")
        self.assertEqual(select_backend("wayland", "KDE", None)[0], "unsupported")
        self.assertEqual(select_backend("wayland", "GNOME", 47)[0], "unsupported")


if __name__ == "__main__":
    unittest.main(verbosity=2)

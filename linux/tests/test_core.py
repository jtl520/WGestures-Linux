from __future__ import unicode_literals

import json
import os
import shutil
import sys
import tempfile
import unittest


LINUX_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPOSITORY_ROOT = os.path.dirname(LINUX_ROOT)
sys.path.insert(0, LINUX_ROOT)

from wgestures.config import (create_default_config, find_matching_profile,
                              normalize_config, resolve_gesture)
from wgestures.diagnostics import select_backend
from wgestures.gesture import (GestureRecognizer, GestureSession,
                               direction_error_degrees, direction_from_delta,
                               gesture_key)
from wgestures.importer import import_legacy_config
from wgestures.storage import ConfigStore
from wgestures.shortcut import (copy_accelerator, display_accelerator,
                                is_terminal_identity, normalize_accelerator,
                                paste_accelerator)


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
    def test_defaults_only_bind_smart_copy_and_paste(self):
        config = create_default_config()
        self.assertEqual([item["type"] for item in config["actions"]],
                         ["CopyAction", "PasteAction"])
        self.assertEqual([
            (item["button"], item["directions"], item["actionId"])
            for item in config["globalProfile"]["gestures"]
        ], [
            ("right", ["up"], "smart-copy"),
            ("right", ["down"], "smart-paste"),
        ])

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
        self.assertEqual(result["report"]["imported"], 35)
        self.assertEqual(len(result["report"]["unsupported"]), 31)
        self.assertEqual(len(result["report"]["unboundProfiles"]), 3)


class EnvironmentTests(unittest.TestCase):
    def test_backend_selection_is_explicit(self):
        self.assertEqual(select_backend("x11", "XFCE", None)[0], "x11")
        self.assertEqual(select_backend("wayland", "ubuntu:GNOME", 46)[0],
                         "gnome46-wayland")
        self.assertEqual(select_backend("wayland", "KDE", None)[0], "unsupported")
        self.assertEqual(select_backend("wayland", "GNOME", 47)[0], "unsupported")


if __name__ == "__main__":
    unittest.main(verbosity=2)

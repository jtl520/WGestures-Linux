import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wgestures.config import create_default_config
from wgestures.settings import DEFAULTS
from wgestures.settings_service import SettingsService
from wgestures.storage import ConfigStore


class MemorySettings(object):
    def __init__(self): self.values = copy.deepcopy(DEFAULTS)
    def get(self, key): return copy.deepcopy(self.values[key])
    def set(self, key, value): self.values[key] = copy.deepcopy(value)
    def bump_revision(self): self.values["config-revision"] += 1


class SettingsServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(os.path.join(self.temp.name, "gestures.json"))
        self.settings = MemorySettings()
        self.service = SettingsService(self.store, self.settings)

    def tearDown(self): self.temp.cleanup()

    def change(self, method, **params):
        params["revision"] = self.service.snapshot()["revision"]
        return self.service.mutate(method, params)["snapshot"]

    def test_edit_forks_shared_action_and_preserves_other_gesture(self):
        config = create_default_config()
        config["globalProfile"]["gestures"][1]["actionId"] = config["globalProfile"]["gestures"][0]["actionId"]
        self.store.save(config)
        self.change("gestureSave", profileId="global", id="gesture-copy", name="Test", button="right", directions=["up"], action={"type": "ShortcutAction", "accelerator": "Ctrl+T"})
        gestures = self.service.snapshot()["profiles"][0]["gestures"]
        self.assertEqual("ShortcutAction", gestures[0]["action"]["type"])
        self.assertEqual("CopyAction", gestures[1]["action"]["type"])

    def test_duplicate_and_invalid_gestures_do_not_mutate_disk(self):
        self.service.snapshot()
        before = Path(self.store.path).read_bytes()
        with self.assertRaisesRegex(ValueError, "冲突"):
            self.change("gestureSave", profileId="global", name="Duplicate", button="right", directions=["up"], action={"type": "NoopAction"})
        with self.assertRaises(ValueError):
            self.change("gestureSave", profileId="global", name="Invalid", button="right", directions=["sideways"], action={"type": "NoopAction"})
        self.assertEqual(before, Path(self.store.path).read_bytes())

    def test_stale_window_rejected_without_losing_external_edit(self):
        old = self.service.snapshot()["revision"]
        config = self.store.load()["config"]
        config["globalProfile"]["gestures"][0]["name"] = "External edit"
        self.store.save(config)
        with self.assertRaisesRegex(ValueError, "其他窗口"):
            self.service.mutate("reset", {"revision": old})
        self.assertEqual("External edit", self.store.load()["config"]["globalProfile"]["gestures"][0]["name"])

    def test_profile_crud_conflicts_order_and_gesture_actions(self):
        params = dict(name="Editor", enabled=True, inheritGlobal=True, matchers=[{"type": "wmClass", "value": "Editor"}])
        snapshot = self.change("profileSave", **params)
        identity = snapshot["profiles"][1]["id"]
        with self.assertRaisesRegex(ValueError, "使用"):
            self.change("profileSave", **params)
        result = self.change("gestureSave", profileId=identity, name="Launch", button="x1", directions=["left"], action={"type": "LaunchAction", "target": "https://example.com"})
        gesture = result["profiles"][1]["gestures"][0]
        self.change("gestureDelete", profileId=identity, id=gesture["id"])
        self.assertFalse(any(a["type"] == "LaunchAction" for a in self.store.load()["config"]["actions"]))
        self.change("profileDelete", id=identity)
        self.assertEqual(1, len(self.service.snapshot()["profiles"]))

    def test_selected_export_does_not_include_other_profiles(self):
        snapshot = self.change("profileSave", name="Editor", enabled=True, inheritGlobal=True, matchers=[{"type": "wmClass", "value": "Editor"}])
        identity = snapshot["profiles"][1]["id"]
        self.change("gestureSave", profileId=identity, name="Noop", button="x1", directions=["left"], action={"type": "NoopAction"})
        document = json.loads(self.service.export(identity))
        self.assertEqual([], document["globalProfile"]["gestures"])
        self.assertEqual(1, len(document["profiles"][0]["gestures"]))
        self.assertEqual(1, len(document["actions"]))
        self.assertEqual(4, len(self.service.snapshot()["profiles"][0]["gestures"]))

    def test_import_preview_is_read_only_and_merge_is_deduplicated(self):
        original = self.service.snapshot()
        preview = self.service.prepare_import(self.service.export("global"))
        self.assertEqual(original, self.service.snapshot())
        snapshot = self.change("importApply", token=preview["token"])
        self.assertEqual(4, len(snapshot["profiles"][0]["gestures"]))
        with self.assertRaisesRegex(ValueError, "失效"):
            self.change("importApply", token=preview["token"])

    def test_validation_rejects_wrong_types_nonfinite_and_out_of_range(self):
        for key, value in (("path-width", float("nan")), ("start-threshold", 999), ("paused", "false"), ("direction-mode", 5), ("path-color", "red"), ("trigger-buttons", ["right", "right"])):
            with self.assertRaises(ValueError): self.change("setting", key=key, value=value)
        self.assertEqual(4.0, self.settings.get("path-width"))
        self.change("setting", key="path-width", value=6.5)
        self.assertEqual(6.5, self.settings.get("path-width"))

    def test_reorder_and_reset_preserve_general_settings(self):
        snapshot = self.change("gestureMove", profileId="global", id="gesture-paste", delta=-1)
        self.assertEqual("gesture-paste", snapshot["profiles"][0]["gestures"][0]["id"])
        self.change("setting", key="path-width", value=7)
        snapshot = self.change("reset")
        self.assertEqual("gesture-copy", snapshot["profiles"][0]["gestures"][0]["id"])
        self.assertEqual(7, snapshot["settings"]["path-width"])

    def test_recognition_uses_current_direction_mode(self):
        self.assertEqual(["up", "right"], self.service.recognize([[0, 100], [0, 70], [0, 40], [40, 40]])["directions"])
        with self.assertRaises(ValueError): self.service.recognize([[0, 0], [float("inf"), 1]])


if __name__ == "__main__": unittest.main()

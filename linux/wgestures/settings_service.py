"""Native adapter for the settings UI; independent of GTK and the web renderer."""
from __future__ import unicode_literals

import copy
import hashlib
import json
import math
import re
import uuid

from .autostart import set_session_autostart
from .config import ACTION_TYPES, WINDOW_OPERATIONS, create_default_config, normalize_config
from .gesture import DIRECTIONS, GestureRecognizer, gesture_key
from .portable import export_portable_config, import_config
from .settings import DEFAULTS, Settings
from .shortcut import normalize_accelerator, display_accelerator
from .storage import ConfigStore


MATCHERS = ("wmClass", "desktopId", "gtkApplicationId", "sandboxedAppId")
NUMBERS = {"direction-mode": (4, 8), "start-threshold": (2, 100),
           "segment-threshold": (2, 200), "path-width": (1, 24), "fade-duration": (0, 3000)}


class SettingsService(object):
    def __init__(self, store=None, settings=None):
        self.store = store or ConfigStore()
        self.settings = settings or Settings()
        self.pending_import = None

    def _config(self):
        return self.store.load()["config"]

    def _values(self):
        return dict((key, self.settings.get(key)) for key in DEFAULTS if key != "config-revision")

    def _revision(self, config):
        value = json.dumps([config, self._values()], sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _profiles(config):
        return [config["globalProfile"]] + config["profiles"]

    def _profile(self, config, identity):
        for profile in self._profiles(config):
            if profile["id"] == identity:
                return profile
        raise ValueError("应用配置已不存在，请重新选择。")

    @staticmethod
    def _gesture(profile, identity):
        for item in profile["gestures"]:
            if item["id"] == identity:
                return item
        raise ValueError("手势已不存在，请刷新后重试。")

    def snapshot(self):
        config = self._config()
        actions = dict((a["id"], a) for a in config["actions"])
        profiles = copy.deepcopy(self._profiles(config))
        for profile in profiles:
            for gesture in profile["gestures"]:
                gesture["action"] = copy.deepcopy(actions[gesture["actionId"]])
                if gesture["action"]["type"] == "ShortcutAction":
                    gesture["action"]["accelerator"] = display_accelerator(gesture["action"]["accelerator"])
                gesture["editable"] = gesture["button"] != "middle"
        return {"platform": "Ubuntu / Linux", "version": "2.2.0", "revision": self._revision(config),
                "settings": self._values(), "profiles": profiles,
                "capabilities": {"actions": list(ACTION_TYPES), "operations": list(WINDOW_OPERATIONS),
                                 "matchers": list(MATCHERS), "reorder": True, "legacy": True}}

    def _save(self, config):
        used = set(g["actionId"] for p in self._profiles(config) for g in p["gestures"])
        config["actions"] = [a for a in config["actions"] if a["id"] in used]
        normalized = normalize_config(config)
        if normalized["warnings"]:
            raise ValueError("\n".join(normalized["warnings"]))
        self.store.save(normalized["config"])
        self.settings.bump_revision()

    def _set(self, key, value):
        if key not in DEFAULTS or key == "config-revision":
            raise ValueError("未知设置项。")
        if isinstance(DEFAULTS[key], bool):
            if not isinstance(value, bool):
                raise ValueError("开关值无效。")
        elif key in NUMBERS:
            lower, upper = NUMBERS[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("请输入有效数字。")
            if not lower <= value <= upper or (key != "path-width" and value != int(value)):
                raise ValueError("数值超出允许范围。")
            if key == "direction-mode" and value not in (4, 8):
                raise ValueError("仅支持四方向或八方向。")
            value = float(value) if key == "path-width" else int(value)
        elif key in ("path-color", "invalid-path-color"):
            if not isinstance(value, str) or not re.match(r"^#[0-9a-fA-F]{6}$", value):
                raise ValueError("颜色必须为 #RRGGBB。")
        elif key == "trigger-buttons":
            if not isinstance(value, list) or len(set(value)) != len(value) or any(b not in ("right", "x1", "x2") for b in value):
                raise ValueError("触发按钮无效。")
        if ((key == "trigger-buttons" and not value and not self.settings.get("middle-panel-enabled")) or
                (key == "middle-panel-enabled" and not value and not self.settings.get("trigger-buttons"))):
            raise ValueError("请至少保留一个手势按钮或中键面板。")
        if key == "autostart-enabled":
            set_session_autostart(value)
        self.settings.set(key, value)
        if self.settings.get(key) != value:
            raise ValueError("设置未能写入，请检查 GSettings 权限。")

    def mutate(self, method, params):
        config = self._config()
        if params.get("revision") != self._revision(config):
            raise ValueError("配置已在其他窗口中修改，请刷新后重试。")
        if method == "setting":
            self._set(params.get("key"), params.get("value"))
            return {"snapshot": self.snapshot()}
        if method.startswith("gesture"):
            profile = self._profile(config, params.get("profileId"))
            if method == "gestureSave":
                self._save_gesture(config, profile, params)
            elif method == "gestureDelete":
                profile["gestures"].remove(self._gesture(profile, params.get("id")))
            elif method == "gestureMove":
                self._move(profile["gestures"], self._gesture(profile, params.get("id")), params.get("delta"))
            else:
                raise ValueError("未知操作。")
        elif method == "profileSave":
            self._save_profile(config, params)
        elif method in ("profileDelete", "profileToggle", "profileMove"):
            profile = self._profile(config, params.get("id"))
            if method == "profileToggle":
                if not isinstance(params.get("enabled"), bool):
                    raise ValueError("开关值无效。")
                profile["enabled"] = params["enabled"]
            elif profile["id"] == "global":
                raise ValueError("不能移除或移动全局配置。")
            elif method == "profileDelete":
                config["profiles"].remove(profile)
            else:
                self._move(config["profiles"], profile, params.get("delta"))
        elif method == "reset":
            config = create_default_config()
        elif method == "importApply":
            if not self.pending_import or params.get("token") != self.pending_import[0]:
                raise ValueError("导入预览已失效，请重新选择文件。")
            self._merge(config, self.pending_import[1])
        else:
            raise ValueError("未知操作。")
        self._save(config)
        if method == "importApply":
            self.pending_import = None
        return {"snapshot": self.snapshot()}

    @staticmethod
    def _move(items, item, delta):
        if delta not in (-1, 1):
            raise ValueError("移动方向无效。")
        index = items.index(item)
        target = index + delta
        if 0 <= target < len(items):
            items[index], items[target] = items[target], items[index]

    def _save_gesture(self, config, profile, params):
        name = str(params.get("name") or "").strip()
        if not name or len(name) > 120:
            raise ValueError("请填写 1–120 字的手势名称。")
        button = params.get("button")
        directions = params.get("directions")
        if button not in ("right", "x1", "x2"):
            raise ValueError("触发按钮无效。")
        if not isinstance(directions, list) or not 1 <= len(directions) <= 32 or any(d not in DIRECTIONS for d in directions):
            raise ValueError("手势方向无效。")
        existing = self._gesture(profile, params["id"]) if params.get("id") else None
        key = gesture_key(button, directions)
        for item in profile["gestures"]:
            if item is not existing and gesture_key(item["button"], item["directions"]) == key:
                raise ValueError("与手势“{0}”冲突。".format(item["name"]))
        action = copy.deepcopy(params.get("action"))
        if not isinstance(action, dict) or action.get("type") not in ACTION_TYPES:
            raise ValueError("动作类型无效。")
        if action["type"] == "ShortcutAction":
            action["accelerator"] = normalize_accelerator(action.get("accelerator", ""))
        elif action["type"] == "WindowAction" and action.get("operation") not in WINDOW_OPERATIONS:
            raise ValueError("窗口动作无效。")
        elif action["type"] in ("CommandAction", "LaunchAction"):
            field = "command" if action["type"] == "CommandAction" else "target"
            if not isinstance(action.get(field), str) or not action[field].strip():
                raise ValueError("动作内容不能为空。")
        # Always allocate an action for this gesture. Imported gestures may share an action.
        action.update({"id": "action-" + uuid.uuid4().hex, "name": name, "enabled": True})
        config["actions"].append(action)
        gesture = existing if existing is not None else {"id": "gesture-" + uuid.uuid4().hex, "enabled": True}
        gesture.update({"name": name, "button": button, "directions": directions, "actionId": action["id"]})
        if existing is None:
            profile["gestures"].append(gesture)

    def _save_profile(self, config, params):
        name = str(params.get("name") or "").strip()
        if not name or len(name) > 120:
            raise ValueError("请填写应用名称。")
        matchers = params.get("matchers")
        if not isinstance(matchers, list) or not matchers:
            raise ValueError("请填写至少一个应用匹配条件。")
        for matcher in matchers:
            if not isinstance(matcher, dict) or matcher.get("type") not in MATCHERS or not isinstance(matcher.get("value"), str) or not matcher["value"].strip():
                raise ValueError("应用匹配条件无效。")
            matcher["value"] = matcher["value"].strip()
        if len(set(m["type"] for m in matchers)) != len(matchers):
            raise ValueError("同一匹配类型只能填写一次。")
        profile = self._profile(config, params["id"]) if params.get("id") else None
        if profile and profile["id"] == "global":
            raise ValueError("全局配置不使用应用匹配条件。")
        for other in config["profiles"]:
            if other is profile:
                continue
            if any(a["type"] == b["type"] and a["value"].lower() == b["value"].lower() for a in matchers for b in other["matchers"]):
                raise ValueError("匹配条件已被“{0}”使用。".format(other["name"]))
        for key in ("enabled", "inheritGlobal"):
            if not isinstance(params.get(key), bool):
                raise ValueError("应用开关值无效。")
        if profile is None:
            profile = {"id": "profile-" + uuid.uuid4().hex, "gestures": []}
            config["profiles"].append(profile)
        profile.update({"name": name, "enabled": params["enabled"], "inheritGlobal": params["inheritGlobal"], "matchers": matchers})

    def export(self, identity):
        config = self._config()
        profile = self._profile(config, identity)
        if identity != "global":
            config["globalProfile"]["gestures"] = []
            config["profiles"] = [profile]
        else:
            config["profiles"] = []
        used = set(g["actionId"] for g in profile["gestures"])
        config["actions"] = [a for a in config["actions"] if a["id"] in used]
        return export_portable_config(config)

    def prepare_import(self, text):
        imported = import_config(text)
        token = uuid.uuid4().hex
        self.pending_import = (token, imported["config"])
        report = imported["report"]
        message = "可导入 {0} 个手势。".format(report["imported"])
        if report["unsupported"]:
            message += "\n\n跳过或修正：\n" + "\n".join(str(x) for x in report["unsupported"])
        if report["unboundProfiles"]:
            message += "\n\n以下应用需重新绑定：\n" + "\n".join(x["name"] for x in report["unboundProfiles"])
        return {"token": token, "message": message}

    def _merge(self, config, imported):
        actions = dict((a["id"], a) for a in imported["actions"])
        for source in self._profiles(imported):
            if source["id"] == "global":
                target = config["globalProfile"]
            else:
                target = next((p for p in config["profiles"] if p["matchers"] == source["matchers"] and p.get("legacyExecutablePath") == source.get("legacyExecutablePath") and (p["matchers"] or p.get("legacyExecutablePath"))), None)
                if target is None:
                    target = copy.deepcopy(source)
                    target.update({"id": "profile-" + uuid.uuid4().hex, "gestures": []})
                    config["profiles"].append(target)
            for gesture in source["gestures"]:
                action = copy.deepcopy(actions[gesture["actionId"]])
                action["id"] = "action-" + uuid.uuid4().hex
                config["actions"].append(action)
                new_gesture = copy.deepcopy(gesture)
                new_gesture.update({"id": "gesture-" + uuid.uuid4().hex, "actionId": action["id"]})
                key = gesture_key(gesture["button"], gesture["directions"])
                old = next((g for g in target["gestures"] if gesture_key(g["button"], g["directions"]) == key), None)
                if old is None:
                    target["gestures"].append(new_gesture)
                else:
                    target["gestures"][target["gestures"].index(old)] = new_gesture

    def recognize(self, points):
        if not isinstance(points, list) or not 2 <= len(points) <= 20000:
            raise ValueError("请绘制一段有效轨迹。")
        if any(not isinstance(p, list) or len(p) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in p) for p in points):
            raise ValueError("轨迹坐标无效。")
        recognizer = GestureRecognizer(int(self.settings.get("direction-mode")), 5, 12)
        recognizer.begin(*points[0])
        for point in points[1:]:
            recognizer.add_point(*point)
        result = recognizer.finish()
        return {"directions": result["directions"] if result["effective"] else []}

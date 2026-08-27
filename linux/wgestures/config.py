from __future__ import unicode_literals

import copy

from .gesture import BUTTONS, DIRECTIONS, gesture_key


SCHEMA_VERSION = 1
ACTION_TYPES = (
    "ShortcutAction", "CopyAction", "WindowAction", "CommandAction",
    "LaunchAction", "PauseAction", "NoopAction",
)
WINDOW_OPERATIONS = (
    "toggle-maximized", "minimize", "close",
    "toggle-fullscreen", "toggle-above",
)


def _action(action_id, name, action_type, **extra):
    value = {"id": action_id, "name": name, "type": action_type, "enabled": True}
    value.update(extra)
    return value


def _gesture(gesture_id, name, button, directions, action_id):
    return {
        "id": gesture_id, "name": name, "enabled": True,
        "button": button, "directions": directions, "actionId": action_id,
    }


def create_default_config():
    return {
        "schemaVersion": SCHEMA_VERSION,
        "actions": [
            _action("shortcut-back", "后退", "ShortcutAction", accelerator="<Alt>Left"),
            _action("shortcut-forward", "前进", "ShortcutAction", accelerator="<Alt>Right"),
            _action("shortcut-close", "关闭标签页", "ShortcutAction", accelerator="<Control>w"),
            _action("window-maximize", "最大化/恢复", "WindowAction", operation="toggle-maximized"),
            _action("window-minimize", "最小化", "WindowAction", operation="minimize"),
        ],
        "globalProfile": {
            "id": "global", "name": "全局", "enabled": True,
            "inheritGlobal": False, "matchers": [],
            "gestures": [
                _gesture("gesture-left", "后退", "right", ["left"], "shortcut-back"),
                _gesture("gesture-right", "前进", "right", ["right"], "shortcut-forward"),
                _gesture("gesture-down-right", "关闭标签页", "right", ["down", "right"], "shortcut-close"),
                _gesture("gesture-up", "最大化/恢复", "right", ["up"], "window-maximize"),
                _gesture("gesture-down", "最小化", "right", ["down"], "window-minimize"),
            ],
        },
        "profiles": [],
    }


def _normalize_action(raw, seen_ids, warnings):
    if not isinstance(raw, dict) or raw.get("type") not in ACTION_TYPES:
        warnings.append("已忽略未知动作类型")
        return None
    action_id = str(raw.get("id") or "").strip()
    if not action_id or action_id in seen_ids:
        warnings.append("已忽略无 ID 或重复的动作：{0}".format(action_id or "(空)"))
        return None
    value = {
        "id": action_id,
        "name": str(raw.get("name") or action_id),
        "type": raw["type"],
        "enabled": raw.get("enabled") is not False,
    }
    if raw["type"] == "ShortcutAction":
        value["accelerator"] = str(raw.get("accelerator") or "").strip()
        if not value["accelerator"]:
            warnings.append("快捷键动作 {0} 没有快捷键".format(action_id))
    elif raw["type"] == "WindowAction":
        operation = raw.get("operation")
        value["operation"] = operation if operation in WINDOW_OPERATIONS else "toggle-maximized"
    elif raw["type"] == "CommandAction":
        value["command"] = str(raw.get("command") or "")
    elif raw["type"] == "LaunchAction":
        value["target"] = str(raw.get("target") or "")
    seen_ids.add(action_id)
    return value


def _normalize_gesture(raw, action_ids, seen_keys, warnings):
    if not isinstance(raw, dict):
        return None
    button = raw.get("button") if raw.get("button") in BUTTONS else None
    directions = [item for item in raw.get("directions", [])
                  if item in DIRECTIONS] if isinstance(raw.get("directions"), list) else []
    action_id = str(raw.get("actionId") or "")
    if not button or not directions or action_id not in action_ids:
        warnings.append("已忽略无效手势：{0}".format(
            raw.get("name") or raw.get("id") or "(未命名)"))
        return None
    key = gesture_key(button, directions)
    if key in seen_keys:
        warnings.append("已忽略冲突手势：{0}".format(key))
        return None
    seen_keys.add(key)
    return {
        "id": str(raw.get("id") or "gesture-{0}".format(len(seen_keys))),
        "name": str(raw.get("name") or key),
        "enabled": raw.get("enabled") is not False,
        "button": button,
        "directions": directions,
        "actionId": action_id,
    }


def _normalize_profile(raw, action_ids, fallback_id, warnings):
    raw = raw if isinstance(raw, dict) else {}
    matchers = []
    for matcher in raw.get("matchers", []) if isinstance(raw.get("matchers"), list) else []:
        if isinstance(matcher, dict) and isinstance(matcher.get("type"), str) \
                and isinstance(matcher.get("value"), str):
            matchers.append({"type": matcher["type"], "value": matcher["value"]})
    seen_keys = set()
    gestures = []
    for item in raw.get("gestures", []) if isinstance(raw.get("gestures"), list) else []:
        gesture = _normalize_gesture(item, action_ids, seen_keys, warnings)
        if gesture:
            gestures.append(gesture)
    value = {
        "id": str(raw.get("id") or fallback_id),
        "name": str(raw.get("name") or fallback_id),
        "enabled": raw.get("enabled") is not False,
        "inheritGlobal": raw.get("inheritGlobal") is not False,
        "matchers": matchers,
        "gestures": gestures,
    }
    if raw.get("legacyExecutablePath"):
        value["legacyExecutablePath"] = str(raw["legacyExecutablePath"])
    return value


def normalize_config(raw):
    source = raw if isinstance(raw, dict) else create_default_config()
    if source.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("Unsupported configuration schema: {0}".format(
            source.get("schemaVersion")))
    warnings = []
    action_ids = set()
    actions = []
    for raw_action in source.get("actions", []) if isinstance(source.get("actions"), list) else []:
        action = _normalize_action(raw_action, action_ids, warnings)
        if action:
            actions.append(action)
    global_raw = copy.deepcopy(source.get("globalProfile") or {})
    global_raw.update({"id": "global", "inheritGlobal": False})
    global_profile = _normalize_profile(global_raw, action_ids, "global", warnings)
    profiles = []
    seen_profile_ids = set(["global"])
    for item in source.get("profiles", []) if isinstance(source.get("profiles"), list) else []:
        profile = _normalize_profile(item, action_ids,
                                     "profile-{0}".format(len(profiles) + 1), warnings)
        if profile["id"] in seen_profile_ids:
            warnings.append("已忽略重复应用配置：{0}".format(profile["id"]))
            continue
        seen_profile_ids.add(profile["id"])
        profiles.append(profile)
    return {
        "config": {
            "schemaVersion": SCHEMA_VERSION,
            "actions": actions,
            "globalProfile": global_profile,
            "profiles": profiles,
        },
        "warnings": warnings,
    }


def find_matching_profile(config, identity=None):
    identity = identity or {}
    ordered = (
        ("sandboxedAppId", identity.get("sandboxedAppId")),
        ("desktopId", identity.get("desktopId")),
        ("gtkApplicationId", identity.get("gtkApplicationId")),
        ("wmClass", identity.get("wmClass")),
    )
    for matcher_type, raw_value in ordered:
        if not raw_value:
            continue
        value = str(raw_value).lower()
        for profile in config.get("profiles", []):
            if any(matcher.get("type") == matcher_type and
                   str(matcher.get("value", "")).lower() == value
                   for matcher in profile.get("matchers", [])):
                return profile
    return None


def resolve_gesture(config, identity, button, directions):
    key = gesture_key(button, directions)
    profile = find_matching_profile(config, identity)
    if profile and not profile.get("enabled", True):
        return None
    candidates = []
    if profile:
        candidates.append(profile)
        if profile.get("inheritGlobal", True):
            candidates.append(config["globalProfile"])
    else:
        candidates.append(config["globalProfile"])
    actions = dict((item["id"], item) for item in config.get("actions", []))
    for candidate in candidates:
        if not candidate.get("enabled", True):
            continue
        for gesture in candidate.get("gestures", []):
            if gesture.get("enabled", True) and gesture_key(
                    gesture["button"], gesture["directions"]) == key:
                action = actions.get(gesture["actionId"])
                if action and action.get("enabled", True):
                    return {"gesture": gesture, "action": action, "profile": candidate}
    return None

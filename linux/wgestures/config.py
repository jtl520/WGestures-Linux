from __future__ import unicode_literals

import copy

from .gesture import (BUTTONS, DIRECTIONS, direction_error_degrees,
                      gesture_key, simplify_corner_transitions)
from .shortcut import normalize_accelerator


SCHEMA_VERSION = 1
ACTION_TYPES = (
    "ShortcutAction", "CopyAction", "PasteAction", "WindowAction", "CommandAction",
    "LaunchAction", "PauseAction", "NoopAction",
)
WINDOW_OPERATIONS = (
    "toggle-maximized", "minimize", "close",
    "toggle-fullscreen", "toggle-above",
)
SINGLE_DIRECTION_TOLERANCE = 35.0


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
            _action("smart-copy", "复制", "CopyAction"),
            _action("smart-paste", "粘贴", "PasteAction"),
            _action("press-enter", "Enter", "ShortcutAction",
                    accelerator="Return"),
            _action("window-toggle-above", "窗口置顶",
                    "WindowAction", operation="toggle-above"),
        ],
        "globalProfile": {
            "id": "global", "name": "全局", "enabled": True,
            "inheritGlobal": False, "matchers": [],
            "gestures": [
                _gesture("gesture-copy", "复制", "right", ["up"], "smart-copy"),
                _gesture("gesture-paste", "粘贴", "right", ["down"], "smart-paste"),
                _gesture("gesture-enter", "Enter", "right",
                         ["down", "right", "down"], "press-enter"),
                _gesture("gesture-toggle-above", "窗口置顶", "right",
                         ["up", "right", "up"], "window-toggle-above"),
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
    action_type = raw["type"]
    if action_type == "ShortcutAction":
        accelerator = str(raw.get("accelerator") or "").strip()
        try:
            normalized_accelerator = normalize_accelerator(accelerator)
        except ValueError:
            normalized_accelerator = accelerator
        if action_id == "smart-copy" and normalized_accelerator == "<Control>c":
            action_type = "CopyAction"
        elif action_id == "smart-paste" and normalized_accelerator == "<Control>v":
            action_type = "PasteAction"
    value = {
        "id": action_id,
        "name": str(raw.get("name") or action_id),
        "type": action_type,
        "enabled": raw.get("enabled") is not False,
    }
    if action_type == "ShortcutAction":
        value["accelerator"] = str(raw.get("accelerator") or "").strip()
        if not value["accelerator"]:
            warnings.append("快捷键动作 {0} 没有快捷键".format(action_id))
    elif action_type == "WindowAction":
        operation = raw.get("operation")
        value["operation"] = operation if operation in WINDOW_OPERATIONS else "toggle-maximized"
    elif action_type == "CommandAction":
        value["command"] = str(raw.get("command") or "")
    elif action_type == "LaunchAction":
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


def resolve_gesture(config, identity, button, directions, movement=None):
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

    simplified_directions = simplify_corner_transitions(directions)
    if simplified_directions != list(directions):
        simplified_key = gesture_key(button, simplified_directions)
        for candidate in candidates:
            if not candidate.get("enabled", True):
                continue
            for gesture in candidate.get("gestures", []):
                if gesture.get("enabled", True) and gesture_key(
                        gesture["button"], gesture["directions"]) == simplified_key:
                    action = actions.get(gesture["actionId"])
                    if action and action.get("enabled", True):
                        return {"gesture": gesture, "action": action,
                                "profile": candidate}

    movement = movement if isinstance(movement, dict) else {}
    origin = movement.get("origin")
    end = movement.get("end")
    try:
        dx, dy = end[0] - origin[0], end[1] - origin[1]
    except (IndexError, KeyError, TypeError):
        return None
    for candidate in candidates:
        if not candidate.get("enabled", True):
            continue
        best = None
        for gesture in candidate.get("gestures", []):
            gesture_directions = gesture.get("directions", [])
            if (not gesture.get("enabled", True) or gesture.get("button") != button or
                    len(gesture_directions) != 1):
                continue
            error = direction_error_degrees(gesture_directions[0], dx, dy)
            action = actions.get(gesture.get("actionId"))
            if (error is not None and error <= SINGLE_DIRECTION_TOLERANCE and
                    action and action.get("enabled", True) and
                    (best is None or error < best[0])):
                best = (error, gesture, action)
        if best is not None:
            return {"gesture": best[1], "action": best[2], "profile": candidate}
    return None

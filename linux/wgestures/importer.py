from __future__ import unicode_literals

import json

from .config import create_default_config, normalize_config


LEGACY_DIRECTIONS = (
    "up", "up-right", "right", "down-right",
    "down", "down-left", "left", "up-left",
)
LEGACY_BUTTONS = {1: "right", 2: "middle", 4: "x1", 8: "x2"}
MODIFIER_CODES = {
    16: "<Shift>", 160: "<Shift>", 161: "<Shift>",
    17: "<Control>", 162: "<Control>", 163: "<Control>",
    18: "<Alt>", 164: "<Alt>", 165: "<Alt>",
    91: "<Super>", 92: "<Super>",
}
SPECIAL_KEYS = {
    8: "BackSpace", 9: "Tab", 13: "Return", 27: "Escape", 32: "space",
    33: "Page_Up", 34: "Page_Down", 35: "End", 36: "Home",
    37: "Left", 38: "Up", 39: "Right", 40: "Down", 45: "Insert",
    46: "Delete", 173: "AudioMute", 174: "AudioLowerVolume",
    175: "AudioRaiseVolume",
}


def _type_name(command):
    if not isinstance(command, dict):
        return ""
    value = str(command.get("$type") or "").split(",", 1)[0]
    return value.rsplit(".", 1)[-1]


def _legacy_key_name(code):
    try:
        numeric = int(code)
    except (TypeError, ValueError):
        return None
    if numeric in SPECIAL_KEYS:
        return SPECIAL_KEYS[numeric]
    if 48 <= numeric <= 57:
        return chr(numeric)
    if 65 <= numeric <= 90:
        return chr(numeric).lower()
    if 112 <= numeric <= 123:
        return "F{0}".format(numeric - 111)
    return None


def _make_id(prefix, state):
    state["next_id"] += 1
    return "{0}-{1}".format(prefix, state["next_id"])


def _unsupported(report, name, reason):
    report["unsupported"].append("{0}: {1}".format(name, reason))


def _convert_action(command, name, state, report):
    command = command if isinstance(command, dict) else {}
    command_type = _type_name(command)
    base = {
        "id": _make_id("imported-action", state),
        "name": name or command_type or "导入动作",
        "enabled": True,
    }
    if command_type == "HotKeyCommand":
        modifiers = []
        for code in command.get("Modifiers", []) if isinstance(command.get("Modifiers"), list) else []:
            value = MODIFIER_CODES.get(_safe_int(code))
            if value and value not in modifiers:
                modifiers.append(value)
        keys = [_legacy_key_name(value) for value in
                command.get("Keys", []) if isinstance(command.get("Keys"), list)]
        keys = [value for value in keys if value]
        if len(keys) != 1:
            _unsupported(report, name, "快捷键包含 {0} 个可识别主键".format(len(keys)))
            return None
        base.update({"type": "ShortcutAction", "accelerator": "".join(modifiers) + keys[0]})
        return base
    if command_type == "WindowControlCommand":
        operations = {0: "toggle-maximized", 1: "minimize", 2: "close", 3: "toggle-above"}
        operation = operations.get(_safe_int(command.get("ChangeWindowStateTo")))
        if not operation:
            _unsupported(report, name, "不支持的窗口停靠动作")
            return None
        base.update({"type": "WindowAction", "operation": operation})
        return base
    if command_type == "GotoUrlCommand":
        base.update({"type": "LaunchAction", "target": str(command.get("Url") or "")})
        return base
    if command_type == "OpenFileCommand":
        target = str(command.get("FilePath") or "")
        if (len(target) > 2 and target[1:3] == ":\\") or target.startswith("\\\\"):
            _unsupported(report, name, "Windows 文件路径需要手工替换")
            return None
        base.update({"type": "LaunchAction", "target": target})
        return base
    if command_type == "PauseWGesturesCommand":
        base["type"] = "PauseAction"
        return base
    if command_type == "DoNothingCommand":
        base["type"] = "NoopAction"
        return base
    if command_type == "ChangeAudioVolumeCommand":
        base.update({"type": "ShortcutAction", "accelerator": "AudioMute"})
        return base
    if command_type == "CmdCommand":
        _unsupported(report, name, "Windows 命令行不会自动启用")
        return None
    if command_type in ("ScriptCommand", "WebSearchCommand", "TaskSwitcherCommand", "SendTextCommand"):
        _unsupported(report, name, "{0} 不在首版支持范围".format(command_type))
        return None
    _unsupported(report, name, "未知动作 {0}".format(command_type or "(空)"))
    return None


def _safe_int(value, default=-1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _convert_intent(intent, profile, config, state, report):
    if not isinstance(intent, dict):
        return
    gesture = intent.get("Gesture")
    name = str(intent.get("Name") or "导入手势")
    if not isinstance(gesture, dict) or _safe_int(gesture.get("Modifier"), 0) != 0:
        _unsupported(report, name, "修饰手势不受支持")
        return
    button = LEGACY_BUTTONS.get(_safe_int(gesture.get("GestureButton")))
    directions = []
    if isinstance(gesture.get("Dirs"), list):
        for raw_direction in gesture["Dirs"]:
            index = _safe_int(raw_direction)
            if 0 <= index < len(LEGACY_DIRECTIONS):
                directions.append(LEGACY_DIRECTIONS[index])
    if not button or not directions:
        _unsupported(report, name, "触发按钮或方向无效")
        return
    action = _convert_action(intent.get("Command"), name, state, report)
    if not action:
        return
    config["actions"].append(action)
    profile["gestures"].append({
        "id": _make_id("imported-gesture", state),
        "name": name, "enabled": True, "button": button,
        "directions": directions, "actionId": action["id"],
    })
    report["imported"] += 1


def import_legacy_config(text):
    try:
        legacy = json.loads(text)
    except (TypeError, ValueError) as error:
        raise ValueError("旧配置不是有效 JSON：{0}".format(error))
    if not isinstance(legacy, dict) or not isinstance(legacy.get("Global"), dict):
        raise ValueError("旧配置缺少 Global 手势数据")
    config = create_default_config()
    config["actions"] = []
    config["globalProfile"]["gestures"] = []
    state = {"next_id": 0}
    report = {"imported": 0, "unsupported": [], "unboundProfiles": []}
    intents = legacy["Global"].get("GestureIntents", [])
    for intent in intents if isinstance(intents, list) else []:
        _convert_intent(intent, config["globalProfile"], config, state, report)
    apps = legacy.get("Apps")
    app_values = list(apps.values()) if isinstance(apps, dict) else []
    for app in app_values:
        if not isinstance(app, dict):
            continue
        profile = {
            "id": _make_id("unbound-profile", state),
            "name": str(app.get("Name") or app.get("ExecutablePath") or "未绑定应用"),
            "enabled": app.get("IsGesturingEnabled") is not False,
            "inheritGlobal": app.get("InheritGlobalGestures") is not False,
            "matchers": [],
            "legacyExecutablePath": str(app.get("ExecutablePath") or ""),
            "gestures": [],
        }
        intents = app.get("GestureIntents", [])
        for intent in intents if isinstance(intents, list) else []:
            _convert_intent(intent, profile, config, state, report)
        if profile["gestures"]:
            config["profiles"].append(profile)
            report["unboundProfiles"].append({
                "id": profile["id"], "name": profile["name"],
                "path": profile["legacyExecutablePath"],
            })
    normalized = normalize_config(config)
    report["warnings"] = normalized["warnings"]
    return {"config": normalized["config"], "report": report}


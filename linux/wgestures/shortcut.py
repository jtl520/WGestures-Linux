from __future__ import unicode_literals

import re


MODIFIER_ALIASES = {
    "control": "Control", "ctrl": "Control", "primary": "Control",
    "alt": "Alt", "shift": "Shift", "super": "Super",
    "win": "Super", "windows": "Super", "meta": "Super",
}
MODIFIER_LABELS = {
    "Control": "Ctrl", "Alt": "Alt", "Shift": "Shift", "Super": "Super",
}
KEY_ALIASES = {
    "enter": "Return", "return": "Return", "esc": "Escape",
    "escape": "Escape", "space": "space", "backspace": "BackSpace",
    "delete": "Delete", "insert": "Insert", "left": "Left",
    "right": "Right", "up": "Up", "down": "Down", "home": "Home",
    "end": "End", "tab": "Tab", "pageup": "Page_Up",
    "pagedown": "Page_Down", "audiomute": "AudioMute",
    "audiolowervolume": "AudioLowerVolume",
    "audioraisevolume": "AudioRaiseVolume",
}
KEY_LABELS = {
    "return": "Enter", "escape": "Esc", "space": "Space",
    "backspace": "Backspace", "page_up": "PageUp", "page_down": "PageDown",
}
TERMINAL_TOKENS = frozenset((
    "terminal", "console", "ptyxis", "konsole", "xterm", "urxvt",
    "tilix", "terminator", "alacritty", "kitty", "wezterm", "foot",
    "ghostty", "guake", "yakuake", "qterminal", "lxterminal",
))


def _modifier(value):
    result = MODIFIER_ALIASES.get(value.strip().lower())
    if not result:
        raise ValueError("不支持的修饰键：{0}".format(value))
    return result


def _key(value):
    key = value.strip()
    if not key:
        raise ValueError("快捷键缺少主键")
    if "<" in key or ">" in key:
        raise ValueError("快捷键格式无效：{0}".format(value))
    compact = re.sub(r"[\s_-]+", "", key).lower()
    if compact in KEY_ALIASES:
        return KEY_ALIASES[compact]
    if re.match(r"^[a-z]$", key, re.I):
        return key.lower()
    if re.match(r"^f\d{1,2}$", key, re.I):
        return key.upper()
    return key


def _parts(accelerator):
    text = str(accelerator or "").strip()
    if not text:
        raise ValueError("快捷键不能为空")

    modifiers = []
    if "<" in text or ">" in text:
        remaining = text
        while remaining.startswith("<"):
            match = re.match(r"^<([^<>]+)>", remaining)
            if not match:
                raise ValueError("快捷键格式无效：{0}".format(text))
            modifiers.append(_modifier(match.group(1)))
            remaining = remaining[match.end():].lstrip()
        if "<" in remaining or ">" in remaining:
            raise ValueError("快捷键格式无效：{0}".format(text))
        key = remaining
    else:
        if "+" in text:
            values = [item.strip() for item in text.split("+")]
            if any(not item for item in values):
                raise ValueError("快捷键格式无效：{0}".format(text))
        else:
            values = text.split()
        if not values:
            raise ValueError("快捷键不能为空")
        modifiers.extend(_modifier(item) for item in values[:-1])
        key = values[-1]

    unique = []
    for modifier in modifiers:
        if modifier not in unique:
            unique.append(modifier)
    return unique, _key(key)


def normalize_accelerator(accelerator):
    """Return the stable GTK-style representation stored in configuration."""
    modifiers, key = _parts(accelerator)
    return "".join("<{0}>".format(item) for item in modifiers) + key


def display_accelerator(accelerator):
    """Return a friendly representation such as Ctrl+Shift+T for the UI."""
    modifiers, key = _parts(accelerator)
    if len(key) == 1 and re.match(r"^[a-z]$", key, re.I):
        key_label = key.upper()
    else:
        key_label = KEY_LABELS.get(key.lower(), key)
    return "+".join([MODIFIER_LABELS[item] for item in modifiers] + [key_label])


def is_terminal_identity(identity):
    """Identify common Linux terminals from the documented application fields."""
    identity = identity if isinstance(identity, dict) else {}
    for field in ("sandboxedAppId", "desktopId", "gtkApplicationId", "wmClass"):
        value = str(identity.get(field) or "").lower()
        tokens = set(item for item in re.split(r"[^a-z0-9]+", value) if item)
        if tokens.intersection(TERMINAL_TOKENS):
            return True
    return False


def copy_accelerator(identity):
    """Return the desktop copy shortcut appropriate for the target window."""
    return "<Control><Shift>c" if is_terminal_identity(identity) else "<Control>c"


def paste_accelerator(identity):
    """Return the desktop paste shortcut appropriate for the target window."""
    return "<Control><Shift>v" if is_terminal_identity(identity) else "<Control>v"


def action_display_name(action, gesture=None):
    """Return the short name shown after an action succeeds."""
    action = action if isinstance(action, dict) else {}
    gesture = gesture if isinstance(gesture, dict) else {}
    return str(gesture.get("name") or action.get("name") or "")

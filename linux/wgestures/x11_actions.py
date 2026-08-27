from __future__ import unicode_literals

import os
import re

from Xlib import X, XK, Xatom, Xutil
from Xlib.ext import xtest
from Xlib.protocol import event as xevent

XK.load_keysym_group("xf86")


MODIFIER_KEYS = {
    "control": "Control_L", "ctrl": "Control_L", "primary": "Control_L",
    "alt": "Alt_L", "shift": "Shift_L", "super": "Super_L",
}
KEY_ALIASES = {
    "enter": "Return", "return": "Return", "esc": "Escape",
    "escape": "Escape", "space": "space", "backspace": "BackSpace",
    "delete": "Delete", "insert": "Insert", "left": "Left",
    "right": "Right", "up": "Up", "down": "Down", "home": "Home",
    "end": "End", "tab": "Tab", "page_up": "Page_Up",
    "pageup": "Page_Up", "page_down": "Page_Down", "pagedown": "Page_Down",
    "audiomute": "XF86_AudioMute", "audiolowervolume": "XF86_AudioLowerVolume",
    "audioraisevolume": "XF86_AudioRaiseVolume",
}


def parse_accelerator(accelerator):
    text = str(accelerator or "").strip()
    modifiers = []
    for match in re.findall(r"<([^>]+)>", text):
        key = MODIFIER_KEYS.get(match.lower())
        if not key:
            raise ValueError("不支持的修饰键：{0}".format(match))
        if key not in modifiers:
            modifiers.append(key)
    key_name = re.sub(r"<[^>]+>", "", text).strip()
    if not key_name:
        raise ValueError("快捷键缺少主键")
    key_name = KEY_ALIASES.get(key_name.lower(), key_name)
    return modifiers, key_name


class X11ActionExecutor(object):
    def __init__(self, connection, settings):
        self.display = connection
        self.settings = settings
        self.root = connection.screen().root

    def execute(self, action, context):
        action_type = action.get("type")
        if action_type == "ShortcutAction":
            self._shortcut(action.get("accelerator"))
        elif action_type == "WindowAction":
            self._window(action.get("operation"), context.get("window"))
        elif action_type == "CommandAction":
            self._command(action.get("command"))
        elif action_type == "LaunchAction":
            self._launch(action.get("target"))
        elif action_type == "PauseAction":
            self.settings.set("paused", True)
        elif action_type != "NoopAction":
            raise ValueError("不支持的动作：{0}".format(action_type))

    def _keysym(self, name):
        keysym = XK.string_to_keysym(name)
        if not keysym and len(name) == 1:
            keysym = ord(name)
        if not keysym:
            raise ValueError("不支持的按键名称：{0}".format(name))
        return keysym

    def _shortcut(self, accelerator):
        modifiers, key_name = parse_accelerator(accelerator)
        keycodes = []
        for name in modifiers + [key_name]:
            keycode = self.display.keysym_to_keycode(self._keysym(name))
            if not keycode:
                raise ValueError("当前键盘布局不包含按键：{0}".format(name))
            keycodes.append(keycode)
        for keycode in keycodes:
            xtest.fake_input(self.display, X.KeyPress, keycode)
        for keycode in reversed(keycodes):
            xtest.fake_input(self.display, X.KeyRelease, keycode)
        self.display.sync()

    def _atom(self, name):
        return self.display.intern_atom(name)

    def _window_states(self, window):
        prop = window.get_full_property(self._atom("_NET_WM_STATE"), Xatom.ATOM)
        return set(prop.value.tolist() if prop is not None and hasattr(prop.value, "tolist")
                   else (prop.value if prop is not None else []))

    def _client_message(self, window, message, data, mask=None):
        event = xevent.ClientMessage(
            window=window, client_type=self._atom(message),
            data=(32, list(data) + [0] * (5 - len(data))))
        self.root.send_event(
            event,
            event_mask=mask or (X.SubstructureRedirectMask | X.SubstructureNotifyMask))
        self.display.flush()

    def _toggle_states(self, window, atoms):
        states = self._window_states(window)
        enabled = all(atom in states for atom in atoms)
        data = [0 if enabled else 1, atoms[0], atoms[1] if len(atoms) > 1 else 0, 2, 0]
        self._client_message(window, "_NET_WM_STATE", data)

    def _window(self, operation, window):
        if window is None:
            raise ValueError("没有可控制的目标窗口")
        if operation == "toggle-maximized":
            self._toggle_states(window, [
                self._atom("_NET_WM_STATE_MAXIMIZED_HORZ"),
                self._atom("_NET_WM_STATE_MAXIMIZED_VERT")])
        elif operation == "minimize":
            event = xevent.ClientMessage(
                window=window, client_type=self._atom("WM_CHANGE_STATE"),
                data=(32, [Xutil.IconicState, 0, 0, 0, 0]))
            self.root.send_event(
                event,
                event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            self.display.flush()
        elif operation == "close":
            self._client_message(window, "_NET_CLOSE_WINDOW", [X.CurrentTime, 2, 0, 0, 0])
        elif operation == "toggle-fullscreen":
            self._toggle_states(window, [self._atom("_NET_WM_STATE_FULLSCREEN")])
        elif operation == "toggle-above":
            self._toggle_states(window, [self._atom("_NET_WM_STATE_ABOVE")])
        else:
            raise ValueError("未知窗口动作：{0}".format(operation))

    @staticmethod
    def _command(command):
        value = str(command or "")
        if not value.strip():
            raise ValueError("命令内容为空")
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
        process = Gio.Subprocess.new(
            ["/bin/sh", "-lc", value],
            Gio.SubprocessFlags.STDOUT_SILENCE |
            Gio.SubprocessFlags.STDERR_SILENCE)
        process.wait_async(None, lambda child, result: child.wait_finish(result))

    @staticmethod
    def _launch(target):
        value = str(target or "").strip()
        if not value:
            raise ValueError("打开目标为空")
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
        if re.match(r"^[a-z][a-z0-9+.-]*:", value, re.I):
            Gio.AppInfo.launch_default_for_uri(value, None)
            return
        if os.path.isabs(value) or os.path.sep in value:
            Gio.AppInfo.launch_default_for_uri(
                Gio.File.new_for_path(value).get_uri(), None)
            return
        desktop_ids = set([value])
        if not value.endswith(".desktop"):
            desktop_ids.add(value + ".desktop")
        for application in Gio.AppInfo.get_all():
            if application.get_id() in desktop_ids:
                application.launch([], None)
                return
        application = Gio.AppInfo.create_from_commandline(
            value, None, Gio.AppInfoCreateFlags.NONE)
        application.launch([], None)

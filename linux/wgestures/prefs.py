from __future__ import unicode_literals

import copy
import uuid

import gi
gi.require_foreign("cairo")
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from .autostart import session_autostart_enabled, set_session_autostart
from .config import ACTION_TYPES, WINDOW_OPERATIONS, create_default_config
from .gesture import BUTTONS, DIRECTIONS, GestureRecognizer, gesture_key
from .portable import export_portable_config, import_config
from .settings import Settings
from .shortcut import display_accelerator, normalize_accelerator
from .storage import ConfigStore


BUTTON_LABELS = {"right": "右键", "middle": "中键", "x1": "X1", "x2": "X2"}
ACTION_LABELS = {
    "ShortcutAction": "快捷键", "CopyAction": "智能复制（自动适配终端）",
    "PasteAction": "智能粘贴（自动适配终端）",
    "WindowAction": "窗口控制",
    "CommandAction": "Shell 命令", "LaunchAction": "打开文件、应用或网址",
    "PauseAction": "暂停", "NoopAction": "空操作",
}
OPERATION_LABELS = {
    "toggle-maximized": "最大化/恢复", "minimize": "最小化", "close": "关闭",
    "toggle-fullscreen": "全屏/恢复", "toggle-above": "置顶/取消置顶",
}
MATCHER_LABELS = {
    "sandboxedAppId": "Snap/Flatpak ID", "desktopId": "Desktop ID",
    "gtkApplicationId": "GTK Application ID", "wmClass": "WM Class",
}


def _combo(values, active=0):
    combo = Gtk.ComboBoxText()
    for value, label in values:
        combo.append(value, label)
    combo.set_active(max(0, active))
    return combo


def _row(grid, row, title, widget):
    label = Gtk.Label(label=title)
    label.set_xalign(0)
    label.set_valign(Gtk.Align.CENTER)
    widget.set_valign(Gtk.Align.CENTER)
    grid.attach(label, 0, row, 1, 1)
    grid.attach(widget, 1, row, 1, 1)


def _compact_control(widget):
    """Keep controls such as switches at their theme-provided natural size."""
    widget.set_halign(Gtk.Align.START)
    return widget


def _message(parent, text, message_type=Gtk.MessageType.INFO):
    dialog = Gtk.MessageDialog(
        transient_for=parent, modal=True, message_type=message_type,
        buttons=Gtk.ButtonsType.OK, text=text)
    dialog.run()
    dialog.destroy()


class GestureDialog(Gtk.Dialog):
    def __init__(self, parent, profile, config, gesture=None, settings=None):
        Gtk.Dialog.__init__(
            self, title="编辑手势" if gesture else "添加手势",
            transient_for=parent, modal=True)
        self.set_default_size(520, 560)
        self.add_button("取消", Gtk.ResponseType.CANCEL)
        self.add_button("保存", Gtk.ResponseType.OK)
        self.profile = profile
        self.config = config
        self.gesture = gesture
        self.settings = settings
        self.action = None
        if gesture:
            self.action = next((item for item in config["actions"]
                                if item["id"] == gesture["actionId"]), None)
        self.recognizer = GestureRecognizer(
            int(settings.get("direction-mode")), 5, 12)
        self.points = []
        self._build()

    def _build(self):
        grid = Gtk.Grid(column_spacing=12, row_spacing=12,
                        margin=18, column_homogeneous=False)
        self.get_content_area().pack_start(grid, True, True, 0)
        self.name_entry = Gtk.Entry(text=self.gesture.get("name", "") if self.gesture else "")
        _row(grid, 0, "名称", self.name_entry)
        self.button_combo = _combo([(item, BUTTON_LABELS[item]) for item in BUTTONS],
                                   BUTTONS.index(self.gesture["button"] if self.gesture else "right"))
        _row(grid, 1, "触发按钮", self.button_combo)
        self.direction_entry = Gtk.Entry()
        self.direction_entry.set_placeholder_text("left,up,right")
        self.direction_entry.set_text(
            ",".join(self.gesture.get("directions", [])) if self.gesture else "")
        _row(grid, 2, "方向（逗号分隔）", self.direction_entry)

        self.drawing = Gtk.DrawingArea()
        self.drawing.set_size_request(360, 150)
        self.drawing.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK)
        self.drawing.connect("draw", self._draw)
        self.drawing.connect("button-press-event", self._draw_begin)
        self.drawing.connect("motion-notify-event", self._draw_motion)
        self.drawing.connect("button-release-event", self._draw_end)
        frame = Gtk.Frame(label="用左键绘制手势")
        frame.add(self.drawing)
        grid.attach(frame, 0, 3, 2, 1)

        action_type = self.action.get("type") if self.action else "ShortcutAction"
        self.action_combo = _combo([(item, ACTION_LABELS[item]) for item in ACTION_TYPES],
                                   ACTION_TYPES.index(action_type))
        self.action_combo.connect("changed", self._action_type_changed)
        _row(grid, 4, "动作类型", self.action_combo)
        self.action_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        grid.attach(self.action_box, 0, 5, 2, 1)
        self._rebuild_action_input()
        self.show_all()

    def _draw(self, _widget, context):
        if len(self.points) < 2:
            return False
        context.set_source_rgba(0.15, 0.68, 0.38, 1)
        context.set_line_width(4)
        context.move_to(*self.points[0])
        for point in self.points[1:]:
            context.line_to(*point)
        context.stroke()
        return False

    def _draw_begin(self, _widget, event):
        if event.button != 1:
            return False
        self.points = [(event.x, event.y)]
        self.recognizer.begin(event.x, event.y)
        self.drawing.queue_draw()
        return True

    def _draw_motion(self, _widget, event):
        if not (event.state & Gdk.ModifierType.BUTTON1_MASK):
            return False
        self.points.append((event.x, event.y))
        self.recognizer.add_point(event.x, event.y)
        self.drawing.queue_draw()
        return True

    def _draw_end(self, _widget, event):
        if event.button != 1:
            return False
        result = self.recognizer.finish()
        if result["effective"]:
            self.direction_entry.set_text(",".join(result["directions"]))
        return True

    def _action_type_changed(self, _combo):
        self._rebuild_action_input()
        self.action_box.show_all()

    def _rebuild_action_input(self):
        for child in self.action_box.get_children():
            self.action_box.remove(child)
        action_type = self.action_combo.get_active_id()
        self.action_value = None
        if action_type == "WindowAction":
            current = self.action.get("operation") if self.action else "toggle-maximized"
            values = [(item, OPERATION_LABELS[item]) for item in WINDOW_OPERATIONS]
            self.action_value = _combo(values, WINDOW_OPERATIONS.index(current)
                                       if current in WINDOW_OPERATIONS else 0)
            self.action_box.pack_start(self.action_value, False, False, 0)
        elif action_type in ("ShortcutAction", "CommandAction", "LaunchAction"):
            keys = {"ShortcutAction": "accelerator", "CommandAction": "command",
                    "LaunchAction": "target"}
            placeholders = {"ShortcutAction": "Ctrl+Shift+T",
                            "CommandAction": "notify-send 'Hello'",
                            "LaunchAction": "网址、文件路径或 org.example.App.desktop"}
            self.action_value = Gtk.Entry()
            self.action_value.set_placeholder_text(placeholders[action_type])
            current = self.action.get(keys[action_type], "") if self.action else ""
            if action_type == "ShortcutAction" and current:
                current = display_accelerator(current)
            self.action_value.set_text(current)
            self.action_box.pack_start(self.action_value, False, False, 0)
            if action_type == "CommandAction":
                warning = Gtk.Label(
                    label="命令将通过 /bin/sh -lc 以当前用户权限执行，请仅使用可信内容。")
                warning.set_xalign(0)
                warning.set_line_wrap(True)
                self.action_box.pack_start(warning, False, False, 0)
        else:
            label = Gtk.Label(label="此动作没有额外参数。")
            label.set_xalign(0)
            self.action_box.pack_start(label, False, False, 0)

    def result(self):
        directions = [item.strip().lower() for item in
                      self.direction_entry.get_text().split(",") if item.strip()]
        if not directions or any(item not in DIRECTIONS for item in directions):
            raise ValueError("方向无效")
        button = self.button_combo.get_active_id()
        key = gesture_key(button, directions)
        for item in self.profile["gestures"]:
            if item is not self.gesture and gesture_key(item["button"], item["directions"]) == key:
                raise ValueError("与手势“{0}”冲突".format(item["name"]))
        action = copy.deepcopy(self.action) if self.action else {
            "id": "action-{0}".format(uuid.uuid4()), "enabled": True}
        action_type = self.action_combo.get_active_id()
        action.update({"name": self.name_entry.get_text().strip() or "未命名动作",
                       "type": action_type})
        for field in ("accelerator", "operation", "command", "target"):
            action.pop(field, None)
        if action_type == "WindowAction":
            action["operation"] = self.action_value.get_active_id()
        elif action_type == "ShortcutAction":
            action["accelerator"] = normalize_accelerator(
                self.action_value.get_text())
        elif action_type == "CommandAction":
            action["command"] = self.action_value.get_text()
        elif action_type == "LaunchAction":
            action["target"] = self.action_value.get_text().strip()
        gesture = copy.deepcopy(self.gesture) if self.gesture else {
            "id": "gesture-{0}".format(uuid.uuid4()), "enabled": True}
        gesture.update({
            "name": self.name_entry.get_text().strip() or "未命名手势",
            "button": button, "directions": directions, "actionId": action["id"],
        })
        return gesture, action


class PreferencesWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        Gtk.ApplicationWindow.__init__(
            self, application=application, title="CrossGestures 设置")
        self.set_default_size(760, 680)
        self.settings = Settings()
        self._updating_autostart = False
        self.store = ConfigStore()
        loaded = self.store.load()
        self.config = loaded["config"]
        self.profile_index = 0
        self.connect("delete-event", self._delete_event)
        self.connect("window-state-event", self._window_state_event)
        self._build()
        for warning in loaded["warnings"]:
            _message(self, warning, Gtk.MessageType.WARNING)

    def _build(self):
        notebook = Gtk.Notebook()
        self.add(notebook)
        notebook.append_page(self._general_page(), Gtk.Label(label="常规"))
        notebook.append_page(self._gestures_page(), Gtk.Label(label="手势"))
        notebook.append_page(self._profiles_page(), Gtk.Label(label="应用配置"))
        notebook.append_page(self._import_page(), Gtk.Label(label="导入与恢复"))
        self.show_all()

    def _general_page(self):
        grid = Gtk.Grid(column_spacing=18, row_spacing=12, margin=24)
        grid.set_halign(Gtk.Align.CENTER)
        grid.set_valign(Gtk.Align.START)
        enabled = _compact_control(
            Gtk.Switch(active=bool(self.settings.get("enabled"))))
        enabled.connect("notify::active", lambda widget, _prop:
                        self.settings.set("enabled", widget.get_active()))
        _row(grid, 0, "启用鼠标手势", enabled)
        paused = _compact_control(
            Gtk.Switch(active=bool(self.settings.get("paused"))))
        paused.connect("notify::active", lambda widget, _prop:
                       self.settings.set("paused", widget.get_active()))
        _row(grid, 1, "临时暂停", paused)
        autostart = _compact_control(Gtk.Switch(active=session_autostart_enabled(
            self.settings.get("autostart-enabled"))))
        autostart.connect("notify::active", self._autostart_changed)
        _row(grid, 2, "登录时自动启动", autostart)
        minimize = _compact_control(
            Gtk.Switch(active=bool(self.settings.get("minimize-to-tray"))))
        minimize.connect("notify::active", lambda widget, _prop:
                         self.settings.set("minimize-to-tray", widget.get_active()))
        _row(grid, 3, "最小化/关闭到托盘", minimize)
        button_box = Gtk.Box(spacing=12)
        for name in BUTTONS:
            check = Gtk.CheckButton(label=BUTTON_LABELS[name])
            check.set_active(name in self.settings.get("trigger-buttons"))
            check.connect("toggled", self._buttons_changed, name, button_box)
            button_box.pack_start(check, False, False, 0)
        _row(grid, 4, "触发按钮", button_box)
        mode = _combo([("4", "四方向"), ("8", "八方向")],
                      0 if self.settings.get("direction-mode") == 4 else 1)
        mode.connect("changed", lambda widget:
                     self.settings.set("direction-mode", int(widget.get_active_id())))
        _row(grid, 5, "方向模式", mode)
        controls = (
            ("start-threshold", "起始移动阈值", 2, 100, 1),
            ("segment-threshold", "方向采样距离", 2, 200, 1),
            ("path-width", "轨迹宽度", 1, 24, 0.5),
            ("fade-duration", "淡出时间（毫秒）", 0, 3000, 50),
        )
        for row_index, (key, title, lower, upper, step) in enumerate(controls, 6):
            spin = Gtk.SpinButton.new_with_range(lower, upper, step)
            spin.set_value(float(self.settings.get(key)))
            spin.connect("value-changed", self._spin_changed, key,
                         key == "path-width")
            _row(grid, row_index, title, spin)
        for row_index, (key, title) in enumerate((
                ("path-color", "轨迹颜色"),
                ("invalid-path-color", "无效轨迹颜色")), 10):
            entry = Gtk.Entry(text=str(self.settings.get(key)))
            entry.connect("changed", self._color_changed, key)
            _row(grid, row_index, title, entry)
        show_name = _compact_control(
            Gtk.Switch(active=bool(self.settings.get("show-command-name"))))
        show_name.connect("notify::active", lambda widget, _prop:
                          self.settings.set("show-command-name", widget.get_active()))
        _row(grid, 12, "显示命令名称", show_name)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(grid)
        return scroll

    def _autostart_changed(self, widget, _property):
        if self._updating_autostart:
            return
        enabled = widget.get_active()
        try:
            set_session_autostart(enabled)
            self.settings.set("autostart-enabled", enabled)
        except OSError as write_error:
            self._updating_autostart = True
            widget.set_active(not enabled)
            self._updating_autostart = False
            _message(self, "无法更新自启动设置：{0}".format(write_error),
                     Gtk.MessageType.ERROR)

    def _delete_event(self, _window, _event):
        if self.settings.get("minimize-to-tray"):
            self.hide()
            return True
        return False

    def _window_state_event(self, _window, event):
        if (self.settings.get("minimize-to-tray") and
                event.changed_mask & Gdk.WindowState.ICONIFIED and
                event.new_window_state & Gdk.WindowState.ICONIFIED):
            GLib.idle_add(self._hide_after_minimize)
        return False

    def _hide_after_minimize(self):
        self.deiconify()
        self.hide()
        return GLib.SOURCE_REMOVE

    def _buttons_changed(self, widget, name, box):
        current = []
        for child, button_name in zip(box.get_children(), BUTTONS):
            if child.get_active():
                current.append(button_name)
        if not current:
            widget.set_active(True)
            return
        self.settings.set("trigger-buttons", current)

    def _spin_changed(self, widget, key, floating):
        value = widget.get_value() if floating else int(widget.get_value())
        self.settings.set(key, value)

    def _color_changed(self, widget, key):
        color = Gdk.RGBA()
        if color.parse(widget.get_text()):
            self.settings.set(key, widget.get_text())

    def _gestures_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=18)
        self.profile_combo = Gtk.ComboBoxText()
        self.profile_combo.connect("changed", self._profile_changed)
        box.pack_start(self.profile_combo, False, False, 0)
        self.gesture_store = Gtk.ListStore(str, str, str, str)
        view = Gtk.TreeView(model=self.gesture_store)
        for index, title in enumerate(("名称", "按钮", "方向", "动作")):
            view.append_column(Gtk.TreeViewColumn(
                title, Gtk.CellRendererText(), text=index))
        self.gesture_view = view
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        box.pack_start(scroll, True, True, 0)
        buttons = Gtk.ButtonBox(layout_style=Gtk.ButtonBoxStyle.START, spacing=6)
        for title, callback in (("添加", self._add_gesture), ("编辑", self._edit_gesture),
                                ("删除", self._delete_gesture), ("上移", self._move_up),
                                ("下移", self._move_down)):
            button = Gtk.Button(label=title)
            button.connect("clicked", callback)
            buttons.add(button)
        box.pack_start(buttons, False, False, 0)
        self._refresh_profiles_combo()
        self._refresh_gestures()
        return box

    def _profiles(self):
        return [self.config["globalProfile"]] + self.config["profiles"]

    def _current_profile(self):
        profiles = self._profiles()
        return profiles[min(self.profile_index, len(profiles) - 1)]

    def _refresh_profiles_combo(self):
        if not hasattr(self, "profile_combo"):
            return
        self.profile_combo.remove_all()
        for index, profile in enumerate(self._profiles()):
            self.profile_combo.append(str(index), profile["name"])
        self.profile_combo.set_active(min(self.profile_index, len(self._profiles()) - 1))

    def _profile_changed(self, combo):
        if combo.get_active() >= 0:
            self.profile_index = combo.get_active()
            self._refresh_gestures()

    def _refresh_gestures(self):
        if not hasattr(self, "gesture_store"):
            return
        self.gesture_store.clear()
        actions = dict((item["id"], item) for item in self.config["actions"])
        for gesture in self._current_profile()["gestures"]:
            action = actions.get(gesture["actionId"], {})
            self.gesture_store.append([
                gesture["name"], BUTTON_LABELS.get(gesture["button"], gesture["button"]),
                " → ".join(gesture["directions"]), ACTION_LABELS.get(action.get("type"), "未知")])

    def _selected_gesture_index(self):
        model, iterator = self.gesture_view.get_selection().get_selected()
        if iterator is None:
            return None
        return model.get_path(iterator).get_indices()[0]

    def _add_gesture(self, _button):
        self._run_gesture_dialog(None)

    def _edit_gesture(self, _button):
        index = self._selected_gesture_index()
        if index is not None:
            self._run_gesture_dialog(self._current_profile()["gestures"][index])

    def _run_gesture_dialog(self, gesture):
        dialog = GestureDialog(self, self._current_profile(), self.config,
                               gesture, self.settings)
        while dialog.run() == Gtk.ResponseType.OK:
            try:
                result_gesture, result_action = dialog.result()
                if gesture:
                    gesture.clear()
                    gesture.update(result_gesture)
                    existing = next(item for item in self.config["actions"]
                                    if item["id"] == result_action["id"])
                    existing.clear()
                    existing.update(result_action)
                else:
                    self.config["actions"].append(result_action)
                    self._current_profile()["gestures"].append(result_gesture)
                self._save()
                break
            except ValueError as validation_error:
                _message(dialog, str(validation_error), Gtk.MessageType.ERROR)
        dialog.destroy()
        self._refresh_gestures()

    def _delete_gesture(self, _button):
        index = self._selected_gesture_index()
        if index is None:
            return
        gesture = self._current_profile()["gestures"].pop(index)
        used = any(item["actionId"] == gesture["actionId"]
                   for profile in self._profiles() for item in profile["gestures"])
        if not used:
            self.config["actions"] = [item for item in self.config["actions"]
                                      if item["id"] != gesture["actionId"]]
        self._save()
        self._refresh_gestures()

    def _move(self, delta):
        index = self._selected_gesture_index()
        gestures = self._current_profile()["gestures"]
        target = index + delta if index is not None else -1
        if index is None or target < 0 or target >= len(gestures):
            return
        gestures[index], gestures[target] = gestures[target], gestures[index]
        self._save()
        self._refresh_gestures()
        self.gesture_view.set_cursor(Gtk.TreePath.new_from_string(str(target)))

    def _move_up(self, _button):
        self._move(-1)

    def _move_down(self, _button):
        self._move(1)

    def _profiles_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=18)
        self.profile_store = Gtk.ListStore(str, str, str, str)
        self.profile_view = Gtk.TreeView(model=self.profile_store)
        for index, title in enumerate(("名称", "启用", "继承全局", "匹配条件")):
            self.profile_view.append_column(Gtk.TreeViewColumn(
                title, Gtk.CellRendererText(), text=index))
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.profile_view)
        box.pack_start(scroll, True, True, 0)
        buttons = Gtk.ButtonBox(layout_style=Gtk.ButtonBoxStyle.START)
        for title, callback in (("添加", self._add_profile), ("编辑", self._edit_profile),
                                ("删除", self._delete_profile),
                                ("上移", self._move_profile_up),
                                ("下移", self._move_profile_down)):
            button = Gtk.Button(label=title)
            button.connect("clicked", callback)
            buttons.add(button)
        box.pack_start(buttons, False, False, 0)
        self._refresh_profile_list()
        return box

    def _refresh_profile_list(self):
        if not hasattr(self, "profile_store"):
            return
        self.profile_store.clear()
        for profile in self.config["profiles"]:
            matchers = ", ".join("{0}={1}".format(
                MATCHER_LABELS.get(item["type"], item["type"]), item["value"])
                for item in profile["matchers"])
            if not matchers and profile.get("legacyExecutablePath"):
                matchers = "未绑定: {0}".format(profile["legacyExecutablePath"])
            self.profile_store.append([
                profile["name"], "是" if profile["enabled"] else "否",
                "是" if profile["inheritGlobal"] else "否", matchers or "未绑定"])

    def _selected_profile_list_index(self):
        model, iterator = self.profile_view.get_selection().get_selected()
        return model.get_path(iterator).get_indices()[0] if iterator is not None else None

    def _profile_dialog(self, profile=None):
        dialog = Gtk.Dialog(title="编辑应用配置" if profile else "添加应用配置",
                            transient_for=self, modal=True)
        dialog.add_button("取消", Gtk.ResponseType.CANCEL)
        dialog.add_button("保存", Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=12, row_spacing=12, margin=18)
        dialog.get_content_area().add(grid)
        name = Gtk.Entry(text=profile["name"] if profile else "")
        _row(grid, 0, "名称", name)
        enabled = Gtk.CheckButton(label="启用")
        enabled.set_active(profile.get("enabled", True) if profile else True)
        grid.attach(enabled, 1, 1, 1, 1)
        inherit = Gtk.CheckButton(label="继承全局手势")
        inherit.set_active(profile.get("inheritGlobal", True) if profile else True)
        grid.attach(inherit, 1, 2, 1, 1)
        current_matchers = dict((item["type"], item["value"])
                                for item in profile.get("matchers", [])) \
            if profile else {}
        matcher_entries = {}
        for row_index, matcher_type in enumerate(MATCHER_LABELS, 3):
            entry = Gtk.Entry(text=current_matchers.get(matcher_type, ""))
            entry.set_placeholder_text("可留空")
            matcher_entries[matcher_type] = entry
            _row(grid, row_index, MATCHER_LABELS[matcher_type], entry)
        dialog.show_all()
        response = dialog.run()
        result = None
        if response == Gtk.ResponseType.OK:
            matchers = [{"type": matcher_type, "value": entry.get_text().strip()}
                        for matcher_type, entry in matcher_entries.items()
                        if entry.get_text().strip()]
            if not name.get_text().strip() or not matchers:
                _message(dialog, "名称不能为空，且至少需要一个匹配值", Gtk.MessageType.ERROR)
            else:
                result = copy.deepcopy(profile) if profile else {
                    "id": "profile-{0}".format(uuid.uuid4()), "gestures": []}
                result.update({
                    "name": name.get_text().strip(), "enabled": enabled.get_active(),
                    "inheritGlobal": inherit.get_active(),
                    "matchers": matchers,
                })
        dialog.destroy()
        return result

    def _add_profile(self, _button):
        result = self._profile_dialog()
        if result:
            conflict = self._profile_matcher_conflict(result)
            if conflict:
                _message(self, "与应用配置“{0}”的匹配条件冲突".format(conflict),
                         Gtk.MessageType.ERROR)
                return
            self.config["profiles"].append(result)
            self._save()
            self._refresh_profile_list()
            self._refresh_profiles_combo()

    def _edit_profile(self, _button):
        index = self._selected_profile_list_index()
        if index is None:
            return
        profile = self.config["profiles"][index]
        result = self._profile_dialog(profile)
        if result:
            conflict = self._profile_matcher_conflict(result, profile)
            if conflict:
                _message(self, "与应用配置“{0}”的匹配条件冲突".format(conflict),
                         Gtk.MessageType.ERROR)
                return
            profile.clear()
            profile.update(result)
            self._save()
            self._refresh_profile_list()
            self._refresh_profiles_combo()

    def _profile_matcher_conflict(self, candidate, excluded=None):
        candidate_keys = set((item["type"], item["value"].lower())
                             for item in candidate["matchers"])
        for profile in self.config["profiles"]:
            if profile is excluded:
                continue
            if any((item["type"], item["value"].lower()) in candidate_keys
                   for item in profile["matchers"]):
                return profile["name"]
        return None

    def _delete_profile(self, _button):
        index = self._selected_profile_list_index()
        if index is None:
            return
        del self.config["profiles"][index]
        self.profile_index = 0
        self._remove_unused_actions()
        self._save()
        self._refresh_profile_list()
        self._refresh_profiles_combo()

    def _move_profile(self, delta):
        index = self._selected_profile_list_index()
        target = index + delta if index is not None else -1
        if index is None or target < 0 or target >= len(self.config["profiles"]):
            return
        profiles = self.config["profiles"]
        profiles[index], profiles[target] = profiles[target], profiles[index]
        self._save()
        self._refresh_profile_list()
        self._refresh_profiles_combo()
        self.profile_view.set_cursor(Gtk.TreePath.new_from_string(str(target)))

    def _move_profile_up(self, _button):
        self._move_profile(-1)

    def _move_profile_down(self, _button):
        self._move_profile(1)

    def _import_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin=24)
        text = Gtk.Label(label=(
            ".cgestures 可与 Windows 双向交换通用手势；平台专属命令会安全跳过。"
            "旧 .wg2 仍按白名单安全解析。"))
        text.set_line_wrap(True)
        text.set_xalign(0)
        box.pack_start(text, False, False, 0)
        export_button = Gtk.Button(label="导出跨平台配置 (.cgestures)")
        export_button.connect("clicked", self._export_portable)
        box.pack_start(export_button, False, False, 0)
        import_button = Gtk.Button(label="导入 .cgestures / .wg2 并预览")
        import_button.connect("clicked", self._choose_import)
        box.pack_start(import_button, False, False, 0)
        reset_button = Gtk.Button(label="恢复默认手势")
        reset_button.connect("clicked", self._reset_defaults)
        box.pack_start(reset_button, False, False, 0)
        return box

    def _export_portable(self, _button):
        chooser = Gtk.FileChooserDialog(
            title="导出 CrossGestures 跨平台配置", transient_for=self,
            action=Gtk.FileChooserAction.SAVE)
        chooser.add_buttons("取消", Gtk.ResponseType.CANCEL,
                            "保存", Gtk.ResponseType.OK)
        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_name("CrossGestures.cgestures")
        file_filter = Gtk.FileFilter()
        file_filter.set_name("CrossGestures 跨平台配置 (*.cgestures)")
        file_filter.add_pattern("*.cgestures")
        chooser.add_filter(file_filter)
        if chooser.run() != Gtk.ResponseType.OK:
            chooser.destroy()
            return
        path = chooser.get_filename()
        chooser.destroy()
        if not path.lower().endswith(".cgestures"):
            path += ".cgestures"
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(export_portable_config(self.config))
            _message(self, "跨平台配置已导出：{0}".format(path))
        except (OSError, ValueError) as export_error:
            _message(self, "导出失败：{0}".format(export_error), Gtk.MessageType.ERROR)

    def _choose_import(self, _button):
        chooser = Gtk.FileChooserDialog(
            title="选择 CrossGestures 配置", transient_for=self,
            action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons("取消", Gtk.ResponseType.CANCEL,
                            "打开", Gtk.ResponseType.OK)
        file_filter = Gtk.FileFilter()
        file_filter.set_name("CrossGestures (*.cgestures; *.wg2)")
        file_filter.add_pattern("*.cgestures")
        file_filter.add_pattern("*.wg2")
        chooser.add_filter(file_filter)
        if chooser.run() != Gtk.ResponseType.OK:
            chooser.destroy()
            return
        path = chooser.get_filename()
        chooser.destroy()
        try:
            with open(path, "r", encoding="utf-8") as stream:
                imported = import_config(stream.read())
            self._import_preview(imported)
        except (OSError, ValueError) as import_error:
            _message(self, "导入失败：{0}".format(import_error), Gtk.MessageType.ERROR)

    def _import_preview(self, imported):
        dialog = Gtk.Dialog(title="选择要导入的手势", transient_for=self, modal=True)
        dialog.set_default_size(620, 560)
        dialog.add_button("取消", Gtk.ResponseType.CANCEL)
        dialog.add_button("导入选中项", Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        report = imported["report"]
        content.pack_start(Gtk.Label(label="可转换：{0}，不兼容：{1}".format(
            report["imported"], len(report["unsupported"]))), False, False, 8)
        list_box = Gtk.ListBox()
        selections = []
        actions = dict((item["id"], item) for item in imported["config"]["actions"])
        for profile in [imported["config"]["globalProfile"]] + imported["config"]["profiles"]:
            for gesture in profile["gestures"]:
                check = Gtk.CheckButton(label="{0} · {1} · {2}".format(
                    profile["name"], gesture["name"], " → ".join(gesture["directions"])))
                check.set_active(True)
                list_box.add(check)
                selections.append((check, profile, gesture, actions[gesture["actionId"]]))
        scroll = Gtk.ScrolledWindow()
        scroll.add(list_box)
        content.pack_start(scroll, True, True, 0)
        if report["unsupported"]:
            warning = Gtk.Label(label="未导入：\n" + "\n".join(report["unsupported"][:8]))
            warning.set_xalign(0)
            warning.set_line_wrap(True)
            content.pack_start(warning, False, False, 8)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            self._merge_import([item for item in selections if item[0].get_active()])
        dialog.destroy()

    def _merge_import(self, selections):
        count, conflicts = 0, 0
        profile_map = {}
        for _check, source_profile, gesture, action in selections:
            if source_profile["id"] == "global":
                target = self.config["globalProfile"]
            else:
                target = profile_map.get(source_profile["id"])
                if target is None:
                    target = {
                        "id": "profile-{0}".format(uuid.uuid4()),
                        "name": source_profile["name"], "enabled": source_profile["enabled"],
                        "inheritGlobal": source_profile["inheritGlobal"],
                        "matchers": [],
                        "legacyExecutablePath": source_profile.get("legacyExecutablePath", ""),
                        "gestures": [],
                    }
                    self.config["profiles"].append(target)
                    profile_map[source_profile["id"]] = target
            key = gesture_key(gesture["button"], gesture["directions"])
            if any(gesture_key(item["button"], item["directions"]) == key
                   for item in target["gestures"]):
                conflicts += 1
                continue
            new_action = copy.deepcopy(action)
            new_action["id"] = "action-{0}".format(uuid.uuid4())
            new_gesture = copy.deepcopy(gesture)
            new_gesture.update({"id": "gesture-{0}".format(uuid.uuid4()),
                                "actionId": new_action["id"]})
            self.config["actions"].append(new_action)
            target["gestures"].append(new_gesture)
            count += 1
        self._save()
        self._refresh_profile_list()
        self._refresh_profiles_combo()
        self._refresh_gestures()
        _message(self, "已导入 {0}，跳过冲突 {1}".format(count, conflicts))

    def _reset_defaults(self, _button):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="当前配置会先备份，然后恢复默认手势。")
        if dialog.run() == Gtk.ResponseType.OK:
            self.config = create_default_config()
            self.profile_index = 0
            self._save()
            self._refresh_profile_list()
            self._refresh_profiles_combo()
            self._refresh_gestures()
        dialog.destroy()

    def _remove_unused_actions(self):
        used = set(gesture["actionId"] for profile in self._profiles()
                   for gesture in profile["gestures"])
        self.config["actions"] = [item for item in self.config["actions"]
                                  if item["id"] in used]

    def _save(self):
        self.config = self.store.save(self.config)
        self.settings.bump_revision()


class PreferencesApplication(Gtk.Application):
    def __init__(self):
        Gtk.Application.__init__(
            self, application_id="com.yingdev.WGestures.Settings",
            flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        windows = self.get_windows()
        window = windows[0] if windows else None
        if window is None:
            window = PreferencesWindow(self)
        present_preferences_window(window)


def present_preferences_window(window):
    """Remap a settings window previously hidden by close-to-tray."""
    window.deiconify()
    window.show_all()
    window.present()


def run_preferences():
    return PreferencesApplication().run([])

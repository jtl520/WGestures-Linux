from __future__ import print_function, unicode_literals

import io
import os
import shlex
import shutil
import subprocess
import threading
import time

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from .panel import (PANEL_ITEM_TYPES, PANEL_SLOT_COUNT, PanelStore,
                    default_panel_label, favicon_cache_path, favicon_url,
                    find_running_process_pid, is_valid_favicon, normalize_panel,
                    panel_item_from_drop_uri)


TYPE_LABELS = {
    "application": "启动软件",
    "file": "打开文件",
    "folder": "打开文件夹",
    "url": "打开网址",
}

FALLBACK_ICON_NAMES = {
    "application": "application-x-executable",
    "file": "text-x-generic",
    "folder": "folder",
    "url": "web-browser",
}

_URI_LIST_TARGET = Gtk.TargetEntry.new("text/uri-list", 0, 0)


_FAVICON_TIMEOUT_SECONDS = 3


_FILE_MANAGER_COMMANDS_BY_DESKTOP = (
    ("xfce", ("thunar",)),
    ("gnome", ("nautilus",)),
    ("kde", ("dolphin",)),
    ("plasma", ("dolphin",)),
    ("cinnamon", ("nemo",)),
    ("mate", ("caja",)),
    ("lxqt", ("pcmanfm-qt",)),
    ("lxde", ("pcmanfm",)),
)
_FILE_MANAGER_FALLBACK_COMMANDS = (
    "thunar", "nautilus", "dolphin", "nemo", "caja", "pcmanfm-qt", "pcmanfm",
)


def panel_layout_for_area(width, height):
    """Return adaptive GTK panel dimensions for a logical monitor area."""
    scale = max(0.68, min(1.35, min(width, height) / 900.0))
    return (
        int(round(104 * scale)), int(round(92 * scale)),
        int(round(40 * scale)), max(5, int(round(8 * scale))),
        max(8, int(round(12 * scale))),
    )


def _file_manager_commands(desktop=None):
    """Return installed-file-manager candidates in desktop-preferred order."""
    desktop_name = (desktop if desktop is not None else
                    (os.environ.get("XDG_CURRENT_DESKTOP") or
                     os.environ.get("DESKTOP_SESSION") or "")).lower()
    commands = []
    for marker, preferred in _FILE_MANAGER_COMMANDS_BY_DESKTOP:
        if marker in desktop_name:
            commands.extend(preferred)
    commands.extend(_FILE_MANAGER_FALLBACK_COMMANDS)
    return list(dict.fromkeys(commands))


def _launch_folder(path, popen=None, which=None, uri_launcher=None, desktop=None):
    """Open a directory with a file manager, never a search/indexing app."""
    popen = popen or subprocess.Popen
    which = which or shutil.which
    for command in _file_manager_commands(desktop):
        executable = which(command)
        if executable:
            popen([executable, path], close_fds=True)
            return
    launcher = uri_launcher or Gio.AppInfo.launch_default_for_uri
    launcher(Gio.File.new_for_path(path).get_uri(), None)


def _favicon_cache_directory():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "wgestures", "favicons")


def _favicon_bytes(url):
    import urllib.request

    request = urllib.request.Request(
        url, headers={"User-Agent": "CrossGestures/2.1 quick-panel favicon"})
    with urllib.request.urlopen(
            request, timeout=_FAVICON_TIMEOUT_SECONDS) as response:
        data = response.read(256 * 1024 + 1)
    return data if is_valid_favicon(data) else None


def _favicon_candidate_urls(target):
    """Prefer the site itself, then handle sites that reject icon clients."""
    direct = favicon_url(target)
    if not direct:
        return []
    from urllib.parse import quote, urlsplit
    host = (urlsplit(target).hostname or "").lower()
    return [
        direct,
        "https://www.google.com/s2/favicons?domain={0}&sz=128".format(
            quote(host, safe="")),
    ]


def _ensure_favicon(item, on_ready):
    # 后台线程下载站点图标；仅下载成功时回调（无新数据不打断面板交互，
    # 离线或站点无图标时静默保持通用图标）。
    url = favicon_url(item["target"])
    if not url:
        return

    def worker():
        if not fetch_favicon(item["target"]):
            return
        GLib.idle_add(on_ready)

    threading.Thread(target=worker, daemon=True).start()


def fetch_favicon(target):
    """Fetch one URL icon for GTK or the GNOME Shell helper process."""
    urls = _favicon_candidate_urls(target)
    if not urls:
        return False
    data = None
    for url in urls:
        try:
            data = _favicon_bytes(url)
        except (OSError, ValueError):
            data = None
        if data:
            break
    if not data:
        return False
    cache_path = favicon_cache_path(_favicon_cache_directory(), target)
    if not cache_path:
        return False
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        temporary = cache_path + ".tmp"
        with io.open(temporary, "wb") as stream:
            stream.write(data)
        os.replace(temporary, cache_path)
        return True
    except OSError:
        return False


_APPLICATION_RECORDS_TTL_SECONDS = 30.0
_APPLICATION_RECORDS_CACHE = {"records": None, "expires": 0.0}


def warm_application_records():
    # 预热应用记录缓存：后台守护启动时调用一次，避免开机后第一次弹出
    # 面板时现场扫描全部 desktop 文件。
    _application_records()


def prewarm_application_records_async():
    threading.Thread(target=warm_application_records, daemon=True).start()


def _application_records():
    # Gio.AppInfo.get_all() scans every installed desktop file; caching the
    # result keeps repeated panel opens fast while still noticing newly
    # installed applications within half a minute.
    now = time.monotonic()
    cache = _APPLICATION_RECORDS_CACHE
    if cache["records"] is not None and now < cache["expires"]:
        return cache["records"]
    records = []
    for application in Gio.AppInfo.get_all():
        app_id = application.get_id()
        if app_id and application.should_show():
            records.append((application.get_display_name() or app_id, app_id, application))
    records.sort(key=lambda item: item[0].lower())
    cache["records"] = records
    cache["expires"] = now + _APPLICATION_RECORDS_TTL_SECONDS
    return records


def _lookup_gicon(item, on_missing_favicon=None):
    icon = None
    try:
        if item["type"] == "application":
            raw_target = item["target"]
            record = next((record for record in _application_records()
                           if record[1] == raw_target), None)
            application = record[2] if record else None
            # DesktopAppInfo.new() raises TypeError (rather than returning
            # None) for paths such as ./studio on current PyGObject. Only a
            # real freedesktop launcher ID belongs in that constructor.
            if (application is None and "/" not in raw_target and
                    raw_target.endswith(".desktop")):
                try:
                    application = Gio.DesktopAppInfo.new(raw_target)
                except (GLib.Error, TypeError):
                    application = None
            icon = application.get_icon() if application else None
            if icon is None:
                target = raw_target
                working_directory = item.get("workingDirectory")
                if not os.path.isabs(target) and working_directory:
                    target = os.path.join(working_directory, target)
                target = os.path.abspath(os.path.expanduser(target))
                if os.path.isfile(target):
                    # Portable applications commonly ship an icon beside the
                    # executable (Android Studio has bin/studio.svg/png).
                    for extension in (".svg", ".png", ".xpm", ".ico"):
                        icon_path = target + extension
                        if os.path.isfile(icon_path):
                            icon = Gio.FileIcon.new(
                                Gio.File.new_for_path(icon_path))
                            break
                    if icon is None:
                        info = Gio.File.new_for_path(target).query_info(
                            "standard::icon", Gio.FileQueryInfoFlags.NONE, None)
                        icon = info.get_icon()
        elif item["type"] in ("file", "folder"):
            info = Gio.File.new_for_path(item["target"]).query_info(
                "standard::icon", Gio.FileQueryInfoFlags.NONE, None)
            icon = info.get_icon()
        elif item["type"] == "url":
            cache_path = favicon_cache_path(
                _favicon_cache_directory(), item["target"])
            if cache_path and os.path.isfile(cache_path):
                with io.open(cache_path, "rb") as stream:
                    data = stream.read()
                if is_valid_favicon(data):
                    icon = Gio.BytesIcon.new(GLib.Bytes.new(data))
            if icon is None and on_missing_favicon is not None:
                on_missing_favicon(item)
    except (GLib.Error, OSError, TypeError):
        icon = None
    return icon


def _cached_gicon(item, size, icon_cache):
    # Cache GIcon objects (headless-safe); widget creation stays separate
    # because Gtk.Image requires a display connection.
    key = (item["type"], item["target"], size)
    icon = icon_cache.get(key)
    if icon is None:
        icon = _lookup_gicon(item)
        icon_cache[key] = icon
    return icon


def _icon_widget(item, size=40, icon_cache=None, on_missing_favicon=None):
    if icon_cache is not None:
        key = (item["type"], item["target"], size)
        icon = icon_cache.get(key)
        if icon is None:
            icon = _lookup_gicon(item, on_missing_favicon=on_missing_favicon)
            icon_cache[key] = icon
    else:
        icon = _lookup_gicon(item, on_missing_favicon=on_missing_favicon)
    if icon is not None:
        image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.DIALOG)
        image.set_pixel_size(size)
        return image
    fallback = FALLBACK_ICON_NAMES[item["type"]]
    image = Gtk.Image.new_from_icon_name(fallback, Gtk.IconSize.DIALOG)
    image.set_pixel_size(size)
    return image


def _configure_modal_child(dialog, parent):
    """Keep every chooser above its owner without making the panel topmost."""
    dialog.set_transient_for(parent)
    dialog.set_modal(True)
    dialog.set_destroy_with_parent(True)
    dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
    return dialog


class PanelItemDialog(Gtk.Dialog):
    def __init__(self, parent, index, item=None, initial_type=None):
        Gtk.Dialog.__init__(self, title="编辑格子" if item else "添加格子")
        _configure_modal_child(self, parent)
        self.set_default_size(720, 520)
        self.add_button("取消", Gtk.ResponseType.CANCEL)
        if item:
            self.add_button("删除", Gtk.ResponseType.REJECT)
        self.add_button("保存", Gtk.ResponseType.OK)
        self.index = index
        self.item = dict(item) if item else None
        grid = Gtk.Grid(column_spacing=12, row_spacing=12, margin=18)
        self.get_content_area().pack_start(grid, True, True, 0)

        self.type_combo = Gtk.ComboBoxText()
        for item_type in PANEL_ITEM_TYPES:
            self.type_combo.append(item_type, TYPE_LABELS[item_type])
        selected_type = item["type"] if item else (initial_type or "application")
        self.type_combo.set_active(PANEL_ITEM_TYPES.index(selected_type))
        self.type_combo.connect("changed", self._type_changed)
        self._row(grid, 0, "动作类型", self.type_combo)

        self.label_entry = Gtk.Entry()
        self.label_entry.set_text(item.get("label", "") if item else "")
        self.label_entry.set_placeholder_text("留空时自动生成名称")
        self._row(grid, 1, "显示名称", self.label_entry)

        self.description_entry = Gtk.Entry()
        self.description_entry.set_text(item.get("description", "") if item else "")
        self._row(grid, 2, "功能/用途说明", self.description_entry)

        target_box = Gtk.Box(spacing=8)
        self.target_entry = Gtk.Entry()
        self.target_entry.set_hexpand(True)
        self.target_entry.set_text(item.get("target", "") if item else "")
        target_box.pack_start(self.target_entry, True, True, 0)
        self.choose_button = Gtk.Button(label="选择…")
        self.choose_button.connect("clicked", self._choose_target)
        target_box.pack_start(self.choose_button, False, False, 0)
        self.target_label = self._row(grid, 3, "路径或网址", target_box)

        self.arguments_entry = Gtk.Entry()
        self.arguments_entry.set_text(item.get("arguments", "") if item else "")
        self.arguments_label = self._row(grid, 4, "参数（可选）", self.arguments_entry)

        working_box = Gtk.Box(spacing=8)
        self.working_box = working_box
        self.working_entry = Gtk.Entry()
        self.working_entry.set_hexpand(True)
        self.working_entry.set_text(item.get("workingDirectory", "") if item else "")
        working_box.pack_start(self.working_entry, True, True, 0)
        working_choose = Gtk.Button(label="选择…")
        working_choose.connect("clicked", self._choose_working_directory)
        working_box.pack_start(working_choose, False, False, 0)
        self.working_label = self._row(grid, 5, "工作目录", working_box)

        self.browser_combo = Gtk.ComboBoxText()
        self.browser_combo.append("", "系统默认浏览器")
        browser_ids = set()
        for browser in Gio.AppInfo.get_recommended_for_type("x-scheme-handler/http"):
            browser_id = browser.get_id()
            if browser_id and browser_id not in browser_ids:
                self.browser_combo.append(browser_id, browser.get_display_name() or browser_id)
                browser_ids.add(browser_id)
        saved_browser = item.get("browser", "") if item else ""
        if saved_browser and saved_browser not in browser_ids:
            self.browser_combo.append(saved_browser, saved_browser)
        self.browser_combo.set_active_id(saved_browser)
        if self.browser_combo.get_active() < 0:
            self.browser_combo.set_active(0)
        self.browser_label = self._row(grid, 6, "浏览器", self.browser_combo)

        options = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.options_box = options
        self.run_as_admin = Gtk.CheckButton(label="以管理员身份运行（通过 pkexec）")
        self.run_as_admin.set_active(bool(item.get("runAsAdministrator")) if item else False)
        self.activate_running = Gtk.CheckButton(label="如果程序已运行，尝试激活已打开的窗口")
        self.activate_running.set_active(bool(item.get("activateIfRunning")) if item else False)
        options.pack_start(self.run_as_admin, False, False, 0)
        options.pack_start(self.activate_running, False, False, 0)
        self.options_label = self._row(grid, 7, "选项", options)
        self.arguments_entry.set_tooltip_text(
            "传给程序的额外内容，例如 --project \"/home/user/My Project\"；不要重复填写程序路径。")
        self.working_entry.set_tooltip_text(
            "相当于先在终端执行 cd 到这个目录，再启动程序；./程序名会从这里查找。")
        self.run_as_admin.set_tooltip_text(
            "Linux 使用 pkexec 弹出系统身份认证窗口；认证成功后以 root 身份启动。")
        self.show_all()
        self._type_changed(self.type_combo)
        if item is None and initial_type == "application":
            GLib.idle_add(self._auto_choose_application)

    def _auto_choose_application(self):
        self._choose_target(None)
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _row(grid, row, title, widget):
        label = Gtk.Label(label=title, xalign=0)
        grid.attach(label, 0, row, 1, 1)
        grid.attach(widget, 1, row, 1, 1)
        return label

    def _type_changed(self, _combo):
        item_type = self.type_combo.get_active_id()
        placeholders = {
            "application": "Desktop ID、/绝对路径，或 ./程序名",
            "file": "/home/user/file.txt",
            "folder": "/home/user/Documents",
            "url": "https://example.com",
        }
        self.target_entry.set_placeholder_text(placeholders[item_type])
        self.target_label.set_text({
            "application": "程序或启动目标",
            "file": "文件路径",
            "folder": "文件夹路径",
            "url": "网址",
        }[item_type])
        self.target_entry.set_tooltip_text({
            "application": "可以填写 Desktop ID、PATH 中的命令、绝对程序路径，或 ./程序名。",
            "file": "要由系统默认应用打开的文件绝对路径。",
            "folder": "要由文件管理器打开的文件夹绝对路径。",
            "url": "完整网址，例如 https://example.com。",
        }[item_type])
        self.arguments_label.set_text("启动参数（不含程序名）")
        self.working_label.set_text("工作目录（启动位置）")
        self.choose_button.set_sensitive(item_type != "url")
        is_application = item_type == "application"
        is_url = item_type == "url"
        for widget in (self.arguments_label, self.arguments_entry,
                       self.working_label, self.working_box,
                       self.options_label, self.options_box):
            widget.set_visible(is_application)
        self.browser_label.set_visible(is_url)
        self.browser_combo.set_visible(is_url)

    def _choose_working_directory(self, _button):
        dialog = Gtk.FileChooserDialog(
            title="选择工作目录",
            action=Gtk.FileChooserAction.SELECT_FOLDER)
        _configure_modal_child(dialog, self)
        dialog.add_buttons("取消", Gtk.ResponseType.CANCEL,
                           "选择", Gtk.ResponseType.OK)
        if dialog.run() == Gtk.ResponseType.OK:
            self.working_entry.set_text(dialog.get_filename())
        dialog.destroy()

    def _choose_target(self, _button):
        item_type = self.type_combo.get_active_id()
        if item_type == "application":
            records = _application_records()
            dialog = Gtk.Dialog(title="选择软件")
            _configure_modal_child(dialog, self)
            dialog.set_default_size(540, 520)
            dialog.add_button("取消", Gtk.ResponseType.CANCEL)
            dialog.add_button("选择可执行文件…", Gtk.ResponseType.APPLY)
            dialog.add_button("选择", Gtk.ResponseType.OK)
            store = Gtk.ListStore(object, str, str)
            for name, app_id, application in records:
                store.append([application.get_icon(), name, app_id])
            search = Gtk.SearchEntry()
            search.set_placeholder_text("搜索应用名称或 Desktop ID")
            filtered = store.filter_new()
            filtered.set_visible_func(lambda model, tree_iter, _data:
                not search.get_text().strip().lower() or
                search.get_text().strip().lower() in model[tree_iter][1].lower() or
                search.get_text().strip().lower() in model[tree_iter][2].lower())
            search.connect("search-changed", lambda _entry: filtered.refilter())
            view = Gtk.TreeView(model=filtered)
            view.append_column(Gtk.TreeViewColumn(
                "", Gtk.CellRendererPixbuf(), gicon=0))
            view.append_column(Gtk.TreeViewColumn(
                "软件", Gtk.CellRendererText(), text=1))
            view.append_column(Gtk.TreeViewColumn(
                "Desktop ID", Gtk.CellRendererText(), text=2))
            scroll = Gtk.ScrolledWindow()
            scroll.add(view)
            dialog.get_content_area().pack_start(search, False, False, 8)
            dialog.get_content_area().pack_start(scroll, True, True, 0)
            dialog.show_all()
            response = dialog.run()
            if response == Gtk.ResponseType.OK:
                model, selected = view.get_selection().get_selected()
                if selected is not None:
                    self.target_entry.set_text(model[selected][2])
                    if not self.label_entry.get_text().strip():
                        self.label_entry.set_text(model[selected][1])
            dialog.destroy()
            if response == Gtk.ResponseType.APPLY:
                self._choose_executable_file()
            return
        action = (Gtk.FileChooserAction.OPEN if item_type == "file"
                  else Gtk.FileChooserAction.SELECT_FOLDER)
        dialog = Gtk.FileChooserDialog(
            title="选择文件" if item_type == "file" else "选择文件夹",
            action=action)
        _configure_modal_child(dialog, self)
        dialog.add_buttons("取消", Gtk.ResponseType.CANCEL,
                           "选择", Gtk.ResponseType.OK)
        if dialog.run() == Gtk.ResponseType.OK:
            target = dialog.get_filename()
            self.target_entry.set_text(target)
            if not self.label_entry.get_text().strip():
                self.label_entry.set_text(os.path.basename(target.rstrip(os.sep)))
        dialog.destroy()

    def _choose_executable_file(self):
        dialog = Gtk.FileChooserDialog(
            title="选择可执行文件",
            action=Gtk.FileChooserAction.OPEN)
        _configure_modal_child(dialog, self)
        dialog.add_buttons("取消", Gtk.ResponseType.CANCEL,
                           "选择", Gtk.ResponseType.OK)
        current_directory = self.working_entry.get_text().strip()
        if os.path.isdir(current_directory):
            dialog.set_current_folder(current_directory)
        if dialog.run() == Gtk.ResponseType.OK:
            target = dialog.get_filename()
            self.target_entry.set_text(target)
            self.working_entry.set_text(os.path.dirname(target))
            if not self.label_entry.get_text().strip():
                self.label_entry.set_text(os.path.basename(target))
        dialog.destroy()

    def result_item(self):
        item_type = self.type_combo.get_active_id()
        target = self.target_entry.get_text().strip()
        candidate = {
            "schemaVersion": 1,
            "slots": [None for _index in range(16)],
        }
        candidate["slots"][self.index] = {
            "id": self.item.get("id", "slot-{0}".format(self.index + 1))
            if self.item else "slot-{0}".format(self.index + 1),
            "label": self.label_entry.get_text().strip() or
                     default_panel_label(item_type, target),
            "type": item_type,
            "target": target,
        }
        slot = candidate["slots"][self.index]
        description = self.description_entry.get_text().strip()
        if description:
            slot["description"] = description
        if item_type == "application":
            arguments = self.arguments_entry.get_text().strip()
            working_directory = self.working_entry.get_text().strip()
            if arguments:
                slot["arguments"] = arguments
            if working_directory:
                slot["workingDirectory"] = working_directory
            if self.run_as_admin.get_active():
                slot["runAsAdministrator"] = True
            if self.activate_running.get_active():
                slot["activateIfRunning"] = True
        if item_type == "url" and self.browser_combo.get_active_id():
            slot["browser"] = self.browser_combo.get_active_id()
        normalized = normalize_panel(candidate)["config"]["slots"][self.index]
        if normalized is None:
            raise ValueError("目标无效，请检查动作类型和路径或网址")
        if item_type == "application":
            records = _application_records()
            is_desktop_application = any(
                record[1] == target for record in records)
            if not is_desktop_application:
                _resolve_executable_target(
                    target, normalized.get("workingDirectory"))
        return normalized


def edit_panel_slot(index, parent=None, initial_type=None):
    if index < 0 or index >= 16:
        raise ValueError("面板格子索引必须在 0 到 15 之间")
    if initial_type is not None and initial_type not in PANEL_ITEM_TYPES:
        raise ValueError("未知的面板动作类型：{0}".format(initial_type))
    store = PanelStore()
    panel = store.load()["config"]
    dialog = PanelItemDialog(
        parent, index, panel["slots"][index], initial_type=initial_type)
    response = dialog.run()
    if response == Gtk.ResponseType.REJECT:
        panel["slots"][index] = None
        store.save(panel)
        dialog.destroy()
        return 0
    while response == Gtk.ResponseType.OK:
        try:
            panel["slots"][index] = dialog.result_item()
            store.save(panel)
            dialog.destroy()
            return 0
        except ValueError as error:
            message = Gtk.MessageDialog(
                transient_for=dialog, modal=True, message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK, text=str(error))
            message.run()
            message.destroy()
            response = dialog.run()
    dialog.destroy()
    return 0


def _activate_running_application(executable):
    # Best effort: without libwnck the caller falls back to a normal launch.
    pid = find_running_process_pid(executable)
    if pid is None:
        return False
    try:
        gi.require_version("Wnck", "3.0")
        from gi.repository import Wnck
    except (ValueError, ImportError):
        return False
    screen = Wnck.Screen.get_default()
    if screen is None:
        return False
    screen.force_update()
    for window in screen.get_windows():
        if window.get_pid() == pid:
            window.activate(Gtk.get_current_event_time())
            return True
    return False


def _resolve_executable_target(target, working_directory=None):
    """Resolve a panel application target without invoking a shell."""
    target = os.path.expanduser(str(target or "").strip())
    working_directory = (os.path.expanduser(working_directory)
                         if working_directory else None)
    if os.path.isabs(target):
        executable = os.path.normpath(target)
    elif "/" in target:
        if not working_directory:
            raise ValueError(
                "使用相对程序路径时必须填写工作目录：{0}".format(target))
        executable = os.path.normpath(os.path.join(working_directory, target))
    else:
        local_candidate = (os.path.join(working_directory, target)
                           if working_directory else None)
        executable = (local_candidate if local_candidate and
                      os.path.isfile(local_candidate) else shutil.which(target))
        if executable is None:
            raise ValueError("找不到软件或命令：{0}".format(target))
    if not os.path.isfile(executable):
        raise ValueError("程序文件不存在：{0}".format(executable))
    if not os.access(executable, os.X_OK):
        raise ValueError(
            "程序文件不可执行，请先运行 chmod +x：{0}".format(executable))
    return os.path.abspath(executable)


def launch_panel_item(item, application_records=None, uri_launcher=None):
    item_type = item["type"]
    target = item["target"]
    if item_type == "application":
        records = (_application_records() if application_records is None
                   else application_records)
        app = next((record[2] for record in records
                    if record[1] == target), None)
        arguments = item.get("arguments", "").strip()
        working_directory = item.get("workingDirectory") or None
        run_as_admin = bool(item.get("runAsAdministrator"))
        direct_launch = (app is None or bool(arguments) or
                         bool(working_directory) or run_as_admin)
        executable = None
        if direct_launch or bool(item.get("activateIfRunning")):
            executable = (app.get_executable() if app is not None else
                          _resolve_executable_target(target, working_directory))
        if bool(item.get("activateIfRunning")) and _activate_running_application(
                executable):
            return
        if direct_launch:
            command = [executable] + shlex.split(arguments)
            if run_as_admin:
                pkexec = shutil.which("pkexec")
                if pkexec is None:
                    raise ValueError(
                        "系统未安装 pkexec，无法以管理员身份运行；请安装 pkexec 或 policykit-1。")
                command.insert(0, pkexec)
            launch_directory = working_directory
            if app is None and launch_directory is None:
                launch_directory = os.path.dirname(executable)
            subprocess.Popen(command, cwd=launch_directory, close_fds=True)
        else:
            # Desktop activation normally raises an existing application when
            # it supports the freedesktop activation protocol.
            app.launch([], None)
        return
    if item_type == "file" and not os.path.isfile(target):
        raise ValueError("文件不存在：{0}".format(target))
    if item_type == "folder" and not os.path.isdir(target):
        raise ValueError("文件夹不存在：{0}".format(target))
    if item_type == "folder":
        if uri_launcher is not None:
            uri_launcher(Gio.File.new_for_path(target).get_uri(), None)
        else:
            _launch_folder(target)
        return
    if item_type == "url" and item.get("browser"):
        browser = item["browser"]
        if os.path.isabs(browser):
            subprocess.Popen([browser, target], close_fds=True)
            return
        application = Gio.DesktopAppInfo.new(browser)
        if application is None:
            raise ValueError("找不到浏览器：{0}".format(browser))
        application.launch_uris([target], None)
        return
    launcher = uri_launcher or Gio.AppInfo.launch_default_for_uri
    launcher(
        target if item_type == "url" else Gio.File.new_for_path(target).get_uri(), None)


class QuickPanel(Gtk.Window):
    def __init__(self, on_closed=None):
        Gtk.Window.__init__(self, type=Gtk.WindowType.POPUP)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_resizable(False)
        self.set_border_width(12)
        self.set_name("crossgestures-quick-panel")
        self.store = PanelStore()
        self.config = None
        self.on_closed = on_closed
        self._closing = False
        self._editing = False
        self._dialog_active = False
        self._menu_action_invoked = False
        self._icon_cache = {}
        self._favicon_requested = set()
        self._shown_at = 0.0
        self._activated_once = False
        self._config_stamp = None
        self._config_changed = True
        self._grid = None
        self._watchdog_source = None
        self._layout_signature = None
        self._tile_width = 104
        self._tile_height = 92
        self._icon_size = 40
        self._grid_spacing = 8
        self.connect("key-press-event", self._key_press)
        self.connect("focus-in-event", self._focus_in)
        self.connect("focus-out-event", self._focus_out)

    def show_at(self, x, y):
        self._closing = False
        self._shown_at = time.monotonic()
        self._activated_once = False
        if self._watchdog_source is None:
            self._watchdog_source = GLib.timeout_add(500, self._watchdog_tick)
        self.config = self._load_config_if_changed()
        display = Gdk.Display.get_default()
        monitor = display.get_monitor_at_point(int(x), int(y))
        area = monitor.get_workarea()
        self._apply_monitor_layout(area)
        if self._grid is None or self._config_changed:
            self._rebuild_tiles()
        self.show_all()
        self.realize()
        width, height = self.get_size()
        left = max(area.x, min(int(x - width / 2), area.x + area.width - width))
        top = max(area.y, min(int(y - height / 2), area.y + area.height - height))
        self.move(left, top)
        self.present()

    def _apply_monitor_layout(self, area):
        # GTK coordinates are logical pixels, so work from the monitor's
        # logical short edge. Small screens shrink the 4x4 grid while large
        # unscaled screens gain a moderate enlargement; desktop scaling is
        # already accounted for by GDK.
        signature = panel_layout_for_area(area.width, area.height)
        if signature == self._layout_signature:
            return
        self._layout_signature = signature
        (self._tile_width, self._tile_height, self._icon_size,
         self._grid_spacing, border) = signature
        self.set_border_width(border)
        if self._grid is not None:
            self._config_changed = True

    def _rebuild_tiles(self):
        # Construct the replacement completely before touching the visible
        # grid. A bad icon or malformed item must never collapse the panel to
        # an empty black POPUP.
        grid = Gtk.Grid(row_spacing=self._grid_spacing,
                        column_spacing=self._grid_spacing)
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        for index, item in enumerate(self.config["slots"]):
            button = self._tile(index, item)
            grid.attach(button, index % 4, index // 4, 1, 1)
        child = self.get_child()
        if child:
            self.remove(child)
        self.add(grid)
        self._grid = grid
        self._config_changed = False

    def _load_config_if_changed(self):
        # 面板文件未变化时直接复用，避免每次弹出的重复读取与解析。
        stamp = (os.path.getmtime(self.store.path)
                 if os.path.exists(self.store.path) else None)
        if self.config is not None and stamp == self._config_stamp:
            self._config_changed = False
            return self.config
        self.config = self.store.load()["config"]
        self._config_stamp = (os.path.getmtime(self.store.path)
                               if os.path.exists(self.store.path) else stamp)
        self._config_changed = True
        return self.config

    def _focus_in(self, _widget, _event):
        # 只有确实获得过输入焦点的面板才允许看门狗自动关闭：焦点被系统
        # 拒绝时面板仍可中键关闭，不该"弹出来又自己消失"。
        self._activated_once = True
        return False

    def _watchdog_tick(self):
        if not self.get_visible():
            self._watchdog_source = None
            return GLib.SOURCE_REMOVE
        if (not self.editing and self._shown_at and
                time.monotonic() - self._shown_at > 3.0 and
                self._activated_once and not self.is_active()):
            # 失焦看门狗：截图工具等全屏覆盖层可能吞掉 focus-out 事件，
            # 非编辑状态失焦超过宽限期仍未收回时强制关闭。
            self._watchdog_source = None
            self.close_panel()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _request_favicon(self, item):
        key = item["target"]
        if key in self._favicon_requested:
            return
        self._favicon_requested.add(key)

        def ready():
            # 拿到新图标才重绘；菜单或编辑对话框打开时跳过（下次打开
            # 面板自然生效），避免重绘打断进行中的格子交互。
            if self.get_visible() and not self._editing:
                self._icon_cache.pop(
                    ("url", item["target"], self._icon_size), None)
                self._config_changed = True
                self._rebuild_tiles()
                self.show_all()

        _ensure_favicon(item, ready)

    def _tile(self, index, item):
        button = Gtk.Button()
        button.set_size_request(self._tile_width, self._tile_height)
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=max(4, int(round(self._grid_spacing * 0.75))))
        if item:
            box.pack_start(
                _icon_widget(item, size=self._icon_size,
                             icon_cache=self._icon_cache,
                             on_missing_favicon=(
                                 self._request_favicon
                                 if item["type"] == "url" else None)),
                True, True, 0)
            label = Gtk.Label(label=item["label"])
            label.set_ellipsize(3)
            # An ellipsized label still advertises its natural text width
            # unless max-width-chars is constrained. Keep the request tiny so
            # the fixed tile request owns the column width; GTK may allocate
            # the full tile and Pango then shows as many characters as fit.
            label.set_max_width_chars(1)
            label.set_single_line_mode(True)
            label.set_hexpand(True)
            box.pack_start(label, False, False, 0)
            details = (item.get("description") or
                       TYPE_LABELS[item["type"]] + "：" + item["target"])
            button.set_tooltip_text(item["label"] + "\n" + details)
        else:
            image = Gtk.Image.new_from_icon_name("list-add", Gtk.IconSize.DIALOG)
            image.set_pixel_size(self._icon_size)
            image.set_opacity(0.35)
            box.pack_start(image, True, True, 0)
            box.pack_start(Gtk.Label(label=""), False, False, 0)
        button.add(box)
        button.drag_dest_set(
            Gtk.DestDefaults.ALL, [_URI_LIST_TARGET], Gdk.DragAction.COPY)
        button.connect("drag-data-received", self._tile_drop_received, index)
        button.connect("button-press-event", self._tile_press, index, item)
        if item:
            button.connect("clicked", self._execute, item)
        return button

    def _tile_drop_received(self, _button, context, _x, _y, selection_data,
                            _info, time, index):
        uris = selection_data.get_uris()
        if context is not None:
            context.finish(bool(uris), False, time)
        self._apply_drop(index, uris)

    def _apply_drop(self, index, uris, desktop_lookup=None):
        # Mirrors the Windows panel: the drop slot must be free, additional
        # URIs fill the following free slots, and nothing is overwritten.
        if self.config is None or not uris:
            return
        if self.config["slots"][index] is not None:
            self._error("第 {0} 个格子已配置：请先右键删除，或拖到空格子。".format(
                index + 1))
            return
        if desktop_lookup is None:
            def desktop_lookup(desktop_id):
                return Gio.DesktopAppInfo.new(desktop_id) is not None
        slot = index
        added = 0
        for uri in uris:
            while slot < PANEL_SLOT_COUNT and self.config["slots"][slot] is not None:
                slot += 1
            if slot >= PANEL_SLOT_COUNT:
                self._error("没有更多空格子可以放置拖入的目标。")
                break
            item = panel_item_from_drop_uri(uri, desktop_lookup=desktop_lookup)
            if item is None:
                self._error("无法识别拖入的目标：{0}".format(uri))
                continue
            self.config["slots"][slot] = item
            slot += 1
            added += 1
        if not added:
            return
        self.store.save(self.config)
        x, y = self.get_position()
        self.show_at(x + self.get_size()[0] / 2, y + self.get_size()[1] / 2)

    @property
    def editing(self):
        # 供 X11 后端查询：编辑对话框/右键菜单打开期间手势全局可用。
        return self._editing or self._dialog_active

    def _tile_press(self, button, event, index, item):
        if event.button != 3:
            return False
        self._editing = True
        self._menu_action_invoked = False
        menu = Gtk.Menu()
        if item:
            edit = Gtk.MenuItem(label="编辑")
            edit.connect(
                "activate", lambda _item:
                QuickPanel._run_menu_action(self, self._edit, index))
            menu.append(edit)
            delete = Gtk.MenuItem(label="删除")
            delete.connect(
                "activate", lambda _item:
                QuickPanel._run_menu_action(self, self._delete, index))
            menu.append(delete)
        else:
            for item_type in PANEL_ITEM_TYPES:
                create = Gtk.MenuItem(label=TYPE_LABELS[item_type])
                create.connect(
                    "activate",
                    lambda _item, selected_type=item_type:
                    QuickPanel._run_menu_action(
                        self, self._edit, index, selected_type))
                menu.append(create)
        menu.show_all()
        menu.connect("deactivate", self._menu_deactivated)
        menu.popup_at_pointer(event)
        return True

    def _run_menu_action(self, callback, *arguments):
        self._menu_action_invoked = True
        callback(*arguments)

    def _menu_deactivated(self, _menu):
        self._editing = False

        def settle_menu_close():
            action_invoked = self._menu_action_invoked
            self._menu_action_invoked = False
            if not self.editing and not action_invoked:
                self.close_panel()
            return GLib.SOURCE_REMOVE

        # A managed toplevel can remain the WM's active window after a menu
        # consumes an outside click. Give an item activation one event-cycle
        # to mark itself, then close unconditionally only when no action ran.
        GLib.timeout_add(50, settle_menu_close)

    def _begin_dialog_stack(self):
        # Keep the low-latency override-redirect panel used by drag/drop and
        # input replay, but move it below the modal chain while editors are
        # open. This preserves panel input semantics without the three-window
        # pile-up seen with Xfwm.
        self._dialog_active = True
        self.set_keep_above(False)
        self.realize()
        window = self.get_window()
        if window is not None:
            window.lower()

    def _end_dialog_stack(self):
        self._dialog_active = False
        self.set_keep_above(True)
        if self.get_visible():
            self.present()

    def _edit(self, index, initial_type=None):
        self._editing = True
        self._begin_dialog_stack()
        try:
            dialog = PanelItemDialog(
                self, index, self.config["slots"][index],
                initial_type=initial_type)
            response = dialog.run()
            if response == Gtk.ResponseType.REJECT:
                dialog.destroy()
                self._delete(index)
                return
            while response == Gtk.ResponseType.OK:
                try:
                    self.config["slots"][index] = dialog.result_item()
                    self.store.save(self.config)
                    dialog.destroy()
                    x, y = self.get_position()
                    self.show_at(x + self.get_size()[0] / 2, y + self.get_size()[1] / 2)
                    return
                except ValueError as error:
                    message = Gtk.MessageDialog(
                        message_type=Gtk.MessageType.ERROR,
                        buttons=Gtk.ButtonsType.OK, text=str(error))
                    _configure_modal_child(message, dialog)
                    message.run()
                    message.destroy()
                    response = dialog.run()
            dialog.destroy()
        finally:
            self._editing = False
            self._end_dialog_stack()

    def _delete(self, index):
        self.config["slots"][index] = None
        self.store.save(self.config)
        x, y = self.get_position()
        self.show_at(x + self.get_size()[0] / 2, y + self.get_size()[1] / 2)

    def _execute(self, _button, item):
        self.close_panel()
        try:
            launch_panel_item(item)
        except (ValueError, GLib.Error) as error:
            self._error(str(error))

    @staticmethod
    def _error(text, parent=None):
        dialog = Gtk.MessageDialog(
            transient_for=parent, modal=False, message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE, text=text)
        dialog.connect("response", lambda widget, _response: widget.destroy())
        dialog.show_all()

    def _key_press(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_panel()
            return True
        return False

    def _focus_out(self, _widget, _event):
        if self.editing:
            return False
        GLib.idle_add(self.close_panel)
        return False

    def close_panel(self):
        if self._closing or not self.get_visible():
            return GLib.SOURCE_REMOVE
        self._closing = True
        self.hide()
        if self.on_closed:
            self.on_closed()
        return GLib.SOURCE_REMOVE

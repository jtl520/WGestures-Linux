"""GTK/WebKit host for the shared, bundled settings interface."""
from __future__ import unicode_literals

import io
import json
import os
import subprocess
import sys
import tempfile

import gi
gi.require_version("Gtk", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:
    gi.require_version("WebKit2", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2

from .settings_service import SettingsService


def ui_directory():
    package = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(package, "..", "settings-ui"),
                      os.path.join(package, "..", "..", "..", "settings-ui")):
        if os.path.isfile(os.path.join(candidate, "index.html")):
            return os.path.realpath(candidate)
    raise RuntimeError("未找到共享设置界面，请重新安装 CrossGestures。")


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        Gtk.ApplicationWindow.__init__(self, application=application, title="CrossGestures 设置")
        self.set_default_size(1050, 780)
        self.set_size_request(640, 500)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.service = SettingsService()
        self.entry_uri = Gio.File.new_for_path(os.path.join(ui_directory(), "index.html")).get_uri()
        manager = WebKit2.UserContentManager()
        manager.connect("script-message-received::crossgestures", self._message)
        manager.register_script_message_handler("crossgestures")
        self.web = WebKit2.WebView.new_with_user_content_manager(manager)
        self.web.get_settings().set_property("enable-developer-extras", False)
        self.web.get_settings().set_property("enable-html5-database", False)
        self.web.connect("decide-policy", self._policy)
        self.web.connect("permission-request", lambda _web, request: (request.deny(), True)[1])
        self.web.connect("context-menu", lambda *_args: True)
        self.add(self.web)
        self.connect("delete-event", self._delete)
        self.connect("window-state-event", self._state_changed)
        self.web.load_uri(self.entry_uri)

    def _policy(self, _web, decision, kind):
        if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri()
            if uri != self.entry_uri:
                decision.ignore()
                return True
        return False

    def _delete(self, *_args):
        # The daemon is independent. Destroying the view releases WebKit processes.
        return False

    def _state_changed(self, _window, event):
        if (self.service.settings.get("minimize-to-tray") and
                event.changed_mask & Gdk.WindowState.ICONIFIED and
                event.new_window_state & Gdk.WindowState.ICONIFIED):
            self.hide()
        return False

    def _message(self, _manager, result):
        message = None
        try:
            if self.web.get_uri() != self.entry_uri:
                return
            message = json.loads(result.get_js_value().to_string())
            if not isinstance(message, dict) or not isinstance(message.get("id"), int):
                raise ValueError("无效设置请求。")
            params = message.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("无效设置参数。")
            value = self.dispatch(message.get("method"), params)
            response = {"id": message["id"], "result": value}
        except Exception as error:
            response = {"id": message.get("id") if isinstance(message, dict) else None, "error": str(error)}
        script = "window.CrossGesturesNative.receive(" + json.dumps(response, ensure_ascii=True) + ");"
        self.web.run_javascript(script, None, None, None)

    def dispatch(self, method, params):
        if method == "snapshot":
            return self.service.snapshot()
        if method == "recognize":
            return self.service.recognize(params.get("points"))
        if method == "legacy":
            # Kept for old imported middle-button gestures and legacy import selection.
            from .prefs import PreferencesWindow
            window = PreferencesWindow(self.get_application())
            window.set_transient_for(self)
            window.show_all()
            return None
        if method in ("export", "importPreview"):
            save = method == "export"
            dialog = Gtk.FileChooserDialog(title="导出配置" if save else "导入配置", transient_for=self,
                                           action=Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN)
            dialog.add_buttons("取消", Gtk.ResponseType.CANCEL, "保存" if save else "打开", Gtk.ResponseType.OK)
            file_filter = Gtk.FileFilter()
            file_filter.set_name("CrossGestures 配置")
            file_filter.add_pattern("*.cgestures")
            if not save:
                file_filter.add_pattern("*.wg2")
            dialog.add_filter(file_filter)
            if save:
                dialog.set_do_overwrite_confirmation(True)
                dialog.set_current_name("CrossGestures.cgestures")
            path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
            dialog.destroy()
            if not path:
                return None
            if not save:
                if os.path.getsize(path) > 10 * 1024 * 1024:
                    raise ValueError("配置文件不能超过 10 MB。")
                with io.open(path, "r", encoding="utf-8-sig") as stream:
                    return self.service.prepare_import(stream.read())
            text = self.service.export(params.get("profileId", "global"))
            descriptor, temporary = tempfile.mkstemp(prefix=".crossgestures-", dir=os.path.dirname(path))
            try:
                with io.open(descriptor, "w", encoding="utf-8", closefd=True) as stream:
                    stream.write(text)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return {"message": "已导出当前应用配置。"}
        return self.service.mutate(method, params)


class SettingsApplication(Gtk.Application):
    def __init__(self):
        Gtk.Application.__init__(self, application_id="com.jtl520.CrossGestures.Settings",
                                 flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        window = next((w for w in self.get_windows() if isinstance(w, SettingsWindow)), None)
        if window is None:
            window = SettingsWindow(self)
        window.deiconify()
        window.show_all()
        window.present()


def run_preferences():
    return SettingsApplication().run([])

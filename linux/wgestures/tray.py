from __future__ import unicode_literals

import os
import subprocess
import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


class X11TrayIcon(object):
    """X11 tray menu with AppIndicator and Gtk.StatusIcon fallbacks."""

    def __init__(self, settings, on_quit, on_show_panel=None):
        self.settings = settings
        self.on_quit = on_quit
        self.on_show_panel = on_show_panel
        self.indicator = None
        self._indicator_module = None
        self.status_icon = None
        self._syncing = False
        self.menu = Gtk.Menu()

        self.status_item = Gtk.MenuItem.new_with_label("CrossGestures")
        self.status_item.set_sensitive(False)
        self.menu.append(self.status_item)
        self.menu.append(Gtk.SeparatorMenuItem())

        self.enabled_item = Gtk.CheckMenuItem.new_with_label("启用鼠标手势")
        self.enabled_item.connect("toggled", self._enabled_toggled)
        self.menu.append(self.enabled_item)
        self.paused_item = Gtk.CheckMenuItem.new_with_label("暂停")
        self.paused_item.connect("toggled", self._paused_toggled)
        self.menu.append(self.paused_item)
        panel_item = Gtk.MenuItem.new_with_label("弹出快捷面板")
        panel_item.connect("activate", self._show_panel)
        self.menu.append(panel_item)
        self.menu.append(Gtk.SeparatorMenuItem())

        settings_item = Gtk.MenuItem.new_with_label("打开设置")
        settings_item.connect("activate", self._open_settings)
        self.menu.append(settings_item)
        quit_item = Gtk.MenuItem.new_with_label("退出后台（下次登录仍自启）")
        quit_item.connect("activate", lambda _item: self.on_quit())
        self.menu.append(quit_item)
        self.menu.show_all()

        if not self._create_app_indicator():
            self._create_status_icon()
        self.settings.connect("enabled", self.sync)
        self.settings.connect("paused", self.sync)
        self.sync()

    def _create_app_indicator(self):
        module = None
        try:
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3
            module = AyatanaAppIndicator3
        except (ImportError, ValueError):
            try:
                gi.require_version("AppIndicator3", "0.1")
                from gi.repository import AppIndicator3
                module = AppIndicator3
            except (ImportError, ValueError):
                return False
        self.indicator = module.Indicator.new(
            "wgestures", "input-mouse", module.IndicatorCategory.APPLICATION_STATUS)
        self._indicator_module = module
        self.indicator.set_status(module.IndicatorStatus.ACTIVE)
        self.indicator.set_menu(self.menu)
        return True

    def _create_status_icon(self):
        self.status_icon = Gtk.StatusIcon.new_from_icon_name("input-mouse")
        self.status_icon.set_title("CrossGestures")
        self.status_icon.set_tooltip_text("CrossGestures 鼠标手势")
        self.status_icon.connect("activate", self._open_settings)
        self.status_icon.connect("popup-menu", self._popup_menu)
        self.status_icon.set_visible(True)

    def _popup_menu(self, icon, button, activate_time):
        self.menu.popup(None, None, Gtk.StatusIcon.position_menu,
                        icon, button, activate_time)

    def _enabled_toggled(self, item):
        if not self._syncing:
            self.settings.set("enabled", item.get_active())

    def _paused_toggled(self, item):
        if not self._syncing:
            self.settings.set("paused", item.get_active())

    def _show_panel(self, _item):
        if self.on_show_panel is not None:
            self.on_show_panel()

    def sync(self):
        enabled = bool(self.settings.get("enabled"))
        paused = bool(self.settings.get("paused"))
        self._syncing = True
        self.enabled_item.set_active(enabled)
        self.paused_item.set_active(paused)
        self.paused_item.set_sensitive(enabled)
        if not enabled:
            status = "状态：已禁用"
        elif paused:
            status = "状态：已暂停"
        else:
            status = "状态：运行中"
        self.status_item.set_label(status)
        self._syncing = False

    @staticmethod
    def _open_settings(_item=None):
        main_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")
        try:
            with open(os.devnull, "wb") as sink:
                subprocess.Popen(
                    [sys.executable, main_path, "--settings"],
                    stdin=sink, stdout=sink, stderr=sink,
                    close_fds=True, start_new_session=True)
        except OSError:
            pass

    def destroy(self):
        if self.indicator is not None:
            try:
                self.indicator.set_status(
                    self._indicator_module.IndicatorStatus.PASSIVE)
            except AttributeError:
                pass
            self.indicator = None
            self._indicator_module = None
        if self.status_icon is not None:
            self.status_icon.set_visible(False)
            self.status_icon = None
        self.menu.destroy()

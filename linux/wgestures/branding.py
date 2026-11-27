"""Shared icon names and source-tree/installed GTK icon lookup."""
from __future__ import unicode_literals

import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

APP_ICON = "crossgestures"
WINDOW_CLASS = "com.jtl520.CrossGestures.Settings"


def register_icons():
    source = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "branding", "icons"))
    theme = Gtk.IconTheme.get_default()
    if os.path.isdir(source):
        if theme is not None and source not in theme.get_search_path():
            theme.prepend_search_path(source)
        return os.path.join(source, "hicolor")
    return "/usr/share/icons/hicolor"


def set_window_icon(window):
    register_icons()
    Gtk.Window.set_default_icon_name(APP_ICON)
    window.set_icon_name(APP_ICON)
    # Match the desktop entry so GNOME groups the window with its launcher.
    window.set_wmclass(WINDOW_CLASS, WINDOW_CLASS)


def tray_icon_name(enabled, paused):
    suffix = "-disabled" if not enabled else "-paused" if paused else ""
    return "crossgestures-tray{0}-symbolic".format(suffix)

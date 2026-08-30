from __future__ import unicode_literals


SCHEMA_ID = "org.gnome.shell.extensions.wgestures"
DEFAULTS = {
    "enabled": True,
    "paused": False,
    "autostart-enabled": True,
    "minimize-to-tray": True,
    "trigger-buttons": ["right"],
    "middle-panel-enabled": True,
    "direction-mode": 8,
    "start-threshold": 8,
    "segment-threshold": 12,
    "path-color": "#27ae60",
    "invalid-path-color": "#e74c3c",
    "path-width": 4.0,
    "fade-duration": 300,
    "show-command-name": True,
    "config-revision": 0,
}


class Settings(object):
    def __init__(self):
        self._fallback = dict(DEFAULTS)
        self._settings = None
        self.error = None
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio
            source = Gio.SettingsSchemaSource.get_default()
            schema = source.lookup(SCHEMA_ID, True) if source else None
            if schema is None:
                raise RuntimeError("GSettings schema is not installed")
            self._settings = Gio.Settings.new_full(schema, None, None)
        except (ImportError, ValueError, RuntimeError) as error:
            self.error = str(error)
        self._migrate_middle_button()

    def _migrate_middle_button(self):
        buttons = list(self.get("trigger-buttons"))
        if "middle" not in buttons:
            return
        self.set("middle-panel-enabled", True)
        self.set("trigger-buttons", [item for item in buttons if item != "middle"])

    @property
    def available(self):
        return self._settings is not None

    def get(self, key):
        if not self._settings:
            value = self._fallback[key]
            return list(value) if isinstance(value, list) else value
        variant = self._settings.get_value(key)
        return variant.unpack()

    def set(self, key, value):
        if not self._settings:
            self._fallback[key] = value
            return False
        from gi.repository import Gio, GLib
        signatures = {
            "enabled": "b", "paused": "b", "autostart-enabled": "b",
            "minimize-to-tray": "b", "trigger-buttons": "as",
            "middle-panel-enabled": "b",
            "direction-mode": "i", "start-threshold": "i",
            "segment-threshold": "i", "path-color": "s",
            "invalid-path-color": "s", "path-width": "d",
            "fade-duration": "i", "show-command-name": "b",
            "config-revision": "u",
        }
        changed = self._settings.set_value(key, GLib.Variant(signatures[key], value))
        if changed:
            Gio.Settings.sync()
        return changed

    def connect(self, key, callback):
        if not self._settings:
            return None
        return self._settings.connect("changed::{0}".format(key),
                                      lambda *_args: callback())

    def bump_revision(self):
        revision = (int(self.get("config-revision")) + 1) & 0xffffffff
        self.set("config-revision", revision)
        return revision

from __future__ import unicode_literals

import os
import tempfile


AUTOSTART_FILENAME = "wgestures-autostart.desktop"


def autostart_path():
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(config_home, "autostart", AUTOSTART_FILENAME)


def session_autostart_enabled(default=True):
    path = autostart_path()
    try:
        with open(path, "r") as stream:
            values = {}
            for raw_line in stream:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip().lower()] = value.strip().lower()
        if values.get("hidden") == "true":
            return False
        if values.get("x-gnome-autostart-enabled") == "false":
            return False
        return True
    except OSError:
        return bool(default)


def set_session_autostart(enabled):
    """Atomically write the per-user override for the system autostart entry."""
    path = autostart_path()
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory, 0o700)
    value = "true" if enabled else "false"
    contents = "\n".join((
        "[Desktop Entry]",
        "Type=Application",
        "Name=WGestures Session Backend",
        "Exec=wgestures --daemon",
        "TryExec=wgestures",
        "Icon=input-mouse",
        "Terminal=false",
        "NoDisplay=true",
        "Hidden={0}".format("false" if enabled else "true"),
        "X-GNOME-Autostart-enabled={0}".format(value),
        "",
    ))
    descriptor, temporary = tempfile.mkstemp(
        prefix=AUTOSTART_FILENAME + ".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path

from __future__ import unicode_literals

import io
import json
import os
import shutil
import tempfile

from .config import create_default_config, normalize_config


def config_directory():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, "wgestures")


def config_path():
    return os.path.join(config_directory(), "gestures-v1.json")


def runtime_directory():
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return os.path.join(base, "wgestures")
    identity = os.getuid() if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
    return os.path.join(tempfile.gettempdir(), "wgestures-{0}".format(identity))


def runtime_status_path():
    return os.path.join(runtime_directory(), "x11-status.json")


class ConfigStore(object):
    def __init__(self, path=None):
        self.path = path or config_path()
        self.directory = os.path.dirname(self.path)

    @staticmethod
    def _read(path):
        with io.open(path, "r", encoding="utf-8") as stream:
            return json.load(stream)

    def load(self):
        if not os.path.isdir(self.directory):
            os.makedirs(self.directory, 0o700)
        if not os.path.exists(self.path):
            defaults = create_default_config()
            self.save(defaults, create_backup=False)
            return {"config": defaults, "warnings": [], "source": "defaults"}
        try:
            result = normalize_config(self._read(self.path))
            result["source"] = "primary"
            return result
        except (OSError, ValueError, TypeError) as primary_error:
            backup_path = self.path + ".bak"
            if os.path.exists(backup_path):
                try:
                    result = normalize_config(self._read(backup_path))
                    result["warnings"].insert(
                        0, "主配置损坏，已从备份恢复：{0}".format(primary_error))
                    result["source"] = "backup"
                    self.save(result["config"], create_backup=False)
                    return result
                except (OSError, ValueError, TypeError):
                    pass
            defaults = create_default_config()
            self.save(defaults, create_backup=False)
            return {
                "config": defaults,
                "warnings": ["配置损坏，已恢复默认值：{0}".format(primary_error)],
                "source": "defaults-recovery",
            }

    def save(self, config, create_backup=True):
        normalized = normalize_config(config)["config"]
        if not os.path.isdir(self.directory):
            os.makedirs(self.directory, 0o700)
        if create_backup and os.path.exists(self.path):
            try:
                normalize_config(self._read(self.path))
                backup_temp = self.path + ".bak.tmp"
                shutil.copyfile(self.path, backup_temp)
                os.replace(backup_temp, self.path + ".bak")
            except (OSError, ValueError, TypeError):
                pass
        descriptor, temp_path = tempfile.mkstemp(
            prefix="gestures-v1.", suffix=".tmp", dir=self.directory)
        try:
            with io.open(descriptor, "w", encoding="utf-8", closefd=True) as stream:
                json.dump(normalized, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
            try:
                directory_fd = os.open(self.directory, os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except (AttributeError, OSError):
                pass
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        return normalized

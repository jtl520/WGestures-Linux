from __future__ import unicode_literals

import io
import json
import os
import shutil
import tempfile

try:
    from urllib.parse import urlparse
    from urllib.request import url2pathname
except ImportError:  # pragma: no cover - Python 2 compatibility is not required.
    from urlparse import urlparse
    from urllib import url2pathname

from .storage import config_directory


PANEL_SCHEMA_VERSION = 1
PANEL_SLOT_COUNT = 16
PANEL_ITEM_TYPES = ("application", "file", "folder", "url")


def create_default_panel():
    return {"schemaVersion": PANEL_SCHEMA_VERSION,
            "slots": [None for _index in range(PANEL_SLOT_COUNT)]}


def _valid_target(item_type, target):
    if not target:
        return False
    if item_type == "application":
        # Accept an installed Desktop ID, a command on PATH, an absolute
        # executable path, or a relative path resolved against
        # workingDirectory by the launcher.
        return "\\" not in target
    if item_type in ("file", "folder"):
        return os.path.isabs(target)
    if item_type == "url":
        parsed = urlparse(target)
        return parsed.scheme.lower() in ("http", "https") and bool(parsed.netloc)
    return False


def normalize_panel(raw):
    if not isinstance(raw, dict) or raw.get("schemaVersion") != PANEL_SCHEMA_VERSION:
        raise ValueError("Unsupported panel configuration schema: {0}".format(
            raw.get("schemaVersion") if isinstance(raw, dict) else None))
    raw_slots = raw.get("slots")
    if not isinstance(raw_slots, list):
        raise ValueError("Panel slots must be an array")
    warnings = []
    slots = []
    seen_ids = set()
    for index in range(PANEL_SLOT_COUNT):
        item = raw_slots[index] if index < len(raw_slots) else None
        if item is None:
            slots.append(None)
            continue
        if not isinstance(item, dict):
            warnings.append("已忽略第 {0} 个无效面板格子".format(index + 1))
            slots.append(None)
            continue
        item_type = str(item.get("type") or "").strip()
        target = str(item.get("target") or "").strip()
        if item_type not in PANEL_ITEM_TYPES or not _valid_target(item_type, target):
            warnings.append("已忽略第 {0} 个目标无效的面板格子".format(index + 1))
            slots.append(None)
            continue
        item_id = str(item.get("id") or "slot-{0}".format(index + 1)).strip()
        if not item_id or item_id in seen_ids:
            item_id = "slot-{0}".format(index + 1)
        seen_ids.add(item_id)
        label = str(item.get("label") or "").strip()
        normalized_item = {
            "id": item_id,
            "label": label or default_panel_label(item_type, target),
            "type": item_type,
            "target": target,
        }
        for key in ("description", "arguments", "workingDirectory", "browser"):
            value = str(item.get(key) or "").strip()
            if value:
                normalized_item[key] = value
        working_directory = normalized_item.get("workingDirectory")
        if working_directory and not os.path.isabs(working_directory):
            warnings.append("已忽略第 {0} 个格子的无效工作目录".format(index + 1))
            normalized_item.pop("workingDirectory", None)
        browser = normalized_item.get("browser")
        if browser and "/" in browser and not os.path.isabs(browser):
            warnings.append("已忽略第 {0} 个格子的无效浏览器".format(index + 1))
            normalized_item.pop("browser", None)
        if bool(item.get("runAsAdministrator")):
            normalized_item["runAsAdministrator"] = True
        if bool(item.get("activateIfRunning")):
            normalized_item["activateIfRunning"] = True
        slots.append(normalized_item)
    if len(raw_slots) != PANEL_SLOT_COUNT:
        warnings.append("面板格子数量已调整为 16 个")
    return {"config": {"schemaVersion": PANEL_SCHEMA_VERSION, "slots": slots},
            "warnings": warnings}


def default_panel_label(item_type, target):
    if item_type == "url":
        return urlparse(target).netloc or target
    if item_type == "application":
        if "/" in target:
            return os.path.basename(target.rstrip(os.sep)) or target
        value = target[:-8] if target.endswith(".desktop") else target
        return value.rsplit(".", 1)[-1] or target
    value = target.rstrip(os.sep)
    return os.path.basename(value) or target


def _default_process_scan():
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with io.open("/proc/" + entry + "/comm", "r",
                         encoding="utf-8", errors="replace") as stream:
                name = stream.read().strip()
        except OSError:
            continue
        if name:
            yield int(entry), name


def find_running_process_pid(executable, scan=None):
    # /proc comm is truncated by the kernel to 15 visible characters, so a
    # long executable name only ever matches its prefix.
    name = os.path.basename(str(executable or "").strip())
    if not name:
        return None
    for pid, process_name in (scan if scan is not None
                              else _default_process_scan()):
        if process_name == name[:15]:
            return pid
    return None


def panel_config_path():
    return os.path.join(config_directory(), "panel-v1.json")


def panel_item_from_drop_uri(uri, desktop_lookup=None):
    """Turn one text/uri-list entry into a panel item dict, or None.

    Directories become folder targets, .desktop launchers become their
    Desktop ID (validated through desktop_lookup when provided), regular
    files become file targets, and HTTP/HTTPS links become url targets.
    """
    value = str(uri or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    if scheme in ("http", "https"):
        return {"type": "url", "target": value} if _valid_target(
            "url", value) else None
    if scheme not in ("", "file"):
        return None
    path = os.path.normpath(
        value if scheme == "" else url2pathname(parsed.path))
    if not os.path.isabs(path):
        return None
    if os.path.isdir(path):
        return {"type": "folder", "target": path}
    if path.endswith(".desktop"):
        if not os.path.isfile(path):
            return None
        desktop_id = os.path.basename(path)
        if desktop_lookup is not None and not desktop_lookup(desktop_id):
            return None
        return {"type": "application", "target": desktop_id}
    if os.path.isfile(path):
        return {"type": "file", "target": path}
    return None


class PanelStore(object):
    def __init__(self, path=None):
        self.path = path or panel_config_path()
        self.directory = os.path.dirname(self.path)

    @staticmethod
    def _read(path):
        with io.open(path, "r", encoding="utf-8") as stream:
            return json.load(stream)

    def load(self):
        if not os.path.isdir(self.directory):
            os.makedirs(self.directory, 0o700)
        if not os.path.exists(self.path):
            defaults = create_default_panel()
            self.save(defaults, create_backup=False)
            return {"config": defaults, "warnings": [], "source": "defaults"}
        try:
            result = normalize_panel(self._read(self.path))
            result["source"] = "primary"
            return result
        except (OSError, ValueError, TypeError) as primary_error:
            backup_path = self.path + ".bak"
            if os.path.exists(backup_path):
                try:
                    result = normalize_panel(self._read(backup_path))
                    result["warnings"].insert(
                        0, "面板主配置损坏，已从备份恢复：{0}".format(primary_error))
                    result["source"] = "backup"
                    self.save(result["config"], create_backup=False)
                    return result
                except (OSError, ValueError, TypeError):
                    pass
            defaults = create_default_panel()
            self.save(defaults, create_backup=False)
            return {"config": defaults,
                    "warnings": ["面板配置损坏，已恢复为空面板：{0}".format(primary_error)],
                    "source": "defaults-recovery"}

    def save(self, config, create_backup=True):
        normalized = normalize_panel(config)["config"]
        if not os.path.isdir(self.directory):
            os.makedirs(self.directory, 0o700)
        if create_backup and os.path.exists(self.path):
            try:
                normalize_panel(self._read(self.path))
                backup_temp = self.path + ".bak.tmp"
                shutil.copyfile(self.path, backup_temp)
                os.replace(backup_temp, self.path + ".bak")
            except (OSError, ValueError, TypeError):
                pass
        descriptor, temporary = tempfile.mkstemp(
            prefix="panel-v1.", suffix=".tmp", dir=self.directory)
        try:
            with io.open(descriptor, "w", encoding="utf-8", closefd=True) as stream:
                json.dump(normalized, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return normalized

FAVICON_MAX_BYTES = 256 * 1024

_FAVICON_MAGICS = (
    bytes((0x89, 0x50, 0x4E, 0x47)),   # PNG
    bytes((0x00, 0x00, 0x01, 0x00)),   # ICO
    bytes((0xFF, 0xD8, 0xFF)),         # JPEG
    bytes((0x47, 0x49, 0x46)),         # GIF
    bytes((0x42, 0x4D)),               # BMP
)


def favicon_url(target):
    # 站点图标地址：直接向目标网站请求 /favicon.ico，不经第三方服务。
    parsed = urlparse(str(target or "").strip())
    host = (parsed.netloc or "").strip().lower()
    if parsed.scheme.lower() not in ("http", "https") or not host:
        return None
    return "https://" + host + "/favicon.ico"


def is_valid_favicon(data):
    # 校验下载内容：常见图片格式且大小合理，防止把错误页存成图标。
    if not isinstance(data, (bytes, bytearray)):
        return False
    if len(data) < 24 or len(data) > FAVICON_MAX_BYTES:
        return False
    prefix = bytes(data[:4])
    return any(prefix.startswith(magic) for magic in _FAVICON_MAGICS)


def favicon_cache_path(cache_directory, target):
    parsed = urlparse(str(target or "").strip())
    host = (parsed.netloc or "").strip().lower()
    if parsed.scheme.lower() not in ("http", "https") or not host:
        return None
    return os.path.join(cache_directory, host + ".ico")

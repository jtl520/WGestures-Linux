from __future__ import print_function, unicode_literals

import json
import os
import platform
import re
import subprocess

from . import __version__
from .settings import Settings
from .storage import ConfigStore, runtime_status_path


def _os_release():
    values = {}
    try:
        with open("/etc/os-release", "r") as stream:
            for raw_line in stream:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    except OSError:
        pass
    return values


def _command_output(command):
    try:
        return subprocess.check_output(
            command, stderr=subprocess.STDOUT,
            universal_newlines=True, timeout=3).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def gnome_shell_major():
    output = _command_output(["gnome-shell", "--version"])
    match = re.search(r"(\d+)(?:\.\d+)?", output)
    return int(match.group(1)) if match else None


def select_backend(session_type=None, desktop=None, shell_major=None):
    session_type = (session_type or os.environ.get("XDG_SESSION_TYPE") or "").lower()
    desktop = (desktop or os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
    if session_type == "x11":
        return "x11", None
    if session_type == "wayland" and "gnome" in desktop and shell_major == 46:
        return "gnome46-wayland", None
    if session_type == "wayland":
        return "unsupported", "Wayland 会话仅支持 GNOME Shell 46"
    return "unsupported", "无法识别图形会话；请在桌面登录会话中运行"


def collect_diagnostics(probe_x11=True):
    release = _os_release()
    session_type = os.environ.get("XDG_SESSION_TYPE", "")
    if not session_type and os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        session_type = "x11"
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    shell_major = gnome_shell_major() if "gnome" in desktop.lower() else None
    backend, unsupported_reason = select_backend(session_type, desktop, shell_major)
    settings = Settings()
    loaded = ConfigStore().load()
    dependencies = {}
    for name, module_name in (
            ("gi", "gi"), ("pythonXlib", "Xlib"), ("cairo", "cairo")):
        try:
            __import__(module_name)
            dependencies[name] = True
        except ImportError:
            dependencies[name] = False
    x11 = {
        "display": os.environ.get("DISPLAY", ""),
        "connected": False,
        "xtest": False,
        "triggerGrabStatus": "not-probed",
        "error": None,
        "daemon": None,
    }
    if probe_x11 and backend == "x11" and dependencies.get("pythonXlib"):
        try:
            from Xlib import display
            connection = display.Display()
            extension = connection.query_extension("XTEST")
            x11["connected"] = True
            x11["xtest"] = bool(extension and getattr(extension, "present", False))
            x11["triggerGrabStatus"] = "checked-when-daemon-starts"
            connection.close()
        except Exception as error:  # Xlib uses several protocol exception types.
            x11["error"] = str(error)
    try:
        with open(runtime_status_path(), "r") as stream:
            status = json.load(stream)
        os.kill(int(status["pid"]), 0)
        x11["daemon"] = status
        x11["triggerGrabStatus"] = status.get("triggerGrabStatus", "active")
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {
        "version": __version__,
        "distribution": release.get("ID", platform.system().lower()),
        "distributionVersion": release.get("VERSION_ID", ""),
        "distributionName": release.get("PRETTY_NAME", ""),
        "sessionType": session_type or "unknown",
        "desktop": desktop or "unknown",
        "gnomeShellMajor": shell_major,
        "backend": backend,
        "unsupportedReason": unsupported_reason,
        "dependencies": dependencies,
        "gsettings": {"available": settings.available, "error": settings.error},
        "configuration": {
            "path": ConfigStore().path,
            "status": loaded.get("source", "unknown"),
            "warnings": loaded.get("warnings", []),
        },
        "x11": x11,
    }


def format_diagnostics(data):
    lines = [
        "WGestures {0}".format(data["version"]),
        "系统: {0}".format(data["distributionName"] or data["distribution"]),
        "桌面/会话: {0} / {1}".format(data["desktop"], data["sessionType"]),
        "后端: {0}".format(data["backend"]),
        "配置: {0} ({1})".format(
            data["configuration"]["path"], data["configuration"]["status"]),
        "GSettings: {0}".format("正常" if data["gsettings"]["available"] else "不可用"),
    ]
    if data.get("unsupportedReason"):
        lines.append("不支持原因: {0}".format(data["unsupportedReason"]))
    if data["backend"] == "x11":
        lines.append("X11/XTEST: {0}/{1}".format(
            "已连接" if data["x11"]["connected"] else "未连接",
            "可用" if data["x11"]["xtest"] else "不可用"))
        lines.append("按钮抓取: {0}".format(data["x11"]["triggerGrabStatus"]))
    missing = [key for key, value in data["dependencies"].items() if not value]
    if missing:
        lines.append("缺少依赖: {0}".format(", ".join(missing)))
    for warning in data["configuration"]["warnings"]:
        lines.append("配置警告: {0}".format(warning))
    return "\n".join(lines)


def diagnostics_json(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)

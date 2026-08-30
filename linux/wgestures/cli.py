from __future__ import print_function, unicode_literals

import argparse
import os
import subprocess
import sys

from .diagnostics import collect_diagnostics, diagnostics_json, format_diagnostics
from .settings import Settings


UUID = "wgestures@yingdev.com"


def _detach_background_gui_stdio():
    """Keep a background-launched GTK window out of terminal job control.

    ``wgestures --settings &`` is a common way to open the preferences from
    a root Kali terminal.  GTK and its image helpers inherit that terminal;
    if any helper reads it, the shell stops the entire background process
    group with SIGTTIN and the already drawn window appears frozen.  Desktop
    launchers have no controlling terminal, and foreground terminal launches
    keep their streams unchanged.
    """
    try:
        stdin_fd = sys.stdin.fileno()
        if (not os.isatty(stdin_fd) or not hasattr(os, "tcgetpgrp") or
                os.tcgetpgrp(stdin_fd) == os.getpgrp()):
            return False
    except (AttributeError, OSError, ValueError):
        return False

    descriptors = (
        (stdin_fd, os.O_RDONLY),
        (sys.stdout.fileno(), os.O_WRONLY),
        (sys.stderr.fileno(), os.O_WRONLY),
    )
    for descriptor, flags in descriptors:
        null_fd = os.open(os.devnull, flags)
        try:
            os.dup2(null_fd, descriptor)
        finally:
            os.close(null_fd)
    return True


def _run_quiet(command):
    try:
        return subprocess.call(command) == 0
    except OSError:
        return False


def _set_enabled(value, diagnostics):
    settings = Settings()
    if not settings.available:
        print("GSettings 不可用：{0}".format(settings.error), file=sys.stderr)
        return 4
    settings.set("enabled", value)
    if diagnostics["backend"] == "gnome46-wayland":
        command = ["gnome-extensions", "enable" if value else "disable", UUID]
        if not _run_quiet(command):
            print("GNOME Shell 尚未发现扩展；首次安装后请注销并重新登录。",
                  file=sys.stderr)
            return 2
    elif value and diagnostics["backend"] == "x11" and \
            diagnostics["x11"].get("daemon") is None:
        main_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")
        with open(os.devnull, "wb") as sink:
            subprocess.Popen(
                [sys.executable, main_path, "--daemon"],
                stdin=sink, stdout=sink, stderr=sink,
                close_fds=True, start_new_session=True)
    return 0


def _daemon():
    diagnostics = collect_diagnostics()
    if diagnostics["backend"] == "gnome46-wayland":
        return 0
    if diagnostics["backend"] != "x11":
        print(diagnostics["unsupportedReason"], file=sys.stderr)
        return 3
    try:
        import fcntl
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
        lock_path = os.path.join(runtime_dir, "wgestures-{0}.lock".format(os.getuid()))
        lock = open(lock_path, "w")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            return 0
        from .x11_backend import X11Backend
        return X11Backend().run()
    except ImportError as error:
        print("X11 后端缺少依赖：{0}".format(error), file=sys.stderr)
        return 4
    except Exception as error:
        print("X11 后端启动失败：{0}".format(error), file=sys.stderr)
        return 5


def _settings(diagnostics):
    if diagnostics["backend"] == "gnome46-wayland":
        try:
            return subprocess.call(["gnome-extensions", "prefs", UUID])
        except OSError:
            print("GNOME Shell 尚未发现扩展，先打开兼容设置界面；请注销并重新登录后再启用扩展。",
                  file=sys.stderr)
    try:
        settings = Settings()
        if not settings.available:
            print("GSettings 不可用：{0}".format(settings.error), file=sys.stderr)
            return 4
        from .prefs import run_preferences
        return run_preferences()
    except ImportError as error:
        print("设置界面缺少 GTK3/PyGObject：{0}".format(error), file=sys.stderr)
        return 4


def build_parser():
    parser = argparse.ArgumentParser(description="CrossGestures Linux control utility")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--daemon", action="store_true", help=argparse.SUPPRESS)
    group.add_argument("--settings", action="store_true", help="打开设置")
    group.add_argument("--enable", action="store_true", help="启用手势")
    group.add_argument("--disable", action="store_true", help="禁用手势")
    group.add_argument("--pause", action="store_true", help="临时暂停")
    group.add_argument("--resume", action="store_true", help="恢复")
    group.add_argument("--status", action="store_true", help="显示状态")
    group.add_argument("--diagnose", action="store_true", help="运行环境诊断")
    group.add_argument("--panel-edit", type=int, metavar="INDEX", help=argparse.SUPPRESS)
    group.add_argument("--panel-fetch-icon", metavar="URL", help=argparse.SUPPRESS)
    parser.add_argument(
        "--panel-type", choices=("application", "file", "folder", "url"),
        help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="诊断输出 JSON")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    opens_settings = args.settings or not any((
        args.daemon, args.enable, args.disable, args.pause, args.resume,
        args.status, args.diagnose, args.panel_edit is not None,
        args.panel_fetch_icon is not None))
    if opens_settings:
        _detach_background_gui_stdio()
    if args.daemon:
        return _daemon()
    if args.panel_edit is not None:
        try:
            from .panel_ui import edit_panel_slot
            return edit_panel_slot(args.panel_edit, initial_type=args.panel_type)
        except (ImportError, ValueError) as error:
            print("无法编辑面板格子：{0}".format(error), file=sys.stderr)
            return 4
    if args.panel_fetch_icon is not None:
        try:
            from .panel_ui import fetch_favicon
            return 0 if fetch_favicon(args.panel_fetch_icon) else 4
        except (ImportError, ValueError):
            return 4
    diagnostics = collect_diagnostics()
    settings = Settings()
    if args.enable:
        return _set_enabled(True, diagnostics)
    if args.disable:
        return _set_enabled(False, diagnostics)
    if args.pause:
        if not settings.available:
            print("GSettings 不可用：{0}".format(settings.error), file=sys.stderr)
            return 4
        settings.set("paused", True)
        return 0
    if args.resume:
        if not settings.available:
            print("GSettings 不可用：{0}".format(settings.error), file=sys.stderr)
            return 4
        settings.set("paused", False)
        return 0
    if args.status:
        print("enabled={0} paused={1} backend={2} grab={3}".format(
            str(settings.get("enabled")).lower(),
            str(settings.get("paused")).lower(), diagnostics["backend"],
            diagnostics["x11"]["triggerGrabStatus"]))
        return 0 if settings.available else 4
    if args.diagnose:
        print(diagnostics_json(diagnostics) if args.json else format_diagnostics(diagnostics))
        return 0 if diagnostics["backend"] != "unsupported" else 3
    return _settings(diagnostics)

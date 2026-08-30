from __future__ import print_function, unicode_literals

import logging
import json
import os
import signal
import time

import gi
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

from Xlib import X, XK, Xatom, display, error
from Xlib.ext import xtest

from .config import resolve_gesture
from .gesture import GestureRecognizer, GestureSession
from .settings import Settings
from .shortcut import action_display_name
from .storage import ConfigStore, runtime_directory, runtime_status_path
from .tray import X11TrayIcon
from .x11_actions import X11ActionExecutor
from .x11_overlay import GestureOverlay
from .panel_ui import QuickPanel, prewarm_application_records_async


LOG = logging.getLogger("wgestures.x11")
BUTTON_NUMBERS = {"left": 1, "right": 3, "middle": 2, "x1": 8, "x2": 9}
BUTTON_NAMES = dict((number, name) for name, number in BUTTON_NUMBERS.items())
REPLAY_SETTLE_MS = 30
REPLAY_HOLD_MS = 24
REPLAY_REGRAB_DELAY_MS = 4


class X11Backend(object):
    def __init__(self):
        try:
            gi.require_foreign("cairo")
        except (ImportError, ValueError) as bridge_error:
            raise RuntimeError(
                "缺少 python3-gi-cairo，已停止 X11 输入捕获以避免右键失效：{0}"
                .format(bridge_error))
        input_debug = os.environ.get("WGESTURES_DEBUG_INPUT") == "1"
        logging.basicConfig(level=logging.DEBUG if input_debug else logging.INFO,
                            format="%(name)s: %(levelname)s: %(message)s")
        self.display = display.Display()
        extension = self.display.query_extension("XTEST")
        if not extension or not getattr(extension, "present", False):
            self.display.close()
            raise RuntimeError("当前 X11 服务器未提供 XTEST 扩展")
        try:
            self.inject_display = display.Display(self.display.get_display_name())
        except error.DisplayConnectionError as inject_error:
            self.display.close()
            raise RuntimeError("无法创建独立的 X11 点击回放连接：{0}".format(
                inject_error))
        self.root = self.display.screen().root
        self.settings = Settings()
        if not self.settings.available:
            self.inject_display.close()
            self.display.close()
            raise RuntimeError("GSettings 不可用：{0}".format(self.settings.error))
        self.store = ConfigStore()
        loaded = self.store.load()
        self.config = loaded["config"]
        for warning in loaded["warnings"]:
            LOG.warning(warning)
        self.recognizer = GestureRecognizer()
        self.session = GestureSession(self.recognizer)
        self.executor = X11ActionExecutor(self.display, self.settings)
        self.overlay = GestureOverlay(
            self.settings, self._cancel_for_monitor_change,
            self._record_frame_latency)
        self.panel = QuickPanel(self._panel_closed)
        # 后台预热应用记录缓存：开机后第一次弹出面板不再扫描全部 desktop。
        prewarm_application_records_async()
        self._panel_candidate = None
        try:
            self.tray = X11TrayIcon(
                self.settings, Gtk.main_quit, self._show_panel_from_tray)
        except Exception as tray_error:
            LOG.warning("无法创建系统托盘图标，后台手势仍可使用：%s", tray_error)
            self.tray = None
        self._grabbed = []
        self._keyboard_grabbed = False
        self._io_watch = None
        self._drain_source = None
        self._replay_source = None
        self._restore_grabs_source = None
        self._config_monitor = None
        self._dbus_subscriptions = []
        self._cleaned = False
        self._last_motion_time = None
        self._motion_latencies = []
        self._frame_latencies = []
        self._configure_recognizer()
        self._connect_settings()
        self._watch_config()
        self._watch_session_state()

    def _configure_recognizer(self):
        self.recognizer.configure(
            int(self.settings.get("direction-mode")),
            int(self.settings.get("start-threshold")),
            int(self.settings.get("segment-threshold")))

    def _connect_settings(self):
        for key in (
                "enabled", "paused", "trigger-buttons", "direction-mode",
                "start-threshold", "segment-threshold", "config-revision",
                "middle-panel-enabled"):
            self.settings.connect(key, self._settings_changed)

    def _settings_changed(self):
        if getattr(self, "_restore_grabs_source", None):
            GLib.source_remove(self._restore_grabs_source)
            self._restore_grabs_source = None
        self.cancel("设置已更新")
        self.panel.close_panel()
        self._configure_recognizer()
        self.config = self.store.load()["config"]
        self._ungrab_all()
        try:
            self._grab_configured()
            self._write_status(self._current_status())
        except RuntimeError as grab_error:
            LOG.error("更新设置后无法抓取按钮：%s", grab_error)
            self._write_status("error", str(grab_error))

    def _watch_config(self):
        directory = Gio.File.new_for_path(self.store.directory)
        try:
            self._config_monitor = directory.monitor_directory(
                Gio.FileMonitorFlags.WATCH_MOVES, None)
            self._config_monitor.connect("changed", self._config_changed)
        except GLib.Error as monitor_error:
            LOG.warning("无法监视配置文件：%s", monitor_error)

    def _config_changed(self, _monitor, _file, _other, event_type):
        if _file.get_basename() != os.path.basename(self.store.path):
            return
        if event_type in (
                Gio.FileMonitorEvent.CHANGES_DONE_HINT,
                Gio.FileMonitorEvent.CREATED,
                Gio.FileMonitorEvent.MOVED_IN):
            self.cancel("配置已重新载入")
            loaded = self.store.load()
            self.config = loaded["config"]

    def _watch_session_state(self):
        session_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        for interface in ("org.gnome.ScreenSaver", "org.xfce.ScreenSaver"):
            subscription = session_bus.signal_subscribe(
                None, interface, "ActiveChanged", None, None,
                Gio.DBusSignalFlags.NONE, self._screen_saver_changed)
            self._dbus_subscriptions.append((session_bus, subscription))
        try:
            system_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            subscription = system_bus.signal_subscribe(
                "org.freedesktop.login1", "org.freedesktop.login1.Manager",
                "PrepareForSleep", "/org/freedesktop/login1", None,
                Gio.DBusSignalFlags.NONE, self._prepare_for_sleep)
            self._dbus_subscriptions.append((system_bus, subscription))
        except GLib.Error as bus_error:
            LOG.warning("无法监听休眠状态：%s", bus_error)

    def _screen_saver_changed(self, _connection, _sender, _path, _interface,
                              _signal, parameters, _data=None):
        try:
            active = bool(parameters.unpack()[0])
        except (IndexError, TypeError):
            active = True
        if active:
            self.panel.close_panel()
            self.cancel("会话已锁定")

    def _prepare_for_sleep(self, _connection, _sender, _path, _interface,
                           _signal, parameters, _data=None):
        try:
            sleeping = bool(parameters.unpack()[0])
        except (IndexError, TypeError):
            sleeping = True
        if sleeping:
            self.panel.close_panel()
            self.cancel("系统准备休眠")

    def _cancel_for_monitor_change(self):
        self.panel.close_panel()
        self.cancel("显示器配置已变化")

    def _lock_modifier_masks(self):
        masks = set([0, X.LockMask])
        lock_masks = [X.LockMask]
        try:
            modifier_map = self.display.get_modifier_mapping()
            for index, keycodes in enumerate(modifier_map):
                for keycode in keycodes:
                    if not keycode:
                        continue
                    keysyms = [self.display.keycode_to_keysym(keycode, group)
                               for group in range(4)]
                    if any(keysym in (XK.string_to_keysym("Num_Lock"),
                                      XK.string_to_keysym("Scroll_Lock"))
                           for keysym in keysyms):
                        mask = 1 << index
                        if mask not in lock_masks:
                            lock_masks.append(mask)
        except Exception as mapping_error:
            LOG.warning("无法读取锁定键映射，按常见 NumLock 映射继续：%s", mapping_error)
            lock_masks.append(X.Mod2Mask)
        masks = set([0])
        for lock_mask in lock_masks:
            masks.update([value | lock_mask for value in list(masks)])
        return sorted(masks)

    def _grab_button_names(self):
        # 面板打开时手势按钮同样保持抓取：面板之外的右键/X 键手势照常
        # 识别，面板表面上的按键由事件处理单独转发给格子。仅面板可见时
        # 临时抓取左键，用于可靠识别桌面/其他窗口上的外部点击。
        names = (list(self.settings.get("trigger-buttons")) +
                 (["middle"] if self.settings.get("middle-panel-enabled") else []))
        if self.panel.get_visible():
            names.append("left")
        return list(dict.fromkeys(names))

    def _grab_configured(self):
        if not self.settings.get("enabled") or self.settings.get("paused"):
            return
        errors = []

        def on_error(protocol_error, _request=None):
            errors.append(protocol_error)

        event_mask = X.ButtonPressMask | X.ButtonReleaseMask | X.PointerMotionMask
        names = self._grab_button_names()
        for name in names:
            button = BUTTON_NUMBERS.get(name)
            if not button:
                continue
            # 手势按钮用同步抓取：按下先冻结指针，由事件处理决定回放给
            # 面板格子（ReplayPointer）还是解冻继续手势（AsyncPointer）。
            # 中键始终被本程序消费，用异步抓取即可。
            pointer_mode = (X.GrabModeAsync if name == "middle"
                            else X.GrabModeSync)
            for modifiers in self._lock_modifier_masks():
                self.root.grab_button(
                    button, modifiers, False, event_mask,
                    pointer_mode, X.GrabModeAsync, X.NONE, X.NONE,
                    onerror=on_error)
                self._grabbed.append((button, modifiers))
        self.display.sync()
        if errors:
            self._ungrab_all()
            details = ", ".join(str(item) for item in errors[:3])
            raise RuntimeError("鼠标按钮已被其他程序占用：{0}".format(details))
        LOG.info("已抓取按钮：%s", ", ".join(names))

    def _ungrab_all(self):
        for button, modifiers in self._grabbed:
            try:
                self.root.ungrab_button(button, modifiers)
            except error.XError:
                pass
        self._grabbed = []
        self.display.sync()

    def _grab_keyboard(self):
        try:
            result = self.root.grab_keyboard(
                False, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)
            self._keyboard_grabbed = result == X.GrabSuccess
        except error.XError:
            self._keyboard_grabbed = False
        if not self._keyboard_grabbed:
            LOG.warning("无法临时抓取键盘，当前手势不能用 Esc 取消")

    def _ungrab_keyboard(self):
        if self._keyboard_grabbed:
            self.display.ungrab_keyboard(X.CurrentTime)
            self.display.flush()
            self._keyboard_grabbed = False

    def run(self):
        try:
            self._grab_configured()
            self._write_status(self._current_status())
            self._io_watch = GLib.io_add_watch(
                self.display.fileno(),
                GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                self._on_x11_io)
            signal.signal(signal.SIGTERM, self._signal_exit)
            signal.signal(signal.SIGINT, self._signal_exit)
            Gtk.main()
            return 0
        except (RuntimeError, error.DisplayConnectionError) as runtime_error:
            LOG.error("X11 后端启动失败：%s", runtime_error)
            self._write_status("error", str(runtime_error))
            return 5
        finally:
            self.cleanup()

    def _signal_exit(self, _signum, _frame):
        GLib.idle_add(Gtk.main_quit)

    def _on_x11_io(self, _source, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            Gtk.main_quit()
            return GLib.SOURCE_REMOVE
        try:
            self._drain_events()
        except Exception as event_error:
            LOG.exception("处理 X11 输入时发生异常：%s", event_error)
            self.cancel("输入处理异常")
        return GLib.SOURCE_CONTINUE

    def _drain_events(self):
        processed = 0
        while self.display.pending_events() and processed < 256:
            event = self.display.next_event()
            self._handle_event(event)
            processed += 1
        if self.display.pending_events() and not self._drain_source:
            self._drain_source = GLib.idle_add(self._drain_remaining)

    def _drain_remaining(self):
        self._drain_source = None
        try:
            self._drain_events()
        except Exception as event_error:
            LOG.exception("继续处理 X11 输入时发生异常：%s", event_error)
            self.cancel("输入处理异常")
        return GLib.SOURCE_REMOVE

    def _handle_event(self, event):
        if event.type == X.ButtonPress:
            self._button_press(event)
        elif event.type == X.ButtonRelease:
            self._button_release(event)
        elif event.type == X.MotionNotify:
            self._motion(event)
        elif event.type == X.KeyPress and self.session.active is not None:
            keysym = self.display.keycode_to_keysym(event.detail, 0)
            if keysym == XK.string_to_keysym("Escape"):
                self.cancel("已取消")

    def _button_press(self, event):
        LOG.debug("captured press button=%s time=%s serial=%s state=%s",
                  event.detail, getattr(event, "time", None),
                  getattr(event, "serial", None), getattr(event, "state", None))
        if self.session.active is not None:
            self._allow_pointer(X.AsyncPointer, event)
            return
        name = BUTTON_NAMES.get(event.detail)
        if not name:
            self._allow_pointer(X.AsyncPointer, event)
            return
        if name == "left" and self.panel.get_visible():
            editing = getattr(self.panel, "editing", False)
            inside = editing or self._pointer_inside_panel(event)
            # ReplayPointer preserves the real press/release sequence, so an
            # outside desktop click still selects/focuses its original target
            # and an inside click still reaches the GTK tile or modal editor.
            self._allow_pointer(X.ReplayPointer, event)
            if not inside:
                self.panel.close_panel()
            return
        if name == "middle" and self.settings.get("middle-panel-enabled"):
            if getattr(self.panel, "editing", False):
                # Modal editors own the visible window stack. Consuming middle
                # here prevents an even-numbered toggle burst from calling
                # show_at()/present() and raising the grid above its chooser.
                self._allow_pointer(X.AsyncPointer, event)
                self._panel_candidate = None
                return
            if self.panel.get_visible():
                self.panel.close_panel()
                self._panel_candidate = None
                return
            if not self.settings.get("enabled") or self.settings.get("paused"):
                self._replay_click(event.detail)
                return
            self._panel_candidate = {
                "x": float(event.root_x), "y": float(event.root_y),
                "cancelled": False,
            }
            # The panel owns middle while enabled. Show on press so the user's
            # click-hold time is not added to perceived latency; motion beyond
            # the threshold closes it again and preserves drag cancellation.
            self._ungrab_all()
            self.panel.show_at(event.root_x, event.root_y)
            self._grab_configured()
            return
        if (self.panel.get_visible() and
                not getattr(self.panel, "editing", False) and
                name != "middle" and
                self._pointer_inside_panel(event)):
            # 面板表面上的右键/X 键属于格子交互：ReplayPointer 把这一按
            # 原样交给格子（事件状态与真实点击完全一致）；面板之外这些
            # 按钮解冻后继续走正常手势识别。
            LOG.debug("panel surface press button=%s at=(%s,%s)", event.detail,
                      event.root_x, event.root_y)
            self._allow_pointer(X.ReplayPointer, event)
            return
        self._allow_pointer(X.AsyncPointer, event)
        if not self.settings.get("enabled") or self.settings.get("paused"):
            self._replay_click(event.detail)
            return
        self._configure_recognizer()
        window = self._window_at(int(event.root_x), int(event.root_y))
        identity = self._identity_for_window(window)
        context = {
            "button_number": event.detail,
            "button_name": name,
            "window": window,
            "identity": identity,
            "pressed_at": time.monotonic(),
        }
        if self.session.begin(context, event.root_x, event.root_y):
            self._grab_keyboard()
            self.overlay.begin(event.root_x, event.root_y)

    def _pointer_inside_panel(self, event):
        window = self.panel.get_window()
        if window is None:
            LOG.debug("panel surface probe: no gdk window")
            return False
        x, y, width, height = window.get_geometry()
        inside = (x <= event.root_x < x + width and
                  y <= event.root_y < y + height)
        LOG.debug("panel surface probe: inside=%s geometry=(%s,%s,%s,%s) "
                  "pointer=(%s,%s)", inside, x, y, width, height,
                  event.root_x, event.root_y)
        return inside

    def _motion(self, event):
        if self._panel_candidate is not None:
            dx = float(event.root_x) - self._panel_candidate["x"]
            dy = float(event.root_y) - self._panel_candidate["y"]
            threshold = float(self.settings.get("start-threshold"))
            if (not self._panel_candidate["cancelled"] and
                    dx * dx + dy * dy > threshold * threshold):
                self._panel_candidate["cancelled"] = True
                self.panel.close_panel()
            return
        if self.session.active is None:
            return
        started = time.monotonic()
        self.session.motion(event.root_x, event.root_y)
        self.overlay.add_point(event.root_x, event.root_y)
        latency = (time.monotonic() - started) * 1000.0
        self._motion_latencies.append(latency)
        if len(self._motion_latencies) > 1024:
            del self._motion_latencies[:512]

    def _record_frame_latency(self, latency):
        self._frame_latencies.append(float(latency))
        if len(self._frame_latencies) > 1024:
            del self._frame_latencies[:512]

    def _button_release(self, event):
        LOG.debug("captured release button=%s time=%s serial=%s state=%s",
                  event.detail, getattr(event, "time", None),
                  getattr(event, "serial", None), getattr(event, "state", None))
        if event.detail == BUTTON_NUMBERS["middle"] and self._panel_candidate is not None:
            self._panel_candidate = None
            return
        released = self.session.release(event.detail)
        if not released.get("handled"):
            return
        if released.get("mismatched"):
            return
        self._ungrab_keyboard()
        context = released["context"]
        result = released["result"]
        LOG.debug("gesture result effective=%s directions=%s",
                  result.get("effective"), result.get("directions"))
        if not result["effective"]:
            self.overlay.cancel()
            self._replay_click(event.detail)
            return
        matched = resolve_gesture(
            self.config, context["identity"], context["button_name"],
            result["directions"], result)
        if not matched:
            self.overlay.complete(False, "无匹配手势")
            return
        LOG.debug("matched action=%s", matched["action"].get("id"))
        label = action_display_name(matched["action"], matched["gesture"])
        try:
            self.executor.execute(matched["action"], context)
            if LOG.isEnabledFor(logging.DEBUG):
                LOG.debug("action complete paused=%s", self.settings.get("paused"))
            self.overlay.complete(True, label)
        except Exception as action_error:
            LOG.exception("执行动作失败：%s", action_error)
            self.overlay.complete(False, "动作失败")

    def _allow_pointer(self, mode, event):
        # 同步抓取按下后指针处于冻结状态，必须显式放行。
        try:
            self.display.allow_events(
                mode, getattr(event, "time", None) or X.CurrentTime)
            self.display.flush()
        except error.XError:
            pass

    def _replay_click(self, button):
        # A passive button grab becomes an active pointer grab for the current
        # physical click. Release it and remove the passive rules now, but inject
        # the replacement from the next GLib iteration. Injecting synchronously
        # inside the physical ButtonRelease callback can be discarded by X11.
        try:
            self.display.ungrab_pointer(X.CurrentTime)
        except error.XError:
            pass
        self._ungrab_all()
        LOG.debug("scheduling replay click button=%s", button)
        if getattr(self, "_restore_grabs_source", None):
            GLib.source_remove(self._restore_grabs_source)
            self._restore_grabs_source = None
        if self._replay_source:
            GLib.source_remove(self._replay_source)
        self._replay_source = GLib.timeout_add(
            REPLAY_SETTLE_MS, self._inject_replayed_click, button)

    def _inject_replayed_click(self, button):
        self._replay_source = None
        if self._cleaned:
            return GLib.SOURCE_REMOVE
        LOG.debug("injecting replay click button=%s", button)
        xtest.fake_input(self.inject_display, X.ButtonPress, button)
        xtest.fake_input(
            self.inject_display, X.ButtonRelease, button, time=REPLAY_HOLD_MS)
        self.inject_display.sync()
        # Do not restore the passive grabs in the same event-loop turn. Some X
        # servers deliver XTEST events to other clients after Sync returns; an
        # immediate re-grab can then capture our own replay and start a loop.
        self._restore_grabs_source = GLib.timeout_add(
            REPLAY_REGRAB_DELAY_MS, self._restore_grabs_after_replay)
        return GLib.SOURCE_REMOVE

    def _restore_grabs_after_replay(self):
        self._restore_grabs_source = None
        if self._cleaned:
            return GLib.SOURCE_REMOVE
        try:
            self._grab_configured()
        except RuntimeError as grab_error:
            LOG.error("回放点击后无法恢复鼠标按钮抓取：%s", grab_error)
            self._write_status("error", str(grab_error))
        return GLib.SOURCE_REMOVE

    def cancel(self, message=None):
        self._panel_candidate = None
        had_active = self.session.cancel()
        if had_active:
            LOG.info(message or "手势已取消")
            try:
                self.display.ungrab_pointer(X.CurrentTime)
                self.display.flush()
            except error.XError:
                pass
        self._ungrab_keyboard()
        self.overlay.cancel()

    def _panel_closed(self):
        if self._cleaned:
            return
        self._ungrab_all()
        try:
            self._grab_configured()
        except RuntimeError as grab_error:
            LOG.error("关闭面板后无法恢复鼠标按钮抓取：%s", grab_error)

    def _show_panel_from_tray(self):
        # Run after the indicator menu has closed, then center the panel at
        # the current pointer. This remains available even if the middle
        # button is unavailable or the gesture engine is paused.
        GLib.idle_add(self._show_panel_from_tray_idle)

    def _show_panel_from_tray_idle(self):
        if self._cleaned:
            return GLib.SOURCE_REMOVE
        try:
            pointer = self.root.query_pointer()
            self._ungrab_all()
            self.panel.show_at(pointer.root_x, pointer.root_y)
            self._grab_configured()
        except Exception as panel_error:
            LOG.error("无法从托盘弹出快捷面板：%s", panel_error)
        return GLib.SOURCE_REMOVE

    def _property_text(self, window, name):
        if window is None:
            return ""
        try:
            prop = window.get_full_property(self.display.intern_atom(name), X.AnyPropertyType)
            if prop is None:
                return ""
            value = prop.value
            if isinstance(value, bytes):
                return value.split(b"\0", 1)[0].decode("utf-8", "replace")
            if hasattr(value, "tobytes"):
                return value.tobytes().split(b"\0", 1)[0].decode("utf-8", "replace")
            return str(value[0] if hasattr(value, "__len__") and len(value) else value)
        except (error.XError, UnicodeError):
            return ""

    def _property_cardinal(self, window, name):
        try:
            prop = window.get_full_property(self.display.intern_atom(name), Xatom.CARDINAL)
            return int(prop.value[0]) if prop is not None and len(prop.value) else None
        except (error.XError, TypeError, ValueError):
            return None

    def _identity_for_window(self, window):
        if window is None:
            return {}
        identity = {}
        gtk_id = self._property_text(window, "_GTK_APPLICATION_ID")
        desktop_file = (self._property_text(window, "_BAMF_DESKTOP_FILE") or
                        self._property_text(window, "_BAMF_DESKTOP_FILE_HINT"))
        try:
            wm_class = window.get_wm_class()
        except error.XError:
            wm_class = None
        if gtk_id:
            identity["gtkApplicationId"] = gtk_id
        if desktop_file:
            identity["desktopId"] = os.path.basename(desktop_file)
        if wm_class:
            identity["wmClass"] = wm_class[-1]
            identity.setdefault("desktopId", wm_class[-1].lower() + ".desktop")
        pid = self._property_cardinal(window, "_NET_WM_PID")
        if pid:
            sandboxed, inferred_desktop = self._sandbox_identity(pid)
            if sandboxed:
                identity["sandboxedAppId"] = sandboxed
            if inferred_desktop:
                identity.setdefault("desktopId", inferred_desktop)
        return identity

    @staticmethod
    def _sandbox_identity(pid):
        try:
            with open("/proc/{0}/environ".format(pid), "rb") as stream:
                values = {}
                for item in stream.read().split(b"\0"):
                    if b"=" in item:
                        key, value = item.split(b"=", 1)
                        values[key.decode("ascii", "ignore")] = value.decode("utf-8", "replace")
            flatpak = values.get("FLATPAK_ID")
            if flatpak:
                return flatpak, flatpak + ".desktop"
            snap = values.get("SNAP_INSTANCE_NAME") or values.get("SNAP_NAME")
            if snap:
                desktop_file = values.get("SNAP_DESKTOP_FILE")
                inferred = os.path.basename(desktop_file) if desktop_file else \
                    snap + "_" + snap + ".desktop"
                return snap, inferred
        except (OSError, IOError):
            pass
        try:
            with open("/proc/{0}/cgroup".format(pid), "r") as stream:
                text = stream.read()
            for pattern in (r"snap\.([A-Za-z0-9_-]+)",
                            r"app-flatpak-([A-Za-z0-9_.-]+)"):
                import re
                match = re.search(pattern, text)
                if match:
                    return match.group(1), None
        except (OSError, IOError):
            pass
        return None, None

    def _client_windows(self):
        try:
            atom = self.display.intern_atom("_NET_CLIENT_LIST_STACKING")
            prop = self.root.get_full_property(atom, Xatom.WINDOW)
            return [self.display.create_resource_object("window", int(window_id))
                    for window_id in (prop.value if prop is not None else [])]
        except error.XError:
            return []

    def _window_at(self, x, y):
        for window in reversed(self._client_windows()):
            try:
                attributes = window.get_attributes()
                if attributes.map_state != X.IsViewable:
                    continue
                geometry = window.get_geometry()
                translated = self.root.translate_coords(window, 0, 0)
                translated_x = getattr(translated, "dst_x", getattr(translated, "x", 0))
                translated_y = getattr(translated, "dst_y", getattr(translated, "y", 0))
                if (translated_x <= x < translated_x + geometry.width and
                        translated_y <= y < translated_y + geometry.height):
                    return window
            except error.XError:
                continue
        try:
            atom = self.display.intern_atom("_NET_ACTIVE_WINDOW")
            prop = self.root.get_full_property(atom, Xatom.WINDOW)
            if prop is not None and len(prop.value):
                return self.display.create_resource_object("window", int(prop.value[0]))
        except error.XError:
            pass
        return None

    def cleanup(self):
        if self._cleaned:
            return
        self._cleaned = True
        try:
            self.cancel("后端退出")
            self._ungrab_all()
            if self._io_watch:
                GLib.source_remove(self._io_watch)
            if self._drain_source:
                GLib.source_remove(self._drain_source)
            if self._replay_source:
                GLib.source_remove(self._replay_source)
                self._replay_source = None
            if getattr(self, "_restore_grabs_source", None):
                GLib.source_remove(self._restore_grabs_source)
                self._restore_grabs_source = None
            if self._config_monitor:
                self._config_monitor.cancel()
            for connection, subscription in self._dbus_subscriptions:
                connection.signal_unsubscribe(subscription)
            if self.tray:
                self.tray.destroy()
            self.panel.destroy()
            self.overlay.destroy()
            self._write_metrics()
            self._remove_status()
        finally:
            try:
                self.inject_display.close()
            finally:
                self.display.close()

    def _write_status(self, status, message=None):
        directory = runtime_directory()
        path = runtime_status_path()
        try:
            if not os.path.isdir(directory):
                os.makedirs(directory, 0o700)
            value = {
                "pid": os.getpid(),
                "backend": "x11",
                "triggerGrabStatus": status,
                "buttons": list(self.settings.get("trigger-buttons")),
                "grabCount": len(self._grabbed),
                "xtest": True,
                "overlayComposited": bool(self.overlay.composited),
                "message": message,
            }
            temporary = path + ".tmp"
            with open(temporary, "w") as stream:
                json.dump(value, stream, indent=2, sort_keys=True)
                stream.write("\n")
            os.replace(temporary, path)
        except OSError as status_error:
            LOG.warning("无法写入运行状态：%s", status_error)

    def _current_status(self):
        if not self.settings.get("enabled"):
            return "disabled"
        if self.settings.get("paused"):
            return "paused"
        return "active"

    @staticmethod
    def _remove_status():
        try:
            path = runtime_status_path()
            with open(path, "r") as stream:
                value = json.load(stream)
            if int(value.get("pid", -1)) == os.getpid():
                os.unlink(path)
        except (OSError, ValueError, TypeError):
            pass

    @staticmethod
    def _percentile(values, percentile):
        if not values:
            return None
        ordered = sorted(values)
        index = int(round((len(ordered) - 1) * percentile))
        return ordered[max(0, min(index, len(ordered) - 1))]

    def _write_metrics(self):
        path = os.environ.get("WGESTURES_METRICS_PATH")
        if not path:
            return
        data = {
            "motionSamples": len(self._motion_latencies),
            "frameSamples": len(self._frame_latencies),
            "inputProcessingP95Ms": self._percentile(self._motion_latencies, 0.95),
            "eventToFrameP95Ms": self._percentile(self._frame_latencies, 0.95),
        }
        try:
            with open(path, "w") as stream:
                json.dump(data, stream, indent=2, sort_keys=True)
                stream.write("\n")
        except OSError as metrics_error:
            LOG.warning("无法写入性能指标：%s", metrics_error)

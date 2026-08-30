from __future__ import unicode_literals

import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

LINUX_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LINUX_ROOT)

try:
    import gi  # noqa: F401
    from gi.repository import Gio
    from wgestures import panel_ui
    from wgestures.panel import PanelStore
    from wgestures.panel_ui import (FALLBACK_ICON_NAMES, PanelItemDialog,
                                    QuickPanel, _configure_modal_child,
                                    _cached_gicon, _icon_widget,
                                    _application_records,
                                    _favicon_candidate_urls, fetch_favicon,
                                    _file_manager_commands, _launch_folder,
                                    _resolve_executable_target,
                                    launch_panel_item,
                                    panel_layout_for_area)
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False


@unittest.skipUnless(HAS_GTK, "PyGObject/GTK3 is not available")
class PanelLaunchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="wgestures-panel-launch-")
        panel_ui._APPLICATION_RECORDS_CACHE.update(records=None, expires=0.0)
        # 屏蔽真实网络下载：URL 图标测试只验证缓存命中与缺失回调。
        favicon_patcher = mock.patch.object(panel_ui, "_ensure_favicon")
        favicon_patcher.start()
        self.addCleanup(favicon_patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.directory)
        panel_ui._APPLICATION_RECORDS_CACHE.update(records=None, expires=0.0)

    def test_dispatches_application_file_folder_and_url(self):
        class FakeApplication(object):
            def __init__(self):
                self.calls = []

            def launch(self, files, context):
                self.calls.append((files, context))

        application = FakeApplication()
        launch_panel_item(
            {"type": "application", "target": "test.desktop"},
            application_records=[("Test", "test.desktop", application)])
        self.assertEqual(application.calls, [([], None)])

        file_path = os.path.join(self.directory, "document.txt")
        with open(file_path, "w") as stream:
            stream.write("test")
        launched = []
        launch_panel_item(
            {"type": "file", "target": file_path},
            uri_launcher=lambda uri, context: launched.append((uri, context)))
        launch_panel_item(
            {"type": "folder", "target": self.directory},
            uri_launcher=lambda uri, context: launched.append((uri, context)))
        launch_panel_item(
            {"type": "url", "target": "https://example.com"},
            uri_launcher=lambda uri, context: launched.append((uri, context)))
        self.assertTrue(launched[0][0].startswith("file://"))
        self.assertTrue(launched[1][0].startswith("file://"))
        self.assertEqual(launched[2], ("https://example.com", None))

    def test_folder_launch_prefers_desktop_file_manager_over_default_uri_handler(self):
        launched = []
        executables = {"thunar": "/usr/bin/thunar", "nautilus": "/usr/bin/nautilus"}
        _launch_folder(
            "/root/Downloads",
            popen=lambda command, **kwargs: launched.append((command, kwargs)),
            which=executables.get,
            uri_launcher=lambda *_args: self.fail("URI handler must not be used"),
            desktop="XFCE")
        self.assertEqual(launched, [
            (["/usr/bin/thunar", "/root/Downloads"], {"close_fds": True})])

    def test_folder_launch_uses_gnome_preference_and_has_uri_fallback(self):
        self.assertEqual(_file_manager_commands("GNOME")[0], "nautilus")
        launched = []
        _launch_folder(
            self.directory, popen=lambda *_args, **_kwargs: None,
            which=lambda _command: None,
            uri_launcher=lambda uri, context: launched.append((uri, context)))
        self.assertTrue(launched[0][0].startswith("file://"))
        self.assertIsNone(launched[0][1])

    def test_missing_targets_fail_without_exiting_backend(self):
        with self.assertRaisesRegex(ValueError, "找不到软件"):
            launch_panel_item(
                {"type": "application", "target": "missing.desktop"},
                application_records=[])
        with self.assertRaisesRegex(ValueError, "文件不存在"):
            launch_panel_item(
                {"type": "file", "target": os.path.join(self.directory, "missing")},
                uri_launcher=lambda _uri, _context: None)

    def test_launches_absolute_executable_with_arguments_and_default_cwd(self):
        executable = os.path.join(self.directory, "studio.sh")
        with open(executable, "w") as stream:
            stream.write("#!/bin/sh\n")
        os.chmod(executable, 0o755)
        with mock.patch("wgestures.panel_ui.subprocess.Popen") as popen:
            launch_panel_item({
                "type": "application", "target": executable,
                "arguments": '--project "hello world"',
            }, application_records=[])
        popen.assert_called_once_with(
            [executable, "--project", "hello world"],
            cwd=self.directory, close_fds=True)

    def test_launches_dot_relative_executable_from_working_directory(self):
        executable = os.path.join(self.directory, "jadx-gui")
        with open(executable, "w") as stream:
            stream.write("#!/bin/sh\n")
        os.chmod(executable, 0o755)
        with mock.patch("wgestures.panel_ui.subprocess.Popen") as popen:
            launch_panel_item({
                "type": "application", "target": "./jadx-gui",
                "workingDirectory": self.directory,
            }, application_records=[])
        popen.assert_called_once_with(
            [executable], cwd=self.directory, close_fds=True)

    def test_relative_executable_requires_cwd_and_execute_permission(self):
        with self.assertRaisesRegex(ValueError, "必须填写工作目录"):
            _resolve_executable_target("./studio.sh")
        executable = os.path.join(self.directory, "studio.sh")
        with open(executable, "w") as stream:
            stream.write("#!/bin/sh\n")
        os.chmod(executable, 0o644)
        with self.assertRaisesRegex(ValueError, "chmod \+x"):
            _resolve_executable_target(executable)

    def test_application_chooser_exposes_executable_file_path(self):
        source_path = os.path.join(LINUX_ROOT, "wgestures", "panel_ui.py")
        with open(source_path, encoding="utf-8") as stream:
            source = stream.read()
        self.assertIn('dialog.add_button("选择可执行文件…",', source)
        self.assertIn('self.working_entry.set_text(os.path.dirname(target))',
                      source)
        self.assertIn("程序或启动目标", source)
        self.assertIn("./程序名会从这里查找", source)
        self.assertNotIn("self.help_label", source)

    def test_save_validation_reports_fully_resolved_relative_target(self):
        working_directory = os.path.join(self.directory, "android-studio")
        os.makedirs(working_directory)
        expected = os.path.join(working_directory, "studio")
        with self.assertRaisesRegex(
                ValueError, "程序文件不存在.*{0}".format(
                    expected.replace("\\", "\\\\"))):
            _resolve_executable_target("./studio", working_directory)

    def test_item_dialog_builds_and_returns_a_saved_application(self):
        from gi.repository import Gdk

        if Gdk.Screen.get_default() is None:
            self.skipTest("no X display available for a real item dialog")
        executable = os.path.join(self.directory, "studio")
        with open(executable, "w") as stream:
            stream.write("#!/bin/sh\n")
        os.chmod(executable, 0o755)
        with mock.patch.object(panel_ui, "_application_records",
                               return_value=[]):
            dialog = PanelItemDialog(None, 0)
            try:
                dialog.target_entry.set_text("./studio")
                dialog.working_entry.set_text(self.directory)
                item = dialog.result_item()
            finally:
                dialog.destroy()
        self.assertEqual(item["label"], "studio")
        self.assertEqual(item["target"], "./studio")
        self.assertEqual(item["workingDirectory"], self.directory)

    def test_panel_layout_adapts_to_small_and_large_logical_screens(self):
        small = panel_layout_for_area(800, 600)
        standard = panel_layout_for_area(1920, 1080)
        large = panel_layout_for_area(3840, 2160)
        self.assertLess(small[0], 104)
        self.assertGreater(standard[0], 104)
        self.assertGreater(large[0], standard[0])
        self.assertEqual(panel_layout_for_area(320, 240),
                         panel_layout_for_area(800, 600))

    def test_long_tile_name_cannot_resize_the_fixed_four_by_four_grid(self):
        from gi.repository import Gdk

        if Gdk.Screen.get_default() is None:
            self.skipTest("no X display available for a real quick panel")
        store = PanelStore(os.path.join(self.directory, "fixed-grid-panel.json"))
        config = store.load()["config"]
        config["slots"][0] = {
            "id": "long-name", "type": "url",
            "label": "android studio " * 20,
            "target": "https://example.com",
        }
        store.save(config)
        panel = QuickPanel()
        panel.store = store
        try:
            panel.show_at(400, 300)
            while panel_ui.Gtk.events_pending():
                panel_ui.Gtk.main_iteration()
            long_size = panel.get_size()
            widths = [child.get_allocated_width()
                      for child in panel._grid.get_children()]
            self.assertEqual(len(widths), 16)
            self.assertEqual(len(set(widths)), 1)

            config["slots"][0]["label"] = "A"
            store.save(config)
            panel.show_at(400, 300)
            while panel_ui.Gtk.events_pending():
                panel_ui.Gtk.main_iteration()
            self.assertEqual(panel.get_size(), long_size)
        finally:
            panel.destroy()

    def test_admin_launch_reports_missing_pkexec(self):
        executable = os.path.join(self.directory, "admin-tool")
        with open(executable, "w") as stream:
            stream.write("#!/bin/sh\n")
        os.chmod(executable, 0o755)
        with mock.patch("wgestures.panel_ui.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "未安装 pkexec"):
                launch_panel_item({
                    "type": "application", "target": executable,
                    "runAsAdministrator": True,
                }, application_records=[])

    def test_activate_if_running_skips_launch_and_launches_when_absent(self):
        class FakeApplication(object):
            def __init__(self):
                self.launches = 0

            def get_executable(self):
                return "testapp"

            def launch(self, _files, _context):
                self.launches += 1

        application = FakeApplication()
        item = {"type": "application", "target": "test.desktop",
                "activateIfRunning": True}
        with mock.patch("wgestures.panel_ui._activate_running_application",
                        return_value=True) as activate:
            launch_panel_item(item, application_records=[
                ("Test", "test.desktop", application)])
        activate.assert_called_once_with("testapp")
        self.assertEqual(application.launches, 0)

        with mock.patch("wgestures.panel_ui._activate_running_application",
                        return_value=False):
            launch_panel_item(item, application_records=[
                ("Test", "test.desktop", application)])
        self.assertEqual(application.launches, 1)

    def test_application_records_are_cached(self):
        with mock.patch.object(Gio.AppInfo, "get_all",
                               return_value=[]) as get_all:
            panel_ui.warm_application_records()
            panel_ui.warm_application_records()
        get_all.assert_called_once()

    def test_quick_panel_reuses_config_until_file_changes(self):
        from gi.repository import Gdk

        if Gdk.Screen.get_default() is None:
            self.skipTest("no X display available for a real quick panel")

        store = PanelStore(os.path.join(self.directory, "panel-v1.json"))
        panel = QuickPanel()
        try:
            panel.store = store
            panel.show_at(60, 60)
            original_grid = panel.get_child()
            with mock.patch.object(panel.store, "load",
                                   side_effect=AssertionError(
                                       "面板文件未变化时不应重新读取")):
                panel.show_at(60, 60)
            self.assertIs(panel.get_child(), original_grid)

            changed = store.load()["config"]
            changed["slots"][0] = {
                "id": "marker", "label": "M", "type": "url",
                "target": "https://example.com",
            }
            store.save(changed)
            panel.show_at(60, 60)
            self.assertEqual(panel.config["slots"][0]["label"], "M")
            self.assertIsNot(panel.get_child(), original_grid)
        finally:
            panel.destroy()

    def test_quick_panel_and_editors_form_managed_modal_chain(self):
        from gi.repository import Gdk, Gtk

        if Gdk.Screen.get_default() is None:
            self.skipTest("no X display available for real window hierarchy")

        panel = QuickPanel()
        editor = None
        chooser = None
        try:
            self.assertEqual(panel.get_window_type(), Gtk.WindowType.POPUP)
            editor = PanelItemDialog(panel, 0)
            self.assertIs(editor.get_transient_for(), panel)
            self.assertTrue(editor.get_modal())
            self.assertTrue(editor.get_destroy_with_parent())

            chooser = Gtk.Dialog(title="chooser")
            _configure_modal_child(chooser, editor)
            self.assertIs(chooser.get_transient_for(), editor)
            self.assertTrue(chooser.get_modal())
            self.assertTrue(chooser.get_destroy_with_parent())

            panel._editing = False
            panel._begin_dialog_stack()
            self.assertTrue(panel.editing)
            panel._end_dialog_stack()
            self.assertFalse(panel.editing)
        finally:
            if chooser is not None:
                chooser.destroy()
            if editor is not None:
                editor.destroy()
            panel.destroy()

    def test_menu_deactivation_does_not_close_active_dialog_stack(self):
        class Holder(object):
            _editing = True
            _dialog_active = True
            _menu_action_invoked = False
            closed = False

            @property
            def editing(self):
                return self._editing or self._dialog_active

            def is_active(self):
                return False

            def close_panel(self):
                self.closed = True

        holder = Holder()
        timeout_callbacks = []
        with mock.patch("wgestures.panel_ui.GLib.timeout_add",
                        side_effect=lambda _delay, callback:
                        timeout_callbacks.append(callback)):
            QuickPanel._menu_deactivated(holder, None)
        self.assertFalse(holder._editing)
        self.assertEqual(len(timeout_callbacks), 1)
        timeout_callbacks[0]()
        self.assertFalse(holder.closed)

        holder._dialog_active = False
        holder._menu_action_invoked = False
        with mock.patch("wgestures.panel_ui.GLib.timeout_add",
                        side_effect=lambda _delay, callback:
                        timeout_callbacks.append(callback)):
            QuickPanel._menu_deactivated(holder, None)
        timeout_callbacks[-1]()
        self.assertTrue(holder.closed)

    def test_watchdog_requires_activated_once(self):
        from gi.repository import Gdk

        if Gdk.Screen.get_default() is None:
            self.skipTest("no X display available for a real quick panel")

        panel = QuickPanel()
        try:
            panel.store = PanelStore(os.path.join(self.directory, "panel-v1.json"))
            panel.show_at(60, 60)
            # 无窗口管理器的 Xvfb 里 focus-in 未必到达；无论哪种情况，
            # 未激活过的面板都不得被看门狗自动关闭。
            deadline = time.monotonic() + 3.6
            with mock.patch.object(type(panel), "is_active",
                                   return_value=False):
                while time.monotonic() < deadline:
                    panel._watchdog_tick()
                    time.sleep(0.1)
                self.assertTrue(panel.get_visible())
                panel._activated_once = True
                panel._shown_at = time.monotonic() - 4.0
                panel._watchdog_tick()
                self.assertFalse(panel.get_visible())
        finally:
            panel.destroy()

    def test_icon_lookup_is_cached_per_target(self):
        folder = os.path.join(self.directory, "icon-cache")
        os.makedirs(folder)
        item = {"type": "folder", "target": folder}
        real_new = Gio.File.new_for_path
        queried = []

        def counting_new(path):
            queried.append(path)
            return real_new(path)

        cache = {}
        with mock.patch.object(Gio.File, "new_for_path",
                               staticmethod(counting_new)):
            icon_one = _cached_gicon(item, 40, cache)
            icon_two = _cached_gicon(item, 40, cache)
        # PyGObject wraps the same C icon in a new proxy per call; a single
        # query is the proof that the cache works.
        self.assertEqual(len(queried), 1)
        self.assertIs(icon_one, icon_two)

    def test_relative_executable_uses_adjacent_icon_not_desktop_id(self):
        executable = os.path.join(self.directory, "studio")
        icon_path = executable + ".svg"
        with open(executable, "w") as stream:
            stream.write("#!/bin/sh\n")
        with open(icon_path, "w") as stream:
            stream.write('<svg xmlns="http://www.w3.org/2000/svg"/>')
        item = {
            "type": "application", "target": "./studio",
            "workingDirectory": self.directory,
        }
        with mock.patch.object(panel_ui, "_application_records",
                               return_value=[]), mock.patch.object(
                                   Gio.DesktopAppInfo, "new",
                                   side_effect=AssertionError(
                                       "relative paths are not Desktop IDs")):
            icon = panel_ui._lookup_gicon(item)
        self.assertIsInstance(icon, Gio.FileIcon)
        self.assertEqual(icon.get_file().get_path(), icon_path)

    def test_failed_tile_rebuild_keeps_previous_four_by_four_grid(self):
        from gi.repository import Gdk

        if Gdk.Screen.get_default() is None:
            self.skipTest("no X display available for a real quick panel")
        panel = QuickPanel()
        panel.store = PanelStore(os.path.join(
            self.directory, "atomic-rebuild-panel.json"))
        original = panel_ui.Gtk.Grid()
        panel.add(original)
        panel._grid = original
        panel.config = panel.store.load()["config"]
        try:
            with mock.patch.object(panel, "_tile",
                                   side_effect=TypeError("bad icon")):
                with self.assertRaisesRegex(TypeError, "bad icon"):
                    panel._rebuild_tiles()
            self.assertIs(panel.get_child(), original)
        finally:
            panel.destroy()

    def test_url_icon_uses_cached_favicon_and_requests_missing(self):
        from wgestures import panel_ui

        cache_home = os.path.join(self.directory, "cache-home")
        favicons = os.path.join(cache_home, "wgestures", "favicons")
        os.makedirs(favicons)
        png = bytes((0x89, 0x50, 0x4E, 0x47)) + b"0" * 60
        with open(os.path.join(favicons, "cached.com.ico"), "wb") as stream:
            stream.write(png)

        cached_item = {"type": "url", "target": "https://cached.com/page"}
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": cache_home}):
            icon = panel_ui._lookup_gicon(cached_item)
            self.assertIsNotNone(icon)
            self.assertEqual(bytes(icon.get_bytes().get_data()), png)

            requested = []
            missing_item = {"type": "url", "target": "https://missing.com/"}
            icon = panel_ui._lookup_gicon(missing_item,
                                          on_missing_favicon=requested.append)
            self.assertIsNone(icon)
        self.assertEqual(requested, [missing_item])
        panel_ui._ensure_favicon.assert_not_called()

    def test_favicon_fetch_is_atomic_and_panel_invalidates_missing_icon(self):
        from gi.repository import Gdk

        cache_home = os.path.join(self.directory, "cache-home")
        png = bytes((0x89, 0x50, 0x4E, 0x47)) + b"0" * 60
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": cache_home}), \
                mock.patch.object(panel_ui, "_favicon_bytes", return_value=png):
            self.assertTrue(fetch_favicon("https://example.com/path"))
        cached = os.path.join(
            cache_home, "wgestures", "favicons", "example.com.ico")
        self.assertTrue(os.path.isfile(cached))
        self.assertFalse(os.path.exists(cached + ".tmp"))

        if Gdk.Screen.get_default() is None:
            return
        store = PanelStore(os.path.join(self.directory, "panel-favicon.json"))
        config = store.load()["config"]
        config["slots"][0] = {
            "id": "url", "label": "URL", "type": "url",
            "target": "https://missing.example/",
        }
        store.save(config)
        panel = QuickPanel()
        try:
            panel.store = store
            with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": cache_home}):
                panel.show_at(60, 60)
                key = ("url", "https://missing.example/", 40)
                panel._icon_cache[key] = object()
                with open(os.path.join(
                        cache_home, "wgestures", "favicons",
                        "missing.example.ico"), "wb") as stream:
                    stream.write(png)
                ready = panel_ui._ensure_favicon.call_args[0][1]
                ready()
                self.assertIn(key, panel._icon_cache)
                self.assertIsNotNone(panel._icon_cache[key])
        finally:
            panel.destroy()

    def test_favicon_fetch_falls_back_when_site_rejects_direct_request(self):
        cache_home = os.path.join(self.directory, "cache-fallback")
        png = bytes((0x89, 0x50, 0x4E, 0x47)) + b"0" * 60
        candidates = _favicon_candidate_urls("https://chatgpt.com/path")
        self.assertEqual(candidates[0], "https://chatgpt.com/favicon.ico")
        self.assertIn("domain=chatgpt.com", candidates[1])
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": cache_home}), \
                mock.patch.object(panel_ui, "_favicon_bytes",
                                  side_effect=[OSError("403"), png]) as fetch:
            self.assertTrue(fetch_favicon("https://chatgpt.com/path"))
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(os.path.isfile(os.path.join(
            cache_home, "wgestures", "favicons", "chatgpt.com.ico")))

    def test_quick_panel_tiles_accept_uri_list_drops(self):
        from gi.repository import Gdk, Gio

        if Gdk.Screen.get_default() is None:
            self.skipTest("no X display available for a real quick panel")

        store = PanelStore(os.path.join(self.directory, "panel-v1.json"))
        dropped_file = os.path.join(self.directory, "dropped.txt")
        with open(dropped_file, "w") as stream:
            stream.write("drop")
        dropped_folder = os.path.join(self.directory, "dropped-dir")
        os.makedirs(dropped_folder)
        panel = QuickPanel()
        try:
            panel.store = store
            panel.show_at(60, 60)
            panel._apply_drop(2, [
                Gio.File.new_for_path(dropped_file).get_uri(),
                Gio.File.new_for_path(dropped_folder).get_uri(),
                "https://example.com/",
            ], desktop_lookup=lambda _desktop_id: True)
            slots = store.load()["config"]["slots"]
            self.assertEqual(slots[2]["type"], "file")
            self.assertEqual(slots[3]["type"], "folder")
            self.assertEqual(slots[4]["type"], "url")

            occupied = store.load()["config"]["slots"]
            panel._apply_drop(2, [dropped_file],
                              desktop_lookup=lambda _desktop_id: True)
            self.assertEqual(store.load()["config"]["slots"], occupied)

            labels = [slot["label"] if slot else None
                      for slot in store.load()["config"]["slots"]]
            self.assertEqual(labels[2], "dropped.txt")
        finally:
            panel.destroy()

    def test_all_action_types_have_stable_fallback_icons(self):
        self.assertEqual(set(FALLBACK_ICON_NAMES),
                         {"application", "file", "folder", "url"})
        self.assertTrue(all(FALLBACK_ICON_NAMES.values()))

    def test_empty_tile_menu_exposes_four_direct_action_entries(self):
        class FakeMenuItem(object):
            def __init__(self, label):
                self.label = label
                self.callback = None

            def connect(self, signal, callback):
                self.assert_signal = signal
                self.callback = callback

        class FakeMenu(object):
            last = None

            def __init__(self):
                self.items = []
                FakeMenu.last = self

            def append(self, item):
                self.items.append(item)

            def show_all(self):
                pass

            def connect(self, _signal, _callback):
                pass

            def popup_at_pointer(self, _event):
                pass

        class Holder(object):
            _editing = False

            def __init__(self):
                self.edits = []

            def _edit(self, index, item_type=None):
                self.edits.append((index, item_type))

            def _menu_deactivated(self, _menu):
                pass

        holder = Holder()
        event = type("Event", (object,), {"button": 3})()
        with mock.patch("wgestures.panel_ui.Gtk.Menu", FakeMenu), \
                mock.patch("wgestures.panel_ui.Gtk.MenuItem", FakeMenuItem):
            self.assertTrue(QuickPanel._tile_press(
                holder, None, event, 4, None))
        self.assertEqual([item.label for item in FakeMenu.last.items], [
            "启动软件", "打开文件", "打开文件夹", "打开网址"])
        for item in FakeMenu.last.items:
            item.callback(item)
        self.assertEqual(holder.edits, [
            (4, "application"), (4, "file"), (4, "folder"), (4, "url")])

    def test_configured_tile_menu_keeps_only_edit_and_delete(self):
        class FakeMenuItem(object):
            def __init__(self, label):
                self.label = label

            def connect(self, _signal, _callback):
                pass

        class FakeMenu(object):
            last = None

            def __init__(self):
                self.items = []
                FakeMenu.last = self

            def append(self, item):
                self.items.append(item)

            def show_all(self):
                pass

            def connect(self, _signal, _callback):
                pass

            def popup_at_pointer(self, _event):
                pass

        class Holder(object):
            _editing = False

            def _edit(self, _index, _item_type=None):
                pass

            def _delete(self, _index):
                pass

            def _menu_deactivated(self, _menu):
                pass

        event = type("Event", (object,), {"button": 3})()
        with mock.patch("wgestures.panel_ui.Gtk.Menu", FakeMenu), \
                mock.patch("wgestures.panel_ui.Gtk.MenuItem", FakeMenuItem):
            QuickPanel._tile_press(
                Holder(), None, event, 0,
                {"type": "url", "target": "https://example.com"})
        self.assertEqual(
            [item.label for item in FakeMenu.last.items], ["编辑", "删除"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

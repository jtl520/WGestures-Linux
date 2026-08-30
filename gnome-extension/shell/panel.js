import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Mtk from 'gi://Mtk';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {matchesExecutableName, validPanelTarget} from '../core/panel.js';
import {PanelStore} from './storage.js';


const FALLBACK_ICONS = Object.freeze({
    application: 'application-x-executable-symbolic',
    file: 'text-x-generic-symbolic',
    folder: 'folder-symbolic',
    url: 'web-browser-symbolic',
});

const PANEL_ACTION_LABELS = Object.freeze({
    application: '启动软件',
    file: '打开文件',
    folder: '打开文件夹',
    url: '打开网址',
});

const FILE_MANAGER_DESKTOP_IDS = Object.freeze([
    'org.gnome.Nautilus.desktop',
    'nautilus.desktop',
    'thunar.desktop',
    'org.kde.dolphin.desktop',
    'nemo.desktop',
    'caja.desktop',
    'pcmanfm-qt.desktop',
    'pcmanfm.desktop',
]);


export class QuickPanel {
    constructor(onClosed = null) {
        this._onClosed = onClosed;
        this._store = new PanelStore();
        this._config = null;
        this._dirty = true;
        this._faviconRequests = new Set();
        this.actor = new St.BoxLayout({
            vertical: true,
            reactive: true,
            can_focus: true,
            visible: false,
            style_class: 'wgestures-quick-panel',
        });
        Main.uiGroup.add_child(this.actor);
        this._itemMenu = null;
        this._itemMenuManager = new PopupMenu.PopupMenuManager(this.actor);
        this._layout = {
            tileWidth: 104, tileHeight: 92, iconSize: 40,
            spacing: 8, padding: 12, radius: 16,
        };
        this._monitor = null;
        try {
            this._monitor = Gio.File.new_for_path(this._store.path).monitor_file(
                Gio.FileMonitorFlags.WATCH_MOVES, null
            );
            this._monitor.connect('changed', () => {
                this._dirty = true;
                if (this.visible)
                    GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                        if (this.visible && this._dirty)
                            this._reload();
                        return GLib.SOURCE_REMOVE;
                    });
            });
        } catch (error) {
            console.warn(`CrossGestures: 无法监视面板配置：${error.message}`);
        }
    }

    get visible() {
        return Boolean(this.actor?.visible);
    }

    showAt(x, y) {
        const monitorIndex = global.display.get_monitor_index_for_rect(new Mtk.Rectangle({
            x: Math.floor(x), y: Math.floor(y), width: 1, height: 1,
        }));
        const area = Main.layoutManager.getWorkAreaForMonitor(
            monitorIndex >= 0 ? monitorIndex : global.display.get_current_monitor()
        );
        this._applyMonitorLayout(area);
        if (this._dirty || !this._config)
            this._reload();
        this.actor.show();
        const [, width] = this.actor.get_preferred_width(-1);
        const [, height] = this.actor.get_preferred_height(width);
        const left = Math.max(area.x, Math.min(Math.round(x - width / 2), area.x + area.width - width));
        const top = Math.max(area.y, Math.min(Math.round(y - height / 2), area.y + area.height - height));
        this.actor.set_position(left, top);
        global.stage.set_key_focus(this.actor);
    }

    _applyMonitorLayout(area) {
        const scale = Math.max(0.68, Math.min(1.35,
            Math.min(area.width, area.height) / 900));
        const layout = {
            tileWidth: Math.round(104 * scale),
            tileHeight: Math.round(92 * scale),
            iconSize: Math.round(40 * scale),
            spacing: Math.max(5, Math.round(8 * scale)),
            padding: Math.max(8, Math.round(12 * scale)),
            radius: Math.max(10, Math.round(16 * scale)),
        };
        const changed = Object.keys(layout).some(key => layout[key] !== this._layout[key]);
        if (!changed)
            return;
        this._layout = layout;
        this.actor.set_style(
            `spacing: ${layout.spacing}px; padding: ${layout.padding}px; ` +
            `border-radius: ${layout.radius}px;`
        );
        this._dirty = true;
    }

    close() {
        this._itemMenu?.close();
        if (!this.visible)
            return;
        this.actor.hide();
        global.stage.set_key_focus(null);
        this._onClosed?.();
    }

    toggleAt(x, y) {
        if (this.visible)
            this.close();
        else
            this.showAt(x, y);
    }

    containsActor(actor) {
        let current = actor;
        while (current) {
            if (current === this.actor || current === this._itemMenu?.actor)
                return true;
            current = current.get_parent?.() || null;
        }
        return false;
    }

    destroy() {
        this._monitor?.cancel();
        this._monitor = null;
        this._itemMenu?.destroy();
        this._itemMenu = null;
        this._itemMenuManager = null;
        this.actor?.destroy();
        this.actor = null;
        this._store = null;
        this._config = null;
        this._faviconRequests = null;
    }

    _reload() {
        this._itemMenu?.destroy();
        this._itemMenu = null;
        const loaded = this._store.load();
        this._config = loaded.config;
        this._dirty = false;
        for (const child of this.actor.get_children())
            child.destroy();
        for (let rowIndex = 0; rowIndex < 4; rowIndex++) {
            const row = new St.BoxLayout({
                style_class: 'wgestures-quick-panel-row',
                style: `spacing: ${this._layout.spacing}px;`,
            });
            this.actor.add_child(row);
            for (let column = 0; column < 4; column++) {
                const index = rowIndex * 4 + column;
                row.add_child(this._tile(index, this._config.slots[index]));
            }
        }
        for (const warning of loaded.warnings)
            Main.notifyError('CrossGestures 面板', warning);
    }

    _tile(index, item) {
        const content = new St.BoxLayout({
            vertical: true,
            style_class: 'wgestures-quick-panel-tile-content',
            style: `spacing: ${Math.max(4, Math.round(this._layout.spacing * 0.75))}px;`,
        });
        content.add_child(new St.Icon({
            gicon: item ? this._iconFor(item) : new Gio.ThemedIcon({name: 'list-add-symbolic'}),
            icon_size: this._layout.iconSize,
            style_class: item ? '' : 'wgestures-quick-panel-empty-icon',
        }));
        content.add_child(new St.Label({
            text: item?.label || '',
            style_class: 'wgestures-quick-panel-label',
            style: `width: ${Math.max(56, this._layout.tileWidth - 20)}px;`,
        }));
        const button = new St.Button({
            child: content,
            reactive: true,
            can_focus: true,
            track_hover: true,
            style_class: 'wgestures-quick-panel-tile',
            style: `width: ${this._layout.tileWidth}px; ` +
                `height: ${this._layout.tileHeight}px; ` +
                `padding: ${Math.max(5, this._layout.spacing)}px;`,
        });
        button.connect('button-press-event', (_actor, event) => {
            const mouseButton = event.get_button();
            if (mouseButton === 3) {
                this._showItemMenu(button, index, item);
                return 1;
            }
            if (mouseButton === 1 && item) {
                this.close();
                this._execute(item);
                return 1;
            }
            return 0;
        });
        return button;
    }

    _showItemMenu(button, index, item) {
        this._itemMenu?.destroy();
        const menu = new PopupMenu.PopupMenu(button, 0.5, St.Side.TOP);
        this._itemMenu = menu;
        Main.uiGroup.add_child(menu.actor);
        this._itemMenuManager.addMenu(menu);
        if (item) {
            menu.addAction('编辑', () => this._edit(index));
            menu.addAction('删除', () => {
                // Rebuilding the tile grid also destroys the menu source.
                // Defer it until the activation signal has unwound.
                GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                    this._delete(index);
                    return GLib.SOURCE_REMOVE;
                });
            });
        } else {
            for (const [type, label] of Object.entries(PANEL_ACTION_LABELS))
                menu.addAction(label, () => this._edit(index, type));
        }
        menu.open();
    }

    _iconFor(item) {
        try {
            if (item.type === 'application') {
                const application = Gio.DesktopAppInfo.new(item.target);
                if (application?.get_icon())
                    return application.get_icon();
                let path = item.target;
                if (!path.startsWith('/') && item.workingDirectory)
                    path = GLib.build_filenamev([item.workingDirectory, path]);
                if (path.startsWith('/') && GLib.file_test(path, GLib.FileTest.IS_REGULAR)) {
                    const info = Gio.File.new_for_path(path).query_info(
                        'standard::icon', Gio.FileQueryInfoFlags.NONE, null
                    );
                    if (info.get_icon())
                        return info.get_icon();
                }
            } else if (item.type === 'file' || item.type === 'folder') {
                const info = Gio.File.new_for_path(item.target).query_info(
                    'standard::icon', Gio.FileQueryInfoFlags.NONE, null
                );
                if (info.get_icon())
                    return info.get_icon();
            } else if (item.type === 'url') {
                const path = this._faviconPath(item.target);
                if (path && GLib.file_test(path, GLib.FileTest.IS_REGULAR))
                    return new Gio.FileIcon({file: Gio.File.new_for_path(path)});
                this._requestFavicon(item.target);
            }
        } catch (_error) {
            // Keep a stable fallback when a configured target was removed.
        }
        return new Gio.ThemedIcon({name: FALLBACK_ICONS[item.type]});
    }

    _faviconPath(target) {
        try {
            const uri = GLib.Uri.parse(target, GLib.UriFlags.NONE);
            const host = uri.get_host()?.toLocaleLowerCase();
            if (!host || !['http', 'https'].includes(uri.get_scheme()?.toLocaleLowerCase()))
                return null;
            return GLib.build_filenamev([
                GLib.get_user_cache_dir(), 'wgestures', 'favicons', `${host}.ico`,
            ]);
        } catch (_error) {
            return null;
        }
    }

    _requestFavicon(target) {
        if (this._faviconRequests.has(target))
            return;
        this._faviconRequests.add(target);
        try {
            const process = Gio.Subprocess.new(
                ['wgestures', '--panel-fetch-icon', target],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE
            );
            process.wait_check_async(null, (source, result) => {
                try {
                    source.wait_check_finish(result);
                    this._dirty = true;
                    if (this.visible)
                        this._reload();
                } catch (_error) {
                    // Offline sites keep the stable themed browser icon.
                }
            });
        } catch (_error) {
            // Missing helper or an offline site is non-fatal.
        }
    }

    _edit(index, initialType = null) {
        // The editor is a separate GTK process. Close the Shell actor first so
        // its global outside-click handler cannot swallow the editor's first
        // click.
        this.close();
        try {
            const command = ['wgestures', '--panel-edit', String(index)];
            if (initialType)
                command.push('--panel-type', initialType);
            const process = Gio.Subprocess.new(
                command,
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE
            );
            process.wait_async(null, (source, result) => {
                try {
                    source.wait_finish(result);
                    if (this.visible)
                        this._reload();
                } catch (error) {
                    Main.notifyError('CrossGestures 面板', error.message);
                }
            });
        } catch (error) {
            Main.notifyError('CrossGestures 面板', `无法打开格子编辑器：${error.message}`);
        }
    }

    _activateRunning(executable) {
        // Match windows to processes through /proc comm, the same heuristic
        // the GTK3 backend uses, and raise the first window that fits.
        for (const actor of global.get_window_actors()) {
            const metaWindow = actor.meta_window;
            const pid = metaWindow.get_pid();
            if (pid <= 0)
                continue;
            try {
                const [, contents] = GLib.file_get_contents(`/proc/${pid}/comm`);
                if (!matchesExecutableName(executable, new TextDecoder().decode(contents)))
                    continue;
            } catch (_error) {
                // The process may have exited between enumeration and read.
                continue;
            }
            Main.activateWindow(metaWindow, global.get_current_time());
            return true;
        }
        return false;
    }

    _delete(index) {
        this._config.slots[index] = null;
        this._store.save(this._config);
        this._dirty = true;
        this._reload();
    }

    _resolveExecutable(target, workingDirectory = null) {
        let executable = String(target || '').trim();
        if (!executable.startsWith('/')) {
            if (executable.includes('/')) {
                if (!workingDirectory)
                    throw new Error(`使用相对程序路径时必须填写工作目录：${target}`);
                executable = GLib.build_filenamev([workingDirectory, executable]);
            } else {
                const local = workingDirectory
                    ? GLib.build_filenamev([workingDirectory, executable]) : null;
                executable = local && GLib.file_test(local, GLib.FileTest.IS_REGULAR)
                    ? local : GLib.find_program_in_path(executable);
                if (!executable)
                    throw new Error(`找不到软件或命令：${target}`);
            }
        }
        executable = GLib.canonicalize_filename(executable, null);
        if (!GLib.file_test(executable, GLib.FileTest.IS_REGULAR))
            throw new Error(`程序文件不存在：${executable}`);
        if (!GLib.file_test(executable, GLib.FileTest.IS_EXECUTABLE))
            throw new Error(`程序文件不可执行，请先运行 chmod +x：${executable}`);
        return executable;
    }

    _execute(item) {
        try {
            if (!validPanelTarget(item.type, item.target))
                throw new Error('格子目标无效');
            const context = global.create_app_launch_context(global.get_current_time(), -1);
            if (item.type === 'application') {
                const application = Gio.DesktopAppInfo.new(item.target);
                if (!application || item.arguments || item.workingDirectory || item.runAsAdministrator) {
                    const executable = application?.get_executable() ||
                        this._resolveExecutable(item.target, item.workingDirectory);
                    if (item.activateIfRunning && this._activateRunning(executable))
                        return;
                    const [, parsedArguments] = GLib.shell_parse_argv(item.arguments || '');
                    const command = [executable, ...parsedArguments];
                    if (item.runAsAdministrator) {
                        const pkexec = GLib.find_program_in_path('pkexec');
                        if (!pkexec)
                            throw new Error('系统未安装 pkexec，无法以管理员身份运行');
                        command.unshift(pkexec);
                    }
                    const launcher = new Gio.SubprocessLauncher({
                        flags: Gio.SubprocessFlags.NONE,
                    });
                    if (item.workingDirectory)
                        launcher.set_cwd(item.workingDirectory);
                    else if (!application)
                        launcher.set_cwd(GLib.path_get_dirname(executable));
                    launcher.spawnv(command);
                } else {
                    // Desktop activation normally raises an existing window
                    // when the application supports the freedesktop protocol.
                    application.launch([], context);
                }
                return;
            }
            if (item.type === 'file' || item.type === 'folder') {
                const file = Gio.File.new_for_path(item.target);
                if (!file.query_exists(null))
                    throw new Error(`目标不存在：${item.target}`);
                if (item.type === 'folder') {
                    for (const desktopId of FILE_MANAGER_DESKTOP_IDS) {
                        const fileManager = Gio.DesktopAppInfo.new(desktopId);
                        if (fileManager) {
                            fileManager.launch([file], context);
                            return;
                        }
                    }
                }
                Gio.AppInfo.launch_default_for_uri(file.get_uri(), context);
                return;
            }
            if (item.browser) {
                if (item.browser.startsWith('/')) {
                    Gio.Subprocess.new(
                        [item.browser, item.target], Gio.SubprocessFlags.NONE
                    );
                } else {
                    const browser = Gio.DesktopAppInfo.new(item.browser);
                    if (!browser)
                        throw new Error(`找不到浏览器：${item.browser}`);
                    browser.launch_uris([item.target], context);
                }
                return;
            }
            Gio.AppInfo.launch_default_for_uri(item.target, context);
        } catch (error) {
            Main.notifyError('CrossGestures 面板启动失败', error.message);
        }
    }
}

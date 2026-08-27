import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';

import {
    copyAccelerator, normalizeAccelerator, pasteAccelerator,
} from '../core/shortcut.js';

const MODIFIER_KEYVALS = Object.freeze({
    control: 'Control_L',
    ctrl: 'Control_L',
    alt: 'Alt_L',
    shift: 'Shift_L',
    super: 'Super_L',
    primary: 'Control_L',
});

const KEY_ALIASES = Object.freeze({
    enter: 'Return',
    return: 'Return',
    esc: 'Escape',
    escape: 'Escape',
    space: 'space',
    backspace: 'BackSpace',
    delete: 'Delete',
    insert: 'Insert',
    left: 'Left',
    right: 'Right',
    up: 'Up',
    down: 'Down',
    home: 'Home',
    end: 'End',
    tab: 'Tab',
    page_up: 'Page_Up',
    pageup: 'Page_Up',
    page_down: 'Page_Down',
    pagedown: 'Page_Down',
    audiomute: 'AudioMute',
    audiolowervolume: 'AudioLowerVolume',
    audioraisevolume: 'AudioRaiseVolume',
});

function clutterKeyval(name) {
    const normalized = KEY_ALIASES[name.toLocaleLowerCase()] || name;
    const property = `KEY_${normalized.length === 1 ? normalized.toLocaleLowerCase() : normalized}`;
    const value = Clutter[property];
    if (typeof value !== 'number')
        throw new Error(`不支持的按键名称：${name}`);
    return value;
}

export function parseAccelerator(accelerator) {
    const modifiers = [];
    const text = normalizeAccelerator(accelerator);
    const keyName = text.replace(/<([^>]+)>/g, (_match, modifier) => {
        const mapped = MODIFIER_KEYVALS[modifier.toLocaleLowerCase()];
        if (!mapped)
            throw new Error(`不支持的修饰键：${modifier}`);
        if (!modifiers.includes(mapped))
            modifiers.push(mapped);
        return '';
    }).trim();
    if (!keyName)
        throw new Error('快捷键缺少主键');
    return {modifiers: modifiers.map(clutterKeyval), key: clutterKeyval(keyName)};
}

export class ActionExecutor {
    constructor(callbacks = {}) {
        this._onPause = callbacks.onPause || (() => {});
        this._getVirtualKeyboard = callbacks.getVirtualKeyboard || (() => null);
    }

    execute(action, context = {}) {
        switch (action.type) {
        case 'ShortcutAction':
            this._executeShortcut(action.accelerator);
            break;
        case 'CopyAction':
            this._executeShortcut(copyAccelerator(context.identity));
            break;
        case 'PasteAction':
            this._executeShortcut(pasteAccelerator(context.identity));
            break;
        case 'WindowAction':
            this._executeWindow(action.operation, context.window);
            break;
        case 'CommandAction':
            this._executeCommand(action.command);
            break;
        case 'LaunchAction':
            this._executeLaunch(action.target);
            break;
        case 'PauseAction':
            this._onPause();
            break;
        case 'NoopAction':
            break;
        default:
            throw new Error(`不支持的动作：${action.type}`);
        }
    }

    _executeShortcut(accelerator) {
        const keyboard = this._getVirtualKeyboard();
        if (!keyboard)
            throw new Error('无法创建虚拟键盘');

        const parsed = parseAccelerator(accelerator);
        let timestamp = GLib.get_monotonic_time();
        for (const modifier of parsed.modifiers)
            keyboard.notify_keyval(timestamp++, modifier, Clutter.KeyState.PRESSED);
        keyboard.notify_keyval(timestamp++, parsed.key, Clutter.KeyState.PRESSED);
        keyboard.notify_keyval(timestamp++, parsed.key, Clutter.KeyState.RELEASED);
        for (const modifier of [...parsed.modifiers].reverse())
            keyboard.notify_keyval(timestamp++, modifier, Clutter.KeyState.RELEASED);
    }

    _executeWindow(operation, window) {
        if (!window)
            throw new Error('没有可控制的目标窗口');
        const timestamp = global.get_current_time();

        switch (operation) {
        case 'toggle-maximized':
            if (window.get_maximize_flags() === Meta.MaximizeFlags.BOTH)
                window.unmaximize(Meta.MaximizeFlags.BOTH);
            else if (window.can_maximize())
                window.maximize(Meta.MaximizeFlags.BOTH);
            break;
        case 'minimize':
            if (window.can_minimize())
                window.minimize();
            break;
        case 'close':
            if (window.can_close())
                window.delete(timestamp);
            break;
        case 'toggle-fullscreen':
            if (window.is_fullscreen())
                window.unmake_fullscreen();
            else
                window.make_fullscreen();
            break;
        case 'toggle-above':
            if (window.is_above())
                window.unmake_above();
            else
                window.make_above();
            break;
        default:
            throw new Error(`未知窗口动作：${operation}`);
        }
    }

    _executeCommand(command) {
        if (!String(command || '').trim())
            throw new Error('命令内容为空');
        Gio.Subprocess.new(
            ['/bin/sh', '-lc', command],
            Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE
        );
    }

    _executeLaunch(target) {
        const value = String(target || '').trim();
        if (!value)
            throw new Error('打开目标为空');
        const context = global.create_app_launch_context(global.get_current_time(), -1);
        if (/^[a-z][a-z0-9+.-]*:/i.test(value)) {
            Gio.AppInfo.launch_default_for_uri(value, context);
            return;
        }
        if (GLib.path_is_absolute(value) || value.includes('/')) {
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(value).get_uri(), context);
            return;
        }
        const desktopIds = new Set([value, value.endsWith('.desktop') ? value : `${value}.desktop`]);
        const application = Gio.AppInfo.get_all().find(app => desktopIds.has(app.get_id()));
        if (application) {
            application.launch([], context);
            return;
        }
        Gio.AppInfo.create_from_commandline(
            value, null, Gio.AppInfoCreateFlags.NONE
        ).launch([], context);
    }
}

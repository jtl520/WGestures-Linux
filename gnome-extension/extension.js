import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import St from 'gi://St';

import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {GestureRecognizer} from './core/gesture.js';
import {GestureSession, ReplayGuard} from './core/input-state.js';
import {resolveGesture} from './core/config.js';
import {actionDisplayName} from './core/shortcut.js';
import {ActionExecutor} from './shell/actions.js';
import {GestureOverlay} from './shell/overlay.js';
import {ConfigStore} from './shell/storage.js';

const CLUTTER_BUTTONS = Object.freeze({2: 'middle', 3: 'right', 8: 'x1', 9: 'x2'});
const EVDEV_BUTTONS = Object.freeze({right: 273, middle: 274, x1: 275, x2: 276});

class WGesturesIndicator extends PanelMenu.Button {
    constructor(settings, openPreferences) {
        super(0.0, _('WGestures'));
        this._settings = settings;
        this._icon = new St.Icon({icon_name: 'input-mouse-symbolic', style_class: 'system-status-icon'});
        this.add_child(this._icon);

        this._enabledItem = new PopupMenu.PopupSwitchMenuItem(_('启用鼠标手势'), true);
        this._enabledItem.connect('toggled', (_item, state) => settings.set_boolean('enabled', state));
        this.menu.addMenuItem(this._enabledItem);

        this._pausedItem = new PopupMenu.PopupSwitchMenuItem(_('暂停'), false);
        this._pausedItem.connect('toggled', (_item, state) => settings.set_boolean('paused', state));
        this.menu.addMenuItem(this._pausedItem);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const preferencesItem = new PopupMenu.PopupMenuItem(_('设置'));
        preferencesItem.connect('activate', openPreferences);
        this.menu.addMenuItem(preferencesItem);
        this._sync();
    }

    _sync() {
        const enabled = this._settings.get_boolean('enabled');
        const paused = this._settings.get_boolean('paused');
        this._enabledItem.setToggleState(enabled);
        this._pausedItem.setToggleState(paused);
        this._icon.icon_name = enabled && !paused ? 'input-mouse-symbolic' : 'media-playback-pause-symbolic';
        this.toggle_style_class_name('wgestures-indicator-paused', !enabled || paused);
    }
}

export default class WGesturesExtension extends Extension {
    enable() {
        this._settings = this.getSettings();
        this._store = new ConfigStore();
        this._loadConfig();
        this._recognizer = new GestureRecognizer();
        this._session = new GestureSession(this._recognizer);
        this._overlay = new GestureOverlay(this._settings);
        this._replayGuard = new ReplayGuard();

        const clutterContext = global.stage.get_context?.() || global.stage.context;
        const backend = clutterContext?.get_backend?.() || Clutter.get_default_backend?.();
        this._seat = backend?.get_default_seat?.() || null;
        this._virtualPointer = null;
        this._virtualKeyboard = null;
        this._virtualDeviceWarningShown = false;
        if (this._seat)
            this._initializeVirtualDevices(this._seat);
        this._executor = new ActionExecutor({
            onPause: () => this._settings.set_boolean('paused', true),
            getVirtualKeyboard: () => this._virtualKeyboard,
        });

        this._indicator = new WGesturesIndicator(this._settings, () => this.openPreferences());
        Main.panel.addToStatusArea(this.uuid, this._indicator);

        this._signals = [
            [global.stage, global.stage.connect('captured-event', (_actor, event) => this._onCapturedEvent(event))],
            [Main.layoutManager, Main.layoutManager.connect('monitors-changed', () => {
                this._cancelGesture();
                this._overlay.resize();
            })],
            [Main.sessionMode, Main.sessionMode.connect('updated', () => this._cancelGesture())],
            [this._settings, this._settings.connect('changed::config-revision', () => {
                this._cancelGesture();
                this._loadConfig();
            })],
            [this._settings, this._settings.connect('changed::paused', () => {
                this._cancelGesture();
                this._indicator._sync();
            })],
            [this._settings, this._settings.connect('changed::enabled', () => {
                this._cancelGesture();
                this._indicator._sync();
            })],
        ];
    }

    disable() {
        this._cancelGesture();
        for (const [object, signalId] of this._signals || [])
            object.disconnect(signalId);
        this._signals = [];
        this._indicator?.destroy();
        this._overlay?.destroy();
        this._indicator = null;
        this._overlay = null;
        this._executor = null;
        this._virtualPointer = null;
        this._virtualKeyboard = null;
        this._seat = null;
        this._recognizer = null;
        this._session = null;
        this._store = null;
        this._settings = null;
        this._config = null;
    }

    _loadConfig() {
        const loaded = this._store.load();
        this._config = loaded.config;
        for (const warning of loaded.warnings)
            console.warn(`WGestures: ${warning}`);
    }

    _onCapturedEvent(event) {
        try {
            const type = event.type();
            const device = event.get_source_device?.();
            if ((!this._virtualPointer || !this._virtualKeyboard) && device?.get_seat)
                this._initializeVirtualDevices(device.get_seat());
            if (device === this._virtualPointer || device === this._virtualKeyboard)
                return Clutter.EVENT_PROPAGATE;

            if (type === Clutter.EventType.KEY_PRESS && this._session.active &&
                event.get_key_symbol() === Clutter.KEY_Escape) {
                this._cancelGesture(_('已取消'));
                return Clutter.EVENT_STOP;
            }

            if (type === Clutter.EventType.BUTTON_PRESS || type === Clutter.EventType.BUTTON_RELEASE) {
                const buttonNumber = event.get_button();
                if (this._consumeReplayGuard(buttonNumber))
                    return Clutter.EVENT_PROPAGATE;
                const buttonName = CLUTTER_BUTTONS[buttonNumber];
                if (!buttonName)
                    return this._session.active ? Clutter.EVENT_STOP : Clutter.EVENT_PROPAGATE;
                if (type === Clutter.EventType.BUTTON_PRESS)
                    return this._onButtonPress(event, buttonNumber, buttonName);
                return this._onButtonRelease(event, buttonNumber, buttonName);
            }

            if (type === Clutter.EventType.MOTION && this._session.active) {
                const [x, y] = event.get_coords();
                this._session.motion(x, y);
                this._overlay.addPoint(x, y);
                return Clutter.EVENT_STOP;
            }
        } catch (error) {
            logError(error, 'WGestures input handler failed');
            this._cancelGesture(_('发生错误'));
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _onButtonPress(event, buttonNumber, buttonName) {
        if (this._session.active)
            return Clutter.EVENT_STOP;
        if (!this._settings.get_boolean('enabled') || this._settings.get_boolean('paused'))
            return Clutter.EVENT_PROPAGATE;
        if (!this._settings.get_strv('trigger-buttons').includes(buttonName))
            return Clutter.EVENT_PROPAGATE;
        if (!this._virtualPointer || !this._virtualKeyboard) {
            if (!this._virtualDeviceWarningShown) {
                this._virtualDeviceWarningShown = true;
                Main.notifyError(
                    _('WGestures 无法启动'),
                    _('GNOME Shell 未提供虚拟输入设备；为避免丢失普通点击，手势捕获已停用。')
                );
            }
            return Clutter.EVENT_PROPAGATE;
        }

        const [x, y] = event.get_coords();
        const window = this._windowForEvent(event);
        this._recognizer.configure({
            directionMode: this._settings.get_int('direction-mode'),
            startThreshold: this._settings.get_int('start-threshold'),
            segmentThreshold: this._settings.get_int('segment-threshold'),
        });
        this._session.begin({
            buttonNumber,
            buttonName,
            window,
            identity: this._identityForWindow(window),
        }, x, y);
        this._overlay.begin(x, y);
        return Clutter.EVENT_STOP;
    }

    _onButtonRelease(_event, buttonNumber, buttonName) {
        const released = this._session.release(buttonNumber);
        if (!released.handled)
            return Clutter.EVENT_PROPAGATE;
        if (released.mismatched)
            return Clutter.EVENT_STOP;
        const active = released.context;
        const result = released.result;
        if (!result.effective) {
            this._overlay.clear();
            this._replayClick(buttonNumber, buttonName);
            return Clutter.EVENT_STOP;
        }

        const matched = resolveGesture(
            this._config, active.identity, buttonName, result.directions, result
        );
        if (!matched) {
            this._overlay.finish(_('未匹配手势'), true);
            return Clutter.EVENT_STOP;
        }

        try {
            this._executor.execute(matched.action, {
                window: active.window,
                identity: active.identity,
            });
            this._overlay.finish(actionDisplayName(matched.action, matched.gesture), false);
        } catch (error) {
            logError(error, `WGestures action failed: ${matched.action.name}`);
            this._overlay.finish(_('动作失败'), true);
            Main.notifyError(_('WGestures 动作失败'), error.message);
        }
        return Clutter.EVENT_STOP;
    }

    _replayClick(buttonNumber, buttonName) {
        const evdevButton = EVDEV_BUTTONS[buttonName];
        if (!this._virtualPointer || !evdevButton)
            return;
        this._replayGuard.arm(buttonNumber, GLib.get_monotonic_time());
        let timestamp = GLib.get_monotonic_time();
        this._virtualPointer.notify_button(timestamp++, evdevButton, Clutter.ButtonState.PRESSED);
        this._virtualPointer.notify_button(timestamp++, evdevButton, Clutter.ButtonState.RELEASED);
    }

    _consumeReplayGuard(buttonNumber) {
        return this._replayGuard.consume(buttonNumber, GLib.get_monotonic_time());
    }

    _windowForEvent(event) {
        let actor = event.get_source?.() || global.stage.get_event_actor?.(event) || null;
        while (actor) {
            const window = actor.metaWindow || actor.meta_window || actor.get_meta_window?.();
            if (window)
                return window;
            actor = actor.get_parent?.() || null;
        }
        const [pointerX, pointerY] = event.get_coords();
        const windowActors = global.get_window_actors?.() || [];
        for (const windowActor of [...windowActors].reverse()) {
            if (!windowActor.visible)
                continue;
            const [actorX, actorY] = windowActor.get_transformed_position();
            const [actorWidth, actorHeight] = windowActor.get_transformed_size();
            if (pointerX >= actorX && pointerX < actorX + actorWidth &&
                pointerY >= actorY && pointerY < actorY + actorHeight) {
                const window = windowActor.metaWindow || windowActor.meta_window ||
                    windowActor.get_meta_window?.();
                if (window)
                    return window;
            }
        }
        return global.display.focus_window || null;
    }

    _identityForWindow(window) {
        if (!window)
            return {};
        const app = Shell.WindowTracker.get_default().get_window_app(window);
        return {
            sandboxedAppId: window.get_sandboxed_app_id?.() || null,
            desktopId: app?.get_id?.() || null,
            gtkApplicationId: window.get_gtk_application_id?.() || null,
            wmClass: window.get_wm_class?.() || null,
        };
    }

    _initializeVirtualDevices(seat) {
        try {
            this._seat = seat;
            this._virtualPointer ||= seat.create_virtual_device(Clutter.InputDeviceType.POINTER_DEVICE);
            this._virtualKeyboard ||= seat.create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
        } catch (error) {
            logError(error, 'WGestures could not create Clutter virtual input devices');
            this._virtualPointer = null;
            this._virtualKeyboard = null;
        }
    }

    _cancelGesture(message = null) {
        const hadActiveGesture = Boolean(this._session?.active);
        if (hadActiveGesture)
            this._session.cancel();
        if (message && hadActiveGesture)
            this._overlay?.finish(message, true);
        else
            this._overlay?.clear();
    }
}

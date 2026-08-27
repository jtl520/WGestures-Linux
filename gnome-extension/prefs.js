import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences, gettext as _} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

import {GestureRecognizer, BUTTONS, DIRECTIONS, gestureKey} from './core/gesture.js';
import {ACTION_TYPES, createDefaultConfig} from './core/config.js';
import {importLegacyConfig} from './core/importer.js';
import {ConfigStore} from './shell/storage.js';

const BUTTON_LABELS = Object.freeze({right: '右键', middle: '中键', x1: 'X1', x2: 'X2'});
const ACTION_LABELS = Object.freeze({
    ShortcutAction: '快捷键',
    WindowAction: '窗口控制',
    CommandAction: 'Shell 命令',
    LaunchAction: '打开文件、应用或网址',
    PauseAction: '暂停',
    NoopAction: '空操作',
});
const WINDOW_OPERATIONS = Object.freeze([
    ['toggle-maximized', '最大化/恢复'],
    ['minimize', '最小化'],
    ['close', '关闭'],
    ['toggle-fullscreen', '全屏/恢复'],
    ['toggle-above', '置顶/取消置顶'],
]);
const MATCHER_TYPES = Object.freeze([
    ['sandboxedAppId', 'Snap/Flatpak ID'],
    ['desktopId', 'Desktop ID'],
    ['gtkApplicationId', 'GTK Application ID'],
    ['wmClass', 'WM Class'],
]);

function stringDropDown(strings, selected = 0) {
    return new Gtk.DropDown({model: Gtk.StringList.new(strings), selected});
}

function label(text) {
    return new Gtk.Label({label: text, xalign: 0, wrap: true});
}

function inputRow(title, widget) {
    const box = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 6});
    box.append(label(title));
    box.append(widget);
    return box;
}

function profileGestureKey(item) {
    return gestureKey(item.button, item.directions);
}

class GestureEditor {
    constructor(owner, profile, gesture = null) {
        this._owner = owner;
        this._profile = profile;
        this._gesture = gesture;
        this._action = gesture
            ? owner._config.actions.find(item => item.id === gesture.actionId) || null
            : null;
        this._points = [];
        this._recognizer = new GestureRecognizer({
            directionMode: owner._settings.get_int('direction-mode'),
            startThreshold: 5,
            segmentThreshold: 12,
        });
        this._build();
    }

    _build() {
        this.dialog = new Gtk.Dialog({
            title: this._gesture ? _('编辑手势') : _('添加手势'),
            transient_for: this._owner._window,
            modal: true,
            use_header_bar: 1,
            default_width: 520,
            default_height: 620,
        });
        this.dialog.add_button(_('取消'), Gtk.ResponseType.CANCEL);
        if (this._gesture)
            this.dialog.add_button(_('删除'), Gtk.ResponseType.REJECT);
        this.dialog.add_button(_('保存'), Gtk.ResponseType.ACCEPT);

        const content = this.dialog.get_content_area();
        content.margin_top = 18;
        content.margin_bottom = 18;
        content.margin_start = 18;
        content.margin_end = 18;
        content.spacing = 14;

        this._name = new Gtk.Entry({text: this._gesture?.name || ''});
        content.append(inputRow(_('名称'), this._name));

        this._button = stringDropDown(BUTTONS.map(item => BUTTON_LABELS[item]),
            Math.max(0, BUTTONS.indexOf(this._gesture?.button || 'right')));
        content.append(inputRow(_('触发按钮'), this._button));

        this._directions = new Gtk.Entry({
            text: this._gesture?.directions?.join(',') || '',
            placeholder_text: 'left,up,right',
        });
        content.append(inputRow(_('方向（用逗号分隔）'), this._directions));

        this._drawing = new Gtk.DrawingArea({
            content_width: 420,
            content_height: 180,
            hexpand: true,
            css_classes: ['card'],
            tooltip_text: _('按住左键绘制以录入方向'),
        });
        this._drawing.set_draw_func((_area, cr) => this._draw(cr));
        const drag = new Gtk.GestureDrag({button: 1});
        drag.connect('drag-begin', (_gesture, x, y) => {
            this._points = [{x, y}];
            this._dragOrigin = {x, y};
            this._recognizer.begin(x, y);
            this._drawing.queue_draw();
        });
        drag.connect('drag-update', (_gesture, dx, dy) => {
            const x = this._dragOrigin.x + dx;
            const y = this._dragOrigin.y + dy;
            this._points.push({x, y});
            this._recognizer.addPoint(x, y);
            this._drawing.queue_draw();
        });
        drag.connect('drag-end', () => {
            const result = this._recognizer.finish();
            if (result.effective)
                this._directions.text = result.directions.join(',');
        });
        this._drawing.add_controller(drag);
        content.append(inputRow(_('手势录制区'), this._drawing));

        const actionIndex = Math.max(0, ACTION_TYPES.indexOf(this._action?.type || 'ShortcutAction'));
        this._actionType = stringDropDown(ACTION_TYPES.map(item => ACTION_LABELS[item]), actionIndex);
        this._actionType.connect('notify::selected', () => this._syncActionInput());
        content.append(inputRow(_('动作类型'), this._actionType));

        this._actionValueBox = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 6});
        content.append(this._actionValueBox);
        this._syncActionInput();

        this.dialog.connect('response', (_dialog, response) => this._onResponse(response));
        this.dialog.present();
    }

    _draw(cr) {
        if (this._points.length < 2)
            return;
        cr.setSourceRGBA(0.15, 0.68, 0.38, 1);
        cr.setLineWidth(4);
        cr.moveTo(this._points[0].x, this._points[0].y);
        for (const point of this._points.slice(1))
            cr.lineTo(point.x, point.y);
        cr.stroke();
    }

    _syncActionInput() {
        while (this._actionValueBox.get_first_child())
            this._actionValueBox.remove(this._actionValueBox.get_first_child());
        const type = ACTION_TYPES[this._actionType.selected];
        this._actionValue = null;

        if (type === 'WindowAction') {
            const current = WINDOW_OPERATIONS.findIndex(([operation]) => operation === this._action?.operation);
            this._actionValue = stringDropDown(WINDOW_OPERATIONS.map(([, name]) => name), Math.max(0, current));
            this._actionValueBox.append(inputRow(_('窗口操作'), this._actionValue));
        } else if (type === 'ShortcutAction') {
            this._actionValue = new Gtk.Entry({
                text: this._action?.accelerator || '',
                placeholder_text: '<Control><Shift>t',
            });
            this._actionValueBox.append(inputRow(_('快捷键'), this._actionValue));
        } else if (type === 'CommandAction') {
            this._actionValue = new Gtk.Entry({
                text: this._action?.command || '',
                placeholder_text: 'notify-send "Hello"',
                tooltip_text: _('命令会通过 /bin/sh -lc 以当前用户权限执行'),
            });
            this._actionValueBox.append(inputRow(_('Shell 命令（请仅使用可信内容）'), this._actionValue));
        } else if (type === 'LaunchAction') {
            this._actionValue = new Gtk.Entry({
                text: this._action?.target || '',
                placeholder_text: 'https://example.com 或 /home/user/file',
            });
            this._actionValueBox.append(inputRow(_('目标'), this._actionValue));
        } else {
            this._actionValueBox.append(label(_('此动作没有额外参数。')));
        }
    }

    _onResponse(response) {
        if (response === Gtk.ResponseType.REJECT) {
            this._delete();
            this.dialog.destroy();
            return;
        }
        if (response !== Gtk.ResponseType.ACCEPT) {
            this.dialog.destroy();
            return;
        }

        const directions = this._directions.text
            .split(',')
            .map(item => item.trim().toLocaleLowerCase())
            .filter(Boolean);
        if (directions.length === 0 || directions.some(item => !DIRECTIONS.includes(item))) {
            this._owner._toast(_('方向无效，请使用 up、up-right、right、down-right、down、down-left、left、up-left'));
            return;
        }
        const button = BUTTONS[this._button.selected];
        const key = gestureKey(button, directions);
        const conflict = this._profile.gestures.find(item =>
            item !== this._gesture && profileGestureKey(item) === key
        );
        if (conflict) {
            this._owner._toast(`${_('手势冲突')}：${conflict.name}`);
            return;
        }

        const type = ACTION_TYPES[this._actionType.selected];
        const action = this._action || {
            id: `action-${GLib.uuid_string_random()}`,
            enabled: true,
        };
        action.name = this._name.text.trim() || _('未命名动作');
        action.type = type;
        delete action.accelerator;
        delete action.operation;
        delete action.command;
        delete action.target;
        if (type === 'ShortcutAction')
            action.accelerator = this._actionValue.text.trim();
        else if (type === 'WindowAction')
            action.operation = WINDOW_OPERATIONS[this._actionValue.selected][0];
        else if (type === 'CommandAction')
            action.command = this._actionValue.text;
        else if (type === 'LaunchAction')
            action.target = this._actionValue.text.trim();

        if (!this._action)
            this._owner._config.actions.push(action);
        const gesture = this._gesture || {
            id: `gesture-${GLib.uuid_string_random()}`,
            enabled: true,
        };
        gesture.name = this._name.text.trim() || _('未命名手势');
        gesture.button = button;
        gesture.directions = directions;
        gesture.actionId = action.id;
        if (!this._gesture)
            this._profile.gestures.push(gesture);

        this._owner._save();
        this._owner._refreshGestures();
        this.dialog.destroy();
    }

    _delete() {
        const gestureIndex = this._profile.gestures.indexOf(this._gesture);
        if (gestureIndex >= 0)
            this._profile.gestures.splice(gestureIndex, 1);
        const stillUsed = [this._owner._config.globalProfile, ...this._owner._config.profiles]
            .some(profile => profile.gestures.some(item => item.actionId === this._gesture.actionId));
        if (!stillUsed) {
            const actionIndex = this._owner._config.actions.findIndex(item => item.id === this._gesture.actionId);
            if (actionIndex >= 0)
                this._owner._config.actions.splice(actionIndex, 1);
        }
        this._owner._save();
        this._owner._refreshGestures();
    }
}

export default class WGesturesPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        this._window = window;
        this._settings = this.getSettings();
        this._store = new ConfigStore();
        const loaded = this._store.load();
        this._config = loaded.config;
        window.set_default_size(760, 720);

        this._buildGeneralPage();
        this._buildGesturesPage();
        this._buildApplicationsPage();
        this._buildImportPage();
        for (const warning of loaded.warnings)
            this._toast(warning);
    }

    _buildGeneralPage() {
        const page = new Adw.PreferencesPage({title: _('常规'), icon_name: 'preferences-system-symbolic'});
        this._window.add(page);
        const behavior = new Adw.PreferencesGroup({title: _('行为')});
        page.add(behavior);

        const enabled = new Adw.SwitchRow({title: _('启用鼠标手势')});
        this._settings.bind('enabled', enabled, 'active', Gio.SettingsBindFlags.DEFAULT);
        behavior.add(enabled);

        const buttonsGroup = new Adw.PreferencesGroup({title: _('触发按钮')});
        page.add(buttonsGroup);
        for (const button of BUTTONS) {
            const row = new Adw.SwitchRow({title: BUTTON_LABELS[button]});
            row.active = this._settings.get_strv('trigger-buttons').includes(button);
            row.connect('notify::active', () => {
                const current = new Set(this._settings.get_strv('trigger-buttons'));
                if (row.active)
                    current.add(button);
                else
                    current.delete(button);
                if (current.size === 0) {
                    row.active = true;
                    return;
                }
                this._settings.set_strv('trigger-buttons', BUTTONS.filter(item => current.has(item)));
            });
            buttonsGroup.add(row);
        }

        const recognition = new Adw.PreferencesGroup({title: _('识别')});
        page.add(recognition);
        const directionMode = new Adw.ComboRow({
            title: _('方向模式'),
            model: Gtk.StringList.new([_('四方向'), _('八方向')]),
            selected: this._settings.get_int('direction-mode') === 4 ? 0 : 1,
        });
        directionMode.connect('notify::selected', () =>
            this._settings.set_int('direction-mode', directionMode.selected === 0 ? 4 : 8));
        recognition.add(directionMode);
        recognition.add(this._spinRow(_('起始移动阈值'), 'start-threshold', 2, 100, 1));
        recognition.add(this._spinRow(_('方向采样距离'), 'segment-threshold', 2, 200, 1));

        const appearance = new Adw.PreferencesGroup({title: _('轨迹')});
        page.add(appearance);
        const color = new Adw.EntryRow({title: _('轨迹颜色'), text: this._settings.get_string('path-color')});
        color.connect('changed', () => {
            if (/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(color.text))
                this._settings.set_string('path-color', color.text);
        });
        appearance.add(color);
        const invalidColor = new Adw.EntryRow({
            title: _('无效手势颜色'),
            text: this._settings.get_string('invalid-path-color'),
        });
        invalidColor.connect('changed', () => {
            if (/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(invalidColor.text))
                this._settings.set_string('invalid-path-color', invalidColor.text);
        });
        appearance.add(invalidColor);
        appearance.add(this._spinRow(_('轨迹宽度'), 'path-width', 1, 24, 0.5, true));
        appearance.add(this._spinRow(_('淡出时间（毫秒）'), 'fade-duration', 0, 3000, 50));
        const showName = new Adw.SwitchRow({title: _('显示命令名称')});
        this._settings.bind('show-command-name', showName, 'active', Gio.SettingsBindFlags.DEFAULT);
        appearance.add(showName);
    }

    _spinRow(title, key, min, max, step, isDouble = false) {
        const row = Adw.SpinRow.new_with_range(min, max, step);
        row.title = title;
        row.value = isDouble ? this._settings.get_double(key) : this._settings.get_int(key);
        row.connect('notify::value', () => {
            if (isDouble)
                this._settings.set_double(key, row.value);
            else
                this._settings.set_int(key, Math.round(row.value));
        });
        return row;
    }

    _buildGesturesPage() {
        const page = new Adw.PreferencesPage({title: _('手势'), icon_name: 'input-mouse-symbolic'});
        this._window.add(page);
        const profileGroup = new Adw.PreferencesGroup({title: _('配置范围')});
        page.add(profileGroup);
        this._profileSelector = new Adw.ComboRow({title: _('应用配置')});
        this._profileSelector.connect('notify::selected', () => this._refreshGestures());
        profileGroup.add(this._profileSelector);

        this._gestureGroup = new Adw.PreferencesGroup({title: _('手势列表')});
        const addButton = new Gtk.Button({label: _('添加'), valign: Gtk.Align.CENTER});
        addButton.connect('clicked', () => new GestureEditor(this, this._selectedProfile()));
        this._gestureGroup.header_suffix = addButton;
        page.add(this._gestureGroup);
        this._refreshProfileSelector();
        this._refreshGestures();
    }

    _selectedProfile() {
        const profiles = [this._config.globalProfile, ...this._config.profiles];
        return profiles[Math.min(this._profileSelector.selected, profiles.length - 1)] || this._config.globalProfile;
    }

    _refreshProfileSelector() {
        const selected = this._profileSelector?.selected || 0;
        this._profileSelector.model = Gtk.StringList.new(
            [this._config.globalProfile, ...this._config.profiles].map(profile => profile.name)
        );
        this._profileSelector.selected = Math.min(selected, this._config.profiles.length);
    }

    _clearGroup(group, rows) {
        for (const row of rows || [])
            group.remove(row);
        return [];
    }

    _refreshGestures() {
        if (!this._gestureGroup)
            return;
        this._gestureRows = this._clearGroup(this._gestureGroup, this._gestureRows);
        const profile = this._selectedProfile();
        for (const [index, gesture] of profile.gestures.entries()) {
            const action = this._config.actions.find(item => item.id === gesture.actionId);
            const row = new Adw.ActionRow({
                title: gesture.name,
                subtitle: `${BUTTON_LABELS[gesture.button]} · ${gesture.directions.join(' → ')} · ${ACTION_LABELS[action?.type] || _('未知动作')}`,
            });
            const edit = new Gtk.Button({icon_name: 'document-edit-symbolic', valign: Gtk.Align.CENTER});
            edit.connect('clicked', () => new GestureEditor(this, profile, gesture));
            const moveUp = new Gtk.Button({icon_name: 'go-up-symbolic', valign: Gtk.Align.CENTER, sensitive: index > 0});
            moveUp.connect('clicked', () => this._moveGesture(profile, index, -1));
            const moveDown = new Gtk.Button({
                icon_name: 'go-down-symbolic',
                valign: Gtk.Align.CENTER,
                sensitive: index < profile.gestures.length - 1,
            });
            moveDown.connect('clicked', () => this._moveGesture(profile, index, 1));
            row.add_suffix(moveUp);
            row.add_suffix(moveDown);
            row.add_suffix(edit);
            this._gestureGroup.add(row);
            this._gestureRows.push(row);
        }
        if (profile.gestures.length === 0) {
            const empty = new Adw.ActionRow({title: _('尚未配置手势')});
            this._gestureGroup.add(empty);
            this._gestureRows.push(empty);
        }
    }

    _moveGesture(profile, index, delta) {
        const target = index + delta;
        if (target < 0 || target >= profile.gestures.length)
            return;
        [profile.gestures[index], profile.gestures[target]] =
            [profile.gestures[target], profile.gestures[index]];
        this._save();
        this._refreshGestures();
    }

    _buildApplicationsPage() {
        const page = new Adw.PreferencesPage({title: _('应用'), icon_name: 'view-app-grid-symbolic'});
        this._window.add(page);
        this._applicationGroup = new Adw.PreferencesGroup({
            title: _('应用配置'),
            description: _('按 Snap/Flatpak ID、Desktop ID、GTK Application ID 或 WM Class 匹配。'),
        });
        const addButton = new Gtk.Button({label: _('添加'), valign: Gtk.Align.CENTER});
        addButton.connect('clicked', () => this._editProfile());
        this._applicationGroup.header_suffix = addButton;
        page.add(this._applicationGroup);
        this._refreshApplications();
    }

    _refreshApplications() {
        this._applicationRows = this._clearGroup(this._applicationGroup, this._applicationRows);
        for (const profile of this._config.profiles) {
            const matcher = profile.matchers[0];
            const subtitle = matcher
                ? `${MATCHER_TYPES.find(([type]) => type === matcher.type)?.[1] || matcher.type}: ${matcher.value}`
                : `${_('未绑定')} · ${profile.legacyExecutablePath || _('需要选择 Linux 应用标识')}`;
            const row = new Adw.ActionRow({title: profile.name, subtitle});
            const edit = new Gtk.Button({icon_name: 'document-edit-symbolic', valign: Gtk.Align.CENTER});
            edit.connect('clicked', () => this._editProfile(profile));
            row.add_suffix(edit);
            this._applicationGroup.add(row);
            this._applicationRows.push(row);
        }
        if (this._config.profiles.length === 0) {
            const empty = new Adw.ActionRow({title: _('尚未添加应用配置')});
            this._applicationGroup.add(empty);
            this._applicationRows.push(empty);
        }
    }

    _editProfile(profile = null) {
        const dialog = new Gtk.Dialog({
            title: profile ? _('编辑应用配置') : _('添加应用配置'),
            transient_for: this._window,
            modal: true,
            use_header_bar: 1,
            default_width: 480,
        });
        dialog.add_button(_('取消'), Gtk.ResponseType.CANCEL);
        if (profile)
            dialog.add_button(_('删除'), Gtk.ResponseType.REJECT);
        dialog.add_button(_('保存'), Gtk.ResponseType.ACCEPT);
        const box = dialog.get_content_area();
        box.margin_top = box.margin_bottom = box.margin_start = box.margin_end = 18;
        box.spacing = 14;
        const name = new Gtk.Entry({text: profile?.name || ''});
        const matcherIndex = Math.max(0, MATCHER_TYPES.findIndex(([type]) => type === profile?.matchers?.[0]?.type));
        const matcherType = stringDropDown(MATCHER_TYPES.map(([, title]) => title), matcherIndex);
        const matcherValue = new Gtk.Entry({text: profile?.matchers?.[0]?.value || ''});
        const inherit = new Gtk.CheckButton({label: _('继承全局手势'), active: profile?.inheritGlobal !== false});
        const enabled = new Gtk.CheckButton({label: _('启用此应用的手势'), active: profile?.enabled !== false});
        box.append(inputRow(_('名称'), name));
        box.append(inputRow(_('匹配类型'), matcherType));
        box.append(inputRow(_('匹配值'), matcherValue));
        box.append(inherit);
        box.append(enabled);
        dialog.connect('response', (_dialog, response) => {
            if (response === Gtk.ResponseType.REJECT) {
                this._config.profiles.splice(this._config.profiles.indexOf(profile), 1);
                this._removeUnusedActions();
                this._save();
            } else if (response === Gtk.ResponseType.ACCEPT) {
                if (!name.text.trim() || !matcherValue.text.trim()) {
                    this._toast(_('名称和匹配值不能为空'));
                    return;
                }
                const target = profile || {
                    id: `profile-${GLib.uuid_string_random()}`,
                    gestures: [],
                };
                target.name = name.text.trim();
                target.enabled = enabled.active;
                target.inheritGlobal = inherit.active;
                target.matchers = [{type: MATCHER_TYPES[matcherType.selected][0], value: matcherValue.text.trim()}];
                if (!profile)
                    this._config.profiles.push(target);
                this._save();
            } else {
                dialog.destroy();
                return;
            }
            this._refreshApplications();
            this._refreshProfileSelector();
            this._refreshGestures();
            dialog.destroy();
        });
        dialog.present();
    }

    _buildImportPage() {
        const page = new Adw.PreferencesPage({title: _('导入与恢复'), icon_name: 'document-open-symbolic'});
        this._window.add(page);
        const importGroup = new Adw.PreferencesGroup({
            title: _('Windows 配置'),
            description: _('安全读取 .wg2 JSON；Windows 路径、命令、Lua 和修饰手势不会自动启用。'),
        });
        page.add(importGroup);
        const importRow = new Adw.ActionRow({title: _('导入 .wg2 文件')});
        const importButton = new Gtk.Button({label: _('选择文件'), valign: Gtk.Align.CENTER});
        importButton.connect('clicked', () => this._chooseLegacyFile());
        importRow.add_suffix(importButton);
        importGroup.add(importRow);

        const resetGroup = new Adw.PreferencesGroup({title: _('恢复')});
        page.add(resetGroup);
        const resetRow = new Adw.ActionRow({
            title: _('恢复默认手势'),
            subtitle: _('当前配置会先保存在 gestures-v1.json.bak'),
        });
        const resetButton = new Gtk.Button({label: _('恢复默认值'), valign: Gtk.Align.CENTER, css_classes: ['destructive-action']});
        resetButton.connect('clicked', () => this._confirmReset());
        resetRow.add_suffix(resetButton);
        resetGroup.add(resetRow);
    }

    _chooseLegacyFile() {
        const chooser = new Gtk.FileDialog({title: _('选择 WGestures .wg2 配置')});
        const filter = new Gtk.FileFilter();
        filter.name = 'WGestures (*.wg2)';
        filter.add_pattern('*.wg2');
        const filters = new Gio.ListStore({item_type: Gtk.FileFilter});
        filters.append(filter);
        chooser.filters = filters;
        chooser.open(this._window, null, (source, result) => {
            try {
                const file = source.open_finish(result);
                const [ok, contents] = file.load_contents(null);
                if (!ok)
                    throw new Error(_('无法读取文件'));
                const imported = importLegacyConfig(new TextDecoder('utf-8').decode(contents));
                this._showImportPreview(imported);
            } catch (error) {
                const dismissed = error.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED) ||
                    String(error.message || '').toLocaleLowerCase().includes('dismiss');
                if (!dismissed)
                    this._toast(`${_('导入失败')}：${error.message}`);
            }
        });
    }

    _showImportPreview(imported) {
        const dialog = new Gtk.Dialog({
            title: _('选择要导入的手势'),
            transient_for: this._window,
            modal: true,
            use_header_bar: 1,
            default_width: 620,
            default_height: 620,
        });
        dialog.add_button(_('取消'), Gtk.ResponseType.CANCEL);
        dialog.add_button(_('导入选中项'), Gtk.ResponseType.ACCEPT);
        const scroll = new Gtk.ScrolledWindow({vexpand: true, hscrollbar_policy: Gtk.PolicyType.NEVER});
        const list = new Gtk.ListBox({selection_mode: Gtk.SelectionMode.NONE, css_classes: ['boxed-list']});
        scroll.child = list;
        dialog.get_content_area().append(label(
            `${_('可转换')}：${imported.report.imported}，${_('不兼容')}：${imported.report.unsupported.length}`
        ));
        dialog.get_content_area().append(scroll);
        const selections = [];
        for (const profile of [imported.config.globalProfile, ...imported.config.profiles]) {
            for (const gesture of profile.gestures) {
                const action = imported.config.actions.find(item => item.id === gesture.actionId);
                const check = new Gtk.CheckButton({active: true, valign: Gtk.Align.CENTER});
                const row = new Adw.ActionRow({
                    title: gesture.name,
                    subtitle: `${profile.name} · ${BUTTON_LABELS[gesture.button]} · ${gesture.directions.join(' → ')} · ${ACTION_LABELS[action?.type]}`,
                });
                row.add_prefix(check);
                list.append(row);
                selections.push({check, profile, gesture, action});
            }
        }
        if (imported.report.unsupported.length > 0) {
            const warning = new Adw.ActionRow({
                title: _('未导入项目'),
                subtitle: imported.report.unsupported.slice(0, 8).join('\n'),
            });
            list.append(warning);
        }
        dialog.connect('response', (_dialog, response) => {
            if (response === Gtk.ResponseType.ACCEPT)
                this._mergeImportedSelections(selections.filter(item => item.check.active));
            dialog.destroy();
        });
        dialog.present();
    }

    _mergeImportedSelections(selections) {
        let importedCount = 0;
        let conflictCount = 0;
        const importedProfiles = new Map();
        for (const selection of selections) {
            let targetProfile;
            if (selection.profile.id === 'global') {
                targetProfile = this._config.globalProfile;
            } else if (importedProfiles.has(selection.profile.id)) {
                targetProfile = importedProfiles.get(selection.profile.id);
            } else {
                targetProfile = {
                    id: `profile-${GLib.uuid_string_random()}`,
                    name: selection.profile.name,
                    enabled: selection.profile.enabled,
                    inheritGlobal: selection.profile.inheritGlobal,
                    matchers: [],
                    legacyExecutablePath: selection.profile.legacyExecutablePath || '',
                    gestures: [],
                };
                this._config.profiles.push(targetProfile);
                importedProfiles.set(selection.profile.id, targetProfile);
            }

            if (targetProfile.gestures.some(item => profileGestureKey(item) === profileGestureKey(selection.gesture))) {
                conflictCount += 1;
                continue;
            }
            const action = {...selection.action, id: `action-${GLib.uuid_string_random()}`};
            const gesture = {
                ...selection.gesture,
                id: `gesture-${GLib.uuid_string_random()}`,
                actionId: action.id,
            };
            this._config.actions.push(action);
            targetProfile.gestures.push(gesture);
            importedCount += 1;
        }
        this._save();
        this._refreshApplications();
        this._refreshProfileSelector();
        this._refreshGestures();
        this._toast(`${_('已导入')} ${importedCount}，${_('跳过冲突')} ${conflictCount}`);
    }

    _confirmReset() {
        const dialog = new Adw.MessageDialog({
            transient_for: this._window,
            heading: _('恢复默认手势？'),
            body: _('当前配置会被备份，然后替换为 Ubuntu 默认手势。'),
        });
        dialog.add_response('cancel', _('取消'));
        dialog.add_response('reset', _('恢复'));
        dialog.set_response_appearance('reset', Adw.ResponseAppearance.DESTRUCTIVE);
        dialog.connect('response', (_dialog, response) => {
            if (response === 'reset') {
                this._config = createDefaultConfig();
                this._save();
                this._refreshApplications();
                this._refreshProfileSelector();
                this._refreshGestures();
                this._toast(_('已恢复默认手势'));
            }
        });
        dialog.present();
    }

    _save() {
        this._config = this._store.save(this._config);
        const revision = this._settings.get_uint('config-revision');
        this._settings.set_uint('config-revision', (revision + 1) >>> 0);
    }

    _removeUnusedActions() {
        const used = new Set(
            [this._config.globalProfile, ...this._config.profiles]
                .flatMap(profile => profile.gestures.map(gesture => gesture.actionId))
        );
        this._config.actions = this._config.actions.filter(action => used.has(action.id));
    }

    _toast(message) {
        this._window.add_toast(new Adw.Toast({title: String(message), timeout: 5}));
    }
}

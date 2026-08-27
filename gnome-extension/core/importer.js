import {createDefaultConfig, normalizeConfig} from './config.js';

const LEGACY_DIRECTIONS = Object.freeze([
    'up', 'up-right', 'right', 'down-right', 'down', 'down-left', 'left', 'up-left',
]);
const LEGACY_BUTTONS = Object.freeze({1: 'right', 2: 'middle', 4: 'x1', 8: 'x2'});
const MODIFIER_CODES = Object.freeze({
    16: '<Shift>', 160: '<Shift>', 161: '<Shift>',
    17: '<Control>', 162: '<Control>', 163: '<Control>',
    18: '<Alt>', 164: '<Alt>', 165: '<Alt>',
    91: '<Super>', 92: '<Super>',
});
const SPECIAL_KEYS = Object.freeze({
    8: 'BackSpace', 9: 'Tab', 13: 'Return', 27: 'Escape', 32: 'space',
    33: 'Page_Up', 34: 'Page_Down', 35: 'End', 36: 'Home',
    37: 'Left', 38: 'Up', 39: 'Right', 40: 'Down', 45: 'Insert', 46: 'Delete',
    173: 'AudioMute', 174: 'AudioLowerVolume', 175: 'AudioRaiseVolume',
});

function typeName(command) {
    return String(command?.$type || '').split(',')[0].split('.').at(-1);
}

function legacyKeyName(code) {
    const numeric = Number(code);
    if (SPECIAL_KEYS[numeric])
        return SPECIAL_KEYS[numeric];
    if (numeric >= 48 && numeric <= 57)
        return String.fromCharCode(numeric);
    if (numeric >= 65 && numeric <= 90)
        return String.fromCharCode(numeric).toLocaleLowerCase();
    if (numeric >= 112 && numeric <= 123)
        return `F${numeric - 111}`;
    return null;
}

function makeId(prefix, state) {
    state.nextId += 1;
    return `${prefix}-${state.nextId}`;
}

function convertAction(command, name, state, report) {
    const commandType = typeName(command);
    const id = makeId('imported-action', state);
    const base = {id, name: name || commandType || '导入动作', enabled: true};

    switch (commandType) {
    case 'HotKeyCommand': {
        const modifiers = Array.isArray(command.Modifiers)
            ? [...new Set(command.Modifiers.map(code => MODIFIER_CODES[Number(code)]).filter(Boolean))]
            : [];
        const keys = Array.isArray(command.Keys)
            ? command.Keys.map(legacyKeyName).filter(Boolean)
            : [];
        if (keys.length !== 1) {
            report.unsupported.push(`${name}: 快捷键包含 ${keys.length} 个可识别主键`);
            return null;
        }
        return {...base, type: 'ShortcutAction', accelerator: `${modifiers.join('')}${keys[0]}`};
    }
    case 'WindowControlCommand': {
        const operations = {
            0: 'toggle-maximized', 1: 'minimize', 2: 'close', 3: 'toggle-above',
        };
        const operation = operations[Number(command.ChangeWindowStateTo)];
        if (!operation) {
            report.unsupported.push(`${name}: 不支持的窗口停靠动作`);
            return null;
        }
        return {...base, type: 'WindowAction', operation};
    }
    case 'GotoUrlCommand':
        return {...base, type: 'LaunchAction', target: String(command.Url || '')};
    case 'OpenFileCommand': {
        const target = String(command.FilePath || '');
        if (/^[a-zA-Z]:\\/.test(target) || target.startsWith('\\\\')) {
            report.unsupported.push(`${name}: Windows 文件路径需要手工替换`);
            return null;
        }
        return {...base, type: 'LaunchAction', target};
    }
    case 'PauseWGesturesCommand':
        return {...base, type: 'PauseAction'};
    case 'DoNothingCommand':
        return {...base, type: 'NoopAction'};
    case 'ChangeAudioVolumeCommand':
        return {...base, type: 'ShortcutAction', accelerator: 'AudioMute'};
    case 'CmdCommand':
        report.unsupported.push(`${name}: Windows 命令行不会自动启用`);
        return null;
    case 'ScriptCommand':
    case 'WebSearchCommand':
    case 'TaskSwitcherCommand':
    case 'SendTextCommand':
        report.unsupported.push(`${name}: ${commandType} 不在首版支持范围`);
        return null;
    default:
        report.unsupported.push(`${name}: 未知动作 ${commandType || '(空)'}`);
        return null;
    }
}

function convertIntent(intent, profile, config, state, report) {
    const legacyGesture = intent?.Gesture;
    const name = String(intent?.Name || '导入手势');
    if (!legacyGesture || Number(legacyGesture.Modifier || 0) !== 0) {
        report.unsupported.push(`${name}: 修饰手势不受支持`);
        return;
    }

    const button = LEGACY_BUTTONS[Number(legacyGesture.GestureButton)];
    const directions = Array.isArray(legacyGesture.Dirs)
        ? legacyGesture.Dirs.map(value => LEGACY_DIRECTIONS[Number(value)]).filter(Boolean)
        : [];
    if (!button || directions.length === 0) {
        report.unsupported.push(`${name}: 触发按钮或方向无效`);
        return;
    }

    const convertedAction = convertAction(intent.Command, name, state, report);
    if (!convertedAction)
        return;

    config.actions.push(convertedAction);
    profile.gestures.push({
        id: makeId('imported-gesture', state),
        name,
        enabled: true,
        button,
        directions,
        actionId: convertedAction.id,
    });
    report.imported += 1;
}

export function importLegacyConfig(text) {
    let legacy;
    try {
        legacy = JSON.parse(text);
    } catch (error) {
        throw new Error(`旧配置不是有效 JSON：${error.message}`);
    }
    if (!legacy || typeof legacy !== 'object' || !legacy.Global)
        throw new Error('旧配置缺少 Global 手势数据');

    const config = createDefaultConfig();
    config.actions = [];
    config.globalProfile.gestures = [];
    const state = {nextId: 0};
    const report = {imported: 0, unsupported: [], unboundProfiles: []};

    const globalIntents = Array.isArray(legacy.Global.GestureIntents)
        ? legacy.Global.GestureIntents
        : [];
    for (const intent of globalIntents)
        convertIntent(intent, config.globalProfile, config, state, report);

    const legacyApps = legacy.Apps && typeof legacy.Apps === 'object'
        ? Object.values(legacy.Apps)
        : [];
    for (const legacyApp of legacyApps) {
        const profile = {
            id: makeId('unbound-profile', state),
            name: String(legacyApp.Name || legacyApp.ExecutablePath || '未绑定应用'),
            enabled: legacyApp.IsGesturingEnabled !== false,
            inheritGlobal: legacyApp.InheritGlobalGestures !== false,
            matchers: [],
            legacyExecutablePath: String(legacyApp.ExecutablePath || ''),
            gestures: [],
        };
        const intents = Array.isArray(legacyApp.GestureIntents) ? legacyApp.GestureIntents : [];
        for (const intent of intents)
            convertIntent(intent, profile, config, state, report);
        if (profile.gestures.length > 0) {
            config.profiles.push(profile);
            report.unboundProfiles.push({id: profile.id, name: profile.name, path: profile.legacyExecutablePath});
        }
    }

    const normalized = normalizeConfig(config);
    return {config: normalized.config, report: {...report, warnings: normalized.warnings}};
}

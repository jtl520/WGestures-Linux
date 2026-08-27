import {BUTTONS, DIRECTIONS, gestureKey} from './gesture.js';

export const SCHEMA_VERSION = 1;
export const ACTION_TYPES = Object.freeze([
    'ShortcutAction',
    'WindowAction',
    'CommandAction',
    'LaunchAction',
    'PauseAction',
    'NoopAction',
]);

const WINDOW_OPERATIONS = Object.freeze([
    'toggle-maximized',
    'minimize',
    'close',
    'toggle-fullscreen',
    'toggle-above',
]);

function clone(value) {
    return JSON.parse(JSON.stringify(value));
}

function action(id, name, type, extra = {}) {
    return {id, name, type, enabled: true, ...extra};
}

function gesture(id, name, button, directions, actionId) {
    return {id, name, enabled: true, button, directions, actionId};
}

export function createDefaultConfig() {
    return {
        schemaVersion: SCHEMA_VERSION,
        actions: [
            action('shortcut-back', '后退', 'ShortcutAction', {accelerator: '<Alt>Left'}),
            action('shortcut-forward', '前进', 'ShortcutAction', {accelerator: '<Alt>Right'}),
            action('shortcut-close', '关闭标签页', 'ShortcutAction', {accelerator: '<Control>w'}),
            action('window-maximize', '最大化/恢复', 'WindowAction', {operation: 'toggle-maximized'}),
            action('window-minimize', '最小化', 'WindowAction', {operation: 'minimize'}),
        ],
        globalProfile: {
            id: 'global',
            name: '全局',
            enabled: true,
            inheritGlobal: false,
            matchers: [],
            gestures: [
                gesture('gesture-left', '后退', 'right', ['left'], 'shortcut-back'),
                gesture('gesture-right', '前进', 'right', ['right'], 'shortcut-forward'),
                gesture('gesture-down-right', '关闭标签页', 'right', ['down', 'right'], 'shortcut-close'),
                gesture('gesture-up', '最大化/恢复', 'right', ['up'], 'window-maximize'),
                gesture('gesture-down', '最小化', 'right', ['down'], 'window-minimize'),
            ],
        },
        profiles: [],
    };
}

function normalizeAction(raw, seenIds, warnings) {
    if (!raw || typeof raw !== 'object' || !ACTION_TYPES.includes(raw.type)) {
        warnings.push('已忽略未知动作类型');
        return null;
    }

    const id = String(raw.id || '').trim();
    if (!id || seenIds.has(id)) {
        warnings.push(`已忽略无 ID 或重复的动作：${id || '(空)'}`);
        return null;
    }

    const normalized = {
        id,
        name: String(raw.name || id),
        type: raw.type,
        enabled: raw.enabled !== false,
    };

    switch (raw.type) {
    case 'ShortcutAction':
        normalized.accelerator = String(raw.accelerator || '').trim();
        if (!normalized.accelerator)
            warnings.push(`快捷键动作 ${id} 没有快捷键`);
        break;
    case 'WindowAction':
        normalized.operation = WINDOW_OPERATIONS.includes(raw.operation)
            ? raw.operation
            : 'toggle-maximized';
        break;
    case 'CommandAction':
        normalized.command = String(raw.command || '');
        break;
    case 'LaunchAction':
        normalized.target = String(raw.target || '');
        break;
    default:
        break;
    }

    seenIds.add(id);
    return normalized;
}

function normalizeGesture(raw, actionIds, seenKeys, warnings) {
    if (!raw || typeof raw !== 'object')
        return null;

    const button = BUTTONS.includes(raw.button) ? raw.button : null;
    const directions = Array.isArray(raw.directions)
        ? raw.directions.filter(direction => DIRECTIONS.includes(direction))
        : [];
    const actionId = String(raw.actionId || '');
    if (!button || directions.length === 0 || !actionIds.has(actionId)) {
        warnings.push(`已忽略无效手势：${raw.name || raw.id || '(未命名)'}`);
        return null;
    }

    const key = gestureKey(button, directions);
    if (seenKeys.has(key)) {
        warnings.push(`已忽略冲突手势：${key}`);
        return null;
    }
    seenKeys.add(key);

    return {
        id: String(raw.id || `gesture-${seenKeys.size}`),
        name: String(raw.name || key),
        enabled: raw.enabled !== false,
        button,
        directions,
        actionId,
    };
}

function normalizeProfile(raw, actionIds, fallbackId, warnings) {
    const seenKeys = new Set();
    const matchers = Array.isArray(raw?.matchers)
        ? raw.matchers
            .filter(matcher => matcher && typeof matcher.type === 'string' && typeof matcher.value === 'string')
            .map(matcher => ({type: matcher.type, value: matcher.value}))
        : [];

    const normalized = {
        id: String(raw?.id || fallbackId),
        name: String(raw?.name || fallbackId),
        enabled: raw?.enabled !== false,
        inheritGlobal: raw?.inheritGlobal !== false,
        matchers,
        gestures: Array.isArray(raw?.gestures)
            ? raw.gestures
                .map(item => normalizeGesture(item, actionIds, seenKeys, warnings))
                .filter(Boolean)
            : [],
    };
    if (raw?.legacyExecutablePath)
        normalized.legacyExecutablePath = String(raw.legacyExecutablePath);
    return normalized;
}

export function normalizeConfig(raw) {
    const warnings = [];
    const source = raw && typeof raw === 'object' ? raw : createDefaultConfig();
    if (source.schemaVersion !== SCHEMA_VERSION)
        throw new Error(`Unsupported configuration schema: ${source.schemaVersion}`);

    const seenActionIds = new Set();
    const actions = Array.isArray(source.actions)
        ? source.actions
            .map(item => normalizeAction(item, seenActionIds, warnings))
            .filter(Boolean)
        : [];

    const globalProfile = normalizeProfile(
        {...source.globalProfile, id: 'global', inheritGlobal: false},
        seenActionIds,
        'global',
        warnings
    );
    const seenProfileIds = new Set(['global']);
    const profiles = [];
    for (const item of Array.isArray(source.profiles) ? source.profiles : []) {
        const profile = normalizeProfile(item, seenActionIds, `profile-${profiles.length + 1}`, warnings);
        if (seenProfileIds.has(profile.id)) {
            warnings.push(`已忽略重复应用配置：${profile.id}`);
            continue;
        }
        seenProfileIds.add(profile.id);
        profiles.push(profile);
    }

    return {config: {schemaVersion: SCHEMA_VERSION, actions, globalProfile, profiles}, warnings};
}

export function findMatchingProfile(config, identity = {}) {
    const orderedIdentity = [
        ['sandboxedAppId', identity.sandboxedAppId],
        ['desktopId', identity.desktopId],
        ['gtkApplicationId', identity.gtkApplicationId],
        ['wmClass', identity.wmClass],
    ];

    for (const [type, value] of orderedIdentity) {
        if (!value)
            continue;
        const lowered = String(value).toLocaleLowerCase();
        const found = config.profiles.find(profile => profile.matchers.some(matcher =>
            matcher.type === type && matcher.value.toLocaleLowerCase() === lowered
        ));
        if (found)
            return found;
    }
    return null;
}

export function resolveGesture(config, identity, button, directions) {
    const key = gestureKey(button, directions);
    const profile = findMatchingProfile(config, identity);
    const candidates = [];

    if (profile) {
        if (!profile.enabled)
            return null;
        candidates.push(profile);
        if (profile.inheritGlobal)
            candidates.push(config.globalProfile);
    } else {
        candidates.push(config.globalProfile);
    }

    const actions = new Map(config.actions.map(item => [item.id, item]));
    for (const candidate of candidates) {
        if (!candidate.enabled)
            continue;
        const matched = candidate.gestures.find(item =>
            item.enabled && gestureKey(item.button, item.directions) === key
        );
        if (!matched)
            continue;
        const matchedAction = actions.get(matched.actionId);
        if (matchedAction?.enabled)
            return {gesture: matched, action: matchedAction, profile: candidate};
    }

    return null;
}

export function cloneConfig(config) {
    return clone(config);
}

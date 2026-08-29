import {
    BUTTONS, DIRECTIONS, directionErrorDegrees, gestureKey, simplifyCornerTransitions,
} from './gesture.js';
import {normalizeAccelerator} from './shortcut.js';

export const SCHEMA_VERSION = 1;
export const ACTION_TYPES = Object.freeze([
    'ShortcutAction',
    'CopyAction',
    'PasteAction',
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
const SINGLE_DIRECTION_TOLERANCE = 35;

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
            action('smart-copy', '复制', 'CopyAction'),
            action('smart-paste', '粘贴', 'PasteAction'),
            action('press-enter', 'Enter', 'ShortcutAction', {
                accelerator: 'Return',
            }),
            action('window-toggle-above', '窗口置顶', 'WindowAction', {
                operation: 'toggle-above',
            }),
        ],
        globalProfile: {
            id: 'global',
            name: '全局',
            enabled: true,
            inheritGlobal: false,
            matchers: [],
            gestures: [
                gesture('gesture-copy', '复制', 'right', ['up'], 'smart-copy'),
                gesture('gesture-paste', '粘贴', 'right', ['down'], 'smart-paste'),
                gesture('gesture-enter', 'Enter', 'right',
                    ['down', 'right', 'down'], 'press-enter'),
                gesture('gesture-toggle-above', '窗口置顶', 'right',
                    ['up', 'right', 'up'], 'window-toggle-above'),
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

    let actionType = raw.type;
    if (actionType === 'ShortcutAction') {
        const accelerator = String(raw.accelerator || '').trim();
        let normalizedAccelerator = accelerator;
        try {
            normalizedAccelerator = normalizeAccelerator(accelerator);
        } catch (_error) {
            // Preserve invalid custom shortcuts so the existing warning path handles them.
        }
        if (id === 'smart-copy' && normalizedAccelerator === '<Control>c')
            actionType = 'CopyAction';
        else if (id === 'smart-paste' && normalizedAccelerator === '<Control>v')
            actionType = 'PasteAction';
    }

    const normalized = {
        id,
        name: String(raw.name || id),
        type: actionType,
        enabled: raw.enabled !== false,
    };

    switch (actionType) {
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

export function resolveGesture(config, identity, button, directions, movement = null) {
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

    const simplifiedDirections = simplifyCornerTransitions(directions);
    if (gestureKey(button, simplifiedDirections) !== key) {
        const simplifiedKey = gestureKey(button, simplifiedDirections);
        for (const candidate of candidates) {
            if (!candidate.enabled)
                continue;
            const matched = candidate.gestures.find(item =>
                item.enabled && gestureKey(item.button, item.directions) === simplifiedKey
            );
            const matchedAction = matched ? actions.get(matched.actionId) : null;
            if (matchedAction?.enabled)
                return {gesture: matched, action: matchedAction, profile: candidate};
        }
    }

    const origin = movement?.origin;
    const end = movement?.end;
    if (!origin || !end)
        return null;
    const dx = end.x - origin.x;
    const dy = end.y - origin.y;
    for (const candidate of candidates) {
        if (!candidate.enabled)
            continue;
        let best = null;
        for (const gesture of candidate.gestures) {
            if (!gesture.enabled || gesture.button !== button || gesture.directions.length !== 1)
                continue;
            const error = directionErrorDegrees(gesture.directions[0], dx, dy);
            const action = actions.get(gesture.actionId);
            if (error !== null && error <= SINGLE_DIRECTION_TOLERANCE && action?.enabled &&
                (!best || error < best.error))
                best = {error, gesture, action};
        }
        if (best)
            return {gesture: best.gesture, action: best.action, profile: candidate};
    }

    return null;
}

export function cloneConfig(config) {
    return clone(config);
}

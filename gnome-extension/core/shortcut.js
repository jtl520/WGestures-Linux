const MODIFIER_ALIASES = Object.freeze({
    control: 'Control',
    ctrl: 'Control',
    primary: 'Control',
    alt: 'Alt',
    shift: 'Shift',
    super: 'Super',
    win: 'Super',
    windows: 'Super',
    meta: 'Super',
});

const MODIFIER_LABELS = Object.freeze({
    Control: 'Ctrl',
    Alt: 'Alt',
    Shift: 'Shift',
    Super: 'Super',
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
    pageup: 'Page_Up',
    pagedown: 'Page_Down',
    audiomute: 'AudioMute',
    audiolowervolume: 'AudioLowerVolume',
    audioraisevolume: 'AudioRaiseVolume',
});

const KEY_LABELS = Object.freeze({
    return: 'Enter',
    escape: 'Esc',
    space: 'Space',
    backspace: 'Backspace',
    page_up: 'PageUp',
    page_down: 'PageDown',
});

const TERMINAL_TOKENS = new Set([
    'terminal', 'console', 'ptyxis', 'konsole', 'xterm', 'urxvt',
    'tilix', 'terminator', 'alacritty', 'kitty', 'wezterm', 'foot',
    'ghostty', 'guake', 'yakuake', 'qterminal', 'lxterminal',
]);

function modifier(value) {
    const result = MODIFIER_ALIASES[value.trim().toLocaleLowerCase()];
    if (!result)
        throw new Error(`不支持的修饰键：${value}`);
    return result;
}

function keyName(value) {
    const key = value.trim();
    if (!key)
        throw new Error('快捷键缺少主键');
    if (key.includes('<') || key.includes('>'))
        throw new Error(`快捷键格式无效：${value}`);
    const compact = key.replace(/[\s_-]+/g, '').toLocaleLowerCase();
    if (KEY_ALIASES[compact])
        return KEY_ALIASES[compact];
    if (/^[a-z]$/i.test(key))
        return key.toLocaleLowerCase();
    if (/^f\d{1,2}$/i.test(key))
        return key.toLocaleUpperCase();
    return key;
}

function parts(accelerator) {
    const text = String(accelerator || '').trim();
    if (!text)
        throw new Error('快捷键不能为空');

    const modifiers = [];
    let key;
    if (text.includes('<') || text.includes('>')) {
        let remaining = text;
        while (remaining.startsWith('<')) {
            const match = remaining.match(/^<([^<>]+)>/);
            if (!match)
                throw new Error(`快捷键格式无效：${text}`);
            modifiers.push(modifier(match[1]));
            remaining = remaining.slice(match[0].length).trimStart();
        }
        if (remaining.includes('<') || remaining.includes('>'))
            throw new Error(`快捷键格式无效：${text}`);
        key = remaining;
    } else {
        const values = text.includes('+')
            ? text.split('+').map(item => item.trim())
            : text.split(/\s+/);
        if (values.length === 0 || values.some(item => !item))
            throw new Error(`快捷键格式无效：${text}`);
        modifiers.push(...values.slice(0, -1).map(modifier));
        key = values[values.length - 1];
    }

    return {
        modifiers: [...new Set(modifiers)],
        key: keyName(key),
    };
}

export function normalizeAccelerator(accelerator) {
    const parsed = parts(accelerator);
    return parsed.modifiers.map(item => `<${item}>`).join('') + parsed.key;
}

export function displayAccelerator(accelerator) {
    const parsed = parts(accelerator);
    const key = /^[a-z]$/i.test(parsed.key)
        ? parsed.key.toLocaleUpperCase()
        : (KEY_LABELS[parsed.key.toLocaleLowerCase()] || parsed.key);
    return [...parsed.modifiers.map(item => MODIFIER_LABELS[item]), key].join('+');
}

export function isTerminalIdentity(identity = {}) {
    for (const field of ['sandboxedAppId', 'desktopId', 'gtkApplicationId', 'wmClass']) {
        const tokens = String(identity?.[field] || '')
            .toLocaleLowerCase()
            .split(/[^a-z0-9]+/)
            .filter(Boolean);
        if (tokens.some(token => TERMINAL_TOKENS.has(token)))
            return true;
    }
    return false;
}

export function copyAccelerator(identity = {}) {
    return isTerminalIdentity(identity) ? '<Control><Shift>c' : '<Control>c';
}

export function pasteAccelerator(identity = {}) {
    return isTerminalIdentity(identity) ? '<Control><Shift>v' : '<Control>v';
}

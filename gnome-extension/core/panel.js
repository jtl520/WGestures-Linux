export const PANEL_SCHEMA_VERSION = 1;
export const PANEL_SLOT_COUNT = 16;
export const PANEL_ITEM_TYPES = Object.freeze(['application', 'file', 'folder', 'url']);

export function createDefaultPanel() {
    return {schemaVersion: PANEL_SCHEMA_VERSION, slots: Array(PANEL_SLOT_COUNT).fill(null)};
}

export function validPanelTarget(type, target) {
    const value = String(target || '').trim();
    if (!value)
        return false;
    if (type === 'application')
        return !value.includes('\\');
    if (type === 'file' || type === 'folder')
        return value.startsWith('/');
    if (type === 'url')
        return /^https?:\/\/[^\s/?#]+(?:[/?#]|$)/i.test(value);
    return false;
}

export function defaultPanelLabel(type, target) {
    const value = String(target || '').trim();
    if (type === 'url') {
        const match = value.match(/^https?:\/\/([^/?#]+)/i);
        return match?.[1] || value;
    }
    if (type === 'application') {
        if (value.includes('/'))
            return value.replace(/\/+$/, '').split('/').at(-1) || value;
        const withoutSuffix = value.endsWith('.desktop') ? value.slice(0, -8) : value;
        return withoutSuffix.split('.').at(-1) || value;
    }
    return value.replace(/\/+$/, '').split('/').at(-1) || value;
}

// /proc comm holds at most 15 visible characters, so a long executable
// name can only match its truncated prefix.
export function matchesExecutableName(executable, commValue) {
    const name = String(executable || '').trim().split('/').pop();
    if (!name)
        return false;
    return String(commValue || '').trim() === name.slice(0, 15);
}

export function normalizePanel(raw) {
    if (!raw || typeof raw !== 'object' || raw.schemaVersion !== PANEL_SCHEMA_VERSION)
        throw new Error(`Unsupported panel configuration schema: ${raw?.schemaVersion}`);
    if (!Array.isArray(raw.slots))
        throw new Error('Panel slots must be an array');
    const warnings = [];
    const seenIds = new Set();
    const slots = Array.from({length: PANEL_SLOT_COUNT}, (_unused, index) => {
        const item = raw.slots[index];
        if (item === null || item === undefined)
            return null;
        if (typeof item !== 'object' || !PANEL_ITEM_TYPES.includes(item.type) ||
            !validPanelTarget(item.type, item.target)) {
            warnings.push(`已忽略第 ${index + 1} 个无效面板格子`);
            return null;
        }
        let id = String(item.id || `slot-${index + 1}`).trim();
        if (!id || seenIds.has(id))
            id = `slot-${index + 1}`;
        seenIds.add(id);
        const target = String(item.target).trim();
        const normalized = {
            id,
            label: String(item.label || '').trim() || defaultPanelLabel(item.type, target),
            type: item.type,
            target,
        };
        for (const key of ['description', 'arguments', 'workingDirectory', 'browser']) {
            const value = String(item[key] || '').trim();
            if (value)
                normalized[key] = value;
        }
        if (normalized.workingDirectory && !normalized.workingDirectory.startsWith('/'))
            delete normalized.workingDirectory;
        if (normalized.browser && normalized.browser.includes('/') &&
            !normalized.browser.startsWith('/'))
            delete normalized.browser;
        if (item.runAsAdministrator)
            normalized.runAsAdministrator = true;
        if (item.activateIfRunning)
            normalized.activateIfRunning = true;
        return normalized;
    });
    if (raw.slots.length !== PANEL_SLOT_COUNT)
        warnings.push('面板格子数量已调整为 16 个');
    return {config: {schemaVersion: PANEL_SCHEMA_VERSION, slots}, warnings};
}

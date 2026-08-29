import {normalizeConfig} from './config.js';
import {importLegacyConfig} from './importer.js';

export const PORTABLE_FORMAT = 'crossgestures-portable';
export const PORTABLE_VERSION = 1;

export function exportPortableConfig(config) {
    const normalized = normalizeConfig(config);
    return `${JSON.stringify({
        ...normalized.config,
        portableFormat: PORTABLE_FORMAT,
        schemaVersion: PORTABLE_VERSION,
    }, null, 2)}\n`;
}

export function importConfig(text) {
    let document;
    try {
        document = JSON.parse(text);
    } catch (error) {
        throw new Error(`配置不是有效 JSON：${error.message}`);
    }
    if (!document || typeof document !== 'object' || document.portableFormat !== PORTABLE_FORMAT)
        return importLegacyConfig(text);
    if (document.schemaVersion !== PORTABLE_VERSION)
        throw new Error(`不支持的 CrossGestures 跨平台配置版本：${document.schemaVersion}`);
    const normalized = normalizeConfig(document);
    const config = normalized.config;
    const profiles = [config.globalProfile, ...config.profiles];
    return {
        config,
        report: {
            imported: profiles.reduce((count, profile) => count + profile.gestures.length, 0),
            unsupported: [...normalized.warnings],
            unboundProfiles: config.profiles
                .filter(profile => profile.legacyExecutablePath && profile.matchers.length === 0)
                .map(profile => ({
                    id: profile.id,
                    name: profile.name,
                    path: profile.legacyExecutablePath,
                })),
            portable: true,
        },
    };
}

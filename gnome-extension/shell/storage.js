import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {createDefaultConfig, normalizeConfig} from '../core/config.js';
import {createDefaultPanel, normalizePanel} from '../core/panel.js';

const decoder = new TextDecoder('utf-8');
const encoder = new TextEncoder();

export function getConfigDirectory() {
    return GLib.build_filenamev([GLib.get_user_config_dir(), 'wgestures']);
}

export function getConfigPath() {
    return GLib.build_filenamev([getConfigDirectory(), 'gestures-v1.json']);
}

export function getPanelConfigPath() {
    return GLib.build_filenamev([getConfigDirectory(), 'panel-v1.json']);
}

function readUtf8(path) {
    const [ok, contents] = GLib.file_get_contents(path);
    if (!ok)
        throw new Error(`Unable to read ${path}`);
    return decoder.decode(contents);
}

function writeUtf8(path, text) {
    if (!GLib.file_set_contents(path, encoder.encode(text)))
        throw new Error(`Unable to write ${path}`);
}

export class ConfigStore {
    constructor() {
        this.path = getConfigPath();
        this.directory = getConfigDirectory();
    }

    load() {
        GLib.mkdir_with_parents(this.directory, 0o700);
        if (!GLib.file_test(this.path, GLib.FileTest.EXISTS)) {
            const defaults = createDefaultConfig();
            this.save(defaults);
            return {config: defaults, warnings: []};
        }

        try {
            return normalizeConfig(JSON.parse(readUtf8(this.path)));
        } catch (error) {
            const backupPath = `${this.path}.bak`;
            if (GLib.file_test(backupPath, GLib.FileTest.EXISTS)) {
                try {
                    const recovered = normalizeConfig(JSON.parse(readUtf8(backupPath)));
                    recovered.warnings.unshift(`主配置损坏，已从备份恢复：${error.message}`);
                    this.save(recovered.config, false);
                    return recovered;
                } catch (backupError) {
                    logError(backupError, 'CrossGestures backup configuration is invalid');
                }
            }

            const defaults = createDefaultConfig();
            this.save(defaults, false);
            return {config: defaults, warnings: [`配置损坏，已恢复默认值：${error.message}`]};
        }
    }

    save(config, createBackup = true) {
        const normalized = normalizeConfig(config).config;
        GLib.mkdir_with_parents(this.directory, 0o700);

        const tempPath = `${this.path}.tmp`;
        const backupPath = `${this.path}.bak`;
        const backupTempPath = `${backupPath}.tmp`;
        writeUtf8(tempPath, `${JSON.stringify(normalized, null, 2)}\n`);

        const destination = Gio.File.new_for_path(this.path);
        if (createBackup && destination.query_exists(null)) {
            try {
                normalizeConfig(JSON.parse(readUtf8(this.path)));
                const backupTemp = Gio.File.new_for_path(backupTempPath);
                destination.copy(backupTemp, Gio.FileCopyFlags.OVERWRITE, null, null);
                backupTemp.move(
                    Gio.File.new_for_path(backupPath),
                    Gio.FileCopyFlags.OVERWRITE,
                    null,
                    null
                );
            } catch (error) {
                console.warn(`CrossGestures: 当前配置无效，保留上一次有效备份：${error.message}`);
            }
        }
        Gio.File.new_for_path(tempPath).move(
            destination,
            Gio.FileCopyFlags.OVERWRITE,
            null,
            null
        );
        return normalized;
    }
}

export class PanelStore {
    constructor(path = null) {
        this.path = path || getPanelConfigPath();
        this.directory = GLib.path_get_dirname(this.path);
    }

    load() {
        GLib.mkdir_with_parents(this.directory, 0o700);
        if (!GLib.file_test(this.path, GLib.FileTest.EXISTS)) {
            const defaults = createDefaultPanel();
            this.save(defaults, false);
            return {config: defaults, warnings: [], source: 'defaults'};
        }
        try {
            return {...normalizePanel(JSON.parse(readUtf8(this.path))), source: 'primary'};
        } catch (error) {
            const backupPath = `${this.path}.bak`;
            if (GLib.file_test(backupPath, GLib.FileTest.EXISTS)) {
                try {
                    const recovered = normalizePanel(JSON.parse(readUtf8(backupPath)));
                    recovered.warnings.unshift(`面板主配置损坏，已从备份恢复：${error.message}`);
                    this.save(recovered.config, false);
                    return {...recovered, source: 'backup'};
                } catch (backupError) {
                    logError(backupError, 'CrossGestures panel backup is invalid');
                }
            }
            const defaults = createDefaultPanel();
            this.save(defaults, false);
            return {
                config: defaults,
                warnings: [`面板配置损坏，已恢复为空面板：${error.message}`],
                source: 'defaults-recovery',
            };
        }
    }

    save(config, createBackup = true) {
        const normalized = normalizePanel(config).config;
        GLib.mkdir_with_parents(this.directory, 0o700);
        const tempPath = `${this.path}.tmp`;
        const backupPath = `${this.path}.bak`;
        const backupTempPath = `${backupPath}.tmp`;
        writeUtf8(tempPath, `${JSON.stringify(normalized, null, 2)}\n`);
        const destination = Gio.File.new_for_path(this.path);
        if (createBackup && destination.query_exists(null)) {
            try {
                normalizePanel(JSON.parse(readUtf8(this.path)));
                destination.copy(
                    Gio.File.new_for_path(backupTempPath),
                    Gio.FileCopyFlags.OVERWRITE, null, null
                );
                Gio.File.new_for_path(backupTempPath).move(
                    Gio.File.new_for_path(backupPath),
                    Gio.FileCopyFlags.OVERWRITE, null, null
                );
            } catch (error) {
                console.warn(`CrossGestures: 当前面板配置无效，保留有效备份：${error.message}`);
            }
        }
        Gio.File.new_for_path(tempPath).move(
            destination, Gio.FileCopyFlags.OVERWRITE, null, null
        );
        return normalized;
    }
}

import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {
    GestureRecognizer, directionErrorDegrees, directionFromDelta, gestureKey,
    simplifyCornerTransitions,
} from '../core/gesture.js';
import {createDefaultConfig, findMatchingProfile, normalizeConfig, resolveGesture} from '../core/config.js';
import {importLegacyConfig} from '../core/importer.js';
import {exportPortableConfig, importConfig} from '../core/portable.js';
import {GestureSession, ReplayGuard} from '../core/input-state.js';
import {createDefaultPanel, matchesExecutableName, normalizePanel, validPanelTarget} from '../core/panel.js';
import {
    actionDisplayName, copyAccelerator, displayAccelerator, isTerminalIdentity,
    normalizeAccelerator, pasteAccelerator,
} from '../core/shortcut.js';

const tests = [];
function test(name, callback) {
    tests.push({name, callback});
}

const sharedFixtures = JSON.parse(readFileSync(
    new URL('../../tests/fixtures/core-conformance.json', import.meta.url),
    'utf8'
));

const shellPanelSource = readFileSync(
    new URL('../shell/panel.js', import.meta.url), 'utf8'
);

const extensionSource = readFileSync(
    new URL('../extension.js', import.meta.url), 'utf8'
);

test('JavaScript recognizer matches cross-backend conformance fixtures', () => {
    for (const item of sharedFixtures.directionCases) {
        assert.equal(directionFromDelta(item.dx, item.dy, item.mode), item.expected);
    }
    for (const item of sharedFixtures.directionToleranceCases) {
        const error = directionErrorDegrees(item.direction, item.dx, item.dy);
        assert.equal(error <= item.maximumError, item.matches);
    }
    for (const item of sharedFixtures.cornerSimplificationCases)
        assert.deepEqual(simplifyCornerTransitions(item.actual), item.expected);
    for (const item of sharedFixtures.recognizerCases) {
        const recognizer = new GestureRecognizer(item.options);
        recognizer.begin(...item.points[0]);
        for (const point of item.points.slice(1))
            recognizer.addPoint(...point);
        const result = recognizer.finish();
        assert.equal(result.effective, item.effective);
        assert.deepEqual(result.directions, item.directions);
    }
});

test('four-direction vectors are classified in screen coordinates', () => {
    assert.equal(directionFromDelta(10, 1, 4), 'right');
    assert.equal(directionFromDelta(0, -10, 4), 'up');
    assert.equal(directionFromDelta(-10, 0, 4), 'left');
    assert.equal(directionFromDelta(0, 10, 4), 'down');
});

test('eight-direction vectors include diagonals', () => {
    assert.equal(directionFromDelta(10, -10, 8), 'up-right');
    assert.equal(directionFromDelta(-10, 10, 8), 'down-left');
});

test('recognizer ignores jitter and compresses repeated directions', () => {
    const recognizer = new GestureRecognizer({directionMode: 8, startThreshold: 5, segmentThreshold: 5});
    recognizer.begin(0, 0);
    recognizer.addPoint(2, 1);
    assert.equal(recognizer.finish().effective, false);
    recognizer.addPoint(10, 0);
    recognizer.addPoint(20, 0);
    recognizer.addPoint(20, 10);
    assert.deepEqual(recognizer.finish().directions, ['right', 'down']);
});

test('gesture keys reject invalid input', () => {
    assert.equal(gestureKey('right', ['left', 'up']), 'right:left,up');
    assert.throws(() => gestureKey('left-button', ['left']));
});

test('quick panel keeps sixteen validated slots', () => {
    const panel = createDefaultPanel();
    assert.equal(panel.slots.length, 16);
    panel.slots[0] = {
        id: 'browser', label: '', type: 'url', target: 'https://example.com/path',
        browser: 'firefox.desktop', description: 'Example site',
    };
    panel.slots.push({id: 'bad', label: 'Bad', type: 'url', target: 'javascript:alert(1)'});
    const normalized = normalizePanel(panel);
    assert.equal(normalized.config.slots.length, 16);
    assert.equal(normalized.config.slots[0].label, 'example.com');
    assert.equal(normalized.config.slots[0].browser, 'firefox.desktop');
    assert.equal(normalized.config.slots[0].description, 'Example site');
    assert.ok(normalized.warnings.length > 0);
    assert.equal(validPanelTarget('url', 'https://example.com'), true);
    assert.equal(validPanelTarget('url', 'file:///tmp/test'), false);
    assert.equal(validPanelTarget('application', '/opt/jadx/bin/jadx-gui'), true);
    assert.equal(validPanelTarget('application', './studio.sh'), true);
    assert.equal(validPanelTarget('application', 'bad\\windows-path'), false);
});

test('GNOME panel resolves executable paths without a shell', () => {
    assert.match(shellPanelSource, /_resolveExecutable\(target, workingDirectory = null\)/);
    assert.match(shellPanelSource, /GLib\.find_program_in_path\(executable\)/);
    assert.match(shellPanelSource, /GLib\.FileTest\.IS_EXECUTABLE/);
    assert.match(shellPanelSource, /launcher\.set_cwd\(GLib\.path_get_dirname\(executable\)\)/);
    assert.doesNotMatch(shellPanelSource, /shell:\s*true/);
});

test('GNOME indicator exposes a fallback panel entry and responsive layout', () => {
    assert.match(extensionSource, /PopupMenuItem\(_\('弹出快捷面板'\)\)/);
    assert.match(extensionSource, /global\.get_pointer\(\)/);
    assert.match(shellPanelSource, /_applyMonitorLayout\(area\)/);
    assert.match(shellPanelSource, /Math\.min\(area\.width, area\.height\) \/ 900/);
    assert.match(shellPanelSource, /this\._layout\.tileWidth/);
});

test('GNOME panel exposes the four direct empty-slot actions', () => {
    const labelsBlock = shellPanelSource.match(
        /const PANEL_ACTION_LABELS = Object\.freeze\(\{([\s\S]*?)\}\);/
    );
    assert.ok(labelsBlock, 'panel action labels are missing');
    const entries = [...labelsBlock[1].matchAll(
        /(application|file|folder|url):\s*'([^']+)'/g
    )].map(match => [match[1], match[2]]);
    assert.deepEqual(Object.fromEntries(entries), {
        application: '启动软件',
        file: '打开文件',
        folder: '打开文件夹',
        url: '打开网址',
    });
    assert.match(shellPanelSource, /new PopupMenu\.PopupMenu\(button,/);
    assert.match(shellPanelSource, /menu\.addAction\(label,/);
    assert.match(shellPanelSource, /command\.push\('--panel-type', initialType\)/);
    assert.match(shellPanelSource, /menu\.addAction\('编辑'/);
    assert.match(shellPanelSource, /menu\.addAction\('删除'/);
});

test('GNOME folder items prefer a real file manager over an incorrect URI handler', () => {
    assert.match(shellPanelSource, /const FILE_MANAGER_DESKTOP_IDS/);
    assert.match(shellPanelSource, /org\.gnome\.Nautilus\.desktop/);
    assert.match(shellPanelSource, /Gio\.DesktopAppInfo\.new\(desktopId\)/);
    assert.match(shellPanelSource, /fileManager\.launch\(\[file\], context\)/);
});

test('GNOME panel reuses its tile tree and refreshes cached site icons', () => {
    assert.match(shellPanelSource, /if \(this\._dirty \|\| !this\._config\)\s*this\._reload\(\)/);
    assert.match(shellPanelSource, /GLib\.get_user_cache_dir\(\)/);
    assert.match(shellPanelSource, /'--panel-fetch-icon'/);
    assert.match(shellPanelSource, /new Gio\.FileIcon/);
    assert.doesNotMatch(shellPanelSource, /showAt\(x, y\) \{\s*this\._reload\(\)/);
});

test('GNOME panel keeps right and X gestures working outside the panel', () => {
    assert.ok(extensionSource.includes(
        '_handleVisiblePanelEvent(event, type) {'));
    assert.ok(extensionSource.includes(
        'if (this._panel.containsActor(actor))'));
    assert.ok(extensionSource.includes(
        'return this._onButtonPress(event, buttonNumber, buttonName);'));
    assert.ok(extensionSource.includes(
        'return this._onButtonRelease(event, buttonNumber, buttonName);'));
});

test('GNOME panel activates a running application instead of spawning a copy', () => {
    assert.equal(matchesExecutableName('/usr/bin/code', 'code\n'), true);
    assert.equal(matchesExecutableName('code', 'code'), true);
    assert.equal(matchesExecutableName('firefox', 'code'), false);
    assert.equal(matchesExecutableName('  ', 'code'), false);
    assert.equal(
        matchesExecutableName('reallylongapplicationname', 'reallylongappli'), true);
    assert.match(shellPanelSource, /item\.activateIfRunning && this\._activateRunning\(executable\)/);
    assert.match(shellPanelSource, /_activateRunning\(executable\) \{/);
    assert.match(shellPanelSource, /GLib\.file_get_contents\(`\/proc\/\$\{pid\}\/comm`\)/);
    assert.match(shellPanelSource, /matchesExecutableName\(executable,/);
    assert.match(shellPanelSource, /Main\.activateWindow\(metaWindow,/);
});

test('defaults keep four gestures and smart Linux clipboard actions', () => {
    const config = createDefaultConfig();
    assert.deepEqual(config.actions.map(item => item.type), [
        'CopyAction', 'PasteAction', 'ShortcutAction', 'WindowAction',
    ]);
    assert.deepEqual(config.globalProfile.gestures.map(item => ({
        button: item.button,
        directions: item.directions,
        actionId: item.actionId,
    })), [
        {button: 'right', directions: ['up'], actionId: 'smart-copy'},
        {button: 'right', directions: ['down'], actionId: 'smart-paste'},
        {
            button: 'right', directions: ['down', 'right', 'down'],
            actionId: 'press-enter',
        },
        {
            button: 'right', directions: ['up', 'right', 'up'],
            actionId: 'window-toggle-above',
        },
    ]);
    assert.equal(config.actions[2].accelerator, 'Return');
});

test('regressed shortcut defaults migrate back to smart clipboard actions', () => {
    const config = createDefaultConfig();
    config.actions[0] = {...config.actions[0], type: 'ShortcutAction', accelerator: 'Ctrl+C'};
    config.actions[1] = {
        ...config.actions[1], type: 'ShortcutAction', accelerator: '<Control>v',
    };
    const migrated = normalizeConfig(config).config;
    assert.deepEqual(migrated.actions.slice(0, 2).map(item => item.type), [
        'CopyAction', 'PasteAction',
    ]);
    assert.equal('accelerator' in migrated.actions[0], false);
    assert.equal('accelerator' in migrated.actions[1], false);

    config.actions[0].accelerator = '<Control><Shift>c';
    const customized = normalizeConfig(config).config;
    assert.equal(customized.actions[0].type, 'ShortcutAction');
});

test('shortcuts accept friendly and legacy formats', () => {
    for (const value of ['Ctrl+C', 'Control+C', 'Ctrl C', 'control c', '<Control>c']) {
        assert.equal(normalizeAccelerator(value), '<Control>c');
        assert.equal(displayAccelerator(value), 'Ctrl+C');
    }
    assert.equal(normalizeAccelerator('Ctrl+Shift+T'), '<Control><Shift>t');
    assert.equal(displayAccelerator('<Alt>Left'), 'Alt+Left');
    assert.throws(() => normalizeAccelerator('Ctrl+'));
});

test('smart clipboard actions use terminal-specific shortcuts', () => {
    for (const identity of [
        {desktopId: 'org.gnome.Terminal.desktop'},
        {wmClass: 'xfce4-terminal'},
        {gtkApplicationId: 'org.gnome.Ptyxis'},
        {desktopId: 'org.kde.konsole.desktop'},
    ]) {
        assert.equal(isTerminalIdentity(identity), true);
        assert.equal(copyAccelerator(identity), '<Control><Shift>c');
        assert.equal(pasteAccelerator(identity), '<Control><Shift>v');
    }
    assert.equal(isTerminalIdentity({desktopId: 'firefox.desktop'}), false);
    assert.equal(copyAccelerator({wmClass: 'libreoffice-writer'}), '<Control>c');
    assert.equal(pasteAccelerator({wmClass: 'libreoffice-writer'}), '<Control>v');
    assert.equal(actionDisplayName(
        {name: '动作名称', type: 'CopyAction'}, {name: '我的复制手势'}
    ), '我的复制手势');
    assert.equal(actionDisplayName({name: '粘贴', type: 'PasteAction'}), '粘贴');
});

test('successful action labels are enabled with a short default fade', () => {
    const schema = readFileSync(
        new URL('../schemas/org.gnome.shell.extensions.wgestures.gschema.xml', import.meta.url),
        'utf8'
    );
    assert.match(schema, /<key name="show-command-name"[\s\S]*?<default>true<\/default>/);
    assert.match(schema, /<key name="fade-duration"[\s\S]*?<default>300<\/default>/);
    assert.match(schema, /<key name="autostart-enabled"[\s\S]*?<default>true<\/default>/);
    assert.match(schema, /<key name="minimize-to-tray"[\s\S]*?<default>true<\/default>/);
    assert.match(schema, /<key name="middle-panel-enabled"[\s\S]*?<default>true<\/default>/);
});

test('preferences place the middle quick panel in the trigger-button group', () => {
    const preferences = readFileSync(new URL('../prefs.js', import.meta.url), 'utf8');
    assert.match(preferences,
        /GENERAL_TRIGGER_BUTTONS = Object\.freeze\(\['right', 'middle', 'x1', 'x2'\]\)/);
    assert.match(preferences,
        /button === 'middle'[\s\S]*?'middle-panel-enabled'[\s\S]*?buttonsGroup\.add\(row\)/);
});

test('application identity uses documented precedence and inherits global gestures', () => {
    const config = createDefaultConfig();
    config.profiles.push({
        id: 'firefox', name: 'Firefox', enabled: true, inheritGlobal: true,
        matchers: [{type: 'desktopId', value: 'firefox_firefox.desktop'}], gestures: [],
    });
    const profile = findMatchingProfile(config, {desktopId: 'FIREFOX_FIREFOX.DESKTOP'});
    assert.equal(profile.id, 'firefox');
    const inheritedCopy = resolveGesture(
        config, {desktopId: 'firefox_firefox.desktop'}, 'right', ['up']
    );
    assert.equal(inheritedCopy.action.id, 'smart-copy');
});

test('disabled application profile blocks global inheritance', () => {
    const config = createDefaultConfig();
    config.profiles.push({
        id: 'blocked', name: 'Blocked', enabled: false, inheritGlobal: true,
        matchers: [{type: 'wmClass', value: 'blocked'}], gestures: [],
    });
    assert.equal(resolveGesture(config, {wmClass: 'blocked'}, 'right', ['left']), null);
});

test('normalization drops conflicts and unknown actions', () => {
    const config = createDefaultConfig();
    config.actions.push({id: 'bad', name: 'Bad', type: 'UnknownAction'});
    config.globalProfile.gestures.push({...config.globalProfile.gestures[0], id: 'duplicate'});
    const normalized = normalizeConfig(config);
    assert.ok(normalized.warnings.length >= 2);
    assert.equal(normalized.config.actions.some(item => item.id === 'bad'), false);
});

test('single-direction gestures allow moderate drawing error', () => {
    const config = createDefaultConfig();
    const upward = resolveGesture(config, {}, 'right', ['up-right', 'up'], {
        origin: {x: 0, y: 0}, end: {x: 60, y: -100},
    });
    assert.equal(upward.action.id, 'smart-copy');
    const downward = resolveGesture(config, {}, 'right', ['down-left', 'down'], {
        origin: {x: 0, y: 0}, end: {x: -50, y: 100},
    });
    assert.equal(downward.action.id, 'smart-paste');
    assert.equal(resolveGesture(config, {}, 'right', ['up-right'], {
        origin: {x: 0, y: 0}, end: {x: 100, y: -100},
    }), null);
    assert.equal(resolveGesture(config, {}, 'middle', ['up-right', 'up'], {
        origin: {x: 0, y: 0}, end: {x: 60, y: -100},
    }), null);
});

test('fast multi-stroke paths do not degrade to copy or paste', () => {
    const config = createDefaultConfig();
    const fastEnter = {
        origin: {x: 0, y: 0}, end: {x: 0, y: 120}, pathLength: 320,
    };
    assert.equal(resolveGesture(config, {}, 'right', ['down'], fastEnter), null);
    assert.equal(resolveGesture(
        config, {}, 'right', ['down-right', 'down'], fastEnter
    ), null);
    const fastTopmost = {
        origin: {x: 0, y: 120}, end: {x: 0, y: 0}, pathLength: 320,
    };
    assert.equal(resolveGesture(config, {}, 'right', ['up'], fastTopmost), null);
    assert.equal(resolveGesture(
        config, {}, 'right', ['up-right', 'up'], fastTopmost
    ), null);
    const straightCopy = {
        origin: {x: 0, y: 100}, end: {x: 8, y: 0}, pathLength: 104,
    };
    assert.equal(resolveGesture(
        config, {}, 'right', ['up'], straightCopy
    ).action.id, 'smart-copy');
});

test('recognizer tracks raw path length across fast corners', () => {
    const recognizer = new GestureRecognizer({
        startThreshold: 5, segmentThreshold: 12,
    });
    recognizer.begin(0, 0);
    for (const [x, y] of [[2, 1], [0, 100], [100, 100], [100, 200]])
        recognizer.addPoint(x, y);
    const result = recognizer.finish();
    assert.equal(result.pathLength, 300);
    assert.deepEqual(result.origin, {x: 0, y: 0});
    assert.deepEqual(result.end, {x: 100, y: 200});
});

test('rounded corners match the window above gesture', () => {
    const config = createDefaultConfig();
    const exact = resolveGesture(config, {}, 'right', ['up', 'right', 'up']);
    assert.equal(exact.action.operation, 'toggle-above');
    const rounded = resolveGesture(config, {}, 'right', [
        'up', 'up-right', 'right', 'up-right', 'up',
    ]);
    assert.equal(rounded.action.id, 'window-toggle-above');
    assert.equal(rounded.gesture.name, '窗口置顶');
});

test('packaged default configuration is valid and matches the generated defaults', () => {
    const packaged = JSON.parse(readFileSync(
        new URL('../defaults/gestures-v1.json', import.meta.url),
        'utf8'
    ));
    const normalized = normalizeConfig(packaged);
    assert.equal(normalized.warnings.length, 0);
    assert.deepEqual(normalized.config, createDefaultConfig());
});

test('unsupported schema versions and malformed legacy JSON fail closed', () => {
    assert.throws(() => normalizeConfig({schemaVersion: 999}), /Unsupported/);
    assert.throws(() => importLegacyConfig('{"Global":'), /有效 JSON/);
});

test('legacy importer converts safe actions and leaves app profiles unbound', () => {
    const legacy = {
        Global: {GestureIntents: [{
            Name: '后退', Gesture: {GestureButton: 1, Dirs: [6], Modifier: 0},
            Command: {$type: 'WGestures.Core.Commands.Impl.HotKeyCommand, WGestures.Core', Modifiers: [164], Keys: [37]},
        }]},
        Apps: {'c:\\windows\\app.exe': {
            Name: 'Old App', ExecutablePath: 'c:\\windows\\app.exe', InheritGlobalGestures: true,
            GestureIntents: [{
                Name: '关闭', Gesture: {GestureButton: 1, Dirs: [4, 2], Modifier: 0},
                Command: {$type: 'WGestures.Core.Commands.Impl.WindowControlCommand, WGestures.Core', ChangeWindowStateTo: 2},
            }],
        }},
    };
    const imported = importLegacyConfig(JSON.stringify(legacy));
    assert.equal(imported.report.imported, 2);
    assert.equal(imported.report.unboundProfiles.length, 1);
    assert.equal(imported.config.profiles[0].legacyExecutablePath, 'c:\\windows\\app.exe');
    assert.equal(imported.config.globalProfile.gestures[0].directions[0], 'left');
});

test('legacy importer never evaluates type metadata or scripts', () => {
    const legacy = {
        Global: {GestureIntents: [{
            Name: 'script', Gesture: {GestureButton: 1, Dirs: [2], Modifier: 0},
            Command: {$type: 'WGestures.Core.Commands.Impl.ScriptCommand, WGestures.Core', Code: 'throw new Error()'},
        }]},
        Apps: {},
    };
    const imported = importLegacyConfig(JSON.stringify(legacy));
    assert.equal(imported.report.imported, 0);
    assert.equal(imported.report.unsupported.length, 1);
});

test('repository default wg2 has a stable safe conversion report', () => {
    const legacyText = readFileSync(
        new URL('../../WGestures.App/defaults/gestures.wg2', import.meta.url),
        'utf8'
    );
    const imported = importLegacyConfig(legacyText);
    assert.equal(imported.report.imported, 4);
    assert.deepEqual(imported.report.unsupported, []);
    assert.deepEqual(imported.report.unboundProfiles, []);
});

test('portable config round trip preserves the normalized Linux configuration', () => {
    const source = createDefaultConfig();
    const text = exportPortableConfig(source);
    const document = JSON.parse(text);
    assert.equal(document.portableFormat, 'crossgestures-portable');
    const imported = importConfig(text);
    assert.equal(imported.report.portable, true);
    assert.equal(imported.report.imported, 4);
    assert.deepEqual(imported.report.unsupported, []);
    assert.deepEqual(imported.config, source);
});

test('portable importer rejects unknown versions and still accepts wg2', () => {
    const document = JSON.parse(exportPortableConfig(createDefaultConfig()));
    document.schemaVersion = 999;
    assert.throws(() => importConfig(JSON.stringify(document)), /不支持/);
    const legacyText = JSON.stringify({Global: {GestureIntents: []}, Apps: {}});
    assert.equal(importConfig(legacyText).report.imported, 0);
});

test('gesture session distinguishes short clicks, gestures, mismatched releases and cancellation', () => {
    const recognizer = new GestureRecognizer({startThreshold: 5, segmentThreshold: 5});
    const session = new GestureSession(recognizer);
    assert.equal(session.begin({buttonNumber: 3}, 0, 0), true);
    assert.equal(session.release(2).mismatched, true);
    const shortClick = session.release(3);
    assert.equal(shortClick.result.effective, false);

    session.begin({buttonNumber: 3}, 0, 0);
    session.motion(10, 0);
    const gesture = session.release(3);
    assert.equal(gesture.result.effective, true);
    assert.deepEqual(gesture.result.directions, ['right']);

    session.begin({buttonNumber: 3}, 0, 0);
    assert.equal(session.cancel(), true);
    assert.equal(session.active, null);
});

test('replay guard forwards exactly the synthetic press and release within its deadline', () => {
    const guard = new ReplayGuard(100);
    guard.arm(3, 1000);
    assert.equal(guard.consume(2, 1010), false);
    assert.equal(guard.consume(3, 1010), true);
    assert.equal(guard.consume(3, 1020), true);
    assert.equal(guard.consume(3, 1030), false);
    guard.arm(3, 1000);
    assert.equal(guard.consume(3, 1200), false);
});

let failures = 0;
for (const {name, callback} of tests) {
    try {
        await callback();
        console.log(`ok - ${name}`);
    } catch (error) {
        failures += 1;
        console.error(`not ok - ${name}`);
        console.error(error.stack || error);
    }
}

console.log(`\n${tests.length - failures}/${tests.length} tests passed`);
process.exitCode = failures === 0 ? 0 : 1;

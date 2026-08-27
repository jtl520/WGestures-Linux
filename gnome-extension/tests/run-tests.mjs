import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {GestureRecognizer, directionFromDelta, gestureKey} from '../core/gesture.js';
import {createDefaultConfig, findMatchingProfile, normalizeConfig, resolveGesture} from '../core/config.js';
import {importLegacyConfig} from '../core/importer.js';
import {GestureSession, ReplayGuard} from '../core/input-state.js';

const tests = [];
function test(name, callback) {
    tests.push({name, callback});
}

const sharedFixtures = JSON.parse(readFileSync(
    new URL('../../tests/fixtures/core-conformance.json', import.meta.url),
    'utf8'
));

test('JavaScript recognizer matches cross-backend conformance fixtures', () => {
    for (const item of sharedFixtures.directionCases) {
        assert.equal(directionFromDelta(item.dx, item.dy, item.mode), item.expected);
    }
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

test('application identity uses documented precedence and inherits global gestures', () => {
    const config = createDefaultConfig();
    config.profiles.push({
        id: 'firefox', name: 'Firefox', enabled: true, inheritGlobal: true,
        matchers: [{type: 'desktopId', value: 'firefox_firefox.desktop'}], gestures: [],
    });
    const profile = findMatchingProfile(config, {desktopId: 'FIREFOX_FIREFOX.DESKTOP'});
    assert.equal(profile.id, 'firefox');
    const resolved = resolveGesture(config, {desktopId: 'firefox_firefox.desktop'}, 'right', ['left']);
    assert.equal(resolved.action.id, 'shortcut-back');
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
    assert.equal(imported.report.imported, 35);
    assert.equal(imported.report.unsupported.length, 31);
    assert.equal(imported.report.unboundProfiles.length, 3);
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

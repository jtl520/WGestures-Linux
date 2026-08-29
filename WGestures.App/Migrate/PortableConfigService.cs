using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Newtonsoft.Json;
using WindowsInput.Native;
using WGestures.Core;
using WGestures.Core.Commands;
using WGestures.Core.Commands.Impl;
using WGestures.Core.Persistence.Impl;

namespace WGestures.App.Migrate
{
    internal sealed class PortableConfigReport
    {
        public int Converted { get; set; }
        public int Skipped { get; set; }
        public List<string> Warnings { get; private set; }

        public PortableConfigReport()
        {
            Warnings = new List<string>();
        }

        public string ToUserMessage(string operation)
        {
            var text = operation + "完成：可兼容 " + Converted + " 个手势，跳过 " + Skipped + " 个。";
            if (Warnings.Count > 0)
                text += Environment.NewLine + Environment.NewLine + string.Join(Environment.NewLine, Warnings.Take(12));
            return text;
        }
    }

    internal static class PortableConfigService
    {
        internal const string FormatName = "crossgestures-portable";
        internal const int SchemaVersion = 1;

        private static readonly string[] DirectionNames =
        {
            "up", "up-right", "right", "down-right",
            "down", "down-left", "left", "up-left"
        };

        public static PortableConfigReport Export(string path, JsonGestureIntentStore store)
        {
            if (store == null) throw new ArgumentNullException("store");
            var report = new PortableConfigReport();
            var document = new PortableDocument
            {
                PortableFormat = FormatName,
                SchemaVersion = SchemaVersion,
                Actions = new List<PortableAction>(),
                Profiles = new List<PortableProfile>(),
                GlobalProfile = new PortableProfile
                {
                    Id = "global",
                    Name = "全局",
                    Enabled = store.GlobalApp.IsGesturingEnabled,
                    InheritGlobal = false,
                    Matchers = new List<Dictionary<string, string>>(),
                    Gestures = new List<PortableGesture>()
                }
            };

            var nextId = 0;
            ExportApp(store.GlobalApp, document.GlobalProfile, document, report, ref nextId);
            foreach (var app in store.Apps.Values.OrderBy(item => item.Name))
            {
                var profile = new PortableProfile
                {
                    Id = "windows-profile-" + (++nextId),
                    Name = app.Name,
                    Enabled = app.IsGesturingEnabled,
                    InheritGlobal = app.InheritGlobalGestures,
                    Matchers = new List<Dictionary<string, string>>(),
                    LegacyExecutablePath = app.ExecutablePath,
                    Gestures = new List<PortableGesture>()
                };
                ExportApp(app, profile, document, report, ref nextId);
                if (profile.Gestures.Count > 0) document.Profiles.Add(profile);
            }

            var json = JsonConvert.SerializeObject(document, Formatting.Indented,
                new JsonSerializerSettings { NullValueHandling = NullValueHandling.Ignore });
            var fullPath = Path.GetFullPath(path);
            var directory = Path.GetDirectoryName(fullPath);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            var temporary = fullPath + ".tmp";
            File.WriteAllText(temporary, json, new UTF8Encoding(false));
            if (File.Exists(fullPath)) File.Replace(temporary, fullPath, null);
            else File.Move(temporary, fullPath);
            return report;
        }

        public static ConfigAndGestures Import(string path, out PortableConfigReport report)
        {
            report = new PortableConfigReport();
            PortableDocument document;
            try
            {
                document = JsonConvert.DeserializeObject<PortableDocument>(
                    File.ReadAllText(path, Encoding.UTF8));
            }
            catch (Exception exception)
            {
                throw new MigrateException("跨平台配置不是有效 JSON：" + exception.Message, exception);
            }
            if (document == null || document.PortableFormat != FormatName ||
                document.SchemaVersion != SchemaVersion)
                throw new MigrateException("不支持的 CrossGestures 跨平台配置版本。");

            var actions = (document.Actions ?? new List<PortableAction>())
                .Where(item => item != null && !string.IsNullOrWhiteSpace(item.Id))
                .GroupBy(item => item.Id)
                .ToDictionary(group => group.Key, group => group.First());
            var store = new JsonGestureIntentStore(
                Path.Combine(Path.GetTempPath(), "crossgestures-portable-" + Guid.NewGuid().ToString("N") + ".wg2"), "3");
            store.GlobalApp.Name = "(Global)";
            ImportProfile(document.GlobalProfile, store.GlobalApp, actions, report);

            foreach (var profile in document.Profiles ?? new List<PortableProfile>())
            {
                if (profile == null || !LooksLikeWindowsExecutablePath(profile.LegacyExecutablePath))
                {
                    var count = profile == null || profile.Gestures == null ? 0 : profile.Gestures.Count;
                    report.Skipped += count;
                    if (count > 0)
                        report.Warnings.Add((profile.Name ?? "Linux 应用配置") + "：没有 Windows 程序路径，需在 Windows 手工绑定。");
                    continue;
                }
                var app = new ExeApp
                {
                    Name = string.IsNullOrWhiteSpace(profile.Name) ? profile.LegacyExecutablePath : profile.Name,
                    ExecutablePath = profile.LegacyExecutablePath,
                    IsGesturingEnabled = profile.Enabled,
                    InheritGlobalGestures = profile.InheritGlobal
                };
                ImportProfile(profile, app, actions, report);
                if (app.GestureIntents.Count == 0) continue;
                ExeApp existing;
                if (store.TryGetExeApp(app.ExecutablePath, out existing)) existing.ImportGestures(app);
                else store.Add(app);
            }

            return new ConfigAndGestures(null, store, report.ToUserMessage("跨平台配置导入"));
        }

        private static void ExportApp(AbstractApp app, PortableProfile profile,
            PortableDocument document, PortableConfigReport report, ref int nextId)
        {
            foreach (var intent in app.GestureIntents.Values)
            {
                var reason = string.Empty;
                var action = ExportAction(intent.Command, ref nextId, intent.Name, out reason);
                if (intent.Gesture == null || intent.Gesture.Dirs.Count == 0 ||
                    intent.Gesture.Modifier != GestureModifier.None || action == null)
                {
                    report.Skipped++;
                    if (string.IsNullOrEmpty(reason) && intent.Gesture != null && intent.Gesture.Modifier != GestureModifier.None)
                        reason = "Linux 暂不支持滚轮/按键修饰手势";
                    report.Warnings.Add((intent.Name ?? "未命名手势") + "：" + (reason.Length == 0 ? "手势无有效方向" : reason));
                    continue;
                }
                var button = ButtonName(intent.Gesture.GestureButton);
                if (button == null)
                {
                    report.Skipped++;
                    report.Warnings.Add((intent.Name ?? "未命名手势") + "：触发按钮不兼容");
                    continue;
                }
                document.Actions.Add(action);
                profile.Gestures.Add(new PortableGesture
                {
                    Id = "windows-gesture-" + (++nextId),
                    Name = intent.Name,
                    Enabled = true,
                    Button = button,
                    Directions = intent.Gesture.Dirs.Select(value => DirectionNames[(int)value]).ToList(),
                    ActionId = action.Id
                });
                report.Converted++;
            }
        }

        private static PortableAction ExportAction(AbstractCommand command, ref int nextId,
            string name, out string reason)
        {
            reason = string.Empty;
            var result = new PortableAction
            {
                Id = "windows-action-" + (++nextId), Name = name, Enabled = true
            };
            var hotKey = command as HotKeyCommand;
            if (hotKey != null)
            {
                string accelerator;
                if (!TryExportAccelerator(hotKey, out accelerator))
                {
                    reason = "快捷键包含无法跨平台转换的键";
                    return null;
                }
                result.Type = "ShortcutAction";
                result.Accelerator = accelerator;
                return result;
            }
            var window = command as WindowControlCommand;
            if (window != null)
            {
                var operations = new[] { "toggle-maximized", "minimize", "close", "toggle-above" };
                var index = (int)window.ChangeWindowStateTo;
                if (index < 0 || index >= operations.Length)
                {
                    reason = "Windows 窗口停靠动作没有 Linux 等价项";
                    return null;
                }
                result.Type = "WindowAction";
                result.Operation = operations[index];
                return result;
            }
            var url = command as GotoUrlCommand;
            if (url != null)
            {
                Uri uri;
                if (!Uri.TryCreate(url.Url, UriKind.Absolute, out uri) ||
                    (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
                {
                    reason = "只有 HTTP/HTTPS 网址可以跨平台迁移";
                    return null;
                }
                result.Type = "LaunchAction";
                result.Target = url.Url;
                return result;
            }
            if (command is PauseWGesturesCommand)
            {
                result.Type = "PauseAction";
                return result;
            }
            if (command is DoNothingCommand)
            {
                result.Type = "NoopAction";
                return result;
            }
            reason = command == null ? "没有动作" : command.GetType().Name + " 是 Windows 专属动作";
            return null;
        }

        private static void ImportProfile(PortableProfile profile, AbstractApp target,
            IDictionary<string, PortableAction> actions, PortableConfigReport report)
        {
            if (profile == null) return;
            target.IsGesturingEnabled = profile.Enabled;
            foreach (var item in profile.Gestures ?? new List<PortableGesture>())
            {
                PortableAction action = null;
                var reason = string.Empty;
                AbstractCommand command = null;
                if (item != null && actions.TryGetValue(item.ActionId ?? string.Empty, out action))
                    command = ImportAction(action, out reason);
                if (item == null || !item.Enabled || command == null)
                {
                    report.Skipped++;
                    report.Warnings.Add((item == null ? "无效手势" : item.Name) + "：" +
                        (string.IsNullOrEmpty(reason) ? "动作缺失或已禁用" : reason));
                    continue;
                }
                GestureTriggerButton button;
                if (!TryButton(item.Button, out button))
                {
                    report.Skipped++;
                    report.Warnings.Add(item.Name + "：触发按钮不兼容");
                    continue;
                }
                var gesture = new Gesture(button);
                var valid = true;
                foreach (var direction in item.Directions ?? new List<string>())
                {
                    var index = Array.IndexOf(DirectionNames, direction);
                    if (index < 0) { valid = false; break; }
                    gesture.Dirs.Add((Gesture.GestureDir)index);
                }
                if (!valid || gesture.Dirs.Count == 0)
                {
                    report.Skipped++;
                    report.Warnings.Add(item.Name + "：方向数据无效");
                    continue;
                }
                target.GestureIntents.AddOrReplace(new GestureIntent
                {
                    Name = string.IsNullOrWhiteSpace(item.Name) ? action.Name : item.Name,
                    Gesture = gesture,
                    Command = command,
                    ExecuteOnModifier = false
                });
                report.Converted++;
            }
        }

        private static AbstractCommand ImportAction(PortableAction action, out string reason)
        {
            reason = string.Empty;
            if (action == null || !action.Enabled) { reason = "动作已禁用"; return null; }
            if (action.Type == "ShortcutAction")
            {
                HotKeyCommand command;
                if (TryImportAccelerator(action.Accelerator, out command)) return command;
                reason = "快捷键无法转换为 Windows 按键";
                return null;
            }
            if (action.Type == "CopyAction") return MakeHotKey(VirtualKeyCode.LCONTROL, VirtualKeyCode.VK_C);
            if (action.Type == "PasteAction") return MakeHotKey(VirtualKeyCode.LCONTROL, VirtualKeyCode.VK_V);
            if (action.Type == "WindowAction")
            {
                var operations = new Dictionary<string, WindowControlCommand.WindowOperation>
                {
                    { "toggle-maximized", WindowControlCommand.WindowOperation.MAXIMIZE_RESTORE },
                    { "minimize", WindowControlCommand.WindowOperation.MINIMIZE },
                    { "close", WindowControlCommand.WindowOperation.CLOSE },
                    { "toggle-above", WindowControlCommand.WindowOperation.TOP_MOST }
                };
                WindowControlCommand.WindowOperation operation;
                if (operations.TryGetValue(action.Operation ?? string.Empty, out operation))
                    return new WindowControlCommand { ChangeWindowStateTo = operation };
                if (action.Operation == "toggle-fullscreen") return MakeHotKey(null, VirtualKeyCode.F11);
                reason = "窗口动作没有 Windows 等价项";
                return null;
            }
            if (action.Type == "LaunchAction")
            {
                Uri uri;
                if (Uri.TryCreate(action.Target, UriKind.Absolute, out uri) &&
                    (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps))
                    return new GotoUrlCommand { Url = action.Target };
                reason = "Linux Desktop ID 或文件路径需在 Windows 手工重新选择";
                return null;
            }
            if (action.Type == "PauseAction") return new PauseWGesturesCommand();
            if (action.Type == "NoopAction") return new DoNothingCommand();
            if (action.Type == "CommandAction")
                reason = "Linux Shell 命令不会在 Windows 自动启用";
            else reason = "未知动作 " + (action.Type ?? "(空)");
            return null;
        }

        private static HotKeyCommand MakeHotKey(VirtualKeyCode? modifier, VirtualKeyCode key)
        {
            var command = new HotKeyCommand();
            if (modifier.HasValue) command.Modifiers.Add(modifier.Value);
            command.Keys.Add(key);
            return command;
        }

        private static bool TryExportAccelerator(HotKeyCommand command, out string accelerator)
        {
            accelerator = null;
            if (command.Keys == null || command.Keys.Count != 1) return false;
            var modifiers = new List<string>();
            foreach (var key in command.Modifiers ?? new List<VirtualKeyCode>())
            {
                var value = ModifierName((int)key);
                if (value == null) return false;
                if (!modifiers.Contains(value)) modifiers.Add(value);
            }
            var keyName = KeyName((int)command.Keys[0]);
            if (keyName == null) return false;
            accelerator = string.Concat(modifiers.Select(value => "<" + value + ">")) + keyName;
            return true;
        }

        private static bool TryImportAccelerator(string accelerator, out HotKeyCommand command)
        {
            command = new HotKeyCommand();
            var remaining = (accelerator ?? string.Empty).Trim();
            while (remaining.StartsWith("<"))
            {
                var match = Regex.Match(remaining, "^<([^<>]+)>");
                if (!match.Success) return false;
                VirtualKeyCode modifier;
                if (!TryModifier(match.Groups[1].Value, out modifier)) return false;
                if (!command.Modifiers.Contains(modifier)) command.Modifiers.Add(modifier);
                remaining = remaining.Substring(match.Length).TrimStart();
            }
            VirtualKeyCode key;
            if (!TryKey(remaining, out key)) return false;
            command.Keys.Add(key);
            return true;
        }

        private static string ModifierName(int code)
        {
            if (code == 16 || code == 160 || code == 161) return "Shift";
            if (code == 17 || code == 162 || code == 163) return "Control";
            if (code == 18 || code == 164 || code == 165) return "Alt";
            if (code == 91 || code == 92) return "Super";
            return null;
        }

        private static string KeyName(int code)
        {
            var special = new Dictionary<int, string>
            {
                { 8, "BackSpace" }, { 9, "Tab" }, { 13, "Return" }, { 27, "Escape" },
                { 32, "space" }, { 33, "Page_Up" }, { 34, "Page_Down" }, { 35, "End" },
                { 36, "Home" }, { 37, "Left" }, { 38, "Up" }, { 39, "Right" },
                { 40, "Down" }, { 45, "Insert" }, { 46, "Delete" }, { 173, "AudioMute" },
                { 174, "AudioLowerVolume" }, { 175, "AudioRaiseVolume" }
            };
            string value;
            if (special.TryGetValue(code, out value)) return value;
            if (code >= 48 && code <= 57) return ((char)code).ToString();
            if (code >= 65 && code <= 90) return ((char)code).ToString().ToLowerInvariant();
            if (code >= 112 && code <= 135) return "F" + (code - 111);
            return null;
        }

        private static bool TryModifier(string name, out VirtualKeyCode key)
        {
            var value = (name ?? string.Empty).Trim().ToLowerInvariant();
            if (value == "control" || value == "ctrl" || value == "primary") { key = VirtualKeyCode.LCONTROL; return true; }
            if (value == "alt") { key = VirtualKeyCode.LMENU; return true; }
            if (value == "shift") { key = VirtualKeyCode.LSHIFT; return true; }
            if (value == "super" || value == "win" || value == "windows" || value == "meta") { key = VirtualKeyCode.LWIN; return true; }
            key = 0;
            return false;
        }

        private static bool TryKey(string name, out VirtualKeyCode key)
        {
            var value = (name ?? string.Empty).Trim();
            var aliases = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
            {
                { "BackSpace", 8 }, { "Tab", 9 }, { "Return", 13 }, { "Enter", 13 },
                { "Escape", 27 }, { "Esc", 27 }, { "space", 32 }, { "Page_Up", 33 },
                { "PageUp", 33 }, { "Page_Down", 34 }, { "PageDown", 34 }, { "End", 35 },
                { "Home", 36 }, { "Left", 37 }, { "Up", 38 }, { "Right", 39 },
                { "Down", 40 }, { "Insert", 45 }, { "Delete", 46 }, { "AudioMute", 173 },
                { "AudioLowerVolume", 174 }, { "AudioRaiseVolume", 175 }
            };
            int code;
            if (aliases.TryGetValue(value, out code)) { key = (VirtualKeyCode)code; return true; }
            if (value.Length == 1 && char.IsLetterOrDigit(value[0]))
            {
                key = (VirtualKeyCode)char.ToUpperInvariant(value[0]);
                return true;
            }
            var match = Regex.Match(value, "^F(\\d{1,2})$", RegexOptions.IgnoreCase);
            int function;
            if (match.Success && int.TryParse(match.Groups[1].Value, out function) && function >= 1 && function <= 24)
            {
                key = (VirtualKeyCode)(111 + function);
                return true;
            }
            key = 0;
            return false;
        }

        private static string ButtonName(GestureTriggerButton button)
        {
            if (button == GestureTriggerButton.Right) return "right";
            if (button == GestureTriggerButton.Middle) return "middle";
            if (button == GestureTriggerButton.X1) return "x1";
            if (button == GestureTriggerButton.X2) return "x2";
            return null;
        }

        private static bool TryButton(string name, out GestureTriggerButton button)
        {
            var values = new Dictionary<string, GestureTriggerButton>(StringComparer.OrdinalIgnoreCase)
            {
                { "right", GestureTriggerButton.Right }, { "middle", GestureTriggerButton.Middle },
                { "x1", GestureTriggerButton.X1 }, { "x2", GestureTriggerButton.X2 }
            };
            return values.TryGetValue(name ?? string.Empty, out button);
        }

        private static bool LooksLikeWindowsExecutablePath(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) return false;
            return Regex.IsMatch(path, "^[A-Za-z]:[\\\\/]") || path.StartsWith("\\\\");
        }

        private sealed class PortableDocument
        {
            [JsonProperty("portableFormat")] public string PortableFormat { get; set; }
            [JsonProperty("schemaVersion")] public int SchemaVersion { get; set; }
            [JsonProperty("actions")] public List<PortableAction> Actions { get; set; }
            [JsonProperty("globalProfile")] public PortableProfile GlobalProfile { get; set; }
            [JsonProperty("profiles")] public List<PortableProfile> Profiles { get; set; }
        }

        private sealed class PortableAction
        {
            [JsonProperty("id")] public string Id { get; set; }
            [JsonProperty("name")] public string Name { get; set; }
            [JsonProperty("type")] public string Type { get; set; }
            [JsonProperty("enabled")] public bool Enabled { get; set; }
            [JsonProperty("accelerator")] public string Accelerator { get; set; }
            [JsonProperty("operation")] public string Operation { get; set; }
            [JsonProperty("target")] public string Target { get; set; }
        }

        private sealed class PortableGesture
        {
            [JsonProperty("id")] public string Id { get; set; }
            [JsonProperty("name")] public string Name { get; set; }
            [JsonProperty("enabled")] public bool Enabled { get; set; }
            [JsonProperty("button")] public string Button { get; set; }
            [JsonProperty("directions")] public List<string> Directions { get; set; }
            [JsonProperty("actionId")] public string ActionId { get; set; }
        }

        private sealed class PortableProfile
        {
            [JsonProperty("id")] public string Id { get; set; }
            [JsonProperty("name")] public string Name { get; set; }
            [JsonProperty("enabled")] public bool Enabled { get; set; }
            [JsonProperty("inheritGlobal")] public bool InheritGlobal { get; set; }
            [JsonProperty("matchers")] public List<Dictionary<string, string>> Matchers { get; set; }
            [JsonProperty("legacyExecutablePath")] public string LegacyExecutablePath { get; set; }
            [JsonProperty("gestures")] public List<PortableGesture> Gestures { get; set; }
        }
    }
}

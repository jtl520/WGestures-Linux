using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using WGestures.App.Gui.Model;
using WGestures.App.Migrate;
using WGestures.Common.OsSpecific.Windows;
using WGestures.Core;
using WGestures.Core.Commands;
using WGestures.Core.Commands.Impl;

namespace WGestures.App.Gui.Windows
{
    // Only explicit commands cross the web/native boundary. Native type names are
    // never accepted from the UI or deserialized with TypeNameHandling.
    internal sealed class SharedSettingsService
    {
        private readonly SettingsFormController controller;
        private ConfigAndGestures pendingImport;
        private string importToken;
        private static readonly string[] Directions = { "up", "up-right", "right", "down-right", "down", "down-left", "left", "up-left" };
        private static readonly string[] Operations = { "toggle-maximized", "minimize", "close", "toggle-above", "dock-left", "dock-right" };
        private static readonly Dictionary<string, GestureTriggerButton> Buttons = new Dictionary<string, GestureTriggerButton>
        {
            { "right", GestureTriggerButton.Right }, { "x1", GestureTriggerButton.X1 }, { "x2", GestureTriggerButton.X2 }
        };

        public SharedSettingsService(SettingsFormController controller) { this.controller = controller; }

        private IEnumerable<ExeApp> Apps()
        {
            return controller.IntentStore.OrderBy(a => (a as OrderableExeApp)?.Order ?? 0);
        }
        private static IEnumerable<GestureIntent> Intents(AbstractApp app)
        {
            return app.GestureIntents.Values.OrderBy(g => (g as OrderableIntent)?.Order ?? 0);
        }
        private AbstractApp Profile(string id)
        {
            if (id == "global") return controller.IntentStore.GlobalApp;
            ExeApp app;
            if (id != null && id.StartsWith("app:") && controller.IntentStore.TryGetExeApp(id.Substring(4), out app)) return app;
            throw new ArgumentException("应用配置已不存在，请重新选择。");
        }
        private static GestureIntent Intent(AbstractApp app, string id)
        {
            var result = app.GestureIntents.Values.FirstOrDefault(g => g.Gesture.ToString() == id);
            if (result == null) throw new ArgumentException("手势已不存在，请刷新后重试。");
            return result;
        }

        private JObject Settings()
        {
            var c = controller;
            return new JObject
            {
                ["paused"] = c.GestureParser.IsPaused,
                ["autostart-enabled"] = c.AutoStart,
                ["minimize-to-tray"] = c.Config.Get("MinimizeToTray", true),
                ["trigger-buttons"] = new JArray(Buttons.Where(b => (c.PathTrackerTriggerButton & b.Value) != 0).Select(b => b.Key)),
                ["middle-panel-enabled"] = c.MiddlePanelEnabled,
                ["direction-mode"] = c.GestureParserEnable8DirGesture ? 8 : 4,
                ["start-threshold"] = c.PathTrackerInitialValidMove,
                ["path-color"] = ColorTranslator.ToHtml(c.GestureViewMainPathColor),
                ["invalid-path-color"] = ColorTranslator.ToHtml(c.GestureViewAlternativePathColor),
                ["path-width"] = c.GesturePathWidth,
                ["fade-duration"] = c.GestureFadeDuration,
                ["show-command-name"] = c.GestureViewShowCommandName,
                ["show-path"] = c.GestureViewShowPath,
                ["disable-fullscreen"] = c.PathTrackerDisableInFullScreen,
                ["prefer-cursor-window"] = c.PathTrackerPreferCursorWindow,
                ["initial-timeout-enabled"] = c.PathTrackerInitialStayTimeout,
                ["initial-timeout"] = c.PathTrackerInitalStayTimeoutMillis,
                ["stay-timeout-enabled"] = c.PathTrackerStayTimeout,
                ["stay-timeout"] = c.PathTrackerStayTimeoutMillis
            };
        }

        private static JObject ActionSnapshot(AbstractCommand command)
        {
            int next = 0; string reason;
            var action = PortableConfigService.ExportAction(command, ref next, "", out reason);
            if (action != null) return JObject.FromObject(action);
            var window = command as WindowControlCommand;
            if (window != null && (int)window.ChangeWindowStateTo >= 0 && (int)window.ChangeWindowStateTo < Operations.Length)
                return new JObject { ["type"] = "WindowAction", ["operation"] = Operations[(int)window.ChangeWindowStateTo] };
            var file = command as OpenFileCommand;
            if (file != null) return new JObject { ["type"] = "LaunchAction", ["target"] = file.FilePath };
            // Complex CMD/Lua/modifier actions retain their original editor and all fields.
            return new JObject { ["type"] = "NativeAction", ["summary"] = command == null ? "未配置" : command.Description() };
        }

        private static JObject ProfileSnapshot(AbstractApp app)
        {
            var exe = app as ExeApp;
            return new JObject
            {
                ["id"] = exe == null ? "global" : "app:" + exe.ExecutablePath,
                ["name"] = exe == null ? "全局" : app.Name,
                ["enabled"] = app.IsGesturingEnabled,
                ["inheritGlobal"] = exe != null && exe.InheritGlobalGestures,
                ["matchers"] = exe == null ? new JArray() : new JArray(new JObject { ["type"] = "executable", ["value"] = exe.ExecutablePath }),
                ["gestures"] = new JArray(Intents(app).Select(g =>
                {
                    var action = ActionSnapshot(g.Command);
                    return new JObject
                    {
                        ["id"] = g.Gesture.ToString(), ["name"] = g.Name,
                        ["button"] = g.Gesture.GestureButton.ToString().ToLowerInvariant(),
                        ["directions"] = new JArray(g.Gesture.Dirs.Select(d => Directions[(int)d])),
                        ["action"] = action,
                        ["editable"] = (string)action["type"] != "NativeAction" && g.Gesture.Modifier == GestureModifier.None && g.Gesture.GestureButton != GestureTriggerButton.Middle
                    };
                }))
            };
        }

        public JObject Snapshot()
        {
            var profiles = new JArray(ProfileSnapshot(controller.IntentStore.GlobalApp));
            foreach (var app in Apps()) profiles.Add(ProfileSnapshot(app));
            var snapshot = new JObject
            {
                ["platform"] = "Windows", ["version"] = "2.2.0", ["settings"] = Settings(), ["profiles"] = profiles,
                ["capabilities"] = new JObject
                {
                    ["actions"] = new JArray("ShortcutAction", "CopyAction", "PasteAction", "WindowAction", "LaunchAction", "PauseAction", "NoopAction"),
                    ["operations"] = new JArray(Operations.Concat(new[] { "toggle-fullscreen" })),
                    ["matchers"] = new JArray("executable"), ["reorder"] = true, ["legacy"] = true, ["fullBackup"] = true
                }
            };
            using (var sha = SHA256.Create())
                snapshot["revision"] = Convert.ToBase64String(sha.ComputeHash(Encoding.UTF8.GetBytes(snapshot.ToString(Formatting.None))));
            return snapshot;
        }

        private static bool Boolean(JToken value)
        {
            if (value == null || value.Type != JTokenType.Boolean) throw new ArgumentException("开关值无效。");
            return (bool)value;
        }
        private static double Number(JToken value, double min, double max, bool integer = true)
        {
            if (value == null || (value.Type != JTokenType.Integer && value.Type != JTokenType.Float)) throw new ArgumentException("请输入有效数字。");
            var number = (double)value;
            if (double.IsNaN(number) || double.IsInfinity(number) || number < min || number > max || (integer && number != Math.Floor(number)))
                throw new ArgumentException("数值超出允许范围。");
            return number;
        }
        private static Color ColorValue(JToken value)
        {
            var text = (string)value;
            if (text == null || !System.Text.RegularExpressions.Regex.IsMatch(text, "^#[0-9a-fA-F]{6}$")) throw new ArgumentException("颜色必须为 #RRGGBB。");
            return ColorTranslator.FromHtml(text);
        }
        private void SetSetting(string key, JToken value)
        {
            var c = controller;
            switch (key)
            {
                case "paused": if (Boolean(value)) c.GestureParser.Pause(); else c.GestureParser.Resume(); break;
                case "autostart-enabled":
                    var enabled = Boolean(value);
                    if (enabled) AutoStarter.Register(Constants.AutoStartIdentifier, System.Windows.Forms.Application.ExecutablePath);
                    else AutoStarter.Unregister(Constants.AutoStartIdentifier);
                    c.Config.Set(ConfigKeys.AutoStart, enabled); break;
                case "minimize-to-tray": c.Config.Set("MinimizeToTray", Boolean(value)); break;
                case "trigger-buttons":
                    var values = value as JArray;
                    if (values == null || values.Any(v => v.Type != JTokenType.String || !Buttons.ContainsKey((string)v)) || values.Distinct(new JTokenEqualityComparer()).Count() != values.Count)
                        throw new ArgumentException("触发按钮无效。");
                    c.PathTrackerTriggerButton = values.Aggregate(GestureTriggerButton.None, (current, v) => current | Buttons[(string)v]); break;
                case "middle-panel-enabled": c.MiddlePanelEnabled = Boolean(value); break;
                case "direction-mode": var mode = Number(value, 4, 8); if (mode != 4 && mode != 8) throw new ArgumentException("仅支持四方向或八方向。"); c.GestureParserEnable8DirGesture = mode == 8; break;
                case "start-threshold": c.PathTrackerInitialValidMove = (int)Number(value, 2, 100); break;
                case "path-color": c.GestureViewMainPathColor = ColorValue(value); break;
                case "invalid-path-color": c.GestureViewAlternativePathColor = ColorValue(value); break;
                case "path-width": c.GesturePathWidth = (float)Number(value, 1, 24, false); break;
                case "fade-duration": c.GestureFadeDuration = (int)Number(value, 0, 3000); break;
                case "show-command-name": c.GestureViewShowCommandName = Boolean(value); break;
                case "show-path": c.GestureViewShowPath = Boolean(value); break;
                case "disable-fullscreen": c.PathTrackerDisableInFullScreen = Boolean(value); break;
                case "prefer-cursor-window": c.PathTrackerPreferCursorWindow = Boolean(value); break;
                case "initial-timeout-enabled": c.PathTrackerInitialStayTimeout = Boolean(value); break;
                case "initial-timeout": c.PathTrackerInitalStayTimeoutMillis = (int)Number(value, 50, 5000); break;
                case "stay-timeout-enabled": c.PathTrackerStayTimeout = Boolean(value); break;
                case "stay-timeout": c.PathTrackerStayTimeoutMillis = (int)Number(value, 50, 5000); break;
                default: throw new ArgumentException("未知设置项。");
            }
            c.Config.Save();
        }

        public JObject Mutate(string method, JObject p)
        {
            if ((string)p["revision"] != (string)Snapshot()["revision"]) throw new InvalidOperationException("配置已在其他窗口中修改，请刷新后重试。");
            if (method == "setting") { SetSetting((string)p["key"], p["value"]); return new JObject { ["snapshot"] = Snapshot() }; }
            if (method.StartsWith("gesture"))
            {
                var profile = Profile((string)p["profileId"]);
                if (method == "gestureSave") SaveGesture(profile, p);
                else if (method == "gestureDelete") profile.Remove(Intent(profile, (string)p["id"]));
                else if (method == "gestureMove") MoveGesture(profile, (string)p["id"], (int)Number(p["delta"], -1, 1));
                else throw new ArgumentException("未知操作。");
            }
            else if (method == "profileSave") SaveProfile(p);
            else if (method == "profileToggle") Profile((string)p["id"]).IsGesturingEnabled = Boolean(p["enabled"]);
            else if (method == "profileDelete")
            {
                var app = Profile((string)p["id"]) as ExeApp;
                if (app == null) throw new ArgumentException("不能删除全局配置。");
                controller.IntentStore.Remove(app);
            }
            else if (method == "profileMove") MoveProfile((string)p["id"], (int)Number(p["delta"], -1, 1));
            else if (method == "reset") controller.RestoreDefaultGestures();
            else if (method == "importApply")
            {
                if (pendingImport == null || (string)p["token"] != importToken) throw new ArgumentException("导入预览已失效，请重新选择文件。");
                controller.Import(pendingImport, false, true, true);
                pendingImport = null; importToken = null;
            }
            else throw new ArgumentException("未知操作。");
            controller.IntentStore.Save();
            return new JObject { ["snapshot"] = Snapshot() };
        }

        private void SaveGesture(AbstractApp profile, JObject p)
        {
            var name = ((string)p["name"] ?? "").Trim();
            if (name.Length == 0 || name.Length > 120) throw new ArgumentException("请填写 1–120 字的手势名称。");
            GestureTriggerButton button;
            if (!Buttons.TryGetValue((string)p["button"] ?? "", out button)) throw new ArgumentException("触发按钮无效。");
            var directions = p["directions"] as JArray;
            if (directions == null || directions.Count < 1 || directions.Count > 32 || directions.Any(d => !Directions.Contains((string)d))) throw new ArgumentException("手势方向无效。");
            var old = p["id"] == null || p["id"].Type == JTokenType.Null ? null : Intent(profile, (string)p["id"]);
            var gesture = new Gesture(button) { Dirs = directions.Select(d => (Gesture.GestureDir)Array.IndexOf(Directions, (string)d)).ToList() };
            var duplicate = profile.Find(gesture);
            if (duplicate != null && duplicate != old) throw new ArgumentException("与手势“" + duplicate.Name + "”冲突。");
            var raw = p["action"] as JObject;
            if (raw == null) throw new ArgumentException("动作类型无效。");
            AbstractCommand command = null;
            var type = (string)raw["type"];
            if (type == "LaunchAction")
            {
                var target = ((string)raw["target"] ?? "").Trim();
                if (target.Length == 0) throw new ArgumentException("目标不能为空。");
                Uri uri;
                if (Uri.TryCreate(target, UriKind.Absolute, out uri) && (uri.Scheme == "http" || uri.Scheme == "https")) command = new GotoUrlCommand { Url = target };
                else if (Path.IsPathRooted(target)) command = new OpenFileCommand { FilePath = target };
                else throw new ArgumentException("请输入 Windows 绝对路径或 HTTP/HTTPS 网址。");
            }
            else if (type == "WindowAction" && Operations.Contains((string)raw["operation"]))
                command = new WindowControlCommand { ChangeWindowStateTo = (WindowControlCommand.WindowOperation)Array.IndexOf(Operations, (string)raw["operation"]) };
            else
            {
                // DTO contains only known scalar fields; no native type metadata.
                var action = raw.ToObject<PortableConfigService.PortableAction>(); action.Enabled = true;
                string reason; command = PortableConfigService.ImportAction(action, out reason);
                if (command == null) throw new ArgumentException(reason);
            }
            var replacement = new OrderableIntent { Name = name, Gesture = gesture, Command = command, Order = (old as OrderableIntent)?.Order ?? profile.GestureIntents.Count };
            if (old != null) profile.Remove(old);
            profile.Add(replacement);
        }

        private void SaveProfile(JObject p)
        {
            var name = ((string)p["name"] ?? "").Trim();
            if (name.Length == 0 || name.Length > 120) throw new ArgumentException("请填写应用名称。");
            var matchers = p["matchers"] as JArray;
            if (matchers == null || matchers.Count != 1 || (string)matchers[0]["type"] != "executable") throw new ArgumentException("请选择程序路径。");
            var path = ((string)matchers[0]["value"] ?? "").Trim();
            if (!Path.IsPathRooted(path) || !path.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)) throw new ArgumentException("请填写 .exe 程序的完整路径。");
            path = Path.GetFullPath(path).ToLowerInvariant();
            var enabled = Boolean(p["enabled"]); var inherit = Boolean(p["inheritGlobal"]);
            var old = p["id"] == null || p["id"].Type == JTokenType.Null ? null : Profile((string)p["id"]) as ExeApp;
            if ((string)p["id"] == "global") throw new ArgumentException("不能替换全局配置。");
            ExeApp duplicate;
            if (controller.IntentStore.TryGetExeApp(path, out duplicate) && duplicate != old) throw new ArgumentException("这个程序已存在应用配置。");
            var app = old == null ? new OrderableExeApp { Order = Apps().Count() } : new OrderableExeApp(old);
            app.Name = name; app.ExecutablePath = path; app.IsGesturingEnabled = enabled; app.InheritGlobalGestures = inherit;
            if (old != null) controller.IntentStore.Remove(old);
            controller.IntentStore.Add(app);
        }

        private static void MoveGesture(AbstractApp app, string id, int delta)
        {
            var items = Intents(app).ToList(); var index = items.IndexOf(Intent(app, id)); var target = index + delta;
            if (Math.Abs(delta) != 1) throw new ArgumentException("移动方向无效。");
            if (target < 0 || target >= items.Count) return;
            var temp = items[index]; items[index] = items[target]; items[target] = temp;
            app.GestureIntents.Clear();
            for (int i = 0; i < items.Count; i++) { var item = new OrderableIntent(items[i]) { Order = i }; app.Add(item); }
        }
        private void MoveProfile(string id, int delta)
        {
            var item = Profile(id) as ExeApp; if (item == null) throw new ArgumentException("不能移动全局配置。");
            var items = Apps().ToList(); var index = items.IndexOf(item); var target = index + delta;
            if (Math.Abs(delta) != 1) throw new ArgumentException("移动方向无效。");
            if (target < 0 || target >= items.Count) return;
            items[index] = items[target]; items[target] = item;
            for (int i = 0; i < items.Count; i++) { controller.IntentStore.Remove(items[i]); controller.IntentStore.Add(new OrderableExeApp(items[i]) { Order = i }); }
        }

        public string Export(string path, string profileId) { return controller.ExportPortableTo(path, Profile(profileId)).ToUserMessage("导出"); }
        public JObject PrepareImport(string path)
        {
            if (new FileInfo(path).Length > 10 * 1024 * 1024) throw new ArgumentException("配置文件不能超过 10 MB。");
            PortableConfigReport report;
            pendingImport = PortableConfigService.Import(path, out report); importToken = Guid.NewGuid().ToString("N");
            return new JObject { ["token"] = importToken, ["message"] = "可导入 " + report.Converted + " 个手势，跳过 " + report.Skipped + " 个。\n\n" + string.Join("\n", report.Warnings) };
        }

        public JObject Recognize(JArray points)
        {
            if (points == null || points.Count < 2 || points.Count > 20000) throw new ArgumentException("请绘制一段有效轨迹。");
            foreach (var point in points)
            {
                if (!(point is JArray) || point.Count() != 2) throw new ArgumentException("轨迹坐标无效。");
                Number(point[0], -100000, 100000, false); Number(point[1], -100000, 100000, false);
            }
            var result = new List<string>(); var x = (double)points[0][0]; var y = (double)points[0][1];
            var mode = controller.GestureParserEnable8DirGesture ? 8 : 4;
            foreach (var point in points.Skip(1))
            {
                var dx = (double)point[0] - x; var dy = (double)point[1] - y;
                if (dx * dx + dy * dy < 144) continue;
                var sector = (int)Math.Floor(Math.Atan2(dy, dx) / (2 * Math.PI / mode) + .5);
                var index = ((sector * (8 / mode) + 2) % 8 + 8) % 8;
                if (result.Count == 0 || result[result.Count - 1] != Directions[index]) result.Add(Directions[index]);
                x = (double)point[0]; y = (double)point[1];
            }
            return new JObject { ["directions"] = new JArray(result) };
        }
    }
}

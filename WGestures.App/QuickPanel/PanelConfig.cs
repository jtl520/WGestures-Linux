using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Newtonsoft.Json;

namespace WGestures.App.QuickPanel
{
    internal static class PanelItemTypes
    {
        public const string Application = "application";
        public const string File = "file";
        public const string Folder = "folder";
        public const string Url = "url";

        public static readonly string[] All = { Application, File, Folder, Url };
    }

    internal sealed class PanelItem
    {
        [JsonProperty("id")]
        public string Id { get; set; }

        [JsonProperty("label")]
        public string Label { get; set; }

        [JsonProperty("type")]
        public string Type { get; set; }

        [JsonProperty("target")]
        public string Target { get; set; }

        [JsonProperty("description", NullValueHandling = NullValueHandling.Ignore)]
        public string Description { get; set; }

        [JsonProperty("arguments", NullValueHandling = NullValueHandling.Ignore)]
        public string Arguments { get; set; }

        [JsonProperty("workingDirectory", NullValueHandling = NullValueHandling.Ignore)]
        public string WorkingDirectory { get; set; }

        [JsonProperty("runAsAdministrator", DefaultValueHandling = DefaultValueHandling.Ignore)]
        public bool RunAsAdministrator { get; set; }

        [JsonProperty("activateIfRunning", DefaultValueHandling = DefaultValueHandling.Ignore)]
        public bool ActivateIfRunning { get; set; }

        [JsonProperty("browser", NullValueHandling = NullValueHandling.Ignore)]
        public string Browser { get; set; }

        public PanelItem Clone()
        {
            return new PanelItem
            {
                Id = Id, Label = Label, Type = Type, Target = Target,
                Description = Description, Arguments = Arguments,
                WorkingDirectory = WorkingDirectory,
                RunAsAdministrator = RunAsAdministrator,
                ActivateIfRunning = ActivateIfRunning, Browser = Browser,
            };
        }
    }

    internal sealed class PanelConfig
    {
        public const int Schema = 1;
        public const int SlotCount = 16;

        [JsonProperty("schemaVersion")]
        public int SchemaVersion { get; set; }

        [JsonProperty("slots")]
        public List<PanelItem> Slots { get; set; }

        public static PanelConfig Empty()
        {
            return new PanelConfig
            {
                SchemaVersion = Schema,
                Slots = Enumerable.Repeat<PanelItem>(null, SlotCount).ToList()
            };
        }

        public static PanelConfig Normalize(PanelConfig source, IList<string> warnings = null)
        {
            if (source == null || source.SchemaVersion != Schema)
                throw new InvalidDataException("不支持的面板配置版本。");
            if (source.Slots == null)
                throw new InvalidDataException("面板 slots 必须是数组。");
            var result = Empty();
            var ids = new HashSet<string>(StringComparer.Ordinal);
            for (var index = 0; index < SlotCount; index++)
            {
                var item = index < source.Slots.Count ? source.Slots[index] : null;
                if (item == null) continue;
                string reason;
                if (!TryValidate(item, out reason))
                {
                    if (warnings != null)
                        warnings.Add("已忽略第 " + (index + 1) + " 个面板格子：" + reason);
                    continue;
                }
                var normalized = item.Clone();
                normalized.Id = (normalized.Id ?? string.Empty).Trim();
                if (normalized.Id.Length == 0 || ids.Contains(normalized.Id))
                    normalized.Id = "slot-" + (index + 1);
                ids.Add(normalized.Id);
                normalized.Type = normalized.Type.Trim();
                normalized.Target = normalized.Target.Trim();
                normalized.Label = (normalized.Label ?? string.Empty).Trim();
                normalized.Description = TrimOrNull(normalized.Description);
                normalized.Arguments = TrimOrNull(normalized.Arguments);
                normalized.WorkingDirectory = TrimOrNull(normalized.WorkingDirectory);
                normalized.Browser = TrimOrNull(normalized.Browser);
                if (normalized.Label.Length == 0)
                    normalized.Label = DefaultLabel(normalized.Type, normalized.Target);
                result.Slots[index] = normalized;
            }
            if (source.Slots.Count != SlotCount && warnings != null)
                warnings.Add("面板格子数量已调整为 16 个。");
            return result;
        }

        private static string TrimOrNull(string value)
        {
            var result = (value ?? string.Empty).Trim();
            return result.Length == 0 ? null : result;
        }

        public static bool TryValidate(PanelItem item, out string reason)
        {
            reason = string.Empty;
            if (item == null || !PanelItemTypes.All.Contains(item.Type))
            {
                reason = "未知动作类型";
                return false;
            }
            var target = (item.Target ?? string.Empty).Trim();
            if (target.Length == 0)
            {
                reason = "目标为空";
                return false;
            }
            if (item.Type == PanelItemTypes.Application || item.Type == PanelItemTypes.File)
            {
                if (!Path.IsPathRooted(target))
                {
                    reason = "文件路径必须是绝对路径";
                    return false;
                }
                if (item.Type == PanelItemTypes.Application)
                {
                    var extension = Path.GetExtension(target);
                    if (!string.Equals(extension, ".exe", StringComparison.OrdinalIgnoreCase) &&
                        !string.Equals(extension, ".lnk", StringComparison.OrdinalIgnoreCase))
                    {
                        reason = "软件目标必须是 EXE 或 Windows 快捷方式";
                        return false;
                    }
                }
            }
            else if (item.Type == PanelItemTypes.Folder)
            {
                if (!Path.IsPathRooted(target))
                {
                    reason = "文件夹路径必须是绝对路径";
                    return false;
                }
            }
            else
            {
                Uri uri;
                if (!Uri.TryCreate(target, UriKind.Absolute, out uri) ||
                    (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps) ||
                    string.IsNullOrWhiteSpace(uri.Host))
                {
                    reason = "网址必须是有效的 HTTP/HTTPS 地址";
                    return false;
                }
            }
            var workingDirectory = (item.WorkingDirectory ?? string.Empty).Trim();
            if (workingDirectory.Length > 0 && !Path.IsPathRooted(workingDirectory))
            {
                reason = "工作目录必须是绝对路径";
                return false;
            }
            var browser = (item.Browser ?? string.Empty).Trim();
            if (browser.Length > 0 && !Path.IsPathRooted(browser))
            {
                reason = "浏览器路径必须是绝对路径";
                return false;
            }
            return true;
        }

        public static string DefaultLabel(string type, string target)
        {
            if (type == PanelItemTypes.Url)
            {
                Uri uri;
                return Uri.TryCreate(target, UriKind.Absolute, out uri) ? uri.Host : target;
            }
            var value = (target ?? string.Empty).TrimEnd(Path.DirectorySeparatorChar,
                Path.AltDirectorySeparatorChar);
            var label = Path.GetFileNameWithoutExtension(value);
            return string.IsNullOrWhiteSpace(label) ? target : label;
        }
    }

    internal sealed class PanelStore
    {
        public string Path { get; private set; }

        public PanelStore(string path = null)
        {
            Path = path ?? AppSettings.PanelConfigFilePath;
        }

        public PanelConfig Load(IList<string> warnings = null)
        {
            var directory = System.IO.Path.GetDirectoryName(Path);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            if (!File.Exists(Path))
            {
                var empty = PanelConfig.Empty();
                Save(empty, false);
                return empty;
            }
            try
            {
                return ReadAndNormalize(Path, warnings);
            }
            catch (Exception primary) when (primary is IOException || primary is JsonException || primary is InvalidDataException)
            {
                var backup = Path + ".bak";
                if (File.Exists(backup))
                {
                    try
                    {
                        var recovered = ReadAndNormalize(backup, warnings);
                        if (warnings != null) warnings.Insert(0, "面板主配置损坏，已从备份恢复：" + primary.Message);
                        Save(recovered, false);
                        return recovered;
                    }
                    catch (Exception) { }
                }
                if (warnings != null) warnings.Add("面板配置损坏，已恢复为空面板：" + primary.Message);
                var empty = PanelConfig.Empty();
                Save(empty, false);
                return empty;
            }
        }

        public void Save(PanelConfig config, bool createBackup = true)
        {
            var normalized = PanelConfig.Normalize(config);
            var directory = System.IO.Path.GetDirectoryName(Path);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            if (createBackup && File.Exists(Path))
            {
                try
                {
                    ReadAndNormalize(Path, null);
                    File.Copy(Path, Path + ".bak.tmp", true);
                    if (File.Exists(Path + ".bak")) File.Delete(Path + ".bak");
                    File.Move(Path + ".bak.tmp", Path + ".bak");
                }
                catch (Exception) { }
            }
            var temporary = Path + ".tmp";
            File.WriteAllText(temporary,
                JsonConvert.SerializeObject(normalized, Formatting.Indented) + Environment.NewLine,
                new UTF8Encoding(false));
            if (File.Exists(Path)) File.Replace(temporary, Path, null);
            else File.Move(temporary, Path);
        }

        private static PanelConfig ReadAndNormalize(string path, IList<string> warnings)
        {
            var source = JsonConvert.DeserializeObject<PanelConfig>(
                File.ReadAllText(path, Encoding.UTF8));
            return PanelConfig.Normalize(source, warnings);
        }
    }
}

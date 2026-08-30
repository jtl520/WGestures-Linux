using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using WGestures.App.QuickPanel;

namespace WGestures.App
{
    internal static class AppSettings
    {
        public static string PanelConfigFilePath { get; set; }
    }
}

internal static class WindowsPanelModelSmoke
{
    private static void Assert(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    public static int Main(string[] args)
    {
        var directory = args.Length == 1 ? args[0] : Path.Combine(
            Path.GetTempPath(), "crossgestures-panel-model-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            var empty = PanelConfig.Empty();
            Assert(empty.SchemaVersion == 1, "schema version must be 1");
            Assert(empty.Slots.Count == 16, "panel must contain exactly 16 slots");

            string reason;
            Assert(PanelConfig.TryValidate(new PanelItem {
                Type = PanelItemTypes.Url, Target = "https://example.com/path" }, out reason),
                "HTTPS URL should be valid");
            Assert(!PanelConfig.TryValidate(new PanelItem {
                Type = PanelItemTypes.Url, Target = "file:///tmp/demo" }, out reason),
                "non-HTTP URL must be rejected");
            Assert(!PanelConfig.TryValidate(new PanelItem {
                Type = PanelItemTypes.File, Target = "relative.txt" }, out reason),
                "relative file must be rejected");
            Assert(PanelConfig.TryValidate(new PanelItem {
                Type = PanelItemTypes.Application, Target = @"C:\Windows\notepad.exe" }, out reason),
                "absolute application path should be valid");
            Assert(!PanelConfig.TryValidate(new PanelItem {
                Type = PanelItemTypes.Application, Target = @"C:\Windows\readme.txt" }, out reason),
                "application must be an EXE or shortcut");
            Assert(PanelConfig.TryValidate(new PanelItem {
                Type = PanelItemTypes.Folder, Target = @"C:\Windows" }, out reason),
                "absolute folder path should be valid");
            var advanced = new PanelItem {
                Id = "advanced", Label = "Notepad", Type = PanelItemTypes.Application,
                Target = @"C:\Windows\notepad.exe", Arguments = "readme.txt",
                WorkingDirectory = @"C:\Windows", RunAsAdministrator = true,
                ActivateIfRunning = true, Description = "Editor" };
            Assert(PanelConfig.TryValidate(advanced, out reason),
                "advanced application options should be valid");
            var advancedCopy = advanced.Clone();
            Assert(advancedCopy.Arguments == "readme.txt" &&
                   advancedCopy.WorkingDirectory == @"C:\Windows" &&
                   advancedCopy.RunAsAdministrator && advancedCopy.ActivateIfRunning,
                "advanced options must survive cloning");

            var oversized = PanelConfig.Empty();
            oversized.Slots.Add(new PanelItem {
                Id = "overflow", Type = PanelItemTypes.Url, Target = "https://example.com" });
            var warnings = new List<string>();
            Assert(PanelConfig.Normalize(oversized, warnings).Slots.Count == 16,
                "oversized panel must be truncated to 16 slots");
            Assert(warnings.Count == 1, "slot correction should be reported");

            var path = Path.Combine(directory, "panel-v1.json");
            var store = new PanelStore(path);
            store.Save(empty, false);
            var changed = PanelConfig.Empty();
            changed.Slots[0] = new PanelItem {
                Id = "web", Label = "Example", Type = PanelItemTypes.Url,
                Target = "https://example.com" };
            store.Save(changed);
            Assert(File.Exists(path + ".bak"), "valid previous config must be backed up");
            File.WriteAllText(path, "{broken", Encoding.UTF8);
            warnings.Clear();
            var recovered = store.Load(warnings);
            Assert(recovered.Slots[0] == null, "load must recover the last valid backup");
            Assert(warnings.Count > 0, "backup recovery must report a warning");

            var unknown = "{\"schemaVersion\":999,\"slots\":[]}";
            File.WriteAllText(path, unknown, Encoding.UTF8);
            File.WriteAllText(path + ".bak", unknown, Encoding.UTF8);
            warnings.Clear();
            recovered = store.Load(warnings);
            Assert(recovered.SchemaVersion == 1 && recovered.Slots.Count == 16,
                "unknown schema without a valid backup must fail closed to an empty panel");

            Console.WriteLine("Windows panel model checks passed.");
            return 0;
        }
        finally
        {
            try { Directory.Delete(directory, true); } catch { }
        }
    }
}

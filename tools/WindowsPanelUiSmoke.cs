using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Windows.Forms;
using WGestures.App.QuickPanel;

namespace WGestures.App
{
    internal static class AppSettings
    {
        public static string PanelConfigFilePath { get; set; }
        public static string UserDataDirectory { get; set; }
    }
}

internal static class WindowsPanelUiSmoke
{
    private static int _state;
    private static bool _dialogOpened;
    private static Exception _failure;
    private static QuickPanelForm _panel;
    private static Timer _timer;
    private static string _directory;

    [STAThread]
    private static int Main()
    {
        var directory = Path.Combine(Path.GetTempPath(),
            "crossgestures-panel-ui-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        _directory = directory;
        WGestures.App.AppSettings.PanelConfigFilePath =
            Path.Combine(directory, "panel-v1.json");
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        CheckResponsiveLayout();
        CheckUrlFaviconHelpers();
        var realShortcut = Environment.GetEnvironmentVariable(
            "CROSSGESTURES_REAL_SHORTCUT");
        if (!string.IsNullOrWhiteSpace(realShortcut))
            CheckRealTargets(realShortcut);
        Application.ThreadException += delegate(object sender, System.Threading.ThreadExceptionEventArgs args)
        {
            _failure = args.Exception;
            Application.Exit();
        };

        _panel = new QuickPanelForm();
        _panel.Shown += delegate
        {
            _timer = new Timer { Interval = 250 };
            _timer.Tick += Tick;
            _timer.Start();
        };
        _panel.FormClosed += delegate { Application.ExitThread(); };
        _panel.ShowAt(new Point(
            Screen.PrimaryScreen.WorkingArea.Left + 500,
            Screen.PrimaryScreen.WorkingArea.Top + 400));
        Application.Run(_panel);

        try { Directory.Delete(directory, true); } catch { }
        if (_failure != null)
        {
            Console.Error.WriteLine(_failure);
            return 2;
        }
        if (!_dialogOpened)
        {
            Console.Error.WriteLine("The first quick-panel create action did not open its editor.");
            return 3;
        }
        Console.WriteLine("Windows panel UI menu/editor/drop checks passed.");
        return 0;
    }

    private static void CheckResponsiveLayout()
    {
        var small = QuickPanelForm.CalculateLayoutScale(new Size(800, 600), 96);
        var standard = QuickPanelForm.CalculateLayoutScale(new Size(1920, 1080), 96);
        var highDpi = QuickPanelForm.CalculateLayoutScale(new Size(3840, 2160), 192);
        if (!(small < 1F && standard > 1F && highDpi > standard))
            throw new InvalidOperationException("Quick-panel monitor scaling is not adaptive.");
    }

    private static void Tick(object sender, EventArgs args)
    {
        try
        {
            if (_state == 3)
            {
                VerifyDrops();
                return;
            }
            if (_state == 0)
            {
                CheckDeferredIconCache();
                var grid = _panel.Controls.OfType<TableLayoutPanel>().Single();
                var button = (Button)grid.Controls[0];
                if (button.Image == null)
                    throw new InvalidOperationException(
                        "An empty tile must show the plus affordance icon.");
                if (_panel.TooltipFor(button) != "右键新建格子，或把文件拖进来")
                    throw new InvalidOperationException(
                        "An empty tile must carry the create hint tooltip.");
                var tooltip = typeof(QuickPanelForm).GetMethod(
                    "TileTooltip", BindingFlags.Static | BindingFlags.NonPublic);
                var described = tooltip.Invoke(null, new object[] {
                    new PanelItem {
                        Type = PanelItemTypes.Url, Target = "https://example.com",
                        Description = "Example site",
                    },
                });
                if ((string)described != "Example site")
                    throw new InvalidOperationException(
                        "The description must win over the target in the tile tooltip.");
                var fallback = tooltip.Invoke(null, new object[] {
                    new PanelItem { Type = PanelItemTypes.Url, Target = "https://example.com" },
                });
                if ((string)fallback != "打开网址：https://example.com")
                    throw new InvalidOperationException(
                        "A tile without a description must fall back to type and target.");
                var handler = typeof(QuickPanelForm).GetMethod(
                    "TileMouseUp", BindingFlags.Instance | BindingFlags.NonPublic);
                Cursor.Position = button.PointToScreen(
                    new Point(button.Width / 2, button.Height / 2));
                handler.Invoke(_panel, new object[] {
                    button,
                    new MouseEventArgs(MouseButtons.Right, 1,
                        button.Width / 2, button.Height / 2, 0),
                });
                _state++;
                return;
            }
            if (_state == 1)
            {
                var menu = _panel.ActiveItemMenu;
                if (menu == null || menu.Items.Count != 4)
                    throw new InvalidOperationException(
                        "An empty tile must expose exactly four create actions.");
                var expected = new[] { "启动软件", "打开文件", "打开文件夹", "打开网址" };
                for (var index = 0; index < expected.Length; index++)
                {
                    if (menu.Items[index].Text != expected[index])
                        throw new InvalidOperationException(
                            "Unexpected create action at index " + index + ".");
                }
                ((ToolStripMenuItem)menu.Items[0]).PerformClick();
                _state++;
                return;
            }

            var dialog = Application.OpenForms.Cast<Form>()
                .FirstOrDefault(form => form.Text == "添加格子");
            if (dialog != null)
            {
                _dialogOpened = true;
                if (!_panel.Editing)
                    throw new InvalidOperationException(
                        "The panel must report the editing state while a slot editor is open.");
                dialog.DialogResult = DialogResult.Cancel;
                dialog.Close();
                foreach (var stray in Application.OpenForms.Cast<Form>().Where(
                        form => form.Text == "选择应用程序").ToArray())
                {
                    stray.DialogResult = DialogResult.Cancel;
                    stray.Close();
                }
                _state++;
                return;
            }
            if (_state++ > 12)
            {
                _timer.Stop();
                _panel.Close();
            }
        }
        catch (TargetInvocationException error)
        {
            _failure = error.InnerException ?? error;
            _timer.Stop();
            _panel.Close();
        }
        catch (Exception error)
        {
            _failure = error;
            _timer.Stop();
            _panel.Close();
        }
    }

    private static void CheckUrlFaviconHelpers()
    {
        WGestures.App.AppSettings.UserDataDirectory = Path.Combine(
            Path.GetTempPath(), "crossgestures-favicon-" + Guid.NewGuid().ToString("N"));
        if (UrlFavicon.HostOf("https://Example.COM/x") != "example.com")
            throw new InvalidOperationException(
                "The favicon host must be normalized to lowercase.");
        if (UrlFavicon.FaviconUrl("https://example.com/a")
                != "https://example.com/favicon.ico")
            throw new InvalidOperationException(
                "The favicon URL must point at the target site directly.");
        var candidates = UrlFavicon.CandidateUrls("https://example.com/a");
        if (candidates.Length != 2 ||
            candidates[0] != "https://example.com/favicon.ico" ||
            !candidates[1].StartsWith(
                "https://www.google.com/s2/favicons?domain=example.com&",
                StringComparison.Ordinal))
            throw new InvalidOperationException(
                "A blocked direct favicon needs the compatibility fallback.");
        byte[] png;
        using (var sample = new Bitmap(8, 8))
        using (var buffer = new MemoryStream())
        {
            sample.Save(buffer, System.Drawing.Imaging.ImageFormat.Png);
            png = buffer.ToArray();
        }
        if (UrlFavicon.ValidateFaviconBytes(png) == null)
            throw new InvalidOperationException("A PNG payload must validate.");
        if (UrlFavicon.ValidateFaviconBytes(
                System.Text.Encoding.ASCII.GetBytes("<html>" + new string('0', 40)))
                != null)
            throw new InvalidOperationException("HTML must not validate as an icon.");
        if (UrlFavicon.ValidateFaviconBytes(
                new byte[] { 0x89, 0x50, 0x4E, 0x47 }) != null)
            throw new InvalidOperationException("Tiny payloads must be rejected.");

        var path = UrlFavicon.CachePathFor("https://cached.com/");
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        File.WriteAllBytes(path, png);
        Image image;
        if (!UrlFavicon.TryGetCachedImage("https://cached.com/", 40, out image) ||
            image == null)
            throw new InvalidOperationException(
                "A cached favicon must produce a tile image.");
        image.Dispose();
        File.WriteAllBytes(path, new byte[] { 1, 2, 3 });
        if (UrlFavicon.TryGetCachedImage("https://cached.com/", 40, out image))
            throw new InvalidOperationException(
                "A corrupt favicon cache must be rejected and removed.");
        if (File.Exists(path))
            throw new InvalidOperationException(
                "A corrupt favicon cache file must be deleted.");
    }

    private static void CheckDeferredIconCache()
    {
        var target = "https://not-cached.invalid/";
        var key = PanelItemTypes.Url + "|" + target + "|40";
        var iconFor = typeof(QuickPanelForm).GetMethod(
            "IconFor", BindingFlags.Instance | BindingFlags.NonPublic);
        var fallback = iconFor.Invoke(_panel, new object[] {
            new PanelItem { Type = PanelItemTypes.Url, Target = target }, 40,
        });
        if (fallback == null)
            throw new InvalidOperationException("A missing favicon needs an immediate fallback.");
        var cache = (System.Collections.IDictionary)typeof(QuickPanelForm).GetField(
            "IconCache", BindingFlags.Static | BindingFlags.NonPublic).GetValue(null);
        if (cache.Contains(key))
            throw new InvalidOperationException(
                "A temporary URL fallback must not hide a favicon that arrives later.");
    }

    private static void CheckRealTargets(string shortcutPath)
    {
        var resolver = typeof(QuickPanelForm).GetMethod(
            "ResolveShortcutTarget", BindingFlags.Static | BindingFlags.NonPublic);
        var resolved = (string)resolver.Invoke(null, new object[] { shortcutPath });
        if (string.IsNullOrWhiteSpace(resolved) || !File.Exists(resolved))
            throw new InvalidOperationException(
                "The real shortcut did not resolve to a live executable: " + resolved);
        Console.WriteLine("Resolved real shortcut: " + resolved);
        var extractor = typeof(QuickPanelForm).GetMethod(
            "ExtractShellIcon", BindingFlags.Static | BindingFlags.NonPublic);
        using (var extracted = (Image)extractor.Invoke(null, new object[]
        {
            new PanelItem
            {
                Type = PanelItemTypes.Application,
                Target = shortcutPath,
            },
            100,
        }))
        {
            if (extracted == null)
                throw new InvalidOperationException(
                    "The real shortcut did not yield an application icon.");
            var iconResult = Environment.GetEnvironmentVariable(
                "CROSSGESTURES_REAL_ICON_RESULT");
            if (!string.IsNullOrWhiteSpace(iconResult))
                extracted.Save(iconResult, System.Drawing.Imaging.ImageFormat.Png);
        }

        var completed = new System.Threading.ManualResetEventSlim(false);
        var succeeded = false;
        UrlFavicon.FetchAsync("https://chatgpt.com/", result =>
        {
            succeeded = result;
            completed.Set();
        });
        if (!completed.Wait(TimeSpan.FromSeconds(15)) || !succeeded)
            throw new InvalidOperationException(
                "The real chatgpt.com favicon fallback did not complete.");
        Image image;
        if (!UrlFavicon.TryGetCachedImage("https://chatgpt.com/", 100, out image) ||
            image == null)
            throw new InvalidOperationException(
                "The downloaded chatgpt.com favicon could not be rendered.");
        image.Dispose();
        Console.WriteLine("Downloaded and rendered real chatgpt.com favicon.");
    }

    private static void SavePanelShot()
    {
        try
        {
            var bounds = _panel.Bounds;
            using (var bitmap = new Bitmap(bounds.Width, bounds.Height))
            {
                using (var graphics = Graphics.FromImage(bitmap))
                    graphics.CopyFromScreen(bounds.Location, Point.Empty, bounds.Size);
                bitmap.Save(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,
                    "panel-tiles.png"), System.Drawing.Imaging.ImageFormat.Png);
            }
        }
        catch { }
    }

    private static void VerifyDrops()
    {
        var folder = Path.Combine(_directory, "dropped-folder");
        Directory.CreateDirectory(folder);
        var file = Path.Combine(_directory, "dropped.txt");
        File.WriteAllText(file, "demo");
        var application = Path.Combine(_directory, "dropped.exe");
        File.WriteAllText(application, "demo");

        var tileBefore = _panel.Controls.OfType<TableLayoutPanel>().Single()
            .GetControlFromPosition(0, 0);
        _panel.HandleTileDrop(0, new[] { folder, file, application });

        var store = new PanelStore(WGestures.App.AppSettings.PanelConfigFilePath);
        var loaded = store.Load().Slots;
        if (loaded[0] == null || loaded[0].Type != PanelItemTypes.Folder ||
            loaded[0].Target != folder)
            throw new InvalidOperationException(
                "A dropped folder must fill the drop slot as a folder item.");
        if (loaded[1] == null || loaded[1].Type != PanelItemTypes.File ||
            loaded[1].Target != file)
            throw new InvalidOperationException(
                "Additional dropped files must fill the following free slots.");
        if (loaded[2] == null || loaded[2].Type != PanelItemTypes.Application ||
            loaded[2].WorkingDirectory != _directory)
            throw new InvalidOperationException(
                "A dropped executable must become an application with its working directory.");

        var grid = _panel.Controls.OfType<TableLayoutPanel>().Single();
        var first = (Button)grid.GetControlFromPosition(0, 0);
        var third = (Button)grid.GetControlFromPosition(2, 0);
        if (!ReferenceEquals(first, tileBefore))
            throw new InvalidOperationException(
                "Tiles must be persistent controls, not rebuilt on every update.");
        if (first.Text != loaded[0].Label || first.Image == null)
            throw new InvalidOperationException(
                "The tile grid must show the dropped folder item after the drop.");
        if ((third.Text ?? string.Empty) != loaded[2].Label)
            throw new InvalidOperationException(
                "The tile grid must show the dropped application label.");
        if (_panel.TooltipFor(third) != "启动软件：" + application)
            throw new InvalidOperationException(
                "A configured tile must show its type and target as the tooltip.");

        var folderImageBefore = first.Image;
        typeof(QuickPanelForm).GetMethod("UpdateTiles",
            BindingFlags.Instance | BindingFlags.NonPublic).Invoke(_panel, null);
        if (!ReferenceEquals(first.Image, folderImageBefore))
            throw new InvalidOperationException(
                "Tile icons must come from the cache and stay identical across updates.");

        var shellIconMethod = typeof(QuickPanelForm).GetMethod(
            "GetShellIconHandle", BindingFlags.Static | BindingFlags.NonPublic);
        var shellIcon = IntPtr.Zero;
        for (var attempt = 0; attempt < 3 && shellIcon == IntPtr.Zero; attempt++)
        {
            shellIcon = (IntPtr)shellIconMethod.Invoke(
                null, new object[] { folder, true });
            if (shellIcon == IntPtr.Zero) System.Threading.Thread.Sleep(80);
        }
        if (shellIcon == IntPtr.Zero)
            throw new InvalidOperationException(
                "Folders must get the real shell folder icon, not a fallback.");

        var before = store.Load().Slots.Count(slot => slot != null);
        _panel.HandleTileDrop(0, new[] { file });
        var after = store.Load().Slots.Count(slot => slot != null);
        if (before != 3 || after != 3)
            throw new InvalidOperationException(
                "Dropping onto an occupied slot must not change the configuration.");

        SavePanelShot();
        _timer.Stop();
        _panel.Close();
    }
}

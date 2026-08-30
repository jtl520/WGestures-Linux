using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace WGestures.App.QuickPanel
{
    internal sealed class QuickPanelForm : Form
    {
        private readonly PanelStore _store = new PanelStore();
        private readonly TableLayoutPanel _grid = new TableLayoutPanel();
        private readonly ToolTip _tooltip = new ToolTip();
        private readonly Button[] _tiles = new Button[PanelConfig.SlotCount];
        // 图标与空格子加号按 (类型|目标|尺寸) 缓存，避免每次弹出面板重复
        // 提取 shell 图标导致显示迟滞。缓存条目数量有限，常驻不释放。
        private static readonly Dictionary<string, Image> IconCache =
            new Dictionary<string, Image>(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> _iconLoads =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> _faviconFetches =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private PanelConfig _config;
        private DateTime _configStamp;
        private bool _editing;
        private bool _menuActionPending;
        private bool _tilesDirty = true;
        private bool _panelVisible;
        private bool _nativeWindowShownOnce;
        private bool _priming;
        private int _shownTicks = Environment.TickCount - 100_000;
        private float _scale = 1F;
        private uint _appliedDpi;
        private Size _appliedWorkingAreaSize;

        private const int LogicalWidth = 464;
        private const int LogicalHeight = 416;

        public event Action<bool> PanelVisibilityChanged;
        public Action<string> NotifyError { get; set; }
        internal ContextMenuStrip ActiveItemMenu { get; private set; }
        private readonly Timer _focusWatch = new Timer();

        /// <summary>面板右键菜单是否处于打开状态（可从钩子线程读取）。</summary>
        internal bool MenuActive { get { return ActiveItemMenu != null; } }

        /// <summary>
        /// 编辑对话框/右键菜单打开期间为真（可从钩子线程读取）。此状态下
        /// 面板表面的右键/X 键不再让给格子，手势在对话框输入框中照常可用。
        /// </summary>
        internal bool Editing { get { return _editing || _menuActionPending; } }

        public QuickPanelForm()
        {
            AutoScaleMode = AutoScaleMode.None;
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.Manual;
            ShowInTaskbar = false;
            TopMost = true;
            KeyPreview = true;
            DoubleBuffered = true;
            ClientSize = new Size(LogicalWidth, LogicalHeight);
            Padding = new Padding(12);
            BackColor = Color.FromArgb(42, 48, 58);
            Font = SystemFonts.MessageBoxFont;

            _grid.Dock = DockStyle.Fill;
            _grid.ColumnCount = 4;
            _grid.RowCount = 4;
            for (var index = 0; index < 4; index++)
            {
                _grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 25));
                _grid.RowStyles.Add(new RowStyle(SizeType.Percent, 25));
            }
            for (var index = 0; index < PanelConfig.SlotCount; index++)
            {
                _tiles[index] = CreateTile(index);
                _grid.Controls.Add(_tiles[index], index % 4, index / 4);
            }
            Controls.Add(_grid);
            // 失焦自动收起依赖 Deactivate 事件；截图工具等全屏覆盖层可能
            // 吞掉失焦通知。加一个低频看门狗：可见且非编辑状态、失焦超过
            // 一小段宽限时间仍未收回时强制收起。
            _focusWatch.Interval = 500;
            _focusWatch.Tick += delegate
            {
                if (!_panelVisible || _editing || _menuActionPending) return;
                if (Environment.TickCount - _shownTicks < 3000) return;
                if (!ContainsFocus) ClosePanel();
            };
            Deactivate += delegate
            {
                if (!_editing) BeginInvoke(new Action(CloseIfInactive));
            };
            KeyDown += delegate(object sender, KeyEventArgs args)
            {
                if (args.KeyCode == Keys.Escape)
                {
                    args.Handled = true;
                    ClosePanel();
                }
            };
        }

        protected override bool ShowWithoutActivation { get { return _priming; } }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _tooltip.Dispose();
                _focusWatch.Dispose();
            }
            base.Dispose(disposing);
        }

        public void ToggleAt(Point point)
        {
            Trace.WriteLine("CrossGestures quick panel toggle on UI thread: visible=" + _panelVisible);
            if (_panelVisible) ClosePanel();
            else ShowAt(point);
        }

        /// <summary>
        /// Create the high-DPI native surface and start icon loading before the
        /// first middle click. The no-activate, off-screen show prevents the
        /// 130-200 ms DWM allocation cost from appearing in user interaction.
        /// </summary>
        public void Prime(Point point)
        {
            if (_nativeWindowShownOnce || IsDisposed) return;
            ReloadConfigIfChanged();
            ApplyDpiForPoint(point);
            if (_tilesDirty) UpdateTiles();
            var desktop = SystemInformation.VirtualScreen;
            Location = new Point(desktop.Left - Width - 128,
                desktop.Top - Height - 128);
            _priming = true;
            try
            {
                Show();
                _nativeWindowShownOnce = true;
                NativeMethods.ShowWindow(Handle, ShowWindowCommands.Hide);
            }
            finally
            {
                _priming = false;
                _panelVisible = false;
            }
            Trace.WriteLine("CrossGestures quick panel primed: size=" + Size +
                            ", dpi=" + _appliedDpi);
        }

        public void ShowAt(Point point)
        {
            var timer = Stopwatch.StartNew();
            var warnings = ReloadConfigIfChanged();
            var configMs = timer.ElapsedMilliseconds;
            ApplyDpiForPoint(point);
            var dpiMs = timer.ElapsedMilliseconds - configMs;
            if (_tilesDirty) UpdateTiles();
            var tilesMs = timer.ElapsedMilliseconds - configMs - dpiMs;
            _shownTicks = Environment.TickCount;
            _focusWatch.Start();
            var area = Screen.FromPoint(point).WorkingArea;
            var left = Math.Max(area.Left, Math.Min(point.X - Width / 2, area.Right - Width));
            var top = Math.Max(area.Top, Math.Min(point.Y - Height / 2, area.Bottom - Height));
            Location = new Point(left, top);
            _panelVisible = true;
            if (!_nativeWindowShownOnce)
            {
                Show();
                _nativeWindowShownOnce = true;
            }
            else NativeMethods.ShowWindow(Handle, ShowWindowCommands.Show);
            var showMs = timer.ElapsedMilliseconds - configMs - dpiMs - tilesMs;
            Activate();
            Trace.WriteLine("CrossGestures quick panel shown: bounds=" + Bounds +
                            " in " + timer.ElapsedMilliseconds + "ms" +
                            " (config=" + configMs + ", dpi=" + dpiMs +
                            ", tiles=" + tilesMs + ", show=" + showMs + ")");
            var changed = PanelVisibilityChanged;
            if (changed != null) changed(true);
            foreach (var warning in warnings) ReportError(warning);
        }

        public void ClosePanel()
        {
            _focusWatch.Stop();
            if (!_panelVisible) return;
            _panelVisible = false;
            if (_nativeWindowShownOnce && IsHandleCreated)
                NativeMethods.ShowWindow(Handle, ShowWindowCommands.Hide);
            else Hide();
            Trace.WriteLine("CrossGestures quick panel hidden");
            var changed = PanelVisibilityChanged;
            if (changed != null) changed(false);
        }

        private List<string> ReloadConfigIfChanged()
        {
            var stamp = File.Exists(_store.Path)
                ? File.GetLastWriteTimeUtc(_store.Path)
                : DateTime.MinValue;
            if (_config != null && stamp == _configStamp)
                return new List<string>();
            var warnings = new List<string>();
            _config = _store.Load(warnings);
            _tilesDirty = true;
            _configStamp = File.Exists(_store.Path)
                ? File.GetLastWriteTimeUtc(_store.Path)
                : stamp;
            return warnings;
        }

        private Button CreateTile(int index)
        {
            var button = new Button
            {
                Dock = DockStyle.Fill,
                Margin = new Padding(ScaleLogical(4)),
                Tag = index,
                Text = string.Empty,
                TextImageRelation = TextImageRelation.ImageAboveText,
                ImageAlign = ContentAlignment.MiddleCenter,
                TextAlign = ContentAlignment.BottomCenter,
                FlatStyle = FlatStyle.Flat,
                ForeColor = Color.White,
                BackColor = Color.FromArgb(62, 70, 83),
                Image = PlusIcon(ScaleLogical(40)),
            };
            button.FlatAppearance.BorderSize = 0;
            _tooltip.SetToolTip(button, TileTooltip(null));
            button.AllowDrop = true;
            button.DragEnter += TileDragEnter;
            button.DragDrop += TileDragDrop;
            button.MouseUp += TileMouseUp;
            return button;
        }

        private void UpdateTiles()
        {
            if (_config == null) return;
            _grid.SuspendLayout();
            try
            {
                var size = ScaleLogical(40);
                for (var index = 0; index < PanelConfig.SlotCount; index++)
                {
                    var item = _config.Slots[index];
                    var button = _tiles[index];
                    button.Text = item == null ? string.Empty : item.Label;
                    button.Image = item == null ? PlusIcon(size) : IconFor(item, size);
                    _tooltip.SetToolTip(button, TileTooltip(item));
                }
            }
            finally { _grid.ResumeLayout(true); }
            _tilesDirty = false;
        }

        private void TileMouseUp(object sender, MouseEventArgs e)
        {
            var button = (Button)sender;
            var index = (int)button.Tag;
            var item = _config.Slots[index];
            if (e.Button == MouseButtons.Right)
            {
                ShowItemMenu(button, index, item);
                return;
            }
            if (e.Button == MouseButtons.Left && item != null)
            {
                ClosePanel();
                Execute(item);
            }
        }

        private void TileDragEnter(object sender, DragEventArgs e)
        {
            e.Effect = e.Data.GetDataPresent(DataFormats.FileDrop) &&
                       e.Data.GetData(DataFormats.FileDrop) is string[] paths &&
                       paths.Length > 0
                ? DragDropEffects.Copy
                : DragDropEffects.None;
        }

        private void TileDragDrop(object sender, DragEventArgs e)
        {
            var paths = e.Data.GetData(DataFormats.FileDrop) as string[];
            HandleTileDrop((int)((Control)sender).Tag, paths);
        }

        internal void HandleTileDrop(int index, IList<string> paths)
        {
            if (_config == null || paths == null || paths.Count == 0) return;
            if (_config.Slots[index] != null)
            {
                ReportError("第 " + (index + 1) + " 个格子已配置：请先右键删除，或拖到空格子。");
                return;
            }
            var slot = index;
            foreach (var path in paths)
            {
                while (slot < PanelConfig.SlotCount && _config.Slots[slot] != null) slot++;
                if (slot >= PanelConfig.SlotCount)
                {
                    ReportError("没有更多空格子可以放置拖入的目标。");
                    break;
                }
                var item = ItemForDroppedPath(path);
                if (item == null)
                {
                    ReportError("无法识别拖入的目标：" + path);
                    continue;
                }
                _config.Slots[slot] = item;
                slot++;
            }
            _store.Save(_config);
            _tilesDirty = true;
            UpdateTiles();
        }

        private static PanelItem ItemForDroppedPath(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) return null;
            var extension = Path.GetExtension(path);
            var application = string.Equals(extension, ".exe", StringComparison.OrdinalIgnoreCase) ||
                              string.Equals(extension, ".lnk", StringComparison.OrdinalIgnoreCase);
            var type = Directory.Exists(path) ? PanelItemTypes.Folder
                : application ? PanelItemTypes.Application
                : File.Exists(path) ? PanelItemTypes.File : null;
            if (type == null) return null;
            var item = new PanelItem
            {
                Id = Guid.NewGuid().ToString("N"),
                Type = type,
                Target = path,
            };
            if (type == PanelItemTypes.Application)
            {
                var directory = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(directory)) item.WorkingDirectory = directory;
            }
            string reason;
            if (!PanelConfig.TryValidate(item, out reason)) return null;
            if (string.IsNullOrWhiteSpace(item.Label))
                item.Label = PanelConfig.DefaultLabel(item.Type, item.Target);
            return item;
        }

        private void ShowItemMenu(Control owner, int index, PanelItem item)
        {
            var menu = new ContextMenuStrip();
            if (item == null)
            {
                AddCreateMenuItem(menu, index, "启动软件", PanelItemTypes.Application);
                AddCreateMenuItem(menu, index, "打开文件", PanelItemTypes.File);
                AddCreateMenuItem(menu, index, "打开文件夹", PanelItemTypes.Folder);
                AddCreateMenuItem(menu, index, "打开网址", PanelItemTypes.Url);
            }
            else
            {
                var edit = new ToolStripMenuItem("编辑");
                edit.Click += delegate { RunAfterMenuClosed(menu, delegate { EditItem(index); }); };
                menu.Items.Add(edit);
                var delete = new ToolStripMenuItem("删除");
                delete.Click += delegate { RunAfterMenuClosed(menu, delegate
                {
                    _config.Slots[index] = null;
                    _store.Save(_config);
                    _tilesDirty = true;
                    UpdateTiles();
                }); };
                menu.Items.Add(delete);
            }
            _editing = true;
            ActiveItemMenu = menu;
            menu.Closed += delegate
            {
                _editing = false;
                // ToolStrip's modal filter still references the drop-down
                // during Closed. Disposing it synchronously can crash later
                // when a modal editor or settings window changes activation.
                BeginInvoke(new Action(delegate
                {
                    if (!menu.IsDisposed) menu.Dispose();
                    if (ReferenceEquals(ActiveItemMenu, menu)) ActiveItemMenu = null;
                    if (!_menuActionPending) CloseIfInactive();
                }));
            };
            menu.Show(owner, owner.PointToClient(Cursor.Position));
            Trace.WriteLine("CrossGestures quick panel context menu shown: slot=" + index +
                            ", items=" + menu.Items.Count);
        }

        private void AddCreateMenuItem(
            ContextMenuStrip menu, int index, string text, string type)
        {
            var create = new ToolStripMenuItem(text);
            create.Click += delegate
            {
                RunAfterMenuClosed(menu, delegate { EditItem(index, type); });
            };
            menu.Items.Add(create);
        }

        private void RunAfterMenuClosed(ContextMenuStrip menu, Action action)
        {
            _menuActionPending = true;
            menu.Close();
            BeginInvoke(new Action(delegate
            {
                try { action(); }
                finally { _menuActionPending = false; }
            }));
        }

        private void CloseIfInactive()
        {
            if (_panelVisible && !_editing && !_menuActionPending && !ContainsFocus)
                ClosePanel();
        }

        private void EditItem(int index, string initialType = null)
        {
            _editing = true;
            try
            {
                using (var dialog = new PanelItemDialog(_config.Slots[index], initialType))
                {
                    if (dialog.ShowDialog(this) != DialogResult.OK) return;
                    _config.Slots[index] = dialog.DeleteRequested ? null : dialog.ResultItem;
                    _store.Save(_config);
                    _tilesDirty = true;
                    UpdateTiles();
                }
            }
            finally
            {
                _editing = false;
                if (_panelVisible) Activate();
            }
        }

        private void Execute(PanelItem item)
        {
            try
            {
                string reason;
                if (!PanelConfig.TryValidate(item, out reason)) throw new InvalidDataException(reason);
                if ((item.Type == PanelItemTypes.Application || item.Type == PanelItemTypes.File) &&
                    !File.Exists(item.Target)) throw new FileNotFoundException("目标文件不存在", item.Target);
                if (item.Type == PanelItemTypes.Folder && !Directory.Exists(item.Target))
                    throw new DirectoryNotFoundException("目标文件夹不存在：" + item.Target);
                if (item.Type == PanelItemTypes.Application && item.ActivateIfRunning &&
                    TryActivateRunningApplication(item.Target)) return;
                var target = item.Type == PanelItemTypes.Url && !string.IsNullOrWhiteSpace(item.Browser)
                    ? item.Browser : item.Target;
                var info = new ProcessStartInfo(target) { UseShellExecute = true };
                if (item.Type == PanelItemTypes.Application)
                {
                    info.Arguments = item.Arguments ?? string.Empty;
                    if (!string.IsNullOrWhiteSpace(item.WorkingDirectory))
                        info.WorkingDirectory = item.WorkingDirectory;
                    if (item.RunAsAdministrator) info.Verb = "runas";
                }
                else if (item.Type == PanelItemTypes.Url && !string.IsNullOrWhiteSpace(item.Browser))
                {
                    info.Arguments = QuoteArgument(item.Target);
                }
                using (var process = Process.Start(info)) { }
            }
            catch (Exception error)
            {
                ReportError("无法启动“" + item.Label + "”：" + error.Message);
            }
        }

        private static string QuoteArgument(string value)
        {
            return "\"" + (value ?? string.Empty).Replace("\"", "\\\"") + "\"";
        }

        private static bool TryActivateRunningApplication(string target)
        {
            var executable = ResolveShortcutTarget(target) ?? target;
            var processName = Path.GetFileNameWithoutExtension(executable);
            if (string.IsNullOrWhiteSpace(processName)) return false;
            foreach (var process in Process.GetProcessesByName(processName))
            {
                using (process)
                {
                    var window = process.MainWindowHandle;
                    if (window == IntPtr.Zero) continue;
                    NativeMethods.ShowWindow(window, 9);
                    if (NativeMethods.SetForegroundWindow(window)) return true;
                }
            }
            return false;
        }

        private static string ResolveShortcutTarget(string path)
        {
            if (!string.Equals(Path.GetExtension(path), ".lnk", StringComparison.OrdinalIgnoreCase))
                return null;
            var direct = ReadShortcutTarget(path);
            if (!string.IsNullOrWhiteSpace(direct) && File.Exists(direct)) return direct;

            // A copied desktop shortcut can outlive an application update or
            // directory rename. Match the shortcut name against the current
            // user/common Start Menu and use its live target. This fixes stale
            // links such as 微信.lnk (D:\WeChat) after Weixin moved to D:\Weixin.
            var name = Path.GetFileName(path);
            string bestTarget = null;
            var bestScore = int.MaxValue;
            foreach (var root in new[]
            {
                Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
                Environment.GetFolderPath(Environment.SpecialFolder.CommonStartMenu),
            })
            {
                if (string.IsNullOrWhiteSpace(root) || !Directory.Exists(root)) continue;
                try
                {
                    foreach (var candidate in Directory.EnumerateFiles(
                        root, name, SearchOption.AllDirectories))
                    {
                        var current = ReadShortcutTarget(candidate);
                        if (!string.IsNullOrWhiteSpace(current) && File.Exists(current))
                        {
                            var score = ShortcutTargetDistance(direct, current);
                            if (score < bestScore)
                            {
                                bestTarget = current;
                                bestScore = score;
                            }
                        }
                    }
                }
                catch (Exception) { }
            }
            return bestTarget ?? direct;
        }

        private static int ShortcutTargetDistance(string staleTarget, string candidateTarget)
        {
            var expected = Path.GetFileNameWithoutExtension(staleTarget ?? string.Empty)
                .ToLowerInvariant();
            var actual = Path.GetFileNameWithoutExtension(candidateTarget ?? string.Empty)
                .ToLowerInvariant();
            if (expected.Length == 0 || actual.Length == 0) return int.MaxValue - 1;
            var previous = Enumerable.Range(0, actual.Length + 1).ToArray();
            for (var row = 1; row <= expected.Length; row++)
            {
                var current = new int[actual.Length + 1];
                current[0] = row;
                for (var column = 1; column <= actual.Length; column++)
                {
                    var substitution = previous[column - 1] +
                        (expected[row - 1] == actual[column - 1] ? 0 : 1);
                    current[column] = Math.Min(Math.Min(
                        previous[column] + 1, current[column - 1] + 1), substitution);
                }
                previous = current;
            }
            return previous[actual.Length];
        }

        private static string ReadShortcutTarget(string path)
        {
            object shell = null;
            object shortcut = null;
            try
            {
                var shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType == null) return null;
                shell = Activator.CreateInstance(shellType);
                shortcut = shellType.InvokeMember("CreateShortcut",
                    System.Reflection.BindingFlags.InvokeMethod, null, shell,
                    new object[] { path });
                return shortcut == null ? null : Convert.ToString(shortcut.GetType().InvokeMember(
                    "TargetPath", System.Reflection.BindingFlags.GetProperty,
                    null, shortcut, null));
            }
            catch (Exception) { return null; }
            finally
            {
                if (shortcut != null && Marshal.IsComObject(shortcut)) Marshal.FinalReleaseComObject(shortcut);
                if (shell != null && Marshal.IsComObject(shell)) Marshal.FinalReleaseComObject(shell);
            }
        }

        private void ReportError(string message)
        {
            var notify = NotifyError;
            if (notify != null) notify(message);
        }

        internal string TooltipFor(Control control)
        {
            return _tooltip.GetToolTip(control);
        }

        private static string TileTooltip(PanelItem item)
        {
            if (item == null) return "右键新建格子，或把文件拖进来";
            if (!string.IsNullOrWhiteSpace(item.Description)) return item.Description;
            var label = item.Type == PanelItemTypes.Application ? "启动软件"
                : item.Type == PanelItemTypes.File ? "打开文件"
                : item.Type == PanelItemTypes.Folder ? "打开文件夹"
                : "打开网址";
            return label + "：" + item.Target;
        }

        private static Bitmap PlusIcon(int size)
        {
            lock (IconCache)
            {
                Image cached;
                if (IconCache.TryGetValue("plus|" + size, out cached))
                    return (Bitmap)cached;
                var bitmap = new Bitmap(size, size);
                using (var graphics = Graphics.FromImage(bitmap))
                {
                    graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                    using (var pen = new Pen(Color.FromArgb(150, 255, 255, 255), Math.Max(2f, size / 10f)))
                    {
                        var middle = size / 2f;
                        var inset = size / 4f;
                        graphics.DrawLine(pen, inset, middle, size - inset, middle);
                        graphics.DrawLine(pen, middle, inset, middle, size - inset);
                    }
                }
                IconCache["plus|" + size] = bitmap;
                return bitmap;
            }
        }

        private Image IconFor(PanelItem item, int size)
        {
            var key = item.Type + "|" + item.Target + "|" + size;
            lock (IconCache)
            {
                Image cached;
                if (IconCache.TryGetValue(key, out cached)) return cached;
            }
            if (item.Type == PanelItemTypes.Url)
            {
                Image favicon;
                if (UrlFavicon.TryGetCachedImage(item.Target, size, out favicon))
                {
                    lock (IconCache) IconCache[key] = favicon;
                    return favicon;
                }
                RequestFavicon(item.Target);
            }
            else
            {
                QueueIconLoad(item, size);
            }
            // Shell icon extraction can block on shortcut handlers or network
            // locations. Never perform it on the UI path: show a stable fallback
            // immediately, then replace it when the background load completes.
            return FallbackIcon(item.Type, size);
        }

        private static Image FallbackIcon(string type, int size)
        {
            var key = "fallback|" + type + "|" + size;
            lock (IconCache)
            {
                Image cached;
                if (IconCache.TryGetValue(key, out cached)) return cached;
            }
            var fallback = type == PanelItemTypes.Folder ? SystemIcons.WinLogo
                : type == PanelItemTypes.Url ? SystemIcons.Information : SystemIcons.Application;
            var image = new Bitmap(fallback.ToBitmap(), new Size(size, size));
            lock (IconCache) IconCache[key] = image;
            return image;
        }

        private void QueueIconLoad(PanelItem item, int size)
        {
            var key = item.Type + "|" + item.Target + "|" + size;
            lock (_iconLoads)
            {
                if (!_iconLoads.Add(key)) return;
            }
            var snapshot = item.Clone();
            // Shortcut resolution uses WScript.Shell COM. Task.Run uses an MTA
            // worker where that shell object intermittently fails and leaves us
            // with the generic .lnk icon. Use a short-lived STA worker instead.
            var worker = new System.Threading.Thread(
                new System.Threading.ThreadStart(delegate
                {
                    try { LoadIconIntoCache(snapshot, size); }
                    finally
                    {
                        lock (_iconLoads) _iconLoads.Remove(key);
                    }
                }));
            worker.IsBackground = true;
            worker.SetApartmentState(System.Threading.ApartmentState.STA);
            worker.Start();
        }

        private void LoadIconIntoCache(PanelItem item, int size)
        {
            var key = item.Type + "|" + item.Target + "|" + size;
            lock (IconCache)
            {
                if (IconCache.ContainsKey(key)) return;
            }
            Image image = null;
            if (item.Type == PanelItemTypes.Url)
                UrlFavicon.TryGetCachedImage(item.Target, size, out image);
            else
                image = ExtractShellIcon(item, size);
            if (image == null) return;
            lock (IconCache) IconCache[key] = image;
            RefreshTileAfterIconLoad(item, size);
        }

        private void RefreshTileAfterIconLoad(PanelItem loadedItem, int size)
        {
            if (IsDisposed || !IsHandleCreated) return;
            try
            {
                BeginInvoke(new Action(delegate
                {
                    if (IsDisposed) return;
                    if (size != ScaleLogical(40))
                    {
                        _tilesDirty = true;
                        return;
                    }
                    for (var index = 0; index < PanelConfig.SlotCount; index++)
                    {
                        var item = _config == null ? null : _config.Slots[index];
                        if (item == null || !string.Equals(item.Type, loadedItem.Type,
                                StringComparison.OrdinalIgnoreCase) ||
                            !string.Equals(item.Target, loadedItem.Target,
                                StringComparison.OrdinalIgnoreCase)) continue;
                        _tiles[index].Image = IconFor(item, size);
                        if (_panelVisible) _tiles[index].Invalidate();
                    }
                }));
            }
            catch (InvalidOperationException) { }
        }

        private void RequestFavicon(string target)
        {
            lock (_faviconFetches)
            {
                if (!_faviconFetches.Add(target)) return;
            }
            UrlFavicon.FetchAsync(target, succeeded =>
            {
                lock (_faviconFetches) _faviconFetches.Remove(target);
                if (!succeeded)
                {
                    // Let a later display retry; network failures and captive
                    // portals must not poison this URL for the process lifetime.
                    _tilesDirty = true;
                    return;
                }
                lock (IconCache)
                {
                    foreach (var key in IconCache.Keys
                        .Where(value => value.StartsWith(
                            PanelItemTypes.Url + "|" + target + "|",
                            StringComparison.OrdinalIgnoreCase)).ToList())
                        IconCache.Remove(key);
                }
                RefreshTileAfterIconLoad(new PanelItem
                {
                    Type = PanelItemTypes.Url,
                    Target = target,
                }, ScaleLogical(40));
            });
        }

        private static Image ExtractShellIcon(PanelItem item, int size)
        {
            try
            {
                if (item.Type == PanelItemTypes.Application ||
                    item.Type == PanelItemTypes.File ||
                    item.Type == PanelItemTypes.Folder)
                {
                    var iconTarget = item.Target;
                    // A shortcut's shell handler can return the generic .lnk icon
                    // when queried off the Explorer thread. Prefer its resolved
                    // executable, which yields the actual application icon.
                    if (item.Type == PanelItemTypes.Application &&
                        string.Equals(Path.GetExtension(iconTarget), ".lnk",
                            StringComparison.OrdinalIgnoreCase))
                        iconTarget = ResolveShortcutTarget(iconTarget) ?? iconTarget;
                    if (item.Type == PanelItemTypes.Application && File.Exists(iconTarget))
                    {
                        // ExtractAssociatedIcon reads the executable's own icon
                        // resource. SHGetFileInfo can return only the generic EXE
                        // icon for launchers such as current Weixin builds.
                        using (var associated = Icon.ExtractAssociatedIcon(iconTarget))
                        {
                            if (associated != null)
                                return new Bitmap(associated.ToBitmap(), new Size(size, size));
                        }
                    }
                    var handle = GetShellIconHandle(iconTarget,
                        item.Type == PanelItemTypes.Folder);
                    if (handle == IntPtr.Zero && !string.Equals(
                        iconTarget, item.Target, StringComparison.OrdinalIgnoreCase))
                        handle = GetShellIconHandle(item.Target, false);
                    if (handle != IntPtr.Zero)
                    {
                        try
                        {
                            using (var icon = Icon.FromHandle(handle))
                                return new Bitmap(icon.ToBitmap(), new Size(size, size));
                        }
                        finally { DestroyIcon(handle); }
                    }
                }
            }
            catch (Exception) { }
            var fallback = item.Type == PanelItemTypes.Folder
                ? SystemIcons.WinLogo
                : item.Type == PanelItemTypes.Url ? SystemIcons.Information : SystemIcons.Application;
            return new Bitmap(fallback.ToBitmap(), new Size(size, size));
        }

        private static IntPtr GetShellIconHandle(string path, bool folder)
        {
            var info = new SHFILEINFO();
            // 已存在的目标交给 shell 解析（.lnk 快捷方式会解析出目标程序的
            // 真实图标，如微信）；目标不存在时按类型给默认图标兜底。
            var flags = SHGFI_ICON | SHGFI_LARGEICON;
            if (!File.Exists(path) && !Directory.Exists(path))
                flags |= SHGFI_USEFILEATTRIBUTES;
            var result = SHGetFileInfo(path,
                folder ? FILE_ATTRIBUTE_DIRECTORY : FILE_ATTRIBUTE_NORMAL,
                ref info, (uint)Marshal.SizeOf(typeof(SHFILEINFO)), flags);
            return result != IntPtr.Zero ? info.hIcon : IntPtr.Zero;
        }

        private void ApplyDpiForPoint(Point point)
        {
            uint dpiX = 96;
            uint dpiY = 96;
            try
            {
                var monitor = NativeMethods.MonitorFromPoint(point, 2);
                if (monitor == IntPtr.Zero ||
                    NativeMethods.GetDpiForMonitor(monitor, 0, out dpiX, out dpiY) != 0)
                    dpiX = dpiY = 96;
            }
            catch (DllNotFoundException) { dpiX = dpiY = 96; }
            catch (EntryPointNotFoundException) { dpiX = dpiY = 96; }
            var workingArea = Screen.FromPoint(point).WorkingArea.Size;
            if (_appliedDpi == dpiX && _appliedWorkingAreaSize == workingArea) return;
            _appliedDpi = dpiX;
            _appliedWorkingAreaSize = workingArea;
            _scale = CalculateLayoutScale(workingArea, dpiX);
            SuspendLayout();
            _grid.SuspendLayout();
            try
            {
                ClientSize = new Size(ScaleLogical(LogicalWidth), ScaleLogical(LogicalHeight));
                Padding = new Padding(ScaleLogical(12));
                foreach (var tile in _tiles)
                    if (tile != null) tile.Margin = new Padding(ScaleLogical(4));
                _tilesDirty = true;
            }
            finally
            {
                _grid.ResumeLayout(false);
                ResumeLayout(false);
            }
            Trace.WriteLine("CrossGestures quick panel DPI: " + dpiX + ", scale=" + _scale);
        }

        internal static float CalculateLayoutScale(Size workingArea, uint dpiX)
        {
            var dpiScale = Math.Max(1F, dpiX / 96F);
            var logicalShortEdge = Math.Min(
                workingArea.Width / dpiScale, workingArea.Height / dpiScale);
            var monitorScale = Math.Max(0.68F,
                Math.Min(1.35F, logicalShortEdge / 900F));
            return dpiScale * monitorScale;
        }

        private int ScaleLogical(int value)
        {
            return Math.Max(1, (int)Math.Round(value * _scale));
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct SHFILEINFO
        {
            public IntPtr hIcon;
            public int iIcon;
            public uint dwAttributes;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
            public string szDisplayName;
        }

        private const uint SHGFI_ICON = 0x000000100;
        private const uint SHGFI_LARGEICON = 0x000000000;
        private const uint SHGFI_USEFILEATTRIBUTES = 0x000000010;
        private const uint FILE_ATTRIBUTE_NORMAL = 0x00000080;
        private const uint FILE_ATTRIBUTE_DIRECTORY = 0x00000010;

        private static class ShowWindowCommands
        {
            internal const int Hide = 0;
            internal const int Show = 5;
        }

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr SHGetFileInfo(string path, uint fileAttributes,
            ref SHFILEINFO info, uint cbFileInfo, uint flags);

        [DllImport("user32.dll")]
        private static extern bool DestroyIcon(IntPtr handle);

        private static class NativeMethods
        {
            [DllImport("user32.dll")]
            internal static extern IntPtr MonitorFromPoint(Point point, uint flags);

            [DllImport("shcore.dll")]
            internal static extern int GetDpiForMonitor(
                IntPtr monitor, int dpiType, out uint dpiX, out uint dpiY);

            [DllImport("user32.dll")]
            internal static extern bool SetForegroundWindow(IntPtr window);

            [DllImport("user32.dll")]
            internal static extern bool ShowWindow(IntPtr window, int command);
        }
    }
}

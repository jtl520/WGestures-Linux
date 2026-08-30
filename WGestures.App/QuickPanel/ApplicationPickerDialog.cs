using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

namespace WGestures.App.QuickPanel
{
    internal sealed class ApplicationPickerDialog : Form
    {
        private readonly TextBox _search = new TextBox();
        private readonly ListView _list = new ListView();
        private readonly Label _status = new Label();
        private readonly Button _select = new Button();
        private List<ApplicationRecord> _applications = new List<ApplicationRecord>();

        public string SelectedPath { get; private set; }
        public string SelectedName { get; private set; }

        public ApplicationPickerDialog()
        {
            Text = "选择应用程序";
            // 绝对行高表格在高 DPI 下不随字体缩放，会互相压盖显示不全；
            // 改用 Dock 布局并手动缩放窗口尺寸，任何 DPI 下都不会裁切。
            AutoScaleMode = AutoScaleMode.None;
            StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.Sizable;
            MinimizeBox = false;
            ShowInTaskbar = false;
            var scale = DeviceDpi / 96F;
            ClientSize = new Size(Scale(820, scale), Scale(560, scale));
            MinimumSize = new Size(Scale(640, scale), Scale(420, scale));
            Font = SystemFonts.MessageBoxFont;
            Padding = new Padding(Scale(10, scale));

            _list.Dock = DockStyle.Fill;
            _list.View = System.Windows.Forms.View.Details;
            _list.FullRowSelect = true;
            _list.MultiSelect = false;
            _list.HideSelection = false;
            _list.Columns.Add("名称", Scale(260, scale));
            _list.Columns.Add("位置", Scale(500, scale));
            _list.SelectedIndexChanged += delegate { _select.Enabled = _list.SelectedItems.Count == 1; };
            _list.DoubleClick += delegate { ChooseSelected(); };
            Controls.Add(_list);

            _status.Dock = DockStyle.Bottom;
            _status.AutoSize = true;
            _status.TextAlign = ContentAlignment.MiddleLeft;
            _status.Padding = new Padding(0, Scale(4, scale), 0, Scale(4, scale));
            _status.Text = "正在扫描开始菜单和已注册应用…";
            Controls.Add(_status);

            var buttons = new FlowLayoutPanel
            {
                Dock = DockStyle.Bottom,
                AutoSize = true,
                AutoSizeMode = AutoSizeMode.GrowAndShrink,
                FlowDirection = FlowDirection.RightToLeft,
                WrapContents = false,
                Padding = new Padding(0, Scale(8, scale), 0, 0),
            };
            var cancel = new Button { Text = "取消", AutoSize = true, DialogResult = DialogResult.Cancel };
            _select.Text = "选择";
            _select.AutoSize = true;
            _select.Enabled = false;
            _select.Click += delegate { ChooseSelected(); };
            var browse = new Button { Text = "浏览其他程序…", AutoSize = true };
            browse.Click += BrowseOther;
            buttons.Controls.Add(cancel);
            buttons.Controls.Add(_select);
            buttons.Controls.Add(browse);
            Controls.Add(buttons);

            _search.Dock = DockStyle.Top;
            _search.TextChanged += delegate { ApplyFilter(); };
            Controls.Add(_search);
            EmSetCueBanner(_search, "搜索应用名称或路径");
            AcceptButton = _select;
            CancelButton = cancel;
            Shown += delegate { BeginScan(); };
        }

        private static int Scale(int value, float scale)
        {
            return Math.Max(1, (int)Math.Round(value * scale));
        }

        private static void EmSetCueBanner(TextBox box, string text)
        {
            try
            {
                SendMessage(box.Handle, EM_SETCUEBANNER, (IntPtr)1, text);
            }
            catch (Exception) { }
        }

        private const int EM_SETCUEBANNER = 0x1501;

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr SendMessage(IntPtr handle, int message,
            IntPtr wParam, string lParam);

        private async void BeginScan()
        {
            try
            {
                _applications = await Task.Run(new Func<List<ApplicationRecord>>(ScanApplications));
                ApplyFilter();
                _status.Text = "已找到 " + _applications.Count + " 个应用；输入文字可筛选。";
                _search.Focus();
            }
            catch (Exception error)
            {
                _status.Text = "扫描失败，可使用“浏览其他程序”：" + error.Message;
            }
        }

        internal static List<ApplicationRecord> ScanApplications()
        {
            var records = new Dictionary<string, ApplicationRecord>(StringComparer.OrdinalIgnoreCase);
            var folders = new[]
            {
                Environment.GetFolderPath(Environment.SpecialFolder.Programs),
                Environment.GetFolderPath(Environment.SpecialFolder.CommonPrograms),
                Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                Environment.GetFolderPath(Environment.SpecialFolder.CommonDesktopDirectory),
            };
            foreach (var folder in folders.Where(Directory.Exists).Distinct(StringComparer.OrdinalIgnoreCase))
            {
                try
                {
                    foreach (var path in Directory.EnumerateFiles(folder, "*.*", SearchOption.AllDirectories))
                    {
                        var extension = Path.GetExtension(path);
                        if (!string.Equals(extension, ".lnk", StringComparison.OrdinalIgnoreCase) &&
                            !string.Equals(extension, ".exe", StringComparison.OrdinalIgnoreCase))
                            continue;
                        AddRecord(records, Path.GetFileNameWithoutExtension(path), path);
                    }
                }
                catch (UnauthorizedAccessException) { }
                catch (IOException) { }
            }
            ReadAppPaths(records, RegistryHive.CurrentUser, RegistryView.Default);
            ReadAppPaths(records, RegistryHive.LocalMachine, RegistryView.Registry64);
            ReadAppPaths(records, RegistryHive.LocalMachine, RegistryView.Registry32);
            return records.Values.OrderBy(record => record.Name, StringComparer.CurrentCultureIgnoreCase).ToList();
        }

        private static void ReadAppPaths(
            IDictionary<string, ApplicationRecord> records, RegistryHive hive, RegistryView view)
        {
            try
            {
                using (var baseKey = RegistryKey.OpenBaseKey(hive, view))
                using (var appPaths = baseKey.OpenSubKey(
                    @"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"))
                {
                    if (appPaths == null) return;
                    foreach (var keyName in appPaths.GetSubKeyNames())
                    {
                        using (var application = appPaths.OpenSubKey(keyName))
                        {
                            var path = application == null ? null : application.GetValue(null) as string;
                            if (!string.IsNullOrWhiteSpace(path) && File.Exists(path))
                                AddRecord(records, Path.GetFileNameWithoutExtension(keyName), path);
                        }
                    }
                }
            }
            catch (Exception error) when (error is UnauthorizedAccessException || error is IOException) { }
        }

        private static void AddRecord(
            IDictionary<string, ApplicationRecord> records, string name, string path)
        {
            if (string.IsNullOrWhiteSpace(path) || records.ContainsKey(path)) return;
            records[path] = new ApplicationRecord(name, path);
        }

        private void ApplyFilter()
        {
            var query = _search.Text.Trim();
            _list.BeginUpdate();
            try
            {
                _list.Items.Clear();
                foreach (var record in _applications.Where(record => query.Length == 0 ||
                    record.Name.IndexOf(query, StringComparison.CurrentCultureIgnoreCase) >= 0 ||
                    record.Path.IndexOf(query, StringComparison.OrdinalIgnoreCase) >= 0))
                {
                    var item = new ListViewItem(record.Name) { Tag = record };
                    item.SubItems.Add(record.Path);
                    _list.Items.Add(item);
                }
            }
            finally { _list.EndUpdate(); }
        }

        private void ChooseSelected()
        {
            if (_list.SelectedItems.Count != 1) return;
            var record = (ApplicationRecord)_list.SelectedItems[0].Tag;
            SelectedName = record.Name;
            SelectedPath = record.Path;
            DialogResult = DialogResult.OK;
            Close();
        }

        private void BrowseOther(object sender, EventArgs args)
        {
            using (var dialog = new OpenFileDialog
            {
                Title = "选择应用程序",
                Filter = "程序和快捷方式 (*.exe;*.lnk)|*.exe;*.lnk|所有文件 (*.*)|*.*",
            })
            {
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                SelectedPath = dialog.FileName;
                SelectedName = Path.GetFileNameWithoutExtension(dialog.FileName);
                DialogResult = DialogResult.OK;
                Close();
            }
        }

        internal sealed class ApplicationRecord
        {
            public string Name { get; private set; }
            public string Path { get; private set; }

            public ApplicationRecord(string name, string path)
            {
                Name = name;
                Path = path;
            }
        }
    }
}

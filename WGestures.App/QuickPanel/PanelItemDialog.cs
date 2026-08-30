using System;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace WGestures.App.QuickPanel
{
    internal sealed class PanelItemDialog : Form
    {
        private readonly ComboBox _type = new ComboBox();
        private readonly TextBox _label = new TextBox();
        private readonly TextBox _description = new TextBox();
        private readonly TextBox _target = new TextBox();
        private readonly TextBox _arguments = new TextBox();
        private readonly TextBox _workingDirectory = new TextBox();
        private readonly TextBox _browser = new TextBox();
        private readonly Button _browseTarget = new Button();
        private readonly Button _browseWorkingDirectory = new Button();
        private readonly Button _browseBrowser = new Button();
        private readonly CheckBox _runAsAdministrator = new CheckBox();
        private readonly CheckBox _activateIfRunning = new CheckBox();
        private readonly TableLayoutPanel _fields = new TableLayoutPanel();
        private readonly ToolTip _fieldToolTip = new ToolTip();
        private readonly PanelItem _original;
        private readonly bool _autoOpenApplicationPicker;

        private const int TargetRow = 3;
        private const int ArgumentsRow = 4;
        private const int WorkingDirectoryRow = 5;
        private const int BrowserRow = 6;
        private const int OptionsRow = 7;

        public PanelItem ResultItem { get; private set; }
        public bool DeleteRequested { get; private set; }

        protected override void Dispose(bool disposing)
        {
            if (disposing) _fieldToolTip.Dispose();
            base.Dispose(disposing);
        }

        private static int Scale(int value, float scale)
        {
            return Math.Max(1, (int)Math.Round(value * scale));
        }

        private int EstimateRequiredHeight()
        {
            return (Font.Height + Scale(30, DeviceDpi / 96F)) * _fields.RowCount
                + Font.Height + Scale(160, DeviceDpi / 96F);
        }

        private static Size ClampToWorkingArea(Size size)
        {
            var area = SystemInformation.WorkingArea;
            return new Size(
                Math.Min(size.Width, area.Width * 9 / 10),
                Math.Min(size.Height, area.Height * 9 / 10));
        }

        protected override void OnLoad(EventArgs e)
        {
            base.OnLoad(e);
            // 字体要在句柄创建后才最终确定（跨显示器 DPI 缩放），列宽和
            // 窗口高度必须按最终字体重算，否则大字体下仍然会裁切。
            var labelWidth = TextRenderer.MeasureText(
                "启动参数（不含程序名）", Font).Width + 12;
            var trailingWidth = _browseTarget.GetPreferredSize(Size.Empty).Width + 8;
            _fields.ColumnStyles[0].Width = labelWidth;
            _fields.ColumnStyles[2].Width = trailingWidth;
            var required = ClampToWorkingArea(new Size(
                labelWidth + trailingWidth + Scale(420, DeviceDpi / 96F),
                Math.Max(Scale(540, DeviceDpi / 96F), EstimateRequiredHeight())));
            if (ClientSize.Width < required.Width || ClientSize.Height < required.Height)
                ClientSize = new Size(Math.Max(ClientSize.Width, required.Width),
                    Math.Max(ClientSize.Height, required.Height));
        }

        public PanelItemDialog(PanelItem item, string initialType = null)
        {
            _original = item == null ? null : item.Clone();
            _autoOpenApplicationPicker = item == null && initialType == PanelItemTypes.Application;
            Text = item == null ? "添加格子" : "编辑格子";
            // 绝对行高不参与 WinForms 高 DPI 缩放，字体放大后整行会被裁切；
            // 关闭自动缩放，全部尺寸按当前 DPI 手动等比计算。
            AutoScaleMode = AutoScaleMode.None;
            var scale = DeviceDpi / 96F;
            // 先设置字体：后面的列宽与窗口高度都按字体实测。
            Font = SystemFonts.MessageBoxFont;
            FormBorderStyle = FormBorderStyle.Sizable;
            MaximizeBox = false;
            MinimizeBox = false;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.CenterParent;
            // 高度按当前字体实测估算，保证字段区不出现滚动条（滚动条会
            // 挤占宽度造成水平溢出），同时不小于默认视觉尺寸、不超过屏幕。
            ClientSize = ClampToWorkingArea(new Size(Scale(820, scale),
                Math.Max(Scale(540, scale), EstimateRequiredHeight())));
            MinimumSize = new Size(Scale(720, scale), Scale(470, scale));

            var root = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                Padding = new Padding(Scale(18, scale)),
                ColumnCount = 1,
                RowCount = 2,
            };
            root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            // 按钮行高跟随字体自动计算，避免高 DPI 固定值压裁按钮。
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            Controls.Add(root);

            _fields.Dock = DockStyle.Fill;
            _fields.AutoScroll = true;
            _fields.ColumnCount = 3;
            _fields.RowCount = 8;
            // 列宽按当前字体实测：固定像素在大字体/高 DPI 下不够宽，
            // AutoSize 列又会和百分比列互相挤爆。
            _browseTarget.Text = "选择…";
            _browseWorkingDirectory.Text = "选择…";
            _browseBrowser.Text = "选择…";
            var labelWidth = TextRenderer.MeasureText(
                "启动参数（不含程序名）", Font).Width
                + Scale(12, scale);
            var trailingWidth = _browseTarget.GetPreferredSize(Size.Empty).Width
                + Scale(8, scale);
            _fields.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, labelWidth));
            _fields.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            _fields.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, trailingWidth));
            // 行高全部跟随字体自动计算：固定值在系统大字体或高 DPI 下
            // 会裁切控件，AutoSize 行在任何字体尺寸下都完整显示。
            for (var row = 0; row < _fields.RowCount; row++)
                _fields.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            root.Controls.Add(_fields, 0, 0);

            _type.DropDownStyle = ComboBoxStyle.DropDownList;
            _type.Items.AddRange(new object[]
            {
                new TypeChoice(PanelItemTypes.Application, "启动软件"),
                new TypeChoice(PanelItemTypes.File, "打开文件"),
                new TypeChoice(PanelItemTypes.Folder, "打开文件夹"),
                new TypeChoice(PanelItemTypes.Url, "打开网址"),
            });
            _type.SelectedIndexChanged += delegate { SyncType(); };
            AddRow(0, "动作类型", _type, null);
            AddRow(1, "显示名称", _label, null);
            AddRow(2, "功能/用途说明", _description, null);

            _browseTarget.Click += BrowseTarget;
            AddRow(TargetRow, "路径或网址", _target, _browseTarget);
            AddRow(ArgumentsRow, "参数（可选）", _arguments, null);

            _browseWorkingDirectory.Click += delegate { BrowseFolderInto(_workingDirectory); };
            AddRow(WorkingDirectoryRow, "工作目录", _workingDirectory, _browseWorkingDirectory);

            _browseBrowser.Click += BrowseBrowser;
            AddRow(BrowserRow, "指定浏览器", _browser, _browseBrowser);

            var options = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                AutoSize = true,
                AutoSizeMode = AutoSizeMode.GrowAndShrink,
                ColumnCount = 1,
                RowCount = 2,
            };
            options.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            options.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            options.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            _runAsAdministrator.Text = "以管理员身份运行";
            _runAsAdministrator.AutoSize = true;
            _runAsAdministrator.Dock = DockStyle.Fill;
            _activateIfRunning.Text = "如果程序已运行，激活已打开的窗口";
            _activateIfRunning.AutoSize = true;
            _activateIfRunning.Dock = DockStyle.Fill;
            options.Controls.Add(_runAsAdministrator, 0, 0);
            options.Controls.Add(_activateIfRunning, 0, 1);
            AddRow(OptionsRow, "选项", options, null);

            _fieldToolTip.SetToolTip(_arguments,
                "传给程序的额外内容，例如 --project \"C:\\My Project\"；不要重复填写程序路径。");
            _fieldToolTip.SetToolTip(_workingDirectory,
                "相当于先切换到这个目录再启动程序；程序产生的相对路径也从这里计算。");
            _fieldToolTip.SetToolTip(_runAsAdministrator,
                "Windows 会显示 UAC 确认窗口，确认后以管理员权限启动。");

            var buttons = new FlowLayoutPanel
            {
                Dock = DockStyle.Fill,
                AutoSize = true,
                AutoSizeMode = AutoSizeMode.GrowAndShrink,
                FlowDirection = FlowDirection.RightToLeft,
                WrapContents = false,
                Padding = new Padding(0, Scale(10, scale), 0, 0),
            };
            var save = new Button { Text = "保存", AutoSize = true };
            save.Click += SaveClick;
            var cancel = new Button { Text = "取消", AutoSize = true, DialogResult = DialogResult.Cancel };
            buttons.Controls.Add(save);
            buttons.Controls.Add(cancel);
            if (item != null)
            {
                var delete = new Button { Text = "删除", AutoSize = true };
                delete.Click += delegate
                {
                    DeleteRequested = true;
                    DialogResult = DialogResult.OK;
                    Close();
                };
                buttons.Controls.Add(delete);
            }
            root.Controls.Add(buttons, 0, 1);
            AcceptButton = save;
            CancelButton = cancel;

            var selectedType = item == null
                ? (initialType ?? PanelItemTypes.Application)
                : item.Type;
            for (var index = 0; index < _type.Items.Count; index++)
            {
                if (((TypeChoice)_type.Items[index]).Value != selectedType) continue;
                _type.SelectedIndex = index;
                break;
            }
            if (item != null)
            {
                _label.Text = item.Label ?? string.Empty;
                _description.Text = item.Description ?? string.Empty;
                _target.Text = item.Target ?? string.Empty;
                _arguments.Text = item.Arguments ?? string.Empty;
                _workingDirectory.Text = item.WorkingDirectory ?? string.Empty;
                _browser.Text = item.Browser ?? string.Empty;
                _runAsAdministrator.Checked = item.RunAsAdministrator;
                _activateIfRunning.Checked = item.ActivateIfRunning;
            }
            else if (selectedType == PanelItemTypes.Url)
            {
                _target.Text = "https://";
            }
            SyncType();
            Shown += delegate
            {
                if (_autoOpenApplicationPicker)
                    BeginInvoke(new Action(OpenApplicationPicker));
            };
        }

        private void AddRow(int row, string title, Control control, Control trailing)
        {
            var label = new Label
            {
                Text = title,
                TextAlign = ContentAlignment.MiddleLeft,
                Dock = DockStyle.Fill,
                AutoEllipsis = true,
            };
            control.Dock = DockStyle.Fill;
            control.Margin = new Padding(4, 8, 4, 8);
            _fields.Controls.Add(label, 0, row);
            _fields.Controls.Add(control, 1, row);
            if (trailing == null)
                _fields.SetColumnSpan(control, 2);
            else
            {
                trailing.Dock = DockStyle.Fill;
                trailing.Margin = new Padding(4, 8, 4, 8);
                _fields.Controls.Add(trailing, 2, row);
            }
        }

        private string SelectedType
        {
            get { return _type.SelectedItem == null ? PanelItemTypes.Application : ((TypeChoice)_type.SelectedItem).Value; }
        }

        private void SyncType()
        {
            var application = SelectedType == PanelItemTypes.Application;
            var url = SelectedType == PanelItemTypes.Url;
            SetRowVisible(ArgumentsRow, application);
            SetRowVisible(WorkingDirectoryRow, application);
            SetRowVisible(OptionsRow, application);
            SetRowVisible(BrowserRow, url);
            _browseTarget.Enabled = !url;
            _fields.GetControlFromPosition(0, TargetRow).Text = application
                ? "程序或启动目标" : url ? "网址"
                : SelectedType == PanelItemTypes.Folder ? "文件夹路径" : "文件路径";
            _fields.GetControlFromPosition(0, ArgumentsRow).Text = "启动参数（不含程序名）";
            _fields.GetControlFromPosition(0, WorkingDirectoryRow).Text = "工作目录（启动位置）";
            _fieldToolTip.SetToolTip(_target, application
                ? "可执行文件或快捷方式的路径。"
                : url ? "完整网址，例如 https://example.com。"
                : "要打开的文件或文件夹路径。");
        }

        private void SetRowVisible(int row, bool visible)
        {
            foreach (Control control in _fields.Controls)
            {
                if (_fields.GetRow(control) == row) control.Visible = visible;
            }
        }

        private void BrowseTarget(object sender, EventArgs args)
        {
            if (SelectedType == PanelItemTypes.Application)
            {
                OpenApplicationPicker();
                return;
            }
            if (SelectedType == PanelItemTypes.Folder)
            {
                BrowseFolderInto(_target);
                return;
            }
            using (var dialog = new OpenFileDialog { Title = "选择要打开的文件" })
            {
                if (dialog.ShowDialog(this) == DialogResult.OK) SetTarget(dialog.FileName, null);
            }
        }

        private void OpenApplicationPicker()
        {
            using (var dialog = new ApplicationPickerDialog())
            {
                if (dialog.ShowDialog(this) == DialogResult.OK)
                    SetTarget(dialog.SelectedPath, dialog.SelectedName);
            }
        }

        private void BrowseBrowser(object sender, EventArgs args)
        {
            using (var dialog = new OpenFileDialog
            {
                Title = "选择浏览器（留空使用系统默认浏览器）",
                Filter = "程序和快捷方式 (*.exe;*.lnk)|*.exe;*.lnk|所有文件 (*.*)|*.*",
            })
            {
                if (dialog.ShowDialog(this) == DialogResult.OK) _browser.Text = dialog.FileName;
            }
        }

        private void BrowseFolderInto(TextBox target)
        {
            using (var dialog = new FolderBrowserDialog { Description = "选择工作目录或文件夹" })
            {
                if (dialog.ShowDialog(this) == DialogResult.OK) target.Text = dialog.SelectedPath;
            }
        }

        private void SetTarget(string target, string displayName)
        {
            _target.Text = target;
            if (string.IsNullOrWhiteSpace(_label.Text))
                _label.Text = string.IsNullOrWhiteSpace(displayName)
                    ? PanelConfig.DefaultLabel(SelectedType, target)
                    : displayName;
            if (SelectedType == PanelItemTypes.Application &&
                string.IsNullOrWhiteSpace(_workingDirectory.Text) &&
                string.Equals(Path.GetExtension(target), ".exe", StringComparison.OrdinalIgnoreCase))
                _workingDirectory.Text = Path.GetDirectoryName(target) ?? string.Empty;
        }

        private void SaveClick(object sender, EventArgs args)
        {
            var candidate = new PanelItem
            {
                Id = _original == null ? Guid.NewGuid().ToString("N") : _original.Id,
                Label = _label.Text.Trim(),
                Description = EmptyToNull(_description.Text),
                Type = SelectedType,
                Target = _target.Text.Trim(),
                Arguments = SelectedType == PanelItemTypes.Application ? EmptyToNull(_arguments.Text) : null,
                WorkingDirectory = SelectedType == PanelItemTypes.Application
                    ? EmptyToNull(_workingDirectory.Text) : null,
                RunAsAdministrator = SelectedType == PanelItemTypes.Application && _runAsAdministrator.Checked,
                ActivateIfRunning = SelectedType == PanelItemTypes.Application && _activateIfRunning.Checked,
                Browser = SelectedType == PanelItemTypes.Url ? EmptyToNull(_browser.Text) : null,
            };
            string reason;
            if (!PanelConfig.TryValidate(candidate, out reason))
            {
                Warn(reason);
                return;
            }
            if ((candidate.Type == PanelItemTypes.Application || candidate.Type == PanelItemTypes.File) &&
                !File.Exists(candidate.Target))
            {
                Warn("文件不存在。");
                return;
            }
            if (candidate.Type == PanelItemTypes.Folder && !Directory.Exists(candidate.Target))
            {
                Warn("文件夹不存在。");
                return;
            }
            if (!string.IsNullOrEmpty(candidate.WorkingDirectory) && !Directory.Exists(candidate.WorkingDirectory))
            {
                Warn("工作目录不存在。");
                return;
            }
            if (!string.IsNullOrEmpty(candidate.Browser) && !File.Exists(candidate.Browser))
            {
                Warn("指定浏览器不存在。");
                return;
            }
            if (candidate.Label.Length == 0)
                candidate.Label = PanelConfig.DefaultLabel(candidate.Type, candidate.Target);
            ResultItem = candidate;
            DialogResult = DialogResult.OK;
            Close();
        }

        private void Warn(string text)
        {
            MessageBox.Show(this, text, "CrossGestures", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }

        private static string EmptyToNull(string value)
        {
            var result = (value ?? string.Empty).Trim();
            return result.Length == 0 ? null : result;
        }

        private sealed class TypeChoice
        {
            public string Value { get; private set; }
            private readonly string _label;

            public TypeChoice(string value, string label)
            {
                Value = value;
                _label = label;
            }

            public override string ToString() { return _label; }
        }
    }
}

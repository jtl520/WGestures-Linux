using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
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

// 面板对话框高 DPI 布局冒烟：以 DPI 感知进程实例化“添加格子”与“选择应用
// 程序”对话框，程序化断言所有控件都落在所属客户区内（高分屏字体放大后
// 不允许互相压盖或裁切），并输出截图供人工复核。
internal static class WindowsPanelDialogSmoke
{
    private static Exception _failure;

    [STAThread]
    private static int Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.ThreadException += delegate(object sender,
            System.Threading.ThreadExceptionEventArgs args)
        {
            _failure = args.Exception;
        };

        var output = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "shots");
        Directory.CreateDirectory(output);
        try
        {
            CheckCreateDialogWithPicker(output);
            CheckEditDialog(output);
        }
        catch (Exception error)
        {
            _failure = error;
        }
        if (_failure != null)
        {
            Console.Error.WriteLine(_failure);
            return 2;
        }
        Console.WriteLine("Windows panel dialog layout checks passed.");
        return 0;
    }

    private static void CheckCreateDialogWithPicker(string output)
    {
        var dialog = new PanelItemDialog(null, null);
        dialog.StartPosition = FormStartPosition.Manual;
        dialog.Location = new Point(80, 80);
        dialog.Show();
        Pump(5);
        var picker = FindPicker(dialog);
        if (picker == null)
        {
            // DoEvents 泵不触发 Shown 自动打开时，显式打开：模态循环内的
            // Timer 负责截图并关闭，专门验证选择器的布局渲染。
            var pickerShot = Path.Combine(output, "picker.png");
            var pickerVerified = false;
            using (var timer = new System.Windows.Forms.Timer { Interval = 200 })
            {
                timer.Tick += delegate
                {
                    timer.Stop();
                    var shown = FindPicker(dialog);
                    if (shown == null) return;
                    AssertWithinClient(shown, "picker");
                    SaveShot(shown, pickerShot);
                    shown.DialogResult = DialogResult.Cancel;
                    shown.Close();
                    pickerVerified = true;
                };
                timer.Start();
                typeof(PanelItemDialog).GetMethod("OpenApplicationPicker",
                    BindingFlags.Instance | BindingFlags.NonPublic)
                    .Invoke(dialog, null);
            }
            if (!pickerVerified)
                throw new InvalidOperationException(
                    "The create dialog must open the application picker.");
        }
        AssertWithinClient(dialog, "create dialog");
        SaveShot(dialog, Path.Combine(output, "create.png"));
        dialog.Close();
        Pump(3);
    }

    private static Form FindPicker(Form owner)
    {
        return Application.OpenForms.OfType<Form>().FirstOrDefault(
            form => form != owner && form.Text == "选择应用程序");
    }

    private static void CheckEditDialog(string output)
    {
        var item = new PanelItem
        {
            Id = "edit", Label = "示例", Type = PanelItemTypes.Folder,
            Target = @"C:\Windows",
        };
        var dialog = new PanelItemDialog(item, null);
        dialog.StartPosition = FormStartPosition.Manual;
        dialog.Location = new Point(80, 80);
        dialog.Show();
        Pump(20);
        AssertWithinClient(dialog, "edit dialog");
        SaveShot(dialog, Path.Combine(output, "edit.png"));
        dialog.Close();
        Pump(3);
    }

    private static void Pump(int ticks)
    {
        for (var index = 0; index < ticks; index++)
        {
            Application.DoEvents();
            Thread.Sleep(100);
        }
    }

    private static void AssertWithinClient(Control container, string label)
    {
        foreach (Control child in container.Controls)
        {
            if (!container.ClientRectangle.Contains(child.Bounds))
                throw new InvalidOperationException(
                    label + " 控件越界：" + (child.Text ?? child.Name) +
                    " child=" + child.Bounds + " parentClient=" +
                    container.ClientRectangle + " parentBounds=" + container.Bounds +
                    " parentParent=" + (container.Parent == null
                        ? "null" : container.Parent.Bounds.ToString()) +
                    " dpi=" + container.DeviceDpi + " fontHeight=" + container.Font.Height);
            AssertWithinClient(child, label);
        }
    }

    private static void SaveShot(Control control, string path)
    {
        var bounds = control.Bounds;
        var bitmap = new Bitmap(bounds.Width, bounds.Height);
        using (var graphics = Graphics.FromImage(bitmap))
        {
            graphics.CopyFromScreen(bounds.Location, Point.Empty, bounds.Size);
        }
        bitmap.Save(path, System.Drawing.Imaging.ImageFormat.Png);
        bitmap.Dispose();
    }
}

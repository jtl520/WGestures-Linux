using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using WGestures.Core;
using WGestures.Core.Commands.Impl;

internal static class WindowsWindowActionSmoke
{
    private const int GwlExStyle = -20;
    private const long WsExTopmost = 0x00000008L;

    private sealed class TestContext : GestureContext
    {
        public override void ActivateTargetWindow() { }
    }

    [STAThread]
    private static int Main()
    {
        Application.EnableVisualStyles();
        using (var target = CreateForm("target", new Point(180, 180), false))
        using (var overlay = CreateForm("overlay", new Point(180, 180), true))
        {
            target.Show();
            overlay.Show();
            Application.DoEvents();

            var point = new Point(220, 220);
            if (WindowFromPoint(point) != overlay.Handle)
                throw new InvalidOperationException("The overlay must obscure the gesture start point.");

            var command = new WindowControlCommand {
                ChangeWindowStateTo = WindowControlCommand.WindowOperation.TOP_MOST,
                Context = new TestContext { WinId = target.Handle, StartPoint = point },
            };
            command.Execute();
            Application.DoEvents();
            if (!IsTopMost(target.Handle) || !IsTopMost(overlay.Handle))
                throw new InvalidOperationException(
                    "Toggle-above must change the frozen target without changing the overlay.");

            command.Execute();
            Application.DoEvents();
            if (IsTopMost(target.Handle) || !IsTopMost(overlay.Handle))
                throw new InvalidOperationException(
                    "The second toggle must remove topmost from the frozen target only.");
        }
        Console.WriteLine("Windows frozen-target window action checks passed.");
        return 0;
    }

    private static Form CreateForm(string name, Point location, bool topMost)
    {
        return new Form {
            Text = name,
            StartPosition = FormStartPosition.Manual,
            Location = location,
            Size = new Size(320, 240),
            TopMost = topMost,
            ShowInTaskbar = false,
        };
    }

    private static bool IsTopMost(IntPtr window)
    {
        return (GetWindowLongPtr(window, GwlExStyle).ToInt64() & WsExTopmost) != 0;
    }

    [DllImport("user32.dll")]
    private static extern IntPtr WindowFromPoint(Point point);

    private static IntPtr GetWindowLongPtr(IntPtr window, int index)
    {
        return IntPtr.Size == 8 ? GetWindowLongPtr64(window, index)
            : new IntPtr(GetWindowLong32(window, index));
    }

    [DllImport("user32.dll", EntryPoint = "GetWindowLong")]
    private static extern int GetWindowLong32(IntPtr window, int index);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtr")]
    private static extern IntPtr GetWindowLongPtr64(IntPtr window, int index);
}

using System;
using System.Collections.Generic;
using System.Configuration;
using System.Diagnostics;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
using WindowsInput;
using WGestures.Common.Annotation;
using WGestures.Common.OsSpecific.Windows;
using Win32;

namespace WGestures.Core.Commands.Impl
{
    [Named("窗口控制"), Serializable]
    public class WindowControlCommand : AbstractCommand, IGestureContextAware
    {
        public enum WindowOperation
        {
            MAXIMIZE_RESTORE = 0, MINIMIZE, CLOSE, TOP_MOST, DOCK_LEFT, DOCK_RIGHT
        }

        public WindowOperation ChangeWindowStateTo { get; set; }

        public override void Execute()
        {
            // The tracker freezes WinId before the trail overlay is shown.  Looking
            // the window up again here can select CrossGestures' own topmost layered
            // canvas instead of the application beneath it, which made every window
            // action (most visibly toggle-always-on-top) appear to do nothing.
            var targetWindow = Context == null ? IntPtr.Zero : Context.WinId;
            if (targetWindow == IntPtr.Zero && Context != null)
            {
                targetWindow = Native.WindowFromPoint(new Native.POINT
                {
                    x = Context.StartPoint.X,
                    y = Context.StartPoint.Y
                });
            }

            Trace.WriteLine("CrossGestures window command: operation=" +
                            ChangeWindowStateTo + ", target=0x" +
                            targetWindow.ToInt64().ToString("X"));
            DoOperation(targetWindow);
        }

        private void DoOperation(IntPtr win)
        {
            while (true)
            {
                //topLevelWin是本进程（？）内的顶层窗口
                //rootWindow可能会跨进程
                var topLevelWin = Native.GetTopLevelWindow(win);
                var rootWin = Native.GetAncestor(topLevelWin, Native.GetAncestorFlags.GetRoot);

                if (rootWin == IntPtr.Zero) return;

                Debug.WriteLine(string.Format("win     : {0:X}", win.ToInt64()));
                Debug.WriteLine(string.Format("root    : {0:X}",rootWin.ToInt64()));
                Debug.WriteLine(string.Format("topLevel: {0:X}", topLevelWin.ToInt64()));

                var rootWinExStyle = User32.GetWindowLong(rootWin, User32.GWL.GWL_EXSTYLE);
                var rootWinStyle = User32.GetWindowLong(rootWin, User32.GWL.GWL_STYLE);
                var topLevelWinstyle = User32.GetWindowLong(topLevelWin, User32.GWL.GWL_STYLE);

                switch (ChangeWindowStateTo)
                {
                    case WindowOperation.MAXIMIZE_RESTORE:
                        IntPtr winToControl;
                        if ((long) User32.WS.WS_MAXIMIZEBOX == (topLevelWinstyle & (long) User32.WS.WS_MAXIMIZEBOX))
                        {
                            winToControl = topLevelWin;
                        }
                        else if (topLevelWin != rootWin && (long) User32.WS.WS_MAXIMIZEBOX == (rootWinStyle & (long) User32.WS.WS_MAXIMIZEBOX))
                        {
                            winToControl = rootWin;
                        }
                        else //如果窗口都不响应， 考虑回滚为处理活动窗口
                        {
                            var fgWin = Native.GetForegroundWindow();
                            if (fgWin == win) return;

                            win = fgWin;
                            continue;
                        }

                        var wp = new User32.WINDOWPLACEMENT();
                        wp.length = Marshal.SizeOf(typeof (User32.WINDOWPLACEMENT));

                        if (!User32.GetWindowPlacement(rootWin, ref wp)) return;

                        if (wp.showCmd == (int) ShowWindowCommands.MAXIMIZED)
                        {
                            User32.ShowWindowAsync(winToControl, (int) ShowWindowCommands.NORMAL);
                        }
                        else
                        {
                            User32.ShowWindowAsync(winToControl, (int) ShowWindowCommands.MAXIMIZED);
                        }
                        goto end;

                    case WindowOperation.MINIMIZE:
                        if ((long) User32.WS.WS_MINIMIZEBOX == (rootWinStyle & (long) User32.WS.WS_MINIMIZEBOX))
                        {
                            User32.PostMessage(rootWin, User32.WM.WM_SYSCOMMAND, (int) User32.SysCommands.SC_MINIMIZE, 0);
                        }
                        else if (topLevelWin != rootWin && (long) User32.WS.WS_MINIMIZEBOX == (topLevelWinstyle & (long) User32.WS.WS_MINIMIZEBOX))
                        {
                            User32.PostMessage(topLevelWin, User32.WM.WM_SYSCOMMAND, (int) User32.SysCommands.SC_MINIMIZE, 0);
                        }
                        goto end;

                    case WindowOperation.CLOSE:
                        User32.PostMessage(rootWin, User32.WM.WM_SYSCOMMAND, (int) User32.SysCommands.SC_CLOSE, 0);
                        goto end;

                    case WindowOperation.TOP_MOST:
                        var makeTopMost =
                            (rootWinExStyle & (int)User32.WS_EX.WS_EX_TOPMOST) == 0;
                        var changed = User32.SetWindowPos(rootWin,
                            makeTopMost ? new IntPtr(-1) : new IntPtr(-2),
                            0, 0, 0, 0,
                            User32.SWP.SWP_NOMOVE | User32.SWP.SWP_NOSIZE |
                            User32.SWP.SWP_NOACTIVATE);
                        Trace.WriteLine("CrossGestures window topmost result: target=0x" +
                                        rootWin.ToInt64().ToString("X") +
                                        ", requested=" + makeTopMost +
                                        ", success=" + changed +
                                        ", win32Error=" + Marshal.GetLastWin32Error());
                        if (!changed)
                        {
                            // Some framework windows expose a child/owner root that
                            // rejects SetWindowPos.  The foreground target captured at
                            // mouse-down is the safest bounded fallback.
                            var foreground = Native.GetForegroundWindow();
                            if (foreground != IntPtr.Zero && foreground != rootWin)
                                User32.SetWindowPos(foreground,
                                    makeTopMost ? new IntPtr(-1) : new IntPtr(-2),
                                    0, 0, 0, 0,
                                    User32.SWP.SWP_NOMOVE | User32.SWP.SWP_NOSIZE |
                                    User32.SWP.SWP_NOACTIVATE);
                        }
                        goto end;
                }
                break;
            }

        end:
        // 这里绝不能做强制 GC：窗口手势在手势线程上执行，强制全量回收
        // 会卡住手势解析，让下一次手势明显变卡。
        ;
        }

        public GestureContext Context { set; private get; }

        public override string Description()
        {
            switch (ChangeWindowStateTo)
            {
                case WindowOperation.MAXIMIZE_RESTORE:
                    return "最大化/恢复";
                case WindowOperation.MINIMIZE:
                    return "最小化";
                case WindowOperation.DOCK_LEFT:
                    return "左停靠";
                case WindowOperation.DOCK_RIGHT:
                    return "右停靠";
                case WindowOperation.TOP_MOST:
                    return "窗口置顶";
                default:
                    return "关闭窗口";
            }
        }

        internal enum ShowWindowCommands : int
        {
            HIDE = 0,
            NORMAL = 1,
            MINIMIZED = 2,
            MAXIMIZED = 3,
        }





    }
}

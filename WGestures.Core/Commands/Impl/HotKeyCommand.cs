using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using WindowsInput;
using WindowsInput.Native;
using WGestures.Common.Annotation;
using WGestures.Common.OsSpecific.Windows;
using Win32;
using Screen = WGestures.Common.OsSpecific.Windows.Screen;
using ThreadState = System.Diagnostics.ThreadState;

namespace WGestures.Core.Commands.Impl
{
    [Named("执行快捷键"), Serializable]
    public class HotKeyCommand : AbstractCommand, IGestureContextAware
    {
        public HotKeyCommand()
        {
            Modifiers = new List<VirtualKeyCode>();
            Keys = new List<VirtualKeyCode>();
        }

        public List<VirtualKeyCode> Modifiers { get; set; }

        public List<VirtualKeyCode> Keys { get; set; }


        public override void Execute()
        {
            if (Keys.Count + Modifiers.Count == 0) return;

            if (Keys.Count == 1 && (Keys[0] == VirtualKeyCode.VK_L) &&
                Modifiers.Count == 1 && (Modifiers[0] == VirtualKeyCode.LWIN || Modifiers[0] == VirtualKeyCode.RWIN))
            {
                User32.LockWorkStation();
                return;
            }


            // Keyboard shortcuts belong to the window/focus captured when the
            // gesture started, not whichever internal child is under the cursor
            // after drawing the gesture.
            var fgWindow = Context != null && Context.WinId != IntPtr.Zero
                ? Context.WinId
                : Native.GetForegroundWindow();

            Debug.WriteLine(string.Format("FGWindow: {0:X}", fgWindow.ToInt64()));

            //如果没有前台窗口，或者前台窗口是任务栏，则使用鼠标指针下方的窗口？
            /*var useCursorWindow = false;
            if (fgWindow != IntPtr.Zero)
            {
                var className = new StringBuilder(32);
                Native.GetClassName(fgWindow, className, className.Capacity);

                //如果是任务栏 或者 窗口处于最小化状态
                if (className.ToString() == "Shell_TrayWnd")
                {
                    useCursorWindow = true;
                } //如果活动窗口与鼠标指针不在同一个屏幕
                else if (!IsCursorAndWindowSameScreen(fgWindow))
                {
                    useCursorWindow = true;
                }
                else
                {
                    rootWindow = Native.GetAncestor(fgWindow, Native.GetAncestorFlags.GetRoot);
                    if (IsWindowMinimized(rootWindow))
                    {
                        Debug.WriteLine("Use Cursor Window Cuz rootWindow is Minimized.");
                        useCursorWindow = true;
                    }
                }
            }
            else
            {
                useCursorWindow = true;
            }*/


            if (fgWindow == IntPtr.Zero) return;

            //失败可能原因之一：被杀毒软件或系统拦截

            try
            {
                IEnumerable<VirtualKeyCode> actualModifiers = Modifiers;
                IEnumerable<VirtualKeyCode> actualKeys = Keys;
                List<VirtualKeyCode> consoleModifiers;
                List<VirtualKeyCode> consoleKeys;
                if (TryGetConsoleClipboardShortcut(out consoleModifiers, out consoleKeys))
                {
                    actualModifiers = consoleModifiers;
                    actualKeys = consoleKeys;
                }

                var modifierList = actualModifiers.ToList();
                var keyList = actualKeys.ToList();

                // Some Chromium editors and terminal hosts discard a complete
                // chord when all transitions arrive in one SendInput call. The
                // original WGestures releases paced each transition; retain that
                // behavior while always releasing modifiers in a finally block.
                SendModifiedKeyStrokeWithPacing(modifierList, keyList);
                Trace.WriteLine("CrossGestures shortcut injected: target=" +
                    fgWindow.ToInt64().ToString("X") + ", shortcut=" +
                    HotKeyToString(modifierList, keyList));
            }
            catch (Exception ex)
            {
                Debug.WriteLine("发送按键的时候发生异常： " + ex);
                Trace.WriteLine("CrossGestures shortcut injection failed: " + ex.Message);
                Native.TryResetKeys(Keys, Modifiers);
#if TEST
                throw;
#endif
            }

            //GC.Collect(GC.MaxGeneration, GCCollectionMode.Forced);



        }

        private bool TryGetConsoleClipboardShortcut(out List<VirtualKeyCode> modifiers,
            out List<VirtualKeyCode> keys)
        {
            modifiers = null;
            keys = null;
            if (Context == null || !IsConsoleTarget(Context)) return false;

            var isCopy = IsControlShortcut(VirtualKeyCode.VK_C) ||
                IsLegacyConsoleMenuShortcut(VirtualKeyCode.VK_Y);
            var isPaste = IsControlShortcut(VirtualKeyCode.VK_V) ||
                IsLegacyConsoleMenuShortcut(VirtualKeyCode.VK_P);
            if (!isCopy && !isPaste) return false;

            if (IsWindowsTerminalTarget(Context))
            {
                // Windows Terminal's native defaults. These work with selected
                // terminal text and avoid the inconsistent Insert handling seen
                // with some Terminal/keyboard-layout combinations.
                modifiers = new List<VirtualKeyCode>
                {
                    VirtualKeyCode.LCONTROL,
                    VirtualKeyCode.LSHIFT
                };
                keys = new List<VirtualKeyCode>
                {
                    isCopy ? VirtualKeyCode.VK_C : VirtualKeyCode.VK_V
                };
                Trace.WriteLine("CrossGestures adapted " + (isCopy ? "copy" : "paste") +
                    " for Windows Terminal.");
            }
            else
            {
                // Console Host supports these independently of QuickEdit and of
                // whether Ctrl+C is currently interpreted as BREAK.
                modifiers = new List<VirtualKeyCode>
                {
                    isCopy ? VirtualKeyCode.LCONTROL : VirtualKeyCode.LSHIFT
                };
                keys = new List<VirtualKeyCode> { VirtualKeyCode.INSERT };
                Trace.WriteLine("CrossGestures adapted " + (isCopy ? "copy" : "paste") +
                    " for Console Host.");
            }
            return true;
        }

        private static void SendModifiedKeyStrokeWithPacing(
            IList<VirtualKeyCode> modifiers, IList<VirtualKeyCode> keys)
        {
            const int transitionDelayMillis = 25;
            var pressedModifiers = new Stack<VirtualKeyCode>();
            try
            {
                // Let the mouse-up that completed the gesture reach the target
                // before beginning the keyboard chord.
                Thread.Sleep(25);
                foreach (var modifier in modifiers)
                {
                    Sim.KeyDown(modifier);
                    pressedModifiers.Push(modifier);
                    Thread.Sleep(transitionDelayMillis);
                }

                foreach (var key in keys)
                {
                    Sim.KeyDown(key);
                    Thread.Sleep(transitionDelayMillis);
                    Sim.KeyUp(key);
                    Thread.Sleep(transitionDelayMillis);
                }
            }
            finally
            {
                while (pressedModifiers.Count > 0)
                {
                    Sim.KeyUp(pressedModifiers.Pop());
                    Thread.Sleep(transitionDelayMillis);
                }
            }
        }

        private bool IsControlShortcut(VirtualKeyCode key)
        {
            return Keys.Count == 1 && Keys[0] == key && Modifiers.Count == 1 &&
                IsControl(Modifiers[0]);
        }

        private bool IsLegacyConsoleMenuShortcut(VirtualKeyCode finalKey)
        {
            return Modifiers.Count == 1 && IsAlt(Modifiers[0]) && Keys.Count == 3 &&
                Keys[0] == VirtualKeyCode.SPACE && Keys[1] == VirtualKeyCode.VK_E &&
                Keys[2] == finalKey;
        }

        private static bool IsConsoleTarget(GestureContext context)
        {
            if (IsWindowsTerminalTarget(context)) return true;

            if (context.WinId != IntPtr.Zero)
            {
                var root = Native.GetAncestor(context.WinId, Native.GetAncestorFlags.GetRoot);
                var className = new StringBuilder(128);
                Native.GetClassName(root, className, className.Capacity);
                var windowClass = className.ToString();
                if (windowClass.Equals("ConsoleWindowClass", StringComparison.OrdinalIgnoreCase))
                    return true;
            }

            string processPath;
            try
            {
                processPath = Native.GetProcessFile(context.ProcId);
            }
            catch (Exception)
            {
                return false;
            }
            if (string.IsNullOrWhiteSpace(processPath)) return false;
            var name = Path.GetFileNameWithoutExtension(processPath).ToLowerInvariant();
            return name == "cmd" || name == "conhost" || name == "openconsole" ||
                name == "windowsterminal" || name == "wt" || name == "powershell" ||
                name == "pwsh" || name == "mintty" || name == "wezterm" ||
                name == "alacritty";
        }

        private static bool IsWindowsTerminalTarget(GestureContext context)
        {
            if (context.WinId != IntPtr.Zero)
            {
                var root = Native.GetAncestor(context.WinId, Native.GetAncestorFlags.GetRoot);
                var className = new StringBuilder(128);
                Native.GetClassName(root, className, className.Capacity);
                if (className.ToString().IndexOf(
                    "CASCADIA", StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            }

            string processPath;
            try
            {
                processPath = Native.GetProcessFile(context.ProcId);
            }
            catch (Exception)
            {
                return false;
            }
            if (string.IsNullOrWhiteSpace(processPath)) return false;
            var name = Path.GetFileNameWithoutExtension(processPath);
            return name.Equals("WindowsTerminal", StringComparison.OrdinalIgnoreCase) ||
                name.Equals("wt", StringComparison.OrdinalIgnoreCase);
        }

        private static bool IsControl(VirtualKeyCode key)
        {
            return key == VirtualKeyCode.CONTROL || key == VirtualKeyCode.LCONTROL ||
                key == VirtualKeyCode.RCONTROL;
        }

        private static bool IsAlt(VirtualKeyCode key)
        {
            return key == VirtualKeyCode.MENU || key == VirtualKeyCode.LMENU ||
                key == VirtualKeyCode.RMENU;
        }

        private static bool IsWindowMinimized(IntPtr hwnd)
        {
            int style = User32.GetWindowLong(hwnd, User32.GWL.GWL_STYLE);

            return (int)User32.WS.WS_MINIMIZE == (style & (int)User32.WS.WS_MINIMIZE);
        }

        private static bool IsCursorAndWindowSameScreen(IntPtr win)
        {
            Native.POINT pt;
            Native.GetCursorPos(out pt);

            var fgWinScreen = Screen.FromHandle(win);
            var cursorScreen = Screen.FromPoint(pt.ToPoint());

            return fgWinScreen.Equals(cursorScreen);

        }

        public override string Description()
        {
            return HotKeyToString(Modifiers, Keys);
        }

        public static void ForceWindowIntoForeground(IntPtr window)
        {
            const uint LSFW_LOCK = 1;
            const uint LSFW_UNLOCK = 2;
            const int ASFW_ANY = -1; // by MSDN

            uint currentThread = Native.GetCurrentThreadId();

            IntPtr activeWindow = User32.GetForegroundWindow();
            //uint activeProcess;
            uint activeThread = User32.GetWindowThreadProcessId(activeWindow, IntPtr.Zero);

            uint windowProcess;
            uint windowThread = User32.GetWindowThreadProcessId(window, IntPtr.Zero);

            if (currentThread != activeThread)
                User32.AttachThreadInput(currentThread, activeThread, true);
            if (windowThread != currentThread)
                User32.AttachThreadInput(windowThread, currentThread, true);

            uint oldTimeout = 0, newTimeout = 0;
            User32.SystemParametersInfo(User32.SPI_GETFOREGROUNDLOCKTIMEOUT, 0, ref oldTimeout, 0);
            User32.SystemParametersInfo(User32.SPI_SETFOREGROUNDLOCKTIMEOUT, 0, ref newTimeout, 0);
            User32.LockSetForegroundWindow(LSFW_UNLOCK);
            User32.AllowSetForegroundWindow(ASFW_ANY);

            User32.SetForegroundWindow(window);
            User32.ShowWindow(window, User32.SW.SW_RESTORE);
            User32.SetFocus(window);

            User32.SystemParametersInfo(User32.SPI_SETFOREGROUNDLOCKTIMEOUT, 0, ref oldTimeout, 0);

            if (currentThread != activeThread)
                User32.AttachThreadInput(currentThread, activeThread, false);
            if (windowThread != currentThread)
                User32.AttachThreadInput(windowThread, currentThread, false);
        }

        public static string HotKeyToString(ICollection<VirtualKeyCode> modifiers, ICollection<VirtualKeyCode> keys)
        {
            if (keys.Count != 0 || modifiers.Count != 0)
            {
                var sb = new StringBuilder(32);
                foreach (var k in modifiers)
                {
                    string str = "";
                    switch (k)
                    {
                        case VirtualKeyCode.MENU:
                        case VirtualKeyCode.RMENU:
                        case VirtualKeyCode.LMENU:
                            str = "Alt";
                            break;
                        case VirtualKeyCode.LCONTROL:
                        case VirtualKeyCode.RCONTROL:
                        case VirtualKeyCode.CONTROL:
                            str = "Ctrl";
                            break;
                        case VirtualKeyCode.RWIN:
                        case VirtualKeyCode.LWIN:
                            str = "Win";
                            break;
                        case VirtualKeyCode.SHIFT:
                        case VirtualKeyCode.LSHIFT:
                        case VirtualKeyCode.RSHIFT:
                            str = "Shift";
                            break;
                        default:
                            str = k.ToString();
                            break;
                    }
                    if(sb.Length > 0) sb.Append('-');
                    sb.Append(str);
                }

                if(sb.Length > 0) sb.Append(" + ");

                foreach (var k in keys)
                {
                    string str = k.ToString();
                    if (str.StartsWith("VK_")) str = str.Substring(3);

                    sb.Append(str);
                    sb.Append(" + ");
                }


                sb.Remove(sb.Length - 3, 3);
                return sb.ToString();
            }

            return "";
        }


        public GestureContext Context { set; private get; }
    }
}

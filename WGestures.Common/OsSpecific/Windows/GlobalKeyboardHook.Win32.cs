using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace WGestures.Common.OsSpecific.Windows
{
    /// <summary>
    /// Manages a 32-bit or 64-bit safe low-level keyboard hook.
    /// </summary>
    public sealed class GlobalKeyboardHook : IDisposable
    {
        private const int WM_KEYDOWN = 0x0100;
        private const int WM_KEYUP = 0x0101;
        private const int WM_SYSKEYDOWN = 0x0104;
        private const int WM_SYSKEYUP = 0x0105;

        private readonly Native.LowLevelKeyboardHookProc _callback;
        private IntPtr _hook = IntPtr.Zero;
        private bool _disposed;

        public event KeyEventHandler KeyDown;
        public event KeyEventHandler KeyUp;

        public GlobalKeyboardHook()
        {
            _callback = HookProcedure;
        }

        ~GlobalKeyboardHook()
        {
            Dispose(false);
        }

        public void hook()
        {
            ThrowIfDisposed();
            if (_hook != IntPtr.Zero)
                return;

            _hook = Native.SetKeyboardHook(_callback);
            if (_hook == IntPtr.Zero)
                throw new Win32Exception(Marshal.GetLastWin32Error(),
                    "Unable to install the global keyboard hook.");
        }

        public void unhook()
        {
            if (_hook == IntPtr.Zero)
                return;

            Native.UnhookWindowsHookEx(_hook);
            _hook = IntPtr.Zero;
        }

        private IntPtr HookProcedure(int code, IntPtr wParam, IntPtr lParam)
        {
            if (code >= 0)
            {
                var data = (Native.KBDLLHOOKSTRUCT)Marshal.PtrToStructure(
                    lParam, typeof(Native.KBDLLHOOKSTRUCT));
                var args = new KeyEventArgs((Keys)data.vkCode);
                var message = wParam.ToInt32();

                if ((message == WM_KEYDOWN || message == WM_SYSKEYDOWN) && KeyDown != null)
                    KeyDown(this, args);
                else if ((message == WM_KEYUP || message == WM_SYSKEYUP) && KeyUp != null)
                    KeyUp(this, args);

                if (args.Handled)
                    return new IntPtr(1);
            }

            return Native.CallNextHookEx(_hook, code, wParam, lParam);
        }

        private void ThrowIfDisposed()
        {
            if (_disposed)
                throw new ObjectDisposedException(GetType().FullName);
        }

        private void Dispose(bool disposing)
        {
            if (_disposed)
                return;

            unhook();
            _disposed = true;
        }

        public void Dispose()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }
    }
}

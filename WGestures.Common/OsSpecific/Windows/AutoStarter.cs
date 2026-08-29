using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using System.Windows.Forms;
using Microsoft.Win32;

namespace WGestures.Common.OsSpecific.Windows
{
    public static class AutoStarter
    {
        private const int TaskCreateOrUpdate = 6;
        private const int TaskActionExecute = 0;
        private const int TaskLogonInteractiveToken = 3;
        private const int TaskRunLevelHighest = 1;
        private const int TaskTriggerLogon = 9;

        static string MakeShortcutPath(string identifier)
        {
            return Environment.GetFolderPath(Environment.SpecialFolder.Startup) + @"\" + identifier + ".lnk";
        }

        public static void Register(string identifier, string appPath)
        {
            Unregister(identifier);
            dynamic service = null;
            dynamic rootFolder = null;
            dynamic task = null;
            dynamic trigger = null;
            dynamic action = null;
            try
            {
                var serviceType = Type.GetTypeFromProgID("Schedule.Service");
                if (serviceType == null)
                    throw new InvalidOperationException("Windows Task Scheduler is unavailable.");

                service = Activator.CreateInstance(serviceType);
                service.Connect();
                rootFolder = service.GetFolder("\\");
                task = service.NewTask(0);
                task.RegistrationInfo.Description = identifier;
                task.Settings.DisallowStartIfOnBatteries = false;
                task.Settings.StopIfGoingOnBatteries = false;
                task.Settings.StartWhenAvailable = true;
                task.Settings.ExecutionTimeLimit = "PT0S";
                task.Settings.Hidden = false;
                task.Settings.MultipleInstances = 2; // Ignore a duplicate launch.

                var userId = WindowsIdentity.GetCurrent().Name;
                task.Principal.LogonType = TaskLogonInteractiveToken;
                task.Principal.UserId = userId;
                task.Principal.RunLevel = TaskRunLevelHighest;

                trigger = task.Triggers.Create(TaskTriggerLogon);
                trigger.UserId = userId;
                action = task.Actions.Create(TaskActionExecute);
                action.Path = appPath;
                action.WorkingDirectory = Path.GetDirectoryName(appPath);

                rootFolder.RegisterTaskDefinition(identifier, task, TaskCreateOrUpdate,
                    userId, null, TaskLogonInteractiveToken, null);
            }
            finally
            {
                ReleaseComObject(action);
                ReleaseComObject(trigger);
                ReleaseComObject(task);
                ReleaseComObject(rootFolder);
                ReleaseComObject(service);
            }
        }
        public static void Unregister(string identifier)
        {
            System.IO.File.Delete(MakeShortcutPath(identifier));

            //ensure removing registry item added in older versions
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Run"))
            {
                if (key != null) key.DeleteValue(identifier, throwOnMissingValue: false);
            }

            dynamic service = null;
            dynamic rootFolder = null;
            try
            {
                var serviceType = Type.GetTypeFromProgID("Schedule.Service");
                if (serviceType == null) return;
                service = Activator.CreateInstance(serviceType);
                service.Connect();
                rootFolder = service.GetFolder("\\");
                try { rootFolder.DeleteTask(identifier, 0); }
                catch (Exception) { }
            }
            finally
            {
                ReleaseComObject(rootFolder);
                ReleaseComObject(service);
            }
        }
        public static bool IsRegistered(string identifier,string appPath)
        {
            dynamic service = null;
            dynamic rootFolder = null;
            dynamic registeredTask = null;
            dynamic action = null;
            try
            {
                var serviceType = Type.GetTypeFromProgID("Schedule.Service");
                if (serviceType == null) return false;
                service = Activator.CreateInstance(serviceType);
                service.Connect();
                rootFolder = service.GetFolder("\\");
                registeredTask = rootFolder.GetTask(identifier);
                action = registeredTask.Definition.Actions.Item(1);
                return string.Equals((string)action.Path, appPath,
                    StringComparison.OrdinalIgnoreCase);
            }
            catch (Exception)
            {
                return false;
            }
            finally
            {
                ReleaseComObject(action);
                ReleaseComObject(registeredTask);
                ReleaseComObject(rootFolder);
                ReleaseComObject(service);
            }
        }

        private static void ReleaseComObject(object value)
        {
            if (value != null && Marshal.IsComObject(value))
                Marshal.FinalReleaseComObject(value);
        }

        public static void CreateShortcut(string shortcutPath, string targetFileLocation)
        {
            try
            {
                var shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType == null)
                    throw new InvalidOperationException("Windows Script Host is unavailable.");

                dynamic shell = Activator.CreateInstance(shellType);
                dynamic shortcut = null;
                try
                {
                    shortcut = shell.CreateShortcut(shortcutPath);
                    shortcut.TargetPath = targetFileLocation;
                    shortcut.WorkingDirectory = System.IO.Path.GetDirectoryName(targetFileLocation);
                    shortcut.Save();
                }
                finally
                {
                    if (shortcut != null && System.Runtime.InteropServices.Marshal.IsComObject(shortcut))
                        System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shortcut);
                    if (shell != null && System.Runtime.InteropServices.Marshal.IsComObject(shell))
                        System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
                }
            }catch(Exception e)
            {
                Debug.WriteLine(e);
                //may be intercepted by 360 etc. ignore...
            }

                                
        }
    }
}

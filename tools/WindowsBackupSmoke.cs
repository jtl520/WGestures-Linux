using System;
using System.Collections;
using System.IO;
using System.Reflection;

[assembly: AssemblyVersion("2.1.2.0")]
[assembly: AssemblyFileVersion("2.1.2.0")]

internal static class WindowsBackupSmoke
{
    private static string applicationDirectory;

    private static int CountEnumerable(object value)
    {
        var count = 0;
        foreach (var ignored in (IEnumerable)value) count++;
        return count;
    }

    private static object Invoke(Type type, string method, params object[] arguments)
    {
        try
        {
            return type.InvokeMember(method,
                BindingFlags.InvokeMethod | BindingFlags.Static |
                BindingFlags.Public | BindingFlags.NonPublic,
                null, null, arguments);
        }
        catch (TargetInvocationException exception)
        {
            throw exception.InnerException ?? exception;
        }
    }

    public static int Main(string[] args)
    {
        if (args.Length != 2 && args.Length != 3)
        {
            Console.Error.WriteLine("Usage: WindowsBackupSmoke <CrossGestures.exe> <output.wgb> [linux.cgestures]");
            return 2;
        }

        try
        {
            var applicationPath = Path.GetFullPath(args[0]);
            applicationDirectory = Path.GetDirectoryName(applicationPath);
            AppDomain.CurrentDomain.AssemblyResolve += delegate(object sender, ResolveEventArgs eventArgs)
            {
                var dependency = Path.Combine(applicationDirectory,
                    new AssemblyName(eventArgs.Name).Name + ".dll");
                return File.Exists(dependency) ? Assembly.LoadFrom(dependency) : null;
            };

            var assembly = Assembly.LoadFrom(applicationPath);
            var migrateService = assembly.GetType("WGestures.App.Migrate.MigrateService", true);
            var outputPath = Path.GetFullPath(args[1]);

            Invoke(migrateService, "ExportTo", outputPath);
            if (!File.Exists(outputPath) || new FileInfo(outputPath).Length == 0)
                throw new InvalidDataException("Backup export did not create a non-empty .wgb file.");

            var imported = Invoke(migrateService, "ImportWgb", outputPath);
            var importedType = imported.GetType();
            var config = importedType.GetProperty("Config").GetValue(imported, null);
            var store = importedType.GetProperty("GestureIntentStore").GetValue(imported, null);
            if (config == null || store == null)
                throw new InvalidDataException("Backup import did not restore both config and gestures.");

            var storeType = store.GetType();
            var apps = (IDictionary)storeType.GetProperty("Apps").GetValue(store, null);
            var global = storeType.GetProperty("GlobalApp").GetValue(store, null);
            var gestureDictionary = global.GetType().GetProperty("GestureIntents").GetValue(global, null);
            var gestures = gestureDictionary.GetType().GetProperty("Values").GetValue(gestureDictionary, null);
            var gestureCount = CountEnumerable(gestures);

            if (gestureCount == 0)
                throw new InvalidDataException("Imported backup contains no global gestures.");

            var defaultGestures = Path.Combine(applicationDirectory, "defaults", "gestures.wg2");
            var defaults = Invoke(migrateService, "Import", defaultGestures);
            var defaultStore = defaults.GetType().GetProperty("GestureIntentStore").GetValue(defaults, null);
            var portableType = assembly.GetType("WGestures.App.Migrate.PortableConfigService", true);
            var portablePath = Path.ChangeExtension(outputPath, ".cgestures");
            Invoke(portableType, "Export", portablePath, defaultStore);
            var portableText = File.ReadAllText(portablePath);
            if (!portableText.Contains("\"portableFormat\": \"crossgestures-portable\""))
                throw new InvalidDataException("Portable export is missing its format marker.");
            var portableImported = Invoke(migrateService, "Import", portablePath);
            var portableStore = portableImported.GetType().GetProperty("GestureIntentStore")
                .GetValue(portableImported, null);
            var portableGlobal = portableStore.GetType().GetProperty("GlobalApp")
                .GetValue(portableStore, null);
            var portableValues = portableGlobal.GetType().GetProperty("GestureIntents")
                .GetValue(portableGlobal, null).GetType().GetProperty("Values")
                .GetValue(portableGlobal.GetType().GetProperty("GestureIntents")
                    .GetValue(portableGlobal, null), null);
            var portableGestureCount = CountEnumerable(portableValues);
            var summary = (string)portableImported.GetType().GetProperty("ImportSummary")
                .GetValue(portableImported, null);
            if (portableGestureCount == 0 || String.IsNullOrWhiteSpace(summary))
                throw new InvalidDataException("Portable import did not restore compatible gestures or its report.");

            var linuxGestureCount = 0;
            if (args.Length == 3)
            {
                var linuxImported = Invoke(migrateService, "Import", Path.GetFullPath(args[2]));
                var linuxStore = linuxImported.GetType().GetProperty("GestureIntentStore")
                    .GetValue(linuxImported, null);
                var linuxGlobal = linuxStore.GetType().GetProperty("GlobalApp")
                    .GetValue(linuxStore, null);
                var linuxIntents = linuxGlobal.GetType().GetProperty("GestureIntents")
                    .GetValue(linuxGlobal, null);
                linuxGestureCount = CountEnumerable(linuxIntents.GetType().GetProperty("Values")
                    .GetValue(linuxIntents, null));
                if (linuxGestureCount == 0)
                    throw new InvalidDataException("Windows could not import the Linux-generated portable config.");
            }

            Console.WriteLine("{{\"passed\":true,\"apps\":{0},\"globalGestures\":{1},\"portableGestures\":{2},\"linuxPortableGestures\":{3},\"bytes\":{4}}}",
                apps.Count, gestureCount, portableGestureCount, linuxGestureCount,
                new FileInfo(outputPath).Length);
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception);
            return 1;
        }
    }
}

using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using WGestures.Common.Config.Impl;
using WGestures.Common.OsSpecific.Windows;
using WGestures.Core;
using WGestures.Core.Impl.Windows;
using WGestures.Core.Persistence.Impl;
using WGestures.Core.Persistence.Impl.Windows;
using WGestures.View.Impl.Windows;

internal static class WindowsSharedSettingsSmoke
{
    private static object service;
    private static Type serviceType;
    private static string output;
    private static int result = 1;
    private static object Call(string name, params object[] args)
    {
        try { return serviceType.GetMethod(name).Invoke(service, args); }
        catch (TargetInvocationException error) { System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(error.InnerException).Throw(); throw; }
    }
    private static JObject Snapshot() { return (JObject)Call("Snapshot"); }
    private static JObject Change(string method, JObject parameters)
    {
        parameters["revision"] = Snapshot()["revision"];
        return (JObject)((JObject)Call("Mutate", method, parameters))["snapshot"];
    }
    private static void Check(bool value, string message) { if (!value) throw new Exception(message); }

    [STAThread]
    private static int Main(string[] args)
    {
        output = Path.GetFullPath(args[0]); Directory.CreateDirectory(output);
        var data = Path.Combine(output, "data"); Directory.CreateDirectory(data);
        Environment.SetEnvironmentVariable("CROSSGESTURES_USER_DATA_DIRECTORY", data);
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        var app = Assembly.LoadFrom(Path.Combine(Application.StartupPath, "CrossGestures.exe"));
        VerifyBrandingResources(app);
        var configPath = Path.Combine(data, "config.plist");
        var gesturesPath = Path.Combine(data, "gestures.wg2");
        File.Copy(Path.Combine(Application.StartupPath, "defaults", "config.plist"), configPath, true);
        File.Copy(Path.Combine(Application.StartupPath, "defaults", "gestures.wg2"), gesturesPath, true);
        var config = new PlistConfig(configPath);
        var store = new JsonGestureIntentStore(gesturesPath, "3");
        var tracker = new Win32MousePathTracker2 { TriggerButton = GestureTriggerButton.Right, StayTimeoutMillis = 500, InitialStayTimeoutMillis = 150 };
        var parser = new GestureParser(tracker, new Win32GestrueIntentFinder(store)) { Enable8DirGesture = true };
        var view = new CanvasWindowGestureView(parser);
        var hotkeys = new GlobalHotKeyManager();
        var controllerType = app.GetType("WGestures.App.Gui.Windows.SettingsFormController", true);
        var controller = Activator.CreateInstance(controllerType, new object[] { config, parser, tracker, store, view, hotkeys });
        serviceType = app.GetType("WGestures.App.Gui.Windows.SharedSettingsService", true);
        service = Activator.CreateInstance(serviceType, new object[] { controller });
        var form = (Form)controllerType.GetField("_form", BindingFlags.NonPublic | BindingFlags.Instance).GetValue(controller);
        try
        {
            Check(((JArray)Snapshot()["profiles"][0]["gestures"]).Count == 4, "Default gestures missing");
            Change("setting", new JObject { { "key", "path-width" }, { "value", 6.5 } });
            Check(view.PathWidth == 6.5f, "Trail width did not reach native renderer");
            Check(new PlistConfig(configPath).Get<double>("GesturePathWidth") == 6.5, "Fractional trail width was not persisted");
            Change("setting", new JObject { { "key", "fade-duration" }, { "value", 650 } });
            Check(view.FadeDuration == 650, "Fade duration did not reach native renderer");
            // Regression: the old setter compared against StayTimeoutMillis (500).
            Change("setting", new JObject { { "key", "initial-timeout" }, { "value", 500 } });
            Check(tracker.InitialStayTimeoutMillis == 500, "Initial timeout setter regression");
            var stale = Snapshot()["revision"].DeepClone();
            Change("setting", new JObject { { "key", "start-threshold" }, { "value", 17 } });
            bool rejected = false;
            try { Call("Mutate", "reset", new JObject { { "revision", stale } }); } catch (InvalidOperationException) { rejected = true; }
            Check(rejected, "Stale settings accepted");
            var gesture = new JObject { { "profileId", "global" }, { "name", "UI test" }, { "button", "x1" }, { "directions", new JArray("left") }, { "action", new JObject { { "type", "NoopAction" } } } };
            Change("gestureSave", gesture);
            rejected = false;
            try { Change("gestureSave", gesture); } catch (ArgumentException) { rejected = true; }
            Check(rejected, "Duplicate gesture accepted");
            var saved = ((JArray)Snapshot()["profiles"][0]["gestures"]).First(g => (string)g["name"] == "UI test");
            Change("gestureDelete", new JObject { { "profileId", "global" }, { "id", saved["id"] } });
            var profile = new JObject { { "name", "Test app" }, { "enabled", true }, { "inheritGlobal", true }, { "matchers", new JArray(new JObject { { "type", "executable" }, { "value", @"C:\Windows\notepad.exe" } }) } };
            Change("profileSave", profile);
            var profileId = Snapshot()["profiles"][1]["id"];
            Change("profileDelete", new JObject { { "id", profileId } });
            var portable = Path.Combine(output, "settings.cgestures");
            Call("Export", portable, "global");
            var preview = (JObject)Call("PrepareImport", portable);
            Change("importApply", new JObject { { "token", preview["token"] } });
            Check(((JArray)Snapshot()["profiles"][0]["gestures"]).Count == 4, "Import did not deduplicate gestures");
            Check(new JsonGestureIntentStore(gesturesPath, "3").GlobalApp.GestureIntents.Count == 4, "Saved configuration cannot be reopened");
            Console.WriteLine("Windows settings adapter: 10 checks passed.");
            var field = form.GetType().GetField("web", BindingFlags.NonPublic | BindingFlags.Instance);
            Check(field != null, "Shared settings host unavailable (WebView2 runtime required)");
            var web = (WebView2)field.GetValue(form);
            form.Shown += async delegate { await TestWebView(form, web); };
            var timeout = new Timer { Interval = 60000 };
            timeout.Tick += delegate { Console.Error.WriteLine("Windows settings UI timeout"); form.Close(); }; timeout.Start();
            Application.Run(form); timeout.Dispose();
        }
        catch (Exception error) { Console.Error.WriteLine(error); }
        finally
        {
            ((IDisposable)controller).Dispose(); view.Dispose(); hotkeys.Dispose(); tracker.Dispose();
        }
        return result;
    }

    private static async Task TestWebView(Form form, WebView2 web)
    {
        try
        {
            for (int i = 0; i < 300; i++)
            {
                if (web.CoreWebView2 != null && await web.CoreWebView2.ExecuteScriptAsync("typeof state !== 'undefined' && !!state") == "true") break;
                await Task.Delay(100);
            }
            Check(web.CoreWebView2 != null, "WebView2 initialization failed");
            await web.CoreWebView2.ExecuteScriptAsync("document.fonts.ready.then(()=>window.__fontsReady=true);'waiting'");
            for (int i = 0; i < 100 && await web.CoreWebView2.ExecuteScriptAsync("window.__fontsReady === true") != "true"; i++) await Task.Delay(50);
            Check(await web.CoreWebView2.ExecuteScriptAsync("Array.from(document.fonts).some(f=>f.family.includes('CrossGestures UI') && f.status==='loaded')") == "true", "Bundled UI font did not load");
            Check(await web.CoreWebView2.ExecuteScriptAsync("(()=>{const icon=document.querySelector('img.brand-icon');return !!icon && icon.complete && icon.naturalWidth>0;})()") == "true", "Shared application icon did not load");
            await Capture(web, "windows-general.png");
            await web.CoreWebView2.ExecuteScriptAsync("document.querySelector('[data-page=gestures]').click()");
            await Task.Delay(250);
            Check(await web.CoreWebView2.ExecuteScriptAsync("document.querySelectorAll('.gesture-item').length") == "4", "Shared gesture list did not render");
            await Capture(web, "windows-gestures.png");
            await web.CoreWebView2.ExecuteScriptAsync(@"
                document.querySelector('.toolbar .primary').click();
                document.querySelector('#dialog-body input').value='WebView test';
                document.querySelectorAll('#dialog-body select')[0].value='x2';
                document.querySelectorAll('.direction-tools button')[6].click();
                document.querySelectorAll('#dialog-body select')[1].value='NoopAction';
                document.querySelectorAll('#dialog-body select')[1].dispatchEvent(new Event('change'));
                document.querySelector('#dialog-form').requestSubmit();
            ");
            for (int i = 0; i < 100 && await web.CoreWebView2.ExecuteScriptAsync("document.querySelector('#modal').hidden") != "true"; i++) await Task.Delay(50);
            Check(await web.CoreWebView2.ExecuteScriptAsync("state.profiles[0].gestures.length") == "5", "Native WebView save failed");
            await web.CoreWebView2.ExecuteScriptAsync(@"
                const testGesture=state.profiles[0].gestures.find(g=>g.name==='WebView test');
                mutate('gestureDelete',{profileId:'global',id:testGesture.id});
            ");
            for (int i = 0; i < 100 && await web.CoreWebView2.ExecuteScriptAsync("state.profiles[0].gestures.length") != "4"; i++) await Task.Delay(50);
            Check(await web.CoreWebView2.ExecuteScriptAsync("state.profiles[0].gestures.length") == "4", "Native WebView delete failed");
            await web.CoreWebView2.ExecuteScriptAsync("editGesture(state.profiles[0].gestures[0])");
            await Task.Delay(200); await Capture(web, "windows-edit-gesture.png");
            await web.CoreWebView2.ExecuteScriptAsync("closeDialog();document.querySelector('[data-page=general]').click()");
            form.ClientSize = new Size(660, 600); await Task.Delay(300); await Capture(web, "windows-narrow.png");
            File.WriteAllText(Path.Combine(output, "result.json"), "{\"adapterChecks\":10,\"uiChecks\":6,\"brandingResources\":6,\"ok\":true}");
            Console.WriteLine("Windows WebView2: rendering, create, delete and dialog checks passed."); result = 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); }
        finally { form.Close(); }
    }
    private static async Task Capture(WebView2 web, string name)
    {
        using (var stream = File.Create(Path.Combine(output, name)))
            await web.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, stream);
    }

    private static void VerifyBrandingResources(Assembly app)
    {
        var manager = new System.Resources.ResourceManager("WGestures.App.Properties.Resources", app);
        var names = new[] { "icon", "icon_bw", "trayIcon", "trayIcon_bw", "trayIcon_light", "trayIcon_bw_light" };
        using (var sheet = new Bitmap(600, 140))
        using (var graphics = Graphics.FromImage(sheet))
        {
            graphics.Clear(Color.FromArgb(247, 245, 241));
            for (var i = 0; i < names.Length; i++)
            {
                var icon = manager.GetObject(names[i]) as Icon;
                Check(icon != null, "Missing icon resource: " + names[i]);
                foreach (var size in new[] { 16, 24, 32, 48, 64 })
                using (var frame = new Icon(icon, size, size))
                using (var bitmap = frame.ToBitmap())
                {
                    bool visible = false;
                    for (var y = 0; y < bitmap.Height && !visible; y++)
                        for (var x = 0; x < bitmap.Width && !visible; x++)
                            visible = bitmap.GetPixel(x, y).A > 0;
                    Check(visible, "Empty or invalid ICO frame: " + names[i] + " " + size);
                }
                if (i >= 4) graphics.FillRectangle(Brushes.DarkSlateGray, i * 100, 0, 100, 140);
                using (var frame = new Icon(icon, 32, 32))
                    graphics.DrawIcon(frame, new Rectangle(i * 100 + 34, 30, 32, 32));
                using (var frame = new Icon(icon, 16, 16))
                    graphics.DrawIcon(frame, new Rectangle(i * 100 + 42, 90, 16, 16));
            }
            sheet.Save(Path.Combine(output, "windows-icons.png"), System.Drawing.Imaging.ImageFormat.Png);
        }
        manager.ReleaseAllResources();
        Console.WriteLine("Windows branding: 6 resources decoded at 5 sizes.");
    }
}

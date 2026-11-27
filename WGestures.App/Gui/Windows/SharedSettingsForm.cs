using System;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace WGestures.App.Gui.Windows
{
    internal sealed class SharedSettingsForm : Form
    {
        private readonly SettingsFormController controller;
        private readonly SharedSettingsService service;
        private readonly WebView2 web;
        private readonly string entryUri;
        private bool starting;

        public static bool IsAvailable()
        {
            if (Environment.GetEnvironmentVariable("CROSSGESTURES_LEGACY_SETTINGS") == "1") return false;
            if (!File.Exists(Path.Combine(Application.StartupPath, "settings-ui", "index.html"))) return false;
            try { return !string.IsNullOrWhiteSpace(CoreWebView2Environment.GetAvailableBrowserVersionString()); }
            catch (Exception) { return false; }
        }

        public SharedSettingsForm(SettingsFormController controller)
        {
            this.controller = controller;
            service = new SharedSettingsService(controller);
            Text = "CrossGestures 设置";
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(1050, 780);
            MinimumSize = new Size(660, 540);
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.FromArgb(250, 249, 247);
            entryUri = new Uri(Path.Combine(Application.StartupPath, "settings-ui", "index.html")).AbsoluteUri;
            web = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = BackColor };
            Controls.Add(web);
            Shown += async (sender, args) => await InitializeAsync();
            Resize += (sender, args) =>
            {
                if (WindowState == FormWindowState.Minimized && controller.Config.Get("MinimizeToTray", true)) Hide();
            };
        }

        private async Task InitializeAsync()
        {
            if (starting) return;
            starting = true;
            try
            {
                var environment = await CoreWebView2Environment.CreateAsync(null,
                    Path.Combine(AppSettings.UserDataDirectory, "SettingsWebView"));
                await web.EnsureCoreWebView2Async(environment);
                var core = web.CoreWebView2;
                core.Settings.AreDevToolsEnabled = false;
                core.Settings.AreDefaultContextMenusEnabled = false;
                core.Settings.AreBrowserAcceleratorKeysEnabled = false;
                core.Settings.IsStatusBarEnabled = false;
                core.Settings.IsPasswordAutosaveEnabled = false;
                core.Settings.IsGeneralAutofillEnabled = false;
                core.NavigationStarting += (sender, args) => { if (!String.Equals(args.Uri, entryUri, StringComparison.Ordinal)) args.Cancel = true; };
                core.NewWindowRequested += (sender, args) => args.Handled = true;
                core.PermissionRequested += (sender, args) => args.State = CoreWebView2PermissionState.Deny;
                core.DownloadStarting += (sender, args) => args.Cancel = true;
                core.WebMessageReceived += MessageReceived;
                core.Navigate(entryUri);
            }
            catch (Exception error)
            {
                web.Visible = false;
                var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(32), FlowDirection = FlowDirection.TopDown };
                panel.Controls.Add(new Label { Text = "共享设置界面暂时无法启动：" + error.Message, AutoSize = true, MaximumSize = new Size(760, 0) });
                var fallback = new Button { Text = "打开兼容设置", AutoSize = true };
                fallback.Click += (sender, args) => ShowLegacy();
                panel.Controls.Add(fallback); Controls.Add(panel); panel.BringToFront();
            }
        }

        private void ShowLegacy()
        {
            using (var form = new SettingsForm(controller)) form.ShowDialog(this);
            controller.Config.Save(); controller.IntentStore.Save();
        }

        private void MessageReceived(object sender, CoreWebView2WebMessageReceivedEventArgs args)
        {
            if (!String.Equals(args.Source, entryUri, StringComparison.Ordinal)) return;
            JObject request = null;
            JObject response;
            try
            {
                request = JObject.Parse(args.WebMessageAsJson);
                if (request["id"] == null || request["id"].Type != JTokenType.Integer) throw new ArgumentException("无效设置请求。");
                var parameters = request["params"] as JObject ?? new JObject();
                var value = Dispatch((string)request["method"], parameters);
                response = new JObject { ["id"] = request["id"], ["result"] = value };
            }
            catch (Exception error) { response = new JObject { ["id"] = request?["id"], ["error"] = error.Message }; }
            if (!IsDisposed && web.CoreWebView2 != null) web.CoreWebView2.PostWebMessageAsJson(response.ToString(Formatting.None));
        }

        internal JToken Dispatch(string method, JObject parameters)
        {
            if (method == "snapshot") return service.Snapshot();
            if (method == "recognize") return service.Recognize(parameters["points"] as JArray);
            if (method == "legacy") { ShowLegacy(); return null; }
            if (method == "export")
            {
                using (var dialog = new SaveFileDialog { Filter = "CrossGestures 配置|*.cgestures", FileName = "CrossGestures.cgestures", DefaultExt = "cgestures" })
                {
                    if (dialog.ShowDialog(this) != DialogResult.OK) return null;
                    return new JObject { ["message"] = service.Export(dialog.FileName, (string)parameters["profileId"]) };
                }
            }
            if (method == "importPreview")
            {
                using (var dialog = new OpenFileDialog { Filter = "CrossGestures 配置|*.cgestures", CheckFileExists = true })
                {
                    if (dialog.ShowDialog(this) != DialogResult.OK) return null;
                    return service.PrepareImport(dialog.FileName);
                }
            }
            return service.Mutate(method, parameters);
        }
    }
}

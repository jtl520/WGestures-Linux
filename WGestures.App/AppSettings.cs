using System;
using System.Collections.Generic;
using System.Configuration;
using System.Linq;
using System.Text;
using System.Windows.Forms;
using WGestures.Common.Product;

namespace WGestures.App
{
    internal static class AppSettings
    {
        public static string UserDataDirectoryOverride { get; set; }

        public static string CheckForUpdateUrl
        {
            get
            {

#if DEBUG
                return ConfigurationManager.AppSettings.Get(Constants.CheckForUpdateUrlAppSettingKey);// "http://localhost:1226/projects/latestVersion?product=WGestures";

#else
                return ConfigurationManager.AppSettings.Get(Constants.CheckForUpdateUrlAppSettingKey);

#endif
            }
        }

        public static string ProductHomePage
        {
            get { return ConfigurationManager.AppSettings.Get(Constants.ProductHomePageAppSettingKey); }
        }

        public static string UserDataDirectory
        {
            // Keep the original WGestures data location so that rebranding does not
            // make existing Windows gesture and application profiles disappear.
            get
            {
                if (!string.IsNullOrWhiteSpace(UserDataDirectoryOverride))
                    return System.IO.Path.GetFullPath(UserDataDirectoryOverride);
                var overridePath = Environment.GetEnvironmentVariable(
                    "CROSSGESTURES_USER_DATA_DIRECTORY");
                if (!string.IsNullOrWhiteSpace(overridePath))
                    return System.IO.Path.GetFullPath(overridePath);
                return System.IO.Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "YingDev.com", "WGestures", Application.ProductVersion);
            }
        }



        public static string ConfigFilePath
        {
            get { return UserDataDirectory + @"\config.plist"; }
        }

        public static string GesturesFilePath
        {
            get { return UserDataDirectory + @"\gestures.wg2"; }
        }

        public static string PanelConfigFilePath
        {
            get { return UserDataDirectory + @"\panel-v1.json"; }
        }

        public static string DefaultGesturesFilePath
        {
            get { return Application.StartupPath + @"\defaults\gestures.wg2"; }
        }


        public static string ConfigFileVersion
        {
            get { return "1"; }
        }

        public static string GesturesFileVersion
        {
            get { return "3"; }
        }

    }
}

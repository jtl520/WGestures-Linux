
namespace WGestures.App
{
    internal static class Constants
    {
        public const string Identifier = "com.jtl520.CrossGestures";
        public const string AutoStartIdentifier = Identifier;
        public const string IpcPipeName = "CrossGestures_IPC_API";
        public const string CheckForUpdateUrlAppSettingKey = "CheckForUpdateUrl";

        public const string ProductHomePageAppSettingKey = "ProductHomePage";

#if DEBUG
        public const int AutoCheckForUpdateInterval = 1000 * 3;
#else 
        public const int AutoCheckForUpdateInterval = 1000*30;
#endif
    }
}

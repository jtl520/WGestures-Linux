using System;
using System.Drawing;
using System.IO;
using System.Net;
using System.Threading.Tasks;

namespace WGestures.App.QuickPanel
{
    /// <summary>
    /// 网址格子的站点图标：优先使用磁盘缓存中的 favicon（直接向目标网站
    /// 请求 https://主机/favicon.ico，不经过任何第三方服务），下载失败或
    /// 未完成时由调用方回退到通用图标。
    /// </summary>
    internal static class UrlFavicon
    {
        private const int MaxBytes = 256 * 1024;
        private const int TimeoutMilliseconds = 3000;

        public static string CacheDirectory()
        {
            return Path.Combine(WGestures.App.AppSettings.UserDataDirectory,
                "panel-icons");
        }

        public static string CachePathFor(string target)
        {
            var host = HostOf(target);
            return host == null ? null : Path.Combine(CacheDirectory(), host + ".ico");
        }

        public static string HostOf(string target)
        {
            Uri uri;
            if (!Uri.TryCreate((target ?? string.Empty).Trim(),
                    UriKind.Absolute, out uri) ||
                (uri.Scheme != Uri.UriSchemeHttps && uri.Scheme != Uri.UriSchemeHttp) ||
                string.IsNullOrWhiteSpace(uri.Host))
                return null;
            return uri.Host.ToLowerInvariant();
        }

        public static string FaviconUrl(string target)
        {
            var host = HostOf(target);
            return host == null ? null : "https://" + host + "/favicon.ico";
        }

        /// <summary>
        /// Direct favicon endpoints are preferred. Some otherwise public sites
        /// (including chatgpt.com) reject non-browser requests with 403, so use
        /// Google's favicon service as a final compatibility fallback. This is
        /// deliberately a fallback rather than the primary source.
        /// </summary>
        public static string[] CandidateUrls(string target)
        {
            var host = HostOf(target);
            if (host == null) return new string[0];
            return new[]
            {
                "https://" + host + "/favicon.ico",
                "https://www.google.com/s2/favicons?domain=" +
                    Uri.EscapeDataString(host) + "&sz=128",
            };
        }

        /// <summary>校验原始字节：必须是常见图片格式且大小合理。</summary>
        public static byte[] ValidateFaviconBytes(byte[] data)
        {
            if (data == null || data.Length < 24 || data.Length > MaxBytes)
                return null;
            if (data[0] == 0x89 && data[1] == 0x50 && data[2] == 0x4E && data[3] == 0x47)
                return data; // PNG
            if (data[0] == 0x00 && data[1] == 0x00 && data[2] == 0x01 && data[3] == 0x00)
                return data; // ICO
            if (data[0] == 0xFF && data[1] == 0xD8)
                return data; // JPEG
            if (data[0] == 0x47 && data[1] == 0x49 && data[2] == 0x46)
                return data; // GIF
            if (data[0] == 0x42 && data[1] == 0x4D)
                return data; // BMP
            return null;
        }

        public static bool TryGetCachedImage(string target, int size, out Image image)
        {
            image = null;
            var path = CachePathFor(target);
            if (path == null || !File.Exists(path)) return false;
            try
            {
                using (var source = new Bitmap(path))
                {
                    image = new Bitmap(source, new Size(size, size));
                    return true;
                }
            }
            catch (Exception)
            {
                // 缓存损坏：删除后走重新下载/兜底路径。
                try { File.Delete(path); } catch { }
                return false;
            }
        }

        /// <summary>后台下载站点图标并落盘。完成（无论成败）后回调一次。</summary>
        public static void FetchAsync(string target, Action<bool> onComplete)
        {
            var urls = CandidateUrls(target);
            if (urls.Length == 0)
            {
                if (onComplete != null) onComplete(false);
                return;
            }
            Task.Run(delegate
            {
                var succeeded = false;
                try
                {
                    byte[] bytes = null;
                    foreach (var url in urls)
                    {
                        try { bytes = Download(url); }
                        catch (Exception) { bytes = null; }
                        if (bytes != null) break;
                    }
                    if (bytes == null) return;
                    var path = CachePathFor(target);
                    Directory.CreateDirectory(Path.GetDirectoryName(path));
                    var temporary = path + ".tmp";
                    File.WriteAllBytes(temporary, bytes);
                    if (File.Exists(path))
                    {
                        try { File.Replace(temporary, path, null); }
                        catch (PlatformNotSupportedException)
                        {
                            File.Delete(path);
                            File.Move(temporary, path);
                        }
                    }
                    else File.Move(temporary, path);
                    succeeded = true;
                }
                catch (Exception)
                {
                    // Offline or all endpoints failed: retain the fallback icon.
                }
                finally
                {
                    if (onComplete != null) onComplete(succeeded);
                }
            });
        }

        private static byte[] Download(string url)
        {
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Timeout = TimeoutMilliseconds;
            request.ReadWriteTimeout = TimeoutMilliseconds;
            request.AllowAutoRedirect = true;
            request.UserAgent = "CrossGestures/2.1 quick-panel favicon";
            using (var response = request.GetResponse())
            {
                if (((HttpWebResponse)response).StatusCode != HttpStatusCode.OK)
                    return null;
                using (var stream = response.GetResponseStream())
                using (var buffer = new MemoryStream())
                {
                    var chunk = new byte[8192];
                    int read;
                    while ((read = stream.Read(chunk, 0, chunk.Length)) > 0)
                    {
                        buffer.Write(chunk, 0, read);
                        if (buffer.Length > MaxBytes) return null;
                    }
                    return ValidateFaviconBytes(buffer.ToArray());
                }
            }
        }
    }
}

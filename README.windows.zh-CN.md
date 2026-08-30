# CrossGestures Windows 安装与开发说明

本仓库重新启用了原版 Windows C# 后端，并与 Ubuntu、Kali 等 Linux 后端并行维护。
Windows 与 Linux 使用各自原生的输入后端和设置界面，不是在 Windows 上运行 Linux
程序，也不要求 WSL。

## 支持范围

| 系统 | 支持级别 | 说明 |
| --- | --- | --- |
| Windows 11 x64 | 主要目标 | 优先修复和发布；使用 64 位安全的低级鼠标/键盘钩子 |
| Windows 10 x86/x64 | 主要目标 | 与 Windows 11 使用同一 Win32 后端 |
| Windows 8.1 | 兼容目标 | 需要先安装 .NET Framework 4.8 |
| Windows 7 SP1 | 兼容目标 | 需要 .NET Framework 4.8；系统本身已停止安全支持 |
| Windows 8.0 | 不支持 | .NET Framework 4.8 不支持 Windows 8.0，请升级到 8.1 或更高版本 |

“兼容目标”表示工程和安装器保留相应系统版本，但 GitHub Actions 没有 Windows
7/8.1 Runner。正式发布前仍应在对应虚拟机中完成下面的手工验收，不能只凭编译
成功宣称实机兼容。

## 安装

从 GitHub Releases 下载：

```text
CrossGestures-2.1.8.0-Windows-Setup.exe
```

双击安装并同意一次 Windows UAC 提示。安装器会安装到：

```text
%ProgramFiles%\CrossGestures
```

Windows 公开构建没有原作者的 UIAccess 私钥证书，因此使用管理员权限保证鼠标钩子
和快捷键能覆盖 Codex、管理员终端等受 UIPI 保护的窗口。首次启动会创建当前用户
配置，并注册“最高权限”登录任务；以后登录后台启动不会重复弹出 UAC。安装器会检查
.NET Framework 4.8；缺少时会打开微软官方下载页。

应用使用 `AnyCPU` 且禁用 `Prefer32Bit`：在 x64 Windows 上作为 64 位进程运行，
在 x86 Windows 上作为 32 位进程运行。安装器相应地在 x64 系统使用原生
`Program Files` 和 64 位注册表视图，在 x86 系统保留 32 位安装模式。

公开 CI 在没有代码签名证书时会生成未签名安装器，因此 Windows SmartScreen
可能显示“未知发布者”。正式公开发布建议在仓库 Secrets 中配置：

- `WINDOWS_CERTIFICATE_BASE64`：PFX 文件的 Base64 内容；
- `WINDOWS_CERTIFICATE_PASSWORD`：PFX 密码。

发布工作流会在配置证书后分别签名 `CrossGestures.exe` 和最终安装器，并添加可信时间戳。

## 卸载

在“设置 → 应用 → 已安装的应用”中搜索完整名称
`CrossGestures version 2.1.8.0`。如果应用列表没有及时刷新，可直接运行：

```powershell
Stop-Process -Name CrossGestures -Force -ErrorAction SilentlyContinue
& "$env:ProgramFiles\CrossGestures\unins000.exe"
```

卸载器会删除程序、开始菜单快捷方式和卸载登记，但默认保留
`%LOCALAPPDATA%\YingDev.com\WGestures\` 下的用户手势。确定不再使用时再清理该
目录；建议先导出 `.cgestures` 跨平台备份。

## 中键 4×4 快捷面板

在设置的“常规”页勾选“中键面板”后，短按并释放中键会在鼠标附近显示
4×4 面板。空格右键直接显示“启动软件、打开文件、打开文件夹、打开网址”，已有
格子右键可编辑或删除；支持启动 EXE/Windows 快捷方式、用默认程序打开文件、
用资源管理器打开文件夹，以及打开 HTTP/HTTPS
网址。再次中键、Esc、点击面板外或执行格子都会关闭面板。

还可以把 EXE/快捷方式、文件或文件夹从资源管理器直接拖到空格子快速创建条目；
一次拖入多个目标时会依次填入后续空格子，拖到已配置的格子会被拒绝，不会覆盖。
悬停格子会显示编辑对话框里填写的“功能/用途说明”，未填写时显示动作类型和目标；
未配置的空格子显示半透明的加号提示。软件格子勾选“如果程序已运行，激活已
打开的窗口”后，点击格子会优先把已打开的窗口切到前台（支持 `.lnk` 解析），
找不到运行中的进程才启动新实例。面板打开时右键和 X1/X2 手势照常可用，
只有面板表面上的按键让给格子交互；编辑对话框输入框中的手势也不受影响。
软件/文件格子的图标由 shell 解析（快捷方式显示目标程序的真实图标）；
网址格子的图标会自动向目标网站请求 `favicon.ico`（直连、3 秒超时、
`panel-icons` 目录缓存；目标站返回 403 等错误时使用 Google favicon 兼容接口，
全部失败才回退地球图标）。面板被截图工具等全屏覆盖层
挡住失焦通知而收不起来时，失焦数秒后由看门狗自动收起。
程序和快捷方式图标在后台解析，网址图标下载完成后会替换临时地球图标；
未变化的 16 个格子不会在每次显示时重复刷新；面板在启动阶段于虚拟桌面外
预建，中键按下即响应，连续请求按奇偶合并，避免 UI 线程处理过时开关队列。

启用面板时中键专用于面板，不会开始手势，也不会把原生中键点击泄漏给目标程序；
超过系统拖动阈值的中键移动会取消本次输入。关闭该开关、全局暂停/禁用或“全屏时
禁用”生效时，中键仍是目标程序的一次普通原生点击。右键和 X1/X2 手势不变。

面板配置独立保存在当前版本用户目录的 `panel-v1.json`，采用原子替换并保留最近
有效的 `.bak`。它不会写入 `.cgestures`，卸载程序也默认保留该文件。

## 与 Linux 互传手势

Windows 设置的导出对话框默认生成 `.cgestures`，Ubuntu/Kali 的“导入与恢复”页
可以直接读取；Windows 只导出“手势”页当前选中列表中的项目，不会夹带其他应用
配置中的手势。Linux 导出的同格式文件也可在 Windows 导入。快捷键、复制/粘贴、
常用窗口动作、网址、暂停和空动作可直接迁移。平台专属的 CMD、Lua、Shell 命令、
Desktop ID、Windows 文件路径和修饰/滚轮手势会在兼容性报告中列为跳过，不会被
自动执行。若要无损保存所有 Windows 专属设置，请在导出类型中改选 `.wgb` 完整备份。

## Windows 11 注意事项

- Windows 11 默认可能把新托盘图标放入“隐藏的图标”区域。也可以再次运行
  CrossGestures，或从开始菜单点击“CrossGestures 设置”。
- 快捷键会发送给手势开始时锁定的目标窗口，并以带短间隔的完整按下/释放序列注入，
  兼容 Chromium、WebView2 和 Codex 等现代输入框。上下左右等单方向手势允许约
  ±35° 的绘制误差，轻微画斜不会导致复制、粘贴失效。
- Windows Terminal（包括其中运行的 CMD 和 PowerShell）使用原生
  `Ctrl+Shift+C`、`Ctrl+Shift+V`；传统 Console Host 使用
  `Ctrl+Insert`、`Shift+Insert`。旧配置中的系统菜单复制/粘贴序列会自动纠正。
- 当前公开构建将 `uiAccess` 设为 `false`，避免依赖原作者已不可用的私钥证书；作为
  无签名替代方案，Release 版请求管理员权限，并用最高权限计划任务完成后台自启动。
- 为兼容旧版，应用配置继续保存在 `%LOCALAPPDATA%\YingDev.com\WGestures\` 下；升级程序不会
  主动删除旧版本配置。

## 本地构建

需要 Windows、Visual Studio 2019/2022 Build Tools 和 NuGet CLI。Visual Studio
应安装“.NET 桌面生成工具”。然后运行：

```powershell
./tools/build-windows.ps1
```

脚本会完成：

1. 恢复 NuGet 依赖；
2. 获取缺失的 .NET Framework 4.8 引用程序集；
3. 编译 `CrossGestures.exe`；
4. 执行 Windows 构建完整性检查；
5. 使用固定版本 Inno Setup 6.4.3 生成 `.exe` 安装程序；
6. 输出安装器路径和 SHA-256。

产物位于：

```text
build\windows\CrossGestures-2.1.8.0-Windows-Setup.exe
```

原 `WGInstall` WixSharp/MSI 工程仍作为历史参考保留，但默认解决方案构建不再执行
它。正式 Windows 发布以 `packaging/windows/CrossGestures.iss` 生成的 EXE 安装器为准。

## 发布前实机验收

每个声称支持的 Windows 版本至少检查：

1. 安装、升级和卸载成功，卸载后用户配置仍保留；
2. 首次运行、托盘图标和开始菜单“设置”入口正常；
3. 右键短按仍显示原生右键菜单；
4. 中键面板启用时不泄漏点击，关闭时恢复原生中键；右键和 X1/X2 手势不受影响；
5. 快捷键、窗口控制、打开网址/文件、命令行和暂停动作正常；
6. Explorer 重启、睡眠恢复、锁屏再登录后仍能工作；
7. 100%、150%、200% DPI 以及多显示器下轨迹位置可接受；
8. 普通应用、浏览器、文件管理器和终端内没有按键粘连；
9. x64 系统同时验证 64 位和 32 位目标应用；
10. SmartScreen、杀毒软件和签名状态符合发布预期。

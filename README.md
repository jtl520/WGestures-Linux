# CrossGestures — Linux 与 Windows

CrossGestures 是面向 Windows、Ubuntu、Kali 和其他 Debian 系桌面的全局鼠标手势软件。
Linux 版本采用双后端：GNOME Shell 扩展负责 Ubuntu 24.04 Wayland，
Python/GTK3 常驻进程负责 Ubuntu 18.04、Kali Xfce 及其他 X11 桌面。

原 Windows C# 工程现已重新纳入构建和发布：Win32 后端负责 Windows 7 SP1、
Windows 8.1、Windows 10 和 Windows 11，其中 Windows 10/11 是主要目标。
Linux 与 Windows 构建彼此独立，并由各自的 CI 工作流验证。
两端设置界面都可导入、导出 `.cgestures` 跨平台配置；通用手势可直接迁移，
平台专属动作会明确报告并安全跳过。

## 支持范围

| 系统 | 桌面会话 | 后端 | 支持级别 |
| --- | --- | --- | --- |
| Ubuntu 24.04 | GNOME 46 / Wayland | GNOME Shell 扩展 | 主力目标 |
| Ubuntu 18.04 | GNOME / Xorg | Python/GTK3 X11 | 兼容目标 |
| Kali 2026.2 | Xfce / X11 | Python/GTK3 X11 | 兼容目标 |
| 其他 Debian 系桌面 | X11 | Python/GTK3 X11 | 尽力兼容 |
| Windows 11 | Win32 | C#/.NET Framework 4.8 | 主要目标 |
| Windows 10 | Win32 | C#/.NET Framework 4.8 | 主要目标 |
| Windows 8.1 | Win32 | C#/.NET Framework 4.8 | 兼容目标 |
| Windows 7 SP1 | Win32 | C#/.NET Framework 4.8 | 兼容目标 |

GNOME/KDE 的其他 Wayland 组合暂不支持。Ubuntu 18.04 已结束标准安全支持；
这里的兼容声明仅针对 CrossGestures 本身。

Windows 8.0 不支持，因为 .NET Framework 4.8 不支持该系统。Windows 7 SP1 和
Windows 8.1 已结束系统安全支持，而且 GitHub Actions 没有对应 Runner；发布前仍
需要在虚拟机完成实机验收。Windows 安装和构建说明见
[Windows 中文说明](README.windows.zh-CN.md)。

## Windows 10/11 安装

从 [GitHub Releases](https://github.com/jtl520/WGestures-Linux/releases/latest)
下载并运行：

```text
CrossGestures-2.1.2.0-Windows-Setup.exe
```

安装器按当前用户安装，不需要管理员权限，并会检查 .NET Framework 4.8。
Windows 11 可能把托盘图标放入隐藏区域；也可以从开始菜单打开
“CrossGestures 设置”。

## 卸载

### Windows

先从托盘菜单退出 CrossGestures，然后在“设置 → 应用 → 已安装的应用”中搜索
完整名称 `CrossGestures version 2.1.2.0` 并卸载。如果 Windows 应用列表尚未刷新，
可直接运行当前用户安装目录中的卸载器：

```powershell
Stop-Process -Name CrossGestures -Force -ErrorAction SilentlyContinue
& "$env:LOCALAPPDATA\Programs\CrossGestures\unins000.exe"
```

卸载程序默认保留 `%LOCALAPPDATA%\YingDev.com\WGestures\` 下的手势配置，方便
以后重装。确认不再需要时再手工清理；建议先导出 `.cgestures`。

### Ubuntu / Kali

在当前桌面普通用户的终端中停用手势，再卸载软件包：

```sh
wgestures --disable
sudo apt purge --simulate wgestures
sudo apt purge wgestures
```

用户配置 `~/.config/wgestures/` 默认保留。更详细的进程、自启动、GNOME 扩展和
配置清理步骤见[中文卸载说明](README.uninstall.zh-CN.md)。

## Ubuntu 24.04 安装（推荐）

Ubuntu 24.04 GNOME 46 Wayland 是本项目的主要支持环境。请在普通桌面用户的
终端中执行以下步骤，不要使用 root 用户运行 `wgestures` 命令。

### 1. 确认桌面会话

```sh
gnome-shell --version
echo "$XDG_CURRENT_DESKTOP / $XDG_SESSION_TYPE"
```

正常应看到 GNOME Shell `46.x`、桌面包含 `GNOME`、会话类型为 `wayland`。
如果显示 `x11`，CrossGestures 会改用 X11 后端；KDE Wayland、GNOME 47 及更高版本
目前不在本版支持范围内。

### 2. 下载并安装

从 [GitHub Releases](https://github.com/jtl520/WGestures-Linux/releases/latest)
下载 `wgestures_2.1.2ubuntu8_all.deb`，保存到“下载”目录，然后运行：

```sh
cd ~/Downloads
sudo apt update
sudo apt install ./wgestures_2.1.2ubuntu8_all.deb
```

必须使用 `apt install ./文件名.deb`，文件名前的 `./` 不能省略。APT 会自动安装
软件包声明的 Python、GTK 和 GSettings 依赖，正常联网时无需提前逐个安装依赖。
不建议直接使用 `sudo dpkg -i`，因为 `dpkg` 不会自动解决缺少的依赖。

### 3. 首次注销并启用

系统级 GNOME Shell 扩展首次安装后，当前 Shell 通常还不能立即发现它。完整注销
当前桌面用户（只关闭终端、锁屏或重启应用无效），重新登录 Ubuntu Wayland
会话，然后运行：

```sh
wgestures --enable
wgestures --resume
wgestures --status
wgestures --diagnose
```

正常结果应包含 `enabled=true`、`paused=false`，诊断后端应为
`gnome46-wayland`，且不应报告缺少依赖。随后打开设置：

```sh
wgestures --settings
```

扩展启用状态由 GNOME 保存，以后登录时会自动加载，无需每次手动执行
`wgestures --enable`。GNOME Wayland 使用顶部面板指示器，不显示传统 X11
系统托盘图标。

### 4. 安装后的默认手势

- 按住右键向上：智能复制。终端发送 `Ctrl+Shift+C`，其他软件发送 `Ctrl+C`。
- 按住右键向下：智能粘贴。终端发送 `Ctrl+Shift+V`，其他软件发送 `Ctrl+V`。
- 按住右键依次“上 → 右 → 上”：窗口置顶/取消置顶。
- 短按右键仍然只产生一次普通右键单击。

### 5. Ubuntu 24.04 注意事项

- 所有 `wgestures --enable`、`--settings` 和 `--diagnose` 命令都应由当前桌面
  普通用户运行；加 `sudo` 会操作 root 的配置，而不是正在登录的用户。
- Wayland 后端依赖 GNOME Shell 扩展。首次安装后如果提示“尚未发现扩展”，
  请确认已经完整注销并重新登录，而不是反复重新安装 `.deb`。
- 升级和卸载不会删除 `~/.config/wgestures`。升级也不会静默覆盖已有手势；
  新增的默认手势只会在首次生成配置或“恢复默认值”后出现。
- “恢复默认值”会替换现有手势配置。已有自定义配置时请先在“导入与恢复”页
  导出备份，或手动添加新的置顶手势。
- GNOME 扩展负责后台运行和顶部面板入口；关闭设置窗口不会停用鼠标手势。
- 本版只承诺 GNOME Shell 46。系统升级到新的 GNOME 大版本前，请先查看项目
  Release 中的兼容说明。

## Ubuntu 18.04、Kali 与其他 Debian 系安装

从仓库的 **Releases** 页面下载：

```text
wgestures_2.1.2ubuntu8_all.deb
```

联网安装时依赖会由 APT 自动解决：

```sh
cd ~/Downloads
sudo apt update
sudo apt install ./wgestures_2.1.2ubuntu8_all.deb
wgestures --diagnose
```

- Ubuntu 18.04、Kali Xfce 和其他 X11 桌面：运行 `wgestures --enable`
  即可立即启动，后续登录图形桌面会自动后台运行。
- 使用 `wgestures --settings` 打开设置。
- 快捷键直接填写 `Ctrl+C`；同时兼容 `Control+C`、`Ctrl C` 和旧写法 `<Control>c`。
- “智能复制”动作让同一手势在终端发送 `Ctrl+Shift+C`，在其他软件发送 `Ctrl+C`。
- “智能粘贴”动作让同一手势在终端发送 `Ctrl+Shift+V`，在其他软件发送 `Ctrl+V`。
- 单方向手势提供约 ±35° 的轨迹容错，鼠标按钮和精确多段手势仍严格匹配。
- 默认预置右键向上复制、右键向下粘贴和右键“上→右→上”切换窗口置顶。
- X11 登录后自动启动并显示托盘菜单；GNOME 46 Wayland 使用顶部面板指示器。
- “常规”页可由用户开关登录自启动和最小化/关闭到托盘。
- 成功提示优先显示手势名称，默认 300 毫秒淡出。

详细步骤见[中文安装说明](README.install.zh-CN.md)，移除程序和清理用户配置见
[中文卸载说明](README.uninstall.zh-CN.md)。完整功能、构建方式和测试门槛见
[Linux 开发说明](README.ubuntu.md)。

## 常用命令

```sh
wgestures --settings
wgestures --enable        # 或 --disable
wgestures --pause         # 或 --resume
wgestures --status
wgestures --diagnose
wgestures --diagnose --json
```

用户配置保存在 `$XDG_CONFIG_HOME/wgestures/gestures-v1.json`。安装、升级或
卸载 `.deb` 均不会删除用户配置。

## Windows / Linux 配置互传

在任一平台的“导入与恢复”或导出入口选择 `.cgestures`。可直接互传的内容包括
普通方向手势、右/中/X1/X2 触发键、快捷键、复制/粘贴、常用窗口控制、网址、
暂停和空动作。Linux Shell 命令、Desktop ID、Windows CMD/Lua/文本输入、Windows
文件路径及修饰/滚轮手势没有可靠的跨平台等价项，因此不会被悄悄转换；导入或
导出完成后会显示兼容数量和跳过原因。Windows 专用的 `.wgb` 完整备份仍保留。

## 源码结构

- `gnome-extension/`：GNOME Shell 46 Wayland 扩展和 Libadwaita 设置页。
- `linux/`：兼容 Python 3.6 的 X11 后端、GTK3 设置页及单元测试。
- `packaging/`、`debian/`：命令入口、自动启动、man page 和 Debian 打包。
- `tests/fixtures/`：JavaScript/Python 双后端共用的一致性测试向量。
- `tools/`：Kali、Ubuntu X11 与 GNOME Wayland 验收工具。
- `WGestures.*`、`WindowsInput/`：Windows Win32 后端、设置程序及动作实现。
- `packaging/windows/`：Windows EXE 安装器定义。
- `WGInstall/`：旧 WixSharp/MSI 安装器参考工程，默认不再参与构建。

## 构建

Ubuntu 24.04：

```sh
sudo apt install build-essential debhelper libglib2.0-bin nodejs npm \
  python3 python3-gi python3-cairo python3-gi-cairo python3-xlib \
  gir1.2-gtk-3.0 zip lintian
make -f Makefile.ubuntu check
make -f Makefile.ubuntu test
make -f Makefile.ubuntu deb
```

Windows Release 和 EXE 安装器：

```powershell
./tools/build-windows.ps1
```

## 当前验证状态

- Python 核心与 X11 测试：33/33 通过（Kali 原生依赖环境）。
- GNOME JavaScript 核心测试：23/23 通过。
- GSettings schema、Debian 构建和 `lintian` 检查通过。
- Kali 2026.2 Xfce/X11：完整手势、动作、性能、安装升级卸载验收通过。
- Windows Release 工程和 EXE 安装器已在 Windows NT build 26200 完成真实编译；
  x64 安全钩子、真实低级鼠标输入、Esc 取消、压力恢复、单实例和跨平台配置往返
  均通过本机自动验收。
- Ubuntu 24.04 GNOME Wayland 和 Ubuntu 18.04 GNOME/Xorg：仍建议在目标机器上
  按 `README.ubuntu.md` 的验收清单完成实机确认。

## 许可证与来源

继续采用仓库原有的 [GPL-2.0 许可证](LICENSE)。原项目由 Ying Yuandong 创建：
[yingDev/WGestures](https://github.com/yingDev/WGestures)。Linux 移植继续保留
原作者署名和许可证声明。

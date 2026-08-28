# WGestures Linux

WGestures 是面向 Ubuntu、Kali 和其他 Debian 系桌面的全局鼠标手势软件。
Linux 版本采用双后端：GNOME Shell 扩展负责 Ubuntu 24.04 Wayland，
Python/GTK3 常驻进程负责 Ubuntu 18.04、Kali Xfce 及其他 X11 桌面。

原 Windows C# 工程仍保留在仓库中，作为算法、配置兼容和 GPL-2.0 来源参考；
Linux 构建不依赖这些 Windows 工程。

## 支持范围

| 系统 | 桌面会话 | 后端 | 支持级别 |
| --- | --- | --- | --- |
| Ubuntu 24.04 | GNOME 46 / Wayland | GNOME Shell 扩展 | 主力目标 |
| Ubuntu 18.04 | GNOME / Xorg | Python/GTK3 X11 | 兼容目标 |
| Kali 2026.2 | Xfce / X11 | Python/GTK3 X11 | 兼容目标 |
| 其他 Debian 系桌面 | X11 | Python/GTK3 X11 | 尽力兼容 |

GNOME/KDE 的其他 Wayland 组合暂不支持。Ubuntu 18.04 已结束标准安全支持；
这里的兼容声明仅针对 WGestures 本身。

## Ubuntu 24.04 安装（推荐）

Ubuntu 24.04 GNOME 46 Wayland 是本项目的主要支持环境。请在普通桌面用户的
终端中执行以下步骤，不要使用 root 用户运行 `wgestures` 命令。

### 1. 确认桌面会话

```sh
gnome-shell --version
echo "$XDG_CURRENT_DESKTOP / $XDG_SESSION_TYPE"
```

正常应看到 GNOME Shell `46.x`、桌面包含 `GNOME`、会话类型为 `wayland`。
如果显示 `x11`，WGestures 会改用 X11 后端；KDE Wayland、GNOME 47 及更高版本
目前不在本版支持范围内。

### 2. 下载并安装

从 [GitHub Releases](https://github.com/jtl520/WGestures-Linux/releases/latest)
下载 `wgestures_2.1.2ubuntu6_all.deb`，保存到“下载”目录，然后运行：

```sh
cd ~/Downloads
sudo apt update
sudo apt install ./wgestures_2.1.2ubuntu6_all.deb
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
wgestures_2.1.2ubuntu6_all.deb
```

联网安装时依赖会由 APT 自动解决：

```sh
cd ~/Downloads
sudo apt update
sudo apt install ./wgestures_2.1.2ubuntu6_all.deb
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

详细步骤见[中文安装说明](README.install.zh-CN.md)。完整功能、构建方式和
测试门槛见 [Linux 开发说明](README.ubuntu.md)。

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

## 源码结构

- `gnome-extension/`：GNOME Shell 46 Wayland 扩展和 Libadwaita 设置页。
- `linux/`：兼容 Python 3.6 的 X11 后端、GTK3 设置页及单元测试。
- `packaging/`、`debian/`：命令入口、自动启动、man page 和 Debian 打包。
- `tests/fixtures/`：JavaScript/Python 双后端共用的一致性测试向量。
- `tools/`：Kali、Ubuntu X11 与 GNOME Wayland 验收工具。
- `WGestures.*`、`WGInstall/`、`WindowsInput/`：原 Windows 版本参考源码。

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

## 当前验证状态

- Python 核心与 X11 测试：25/25 通过（Kali 原生依赖环境）。
- GNOME JavaScript 核心测试：21/21 通过。
- GSettings schema、Debian 构建和 `lintian` 检查通过。
- Kali 2026.2 Xfce/X11：完整手势、动作、性能、安装升级卸载验收通过。
- Ubuntu 24.04 GNOME Wayland 和 Ubuntu 18.04 GNOME/Xorg：仍建议在目标机器上
  按 `README.ubuntu.md` 的验收清单完成实机确认。

## 许可证与来源

继续采用仓库原有的 [GPL-2.0 许可证](LICENSE)。原项目由 Ying Yuandong 创建：
[yingDev/WGestures](https://github.com/yingDev/WGestures)。Linux 移植继续保留
原作者署名和许可证声明。

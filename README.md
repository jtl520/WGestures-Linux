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

## 下载与安装

从仓库的 **Releases** 页面下载：

```text
wgestures_2.1.2ubuntu1_all.deb
```

联网安装时依赖会由 APT 自动解决：

```sh
cd ~/Downloads
sudo apt update
sudo apt install ./wgestures_2.1.2ubuntu1_all.deb
wgestures --diagnose
```

- Ubuntu 24.04 GNOME Wayland：首次安装后注销并重新登录一次，然后运行
  `wgestures --enable`。
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
  python3 python3-gi python3-cairo python3-xlib gir1.2-gtk-3.0 zip lintian
make -f Makefile.ubuntu check
make -f Makefile.ubuntu test
make -f Makefile.ubuntu deb
```

## 当前验证状态

- Python 核心与 X11 测试：18/18 通过。
- GNOME JavaScript 核心测试：15/15 通过。
- Kali 2026.2 Xfce/X11：完整手势、动作、性能、安装升级卸载验收通过。
- Ubuntu 24.04 GNOME Wayland 和 Ubuntu 18.04 GNOME/Xorg：仍建议在目标机器上
  按 `README.ubuntu.md` 的验收清单完成实机确认。

## 许可证与来源

继续采用仓库原有的 [GPL-2.0 许可证](LICENSE)。原项目由 Ying Yuandong 创建：
[yingDev/WGestures](https://github.com/yingDev/WGestures)。Linux 移植继续保留
原作者署名和许可证声明。

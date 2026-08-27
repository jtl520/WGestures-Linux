# WGestures Linux 安装说明

本文适用于当前构建的 `wgestures_2.1.2ubuntu1_all.deb`。

## 1. 支持的桌面会话

| 系统 | 需要使用的会话 | 后端 |
| --- | --- | --- |
| Ubuntu 24.04 | GNOME 46 / Wayland | GNOME Shell 扩展 |
| Ubuntu 18.04 | GNOME / Xorg | X11 后台进程 |
| Kali Xfce | X11 | X11 后台进程 |
| 其他 Debian 系桌面 | X11 | 尽力兼容 |

先在目标机器的普通用户桌面终端中检查会话：

```sh
echo "$XDG_CURRENT_DESKTOP / $XDG_SESSION_TYPE"
```

Ubuntu 24.04 应看到 `GNOME` 和 `wayland`。Ubuntu 18.04、Kali Xfce
应看到 `x11`。KDE Wayland、非 GNOME 46 的 GNOME Wayland 以及其他
Wayland 合成器目前不支持；请在登录界面选择 X11/Xorg 会话。

## 2. 安装前是否需要手动安装依赖

正常联网时不需要。依赖已经声明在 `.deb` 中，使用 `apt install` 安装
本地软件包时会自动下载并安装：

- Python 3.6 或更高版本；
- `python3-xlib`；
- `python3-gi` 和 `gir1.2-gtk-3.0`；
- `python3-cairo`；
- GSettings/dconf 后端。

不要把 `dpkg -i` 作为首选安装命令，因为 `dpkg` 不会自动下载缺少的依赖。
Ubuntu 24.04 桌面版已有 GNOME Shell，无需另外安装桌面环境。

## 3. 联网安装（推荐）

把安装包复制到目标机器，例如放进 `~/Downloads`，然后运行：

```sh
cd ~/Downloads
sudo apt update
sudo apt install ./wgestures_2.1.2ubuntu1_all.deb
```

本地文件名前面的 `./` 不能省略。安装后先运行诊断：

```sh
wgestures --diagnose
```

诊断不应出现“缺少依赖”。然后根据桌面会话完成下面对应的首次启用步骤。

## 4. Ubuntu 24.04 GNOME 46 / Wayland 首次启用

系统级 GNOME 扩展第一次安装后，GNOME Shell 可能要重新登录才能发现它：

1. 注销当前桌面用户；
2. 在登录界面重新进入 Ubuntu Wayland 会话；
3. 打开终端并运行：

```sh
wgestures --enable
wgestures --status
wgestures --diagnose
```

诊断中的后端应为 `gnome46-wayland`。打开设置：

```sh
wgestures --settings
```

扩展启用状态由 GNOME 保存，以后登录桌面时会自动加载，不需要每次手动运行。

如果 `wgestures --enable` 提示 Shell 尚未发现扩展，请确认已经注销并重新登录，
而不是只关闭终端或锁屏。

## 5. Ubuntu 18.04 / Kali Xfce / 其他 X11 桌面首次启用

在普通桌面用户的终端中运行：

```sh
wgestures --enable
wgestures --status
wgestures --diagnose
```

`--enable` 会立即启动当前用户的 X11 后台进程。诊断结果应满足：

- 后端为 `x11`；
- `X11/XTEST` 显示已连接/可用；
- 按钮抓取状态为活动状态；
- 没有缺少 `gi`、`pythonXlib` 或 `cairo`。

安装包同时提供 `/etc/xdg/autostart/wgestures-autostart.desktop`。以后每次
该用户登录图形桌面时，WGestures 会在后台自动运行；它不是 root 服务，也不会
在无人登录时抓取输入。打开设置：

```sh
wgestures --settings
```

## 6. 基本使用与状态命令

默认触发键是鼠标右键。短按右键仍产生一次普通右键单击；按住右键并移动形成
有效手势后，原右键菜单不会弹出。

快捷键按常见格式填写，例如复制填写 `Ctrl+C`，终端复制填写
`Ctrl+Shift+C`。`Control+C`、`Ctrl C`、`control c` 以及旧配置中的
`<Control>c` 也兼容；设置界面会统一显示为 `Ctrl+C`。

如果希望同一个鼠标手势在所有软件中复制，请把“动作类型”选为
“智能复制（自动适配终端）”。它会在 GNOME Terminal、Xfce Terminal、
Ptyxis、Konsole 等终端发送 `Ctrl+Shift+C`，在浏览器、编辑器、办公软件等
普通窗口发送 `Ctrl+C`。不要用连续发送两组按键代替，否则终端中的
`Ctrl+C` 可能中断正在运行的命令。

粘贴同理，把另一个手势的“动作类型”选为“智能粘贴（自动适配终端）”：
终端中自动发送 `Ctrl+Shift+V`，其他软件中发送 `Ctrl+V`。

```sh
wgestures --pause       # 临时暂停
wgestures --resume      # 恢复
wgestures --disable     # 禁用
wgestures --enable      # 启用
wgestures --status      # 查看状态
wgestures --diagnose    # 环境和依赖诊断
wgestures --diagnose --json
```

配置保存在：

```text
~/.config/wgestures/gestures-v1.json
```

安装、升级和卸载软件包都不会以 root 身份修改或删除这份用户配置。

## 7. 手动安装依赖或离线准备

如果目标机器的软件源可用，但希望先装依赖，可运行：

```sh
sudo apt update
sudo apt install python3 python3-xlib python3-gi python3-cairo \
  gir1.2-gtk-3.0 dconf-gsettings-backend
sudo apt install ./wgestures_2.1.2ubuntu1_all.deb
```

完全离线时，除了 WGestures 的 `.deb`，还必须准备目标发行版和版本对应的上述
依赖包及其传递依赖。不要混用 Ubuntu 18.04、Ubuntu 24.04 与 Kali 软件源中
下载的依赖包。最稳妥的方式是在同版本、同架构且联网的机器中先下载依赖，再把
所有 `.deb` 一起复制到离线机器安装。

## 8. 升级与卸载

升级时直接安装新包；用户配置会保留：

```sh
sudo apt install ./wgestures_新版本_all.deb
```

卸载程序：

```sh
sudo apt remove wgestures
```

卸载后 `~/.config/wgestures` 仍会保留。如果确定不再需要，可由当前普通用户自行
备份后删除；安装脚本不会替用户删除它。

## 9. 常见问题

### 诊断显示“不支持 Wayland 会话”

Ubuntu 24.04 只支持 GNOME Shell 46 Wayland。Kali、Ubuntu 18.04 和其他
桌面请在登录界面选择 X11/Xorg 会话，然后再次运行 `wgestures --diagnose`。

### X11 下右键完全没有反应

先运行：

```sh
wgestures --diagnose
wgestures --disable
wgestures --enable
```

检查诊断中的 XTEST 和按钮抓取状态。另一个全局手势、按键映射或鼠标工具也可能
占用了右键抓取，应先退出冲突程序再试。

### 设置窗口打不开或提示缺少模块

联网修复依赖：

```sh
sudo apt --fix-broken install
sudo apt install --reinstall python3-xlib python3-gi python3-cairo gir1.2-gtk-3.0
```

然后重新运行 `wgestures --diagnose`。

### 校验安装包

在 Linux 上计算 SHA-256，并与发布方在包外提供的校验值比较：

```sh
sha256sum wgestures_2.1.2ubuntu1_all.deb
```

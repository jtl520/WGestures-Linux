# CrossGestures Linux 卸载说明

本文适用于通过 CrossGestures Linux `.deb` 安装包安装的版本。卸载分为两种：

- 只卸载程序、保留手势配置，方便以后重装；
- 卸载程序后，再由当前用户清理自己的配置和自启动覆盖。

`wgestures` 控制命令必须由当前桌面普通用户运行，不要加 `sudo`；只有 APT
卸载系统软件包时才使用 `sudo`。

## 1. 确认安装来源

先确认系统中安装的是 Debian 软件包：

```sh
dpkg-query -W -f='${Status}  ${Package}  ${Version}\n' wgestures
command -v wgestures
```

正常会看到状态 `install ok installed`、包名 `wgestures`，程序路径通常是
`/usr/bin/wgestures`。

## 2. 停用手势并退出后台

在当前图形桌面的普通用户终端中运行：

```sh
wgestures --disable
```

这一步会先释放鼠标按钮抓取。Ubuntu 24.04 GNOME Wayland 会禁用 GNOME Shell
扩展；X11 桌面还应从托盘菜单选择“退出后台”。如果托盘不可用，可只结束当前
用户且命令行完全匹配的 CrossGestures 后台：

```sh
pkill -u "$(id -u)" -f '^/usr/bin/python3 /usr/lib/wgestures/main.py --daemon$' || true
```

如果旧安装已经损坏、`wgestures` 命令无法运行，可以跳过报错并继续卸载；卸载后
注销并重新登录一次即可清除当前会话中残留的进程或扩展实例。

## 3. 模拟并卸载系统软件包

先查看 APT 准备执行的操作，不会真正删除文件：

```sh
sudo apt purge --simulate wgestures
```

确认列表中的目标包是 `wgestures` 后，再正式卸载：

```sh
sudo apt purge wgestures
```

推荐使用 `purge`，它会同时移除 CrossGestures 的系统级自启动文件和包级配置。
`remove` 也能卸载主程序，但可能保留 `/etc/xdg/autostart/` 下的包配置。

不要为了卸载 CrossGestures 手动删除 Python、GTK、GNOME Shell 或 GSettings。
这些依赖可能正在被其他桌面程序共用。如果需要清理 APT 自动安装且已不再使用的
依赖，仍应先模拟并逐项确认：

```sh
sudo apt autoremove --purge --simulate
```

只有确认列表中没有需要保留的软件后，才运行不带 `--simulate` 的命令。

## 4. 验证程序已卸载

```sh
dpkg-query -W wgestures
command -v wgestures
pgrep -af '/usr/lib/wgestures/main.py --daemon'
```

前两个命令应提示未安装或不再返回程序路径，最后一个命令不应列出 CrossGestures
后台。GNOME 桌面可以再检查扩展：

```sh
gnome-extensions info wgestures@yingdev.com
```

系统扩展被移除后，该命令通常会提示找不到扩展。GNOME Shell 有缓存时，请完整
注销并重新登录后再检查。

## 5. 保留或清理当前用户配置

APT 不会删除用户主目录中的数据。默认会保留：

```text
~/.config/wgestures/
~/.config/autostart/wgestures-autostart.desktop
dconf: /org/gnome/shell/extensions/wgestures/
```

只想以后重装时恢复原有手势，到这里就可以结束。重新安装相同或更新版本后，程序
会继续读取原配置。

如果确定不再需要，先列出当前用户实际对应的路径：

```sh
config_root="${XDG_CONFIG_HOME:-$HOME/.config}"
config_dir="$config_root/wgestures"
autostart_file="$config_root/autostart/wgestures-autostart.desktop"
printf '手势配置：%s\n用户自启动：%s\n' "$config_dir" "$autostart_file"
ls -ld "$config_dir" "$autostart_file" 2>/dev/null || true
```

确认显示的路径正确后，可先移动到桌面环境的回收站，仍可恢复：

```sh
gio trash "$config_dir" 2>/dev/null || true
gio trash "$autostart_file" 2>/dev/null || true
dconf reset -f /org/gnome/shell/extensions/wgestures/
```

以上操作只清理当前用户。电脑上有多个桌面用户时，其他用户的配置不会也不应该
由 APT 或管理员自动删除。

## 6. 清理旧的用户级 GNOME 扩展

如果以前运行过 `make -f Makefile.ubuntu install-user`，可能还有一份安装在
`~/.local/share/gnome-shell/extensions/` 的旧扩展。先检查扩展路径：

```sh
gnome-extensions info wgestures@yingdev.com
```

只有输出路径位于当前用户的 `~/.local/share/gnome-shell/extensions/` 时，才运行：

```sh
gnome-extensions disable wgestures@yingdev.com 2>/dev/null || true
gnome-extensions uninstall wgestures@yingdev.com
```

路径位于 `/usr/share/gnome-shell/extensions/` 的版本属于 Debian 软件包，应由
`sudo apt purge wgestures` 管理，不要手动删除系统目录。

## 7. 卸载后右键菜单仍不出现

先检查是否还有旧的 X11 后台：

```sh
pgrep -af '/usr/lib/wgestures/main.py --daemon'
```

如果仍有匹配项，执行第 2 节中的精确 `pkill` 命令，然后完整注销并重新登录。
如果没有匹配项，则检查系统中是否还运行着其他全局鼠标手势、按键映射或输入抓取
软件；已经卸载的 CrossGestures 文件本身不会继续抓取鼠标按钮。

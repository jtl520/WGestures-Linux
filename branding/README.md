# CrossGestures 图标

采用橙色转折轨迹。`crossgestures.svg` 是唯一母版，桌面、任务栏／Dock、
设置页和安装器使用同一图形；后台托盘使用相同轨迹的单色版。
暂停附加双竖线，Linux 禁用状态附加减号，不只依靠颜色区分。

生成平台资源：

```sh
python3 tools/build-icons.py
```

生成工具需要 Python 3、PyGObject、librsvg、Cairo、Pillow；生成结果已提交，
普通 Linux／Windows 构建不需要额外安装这些依赖。

- Linux：`icons/hicolor/`，随 Debian 包安装到 `/usr/share/icons/hicolor/`。
- GNOME 扩展：`gnome-extension/icons/`，支持扩展单独打包。
- Windows：`WGestures.App/Resources/` 内的 ICO，含 16～256 px 应用尺寸及
  16～64 px 托盘尺寸。浅色任务栏使用深色轨迹，深色任务栏使用白色轨迹。
- 共享设置：`settings-ui/crossgestures.svg`，直接复制母版。

选择不同尺寸只改变栅格化分辨率，禁止单独重绘某个平台的图标。

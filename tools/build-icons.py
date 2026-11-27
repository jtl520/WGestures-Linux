#!/usr/bin/env python3
"""Export every platform icon from branding/crossgestures.svg.

Developer-only requirements: python3-gi, gir1.2-rsvg-2.0, python3-cairo,
python3-pil. Generated resources are committed, so normal builds need none
of these additional tools. No images from a concept board are used at runtime.
"""
import io
import struct
from pathlib import Path
from xml.etree import ElementTree as ET

import cairo
import gi
gi.require_version("Rsvg", "2.0")
from gi.repository import Rsvg
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MASTER = (ROOT / "branding/crossgestures.svg").read_text()
NS = "{http://www.w3.org/2000/svg}"
ET.register_namespace("", NS[1:-1])
MARK = ET.tostring(ET.fromstring(MASTER).find(".//" + NS + "g[@id='gesture']"), encoding="unicode")
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 192, 256)
TRAY_SIZES = (16, 20, 24, 32, 40, 48, 64)


def write(path, data):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def tray(color="#2e3436", state="running"):
    mark = MARK.replace("#fff", color)
    # Badge is independent of color: pause bars and a disabled minus remain
    # distinguishable on monochrome panels and high-contrast themes.
    badge = ""
    if state != "running":
        cutouts = ("M44 44h3v10h-3z M50 44h3v10h-3z" if state == "paused"
                   else "M43 47.5h11v3H43z")
        badge = ('<path fill="{0}" fill-rule="evenodd" '
                 'd="M58 49a9.5 9.5 0 1 1-19 0a9.5 9.5 0 1 1 19 0z {1}"/>').format(color, cutouts)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
            'viewBox="6 10 54 50">{0}{1}</svg>\n').format(mark, badge)


def raster(svg, size):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    handle = Rsvg.Handle.new_from_data(svg.encode("utf-8"))
    viewport = Rsvg.Rectangle()
    viewport.x = viewport.y = 0
    viewport.width = viewport.height = size
    handle.render_document(cairo.Context(surface), viewport)
    stream = io.BytesIO()
    surface.write_to_png(stream)
    return stream.getvalue()


def ico(svg, sizes):
    """Use 32-bit DIB frames below 256px for WinForms/Win7 compatibility."""
    frames = []
    for size in sizes:
        png = raster(svg, size)
        if size == 256:
            frames.append((size, png))
            continue
        rgba = Image.open(io.BytesIO(png)).convert("RGBA")
        bitmap = io.BytesIO()
        rgba.save(bitmap, format="BMP")
        dib = bytearray(bitmap.getvalue()[14:])
        struct.pack_into("<i", dib, 8, size * 2)
        alpha = rgba.getchannel("A")
        stride = ((size + 31) // 32) * 4
        mask = bytearray(stride * size)
        for y in range(size):
            for x in range(size):
                if alpha.getpixel((x, size - 1 - y)) == 0:
                    mask[y * stride + x // 8] |= 0x80 >> (x % 8)
        frames.append((size, bytes(dib) + bytes(mask)))
    result = bytearray(struct.pack("<HHH", 0, 1, len(frames)))
    offset = 6 + 16 * len(frames)
    for size, data in frames:
        result.extend(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    for _, data in frames:
        result.extend(data)
    return bytes(result)


def main():
    write("settings-ui/crossgestures.svg", MASTER)
    write("branding/icons/hicolor/scalable/apps/crossgestures.svg", MASTER)
    for size in SIZES + (512,):
        png = raster(MASTER, size)
        write("branding/icons/hicolor/{0}x{0}/apps/crossgestures.png".format(size), png)
        if size in (16, 24, 32, 48, 64, 128, 192, 256):
            write("WGestures.App/externalResource/Icon/{0}.png".format(size), png)
        if size == 128:
            write("WGestures.App/Resources/128.png", png)
    write("WGestures.App/Resources/icon.ico", ico(MASTER, SIZES))
    write("WGInstall/logo.ico", ico(MASTER, SIZES))
    grey = MASTER.replace("#f57632", "#9d9b98").replace("#df4f20", "#777571").replace("#bc3614", "#5e5c59")
    write("WGestures.App/Resources/icon_bw.ico", ico(grey, SIZES))
    for state, suffix in (("running", ""), ("paused", "-paused"), ("disabled", "-disabled")):
        svg = tray(state=state)
        name = "crossgestures-tray{0}-symbolic.svg".format(suffix)
        write("branding/icons/hicolor/scalable/status/" + name, svg)
        write("gnome-extension/icons/" + name, svg)
    for name, color, state in (
        ("trayIcon", "#252525", "running"),
        ("trayIcon_bw", "#252525", "paused"),
        ("trayIcon_light", "#ffffff", "running"),
        ("trayIcon_bw_light", "#ffffff", "paused"),
    ):
        write("WGestures.App/Resources/" + name + ".ico", ico(tray(color, state), TRAY_SIZES))
    print("Generated app, tray, settings and installer icons from one SVG master.")


if __name__ == "__main__":
    main()

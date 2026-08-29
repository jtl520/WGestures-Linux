from __future__ import division, unicode_literals

import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo


class GestureOverlay(object):
    """One input-transparent ARGB overlay spanning the X11 virtual desktop."""

    FRAME_MS = 16
    MAX_POINTS = 8192

    def __init__(self, settings, on_monitors_changed=None, on_frame=None):
        self.settings = settings
        self.on_monitors_changed = on_monitors_changed
        self.on_frame = on_frame
        self.points = []
        self.valid = True
        self.label = ""
        self.opacity = 1.0
        self.origin_x = 0
        self.origin_y = 0
        self._draw_pending = False
        self._fade_source = None
        self._fade_started = 0.0
        self._last_input_time = None
        self.window = Gtk.Window.new(Gtk.WindowType.POPUP)
        self.window.set_decorated(False)
        self.window.set_accept_focus(False)
        self.window.set_focus_on_map(False)
        self.window.set_skip_pager_hint(True)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_keep_above(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        self.window.set_app_paintable(True)
        self.window.connect("draw", self._draw)
        self.window.connect("realize", self._on_realize)
        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        self.composited = bool(visual is not None and screen.is_composited())
        if self.composited:
            self.window.set_visual(visual)
        screen.connect("monitors-changed", self._monitors_changed)
        self._update_geometry()

    def _on_realize(self, _window):
        gdk_window = self.window.get_window()
        if gdk_window is not None:
            gdk_window.input_shape_combine_region(cairo.Region(), 0, 0)

    def _monitors_changed(self, _screen):
        self.cancel()
        self._update_geometry()
        if self.on_monitors_changed:
            self.on_monitors_changed()

    def _update_geometry(self):
        screen = self.window.get_screen()
        geometries = [screen.get_monitor_geometry(index)
                      for index in range(screen.get_n_monitors())]
        if not geometries:
            return
        left = min(item.x for item in geometries)
        top = min(item.y for item in geometries)
        right = max(item.x + item.width for item in geometries)
        bottom = max(item.y + item.height for item in geometries)
        self.origin_x, self.origin_y = left, top
        self.window.move(left, top)
        self.window.resize(max(1, right - left), max(1, bottom - top))

    def begin(self, x, y):
        self._stop_fade()
        self.points = [(x, y)]
        self.valid = True
        self.label = ""
        self.opacity = 1.0
        self._update_geometry()
        if self.composited:
            self.window.show_all()
        self._queue_draw()

    def add_point(self, x, y):
        if not self.points:
            return
        # Coalesce sub-pixel/no-op motion before frame throttling.
        if self.points[-1][0] == x and self.points[-1][1] == y:
            return
        self.points.append((x, y))
        if len(self.points) > self.MAX_POINTS:
            self.points = self.points[::2]
            if self.points[-1] != (x, y):
                self.points.append((x, y))
        self._last_input_time = time.monotonic()
        self._queue_draw()

    def complete(self, valid, label=""):
        if not self.points:
            return
        self.valid = bool(valid)
        self.label = label or ""
        self.opacity = 1.0
        self._queue_draw()
        duration = max(0, int(self.settings.get("fade-duration")))
        if duration == 0:
            self.cancel()
            return
        self._fade_started = time.monotonic()
        self._fade_source = GLib.timeout_add(self.FRAME_MS, self._fade_tick, duration)

    def _fade_tick(self, duration):
        elapsed = (time.monotonic() - self._fade_started) * 1000.0
        self.opacity = max(0.0, 1.0 - elapsed / duration)
        self.window.queue_draw()
        if self.opacity <= 0.0:
            self.cancel()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _stop_fade(self):
        if self._fade_source:
            GLib.source_remove(self._fade_source)
            self._fade_source = None

    def cancel(self):
        self._stop_fade()
        self.points = []
        self.label = ""
        self.opacity = 1.0
        self.window.hide()

    def destroy(self):
        self.cancel()
        self.window.destroy()

    def _queue_draw(self):
        if self._draw_pending:
            return
        self._draw_pending = True
        GLib.timeout_add(self.FRAME_MS, self._flush_draw)

    def _flush_draw(self):
        self._draw_pending = False
        if self.points:
            if self.composited:
                self.window.queue_draw()
            if self.composited and self.on_frame and self._last_input_time is not None:
                self.on_frame((time.monotonic() - self._last_input_time) * 1000.0)
                self._last_input_time = None
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _parse_color(text):
        value = Gdk.RGBA()
        if not value.parse(str(text)):
            value.parse("#27ae60")
        return value

    def _draw(self, _widget, context):
        context.set_operator(cairo.OPERATOR_SOURCE)
        context.set_source_rgba(0, 0, 0, 0)
        context.paint()
        context.set_operator(cairo.OPERATOR_OVER)
        if len(self.points) < 2:
            return False
        color_key = "path-color" if self.valid else "invalid-path-color"
        color = self._parse_color(self.settings.get(color_key))
        context.set_source_rgba(color.red, color.green, color.blue,
                                color.alpha * self.opacity)
        context.set_line_width(float(self.settings.get("path-width")))
        context.set_line_cap(cairo.LINE_CAP_ROUND)
        context.set_line_join(cairo.LINE_JOIN_ROUND)
        first = self.points[0]
        context.move_to(first[0] - self.origin_x, first[1] - self.origin_y)
        for x, y in self.points[1:]:
            context.line_to(x - self.origin_x, y - self.origin_y)
        context.stroke()
        if self.label and self.settings.get("show-command-name"):
            x, y = self.points[-1]
            layout = PangoCairo.create_layout(context)
            font = Pango.FontDescription()
            font.set_family("Sans")
            font.set_weight(Pango.Weight.BOLD)
            font.set_absolute_size(18 * Pango.SCALE)
            layout.set_font_description(font)
            layout.set_text(self.label, -1)
            _ink_rect, logical_rect = layout.get_pixel_extents()
            text_width = max(1, logical_rect.width)
            text_height = max(1, logical_rect.height)
            padding = 8
            box_x = x - self.origin_x + 16
            box_y = y - self.origin_y - text_height - padding * 2
            context.set_source_rgba(0.05, 0.05, 0.05, 0.82 * self.opacity)
            context.rectangle(box_x, box_y,
                              text_width + padding * 2,
                              text_height + padding * 2)
            context.fill()
            context.set_source_rgba(1, 1, 1, self.opacity)
            context.move_to(box_x + padding - logical_rect.x,
                            box_y + padding - logical_rect.y)
            PangoCairo.show_layout(context, layout)
        return False

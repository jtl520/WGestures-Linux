#!/usr/bin/python3
from __future__ import print_function, unicode_literals

import json
import os
import sys
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk


class Harness(Gtk.Window):
    def __init__(self, log_path):
        Gtk.Window.__init__(self, title="WGestures Acceptance Harness")
        self.log_path = log_path
        self._last_button_event = None
        self.set_default_size(520, 360)
        self.move(180, 180)
        self.connect("destroy", Gtk.main_quit)
        self.connect("button-press-event", self._button_press)
        self.connect("button-release-event", self._button_release)
        self.connect("key-press-event", self._key_press)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                        Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.KEY_PRESS_MASK)
        label = Gtk.Label(label=(
            "WGestures X11 acceptance target\n"
            "Automated input is expected in this window."))
        self.add(label)

    def _record(self, event_type, **fields):
        value = {"type": event_type, "time": time.monotonic()}
        value.update(fields)
        with open(self.log_path, "a") as stream:
            stream.write(json.dumps(value, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _button_press(self, _widget, event):
        signature = ("button-press", int(event.button), int(event.time))
        if signature == self._last_button_event:
            return False
        self._last_button_event = signature
        self._record("button-press", button=int(event.button),
                     x=float(event.x_root), y=float(event.y_root),
                     serverTime=int(event.time), synthetic=bool(event.send_event))
        return False

    def _button_release(self, _widget, event):
        signature = ("button-release", int(event.button), int(event.time))
        if signature == self._last_button_event:
            return False
        self._last_button_event = signature
        self._record("button-release", button=int(event.button),
                     x=float(event.x_root), y=float(event.y_root),
                     serverTime=int(event.time), synthetic=bool(event.send_event))
        return False

    def _key_press(self, _widget, event):
        self._record("key-press", key=Gdk.keyval_name(event.keyval),
                     state=int(event.state))
        return False


def main():
    if len(sys.argv) != 2:
        print("usage: x11_harness.py LOG_PATH", file=sys.stderr)
        return 2
    open(sys.argv[1], "w").close()
    window = Harness(sys.argv[1])
    window.show_all()
    window.present()
    print("READY", flush=True)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())

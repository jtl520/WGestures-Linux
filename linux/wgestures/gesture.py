from __future__ import division

import math


BUTTONS = ("right", "middle", "x1", "x2")
DIRECTIONS = (
    "up", "up-right", "right", "down-right",
    "down", "down-left", "left", "up-left",
)
FOUR_DIRECTIONS = ("right", "down", "left", "up")
EIGHT_DIRECTIONS = (
    "right", "down-right", "down", "down-left",
    "left", "up-left", "up", "up-right",
)


def direction_from_delta(dx, dy, direction_mode=8):
    if dx == 0 and dy == 0:
        return None
    names = FOUR_DIRECTIONS if direction_mode == 4 else EIGHT_DIRECTIONS
    sector_size = math.pi * 2.0 / len(names)
    angle = math.atan2(dy, dx)
    # JavaScript Math.round() rounds half towards +infinity. Angles exactly on
    # a sector boundary are rare, but matching it keeps both backends stable.
    index = int(math.floor(angle / sector_size + 0.5))
    return names[index % len(names)]


def gesture_key(button, directions):
    if button not in BUTTONS:
        raise ValueError("Unsupported gesture button: {0}".format(button))
    if not isinstance(directions, (list, tuple)) or any(
            direction not in DIRECTIONS for direction in directions):
        raise ValueError("Gesture contains an unsupported direction")
    return "{0}:{1}".format(button, ",".join(directions))


def _distance(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


class GestureRecognizer(object):
    def __init__(self, direction_mode=8, start_threshold=8,
                 segment_threshold=12):
        self.configure(direction_mode, start_threshold, segment_threshold)
        self.reset()

    def configure(self, direction_mode=8, start_threshold=8,
                  segment_threshold=12):
        self.direction_mode = 4 if direction_mode == 4 else 8
        self.start_threshold = max(1.0, float(start_threshold))
        self.segment_threshold = max(1.0, float(segment_threshold))

    def reset(self):
        self.origin = None
        self.anchor = None
        self.last_point = None
        self.directions = []
        self.effective = False

    def begin(self, x, y):
        self.reset()
        self.origin = (x, y)
        self.anchor = (x, y)
        self.last_point = (x, y)

    def add_point(self, x, y):
        if self.origin is None:
            raise RuntimeError("GestureRecognizer.begin() must be called first")
        point = (x, y)
        self.last_point = point
        if not self.effective and _distance(self.origin, point) < self.start_threshold:
            return None
        self.effective = True
        if _distance(self.anchor, point) < self.segment_threshold:
            return None
        direction = direction_from_delta(
            point[0] - self.anchor[0], point[1] - self.anchor[1],
            self.direction_mode)
        self.anchor = point
        if direction and (not self.directions or self.directions[-1] != direction):
            self.directions.append(direction)
            return direction
        return None

    def finish(self):
        return {
            "effective": bool(self.effective and self.directions),
            "directions": list(self.directions),
            "origin": self.origin,
            "end": self.last_point,
        }


class GestureSession(object):
    def __init__(self, recognizer):
        self.recognizer = recognizer
        self.active = None

    def begin(self, context, x, y):
        if self.active is not None:
            return False
        self.recognizer.begin(x, y)
        self.active = context
        return True

    def motion(self, x, y):
        if self.active is None:
            return None
        return self.recognizer.add_point(x, y)

    def release(self, button_number):
        if self.active is None:
            return {"handled": False}
        if self.active["button_number"] != button_number:
            return {"handled": True, "mismatched": True}
        context = self.active
        result = self.recognizer.finish()
        self.active = None
        return {
            "handled": True,
            "mismatched": False,
            "context": context,
            "result": result,
        }

    def cancel(self):
        had_active = self.active is not None
        self.active = None
        self.recognizer.reset()
        return had_active


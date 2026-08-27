export const BUTTONS = Object.freeze(['right', 'middle', 'x1', 'x2']);

export const DIRECTIONS = Object.freeze([
    'up',
    'up-right',
    'right',
    'down-right',
    'down',
    'down-left',
    'left',
    'up-left',
]);

const FOUR_DIRECTIONS = Object.freeze(['right', 'down', 'left', 'up']);
const EIGHT_DIRECTIONS = Object.freeze([
    'right',
    'down-right',
    'down',
    'down-left',
    'left',
    'up-left',
    'up',
    'up-right',
]);

function distance(a, b) {
    return Math.hypot(b.x - a.x, b.y - a.y);
}

export function directionFromDelta(dx, dy, directionMode = 8) {
    if (dx === 0 && dy === 0)
        return null;

    const names = directionMode === 4 ? FOUR_DIRECTIONS : EIGHT_DIRECTIONS;
    const sectorSize = (Math.PI * 2) / names.length;
    const angle = Math.atan2(dy, dx);
    const index = Math.round(angle / sectorSize);
    return names[(index + names.length) % names.length];
}

export function gestureKey(button, directions) {
    if (!BUTTONS.includes(button))
        throw new Error(`Unsupported gesture button: ${button}`);
    if (!Array.isArray(directions) || directions.some(direction => !DIRECTIONS.includes(direction)))
        throw new Error('Gesture contains an unsupported direction');

    return `${button}:${directions.join(',')}`;
}

export class GestureRecognizer {
    constructor(options = {}) {
        this.configure(options);
        this.reset();
    }

    configure(options = {}) {
        this.directionMode = options.directionMode === 4 ? 4 : 8;
        this.startThreshold = Math.max(1, Number(options.startThreshold ?? 8));
        this.segmentThreshold = Math.max(1, Number(options.segmentThreshold ?? 12));
    }

    reset() {
        this.origin = null;
        this.anchor = null;
        this.lastPoint = null;
        this.directions = [];
        this.effective = false;
    }

    begin(x, y) {
        this.reset();
        this.origin = {x, y};
        this.anchor = {x, y};
        this.lastPoint = {x, y};
    }

    addPoint(x, y) {
        if (!this.origin)
            throw new Error('GestureRecognizer.begin() must be called first');

        const point = {x, y};
        this.lastPoint = point;

        if (!this.effective && distance(this.origin, point) < this.startThreshold)
            return null;

        this.effective = true;
        if (distance(this.anchor, point) < this.segmentThreshold)
            return null;

        const direction = directionFromDelta(
            point.x - this.anchor.x,
            point.y - this.anchor.y,
            this.directionMode
        );
        this.anchor = point;

        if (direction && this.directions.at(-1) !== direction) {
            this.directions.push(direction);
            return direction;
        }

        return null;
    }

    finish() {
        return {
            effective: this.effective && this.directions.length > 0,
            directions: [...this.directions],
            origin: this.origin ? {...this.origin} : null,
            end: this.lastPoint ? {...this.lastPoint} : null,
        };
    }
}

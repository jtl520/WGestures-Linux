import Clutter from 'gi://Clutter';
import St from 'gi://St';
import Cairo from 'cairo';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

function parseColor(value) {
    const match = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i.exec(String(value || ''));
    if (!match)
        return [0.15, 0.68, 0.38, 1];
    const rgb = match[1];
    const alpha = match[2] || 'ff';
    return [
        Number.parseInt(rgb.slice(0, 2), 16) / 255,
        Number.parseInt(rgb.slice(2, 4), 16) / 255,
        Number.parseInt(rgb.slice(4, 6), 16) / 255,
        Number.parseInt(alpha, 16) / 255,
    ];
}

export class GestureOverlay {
    constructor(settings) {
        this._settings = settings;
        this._points = [];
        this._invalid = false;

        this._area = new St.DrawingArea({
            reactive: false,
            can_focus: false,
            visible: false,
        });
        this._area.connect('repaint', () => this._repaint());
        Main.uiGroup.add_child(this._area);

        this._label = new St.Label({
            style_class: 'wgestures-status-label',
            reactive: false,
            visible: false,
        });
        Main.uiGroup.add_child(this._label);
        this.resize();
    }

    resize() {
        this._area.set_position(0, 0);
        this._area.set_size(global.stage.width, global.stage.height);
    }

    begin(x, y) {
        this._area.remove_all_transitions();
        this._label.remove_all_transitions();
        this._area.opacity = 255;
        this._label.opacity = 255;
        this._points = [{x, y}];
        this._invalid = false;
        this._label.hide();
        this._area.show();
        this._area.queue_repaint();
    }

    addPoint(x, y) {
        this._points.push({x, y});
        if (this._points.length > 8192) {
            this._points = this._points.filter((_point, index) => index % 2 === 0);
            const last = this._points.at(-1);
            if (!last || last.x !== x || last.y !== y)
                this._points.push({x, y});
        }
        this._area.queue_repaint();
    }

    finish(text, invalid = false) {
        this._invalid = invalid;
        this._area.queue_repaint();
        const last = this._points.at(-1);
        if (text && last && this._settings.get_boolean('show-command-name')) {
            this._label.text = text;
            this._label.set_position(
                Math.min(last.x + 14, Math.max(0, global.stage.width - 240)),
                Math.min(last.y + 14, Math.max(0, global.stage.height - 60))
            );
            this._label.show();
        }

        const duration = this._settings.get_int('fade-duration');
        if (duration === 0) {
            this.clear();
            return;
        }
        this._area.ease({
            opacity: 0,
            duration,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => this.clear(),
        });
        this._label.ease({
            opacity: 0,
            duration,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    clear() {
        this._points = [];
        this._area.hide();
        this._label.hide();
        this._area.opacity = 255;
        this._label.opacity = 255;
    }

    _repaint() {
        if (this._points.length < 2)
            return;
        const cr = this._area.get_context();
        const color = parseColor(this._settings.get_string(
            this._invalid ? 'invalid-path-color' : 'path-color'
        ));
        cr.setSourceRGBA(...color);
        cr.setLineWidth(this._settings.get_double('path-width'));
        cr.setLineCap(Cairo.LineCap.ROUND);
        cr.setLineJoin(Cairo.LineJoin.ROUND);
        cr.moveTo(this._points[0].x, this._points[0].y);
        for (const point of this._points.slice(1))
            cr.lineTo(point.x, point.y);
        cr.stroke();
        cr.$dispose();
    }

    destroy() {
        this._area.destroy();
        this._label.destroy();
        this._area = null;
        this._label = null;
        this._points = [];
    }
}

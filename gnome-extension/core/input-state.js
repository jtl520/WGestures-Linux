export class GestureSession {
    constructor(recognizer) {
        this._recognizer = recognizer;
        this.active = null;
    }

    begin(context, x, y) {
        if (this.active)
            return false;
        this._recognizer.begin(x, y);
        this.active = context;
        return true;
    }

    motion(x, y) {
        if (!this.active)
            return null;
        return this._recognizer.addPoint(x, y);
    }

    release(buttonNumber) {
        if (!this.active)
            return {handled: false};
        if (this.active.buttonNumber !== buttonNumber)
            return {handled: true, mismatched: true};
        const context = this.active;
        const result = this._recognizer.finish();
        this.active = null;
        return {handled: true, mismatched: false, context, result};
    }

    cancel() {
        const hadActiveGesture = Boolean(this.active);
        this.active = null;
        this._recognizer.reset();
        return hadActiveGesture;
    }
}

export class ReplayGuard {
    constructor(durationUsec = 250000) {
        this.durationUsec = durationUsec;
        this._state = null;
    }

    arm(buttonNumber, nowUsec) {
        this._state = {buttonNumber, remaining: 2, deadline: nowUsec + this.durationUsec};
    }

    consume(buttonNumber, nowUsec) {
        if (!this._state)
            return false;
        if (nowUsec > this._state.deadline) {
            this._state = null;
            return false;
        }
        if (buttonNumber !== this._state.buttonNumber)
            return false;
        this._state.remaining -= 1;
        if (this._state.remaining <= 0)
            this._state = null;
        return true;
    }

    clear() {
        this._state = null;
    }
}

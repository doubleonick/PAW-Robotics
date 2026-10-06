#include "CogServo.h"

// -------------------- Constructors --------------------

CogServo::CogServo()
: _leftValue(0), _rightValue(0),
  _leftUs(DEFAULT_NEUTRAL_US),  _rightUs(DEFAULT_NEUTRAL_US),
  _leftNeutralUs(DEFAULT_NEUTRAL_US), _rightNeutralUs(DEFAULT_NEUTRAL_US) {
}

// -------------------- Public API --------------------

void CogServo::begin(uint8_t leftPin, uint8_t rightPin) {
    _leftServo.attach(leftPin);
    _rightServo.attach(rightPin);
    // Neutral before anything else can command motion.
    _leftUs  = _leftNeutralUs;
    _rightUs = _rightNeutralUs;
    writeCurrent();
}

void CogServo::setNeutral(int leftNeutralUs, int rightNeutralUs) {
    _leftNeutralUs  = clampMicros(leftNeutralUs);
    _rightNeutralUs = clampMicros(rightNeutralUs);
    // Apply immediately: whatever was commanded before was relative to the
    // OLD neutral, so leaving it in place would mean a silent drift.
    _leftUs  = _leftNeutralUs;
    _rightUs = _rightNeutralUs;
    writeCurrent();
}


// ── Cooperative wait ──────────────────────────────────────────────────────────

void (*CogServo::_waitTick)() = nullptr;

void CogServo::setWaitTick(void (*fn)()) { _waitTick = fn; }

// Spin until `seconds` have elapsed, giving the tick a chance to run. Falls
// back to delay() when no hook is installed, so behaviour is unchanged for
// sketches that never call setWaitTick().
void CogServo::_hold(float seconds)
{
    if (seconds <= 0.0f) return;
    const unsigned long ms = (unsigned long)(seconds * 1000.0f);

    if (_waitTick == nullptr) {
        delay(ms);
        return;
    }
    const unsigned long start = millis();
    while (millis() - start < ms) {
        _waitTick();
    }
}

void CogServo::driveProportional(int leftProportion, int rightProportion, float durationInSeconds) {
    leftProportion = -leftProportion;

    _leftUs  = mapProportionToMicros(leftProportion,  _leftNeutralUs);
    _rightUs = mapProportionToMicros(rightProportion, _rightNeutralUs);

    writeCurrent();

    // ORIGINAL (blocking) -- kept for reference; _hold() is identical when no
    // wait tick is installed:
    //     if (durationInSeconds > 0.0f) {
    //         const unsigned long ms =
    //             (unsigned long)(durationInSeconds * 1000.0f);
    //         delay(ms);
    //     }
    _hold(durationInSeconds);
}

void CogServo::drive(float durationInSeconds) {
    // Write whatever the current members are (no remapping)
    writeCurrent();

    // ORIGINAL (blocking):
    //     if (durationInSeconds > 0.0f) {
    //         const unsigned long ms =
    //             (unsigned long)(durationInSeconds * 1000.0f);
    //         delay(ms);
    //     }
    _hold(durationInSeconds);
}

// delta is in MICROSECONDS now, not degrees.
void CogServo::translate(int delta) {
    _leftUs  = clampMicros(_leftUs  + delta);
    _rightUs = clampMicros(_rightUs + delta);
    writeCurrent();
}

void CogServo::rotate(int leftDelta, int rightDelta) {
    _leftUs  = clampMicros(_leftUs  + leftDelta);
    _rightUs = clampMicros(_rightUs + rightDelta);
    writeCurrent();
}

void CogServo::halt(float durationInSeconds) {
    _leftUs  = _leftNeutralUs;
    _rightUs = _rightNeutralUs;
    writeCurrent();

    if (durationInSeconds > 0.0f) {
        const unsigned long ms = (unsigned long)(durationInSeconds * 1000.0f);
        delay(ms);
    }
}

// -------------------- Private helpers --------------------

int CogServo::clampMicros(int us) {
    // Standard hobby-servo pulse range. Anything outside is meaningless and
    // some servos stall or buzz when fed it.
    if (us < 900) us = 900;
    if (us > 2100) us = 2100;
    return us;
}

// Proportion 0 -> this side's neutral; +/-100 -> neutral -/+ SPAN_US.
// The sign is inverted (+100 maps BELOW neutral) to preserve the direction
// convention the old angle mapping had: map(p, -100, 100, 180, 0).
int CogServo::mapProportionToMicros(int proportion, int neutralUs) {
    proportion = constrain(proportion, -100, 100);
    return clampMicros(neutralUs - (proportion * SPAN_US) / 100);
}


void CogServo::writeCurrent() {
    // writeMicroseconds, NOT write(angle): Servo.h maps angles onto
    // 544..2400 us, so write(90) emits 1472 us and "stop" becomes a crawl.
    _leftServo.writeMicroseconds(_leftUs);
    _rightServo.writeMicroseconds(_rightUs);
}

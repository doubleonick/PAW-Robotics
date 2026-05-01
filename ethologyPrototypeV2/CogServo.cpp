#include "CogServo.h"

// -------------------- Constructors --------------------

CogServo::CogServo()
: _mode(Mode::ServoMode),
  _leftValue(90), _rightValue(90),
  _leftAngle(90), _rightAngle(90),
  _leftUS(1450), _rightUS(1450) {
}

CogServo::CogServo(Adafruit_PWMServoDriver &pwmDriver)
: _mode(Mode::PwmMode),
  _pwm(&pwmDriver),
  _leftValue(0), _rightValue(0),
  _leftAngle(90), _rightAngle(90),
  _leftUS(1450), _rightUS(1450) {
}

// -------------------- Public API --------------------

void CogServo::begin(uint8_t leftPinOrChannel, uint8_t rightPinOrChannel, bool initPwmDriver) {
    if (_mode == Mode::ServoMode) {
        _leftServo.attach(leftPinOrChannel);
        _rightServo.attach(rightPinOrChannel);
        // Keep neutral by default
        _leftAngle = 90;
        _rightAngle = 90;
        writeCurrent();
    } else {
        // PWM mode: treat inputs as PCA9685 channels
        _leftChannel  = leftPinOrChannel;
        _rightChannel = rightPinOrChannel;

        // Optionally ensure 50Hz for servos
        if (_pwm && initPwmDriver) {
            _pwm->begin();
            _pwm->setPWMFreq(50); // typical servo frequency
            delay(10);
        }

        // Neutral microseconds
        _leftUS  = 1450;
        _rightUS = 1450;
        writeCurrent();
    }
}

void CogServo::driveProportional(int leftProportion, int rightProportion, float durationInSeconds) {
    // // Flip right as in your original code
    // rightProportion = -rightProportion;

    if (_mode == Mode::ServoMode) {
        _leftAngle  = mapProportionToAngle(leftProportion);
        _rightAngle = mapProportionToAngle(rightProportion);
    } else {
        _leftUS  = mapProportionToMicrosecond(leftProportion);
        _rightUS = mapProportionToMicrosecond(rightProportion);
    }

    writeCurrent();

    if (durationInSeconds > 0.0f) {
        const unsigned long ms = (unsigned long)(durationInSeconds * 1000.0f);
        delay(ms);
    }
}

void CogServo::drive(float durationInSeconds) {
    // Write whatever the current members are (no remapping)
    writeCurrent();

    if (durationInSeconds > 0.0f) {
        const unsigned long ms = (unsigned long)(durationInSeconds * 1000.0f);
        delay(ms);
    }
}

void CogServo::translate(int delta) {
    if (_mode == Mode::ServoMode) {
        _leftAngle  = clampAngle(_leftAngle  + delta);
        _rightAngle = clampAngle(_rightAngle + delta);
    } else {
        // Adjust in microseconds; then re-clamp and apply deadband if needed
        int l = (int)_leftUS + delta;
        int r = (int)_rightUS + delta;
        l = constrain(l, 800, 2100);
        r = constrain(r, 800, 2100);
        // Re-apply the commanded values (respect deadband rule)
        _leftUS  = (l >= 1350 && l <= 1550) ? 1450 : (uint16_t)l;
        _rightUS = (r >= 1350 && r <= 1550) ? 1450 : (uint16_t)r;
    }
    writeCurrent();
}

void CogServo::rotate(int leftDelta, int rightDelta) {
    if (_mode == Mode::ServoMode) {
        _leftAngle  = clampAngle(_leftAngle  + leftDelta);
        _rightAngle = clampAngle(_rightAngle + rightDelta);
    } else {
        int l = (int)_leftUS + leftDelta;
        int r = (int)_rightUS + rightDelta;
        l = constrain(l, 800, 2100);
        r = constrain(r, 800, 2100);
        _leftUS  = (l >= 1350 && l <= 1550) ? 1450 : (uint16_t)l;
        _rightUS = (r >= 1350 && r <= 1550) ? 1450 : (uint16_t)r;
    }
    writeCurrent();
}

void CogServo::halt(float durationInSeconds) {
    if (_mode == Mode::ServoMode) {
        _leftAngle  = 90;
        _rightAngle = 90;
    } else {
        _leftUS  = 1450;
        _rightUS = 1450;
    }
    writeCurrent();

    if (durationInSeconds > 0.0f) {
        const unsigned long ms = (unsigned long)(durationInSeconds * 1000.0f);
        delay(ms);
    }
}

// -------------------- Private helpers --------------------

int CogServo::clampAngle(int v) {
    if (v < 0)   return 0;
    if (v > 180) return 180;
    return v;
}

int CogServo::mapProportionToAngle(int proportion) {
    // Constrain input to [-100, 100], then map to [0, 180].
    proportion = constrain(proportion, -100, 100);
    long mapped = map(proportion, -100, 100, 180, 0);
    return (int)mapped;
}

uint16_t CogServo::mapProportionToMicrosecond(int proportion) {
    // Constrain to [-100..100] and map to [800..2100]
    proportion = constrain(proportion, -100, 100);
    long us = map(proportion, -100, 100, 2100, 800);

    // Deadband: anything in [1350..1550] => 1450
    if (us >= 1350 && us <= 1550) {
        us = 1450;
    }

    // Final clamp & cast
    if (us < 800)  us = 800;
    if (us > 2100) us = 2100;
    return (uint16_t)us;
}

void CogServo::writeCurrent() {
    if (_mode == Mode::ServoMode) {
        // (Keep the same behavior as your original implementation)
        _leftServo.write(_leftAngle);
        _rightServo.write(_rightAngle);
    } else {
        // PWM driver mode: write microseconds via the Adafruit driver
        if (_pwm) {
            _pwm->writeMicroseconds(_leftChannel,  _leftUS);
            _pwm->writeMicroseconds(_rightChannel, _rightUS);
        }
    }
}
#include "Robot.h"

// -------------------- Constructors --------------------

Robot::Robot()
: _drivetrain() {
}

Robot::Robot(Adafruit_PWMServoDriver& pwmDriver)
: _drivetrain(pwmDriver) {
}

// -------------------- Public API --------------------

void Robot::begin(uint8_t leftServoPin, uint8_t rightServoPin) {
    _drivetrain.begin(leftServoPin, rightServoPin);
}

void Robot::drive(float durationInSeconds) {
    _drivetrain.drive(durationInSeconds);
}

void Robot::driveProportional(int leftProportion, int rightProportion, float durationInSeconds) {
    _drivetrain.driveProportional(leftProportion, rightProportion, durationInSeconds);
}

void Robot::translate(int delta) {
    _drivetrain.translate(delta);
}

void Robot::rotate(int leftDelta, int rightDelta) {
    _drivetrain.rotate(leftDelta, rightDelta);
}

void Robot::halt(float durationInSeconds) {
    // Preserve your existing semantics
    _drivetrain.driveProportional(-25, -25, durationInSeconds);
}
#ifndef ROBOT_H
#define ROBOT_H

#include <Arduino.h>
#include "CogServo.h"

// Robot composes a CogServo drivetrain.
// All child classes inherit this behavior automatically.
class Robot {
public:
    // --- Constructors ---
    // Default: uses Servo.h internally
    Robot();


    virtual ~Robot() = default;

    // Initialize drivetrain:
    //  Servo mode -> Arduino pins
    //  PWM mode   -> PCA9685 channels
    virtual void begin(uint8_t leftServoPin, uint8_t rightServoPin);

    // Drivetrain passthroughs
    void drive(float durationInSeconds);
    void driveProportional(int leftProportion, int rightProportion, float durationInSeconds);
    // NOTE: delta is in MICROSECONDS, not degrees — CogServo became
    // microsecond-based. No caller in this tree uses these, so the unit
    // change is silent; check yours if you add one.
    void translate(int delta);
    void rotate(int leftDelta, int rightDelta);
    void halt(float durationInSeconds);

    // Optional accessors
    // Now return PULSE WIDTHS in microseconds, not degrees. Names kept so
    // existing callers still compile; prefer getLeftMicros()/getRightMicros().
    int getLeftAngle() const  { return _drivetrain.getLeftAngle(); }
    int getRightAngle() const { return _drivetrain.getRightAngle(); }
    int getLeftMicros() const  { return _drivetrain.getLeftMicros(); }
    int getRightMicros() const { return _drivetrain.getRightMicros(); }

protected:
    // Protected so child robot types can act on the drivetrain
    CogServo _drivetrain;
};

#endif // ROBOT_H
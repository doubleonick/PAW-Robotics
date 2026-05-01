#ifndef ROBOT_H
#define ROBOT_H

#include <Arduino.h>
#include <Adafruit_PWMServoDriver.h>
#include "CogServo.h"

// Robot composes a CogServo drivetrain.
// All child classes inherit this behavior automatically.
class Robot {
public:
    // --- Constructors ---
    // Default: uses Servo.h internally
    Robot();

    // PCA9685 / Adafruit PWM mode
    explicit Robot(Adafruit_PWMServoDriver& pwmDriver);

    virtual ~Robot() = default;

    // Initialize drivetrain:
    //  Servo mode -> Arduino pins
    //  PWM mode   -> PCA9685 channels
    virtual void begin(uint8_t leftServoPin, uint8_t rightServoPin);

    // Drivetrain passthroughs
    void drive(float durationInSeconds);
    void driveProportional(int leftProportion, int rightProportion, float durationInSeconds);
    void translate(int delta);
    void rotate(int leftDelta, int rightDelta);
    void halt(float durationInSeconds);

    // Optional accessors
    int getLeftAngle() const  { return _drivetrain.getLeftAngle(); }
    int getRightAngle() const { return _drivetrain.getRightAngle(); }

protected:
    // Protected so child robot types can act on the drivetrain
    CogServo _drivetrain;
};

#endif // ROBOT_H
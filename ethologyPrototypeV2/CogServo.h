#ifndef COGSERVO_H
#define COGSERVO_H

#include <Arduino.h>
#include <Servo.h>
#include <Adafruit_PWMServoDriver.h>

class CogServo {
public:
    // --- Constructors ---
    // Default: use the standard Servo.h
    CogServo();

    // Use Adafruit PCA9685 driver (Adafruit_PWMServoDriver)
    explicit CogServo(Adafruit_PWMServoDriver &pwmDriver);

    ~CogServo() = default;

    // Attach two drive outputs:
    // - Servo mode: 'leftPin' and 'rightPin' are Arduino pins for Servo.attach()
    // - PWM mode:   'leftPin' and 'rightPin' are PCA9685 channel numbers [0..15]
    //   If 'initPwmDriver' is true, we set PWM frequency to 50 Hz.
    void begin(uint8_t leftPin, uint8_t rightPin, bool initPwmDriver = true);

    // Drive using proportions in [-100, 100]; blocks for durationInSeconds.
    // In Servo mode -> map to [0..180] via mapProportionToAngle().
    // In PWM mode   -> map to [600..2100] via mapProportionToMicrosecond().
    void driveProportional(int leftProportion, int rightProportion, float durationInSeconds);

    // Writes current values to hardware and then delays (no remapping)
    void drive(float durationInSeconds);

    // Adjust both by 'delta' (angles in Servo mode, microseconds in PWM mode) and write.
    void translate(int delta);

    // Adjust left/right independently and write.
    void rotate(int leftDelta, int rightDelta);

    // Halt: centers both (90 deg in Servo mode, 1450 us in PWM mode).
    void halt(float durationInSeconds);

    // Optional helpers (angles when in Servo mode; last requested angle)
    int getLeftValue()  const { return _leftValue; }
    int getRightValue() const { return _rightValue; }
    int getLeftAngle()  const { return _leftAngle; }
    int getRightAngle() const { return _rightAngle; }

private:
    enum class Mode : uint8_t { ServoMode, PwmMode };

    // Mode
    Mode _mode;

    // --- Servo.h mode members ---
    Servo _leftServo;
    Servo _rightServo;

    // --- PWM driver mode members ---
    Adafruit_PWMServoDriver* _pwm = nullptr;
    uint8_t _leftChannel  = 0;
    uint8_t _rightChannel = 1;

    // Bookkeeping (semantic: “current request”)
    int _leftValue;    // generic current value (kept for compatibility)
    int _rightValue;
    int _leftAngle;    // 0..180 (used in Servo mode)
    int _rightAngle;   // 0..180
    uint16_t _leftUS;  // 600..2100 (used in PWM mode)
    uint16_t _rightUS; // 600..2100

    // Helpers
    static int clampAngle(int v);
    static int mapProportionToAngle(int proportion);               // [-100..100] -> [0..180]
    static uint16_t mapProportionToMicrosecond(int proportion);    // [-100..100] -> [600..2100], deadband 1350..1550 => 1450
    void writeCurrent();                                           // Writes to hardware (Servo.write or PWM.writeMicroseconds)
};

#endif // COGSERVO_H
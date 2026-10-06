#ifndef COGSERVO_H
#define COGSERVO_H

#include <Arduino.h>
#include <Servo.h>

// SERVO.H ONLY. The PCA9685 (Adafruit_PWMServoDriver) path was removed: the
// physical robot drives two continuous-rotation servos straight off Arduino
// pins, and the dual-mode code was never exercised. Keeping it cost a real
// bug — the sketch declared a PCA9685, constructed the robot in Servo mode
// anyway, and passed PCA9685 CHANNEL numbers as pin numbers, so the robot
// spun at power-on before any behaviour ran.
class CogServo {
public:
    // --- Constructors ---
    // Default: use the standard Servo.h
    CogServo();


    ~CogServo() = default;

    // ── Neutral pulse widths ──────────────────────────────────────────────
    //
    // The pulse width at which each wheel does NOT turn. Proportion 0 maps
    // here; +/-100 maps SPAN_US either side.
    //
    // One per side because continuous-rotation servos are not identical: if
    // the two neutrals differ, driveProportional(50, 50) does not drive
    // straight, and that reads as a control problem rather than a hardware
    // one. Measure each wheel's stop point and set them per robot.
    //
    // 1500 us is the nominal CR neutral and the right DEFAULT, but it is not
    // a fact about any particular servo. A development pair measured here sat
    // still from 1500 all the way to 1600 — a 100 us dead zone centred nearer
    // 1550 than 1500.
    //
    // WHY MICROSECONDS AND NOT ANGLES: Servo.h maps write(angle) onto
    // 544..2400 us, so write(90) emits 1472 us — 28 us BELOW neutral, about
    // 14% of full speed. "Stop" was a slow spin. Angles cannot express a
    // servo's true neutral; microseconds can.
    static const int DEFAULT_NEUTRAL_US = 1500;
    static const int SPAN_US            = 600;   // +/-100 -> neutral +/- 600

    // Attach two drive outputs on Arduino pins and hold both at neutral.
    void begin(uint8_t leftPin, uint8_t rightPin);

    // Override the measured stop points, in microseconds. Call after begin().
    void setNeutral(int leftNeutralUs, int rightNeutralUs);
    int  leftNeutral()  const { return _leftNeutralUs; }
    int  rightNeutral() const { return _rightNeutralUs; }

    // Drive using proportions in [-100, 100]; 0 is neutral, negative is
    // reverse. Blocks (cooperatively) for durationInSeconds.
    // ── Cooperative wait hook ─────────────────────────────────────────────
    //
    // driveProportional() and drive() hold the robot in a primitive for a
    // fixed duration. That wait used to be a bare delay(), which stops
    // EVERYTHING -- including the BLE stack, which is only serviced from
    // loop(). A 1.0 s primitive therefore left the radio unserviced for a
    // full second, long enough for a scan or a connection attempt to time
    // out, and it is why a running robot appeared to vanish.
    //
    // Set a tick function and the wait calls it repeatedly instead of
    // sleeping. Pass nullptr (the default) to get the old blocking
    // behaviour. The hook must be cheap and must NOT drive the motors.
    //
    //     CogServo::setWaitTick([]{ BLE.poll(); });
    //
    // Static because the sketch has one drivetrain and the hook is a
    // property of the program, not of an instance.
    static void setWaitTick(void (*fn)());

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
    // Last commanded pulse widths, in microseconds.
    int getLeftAngle()  const { return _leftUs; }   // name kept for callers
    int getRightAngle() const { return _rightUs; }
    int getLeftMicros()  const { return _leftUs; }
    int getRightMicros() const { return _rightUs; }

protected:
    // Hold for `seconds`, calling the wait tick if one is installed.
    static void _hold(float seconds);
    static void (*_waitTick)();

private:

    // Mode

    // --- Servo.h mode members ---
    Servo _leftServo;
    Servo _rightServo;

    // --- PWM driver mode members ---

    // Bookkeeping (semantic: “current request”)
    int _leftValue;    // generic current value (kept for compatibility)
    int _rightValue;
    int _leftUs;            // last commanded pulse width
    int _rightUs;
    int _leftNeutralUs;     // this wheel's measured stop point
    int _rightNeutralUs;

    // Helpers
    static int clampMicros(int us);
    // [-100..100] -> microseconds about THIS side's neutral.
    static int mapProportionToMicros(int proportion, int neutralUs);
    void writeCurrent();                                           // Servo.write() on both pins
};

#endif // COGSERVO_H
/*
  drivetrain_baseline.ino
  -----------------------------------------------------------------------------
  BASELINE TEST — no sensors, no field logic. Just drives both wheels equally
  forward, to answer one question: does this robot drive STRAIGHT when commanded
  symmetrically?

  If it drives straight:  the CogServo drivetrain + left-motor inversion are
                          correct; any curving under the potential field is the
                          field math, not the drivetrain.
  If it curves/veers:     there is a drivetrain-level asymmetry (servo trim,
                          wheel/tire, or centering) that would also corrupt any
                          field behavior. Fix this FIRST.

  Servos: LEFT channel 6, RIGHT channel 5 (canonical). Classic AVR board.

  Try the three modes below by changing TEST_MODE:
    0 = drive straight forward (the main baseline)
    1 = pivot in place (left back, right forward) — confirms turn DIRECTION
    2 = stop (sanity: robot should not move)
*/

#include <Servo.h>
#include "CogServo.h"

const int LEFT_SERVO_CHANNEL  = 6;
const int RIGHT_SERVO_CHANNEL = 5;
CogServo drivetrain;

const int TEST_MODE = 0;   // 0=straight, 1=pivot, 2=stop
const int SPEED     = 45;

void setup() {
    Serial.begin(9600);
    drivetrain.begin(LEFT_SERVO_CHANNEL, RIGHT_SERVO_CHANNEL);
    Serial.print("drivetrain_baseline, mode="); Serial.println(TEST_MODE);
}

void loop() {
    if (TEST_MODE == 0) {
        drivetrain.driveProportional(SPEED, SPEED, 0.05);   // both equal -> straight
        Serial.println("straight: L=45 R=45");
    } else if (TEST_MODE == 1) {
        // Matches RE approachLight "turn toward a right-side light": (-,+).
        drivetrain.driveProportional(-SPEED, SPEED, 0.05);
        Serial.println("pivot: L=-45 R=45 (should rotate toward its RIGHT)");
    } else {
        drivetrain.driveProportional(0, 0, 0.05);
        Serial.println("stop: L=0 R=0");
    }
}

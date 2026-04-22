/*
  ir_verify.ino
  -------------
  IR sensor verification sketch.

  Drives slowly toward the north wall, printing raw ADC values each
  loop tick.  Stops when either sensor exceeds STOP_RAW (closer =
  higher ADC), holds briefly, then reverses and repeats.

  Decisions are made on raw ADC values only, matching physical robot
  behaviour.  getData() cm values are printed alongside for reference
  but are never used for control.

  Use with:  py -3.12 main.py --sketch sketches/ir_verify.ino --hud --ir-only
*/

#include <Servo.h>
#include "CogServo.h"
#include "CogProximity.h"

CogServo driveServos;

CogProximity leftIR("A0");
CogProximity rightIR("A1");

const int   STOP_RAW     = 600;   // ADC threshold — stop when either sensor >= this
const int   DRIVE_SPEED  = 30;
const int   REVERSE_SPEED = 30;
const float REVERSE_TIME  = 3.0;

void setup() {
  Serial.begin(9600);
  driveServos.begin(0, 1);
  driveServos.halt(0.0);
}

void loop() {
  int leftRaw  = leftIR.getRawData();
  int rightRaw = rightIR.getRawData();
  int leftCm   = leftIR.getData();
  int rightCm  = rightIR.getData();

  Serial.print("L raw=");
  Serial.print(leftRaw);
  Serial.print(" cm=");
  Serial.print(leftCm);
  Serial.print("  R raw=");
  Serial.print(rightRaw);
  Serial.print(" cm=");
  Serial.println(rightCm);

  if (leftRaw >= STOP_RAW || rightRaw >= STOP_RAW) {
    driveServos.halt(0.0);
    Serial.println("-- STOP --");
    driveServos.driveProportional(-REVERSE_SPEED, -REVERSE_SPEED, REVERSE_TIME);
  } else {
    driveServos.driveProportional(DRIVE_SPEED, DRIVE_SPEED, 0);
  }
}

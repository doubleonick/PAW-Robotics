/*
  ir_static_test.ino
  ------------------
  Stationary IR sensor test.  Motors halted, reads and prints raw ADC
  values only.  cm values printed alongside for reference.

  Use with:  py -3.12 main.py --sketch sketches/ir_static_test.ino
*/

#include <Servo.h>
#include "CogServo.h"
#include "CogProximity.h"

CogServo driveServos;
CogProximity leftIR("A0");
CogProximity rightIR("A1");

void setup() {
  Serial.begin(9600);
  driveServos.begin(0, 1);
  driveServos.halt(0.0);
}

void loop() {
  driveServos.halt(0.0);
  Serial.print("L raw=");
  Serial.print(leftIR.getRawData());
  Serial.print(" cm=");
  Serial.print(leftIR.getData());
  Serial.print("  R raw=");
  Serial.print(rightIR.getRawData());
  Serial.print(" cm=");
  Serial.println(rightIR.getData());
}

/*
  demo_sequence.ino
  -----------------
  Timed spin/drive sequence for basic movement testing.
*/

#include <Servo.h>
#include "CogServo.h"
#include "DemoRobot.h"

CogServo driveServos;
DemoRobot bot(driveServos);

void setup() {
  Serial.begin(9600);
  driveServos.begin(0, 1);
  bot.begin();
}

void loop() {
  bot.runSequence();
}

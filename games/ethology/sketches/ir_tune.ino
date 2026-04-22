/*
  ir_tune.ino
  -----------
  Proportional speed ramp based on IR sensor ADC values.
  Approaches wall, slows, stops, returns, repeats.
*/

#include <Servo.h>
#include "CogServo.h"
#include "IRTuneRobot.h"
#include "CogProximity.h"

CogServo driveServos;
IRTuneRobot bot(driveServos);

void setup() {
  Serial.begin(9600);
  driveServos.begin(0, 1);
  bot.begin();
}

void loop() {
  bot.runSequence();
}

/*
  wall_drive.ino
  --------------
  Drives forward until wall contact, holds 3s pressing against it,
  then resets and repeats through 5 different headings.
*/

#include <Servo.h>
#include "CogServo.h"
#include "WallDriveRobot.h"

CogServo driveServos;
WallDriveRobot bot(driveServos);

void setup() {
  Serial.begin(9600);
  driveServos.begin(0, 1);
  bot.begin();
}

void loop() {
  bot.runSequence();
}

/*
  physics_demo.ino
  ----------------
  Drives the robot into walls at different headings to demonstrate
  rigid-body collision physics.

  Each run drives forward until wall contact is detected, then holds
  for 3 seconds pressing against the wall, then resets to (0,0) at
  the next heading.

  Headings:
    Run 1:  90° — dead into north wall
    Run 2:  70° — glancing into north wall
    Run 3:  45° — into NE corner
    Run 4:   0° — dead into east wall
    Run 5: 135° — into NW corner
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

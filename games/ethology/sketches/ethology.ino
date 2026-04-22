/*
  ethology.ino
  ------------
  Behaviour hierarchy robot.

  Priority (highest first):
    1. ESCAPE    — collision detected: spin away from contact side
    2. AVOID     — IR threshold exceeded: steer away from obstacle
    3. CRUISE    — default: drive forward

  Use with:  py -3.12 main.py --sketch sketches/ethology.ino
*/

#include <Servo.h>
#include "CogServo.h"
#include "EthologyRobot.h"

CogServo driveServos;
EthologyRobot bot(driveServos);

void setup() {
  Serial.begin(9600);
  driveServos.begin(0, 1);
  bot.begin();
}

void loop() {
  bot.hierarchy();
}

/*
  ldr_ethology.ino
  ----------------
  Full ethology with light-seeking added to the hierarchy.

  Priority (highest first):
    1. ESCAPE    — front/rear collision: arc back or spin away
    2. AVOID     — IR threshold exceeded: arc away from obstacle
    3. SEEK      — LDR gradient detected: arc toward brighter side
    4. CRUISE    — default: drive straight forward

  Use with:  py -3.12 main.py --sketch sketches/ldr_ethology.ino
*/

#include <Servo.h>
#include "CogServo.h"
#include "LDREthologyRobot.h"

CogServo driveServos;
LDREthologyRobot bot(driveServos);

void setup() {
  Serial.begin(9600);
  driveServos.begin(0, 1);
  bot.begin();
}

void loop() {
  bot.hierarchy();
}

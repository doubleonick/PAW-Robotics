/*
  contact_test.ino
  ----------------
  Contact sensor reporting sketch.

  Drives slowly forward into a wall, then reverses, reporting all
  four contact sensor states each loop tick.

  OUTPUT convention (INPUT_PULLUP):
    0 = triggered (contact detected)
    1 = clear

  Use with:  py -3.12 main.py --sketch sketches/contact_test.ino
*/

#include <Servo.h>
#include "CogServo.h"
#include "CogCollision.h"

CogServo driveServos;

CogCollision leftFront(4);
CogCollision rightFront(2);
CogCollision leftRear(3);
CogCollision rightRear(5);

const int   DRIVE_SPEED   = 30;
const int   REVERSE_SPEED = 30;
const float REVERSE_TIME  = 2.0;

void setup() {
  Serial.begin(9600);
  driveServos.begin(0, 1);
  driveServos.halt(0.0);
}

void loop() {
  int lf = leftFront.getData();
  int rf = rightFront.getData();
  int lr = leftRear.getData();
  int rr = rightRear.getData();

  Serial.print("LF=");
  Serial.print(lf);
  Serial.print(" RF=");
  Serial.print(rf);
  Serial.print(" LR=");
  Serial.print(lr);
  Serial.print(" RR=");
  Serial.println(rr);

  if (lf == 0 || rf == 0) {
    driveServos.halt(0.0);
    Serial.println("-- FRONT CONTACT --");
    driveServos.driveProportional(-REVERSE_SPEED, -REVERSE_SPEED, REVERSE_TIME);
  } else {
    driveServos.driveProportional(DRIVE_SPEED, DRIVE_SPEED, 0);
  }
}

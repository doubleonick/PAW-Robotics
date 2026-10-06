/*
  ethology_standalone.ino
  -----------------------------------------------------------------------------
  PAW Robot Ethology — STANDALONE reference sketch (no Bluetooth).

  This is the "teach the code" reference for the Robot Ethology lab. It runs ONE
  fixed behavior hierarchy directly on the robot at power-up — no BLE, no host
  needed. It is meant to be READ and EXPLAINED: it shows, in plain code, exactly
  what the behavior hierarchy the students studied actually does.

  It uses the SAME vetted robot classes as the BLE robot (EthologyRobot and the
  Cog* sensor/motor classes), so the behavior is identical to what the physical
  robot does when the corresponding hierarchy is sent over BLE — this sketch is
  just the "unrolled", always-on form of that same logic.

  THE HIERARCHY (priority order, highest first):
      1. escape_front     — if something hits the front, back away
      2. avoid_object     — if something is close ahead, turn from it
      3. approach_light       — otherwise, steer toward the brightest light
      4. cruise_straight  — if nothing else applies, drive straight

  Subsumption: each tick we check behaviors from the top down and run the FIRST
  one whose condition is met. Higher behaviors "subsume" (override) lower ones.
*/

#include "EthologyRobot.h"

// Servo channels (match the robot's wiring)
const int LEFT_SERVO_PIN  = 6;
const int RIGHT_SERVO_PIN = 5;

EthologyRobot bot;

void setup() {
    Serial.begin(9600);
    bot.begin(LEFT_SERVO_PIN, RIGHT_SERVO_PIN);
}

void loop() {
    // Sense first. readSensors() halts the motors and samples every
    // sensor once, so the guards below all see the same reading and a
    // tick where nothing fires leaves the robot stopped. hierarchy()
    // does this itself; this sketch hand-writes its rungs, so it must
    // call it explicitly.
    bot.readSensors();

    // ── The behavior hierarchy, checked top (highest priority) to bottom. ──
    // Read each sensor condition; run the first behavior whose condition holds.
    // This is exactly the subsumption arbitration the students inferred by
    // watching the robot — written out as code.

//    // 1. escape_front — highest priority: react to a front collision.
//    if (bot.collisionThreshold()) {
//        bot.escapeFrontCollision();
//        return;                          // a higher behavior fired; stop here
//    }
//
//    // 2. avoid_object — something close in front (but no collision yet).
//    else if (bot.proximityThreshold()) {
//        bot.avoidObject();
//        return;
//    }

    // 3. approach_light — no obstacle: steer toward the brightest light.
//    else 
    if (bot.lightGradientThreshold()) {
        bot.avoidLight();
        return;
    }

    // 4. cruise_straight — default fallback: nothing else applies, drive on.
    bot.cruiseStraight();
}

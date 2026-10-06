/*
  colorpal_seek_light.ino
  -----------------------------------------------------------------------------
  Single-sensor light-seeking on a two-wheeled proportional-drive robot.

  Control law (inspired by a tadpole that always swims forward and deflects its
  tail by how fast sensed light is changing — but here it's a differential-drive
  robot, no tail):

    * The ColorPAL is mounted on the LEFT, pointed OUT to the left, in LEDs-off
      incident-light mode (CogVisLight::readLight).
    * Each cycle: delta = current_light - previous_light.
    * Steer by the SIGN and MAGNITUDE of delta, on top of a constant forward
      drive (the robot always rolls forward — the "always swimming" part):
          left  = BASE - GAIN * delta
          right = BASE + GAIN * delta
      -> current > previous (brighter): right faster => turn LEFT  (toward the
         left-pointed sensor's light).
      -> current < previous (dimmer):  left  faster => turn RIGHT (swing the
         left sensor back toward the source).
    * No deadband — pure response, twitches and all.

  The robot continuously steers to keep its left-pointed sensor seeing more
  light, hunting toward the source through motion itself.

  HARDWARE:
    ColorPAL SIG -> SIG_PIN (6), +5V -> 5V, GND -> GND.  Classic AVR board.
    Servos: LEFT channel 6, RIGHT channel 5.
    Mount the sensor on the LEFT of the robot, aimed OUT to the left.

  TUNING: BASE (forward speed), GAIN (how hard a given light-change steers),
  SLICE_SEC (control-loop slice). GAIN is the main knob — too high = wild
  swings, too low = sluggish tracking.
*/

#include "CogVisLight.h"
#include <Servo.h>
#include "CogServo.h"

// ── Light sensor (LEFT-mounted, aimed left, LEDs-off incident-light mode) ──
const uint8_t SIG_PIN  = 6;
const long    PAL_BAUD = 4800;
CogVisLight   light(SIG_PIN, PAL_BAUD);

// ── Drivetrain ──
const int LEFT_SERVO_CHANNEL  = 6;
const int RIGHT_SERVO_CHANNEL = 5;
CogServo  drive;

// ── Tadpole-style control tuning ──
// GAIN is the main knob. In simulation, higher gain tightens the inward spiral
// (helical klinotaxis); too-low gain wanders more than it spirals. The RIGHT
// value depends on your sensor's real directional response and the actual size
// of the light deltas per step, so expect to tune this on hardware. Start here
// and raise GAIN if the robot wanders instead of spiralling toward the light;
// lower it if the steering is violently twitchy.
const int   BASE      = 35;     // constant forward drive (always rolling)
const float GAIN      = 2.0;    // wheel offset per unit of light-delta
const float SLICE_SEC = 0.12;   // control-loop time slice

int previousLight = -1;         // last reading (-1 = none yet)

static int clampProp(int v) {
    if (v >  100) return  100;
    if (v < -100) return -100;
    return v;
}

void setup() {
    Serial.begin(9600);
    Serial.println("ColorPAL tadpole-style light-seek (left sensor, delta steering)");
    drive.begin(LEFT_SERVO_CHANNEL, RIGHT_SERVO_CHANNEL);
    light.beginLightMode();
    delay(300);
}

void loop() {
    int now;
    if (!light.readLight(&now)) {
        // Dropped frame: keep swimming straight forward, try again next cycle.
        drive.driveProportional(BASE, BASE, SLICE_SEC);
        return;
    }

    if (previousLight < 0) {          // first reading: establish baseline
        previousLight = now;
        drive.driveProportional(BASE, BASE, SLICE_SEC);
        return;
    }

    int delta = now - previousLight;                 // temporal light change
    int offset = (int)(GAIN * delta);                // steering deflection

    int leftProp  = clampProp(BASE - offset);        // brighter -> left slower
    int rightProp = clampProp(BASE + offset);        // brighter -> right faster
    drive.driveProportional(leftProp, rightProp, SLICE_SEC);

    Serial.print("light="); Serial.print(now);
    Serial.print(" delta="); Serial.print(delta);
    Serial.print(" -> L="); Serial.print(leftProp);
    Serial.print(" R="); Serial.println(rightProp);

    previousLight = now;
}

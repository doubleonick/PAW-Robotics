/*
  potential_field_standalone.ino  —  CHARACTERIZATION RIG
  =============================================================================
  A potential-field robot test rig for MAPPING what push/pull can produce, so
  the simulation can later be matched to measured reality.

  COORDINATE CONVENTION (matches ethology/robot.json + the sim + physical robot):
      +Y = FORWARD  (toward the front of the robot)
      +X = RIGHT    (so LEFT sensors have NEGATIVE x, RIGHT have POSITIVE x)
      origin = robot geometric centre; offsets in metres.
    Lateral axis = X (this is the L/C/R axis). Forward axis = Y.
    angle_deg = orientation the sensor POINTS, degrees CCW from forward (+Y);
      positive leans LEFT, negative leans RIGHT. (Engine-verified on hardware.)

  SENSOR CONVENTION (matches robot.json IDs):
    * Each sensor id is TYPE·ZONE, e.g. IR·L, LDR·C1.
    * ZONE is DERIVED from x_m (the LATERAL axis) by the peg rule
      (PLEG_SPACING_M = 0.008):
          C : |x_m| <= 0.008   (the 3 middle peg positions)
          R : x_m  >  0.008    (+X = right)
          L : x_m  < -0.008
      Same-zone sensors numbered front-to-back (C1, C2, ...).
    * channel = W/R/G/B (from BYOV); "W" = plain LDR / IR.

  When you PHYSICALLY move a sensor, edit its row so x_m/y_m/angle match the
  hardware. The id's zone letter should agree with the x_m rule — setup() warns
  over serial if they disagree (a HW/SW-drift guard).

  NOTE: the point-mass CogPotentialField engine currently only CONSUMES
  angle_deg; x_m/y_m are carried for register with the sim and logged, not yet
  used in the vector math.

  KNOWN INCONSISTENCY (flagged, not fixed here): games/valentinos/data/byov/
  robot.json uses the OPPOSITE axis labels (x_m=forward, y_m=lateral). The suite
  should be reconciled to this ethology/sim convention (y=forward, x=lateral),
  but that touches shipped sim data and is a separate decision.

  FUTURE (recorded, NOT built): a RADIAL mounting scheme (bearing+radius from
  centre; orientation relative to mounting face) would generalise better for
  sensors on an octagon's faces. Too big a reconfig now.

  Drivetrain ground truth (drivetrain_baseline): driveProportional(+L,-R) pivots
  the robot toward its RIGHT.
  =============================================================================
*/

#include "CogProximity.h"
#include "CogLight.h"
#include "CogPotentialField.h"
#include <Servo.h>
#include "CogServo.h"

// ============================ ROBOT CONFIG ==================================
// EDIT to match the physical robot. One row per sensor. Fields:
//   id     : "TYPE·ZONE" (zone is derived from x_m; id is for logging/register)
//   type   : SENSOR_IR (proximity) or SENSOR_LDR (light)
//   pin    : analog pin label, e.g. "A0"
//   x_m    : LATERAL offset, metres (+ = RIGHT, - = LEFT)  [zone derives from this]
//   y_m    : FORWARD offset, metres (+ = front)
//   angle  : orientation, deg CCW from forward (+Y). + leans LEFT, - leans RIGHT.
//   channel: 'W','R','G','B' (W = plain).
//   policy : POL_PUSH (repel/avoid) or POL_PULL (attract/seek)
//   gain   : contribution scale (1.0 nominal)
// Comment a row out to drop that sensor (IR-only / LDR-only isolation tests).

#define TRIAL_LABEL "trial: LDR·L/R pull + IR·L/R push (default)"

enum SensorType { SENSOR_IR, SENSOR_LDR };
enum PolicyTag  { POL_PUSH, POL_PULL };

struct SensorConfig {
    const char* id;       // "TYPE·ZONE"
    SensorType  type;
    const char* pin;
    float       x_m;      // LATERAL offset (+right / -left) -> zone
    float       y_m;      // FORWARD offset (+front)
    float       angle;    // orientation, deg CCW from +Y (+left / -right)
    char        channel;  // 'W'/'R'/'G'/'B'
    PolicyTag   policy;
    float       gain;
};

// ---- THE TABLE (edit rows to match the physical build) ----
//   Left sensors: NEGATIVE x_m.  Right sensors: POSITIVE x_m.  Forward: +y_m.
SensorConfig CONFIG[] = {
    { "IR\xB7L",  SENSOR_IR,  "A0", -0.040f, 0.072f,  25.0f, 'W', POL_PUSH, 1.0f },
    { "IR\xB7R",  SENSOR_IR,  "A1",  0.040f, 0.072f, -25.0f, 'W', POL_PUSH, 1.0f },
    { "LDR\xB7L", SENSOR_LDR, "A2", -0.040f, 0.056f,  40.0f, 'W', POL_PULL, 1.0f },
    { "LDR\xB7R", SENSOR_LDR, "A3",  0.040f, 0.056f, -40.0f, 'W', POL_PULL, 1.0f },
};
const int NUM_SENSORS = sizeof(CONFIG) / sizeof(CONFIG[0]);

const float PLEG_SPACING_M = 0.008f;   // L/C/R peg rule threshold on x_m

// ---- Drivetrain + engine tuning ----
const int   LEFT_SERVO_CHANNEL  = 6;
const int   RIGHT_SERVO_CHANNEL = 5;
const int   BASE_SPEED   = 45;
const float FORWARD_GAIN = 0.6f;
const float TURN_GAIN    = 1.2f;
const int   TICK_MS      = 50;
// ===========================================================================

CogServo          drivetrain;
CogPotentialField field;

CogProximity* irByIndex[16]  = { nullptr };
CogLight*     ldrByIndex[16] = { nullptr };
unsigned long tickCount = 0;

// Derive L/C/R zone from a LATERAL offset x_m (+X = right).
char zoneOf(float x_m) {
    if (x_m >  PLEG_SPACING_M) return 'R';
    if (x_m < -PLEG_SPACING_M) return 'L';
    return 'C';
}

void setup() {
    Serial.begin(9600);
    drivetrain.begin(LEFT_SERVO_CHANNEL, RIGHT_SERVO_CHANNEL);

    for (int i = 0; i < NUM_SENSORS; i++) {
        SensorConfig& c = CONFIG[i];
        CogPotentialField::Policy pol =
            (c.policy == POL_PULL) ? CogPotentialField::Policy::Pull
                                   : CogPotentialField::Policy::Push;
        if (c.type == SENSOR_IR) {
            CogProximity* s = new CogProximity(c.pin);
            irByIndex[i] = s;
            field.addProximity(s, c.angle, c.gain, pol);
        } else {
            CogLight* s = new CogLight(c.pin);
            ldrByIndex[i] = s;
            field.addLight(s, c.angle, c.gain, pol);
        }
    }

    field.setBaseSpeed(BASE_SPEED);
    field.setDriveGains(FORWARD_GAIN, TURN_GAIN);

    // ---- Run header: self-describing so a saved log knows its provenance ----
    Serial.println();
    Serial.print("# "); Serial.println(TRIAL_LABEL);
    Serial.println("# convention: +Y=forward, +X=right; zone from x_m (lateral)");
    for (int i = 0; i < NUM_SENSORS; i++) {
        SensorConfig& c = CONFIG[i];
        char derived = zoneOf(c.x_m);
        Serial.print("# "); Serial.print(c.id);
        Serial.print("  type="); Serial.print(c.type == SENSOR_IR ? "IR" : "LDR");
        Serial.print(" pin="); Serial.print(c.pin);
        Serial.print(" x_m="); Serial.print(c.x_m, 3);
        Serial.print(" y_m="); Serial.print(c.y_m, 3);
        Serial.print(" ang="); Serial.print(c.angle, 0);
        Serial.print(" ch="); Serial.print(c.channel);
        Serial.print(c.policy == POL_PULL ? " pull" : " push");
        Serial.print(" g="); Serial.print(c.gain, 1);
        Serial.print("  zone(derived)="); Serial.print(derived);
        const char* dot = strchr(c.id, '\xB7');
        if (dot && *(dot+1) && *(dot+1) != derived) {
            Serial.print("  <<< WARN: id zone != x_m-derived zone (HW/SW drift?)");
        }
        Serial.println();
    }
    Serial.print("# base="); Serial.print(BASE_SPEED);
    Serial.print(" fGain="); Serial.print(FORWARD_GAIN, 2);
    Serial.print(" tGain="); Serial.print(TURN_GAIN, 2);
    Serial.print(" tick_ms="); Serial.println(TICK_MS);

    // ---- CSV column header ----
    Serial.print("tick");
    for (int i = 0; i < NUM_SENSORS; i++) { Serial.print(','); Serial.print(CONFIG[i].id); }
    Serial.println(",Vx,Vy,L,R");
}

void loop() {
    field.computeNetVector(nullptr, nullptr);

    int leftProp = 0, rightProp = 0;
    field.vectorToDifferential(&leftProp, &rightProp);
    drivetrain.driveProportional(leftProp, rightProp, TICK_MS / 1000.0f);

    Serial.print(tickCount++);
    for (int i = 0; i < NUM_SENSORS; i++) {
        Serial.print(',');
        if (CONFIG[i].type == SENSOR_IR) Serial.print(irByIndex[i]->peekData());
        else                             Serial.print(ldrByIndex[i]->peekData());
    }
    Serial.print(','); Serial.print(field.netVx(), 3);
    Serial.print(','); Serial.print(field.netVy(), 3);
    Serial.print(','); Serial.print(leftProp);
    Serial.print(','); Serial.println(rightProp);
}

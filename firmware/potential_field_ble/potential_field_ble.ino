/*
  potential_field_ble.ino  —  CHARACTERIZATION RIG with WIRELESS (BLE) LOGGING
  =============================================================================
  Same potential-field characterization rig as potential_field_standalone, but
  it also STREAMS the per-tick CSV log over BLE so trials can be captured
  wirelessly (no USB tether). Requires a BLE-capable board — UNO R4 WiFi.

  On the PC, run tools/pf_ble_logger.py to connect, receive the stream, and
  write it to a timestamped file. The robot RUNS with or without a receiver
  connected — BLE logging is opportunistic (skipped when no one's listening).

  Conventions unchanged from potential_field_standalone:
    +Y = FORWARD, +X = RIGHT; zone from x_m (lateral). See that sketch's header
    for the full CONFIG-field explanation.
  =============================================================================
*/

#include "CogProximity.h"
#include "CogLight.h"
#include "CogPotentialField.h"
#include <Servo.h>
#include "CogServo.h"
#include "CogBleLog.h"

// ============================ ROBOT CONFIG ==================================
// (Preserved from your current potential_field_standalone edits.)
#define TRIAL_LABEL "trial: IR·L pull@135 + IR·R pull@-45 (LDRs off)"

enum SensorType { SENSOR_IR, SENSOR_LDR };
enum PolicyTag  { POL_PUSH, POL_PULL };

struct SensorConfig {
    const char* id;
    SensorType  type;
    const char* pin;
    float       x_m;      // LATERAL (+right / -left) -> zone
    float       y_m;      // FORWARD (+front)
    float       angle;    // orientation, deg CCW from +Y (+left / -right)
    char        channel;
    PolicyTag   policy;
    float       gain;
};

SensorConfig CONFIG[] = {
    { "IR\xB7L",  SENSOR_IR,  "A0", -0.040f, 0.072f,  135.0f, 'W', POL_PULL, 1.0f },
    { "IR\xB7R",  SENSOR_IR,  "A1",  0.040f, 0.072f,  -45.0f, 'W', POL_PULL, 1.0f },
//    { "LDR\xB7R", SENSOR_LDR, "A2",  0.040f, 0.056f,  -90.0f, 'W', POL_PULL, 1.0f },
//    { "LDR\xB7L", SENSOR_LDR, "A3", -0.040f, 0.056f,   90.0f, 'W', POL_PULL, 1.0f },
};
const int NUM_SENSORS = sizeof(CONFIG) / sizeof(CONFIG[0]);

const float PLEG_SPACING_M = 0.008f;

// ---- Drivetrain + engine tuning ----
const int   LEFT_SERVO_CHANNEL  = 6;
const int   RIGHT_SERVO_CHANNEL = 5;
const int   BASE_SPEED   = 45;
const float FORWARD_GAIN = 0.6f;
const float TURN_GAIN    = 1.2f;
const int   TICK_MS      = 50;

// ---- BLE logging ----
#define BLE_DEVICE_NAME   "PAW-PField"
// Stream a log line every N control ticks (decoupled from the 50ms control
// loop). 1 = every tick (~20 Hz, may stress BLE). 4 = ~5 Hz (safer wireless).
const int   LOG_EVERY_N_TICKS = 4;
const bool  ALSO_SERIAL       = true;   // keep USB serial log too (harmless untethered)
// ===========================================================================

CogServo          drivetrain;
CogPotentialField field;
CogBleLog         blelog;

CogProximity* irByIndex[16]  = { nullptr };
CogLight*     ldrByIndex[16] = { nullptr };
unsigned long tickCount = 0;

char zoneOf(float x_m) {
    if (x_m >  PLEG_SPACING_M) return 'R';
    if (x_m < -PLEG_SPACING_M) return 'L';
    return 'C';
}

// Build the run-header lines (same info as the serial header) so a captured
// BLE log is self-describing. Sent both to Serial and over BLE at startup and
// again whenever a fresh receiver connects.
void emitHeader(bool toBle) {
    String h1 = String("# ") + TRIAL_LABEL;
    String h2 = "# convention: +Y=forward, +X=right; zone from x_m (lateral)";
    if (ALSO_SERIAL) { Serial.println(); Serial.println(h1); Serial.println(h2); }
    if (toBle) { blelog.send(h1); blelog.send(h2); }

    for (int i = 0; i < NUM_SENSORS; i++) {
        SensorConfig& c = CONFIG[i];
        char derived = zoneOf(c.x_m);
        String row = String("# ") + c.id + " type=" + (c.type==SENSOR_IR?"IR":"LDR")
                   + " pin=" + c.pin + " x_m=" + String(c.x_m,3) + " y_m=" + String(c.y_m,3)
                   + " ang=" + String(c.angle,0) + " ch=" + c.channel
                   + (c.policy==POL_PULL?" pull":" push") + " g=" + String(c.gain,1)
                   + "  zone(derived)=" + derived;
        const char* dot = strchr(c.id, '\xB7');
        if (dot && *(dot+1) && *(dot+1) != derived) row += "  <<< WARN: id zone != x_m zone";
        if (ALSO_SERIAL) Serial.println(row);
        if (toBle) blelog.send(row);
    }
    String tune = String("# base=") + BASE_SPEED + " fGain=" + String(FORWARD_GAIN,2)
                + " tGain=" + String(TURN_GAIN,2) + " tick_ms=" + TICK_MS
                + " log_every=" + LOG_EVERY_N_TICKS;
    if (ALSO_SERIAL) Serial.println(tune);
    if (toBle) blelog.send(tune);

    // CSV column header
    String cols = "tick";
    for (int i = 0; i < NUM_SENSORS; i++) cols += String(",") + CONFIG[i].id;
    cols += ",Vx,Vy,L,R";
    if (ALSO_SERIAL) Serial.println(cols);
    if (toBle) blelog.send(cols);
}

bool _bleWasConnected = false;

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

    blelog.begin(BLE_DEVICE_NAME);   // advertise; robot runs regardless

    emitHeader(false);               // serial header at boot
}

void loop() {
    blelog.poll();                   // service BLE

    // Header delivery over BLE is timing-sensitive: at the moment a central
    // first connects it may not have SUBSCRIBED to notifications yet, so a
    // single connect-edge send can be lost. So we (a) send on the connect edge
    // AND (b) re-send periodically, guaranteeing every capture gets a header
    // block within a few seconds regardless of when the receiver attached.
    bool nowConn = blelog.connected();
    bool justConnected = nowConn && !_bleWasConnected;
    _bleWasConnected = nowConn;

    static unsigned long lastHeaderMs = 0;
    if (nowConn && (justConnected || millis() - lastHeaderMs > 5000)) {
        emitHeader(true);
        lastHeaderMs = millis();
    }

    // --- control tick ---
    field.computeNetVector(nullptr, nullptr);
    int leftProp = 0, rightProp = 0;
    field.vectorToDifferential(&leftProp, &rightProp);
    drivetrain.driveProportional(leftProp, rightProp, TICK_MS / 1000.0f);

    // --- build the CSV line ---
    // Use peekData() (NOT getData()) so the logged reading is the EXACT sample
    // computeNetVector() just consumed this tick — not a fresh second ADC sample.
    // This keeps each row internally consistent: its readings are the ones that
    // produced its Vx/Vy/L/R. (getData() re-samples; peekData() returns cache.)
    String line = String(tickCount);
    for (int i = 0; i < NUM_SENSORS; i++) {
        line += ",";
        if (CONFIG[i].type == SENSOR_IR) line += String(irByIndex[i]->peekData());
        else                             line += String(ldrByIndex[i]->peekData());
    }
    line += String(",") + String(field.netVx(),3) + "," + String(field.netVy(),3)
          + "," + leftProp + "," + rightProp;

    if (ALSO_SERIAL) Serial.println(line);

    // Stream over BLE every N ticks (decoupled rate to stay within BLE comfort).
    if (nowConn && (tickCount % LOG_EVERY_N_TICKS == 0)) blelog.send(line);

    tickCount++;
}

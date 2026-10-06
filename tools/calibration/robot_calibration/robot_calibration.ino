/*
  robot_calibration.ino  (revised)
  ---------------------------------
  Closed-loop BLE calibration for the Uno R4 WiFi.

  Flow
  ----
  1. Robot advertises "PAW-Calibration" and waits for a host to connect.
  2. Host connects, robot sends {"t":"ready"}.
  3. Each phase begins only when the host sends {"cmd":"next"}.
     Between phases the robot sits still and waits — giving the operator
     time to reposition the robot, move a light source, etc.
  4. Within a phase, the robot runs autonomously until the phase ends
     (time limit, contact event, or timeout), then sends {"t":"done","p":N}
     and waits for the next {"cmd":"next"}.
  5. After all phases the robot sends {"t":"complete"} and returns to idle.
  6. The host may send {"cmd":"abort"} at any time to halt immediately.

  Commands (host → robot):
      {"cmd":"next"}            begin the current waiting phase
      {"cmd":"abort"}           stop motors and end calibration
      {"cmd":"ping"}            check connection

  Packets (robot → host, one JSON line each):
      {"t":"ready", ...}        connected and waiting for phase 1
      {"t":"waiting","p":N,"prompt":"..."}   ready for operator action
      {"t":"phase","p":N,"name":"..."}       phase starting
      {"t":"s","p":N,"ms":...,"rPR":...}     sensor sample
      {"t":"contact","p":N,"ms":...}         bumper fired
      {"t":"done","p":N}                     phase complete
      {"t":"complete"}                       all phases done

  Phases
  ------
  1  Spin in place — operator counts wheel rotations, then sends next
  2  Straight cruise, open space — no wall needed
  3  Approach wall until contact — operator positions robot first
  4  LDR static — operator moves light to distances, confirms each
  5  Approach wall from second distance — cross-validation
*/

#include <ArduinoBLE.h>
#include "EthologyRobot.h"

// ── Physical constants — edit before flashing ─────────────────────────────────
static const float WHEEL_RADIUS_MM    = 24.0f;

// ── Servo and timing parameters ───────────────────────────────────────────────
static const int   LEFT_SERVO_PIN     = 6;
static const int   RIGHT_SERVO_PIN    = 5;



static const int   SPIN_PROPORTION    = 60;
static const int   CRUISE_PROPORTION  = 60;
static const float SPIN_DURATION_S    = 4.0f;
static const float CRUISE_DURATION_S  = 2.0f;
static const float APPROACH_TIMEOUT_S = 12.0f;
static const int   SAMPLE_MS          = 100;
static const int   LDR_BURSTS         = 20;
static const int   LDR_BURST_MS       = 500;

// ── BLE ───────────────────────────────────────────────────────────────────────
BLEService         calService("19B10000-E8F2-537E-4F6C-D104768A1214");
BLEStringCharacteristic cmdChar ("19B10001-E8F2-537E-4F6C-D104768A1214",
                                  BLEWrite, 64);
BLEStringCharacteristic dataChar("19B10002-E8F2-537E-4F6C-D104768A1214",
                                  BLERead | BLENotify, 128);

// ── Hardware ──────────────────────────────────────────────────────────────────
// EthologyRobot owns its CogServo drivetrain internally.
EthologyRobot bot;

// ── State ─────────────────────────────────────────────────────────────────────
static bool g_aborted = false;

// ── Helpers ───────────────────────────────────────────────────────────────────

void send(const String& json) {
    dataChar.writeValue(json);
    Serial.println(json);
}

String sample(int phase, uint32_t ms, int pwL, int pwR) {
    return "{\"t\":\"s\",\"p\":"  + String(phase)
         + ",\"ms\":"   + String(ms)
         + ",\"rPR\":"  + String(bot.rightProx.getRawData())
         + ",\"rPL\":"  + String(bot.leftProx.getRawData())
         + ",\"rLR\":"  + String(bot.rightLight.getRawData())
         + ",\"rLL\":"  + String(bot.leftLight.getRawData())
         + ",\"bR\":"   + String(bot.rightFrontBump.getData())
         + ",\"bL\":"   + String(bot.leftFrontBump.getData())
         + ",\"pwL\":"  + String(pwL)
         + ",\"pwR\":"  + String(pwR)
         + "}";
}

// haltMotors() replaced by direct driveProportional(0,0,t) call.
// bot.halt() produces unexpected servo motion; driveProportional(0,0,t) works.
#define haltMotors() bot.driveProportional(0, 0, 0.4)

// Block until {"cmd":"next"} received or abort
bool waitForNext(int phase, const String& prompt) {
    send("{\"t\":\"waiting\",\"p\":" + String(phase)
         + ",\"prompt\":\"" + prompt + "\"}");
    while (true) {
        if (!BLE.central().connected()) return false;
        if (cmdChar.written()) {
            String val = cmdChar.value();
            val.trim();
            if (val.indexOf("abort") >= 0) { g_aborted = true; return false; }
            if (val.indexOf("next")  >= 0) return true;
        }
        delay(20);
    }
}

bool checkAbort() {
    if (cmdChar.written()) {
        String val = cmdChar.value();
        val.trim();
        if (val.indexOf("abort") >= 0) {
            g_aborted = true;
            haltMotors();
            return true;
        }
    }
    return false;
}

// ── Phases ────────────────────────────────────────────────────────────────────

void phase1_spin() {
    send("{\"t\":\"phase\",\"p\":1,\"name\":\"spin\","
         "\"prop\":" + String(SPIN_PROPORTION) + ","
         "\"duration_s\":" + String(SPIN_DURATION_S) + "}");

    uint32_t start = millis();
    uint32_t dur   = (uint32_t)(SPIN_DURATION_S * 1000);
    uint32_t last  = 0;

    bot.driveProportional(SPIN_PROPORTION, -SPIN_PROPORTION, 0);
    while (millis() - start < dur) {
        if (checkAbort()) return;
        uint32_t el = millis() - start;
        if (el - last >= SAMPLE_MS) {
            send(sample(1, el, SPIN_PROPORTION, -SPIN_PROPORTION));
            last = el;
        }
    }
    haltMotors();
    delay(400);   // allow servos to reach neutral before next phase
    send("{\"t\":\"done\",\"p\":1}");
}

void phase2_cruise_open() {
    send("{\"t\":\"phase\",\"p\":2,\"name\":\"cruise_open\","
         "\"prop\":" + String(CRUISE_PROPORTION) + "}");

    uint32_t start = millis();
    uint32_t dur   = (uint32_t)(CRUISE_DURATION_S * 1000);
    uint32_t last  = 0;

    bot.driveProportional(CRUISE_PROPORTION, CRUISE_PROPORTION, 0);
    while (millis() - start < dur) {
        if (checkAbort()) return;
        uint32_t el = millis() - start;
        if (el - last >= SAMPLE_MS) {
            send(sample(2, el, CRUISE_PROPORTION, CRUISE_PROPORTION));
            last = el;
        }
    }
    haltMotors();
    delay(400);
    send("{\"t\":\"done\",\"p\":2}");
}

void phase3_approach(int phaseNum, float startDistCm) {
    send("{\"t\":\"phase\",\"p\":" + String(phaseNum)
         + ",\"name\":\"approach_contact\""
         + ",\"start_cm\":" + String(startDistCm)
         + ",\"prop\":"     + String(CRUISE_PROPORTION) + "}");

    uint32_t start   = millis();
    uint32_t timeout = (uint32_t)(APPROACH_TIMEOUT_S * 1000);
    uint32_t last    = 0;
    bool     hit     = false;

    bot.driveProportional(CRUISE_PROPORTION, CRUISE_PROPORTION, 0);
    while (millis() - start < timeout) {
        if (checkAbort()) return;
        uint32_t el = millis() - start;
        int bL = bot.leftFrontBump.getData();
        int bR = bot.rightFrontBump.getData();
        if (bL == 0 || bR == 0) {
            haltMotors();
            String side = (bL == 0 && bR == 0) ? "both" : (bL == 0 ? "L" : "R");
            send(sample(phaseNum, el, CRUISE_PROPORTION, CRUISE_PROPORTION));
            send("{\"t\":\"contact\",\"p\":" + String(phaseNum)
                 + ",\"ms\":"   + String(el)
                 + ",\"side\":\"" + side + "\""
                 + ",\"bL\":"   + String(bL)
                 + ",\"bR\":"   + String(bR) + "}");
            hit = true;
            break;
        }
        if (el - last >= SAMPLE_MS) {
            send(sample(phaseNum, el, CRUISE_PROPORTION, CRUISE_PROPORTION));
            last = el;
        }
    }
    haltMotors();
    delay(400);
    if (!hit) send("{\"t\":\"timeout\",\"p\":" + String(phaseNum) + "}");
    send("{\"t\":\"done\",\"p\":" + String(phaseNum) + "}");
}

void phase4_ldr() {
    send("{\"t\":\"phase\",\"p\":4,\"name\":\"ldr_static\","
         "\"bursts\":" + String(LDR_BURSTS) + ","
         "\"burst_ms\":" + String(LDR_BURST_MS) + "}");

    for (int b = 0; b < LDR_BURSTS; b++) {
        if (checkAbort()) return;
        send(sample(4, (uint32_t)b * LDR_BURST_MS, 0, 0));
        delay(LDR_BURST_MS);
    }
    send("{\"t\":\"done\",\"p\":4}");
}

// ── Arduino entry points ──────────────────────────────────────────────────────

void setup() {
    Serial.begin(9600);
    bot.begin(LEFT_SERVO_PIN, RIGHT_SERVO_PIN);

    if (!BLE.begin()) {
        Serial.println("BLE init failed");
        while (true);
    }
    BLE.setLocalName("PAW-Calibration");
    BLE.setAdvertisedService(calService);
    calService.addCharacteristic(cmdChar);
    calService.addCharacteristic(dataChar);
    BLE.addService(calService);
    dataChar.writeValue("{\"t\":\"ready\"}");
    BLE.advertise();
    Serial.println("PAW-Calibration ready");
}

void loop() {
    BLEDevice central = BLE.central();
    if (!central) return;

    Serial.print("Connected: "); Serial.println(central.address());
    g_aborted = false;

    delay(500);   // let host's notify subscription register before ready packet
    send("{\"t\":\"ready\","
         "\"wheel_radius_mm\":" + String(WHEEL_RADIUS_MM) + ","
         "\"spin_prop\":"       + String(SPIN_PROPORTION)  + ","
         "\"cruise_prop\":"     + String(CRUISE_PROPORTION) + ","
         "\"sample_ms\":"       + String(SAMPLE_MS) + "}");

    // Phase 1 — spin
    if (!waitForNext(1, "Place robot in open space. Press Enter to spin."))
        goto done;
    phase1_spin();
    if (g_aborted) goto done;

    // Phase 2 — open cruise (runs immediately after spin, no repositioning needed)
    if (!waitForNext(2, "Robot will drive straight briefly. Press Enter."))
        goto done;
    phase2_cruise_open();
    if (g_aborted) goto done;

    // Phase 3 — approach contact
    if (!waitForNext(3, "Position robot facing wall. Enter start distance, then Enter."))
        goto done;
    // start_cm is passed in via the next command — we use the default
    // because the Python side records it; the sketch just drives.
    phase3_approach(3, 60.0f);
    if (g_aborted) goto done;

    // Phase 4 — LDR static
    if (!waitForNext(4, "Place light source at first distance. Press Enter to begin LDR sampling."))
        goto done;
    phase4_ldr();
    if (g_aborted) goto done;

    // Phase 5 — validation approach
    if (!waitForNext(5, "Position robot at second distance from wall. Enter distance, then Enter."))
        goto done;
    phase3_approach(5, 40.0f);
    if (g_aborted) goto done;

    send("{\"t\":\"complete\","
         "\"wheel_radius_mm\":" + String(WHEEL_RADIUS_MM) + ","
         "\"spin_prop\":"       + String(SPIN_PROPORTION)  + ","
         "\"cruise_prop\":"     + String(CRUISE_PROPORTION) + ","
         "\"sample_ms\":"       + String(SAMPLE_MS) + "}");

done:
    haltMotors();
    Serial.println("Session ended — re-advertising");
    // Re-advertise so the host can reconnect without resetting the board
    BLE.advertise();
}

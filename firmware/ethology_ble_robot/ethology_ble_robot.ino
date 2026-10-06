/*
  ethology_robot_firmware.ino
  ---------------------------
  27 Aug 2026

  PAW Ethology robot sketch — BLE hierarchy dispatch.

  Merge of ethologyPrototypeV2.ino (robot behaviour + CogDisplay) and
  ethology_ble_robot.ino (BLE command handling).

  SEPARATION OF CONCERNS
  ----------------------
      CogBluetooth   communications only.  Receives a hierarchy as a list
                     of strings and hands it over.  Knows nothing about
                     robots or behaviours.

      EthologyRobot  owns the behaviour vocabulary, validates and stores a
                     hierarchy, and executes it via hierarchy().

      this sketch    the state machine that wires the two together.

  STATE MACHINE
  -------------
      ADVERTISING ──connected──> LISTENING ──valid hierarchy──> RUNNING
           ^                         |                             |
           └──disconnected (1s)──────┘                       (no exit)

      ADVERTISING  BLE advertising.  NO motor action.
      LISTENING    Connected, waiting for a hierarchy.  NO motor action.
                   A dropped link returns to ADVERTISING, but only after
                   the BLEDisconnected handler fires, so a
                   brief glitch does not bounce the state.
      RUNNING      A hierarchy is installed and executes every tick until
                   power off.  Connection state is NEVER consulted here:
                   the link may drop, recover, or drop again and the robot
                   keeps running.  This is what stops the display and the
                   motors from flapping with the connection.

  Once RUNNING is entered, the ONLY exit is power off.  "stop" and "reset"
  arriving over BLE are answered with an error by CogBluetooth and do not
  halt the robot.

  Files required in this sketch folder:
      ethology_robot_firmware.ino  (this file)
      CogBluetooth.h / .cpp        (BLE transport)
      CogDisplay.h / .cpp          (GIGA Display Shield HUD)
      EthologyRobot.h / .cpp       (behaviours + hierarchy execution)
      Robot.h / .cpp               (drivetrain base)
      CogServo.h / .cpp            (servo driver)
      CogProximity.h / .cpp        (IR sensors)
      CogLight.h / .cpp            (LDR sensors)
      CogCollision.h / .cpp        (bumper)
      CogAnaDigi.h / .cpp          (sensor base)

  Hardware
  --------
      D6   Left servo
      D5   Right servo
      A0   Left proximity  (leftProx)
      A1   Right proximity (rightProx)
      A2   Left light      (leftLight)
      A3   Right light     (rightLight)
      D4   Left front bumper  (INPUT_PULLUP)
      D2   Right front bumper (INPUT_PULLUP)
      D3   Left back bumper   (INPUT_PULLUP)   <-- PLACEHOLDER PIN
      D7   Right back bumper  (INPUT_PULLUP)   <-- PLACEHOLDER PIN

  The back bumper pins are guesses at the next free digital pins and must be
  confirmed against the actual wiring before escape_back is used.  They are
  declared in EthologyRobot.h.

  Display policy
  --------------
  The GIGA Display Shield shows BLE connection status and session token
  ONLY.  It deliberately does NOT show sensor values, wheel commands, or
  the active hierarchy: students are meant to observe the robot's
  behaviour and infer the hierarchy themselves.  The full sensor/wheel
  HUD is retained in CogDisplay but is never built or drawn, and every
  call to it below is commented out.
*/

#include "CogServo.h"
#include "EthologyRobot.h"
#include "CogBluetooth.h"
// ── Display: OPTIONAL ─────────────────────────────────────────────────────────
// The GIGA Display Shield HUD is a separate concern from the game suite, so it
// is a compile-time option rather than a hard dependency or a second copy of
// this sketch. Two lineages of the same firmware is how the cruise-arc values
// and the CogLight polarity both drifted.
//
//   All build switches now live in PAWConfig.h — robot letter, display mode,
//   sensor tracing. Edit that file; they must be visible to every translation
//   unit, not just this one.
// ── Build configuration ───────────────────────────────────────────────────────
// Robot letter, display mode and tracing all live in PAWConfig.h so that this
// sketch and CogDisplay.cpp compile against the SAME values. Defining them
// here instead would apply only to this file, and the link would fail with
// "undefined reference to CogDisplay::setGuards" — the library half would have
// been built with the defaults.
#include "PAWConfig.h"

// CogDisplay.h supplies a do-nothing stand-in of its own when PAW_USE_DISPLAY
// is 0, so this include is unconditional and the call sites below need no #if.
#include "CogDisplay.h"

// #include "CogAnaDigi.h"

// #include "CogProximity.h"
// #include "CogLight.h"

// CogProximity rightProx("A1");
// CogProximity leftProx("A0");
// CogLight     rightLight("A3");
// CogLight     leftLight("A2");

// Pick your actual PWM-capable pins for your Arduino board
// Arduino PIN numbers — this robot drives two continuous-rotation servos
// directly off the board. They were named ...CHANNEL when a PCA9685 was still
// an option, and that naming hid a real bug: the sketch declared a PCA9685,
// constructed the robot in Servo mode anyway, and passed these as if they were
// PCA9685 channels. The driver was never initialised, so its outputs came up
// uncommanded and the robot spun at power-on before any behaviour ran.
constexpr uint8_t LEFT_SERVO_PIN  = 6;
constexpr uint8_t RIGHT_SERVO_PIN = 5;

// How long the link must stay down before LISTENING falls back to
// ADVERTISING.  Prevents a momentary drop from bouncing the state.
// DISCONNECT_GRACE_MS removed — see the note by the state variables.

EthologyRobot bot;
CogBluetooth  ble;
CogDisplay    display;

// ── Robot state ───────────────────────────────────────────────────────────────

enum class RobotState : uint8_t {
    Advertising,
    Listening,
    Running
};

static RobotState    _state = RobotState::Advertising;
// _disconnectedSince and DISCONNECT_GRACE_MS are gone: re-advertising moved
// into CogBluetooth's BLEDisconnected handler, which fires in every state.
// Tracking "how long has the link been down" per state was the mechanism that
// let Running forget to re-advertise at all.

// ── Heartbeat LED ─────────────────────────────────────────────────────────────
// The robot is deliberately motionless until a hierarchy arrives, which is
// indistinguishable from "dead" without some sign of life. Blinking means
// WAITING FOR A HIERARCHY; solid ON means running one.
//
//   blink  -> Advertising / Listening : powered, waiting, nothing installed
//   solid  -> Running                 : hierarchy installed, executing
//   off    -> no power, or setup() failed before reaching the loop
//
// Non-blocking: never delay() here, or a blink would stall BLE servicing.
static const unsigned long HEARTBEAT_MS = 500;
static unsigned long _lastBlink = 0;
static bool          _ledOn     = false;

static void heartbeat(bool running)
{
    if (running) {
        if (!_ledOn) { LED_WRITE(true); _ledOn = true; }
        return;
    }
    if (millis() - _lastBlink >= HEARTBEAT_MS) {
        _lastBlink = millis();
        _ledOn = !_ledOn;
        LED_WRITE(_ledOn);
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

// Push the current state to the display.  BLE status/session only —
// never sensor state, never the hierarchy.
static void showState() {
    switch (_state) {
        case RobotState::Advertising:
            display.setBleStatus("ADVERTISING", "");
            break;
        case RobotState::Listening:
            display.setBleStatus("CONNECTED", "");
            break;
        case RobotState::Running:
            display.setBleStatus("RUNNING", ble.session());
            break;
    }
}

// A hierarchy arrived.  Validate it against EthologyRobot's vocabulary,
// install it, and answer the host.  Returns true if the run was accepted.
static bool tryInstallHierarchy() {
    const int count = ble.pendingCount();

    const int bad = bot.setHierarchy(ble.pendingNames(), count);

    if (bad == EthologyRobot::HIERARCHY_OK) {
        // Seed the PRNG that cruise_arc flips on.  Seeding here rather than in
        // setup() matters: micros() at power-on is near-identical every boot,
        // which would make every robot arc the same way in every session.
        // The wait for a human to connect and send a hierarchy is the entropy.
        randomSeed(micros());

        Serial.print("Hierarchy installed, ");
        Serial.print(String(count));
        Serial.println(" rungs");
        // BEFORE acceptHierarchy(): it calls _clearPending(), so pendingNames()
        // is empty afterwards.
        display.setHierarchy(ble.pendingNames(), count);

        ble.acceptHierarchy();
        return true;
    }

    // Report which name failed, so the host is not left guessing.
    String reason = "unknown behavior: ";
    reason += ble.pendingName(bad);

    ble.rejectHierarchy(reason.c_str());
    return false;
}

// ── setup() ───────────────────────────────────────────────────────────────────

void setup()
{
    Serial.begin(9600);

    // Say which release built this, before anything that can fail. After a
    // MAJOR release an old receiver may not understand a new builder, and this
    // line is how you find out which one you have.
    Serial.print("Hierarchy Builder version: ");
    Serial.println(PAW_BUILDER_VERSION);   // "unversioned" = not a download
    bot.begin(LEFT_SERVO_PIN, RIGHT_SERVO_PIN);
    display.begin();

    // ─────────────────────────────────────────────────────────────────────
    //  ROBOT IDENTITY — pick which robot this board is.
    //  The Hierarchy Builder scans for these names so the instructor can
    //  target Robot A or Robot B even when BOTH are powered on at once.
    //
    //  SET THIS ROBOT'S IDENTITY at the top of the sketch:
    //
    //      #define PAW_ROBOT_ID  A      <-- RobotA
    //      #define PAW_ROBOT_ID  B      <-- RobotB
    //
    //  It used to be two lines here, one commented out, which is easy to
    //  forget: every board flashed from an unedited copy came up as RobotA,
    //  so RobotB was never reachable and two robots powered at once collided
    //  on the same name.
    // ─────────────────────────────────────────────────────────────────────
    const char* ROBOT_NAME = PAW_ROBOT_NAME;

    // FIRST: make the LED usable. It is the only channel that survives every
    // other failure — no USB, no display, no radio. Everything below can fail;
    // this cannot.
    pinMode(LED_BUILTIN, OUTPUT);
    LED_WRITE(false);

    // Hand the transport the robot's behaviour vocabulary so a host can
    // discover it with {"cmd":"behaviors"} instead of hard-coding a copy.
    ble.setBehaviorCatalog(
        EthologyRobot::behaviorCatalog(),
        EthologyRobot::behaviorCount());

    if (!ble.begin(ROBOT_NAME)) {
        // BLE hardware unavailable.
        //
        // This used to spin forever with only a Serial message and a display
        // call — and the display is a no-op unless PAW_USE_DISPLAY is 1, and
        // Serial is gone the moment USB is unplugged. The LED was not even
        // configured yet. So a BLE failure produced a completely silent board,
        // indistinguishable from one that is dead or unflashed.
        //
        // Now it FAST-BLINKS: ~5 Hz, clearly different from the 1 Hz
        // "waiting for a hierarchy" blink.
        Serial.println("FATAL: BLE init failed");
        display.setBleStatus("BLE INIT FAILED", "");
        bool on = false;
        while (true) {
            on = !on;
            LED_WRITE(on);
            display.updateStatus();
            delay(100);
        }
    }

    // Keep the radio alive DURING motor primitives. driveProportional() holds
    // for up to a second, and without this the BLE stack goes unserviced for
    // that whole time — long enough for a scan or connect to time out, which
    // is why a running robot seemed to disappear. See CogServo::setWaitTick.
    CogServo::setWaitTick([]() {
        if (ble.isStarted()) ble.poll();
    });

    // Power on: advertise, but take no motor action. The LED blinks from here
    // until a hierarchy is installed.
    _state = RobotState::Advertising;
    showState();
    display.updateStatus();
}

// ── loop() ────────────────────────────────────────────────────────────────────

void loop()
{
    switch (_state) {

    // ── Advertising: no motor action, wait for a central ──────────────────
    case RobotState::Advertising:
        ble.poll();

        if (ble.isConnected()) {
            _state = RobotState::Listening;
            Serial.println("Central connected — listening for hierarchy");
        }
        break;

    // ── Listening: connected, no motor action, wait for a hierarchy ───────
    case RobotState::Listening:
        ble.poll();

        if (ble.hasPendingHierarchy()) {
            if (tryInstallHierarchy()) {
                _state = RobotState::Running;
                Serial.println("RUNNING — hierarchy runs until power off");
                break;
            }
            // Rejected: stay in Listening so the host can send a corrected
            // hierarchy without a power cycle.
        }
        // Re-advertising is handled by CogBluetooth's BLEDisconnected
        // handler now, in every state at once. It used to live here and in
        // Running as separate copies, and Running's was missing.
        break;

    // ── Running: execute the hierarchy until power off ────────────────────
    case RobotState::Running:
        // Motors first: behaviour must not be starved by comms.
        bot.hierarchy();

        // Still serviced so the host can read status, but nothing it sends
        // can leave this state.
        ble.poll();
        break;
    }

    // ── Heartbeat ─────────────────────────────────────────────────────────
    heartbeat(_state == RobotState::Running);

    // ── Display ───────────────────────────────────────────────────────────
    // With PAW_DISPLAY_DEV 0 every call below compiles to nothing, so the
    // classroom build still shows BLE status and session only. No #if here:
    // commented-out call sites rot, and these went stale once already —
    // they re-read the Cog objects, which takes a NEW sample that can
    // disagree with the one this tick's arbitration used.
    if (_state == RobotState::Running) {
        bool guards[CogDisplay::MAX_ROWS];
        const int n = bot.hierarchyLength();
        for (int i = 0; i < n; i++) {
            guards[i] = bot.guardMet(bot.behaviorAt(i));
        }
        display.setGuards(guards, n);
        display.setActive(bot.lastFiredIndex());

        const EthologyRobot::SensorSnapshot s = bot.snapshot();
        display.setSensors(s.leftProx, s.rightProx, s.lightGradient,
                           s.leftFrontBump, s.rightFrontBump,
                           s.leftBackBump,  s.rightBackBump);
    }
    display.update();

    showState();
    display.updateStatus();

    // Small yield keeps the BLE stack responsive between ticks.
    // Only meaningful while idle — in RUNNING the behaviour calls dominate.
    if (_state != RobotState::Running) {
        delay(20);
    }
}

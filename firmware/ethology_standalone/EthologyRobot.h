#pragma once

#include "Robot.h"

// Set -DPAW_SENSOR_TRACE=1 (or define it before including this) to have
// readSensors() print live sensor values to Serial twice a second. Off by
// default: it is a bench tool, and in Ethology observation mode revealing
// sensor values would give away the exercise.
#ifndef PAW_SENSOR_TRACE
#define PAW_SENSOR_TRACE 0
#endif

#include "CogProximity.h"
#include "CogLight.h"
#include "CogCollision.h"

// ============================================================================
// Behavior vocabulary
// ----------------------------------------------------------------------------
// EthologyRobot owns the list of behaviors it can perform, the mapping from
// wire names to behaviors, and the execution of a hierarchy.  CogBluetooth
// knows none of this -- it only moves strings.
//
// NAMING CONVENTION: verb_target.  The verb says what the robot does, the
// target says what it does it to.  avoid_object / approach_object and
// avoid_light / approach_light are exact pairs.  escape_front / escape_back
// are the deliberate exception: "escape" is reflexive rather than directed, so
// the second word names where the robot was struck, not what it flees.
//
// The wire names below MUST match Python BEHAVIOR_MAP in codegen.py. They now
// do: the Python side was brought into line (seek_light -> approach_light,
// escape_rear -> escape_back) so this table is the single authority.
// setHierarchy() rejects a hierarchy WHOLE if any name is unknown, so a
// mismatch does not degrade gracefully.
// ============================================================================
enum class Behavior : uint8_t {
    None = 0,
    EscapeFront,      // "escape_front"     front bump -> escapeFrontCollision()
    EscapeBack,       // "escape_back"      back bump  -> escapeBackCollision()
    AvoidObject,      // "avoid_object"     proximity  -> avoidObject()
    ApproachObject,   // "approach_object"  proximity  -> approachObject()
    AvoidLight,       // "avoid_light"      gradient   -> avoidLight()
    ApproachLight,    // "approach_light"   gradient   -> approachLight()
    CruiseStraight,   // "cruise_straight"  always     -> cruiseStraight()
    CruiseArc         // "cruise_arc"       always     -> cruiseArc()
};

class EthologyRobot : public Robot {
public:
    // ================================
    // Sensors
    // ================================
    CogProximity rightProx {"A1"};
    CogProximity leftProx  {"A0"};

    CogLight     rightLight {"A3"};
    CogLight     leftLight  {"A2"};

    CogCollision rightFrontBump {2};
    CogCollision leftFrontBump  {4};

    // ---- BACK BUMPERS -- PIN NUMBERS ARE PLACEHOLDERS ----
    // D5 and D6 are the servos and D2/D4 are the front bumpers, so 3 and 7
    // are simply the next free digital pins.  CONFIRM AGAINST YOUR WIRING
    // before running escape_back.  ethologyPrototypeV2 has no back bumpers at
    // all, so this pair has never been exercised on hardware.
    CogCollision rightBackBump {7};
    // D8, not D3: D3 is a PWM pin and is wanted elsewhere. A bumper only needs
    // a digital input with a pull-up, so it has no claim on a PWM-capable pin.
    CogCollision leftBackBump  {8};

    // ================================
    // Thresholds
    // ================================
    // PROX_THRESHOLD is in CENTIMETRES: CogProximity::getData() maps raw
    // [120,720] -> [60,18] cm and SATURATES at 18 (a wall at 18 cm and one at
    // 2 cm both read 18).
    //
    // *** UNVERIFIED -- TEST BEFORE TRUSTING ***
    // Two open questions, both needing a bench measurement:
    //
    //   1. VALUE.  The simulator uses 20, not 35.  At 35 the robot triggers
    //      almost everywhere indoors, and a corridor narrower than about 60 cm
    //      leaves both sensors under threshold at once -- which makes
    //      avoid_object oscillate instead of traverse.  20 was chosen to sit
    //      just above the 18 cm saturation floor.  It is left at 35 here
    //      because of (2).
    //
    //   2. CALIBRATION.  The [120,720] -> [60,18] mapping was derived on an
    //      Uno R4 WiFi (5 V logic).  On a Giga R1 (3.3 V) the same sensor
    //      voltage produces a much larger raw reading -- roughly 961 where the
    //      Uno read 634 -- so the clamp range, and therefore every distance
    //      this class reports, is wrong on that board.
    //
    // Measure raw analogRead() at known distances on the board you are
    // actually using, fix the mapping first, then choose the threshold.
    static constexpr int PROX_THRESHOLD  = 35;
    static constexpr int LIGHT_THRESHOLD = 15;
    static constexpr int COLL_THRESHOLD  = 1;

    // ================================
    // Cruise tuning
    // ================================
    // Values from ethologyPrototypeV2, which is the behaviour that has been
    // verified on hardware.
    //
    // NOTE THE SHAPE OF AN ARC.  It is NOT cruise with one wheel boosted: the
    // inner wheel drops well BELOW cruise and the outer wheel stays below it
    // too, so an arc is a slow, tight turn rather than a fast drift.  A
    // CRUISE_SPEED + ARC_BOOST formulation (60/70) looks tidier and produces a
    // 0.52 m turning radius against this pairing's 0.16 m -- more than three
    // times wider, which will not turn inside a corridor the robot can fit in.
    static constexpr int   CRUISE_SPEED    = 60;
    static constexpr int   ARC_INNER_SPEED = 30;   // verified prototype
    static constexpr int   ARC_OUTER_SPEED = 50;   // note: BELOW cruise, not boosted
    static constexpr float CRUISE_SECONDS  = 0.1;

    // HOW LONG ONE ARC LASTS.
    //
    // cruise_arc used to flip a fresh coin every tick. A tick is
    // CRUISE_SECONDS = 0.1 s, so it re-randomised ten times a second and the
    // left and right arcs cancelled: the robot tracked essentially straight
    // with a wobble, which is why cruise_arc and cruise_straight looked
    // identical on the floor.
    //
    // A direction now holds for a random span in this range before the next
    // flip, which is long enough at 30/50 to be a visible curve. Widen the
    // range for lazier wandering; narrow it toward CRUISE_SECONDS to get the
    // old straight-line behaviour back.
    // HOW LONG AN ESCAPE RUNS.
    //
    // An escape has to be long enough to read as its own behaviour against
    // whatever it interrupted. escape_back used to run for 0.1 s -- a single
    // tick -- which against a robot already cruising forward was an invisible
    // blip, so the behaviour looked broken when it was merely brief.
    //
    // Long enough to clear an obstacle, short enough that the hierarchy stays
    // responsive. Both escapes use it so they are equally legible.
    static constexpr float ESCAPE_SECONDS = 0.8;

    static constexpr unsigned long ARC_HOLD_MIN_MS = 700;
    static constexpr unsigned long ARC_HOLD_MAX_MS = 1900;

    // ── Cached sensor data ────────────────────────────────────────────────
    // Filled once per tick by readSensors(). Guards AND behaviours read these
    // rather than sampling again: previously proximityThreshold() read the
    // sensor and then avoidObject() read it a SECOND time, so the guard and
    // the action could disagree — the guard passes, the re-read comes back
    // above threshold, neither branch runs, and the last motor command
    // latches.
    //
    // Initialised to a resting world, not to zero. These are read by guards
    // that may run before the first readSensors() — and zero is PRESSED for a
    // bumper (INPUT_PULLUP) and NEAR for proximity, so zero-init would make
    // escape_front and avoid_object fire on an untouched robot.
    int _leftProxData       = 999;   // far; proximityThreshold() wants <= 35
    int _rightProxData      = 999;
    int _lightGradient      = 0;     // no gradient; needs |g| >= 15
    int _leftFrontBumpData  = 1;     // HIGH = not pressed
    int _rightFrontBumpData = 1;
    int _leftBackBumpData   = 1;
    int _rightBackBumpData  = 1;

    // ================================
    // Constructors
    // ================================

    // Servo.h drivetrain. Verified working on Giga R1 via
    // CogServo::writeMicroseconds() despite Servo.h not listing mbed_giga
    // among its architectures. There is no second constructor: the PCA9685
    // path was removed from CogServo.
    EthologyRobot();


    // ================================
    // Sense - decide - act
    // ================================

    // Sample every sensor once and cache it. Called at the top of each
    // hierarchy() tick.
    //
    // It also HALTS first. Two reasons:
    //   1. A stopped robot is the resting state. Servos latch — a pulse width
    //      persists until something writes another — so without this, "no
    //      behaviour applies" means "keep doing whatever you were doing".
    //      Halting here covers every such case, including a behaviour whose
    //      guard passes but whose own branches all miss.
    //   2. Motors running during an analogRead() inject noise into it.
    //
    // halt(0) does not block, and the stop is not visible: servos are updated
    // on a ~20 ms frame, and halt -> sample -> drive completes well inside
    // one, so the neutral is usually overwritten before it is ever emitted.
    void readSensors();

    // ================================
    // Sensor Threshold Checks
    // ================================
    bool proximityThreshold();
    bool lightGradientThreshold();
    bool collisionThreshold();       // front bumpers
    bool backCollisionThreshold();   // back bumpers

    // ================================
    // The eight behaviours
    // ================================
    // One method per wire name, and nothing else on the wire.

    void avoidObject();
    void approachObject();

    void avoidLight();
    void approachLight();

    void escapeFrontCollision();
    void escapeBackCollision();

    void cruiseStraight();

    // cruiseArc() is the only arc exposed on the wire.  It flips a fresh coin
    // EVERY tick and delegates; the two directional arcs are its
    // implementation, kept public only so a test sketch can drive them
    // directly.  randomSeed() must be called in setup(), or every power cycle
    // replays the same sequence of "random" turns.
    void cruiseArc();
    void cruiseLeftArc();
    void cruiseRightArc();

    // ================================
    // Behavior Hierarchy
    // ================================

    // Maximum rungs in a hierarchy.
    static const int MAX_HIERARCHY = 8;

    // Returned by setHierarchy() when every name was recognised.
    static const int HIERARCHY_OK = -1;

    // Wire name <-> Behavior.  behaviorFromName() returns Behavior::None
    // for an unrecognised name.
    static Behavior    behaviorFromName(const char* name);
    static const char* behaviorName(Behavior b);

    // The complete behaviour vocabulary, for a host to discover at runtime
    // rather than hard-coding a second copy of the list.
    static const char* const* behaviorCatalog();
    static int                behaviorCount();

    // Install a hierarchy from wire names, highest priority first.
    // Returns HIERARCHY_OK on success, or the index of the first name that
    // could not be recognised (in which case nothing is installed).
    // A count outside 1..MAX_HIERARCHY returns index 0.
    int  setHierarchy(const char* const* names, int count);

    bool hasHierarchy() const { return _hierLen > 0; }
    int  hierarchyLength() const { return _hierLen; }
    void clearHierarchy() { _hierLen = 0; _lastFired = -1; }

    // Run ONE subsumption tick of the installed hierarchy: walk the rungs
    // highest priority first and run the first whose condition is met.
    // Does nothing if no hierarchy is installed.
    void hierarchy();

    // ================================
    // Introspection
    // ================================
    //
    // For CogDisplay's development HUD and PAW_SENSOR_TRACE. None of it
    // affects arbitration; all of it reads state the tick already produced.

    // The rung that fired on the last hierarchy() tick, or -1 if none did.
    int lastFiredIndex() const { return _lastFired; }

    // The behaviour installed at a rung, or Behavior::None if out of range.
    Behavior behaviorAt(int i) const {
        return (i >= 0 && i < _hierLen) ? _hier[i] : Behavior::None;
    }

    // Is this behaviour's condition met, using the readings readSensors()
    // cached? Does NOT act. Cruise behaviours are ungated and always true.
    //
    // _runRung() calls this too, so the guard-to-behaviour mapping lives in
    // exactly one switch. Asking it again inside the same tick cannot disagree
    // with the arbitration, because the guards only read cached values.
    //
    // Why this is worth having: hierarchy() short-circuits at the first rung
    // that fires, so it never learns whether the rungs below would also have
    // passed. Evaluating them separately is what distinguishes "correctly
    // subsumed" from "broken" — and on a partly wired robot a floating pin
    // pins a guard true and masks everything below it.
    bool guardMet(Behavior b);

    // The seven readings this tick's decision was actually made on. Prefer
    // this to re-reading the Cog objects: CogCollision has no peek, so a fresh
    // getData() takes a NEW sample that may disagree with the one arbitration
    // used.
    struct SensorSnapshot {
        int leftProx, rightProx;
        int lightGradient;
        int leftFrontBump, rightFrontBump;
        int leftBackBump,  rightBackBump;
    };

    SensorSnapshot snapshot() const {
        return { _leftProxData, _rightProxData, _lightGradient,
                 _leftFrontBumpData, _rightFrontBumpData,
                 _leftBackBumpData,  _rightBackBumpData };
    }

private:
    Behavior _hier[MAX_HIERARCHY];
    int      _hierLen = 0;
    int      _lastFired = -1;

    // cruise_arc's current direction and when it expires. See ARC_HOLD_MIN_MS.
    bool          _arcLeft    = false;
    unsigned long _arcUntilMs = 0;

    // Evaluate one rung.  Returns true if it fired (and thus subsumes
    // everything below it).
    bool _runRung(Behavior b);
};

#include "EthologyRobot.h"
#include <cmath>  // std::abs
#include <string.h>  // strcmp

// ================================
// Constructors
// ================================

// Servo.h mode
EthologyRobot::EthologyRobot()
: Robot() {
}

// ================================
// Sense - decide - act
// ================================

void EthologyRobot::readSensors() {
    // STOP FIRST. The resting state of the robot is "not moving"; a tick that
    // decides to do nothing must leave it not moving. Servos latch, so this
    // has to be an explicit write, not an omission. Non-blocking.
    halt(0.0f);

    // Then sample everything ONCE, so every guard and every behaviour in this
    // tick sees the same world.
    _rightProxData      = rightProx.getData();
    _leftProxData       = leftProx.getData();
    _lightGradient      = rightLight.getData() - leftLight.getData();
    _leftFrontBumpData  = leftFrontBump.getData();
    _rightFrontBumpData = rightFrontBump.getData();
    _leftBackBumpData   = leftBackBump.getData();
    _rightBackBumpData  = rightBackBump.getData();

#if PAW_SENSOR_TRACE
    // One line per tick, rate-limited. Set -DPAW_SENSOR_TRACE=1 to enable.
    //
    // This exists because "the robot does nothing" and "the robot's guards are
    // all failing" look identical from outside, and a gated behaviour doing
    // nothing is usually CORRECT. approach_light needs the two light sensors
    // to differ by LIGHT_THRESHOLD (15 of 100); in even room light they read
    // nearly the same, so the robot sits still exactly as designed.
    static unsigned long _lastTrace = 0;
    if (millis() - _lastTrace >= 500) {
        _lastTrace = millis();
        Serial.print("prox L/R "); Serial.print(_leftProxData);
        Serial.print("/");         Serial.print(_rightProxData);
        Serial.print("  light grad "); Serial.print(_lightGradient);
        Serial.print(" (need |g| >= "); Serial.print(LIGHT_THRESHOLD);
        Serial.print(")  bumpF L/R "); Serial.print(_leftFrontBumpData);
        Serial.print("/");             Serial.print(_rightFrontBumpData);
        Serial.println();
    }
#endif
}

// ================================
// Sensor Threshold Checks
// ================================
// These now READ THE CACHE. They used to sample, which meant a guard and its
// paired action could see different readings.
bool EthologyRobot::proximityThreshold() {
    return (_rightProxData <= PROX_THRESHOLD ||
            _leftProxData  <= PROX_THRESHOLD);
}

bool EthologyRobot::lightGradientThreshold() {
    return (abs(_lightGradient) >= LIGHT_THRESHOLD);
}

bool EthologyRobot::collisionThreshold() {
    bool thresholdMet = false;

    if (_leftFrontBumpData == 0 || _rightFrontBumpData == 0) {
        thresholdMet = true;
    }

    return thresholdMet;
}

bool EthologyRobot::backCollisionThreshold() {
    bool thresholdMet = false;

    if (_leftBackBumpData == 0 || _rightBackBumpData == 0) {
        thresholdMet = true;
    }

    return thresholdMet;
}

// ================================
// Object-Based Behaviors
// ================================
void EthologyRobot::avoidObject() {
    if (_rightProxData <= PROX_THRESHOLD) {
        // obstacle on right → steer left
        driveProportional(-40, 40, 0.5);
    }
    else if (_leftProxData <= PROX_THRESHOLD) {
        // obstacle on left → steer right
        driveProportional(40, -40, 0.5);
    }
}

// The mirror of avoidObject: curve TOWARD the side that sees something.
//
// This tested `>= PROX_THRESHOLD` — the opposite of its own guard, which
// defines "near" as `<=`. With an object 20 cm off the right sensor the guard
// passed, the right branch failed (20 is not >= 35), and the left branch fired
// because the LEFT sensor was reading 60 cm of empty room. The robot then
// steered using the side with nothing in it, which read as backing away.
//
// The wheel pairs were also away-from rather than toward: compare avoidObject,
// where an obstacle on the right gives (-40, 40) to peel left. Approaching the
// same obstacle is the opposite sign.
void EthologyRobot::approachObject() {
    const bool right = (_rightProxData <= PROX_THRESHOLD);
    const bool left  = (_leftProxData  <= PROX_THRESHOLD);

    if (right && left) {
        // Dead ahead: drive straight in. Without this case both sensors could
        // read near while every branch below missed, so the guard passed and
        // the behaviour did nothing — the exact hole the header warns about.
        driveProportional(CRUISE_SPEED, CRUISE_SPEED, 0.1);
    }
    else if (right) {
        driveProportional(60, 40, 0.1);   // object on the right → curve right
    }
    else if (left) {
        driveProportional(40, 60, 0.1);   // object on the left  → curve left
    }
}

// ================================
// Light-Based Behaviors
// ================================
// gradient = right - left, and CogLight reports 0=dark 100=bright, so a
// POSITIVE gradient means the light is on the RIGHT.
//
// VERIFIED ON HARDWARE, and it is the opposite of what the wheel arithmetic
// suggests: driveProportional(-40, 40) is what carries this robot AWAY from a
// light on its right. Reasoning from the sign of the gradient alone got this
// backwards twice — once here and once in the BLE tree, where two reversals
// cancelled and hid the fault. Do not "correct" these from first principles;
// put the robot next to a lamp instead.
void EthologyRobot::avoidLight() {
    if (_lightGradient >= LIGHT_THRESHOLD) {
        // light on the right -> peel away to the right
        driveProportional(40, -40, 0.1);
    }
    else if (_lightGradient <= -LIGHT_THRESHOLD) {
        driveProportional(-40, 40, 0.1);
    }
}

void EthologyRobot::approachLight() {
    if (_lightGradient >= LIGHT_THRESHOLD) {
        // light on the right -> turn toward it
        driveProportional(-40, 40, 0.5);
    }
    else if (_lightGradient <= -LIGHT_THRESHOLD) {
        driveProportional(40, -40, 0.5);
    }
}

// ================================
// Collision-Based Behaviors
// ================================
// Struck on the front: spin AWAY from the side that was hit.
//
// VERIFIED ON HARDWARE. The per-side directions were previously swapped, so
// the robot turned into the obstacle it had just hit and stayed jammed
// against it. As with the light behaviours, do not re-derive these from the
// wheel arithmetic — press a bumper and watch.
//
// The two tests are now EXCLUSIVE. They used to be separate ifs, so a
// head-on hit that closed both bumpers ran one spin and then the other, and
// the two cancelled: the robot sat still while pinned, which is the worst
// possible response to being stuck. A both-sides hit now reverses instead,
// which is the only move that clears a square-on obstacle.
void EthologyRobot::escapeFrontCollision() {
    const bool left  = (_leftFrontBumpData  == 0);
    const bool right = (_rightFrontBumpData == 0);

    if (left && right) {
        driveProportional(-100, -100, ESCAPE_SECONDS);   // pinned: back straight out
    }
    else if (left) {
        driveProportional(-100, 100, ESCAPE_SECONDS);
    }
    else if (right) {
        driveProportional(100, -100, ESCAPE_SECONDS);
    }
}

// Struck from behind: sprint forward, away from whatever hit us.
//
// Duration was 0.1 s -- one tick. Against a robot already cruising forward
// that is a barely perceptible blip, so escape_back looked like it was not
// firing at all even when the guard was met. The escape has to outrun cruise
// long enough to read as a distinct behaviour, which is what ESCAPE_SECONDS
// is for.
void EthologyRobot::escapeBackCollision() {
    driveProportional(100, 100, ESCAPE_SECONDS);
}

// ================================
// Cruise Behaviors
// ================================
void EthologyRobot::cruiseStraight() {
    driveProportional(CRUISE_SPEED, CRUISE_SPEED, CRUISE_SECONDS);
}

// Coin flip, then HOLD that direction for ARC_HOLD_MIN_MS..ARC_HOLD_MAX_MS
// before flipping again.
//
// This used to re-flip every tick. A tick is CRUISE_SECONDS = 0.1 s, so the
// direction changed ten times a second and successive left and right arcs
// cancelled -- the robot travelled almost straight, and cruise_arc was
// indistinguishable from cruise_straight on the floor. The arc geometry was
// never the problem; the sampling rate was.
//
// Still needs randomSeed() in setup(), or every power cycle repeats the same
// sequence of turns.
void EthologyRobot::cruiseArc() {
    const unsigned long now = millis();

    if (now >= _arcUntilMs) {
        _arcLeft    = (random(2) == 0);
        _arcUntilMs = now + random(ARC_HOLD_MIN_MS, ARC_HOLD_MAX_MS + 1);
    }

    if (_arcLeft) {
        cruiseLeftArc();
    } else {
        cruiseRightArc();
    }
}

// Inner wheel slowed, outer wheel also below cruise -> a slow, TIGHT arc.
// Restored from ethologyPrototypeV2 (30, 50): the merged version had used
// CRUISE_SPEED + ARC_BOOST (60, 70), which is 3.3x wider and cannot turn
// inside a corridor the robot fits through.
void EthologyRobot::cruiseLeftArc() {
    driveProportional(ARC_INNER_SPEED, ARC_OUTER_SPEED, CRUISE_SECONDS);
}

// Exact mirror.
void EthologyRobot::cruiseRightArc() {
    driveProportional(ARC_OUTER_SPEED, ARC_INNER_SPEED, CRUISE_SECONDS);
}

// ================================
// Behavior Hierarchy
// ================================

// Wire-name table.
// ----------------------------------------------------------------------------
// ORDER IS LOAD-BEARING: entry i corresponds to Behavior(i + 1).  The
// static_assert below catches a name being added without a matching enum
// member (or vice versa).  These names are the single source of truth for
// the wire vocabulary -- a host should discover them via behaviorCatalog()
// rather than keeping its own copy.
//
// CONVENTION: verb_target.  avoid_/approach_ are exact pairs; escape_ names
// where the robot was struck.  EXACTLY EIGHT -- if you are adding a ninth,
// the Python builder and its saved hierarchies need it too.
namespace {
    const char* const BEHAVIOR_NAMES[] = {
        "escape_front",      // Behavior::EscapeFront
        "escape_back",       // Behavior::EscapeBack
        "avoid_object",      // Behavior::AvoidObject
        "approach_object",   // Behavior::ApproachObject
        "avoid_light",       // Behavior::AvoidLight
        "approach_light",    // Behavior::ApproachLight
        "cruise_straight",   // Behavior::CruiseStraight
        "cruise_arc"         // Behavior::CruiseArc
    };

    const int BEHAVIOR_N =
        sizeof(BEHAVIOR_NAMES) / sizeof(BEHAVIOR_NAMES[0]);

    static_assert(
        BEHAVIOR_N == static_cast<int>(Behavior::CruiseArc),
        "BEHAVIOR_NAMES is out of sync with the Behavior enum");
}

const char* const* EthologyRobot::behaviorCatalog() {
    return BEHAVIOR_NAMES;
}

int EthologyRobot::behaviorCount() {
    return BEHAVIOR_N;
}

Behavior EthologyRobot::behaviorFromName(const char* name) {
    if (name == nullptr) return Behavior::None;

    for (int i = 0; i < BEHAVIOR_N; i++) {
        if (strcmp(name, BEHAVIOR_NAMES[i]) == 0) {
            return static_cast<Behavior>(i + 1);
        }
    }
    return Behavior::None;
}

const char* EthologyRobot::behaviorName(Behavior b) {
    const int idx = static_cast<int>(b) - 1;

    if (idx < 0 || idx >= BEHAVIOR_N) {
        return "unknown";
    }
    return BEHAVIOR_NAMES[idx];
}

// Validate every name BEFORE installing anything, so a hierarchy is either
// installed whole or not at all.  Silently dropping unrecognised rungs would
// run a hierarchy the host never asked for.
int EthologyRobot::setHierarchy(const char* const* names, int count) {
    if (names == nullptr || count <= 0 || count > MAX_HIERARCHY) {
        return 0;
    }

    Behavior parsed[MAX_HIERARCHY];

    for (int i = 0; i < count; i++) {
        parsed[i] = behaviorFromName(names[i]);
        if (parsed[i] == Behavior::None) {
            return i;
        }
    }

    for (int i = 0; i < count; i++) {
        _hier[i] = parsed[i];
    }
    _hierLen   = count;
    _lastFired = -1;   // stale index must not outlive the hierarchy it indexed

    return HIERARCHY_OK;
}

// One rung.  Condition first, then action -- lightGradientThreshold() and
// collisionThreshold() cache the sensor readings that their paired actions
// depend on, so the condition must always be evaluated first.
bool EthologyRobot::guardMet(Behavior b) {
    switch (b) {

        // ---- Bumper-gated ----
        case Behavior::EscapeFront:    return collisionThreshold();
        case Behavior::EscapeBack:     return backCollisionThreshold();

        // ---- Proximity-gated ----
        case Behavior::AvoidObject:
        case Behavior::ApproachObject: return proximityThreshold();

        // ---- Light-gradient-gated ----
        case Behavior::AvoidLight:
        case Behavior::ApproachLight:  return lightGradientThreshold();

        // ---- Ungated (terminal): always fires, subsuming all rungs below ----
        case Behavior::CruiseStraight:
        case Behavior::CruiseArc:      return true;

        default:                       return false;
    }
}

bool EthologyRobot::_runRung(Behavior b) {
    // Guard first, in one place. This used to be eight if(guard){act;} pairs,
    // which meant the mapping existed here and nowhere else — so nothing could
    // ask "would this rung fire?" without acting on the answer.
    if (!guardMet(b)) return false;

    switch (b) {
        case Behavior::EscapeFront:    escapeFrontCollision(); return true;
        case Behavior::EscapeBack:     escapeBackCollision();  return true;
        case Behavior::AvoidObject:    avoidObject();          return true;
        case Behavior::ApproachObject: approachObject();       return true;
        case Behavior::AvoidLight:     avoidLight();           return true;
        case Behavior::ApproachLight:  approachLight();        return true;
        case Behavior::CruiseStraight: cruiseStraight();       return true;
        case Behavior::CruiseArc:      cruiseArc();            return true;

        default:                       return false;
    }
}

// Highest priority first; first rung whose condition is met wins the tick.
// If no rung fires, the robot simply takes no action this tick.
void EthologyRobot::hierarchy() {
    // Sense-decide-act. readSensors() halts first, so if no rung fires the
    // robot is already stopped — no trailing halt needed, and it covers cases
    // a trailing halt would miss (a guard that passes while every branch
    // inside the behaviour misses, e.g. approachObject with an object dead
    // ahead).
    readSensors();

    // Which rung won is recorded for CogDisplay; it does not affect
    // arbitration. -1 means nothing fired, which readSensors() has already
    // left as "stopped".
    _lastFired = -1;

    for (int i = 0; i < _hierLen; i++) {
        if (_runRung(_hier[i])) {
            _lastFired = i;
            return;
        }
    }
}

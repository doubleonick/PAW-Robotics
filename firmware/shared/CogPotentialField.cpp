#include "CogPotentialField.h"
#include <math.h>

// Degrees -> radians helper (kept local; Arduino has radians() but be explicit).
static inline float degToRad(float deg) { return deg * (float)PI / 180.0f; }

CogPotentialField::CogPotentialField()
: _count(0), _netVx(0.0f), _netVy(0.0f),
  _forwardGain(1.0f), _turnGain(1.0f), _baseSpeed(0) {
    for (int i = 0; i < MAX_SENSORS; ++i) {
        _sources[i].type = SrcType::IR;
        _sources[i].ir = nullptr;
        _sources[i].ldr = nullptr;
        _sources[i].mountAngle = 0.0f;
        _sources[i].gain = 1.0f;
        _sources[i].policy = Policy::Push;
    }
}

bool CogPotentialField::addProximity(CogProximity* sensor, float mountAngle,
                                     float gain, Policy policy) {
    if (_count >= MAX_SENSORS || sensor == nullptr) return false;
    _sources[_count].type       = SrcType::IR;
    _sources[_count].ir         = sensor;
    _sources[_count].ldr        = nullptr;
    _sources[_count].mountAngle = mountAngle;
    _sources[_count].gain       = gain;
    _sources[_count].policy     = policy;
    _count++;
    return true;
}

bool CogPotentialField::addLight(CogLight* sensor, float mountAngle,
                                 float gain, Policy policy) {
    if (_count >= MAX_SENSORS || sensor == nullptr) return false;
    _sources[_count].type       = SrcType::LDR;
    _sources[_count].ir         = nullptr;
    _sources[_count].ldr        = sensor;
    _sources[_count].mountAngle = mountAngle;
    _sources[_count].gain       = gain;
    _sources[_count].policy     = policy;
    _count++;
    return true;
}

// CogProximity::getData() returns a distance-like value, ~[18..60], where
// SMALLER means CLOSER. For a field source we want strength to grow as the
// obstacle gets closer, so invert and normalize into ~[0..1].
float CogPotentialField::proximityStrength(CogProximity* s) {
    const float NEAR_CM = 18.0f;   // clamp floor (matches CogProximity map)
    const float FAR_CM  = 60.0f;   // clamp ceil  (matches CogProximity map)
    float d = (float)s->getData();
    if (d < NEAR_CM) d = NEAR_CM;
    if (d > FAR_CM)  d = FAR_CM;
    // closer (d -> NEAR) => strength -> 1 ; far (d -> FAR) => strength -> 0
    return (FAR_CM - d) / (FAR_CM - NEAR_CM);
}

// CogLight::getData() returns brightness in [0..100]; normalize to [0..1] so
// brighter => stronger field contribution.
float CogPotentialField::lightStrength(CogLight* s) {
    float v = (float)s->getData();     // [0..100]
    if (v < 0.0f)   v = 0.0f;
    if (v > 100.0f) v = 100.0f;
    return v / 100.0f;
}

void CogPotentialField::computeNetVector(float* outVx, float* outVy) {
    float vx = 0.0f, vy = 0.0f;

    for (int i = 0; i < _count; ++i) {
        Source& src = _sources[i];

        // Strength depends on the sensor kind: IR => closer is stronger;
        // LDR => brighter is stronger.
        float strength;
        if (src.type == SrcType::IR) {
            if (src.ir == nullptr) continue;
            strength = proximityStrength(src.ir);      // [0..1]
        } else { // LDR
            if (src.ldr == nullptr) continue;
            strength = lightStrength(src.ldr);         // [0..1]
        }
        float mag = strength * src.gain;

        // Contribution DIRECTION: toward the mount angle for PULL, opposite for
        // PUSH. Angle is CCW from +Y (forward). Body frame: +Y forward, +X right.
        float dirDeg = src.mountAngle;
        if (src.policy == Policy::Push) dirDeg += 180.0f;
        float dirRad = degToRad(dirDeg);

        // Unit vector for an angle measured CCW from +Y:
        //   +Y (forward) component = cos(angle)
        //   +X (right)   component = -sin(angle)   (CCW from +Y turns toward -X)
        float ux = -sinf(dirRad);
        float uy =  cosf(dirRad);

        vx += mag * ux;
        vy += mag * uy;
    }

    _netVx = vx;
    _netVy = vy;
    if (outVx) *outVx = vx;
    if (outVy) *outVy = vy;
}

void CogPotentialField::vectorToDifferential(int* leftProp, int* rightProp) const {
    // Net vector in body frame: _netVy = forward push/pull, _netVx = lateral.
    // Base speed gives a constant forward bias (so a pure repulsor that points
    // backward still yields motion to steer with). Forward component modulates
    // speed; lateral component sets the turn.
    float forward = (float)_baseSpeed + _forwardGain * _netVy * 100.0f;
    float turn    = _turnGain * _netVx * 100.0f;

    // Differential mix, matching the robot's REAL drivetrain (verified by the
    // drivetrain_baseline test): driveProportional(+left, -right) pivots the
    // robot toward its RIGHT, so turning toward the robot's right needs
    // LEFT wheel > RIGHT wheel. A vector to the right (+Vx) => turn>0 =>
    // left = forward+turn (higher), right = forward-turn (lower) => turns RIGHT.
    // (This is the ORIGINAL convention; an earlier patch here was based on a
    // wrong reading of approachLight and has been reverted. The real light-
    // polarity bug was the M5Stack LDRs reading inverted — fixed in CogLight.)
    float left  = forward + turn;
    float right = forward - turn;

    // clamp to [-100, 100]
    if (left  >  100.0f) left  =  100.0f;
    if (left  < -100.0f) left  = -100.0f;
    if (right >  100.0f) right =  100.0f;
    if (right < -100.0f) right = -100.0f;

    if (leftProp)  *leftProp  = (int)left;
    if (rightProp) *rightProp = (int)right;
}

void CogPotentialField::setDriveGains(float forwardGain, float turnGain) {
    _forwardGain = forwardGain;
    _turnGain    = turnGain;
}

void CogPotentialField::setBaseSpeed(int baseSpeed) {
    _baseSpeed = baseSpeed;
}

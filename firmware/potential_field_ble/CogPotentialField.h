#ifndef COGPOTENTIALFIELD_H
#define COGPOTENTIALFIELD_H

#include <Arduino.h>
#include "CogProximity.h"
#include "CogLight.h"

// =============================================================================
// CogPotentialField
// -----------------------------------------------------------------------------
// A general potential-field engine for a differential-drive robot.
//
// The physical potential-field model (no global map needed): each sensor
// reading IS the field measurement at that sensor's fixed mounting angle. For
// every sensor we build a contribution VECTOR:
//     magnitude  = signal_strength * gain
//     direction  = mountAngle            (PULL / attractor)
//                = mountAngle + 180deg   (PUSH / repulsor)
// We sum all contributions into a net vector in the robot's body frame, then
// convert that net vector to differential-drive wheel commands. Steering
// EMERGES from the geometry of the registered sensors — nothing is special-
// cased — so the same engine works for 2 forward IRs, splayed LDRs, or sensors
// mounted around an octagon.
//
// Design notes:
//  - Point-mass model: a sensor's mounting POSITION affects behavior implicitly
//    through what it reads (a right-mounted sensor reads right-side obstacles
//    sooner); the engine needs each sensor's ANGLE as the contribution
//    direction. (Position can be added later as an extension, not a rewrite.)
//  - Body frame: +Y = forward, +X = right, angle measured in degrees CCW from
//    +Y (matches the rest of the PAW robot code).
//  - v1 scope: IR (CogProximity) sensors only, to prove push/pull. LDR support
//    is an additive next step.
// =============================================================================

class CogPotentialField {
public:
    static constexpr int MAX_SENSORS = 8;

    enum class Policy : uint8_t { Push, Pull };

    CogPotentialField();

    // Register an IR proximity sensor as a field source.
    //   sensor     : pointer to a constructed CogProximity (owned by caller)
    //   mountAngle : degrees CCW from forward (+Y). 0 = straight ahead.
    //   gain       : scales this sensor's contribution magnitude.
    //   policy     : Push (repel, away from mount dir) or Pull (attract, toward).
    // Returns false if the sensor table is full.
    bool addProximity(CogProximity* sensor, float mountAngle,
                      float gain, Policy policy);

    // Register an LDR light sensor as a field source. Same parameters as
    // addProximity, but the strength grows with BRIGHTNESS (brighter => stronger
    // contribution). Pull => attract toward light (seek); Push => repel (flee).
    // The LDR should be mounted at its mountAngle (e.g. splayed outward) so the
    // field has direction. Returns false if the sensor table is full.
    bool addLight(CogLight* sensor, float mountAngle,
                  float gain, Policy policy);

    // Read all sensors and compute the net field vector in the body frame.
    // Results are cached and also returned via out-params (may pass nullptr).
    void computeNetVector(float* outVx, float* outVy);

    // Convenience accessors for the last computed net vector.
    float netVx() const { return _netVx; }
    float netVy() const { return _netVy; }

    // Convert the last-computed net vector to differential-drive proportions
    // in [-100, 100]. Forward component -> base speed; lateral component ->
    // turn. Fills leftProp / rightProp.
    void vectorToDifferential(int* leftProp, int* rightProp) const;

    // Tuning knobs for the vector->wheels conversion.
    void setDriveGains(float forwardGain, float turnGain);
    void setBaseSpeed(int baseSpeed);   // constant forward bias [0..100]

private:
    enum class SrcType : uint8_t { IR, LDR };

    struct Source {
        SrcType       type;         // which sensor kind this source is
        CogProximity* ir;           // valid when type == IR
        CogLight*     ldr;          // valid when type == LDR
        float mountAngle;   // degrees CCW from +Y
        float gain;
        Policy policy;
    };

    Source _sources[MAX_SENSORS];
    int    _count;

    float _netVx;   // body-frame net vector (right)
    float _netVy;   // body-frame net vector (forward)

    // vector->wheels tuning
    float _forwardGain;
    float _turnGain;
    int   _baseSpeed;

    // Convert one IR reading to a field STRENGTH where closer => stronger.
    // CogProximity::getData() returns a distance-like value (~[18..60], smaller
    // = closer), so strength is an inverse of that distance, normalized ~[0..1].
    static float proximityStrength(CogProximity* s);

    // Convert one LDR reading to a field STRENGTH where brighter => stronger.
    // CogLight::getData() returns [0..100]; normalize to [0..1].
    static float lightStrength(CogLight* s);
};

#endif // COGPOTENTIALFIELD_H

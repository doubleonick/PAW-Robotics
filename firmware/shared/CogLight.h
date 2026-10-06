#ifndef COGLIGHT_H
#define COGLIGHT_H

#include <Arduino.h>
#include "CogAnaDigi.h"

// Analog light sensor derived from CogAnaDigi.
//
// POLARITY — getData() always returns 0 = DARK, 100 = BRIGHT.
//
// Which end of the RAW range is bright is a property of the sensor, not of the
// behaviours, and is set once in PAWConfig.h via PAW_LIGHT_HIGH_IS_BRIGHT.
// Default 0 means raw rises in the DARK, which is the sensor every light
// behaviour in EthologyRobot was tuned against. Set it wrong and the gradient
// sign flips: approach_light flees the lamp and avoid_light chases it.
//
// Do NOT "fix" an apparent reversal by swapping approachLight() and
// avoidLight() or by re-deriving their motor pairs. Those were each got wrong
// twice by reasoning from the gradient sign, and are now correct.
//
// TO TELL WHICH SENSOR YOU HAVE: Serial.println(rightLight.getData()), then
// shine a torch at the right sensor. The number must go UP toward 100. If it
// goes down, flip PAW_LIGHT_HIGH_IS_BRIGHT.
//
// SIMULATOR PAIRING: engine/sensors/sensor_models.LightSensor must end up on
// this same convention, and it inverts its raw value ONCE to get there. Do not
// also invert here on the Python side — two inversions compose to the identity
// and silently change nothing, which cost a debugging round.
class CogLight : public CogAnaDigi {
public:
    // Require a labeled analog pin, e.g., "A0", "A3"
    explicit CogLight(const String& pinLabel);

    // Read raw sensor value via base class, mirror to subclass _rawData
    int getRawData();

    // Map raw [0..1023] to [0..100], 0 = dark and 100 = bright. Which end of
    // the raw range is bright depends on the sensor: PAW_LIGHT_HIGH_IS_BRIGHT
    // in PAWConfig.h.
    int getData();
    // Return the LAST value computed by getData() WITHOUT taking a new
    // sample. Use this when you need the exact reading a prior getData()
    // used (e.g. logging the same sample the control math consumed).
    int peekData() const { return _data; }

private:
    int _pin;      // mirrored pin reference
    int _rawData;  // last raw reading
    int _data;     // processed/normalized data
};

#endif // COGLIGHT_H
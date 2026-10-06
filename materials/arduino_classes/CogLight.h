#ifndef COGLIGHT_H
#define COGLIGHT_H

#include <Arduino.h>
#include "CogAnaDigi.h"

// Analog light sensor derived from CogAnaDigi.
// ============================================================================
// SENSOR POLARITY — read before pairing this code with different hardware
// ============================================================================
// getData() returns 0 = BRIGHT, 100 = DARK.
//
// The SIMULATOR matches this in engine/sensors/sensor_models.LightSensor,
// which inverts its raw value ONCE. Do not also invert CogLight's map on the
// Python side: two inversions compose to the identity and silently change
// nothing, which cost a debugging round here.
//
// That is the opposite of what most people expect, and it is not arbitrary:
// the LDR on this robot sits in a divider whose analogRead RISES IN THE DARK.
// analyzeData() maps raw [0,1023] -> [100,0], so the inversion in the map
// CANCELS the inversion in the wiring... and then the whole chain is inverted
// once more relative to intuition. The behaviours in EthologyRobot are
// calibrated against THIS convention and are verified on hardware.
//
// WHAT THIS MEANS FOR A DIFFERENT ROBOT
// -------------------------------------
// If you pair this firmware with light sensors wired the other way (rising
// with brightness — an LDR pulled the opposite way, or most breakout modules
// and phototransistor boards), every light behaviour will invert:
// approach_light will flee and avoid_light will home in.
//
// THE FIX IS HERE, IN ONE LINE, NOT IN THE BEHAVIOURS.
// Change the map in analyzeData() so that getData() still returns
// 0 = BRIGHT, 100 = DARK for your sensor:
//
//     rising-in-dark  (this robot):  map(raw, 0, 1023, 100, 0)
//     rising-in-light (many others): map(raw, 0, 1023, 0, 100)
//
// Do NOT "fix" it by swapping approachLight() and avoidLight(), and do not
// re-derive their motor commands. Those were each got wrong twice by
// reasoning from the gradient sign, and are now correct.
//
// HOW TO TELL WHICH YOU HAVE
// --------------------------
//     Serial.println(rightLight.getData());
// Shine a torch at the right sensor. The number must go DOWN toward 0.
// If it goes UP, flip the map above.
// ============================================================================

class CogLight : public CogAnaDigi {
public:
    // Require a labeled analog pin, e.g., "A0", "A3"
    explicit CogLight(const String& pinLabel);

    // Read raw sensor value via base class, mirror to subclass _rawData
    int getRawData();

    // Map raw [0..1023] to [0..100] and return
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
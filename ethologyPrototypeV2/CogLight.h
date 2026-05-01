#ifndef COGLIGHT_H
#define COGLIGHT_H

#include <Arduino.h>
#include "CogAnaDigi.h"

// Analog light sensor derived from CogAnaDigi.
class CogLight : public CogAnaDigi {
public:
    // Require a labeled analog pin, e.g., "A0", "A3"
    explicit CogLight(const String& pinLabel);

    // Read raw sensor value via base class, mirror to subclass _rawData
    int getRawData();

    // Map raw [0..1023] to [0..100] and return
    int getData();

private:
    int _pin;      // mirrored pin reference
    int _rawData;  // last raw reading
    int _data;     // processed/normalized data
};

#endif // COGLIGHT_H
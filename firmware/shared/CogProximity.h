#ifndef COGPROXIMITY_H
#define COGPROXIMITY_H

#include <Arduino.h>
#include "CogAnaDigi.h"

// Analog proximity sensor derived from CogAnaDigi.
class CogProximity : public CogAnaDigi {
public:
    // Require a labeled analog pin, e.g., "A0", "A3"
    explicit CogProximity(const String& pinLabel);

    // Read raw sensor value via base class, mirror to subclass _rawData
    int getRawData();

    // Compute processed data: clamp raw to [0,1000] then map to [10,80]
    int getData();
    // Return the LAST value computed by getData() WITHOUT taking a new
    // sample. Use this when you need the exact reading a prior getData()
    // used (e.g. logging the same sample the control math consumed).
    int peekData() const { return _data; }

private:
    int _pin;      // mirrored pin reference for subclass bookkeeping (optional but per your spec)
    int _rawData;  // last raw reading
    int _data;     // processed/normalized data

    // Helper to analyze the raw value
    int analyzeData(int raw);
};

#endif // COGPROXIMITY_H
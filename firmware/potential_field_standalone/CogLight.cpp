#include "CogLight.h"

// PAW_LIGHT_HIGH_IS_BRIGHT comes from here. It must be a header this file
// includes: CogLight.cpp is compiled on its own, so a #define in the sketch
// would never reach it.
#include "PAWConfig.h"

CogLight::CogLight(const String& pinLabel)
: CogAnaDigi(pinLabel), _pin(0), _rawData(0), _data(0)
{
    // Mirror the resolved pin like in CogProximity
    int aIdx = pinLabel.indexOf('A');
    if (aIdx < 0) aIdx = pinLabel.indexOf('a');
    String numPart = pinLabel.substring(aIdx + 1);
    numPart.trim();
    int analogIndex = numPart.toInt();
    _pin = analogIndex;
}

int CogLight::getRawData() {
    _rawData = CogAnaDigi::getRawData();
    return _rawData;
}

// Normalise to 0 = dark, 100 = bright, whichever way round the sensor reads.
// The direction is a property of the sensor, set in PAWConfig.h — every light
// behaviour depends on this output meaning the same thing on every robot.
int CogLight::getData() {
    int raw = getRawData();
#if PAW_LIGHT_HIGH_IS_BRIGHT
    _data = map(raw, 0, 1023, 0, 100);   // raw high = bright
#else
    _data = map(raw, 0, 1023, 100, 0);   // raw high = dark
#endif
    return _data;
}

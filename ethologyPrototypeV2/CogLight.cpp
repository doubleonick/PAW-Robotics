#include "CogLight.h"

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

int CogLight::getData() {
    int raw = getRawData();
    // Map 0..1023 to 0..100
    _data = map(raw, 0, 1023, 0, 100);
    return _data;
}
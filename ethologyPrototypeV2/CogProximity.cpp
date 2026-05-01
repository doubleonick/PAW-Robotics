#include "CogProximity.h"

CogProximity::CogProximity(const String& pinLabel)
: CogAnaDigi(pinLabel), _pin(0), _rawData(0), _data(0)
{
    // Optional: store numeric pin resolved by CogAnaDigi from the label
    // We can't directly access base _pin (private), so we mirror by re-parsing the label:
    // If desired, you can add a getter in CogAnaDigi to expose its resolved pin.
    int aIdx = pinLabel.indexOf('A');
    if (aIdx < 0) aIdx = pinLabel.indexOf('a');
    String numPart = pinLabel.substring(aIdx + 1);
    numPart.trim();
    int analogIndex = numPart.toInt();
    _pin = analogIndex;
}

int CogProximity::getRawData() {
    // Call the base class reader to ensure correct analog path
    _rawData = CogAnaDigi::getRawData();
    return _rawData;
}

int CogProximity::analyzeData(int raw) {
    // Clamp to [0, 1000], then map to [10, 80]
    int clamped = constrain(raw, 120, 720);
    int mapped  = map(clamped, 120, 720, 60, 18);
    return mapped;
}

int CogProximity::getData() {
    int raw = getRawData();
    _data = analyzeData(raw);
    return _data;
}

#include "CogAnaDigi.h"

// Define the class String constants
const String CogAnaDigi::ANALOG  = "Analog";
const String CogAnaDigi::DIGITAL = "Digital";

CogAnaDigi::CogAnaDigi(const String& pinLabel) {
    initFromLabel(pinLabel);
    commonInit();
}

CogAnaDigi::CogAnaDigi(int pin)
: _sensorType(DIGITAL), _pin(pin), _rawData(0)  // default to DIGITAL for numeric constructor
{
    commonInit();
}

void CogAnaDigi::initFromLabel(const String& pinLabel) {
    // Detect presence of 'A' or 'a' anywhere in the label
    bool hasA = (pinLabel.indexOf('A') >= 0) || (pinLabel.indexOf('a') >= 0);
    if (hasA) {
        _sensorType = ANALOG;

        // Extract the digits after the first 'A'/'a'
        int aIdx = pinLabel.indexOf('A');
        if (aIdx < 0) aIdx = pinLabel.indexOf('a');

        String numPart = pinLabel.substring(aIdx + 1);
        numPart.trim();

        int analogIndex = numPart.toInt(); // e.g., "3" -> 3 for A3

        // Compute pin constant. On AVR/most cores A0..An are consecutive.
        // Using A0 + index keeps it portable across many boards.
        _pin = analogIndex;
    } else {
        _sensorType = DIGITAL;
        _pin = pinLabel.toInt(); // e.g., "13" -> 13
    }
}

void CogAnaDigi::commonInit() {
    pinMode(_pin, INPUT);
    _rawData = 0;
}

int CogAnaDigi::getRawData() {
    if (_sensorType == DIGITAL) {
        _rawData = digitalRead(_pin);
    } else {
        _rawData = analogRead(_pin);
    }
    return _rawData;
}

String CogAnaDigi::getSensorType(){
  return _sensorType;
}

int CogAnaDigi::getPin(){
  return _pin;
}
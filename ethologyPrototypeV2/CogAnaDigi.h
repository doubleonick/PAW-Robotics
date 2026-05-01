#ifndef COGANADIGI_H
#define COGANADIGI_H

#include <Arduino.h>

class CogAnaDigi {
public:
    // Class-string constants (values "Analog" and "Digital")
    static const String ANALOG;
    static const String DIGITAL;

    // Constructor that accepts a label like "A0" or "13".
    explicit CogAnaDigi(const String& pinLabel);

    // Constructor that accepts a numeric pin (assumed DIGITAL by default).
    explicit CogAnaDigi(int pin);

    // Read raw sensor data: digitalRead for DIGITAL, analogRead for ANALOG
    int getRawData();

    String getSensorType();

    int getPin();

private:
    String _sensorType; // "Analog" or "Digital"
    int    _pin;        // Arduino pin: e.g., A0 or 9
    int    _rawData;    // last raw reading

    // Helper: parse "A#" or "#" into a pin number and set _sensorType
    void initFromLabel(const String& pinLabel);

    // Common initializer after _pin/_sensorType are decided
    void commonInit();
};

#endif // COGANADIGI_H

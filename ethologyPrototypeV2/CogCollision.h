#ifndef COGCOLLISION_H
#define COGCOLLISION_H

#include <Arduino.h>
#include "CogAnaDigi.h"

// Digital collision sensor that inherits from CogAnaDigi.
// Uses INPUT_PULLUP in the constructor; returns digitalRead() via getData().
class CogCollision : public CogAnaDigi {
public:
    explicit CogCollision(int pin);

    // Return value from digitalRead() (0 or 1).
    int getData();

private:
    int _pin;   // digital pin for collision sensor (mirrored for the subclass)
    int _data;  // last read value
};

#endif // COGCOLLISION_H
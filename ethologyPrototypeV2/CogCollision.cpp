#include "CogCollision.h"

CogCollision::CogCollision(int pin)
: CogAnaDigi(pin), _pin(pin), _data(0)
{
    // Override default INPUT from base and use INPUT_PULLUP for collision switches
    pinMode(_pin, INPUT_PULLUP);
}

int CogCollision::getData() {
    _data = digitalRead(_pin);
    return _data;
}
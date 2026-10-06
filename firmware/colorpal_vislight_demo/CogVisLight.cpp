#include "CogVisLight.h"

// Non-existent pin for the "unused" half of each SoftwareSerial (reference uses
// 255). Two SoftwareSerial objects share the one SIG pin: serin RX-only,
// serout TX-only — exactly the reference arrangement.
static const uint8_t PAL_UNUSED = 255;

CogVisLight::CogVisLight(uint8_t sigPin, long baud)
: _sigPin(sigPin), _baud(baud),
  _serin(sigPin, PAL_UNUSED),     // RX on sigPin
  _serout(PAL_UNUSED, sigPin),    // TX on sigPin
  _r(0), _g(0), _b(0) {}

// Reference reset sequence (behaviour preserved; bounded wait as insurance).
void CogVisLight::resetPAL() {
    delay(200);
    pinMode(_sigPin, OUTPUT);
    digitalWrite(_sigPin, LOW);
    pinMode(_sigPin, INPUT);
    unsigned long start = millis();
    while (digitalRead(_sigPin) != HIGH) {
        if (millis() - start > 1000) break;   // don't hang if sensor is absent
    }
    pinMode(_sigPin, OUTPUT);
    digitalWrite(_sigPin, LOW);
    delay(80);
    pinMode(_sigPin, INPUT);
    delay(200);
}

// Reset, program the looping macro, switch to receive — the reference's setup().
void CogVisLight::begin() {
    resetPAL();
    _serout.begin(_baud);
    pinMode(_sigPin, OUTPUT);
    _serout.print("=(00 $ m)!");   // loop: emit '$' then ambient-corrected RGB
    _serout.end();
    pinMode(_sigPin, INPUT);
    _serin.begin(_baud);
}

// Read one frame, mirroring the reference readData()/parseAndPrint() exactly:
// wait for '$', read 9 hex chars, sscanf three 3-hex values into R,G,B.
bool CogVisLight::read() {
    // Wait for a '$' delimiter (bounded so we don't block forever).
    unsigned long start = millis();
    bool synced = false;
    while (millis() - start < 2000) {
        if (_serin.available() > 0) {
            if ((char)_serin.read() == '$') { synced = true; break; }
        }
    }
    if (!synced) return false;

    // Read 9 characters after the '$'. If a '$' appears, the frame restarted.
    char buffer[10];
    for (int i = 0; i < 9; i++) {
        while (_serin.available() == 0) {
            if (millis() - start > 2000) return false;
        }
        buffer[i] = _serin.read();
        if (buffer[i] == '$') return false;   // early restart; try again
    }
    buffer[9] = '\0';

    int red, grn, blu;
    if (sscanf(buffer, "%3x%3x%3x", &red, &grn, &blu) != 3) return false;
    _r = red; _g = grn; _b = blu;
    return true;
}

// ---- Qualitative helpers ---------------------------------------------------

const char* CogVisLight::lightLevel() const {
    int sum = _r + _g + _b;           // 0 .. ~3069
    if (sum < 150)  return "dark";
    if (sum < 600)  return "dim";
    if (sum < 1500) return "lit";
    return "bright";
}

const char* CogVisLight::colorName() const {
    int sum = _r + _g + _b;
    if (sum < 150) return "dark";     // too little light to call a colour

    // Compare each channel to the average; a channel well above average
    // "dominates". Combinations give secondary colours; all-similar = white.
    int avg = sum / 3;
    int th  = avg / 4 + 1;            // "significantly above average" threshold
    bool rHi = _r > avg + th;
    bool gHi = _g > avg + th;
    bool bHi = _b > avg + th;
    bool rLo = _r < avg - th;
    bool gLo = _g < avg - th;
    bool bLo = _b < avg - th;

    if (rHi && !gHi && !bHi) return "red";
    if (gHi && !rHi && !bHi) return "green";
    if (bHi && !rHi && !gHi) return "blue";
    if (rHi && gHi && bLo)   return "yellow";   // red+green
    if (gHi && bHi && rLo)   return "cyan";      // green+blue
    if (rHi && bHi && gLo)   return "magenta";   // red+blue
    return "white";                              // roughly balanced
}

// ---- Diagnostic ------------------------------------------------------------

void CogVisLight::debugDumpRaw(uint16_t ms) {
    unsigned long start = millis();
    while (millis() - start < ms) {
        if (_serin.available()) {
            char ch = (char)_serin.read();
            if (ch >= 32 && ch <= 126) Serial.print(ch);
            else { Serial.print('<'); Serial.print((uint8_t)ch, HEX); Serial.print('>'); }
        }
    }
    Serial.println();
}

// ---- LEDs-off incident-light mode (the light-seeking experiment) -----------
// Program the ColorPAL to loop "X s": X = turn the LED off, s = sample the
// light sensor. With the LED off, the reading reflects INCIDENT light on the
// sensor (ambient / a light source you point at it), not reflection of the
// ColorPAL's own LEDs. One 3-hex value per '$'-delimited frame.
void CogVisLight::beginLightMode() {
    resetPAL();
    _serout.begin(_baud);
    pinMode(_sigPin, OUTPUT);
    _serout.print("=(00 $ X s)!");   // loop: '$' then one LEDs-off sample
    _serout.end();
    pinMode(_sigPin, INPUT);
    _serin.begin(_baud);
}

// Read one LEDs-off sample: wait for '$', then read 3 hex digits.
bool CogVisLight::readLight(int* out) {
    unsigned long start = millis();
    bool synced = false;
    while (millis() - start < 2000) {
        if (_serin.available() > 0 && (char)_serin.read() == '$') { synced = true; break; }
    }
    if (!synced) return false;

    char buffer[4];
    for (int i = 0; i < 3; i++) {
        while (_serin.available() == 0) {
            if (millis() - start > 2000) return false;
        }
        char ch = _serin.read();
        if (ch == '$') return false;   // frame restarted early
        buffer[i] = ch;
    }
    buffer[3] = '\0';

    int val;
    if (sscanf(buffer, "%3x", &val) != 1) return false;
    if (out) *out = val;
    return true;
}

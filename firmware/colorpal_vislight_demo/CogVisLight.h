#ifndef COGVISLIGHT_H
#define COGVISLIGHT_H

#include <Arduino.h>
#include <SoftwareSerial.h>

// =============================================================================
// CogVisLight  (built on the PROVEN Parallax reference driver)
// -----------------------------------------------------------------------------
// Wraps the Parallax ColorPAL (#28380) reference sketch's WORKING serial
// protocol in a class, and adds two conveniences on top:
//   * a QUALITATIVE colour name   (colorName(): "red", "green", "blue", ...)
//   * a QUALITATIVE light level   (lightLevel(): "dark", "dim", "lit", "bright")
//     plus a numeric ambient/brightness proxy (ambient()).
//
// PROTOCOL: kept faithful to the reference that works on this hardware — two
// SoftwareSerial objects on one pin (serin RX-only, serout TX-only,
// unused=255), reset into Direct mode, program the looping macro "=(00 $ m)!",
// then read the '$'-delimited stream of three 3-hex-digit values (ambient-
// corrected R, G, B). 4800 baud. The transport is NOT "improved" — that's the
// part that works.
//
// AMBIENT NOTE: the 'm' macro already subtracts ambient from each RGB channel.
// Rather than switch the device into a separate ambient mode (which proved
// flaky), this class derives a BRIGHTNESS proxy from the RGB sum — an honest
// "how much is coming back overall" measure.
// =============================================================================

class CogVisLight {
public:
    explicit CogVisLight(uint8_t sigPin, long baud = 4800);

    void begin();             // reset + program + start receive stream
    bool read();              // read one R,G,B frame; caches r()/g()/b()

    // LEDs-OFF incident-light test: program the sensor to loop "X s" (LEDs off,
    // sample) so it reports whatever light FALLS ON it (not reflection of its
    // own LEDs). This is the mode that could plausibly do light-seeking.
    void beginLightMode();    // switch to LEDs-off ambient streaming
    bool readLight(int* out); // read one LEDs-off sample (~0..1023); true=ok

    int r() const { return _r; }
    int g() const { return _g; }
    int b() const { return _b; }

    // Qualitative helpers (operate on the last read() values):
    int         ambient()    const { return _r + _g + _b; }  // brightness proxy
    const char* lightLevel() const;   // "dark"|"dim"|"lit"|"bright"
    const char* colorName()  const;   // "red"|"green"|"blue"|"yellow"|...

    void debugDumpRaw(uint16_t ms);   // troubleshooting: dump raw bytes

private:
    uint8_t        _sigPin;
    long           _baud;
    SoftwareSerial _serin;    // RX on _sigPin (TX = unused 255)
    SoftwareSerial _serout;   // TX on _sigPin (RX = unused 255)
    int _r, _g, _b;
    void resetPAL();
};

#endif // COGVISLIGHT_H

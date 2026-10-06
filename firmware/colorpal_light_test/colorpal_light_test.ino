/*
  colorpal_light_test.ino
  -----------------------------------------------------------------------------
  FOCUSED EXPERIMENT: can the Parallax ColorPAL sense INCIDENT light (act like
  a crude LDR) with its LEDs OFF? This decides whether it could ever do
  light-seeking/avoiding.

  In normal color mode the ColorPAL fires its own LEDs and reads reflection —
  useless for a distant light source. The "X s" command samples the light
  sensor with the LED OFF, so the reading should track light FALLING ON it.

  WHAT TO DO: open Serial Monitor (9600). Watch the streamed value while you:
    1. Cover the sensor with your hand           -> expect LOW  (less light)
    2. Point it at a bright lamp / phone torch    -> expect HIGH (more light)
    3. Move the lamp closer / farther             -> expect value to track it
    4. Turn room lights off/on                    -> expect value to follow

  INTERPRETATION:
    * If the value clearly RISES with more incident light and FALLS with less,
      and responds at useful distance -> the ColorPAL CAN do (crude, non-
      directional) light sensing; light-seeking is possible (needs TWO units,
      angled, for steering).
    * If the value barely moves, or only reacts to a hand a few cm away (like
      the reflective color mode did) -> the ColorPAL CANNOT usefully sense
      incident light; use LDRs for light-seeking instead.

  Wiring: ColorPAL SIG -> SIG_PIN, +5V -> 5V, GND -> GND. Classic AVR board.
*/

#include "CogVisLight.h"

const uint8_t SIG_PIN  = 6;      // match your wiring (reference used pin 6)
const long    PAL_BAUD = 4800;   // proven baud
CogVisLight vis(SIG_PIN, PAL_BAUD);

int  minSeen = 9999;
int  maxSeen = -1;

void setup() {
    Serial.begin(9600);
    Serial.println("ColorPAL LEDs-OFF incident-light test");
    Serial.println("Cover it (expect low), shine light at it (expect high).");
    vis.beginLightMode();
}

void loop() {
    int v;
    if (vis.readLight(&v)) {
        if (v < minSeen) minSeen = v;
        if (v > maxSeen) maxSeen = v;
        Serial.print("light = "); Serial.print(v);
        Serial.print("   (min "); Serial.print(minSeen);
        Serial.print(", max "); Serial.print(maxSeen);
        Serial.print(", range "); Serial.print(maxSeen - minSeen);
        Serial.println(")");
    }
    delay(100);
}

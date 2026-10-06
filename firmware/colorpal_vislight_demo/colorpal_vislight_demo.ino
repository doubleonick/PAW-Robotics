/*
  colorpal_vislight_demo.ino
  -----------------------------------------------------------------------------
  Demo for CogVisLight (Parallax ColorPAL #28380), built on the PROVEN Parallax
  reference protocol, with two added conveniences:
    * qualitative COLOUR name   (red/green/blue/yellow/cyan/magenta/white/dark)
    * qualitative LIGHT level    (dark/dim/lit/bright) + numeric brightness

  Wiring (same as the working reference sketch):
    ColorPAL SIG -> Arduino digital pin SIG_PIN
    ColorPAL +5V -> 5V,  GND -> GND   (ColorPAL has its own pull-up)

  BOARD: classic AVR (UNO R3 / Mega 2560). Not the UNO R4.

  IMPORTANT: this uses the reference's 4800 baud and exact protocol, since that
  is what works on this hardware. If you still see no data, set RAW_DIAGNOSTIC
  true to view raw bytes, and make sure SIG_PIN matches your wiring.
*/

#include "CogVisLight.h"

const uint8_t SIG_PIN = 6;          // The reference used pin 6. Match your wiring!
const long    PAL_BAUD = 4800;      // reference baud (proven)
CogVisLight vis(SIG_PIN, PAL_BAUD);

const bool RAW_DIAGNOSTIC = false;  // true = dump raw bytes for troubleshooting

void setup() {
    Serial.begin(9600);
    Serial.println("CogVisLight (ColorPAL) - reference-based, with color+light words");
    vis.begin();
}

void loop() {
    if (RAW_DIAGNOSTIC) { vis.debugDumpRaw(1000); return; }

    if (vis.read()) {
        Serial.print("R="); Serial.print(vis.r());
        Serial.print(" G="); Serial.print(vis.g());
        Serial.print(" B="); Serial.print(vis.b());
        Serial.print("  | colour: "); Serial.print(vis.colorName());
        Serial.print("  | light: ");  Serial.print(vis.lightLevel());
        Serial.print(" ("); Serial.print(vis.ambient()); Serial.println(")");
    }
    // (No "failed" spam: the reference simply waits for the next frame.)
    delay(50);
}

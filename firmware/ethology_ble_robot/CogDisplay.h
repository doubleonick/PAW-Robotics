#ifndef COGDISPLAY_H
#define COGDISPLAY_H

#include <Arduino.h>

// PAW_USE_DISPLAY and PAW_DISPLAY_DEV come from here, NOT from the sketch.
// CogDisplay.cpp is a separate translation unit: a #define in the .ino never
// reaches it, so the sketch would declare real methods while this file
// compiled empty inline ones and the link would fail with
// "undefined reference to CogDisplay::setGuards".
#include "PAWConfig.h"

// GIGA Display Shield output (800x480).
//
// Built only when PAW_USE_DISPLAY is 1. The sketch provides a do-nothing
// stand-in otherwise, so the call sites never need an #if of their own.
//
// ── Two tiers ────────────────────────────────────────────────────────────────
//
//   PAW_DISPLAY_DEV 0  (default)  BLE status and session token, nothing else.
//                                 This is the classroom build. Students are
//                                 meant to observe behaviour and infer the
//                                 hierarchy; showing sensor values or the rung
//                                 list gives away the exercise.
//
//   PAW_DISPLAY_DEV 1             Adds the hierarchy with per-rung guard state
//                                 and a raw sensor strip. Bench instrument.
//
// The tier is a compile-time switch rather than a second class or a second
// sketch, for the same reason PAW_USE_DISPLAY is: two lineages of the same
// firmware is how the cruise-arc values and the CogLight polarity both
// drifted. One file, one set of call sites.
//
// Set -DPAW_DISPLAY_DEV=1 to build the instrument.
#ifndef PAW_DISPLAY_DEV
#define PAW_DISPLAY_DEV 0
#endif

// ── What the development tier shows ──────────────────────────────────────────
//
//   STATUS   connection state, blinking while a link is pending
//   RUNGS    the installed hierarchy, one row each, with two independent marks:
//              - guard dot lit   = this rung's condition is met right now
//              - row highlighted = this rung is the one that fired
//            A lit dot on an unhighlighted row was subsumed by a rung above.
//            All dots dark means nothing can fire.
//   SENSORS  the raw readings the guards actually used
//
// The pairing is the diagnostic. hierarchy() short-circuits at the first rung
// that fires, so it never learns whether the rungs below would also have
// passed — EthologyRobot::guardMet() is what makes a masked rung visible. On a
// partly wired robot a floating pin holds a guard true and starves everything
// below it, which from outside looks identical to "the robot just sits there".
//
// CogDisplay knows nothing about EthologyRobot. It takes plain values and
// indices, so it stays an output device like the other Cog classes.

#if PAW_USE_DISPLAY

class CogDisplay {
public:
    // Mirrors EthologyRobot::MAX_HIERARCHY.
    static const int MAX_ROWS = 8;

    CogDisplay() = default;

    // Bring up the panel. Call once in setup().
    void begin();

    // ── Verbose toggle ───────────────────────────────────────────────────
    //
    // Two levels of control, and they do different jobs:
    //
    //   PAW_DISPLAY_DEV   compile-time. 0 means the rung list and sensor code
    //                     is not in the binary at all, so a classroom build
    //                     cannot be talked into showing it.
    //   setVerbose()      run-time, only meaningful when PAW_DISPLAY_DEV is 1.
    //                     Flip the HUD on and off without recompiling — useful
    //                     when you want to watch actual behaviour for a minute
    //                     and then go back to diagnosing.
    //
    // Defaults to on when the HUD is compiled in. Turning it off repaints,
    // leaving status only.
    void setVerbose(bool on);
    void toggleVerbose();
    bool verbose() const;

    // ── Classroom tier ───────────────────────────────────────────────────
    // Headline plus an optional second line (the session token). Both copied.
    void setBleStatus(const char* status, const char* session);

    // Same thing without the BLE flavour, for sketches that have no link —
    // a downloaded hierarchy sketch runs standalone and never advertises.
    void setStatus(const char* status, const char* detail = "") {
        setBleStatus(status, detail);
    }

    // Repaint the status region if it changed. Safe to call every loop().
    void updateStatus();

    // ── Development tier ─────────────────────────────────────────────────
    // Declared unconditionally so the sketch's call sites need no #if. With
    // PAW_DISPLAY_DEV 0 the bodies below are empty and inline, so they are
    // compiled out entirely rather than becoming empty calls each tick.

#if PAW_DISPLAY_DEV
    // The behaviour list, highest priority first, as wire names. Prettied for
    // display, so there is no second label table to drift. Copied.
    void setHierarchy(const char* const* names, int count);
    void clearHierarchy();

    // Which rung fired this tick, or -1. From bot.lastFiredIndex().
    void setActive(int index);

    // Which rungs' conditions are met, in hierarchy order. From
    // bot.guardMet(bot.behaviorAt(i)).
    void setGuards(const bool* guards, int count);

    // The readings the guards used. From bot.snapshot() — not from re-reading
    // the Cog objects, or the screen will contradict the decision it is
    // explaining. Bumpers are INPUT_PULLUP: 0 is pressed.
    void setSensors(int leftProx, int rightProx, int lightGradient,
                    int leftFrontBump, int rightFrontBump,
                    int leftBackBump,  int rightBackBump);

    // Repaint whatever changed in the development regions.
    void update();

    // Retained from the pre-BLE HUD so older call sites still compile.
    void setLights(int left, int right);
    void setProximity(int left, int right);
    void setBumps(int leftFront, int rightFront, int leftBack, int rightBack);
    void setWheelSpeeds(int left, int right);
#else
    // Present so call sites compile either way; there is nothing to reveal.
    void setHierarchy(const char* const*, int) {}
    void clearHierarchy() {}
    void setActive(int) {}
    void setGuards(const bool*, int) {}
    void setSensors(int, int, int, int, int, int, int) {}
    void update() {}
    void setLights(int, int) {}
    void setProximity(int, int) {}
    void setBumps(int, int, int, int) {}
    void setWheelSpeeds(int, int) {}
#endif

private:
    // 16-bit RGB565.
    static const uint16_t C_BG      = 0x0000;
    static const uint16_t C_DIM     = 0x4208;
    static const uint16_t C_TEXT    = 0xC618;
    static const uint16_t C_LIVE    = 0x07E0;
    static const uint16_t C_WAIT    = 0xFD20;
    static const uint16_t C_ERR     = 0xF800;
    static const uint16_t C_GUARD   = 0x07FF;
    static const uint16_t C_HI_BG   = 0x07E0;
    static const uint16_t C_HI_TEXT = 0x0000;

    static const int16_t PAD      = 20;
    // No title row: the status headline starts at the top of the panel.
    static const int16_t STATUS_Y = 10;
    static const int16_t DETAIL_Y = 84;
    static const int16_t RULE1_Y  = 114;
    static const int16_t LIST_Y   = 126;
    static const int16_t ROW_H    = 34;
    static const int16_t RULE2_Y  = 416;
    static const int16_t SENS_Y   = 426;

    char _status[24]  = {0};
    char _session[24] = {0};

    bool     _dirtyStatus = true;
    bool     _blinkOn     = true;
    uint32_t _blinkAt     = 0;
    bool     _verbose     = (PAW_DISPLAY_DEV != 0);

    void        _paintFrame();
    void        _paintStatus();
    uint16_t    _statusColor() const;
    bool        _statusBlinks() const;

#if PAW_DISPLAY_DEV
    char _rows[MAX_ROWS][22] = {{0}};
    int  _rowCount = 0;

    bool _guards[MAX_ROWS]        = {false};
    bool _paintedGuards[MAX_ROWS] = {false};
    int  _active        = -1;
    int  _paintedActive = -1;

    int  _sens[7]        = {0};
    int  _paintedSens[7] = {0};
    bool _hasSensors     = false;

    bool _dirtyList    = true;
    bool _dirtySensors = true;

    void _paintList();
    void _paintRow(int i);
    void _paintSensors();

    // "escape_front" -> "ESCAPE FRONT"
    static void _pretty(const char* wire, char* out, size_t cap);
#endif
};

#else   // PAW_USE_DISPLAY == 0

// Do-nothing stand-in so call sites need no #if of their own. Every method is
// empty and inline, so a display-free build carries no display code and takes
// no dependency on Arduino_GigaDisplay_GFX. CogDisplay.cpp compiles to nothing
// in this configuration.
class CogDisplay {
public:
    static const int MAX_ROWS = 8;
    void begin() {}
    void setBleStatus(const char*, const char*) {}
    void setStatus(const char*, const char* = "") {}
    void updateStatus() {}
    void update() {}
    void setVerbose(bool) {}
    void toggleVerbose() {}
    bool verbose() const { return false; }
    void setHierarchy(const char* const*, int) {}
    void clearHierarchy() {}
    void setActive(int) {}
    void setGuards(const bool*, int) {}
    void setSensors(int, int, int, int, int, int, int) {}
    void setLights(int, int) {}
    void setProximity(int, int) {}
    void setBumps(int, int, int, int) {}
    void setWheelSpeeds(int, int) {}
};

#endif  // PAW_USE_DISPLAY

#endif // COGDISPLAY_H

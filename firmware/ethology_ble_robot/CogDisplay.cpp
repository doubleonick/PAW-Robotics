#include "CogDisplay.h"

// Nothing here exists unless the display is switched on in PAWConfig.h. The
// include below is inside the guard so a display-free build never needs the
// library installed.
#if PAW_USE_DISPLAY

#include <Arduino_GigaDisplay_GFX.h>
#include <string.h>
#include <stdio.h>

// Note: the sketch's file-list comment says CogDisplay needs Arduino_H7_Video.
// It does not. That is the lvgl/framebuffer stack; this draws text and filled
// rectangles, which Arduino_GigaDisplay_GFX covers with far less overhead.
// Requires GIGA core 4.0.6 or later.

namespace {
    GigaDisplay_GFX gfx;

    // Landscape. Swap these AND change DISPLAY_ROTATION to 0 or 2 for portrait.
    const uint8_t DISPLAY_ROTATION = 1;
    const int16_t SCREEN_W = 800;
    const int16_t SCREEN_H = 480;

    // Default GFX font is 6x8 px at size 1.
    inline int16_t textW(int len, uint8_t size) { return (int16_t)(len * 6 * size); }
    inline int16_t textH(uint8_t size)          { return (int16_t)(8 * size); }
}

void CogDisplay::begin() {
    gfx.begin();
    // The panel is natively 480x800 portrait. Rotation 1 turns it landscape,
    // which is what the 800x480 layout below assumes. If the image is upside
    // down, the shield is mounted the other way round: use 3.
    gfx.setRotation(DISPLAY_ROTATION);
    gfx.setTextWrap(false);
    gfx.fillScreen(C_BG);
    _paintFrame();
    _dirtyStatus = true;
#if PAW_DISPLAY_DEV
    _dirtyList    = true;
    _dirtySensors = true;
#endif
    updateStatus();
}

// ── Classroom tier ────────────────────────────────────────────────────────

void CogDisplay::setBleStatus(const char* status, const char* session) {
    const char* st = status  ? status  : "";
    const char* se = session ? session : "";

    if (strncmp(st, _status,  sizeof(_status))  == 0 &&
        strncmp(se, _session, sizeof(_session)) == 0) {
        return;   // nothing changed; do not touch the panel
    }

    strncpy(_status,  st, sizeof(_status)  - 1); _status [sizeof(_status)  - 1] = '\0';
    strncpy(_session, se, sizeof(_session) - 1); _session[sizeof(_session) - 1] = '\0';

    _blinkOn     = true;
    _blinkAt     = millis();
    _dirtyStatus = true;
}

void CogDisplay::updateStatus() {
    // Blink while a link is pending, so a stalled advertise is visibly
    // different from a frozen sketch.
    if (_statusBlinks()) {
        const uint32_t now = millis();
        if (now - _blinkAt >= 500) {
            _blinkAt     = now;
            _blinkOn     = !_blinkOn;
            _dirtyStatus = true;
        }
    } else if (!_blinkOn) {
        _blinkOn     = true;
        _dirtyStatus = true;
    }

    if (_dirtyStatus) { _paintStatus(); _dirtyStatus = false; }
}

void CogDisplay::_paintFrame() {
    gfx.drawFastHLine(PAD, RULE1_Y, SCREEN_W - 2 * PAD, C_DIM);
#if PAW_DISPLAY_DEV
    if (_verbose) gfx.drawFastHLine(PAD, RULE2_Y, SCREEN_W - 2 * PAD, C_DIM);
#endif
}

void CogDisplay::_paintStatus() {
    const uint16_t col = _statusColor();

    // Each region is cleared first: GFX text does not erase what it overdraws.
    gfx.fillRect(PAD, STATUS_Y, 28, 44, C_BG);
    if (_blinkOn) gfx.fillRect(PAD, STATUS_Y + 8, 28, 28, col);

    const int16_t tx = PAD + 48;
    gfx.fillRect(tx, STATUS_Y, SCREEN_W - tx - PAD, 44, C_BG);
    gfx.setTextSize(4);
    gfx.setTextColor(col);
    gfx.setCursor(tx, STATUS_Y + (44 - textH(4)) / 2);
    gfx.print(_status);

    gfx.fillRect(tx, DETAIL_Y, SCREEN_W - tx - PAD, 20, C_BG);
    if (_session[0] != '\0') {
        gfx.setTextSize(2);
        gfx.setTextColor(C_DIM);
        gfx.setCursor(tx, DETAIL_Y);
        gfx.print(_session);
    }
}

uint16_t CogDisplay::_statusColor() const {
    if (strstr(_status, "FAIL") || strstr(_status, "ERROR")) return C_ERR;
    if (strcmp(_status, "RUNNING")   == 0)                   return C_LIVE;
    if (strcmp(_status, "CONNECTED") == 0)                   return C_LIVE;
    if (strcmp(_status, "ADVERTISING") == 0)                 return C_WAIT;
    if (_status[0] == '\0')                                  return C_DIM;
    return C_WAIT;
}

bool CogDisplay::_statusBlinks() const {
    return strcmp(_status, "ADVERTISING") == 0;
}

// ── Verbose toggle ────────────────────────────────────────────────────────

bool CogDisplay::verbose() const {
#if PAW_DISPLAY_DEV
    return _verbose;
#else
    return false;   // not compiled in; nothing to show
#endif
}

void CogDisplay::setVerbose(bool on) {
#if PAW_DISPLAY_DEV
    if (on == _verbose) return;
    _verbose = on;

    // Clear whatever the other mode left behind, then let update() repaint.
    gfx.fillRect(0, LIST_Y, SCREEN_W, SCREEN_H - LIST_Y, C_BG);
    if (_verbose) {
        gfx.drawFastHLine(PAD, RULE2_Y, SCREEN_W - 2 * PAD, C_DIM);
    }
    _dirtyList     = true;
    _dirtySensors  = true;
    _paintedActive = -1;
#else
    (void)on;
#endif
}

void CogDisplay::toggleVerbose() { setVerbose(!verbose()); }

// ── Development tier ──────────────────────────────────────────────────────

#if PAW_DISPLAY_DEV

void CogDisplay::setHierarchy(const char* const* names, int count) {
    if (names == nullptr || count < 0) count = 0;
    if (count > MAX_ROWS) count = MAX_ROWS;

    for (int i = 0; i < count; i++) {
        _pretty(names[i], _rows[i], sizeof(_rows[0]));
        _guards[i]        = false;
        _paintedGuards[i] = false;
    }
    _rowCount      = count;
    _active        = -1;
    _paintedActive = -1;
    _dirtyList     = true;
}

void CogDisplay::clearHierarchy() {
    _rowCount      = 0;
    _active        = -1;
    _paintedActive = -1;
    _dirtyList     = true;
}

// setActive, setGuards and setSensors only store. update() diffs against what
// is on the panel, so the sketch calls them unconditionally every tick.

void CogDisplay::setActive(int index) {
    if (index < -1 || index >= _rowCount) index = -1;
    _active = index;
}

void CogDisplay::setGuards(const bool* guards, int count) {
    if (guards == nullptr) return;
    if (count > _rowCount) count = _rowCount;
    for (int i = 0; i < count; i++) _guards[i] = guards[i];
}

void CogDisplay::setSensors(int leftProx, int rightProx, int lightGradient,
                            int leftFrontBump, int rightFrontBump,
                            int leftBackBump,  int rightBackBump) {
    _sens[0] = leftProx;      _sens[1] = rightProx;
    _sens[2] = lightGradient;
    _sens[3] = leftFrontBump; _sens[4] = rightFrontBump;
    _sens[5] = leftBackBump;  _sens[6] = rightBackBump;
    _hasSensors = true;
}

void CogDisplay::update() {
    if (!_verbose) return;   // status only; updateStatus() still runs

    if (_dirtyList) {
        _paintList();
        _dirtyList     = false;
        _paintedActive = _active;
        for (int i = 0; i < _rowCount; i++) _paintedGuards[i] = _guards[i];
    } else {
        for (int i = 0; i < _rowCount; i++) {
            const bool wasActive = (i == _paintedActive);
            const bool nowActive = (i == _active);
            if (wasActive != nowActive || _paintedGuards[i] != _guards[i]) {
                _paintRow(i);
                _paintedGuards[i] = _guards[i];
            }
        }
        _paintedActive = _active;
    }

    if (_hasSensors) {
        if (!_dirtySensors) {
            for (int i = 0; i < 7; i++) {
                if (_sens[i] != _paintedSens[i]) { _dirtySensors = true; break; }
            }
        }
        if (_dirtySensors) {
            _paintSensors();
            for (int i = 0; i < 7; i++) _paintedSens[i] = _sens[i];
            _dirtySensors = false;
        }
    }
}

void CogDisplay::_paintList() {
    gfx.fillRect(0, LIST_Y, SCREEN_W, RULE2_Y - LIST_Y - 2, C_BG);

    if (_rowCount == 0) {
        gfx.setTextSize(2);
        gfx.setTextColor(C_DIM);
        gfx.setCursor(PAD, LIST_Y + 6);
        gfx.print("No hierarchy installed");
        return;
    }
    for (int i = 0; i < _rowCount; i++) _paintRow(i);
}

void CogDisplay::_paintRow(int i) {
    const bool    active = (i == _active);
    const int16_t y      = LIST_Y + i * ROW_H;
    const int16_t w      = SCREEN_W - 2 * PAD;
    const int16_t h      = ROW_H - 4;

    gfx.fillRect(PAD, y, w, h, active ? C_HI_BG : C_BG);

    // Guard dot: is this rung's condition met, whether or not it won.
    const uint16_t dot = _guards[i] ? (active ? C_HI_TEXT : C_GUARD) : C_DIM;
    gfx.fillRect(PAD + 8, y + h / 2 - 6, 12, 12, dot);

    const uint16_t fg = active ? C_HI_TEXT : C_TEXT;
    const int16_t  ty = y + (h - textH(3)) / 2;
    const int16_t  tx = PAD + 34;

    gfx.setTextSize(3);
    gfx.setTextColor(active ? C_HI_TEXT : C_DIM);
    gfx.setCursor(tx, ty);
    gfx.print(i + 1);

    gfx.setTextColor(fg);
    gfx.setCursor(tx + textW(2, 3), ty);
    gfx.print(_rows[i]);

    // A rung whose condition is met but which did not fire was subsumed by
    // something above it. Naming it saves inferring it.
    if (_guards[i] && !active) {
        gfx.setTextSize(2);
        gfx.setTextColor(C_DIM);
        gfx.setCursor(SCREEN_W - PAD - textW(8, 2) - 6, y + (h - textH(2)) / 2);
        gfx.print("SUBSUMED");
    }
}

void CogDisplay::_paintSensors() {
    char line[64];

    gfx.fillRect(PAD, SENS_Y, SCREEN_W - 2 * PAD, SCREEN_H - SENS_Y - 4, C_BG);
    gfx.setTextSize(2);
    gfx.setTextColor(C_TEXT);

    snprintf(line, sizeof(line), "PROX  L %4d  R %4d      LIGHT GRAD %5d",
             _sens[0], _sens[1], _sens[2]);
    gfx.setCursor(PAD, SENS_Y);
    gfx.print(line);

    // INPUT_PULLUP: 0 is pressed.
    snprintf(line, sizeof(line), "BUMP  LF %c  RF %c   LB %c  RB %c",
             _sens[3] == 0 ? '*' : '.', _sens[4] == 0 ? '*' : '.',
             _sens[5] == 0 ? '*' : '.', _sens[6] == 0 ? '*' : '.');
    gfx.setCursor(PAD, SENS_Y + 22);
    gfx.print(line);
}

void CogDisplay::_pretty(const char* wire, char* out, size_t cap) {
    if (wire == nullptr || cap == 0) { if (cap) out[0] = '\0'; return; }

    size_t j = 0;
    for (size_t i = 0; wire[i] != '\0' && j < cap - 1; i++) {
        const char c = wire[i];
        out[j++] = (c == '_') ? ' ' : (char)toupper((unsigned char)c);
    }
    out[j] = '\0';
}

// Retained call sites forward into the sensor strip. The four-argument
// setBumps carries front and back; the old two-argument form is gone.
void CogDisplay::setLights(int left, int right) {
    _sens[2] = right - left;   // gradient, matching readSensors()
    _hasSensors = true;
}

void CogDisplay::setProximity(int left, int right) {
    _sens[0] = left; _sens[1] = right; _hasSensors = true;
}

void CogDisplay::setBumps(int leftFront, int rightFront,
                          int leftBack,  int rightBack) {
    _sens[3] = leftFront; _sens[4] = rightFront;
    _sens[5] = leftBack;  _sens[6] = rightBack;
    _hasSensors = true;
}

void CogDisplay::setWheelSpeeds(int, int) {
    // Deliberately empty. Wheel commands are not shown: the rung highlight
    // already says what the robot was told to do, and a speed readout invites
    // reading motion off the screen instead of off the robot.
}

#endif  // PAW_DISPLAY_DEV

#endif  // PAW_USE_DISPLAY

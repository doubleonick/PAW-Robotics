#include "CogBluetooth.h"

// ── Known behaviour names (must match Python BEHAVIOR_MAP in codegen.py) ──────
static const int N_BEHAVIORS = 4;
static const char* BEHAVIOR_NAMES[N_BEHAVIORS] = {
    "escape_front",
    "avoid_object",
    "seek_light",
    "cruise_straight",
};

// ── Constructor ───────────────────────────────────────────────────────────────

CogBluetooth::CogBluetooth()
    : _service ("19B20000-E8F2-537E-4F6C-D104768A1214"),
      _cmdChar ("19B20001-E8F2-537E-4F6C-D104768A1214", BLEWrite, 128),
      _dataChar("19B20002-E8F2-537E-4F6C-D104768A1214", BLERead | BLENotify, 128),
      _running(false),
      _sessionN(0),
      _hierLen(0)
{
    _session[0] = '\0';
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────

bool CogBluetooth::begin(const char* deviceName) {
    if (!BLE.begin()) {
        Serial.println("CogBluetooth: BLE init failed");
        return false;
    }
    BLE.setLocalName(deviceName);
    BLE.setAdvertisedService(_service);
    _service.addCharacteristic(_cmdChar);
    _service.addCharacteristic(_dataChar);
    BLE.addService(_service);
    _dataChar.writeValue("{\"status\":\"idle\"}");
    BLE.advertise();
    Serial.print("CogBluetooth: advertising as '");
    Serial.print(deviceName);
    Serial.println("'");
    return true;
}

bool CogBluetooth::isConnected() const {
    return (bool)BLE.central();
}

// ── poll() ────────────────────────────────────────────────────────────────────
// Call every loop() iteration.  Handles connection/disconnection and
// reads incoming commands.

void CogBluetooth::poll() {
    BLEDevice central = BLE.central();
    if (!central) return;

    // Process any pending command
    if (_cmdChar.written()) {
        String val = _cmdChar.value();
        val.trim();
        _handleCommand(val);
    }
}

// ── respond() ─────────────────────────────────────────────────────────────────

void CogBluetooth::respond(const String& json) {
    _dataChar.writeValue(json);
    Serial.println(json);
}

// ── runHierarchyTick() ────────────────────────────────────────────────────────
// One subsumption tick — check behaviours highest priority first,
// run the first whose condition is met, then return.

void CogBluetooth::runHierarchyTick(EthologyRobot& bot) {
    for (int i = 0; i < _hierLen; i++) {
        const char* name = _hier[i];

        if (strcmp(name, "escape_front") == 0) {
            if (bot.front_contact_met()) {
                bot.escape_front();
                return;
            }
        } else if (strcmp(name, "avoid_object") == 0) {
            if (bot.proximity_threshold_met()) {
                bot.avoid_object();
                return;
            }
        } else if (strcmp(name, "seek_light") == 0) {
            if (bot.light_gradient_met()) {
                bot.seek_light();
                return;
            }
        } else if (strcmp(name, "cruise_straight") == 0) {
            bot.cruise_straight();
            return;
        }
    }
}

// ── _handleCommand() ──────────────────────────────────────────────────────────

void CogBluetooth::_handleCommand(const String& raw) {
    String cmd = _jsonGet(raw, "cmd");
    Serial.print("BLE CMD: "); Serial.println(cmd);

    if (cmd == "ping") {
        if (_running)
            respond("{\"status\":\"busy\",\"session\":\"" + String(_session) + "\"}");
        else
            respond("{\"status\":\"idle\"}");

    } else if (cmd == "run") {
        if (_running) {
            respond("{\"status\":\"busy\",\"session\":\"" + String(_session) + "\"}");
            return;
        }
        if (!_parseHierarchy(raw)) {
            respond("{\"error\":\"missing or invalid hierarchy\"}");
            return;
        }
        _sessionN++;
        snprintf(_session, sizeof(_session), "%d", _sessionN);
        _running = true;
        Serial.print("RUN session="); Serial.println(_session);
        respond("{\"status\":\"running\",\"session\":\"" + String(_session) + "\"}");

    } else if (cmd == "stop") {
        String tok = _jsonGet(raw, "session");
        if (!_running) {
            respond("{\"ok\":true,\"note\":\"already idle\"}");
            return;
        }
        if (tok != String(_session)) {
            respond("{\"ok\":false,\"error\":\"invalid session\"}");
            return;
        }
        _running  = false;
        _hierLen  = 0;
        Serial.println("STOP");
        respond("{\"ok\":true}");

    } else if (cmd == "reset") {
        _running  = false;
        _hierLen  = 0;
        respond("{\"ok\":true,\"note\":\"reset\"}");

    } else {
        respond("{\"error\":\"unknown command\"}");
    }
}

// ── _parseHierarchy() ─────────────────────────────────────────────────────────

bool CogBluetooth::_parseHierarchy(const String& src) {
    int arrStart = src.indexOf("[");
    int arrEnd   = src.indexOf("]");
    if (arrStart < 0 || arrEnd <= arrStart) return false;

    String arr = src.substring(arrStart + 1, arrEnd);
    _hierLen = 0;
    int pos = 0;

    while (pos < (int)arr.length() && _hierLen < MAX_HIER) {
        int q1 = arr.indexOf('"', pos);
        if (q1 < 0) break;
        int q2 = arr.indexOf('"', q1 + 1);
        if (q2 < 0) break;
        String item = arr.substring(q1 + 1, q2);
        if (_validBehavior(item.c_str())) {
            item.toCharArray(_hier[_hierLen++], 32);
        }
        pos = q2 + 1;
    }
    return _hierLen > 0;
}

bool CogBluetooth::_validBehavior(const char* name) {
    for (int i = 0; i < N_BEHAVIORS; i++)
        if (strcmp(name, BEHAVIOR_NAMES[i]) == 0) return true;
    return false;
}

// ── _jsonGet() ────────────────────────────────────────────────────────────────

String CogBluetooth::_jsonGet(const String& src, const String& key) {
    String needle = "\"" + key + "\"";
    int ki = src.indexOf(needle);
    if (ki < 0) return "";
    int ci = src.indexOf(":", ki + needle.length());
    if (ci < 0) return "";
    ci++;
    while (ci < (int)src.length() && src[ci] == ' ') ci++;
    if (src[ci] == '"') {
        int end = src.indexOf('"', ci + 1);
        return (end < 0) ? "" : src.substring(ci + 1, end);
    }
    int end = ci;
    while (end < (int)src.length() &&
           src[end] != ',' && src[end] != '}') end++;
    return src.substring(ci, end);
}

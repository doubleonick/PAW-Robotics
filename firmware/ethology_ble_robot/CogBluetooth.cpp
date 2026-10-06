#include "CogBluetooth.h"

// NOTE: there is deliberately no behaviour-name table in this file.
// EthologyRobot owns the behaviour vocabulary; this class only moves
// strings between the host and the caller.

// ── Constructor ───────────────────────────────────────────────────────────────

CogBluetooth::CogBluetooth()
    : _service ("19B20000-E8F2-537E-4F6C-D104768A1214"),
      _cmdChar ("19B20001-E8F2-537E-4F6C-D104768A1214", BLEWrite, 256),
      _dataChar("19B20002-E8F2-537E-4F6C-D104768A1214", BLERead | BLENotify, 256),
      _started(false),
      _running(false),
      _sessionN(0),
      _catalog(nullptr),
      _catalogLen(0),
      _pending(false),
      _pendingLen(0)
{
    _session[0] = '\0';

    for (int i = 0; i < MAX_HIER; i++) {
        _pendingNames[i][0] = '\0';
        _pendingPtrs[i]     = _pendingNames[i];
    }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────

// ── Event handlers ────────────────────────────────────────────────────────────
// Registering these replaces per-loop state polling. The old arrangement asked
// "am I connected?" once per loop() and re-advertised from whichever state
// remembered to — and the Running state did not, so a robot that finished
// connecting became permanently undiscoverable and could never deliver its
// own "busy" reply. A disconnect handler cannot forget.

CogBluetooth* CogBluetooth::_self = nullptr;

void CogBluetooth::_onConnected(BLEDevice central) {
    Serial.print("BLE connected: ");
    Serial.println(central.address());
}

void CogBluetooth::_onDisconnected(BLEDevice central) {
    Serial.print("BLE disconnected: ");
    Serial.println(central.address());
    // ALWAYS resume advertising, in every state. One hierarchy per power
    // cycle is deliberate, but the robot must stay reachable to SAY so —
    // otherwise a second attempt sees nothing and cannot tell "already
    // running" from "flat battery".
    BLE.advertise();
}

void CogBluetooth::_onCmdWritten(BLEDevice central, BLECharacteristic ch) {
    if (_self == nullptr) return;
    String val = _self->_cmdChar.value();
    val.trim();
    _self->_handleCommand(val);
}

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

    // Event-driven from here: connect, disconnect and inbound writes are
    // delivered as callbacks rather than discovered by polling state.
    _self = this;
    BLE.setEventHandler(BLEConnected,    _onConnected);
    BLE.setEventHandler(BLEDisconnected, _onDisconnected);
    _cmdChar.setEventHandler(BLEWritten, _onCmdWritten);

    BLE.advertise();
    _started = true;
    Serial.print("CogBluetooth: advertising as '");
    Serial.print(deviceName);
    Serial.println("'");
    return true;
}

void CogBluetooth::setBehaviorCatalog(const char* const* names, int count) {
    _catalog    = names;
    _catalogLen = (names == nullptr) ? 0 : count;
}

bool CogBluetooth::isConnected() const {
    return (bool)BLE.central();
}

// ── poll() ────────────────────────────────────────────────────────────────────
// Call every loop() iteration.  Services the BLE stack and reads any
// incoming command.

void CogBluetooth::poll() {
    // Just service the stack. Commands arrive via _onCmdWritten and
    // connect/disconnect via their handlers, so there is nothing to inspect
    // here — which is the point: no state can forget to check something.
    //
    // ORIGINAL (polled):
    //     BLEDevice central = BLE.central();
    //     if (!central) return;
    //     if (_cmdChar.written()) {
    //         String val = _cmdChar.value();
    //         val.trim();
    //         _handleCommand(val);
    //     }
    if (!_started) return;
    BLE.poll();
}

// ── respond() ─────────────────────────────────────────────────────────────────

void CogBluetooth::respond(const String& json) {
    _dataChar.writeValue(json);
    Serial.println(json);
}

// ── Pending hierarchy ─────────────────────────────────────────────────────────

const char* CogBluetooth::pendingName(int i) const {
    if (i < 0 || i >= _pendingLen) return "";
    return _pendingNames[i];
}

void CogBluetooth::_clearPending() {
    _pending    = false;
    _pendingLen = 0;
}

void CogBluetooth::acceptHierarchy() {
    _sessionN++;
    snprintf(_session, sizeof(_session), "%d", _sessionN);
    _running = true;
    _clearPending();

    Serial.print("RUN session=");
    Serial.println(_session);

    respond("{\"status\":\"running\",\"session\":\"" + String(_session) + "\"}");
}

void CogBluetooth::rejectHierarchy(const char* reason) {
    _clearPending();

    Serial.print("REJECTED: ");
    Serial.println(reason);

    respond("{\"ok\":false,\"error\":\"" + String(reason) + "\"}");
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

    } else if (cmd == "behaviors") {
        // Let the host discover what this firmware can actually do, so it
        // does not have to maintain a second copy of the vocabulary.
        if (_catalog == nullptr || _catalogLen == 0) {
            respond("{\"error\":\"no behavior catalog\"}");
            return;
        }
        String out = "{\"behaviors\":[";
        for (int i = 0; i < _catalogLen; i++) {
            if (i > 0) out += ",";
            out += "\"";
            out += _catalog[i];
            out += "\"";
        }
        out += "]}";
        respond(out);

    } else if (cmd == "run") {
        // A run is a one-way door: no second hierarchy this power cycle.
        if (_running) {
            respond("{\"status\":\"busy\",\"session\":\"" + String(_session) + "\"}");
            return;
        }
        if (!_parseHierarchy(raw)) {
            respond("{\"error\":\"missing or invalid hierarchy\"}");
            return;
        }

        // Names are staged, not accepted.  The sketch validates them against
        // EthologyRobot's vocabulary and then calls acceptHierarchy() or
        // rejectHierarchy().  No response is sent here.
        _pending = true;

    } else if (cmd == "stop" || cmd == "reset") {
        // Reachable over the link, so answer it -- but never act on it.
        // The robot runs its hierarchy until power off, by design.
        if (_running) {
            respond("{\"ok\":false,\"error\":\"run in progress; power cycle to end\"}");
        } else {
            respond("{\"ok\":true,\"note\":\"already idle\"}");
        }

    } else {
        respond("{\"error\":\"unknown command\"}");
    }
}

// ── _parseHierarchy() ─────────────────────────────────────────────────────────
// Extracts every quoted string from the "hierarchy" array, in order.
// Unrecognised names are NOT filtered out here: dropping them silently
// would run a hierarchy the host never specified.  They are passed
// through so the caller can reject the whole request.

bool CogBluetooth::_parseHierarchy(const String& src) {
    int arrStart = src.indexOf("[");
    int arrEnd   = src.indexOf("]");
    if (arrStart < 0 || arrEnd <= arrStart) return false;

    String arr = src.substring(arrStart + 1, arrEnd);
    _pendingLen = 0;
    int pos = 0;

    while (pos < (int)arr.length() && _pendingLen < MAX_HIER) {
        int q1 = arr.indexOf('"', pos);
        if (q1 < 0) break;
        int q2 = arr.indexOf('"', q1 + 1);
        if (q2 < 0) break;

        String item = arr.substring(q1 + 1, q2);
        item.toCharArray(_pendingNames[_pendingLen], MAX_NAME);
        _pendingLen++;

        pos = q2 + 1;
    }
    return _pendingLen > 0;
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

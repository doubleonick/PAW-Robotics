#ifndef COGBLUETOOTH_H
#define COGBLUETOOTH_H

/*
  CogBluetooth.h
  --------------
  BLE GATT transport for the PAW Ethology robot.

  SCOPE — read this before adding anything to this class
  ------------------------------------------------------
  This class moves STRINGS between the host and the sketch. It owns the BLE
  service, both characteristics, and the session token. It owns NO behaviour
  vocabulary, no name table, and no hierarchy execution.

  EthologyRobot owns all of that: the Behavior enum, BEHAVIOR_NAMES,
  behaviorFromName(), setHierarchy() and hierarchy(). If you find yourself
  wanting a behaviour name in this file, put it in EthologyRobot instead and
  hand it here via setBehaviorCatalog().

  This is why the previous version of this header is incompatible: it stored
  a parsed hierarchy in _hier[] and executed it via runHierarchyTick(). That
  responsibility has moved. The members are gone, not renamed.

  THE HANDSHAKE
  -------------
  A "run" command does NOT start a run. Names are STAGED as pending, the
  sketch validates them against EthologyRobot's vocabulary, and only then is
  the request accepted or rejected. Nothing is half-installed:

      loop:
          ble.poll();
          if (ble.hasPendingHierarchy()) {
              int n   = ble.pendingCount();
              int bad = bot.setHierarchy(ble.pendingNames(), n);
              if (bad == EthologyRobot::HIERARCHY_OK) ble.acceptHierarchy();
              else ble.rejectHierarchy(reasonMentioning(ble.pendingName(bad)));
          }

  poll() sends no reply to "run" — acceptHierarchy() / rejectHierarchy() do.
  Forgetting to call one of them leaves the host waiting forever.

  Protocol (matches RobotBLEClient in engine/bluetooth/robot_bt_client.py)
  -----------------------------------------------------------------------
  Host -> Arduino (write to CMD characteristic):
      {"cmd":"ping"}
      {"cmd":"behaviors"}
      {"cmd":"run","hierarchy":["escape_front","avoid_object",...]}
      {"cmd":"stop","session":"1"}
      {"cmd":"reset"}

  Arduino -> Host (notify on DATA characteristic):
      {"status":"idle"}
      {"status":"running","session":"1"}
      {"status":"busy","session":"1"}
      {"behaviors":["escape_front",...]}
      {"ok":false,"error":"..."}
      {"error":"..."}

  A run is a ONE-WAY DOOR. "stop" and "reset" are answered so the link stays
  well-behaved, but they never end a run — the robot executes its hierarchy
  until power off, by design. Session tokens are an incrementing counter.

  BLE UUIDs (must match RobotBLEClient in engine/bluetooth/robot_bt_client.py)
  ---------------------------------------------------------------------------
  Service:   19B20000-E8F2-537E-4F6C-D104768A1214
  CMD char:  19B20001-E8F2-537E-4F6C-D104768A1214  (BLEWrite, 256 bytes)
  DATA char: 19B20002-E8F2-537E-4F6C-D104768A1214  (BLERead | BLENotify, 256)
*/

#include <Arduino.h>
#include <ArduinoBLE.h>

// NOTE: EthologyRobot.h is deliberately NOT included. This class never
// touches the robot — the sketch mediates. Keeping the include out is what
// stops behaviour knowledge leaking back in here.

class CogBluetooth {
public:
    // Maximum rungs in a hierarchy. Must be >= EthologyRobot::MAX_HIERARCHY,
    // or a hierarchy the robot could run would be truncated in transit.
    static const int MAX_HIER = 8;

    // Longest wire name, including the terminating NUL.
    static const int MAX_NAME = 32;

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    CogBluetooth();

    // Initialise BLE, set device name, start advertising. Call once from
    // setup(). Returns false if the BLE hardware is unavailable.
    // The sketch passes ROBOT_NAME (RobotA / RobotB); the default is
    // only a fallback.
    bool begin(const char* deviceName = "RobotA");

    // Hand this class the robot's behaviour vocabulary so a host can discover
    // it with {"cmd":"behaviors"} instead of keeping its own copy. Call from
    // setup() BEFORE begin(). The array is not copied — pass something with
    // static lifetime, e.g. EthologyRobot::behaviorCatalog().
    void setBehaviorCatalog(const char* const* names, int count);

    // Service the BLE stack. Must be called often — every loop() iteration,
    // AND from inside any long wait (see CogServo::setWaitTick), or events
    // will not fire while a motor primitive is holding.
    void poll();

    // True once begin() has succeeded, so a wait tick can safely poll.
    bool isStarted() const { return _started; }

    // ── State queries ─────────────────────────────────────────────────────────

    bool        isRunning()   const { return _running; }
    bool        isConnected() const;
    const char* session()     const { return _session; }

    // ── Pending hierarchy ─────────────────────────────────────────────────────
    // Set by a "run" command; cleared by accept/reject. See THE HANDSHAKE.

    // True when names are staged and awaiting validation by the sketch.
    bool hasPendingHierarchy() const { return _pending; }

    // How many names were staged.
    int pendingCount() const { return _pendingLen; }

    // The staged names, in priority order, for EthologyRobot::setHierarchy().
    // Valid until accept/reject. Entries beyond pendingCount() are empty.
    const char* const* pendingNames() const { return _pendingPtrs; }

    // One staged name by index, for building a rejection message.
    // Returns "" if out of range.
    const char* pendingName(int i) const;

    // The sketch installed the hierarchy: start a session, reply
    // {"status":"running","session":"N"}, and clear the pending state.
    void acceptHierarchy();

    // The sketch refused it: reply {"ok":false,"error":reason} and clear the
    // pending state. No session is started and no run begins.
    void rejectHierarchy(const char* reason);

    // ── Direct response helper (for sketch use) ───────────────────────────────

    void respond(const String& json);

private:
    // BLE objects
    BLEService                  _service;
    BLEStringCharacteristic     _cmdChar;
    BLEStringCharacteristic     _dataChar;

    // Event-driven plumbing. ArduinoBLE handlers are plain C function
    // pointers with no user data, so the single instance registers itself
    // here and the static thunks forward to it. One radio, one instance.
    static CogBluetooth* _self;
    static void _onConnected(BLEDevice central);
    static void _onDisconnected(BLEDevice central);
    static void _onCmdWritten(BLEDevice central, BLECharacteristic ch);

    bool    _started;

    // Session state
    bool    _running;
    int     _sessionN;
    char    _session[8];

    // Behaviour catalog, borrowed from EthologyRobot. Not owned, not copied.
    const char* const* _catalog;
    int                _catalogLen;

    // Staged hierarchy, awaiting the sketch's verdict.
    bool  _pending;
    int   _pendingLen;
    char  _pendingNames[MAX_HIER][MAX_NAME];

    // Stable pointers into _pendingNames, so pendingNames() can hand out a
    // const char* const* that EthologyRobot::setHierarchy() accepts directly.
    // Populated once in the constructor; never reseated.
    const char* _pendingPtrs[MAX_HIER];

    // ── Internal helpers ──────────────────────────────────────────────────────

    void _handleCommand(const String& raw);
    bool _parseHierarchy(const String& src);
    void _clearPending();

    // Minimal JSON string-value extractor (no library dependency)
    String _jsonGet(const String& src, const String& key);
};

#endif // COGBLUETOOTH_H

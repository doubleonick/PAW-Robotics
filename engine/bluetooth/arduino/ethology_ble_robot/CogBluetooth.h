#ifndef COGBLUETOOTH_H
#define COGBLUETOOTH_H

/*
  CogBluetooth.h
  --------------
  BLE GATT interface for the PAW Ethology robot.
  Follows the CogAnaDigi class pattern: one class, one resource,
  clean interface, fully encapsulated.

  The class owns the BLE service, both characteristics, the session
  token, and the stored hierarchy.  It also owns the hierarchy dispatch
  logic — the sketch loop is simply:

      ble.poll();
      if (ble.isRunning()) ble.runHierarchyTick(bot);

  Protocol (matches RobotBLEClient on the Python side)
  -----------------------------------------------------
  Host → Arduino (write to CMD characteristic):
      {"cmd":"ping"}
      {"cmd":"run","hierarchy":["escape_front","avoid_object",...]}
      {"cmd":"stop","session":"1"}
      {"cmd":"reset"}

  Arduino → Host (notify on DATA characteristic):
      {"status":"idle"}
      {"status":"running","session":"1"}
      {"status":"busy","session":"1"}
      {"ok":true}
      {"ok":false,"error":"invalid session"}
      {"error":"..."}

  Session tokens
  --------------
  An incrementing integer counter.  Each successful "run" command
  increments the counter and returns the new value as the session token.
  "stop" commands must carry the matching token.  Mismatched tokens are
  rejected, protecting against stale stop commands from a previous run.

  BLE UUIDs  (must match RobotBLEClient in engine/bluetooth/robot_bt_client.py)
  -------------------------------------------------------------------------------
  Service:  19B20000-E8F2-537E-4F6C-D104768A1214
  CMD char: 19B20001-E8F2-537E-4F6C-D104768A1214  (BLEWrite, 128 bytes)
  DATA char:19B20002-E8F2-537E-4F6C-D104768A1214  (BLERead | BLENotify, 128 bytes)
*/

#include <Arduino.h>
#include <ArduinoBLE.h>
#include "EthologyRobot.h"

class CogBluetooth {
public:
    // Maximum number of behaviours in a hierarchy
    static const int MAX_HIER = 8;

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    CogBluetooth();

    // Initialise BLE, set device name, start advertising.
    // Call once from setup().
    // Returns true on success, false if BLE hardware unavailable.
    bool begin(const char* deviceName = "PAW-Ethology");

    // Must be called every loop() iteration.
    // Handles connection events, reads incoming commands, updates state.
    void poll();

    // ── State queries ─────────────────────────────────────────────────────────

    // True while a "run" hierarchy is active.
    bool isRunning() const { return _running; }

    // True while a central is connected.
    bool isConnected() const;

    // Current session token string ("" if not running).
    const char* session() const { return _session; }

    // ── Hierarchy execution ───────────────────────────────────────────────────

    // Execute one tick of the stored hierarchy against bot.
    // Call this every loop() iteration when isRunning() is true.
    // The hierarchy is evaluated highest-priority-first; the first
    // behaviour whose condition is met runs its action and returns.
    void runHierarchyTick(EthologyRobot& bot);

    // ── Direct response helpers (for sketch use) ──────────────────────────────

    // Send a JSON string to the connected host via BLE notify.
    void respond(const String& json);

private:
    // BLE objects
    BLEService                  _service;
    BLEStringCharacteristic     _cmdChar;
    BLEStringCharacteristic     _dataChar;

    // Session state
    bool    _running;
    int     _sessionN;
    char    _session[8];

    // Stored hierarchy (received via "run" command)
    char    _hier[MAX_HIER][32];
    int     _hierLen;

    // ── Internal helpers ──────────────────────────────────────────────────────

    void _handleCommand(const String& raw);
    bool _parseHierarchy(const String& src);
    bool _validBehavior(const char* name);

    // Minimal JSON string-value extractor (no library dependency)
    String _jsonGet(const String& src, const String& key);
};

#endif // COGBLUETOOTH_H

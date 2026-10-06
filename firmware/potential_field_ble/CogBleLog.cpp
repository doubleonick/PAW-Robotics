#include "CogBleLog.h"

// Distinct UUIDs from the ethology robot's service (19B20000...) so a PC won't
// confuse the two. DATA characteristic is sized 128 bytes; actual delivered
// payload per notify is MTU-bounded (see header note).
static const char* PF_SERVICE_UUID = "19B21000-E8F2-537E-4F6C-D104768A1214";
static const char* PF_DATA_UUID    = "19B21002-E8F2-537E-4F6C-D104768A1214";

CogBleLog::CogBleLog()
: _service(PF_SERVICE_UUID),
  _dataChar(PF_DATA_UUID, BLERead | BLENotify, 128),
  _wasConnected(false) {}

bool CogBleLog::begin(const char* deviceName) {
    if (!BLE.begin()) {
        Serial.println("CogBleLog: BLE init failed");
        return false;
    }
    BLE.setLocalName(deviceName);
    BLE.setDeviceName(deviceName);
    BLE.setAdvertisedService(_service);
    _service.addCharacteristic(_dataChar);
    BLE.addService(_service);
    _dataChar.writeValue((const uint8_t*)"# ble-log ready\n", 16);
    BLE.advertise();
    Serial.print("CogBleLog: advertising as '");
    Serial.print(deviceName);
    Serial.println("'");
    return true;
}

void CogBleLog::poll() {
    // Mirror CogBluetooth's proven pattern: BLE.central() both services BLE
    // events and yields the connected central. We cache connection state so the
    // sketch can detect connect/disconnect edges.
    BLEDevice central = BLE.central();
    _wasConnected = (bool)central && central.connected();
}

bool CogBleLog::connected() const {
    return _wasConnected;
}

void CogBleLog::send(const String& line) {
    if (!_wasConnected) return;
    // Append newline so the host can split the stream into records.
    String out = line + "\n";
    int len = out.length();
    if (len > 128) len = 128;   // characteristic value cap
    _dataChar.writeValue((const uint8_t*)out.c_str(), len);
}

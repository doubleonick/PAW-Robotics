// Minimal ArduinoBLE stand-in for the offline link check.
//
// Declares only what CogBluetooth touches. This exists so CogBluetooth.cpp is
// compiled as a real translation unit against CogBluetooth.h, the same way
// CogDisplay.cpp is: a mismatch between the two is exactly the class of error
// that only shows up at link time.
//
// If a check fails here with "no member named X", ADD THE SIGNATURE TO THIS
// STUB. Do not change the firmware to avoid it.
#ifndef ARDUINOBLE_STUB_H
#define ARDUINOBLE_STUB_H

#include <Arduino.h>

enum BLEProperty {
    BLERead   = 0x02,
    BLEWrite  = 0x08,
    BLENotify = 0x10
};

class BLEDevice {
public:
    explicit operator bool() const { return _connected; }
    bool connected() const { return _connected; }
    String address() const { return String("00:00:00:00:00:00"); }
private:
    bool _connected = false;
};

typedef void (*BLEDeviceEventHandler)(BLEDevice);

enum BLEDeviceEvent {
    BLEConnected,
    BLEDisconnected
};

enum BLECharacteristicEvent {
    BLEWritten,
    BLESubscribed,
    BLEUnsubscribed
};

class BLECharacteristic;
typedef void (*BLECharacteristicEventHandler)(BLEDevice, BLECharacteristic);

class BLECharacteristic {
public:
    bool written() { return false; }
    void setEventHandler(BLECharacteristicEvent, BLECharacteristicEventHandler) {}
};

class BLEStringCharacteristic : public BLECharacteristic {
public:
    BLEStringCharacteristic(const char*, unsigned int, int) {}
    String value() { return String(""); }
    void writeValue(const String&) {}
};

class BLEService {
public:
    explicit BLEService(const char*) {}
    void addCharacteristic(BLECharacteristic&) {}
};

class BLELocalDeviceStub {
public:
    bool begin() { return true; }
    void poll() {}
    void setLocalName(const char*) {}
    void setAdvertisedService(BLEService&) {}
    void addService(BLEService&) {}
    void advertise() {}
    BLEDevice central() { return BLEDevice(); }
    void setEventHandler(BLEDeviceEvent, BLEDeviceEventHandler) {}
};

extern BLELocalDeviceStub BLE;

#endif // ARDUINOBLE_STUB_H

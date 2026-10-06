#ifndef COGBLELOG_H
#define COGBLELOG_H

/*
  CogBleLog.h
  -----------
  Lean BLE "data logger" for streaming text lines from the robot to a host
  (a PC running the pf_ble_logger.py receiver), so trials can be captured
  wirelessly instead of over a USB tether.

  This is intentionally MINIMAL — unlike CogBluetooth (which also receives
  commands and runs hierarchies), CogBleLog only does ONE thing: notify text
  lines out on a DATA characteristic. Same ArduinoBLE pattern the RE robot
  uses (proven on UNO R4 WiFi), same UUID scheme so the Python side is familiar.

  Usage in a sketch:
      CogBleLog blelog;
      void setup(){ ... blelog.begin("PAW-PField"); ... }
      void loop(){
          blelog.poll();                 // service BLE each tick
          ...
          if (blelog.connected()) blelog.send(csvLine);   // stream a line
      }

  BLE UUIDs (distinct service from the ethology robot so they don't collide):
    Service : 19B21000-E8F2-537E-4F6C-D104768A1214
    DATA    : 19B21002-E8F2-537E-4F6C-D104768A1214  (BLERead | BLENotify)

  NOTE on throughput: BLE notifications are MTU-limited. On Windows + bleak the
  negotiated MTU is usually large enough for a ~60-char line in one notify, but
  keep lines compact and DON'T stream every control tick — stream every few
  ticks (the sketch controls the rate). If lines are truncated on the host,
  either shorten them or lower the log rate.
*/

#include <Arduino.h>
#include <ArduinoBLE.h>

class CogBleLog {
public:
    CogBleLog();

    // Initialise BLE, advertise under deviceName. Call once in setup().
    // Returns false if BLE hardware is unavailable.
    bool begin(const char* deviceName = "PAW-PField");

    // Service BLE events. Call every loop() iteration.
    void poll();

    // True while a central (the PC receiver) is connected.
    bool connected() const;

    // Notify one text line to the host (if connected). A trailing '\n' is
    // added so the receiver can split a stream into lines.
    void send(const String& line);

private:
    BLEService              _service;
    BLECharacteristic       _dataChar;   // raw bytes, notify
    bool                    _wasConnected;
};

#endif // COGBLELOG_H

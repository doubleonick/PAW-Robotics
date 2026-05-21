/*
  ethology_ble_robot.ino
  ----------------------
  PAW Ethology robot sketch — BLE hierarchy dispatch.

  Based on ethologyPrototypeV2.ino.  BLE communication is fully
  encapsulated in CogBluetooth, following the same pattern as
  CogProximity, CogLight, etc.

  Files required in this sketch folder:
      ethology_ble_robot.ino   (this file)
      CogBluetooth.h / .cpp    (BLE encapsulation)
      EthologyRobot.h / .cpp   (robot behaviour)
      Robot.h / .cpp           (drivetrain base)
      CogServo.h / .cpp        (servo driver)
      CogProximity.h / .cpp    (IR sensors)
      CogLight.h / .cpp        (LDR sensors)
      CogCollision.h / .cpp    (bumper)
      CogAnaDigi.h / .cpp      (sensor base)

  Hardware
  --------
      D6   Left servo
      D5   Right servo
      A0   Left proximity  (leftProx)
      A1   Right proximity (rightProx)
      A2   Left light      (leftLight)
      A3   Right light     (rightLight)
      D4   Left front bumper  (INPUT_PULLUP)
      D2   Right front bumper (INPUT_PULLUP)

  Operation
  ---------
  1. Power on.  Board advertises as "PAW-Ethology".
  2. Python sends {"cmd":"run","hierarchy":["escape_front","cruise_straight"]}
  3. Robot executes the hierarchy each loop tick until stopped.
  4. Python sends {"cmd":"stop","session":"1"} to halt.
  5. On disconnect, motors stop and board re-advertises.
*/

#include "EthologyRobot.h"
#include "CogBluetooth.h"

constexpr uint8_t LEFT_SERVO_CHANNEL  = 6;
constexpr uint8_t RIGHT_SERVO_CHANNEL = 5;

EthologyRobot  bot;
CogBluetooth   ble;

// Track connection state to detect disconnect events
static bool _wasConnected = false;

void setup() {
    Serial.begin(9600);
    bot.begin(LEFT_SERVO_CHANNEL, RIGHT_SERVO_CHANNEL);

    if (!ble.begin("PAW-Ethology")) {
        // BLE hardware unavailable — spin forever with Serial error
        Serial.println("FATAL: BLE init failed");
        while (true) { delay(1000); }
    }
}

void loop() {
    bool connected = ble.isConnected();

    // Detect fresh disconnect — stop motors and re-advertise
    if (_wasConnected && !connected) {
        bot.driveProportional(0, 0, 0.4);   // reliable stop
        Serial.println("Disconnected — motors stopped, re-advertising");
        BLE.advertise();
    }
    _wasConnected = connected;

    // Process any incoming BLE commands
    ble.poll();

    // Execute one hierarchy tick if a run is active
    if (ble.isRunning()) {
        ble.runHierarchyTick(bot);
    }

    // Small yield keeps BLE stack responsive between ticks
    delay(20);
}

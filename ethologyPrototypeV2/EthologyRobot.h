#pragma once

#include "Robot.h"
#include <Adafruit_PWMServoDriver.h>

#include "CogProximity.h"
#include "CogLight.h"
#include "CogCollision.h"

class EthologyRobot : public Robot {
public:
    // ================================
    // Sensors
    // ================================
    CogProximity rightProx {"A1"};
    CogProximity leftProx  {"A0"};

    CogLight     rightLight {"A3"};
    CogLight     leftLight  {"A2"};

    CogCollision rightFrontBump {2};
    CogCollision leftFrontBump  {4};

    // ================================
    // Thresholds
    // ================================
    static constexpr int PROX_THRESHOLD  = 35;
    static constexpr int LIGHT_THRESHOLD = 15;
    static constexpr int COLL_THRESHOLD  = 1;

    // Cached sensor data
    int _lightGradient;
    int _leftFrontBumpData;
    int _rightFrontBumpData;

    // ================================
    // Constructors
    // ================================

    // Default: Servo.h drivetrain
    EthologyRobot();

    // PCA9685 / Adafruit PWM Servo Driver drivetrain
    explicit EthologyRobot(Adafruit_PWMServoDriver& pwm);

    // ================================
    // Sensor Threshold Checks
    // ================================
    bool proximityThreshold();
    bool lightGradientThreshold();
    bool collisionThreshold();

    // ================================
    // Object-Based Behaviors
    // ================================
    void avoidObject();
    void approachObject();

    // ================================
    // Light-Based Behaviors
    // ================================
    void avoidLight();
    void approachLight();

    // ================================
    // Collision-Based Behaviors
    // ================================
    void escapeFrontCollision();
    void escalateFrontCollision();

    // ================================
    // Cruise Behaviors
    // ================================
    void cruiseStraight();
    void cruiseLeftArc();
    void cruiseRightArc();

    // ================================
    // Behavior Hierarchy
    // ================================
    void hierarchy();
};
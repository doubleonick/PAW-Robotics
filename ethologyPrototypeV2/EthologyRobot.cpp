#include "EthologyRobot.h"
#include <cmath> // std::abs

// ================================
// Constructors
// ================================

// Servo.h mode
EthologyRobot::EthologyRobot()
: Robot() {
}

// PCA9685 / PWM driver mode
EthologyRobot::EthologyRobot(Adafruit_PWMServoDriver& pwm)
: Robot(pwm) {
}

// ================================
// Sensor Threshold Checks
// ================================
bool EthologyRobot::proximityThreshold() {
    return (rightProx.getData() <= PROX_THRESHOLD ||
            leftProx.getData()  <= PROX_THRESHOLD);
}

bool EthologyRobot::lightGradientThreshold() {
    _lightGradient = rightLight.getData() - leftLight.getData();
    return (abs(_lightGradient) >= LIGHT_THRESHOLD);
}

bool EthologyRobot::collisionThreshold() {
    bool thresholdMet = false;

    _leftFrontBumpData  = leftFrontBump.getData();
    _rightFrontBumpData = rightFrontBump.getData();

    if (_leftFrontBumpData == 0 || _rightFrontBumpData == 0) {
        thresholdMet = true;
    }

    return thresholdMet;
}

// ================================
// Object-Based Behaviors
// ================================
void EthologyRobot::avoidObject() {
    if (rightProx.getData() <= PROX_THRESHOLD) {
        // obstacle on right → steer left
        driveProportional(-40, 40, 0.5);
    }
    else if (leftProx.getData() <= PROX_THRESHOLD) {
        // obstacle on left → steer right
        driveProportional(40, -40, 0.5);
    }
}

void EthologyRobot::approachObject() {
    if (rightProx.getData() >= PROX_THRESHOLD) {
        driveProportional(40, 60, 0.1);
    }
    else if (leftProx.getData() >= PROX_THRESHOLD) {
        driveProportional(60, 40, 0.1);
    }
}

// ================================
// Light-Based Behaviors
// ================================
void EthologyRobot::avoidLight() {
    if (_lightGradient >= LIGHT_THRESHOLD) {
        driveProportional(-40, 40, 0.1);
    }
    else if (_lightGradient <= -LIGHT_THRESHOLD) {
        driveProportional(40, -40, 0.1);
    }
}

void EthologyRobot::approachLight() {
    if (_lightGradient >= LIGHT_THRESHOLD) {
        driveProportional(-40, 40, 0.5);
    }
    else if (_lightGradient <= -LIGHT_THRESHOLD) {
        driveProportional(40, -40, 0.5);
    }
}

// ================================
// Collision-Based Behaviors
// ================================
void EthologyRobot::escapeFrontCollision() {
    if (_leftFrontBumpData == 0) {
        driveProportional(100, -100, 1.0);
    }
    if (_rightFrontBumpData == 0) {
        driveProportional(-100, 100, 1.0);
    }
}

void EthologyRobot::escalateFrontCollision() {
    driveProportional(-50, -50, 0.2);
    driveProportional(100, 100, 0.1);
}

// ================================
// Cruise Behaviors
// ================================
void EthologyRobot::cruiseStraight() {
    driveProportional(60, 60, 0.1);
}

void EthologyRobot::cruiseLeftArc() {
    driveProportional(30, 50, 0.1);
}

void EthologyRobot::cruiseRightArc() {
    driveProportional(50, 30, 0.1);
}

// ================================
// Behavior Hierarchy
// ================================
void EthologyRobot::hierarchy() {
  // cruiseStraight();
    // if (collisionThreshold()) {
    //     escapeFrontCollision();
    // }
    // else if (proximityThreshold()) {
    //     avoidObject();
    // }
    // else 
    if (lightGradientThreshold()) {
        approachLight();
    }
    else {
        cruiseStraight();
    }
}
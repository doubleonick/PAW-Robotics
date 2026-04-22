#include "EthologyRobot.h"

constexpr uint8_t LEFT_SERVO_CHANNEL  = 6;
constexpr uint8_t RIGHT_SERVO_CHANNEL = 5;

Adafruit_PWMServoDriver pwm;
EthologyRobot bot;

void setup()
{
  Serial.begin(9600);
  bot.begin(LEFT_SERVO_CHANNEL, RIGHT_SERVO_CHANNEL);
}

void loop()
{
  bot.hierarchy();
}

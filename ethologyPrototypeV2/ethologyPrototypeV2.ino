#include "EthologyRobot.h"
// #include "CogAnaDigi.h"

// #include "CogProximity.h"
// #include "CogLight.h"

// CogProximity rightProx("A1");
// CogProximity leftProx("A0");
// CogLight     rightLight("A3");
// CogLight     leftLight("A2");

// Example usage with a labeled analog pin and a numeric digital pin
// CogAnaDigi analogSensor(A0);//DO I HAVE TO USE "A0", or will A0 do?
// CogAnaDigi digitalSensor(7);  // assumed DIGITAL by constructor

// Pick your actual PWM-capable pins for your Arduino board
constexpr uint8_t LEFT_SERVO_CHANNEL  = 6;
constexpr uint8_t RIGHT_SERVO_CHANNEL = 5;

Adafruit_PWMServoDriver pwm;
EthologyRobot bot;//pwm);

//EthologyRobot bot;//USE FOR Servo.h IMPLEMENTATION

// void rotateClockwise()
// {
//   for(int rate = 0; rate <=100; rate += 5)
//   {
//     bot.driveProportional(rate, -rate,  0.5);
//   }
// }

// void rotateAntiClockwise()
// {
//   for(int rate = 0; rate >= -100; rate -= 5)
//   {
//     bot.driveProportional(rate, -rate,  0.5);
//   }
// }

// void driveForward()
// {
//   for(int rate = 0; rate <=100; rate += 5)
//   {
//     bot.driveProportional(rate, rate,  0.5);
//   }
// }

// void driveBackward()
// {
//   for(int rate = 0; rate >= -100; rate -= 5)
//   {
//     bot.driveProportional(rate, rate,  0.5);
//   }
// }

void setup() 
{
  Serial.begin(9600);
  bot.begin(LEFT_SERVO_CHANNEL, RIGHT_SERVO_CHANNEL);
  // bot.halt(3.0);
}

void loop() 
{
  // for(int pos = -100; pos <= 100; pos ++)
  // {
  //   Serial.println(pos);
  //   bot.driveProportional(pos, pos, 0.5);
  // }
  // bot.driveProportional(95, -30, 1.0);
  // bot.driveProportional(0, 0, 1.0);
  // bot.halt(0.5);
  bot.hierarchy();
  Serial.print("rightProx is a ");
  Serial.print(bot.rightProx.getSensorType());
  Serial.print(" sensor....  ");
  Serial.print("It is connected to pin ");
  Serial.print(bot.rightProx.getPin());
  Serial.print(".  Right prox raw = ");
  Serial.print(bot.rightProx.getRawData());
  Serial.print(" data = ");
  Serial.println(bot.rightProx.getData());

  // Serial.print("leftProx is a ");
  // Serial.print(bot.leftProx.getSensorType());
  // Serial.print(" sensor....  ");
  // Serial.print("It is connected to pin ");
  // Serial.print(bot.leftProx.getPin());
  // Serial.print(".  left prox raw = ");
  // Serial.print(bot.leftProx.getRawData());
  // Serial.print(" data = ");
  // Serial.println(bot.leftProx.getData());
  // /*
  // if (bot.proximityThreshold()) {
  //   bot.avoidObject();
  // }
  // else*/ if (bot.collisionThreshold()){
  //   bot.escapeFrontCollision();
  // }/*
  // else if (bot.lightGradientThreshold()) {
  //   bot.approachLight();
  // }*/
  // else {
  //   bot.cruiseStraight();
  // }  
  //Sensor Examples
  // int a = analogSensor.getRawData();   // e.g., 0..1023 on many boards
  // int d = digitalSensor.getRawData();  // 0 or 1

  // Serial.print("Analog(A0): ");
  // Serial.print(a);
  // Serial.print("  Digital(7): ");
  // Serial.println(d);

  // delay(250);
  /************************************************/
  //Proximity and Light Sensor Examples
  // int rightProxRaw  = rightProx.getRawData();
  // int rightProxData = rightProx.getData();  // 10..80 after clamping 0..1000 and mapping
  // int leftProxRaw  = leftProx.getRawData();
  // int leftProxData = leftProx.getData();  // 10..80 after clamping 0..1000 and mapping

  // int rightLightRaw  = rightLight.getRawData();
  // int rightLightData = rightLight.getData(); // 0..100 mapped from 0..1023
  // int leftLightRaw  = leftLight.getRawData();
  // int leftLightData = leftLight.getData(); // 0..100 mapped from 0..1023

  // Serial.print("rightProx is a ");
  // Serial.print(rightProx.getSensorType());
  // Serial.print(" sensor....  ");
  // Serial.print("It is connected to pin ");
  // Serial.print(rightProx.getPin());
  // Serial.print(".  Right prox raw = ");
  // Serial.print(rightProxRaw);
  // Serial.print(" data = ");
  // Serial.println(rightProxData);

  // Serial.print("leftProx is a ");
  // Serial.print(leftProx.getSensorType());
  // Serial.print(" sensor....  ");
  // Serial.print("It is connected to pin ");
  // Serial.print(leftProx.getPin());
  // Serial.print(".  Left prox raw = ");
  // Serial.print(leftProxRaw);
  // Serial.print(" data = ");
  // Serial.println(leftProxData);

  // Serial.print("rightLight is a ");
  // Serial.print(rightLight.getSensorType());
  // Serial.print(" sensor....  ");
  // Serial.print("It is connected to pin ");
  // Serial.print(rightLight.getPin());
  // Serial.print(".  Right Light raw = ");
  // Serial.print(rightLightRaw);
  // Serial.print(" data = ");
  // Serial.println(rightLightData);

  // Serial.print("leftLight is a ");
  // Serial.print(leftLight.getSensorType());
  // Serial.print(" sensor....  ");
  // Serial.print("It is connected to pin ");
  // Serial.print(leftLight.getPin());
  // Serial.print(".  Left Light raw = ");
  // Serial.print(leftLightRaw);
  // Serial.print(" data = ");
  // Serial.println(leftLightData);

  // delay(1000);
  /************************************************/
  // //Servo Examples
  // Serial.println("rotateClockwise...");
  // rotateClockwise();
  // Serial.println("halt...");
  // bot.halt(3.0);
  // Serial.println("rotateAntiClockwise...");
  // rotateAntiClockwise();
  // Serial.println("halt...");
  // bot.halt(3.0);
  // Serial.println("driveFoward...");
  // driveForward();
  // Serial.println("halt...");
  // bot.halt(3.0);
  // Serial.println("driveBackward...");
  // driveBackward();
  // Serial.println("halt...");
  // bot.halt(3.0);
}
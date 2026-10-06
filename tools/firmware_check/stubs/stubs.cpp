#include "Arduino.h"
#include "Servo.h"
#include "Arduino_GigaDisplay_GFX.h"
SerialT Serial;
unsigned long millis(){return 0;} unsigned long micros(){return 0;}
void pinMode(int,int){} int digitalRead(int){return 1;} void digitalWrite(int,int){}
int analogRead(int){return 0;} void delay(unsigned long){} void randomSeed(unsigned long){}
long random(long a,long b){return a;} long random(long a){return 0;}
void SerialT::begin(int){} void SerialT::print(const char*){} void SerialT::print(int){}
void SerialT::print(float){} void SerialT::print(const String&){} void SerialT::println(const char*){}
void SerialT::println(int){} void SerialT::println(){} void SerialT::println(const String&){} int SerialT::available(){return 0;} int SerialT::read(){return -1;}
void Servo::attach(int){} void Servo::detach(){} void Servo::write(int){} void Servo::writeMicroseconds(int){} bool Servo::attached(){return true;}
void GigaDisplay_GFX::begin(){} void GigaDisplay_GFX::setRotation(uint8_t){}
void GigaDisplay_GFX::setTextWrap(bool){} void GigaDisplay_GFX::fillScreen(uint16_t){}
void GigaDisplay_GFX::fillRect(int16_t,int16_t,int16_t,int16_t,uint16_t){}
void GigaDisplay_GFX::drawFastHLine(int16_t,int16_t,int16_t,uint16_t){}
void GigaDisplay_GFX::setCursor(int16_t,int16_t){} void GigaDisplay_GFX::setTextSize(uint8_t){}
void GigaDisplay_GFX::setTextColor(uint16_t){} void GigaDisplay_GFX::print(const char*){} void GigaDisplay_GFX::print(int){}

// Added for the PAW-Robotics link check: overloads real Arduino provides.
void SerialT::print(float, int) {}
void SerialT::println(float, int) {}
void SerialT::print(double, int) {}
void SerialT::println(double, int) {}
void SerialT::print(unsigned long) {}
void SerialT::println(unsigned long) {}
void SerialT::print(long) {}
void SerialT::println(long) {}
void SerialT::print(unsigned int) {}
void SerialT::println(unsigned int) {}
void SerialT::print(char) {}
void SerialT::println(char) {}

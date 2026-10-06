#pragma once
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdio.h>
#include <math.h>
#include <string>
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define HIGH 1
#define LOW 0
#define A0 14
#define A1 15
#define A2 16
#define A3 17
#define A5 19
#define LED_BUILTIN 13
template<class T,class L,class H> T constrain(T v,L lo,H hi){return v<(T)lo?(T)lo:(v>(T)hi?(T)hi:v);}
template<class T> T map(T x,T a,T b,T c,T d){return (x-a)*(d-c)/(b-a)+c;}
struct String : std::string {
  String():std::string(){}
  String(const char* s):std::string(s?s:""){}
  String(const std::string& s):std::string(s){}
  String(int v){char b[24];snprintf(b,sizeof b,"%d",v);assign(b);}
  int indexOf(char c) const { auto p=find(c); return p==npos?-1:(int)p; }
  int indexOf(char c, unsigned int from) const { auto p=find(c, from); return p==npos?-1:(int)p; }
  int indexOf(const char* s, unsigned int from) const { auto p=find(s, from); return p==npos?-1:(int)p; }
  int indexOf(const String& s) const { auto p=find(s); return p==npos?-1:(int)p; }
  int indexOf(const String& s, unsigned int from) const { auto p=find(s, from); return p==npos?-1:(int)p; }
  void toCharArray(char* buf, unsigned int size) const {
      if (buf == nullptr || size == 0) { return; }
      unsigned int n = (unsigned int)this->size();
      if (n > size - 1) { n = size - 1; }
      for (unsigned int i = 0; i < n; i++) { buf[i] = (*this)[i]; }
      buf[n] = '\0';
  }
  int indexOf(const char* s) const { auto p=find(s); return p==npos?-1:(int)p; }
  String substring(int a) const { return String(substr(a)); }
  String substring(int a,int b) const { return String(substr(a,b-a)); }
  int toInt() const { return atoi(c_str()); }
  char charAt(int i) const { return (*this)[i]; }
  bool equals(const char* s) const { return *this==s; }
  bool startsWith(const char* s) const { return rfind(s,0)==0; }
  void trim() {}
  void toUpperCase() {}
};
unsigned long millis(); unsigned long micros();
void pinMode(int,int); int digitalRead(int); void digitalWrite(int,int);
int analogRead(int); void delay(unsigned long); void randomSeed(unsigned long);
long random(long,long); long random(long);
struct SerialT { void begin(int); void print(const char*); void print(int);
  void print(float); void print(const String&); void println(const char*);
  void println(int); void println(const String&); void println();
  // Real Arduino takes a decimal-places argument on the float overloads and
  // accepts the unsigned integer widths. Without these a sketch that prints a
  // float to 2 dp fails to compile here but is fine on hardware.
  void print(float, int); void println(float, int);
  void print(double, int); void println(double, int);
  void print(unsigned long); void println(unsigned long);
  void print(long); void println(long);
  void print(unsigned int); void println(unsigned int);
  void print(char); void println(char);
  int available(); int read(); operator bool(){return true;} };
extern SerialT Serial;

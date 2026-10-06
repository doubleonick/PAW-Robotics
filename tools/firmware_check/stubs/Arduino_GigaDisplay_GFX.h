#pragma once
#include <stdint.h>
class GigaDisplay_GFX {
public:
  void begin(); void setRotation(uint8_t); void setTextWrap(bool); void fillScreen(uint16_t);
  void fillRect(int16_t,int16_t,int16_t,int16_t,uint16_t);
  void drawFastHLine(int16_t,int16_t,int16_t,uint16_t);
  void setCursor(int16_t,int16_t); void setTextSize(uint8_t);
  void setTextColor(uint16_t); void print(const char*); void print(int);
};

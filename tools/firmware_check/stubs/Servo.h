#pragma once
class Servo { public: void attach(int); void detach(); void write(int); void writeMicroseconds(int); bool attached(); };

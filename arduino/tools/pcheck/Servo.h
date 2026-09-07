#ifndef PCHECK_SERVO_H
#define PCHECK_SERVO_H
#include <cstdint>
class Servo {
public:
  uint8_t attach(int) { return 0; }
  uint8_t attach(int, int, int) { return 0; }
  void detach() {}
  void write(int) {}
  void writeMicroseconds(int) {}
  int read() { return 0; }
  int readMicroseconds() { return 0; }
  bool attached() { return true; }
};
#endif

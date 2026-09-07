#ifndef PCHECK_STEPPER_H
#define PCHECK_STEPPER_H
class Stepper {
public:
  Stepper(int, int, int) {}
  Stepper(int, int, int, int, int) {}
  void setSpeed(long) {}
  void step(int) {}
  int version() { return 0; }
};
#endif

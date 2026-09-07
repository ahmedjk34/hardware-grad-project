// Minimal stub of the Arduino core, enough to `g++ -fsyntax-only` the
// build_test_v1 sketch on a desktop with no AVR toolchain.
//
// This proves the sketch PARSES and TYPE-CHECKS. It does NOT prove it builds
// for AVR and definitely not that it behaves. See AGENTS.md: "A clean compile
// is not a test."  Every path touching motion / limits / Z still has to be
// flashed and watched on the physical rig.
#ifndef PCHECK_ARDUINO_H
#define PCHECK_ARDUINO_H

#include <cstdint>
#include <cstddef>
#include <cmath>
#include <cstring>
#include <cstdlib>

typedef uint8_t byte;
typedef bool boolean;

#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define LSBFIRST 0
#define MSBFIRST 1
#define PROGMEM
#define DEC 10
#define HEX 16
#define OCT 8
#define BIN 2

// F() and the flash-string type. On real Arduino F("x") yields a
// __FlashStringHelper*; here it is just a const char* wearing that hat.
class __FlashStringHelper;
#define F(str) (reinterpret_cast<const __FlashStringHelper *>(str))
#define PSTR(str) (str)

template <typename T> T min(T a, T b) { return a < b ? a : b; }
template <typename T> T max(T a, T b) { return a > b ? a : b; }
template <typename T> T abs(T a) { return a < 0 ? -a : a; }
template <typename T> T constrain(T x, T lo, T hi) { return x < lo ? lo : (x > hi ? hi : x); }
inline long map(long x, long a, long b, long c, long d) {
  return (x - a) * (d - c) / (b - a) + c;
}
inline unsigned int word(unsigned char h, unsigned char l) {
  return (unsigned int)h << 8 | l;
}

inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t, uint8_t) {}
inline int digitalRead(uint8_t) { return LOW; }
inline int analogRead(uint8_t) { return 0; }
inline void analogWrite(uint8_t, int) {}
inline unsigned long millis() { return 0; }
inline unsigned long micros() { return 0; }
inline void delay(unsigned long) {}
inline void delayMicroseconds(unsigned int) {}
inline uint8_t digitalPinToInterrupt(uint8_t p) { return p; }
inline void attachInterrupt(uint8_t, void (*)(), int) {}
inline void detachInterrupt(uint8_t) {}
inline void interrupts() {}
inline void noInterrupts() {}
#define CHANGE 1
#define FALLING 2
#define RISING 3

struct SerialStub {
  void begin(long) {}
  void end() {}
  int available() { return 0; }
  int read() { return -1; }
  int peek() { return -1; }
  void flush() {}
  operator bool() const { return true; }
  size_t print(const char *) { return 0; }
  size_t print(char) { return 0; }
  size_t print(int, int = DEC) { return 0; }
  size_t print(unsigned int, int = DEC) { return 0; }
  size_t print(long, int = DEC) { return 0; }
  size_t print(unsigned long, int = DEC) { return 0; }
  size_t print(double, int = 2) { return 0; }
  size_t print(const __FlashStringHelper *) { return 0; }
  size_t println(const char *) { return 0; }
  size_t println(char) { return 0; }
  size_t println(int, int = DEC) { return 0; }
  size_t println(unsigned int, int = DEC) { return 0; }
  size_t println(long, int = DEC) { return 0; }
  size_t println(unsigned long, int = DEC) { return 0; }
  size_t println(double, int = 2) { return 0; }
  size_t println(const __FlashStringHelper *) { return 0; }
  size_t println() { return 0; }
  size_t write(uint8_t) { return 0; }
};
extern SerialStub Serial;

// The sketch declares its own `extern int __heap_start; extern int *__brkval;`
// for freeRam(); -fsyntax-only never links, so nothing more is needed here.

// The sketch's own entry points.
void setup();
void loop();

#endif

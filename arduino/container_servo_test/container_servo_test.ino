#include <Servo.h>

// Servo signal pins, in the order they will be tested.
const uint8_t SERVO_PINS[] = {2, 3, 4};
const uint8_t SERVO_COUNT = sizeof(SERVO_PINS) / sizeof(SERVO_PINS[0]);

// Adjust these two angles to match the mechanical containers.
const uint8_t SERVO_CLOSED_ANGLE = 0;
const uint8_t SERVO_OPEN_ANGLE = 30;

const unsigned long OPEN_TIME_MS = 2000;

Servo servos[SERVO_COUNT];

void closeAllServos()
{
  for (uint8_t i = 0; i < SERVO_COUNT; i++) {
    servos[i].write(SERVO_CLOSED_ANGLE);
  }
}

void setup()
{
  Serial.begin(9600);

  for (uint8_t i = 0; i < SERVO_COUNT; i++) {
    servos[i].attach(SERVO_PINS[i]);
  }

  closeAllServos();
  delay(500);
  Serial.println(F("Container servo test started"));
}

void loop()
{
  for (uint8_t i = 0; i < SERVO_COUNT; i++) {
    Serial.print(F("Opening servo on pin "));
    Serial.println(SERVO_PINS[i]);

    servos[i].write(SERVO_OPEN_ANGLE);
    delay(OPEN_TIME_MS);

    servos[i].write(SERVO_CLOSED_ANGLE);
    Serial.print(F("Closing servo on pin "));
    Serial.println(SERVO_PINS[i]);
  }
}

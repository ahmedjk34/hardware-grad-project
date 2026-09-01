// Container + belt controller for an Arduino Mega 2560.
//
// Opening the container arms the ultrasonic sensor. When a block is detected
// closer than 10 cm, the belt runs counter-clockwise for five seconds.
//
// Default wiring:
//   A4988 DIR  = 2, STEP = 3
//   Ultrasonic: TRIG = 4, ECHO = 5
//   Container servo signal = 6

#include <Arduino.h>
#include <Servo.h>

// Change these pin variables if the wiring changes.
uint8_t stepPin = 3;
uint8_t dirPin = 2;
uint8_t trigPin1 = 4;
uint8_t echoPin1 = 5;
uint8_t servoPin = 6;

const uint8_t SERVO_CLOSE_ANGLE = 20;
const uint8_t SERVO_OPEN_ANGLE = 140;
const unsigned long BELT_RUN_TIME_MS = 5000;
// Flip this if the installed belt turns clockwise with LOW.
const uint8_t BELT_CCW_DIRECTION_LEVEL = LOW;

Servo containerServo;

// Runtime settings.
unsigned long stepDelayUs = 2000;  // delay between motor steps
const float detectDistanceCm = 10.0; // block is detected strictly below this
unsigned long sensorIntervalMs = 100;

bool beltRunning = false;
bool containerOpen = false;
bool sensorArmed = false;
bool blockTriggered = false;

float distance1Cm = -1.0;
bool sensor1Detected = false;
unsigned long lastSensorReadMs = 0;

float readDistanceCm(uint8_t trigPin, uint8_t echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  unsigned long duration = pulseIn(echoPin, HIGH, 30000);
  if (duration == 0) {
    return -1.0;
  }

  return duration * 0.0343 / 2.0;
}

bool objectDetected(float distanceCm) {
  return distanceCm >= 0.0 && distanceCm < detectDistanceCm;
}

void stopBelt() {
  beltRunning = false;
  digitalWrite(stepPin, LOW);
}

void runBeltCounterClockwiseForFiveSeconds() {
  Serial.println(F("BLOCK detected (<10 cm) -> BELT CCW for 5 seconds"));
  beltRunning = true;
  unsigned long startedAt = millis();
  digitalWrite(dirPin, BELT_CCW_DIRECTION_LEVEL);

  while (millis() - startedAt < BELT_RUN_TIME_MS) {
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(5);
    digitalWrite(stepPin, LOW);
    delayMicroseconds(stepDelayUs);
  }

  stopBelt();
  Serial.println(F("BELT STOPPED after 5 seconds"));
}

void updateSensors() {
  if (!containerOpen || !sensorArmed || blockTriggered ||
      millis() - lastSensorReadMs < sensorIntervalMs) {
    return;
  }
  lastSensorReadMs = millis();

  distance1Cm = readDistanceCm(trigPin1, echoPin1);
  sensor1Detected = objectDetected(distance1Cm);
  if (sensor1Detected) {
    blockTriggered = true;
    sensorArmed = false;
    runBeltCounterClockwiseForFiveSeconds();
  }
}

void printDistance(const char *name, float distanceCm, bool detected) {
  Serial.print(name);
  Serial.print(F(": "));
  if (distanceCm < 0.0) {
    Serial.print(F("NO ECHO"));
  } else {
    Serial.print(distanceCm, 1);
    Serial.print(F(" cm"));
  }
  Serial.print(F(" | "));
  Serial.println(detected ? F("DETECT OBJECT") : F("NOT DETECT OBJECT"));
}

void printStatus() {
  Serial.println(F("--- STATUS ---"));
  Serial.print(F("Belt: "));
  Serial.println(beltRunning ? F("RUNNING") : F("STOPPED"));
  Serial.print(F("Container: "));
  Serial.println(containerOpen ? F("OPEN (140 deg)") : F("CLOSED (20 deg)"));
  Serial.print(F("Ultrasonic armed: "));
  Serial.println(sensorArmed ? F("YES") : F("NO"));
  Serial.print(F("Step delay: "));
  Serial.print(stepDelayUs);
  Serial.println(F(" us"));
  printDistance("US1", distance1Cm, sensor1Detected);
}

void printHelp() {
  Serial.println(F("D <us>       change step delay; example: D 2000"));
  Serial.println(F("I <ms>       change ultrasonic read interval"));
  Serial.println(F("O            open container (140 deg) and arm ultrasonic"));
  Serial.println(F("C            close container (20 deg) and stop belt"));
  Serial.println(F("F            manual belt direction test"));
  Serial.println(F("R            manual belt CCW test"));
  Serial.println(F("X            stop belt"));
  Serial.println(F("S            print status and distances"));
  Serial.println(F("H            print this help"));
}

void readSerialCommand() {
  if (!Serial.available()) {
    return;
  }

  char command = Serial.read();

  if (command == 'D' || command == 'd') {
    delay(5);
    unsigned long value = Serial.parseInt();
    if (value >= 20 && value <= 1000000) {
      stepDelayUs = value;
      Serial.print(F("Step delay: "));
      Serial.print(stepDelayUs);
      Serial.println(F(" us"));
    }
  } else if (command == 'I' || command == 'i') {
    delay(5);
    unsigned long value = Serial.parseInt();
    if (value >= 20 && value <= 60000) {
      sensorIntervalMs = value;
      Serial.println(F("Sensor interval updated."));
    }
  } else if (command == 'F' || command == 'f') {
    digitalWrite(dirPin, HIGH);
    beltRunning = true;
    Serial.println(F("BELT RUNNING (manual direction HIGH)"));
  } else if (command == 'R' || command == 'r') {
    digitalWrite(dirPin, BELT_CCW_DIRECTION_LEVEL);
    beltRunning = true;
    Serial.println(F("BELT RUNNING CCW (manual)"));
  } else if (command == 'X' || command == 'x') {
    stopBelt();
    Serial.println(F("BELT STOPPED"));
  } else if (command == 'O' || command == 'o') {
    stopBelt();
    containerServo.write(SERVO_OPEN_ANGLE);
    containerOpen = true;
    sensorArmed = true;
    blockTriggered = false;
    sensor1Detected = false;
    Serial.println(F("CONTAINER OPEN (140 deg); ultrasonic armed"));
  } else if (command == 'C' || command == 'c') {
    stopBelt();
    containerServo.write(SERVO_CLOSE_ANGLE);
    containerOpen = false;
    sensorArmed = false;
    blockTriggered = false;
    sensor1Detected = false;
    Serial.println(F("CONTAINER CLOSED (20 deg)"));
  } else if (command == 'S' || command == 's') {
    printStatus();
  } else if (command == 'H' || command == 'h' || command == '?') {
    printHelp();
  }
}

void setup() {
  pinMode(stepPin, OUTPUT);
  pinMode(dirPin, OUTPUT);
  pinMode(trigPin1, OUTPUT);
  pinMode(echoPin1, INPUT);

  digitalWrite(stepPin, LOW);
  digitalWrite(trigPin1, LOW);

  containerServo.attach(servoPin);
  containerServo.write(SERVO_CLOSE_ANGLE);

  Serial.begin(9600);
  Serial.println(F("CONTAINER + BELT READY - servo 6, US (4/5), belt DIR/STEP (2/3)"));
  printHelp();
}

void loop() {
  readSerialCommand();
  updateSensors();

  if (beltRunning) {
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(5);
    digitalWrite(stepPin, LOW);
    delayMicroseconds(stepDelayUs);
  }
}

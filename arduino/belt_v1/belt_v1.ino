// Simple belt controller for an Arduino Mega 2560.
//
// Ultrasonic 1 detects an object -> start the belt.
// Ultrasonic 2 detects an object -> stop the belt.
//
// Default wiring:
//   A4988 DIR  = 2, STEP = 3
//   Ultrasonic 1: TRIG = 4, ECHO = 5
//   Ultrasonic 2: TRIG = 6, ECHO = 7

#include <Arduino.h>

// Change these pin variables if the wiring changes.
uint8_t stepPin = 3;
uint8_t dirPin = 2;
uint8_t trigPin1 = 4;
uint8_t echoPin1 = 5;
uint8_t trigPin2 = 6;
uint8_t echoPin2 = 7;

// Runtime settings.
unsigned long stepDelayUs = 2000;  // delay between motor steps
float detectDistanceCm = 20.0;     // object is detected below this distance
unsigned long sensorIntervalMs = 100;

bool beltRunning = false;
bool forward = true;
bool automaticMode = true;
bool readyForSensor1 = true;

float distance1Cm = -1.0;
float distance2Cm = -1.0;
bool sensor1Detected = false;
bool sensor2Detected = false;
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
  return distanceCm >= 0.0 && distanceCm <= detectDistanceCm;
}

void updateSensors() {
  if (millis() - lastSensorReadMs < sensorIntervalMs) {
    return;
  }
  lastSensorReadMs = millis();

  distance1Cm = readDistanceCm(trigPin1, echoPin1);
  distance2Cm = readDistanceCm(trigPin2, echoPin2);
  bool oldSensor1Detected = sensor1Detected;
  sensor1Detected = objectDetected(distance1Cm);
  sensor2Detected = objectDetected(distance2Cm);

  if (!automaticMode) {
    return;
  }

  // Sensor 2 always has priority and stops the belt.
  if (sensor2Detected) {
    if (beltRunning) {
      beltRunning = false;
      Serial.println(F("US2 detected object -> BELT STOPPED"));
    }
    readyForSensor1 = false;
    return;
  }

  // Require both sensors to clear before accepting the next object.
  if (!sensor1Detected && !sensor2Detected) {
    readyForSensor1 = true;
  }

  // Start only when US1 changes from clear to detected.
  if (readyForSensor1 && sensor1Detected && !oldSensor1Detected) {
    beltRunning = true;
    readyForSensor1 = false;
    Serial.println(F("US1 detected object -> BELT STARTED"));
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
  Serial.print(F("Direction: "));
  Serial.println(forward ? F("FORWARD") : F("REVERSE"));
  Serial.print(F("Step delay: "));
  Serial.print(stepDelayUs);
  Serial.println(F(" us"));
  Serial.print(F("Automatic mode: "));
  Serial.println(automaticMode ? F("ON") : F("OFF"));
  printDistance("US1", distance1Cm, sensor1Detected);
  printDistance("US2", distance2Cm, sensor2Detected);
}

void printHelp() {
  Serial.println(F("D <us>       change step delay; example: D 2000"));
  Serial.println(F("T <cm>       change detection threshold"));
  Serial.println(F("I <ms>       change ultrasonic read interval"));
  Serial.println(F("F            run forward"));
  Serial.println(F("R            run reverse"));
  Serial.println(F("X            stop belt"));
  Serial.println(F("A ON/OFF      automatic US1-start / US2-stop mode"));
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
  } else if (command == 'T' || command == 't') {
    delay(5);
    float value = Serial.parseFloat();
    if (value > 0 && value <= 400) {
      detectDistanceCm = value;
      Serial.println(F("Detection threshold updated."));
    }
  } else if (command == 'I' || command == 'i') {
    delay(5);
    unsigned long value = Serial.parseInt();
    if (value >= 20 && value <= 60000) {
      sensorIntervalMs = value;
      Serial.println(F("Sensor interval updated."));
    }
  } else if (command == 'F' || command == 'f') {
    forward = true;
    beltRunning = true;
    Serial.println(F("BELT RUNNING FORWARD"));
  } else if (command == 'R' || command == 'r') {
    forward = false;
    beltRunning = true;
    Serial.println(F("BELT RUNNING REVERSE"));
  } else if (command == 'X' || command == 'x') {
    beltRunning = false;
    Serial.println(F("BELT STOPPED"));
  } else if (command == 'A' || command == 'a') {
    delay(5);
    while (Serial.available() &&
           (Serial.peek() == ' ' || Serial.peek() == '\t')) {
      Serial.read();
    }

    char first = Serial.read();
    while (Serial.available() &&
           (Serial.peek() == ' ' || Serial.peek() == '\t')) {
      Serial.read();
    }
    char second = Serial.read();

    if ((first == 'O' || first == 'o') &&
        (second == 'N' || second == 'n')) {
      automaticMode = true;
      beltRunning = false;
      readyForSensor1 = true;
      Serial.println(F("AUTOMATIC MODE ON; waiting for US1"));
    } else if ((first == 'O' || first == 'o') &&
               (second == 'F' || second == 'f')) {
      automaticMode = false;
      Serial.println(F("AUTOMATIC MODE OFF"));
    } else {
      Serial.println(F("Use A ON or A OFF"));
    }
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
  pinMode(trigPin2, OUTPUT);
  pinMode(echoPin2, INPUT);

  digitalWrite(stepPin, LOW);
  digitalWrite(trigPin1, LOW);
  digitalWrite(trigPin2, LOW);

  Serial.begin(9600);
  Serial.println(F("BELT V1 READY - US1 (4/5) starts, US2 (6/7) stops"));
  printHelp();
}

void loop() {
  readSerialCommand();
  updateSensors();

  if (beltRunning) {
    digitalWrite(dirPin, forward ? HIGH : LOW);
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(5);
    digitalWrite(stepPin, LOW);
    delayMicroseconds(stepDelayUs);
  }
}

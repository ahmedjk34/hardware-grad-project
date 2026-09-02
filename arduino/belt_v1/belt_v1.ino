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

// A4988 wiring: STEP = 3, DIR = 2. ENABLE is not used; tie it to GND.
uint8_t stepPin = 3;
uint8_t dirPin = 2;
uint8_t trigPin1 = 4;
uint8_t echoPin1 = 5;
uint8_t servoPin = 6;

const uint8_t SERVO_CLOSE_ANGLE = 20;
const uint8_t SERVO_OPEN_ANGLE = 0;
const unsigned long BELT_RUN_TIME_MS = 5000;
// Flip this if the installed belt turns clockwise with LOW.
const uint8_t BELT_CCW_DIRECTION_LEVEL = LOW;

Servo containerServo;

// Runtime settings.
int motorSpeed = 200;  // default speed in steps per second
unsigned long stepIntervalUs = 5000;
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

void setMotorSpeed(int speed) {
  motorSpeed = constrain(speed, 10, 3000);
  stepIntervalUs = 1000000UL / motorSpeed;

  Serial.print(F("Speed: "));
  Serial.print(motorSpeed);
  Serial.println(F(" steps/second"));
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
    delayMicroseconds(stepIntervalUs);
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
  Serial.println(containerOpen ? F("OPEN (0 deg)") : F("CLOSED (20 deg)"));
  Serial.print(F("Ultrasonic armed: "));
  Serial.println(sensorArmed ? F("YES") : F("NO"));
  Serial.print(F("Speed: "));
  Serial.print(motorSpeed);
  Serial.println(F(" steps/second"));
  printDistance("US1", distance1Cm, sensor1Detected);
}

void printHelp() {
  Serial.println(F("S <speed>    change speed; example: S 500"));
  Serial.println(F("I <ms>       change ultrasonic read interval"));
  Serial.println(F("O            open container (0 deg) and arm ultrasonic"));
  Serial.println(F("C            close container (20 deg) and stop belt"));
  Serial.println(F("ON           start belt"));
  Serial.println(F("OFF          stop belt"));
  Serial.println(F("F            run belt forward"));
  Serial.println(F("B            run belt backward"));
  Serial.println(F("T            toggle direction and run"));
  Serial.println(F("X            stop belt (alias for OFF)"));
  Serial.println(F("P            print status and distances"));
  Serial.println(F("H            print this help"));
}

void readSerialCommand() {
  if (!Serial.available()) {
    return;
  }

  String command = Serial.readStringUntil('\n');
  command.trim();
  command.toUpperCase();

  if (command.startsWith("S ")) {
    setMotorSpeed(command.substring(2).toInt());
  } else if (command.startsWith("I ")) {
    unsigned long value = command.substring(2).toInt();
    if (value >= 20 && value <= 60000) {
      sensorIntervalMs = value;
      Serial.println(F("Sensor interval updated."));
    }
  } else if (command == "ON") {
    beltRunning = true;
    Serial.println(F("BELT RUNNING"));
  } else if (command == "OFF" || command == "X") {
    stopBelt();
    Serial.println(F("BELT STOPPED"));
  } else if (command == "F") {
    digitalWrite(dirPin, HIGH);
    beltRunning = true;
    Serial.println(F("BELT RUNNING FORWARD"));
  } else if (command == "B" || command == "R") {
    digitalWrite(dirPin, BELT_CCW_DIRECTION_LEVEL);
    beltRunning = true;
    Serial.println(F("BELT RUNNING BACKWARD"));
  } else if (command == "T") {
    digitalWrite(dirPin, digitalRead(dirPin) == HIGH ? BELT_CCW_DIRECTION_LEVEL : HIGH);
    beltRunning = true;
    Serial.println(F("BELT DIRECTION TOGGLED"));
  } else if (command == "O") {
    stopBelt();
    containerServo.write(SERVO_OPEN_ANGLE);
    containerOpen = true;
    sensorArmed = true;
    blockTriggered = false;
    sensor1Detected = false;
    Serial.println(F("CONTAINER OPEN (0 deg); ultrasonic armed"));
  } else if (command == "C") {
    stopBelt();
    containerServo.write(SERVO_CLOSE_ANGLE);
    containerOpen = false;
    sensorArmed = false;
    blockTriggered = false;
    sensor1Detected = false;
    Serial.println(F("CONTAINER CLOSED (20 deg)"));
  } else if (command == "P") {
    printStatus();
  } else if (command == "H" || command == "?") {
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
    delayMicroseconds(stepIntervalUs);
  }
}

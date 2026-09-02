// Container + belt controller for an Arduino Mega 2560.
//
// RUN performs a complete cycle: close, open, detect a block, then run the
// belt for ten seconds.
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
const uint8_t SERVO_OPEN_ANGLE = 140;
const unsigned long BELT_RUN_TIME_MS = 10000;
const unsigned long RUN_CLOSE_SETTLE_MS = 500;
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
bool fullRunMode = false;
bool timedBeltRun = false;
unsigned long beltStopAtMs = 0;
unsigned long fullRunOpenAtMs = 0;

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
  timedBeltRun = false;
  digitalWrite(stepPin, LOW);
}

void cancelFullRun() {
  fullRunMode = false;
  sensorArmed = false;
}

void openContainer(bool armSensor) {
  containerServo.write(SERVO_OPEN_ANGLE);
  containerOpen = true;
  sensorArmed = armSensor;
  blockTriggered = false;
  sensor1Detected = false;
  Serial.println(armSensor ? F("CONTAINER OPEN (140 deg); ultrasonic armed")
                           : F("CONTAINER OPEN (140 deg)"));
}

void closeContainer() {
  stopBelt();
  containerServo.write(SERVO_CLOSE_ANGLE);
  containerOpen = false;
  sensorArmed = false;
  blockTriggered = false;
  sensor1Detected = false;
  Serial.println(F("CONTAINER CLOSED (20 deg)"));
}

void startFullRun() {
  stopBelt();
  fullRunMode = true;
  closeContainer();
  fullRunOpenAtMs = millis() + RUN_CLOSE_SETTLE_MS;
  Serial.println(F("FULL RUN: closed; opening in 500 ms"));
}

void updateFullRun() {
  if (!fullRunMode || containerOpen || millis() < fullRunOpenAtMs) {
    return;
  }

  openContainer(true);
  Serial.println(F("FULL RUN: waiting for object below 10 cm"));
}

void updateTimedBeltRun() {
  if (!timedBeltRun || millis() < beltStopAtMs) {
    return;
  }

  timedBeltRun = false;
  stopBelt();
  if (fullRunMode) {
    fullRunMode = false;
    sensorArmed = false;
    Serial.println(F("FULL RUN COMPLETE"));
  }
  Serial.println(F("BELT STOPPED after 10 seconds"));
}

void setMotorSpeed(int speed) {
  motorSpeed = constrain(speed, 10, 3000);
  stepIntervalUs = 1000000UL / motorSpeed;

  Serial.print(F("Speed: "));
  Serial.print(motorSpeed);
  Serial.println(F(" steps/second"));
}

void runBeltCounterClockwiseForTenSeconds() {
  Serial.println(F("BLOCK detected (<10 cm) -> BELT CCW for 10 seconds"));
  beltRunning = true;
  timedBeltRun = true;
  beltStopAtMs = millis() + BELT_RUN_TIME_MS;
  digitalWrite(dirPin, BELT_CCW_DIRECTION_LEVEL);
}

void updateSensors() {
  // Sensor-triggered belt movement is part of RUN only. Manual motor
  // commands (ON/F/B) run continuously and are never changed by the sensor.
  if (!fullRunMode || !containerOpen || !sensorArmed || blockTriggered ||
      millis() - lastSensorReadMs < sensorIntervalMs) {
    return;
  }
  lastSensorReadMs = millis();

  distance1Cm = readDistanceCm(trigPin1, echoPin1);
  sensor1Detected = objectDetected(distance1Cm);
  if (sensor1Detected) {
    blockTriggered = true;
    sensorArmed = false;
    runBeltCounterClockwiseForTenSeconds();
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
  Serial.print(F("Full run: "));
  Serial.println(fullRunMode ? F("ACTIVE") : F("OFF"));
  Serial.print(F("Ultrasonic armed: "));
  Serial.println(sensorArmed ? F("YES") : F("NO"));
  Serial.print(F("Speed: "));
  Serial.print(motorSpeed);
  Serial.println(F(" steps/second"));
  printDistance("US1", distance1Cm, sensor1Detected);
}

void printHelp() {
  Serial.println();
  Serial.println(F("=================================================="));
  Serial.println(F("              BELT TEST V1 MENU"));
  Serial.println(F("=================================================="));
  Serial.println(F("WIRING: A4988 STEP = D3 | DIR = D2 | ENABLE = GND"));
  Serial.println(F("DEFAULT MOTOR SPEED: 200 steps/second"));
  Serial.println();
  Serial.println(F("[FULL AUTOMATIC TEST]"));
  Serial.println(F("  RUN              Complete test cycle"));
  Serial.println(F("                   Close 20 deg -> Open 140 deg"));
  Serial.println(F("                   Detect object -> Run belt 10 sec"));
  Serial.println();
  Serial.println(F("[SERVO / CONTAINER CONTROL]"));
  Serial.println(F("  OPEN             Open servo to 140 deg  [O]"));
  Serial.println(F("  CLOSE            Close servo to 20 deg  [C]"));
  Serial.println(F("  ANGLE 90         Move servo to custom angle 0-180"));
  Serial.println(F("  ARM              Enable ultrasonic detection"));
  Serial.println();
  Serial.println(F("[MOTOR CONTROL]"));
  Serial.println(F("  ON               Start motor"));
  Serial.println(F("  OFF              Stop motor             [X]"));
  Serial.println(F("  F                Forward"));
  Serial.println(F("  B                Backward               [R]"));
  Serial.println(F("  REVERSE           Run backward           [B]"));
  Serial.println(F("  T                Toggle direction"));
  Serial.println(F("  S 200            Set speed in steps/sec"));
  Serial.println(F("                   Range: 10 to 3000"));
  Serial.println();
  Serial.println(F("[SENSOR / INFORMATION]"));
  Serial.println(F("  US               Read ultrasonic once"));
  Serial.println(F("  P                Print status"));
  Serial.println(F("  I 100            Set sensor interval in ms"));
  Serial.println(F("  H or ?           Show this menu"));
  Serial.println();
  Serial.println(F("[QUICK START EXAMPLES]"));
  Serial.println(F("  RUN              Start the complete automatic test"));
  Serial.println(F("  OPEN             Test opening the container"));
  Serial.println(F("  ANGLE 90         Test a custom servo position"));
  Serial.println(F("  S 500            Set motor speed to 500 steps/sec"));
  Serial.println(F("  F                Run forward"));
  Serial.println(F("  OFF              Stop immediately"));
  Serial.println(F("=================================================="));
}

void readSerialCommand() {
  if (!Serial.available()) {
    return;
  }

  String command = Serial.readStringUntil('\n');
  command.trim();
  command.toUpperCase();

  if (command == "RUN") {
    startFullRun();
  } else if (command.startsWith("S ")) {
    setMotorSpeed(command.substring(2).toInt());
  } else if (command.startsWith("I ")) {
    unsigned long value = command.substring(2).toInt();
    if (value >= 20 && value <= 60000) {
      sensorIntervalMs = value;
      Serial.println(F("Sensor interval updated."));
    }
  } else if (command == "ON") {
    cancelFullRun();
    beltRunning = true;
    Serial.println(F("BELT RUNNING"));
  } else if (command == "OFF" || command == "X") {
    cancelFullRun();
    stopBelt();
    Serial.println(F("BELT STOPPED"));
  } else if (command == "F") {
    cancelFullRun();
    digitalWrite(dirPin, HIGH);
    beltRunning = true;
    Serial.println(F("BELT RUNNING FORWARD"));
  } else if (command == "B" || command == "R" || command == "REVERSE") {
    cancelFullRun();
    digitalWrite(dirPin, BELT_CCW_DIRECTION_LEVEL);
    beltRunning = true;
    Serial.println(F("BELT RUNNING BACKWARD"));
  } else if (command == "T") {
    cancelFullRun();
    digitalWrite(dirPin, digitalRead(dirPin) == HIGH ? BELT_CCW_DIRECTION_LEVEL : HIGH);
    beltRunning = true;
    Serial.println(F("BELT DIRECTION TOGGLED"));
  } else if (command == "OPEN" || command == "O") {
    cancelFullRun();
    stopBelt();
    openContainer(false);
  } else if (command == "CLOSE" || command == "C") {
    cancelFullRun();
    closeContainer();
  } else if (command.startsWith("ANGLE ") || command.startsWith("A ")) {
    cancelFullRun();
    int angle = command.startsWith("ANGLE ") ? command.substring(6).toInt()
                                             : command.substring(2).toInt();
    angle = constrain(angle, 0, 180);
    containerServo.write(angle);
    containerOpen = angle != SERVO_CLOSE_ANGLE;
    Serial.print(F("SERVO ANGLE: "));
    Serial.println(angle);
  } else if (command == "ARM") {
    sensorArmed = true;
    blockTriggered = false;
    Serial.println(F("ULTRASONIC ARMED"));
  } else if (command == "US") {
    distance1Cm = readDistanceCm(trigPin1, echoPin1);
    sensor1Detected = objectDetected(distance1Cm);
    printDistance("US1", distance1Cm, sensor1Detected);
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
  updateFullRun();
  updateSensors();
  updateTimedBeltRun();

  if (beltRunning) {
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(5);
    digitalWrite(stepPin, LOW);
    delayMicroseconds(stepIntervalUs);
  }
}

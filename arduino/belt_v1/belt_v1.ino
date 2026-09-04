/*
  Arduino Uno feeder: hopper/container, belt, alignment, and block staging.

  Wiring
    A4988 belt:       DIR 2, STEP 3 (ENABLE tied to GND)
    Exit HC-SR04:      TRIG 4, ECHO 5
    Alignment servo:   6
    Stage HC-SR04:     TRIG 8, ECHO 9
    Container servo:   12

  Controller protocol (all commands are newline terminated):
    FEED [id] / RUN [id]  release and stage one block
    STOP                  cancel a cycle and stop the belt
    STATUS                print a snapshot
    OPEN, CLOSE, ON, OFF, F, B, S <steps/s>, US, HELP

  A cycle emits machine-readable lines.  `@<id> OK state=block_ready` is the
  only successful terminal result; `@<id> ERROR reason=...` is terminal.
  Human-readable status lines are deliberately separate from the protocol.
*/

#include <Arduino.h>
#include <Servo.h>

const uint8_t DIR_PIN = 2;
const uint8_t STEP_PIN = 3;
const uint8_t EXIT_TRIG_PIN = 4;
const uint8_t EXIT_ECHO_PIN = 5;
const uint8_t ALIGN_SERVO_PIN = 6;
const uint8_t STAGE_TRIG_PIN = 8;
const uint8_t STAGE_ECHO_PIN = 9;
const uint8_t CONTAINER_SERVO_PIN = 12;

const uint8_t BELT_CCW_DIRECTION_LEVEL = LOW;
const uint8_t CONTAINER_CLOSED_ANGLE = 20;
const uint8_t CONTAINER_STAGE_1_ANGLE = 90;
const uint8_t CONTAINER_OPEN_ANGLE = 160;
const uint8_t ALIGN_REST_ANGLE = 90;
const uint8_t ALIGN_NUDGE_ANGLE = 120;

const unsigned long CONTAINER_STAGE_DELAY_MS = 500;
const unsigned long CLOSE_SETTLE_MS = 500;
const unsigned long ALIGN_SETTLE_MS = 350;
const unsigned long EXIT_TIMEOUT_MS = 10000;
const unsigned long STAGE_TIMEOUT_MS = 15000;
const unsigned long SENSOR_INTERVAL_MS = 100;
const float DETECT_DISTANCE_CM = 10.0;

Servo containerServo;
Servo alignmentServo;

enum FeedState {
  IDLE,
  CLOSING,
  OPENING_STAGE_1,
  OPENING_STAGE_2,
  WAITING_FOR_EXIT,
  MOVING_TO_STAGE,
  ALIGNING,
  VERIFYING_STAGE,
  BLOCK_READY,
  FAULT
};

FeedState feedState = IDLE;
unsigned long stateStartedAtMs = 0;
unsigned long lastSensorReadMs = 0;
unsigned long commandId = 0;
bool cycleActive = false;
bool beltRunning = false;
bool containerOpen = false;
int motorSpeed = 150;
unsigned long stepIntervalUs = 1000000UL / 150;
float exitDistanceCm = -1.0;
float stageDistanceCm = -1.0;

char commandBuffer[48];
uint8_t commandLength = 0;

bool elapsed(unsigned long since, unsigned long duration) {
  return millis() - since >= duration;
}

float readDistanceCm(uint8_t trigPin, uint8_t echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  unsigned long duration = pulseIn(echoPin, HIGH, 30000);
  return duration == 0 ? -1.0 : duration * 0.0343f / 2.0f;
}

bool detected(float distanceCm) {
  return distanceCm >= 0.0f && distanceCm < DETECT_DISTANCE_CM;
}

void protocolPrefix() {
  Serial.print('@');
  Serial.print(commandId);
}

void event(const __FlashStringHelper *phase) {
  protocolPrefix();
  Serial.print(F(" EVENT phase="));
  Serial.println(phase);
}

void eventDistance(const __FlashStringHelper *phase, float distanceCm) {
  protocolPrefix();
  Serial.print(F(" EVENT phase="));
  Serial.print(phase);
  Serial.print(F(" distance_cm="));
  Serial.println(distanceCm, 1);
}

void success() {
  protocolPrefix();
  Serial.println(F(" OK state=block_ready"));
}

void failure(const __FlashStringHelper *reason) {
  protocolPrefix();
  Serial.print(F(" ERROR reason="));
  Serial.println(reason);
}

void setState(FeedState next) {
  feedState = next;
  stateStartedAtMs = millis();
}

void stopBelt() {
  beltRunning = false;
  digitalWrite(STEP_PIN, LOW);
}

void startBelt(uint8_t direction) {
  digitalWrite(DIR_PIN, direction);
  beltRunning = true;
}

void closeContainer() {
  containerServo.write(CONTAINER_CLOSED_ANGLE);
  containerOpen = false;
}

void openContainerStage1() {
  containerServo.write(CONTAINER_STAGE_1_ANGLE);
}

void openContainerStage2() {
  containerServo.write(CONTAINER_OPEN_ANGLE);
  containerOpen = true;
}

void restAligner() {
  alignmentServo.write(ALIGN_REST_ANGLE);
}

void cancelCycle(bool announce) {
  if (!cycleActive) return;
  cycleActive = false;
  stopBelt();
  restAligner();
  setState(IDLE);
  if (announce) {
    event(F("cancelled"));
    failure(F("cancelled"));
  }
}

void startFeed(unsigned long id) {
  cancelCycle(false);
  commandId = id;
  protocolPrefix();
  Serial.println(F(" RECV cmd=FEED"));
  stopBelt();
  closeContainer();
  restAligner();
  stageDistanceCm = readDistanceCm(STAGE_TRIG_PIN, STAGE_ECHO_PIN);
  if (detected(stageDistanceCm)) {
    setState(FAULT);
    failure(F("stage_occupied"));
    return;
  }
  cycleActive = true;
  closeContainer();
  restAligner();
  setState(CLOSING);
  event(F("container_closing"));
}

void fault(const __FlashStringHelper *reason) {
  stopBelt();
  closeContainer();
  restAligner();
  cycleActive = false;
  setState(FAULT);
  failure(reason);
}

void updateFeedCycle() {
  if (!cycleActive) return;

  switch (feedState) {
    case CLOSING:
      if (elapsed(stateStartedAtMs, CLOSE_SETTLE_MS)) {
        openContainerStage1();
        setState(OPENING_STAGE_1);
        event(F("container_opening_stage_1"));
      }
      break;
    case OPENING_STAGE_1:
      if (elapsed(stateStartedAtMs, CONTAINER_STAGE_DELAY_MS)) {
        openContainerStage2();
        setState(OPENING_STAGE_2);
        event(F("container_opening_stage_2"));
      }
      break;
    case OPENING_STAGE_2:
      if (elapsed(stateStartedAtMs, CONTAINER_STAGE_DELAY_MS)) {
        setState(WAITING_FOR_EXIT);
        event(F("waiting_for_exit"));
      }
      break;
    case WAITING_FOR_EXIT:
      if (elapsed(stateStartedAtMs, EXIT_TIMEOUT_MS)) {
        fault(F("exit_timeout"));
      }
      break;
    case MOVING_TO_STAGE:
      if (elapsed(stateStartedAtMs, STAGE_TIMEOUT_MS)) {
        fault(F("stage_timeout"));
      }
      break;
    case ALIGNING:
      if (elapsed(stateStartedAtMs, ALIGN_SETTLE_MS)) {
        restAligner();
        setState(VERIFYING_STAGE);
        event(F("verifying_stage"));
      }
      break;
    case VERIFYING_STAGE:
      if (elapsed(stateStartedAtMs, SENSOR_INTERVAL_MS)) {
        stageDistanceCm = readDistanceCm(STAGE_TRIG_PIN, STAGE_ECHO_PIN);
        if (detected(stageDistanceCm)) {
          setState(BLOCK_READY);
          cycleActive = false;
          eventDistance(F("block_ready"), stageDistanceCm);
          success();
        } else {
          startBelt(BELT_CCW_DIRECTION_LEVEL);
          setState(MOVING_TO_STAGE);
          event(F("stage_lost_resuming_belt"));
        }
      }
      break;
    default:
      break;
  }
}

void updateSensors() {
  if (!cycleActive || !elapsed(lastSensorReadMs, SENSOR_INTERVAL_MS)) return;
  lastSensorReadMs = millis();

  if (feedState == WAITING_FOR_EXIT) {
    exitDistanceCm = readDistanceCm(EXIT_TRIG_PIN, EXIT_ECHO_PIN);
    if (detected(exitDistanceCm)) {
      // One block has left the hopper.  Shut the gate before transporting it
      // so a second block cannot follow it onto the belt.
      closeContainer();
      startBelt(BELT_CCW_DIRECTION_LEVEL);
      setState(MOVING_TO_STAGE);
      eventDistance(F("exit_detected_container_closed_belt_running"), exitDistanceCm);
    }
  } else if (feedState == MOVING_TO_STAGE) {
    stageDistanceCm = readDistanceCm(STAGE_TRIG_PIN, STAGE_ECHO_PIN);
    if (detected(stageDistanceCm)) {
      stopBelt();
      alignmentServo.write(ALIGN_NUDGE_ANGLE);
      setState(ALIGNING);
      eventDistance(F("stage_detected_aligning"), stageDistanceCm);
    }
  }
}

void setMotorSpeed(long speed) {
  motorSpeed = constrain(speed, 10L, 3000L);
  stepIntervalUs = 1000000UL / motorSpeed;
  Serial.print(F("Speed: "));
  Serial.print(motorSpeed);
  Serial.println(F(" steps_per_second"));
}

void printDistance(const __FlashStringHelper *name, float value) {
  Serial.print(name);
  Serial.print('=');
  if (value < 0.0f) Serial.print(F("no_echo"));
  else Serial.print(value, 1);
  Serial.println(F("cm"));
}

const __FlashStringHelper *stateName() {
  switch (feedState) {
    case IDLE: return F("idle"); case CLOSING: return F("closing");
    case OPENING_STAGE_1: return F("opening_stage_1"); case OPENING_STAGE_2: return F("opening_stage_2");
    case WAITING_FOR_EXIT: return F("waiting_for_exit"); case MOVING_TO_STAGE: return F("moving_to_stage");
    case ALIGNING: return F("aligning"); case VERIFYING_STAGE: return F("verifying_stage");
    case BLOCK_READY: return F("block_ready"); default: return F("fault");
  }
}

void printStatus() {
  exitDistanceCm = readDistanceCm(EXIT_TRIG_PIN, EXIT_ECHO_PIN);
  stageDistanceCm = readDistanceCm(STAGE_TRIG_PIN, STAGE_ECHO_PIN);
  Serial.print(F("STATE state=")); Serial.print(stateName());
  Serial.print(F(" belt=")); Serial.print(beltRunning ? F("running") : F("stopped"));
  Serial.print(F(" container=")); Serial.println(containerOpen ? F("open") : F("closed"));
  printDistance(F("EXIT_DISTANCE"), exitDistanceCm);
  printDistance(F("STAGE_DISTANCE"), stageDistanceCm);
}

void printHelp() {
  Serial.println(F("FEED [id] | RUN [id] : stage exactly one block"));
  Serial.println(F("STOP | STATUS | OPEN | CLOSE | ON | OFF | F | B | S <steps/s> | US | HELP"));
  Serial.println(F("Terminal protocol: @id OK state=block_ready | @id ERROR reason=..."));
}

unsigned long requestIdFrom(const char *argument) {
  while (*argument == ' ') ++argument;
  return *argument ? strtoul(argument, NULL, 10) : ++commandId;
}

void handleCommand(char *line) {
  for (char *p = line; *p; ++p) *p = toupper(*p);
  char *argument = strchr(line, ' ');
  if (argument) { *argument++ = '\0'; }

  if (!strcmp(line, "FEED") || !strcmp(line, "RUN")) {
    startFeed(requestIdFrom(argument ? argument : ""));
  } else if (!strcmp(line, "STOP") || !strcmp(line, "OFF") || !strcmp(line, "X")) {
    cancelCycle(true); stopBelt(); Serial.println(F("BELT STOPPED"));
  } else if (!strcmp(line, "STATUS") || !strcmp(line, "P")) {
    printStatus();
  } else if (!strcmp(line, "OPEN") || !strcmp(line, "O")) {
    cancelCycle(true); stopBelt(); openContainerStage1(); delay(CONTAINER_STAGE_DELAY_MS); openContainerStage2(); Serial.println(F("CONTAINER OPEN"));
  } else if (!strcmp(line, "CLOSE") || !strcmp(line, "C")) {
    cancelCycle(true); stopBelt(); closeContainer(); Serial.println(F("CONTAINER CLOSED"));
  } else if (!strcmp(line, "ON")) {
    cancelCycle(true); startBelt(BELT_CCW_DIRECTION_LEVEL); Serial.println(F("BELT RUNNING"));
  } else if (!strcmp(line, "F")) {
    cancelCycle(true); startBelt(HIGH); Serial.println(F("BELT RUNNING FORWARD"));
  } else if (!strcmp(line, "B") || !strcmp(line, "R") || !strcmp(line, "REVERSE")) {
    cancelCycle(true); startBelt(BELT_CCW_DIRECTION_LEVEL); Serial.println(F("BELT RUNNING BACKWARD"));
  } else if (!strcmp(line, "S") && argument) {
    setMotorSpeed(strtol(argument, NULL, 10));
  } else if (!strcmp(line, "US")) {
    printStatus();
  } else if (!strcmp(line, "H") || !strcmp(line, "HELP") || !strcmp(line, "?")) {
    printHelp();
  } else {
    Serial.print(F("ERROR unknown_command=")); Serial.println(line);
  }
}

void readSerialCommands() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      commandBuffer[commandLength] = '\0';
      if (commandLength) handleCommand(commandBuffer);
      commandLength = 0;
    } else if (commandLength < sizeof(commandBuffer) - 1) {
      commandBuffer[commandLength++] = c;
    } else {
      commandLength = 0;
      Serial.println(F("ERROR command_too_long"));
    }
  }
}

void setup() {
  pinMode(DIR_PIN, OUTPUT); pinMode(STEP_PIN, OUTPUT);
  pinMode(EXIT_TRIG_PIN, OUTPUT); pinMode(EXIT_ECHO_PIN, INPUT);
  pinMode(STAGE_TRIG_PIN, OUTPUT); pinMode(STAGE_ECHO_PIN, INPUT);
  digitalWrite(STEP_PIN, LOW); digitalWrite(EXIT_TRIG_PIN, LOW); digitalWrite(STAGE_TRIG_PIN, LOW);
  containerServo.attach(CONTAINER_SERVO_PIN); alignmentServo.attach(ALIGN_SERVO_PIN);
  closeContainer(); restAligner();
  Serial.begin(9600);
  Serial.println(F("@0 READY firmware=belt_v1 protocol=1 board=uno"));
  printHelp();
}

void loop() {
  readSerialCommands();
  updateFeedCycle();
  updateSensors();
  if (beltRunning) {
    digitalWrite(STEP_PIN, HIGH); delayMicroseconds(5);
    digitalWrite(STEP_PIN, LOW); delayMicroseconds(stepIntervalUs);
  }
}

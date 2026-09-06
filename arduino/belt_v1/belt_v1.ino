/*
  Arduino Uno feeder: hopper/container, belt, alignment, and block staging.

  Wiring
    A4988 belt:       DIR 2, STEP 3 (ENABLE tied to GND)
    Exit IR sensor:    OUT 4 (VCC and GND to the sensor supply)
    Alignment servo:   6
    Stage IR sensor:   OUT 8 (VCC and GND to the sensor supply)
    Container servo:   12

  Controller protocol (all commands are newline terminated):
    FEED [id] / RUN [id]  release and stage one block
    STOP                  cancel a cycle and stop the belt
    STATUS                print a snapshot
    OPEN, CLOSE, ON, OFF, F, B, S <steps/s>, US, HELP

  A cycle emits machine-readable lines. The exact terminal success is
  `@<id> OK state=block_ready result=staged`; `@<id> ERROR ...` is terminal.
  Human-readable status lines are deliberately separate from the protocol.
*/

#include <Arduino.h>
#include <Servo.h>

const uint8_t DIR_PIN = 2;
const uint8_t STEP_PIN = 3;
const uint8_t EXIT_IR_PIN = 4;
const uint8_t ALIGN_SERVO_PIN = 6;
const uint8_t STAGE_IR_PIN = 8;
// Most LM393 IR obstacle sensors drive OUT LOW when an object is detected.
// Change this to HIGH if the installed sensor has inverted output logic.
const uint8_t STAGE_IR_DETECTED_LEVEL = LOW;
// Most LM393 IR obstacle sensors drive OUT LOW when an object is detected.
// Change this to HIGH if the installed exit sensor has inverted output logic.
const uint8_t EXIT_IR_DETECTED_LEVEL = LOW;
const uint8_t CONTAINER_SERVO_PIN = 12;

const uint8_t BELT_FORWARD_DIRECTION_LEVEL = HIGH;
const uint8_t BELT_REVERSE_DIRECTION_LEVEL = LOW;
// Container gate sequence: closed, first opening stage, then fully open.
const uint8_t CONTAINER_CLOSED_ANGLE = 23;
const uint8_t CONTAINER_STAGE_1_ANGLE = 80;
const uint8_t CONTAINER_OPEN_ANGLE = 150;
const uint8_t ALIGN_REST_ANGLE = 90;
const uint8_t ALIGN_NUDGE_ANGLE = 120;

// Keep one second between the commanded positions of either servo.
const unsigned long SERVO_MOVEMENT_DELAY_MS = 1000;
const unsigned long CONTAINER_STAGE_DELAY_MS = SERVO_MOVEMENT_DELAY_MS;
const unsigned long CLOSE_SETTLE_MS = SERVO_MOVEMENT_DELAY_MS;
const unsigned long ALIGN_SETTLE_MS = SERVO_MOVEMENT_DELAY_MS;
// Every FEED/RUN starts by advancing the belt before the container is closed.
const unsigned long PRE_CLOSE_BELT_RUN_MS = 1000;
// After the exit IR sees a block, keep the gate open while the belt starts.
const unsigned long EXIT_DETECTED_TO_CLOSE_DELAY_MS = 1250;
// Let the block travel slightly past the stage IR before stopping the belt.
// Continue walking the belt for 180 ms after the stage IR detects the block.
const unsigned long STAGE_DETECTED_BELT_SETTLE_MS = 180;
const unsigned long EXIT_TIMEOUT_MS = 10000;
const unsigned long STAGE_TIMEOUT_MS = 15000;
const unsigned long SENSOR_INTERVAL_MS = 100;

Servo containerServo;
Servo alignmentServo;

enum FeedState {
  IDLE,
  PRE_CLOSING_BELT_RUN,
  CLOSING,
  OPENING_STAGE_1,
  OPENING_STAGE_2,
  WAITING_FOR_EXIT,
  WAITING_TO_CLOSE_AFTER_EXIT,
  MOVING_TO_STAGE,
  STAGE_BELT_SETTLING,
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
int motorSpeed = 325;
unsigned long stepIntervalUs = 1000000UL / 325;
bool exitDetected = false;

char commandBuffer[48];
uint8_t commandLength = 0;
bool discardingCommand = false;

bool elapsed(unsigned long since, unsigned long duration) {
  return millis() - since >= duration;
}

const __FlashStringHelper *stateName();

bool exitSensorDetected() {
  return digitalRead(EXIT_IR_PIN) == EXIT_IR_DETECTED_LEVEL;
}

bool stageDetected() {
  return digitalRead(STAGE_IR_PIN) == STAGE_IR_DETECTED_LEVEL;
}

void protocolPrefixFor(unsigned long id) {
  Serial.print('@');
  Serial.print(id);
}

void protocolPrefix() {
  protocolPrefixFor(commandId);
}

void stateChanged() {
  protocolPrefix();
  Serial.print(F(" STATE state="));
  Serial.println(stateName());
}

void sensorReportFor(unsigned long id, const __FlashStringHelper *sensor,
                     bool detectedNow) {
  protocolPrefixFor(id);
  Serial.print(F(" SENSOR sensor="));
  Serial.print(sensor);
  Serial.print(F(" detected="));
  Serial.println(detectedNow ? 1 : 0);
}

void stageSensorReportFor(unsigned long id, bool detectedNow) {
  protocolPrefixFor(id);
  Serial.print(F(" SENSOR sensor=stage detected="));
  Serial.println(detectedNow ? 1 : 0);
}

void acknowledgeManual(const __FlashStringHelper *command) {
  protocolPrefixFor(0);
  Serial.print(F(" ACK cmd="));
  Serial.println(command);
}

void event(const __FlashStringHelper *phase) {
  protocolPrefix();
  Serial.print(F(" EVENT phase="));
  Serial.println(phase);
}

void success() {
  protocolPrefix();
  Serial.println(F(" OK state=block_ready result=staged"));
}

void failure(const __FlashStringHelper *reason) {
  protocolPrefix();
  Serial.print(F(" ERROR state="));
  Serial.print(stateName());
  Serial.print(F(" reason="));
  Serial.println(reason);
}

void failureFor(unsigned long id, const __FlashStringHelper *reason) {
  protocolPrefixFor(id);
  Serial.print(F(" ERROR state="));
  Serial.print(stateName());
  Serial.print(F(" reason="));
  Serial.println(reason);
}

void setState(FeedState next) {
  feedState = next;
  stateStartedAtMs = millis();
  stateChanged();
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
  // The pickup stage is a single-owner resource. Never cancel and replace an
  // in-flight transaction: its first block may already have left the hopper.
  if (cycleActive) {
    failureFor(id, F("busy"));
    return;
  }
  commandId = id;
  protocolPrefix();
  Serial.println(F(" RECV cmd=FEED"));
  stopBelt();
  restAligner();
  const bool stagePresent = stageDetected();
  stageSensorReportFor(commandId, stagePresent);
  if (stagePresent) {
    setState(FAULT);
    failure(F("stage_occupied"));
    return;
  }
  protocolPrefix();
  Serial.println(F(" ACK cmd=FEED accepted=1"));
  cycleActive = true;
  // Advance the belt for one second before closing the gate, as requested.
  startBelt(BELT_FORWARD_DIRECTION_LEVEL);
  setState(PRE_CLOSING_BELT_RUN);
  event(F("belt_running_before_container_close"));
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
    case PRE_CLOSING_BELT_RUN:
      if (elapsed(stateStartedAtMs, PRE_CLOSE_BELT_RUN_MS)) {
        stopBelt();
        closeContainer();
        setState(CLOSING);
        event(F("container_closing_after_belt_run"));
      }
      break;
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
    case WAITING_TO_CLOSE_AFTER_EXIT:
      if (elapsed(stateStartedAtMs, EXIT_DETECTED_TO_CLOSE_DELAY_MS)) {
        closeContainer();
        setState(MOVING_TO_STAGE);
        event(F("exit_delay_elapsed_container_closed"));
      }
      break;
    case MOVING_TO_STAGE:
      if (elapsed(stateStartedAtMs, STAGE_TIMEOUT_MS)) {
        fault(F("stage_timeout"));
      }
      break;
    case STAGE_BELT_SETTLING:
      if (elapsed(stateStartedAtMs, STAGE_DETECTED_BELT_SETTLE_MS)) {
        stopBelt();
        alignmentServo.write(ALIGN_NUDGE_ANGLE);
        setState(ALIGNING);
        event(F("stage_settled_aligning"));
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
        const bool stagePresent = stageDetected();
        stageSensorReportFor(commandId, stagePresent);
        if (stagePresent) {
          setState(BLOCK_READY);
          cycleActive = false;
          event(F("block_ready"));
          success();
        } else {
          startBelt(BELT_FORWARD_DIRECTION_LEVEL);
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
    exitDetected = exitSensorDetected();
    if (exitDetected) {
      // One block has left the hopper. Start transport immediately, then wait
      // 1.25 seconds before shutting the gate so the block can clear it.
      startBelt(BELT_FORWARD_DIRECTION_LEVEL);
      setState(WAITING_TO_CLOSE_AFTER_EXIT);
      sensorReportFor(commandId, F("exit"), exitDetected);
      event(F("exit_detected_belt_running_waiting_to_close"));
    }
  } else if (feedState == MOVING_TO_STAGE) {
    if (stageDetected()) {
      stageSensorReportFor(commandId, true);
      if (STAGE_DETECTED_BELT_SETTLE_MS == 0) {
        stopBelt();
        alignmentServo.write(ALIGN_NUDGE_ANGLE);
        setState(ALIGNING);
        event(F("stage_detected_aligning"));
      } else {
        setState(STAGE_BELT_SETTLING);
        event(F("stage_detected_belt_settling"));
      }
    }
  }
}

void setMotorSpeed(long speed) {
  motorSpeed = constrain(speed, 10L, 3000L);
  stepIntervalUs = 1000000UL / motorSpeed;
}

const __FlashStringHelper *stateName() {
  switch (feedState) {
    case IDLE: return F("idle"); case PRE_CLOSING_BELT_RUN: return F("pre_closing_belt_run");
    case CLOSING: return F("closing");
    case OPENING_STAGE_1: return F("opening_stage_1"); case OPENING_STAGE_2: return F("opening_stage_2");
    case WAITING_FOR_EXIT: return F("waiting_for_exit");
    case WAITING_TO_CLOSE_AFTER_EXIT: return F("waiting_to_close_after_exit");
    case MOVING_TO_STAGE: return F("moving_to_stage");
    case STAGE_BELT_SETTLING: return F("stage_belt_settling");
    case ALIGNING: return F("aligning"); case VERIFYING_STAGE: return F("verifying_stage");
    case BLOCK_READY: return F("block_ready"); default: return F("fault");
  }
}

void printStatus() {
  exitDetected = exitSensorDetected();
  protocolPrefixFor(0);
  Serial.print(F(" STATUS state=")); Serial.print(stateName());
  Serial.print(F(" active=")); Serial.print(cycleActive ? 1 : 0);
  Serial.print(F(" belt=")); Serial.print(beltRunning ? F("running") : F("stopped"));
  Serial.print(F(" container=")); Serial.print(containerOpen ? F("open") : F("closed"));
  Serial.print(F(" speed_steps_s=")); Serial.println(motorSpeed);
  sensorReportFor(0, F("exit"), exitDetected);
  stageSensorReportFor(0, stageDetected());
}

void printHelp() {
  Serial.println(F("FEED [id] | RUN [id] : stage exactly one block"));
  Serial.println(F("STOP | STATUS | OPEN | CLOSE | ON | OFF | F | B | S <steps/s> | US | HELP"));
  Serial.println(F("Protocol: RECV, ACK, STATE, SENSOR, EVENT, then one OK or ERROR."));
}

bool requestIdFrom(const char *argument, unsigned long *result) {
  while (*argument == ' ') ++argument;
  if (!*argument) {
    unsigned long next = commandId + 1;
    *result = next == 0 ? 1 : next;
    return true;
  }
  char *end = NULL;
  unsigned long requested = strtoul(argument, &end, 10);
  while (end && *end == ' ') ++end;
  // @0 is reserved for boot/status/manual messages. Requiring the entire
  // argument to be decimal also rejects ambiguous tails such as `12x`.
  if (!end || *end || requested == 0 || *argument == '-') return false;
  *result = requested;
  return true;
}

void handleCommand(char *line) {
  for (char *p = line; *p; ++p) *p = toupper(*p);
  char *argument = strchr(line, ' ');
  if (argument) { *argument++ = '\0'; }

  if (!strcmp(line, "FEED") || !strcmp(line, "RUN")) {
    unsigned long requestId = 0;
    if (!requestIdFrom(argument ? argument : "", &requestId)) {
      Serial.println(F("@0 ERROR reason=invalid_request_id"));
    } else {
      startFeed(requestId);
    }
  } else if (!strcmp(line, "STOP") || !strcmp(line, "OFF") || !strcmp(line, "X")) {
    cancelCycle(true); stopBelt(); acknowledgeManual(F("STOP"));
  } else if (!strcmp(line, "STATUS") || !strcmp(line, "P")) {
    printStatus();
  } else if (!strcmp(line, "OPEN") || !strcmp(line, "O")) {
    cancelCycle(true); stopBelt(); openContainerStage1(); delay(CONTAINER_STAGE_DELAY_MS); openContainerStage2(); acknowledgeManual(F("OPEN"));
  } else if (!strcmp(line, "CLOSE") || !strcmp(line, "C")) {
    cancelCycle(true); stopBelt(); closeContainer(); acknowledgeManual(F("CLOSE"));
  } else if (!strcmp(line, "ON")) {
    cancelCycle(true); startBelt(BELT_FORWARD_DIRECTION_LEVEL); acknowledgeManual(F("ON"));
  } else if (!strcmp(line, "F")) {
    cancelCycle(true); startBelt(BELT_FORWARD_DIRECTION_LEVEL); acknowledgeManual(F("F"));
  } else if (!strcmp(line, "B") || !strcmp(line, "R") || !strcmp(line, "REVERSE")) {
    cancelCycle(true); startBelt(BELT_REVERSE_DIRECTION_LEVEL); acknowledgeManual(F("B"));
  } else if (!strcmp(line, "S") && argument) {
    setMotorSpeed(strtol(argument, NULL, 10));
    protocolPrefixFor(0);
    Serial.print(F(" CONFIG speed_steps_s="));
    Serial.println(motorSpeed);
    acknowledgeManual(F("S"));
  } else if (!strcmp(line, "US")) {
    printStatus();
  } else if (!strcmp(line, "H") || !strcmp(line, "HELP") || !strcmp(line, "?")) {
    printHelp();
  } else {
    protocolPrefixFor(0);
    Serial.print(F(" ERROR reason=unknown_command command=")); Serial.println(line);
  }
}

void readSerialCommands() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (discardingCommand) {
        discardingCommand = false;
        commandLength = 0;
        continue;
      }
      commandBuffer[commandLength] = '\0';
      if (commandLength) handleCommand(commandBuffer);
      commandLength = 0;
    } else if (discardingCommand) {
      continue;
    } else if (commandLength < sizeof(commandBuffer) - 1) {
      commandBuffer[commandLength++] = c;
    } else {
      commandLength = 0;
      discardingCommand = true;
      Serial.println(F("@0 ERROR reason=command_too_long"));
    }
  }
}

void setup() {
  pinMode(DIR_PIN, OUTPUT); pinMode(STEP_PIN, OUTPUT);
  pinMode(EXIT_IR_PIN, INPUT);
  pinMode(STAGE_IR_PIN, INPUT);
  digitalWrite(STEP_PIN, LOW);
  containerServo.attach(CONTAINER_SERVO_PIN); alignmentServo.attach(ALIGN_SERVO_PIN);
  closeContainer(); restAligner();
  Serial.begin(9600);
  Serial.println(F("@0 READY firmware=belt_v1 protocol=3 board=uno"));
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

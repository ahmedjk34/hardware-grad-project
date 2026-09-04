// Container + belt controller for an Arduino Mega 2560.
//
// RUN performs a complete cycle:
// 1. Close container
// 2. Open container in 2 stages (90 -> 160), 0.5s delay each stage
// 3. Detect a block
// 4. Run belt for five seconds
// 5. Close container
//

#include <Arduino.h>
#include <Servo.h>

// A4988
uint8_t stepPin = 3;
uint8_t dirPin = 2;

// leave 4,5,6,7 unused

// Ultrasonic
uint8_t trigPin1 = 8;
uint8_t echoPin1 = 9;

// leave 10,11 unused

// Servo
uint8_t servoPin = 12;

// 2-stage open positions
const uint8_t SERVO_CLOSED_ANGLE = 20; // fully closed
const uint8_t SERVO_STAGE_1 = 90;      // first open stage
const uint8_t SERVO_STAGE_2 = 160;     // second open stage (fully open)

const uint8_t SERVO_CLOSE_ANGLE = SERVO_CLOSED_ANGLE;
const uint8_t SERVO_OPEN_ANGLE = SERVO_STAGE_2;

const unsigned long SERVO_STAGE_DELAY_MS = 500;

const unsigned long BELT_RUN_TIME_MS = 5000;
const unsigned long RUN_CLOSE_SETTLE_MS = 500;

// Flip this if installed belt direction is reversed
const uint8_t BELT_CCW_DIRECTION_LEVEL = LOW;

Servo containerServo;

// Runtime settings
int motorSpeed = 150;
unsigned long stepIntervalUs = 5000;

const float detectDistanceCm = 10.0;
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

float readDistanceCm(uint8_t trigPin, uint8_t echoPin)
{
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);

  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);

  digitalWrite(trigPin, LOW);

  unsigned long duration = pulseIn(echoPin, HIGH, 30000);

  if (duration == 0)
  {
    return -1.0;
  }

  return duration * 0.0343 / 2.0;
}

bool objectDetected(float distanceCm)
{
  return distanceCm >= 0.0 && distanceCm < detectDistanceCm;
}

void stopBelt()
{
  beltRunning = false;
  timedBeltRun = false;
  digitalWrite(stepPin, LOW);
}

void cancelFullRun()
{
  fullRunMode = false;
  sensorArmed = false;
}

void moveContainerToOpenSmooth()
{
  containerServo.write(SERVO_STAGE_1);
  delay(SERVO_STAGE_DELAY_MS);

  containerServo.write(SERVO_STAGE_2);
  delay(SERVO_STAGE_DELAY_MS);
}

void openContainer(bool armSensor)
{
  moveContainerToOpenSmooth();

  containerOpen = true;
  sensorArmed = armSensor;
  blockTriggered = false;
  sensor1Detected = false;

  Serial.println(
      armSensor
          ? F("CONTAINER OPEN (90->160); ultrasonic armed")
          : F("CONTAINER OPEN (90->160)"));
}

void closeContainer()
{
  stopBelt();

  containerServo.write(SERVO_CLOSED_ANGLE);

  containerOpen = false;
  sensorArmed = false;
  blockTriggered = false;
  sensor1Detected = false;

  Serial.println(F("CONTAINER CLOSED (20 deg)"));
}

void startFullRun()
{
  stopBelt();

  fullRunMode = true;

  closeContainer();

  fullRunOpenAtMs = millis() + RUN_CLOSE_SETTLE_MS;

  Serial.println(F("FULL RUN: closed; opening in 500 ms"));
}

void updateFullRun()
{
  if (!fullRunMode)
  {
    return;
  }

  if (containerOpen)
  {
    return;
  }

  if (millis() < fullRunOpenAtMs)
  {
    return;
  }

  openContainer(true);

  Serial.println(F("FULL RUN: waiting for object below 10 cm"));
}

void updateTimedBeltRun()
{
  if (!timedBeltRun)
  {
    return;
  }

  if (millis() < beltStopAtMs)
  {
    return;
  }

  timedBeltRun = false;

  // stopBelt() also gets called inside closeContainer(), but call it here
  // too so the belt halts immediately even if we're not in a full run.
  stopBelt();

  Serial.println(F("BELT STOPPED after 5 seconds"));

  if (fullRunMode)
  {
    fullRunMode = false;

    // Detection already happened for this cycle; close the container now
    // that the belt run is finished.
    closeContainer();

    Serial.println(F("FULL RUN COMPLETE: container closed after detection"));
  }
}

void setMotorSpeed(int speed)
{
  motorSpeed = constrain(speed, 10, 3000);

  stepIntervalUs = 1000000UL / motorSpeed;

  Serial.print(F("Speed: "));
  Serial.print(motorSpeed);
  Serial.println(F(" steps/second"));
}

void runBeltCounterClockwiseForFiveSeconds()
{
  Serial.println(F("BLOCK detected (<10 cm) -> BELT CCW for 5 seconds"));

  beltRunning = true;
  timedBeltRun = true;

  beltStopAtMs = millis() + BELT_RUN_TIME_MS;

  digitalWrite(dirPin, BELT_CCW_DIRECTION_LEVEL);
}

void updateSensors()
{
  if (!fullRunMode)
    return;
  if (!containerOpen)
    return;
  if (!sensorArmed)
    return;
  if (blockTriggered)
    return;

  if (millis() - lastSensorReadMs < sensorIntervalMs)
  {
    return;
  }

  lastSensorReadMs = millis();

  distance1Cm = readDistanceCm(trigPin1, echoPin1);

  sensor1Detected = objectDetected(distance1Cm);

  if (sensor1Detected)
  {
    blockTriggered = true;
    sensorArmed = false;

    runBeltCounterClockwiseForFiveSeconds();
  }
}

void printDistance(const char *name,
                   float distanceCm,
                   bool detected)
{
  Serial.print(name);
  Serial.print(F(": "));

  if (distanceCm < 0.0)
  {
    Serial.print(F("NO ECHO"));
  }
  else
  {
    Serial.print(distanceCm, 1);
    Serial.print(F(" cm"));
  }

  Serial.print(F(" | "));

  Serial.println(
      detected
          ? F("DETECT OBJECT")
          : F("NOT DETECT OBJECT"));
}

void printStatus()
{
  Serial.println(F("--- STATUS ---"));

  Serial.print(F("Belt: "));
  Serial.println(beltRunning ? F("RUNNING") : F("STOPPED"));

  Serial.print(F("Container: "));
  Serial.println(containerOpen
                     ? F("OPEN (160 deg)")
                     : F("CLOSED (20 deg)"));

  Serial.print(F("Full run: "));
  Serial.println(fullRunMode ? F("ACTIVE") : F("OFF"));

  Serial.print(F("Ultrasonic armed: "));
  Serial.println(sensorArmed ? F("YES") : F("NO"));

  Serial.print(F("Speed: "));
  Serial.print(motorSpeed);
  Serial.println(F(" steps/second"));

  printDistance("US1", distance1Cm, sensor1Detected);
}

void printHelp()
{
  Serial.println();
  Serial.println(F("=================================================="));
  Serial.println(F("              BELT TEST V1 MENU"));
  Serial.println(F("=================================================="));
  Serial.println(F("RUN      = Full automatic cycle"));
  Serial.println(F("OPEN     = Open container"));
  Serial.println(F("CLOSE    = Close container"));
  Serial.println(F("ON       = Start belt"));
  Serial.println(F("OFF      = Stop belt"));
  Serial.println(F("F        = Forward"));
  Serial.println(F("B        = Backward"));
  Serial.println(F("S 500    = Set speed"));
  Serial.println(F("US       = Read ultrasonic"));
  Serial.println(F("P        = Print status"));
  Serial.println(F("=================================================="));
}

void readSerialCommand()
{
  if (!Serial.available())
  {
    return;
  }

  String command = Serial.readStringUntil('\n');

  command.trim();
  command.toUpperCase();

  if (command == "RUN")
  {
    startFullRun();
  }

  else if (command.startsWith("S "))
  {
    setMotorSpeed(command.substring(2).toInt());
  }

  else if (command == "ON")
  {
    cancelFullRun();
    beltRunning = true;
    Serial.println(F("BELT RUNNING"));
  }

  else if (command == "OFF" || command == "X")
  {
    cancelFullRun();
    stopBelt();
    Serial.println(F("BELT STOPPED"));
  }

  else if (command == "F")
  {
    cancelFullRun();

    digitalWrite(dirPin, HIGH);

    beltRunning = true;

    Serial.println(F("BELT RUNNING FORWARD"));
  }

  else if (command == "B" ||
           command == "R" ||
           command == "REVERSE")
  {
    cancelFullRun();

    digitalWrite(dirPin, BELT_CCW_DIRECTION_LEVEL);

    beltRunning = true;

    Serial.println(F("BELT RUNNING BACKWARD"));
  }

  else if (command == "OPEN" ||
           command == "O")
  {
    cancelFullRun();

    stopBelt();

    openContainer(false);
  }

  else if (command == "CLOSE" ||
           command == "C")
  {
    cancelFullRun();

    closeContainer();
  }

  else if (command.startsWith("ANGLE ") ||
           command.startsWith("A "))
  {
    cancelFullRun();

    int angle =
        command.startsWith("ANGLE ")
            ? command.substring(6).toInt()
            : command.substring(2).toInt();

    angle = constrain(angle, 0, 180);

    containerServo.write(angle);

    containerOpen = angle != SERVO_CLOSE_ANGLE;

    Serial.print(F("SERVO ANGLE: "));
    Serial.println(angle);
  }

  else if (command == "ARM")
  {
    sensorArmed = true;
    blockTriggered = false;

    Serial.println(F("ULTRASONIC ARMED"));
  }

  else if (command == "US")
  {
    distance1Cm = readDistanceCm(trigPin1, echoPin1);

    sensor1Detected = objectDetected(distance1Cm);

    printDistance(
        "US1",
        distance1Cm,
        sensor1Detected);
  }

  else if (command == "P")
  {
    printStatus();
  }

  else if (command == "H" ||
           command == "?")
  {
    printHelp();
  }
}

void setup()
{
  pinMode(stepPin, OUTPUT);
  pinMode(dirPin, OUTPUT);

  pinMode(trigPin1, OUTPUT);
  pinMode(echoPin1, INPUT);

  digitalWrite(stepPin, LOW);
  digitalWrite(trigPin1, LOW);

  containerServo.attach(servoPin);

  containerServo.write(SERVO_CLOSED_ANGLE);

  Serial.begin(9600);

  Serial.println(
      F("CONTAINER + BELT READY"));

  printHelp();
}

void loop()
{
  readSerialCommand();

  updateFullRun();
  updateSensors();
  updateTimedBeltRun();

  if (beltRunning)
  {
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(5);

    digitalWrite(stepPin, LOW);
    delayMicroseconds(stepIntervalUs);
  }
}
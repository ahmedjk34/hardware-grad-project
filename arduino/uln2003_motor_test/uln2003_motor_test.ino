// Simple 28BYJ-48 + ULN2003 motor test.
// Serial commands:
//   R  = rotate one way
//   RR = rotate the other way

// Your wiring:
//   IN1 / BLACK -> Mega pin 38
//   IN2 / GREEN -> Mega pin 36
//   IN3 / BLUE  -> Mega pin 39
//   IN4 / RED   -> Mega pin 37
const int IN1 = 38;
const int IN2 = 36;
const int IN3 = 39;
const int IN4 = 37;

const int coils[4] = {IN1, IN3, IN2, IN4};

const byte sequence[4][4] = {
  {HIGH, LOW,  LOW,  LOW},
  {LOW,  LOW,  HIGH, LOW},
  {LOW,  HIGH, LOW,  LOW},
  {LOW,  LOW,  LOW,  HIGH}
};

int stepIndex = 0;

void energize(int index) {
  for (int i = 0; i < 4; i++) {
    digitalWrite(coils[i], sequence[index][i]);
  }
}

void rotateMotor(int direction) {
  for (int i = 0; i < 512; i++) {
    stepIndex = (stepIndex + direction + 4) % 4;
    energize(stepIndex);
    delay(3);
  }

  // Release the motor when the test move is complete.
  for (int i = 0; i < 4; i++) {
    digitalWrite(coils[i], LOW);
  }
}

void setup() {
  for (int i = 0; i < 4; i++) {
    pinMode(coils[i], OUTPUT);
    digitalWrite(coils[i], LOW);
  }

  Serial.begin(9600);
  Serial.println(F("Send R or RR"));
}

void loop() {
  if (Serial.available()) {
    char command = Serial.read();

    if (command == 'R') {
      delay(2);
      if (Serial.peek() == 'R') {
        Serial.read();
        rotateMotor(-1);
        Serial.println(F("RR"));
      } else {
        rotateMotor(1);
        Serial.println(F("R"));
      }
    }
  }
}

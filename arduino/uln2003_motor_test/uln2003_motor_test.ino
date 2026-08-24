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
    {HIGH, LOW, LOW, LOW},
    {LOW, LOW, HIGH, LOW},
    {LOW, HIGH, LOW, LOW},
    {LOW, LOW, LOW, HIGH}};

int stepIndex = 0;

// Steps per full revolution. Change this to match your motor/gearbox
// if you find a different effective step count (some modules use 4096).
const long STEPS_PER_REV = 512;

void energize(int index)
{
  for (int i = 0; i < 4; i++)
  {
    digitalWrite(coils[i], sequence[index][i]);
  }
}

// Rotate by a signed number of steps. Positive = forward, negative = reverse.
void rotateSteps(long steps)
{
  long absSteps = steps >= 0 ? steps : -steps;
  int direction = steps >= 0 ? 1 : -1;

  for (long i = 0; i < absSteps; i++)
  {
    stepIndex = (stepIndex + direction + 4) % 4;
    energize(stepIndex);
    delay(3);
  }

  // Release the motor when the move is complete.
  for (int i = 0; i < 4; i++)
  {
    digitalWrite(coils[i], LOW);
  }
}

void setup()
{
  for (int i = 0; i < 4; i++)
  {
    pinMode(coils[i], OUTPUT);
    digitalWrite(coils[i], LOW);
  }

  Serial.begin(9600);
  Serial.println(F("Send R or RR (legacy), or send a number in degrees (e.g. 90, -45)"));
}

void loop()
{
  if (Serial.available())
  {
    // Read a line (until newline) so the user can send complete numbers.
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0)
      return;

    // Legacy commands: 'R' or 'RR'
    if (line.equals("R"))
    {
      rotateSteps(STEPS_PER_REV);
      Serial.println(F("R"));
      return;
    }
    if (line.equals("RR"))
    {
      rotateSteps(-STEPS_PER_REV);
      Serial.println(F("RR"));
      return;
    }

    // Otherwise, try to parse as signed degrees.
    char c = line.charAt(0);
    if ((c >= '0' && c <= '9') || c == '+' || c == '-' || c == '.')
    {
      float deg = line.toFloat();
      float rawSteps = (deg / 360.0) * (float)STEPS_PER_REV;
      long steps = (long)(rawSteps >= 0 ? rawSteps + 0.5 : rawSteps - 0.5);
      if (steps != 0)
        rotateSteps(steps);

      Serial.print(F("Rotated "));
      Serial.print(deg);
      Serial.println(F(" deg"));
      return;
    }

    Serial.println(F("Unknown command. Send R, RR, or an angle in degrees."));
  }
}

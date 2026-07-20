/*
  ============================================================
  Dual TB6600 + Arduino MEGA 2560
  CNC-style step testing with limit switches and step counters
  ============================================================

  Each serial command moves a fixed number of steps along a labeled
  axis direction, then stops and holds position.

  SERIAL COMMANDS
    1 = Y-   (Motor 1 CW  / Motor 2 CW )
    2 = X-   (Motor 1 CW  / Motor 2 CCW)
    3 = X+   (Motor 1 CCW / Motor 2 CW )
    4 = Y+   (Motor 1 CCW / Motor 2 CCW)
    5 = Show step counters (totals since power-on / reset)
    6 = Reset step counters to zero
    7 = Disable both motors (release holding torque)

  LIMIT SWITCHES
    Pin 30 = X axis limit switch  (mounted at the X- end of travel)
    Pin 31 = Y axis limit switch  (mounted at the Y- end of travel)

    A tripped switch blocks ONLY the direction that drives into it.
    Example: X switch hit -> command 2 (X-) is refused, but command 3
    (X+) still works so you can back off the switch.

    The switch is checked before the move AND before every step pulse,
    so a mid-move trip aborts immediately and only the steps that were
    actually executed get counted.

  ============================================================
*/

// ============================================================
// SECTION 1 - MOTOR PIN CONFIGURATION
// ============================================================

const int DIR_PIN1 = 2;
const int STEP_PIN1 = 3;
const int EN_PIN1 = 4;

const int DIR_PIN2 = 8;
const int STEP_PIN2 = 9;
const int EN_PIN2 = 10;

// Level that ENABLES the TB6600 in the current wiring.
// Flip to HIGH if your drivers are wired the other way.
const bool EN_ACTIVE_LEVEL = LOW;
const bool EN_INACTIVE_LEVEL = HIGH;

// ============================================================
// SECTION 2 - MOTION TUNING
// ============================================================

// Half-period of the step pulse, in microseconds.
// Smaller = faster. Too small and the motor will stall or skip.
unsigned int STEP_DELAY = 500;

// How many steps a single command moves.
// Not const on purpose, so it is easy to change here or wire up
// a serial command later to update it live while testing.
int stepsPerMove = 125;

// Settle time after changing a DIR pin before the first step pulse.
const unsigned int DIR_SETTLE_MS = 5;

// ============================================================
// SECTION 3 - MOTOR DIRECTION POLARITY
// ============================================================
//
// Motor 1 and Motor 2 may have different direction polarity because
// of motor mounting or because one coil pair was reversed.
//
// If ONE motor spins the wrong way, swap only that motor's two
// values below. Do NOT rewire the motor coils again.

const bool MOTOR1_CW = HIGH;
const bool MOTOR1_CCW = LOW;

const bool MOTOR2_CW = LOW;
const bool MOTOR2_CCW = HIGH;

// ============================================================
// SECTION 4 - AXIS DEFINITIONS
// ============================================================
//
// Axis identifiers, used to pair a movement with its limit switch.

const uint8_t AXIS_X = 0;
const uint8_t AXIS_Y = 1;

// Sign convention: -1 = negative direction, +1 = positive direction.
const int8_t DIR_NEG = -1;
const int8_t DIR_POS = +1;

// ============================================================
// SECTION 5 - MOVEMENT TABLE  (the direction / label mapping)
// ============================================================
//
// This is the single place where "command number" -> "what the
// machine actually does" is defined. Change a row here and the
// labels, limit checks, and counters all follow automatically.
//
//   label : text printed to serial
//   dir1  : DIR level sent to Motor 1
//   dir2  : DIR level sent to Motor 2
//   axis  : which limit switch guards this move
//   sign  : which end of that axis this move travels toward

struct MoveDef
{
    const char *label;
    bool dir1;
    bool dir2;
    uint8_t axis;
    int8_t sign;
};

const uint8_t MOVE_COUNT = 4;

const MoveDef MOVES[MOVE_COUNT] = {
    // Command '1'
    {"Y-", MOTOR1_CW, MOTOR2_CW, AXIS_Y, DIR_NEG},
    // Command '2'
    {"X-", MOTOR1_CW, MOTOR2_CCW, AXIS_X, DIR_NEG},
    // Command '3'
    {"X+", MOTOR1_CCW, MOTOR2_CW, AXIS_X, DIR_POS},
    // Command '4'
    {"Y+", MOTOR1_CCW, MOTOR2_CCW, AXIS_Y, DIR_POS}};

// ============================================================
// SECTION 6 - LIMIT SWITCH CONFIGURATION
// ============================================================

// --- Pins ---
// Pin 30 -> X AXIS limit switch
// Pin 31 -> Y AXIS limit switch
const int LIMIT_PIN_X = 30;
const int LIMIT_PIN_Y = 31;

// --- Switch wiring type ---
// true  = NC (normally closed): pressed opens the circuit -> pin reads HIGH
// false = NO (normally open):   pressed closes to GND     -> pin reads LOW
// Both use INPUT_PULLUP.
const bool LIMIT_X_USE_NC = true;
const bool LIMIT_Y_USE_NC = true;

// --- Where each switch is physically mounted ---
// This decides WHICH direction the switch blocks.
// DIR_NEG = switch sits at the negative end of travel (X- / Y-)
// DIR_POS = switch sits at the positive end of travel (X+ / Y+)
const int8_t LIMIT_X_AT_END = DIR_NEG; // X switch is at the X- end
const int8_t LIMIT_Y_AT_END = DIR_NEG; // Y switch is at the Y- end

// --- Master enable ---
// Set false to ignore an axis' switch entirely (bench testing with
// nothing wired to the pin, etc.).
const bool LIMIT_X_ENABLED = true;
const bool LIMIT_Y_ENABLED = true;

// --- Noise rejection ---
// A hit must survive a second read this many microseconds later
// before it is believed. Keep small: this runs between step pulses.
const unsigned int LIMIT_CONFIRM_US = 200;

// Check the switch every N steps. 1 = check before every single
// pulse (safest). Raise it only if you need faster step rates.
const uint8_t LIMIT_CHECK_EVERY_N_STEPS = 1;

// Debounce used for the slower startup / status reads.
const unsigned int LIMIT_DEBOUNCE_MS = 100;

// ============================================================
// SECTION 7 - STEP COUNTER CONFIGURATION
// ============================================================
//
// Counters increment once per step pulse ACTUALLY sent, so an
// aborted move only counts the steps the machine really made.
// Index matches the MOVES table above: 0=Y-, 1=X-, 2=X+, 3=Y+

unsigned long stepCounts[MOVE_COUNT] = {0, 0, 0, 0};

// Optional distance readout in the counter report.
// Set SHOW_DISTANCE to false to print raw steps only.
const bool SHOW_DISTANCE = false;
const float STEPS_PER_UNIT = 200.0; // steps per mm (or per whatever unit)
const char *DISTANCE_UNIT = "mm";

// ============================================================
// SECTION 8 - COMMAND NUMBERS
// ============================================================

const char CMD_MOVE_FIRST = '1'; // '1'..'4' are the four moves
const char CMD_MOVE_LAST = '4';
const char CMD_SHOW_COUNTS = '5';
const char CMD_RESET_COUNTS = '6';
const char CMD_MOTORS_OFF = '7';

// ============================================================
// SETUP
// ============================================================

void setup()
{
    pinMode(DIR_PIN1, OUTPUT);
    pinMode(STEP_PIN1, OUTPUT);
    pinMode(EN_PIN1, OUTPUT);

    pinMode(DIR_PIN2, OUTPUT);
    pinMode(STEP_PIN2, OUTPUT);
    pinMode(EN_PIN2, OUTPUT);

    // Limit switches: internal pull-ups, works for both NC and NO wiring
    pinMode(LIMIT_PIN_X, INPUT_PULLUP);
    pinMode(LIMIT_PIN_Y, INPUT_PULLUP);

    digitalWrite(STEP_PIN1, LOW);
    digitalWrite(STEP_PIN2, LOW);

    disableMotors(); // start idle; motors energize only on a command

    Serial.begin(9600);
    delay(1000); // let the switch lines settle before first read

    printInstructions();
    printLimitStatus();
}

// ============================================================
// MAIN LOOP
// ============================================================

void loop()
{
    checkSerial();
    // Nothing else runs here. Motors move only in response to a
    // command, and each command moves exactly stepsPerMove steps
    // (or fewer, if a limit switch stops it early).
}

void checkSerial()
{
    while (Serial.available() > 0)
    {
        char command = Serial.read();
        handleCommand(command);
    }
}

void handleCommand(char command)
{
    if (command >= CMD_MOVE_FIRST && command <= CMD_MOVE_LAST)
    {
        uint8_t index = command - CMD_MOVE_FIRST; // '1' -> 0, '2' -> 1, ...
        executeMove(index);
        return;
    }

    switch (command)
    {
    case CMD_SHOW_COUNTS:
        printStepCounts();
        break;

    case CMD_RESET_COUNTS:
        resetStepCounts();
        break;

    case CMD_MOTORS_OFF:
        disableMotors();
        Serial.println();
        Serial.println("MOTORS OFF (holding torque released)");
        break;

    default:
        // Ignore newlines, spaces, and anything unrecognized.
        break;
    }
}

// ============================================================
// MOVEMENT
// ============================================================

void executeMove(uint8_t index)
{
    const MoveDef &m = MOVES[index];

    Serial.println();
    Serial.print("COMMAND: ");
    Serial.println(m.label);

    // Refuse to start if we are already sitting on the switch
    // for this direction.
    if (isMoveBlocked(m.axis, m.sign))
    {
        Serial.print("  BLOCKED - ");
        Serial.print(axisName(m.axis));
        Serial.println(" limit switch is active in this direction.");
        Serial.println("  Move the opposite way to back off the switch.");
        return;
    }

    setDirection(m.dir1, m.dir2);

    unsigned long moved = moveSteps(stepsPerMove, m.axis, m.sign);

    // Count only what actually happened.
    stepCounts[index] += moved;

    Serial.print("  Moved ");
    Serial.print(moved);
    Serial.print(" of ");
    Serial.print(stepsPerMove);
    Serial.print(" steps  [");
    Serial.print(m.label);
    Serial.println("]");

    if (moved < (unsigned long)stepsPerMove)
    {
        Serial.print("  STOPPED EARLY - ");
        Serial.print(axisName(m.axis));
        Serial.println(" limit switch tripped during the move.");
    }
}

// Sends step pulses, checking the relevant limit switch as it goes.
// Returns the number of pulses actually sent.
unsigned long moveSteps(int steps, uint8_t axis, int8_t sign)
{
    enableMotors();

    unsigned long done = 0;
    uint8_t counter = 0;

    for (int i = 0; i < steps; i++)
    {

        // Limit check before each pulse (or every N pulses).
        if (counter == 0)
        {
            if (isMoveBlocked(axis, sign))
            {
                break;
            }
        }
        counter++;
        if (counter >= LIMIT_CHECK_EVERY_N_STEPS)
        {
            counter = 0;
        }

        digitalWrite(STEP_PIN1, HIGH);
        digitalWrite(STEP_PIN2, HIGH);
        delayMicroseconds(STEP_DELAY);

        digitalWrite(STEP_PIN1, LOW);
        digitalWrite(STEP_PIN2, LOW);
        delayMicroseconds(STEP_DELAY);

        done++;
    }

    // Motors stay enabled after the move to hold position.
    // Send '7' to release holding torque.
    return done;
}

void setDirection(bool dir1, bool dir2)
{
    digitalWrite(DIR_PIN1, dir1);
    digitalWrite(DIR_PIN2, dir2);
    delay(DIR_SETTLE_MS); // let the TB6600 register DIR before stepping
}

void enableMotors()
{
    digitalWrite(EN_PIN1, EN_ACTIVE_LEVEL);
    digitalWrite(EN_PIN2, EN_ACTIVE_LEVEL);
}

void disableMotors()
{
    digitalWrite(STEP_PIN1, LOW);
    digitalWrite(STEP_PIN2, LOW);

    digitalWrite(EN_PIN1, EN_INACTIVE_LEVEL);
    digitalWrite(EN_PIN2, EN_INACTIVE_LEVEL);
}

// ============================================================
// LIMIT SWITCHES
// ============================================================

// Translates a raw pin reading into "is the switch pressed?"
bool interpretLimit(int pinState, bool useNC)
{
    if (useNC)
    {
        // NC: pressing opens the circuit, pull-up takes the pin HIGH
        return pinState == HIGH;
    }
    else
    {
        // NO: pressing closes the circuit to GND, pin goes LOW
        return pinState == LOW;
    }
}

// Reads one axis' switch twice to reject electrical noise.
bool isLimitHit(uint8_t axis)
{
    int pin;
    bool useNC;
    bool enabled;

    if (axis == AXIS_X)
    {
        pin = LIMIT_PIN_X;
        useNC = LIMIT_X_USE_NC;
        enabled = LIMIT_X_ENABLED;
    }
    else
    {
        pin = LIMIT_PIN_Y;
        useNC = LIMIT_Y_USE_NC;
        enabled = LIMIT_Y_ENABLED;
    }

    if (!enabled)
    {
        return false; // this axis' switch is turned off in config
    }

    if (!interpretLimit(digitalRead(pin), useNC))
    {
        return false;
    }

    // Confirm the hit with a second read.
    delayMicroseconds(LIMIT_CONFIRM_US);
    return interpretLimit(digitalRead(pin), useNC);
}

// A switch only blocks the direction that drives INTO it.
// Moving away from a tripped switch is always allowed.
bool isMoveBlocked(uint8_t axis, int8_t sign)
{
    int8_t blockedSign = (axis == AXIS_X) ? LIMIT_X_AT_END : LIMIT_Y_AT_END;

    if (sign != blockedSign)
    {
        return false; // moving away from the switch, always permitted
    }

    return isLimitHit(axis);
}

const char *axisName(uint8_t axis)
{
    return (axis == AXIS_X) ? "X" : "Y";
}

void printLimitStatus()
{
    Serial.println();
    Serial.println("--- LIMIT SWITCH STATUS ---");

    Serial.print("X (pin ");
    Serial.print(LIMIT_PIN_X);
    Serial.print(", ");
    Serial.print(LIMIT_X_USE_NC ? "NC" : "NO");
    Serial.print(", guards X");
    Serial.print(LIMIT_X_AT_END == DIR_NEG ? "-" : "+");
    Serial.print("): ");
    if (!LIMIT_X_ENABLED)
        Serial.println("DISABLED IN CONFIG");
    else if (isLimitHit(AXIS_X))
        Serial.println("*** LIMIT HIT ***");
    else
        Serial.println("clear");

    Serial.print("Y (pin ");
    Serial.print(LIMIT_PIN_Y);
    Serial.print(", ");
    Serial.print(LIMIT_Y_USE_NC ? "NC" : "NO");
    Serial.print(", guards Y");
    Serial.print(LIMIT_Y_AT_END == DIR_NEG ? "-" : "+");
    Serial.print("): ");
    if (!LIMIT_Y_ENABLED)
        Serial.println("DISABLED IN CONFIG");
    else if (isLimitHit(AXIS_Y))
        Serial.println("*** LIMIT HIT ***");
    else
        Serial.println("clear");
}

// ============================================================
// STEP COUNTERS
// ============================================================

void resetStepCounts()
{
    for (uint8_t i = 0; i < MOVE_COUNT; i++)
    {
        stepCounts[i] = 0;
    }
    Serial.println();
    Serial.println("STEP COUNTERS RESET TO ZERO");
}

// Signed net travel on one axis, in steps.
long netSteps(uint8_t axis)
{
    long net = 0;
    for (uint8_t i = 0; i < MOVE_COUNT; i++)
    {
        if (MOVES[i].axis == axis)
        {
            net += (long)stepCounts[i] * MOVES[i].sign;
        }
    }
    return net;
}

void printStepCounts()
{
    Serial.println();
    Serial.println("======================================");
    Serial.println("STEP COUNTERS (since power-on / reset)");
    Serial.println("======================================");

    for (uint8_t i = 0; i < MOVE_COUNT; i++)
    {
        Serial.print("  ");
        Serial.print(MOVES[i].label);
        Serial.print("\t: ");
        Serial.print(stepCounts[i]);
        Serial.println(" steps");
    }

    Serial.println("--------------------------------------");
    printNetLine("X", netSteps(AXIS_X));
    printNetLine("Y", netSteps(AXIS_Y));
    Serial.println("======================================");

    printLimitStatus();
}

void printNetLine(const char *axisLabel, long net)
{
    Serial.print("  NET ");
    Serial.print(axisLabel);
    Serial.print("\t: ");
    if (net > 0)
        Serial.print("+");
    Serial.print(net);
    Serial.print(" steps");

    if (SHOW_DISTANCE)
    {
        Serial.print("  (");
        Serial.print(net / STEPS_PER_UNIT, 3);
        Serial.print(" ");
        Serial.print(DISTANCE_UNIT);
        Serial.print(")");
    }
    Serial.println();
}

// ============================================================
// HELP TEXT
// ============================================================

void printInstructions()
{
    Serial.println("======================================");
    Serial.println("Dual TB6600 CNC Step Test - MEGA 2560");
    Serial.println("======================================");
    Serial.print("Step size per command: ");
    Serial.println(stepsPerMove);
    Serial.println("--------------------------------------");
    Serial.println("1 = Y-   (M1 CW  / M2 CW )");
    Serial.println("2 = X-   (M1 CW  / M2 CCW)");
    Serial.println("3 = X+   (M1 CCW / M2 CW )");
    Serial.println("4 = Y+   (M1 CCW / M2 CCW)");
    Serial.println("5 = Show step counters");
    Serial.println("6 = Reset step counters");
    Serial.println("7 = Disable both motors");
    Serial.println("======================================");
}
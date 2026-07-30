/*
  ============================================================
  Dual TB6600 + Arduino MEGA 2560
  CNC-style step testing with limit switches, SOFTWARE limits,
  live position tracking and step counters
  ============================================================

  Each serial command moves a fixed number of steps along a labeled
  axis direction, then stops and holds position.

  SERIAL COMMANDS
    1 = Y-   (Motor 1 CW  / Motor 2 CCW)   <-- physical limit switch end
    2 = Y+   (Motor 1 CCW / Motor 2 CW )   <-- SOFTWARE limit end
    3 = X-   (Motor 1 CW  / Motor 2 CW )   <-- physical limit switch end
    4 = X+   (Motor 1 CCW / Motor 2 CCW)   <-- SOFTWARE limit end
    5 = Show step counters + position + limit status
    6 = Reset step counters to zero
    7 = Disable both motors (release holding torque)
    8 = ZERO the position counters (set "here" as origin 0,0)

  VERIFIED MOTOR / AXIS MAPPING
    These pairings were confirmed by physical testing on the machine:
      M1 CW  + M2 CW   ->  X-
      M1 CW  + M2 CCW  ->  Y-
      M1 CCW + M2 CW   ->  Y+
      M1 CCW + M2 CCW  ->  X+

  PHYSICAL LIMIT SWITCHES
    Pin 30 = X AXIS limit switch, mounted at the X- end of travel
    Pin 31 = Y AXIS limit switch, mounted at the Y- end of travel

  SOFTWARE LIMITS  (the ends with NO switch fitted)
    X+ end : 1295 steps of travel allowed from origin
    Y+ end : infinite (disabled) for now

    A software limit works exactly like a switch: it blocks ONLY the
    direction that drives into it. Moving back the other way is always
    allowed, and doing so re-arms the limit automatically.

  POSITION TRACKING
    axisPos[] is the signed position in steps, updated once per pulse
    ACTUALLY sent. Origin (0) is wherever the machine sat at power-on,
    unless you re-zero it with command 8 or let a physical switch
    auto-zero it (see SOFT_ZERO_ON_LIMIT_HIT below).

  ============================================================
*/

// ============================================================
// SECTION 1 - MOTOR PIN CONFIGURATION
// ============================================================

// IMPORTANT: The driver wired to pins 2/3 (DIR_PIN1/STEP_PIN1) actually
// drives CW on ACTIVE HIGH, not active low like the others. Its coil
// wiring was physically reversed to compensate - do not "fix" this pin
// polarity in software without re-checking the physical wiring first.
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
// Motor 1 and Motor 2 have different direction polarity because of
// motor mounting / reversed coil pair.
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

const uint8_t AXIS_X = 0;
const uint8_t AXIS_Y = 1;
const uint8_t AXIS_COUNT = 2;

// Sign convention: -1 = negative direction, +1 = positive direction.
const int8_t DIR_NEG = -1;
const int8_t DIR_POS = +1;

// ============================================================
// SECTION 5 - MOVEMENT TABLE  (command -> direction mapping)
// ============================================================
//
// This is the single place where "command number" -> "what the
// machine actually does" is defined. Change a row here and the
// labels, limit checks, counters and position all follow.
//
//   label : text printed to serial
//   dir1  : DIR level sent to Motor 1
//   dir2  : DIR level sent to Motor 2
//   axis  : which axis this move belongs to
//   sign  : which end of that axis this move travels toward
//
// Row order sets the command numbers: row 0 = '1', row 1 = '2', etc.

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
    // Command '1'  -  toward the Y limit switch (pin 31)
    {"Y-", MOTOR1_CW, MOTOR2_CCW, AXIS_Y, DIR_NEG},

    // Command '2'  -  away from the Y switch, toward the Y SOFT limit
    {"Y+", MOTOR1_CCW, MOTOR2_CW, AXIS_Y, DIR_POS},

    // Command '3'  -  toward the X limit switch (pin 30)
    {"X-", MOTOR1_CW, MOTOR2_CW, AXIS_X, DIR_NEG},

    // Command '4'  -  away from the X switch, toward the X SOFT limit
    {"X+", MOTOR1_CCW, MOTOR2_CCW, AXIS_X, DIR_POS}};

// ============================================================
// SECTION 6 - PHYSICAL LIMIT SWITCH CONFIGURATION
// ============================================================

// --- Pins ---
const int LIMIT_PIN_X = 30; // X AXIS limit switch
const int LIMIT_PIN_Y = 31; // Y AXIS limit switch

// --- Switch wiring type ---
// true  = NC (normally closed): pressed opens the circuit -> pin reads HIGH
// false = NO (normally open):   pressed closes to GND     -> pin reads LOW
// Both use INPUT_PULLUP.
const bool LIMIT_X_USE_NC = true;
const bool LIMIT_Y_USE_NC = true;

// --- Where each switch is physically mounted ---
const int8_t LIMIT_X_AT_END = DIR_NEG; // X switch is at the X- end
const int8_t LIMIT_Y_AT_END = DIR_NEG; // Y switch is at the Y- end

// --- Master enable ---
const bool LIMIT_X_ENABLED = true;
const bool LIMIT_Y_ENABLED = true;

// --- Noise rejection ---
const unsigned int LIMIT_CONFIRM_US = 200;

// Check limits every N steps. 1 = check before every single
// pulse (safest). Raise it only if you need faster step rates.
// This governs the SOFTWARE limit check too.
const uint8_t LIMIT_CHECK_EVERY_N_STEPS = 1;

// ============================================================
// SECTION 6B - SOFTWARE LIMIT CONFIGURATION   <<< NEW
// ============================================================
//
// A software limit replaces a switch on the end of travel where no
// switch is fitted. It is purely a step count: once the axis position
// reaches the cap in the guarded direction, further steps that way
// are refused. Steps the other way are always allowed and immediately
// give the travel back.
//
// ------------------------------------------------------------
//   THE TWO NUMBERS YOU WILL ACTUALLY TUNE
// ------------------------------------------------------------
//   Units are STEPS, measured from origin (position 0).
//   Set to SOFT_LIMIT_INFINITE (0) to disable that axis' soft limit.

const long SOFT_LIMIT_INFINITE = 0; // sentinel: no cap at all

long SOFT_LIMIT_X_TRAVEL = 1295;              // X+ travel cap, in steps
long SOFT_LIMIT_Y_TRAVEL = 2550; // Y+ : infinite for now

// ------------------------------------------------------------
//   WHICH END EACH SOFTWARE LIMIT GUARDS
// ------------------------------------------------------------
// Normally the opposite end from the physical switch, so the two
// together fence in the full travel of the axis.
//   DIR_NEG -> caps how far NEGATIVE the axis may go (pos >= -cap)
//   DIR_POS -> caps how far POSITIVE the axis may go (pos <= +cap)

const int8_t SOFT_LIMIT_X_AT_END = DIR_POS; // guards the X+ end
const int8_t SOFT_LIMIT_Y_AT_END = DIR_POS; // guards the Y+ end

// ------------------------------------------------------------
//   MASTER ENABLES
// ------------------------------------------------------------
// Independent of the travel value, so you can switch the whole
// feature off for bench testing without losing your tuned number.

const bool SOFT_LIMIT_X_ENABLED = true;
const bool SOFT_LIMIT_Y_ENABLED = true;

// ------------------------------------------------------------
//   BEHAVIOUR OPTIONS
// ------------------------------------------------------------

// Re-zero an axis automatically the moment its PHYSICAL switch trips.
// This turns the switch into a homing reference, which makes the
// software limit on the far end meaningful even after lost steps.
// The axis is zeroed to the switch end, so a switch at the + end
// sets position 0 there and all travel away from it reads negative.
const bool SOFT_ZERO_ON_LIMIT_HIT = true;

// Print a one-line warning when a soft limit stops a move.
const bool SOFT_LIMIT_VERBOSE = true;

// ============================================================
// SECTION 7 - STEP COUNTER / POSITION CONFIGURATION
// ============================================================
//
// Counters increment once per step pulse ACTUALLY sent, so an
// aborted move only counts the steps the machine really made.
// Index matches the MOVES table above: 0=Y-, 1=Y+, 2=X-, 3=X+

unsigned long stepCounts[MOVE_COUNT] = {0, 0, 0, 0};

// Live signed position per axis, in steps. This is what the
// software limits are compared against.
long axisPos[AXIS_COUNT] = {0, 0};

// Optional distance readout in the counter report.
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
const char CMD_ZERO_POSITION = '8';

// ============================================================
// BLOCK REASONS
// ============================================================

const uint8_t BLOCK_NONE = 0;
const uint8_t BLOCK_PHYSICAL = 1;
const uint8_t BLOCK_SOFTWARE = 2;

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
    pinMode(LIMIT_PIN_X, INPUT_PULLUP); // X axis switch, X- end
    pinMode(LIMIT_PIN_Y, INPUT_PULLUP); // Y axis switch, Y- end

    digitalWrite(STEP_PIN1, LOW);
    digitalWrite(STEP_PIN2, LOW);

    disableMotors(); // start idle; motors energize only on a command

    Serial.begin(9600);
    delay(1000); // let the switch lines settle before first read

    printInstructions();
    printLimitStatus();
    printSoftLimitStatus();
}

// ============================================================
// MAIN LOOP
// ============================================================

void loop()
{
    checkSerial();
    // Nothing else runs here. Motors move only in response to a
    // command, and each command moves exactly stepsPerMove steps
    // (or fewer, if a limit stops it early).
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

    case CMD_ZERO_POSITION:
        zeroPosition();
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

    // Refuse to start if we are already against a limit in this
    // direction (physical switch OR software cap).
    uint8_t blocked = blockReason(m.axis, m.sign);
    if (blocked != BLOCK_NONE)
    {
        printBlockMessage(blocked, m.axis, m.sign);
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
    Serial.print("]  pos ");
    Serial.print(axisName(m.axis));
    Serial.print(" = ");
    Serial.println(axisPos[m.axis]);

    if (moved < (unsigned long)stepsPerMove)
    {
        uint8_t why = blockReason(m.axis, m.sign);
        Serial.print("  STOPPED EARLY - ");
        if (why == BLOCK_SOFTWARE)
        {
            Serial.print(axisName(m.axis));
            Serial.println(" SOFTWARE limit reached during the move.");
        }
        else
        {
            Serial.print(axisName(m.axis));
            Serial.println(" limit switch tripped during the move.");
        }
    }
}

// Sends step pulses, checking limits as it goes.
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
            if (blockReason(axis, sign) != BLOCK_NONE)
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

        // The pulse really happened - move the position with it.
        axisPos[axis] += sign;
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
// PHYSICAL LIMIT SWITCHES
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
        pin = LIMIT_PIN_X; // pin 30
        useNC = LIMIT_X_USE_NC;
        enabled = LIMIT_X_ENABLED;
    }
    else
    {
        pin = LIMIT_PIN_Y; // pin 31
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

int8_t limitEndOf(uint8_t axis)
{
    return (axis == AXIS_X) ? LIMIT_X_AT_END : LIMIT_Y_AT_END;
}

// A switch only blocks the direction that drives INTO it.
bool isPhysicalBlocked(uint8_t axis, int8_t sign)
{
    if (sign != limitEndOf(axis))
    {
        return false; // moving away from the switch, always permitted
    }

    if (!isLimitHit(axis))
    {
        return false;
    }

    // Optional homing behaviour: the switch is a known reference,
    // so treat it as position zero for this axis.
    if (SOFT_ZERO_ON_LIMIT_HIT)
    {
        axisPos[axis] = 0;
    }

    return true;
}

// ============================================================
// SOFTWARE LIMITS
// ============================================================

// Which end of this axis the software limit guards.
int8_t softEndOf(uint8_t axis)
{
    return (axis == AXIS_X) ? SOFT_LIMIT_X_AT_END : SOFT_LIMIT_Y_AT_END;
}

// The travel cap for this axis, in steps. 0 = infinite.
long softTravelOf(uint8_t axis)
{
    return (axis == AXIS_X) ? SOFT_LIMIT_X_TRAVEL : SOFT_LIMIT_Y_TRAVEL;
}

bool softEnabledOn(uint8_t axis)
{
    bool enabled = (axis == AXIS_X) ? SOFT_LIMIT_X_ENABLED : SOFT_LIMIT_Y_ENABLED;
    return enabled && softTravelOf(axis) != SOFT_LIMIT_INFINITE;
}

// How many more steps this axis may travel in the given direction
// before the software limit stops it. Returns -1 for "unlimited".
long softStepsRemaining(uint8_t axis, int8_t sign)
{
    if (!softEnabledOn(axis))
    {
        return -1;
    }
    if (sign != softEndOf(axis))
    {
        return -1; // moving away from the cap is never restricted
    }

    long cap = softTravelOf(axis);
    long travelled = axisPos[axis] * sign; // distance toward the capped end
    long remaining = cap - travelled;

    return (remaining > 0) ? remaining : 0;
}

// Mirrors isPhysicalBlocked, but for the counted limit.
bool isSoftBlocked(uint8_t axis, int8_t sign)
{
    long remaining = softStepsRemaining(axis, sign);
    if (remaining < 0)
    {
        return false; // unlimited in this direction
    }
    return remaining == 0;
}

// ============================================================
// COMBINED LIMIT CHECK
// ============================================================
//
// Physical switch wins over the software cap when both would fire,
// because the switch is real hardware and the cap is only a guess.

uint8_t blockReason(uint8_t axis, int8_t sign)
{
    if (isPhysicalBlocked(axis, sign))
    {
        return BLOCK_PHYSICAL;
    }
    if (isSoftBlocked(axis, sign))
    {
        return BLOCK_SOFTWARE;
    }
    return BLOCK_NONE;
}

void printBlockMessage(uint8_t reason, uint8_t axis, int8_t sign)
{
    if (reason == BLOCK_SOFTWARE)
    {
        Serial.print("  BLOCKED - ");
        Serial.print(axisName(axis));
        Serial.print(" SOFTWARE limit reached (");
        Serial.print(softTravelOf(axis));
        Serial.println(" steps of travel used).");
        if (SOFT_LIMIT_VERBOSE)
        {
            Serial.print("  Position ");
            Serial.print(axisName(axis));
            Serial.print(" = ");
            Serial.print(axisPos[axis]);
            Serial.println(". Move the opposite way to free travel.");
        }
    }
    else
    {
        Serial.print("  BLOCKED - ");
        Serial.print(axisName(axis));
        Serial.println(" limit switch is active in this direction.");
        Serial.println("  Move the opposite way to back off the switch.");
    }
}

const char *axisName(uint8_t axis)
{
    return (axis == AXIS_X) ? "X" : "Y";
}

const char *signName(int8_t sign)
{
    return (sign == DIR_NEG) ? "-" : "+";
}

// ============================================================
// STATUS REPORTS
// ============================================================

void printLimitStatus()
{
    Serial.println();
    Serial.println("--- PHYSICAL LIMIT SWITCHES ---");

    Serial.print("X (pin ");
    Serial.print(LIMIT_PIN_X);
    Serial.print(", ");
    Serial.print(LIMIT_X_USE_NC ? "NC" : "NO");
    Serial.print(", guards X");
    Serial.print(signName(LIMIT_X_AT_END));
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
    Serial.print(signName(LIMIT_Y_AT_END));
    Serial.print("): ");
    if (!LIMIT_Y_ENABLED)
        Serial.println("DISABLED IN CONFIG");
    else if (isLimitHit(AXIS_Y))
        Serial.println("*** LIMIT HIT ***");
    else
        Serial.println("clear");
}

void printSoftLimitLine(uint8_t axis)
{
    Serial.print(axisName(axis));
    Serial.print(" (guards ");
    Serial.print(axisName(axis));
    Serial.print(signName(softEndOf(axis)));
    Serial.print("): ");

    if (!softEnabledOn(axis))
    {
        Serial.println("INFINITE / disabled");
        return;
    }

    long remaining = softStepsRemaining(axis, softEndOf(axis));

    Serial.print("cap ");
    Serial.print(softTravelOf(axis));
    Serial.print(" steps, ");
    Serial.print(remaining);
    Serial.print(" left");
    if (remaining == 0)
        Serial.println("  *** AT SOFT LIMIT ***");
    else
        Serial.println();
}

void printSoftLimitStatus()
{
    Serial.println();
    Serial.println("--- SOFTWARE LIMITS ---");
    printSoftLimitLine(AXIS_X);
    printSoftLimitLine(AXIS_Y);
}

void printPosition()
{
    Serial.println("--------------------------------------");
    for (uint8_t a = 0; a < AXIS_COUNT; a++)
    {
        Serial.print("  POS ");
        Serial.print(axisName(a));
        Serial.print("\t: ");
        if (axisPos[a] > 0)
            Serial.print("+");
        Serial.print(axisPos[a]);
        Serial.print(" steps");

        if (SHOW_DISTANCE)
        {
            Serial.print("  (");
            Serial.print(axisPos[a] / STEPS_PER_UNIT, 3);
            Serial.print(" ");
            Serial.print(DISTANCE_UNIT);
            Serial.print(")");
        }
        Serial.println();
    }
}

// ============================================================
// STEP COUNTERS / POSITION
// ============================================================

void resetStepCounts()
{
    for (uint8_t i = 0; i < MOVE_COUNT; i++)
    {
        stepCounts[i] = 0;
    }
    Serial.println();
    Serial.println("STEP COUNTERS RESET TO ZERO");
    Serial.println("(position and software limits are NOT affected - use 8)");
}

void zeroPosition()
{
    for (uint8_t a = 0; a < AXIS_COUNT; a++)
    {
        axisPos[a] = 0;
    }
    Serial.println();
    Serial.println("POSITION ZEROED - this point is now the origin");
    printSoftLimitStatus();
}

// Signed net travel on one axis, in steps (from the counters).
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
    printPosition();
    Serial.println("======================================");

    printLimitStatus();
    printSoftLimitStatus();
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
    Serial.println("1 = Y-   (M1 CW  / M2 CCW)  [limit: pin 31]");
    Serial.println("2 = Y+   (M1 CCW / M2 CW )  [soft limit]");
    Serial.println("3 = X-   (M1 CW  / M2 CW )  [limit: pin 30]");
    Serial.println("4 = X+   (M1 CCW / M2 CCW)  [soft limit]");
    Serial.println("5 = Show counters / position / limits");
    Serial.println("6 = Reset step counters");
    Serial.println("7 = Disable both motors");
    Serial.println("8 = Zero position (set origin here)");
    Serial.println("======================================");
}
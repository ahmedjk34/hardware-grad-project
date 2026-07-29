/*
  ============================================================
  Dual TB6600 + Arduino MEGA 2560
  CNC-style step testing with limit switches, SOFTWARE limits,
  live position tracking, step counters, and GRID ADDRESSING

  Plus a THIRD, independent motor driving a Z axis (single motor,
  not coupled to the X/Y pair).
  ============================================================

  SERIAL COMMANDS
    1 = Y-   (Motor 1 CW  / Motor 2 CCW)   <-- physical limit switch end
    2 = Y+   (Motor 1 CCW / Motor 2 CW )   <-- SOFTWARE limit end
    3 = X-   (Motor 1 CW  / Motor 2 CW )   <-- physical limit switch end
    4 = X+   (Motor 1 CCW / Motor 2 CCW)   <-- SOFTWARE limit end
    5 = Show step counters + position + limit status
    6 = Reset step counters to zero
    7 = Disable both motors (release holding torque)
    8 = ZERO the position counters (set "here" as origin 0,0)
    9 = Show ASCII grid map + current cell
    0 = HOME / GO TO ORIGIN (drive into both switches, X/Y only)

    D = Z-   (Motor 3 CW )   <-- physical limit switch end
    U = Z+   (Motor 3 CCW)   <-- SOFTWARE limit end (starts at INFINITE)

    G <col> <row>   = go to grid cell (1-based). e.g.  G 3 5   or  G3,5
    S <cols> <rows> = change the grid division live. e.g.  S 20 39
    ?               = reprint the help text

  Multi-character commands need a newline. Single digit commands
  work with or without one. D and U are letters, so like G/S/? they
  need a newline too.

  Z is NOT part of homing (0) or the grid (G) yet - it is jogged
  independently with D/U. It still respects its own physical and
  software limits.

  ------------------------------------------------------------
  COORDINATE SYSTEM  (this is the important part)
  ------------------------------------------------------------
  SOFT_ZERO_ON_LIMIT_HIT is true, so each physical switch zeros its
  own axis the moment it trips. The corner where BOTH switches are
  pressed is therefore machine position (0, 0) = the ORIGIN.

  From that corner the machine travels in the SAME sign on both axes:

      X switch at the X- end  ->  X runs   0  ...  +1295   (soft limit)
      Y switch at the Y- end  ->  Y runs   0  ...  +2550   (soft limit)

  So the work envelope is 1295 x 2550 steps, living in the rectangle
  X in [0, +1295], Y in [0, +2550]. Grid indices hide this sign mess:

      col 1  = nearest the X switch (X = 0 side)
      col N  = far end of X travel  (X = +1295 side)
      row 1  = nearest the Y switch (Y = 0 side)
      row M  = far end of Y travel  (Y = +2550 side)

  Generalised in code as: each axis extends from 0 in the direction
  softEndOf(axis), for softTravelOf(axis) steps. Change the soft
  limits and the grid rescales itself automatically.

  ------------------------------------------------------------
  GO-TO SEQUENCE
  ------------------------------------------------------------
    1. Home Y into its switch, then home X into its switch  (= origin)
    2. Move Y to the target row
    3. Move X to the target column
  Re-homing every time means lost steps never accumulate.

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

// Z axis - single independent motor, not coupled to X/Y.
// No enable pin was specified for this driver, so it is left
// permanently enabled (only DIR/STEP are driven).
const int DIR_PIN3 = 11;
const int STEP_PIN3 = 12;

// Level that ENABLES the TB6600 in the current wiring.
const bool EN_ACTIVE_LEVEL = LOW;
const bool EN_INACTIVE_LEVEL = HIGH;

// ============================================================
// SECTION 2 - MOTION TUNINGD
// ============================================================

// Half-period of the step pulse, in microseconds.
unsigned int STEP_DELAY = 1000;

// How many steps a single MANUAL jog command (1-4) moves.
int stepsPerMove = 125;

// Settle time after changing a DIR pin before the first step pulse.
const unsigned int DIR_SETTLE_MS = 5;

// ============================================================
// SECTION 3 - MOTOR DIRECTION POLARITY
// ============================================================

const bool MOTOR1_CW = HIGH;
const bool MOTOR1_CCW = LOW;

const bool MOTOR2_CW = LOW;
const bool MOTOR2_CCW = HIGH;

// CW = -Z, CCW = +Z (per spec). Flip these two if the physical
// direction ends up reversed once wired up.
const bool MOTOR3_CW = LOW;
const bool MOTOR3_CCW = HIGH;

// ============================================================
// SECTION 4 - AXIS DEFINITIONS
// ============================================================

const uint8_t AXIS_X = 0;
const uint8_t AXIS_Y = 1;
const uint8_t AXIS_Z = 2;
const uint8_t AXIS_COUNT = 3;

const int8_t DIR_NEG = -1;
const int8_t DIR_POS = +1;

// ============================================================
// SECTION 5 - MOVEMENT TABLE  (command -> direction mapping)
// ============================================================

struct MoveDef
{
    const char *label;
    bool dir1; // DIR_PIN1 level (X/Y moves only)
    bool dir2; // DIR_PIN2 level (X/Y moves only)
    bool dir3; // DIR_PIN3 level (Z moves only)
    uint8_t axis;
    int8_t sign;
};

const uint8_t MOVE_COUNT = 6;

// X/Y entries pulse STEP_PIN1+STEP_PIN2 together (coupled drive).
// Z entries pulse STEP_PIN3 alone. See moveSteps().
const MoveDef MOVES[MOVE_COUNT] = {
    {"Y-", MOTOR1_CW, MOTOR2_CCW, false, AXIS_Y, DIR_NEG},
    {"Y+", MOTOR1_CCW, MOTOR2_CW, false, AXIS_Y, DIR_POS},
    {"X-", MOTOR1_CW, MOTOR2_CW, false, AXIS_X, DIR_NEG},
    {"X+", MOTOR1_CCW, MOTOR2_CCW, false, AXIS_X, DIR_POS},
    {"Z-", false, false, MOTOR3_CW, AXIS_Z, DIR_NEG},
    {"Z+", false, false, MOTOR3_CCW, AXIS_Z, DIR_POS}};

// ============================================================
// SECTION 6 - PHYSICAL LIMIT SWITCH CONFIGURATION
// ============================================================

const int LIMIT_PIN_X = 30; // X AXIS limit switch
const int LIMIT_PIN_Y = 31; // Y AXIS limit switch
const int LIMIT_PIN_Z = 28; // Z AXIS limit switch

const bool LIMIT_X_USE_NC = true;
const bool LIMIT_Y_USE_NC = true;
const bool LIMIT_Z_USE_NC = true;

const int8_t LIMIT_X_AT_END = DIR_NEG; // X switch is at the X- end
const int8_t LIMIT_Y_AT_END = DIR_NEG; // Y switch is at the Y- end
const int8_t LIMIT_Z_AT_END = DIR_NEG; // Z switch is at the Z- end (down)

const bool LIMIT_X_ENABLED = true;
const bool LIMIT_Y_ENABLED = true;
const bool LIMIT_Z_ENABLED = true;

const unsigned int LIMIT_CONFIRM_US = 200;
const uint8_t LIMIT_CHECK_EVERY_N_STEPS = 1;

// ============================================================
// SECTION 6B - SOFTWARE LIMIT CONFIGURATION
// ============================================================
//
// These two numbers ALSO define the size of the grid envelope.

const long SOFT_LIMIT_INFINITE = 0; // sentinel: no cap at all

long SOFT_LIMIT_X_TRAVEL = 1295;                // X+ travel cap, in steps
long SOFT_LIMIT_Y_TRAVEL = 2200;                // Y+ travel cap, in steps
long SOFT_LIMIT_Z_TRAVEL = 1400; // Z+ travel cap - in steps

const int8_t SOFT_LIMIT_X_AT_END = DIR_POS; // guards the X+ end
const int8_t SOFT_LIMIT_Y_AT_END = DIR_POS; // guards the Y+ end
const int8_t SOFT_LIMIT_Z_AT_END = DIR_POS; // guards the Z+ end (up)

const bool SOFT_LIMIT_X_ENABLED = true;
const bool SOFT_LIMIT_Y_ENABLED = true;
const bool SOFT_LIMIT_Z_ENABLED = true; // travel = INFINITE, so no cap yet

// Re-zero an axis automatically the moment its PHYSICAL switch trips.
// REQUIRED for the grid to mean anything - leave this true.
const bool SOFT_ZERO_ON_LIMIT_HIT = true;

const bool SOFT_LIMIT_VERBOSE = true;

// ============================================================
// SECTION 6C - GRID CONFIGURATION            <<< NEW
// ============================================================
//
// The envelope (1295 x 2550 steps) is divided into COLS x ROWS
// equal rectangles. The machine parks at the CENTRE of a cell.
//
// Cell size does NOT have to divide evenly into the travel. Targets
// are computed from the absolute position each time, so rounding
// error is always under one step and never accumulates.
//
// ------------------------------------------------------------
//   HOW FINE CAN THIS GO?
// ------------------------------------------------------------
//   Arithmetically the floor is 1 step per cell (1295 x 2550
//   = 3.3 million cells), which is meaningless - it is far below
//   what the machine can repeat mechanically.
//
//   If you want cells that are EXACTLY square in whole steps, the
//   limit is gcd(1295, 2550) = 5, giving 5x5 step cells and a
//   259 x 510 grid. That is the true "maximum" answer.
//
//   Practical near-square presets (cell sizes in steps):
//        COLS   ROWS   CELL (X x Y)   CELLS
//         10  x  20     129.5 x 127.5     200   <- default, readable
//         20  x  39      64.8 x  65.4     780
//         35  x  69      37.0 x  37.0    2415   <- very near perfect
//        259  x 510       5.0 x   5.0  132090   <- exact-square max
//
//   Change these here, or live with:  S <cols> <rows>

long GRID_COLS = 10;
long GRID_ROWS = 20;

const long GRID_COLS_MAX = 1295; // 1 step per cell
const long GRID_ROWS_MAX = 2550;

// The ASCII map is only drawn when the grid is small enough to be
// readable. Bigger grids print a numeric summary instead.
const long GRID_MAP_MAX_COLS = 48;
const long GRID_MAP_MAX_ROWS = 48;

// Last commanded cell. 0 = unknown / not on a cell.
long curCol = 0;
long curRow = 0;

// ============================================================
// SECTION 6D - HOMING CONFIGURATION           <<< NEW
// ============================================================

// Steps per homing chunk. Between chunks the switch is re-checked
// anyway by moveSteps, so this mostly controls report granularity.
const long HOME_CHUNK_STEPS = 200;

// Safety stop: if an axis has travelled this far without finding its
// switch, something is wrong (broken switch, unplugged, wrong pin).
const long HOME_MAX_STEPS_X = 1295L * 2 + 500;
const long HOME_MAX_STEPS_Y = 2550L * 2 + 500;

const bool HOME_VERBOSE = true;

// ============================================================
// SECTION 7 - STEP COUNTER / POSITION CONFIGURATION
// ============================================================

unsigned long stepCounts[MOVE_COUNT] = {0, 0, 0, 0, 0, 0};

long axisPos[AXIS_COUNT] = {0, 0, 0};

// True only after a successful home. Grid moves refuse to run
// before this, because the grid is nonsense without a real origin.
// (Z is set true the moment its physical switch trips, same as X/Y.)
bool axisHomed[AXIS_COUNT] = {false, false, false};

const bool SHOW_DISTANCE = false;
const float STEPS_PER_UNIT = 200.0;
const char *DISTANCE_UNIT = "mm";

// ============================================================
// SECTION 8 - COMMAND CHARACTERS
// ============================================================

const char CMD_MOVE_FIRST = '1';
const char CMD_MOVE_LAST = '4';
const char CMD_SHOW_COUNTS = '5';
const char CMD_RESET_COUNTS = '6';
const char CMD_MOTORS_OFF = '7';
const char CMD_ZERO_POSITION = '8';
const char CMD_SHOW_GRID = '9';
const char CMD_GO_ORIGIN = '0';

const char CMD_MOVE_Z_NEG = 'D'; // Z-  (software limit end)
const char CMD_MOVE_Z_POS = 'U'; // Z+  (physical limit switch end)

// ============================================================
// BLOCK REASONS
// ============================================================

const uint8_t BLOCK_NONE = 0;
const uint8_t BLOCK_PHYSICAL = 1;
const uint8_t BLOCK_SOFTWARE = 2;

// ============================================================
// SERIAL LINE BUFFER
// ============================================================

const uint8_t LINE_BUF_SIZE = 32;
char lineBuf[LINE_BUF_SIZE];
uint8_t lineLen = 0;

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

    pinMode(DIR_PIN3, OUTPUT);
    pinMode(STEP_PIN3, OUTPUT);

    pinMode(LIMIT_PIN_X, INPUT_PULLUP);
    pinMode(LIMIT_PIN_Y, INPUT_PULLUP);
    pinMode(LIMIT_PIN_Z, INPUT_PULLUP);

    digitalWrite(STEP_PIN1, LOW);
    digitalWrite(STEP_PIN2, LOW);
    digitalWrite(STEP_PIN3, LOW);

    disableMotors();

    Serial.begin(9600);
    delay(1000);

    printInstructions();
    printLimitStatus();
    printSoftLimitStatus();
    printGridConfig();

    Serial.println();
    Serial.println(">> Position is UNKNOWN until you home. Send 0 to home.");
}

// ============================================================
// MAIN LOOP
// ============================================================

void loop()
{
    checkSerial();
}

// ============================================================
// SERIAL PARSING
// ============================================================
//
// Single digits execute immediately (works with "No line ending").
// Anything else accumulates until newline, then gets parsed.

void checkSerial()
{
    while (Serial.available() > 0)
    {
        char c = Serial.read();

        if (c == '\n' || c == '\r')
        {
            if (lineLen > 0)
            {
                lineBuf[lineLen] = '\0';
                handleLine(lineBuf);
                lineLen = 0;
            }
            continue;
        }

        // Fast path: a lone digit with nothing buffered is a command.
        if (lineLen == 0 && c >= '0' && c <= '9')
        {
            handleSingleChar(c);
            continue;
        }

        if (c == ' ' && lineLen == 0)
        {
            continue; // ignore leading spaces
        }

        if (lineLen < LINE_BUF_SIZE - 1)
        {
            lineBuf[lineLen++] = c;
        }
        else
        {
            lineLen = 0; // overflow: drop the garbage line
            Serial.println("  ERROR - command too long, ignored.");
        }
    }
}

void handleLine(char *line)
{
    char head = line[0];

    if (head >= 'a' && head <= 'z')
    {
        head = head - 'a' + 'A';
    }

    // A single character on its own line behaves like the fast path.
    if (line[1] == '\0')
    {
        if (head == '?')
        {
            printInstructions();
            return;
        }
        handleSingleChar(head);
        return;
    }

    long a = 0, b = 0;

    switch (head)
    {
    case 'G':
        if (parseTwoNumbers(line + 1, &a, &b))
        {
            gotoCell(a, b);
        }
        else
        {
            Serial.println();
            Serial.println("  ERROR - use:  G <col> <row>   e.g.  G 3 5");
        }
        break;

    case 'S':
        if (parseTwoNumbers(line + 1, &a, &b))
        {
            setGridSize(a, b);
        }
        else
        {
            Serial.println();
            Serial.println("  ERROR - use:  S <cols> <rows>   e.g.  S 20 39");
        }
        break;

    default:
        Serial.println();
        Serial.print("  Unknown command: ");
        Serial.println(line);
        break;
    }
}

void handleSingleChar(char command)
{
    if (command >= CMD_MOVE_FIRST && command <= CMD_MOVE_LAST)
    {
        uint8_t index = command - CMD_MOVE_FIRST;
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

    case CMD_SHOW_GRID:
        printGrid();
        break;

    case CMD_GO_ORIGIN:
        goToOrigin();
        break;

    case CMD_MOVE_Z_NEG:
    {
        int8_t idx = findMoveIndex(AXIS_Z, DIR_NEG);
        if (idx >= 0)
        {
            executeMove((uint8_t)idx);
        }
        break;
    }

    case CMD_MOVE_Z_POS:
    {
        int8_t idx = findMoveIndex(AXIS_Z, DIR_POS);
        if (idx >= 0)
        {
            executeMove((uint8_t)idx);
        }
        break;
    }

    default:
        break;
    }
}

// Pulls two integers out of a string, ignoring any separators
// (space, comma, colon, etc). Returns false if two were not found.
bool parseTwoNumbers(const char *s, long *outA, long *outB)
{
    long values[2] = {0, 0};
    uint8_t found = 0;
    uint8_t i = 0;

    while (s[i] != '\0' && found < 2)
    {
        if (s[i] >= '0' && s[i] <= '9')
        {
            long v = 0;
            while (s[i] >= '0' && s[i] <= '9')
            {
                v = v * 10 + (s[i] - '0');
                i++;
            }
            values[found++] = v;
        }
        else
        {
            i++;
        }
    }

    if (found < 2)
    {
        return false;
    }

    *outA = values[0];
    *outB = values[1];
    return true;
}

// ============================================================
// MANUAL JOG MOVEMENT (commands 1-4)
// ============================================================

void executeMove(uint8_t index)
{
    const MoveDef &m = MOVES[index];

    Serial.println();
    Serial.print("COMMAND: ");
    Serial.println(m.label);

    uint8_t blocked = blockReason(m.axis, m.sign);
    if (blocked != BLOCK_NONE)
    {
        printBlockMessage(blocked, m.axis, m.sign);
        return;
    }

    setDirection(m.dir1, m.dir2, m.dir3);

    unsigned long moved = moveSteps(stepsPerMove, m.axis, m.sign);
    stepCounts[index] += moved;

    // A manual jog invalidates the "we are sitting on cell N" idea.
    // Z is not part of the X/Y grid, so a Z jog leaves the cell alone.
    if (m.axis != AXIS_Z)
    {
        curCol = 0;
        curRow = 0;
    }

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
        Serial.print(axisName(m.axis));
        if (why == BLOCK_SOFTWARE)
        {
            Serial.println(" SOFTWARE limit reached during the move.");
        }
        else
        {
            Serial.println(" limit switch tripped during the move.");
        }
    }
}

// Sends step pulses, checking limits as it goes.
// Z is an independent motor, so it pulses STEP_PIN3 alone; X/Y stay
// a coupled pair and pulse STEP_PIN1+STEP_PIN2 together.
// Returns the number of pulses actually sent.
unsigned long moveSteps(long steps, uint8_t axis, int8_t sign)
{
    enableMotors();

    unsigned long done = 0;
    uint8_t counter = 0;
    bool isZ = (axis == AXIS_Z);

    for (long i = 0; i < steps; i++)
    {
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

        if (isZ)
        {
            digitalWrite(STEP_PIN3, HIGH);
        }
        else
        {
            digitalWrite(STEP_PIN1, HIGH);
            digitalWrite(STEP_PIN2, HIGH);
        }
        delayMicroseconds(STEP_DELAY);

        if (isZ)
        {
            digitalWrite(STEP_PIN3, LOW);
        }
        else
        {
            digitalWrite(STEP_PIN1, LOW);
            digitalWrite(STEP_PIN2, LOW);
        }
        delayMicroseconds(STEP_DELAY);

        axisPos[axis] += sign;
        done++;
    }

    return done;
}

// Finds the MOVES row that drives the given axis in the given
// direction, so direction pins and counters stay in one place.
int8_t findMoveIndex(uint8_t axis, int8_t sign)
{
    for (uint8_t i = 0; i < MOVE_COUNT; i++)
    {
        if (MOVES[i].axis == axis && MOVES[i].sign == sign)
        {
            return (int8_t)i;
        }
    }
    return -1;
}

// Moves one axis by a signed number of steps, using the right
// direction pins and updating the right counter.
// Returns steps actually sent.
unsigned long moveAxisSteps(uint8_t axis, long deltaSteps)
{
    if (deltaSteps == 0)
    {
        return 0;
    }

    int8_t sign = (deltaSteps > 0) ? DIR_POS : DIR_NEG;
    long count = (deltaSteps > 0) ? deltaSteps : -deltaSteps;

    int8_t idx = findMoveIndex(axis, sign);
    if (idx < 0)
    {
        return 0;
    }

    setDirection(MOVES[idx].dir1, MOVES[idx].dir2, MOVES[idx].dir3);
    unsigned long moved = moveSteps(count, axis, sign);
    stepCounts[idx] += moved;
    return moved;
}

// Drives an axis to an absolute machine position.
bool moveAxisTo(uint8_t axis, long target)
{
    long delta = target - axisPos[axis];
    long want = (delta > 0) ? delta : -delta;

    unsigned long moved = moveAxisSteps(axis, delta);

    if (moved < (unsigned long)want)
    {
        Serial.print("  !! ");
        Serial.print(axisName(axis));
        Serial.print(" stopped early at ");
        Serial.print(axisPos[axis]);
        Serial.print(" (wanted ");
        Serial.print(target);
        Serial.println(")");
        return false;
    }
    return true;
}

void setDirection(bool dir1, bool dir2, bool dir3)
{
    digitalWrite(DIR_PIN1, dir1);
    digitalWrite(DIR_PIN2, dir2);
    digitalWrite(DIR_PIN3, dir3);
    delay(DIR_SETTLE_MS);
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
// HOMING / ORIGIN                              <<< NEW
// ============================================================

long homeMaxStepsOf(uint8_t axis)
{
    return (axis == AXIS_X) ? HOME_MAX_STEPS_X : HOME_MAX_STEPS_Y;
}

bool limitEnabledOn(uint8_t axis)
{
    return (axis == AXIS_X) ? LIMIT_X_ENABLED : LIMIT_Y_ENABLED;
}

// Drives toward the axis' physical switch until it trips.
// The switch itself sets axisPos to 0 via isPhysicalBlocked().
bool homeAxis(uint8_t axis)
{
    if (!limitEnabledOn(axis))
    {
        Serial.print("  CANNOT HOME ");
        Serial.print(axisName(axis));
        Serial.println(" - its limit switch is DISABLED in config.");
        axisHomed[axis] = false;
        return false;
    }

    int8_t sign = limitEndOf(axis);
    long travelled = 0;
    long maxSteps = homeMaxStepsOf(axis);

    if (HOME_VERBOSE)
    {
        Serial.print("  Homing ");
        Serial.print(axisName(axis));
        Serial.print(signName(sign));
        Serial.print(" ...");
    }

    while (travelled < maxSteps)
    {
        if (isPhysicalBlocked(axis, sign))
        {
            axisPos[axis] = 0; // belt and braces; the check already did it
            axisHomed[axis] = true;
            if (HOME_VERBOSE)
            {
                Serial.print(" switch found after ");
                Serial.print(travelled);
                Serial.println(" steps. Axis zeroed.");
            }
            return true;
        }

        unsigned long moved = moveAxisSteps(axis, (long)sign * HOME_CHUNK_STEPS);
        travelled += (long)moved;

        if (moved == 0)
        {
            break; // something is blocking and it is not the switch
        }
    }

    // Fell out without finding the switch.
    if (isPhysicalBlocked(axis, sign))
    {
        axisPos[axis] = 0;
        axisHomed[axis] = true;
        if (HOME_VERBOSE)
        {
            Serial.println(" switch found. Axis zeroed.");
        }
        return true;
    }

    Serial.println();
    Serial.print("  HOMING FAILED on ");
    Serial.print(axisName(axis));
    Serial.print(" after ");
    Serial.print(travelled);
    Serial.println(" steps - switch never tripped.");
    Serial.println("  Check wiring, pin number, and NC/NO setting.");
    axisHomed[axis] = false;
    return false;
}

// Y first, then X - same order as the go-to sequence.
bool goToOrigin()
{
    Serial.println();
    Serial.println("=== GO TO ORIGIN (homing both axes) ===");

    bool okY = homeAxis(AXIS_Y);
    bool okX = homeAxis(AXIS_X);

    if (okX && okY)
    {
        curCol = 0;
        curRow = 0;
        Serial.println("  AT ORIGIN. Position = X 0 / Y 0");
        return true;
    }

    Serial.println("  ORIGIN NOT REACHED - position is NOT trustworthy.");
    return false;
}

// ============================================================
// GRID MATH                                    <<< NEW
// ============================================================

// Envelope size and direction of travel for an axis, taken straight
// from the software limits so the two can never drift apart.
long gridTravelOf(uint8_t axis)
{
    return softTravelOf(axis);
}

int8_t gridDirOf(uint8_t axis)
{
    return softEndOf(axis);
}

long gridCountOf(uint8_t axis)
{
    return (axis == AXIS_X) ? GRID_COLS : GRID_ROWS;
}

// Centre of cell `index` (1-based) as a MAGNITUDE from the origin,
// rounded to the nearest whole step.
//     magnitude = (index - 0.5) * travel / count
long cellCentreMagnitude(uint8_t axis, long index)
{
    long travel = gridTravelOf(axis);
    long count = gridCountOf(axis);

    long numerator = (2L * index - 1L) * travel;
    long denominator = 2L * count;

    long mag = (numerator + denominator / 2) / denominator;

    if (mag > travel)
    {
        mag = travel;
    }
    if (mag < 0)
    {
        mag = 0;
    }
    return mag;
}

// Same thing as a signed machine position.
long cellTargetPosition(uint8_t axis, long index)
{
    return cellCentreMagnitude(axis, index) * (long)gridDirOf(axis);
}

// Cell size in steps, printed as a rounded value.
long cellSizeOf(uint8_t axis)
{
    return gridTravelOf(axis) / gridCountOf(axis);
}

// Which cell index a raw position falls in. 0 = outside the grid.
long positionToIndex(uint8_t axis, long pos)
{
    long travel = gridTravelOf(axis);
    long count = gridCountOf(axis);
    long mag = pos * (long)gridDirOf(axis); // distance from origin

    if (mag < 0 || mag > travel || travel <= 0)
    {
        return 0;
    }

    long idx = (mag * count) / travel + 1;
    if (idx > count)
    {
        idx = count;
    }
    return idx;
}

bool gridReady()
{
    if (!softEnabledOn(AXIS_X) || !softEnabledOn(AXIS_Y))
    {
        Serial.println("  ERROR - grid needs BOTH software limits enabled");
        Serial.println("  and non-zero. Check SECTION 6B.");
        return false;
    }
    return true;
}

void setGridSize(long cols, long rows)
{
    Serial.println();

    if (cols < 1 || rows < 1 || cols > GRID_COLS_MAX || rows > GRID_ROWS_MAX)
    {
        Serial.print("  ERROR - grid must be 1..");
        Serial.print(GRID_COLS_MAX);
        Serial.print(" cols and 1..");
        Serial.print(GRID_ROWS_MAX);
        Serial.println(" rows.");
        return;
    }

    GRID_COLS = cols;
    GRID_ROWS = rows;

    // Old cell numbers no longer mean the same thing.
    curCol = positionToIndex(AXIS_X, axisPos[AXIS_X]);
    curRow = positionToIndex(AXIS_Y, axisPos[AXIS_Y]);

    Serial.println("GRID RESIZED");
    printGridConfig();
}

// ============================================================
// GO TO CELL                                   <<< NEW
// ============================================================

void gotoCell(long col, long row)
{
    Serial.println();
    Serial.print("=== GOTO CELL [");
    Serial.print(col);
    Serial.print(",");
    Serial.print(row);
    Serial.println("] ===");

    if (!gridReady())
    {
        return;
    }

    if (col < 1 || col > GRID_COLS || row < 1 || row > GRID_ROWS)
    {
        Serial.print("  ERROR - out of range. Valid: col 1..");
        Serial.print(GRID_COLS);
        Serial.print(", row 1..");
        Serial.println(GRID_ROWS);
        return;
    }

    long targetX = cellTargetPosition(AXIS_X, col);
    long targetY = cellTargetPosition(AXIS_Y, row);

    Serial.print("  Target position: X ");
    Serial.print(targetX);
    Serial.print(" / Y ");
    Serial.println(targetY);

    // STEP 1 - back to a known origin.
    if (!goToOrigin())
    {
        Serial.println("  ABORTED - cannot trust position without origin.");
        return;
    }

    // STEP 2 - Y axis.
    Serial.print("  Moving Y to ");
    Serial.print(targetY);
    Serial.println(" ...");
    bool okY = moveAxisTo(AXIS_Y, targetY);

    // STEP 3 - X axis.
    Serial.print("  Moving X to ");
    Serial.print(targetX);
    Serial.println(" ...");
    bool okX = moveAxisTo(AXIS_X, targetX);

    if (okX && okY)
    {
        curCol = col;
        curRow = row;
        Serial.print("  ARRIVED at cell [");
        Serial.print(col);
        Serial.print(",");
        Serial.print(row);
        Serial.print("]  pos X ");
        Serial.print(axisPos[AXIS_X]);
        Serial.print(" / Y ");
        Serial.println(axisPos[AXIS_Y]);
    }
    else
    {
        curCol = positionToIndex(AXIS_X, axisPos[AXIS_X]);
        curRow = positionToIndex(AXIS_Y, axisPos[AXIS_Y]);
        Serial.println("  MOVE INCOMPLETE - a limit stopped it short.");
    }
}

// ============================================================
// PHYSICAL LIMIT SWITCHES
// ============================================================

bool interpretLimit(int pinState, bool useNC)
{
    if (useNC)
    {
        return pinState == HIGH;
    }
    else
    {
        return pinState == LOW;
    }
}

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
    else if (axis == AXIS_Y)
    {
        pin = LIMIT_PIN_Y;
        useNC = LIMIT_Y_USE_NC;
        enabled = LIMIT_Y_ENABLED;
    }
    else
    {
        pin = LIMIT_PIN_Z;
        useNC = LIMIT_Z_USE_NC;
        enabled = LIMIT_Z_ENABLED;
    }

    if (!enabled)
    {
        return false;
    }

    if (!interpretLimit(digitalRead(pin), useNC))
    {
        return false;
    }

    delayMicroseconds(LIMIT_CONFIRM_US);
    return interpretLimit(digitalRead(pin), useNC);
}

int8_t limitEndOf(uint8_t axis)
{
    if (axis == AXIS_X)
    {
        return LIMIT_X_AT_END;
    }
    if (axis == AXIS_Y)
    {
        return LIMIT_Y_AT_END;
    }
    return LIMIT_Z_AT_END;
}

bool isPhysicalBlocked(uint8_t axis, int8_t sign)
{
    if (sign != limitEndOf(axis))
    {
        return false;
    }

    if (!isLimitHit(axis))
    {
        return false;
    }

    if (SOFT_ZERO_ON_LIMIT_HIT)
    {
        axisPos[axis] = 0;
        axisHomed[axis] = true;
    }

    return true;
}

// ============================================================
// SOFTWARE LIMITS
// ============================================================

int8_t softEndOf(uint8_t axis)
{
    if (axis == AXIS_X)
    {
        return SOFT_LIMIT_X_AT_END;
    }
    if (axis == AXIS_Y)
    {
        return SOFT_LIMIT_Y_AT_END;
    }
    return SOFT_LIMIT_Z_AT_END;
}

long softTravelOf(uint8_t axis)
{
    if (axis == AXIS_X)
    {
        return SOFT_LIMIT_X_TRAVEL;
    }
    if (axis == AXIS_Y)
    {
        return SOFT_LIMIT_Y_TRAVEL;
    }
    return SOFT_LIMIT_Z_TRAVEL;
}

bool softEnabledOn(uint8_t axis)
{
    bool enabled;
    if (axis == AXIS_X)
    {
        enabled = SOFT_LIMIT_X_ENABLED;
    }
    else if (axis == AXIS_Y)
    {
        enabled = SOFT_LIMIT_Y_ENABLED;
    }
    else
    {
        enabled = SOFT_LIMIT_Z_ENABLED;
    }
    return enabled && softTravelOf(axis) != SOFT_LIMIT_INFINITE;
}

long softStepsRemaining(uint8_t axis, int8_t sign)
{
    if (!softEnabledOn(axis))
    {
        return -1;
    }
    if (sign != softEndOf(axis))
    {
        return -1;
    }

    long cap = softTravelOf(axis);
    long travelled = axisPos[axis] * sign;
    long remaining = cap - travelled;

    return (remaining > 0) ? remaining : 0;
}

bool isSoftBlocked(uint8_t axis, int8_t sign)
{
    long remaining = softStepsRemaining(axis, sign);
    if (remaining < 0)
    {
        return false;
    }
    return remaining == 0;
}

// ============================================================
// COMBINED LIMIT CHECK
// ============================================================

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
    if (axis == AXIS_X)
    {
        return "X";
    }
    if (axis == AXIS_Y)
    {
        return "Y";
    }
    return "Z";
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

    Serial.print("Z (pin ");
    Serial.print(LIMIT_PIN_Z);
    Serial.print(", ");
    Serial.print(LIMIT_Z_USE_NC ? "NC" : "NO");
    Serial.print(", guards Z");
    Serial.print(signName(LIMIT_Z_AT_END));
    Serial.print("): ");
    if (!LIMIT_Z_ENABLED)
        Serial.println("DISABLED IN CONFIG");
    else if (isLimitHit(AXIS_Z))
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
    printSoftLimitLine(AXIS_Z);
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

        if (!axisHomed[a])
        {
            Serial.print("  (NOT HOMED)");
        }

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

void printGridConfig()
{
    Serial.println();
    Serial.println("--- GRID ---");
    Serial.print("Envelope : ");
    Serial.print(gridTravelOf(AXIS_X));
    Serial.print(" x ");
    Serial.print(gridTravelOf(AXIS_Y));
    Serial.println(" steps");

    Serial.print("Division : ");
    Serial.print(GRID_COLS);
    Serial.print(" cols x ");
    Serial.print(GRID_ROWS);
    Serial.print(" rows  = ");
    Serial.print(GRID_COLS * GRID_ROWS);
    Serial.println(" cells");

    Serial.print("Cell size: ~");
    Serial.print((float)gridTravelOf(AXIS_X) / (float)GRID_COLS, 2);
    Serial.print(" x ");
    Serial.print((float)gridTravelOf(AXIS_Y) / (float)GRID_ROWS, 2);
    Serial.println(" steps");

    Serial.println("col 1 = X switch side, row 1 = Y switch side");
}

// ============================================================
// ASCII GRID MAP                               <<< NEW
// ============================================================

void printGrid()
{
    Serial.println();
    Serial.println("======================================");
    Serial.println("GRID MAP");
    Serial.println("======================================");

    printGridConfig();

    long liveCol = positionToIndex(AXIS_X, axisPos[AXIS_X]);
    long liveRow = positionToIndex(AXIS_Y, axisPos[AXIS_Y]);

    Serial.println();
    Serial.print("Machine pos : X ");
    Serial.print(axisPos[AXIS_X]);
    Serial.print("  /  Y ");
    Serial.println(axisPos[AXIS_Y]);

    Serial.print("Current cell: ");
    if (!axisHomed[AXIS_X] || !axisHomed[AXIS_Y])
    {
        Serial.println("UNKNOWN - not homed yet (send 0)");
    }
    else if (liveCol == 0 || liveRow == 0)
    {
        Serial.println("outside the grid envelope");
    }
    else
    {
        Serial.print("[");
        Serial.print(liveCol);
        Serial.print(",");
        Serial.print(liveRow);
        Serial.println("]");
    }

    if (curCol > 0 && curRow > 0)
    {
        Serial.print("Last commanded cell: [");
        Serial.print(curCol);
        Serial.print(",");
        Serial.print(curRow);
        Serial.println("]");
    }

    if (GRID_COLS > GRID_MAP_MAX_COLS || GRID_ROWS > GRID_MAP_MAX_ROWS)
    {
        Serial.println();
        Serial.print("Map not drawn - grid larger than ");
        Serial.print(GRID_MAP_MAX_COLS);
        Serial.print("x");
        Serial.print(GRID_MAP_MAX_ROWS);
        Serial.println(" is unreadable here.");
        Serial.println("======================================");
        return;
    }

    Serial.println();
    Serial.println("  # = machine   . = empty cell");
    Serial.println("  (top row = far Y end, left col = X switch)");
    Serial.println();

    for (long r = GRID_ROWS; r >= 1; r--)
    {
        // Right-aligned row label, 3 wide.
        if (r < 100)
            Serial.print(" ");
        if (r < 10)
            Serial.print(" ");
        Serial.print(r);
        Serial.print(" |");

        for (long c = 1; c <= GRID_COLS; c++)
        {
            if (c == liveCol && r == liveRow && axisHomed[AXIS_X] && axisHomed[AXIS_Y])
            {
                Serial.print(" #");
            }
            else
            {
                Serial.print(" .");
            }
        }
        Serial.println();
    }

    // Bottom rule.
    Serial.print("    +");
    for (long c = 1; c <= GRID_COLS; c++)
    {
        Serial.print("--");
    }
    Serial.println();

    // Column numbers, last digit only (keeps the map aligned).
    Serial.print("     ");
    for (long c = 1; c <= GRID_COLS; c++)
    {
        Serial.print(c % 10);
        Serial.print(" ");
    }
    Serial.println();
    Serial.println("     ^ origin corner is bottom-left [1,1]");
    Serial.println("======================================");
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
        axisHomed[a] = false; // a manual zero is NOT a homed origin
    }
    curCol = 0;
    curRow = 0;

    Serial.println();
    Serial.println("POSITION ZEROED - this point is now the origin");
    Serial.println("NOTE: grid moves still require a real home (0).");
    printSoftLimitStatus();
}

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
    printNetLine("Z", netSteps(AXIS_Z));
    printPosition();
    Serial.println("======================================");

    printLimitStatus();
    printSoftLimitStatus();
    printGridConfig();
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
    Serial.println("Dual TB6600 CNC Grid Control - MEGA 2560");
    Serial.println("======================================");
    Serial.print("Jog size per command: ");
    Serial.println(stepsPerMove);
    Serial.println("--------------------------------------");
    Serial.println("1 = Y-   (M1 CW  / M2 CCW)  [limit: pin 31]");
    Serial.println("2 = Y+   (M1 CCW / M2 CW )  [soft limit]");
    Serial.println("3 = X-   (M1 CW  / M2 CW )  [limit: pin 30]");
    Serial.println("4 = X+   (M1 CCW / M2 CCW)  [soft limit]");
    Serial.println("5 = Show counters / position / limits");
    Serial.println("6 = Reset step counters");
    Serial.println("7 = Disable both motors");
    Serial.println("8 = Zero position (manual, NOT a home)");
    Serial.println("9 = Show ASCII grid map");
    Serial.println("0 = HOME / go to origin (X/Y switches only)");
    Serial.println("--------------------------------------");
    Serial.println("D = Z-   (M3 CW )           [limit: pin 28]");
    Serial.println("U = Z+   (M3 CCW)           [soft limit: INFINITE]");
    Serial.println("--------------------------------------");
    Serial.println("G <col> <row>   goto cell, e.g.  G 3 5");
    Serial.println("S <cols> <rows> resize grid, e.g. S 20 39");
    Serial.println("?               reprint this help");
    Serial.println("(D, U, G and S need a newline / Enter)");
    Serial.println("======================================");
}
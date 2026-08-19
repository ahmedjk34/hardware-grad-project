/*
  ============================================================
  Dual TB6600 + Arduino MEGA 2560
  CNC-style step testing with limit switches, SOFTWARE limits,
  live position tracking, step counters, and GRID ADDRESSING

  Plus a THIRD, independent motor driving a Z axis (single motor,
  not coupled to the X/Y pair), a GRIPPER SERVO on pin 6 with just
  two positions (OPEN and CLOSE), and a FOURTH, independent
  28BYJ-48 + ULN2003 stepper that only jogs +/-90 degrees on command.
  ============================================================

  SERIAL COMMANDS
    1 = X-   (Motor 1 CW  / Motor 2 CW )   <-- SOFTWARE limit end
    2 = X+   (Motor 1 CCW / Motor 2 CCW)   <-- physical limit switch end
    3 = Y-   (Motor 1 CW  / Motor 2 CCW)   <-- physical limit switch end
    4 = Y+   (Motor 1 CCW / Motor 2 CW )   <-- SOFTWARE limit end
    5 = Show step counters + position + limit status
    6 = Reset step counters to zero
    7 = Disable both motors (release holding torque)
    8 = ZERO the position counters (set "here" as origin 0,0)
    9 = Show ASCII grid map + current cell
    0 = HOME / GO TO ORIGIN (drive into both switches, X/Y only)

    D = Z-   (Motor 3 CW )   <-- physical limit switch, pin 28 (GROUND)
    U = Z+   (Motor 3 CCW)   <-- physical limit switch, pin 29 (TOP)

    O = Servo OPEN   (pin 6)
    C = Servo CLOSE  (pin 6)

    R  = Aux stepper rotate ~90 deg CW   (28BYJ-48, pins 36-39)
    RR = Aux stepper rotate ~90 deg CCW  (28BYJ-48, pins 36-39)

    G <col> <row>   = go to grid cell (1-based). e.g.  G 3 5   or  G3,5
    S <cols> <rows> = change the grid division live. e.g.  S 20 39
    ?               = reprint the help text

  Multi-character commands need a newline. Single digit commands
  work with or without one. D, U, O, C and R are letters, so like
  G/S/? they need a newline too. RR is two letters and ALSO needs
  a newline - there is no single-character fast path for it.

  Z is NOT part of homing (0) or the grid (G) yet - it is jogged
  independently with D/U. BOTH ends of its travel are physical limit
  switches now: pin 28 at the bottom (GROUND, and Z's zero) and pin 29
  at the top. The Z+ software limit is gone - the switch replaced it.

  ------------------------------------------------------------
  COORDINATE SYSTEM  (this is the important part)
  ------------------------------------------------------------
  SOFT_ZERO_ON_LIMIT_HIT is true, so each HOME switch zeros its own
  axis the moment it trips. The corner where BOTH X/Y switches are
  pressed is therefore machine position (0, 0) = the ORIGIN. Z's top
  switch is NOT a home switch, so it stops the axis without zeroing it.

  Each axis travels AWAY from its own home switch. The two switches sit at
  OPPOSITE ends now, so the two axes no longer share a sign:

      X switch at the X+ end  ->  X runs   0  ...  -5100   (soft limit)
      Y switch at the Y- end  ->  Y runs   0  ...  +8500   (soft limit)

  So the work envelope is 5100 x 8500 steps, living in the rectangle
  X in [-5100, 0], Y in [0, +8500]. Grid indices hide this sign mess:

      col 1  = nearest the X switch (X = 0 side, the X+ end)
      col N  = far end of X travel  (X = -5100 side)
      row 1  = nearest the Y switch (Y = 0 side)
      row M  = far end of Y travel  (Y = +8500 side)

  Generalised in code as: each axis extends from 0 in the direction
  travelEndOf(axis), for axisTravelOf(axis) steps - whether that far
  end is held by a software cap (X/Y) or by a switch (Z). Change the
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

#include <Servo.h>
#include <Stepper.h>

// ============================================================
// SECTION 1 - MOTOR PIN CONFIGURATION
// ============================================================

// IMPORTANT: BOTH X/Y drivers now go CW on ACTIVE HIGH. The pins 2/3
// driver (DIR_PIN1/STEP_PIN1) always did, because its coil wiring was
// physically reversed; the pins 8/9 driver ended up the same after the
// machine was rewired. Do not "fix" either polarity in software without
// re-checking the physical wiring first - see SECTION 3.
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
// SECTION 1B - GRIPPER SERVO CONFIGURATION
// ============================================================
//
// A single hobby servo, two positions only: OPEN [O] and CLOSE [C].

const int SERVO_PIN = 6;

const int SERVO_OPEN_ANGLE = 0;
const int SERVO_CLOSE_ANGLE = 90;

Servo gripperServo;

// True = last commanded position was OPEN. Set to a known state in
// setup() so this always reflects reality, not just "assumed".
bool servoIsOpen = false;

// ============================================================
// SECTION 1C - AUXILIARY STEPPER CONFIGURATION (28BYJ-48 + ULN2003)
// ============================================================
//
// A fourth, independent motor - not part of the X/Y/Z rig. It only
// jogs +/-90 degrees on command (R / RR), no homing, no limits.
//
// ULN2003 connections:
//   IN1 -> pin 36   BLACK
//   IN2 -> pin 37   GREEN
//   IN3 -> pin 38   BLUE
//   IN4 -> pin 39   RED
// Power the ULN2003 from a 5V external supply with a shared GND.

const int AUX_STEPPER_IN1 = 36;
const int AUX_STEPPER_IN2 = 37;
const int AUX_STEPPER_IN3 = 38;
const int AUX_STEPPER_IN4 = 39;

// Approximate number of steps for one output-shaft revolution.
const int AUX_STEPPER_STEPS_PER_REV = 2048;

// A quarter turn - what R / RR actually move.
const int AUX_STEPPER_QUARTER_TURN = AUX_STEPPER_STEPS_PER_REV / 4;

const int AUX_STEPPER_SPEED_RPM = 10;

// IMPORTANT: the correct Stepper library pin order for most
// 28BYJ-48 + ULN2003 boards is IN1, IN3, IN2, IN4 (not IN1..IN4).
Stepper auxStepper(
    AUX_STEPPER_STEPS_PER_REV,
    AUX_STEPPER_IN1,
    AUX_STEPPER_IN3,
    AUX_STEPPER_IN2,
    AUX_STEPPER_IN4);

// Net position in steps, relative to power-on. Purely informational -
// this motor has no limits or homing to keep it honest.
long auxStepperPos = 0;

// ============================================================
// SECTION 2 - MOTION TUNINGD
// ============================================================

// ------------------------------------------------------------
//   X/Y AND Z ARE TUNED SEPARATELY
// ------------------------------------------------------------
//   Z is a single motor lifting against gravity, so the pulse rate
//   and jog size that suit the X/Y gantry rarely suit the lift. Z
//   gets its own of each. Every Z move reads them - manual D/U jogs
//   and homing alike.

// Half-period of the step pulse, in microseconds. One full step is
// two of these. RAISE the Z value to slow Z down (more torque, less
// chance of losing steps under load); LOWER it to speed the lift up.
unsigned int STEP_DELAY = 500;   // X and Y
unsigned int STEP_DELAY_Z = 500; // Z only

// How many steps a single MANUAL jog moves.
//   stepsPerMove  -> the 1-4 commands (X/Y)
//   stepsPerMoveZ -> the D/U commands (Z)
int stepsPerMove = 150;  // X and Y
int stepsPerMoveZ = 150; // Z only

// Settle time after changing a DIR pin before the first step pulse.
const unsigned int DIR_SETTLE_MS = 5;

// ============================================================
// SECTION 3 - MOTOR DIRECTION POLARITY
// ============================================================

const bool MOTOR1_CW = HIGH;
const bool MOTOR1_CCW = LOW;

// Motor 2 now turns CW on HIGH, same as motor 1 - its direction sense
// inverted when the machine was rewired. These two values were swapped
// to match what the shafts were observed to do. The pin levels each
// command sends did NOT change, only the names for them, so motion is
// identical to before the swap.
const bool MOTOR2_CW = HIGH;
const bool MOTOR2_CCW = LOW;

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
//
// VERIFIED ON THE MACHINE after the rig was physically re-oriented and
// motor 2 was rewired. Confirmed by watching the shafts turn:
//     M1 CW  + M2 CW   ->  X-   (short axis, toward the X SOFT limit)
//     M1 CCW + M2 CCW  ->  X+   (toward the X switch, pin 30)
//     M1 CW  + M2 CCW  ->  Y-   (long axis, toward the Y switch, pin 31)
//     M1 CCW + M2 CW   ->  Y+   (toward the Y SOFT limit)
// Motors turning the SAME sense walk X; opposed senses walk Y. The axis
// names, travel caps, switch pins and grid all kept their original
// meaning. Re-verify against the hardware before changing this.
const MoveDef MOVES[MOVE_COUNT] = {
    {"X-", MOTOR1_CW, MOTOR2_CW, false, AXIS_X, DIR_NEG},
    {"X+", MOTOR1_CCW, MOTOR2_CCW, false, AXIS_X, DIR_POS},
    {"Y-", MOTOR1_CW, MOTOR2_CCW, false, AXIS_Y, DIR_NEG},
    {"Y+", MOTOR1_CCW, MOTOR2_CW, false, AXIS_Y, DIR_POS},
    {"Z-", false, false, MOTOR3_CW, AXIS_Z, DIR_NEG},
    {"Z+", false, false, MOTOR3_CCW, AXIS_Z, DIR_POS}};

// ============================================================
// SECTION 6 - PHYSICAL LIMIT SWITCH CONFIGURATION
// ============================================================
//
// Every switch on the machine lives in ONE table. A switch is
// described by WHICH END OF WHICH AXIS it guards, not by its axis
// alone - which is exactly what lets Z carry two of them:
//
//     X    one switch  at the X+ end          pin 30
//     Y    one switch  at the Y- end          pin 31
//     Z    TWO switches:
//              Z-  bottom / GROUND            pin 28
//              Z+  top of travel              pin 29   <<< was software
//
// The Z+ switch REPLACED the Z+ software limit. Nothing about it is
// special-cased: it is read, debounced and obeyed by the same code
// as every other end stop.
//
// ------------------------------------------------------------
//   isHome  -  which switch is an axis' ZERO?
// ------------------------------------------------------------
//   An axis needs exactly one switch that means "you are at 0". That
//   is the one homing drives into, and the one that re-zeros the
//   counter under SOFT_ZERO_ON_LIMIT_HIT.
//
//   Z- is Z's home switch: it is the GROUND the claw measures from.
//   Z+ is a FAR-END switch - it stops the axis and reports where the
//   top is, but it does not redefine zero. See applyLimitReference().

const int LIMIT_PIN_X = 30;     // X AXIS limit switch
const int LIMIT_PIN_Y = 31;     // Y AXIS limit switch
const int LIMIT_PIN_Z_BOT = 28; // Z AXIS bottom (GROUND) limit switch
const int LIMIT_PIN_Z_TOP = 29; // Z AXIS top limit switch   <<< NEW

struct LimitSwitch
{
  uint8_t axis;
  int8_t end;   // DIR_NEG / DIR_POS - which end of the axis it guards
  uint8_t pin;
  bool useNC;   // true = normally-closed wiring
  bool enabled; // false = ignore this switch completely
  bool isHome;  // true = tripping it means "this axis is at 0"
};

const uint8_t LIMIT_COUNT = 4;

// The order here is the order every report prints them in.
const LimitSwitch LIMITS[LIMIT_COUNT] = {
  {AXIS_X, DIR_POS, LIMIT_PIN_X, true, true, true},
  {AXIS_Y, DIR_NEG, LIMIT_PIN_Y, true, true, true},
  {AXIS_Z, DIR_NEG, LIMIT_PIN_Z_BOT, true, true, true},
  {AXIS_Z, DIR_POS, LIMIT_PIN_Z_TOP, true, true, false}};

// When Z runs up into the top switch it can either KEEP the step
// count it just made, or ADOPT Z_TRAVEL_STEPS as its position.
// Keeping the count (false) is more accurate whenever Z already has a
// true zero from the bottom switch: that count came from the real
// hardware this run, while Z_TRAVEL_STEPS is a hand-entered constant.
//
// When Z has NO zero at all, the top switch adopts Z_TRAVEL_STEPS
// regardless - a rough reference beats no reference.
const bool Z_TOP_REFERENCES_POSITION = false;

const unsigned int LIMIT_CONFIRM_US = 200;
const uint8_t LIMIT_CHECK_EVERY_N_STEPS = 1;

// ============================================================
// SECTION 6B - SOFTWARE LIMIT CONFIGURATION
// ============================================================
//
// These two numbers ALSO define the size of the grid envelope.

const long SOFT_LIMIT_INFINITE = 0; // sentinel: no cap at all

long SOFT_LIMIT_X_TRAVEL = 5050; // X- travel cap, in steps
long SOFT_LIMIT_Y_TRAVEL = 8500; // Y+ travel cap, in steps
// Z has no software cap any more: both ends of its travel are real
// switches (pin 28 at the bottom, pin 29 at the top). The old cap
// survives as Z_TRAVEL_STEPS, a SIZING figure - it is what the Z
// homing cap scales from, and what the top switch falls back on when
// the axis has never been zeroed. It stops nothing; the switch does.
long Z_TRAVEL_STEPS = 1350;

// Measured physical distance between the Z- and Z+ hardware switches.
const float Z_TRAVEL_CM = 26.5;

// What the rig last counted between the two Z switches. 0 = not
// measured yet. Recorded by applyLimitReference(), reported by 0+.
long zTravelMeasured = 0;

const long SOFT_LIMIT_Z_TRAVEL = SOFT_LIMIT_INFINITE; // Z: switch, not a cap

const int8_t SOFT_LIMIT_X_AT_END = DIR_NEG; // guards the X- end
const int8_t SOFT_LIMIT_Y_AT_END = DIR_POS; // guards the Y+ end
const int8_t SOFT_LIMIT_Z_AT_END = DIR_POS; // (unused - Z has no cap)

const bool SOFT_LIMIT_X_ENABLED = true;
const bool SOFT_LIMIT_Y_ENABLED = true;
const bool SOFT_LIMIT_Z_ENABLED = false; // the pin 29 switch replaced it

// Re-zero an axis automatically the moment its HOME switch trips.
// Far-end switches (Z+) never re-zero - see applyLimitReference().
// REQUIRED for the grid to mean anything - leave this true.
const bool SOFT_ZERO_ON_LIMIT_HIT = true;

const bool SOFT_LIMIT_VERBOSE = true;

// ============================================================
// SECTION 6C - GRID CONFIGURATION            <<< NEW
// ============================================================
//
// The envelope (5100 x 8500 steps) is divided into COLS x ROWS
// equal rectangles. The machine parks at the CENTRE of a cell.
//
// Cell size does NOT have to divide evenly into the travel. Targets
// are computed from the absolute position each time, so rounding
// error is always under one step and never accumulates.
//
// ------------------------------------------------------------
//   HOW FINE CAN THIS GO?
// ------------------------------------------------------------
//   Arithmetically the floor is 1 step per cell (5100 x 8500
//   = 43.35 million cells), which is meaningless - it is far below
//   what the machine can repeat mechanically.
//
//   The envelope is a clean 3:5 ratio (5100:8500), so ANY grid whose
//   cols:rows is 3:5 gives EXACTLY square cells in whole steps:
//        COLS   ROWS   CELL (X x Y)      CELLS
//           6 x   10     850 x 850          60
//          12 x   20     425 x 425         240   <- square, same scale
//          30 x   50     170 x 170        1500      as the default
//          60 x  100      85 x  85        6000
//         300 x  500      17 x  17      150000
//        5100 x 8500       1 x   1    43350000   <- 1 step per cell
//
//   NOTE: the 10 x 20 default below is NOT square - it gives
//   510 x 425 step cells. Use 12 x 20 if you want square ones.
//
//   Change these here, or live with:  S <cols> <rows>

long GRID_COLS = 10;
long GRID_ROWS = 20;

const long GRID_COLS_MAX = 5100; // 1 step per cell
const long GRID_ROWS_MAX = 8500;

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
const long HOME_MAX_STEPS_X = 5100L * 2 + 500;
const long HOME_MAX_STEPS_Y = 8500L * 2 + 500;

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

// Where that position came from: true = the axis' HOME switch set it,
// which is the only reference precise enough to measure against.
//
// Z can also be positioned by its TOP switch, which is a guess taken
// from Z_TRAVEL_STEPS rather than something counted - good enough to
// work with, not good enough to calibrate from. Keeping the two apart
// is what stops a top-switch guess being reported back as a
// measurement of itself. See applyLimitReference().
bool axisRefAtHome[AXIS_COUNT] = {false, false, false};

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

const char CMD_MOVE_Z_NEG = 'D'; // Z-  (bottom limit switch, pin 28)
const char CMD_MOVE_Z_POS = 'U'; // Z+  (top limit switch, pin 29)

const char CMD_SERVO_OPEN = 'O';
const char CMD_SERVO_CLOSE = 'C';

const char CMD_AUX_STEPPER_CW = 'R'; // "R"  (RR is handled in handleLine)

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

// When the last character landed - used only to decide that a lone
// "0" / "0+" has stopped growing and can be run. A whole line arrives
// from the Serial Monitor in one burst, so this only ever expires
// between commands. See flushPendingZeroCommand().
unsigned long lastCharAtMs = 0;
const unsigned long ZERO_CMD_IDLE_MS = 50;

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

  // Every switch in the table, however many there are.
  for (uint8_t i = 0; i < LIMIT_COUNT; i++)
  {
    pinMode(LIMITS[i].pin, INPUT_PULLUP);
  }

  digitalWrite(STEP_PIN1, LOW);
  digitalWrite(STEP_PIN2, LOW);
  digitalWrite(STEP_PIN3, LOW);

  disableMotors();

  gripperServo.attach(SERVO_PIN);
  gripperServo.write(SERVO_CLOSE_ANGLE);
  servoIsOpen = false;

  auxStepper.setSpeed(AUX_STEPPER_SPEED_RPM);

  Serial.begin(9600);
  delay(1000);

  printInstructions();
  printLimitStatus();
  printSoftLimitStatus();
  printGridConfig();
  printServoStatus();
  printAuxStepperStatus();

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
    //
    // '0' is the ONE exception. It might be the start of "0+", so it
    // has to wait and see what follows. The not-a-plus flush below and
    // the idle flush after the loop make that wait invisible.
    if (lineLen == 0 && c >= '1' && c <= '9')
    {
      handleSingleChar(c);
      continue;
    }

    if (c == ' ' && lineLen == 0)
    {
      continue; // ignore leading spaces
    }

    // A buffered '0' followed by anything that is NOT '+' was just a
    // plain home. Run it now, then deal with c as a fresh command.
    if (lineLen == 1 && lineBuf[0] == CMD_GO_ORIGIN && c != '+')
    {
      lineLen = 0;
      handleSingleChar(CMD_GO_ORIGIN);

      if (c >= '1' && c <= '9')
      {
        handleSingleChar(c);
        continue;
      }
    }

    if (lineLen < LINE_BUF_SIZE - 1)
    {
      lineBuf[lineLen++] = c;
      lastCharAtMs = millis();
    }
    else
    {
      lineLen = 0; // overflow: drop the garbage line
      Serial.println("  ERROR - command too long, ignored.");
    }
  }

  flushPendingZeroCommand();
}

// "0" and "0+" are the only commands that can sit in the buffer with
// nothing following them, because they are the only ones that had to
// wait for a possible '+'. Without this they would be lost whenever
// the Serial Monitor is set to "No line ending" - so once the line
// has gone quiet, run what we have.
//
// Nothing else is flushed this way: every other multi-character
// command still needs its newline, exactly as documented.
void flushPendingZeroCommand()
{
  bool isPendingZero =
      (lineLen == 1 && lineBuf[0] == CMD_GO_ORIGIN) ||
      (lineLen == 2 && lineBuf[0] == CMD_GO_ORIGIN && lineBuf[1] == '+');

  if (!isPendingZero)
  {
    return;
  }
  if ((millis() - lastCharAtMs) < ZERO_CMD_IDLE_MS)
  {
    return;
  }

  lineBuf[lineLen] = '\0';
  handleLine(lineBuf);
  lineLen = 0;
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
  case CMD_GO_ORIGIN:
    if (line[1] == '+' && line[2] == '\0')
    {
      goToOriginWithZ();
    }
    else
    {
      Serial.println();
      Serial.println("  ERROR - use:  0 (home X/Y) or 0+ (reset Z too)");
    }
    break;

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

  case 'R':
    if ((line[1] == 'R' || line[1] == 'r') && line[2] == '\0')
    {
      rotateAuxStepperCCW();
    }
    else
    {
      Serial.println();
      Serial.println("  ERROR - use:  R (CW ~90 deg) or RR (CCW ~90 deg)");
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

  case CMD_SERVO_OPEN:
    openServo();
    break;

  case CMD_SERVO_CLOSE:
    closeServo();
    break;

  case CMD_AUX_STEPPER_CW:
    rotateAuxStepperCW();
    break;

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

// ------------------------------------------------------------
// Per-axis motion tuning. Z is independent of the X/Y pair in BOTH
// pulse rate and jog size - every move funnels through these, so
// there is one place to change and no way for them to drift apart.
// ------------------------------------------------------------

unsigned int stepDelayOf(uint8_t axis)
{
  return (axis == AXIS_Z) ? STEP_DELAY_Z : STEP_DELAY;
}

int jogStepsOf(uint8_t axis)
{
  return (axis == AXIS_Z) ? stepsPerMoveZ : stepsPerMove;
}

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

  int jog = jogStepsOf(m.axis);

  unsigned long moved = moveSteps(jog, m.axis, m.sign);
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
  Serial.print(jog);
  Serial.print(" steps  [");
  Serial.print(m.label);
  Serial.print("]  pos ");
  Serial.print(axisName(m.axis));
  Serial.print(" = ");
  Serial.println(axisPos[m.axis]);

  if (moved < (unsigned long)jog)
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

  // Read the axis' own pulse rate ONCE, not per step. Every move
  // funnels through here, so this is what gives Z its own speed
  // during homing too, not just manual jogs.
  unsigned int pulseDelay = stepDelayOf(axis);

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
    delayMicroseconds(pulseDelay);

    if (isZ)
    {
      digitalWrite(STEP_PIN3, LOW);
    }
    else
    {
      digitalWrite(STEP_PIN1, LOW);
      digitalWrite(STEP_PIN2, LOW);
    }
    delayMicroseconds(pulseDelay);

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
// GRIPPER SERVO                                <<< NEW
// ============================================================

void openServo()
{
  gripperServo.write(SERVO_OPEN_ANGLE);
  servoIsOpen = true;

  Serial.println();
  Serial.print("SERVO: OPEN (");
  Serial.print(SERVO_OPEN_ANGLE);
  Serial.println(" deg)");
}

void closeServo()
{
  gripperServo.write(SERVO_CLOSE_ANGLE);
  servoIsOpen = false;

  Serial.println();
  Serial.print("SERVO: CLOSE (");
  Serial.print(SERVO_CLOSE_ANGLE);
  Serial.println(" deg)");
}

// ============================================================
// AUXILIARY STEPPER (28BYJ-48)                 <<< NEW
// ============================================================

void rotateAuxStepperCW()
{
  Serial.println();
  Serial.println("AUX STEPPER: rotating ~90 deg CW...");
  auxStepper.step(AUX_STEPPER_QUARTER_TURN);
  auxStepperPos += AUX_STEPPER_QUARTER_TURN;
  Serial.println("AUX STEPPER: done.");
}

void rotateAuxStepperCCW()
{
  Serial.println();
  Serial.println("AUX STEPPER: rotating ~90 deg CCW...");
  auxStepper.step(-AUX_STEPPER_QUARTER_TURN);
  auxStepperPos -= AUX_STEPPER_QUARTER_TURN;
  Serial.println("AUX STEPPER: done.");
}

// ============================================================
// HOMING / ORIGIN                              <<< NEW
// ============================================================

// Derived from the soft travel, so re-tuning a travel cap can never
// leave a stale homing cap behind. Z is included - a full reset (0+)
// homes it like any other axis.
long homeMaxStepsOf(uint8_t axis)
{
  long travel = axisTravelOf(axis);

  if (travel <= 0)
  {
    return 20000; // no cap configured to scale from
  }
  return travel * 2 + 500;
}

// ------------------------------------------------------------
// Drives toward the switch at ONE END of an axis until it trips.
// ------------------------------------------------------------
// This used to be homeAxis() and could only ever run toward the home
// switch, because that was the only switch an axis had. Z+ on pin 29
// changed that: "go to the top of Z" is now the same operation as
// "home Z", just aimed at the other end, so both come through here.
//
// isPhysicalBlocked() is what notices the contact, and
// applyLimitReference() is what the contact means for the position -
// this function only walks until one of them says stop.
bool seekLimit(uint8_t axis, int8_t end)
{
  int8_t idx = findLimitIndex(axis, end);
  bool isHomeSeek = (idx >= 0) && LIMITS[idx].isHome;

  if (idx < 0 || !LIMITS[idx].enabled)
  {
    Serial.print("  CANNOT SEEK ");
    Serial.print(axisName(axis));
    Serial.print(signName(end));
    Serial.println(" - no enabled limit switch at that end.");
    if (isHomeSeek)
    {
      axisHomed[axis] = false;
    }
    return false;
  }

  long travelled = 0;
  long maxSteps = homeMaxStepsOf(axis);

  if (HOME_VERBOSE)
  {
    if (isHomeSeek)
    {
      Serial.print("  Homing ");
    }
    else
    {
      Serial.print("  Seeking ");
    }
    Serial.print(axisName(axis));
    Serial.print(signName(end));
    Serial.print(" (pin ");
    Serial.print(LIMITS[idx].pin);
    Serial.print(") ...");
  }

  while (travelled < maxSteps)
  {
    if (isPhysicalBlocked(axis, end))
    {
      if (HOME_VERBOSE)
      {
        Serial.print(" switch found after ");
        Serial.print(travelled);
        Serial.print(" steps. ");
        if (isHomeSeek)
        {
          Serial.println("Axis zeroed.");
        }
        else
        {
          Serial.println("At the end stop.");
        }
      }
      return true;
    }

    unsigned long moved = moveAxisSteps(axis, (long)end * HOME_CHUNK_STEPS);
    travelled += (long)moved;

    if (moved == 0)
    {
      break; // something is blocking and it is not this switch
    }
  }

  // Fell out without finding the switch.
  if (isPhysicalBlocked(axis, end))
  {
    if (HOME_VERBOSE)
    {
      Serial.println(" switch found.");
    }
    return true;
  }

  Serial.println();
  Serial.print("  SEEK FAILED on ");
  Serial.print(axisName(axis));
  Serial.print(signName(end));
  Serial.print(" after ");
  Serial.print(travelled);
  Serial.println(" steps - switch never tripped.");
  Serial.println("  Check wiring, pin number, and NC/NO setting.");
  if (isHomeSeek)
  {
    axisHomed[axis] = false;
  }
  return false;
}

// Drives toward the axis' HOME switch until it trips.
// The switch itself sets axisPos to 0 via isPhysicalBlocked().
bool homeAxis(uint8_t axis)
{
  return seekLimit(axis, homeEndOf(axis));
}

// Raise Z until the TOP SWITCH stops it.
//
// This is what pin 29 bought us. The old code could not lift Z until
// it had been homed at the BOTTOM, because "the top" was a count of
// steps and a count needs a zero to start from - so getting clear of
// the bed meant going down into the bed first. Now the top is a
// switch: drive at it and it stops you, homed or not.
bool zGoTop()
{
  return seekLimit(AXIS_Z, travelEndOf(AXIS_Z));
}

// ------------------------------------------------------------
// 0+  -  the "reset everything" homing.
// ------------------------------------------------------------
// Plain 0 homes X/Y and deliberately leaves Z alone. 0+ resets the
// Z axis as well, which takes two moves rather than one:
//
//   Z DOWN into its BOTTOM switch    - the axis' true zero, and the
//     GROUND everything is measured from. Both ends are switches
//     now, so this run is no longer needed to find the top - but it
//     is still needed for any height to MEAN anything.
//
//   Z UP into its TOP switch         - where the claw wants to sit
//     between jobs: clear of the bed and clear of anything built.
//     Doing it in this order also measures the switch-to-switch
//     distance for free.
//
// Z is done BEFORE X/Y so the gantry never drags a low claw across
// the bed - by the time X/Y move, the claw is parked at the top.
bool goToOriginWithZ()
{
  Serial.println();
  Serial.println("=== FULL RESET - Z, then X/Y ===");

  // ---- 1. give Z a real zero ----
  Serial.println("  [1/3] Z down into its BOTTOM switch (true zero)...");
  if (!homeAxis(AXIS_Z))
  {
    Serial.println("  ABORTED - Z never found its bottom switch.");
    Serial.println("  X/Y were NOT homed: moving now could drag the claw.");
    return false;
  }

  // ---- 2. park it at the top ----
  Serial.println("  [2/3] Z up into its TOP switch (pin 29)...");

  bool okZ = zGoTop();
  if (!okZ)
  {
    // Z has a valid zero and stopped somewhere known, so homing X/Y
    // is still safe and still worth doing. Say so and carry on.
    Serial.println("  WARNING - Z never reached the top switch.");
  }
  else
  {
    printZTravelMeasurement();
  }

  // ---- 3. now the claw is high, walk the gantry home ----
  Serial.println("  [3/3] Homing X/Y...");
  bool okXY = goToOrigin();

  Serial.println();
  if (okXY && okZ)
  {
    Serial.println("FULL RESET COMPLETE - X/Y at origin, Z on its top switch.");
    return true;
  }

  Serial.println("FULL RESET INCOMPLETE - see the warnings above.");
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

// Envelope size and direction of travel for an axis. The grid only
// covers X and Y, whose far ends are software caps - taken through
// axisTravelOf so the two can never drift apart.
long gridTravelOf(uint8_t axis)
{
  return axisTravelOf(axis);
}

int8_t gridDirOf(uint8_t axis)
{
  return travelEndOf(axis);
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

// ------------------------------------------------------------
// Looking switches up in the table.
// ------------------------------------------------------------
// Everything below asks "is there a switch at THIS end of THIS axis",
// which is what makes a second switch on Z cost nothing: Z+ is found
// by the same lookup that finds X+ or Y-.

// The switch guarding one end of one axis, or -1 if that end is open.
int8_t findLimitIndex(uint8_t axis, int8_t end)
{
  for (uint8_t i = 0; i < LIMIT_COUNT; i++)
  {
    if (LIMITS[i].axis == axis && LIMITS[i].end == end)
    {
      return (int8_t)i;
    }
  }
  return -1;
}

// The switch that defines position 0 for an axis.
int8_t homeLimitIndexOf(uint8_t axis)
{
  for (uint8_t i = 0; i < LIMIT_COUNT; i++)
  {
    if (LIMITS[i].axis == axis && LIMITS[i].isHome)
    {
      return (int8_t)i;
    }
  }
  return -1;
}

// Which end of the axis its home switch sits at. Homing drives this
// way; the axis then travels the opposite way.
int8_t homeEndOf(uint8_t axis)
{
  int8_t idx = homeLimitIndexOf(axis);
  return (idx >= 0) ? LIMITS[idx].end : DIR_NEG;
}

// The direction an axis travels AWAY from its home switch - the
// direction its positions count up in.
int8_t travelEndOf(uint8_t axis)
{
  return (int8_t)(-homeEndOf(axis));
}

// How far an axis can go, in steps, whatever enforces the far end:
// X/Y are held by a software cap, Z by the pin 29 switch. Used for
// the homing cap and the grid maths, so neither has to care which
// kind of limit an axis has.
long axisTravelOf(uint8_t axis)
{
  if (axis == AXIS_Z)
  {
    return Z_TRAVEL_STEPS; // sizing figure, not a cap - SECTION 6B
  }
  return softTravelOf(axis);
}

bool limitEnabledAt(uint8_t axis, int8_t end)
{
  int8_t idx = findLimitIndex(axis, end);
  return (idx >= 0) && LIMITS[idx].enabled;
}

// Debounced read of one switch by table index.
bool isLimitHitAt(int8_t idx)
{
  if (idx < 0)
  {
    return false;
  }

  const LimitSwitch &sw = LIMITS[idx];

  if (!sw.enabled)
  {
    return false;
  }
  if (!interpretLimit(digitalRead(sw.pin), sw.useNC))
  {
    return false;
  }

  delayMicroseconds(LIMIT_CONFIRM_US);
  return interpretLimit(digitalRead(sw.pin), sw.useNC);
}

// ------------------------------------------------------------
// What a switch does to the position counter when it trips.
// ------------------------------------------------------------
// A HOME switch (X+, Y-, Z-) means "you are at 0" and says so.
//
// A FAR-END switch - today only Z+ on pin 29 - means "you are at the
// far end", which is a weaker statement: the exact step count out
// there is a property of the hardware, not something the switch can
// tell us. So it does the useful thing instead and RECORDS what was
// counted, which is the number Z_TRAVEL_STEPS wants to be.
void applyLimitReference(int8_t idx)
{
  const LimitSwitch &sw = LIMITS[idx];
  uint8_t axis = sw.axis;

  if (sw.isHome)
  {
    if (SOFT_ZERO_ON_LIMIT_HIT)
    {
      axisPos[axis] = 0;
      axisHomed[axis] = true;
      axisRefAtHome[axis] = true;
    }
    return;
  }

  if (axisRefAtHome[axis])
  {
    // We climbed here from a true zero, so the count IS the real
    // switch-to-switch distance. Keep it (see SECTION 6).
    zTravelMeasured = axisPos[axis] * (long)travelEndOf(axis);

    if (!Z_TOP_REFERENCES_POSITION)
    {
      return;
    }
  }

  // Either the axis had no zero to count from, or we were told to
  // trust the constant over the count. Adopt the configured travel -
  // and remember that this position is a constant, not a measurement,
  // so resting here cannot be mistaken for measuring the travel.
  axisPos[axis] = axisTravelOf(axis) * (long)travelEndOf(axis);
  axisHomed[axis] = true;
  axisRefAtHome[axis] = false;
}

bool isPhysicalBlocked(uint8_t axis, int8_t sign)
{
  int8_t idx = findLimitIndex(axis, sign);
  if (idx < 0)
  {
    return false; // no switch guards this direction
  }

  if (!isLimitHitAt(idx))
  {
    return false;
  }

  applyLimitReference(idx);
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

// One line per switch in the table, so adding a switch adds a line
// here with no extra code. Z prints twice now: Z- and Z+.
void printLimitStatus()
{
  Serial.println();
  Serial.println("--- PHYSICAL LIMIT SWITCHES ---");

  for (uint8_t i = 0; i < LIMIT_COUNT; i++)
  {
    const LimitSwitch &sw = LIMITS[i];

    Serial.print(axisName(sw.axis));
    Serial.print(signName(sw.end));
    Serial.print(" (pin ");
    Serial.print(sw.pin);
    Serial.print(", ");
    Serial.print(sw.useNC ? "NC" : "NO");
    Serial.print(sw.isHome ? ", HOME/zero" : ", far end");
    Serial.print("): ");

    if (!sw.enabled)
      Serial.println("DISABLED IN CONFIG");
    else if (isLimitHitAt((int8_t)i))
      Serial.println("*** LIMIT HIT ***");
    else
      Serial.println("clear");
  }
}

// What the rig last counted between the two Z switches, against what
// SECTION 6B says it should be. This is the calibration feedback the
// top switch made possible - before pin 29 there was nothing at the
// top to measure against.
void printZTravelMeasurement()
{
  if (zTravelMeasured <= 0)
  {
    return;
  }

  long diff = zTravelMeasured - Z_TRAVEL_STEPS;

  Serial.print("  Z switch-to-switch: measured ");
  Serial.print(zTravelMeasured);
  Serial.print(" steps, configured ");
  Serial.print(Z_TRAVEL_STEPS);
  Serial.print("  (diff ");
  if (diff > 0)
  {
    Serial.print("+");
  }
  Serial.print(diff);
  Serial.println(")");

  if (diff != 0)
  {
    Serial.print("  -> set Z_TRAVEL_STEPS = ");
    Serial.print(zTravelMeasured);
    Serial.println(" in SECTION 6B to match the rig.");
  }
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
    // Z is the deliberate case: its far end is the pin 29 switch,
    // so it is meant to have no software cap at all.
    if (limitEnabledAt(axis, travelEndOf(axis)))
    {
      Serial.print("none - hardware switch on pin ");
      Serial.println(LIMITS[findLimitIndex(axis, travelEndOf(axis))].pin);
    }
    else
    {
      Serial.println("INFINITE / disabled");
    }
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
  Serial.println("(both ends of Z are real switches - see above)");
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

void printServoStatus()
{
  Serial.println();
  Serial.println("--- GRIPPER SERVO ---");
  Serial.print("Pin ");
  Serial.print(SERVO_PIN);
  Serial.print(": ");
  Serial.println(servoIsOpen ? "OPEN" : "CLOSED");
}

void printAuxStepperStatus()
{
  Serial.println();
  Serial.println("--- AUX STEPPER (28BYJ-48) ---");
  Serial.print("Pins IN1-IN4: ");
  Serial.print(AUX_STEPPER_IN1);
  Serial.print(", ");
  Serial.print(AUX_STEPPER_IN2);
  Serial.print(", ");
  Serial.print(AUX_STEPPER_IN3);
  Serial.print(", ");
  Serial.println(AUX_STEPPER_IN4);
  Serial.print("Net position: ");
  if (auxStepperPos > 0)
    Serial.print("+");
  Serial.print(auxStepperPos);
  Serial.println(" steps (since power-on)");
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
    axisHomed[a] = false;     // a manual zero is NOT a homed origin
    axisRefAtHome[a] = false; // ...and definitely not a switch one
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
  printServoStatus();
  printAuxStepperStatus();
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
  Serial.print("Jog size: X/Y ");
  Serial.print(stepsPerMove);
  Serial.print(" steps @ ");
  Serial.print(STEP_DELAY);
  Serial.print(" us  |  Z ");
  Serial.print(stepsPerMoveZ);
  Serial.print(" steps @ ");
  Serial.print(STEP_DELAY_Z);
  Serial.println(" us");
  Serial.println("--------------------------------------");
  Serial.println("1 = X-   (M1 CW  / M2 CW )  [soft limit]");
  Serial.println("2 = X+   (M1 CCW / M2 CCW)  [limit: pin 30]");
  Serial.println("3 = Y-   (M1 CW  / M2 CCW)  [limit: pin 31]");
  Serial.println("4 = Y+   (M1 CCW / M2 CW )  [soft limit]");
  Serial.println("5 = Show counters / position / limits");
  Serial.println("6 = Reset step counters");
  Serial.println("7 = Disable both motors");
  Serial.println("8 = Zero position (manual, NOT a home)");
  Serial.println("9 = Show ASCII grid map");
  Serial.println("0 = HOME / go to origin (X/Y switches only)");
  Serial.println("0+= FULL RESET: also zero Z and park it at the top");
  Serial.println("--------------------------------------");
  Serial.println("D = Z-   (M3 CW )           [limit: pin 28, GROUND]");
  Serial.println("U = Z+   (M3 CCW)           [limit: pin 29, TOP]");
  Serial.println("--------------------------------------");
  Serial.println("O = Servo OPEN              [pin 6]");
  Serial.println("C = Servo CLOSE             [pin 6]");
  Serial.println("--------------------------------------");
  Serial.println("R  = Aux stepper ~90 deg CW   [28BYJ-48, pins 36-39]");
  Serial.println("RR = Aux stepper ~90 deg CCW  [28BYJ-48, pins 36-39]");
  Serial.println("--------------------------------------");
  Serial.println("G <col> <row>   goto cell, e.g.  G 3 5");
  Serial.println("S <cols> <rows> resize grid, e.g. S 20 39");
  Serial.println("?               reprint this help");
  Serial.println("(D, U, O, C, R, RR, G and S need a newline / Enter)");
  Serial.println("======================================");
}

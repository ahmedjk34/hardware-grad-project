/*
  ============================================================
  Dual TB6600 + Arduino MEGA 2560
  CNC-style step testing with limit switches, SOFTWARE limits,
  live position tracking, step counters, and GRID ADDRESSING

  Plus a THIRD, independent motor driving a Z axis (single motor,
  not coupled to the X/Y pair), a GRIPPER SERVO on pin 6 with just
  two positions (OPEN and CLOSE), and a FOURTH, independentB 
  28BYJ-48 + ULN2003 stepper that only jogs +/-90 degrees on command.

  NEW IN build_tesT_v1:  the  B  (BUILD) command - one full
  pick-and-place cycle expressed in BLOCK LEVELS instead of steps.
  ============================================================C

  SERIAL COMMANDS
    1 = X-   (Motor 1 CW  / Motor 2 CW )   <-- SOFTWARE limit end
    2 = X+   (Motor 1 CCW / Motor 2 CCW)   <-- physical limit switch end
    3 = Y-   (Motor 1 CW  / Motor 2 CCW)   <-- physical limit switch end
    4 = Y+   (Motor 1 CCW / Motor 2 CW )   <-- SOFTWARE limit end
    5 = FULL MACHINE REPORT (position, counters, every statistic)
    6 = Reset ALL statistics to zero
    7 = Disable both motors (release holding torque)
    8 = ZERO the position counters (set "here" as origin 0,0)
    9 = Show ASCII grid map + current cell
    0 = HOME / GO TO ORIGIN (drive into both switches, X/Y only)
    0+ = FULL RESET: Z down to its switch, Z up to the soft limit,
         then home X/Y. Use this to put the rig in a known state.

    D = Z-   (Motor 3 CW )   <-- physical limit switch end
    U = Z+   (Motor 3 CCW)   <-- SOFTWARE limit end

    O = Servo OPEN   (pin 6)
    C = Servo CLOSE  (pin 6)

    R  = Aux stepper rotate ~90 deg CW   (28BYJ-48, pins 36-39)
    RR = Aux stepper rotate ~90 deg CCW  (28BYJ-48, pins 36-39)

    G <col> <row>   = go to grid cell (1-based). e.g.  G 3 5   or  G3,5
    S <cols> <rows> = change the grid division live. e.g.  S 20 39

    B <col> <row> <level> [R|RR|NR]   = BUILD one block   <<< NEW
    Z               = print the Z / build calibration table  <<< NEW
    ?               = reprint the help text

  Multi-character commands need a newline. Single digit commands
  work with or without one - including 0 and 0+, which are special
  cased in checkSerial() so the '+' has a chance to arrive. D, U, O, C, R and Z are letters, so like
  G/S/B/? they need a newline too. RR is two letters and ALSO needs
  a newline - there is no single-character fast path for it.

  ------------------------------------------------------------
  COORDINATE SYSTEM  (this is the important part)
  ------------------------------------------------------------
  SOFT_ZERO_ON_LIMIT_HIT is true, so each physical switch zeros its
  own axis the moment it trips. The corner where BOTH switches are
  pressed is therefore machine position (0, 0) = the ORIGIN.

  Each axis travels AWAY from its own switch. The two switches sit at
  OPPOSITE ends now, so the two axes no longer share a sign:

      X switch at the X+ end  ->  X runs   0  ...  -5050   (soft limit)
      Y switch at the Y- end  ->  Y runs   0  ...  +8500   (soft limit)
      Z switch at the Z- end  ->  Z runs   0  ...  +1350   (soft limit)

  So the work envelope is 5050 x 8500 steps, living in the rectangle
  X in [-5050, 0], Y in [0, +8500]. Grid indices hide this sign mess:

      col 1  = nearest the X switch (X = 0 side, the X+ end)
      col N  = far end of X travel  (X = -5050 side)
      row 1  = nearest the Y switch (Y = 0 side)
      row M  = far end of Y travel  (Y = +8500 side)

  Generalised in code as: each axis extends from 0 in the direction
  softEndOf(axis), for softTravelOf(axis) steps. Change the soft
  limits and the grid rescales itself automatically.

  Z works the same way: Z = 0 is the physical switch (the GROUND /
  table surface, claw all the way down) and Z = +SOFT_LIMIT_Z_TRAVEL
  is the top of travel. SECTION 6E turns that step range into
  centimetres and then into BLOCK LEVELS.

  ------------------------------------------------------------
  GO-TO SEQUENCE
  ------------------------------------------------------------
    1. Home Y into its switch, then home X into its switch  (= origin)
    2. Move Y to the target row
    3. Move X to the target column
  Re-homing every time means lost steps never accumulate.

  ------------------------------------------------------------
  BUILD SEQUENCE  (the B command)                        <<< NEW
  ------------------------------------------------------------
    1. Z up to the software limit                (clear of everything)
    2. X/Y home to the origin                    (the block feeder)
    3. Un-rotate the claw if the LAST build rotated it
    4. Open the claw
    5. Z down to GROUND (into the Z switch - this also re-zeroes Z)
    6. Close the claw                            (block is now held)
    7. Z up to the software limit                (carry height)
    8. X/Y to the requested cell
    9. Rotate the claw if this build asked for R / RR
   10. Z down to the requested BLOCK LEVEL
   11. Open the claw                             (block is placed)

  ...then it PARKS itself, so the rig never sits over the stack with
  an open claw and the next B starts from a known state:

   12. Z up to the software limit                (clear of the block)
   13. X/Y home to the origin
   14. Rotate the claw back to neutral           (if this build turned it)

  Phases 12-14 are skipped if BUILD_PARK_AFTER_PLACE is false. A
  failure in them is a WARNING, not a failed build - the block is
  already down by then.

  ------------------------------------------------------------
  A NOTE ON F("...")  -  DO NOT DROP IT
  ------------------------------------------------------------
  The MEGA has 8 KB of SRAM, and on AVR every plain string literal
  handed to Serial.print() is COPIED INTO SRAM at boot. This sketch
  prints a lot of text, and written the naive way it needed 9443
  bytes of SRAM - 115% of the chip. It would not have run.

  Wrapping the literals in F() keeps them in flash and streams them
  out instead, which costs nothing but a little program space:

        SRAM   9443 bytes (115%)   ->   2099 bytes (26%)
        flash 39158 bytes  (15%)   ->  40590 bytes (15%)

  So: any new Serial.print of a fixed string MUST be F("..."), e.g.
        Serial.println(F("--- MY NEW SECTION ---"));
  Variables print normally - F() is only for literals.

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

// The servo is commanded and then forgotten - nothing reports back
// when it has actually arrived. The build sequence must not start
// moving Z while the jaws are still swinging, so every open/close
// inside a build waits this long afterwards.
unsigned int SERVO_SETTLE_MS = 600;

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
// SECTION 2 - MOTION TUNING
// ============================================================

// ------------------------------------------------------------
//   X/Y AND Z ARE TUNED SEPARATELY
// ------------------------------------------------------------
//   The Z axis is a single motor lifting against gravity - and, once
//   a block is gripped, against a load. The pulse rate that suits the
//   X/Y gantry is rarely the one that suits the lift, so Z has its
//   own pulse delay and its own jog size. Change either without
//   touching how the gantry behaves.
//
//   Every Z move goes through these: manual D/U jogs, homing, and
//   the build sequence.

// Half-period of the step pulse, in microseconds. One full step is
// two of these, so 500 us => 1.00 ms per step => ~1000 steps/sec.
// RAISE the Z value to slow Z down (more torque, less chance of
// losing steps under load); LOWER it to speed the lift up.
unsigned int STEP_DELAY = 500;   // X and Y

unsigned int STEP_DELAY_Z = 950; // Z only

// How many steps a single MANUAL jog moves.
//   stepsPerMove  -> the 1-4 commands (X/Y)
//   stepsPerMoveZ -> the D/U commands (Z)
// Z is worth setting finer: 150 steps is only ~2.9 cm of X/Y travel
// but is nearly a fifth of the whole Z range.
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

const int LIMIT_PIN_X = 30; // X AXIS limit switch
const int LIMIT_PIN_Y = 31; // Y AXIS limit switch
const int LIMIT_PIN_Z = 28; // Z AXIS limit switch

const bool LIMIT_X_USE_NC = true;
const bool LIMIT_Y_USE_NC = true;
const bool LIMIT_Z_USE_NC = true;

const int8_t LIMIT_X_AT_END = DIR_POS; // X switch is at the X+ end
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
// These numbers ALSO define the size of the grid envelope, and
// SOFT_LIMIT_Z_TRAVEL is what SECTION 6E converts into centimetres.

const long SOFT_LIMIT_INFINITE = 0; // sentinel: no cap at all

long SOFT_LIMIT_X_TRAVEL = 5050; // X- travel cap, in steps
long SOFT_LIMIT_Y_TRAVEL = 8500; // Y+ travel cap, in steps
long SOFT_LIMIT_Z_TRAVEL = 1350; // Z+ travel cap, in steps

const int8_t SOFT_LIMIT_X_AT_END = DIR_NEG; // guards the X- end
const int8_t SOFT_LIMIT_Y_AT_END = DIR_POS; // guards the Y+ end
const int8_t SOFT_LIMIT_Z_AT_END = DIR_POS; // guards the Z+ end (up)

const bool SOFT_LIMIT_X_ENABLED = true;
const bool SOFT_LIMIT_Y_ENABLED = true;
const bool SOFT_LIMIT_Z_ENABLED = true;

// Re-zero an axis automatically the moment its PHYSICAL switch trips.
// REQUIRED for the grid AND for the build levels to mean anything -
// leave this true.
const bool SOFT_ZERO_ON_LIMIT_HIT = true;

const bool SOFT_LIMIT_VERBOSE = true;

// ============================================================
// SECTION 6C - GRID CONFIGURATION
// ============================================================
//
// The envelope (5050 x 8500 steps) is divided into COLS x ROWS
// equal rectangles. The machine parks at the CENTRE of a cell.
//
// Cell size does NOT have to divide evenly into the travel. Targets
// are computed from the absolute position each time, so rounding
// error is always under one step and never accumulates.
//
// ------------------------------------------------------------
//   HOW FINE CAN THIS GO?
// ------------------------------------------------------------
//   Arithmetically the floor is 1 step per cell (5050 x 8500
//   = 42.9 million cells), which is meaningless - it is far below
//   what the machine can repeat mechanically.
//
//   The envelope is 5050:8500, which reduces to 101:170 (gcd 50).
//   SQUARE cells in whole steps therefore need cols:rows = 101:170,
//   and the only whole-step cell sizes are the divisors of 50:
//        COLS   ROWS   CELL (X x Y)      CELLS
//         101 x  170      50 x  50       17170   <- coarsest square
//         202 x  340      25 x  25       68680
//         505 x  850      10 x  10      429250
//        1010 x 1700       5 x   5     1717000
//        5050 x 8500       1 x   1    42925000   <- 1 step per cell
//
//   NOTE: the 10 x 20 default below is NOT square - it gives
//   505 x 425 step cells. Square cells are impractically fine on
//   this envelope, so the default trades squareness for usable size.
//
//   Change these here, or live with:  S <cols> <rows>

long GRID_COLS = 10;
long GRID_ROWS = 20;

// The ceiling is one step per cell, so it is NOT a fixed number -
// it follows the software limits. Re-tune a travel cap and the
// allowed grid range follows it automatically.
long gridCountMaxOf(uint8_t axis)
{
  return softTravelOf(axis);
}

// The ASCII map is only drawn when the grid is small enough to be
// readable. Bigger grids print a numeric summary instead.
const long GRID_MAP_MAX_COLS = 48;
const long GRID_MAP_MAX_ROWS = 48;

// Last commanded cell. 0 = unknown / not on a cell.
long curCol = 0;
long curRow = 0;

// ============================================================
// SECTION 6D - HOMING CONFIGURATION
// ============================================================

// Steps per homing chunk. Between chunks the switch is re-checked
// anyway by moveSteps, so this mostly controls report granularity.
const long HOME_CHUNK_STEPS = 200;

// Safety stop: if an axis has travelled this far without finding its
// switch, something is wrong (broken switch, unplugged, wrong pin).
//
// Derived from the soft travel rather than hard-coded, so re-tuning a
// travel cap can never leave a stale homing cap behind. Two full
// lengths plus slack covers "we started at the far end and the axis
// has drifted", which is the worst honest case.
const long HOME_MAX_MULTIPLIER = 2;
const long HOME_MAX_SLACK_STEPS = 500;

// Used only when an axis has no usable soft travel to derive from.
const long HOME_MAX_STEPS_FALLBACK = 20000;

const bool HOME_VERBOSE = true;

// ============================================================
// SECTION 6E - Z HEIGHT / BLOCK LEVEL CALIBRATION     <<< NEW
// ============================================================
//
// Everything the BUILD command knows about height lives here. Change
// a number in this section and the whole build system rescales - no
// other code needs touching.
//
// ------------------------------------------------------------
//   THE ONE MEASUREMENT THAT MATTERS
// ------------------------------------------------------------
//   Z_TRAVEL_CM is the REAL, TAPE-MEASURED distance the claw covers
//   between the two ends of its travel:
//
//        bottom = the Z physical limit switch  (Z = 0 steps, GROUND)
//        top    = the Z software limit         (Z = SOFT_LIMIT_Z_TRAVEL)
//
//   Those two ends are SOFT_LIMIT_Z_TRAVEL steps apart, so:
//
//        steps per cm = SOFT_LIMIT_Z_TRAVEL / Z_TRAVEL_CM
//                     = 1350 / 27.0
//                     = 50.00 steps per cm exactly
//
//   and one 1.5 cm block is 1.5 * 50 = 75 steps exactly. That the
//   numbers come out round here is luck, not a requirement - the
//   maths below rounds to the nearest step either way.
//
//   This is computed at RUN TIME by zStepsPerCm(), never hard-coded,
//   so re-measuring the rig or re-tuning SOFT_LIMIT_Z_TRAVEL is a
//   one-line change. Send  Z  to print the resulting table.

// Real-world height of the full Z travel, in centimetres.
float Z_TRAVEL_CM = 27.0;

// Height of one block, in centimetres. Levels are multiples of this:
//   level 0 = GROUND (drive into the physical switch)
//   level 1 = 1.5 cm, level 2 = 3.0 cm, level 3 = 4.5 cm ...
float BLOCK_HEIGHT_CM = 1.5;

// ------------------------------------------------------------
//   MARGIN OF ERROR  (all three may be POSITIVE or NEGATIVE)
// ------------------------------------------------------------
//   Reality never matches the arithmetic exactly. If a placed block
//   ends up 1.52 cm high instead of 1.50, the error is PER LEVEL and
//   it accumulates up the stack - trim it with the PER_LEVEL margin.
//   If every level is uniformly a bit low or high (claw geometry, the
//   switch tripping early, block lip), that is a CONSTANT error -
//   trim it with the FIXED margin.
//
//        target_cm = level * (BLOCK_HEIGHT_CM + Z_MARGIN_PER_LEVEL_CM)
//                    + Z_MARGIN_FIXED_CM
//        target_steps = round(target_cm * stepsPerCm) + Z_MARGIN_FIXED_STEPS
//
//   Examples:
//     blocks land 0.02 cm too HIGH each level  ->  PER_LEVEL = -0.02
//     blocks land 0.02 cm too LOW  each level  ->  PER_LEVEL = +0.02
//     everything sits 0.10 cm too low          ->  FIXED     = +0.10
//
//   Level 0 ignores all of these on purpose: ground is the physical
//   switch, not a computed number, so it cannot drift.

float Z_MARGIN_PER_LEVEL_CM = 0.0;  // cm added to EACH level (cumulative)
float Z_MARGIN_FIXED_CM = 0.0;      // cm added ONCE to any level >= 1
long Z_MARGIN_FIXED_STEPS = 0;      // raw step trim, applied last

// ------------------------------------------------------------
//   HOW HIGH ARE WE ALLOWED TO BUILD?
// ------------------------------------------------------------
//   The claw can physically reach Z_TRAVEL_CM (27 cm), but building
//   that high leaves no room to fly a block over the stack. Cap the
//   BUILD height lower than the travel and keep the difference as
//   headroom: carry height is always the full software limit, so
//   (Z_TRAVEL_CM - MAX_BUILD_HEIGHT_CM) is the clearance over the
//   tallest possible tower.
//
//   The highest usable level is floor(MAX_BUILD_HEIGHT_CM /
//   BLOCK_HEIGHT_CM) - it does NOT have to come out even.
//     25.0 / 1.5 = 16.67  ->  level 16  (24.0 cm), 3.0 cm of headroom

float MAX_BUILD_HEIGHT_CM = 25.0;

// Rounding slack so a cap that is an exact multiple of the block
// height (e.g. 24.0 / 1.5 = 16) is not lost to float error.
const float LEVEL_EPSILON = 0.001;

// ------------------------------------------------------------
//   BUILD BEHAVIOUR
// ------------------------------------------------------------

// Pause after each phase of the build, so the rig settles (and so a
// human can follow along / hit reset). 0 disables.
unsigned int BUILD_PHASE_PAUSE_MS = 250;

// After the block is released, PARK the rig: lift Z clear of what was
// just placed, walk X/Y back to the origin, and un-rotate the claw.
//
// This leaves the machine in exactly the state a build expects to
// start from, so the rig is never left hanging over a stack with an
// open claw - and the next B command finds everything already where
// it wants it (its first two phases become no-ops).
//
// Set false only if you want the claw to stay put over the block it
// just placed, e.g. while eyeballing placement accuracy by hand.
bool BUILD_PARK_AFTER_PLACE = true;

// How many phases a full build prints. Purely cosmetic - it only
// feeds the "[BUILD n/N]" progress lines.
const uint8_t BUILD_STEP_COUNT = 14;

const bool BUILD_VERBOSE = true;

// ============================================================
// SECTION 6F - CLAW ROTATION STATE                    <<< NEW
// ============================================================
//
// The claw is assumed to START in the neutral / correct orientation -
// it is set by hand (or by R / RR) before the program is driven.
//
// A build may ask for R (90 CW) or RR (90 CCW) so the block lands
// turned. That leaves the claw turned too, which would be wrong for
// the NEXT pick-up. So the build sequence always UN-ROTATES back to
// neutral while it is over the feeder at 0,0 - before it descends -
// and only then applies whatever THIS build asked for, at the target.
//
//   last build did R   ->  next build rotates RR at home  (back to 0)
//   last build did RR  ->  next build rotates R  at home  (back to 0)
//   last build did NR  ->  nothing to undo

const int8_t ROT_NONE = 0;
const int8_t ROT_CW = +1;  // "R"
const int8_t ROT_CCW = -1; // "RR"

// Where the claw is RIGHT NOW, relative to neutral.
int8_t clawRotation = ROT_NONE;

// ============================================================
// SECTION 7 - STEP COUNTER / POSITION CONFIGURATION
// ============================================================

unsigned long stepCounts[MOVE_COUNT] = {0, 0, 0, 0, 0, 0};

long axisPos[AXIS_COUNT] = {0, 0, 0};

// True only after a successful home. Grid moves and builds refuse to
// run before this, because both are nonsense without a real origin.
// (Z is set true the moment its physical switch trips, same as X/Y.)
bool axisHomed[AXIS_COUNT] = {false, false, false};

const bool SHOW_DISTANCE = false;
const float STEPS_PER_UNIT = 200.0;
const char *DISTANCE_UNIT = "mm";

// ============================================================
// SECTION 7B - STATISTICS                             <<< NEW
// ============================================================
//
// Everything the machine has done since power-on (or since the last
// stats reset with command 6). Command 5 prints all of it.
//
// These are diagnostics, not control state - nothing here ever
// changes what the machine does. That means a reset is always safe.

// --- when the current stats window started ---
unsigned long statsSinceMs = 0;

// --- commands accepted, by kind ---
unsigned long statJogs = 0;         // 1-4, D, U
unsigned long statGotos = 0;        // G
unsigned long statHomeCommands = 0; // 0
unsigned long statBuildCommands = 0;// B (parsed OK, whether or not it ran)
unsigned long statBadCommands = 0;  // unparseable / unknown lines

// --- per axis ---
unsigned long statHomeRuns[AXIS_COUNT] = {0, 0, 0};
unsigned long statHomeFails[AXIS_COUNT] = {0, 0, 0};
unsigned long statLimitTrips[AXIS_COUNT] = {0, 0, 0};  // switch hit events
unsigned long statSoftBlocks[AXIS_COUNT] = {0, 0, 0};  // soft limit refusals
unsigned long statShortMoves[AXIS_COUNT] = {0, 0, 0};  // moves that stopped early

// Edge detection, so one physical trip counts once instead of once
// per step spent sitting on the switch.
bool limitWasActive[AXIS_COUNT] = {false, false, false};
bool softWasActive[AXIS_COUNT] = {false, false, false};

// --- gripper + rotation ---
unsigned long statServoOpens = 0;
unsigned long statServoCloses = 0;
unsigned long statRotCW = 0;
unsigned long statRotCCW = 0;

// --- builds ---
unsigned long statBuildsAttempted = 0;
unsigned long statBuildsCompleted = 0;
unsigned long statBuildsRejected = 0; // failed validation, never moved
unsigned long statBuildsAborted = 0;  // started moving, then failed
unsigned long statBuildTotalMs = 0;   // completed builds only
unsigned long statBuildLastMs = 0;
unsigned long statBuildFastestMs = 0; // 0 = none yet
unsigned long statBuildSlowestMs = 0;

// Last build, whatever happened to it.
long statLastCol = 0;
long statLastRow = 0;
long statLastLevel = -1; // -1 = no build yet
int8_t statLastRot = ROT_NONE;
bool statLastOk = false;
const char *statLastFailure = NULL; // NULL = it succeeded

// Blocks actually placed, per level. Sized generously so a re-tune of
// BLOCK_HEIGHT_CM cannot overflow it; levels past the end are still
// counted in the total, just not in the histogram.
const uint8_t LEVEL_HISTOGRAM_SIZE = 40;
uint16_t statBlocksAtLevel[LEVEL_HISTOGRAM_SIZE];
unsigned long statBlocksPlaced = 0;

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

const char CMD_MOVE_Z_NEG = 'D'; // Z-  (physical limit switch end)
const char CMD_MOVE_Z_POS = 'U'; // Z+  (software limit end)

const char CMD_SERVO_OPEN = 'O';
const char CMD_SERVO_CLOSE = 'C';

const char CMD_AUX_STEPPER_CW = 'R'; // "R"  (RR is handled in handleLine)

const char CMD_BUILD = 'B';      // B <col> <row> <level> [R|RR|NR]
const char CMD_Z_TABLE = 'Z';    // print the Z / build calibration

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
// "0" / "0+" has stopped growing and can be run. See
// flushPendingZeroCommand(). A whole line arrives from the Serial
// Monitor in one burst, so this only ever expires between commands.
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

  pinMode(LIMIT_PIN_X, INPUT_PULLUP);
  pinMode(LIMIT_PIN_Y, INPUT_PULLUP);
  pinMode(LIMIT_PIN_Z, INPUT_PULLUP);

  digitalWrite(STEP_PIN1, LOW);
  digitalWrite(STEP_PIN2, LOW);
  digitalWrite(STEP_PIN3, LOW);

  disableMotors();

  gripperServo.attach(SERVO_PIN);
  gripperServo.write(SERVO_CLOSE_ANGLE);
  servoIsOpen = false;

  auxStepper.setSpeed(AUX_STEPPER_SPEED_RPM);

  // The claw is assumed to be physically neutral at power-on.
  clawRotation = ROT_NONE;

  // Start the statistics window with the machine.
  statsSinceMs = millis();

  Serial.begin(9600);
  delay(1000);

  printInstructions();
  printLimitStatus();
  printSoftLimitStatus();
  printGridConfig();
  printServoStatus();
  printAuxStepperStatus();
  printBuildConfig();

  Serial.println();
  Serial.println(F(">> Position is UNKNOWN until you home. Send 0 to home."));
  Serial.println(F(">> B homes everything itself, including Z."));
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
    // has to wait and see what follows. Everything below - the
    // not-a-plus flush and the idle flush - exists to make that wait
    // invisible: a plain 0 still behaves exactly as it always did.
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
      Serial.println(F("  ERROR - command too long, ignored."));
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
  char head = toUpperChar(line[0]);

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
      statHomeCommands++;
      goToOriginWithZ();
    }
    else
    {
      statBadCommands++;
      Serial.println();
      Serial.println(F("  ERROR - use:  0 (home X/Y) or 0+ (reset Z too)"));
    }
    break;

  case 'G':
    if (parseTwoNumbers(line + 1, &a, &b))
    {
      statGotos++;
      gotoCell(a, b);
    }
    else
    {
      statBadCommands++;
      Serial.println();
      Serial.println(F("  ERROR - use:  G <col> <row>   e.g.  G 3 5"));
    }
    break;

  case 'S':
    if (parseTwoNumbers(line + 1, &a, &b))
    {
      setGridSize(a, b);
    }
    else
    {
      statBadCommands++;
      Serial.println();
      Serial.println(F("  ERROR - use:  S <cols> <rows>   e.g.  S 20 39"));
    }
    break;

  case CMD_BUILD:
    handleBuildCommand(line + 1);
    break;

  case 'R':
    if (toUpperChar(line[1]) == 'R' && line[2] == '\0')
    {
      rotateAuxStepperCCW();
    }
    else
    {
      statBadCommands++;
      Serial.println();
      Serial.println(F("  ERROR - use:  R (CW ~90 deg) or RR (CCW ~90 deg)"));
    }
    break;

  default:
    statBadCommands++;
    Serial.println();
    Serial.print(F("  Unknown command: "));
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
    printFullReport();
    break;

  case CMD_RESET_COUNTS:
    resetStatistics();
    break;

  case CMD_MOTORS_OFF:
    disableMotors();
    Serial.println();
    Serial.println(F("MOTORS OFF (holding torque released)"));
    break;

  case CMD_ZERO_POSITION:
    zeroPosition();
    break;

  case CMD_SHOW_GRID:
    printGrid();
    break;

  case CMD_GO_ORIGIN:
    statHomeCommands++;
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

  case CMD_Z_TABLE:
    printBuildConfig();
    printLevelTable();
    break;

  case CMD_BUILD:
    printBuildUsage();
    break;

  default:
    break;
  }
}

char toUpperChar(char c)
{
  if (c >= 'a' && c <= 'z')
  {
    return c - 'a' + 'A';
  }
  return c;
}

// Pulls up to maxCount integers out of a string, ignoring any
// separators (space, comma, colon, etc). Reports how many it found
// and where it stopped, so a trailing keyword can be parsed after it.
uint8_t parseNumbers(const char *s, long *out, uint8_t maxCount, uint8_t *endIndex)
{
  uint8_t found = 0;
  uint8_t i = 0;

  while (s[i] != '\0' && found < maxCount)
  {
    if (s[i] >= '0' && s[i] <= '9')
    {
      long v = 0;
      while (s[i] >= '0' && s[i] <= '9')
      {
        v = v * 10 + (s[i] - '0');
        i++;
      }
      out[found++] = v;
    }
    else if (s[i] >= 'A' && s[i] <= 'Z')
    {
      break; // a keyword started - stop, do not eat it
    }
    else if (s[i] >= 'a' && s[i] <= 'z')
    {
      break;
    }
    else
    {
      i++;
    }
  }

  if (endIndex != NULL)
  {
    *endIndex = i;
  }
  return found;
}

// Kept for G and S, which want exactly two numbers.
bool parseTwoNumbers(const char *s, long *outA, long *outB)
{
  long values[2] = {0, 0};

  if (parseNumbers(s, values, 2, NULL) < 2)
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
// pulse rate and jog size - every Z move reads these, so there is
// one place to change and no way for the two to drift apart.
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
  Serial.print(F("COMMAND: "));
  Serial.println(m.label);

  statJogs++;

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

  Serial.print(F("  Moved "));
  Serial.print(moved);
  Serial.print(F(" of "));
  Serial.print(jog);
  Serial.print(F(" steps  ["));
  Serial.print(m.label);
  Serial.print(F("]  pos "));
  Serial.print(axisName(m.axis));
  Serial.print(F(" = "));
  Serial.println(axisPos[m.axis]);

  if (moved < (unsigned long)jog)
  {
    statShortMoves[m.axis]++;
    uint8_t why = blockReason(m.axis, m.sign);
    Serial.print(F("  STOPPED EARLY - "));
    Serial.print(axisName(m.axis));
    if (why == BLOCK_SOFTWARE)
    {
      Serial.println(F(" SOFTWARE limit reached during the move."));
    }
    else
    {
      Serial.println(F(" limit switch tripped during the move."));
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

  // Read the axis' own pulse rate ONCE, not per step. Because every
  // move funnels through here, this is what gives Z its own speed
  // during homing and the build sequence, not just manual jogs.
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
    statShortMoves[axis]++;
    Serial.print(F("  !! "));
    Serial.print(axisName(axis));
    Serial.print(F(" stopped early at "));
    Serial.print(axisPos[axis]);
    Serial.print(F(" (wanted "));
    Serial.print(target);
    Serial.println(F(")"));
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
// GRIPPER SERVO
// ============================================================

void openServo()
{
  gripperServo.write(SERVO_OPEN_ANGLE);
  servoIsOpen = true;
  statServoOpens++;

  Serial.println();
  Serial.print(F("SERVO: OPEN ("));
  Serial.print(SERVO_OPEN_ANGLE);
  Serial.println(F(" deg)"));
}

void closeServo()
{
  gripperServo.write(SERVO_CLOSE_ANGLE);
  servoIsOpen = false;
  statServoCloses++;

  Serial.println();
  Serial.print(F("SERVO: CLOSE ("));
  Serial.print(SERVO_CLOSE_ANGLE);
  Serial.println(F(" deg)"));
}

// Same as above, but waits for the jaws to actually get there.
// The build sequence must never move Z on top of a moving servo.
void openServoAndWait()
{
  openServo();
  delay(SERVO_SETTLE_MS);
}

void closeServoAndWait()
{
  closeServo();
  delay(SERVO_SETTLE_MS);
}

// ============================================================
// AUXILIARY STEPPER (28BYJ-48)
// ============================================================

void rotateAuxStepperCW()
{
  Serial.println();
  Serial.println(F("AUX STEPPER: rotating ~90 deg CW..."));
  auxStepper.step(AUX_STEPPER_QUARTER_TURN);
  auxStepperPos += AUX_STEPPER_QUARTER_TURN;
  statRotCW++;
  Serial.println(F("AUX STEPPER: done."));
}

void rotateAuxStepperCCW()
{
  Serial.println();
  Serial.println(F("AUX STEPPER: rotating ~90 deg CCW..."));
  auxStepper.step(-AUX_STEPPER_QUARTER_TURN);
  auxStepperPos -= AUX_STEPPER_QUARTER_TURN;
  statRotCCW++;
  Serial.println(F("AUX STEPPER: done."));
}

// ------------------------------------------------------------
// Rotation as a TRACKED STATE, not a blind jog.        <<< NEW
// ------------------------------------------------------------
// Everything the build does goes through here, so clawRotation
// always describes where the claw actually is.

const char *rotationName(int8_t rot)
{
  if (rot == ROT_CW)
  {
    return "R (90 CW)";
  }
  if (rot == ROT_CCW)
  {
    return "RR (90 CCW)";
  }
  return "NR (neutral)";
}

// Turns the claw so it ends up at `target` (ROT_NONE / CW / CCW),
// whatever it is doing now. One quarter turn covers every case we
// use, because the only states are -1, 0 and +1.
void rotateClawTo(int8_t target)
{
  if (clawRotation == target)
  {
    if (BUILD_VERBOSE)
    {
      Serial.print(F("  Claw already at "));
      Serial.print(rotationName(target));
      Serial.println(F(" - no rotation needed."));
    }
    return;
  }

  int8_t delta = target - clawRotation; // -2 .. +2

  Serial.print(F("  Rotating claw: "));
  Serial.print(rotationName(clawRotation));
  Serial.print(F("  ->  "));
  Serial.println(rotationName(target));

  while (delta > 0)
  {
    rotateAuxStepperCW();
    delta--;
  }
  while (delta < 0)
  {
    rotateAuxStepperCCW();
    delta++;
  }

  clawRotation = target;
}

// ============================================================
// HOMING / ORIGIN
// ============================================================

long homeMaxStepsOf(uint8_t axis)
{
  long travel = softTravelOf(axis);

  if (travel <= 0)
  {
    return HOME_MAX_STEPS_FALLBACK; // no cap configured to scale from
  }
  return travel * HOME_MAX_MULTIPLIER + HOME_MAX_SLACK_STEPS;
}

bool limitEnabledOn(uint8_t axis)
{
  if (axis == AXIS_X)
  {
    return LIMIT_X_ENABLED;
  }
  if (axis == AXIS_Y)
  {
    return LIMIT_Y_ENABLED;
  }
  return LIMIT_Z_ENABLED;
}

// Drives toward the axis' physical switch until it trips.
// The switch itself sets axisPos to 0 via isPhysicalBlocked().
bool homeAxis(uint8_t axis)
{
  if (!limitEnabledOn(axis))
  {
    Serial.print(F("  CANNOT HOME "));
    Serial.print(axisName(axis));
    Serial.println(F(" - its limit switch is DISABLED in config."));
    axisHomed[axis] = false;
    statHomeRuns[axis]++;
    statHomeFails[axis]++;
    return false;
  }

  int8_t sign = limitEndOf(axis);
  long travelled = 0;
  long maxSteps = homeMaxStepsOf(axis);

  statHomeRuns[axis]++;

  if (HOME_VERBOSE)
  {
    Serial.print(F("  Homing "));
    Serial.print(axisName(axis));
    Serial.print(signName(sign));
    Serial.print(F(" ..."));
  }

  while (travelled < maxSteps)
  {
    if (isPhysicalBlocked(axis, sign))
    {
      axisPos[axis] = 0; // belt and braces; the check already did it
      axisHomed[axis] = true;
      if (HOME_VERBOSE)
      {
        Serial.print(F(" switch found after "));
        Serial.print(travelled);
        Serial.println(F(" steps. Axis zeroed."));
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
      Serial.println(F(" switch found. Axis zeroed."));
    }
    return true;
  }

  Serial.println();
  Serial.print(F("  HOMING FAILED on "));
  Serial.print(axisName(axis));
  Serial.print(F(" after "));
  Serial.print(travelled);
  Serial.println(F(" steps - switch never tripped."));
  Serial.println(F("  Check wiring, pin number, and NC/NO setting."));
  axisHomed[axis] = false;
  statHomeFails[axis]++;
  return false;
}

// ------------------------------------------------------------
// 0+  -  the "reset everything" homing.
// ------------------------------------------------------------
// Plain 0 homes X/Y and deliberately leaves Z alone. 0+ resets the
// Z axis as well, which takes two moves rather than one:
//
//   Z DOWN into its physical switch  - the only true reference the
//     axis has. A soft limit is just a number counted from the
//     switch, so an axis that has never touched the switch cannot
//     know where its top is. Resetting therefore means going DOWN
//     first, even though the axis ends up at the top.
//
//   Z UP to the software limit       - where the claw wants to sit
//     between jobs: clear of the bed, clear of anything built, and
//     exactly where a build expects to start from.
//
// Z is done BEFORE X/Y so the gantry never drags a low claw across
// the bed - by the time X/Y move, the claw is parked at the top.
bool goToOriginWithZ()
{
  Serial.println();
  Serial.println(F("=== FULL RESET - Z, then X/Y ==="));

  // ---- 1. give Z a real zero ----
  Serial.println(F("  [1/3] Z down into its limit switch (true zero)..."));
  if (!homeAxis(AXIS_Z))
  {
    Serial.println(F("  ABORTED - Z never found its switch."));
    Serial.println(F("  X/Y were NOT homed: moving now could drag the claw."));
    return false;
  }

  // ---- 2. park it at the top ----
  Serial.print(F("  [2/3] Z up to the software limit ("));
  Serial.print(SOFT_LIMIT_Z_TRAVEL);
  Serial.println(F(" steps)..."));

  bool okZ = moveAxisTo(AXIS_Z, zTopPosition());
  if (!okZ)
  {
    // Z has a valid zero and stopped somewhere known, so homing X/Y
    // is still safe and still worth doing. Say so and carry on.
    Serial.println(F("  WARNING - Z stopped short of the top."));
  }

  // ---- 3. now the claw is high, walk the gantry home ----
  Serial.println(F("  [3/3] Homing X/Y..."));
  bool okXY = goToOrigin();

  Serial.println();
  if (okXY && okZ)
  {
    Serial.println(F("FULL RESET COMPLETE - X/Y at origin, Z parked at top."));
    return true;
  }

  Serial.println(F("FULL RESET INCOMPLETE - see the warnings above."));
  return false;
}

// Y first, then X - same order as the go-to sequence.
bool goToOrigin()
{
  Serial.println();
  Serial.println(F("=== GO TO ORIGIN (homing both axes) ==="));

  bool okY = homeAxis(AXIS_Y);
  bool okX = homeAxis(AXIS_X);

  if (okX && okY)
  {
    curCol = 0;
    curRow = 0;
    Serial.println(F("  AT ORIGIN. Position = X 0 / Y 0"));
    return true;
  }

  Serial.println(F("  ORIGIN NOT REACHED - position is NOT trustworthy."));
  return false;
}

// ============================================================
// GRID MATH
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
    Serial.println(F("  ERROR - grid needs BOTH software limits enabled"));
    Serial.println(F("  and non-zero. Check SECTION 6B."));
    return false;
  }
  return true;
}

bool cellInRange(long col, long row)
{
  if (col < 1 || col > GRID_COLS || row < 1 || row > GRID_ROWS)
  {
    Serial.print(F("  ERROR - out of range. Valid: col 1.."));
    Serial.print(GRID_COLS);
    Serial.print(F(", row 1.."));
    Serial.println(GRID_ROWS);
    return false;
  }
  return true;
}

void setGridSize(long cols, long rows)
{
  Serial.println();

  if (cols < 1 || rows < 1 ||
      cols > gridCountMaxOf(AXIS_X) || rows > gridCountMaxOf(AXIS_Y))
  {
    Serial.print(F("  ERROR - grid must be 1.."));
    Serial.print(gridCountMaxOf(AXIS_X));
    Serial.print(F(" cols and 1.."));
    Serial.print(gridCountMaxOf(AXIS_Y));
    Serial.println(F(" rows."));
    return;
  }

  GRID_COLS = cols;
  GRID_ROWS = rows;

  // Old cell numbers no longer mean the same thing.
  curCol = positionToIndex(AXIS_X, axisPos[AXIS_X]);
  curRow = positionToIndex(AXIS_Y, axisPos[AXIS_Y]);

  Serial.println(F("GRID RESIZED"));
  printGridConfig();
}

// ============================================================
// GO TO CELL
// ============================================================

// Homes, then drives Y and X to the centre of the cell.
// Returns true only if BOTH axes actually arrived.
bool gotoCell(long col, long row)
{
  Serial.println();
  Serial.print(F("=== GOTO CELL ["));
  Serial.print(col);
  Serial.print(F(","));
  Serial.print(row);
  Serial.println(F("] ==="));

  if (!gridReady())
  {
    return false;
  }

  if (!cellInRange(col, row))
  {
    return false;
  }

  long targetX = cellTargetPosition(AXIS_X, col);
  long targetY = cellTargetPosition(AXIS_Y, row);

  Serial.print(F("  Target position: X "));
  Serial.print(targetX);
  Serial.print(F(" / Y "));
  Serial.println(targetY);

  // STEP 1 - back to a known origin.
  if (!goToOrigin())
  {
    Serial.println(F("  ABORTED - cannot trust position without origin."));
    return false;
  }

  // STEP 2 - Y axis.
  Serial.print(F("  Moving Y to "));
  Serial.print(targetY);
  Serial.println(F(" ..."));
  bool okY = moveAxisTo(AXIS_Y, targetY);

  // STEP 3 - X axis.
  Serial.print(F("  Moving X to "));
  Serial.print(targetX);
  Serial.println(F(" ..."));
  bool okX = moveAxisTo(AXIS_X, targetX);

  if (okX && okY)
  {
    curCol = col;
    curRow = row;
    Serial.print(F("  ARRIVED at cell ["));
    Serial.print(col);
    Serial.print(F(","));
    Serial.print(row);
    Serial.print(F("]  pos X "));
    Serial.print(axisPos[AXIS_X]);
    Serial.print(F(" / Y "));
    Serial.println(axisPos[AXIS_Y]);
    return true;
  }

  curCol = positionToIndex(AXIS_X, axisPos[AXIS_X]);
  curRow = positionToIndex(AXIS_Y, axisPos[AXIS_Y]);
  Serial.println(F("  MOVE INCOMPLETE - a limit stopped it short."));
  return false;
}

// ============================================================
// Z HEIGHT MATH  -  steps <-> cm <-> block levels      <<< NEW
// ============================================================
//
// Nothing below is hard-coded. Every number falls out of
// SOFT_LIMIT_Z_TRAVEL and the SECTION 6E measurements.

// The whole conversion, in one place:
//     steps per cm = Z travel in steps / Z travel in cm
float zStepsPerCm()
{
  if (Z_TRAVEL_CM <= 0.0)
  {
    return 0.0;
  }
  return (float)SOFT_LIMIT_Z_TRAVEL / Z_TRAVEL_CM;
}

float zCmPerStep()
{
  float sc = zStepsPerCm();
  return (sc > 0.0) ? (1.0 / sc) : 0.0;
}

// How many steps one block is worth, margin included. Informational -
// levels are always computed absolutely, never by adding this up.
float blockHeightInSteps()
{
  return (BLOCK_HEIGHT_CM + Z_MARGIN_PER_LEVEL_CM) * zStepsPerCm();
}

// The tallest level we allow, from the SOFTER of the two caps:
// the build ceiling (MAX_BUILD_HEIGHT_CM) and the physical travel.
long maxBuildLevel()
{
  float ceilingCm = MAX_BUILD_HEIGHT_CM;

  if (ceilingCm > Z_TRAVEL_CM)
  {
    ceilingCm = Z_TRAVEL_CM; // never promise more than the rig has
  }
  if (ceilingCm < 0.0 || BLOCK_HEIGHT_CM <= 0.0)
  {
    return 0;
  }

  return (long)((ceilingCm + LEVEL_EPSILON) / BLOCK_HEIGHT_CM);
}

// Commanded height of a level, in cm, margins folded in.
// Level 0 is the physical switch, so it is exactly 0 by definition.
float levelToCm(long level)
{
  if (level <= 0)
  {
    return 0.0;
  }
  return (float)level * (BLOCK_HEIGHT_CM + Z_MARGIN_PER_LEVEL_CM) + Z_MARGIN_FIXED_CM;
}

// Same level as an absolute Z machine position, in steps.
// Clamped into the real travel so a bad margin can never command
// the axis past its own software limit.
long levelToZSteps(long level)
{
  if (level <= 0)
  {
    return 0;
  }

  long steps = lround(levelToCm(level) * zStepsPerCm()) + Z_MARGIN_FIXED_STEPS;

  if (steps < 0)
  {
    steps = 0;
  }
  if (steps > SOFT_LIMIT_Z_TRAVEL)
  {
    steps = SOFT_LIMIT_Z_TRAVEL;
  }

  // Z counts UP from its switch in the softEndOf(AXIS_Z) direction.
  return steps * (long)softEndOf(AXIS_Z);
}

// Top of travel - the carry height every build flies at.
long zTopPosition()
{
  return SOFT_LIMIT_Z_TRAVEL * (long)softEndOf(AXIS_Z);
}

// ============================================================
// Z MOVES USED BY THE BUILD                            <<< NEW
// ============================================================

// Raise Z as far as the software limit allows.
bool zGoTop()
{
  if (!axisHomed[AXIS_Z])
  {
    // Without a zero, "the software limit" is a guess. Find the
    // switch first - it is the only trustworthy reference we have.
    Serial.println(F("  Z not homed yet - finding the Z switch first."));
    if (!homeAxis(AXIS_Z))
    {
      return false;
    }
  }

  Serial.print(F("  Z up to software limit ("));
  Serial.print(zTopPosition());
  Serial.println(F(" steps) ..."));
  return moveAxisTo(AXIS_Z, zTopPosition());
}

// Drop Z onto the table - the physical switch IS ground, so this
// re-zeroes the axis and kills any accumulated Z error every cycle.
bool zGoGround()
{
  Serial.println(F("  Z down to GROUND (into the Z switch) ..."));
  return homeAxis(AXIS_Z);
}

// Drop Z to a computed block level.
bool zGoLevel(long level)
{
  if (level <= 0)
  {
    return zGoGround();
  }

  long target = levelToZSteps(level);

  Serial.print(F("  Z down to level "));
  Serial.print(level);
  Serial.print(F("  =  "));
  Serial.print(levelToCm(level), 3);
  Serial.print(F(" cm  =  "));
  Serial.print(target);
  Serial.println(F(" steps ..."));

  bool ok = moveAxisTo(AXIS_Z, target);

  if (!ok)
  {
    Serial.println(F("  !! Z did not reach the level - a limit stopped it."));
  }
  return ok;
}

// ============================================================
// BUILD COMMAND                                        <<< NEW
// ============================================================
//
//    B <col> <row> <level> [R | RR | NR]
//
// col / row are grid cells, exactly as in the G command.
// level is a BLOCK level: 0 = ground, 1 = 1.5 cm, 2 = 3.0 cm ...
// The rotation word is OPTIONAL and defaults to NR (no rotation).

void printBuildUsage()
{
  Serial.println();
  Serial.println(F("  ERROR - use:  B <col> <row> <level> [R|RR|NR]"));
  Serial.println(F("    col   1..GRID_COLS      (same as G)"));
  Serial.println(F("    row   1..GRID_ROWS      (same as G)"));
  Serial.print(F("    level 0.."));
  Serial.print(maxBuildLevel());
  Serial.print(F("   (0 = ground, 1 = "));
  Serial.print(BLOCK_HEIGHT_CM, 2);
  Serial.println(F(" cm, ...)"));
  Serial.println(F("    R = 90 CW, RR = 90 CCW, NR / omitted = no rotation"));
  Serial.println(F("    e.g.  B 3 5 2 R      or   B 3 5 0"));
}

// Reads the optional trailing rotation word. Returns false only if
// something was there and it was not R / RR / NR.
bool parseRotationWord(const char *s, int8_t *outRot)
{
  uint8_t i = 0;

  // Skip separators.
  while (s[i] == ' ' || s[i] == ',' || s[i] == ':' || s[i] == ';' || s[i] == '\t')
  {
    i++;
  }

  if (s[i] == '\0')
  {
    *outRot = ROT_NONE; // nothing given - the documented default
    return true;
  }

  char w[4] = {0, 0, 0, 0};
  uint8_t n = 0;
  while (s[i] != '\0' && n < 3)
  {
    char c = toUpperChar(s[i]);
    if (c < 'A' || c > 'Z')
    {
      break;
    }
    w[n++] = c;
    i++;
  }

  // Anything trailing after the word (other than separators) is junk.
  while (s[i] == ' ' || s[i] == ',' || s[i] == '\t')
  {
    i++;
  }
  if (s[i] != '\0')
  {
    return false;
  }

  if (n == 1 && w[0] == 'R')
  {
    *outRot = ROT_CW;
    return true;
  }
  if (n == 2 && w[0] == 'R' && w[1] == 'R')
  {
    *outRot = ROT_CCW;
    return true;
  }
  if (n == 2 && w[0] == 'N' && w[1] == 'R')
  {
    *outRot = ROT_NONE;
    return true;
  }

  return false;
}

void handleBuildCommand(const char *args)
{
  long v[3] = {0, 0, 0};
  uint8_t endIndex = 0;

  if (parseNumbers(args, v, 3, &endIndex) < 3)
  {
    statBadCommands++;
    printBuildUsage();
    return;
  }

  int8_t rot = ROT_NONE;
  if (!parseRotationWord(args + endIndex, &rot))
  {
    statBadCommands++;
    Serial.println();
    Serial.println(F("  ERROR - rotation must be R, RR or NR (or left out)."));
    printBuildUsage();
    return;
  }

  statBuildCommands++;
  buildBlock(v[0], v[1], v[2], rot);
}

void buildPause()
{
  if (BUILD_PHASE_PAUSE_MS > 0)
  {
    delay(BUILD_PHASE_PAUSE_MS);
  }
}

void buildStep(uint8_t n, const char *what)
{
  if (!BUILD_VERBOSE)
  {
    return;
  }
  Serial.println();
  Serial.print(F("[BUILD "));
  Serial.print(n);
  Serial.print(F("/"));
  Serial.print(BUILD_STEP_COUNT);
  Serial.print(F("] "));
  Serial.println(what);
}

// Refused before anything moved - the rig is untouched and safe.
bool buildReject(const char *why)
{
  statBuildsRejected++;
  statLastOk = false;
  statLastFailure = why;

  Serial.print(F("  BUILD REJECTED - "));
  Serial.println(why);
  Serial.println(F("  Nothing moved."));
  return false;
}

// Failed PART WAY THROUGH - the rig is somewhere unknown and may
// still be gripping a block. Loud on purpose.
void buildAbort(const char *why)
{
  statBuildsAborted++;
  statLastOk = false;
  statLastFailure = why;

  Serial.println();
  Serial.print(F("*** BUILD ABORTED - "));
  Serial.println(why);
  Serial.println(F("*** The claw may still be holding a block. Check the rig."));
}

// Records a placed block against its level.
void countPlacedBlock(long level)
{
  statBlocksPlaced++;

  if (level >= 0 && level < (long)LEVEL_HISTOGRAM_SIZE)
  {
    // Saturate rather than wrap - a wrapped count is a lie.
    if (statBlocksAtLevel[level] < 0xFFFF)
    {
      statBlocksAtLevel[level]++;
    }
  }
}

// ------------------------------------------------------------
// PHASES 12-14 - park the rig after the block is down.
// ------------------------------------------------------------
// Z has to come up FIRST: the claw is sitting inside the stack it
// just added to, so any X/Y move before the lift would drag through
// it. Then home X/Y, then undo any rotation this build applied.
//
// The block is already placed when this runs, so every failure here
// is a warning rather than an abort - the build itself succeeded.
bool buildPark()
{
  buildStep(12, "Raise Z clear of the block just placed");
  if (!zGoTop())
  {
    Serial.println(F("  !! could not raise Z - NOT parking X/Y."));
    Serial.println(F("  !! moving the gantry now could drag through the stack."));
    return false;
  }
  buildPause();

  buildStep(13, "Return X/Y to the origin");
  if (!goToOrigin())
  {
    Serial.println(F("  !! X/Y did not reach the origin."));
    return false;
  }
  buildPause();

  buildStep(14, "Return the claw to its original rotation");
  rotateClawTo(ROT_NONE);

  return true;
}

// One complete pick-and-place cycle. See the header comment for the
// phases; each one bails out the moment something goes wrong,
// because carrying on with an unknown position would crash the rig.
bool buildBlock(long col, long row, long level, int8_t wantRot)
{
  Serial.println();
  Serial.println(F("======================================"));
  Serial.print(F("BUILD  cell ["));
  Serial.print(col);
  Serial.print(F(","));
  Serial.print(row);
  Serial.print(F("]  level "));
  Serial.print(level);
  Serial.print(F("  rot "));
  Serial.println(rotationName(wantRot));
  Serial.println(F("======================================"));

  // Remember what was asked for, whatever the outcome turns out to be.
  statLastCol = col;
  statLastRow = row;
  statLastLevel = level;
  statLastRot = wantRot;
  statLastOk = false;
  statLastFailure = NULL;

  // ---- validation, all of it, before anything moves ----

  if (!gridReady())
  {
    return buildReject("grid needs both X/Y software limits");
  }
  if (!cellInRange(col, row))
  {
    return buildReject("cell out of range");
  }

  if (!softEnabledOn(AXIS_Z))
  {
    Serial.println(F("  ERROR - build needs the Z software limit enabled"));
    Serial.println(F("  and non-zero. Check SECTION 6B."));
    return buildReject("Z software limit disabled");
  }
  if (Z_TRAVEL_CM <= 0.0 || BLOCK_HEIGHT_CM <= 0.0)
  {
    Serial.println(F("  ERROR - Z_TRAVEL_CM and BLOCK_HEIGHT_CM must both"));
    Serial.println(F("  be greater than zero. Check SECTION 6E."));
    return buildReject("Z calibration is not usable");
  }

  long maxLevel = maxBuildLevel();
  if (level < 0 || level > maxLevel)
  {
    Serial.print(F("  ERROR - level out of range. Valid: 0.."));
    Serial.println(maxLevel);
    Serial.print(F("  (build ceiling "));
    Serial.print(MAX_BUILD_HEIGHT_CM, 2);
    Serial.print(F(" cm / block "));
    Serial.print(BLOCK_HEIGHT_CM, 2);
    Serial.println(F(" cm)"));
    return buildReject("level out of range");
  }

  Serial.print(F("  Target height: "));
  Serial.print(levelToCm(level), 3);
  Serial.print(F(" cm  =  "));
  Serial.print(levelToZSteps(level));
  Serial.print(F(" steps   ("));
  Serial.print(zStepsPerCm(), 3);
  Serial.println(F(" steps/cm)"));

  // Past validation - from here on the machine actually moves.
  statBuildsAttempted++;
  unsigned long buildStartMs = millis();

  // ---- 1. get clear of whatever is already built ----

  buildStep(1, "Raise Z to the software limit (clearance)");
  if (!zGoTop())
  {
    buildAbort("could not raise Z to the top of travel");
    return false;
  }
  buildPause();

  // ---- 2. back to the feeder at the origin ----

  buildStep(2, "Home X/Y to the origin 0,0 (the feeder)");
  if (!goToOrigin())
  {
    buildAbort("homing X/Y failed");
    return false;
  }
  buildPause();

  // ---- 3. undo the previous build's rotation, while still high ----

  // Normally a no-op, because phase 14 already left the claw neutral.
  // It stays as a safety net for a manual R/RR between builds.
  buildStep(3, "Return the claw to neutral before picking up");
  rotateClawTo(ROT_NONE);
  buildPause();

  // ---- 4. open the jaws BEFORE descending onto the block ----

  buildStep(4, "Open the claw");
  openServoAndWait();
  buildPause();

  // ---- 5. down to ground (this also re-zeroes Z) ----

  buildStep(5, "Lower Z to GROUND (Z limit switch)");
  if (!zGoGround())
  {
    buildAbort("Z never reached the ground switch");
    return false;
  }
  buildPause();

  // ---- 6. grab it ----

  buildStep(6, "Close the claw (grip the block)");
  closeServoAndWait();
  buildPause();

  // ---- 7. lift to carry height ----

  buildStep(7, "Raise Z to the software limit (carry height)");
  if (!zGoTop())
  {
    buildAbort("could not lift the block to carry height");
    return false;
  }
  buildPause();

  // ---- 8. fly to the target cell ----

  buildStep(8, "Move X/Y to the target cell");
  if (!gotoCell(col, row))
  {
    buildAbort("could not reach the target cell");
    return false;
  }
  buildPause();

  // ---- 9. turn the block, still above the stack ----

  buildStep(9, "Apply the requested rotation");
  rotateClawTo(wantRot);
  buildPause();

  // ---- 10. down onto the stack ----

  buildStep(10, "Lower Z to the target block level");
  if (!zGoLevel(level))
  {
    buildAbort("Z did not reach the target level");
    return false;
  }
  buildPause();

  // ---- 11. let go ----

  buildStep(11, "Open the claw (release the block)");
  openServoAndWait();

  // ---- the block is down: book it BEFORE parking ----
  //
  // The placement is what the command was for, and it has succeeded
  // by this point. Parking is tidy-up: if it goes wrong the block is
  // still correctly placed, so it must not turn a good build into a
  // failed one.

  unsigned long elapsed = millis() - buildStartMs;

  statBuildsCompleted++;
  statBuildTotalMs += elapsed;
  statBuildLastMs = elapsed;

  if (statBuildFastestMs == 0 || elapsed < statBuildFastestMs)
  {
    statBuildFastestMs = elapsed;
  }
  if (elapsed > statBuildSlowestMs)
  {
    statBuildSlowestMs = elapsed;
  }

  countPlacedBlock(level);
  statLastOk = true;
  statLastFailure = NULL;

  // ---- 12-14. park the rig back at its rest state ----

  bool parked = true;
  if (BUILD_PARK_AFTER_PLACE)
  {
    parked = buildPark();
  }

  Serial.println();
  Serial.println(F("======================================"));
  Serial.print(F("BUILD COMPLETE - block placed at ["));
  Serial.print(col);
  Serial.print(F(","));
  Serial.print(row);
  Serial.print(F("] level "));
  Serial.print(level);
  Serial.print(F(" ("));
  Serial.print(levelToCm(level), 2);
  Serial.println(F(" cm)"));
  Serial.print(F("Place time: "));
  printDuration(elapsed);
  Serial.println();

  Serial.print(F("Claw rotation: "));
  Serial.println(rotationName(clawRotation));

  if (!BUILD_PARK_AFTER_PLACE)
  {
    Serial.println(F("NOT PARKED - claw is still over the block it placed."));
    Serial.println(F("(BUILD_PARK_AFTER_PLACE is false)"));
  }
  else if (parked)
  {
    Serial.println(F("PARKED - Z at the top, X/Y at the origin."));
    Serial.println(F("Ready for the next B."));
  }
  else
  {
    Serial.println(F("!! BLOCK IS PLACED, BUT PARKING FAILED - see above."));
    Serial.println(F("!! Check the rig before the next command."));
  }

  Serial.println(F("======================================"));
  return true;
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
    // Approaching and still clear - arm the edge detector so the next
    // contact is counted as a fresh trip.
    limitWasActive[axis] = false;
    return false;
  }

  // Count the CONTACT, not the thousand steps spent resting on it.
  if (!limitWasActive[axis])
  {
    limitWasActive[axis] = true;
    statLimitTrips[axis]++;
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
    return false; // this direction is not the one the cap guards
  }

  if (remaining > 0)
  {
    softWasActive[axis] = false;
    return false;
  }

  // Same edge trick as the physical switch - one event per arrival.
  if (!softWasActive[axis])
  {
    softWasActive[axis] = true;
    statSoftBlocks[axis]++;
  }
  return true;
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
    Serial.print(F("  BLOCKED - "));
    Serial.print(axisName(axis));
    Serial.print(F(" SOFTWARE limit reached ("));
    Serial.print(softTravelOf(axis));
    Serial.println(F(" steps of travel used)."));
    if (SOFT_LIMIT_VERBOSE)
    {
      Serial.print(F("  Position "));
      Serial.print(axisName(axis));
      Serial.print(F(" = "));
      Serial.print(axisPos[axis]);
      Serial.println(F(". Move the opposite way to free travel."));
    }
  }
  else
  {
    Serial.print(F("  BLOCKED - "));
    Serial.print(axisName(axis));
    Serial.println(F(" limit switch is active in this direction."));
    Serial.println(F("  Move the opposite way to back off the switch."));
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
  Serial.println(F("--- PHYSICAL LIMIT SWITCHES ---"));

  Serial.print(F("X (pin "));
  Serial.print(LIMIT_PIN_X);
  Serial.print(F(", "));
  Serial.print(LIMIT_X_USE_NC ? "NC" : "NO");
  Serial.print(F(", guards X"));
  Serial.print(signName(LIMIT_X_AT_END));
  Serial.print(F("): "));
  if (!LIMIT_X_ENABLED)
    Serial.println(F("DISABLED IN CONFIG"));
  else if (isLimitHit(AXIS_X))
    Serial.println(F("*** LIMIT HIT ***"));
  else
    Serial.println(F("clear"));

  Serial.print(F("Y (pin "));
  Serial.print(LIMIT_PIN_Y);
  Serial.print(F(", "));
  Serial.print(LIMIT_Y_USE_NC ? "NC" : "NO");
  Serial.print(F(", guards Y"));
  Serial.print(signName(LIMIT_Y_AT_END));
  Serial.print(F("): "));
  if (!LIMIT_Y_ENABLED)
    Serial.println(F("DISABLED IN CONFIG"));
  else if (isLimitHit(AXIS_Y))
    Serial.println(F("*** LIMIT HIT ***"));
  else
    Serial.println(F("clear"));

  Serial.print(F("Z (pin "));
  Serial.print(LIMIT_PIN_Z);
  Serial.print(F(", "));
  Serial.print(LIMIT_Z_USE_NC ? "NC" : "NO");
  Serial.print(F(", guards Z"));
  Serial.print(signName(LIMIT_Z_AT_END));
  Serial.print(F("): "));
  if (!LIMIT_Z_ENABLED)
    Serial.println(F("DISABLED IN CONFIG"));
  else if (isLimitHit(AXIS_Z))
    Serial.println(F("*** LIMIT HIT ***"));
  else
    Serial.println(F("clear"));
}

void printSoftLimitLine(uint8_t axis)
{
  Serial.print(axisName(axis));
  Serial.print(F(" (guards "));
  Serial.print(axisName(axis));
  Serial.print(signName(softEndOf(axis)));
  Serial.print(F("): "));

  if (!softEnabledOn(axis))
  {
    Serial.println(F("INFINITE / disabled"));
    return;
  }

  long remaining = softStepsRemaining(axis, softEndOf(axis));

  Serial.print(F("cap "));
  Serial.print(softTravelOf(axis));
  Serial.print(F(" steps, "));
  Serial.print(remaining);
  Serial.print(F(" left"));
  if (remaining == 0)
    Serial.println(F("  *** AT SOFT LIMIT ***"));
  else
    Serial.println();
}

void printSoftLimitStatus()
{
  Serial.println();
  Serial.println(F("--- SOFTWARE LIMITS ---"));
  printSoftLimitLine(AXIS_X);
  printSoftLimitLine(AXIS_Y);
  printSoftLimitLine(AXIS_Z);
}

void printServoStatus()
{
  Serial.println();
  Serial.println(F("--- GRIPPER SERVO ---"));
  Serial.print(F("Pin "));
  Serial.print(SERVO_PIN);
  Serial.print(F(": "));
  Serial.print(servoIsOpen ? "OPEN" : "CLOSED");
  Serial.print(F("   (open "));
  Serial.print(SERVO_OPEN_ANGLE);
  Serial.print(F(" deg / close "));
  Serial.print(SERVO_CLOSE_ANGLE);
  Serial.println(F(" deg)"));

  Serial.print(F("Actuations: "));
  Serial.print(statServoOpens);
  Serial.print(F(" opens, "));
  Serial.print(statServoCloses);
  Serial.print(F(" closes, "));
  Serial.print(statServoOpens < statServoCloses ? statServoOpens : statServoCloses);
  Serial.println(F(" full grip cycles"));
}

void printAuxStepperStatus()
{
  Serial.println();
  Serial.println(F("--- AUX STEPPER (28BYJ-48) ---"));
  Serial.print(F("Pins IN1-IN4: "));
  Serial.print(AUX_STEPPER_IN1);
  Serial.print(F(", "));
  Serial.print(AUX_STEPPER_IN2);
  Serial.print(F(", "));
  Serial.print(AUX_STEPPER_IN3);
  Serial.print(F(", "));
  Serial.println(AUX_STEPPER_IN4);
  Serial.print(F("Net position: "));
  if (auxStepperPos > 0)
    Serial.print(F("+"));
  Serial.print(auxStepperPos);
  Serial.print(F(" steps (since power-on) = "));
  Serial.print((float)auxStepperPos / (float)AUX_STEPPER_STEPS_PER_REV, 3);
  Serial.println(F(" revolutions"));

  Serial.print(F("Quarter turns: "));
  Serial.print(statRotCW);
  Serial.print(F(" CW, "));
  Serial.print(statRotCCW);
  Serial.print(F(" CCW  (net "));
  Serial.print((long)statRotCW - (long)statRotCCW);
  Serial.println(F(")"));

  Serial.print(F("Claw rotation: "));
  Serial.print(rotationName(clawRotation));
  if (clawRotation != ROT_NONE)
  {
    Serial.print(F("  <- the next B un-rotates this at the feeder"));
  }
  Serial.println();
}

void printGridConfig()
{
  Serial.println();
  Serial.println(F("--- GRID ---"));
  Serial.print(F("Envelope : "));
  Serial.print(gridTravelOf(AXIS_X));
  Serial.print(F(" x "));
  Serial.print(gridTravelOf(AXIS_Y));
  Serial.println(F(" steps"));

  Serial.print(F("Division : "));
  Serial.print(GRID_COLS);
  Serial.print(F(" cols x "));
  Serial.print(GRID_ROWS);
  Serial.print(F(" rows  = "));
  Serial.print(GRID_COLS * GRID_ROWS);
  Serial.println(F(" cells"));

  Serial.print(F("Cell size: ~"));
  Serial.print((float)gridTravelOf(AXIS_X) / (float)GRID_COLS, 2);
  Serial.print(F(" x "));
  Serial.print((float)gridTravelOf(AXIS_Y) / (float)GRID_ROWS, 2);
  Serial.println(F(" steps"));

  Serial.println(F("col 1 = X switch side, row 1 = Y switch side"));
}

// Where the machine is in GRID terms - shared by the map and the
// full report, so the two can never disagree.
void printGridPosition()
{
  long liveCol = positionToIndex(AXIS_X, axisPos[AXIS_X]);
  long liveRow = positionToIndex(AXIS_Y, axisPos[AXIS_Y]);

  Serial.print(F("Machine pos : X "));
  Serial.print(axisPos[AXIS_X]);
  Serial.print(F("  /  Y "));
  Serial.println(axisPos[AXIS_Y]);

  Serial.print(F("Current cell: "));
  if (!axisHomed[AXIS_X] || !axisHomed[AXIS_Y])
  {
    Serial.println(F("UNKNOWN - not homed yet (send 0)"));
  }
  else if (liveCol == 0 || liveRow == 0)
  {
    Serial.println(F("outside the grid envelope"));
  }
  else
  {
    Serial.print(F("["));
    Serial.print(liveCol);
    Serial.print(F(","));
    Serial.print(liveRow);
    Serial.println(F("]"));
  }

  Serial.print(F("Last commanded cell: "));
  if (curCol > 0 && curRow > 0)
  {
    Serial.print(F("["));
    Serial.print(curCol);
    Serial.print(F(","));
    Serial.print(curRow);
    Serial.println(F("]"));
  }
  else
  {
    Serial.println(F("none / invalidated by a manual jog"));
  }
}

// ============================================================
// BUILD / Z CALIBRATION REPORT                         <<< NEW
// ============================================================

void printBuildConfig()
{
  Serial.println();
  Serial.println(F("--- Z / BUILD CALIBRATION ---"));

  Serial.print(F("Z travel     : "));
  Serial.print(SOFT_LIMIT_Z_TRAVEL);
  Serial.print(F(" steps  =  "));
  Serial.print(Z_TRAVEL_CM, 2);
  Serial.println(F(" cm  (switch -> soft limit)"));

  Serial.print(F("Scale        : "));
  Serial.print(zStepsPerCm(), 4);
  Serial.print(F(" steps/cm   ("));
  Serial.print(zCmPerStep(), 5);
  Serial.println(F(" cm/step)"));

  Serial.print(F("Block height : "));
  Serial.print(BLOCK_HEIGHT_CM, 2);
  Serial.print(F(" cm  =  "));
  Serial.print(blockHeightInSteps(), 2);
  Serial.println(F(" steps (margin included)"));

  Serial.print(F("Margins      : per-level "));
  Serial.print(Z_MARGIN_PER_LEVEL_CM, 3);
  Serial.print(F(" cm / fixed "));
  Serial.print(Z_MARGIN_FIXED_CM, 3);
  Serial.print(F(" cm / fixed "));
  Serial.print(Z_MARGIN_FIXED_STEPS);
  Serial.println(F(" steps"));

  Serial.print(F("Build ceiling: "));
  Serial.print(MAX_BUILD_HEIGHT_CM, 2);
  Serial.print(F(" cm  ->  max level "));
  Serial.print(maxBuildLevel());
  Serial.print(F("  ("));
  Serial.print(levelToCm(maxBuildLevel()), 2);
  Serial.println(F(" cm)"));

  Serial.print(F("Headroom     : "));
  Serial.print(Z_TRAVEL_CM - levelToCm(maxBuildLevel()), 2);
  Serial.println(F(" cm above the tallest block"));

  if (MAX_BUILD_HEIGHT_CM > Z_TRAVEL_CM)
  {
    Serial.println(F("!! WARNING - build ceiling is ABOVE the physical travel."));
    Serial.println(F("!! It has been clamped to the travel. Fix SECTION 6E."));
  }
}

void printLevelTable()
{
  long maxLevel = maxBuildLevel();

  Serial.println();
  Serial.println(F("--- BLOCK LEVEL TABLE ---"));
  Serial.println(F("level      cm     steps"));

  for (long L = 0; L <= maxLevel; L++)
  {
    long steps = levelToZSteps(L) * (long)softEndOf(AXIS_Z);

    if (L < 10)
      Serial.print(F(" "));
    Serial.print(L);
    Serial.print(F("    "));
    if (levelToCm(L) < 10.0)
      Serial.print(F(" "));
    Serial.print(levelToCm(L), 2);
    Serial.print(F("     "));
    Serial.println(steps);
  }

  Serial.println(F("level 0 = the physical Z switch, not a computed value"));
}

// ============================================================
// ASCII GRID MAP
// ============================================================

void printGrid()
{
  Serial.println();
  Serial.println(F("======================================"));
  Serial.println(F("GRID MAP"));
  Serial.println(F("======================================"));

  printGridConfig();
  printGridPosition();

  long liveCol = positionToIndex(AXIS_X, axisPos[AXIS_X]);
  long liveRow = positionToIndex(AXIS_Y, axisPos[AXIS_Y]);

  if (GRID_COLS > GRID_MAP_MAX_COLS || GRID_ROWS > GRID_MAP_MAX_ROWS)
  {
    Serial.println();
    Serial.print(F("Map not drawn - grid larger than "));
    Serial.print(GRID_MAP_MAX_COLS);
    Serial.print(F("x"));
    Serial.print(GRID_MAP_MAX_ROWS);
    Serial.println(F(" is unreadable here."));
    Serial.println(F("======================================"));
    return;
  }

  Serial.println();
  Serial.println(F("  # = machine   . = empty cell"));
  Serial.println(F("  (top row = far Y end, left col = X switch)"));
  Serial.println();

  for (long r = GRID_ROWS; r >= 1; r--)
  {
    // Right-aligned row label, 3 wide.
    if (r < 100)
      Serial.print(F(" "));
    if (r < 10)
      Serial.print(F(" "));
    Serial.print(r);
    Serial.print(F(" |"));

    for (long c = 1; c <= GRID_COLS; c++)
    {
      if (c == liveCol && r == liveRow && axisHomed[AXIS_X] && axisHomed[AXIS_Y])
      {
        Serial.print(F(" #"));
      }
      else
      {
        Serial.print(F(" ."));
      }
    }
    Serial.println();
  }

  // Bottom rule.
  Serial.print(F("    +"));
  for (long c = 1; c <= GRID_COLS; c++)
  {
    Serial.print(F("--"));
  }
  Serial.println();

  // Column numbers, last digit only (keeps the map aligned).
  Serial.print(F("     "));
  for (long c = 1; c <= GRID_COLS; c++)
  {
    Serial.print(c % 10);
    Serial.print(F(" "));
  }
  Serial.println();
  Serial.println(F("     ^ origin corner is bottom-left [1,1]"));
  Serial.println(F("======================================"));
}

// ============================================================
// STEP COUNTERS / POSITION
// ============================================================

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
  Serial.println(F("POSITION ZEROED - this point is now the origin"));
  Serial.println(F("NOTE: grid moves and builds still require a real home."));
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
  Serial.println(F("--- STEP COUNTERS (this stats window) ---"));

  unsigned long grandTotal = 0;

  // Each axis runs at its own rate, so the time estimate has to be
  // accumulated per move rather than from one global step period.
  float motionMs = 0.0;

  for (uint8_t i = 0; i < MOVE_COUNT; i++)
  {
    Serial.print(F("  "));
    Serial.print(MOVES[i].label);
    Serial.print(F("\t: "));
    Serial.print(stepCounts[i]);
    Serial.println(F(" steps"));
    grandTotal += stepCounts[i];
    motionMs += (float)stepCounts[i] * stepPeriodMs(MOVES[i].axis);
  }

  Serial.println(F("  ------------------------------------"));
  printNetLine("X", netSteps(AXIS_X));
  printNetLine("Y", netSteps(AXIS_Y));
  printNetLine("Z", netSteps(AXIS_Z));

  Serial.print(F("  TOTAL\t: "));
  Serial.print(grandTotal);
  Serial.print(F(" pulses  (~"));
  printDuration((unsigned long)motionMs);
  Serial.println(F(" of motion)"));
}

// ============================================================
// COMPREHENSIVE REPORT  (command 5)                    <<< NEW
// ============================================================

// One full step is TWO half-periods. Per axis, because Z runs at its
// own rate.
float stepPeriodMs(uint8_t axis)
{
  return (2.0 * (float)stepDelayOf(axis)) / 1000.0;
}

float stepsPerSecond(uint8_t axis)
{
  float p = stepPeriodMs(axis);
  return (p > 0.0) ? (1000.0 / p) : 0.0;
}

// SRAM left between the heap and the stack. The single most useful
// number when a Mega starts behaving strangely.
int freeRam()
{
  extern int __heap_start;
  extern int *__brkval;
  int here;
  return (int)&here - (__brkval == 0 ? (int)&__heap_start : (int)__brkval);
}

void printDuration(unsigned long ms)
{
  unsigned long totalSec = ms / 1000UL;
  unsigned long h = totalSec / 3600UL;
  unsigned long m = (totalSec % 3600UL) / 60UL;
  unsigned long s = totalSec % 60UL;

  if (h > 0)
  {
    Serial.print(h);
    Serial.print(F("h "));
    Serial.print(m);
    Serial.print(F("m "));
    Serial.print(s);
    Serial.print(F("s"));
  }
  else if (m > 0)
  {
    Serial.print(m);
    Serial.print(F("m "));
    Serial.print(s);
    Serial.print(F("s"));
  }
  else
  {
    Serial.print((float)ms / 1000.0, 2);
    Serial.print(F(" s"));
  }
}

void printPercent(long part, long whole)
{
  if (whole <= 0)
  {
    Serial.print(F("--"));
    return;
  }
  Serial.print((float)part * 100.0 / (float)whole, 1);
  Serial.print(F("%"));
}

void printSessionStats()
{
  unsigned long now = millis();

  Serial.println();
  Serial.println(F("--- SESSION ---"));

  Serial.print(F("Uptime       : "));
  printDuration(now);
  Serial.println();

  Serial.print(F("Stats window : "));
  printDuration(now - statsSinceMs);
  Serial.println(F("   (reset with 6)"));

  Serial.print(F("Free SRAM    : "));
  Serial.print(freeRam());
  Serial.println(F(" bytes"));
}

void printMotionTuning()
{
  Serial.println();
  Serial.println(F("--- MOTION TUNING ---"));

  Serial.print(F("X/Y pulse    : "));
  Serial.print(STEP_DELAY);
  Serial.print(F(" us half-period  ->  "));
  Serial.print(stepPeriodMs(AXIS_X), 3);
  Serial.print(F(" ms/step  ->  "));
  Serial.print(stepsPerSecond(AXIS_X), 1);
  Serial.println(F(" steps/s"));

  Serial.print(F("Z pulse      : "));
  Serial.print(STEP_DELAY_Z);
  Serial.print(F(" us half-period  ->  "));
  Serial.print(stepPeriodMs(AXIS_Z), 3);
  Serial.print(F(" ms/step  ->  "));
  Serial.print(stepsPerSecond(AXIS_Z), 1);
  Serial.print(F(" steps/s  ="));
  Serial.print(stepsPerSecond(AXIS_Z) * zCmPerStep(), 2);
  Serial.println(F(" cm/s"));

  Serial.print(F("X/Y jog size : "));
  Serial.print(stepsPerMove);
  Serial.println(F(" steps per 1-4 command"));

  Serial.print(F("Z jog size   : "));
  Serial.print(stepsPerMoveZ);
  Serial.print(F(" steps per D / U command  ="));
  Serial.print((float)stepsPerMoveZ * zCmPerStep(), 2);
  Serial.println(F(" cm"));

  Serial.print(F("DIR settle   : "));
  Serial.print(DIR_SETTLE_MS);
  Serial.println(F(" ms"));

  Serial.print(F("Limit check  : every "));
  Serial.print(LIMIT_CHECK_EVERY_N_STEPS);
  Serial.print(F(" step(s), "));
  Serial.print(LIMIT_CONFIRM_US);
  Serial.println(F(" us confirm"));

  Serial.print(F("Servo settle : "));
  Serial.print(SERVO_SETTLE_MS);
  Serial.println(F(" ms"));

  Serial.print(F("Home chunk   : "));
  Serial.print(HOME_CHUNK_STEPS);
  Serial.print(F(" steps, cap X/Y/Z "));
  Serial.print(homeMaxStepsOf(AXIS_X));
  Serial.print(F("/"));
  Serial.print(homeMaxStepsOf(AXIS_Y));
  Serial.print(F("/"));
  Serial.println(homeMaxStepsOf(AXIS_Z));

  Serial.print(F("Build pause  : "));
  Serial.print(BUILD_PHASE_PAUSE_MS);
  Serial.print(F(" ms/phase, park after place: "));
  Serial.println(BUILD_PARK_AFTER_PLACE ? "YES" : "no");
}

// Position, travel used, travel left - per axis, in one table.
void printPositionTable()
{
  Serial.println();
  Serial.println(F("--- POSITION ---"));
  Serial.println(F("axis   steps    homed    used/travel      left     real"));

  for (uint8_t a = 0; a < AXIS_COUNT; a++)
  {
    long travel = softTravelOf(a);
    long used = axisPos[a] * (long)softEndOf(a); // distance from the switch
    long left = travel - used;

    Serial.print(F("  "));
    Serial.print(axisName(a));
    Serial.print(F("   "));
    if (axisPos[a] > 0)
    {
      Serial.print(F("+"));
    }
    Serial.print(axisPos[a]);
    Serial.print(F("\t "));
    Serial.print(axisHomed[a] ? "yes " : "NO  ");
    Serial.print(F("\t "));

    if (softEnabledOn(a))
    {
      Serial.print(used);
      Serial.print(F("/"));
      Serial.print(travel);
      Serial.print(F(" ("));
      printPercent(used, travel);
      Serial.print(F(")\t "));
      Serial.print(left);
    }
    else
    {
      Serial.print(F("no cap\t\t --"));
    }

    // Z is the only axis with a real-world calibration.
    if (a == AXIS_Z && zStepsPerCm() > 0.0)
    {
      Serial.print(F("\t "));
      Serial.print(used * zCmPerStep(), 2);
      Serial.print(F(" cm"));
    }
    Serial.println();
  }

  if (!axisHomed[AXIS_X] || !axisHomed[AXIS_Y] || !axisHomed[AXIS_Z])
  {
    Serial.println(F("  !! an axis is NOT homed - its position is a guess"));
  }
}

// Total distance driven, regardless of direction. This is the wear
// figure - net position says nothing about how far the rig has run.
void printOdometer()
{
  Serial.println();
  Serial.println(F("--- ODOMETER (total travel, both directions) ---"));

  for (uint8_t a = 0; a < AXIS_COUNT; a++)
  {
    unsigned long total = 0;
    for (uint8_t i = 0; i < MOVE_COUNT; i++)
    {
      if (MOVES[i].axis == a)
      {
        total += stepCounts[i];
      }
    }

    Serial.print(F("  "));
    Serial.print(axisName(a));
    Serial.print(F("\t: "));
    Serial.print(total);
    Serial.print(F(" steps"));

    if (a == AXIS_Z && zStepsPerCm() > 0.0)
    {
      Serial.print(F("   ("));
      Serial.print((float)total * zCmPerStep(), 1);
      Serial.print(F(" cm travelled)"));
    }
    Serial.println();
  }
}

void printAxisEventStats()
{
  Serial.println();
  Serial.println(F("--- AXIS EVENTS ---"));
  Serial.println(F("axis  homings  failed  switch hits  soft blocks  short moves"));

  for (uint8_t a = 0; a < AXIS_COUNT; a++)
  {
    Serial.print(F("  "));
    Serial.print(axisName(a));
    Serial.print(F("\t "));
    Serial.print(statHomeRuns[a]);
    Serial.print(F("\t "));
    Serial.print(statHomeFails[a]);
    Serial.print(F("\t "));
    Serial.print(statLimitTrips[a]);
    Serial.print(F("\t\t "));
    Serial.print(statSoftBlocks[a]);
    Serial.print(F("\t\t "));
    Serial.println(statShortMoves[a]);
  }
  Serial.println(F("(switch hits and soft blocks count ARRIVALS, not steps)"));
}

void printBuildStats()
{
  Serial.println();
  Serial.println(F("--- BUILD STATISTICS ---"));

  Serial.print(F("Commands     : "));
  Serial.print(statBuildCommands);
  Serial.println(F(" accepted"));

  Serial.print(F("Attempted    : "));
  Serial.print(statBuildsAttempted);
  Serial.println(F("   (passed validation and moved)"));

  Serial.print(F("Completed    : "));
  Serial.print(statBuildsCompleted);
  Serial.print(F("   ("));
  printPercent((long)statBuildsCompleted, (long)statBuildsAttempted);
  Serial.println(F(" of attempts)"));

  Serial.print(F("Aborted      : "));
  Serial.print(statBuildsAborted);
  Serial.println(F("   (stopped mid-cycle)"));

  Serial.print(F("Rejected     : "));
  Serial.print(statBuildsRejected);
  Serial.println(F("   (bad request, never moved)"));

  Serial.print(F("Blocks placed: "));
  Serial.println(statBlocksPlaced);

  if (statBuildsCompleted > 0)
  {
    Serial.print(F("Cycle time   : avg "));
    printDuration(statBuildTotalMs / statBuildsCompleted);
    Serial.print(F(" / fastest "));
    printDuration(statBuildFastestMs);
    Serial.print(F(" / slowest "));
    printDuration(statBuildSlowestMs);
    Serial.println();

    Serial.print(F("Last cycle   : "));
    printDuration(statBuildLastMs);
    Serial.println();

    Serial.print(F("Total in     : "));
    printDuration(statBuildTotalMs);
    Serial.println(F(" of building"));
  }

  // ---- what happened to the most recent request ----

  Serial.print(F("Last request : "));
  if (statLastLevel < 0)
  {
    Serial.println(F("none this window"));
  }
  else
  {
    Serial.print(F("["));
    Serial.print(statLastCol);
    Serial.print(F(","));
    Serial.print(statLastRow);
    Serial.print(F("] level "));
    Serial.print(statLastLevel);
    Serial.print(F(" "));
    Serial.print(rotationName(statLastRot));
    Serial.print(F("  ->  "));
    if (statLastOk)
    {
      Serial.println(F("OK"));
    }
    else
    {
      Serial.print(F("FAILED: "));
      Serial.println(statLastFailure != NULL ? statLastFailure : "unknown");
    }
  }

  // ---- how tall the build actually got ----

  if (statBlocksPlaced > 0)
  {
    Serial.println();
    Serial.println(F("Blocks per level:"));
    Serial.println(F("  level    cm    count"));

    long highest = -1;

    for (uint8_t L = 0; L < LEVEL_HISTOGRAM_SIZE; L++)
    {
      if (statBlocksAtLevel[L] == 0)
      {
        continue;
      }
      highest = L;

      Serial.print(F("   "));
      if (L < 10)
      {
        Serial.print(F(" "));
      }
      Serial.print(L);
      Serial.print(F("    "));
      Serial.print(levelToCm(L), 2);
      Serial.print(F("     "));
      Serial.println(statBlocksAtLevel[L]);
    }

    if (highest >= 0)
    {
      Serial.print(F("  Tallest placement: level "));
      Serial.print(highest);
      Serial.print(F(" = "));
      Serial.print(levelToCm(highest), 2);
      Serial.print(F(" cm, leaving "));
      Serial.print(Z_TRAVEL_CM - levelToCm(highest), 2);
      Serial.println(F(" cm of headroom"));
    }
  }
}

void printCommandStats()
{
  Serial.println();
  Serial.println(F("--- COMMANDS (this stats window) ---"));

  Serial.print(F("  Jogs (1-4/D/U) : "));
  Serial.println(statJogs);
  Serial.print(F("  Homings (0)    : "));
  Serial.println(statHomeCommands);
  Serial.print(F("  Goto cell (G)  : "));
  Serial.println(statGotos);
  Serial.print(F("  Builds (B)     : "));
  Serial.println(statBuildCommands);
  Serial.print(F("  Servo O/C      : "));
  Serial.print(statServoOpens);
  Serial.print(F(" opens / "));
  Serial.print(statServoCloses);
  Serial.println(F(" closes"));
  Serial.print(F("  Rotations R/RR : "));
  Serial.print(statRotCW);
  Serial.print(F(" CW / "));
  Serial.print(statRotCCW);
  Serial.println(F(" CCW"));
  Serial.print(F("  Rejected input : "));
  Serial.println(statBadCommands);
}

// THE report. Command 5. Everything the firmware knows, in one place.
void printFullReport()
{
  Serial.println();
  Serial.println(F("======================================"));
  Serial.println(F("FULL MACHINE REPORT"));
  Serial.println(F("======================================"));

  printSessionStats();
  printMotionTuning();
  printPositionTable();
  printStepCounts();
  printOdometer();
  printAxisEventStats();
  printLimitStatus();
  printSoftLimitStatus();
  printGridConfig();
  printGridPosition();
  printServoStatus();
  printAuxStepperStatus();
  printBuildConfig();
  printBuildStats();
  printCommandStats();

  Serial.println();
  Serial.println(F("======================================"));
  Serial.println(F("END OF REPORT   (6 = reset statistics)"));
  Serial.println(F("======================================"));
}

// ============================================================
// STATISTICS RESET
// ============================================================

void resetStatistics()
{
  for (uint8_t i = 0; i < MOVE_COUNT; i++)
  {
    stepCounts[i] = 0;
  }

  for (uint8_t a = 0; a < AXIS_COUNT; a++)
  {
    statHomeRuns[a] = 0;
    statHomeFails[a] = 0;
    statLimitTrips[a] = 0;
    statSoftBlocks[a] = 0;
    statShortMoves[a] = 0;
  }

  statJogs = 0;
  statGotos = 0;
  statHomeCommands = 0;
  statBuildCommands = 0;
  statBadCommands = 0;

  statServoOpens = 0;
  statServoCloses = 0;
  statRotCW = 0;
  statRotCCW = 0;

  statBuildsAttempted = 0;
  statBuildsCompleted = 0;
  statBuildsRejected = 0;
  statBuildsAborted = 0;
  statBuildTotalMs = 0;
  statBuildLastMs = 0;
  statBuildFastestMs = 0;
  statBuildSlowestMs = 0;

  statLastCol = 0;
  statLastRow = 0;
  statLastLevel = -1;
  statLastRot = ROT_NONE;
  statLastOk = false;
  statLastFailure = NULL;

  for (uint8_t L = 0; L < LEVEL_HISTOGRAM_SIZE; L++)
  {
    statBlocksAtLevel[L] = 0;
  }
  statBlocksPlaced = 0;

  statsSinceMs = millis();

  Serial.println();
  Serial.println(F("ALL STATISTICS RESET TO ZERO"));
  Serial.println(F("(step counters, event counts, build history)"));
  Serial.println(F("Position, homing state and software limits are NOT"));
  Serial.println(F("affected - this only clears the bookkeeping. Use 8"));
  Serial.println(F("to move the origin."));
}

void printNetLine(const char *axisLabel, long net)
{
  Serial.print(F("  NET "));
  Serial.print(axisLabel);
  Serial.print(F("\t: "));
  if (net > 0)
    Serial.print(F("+"));
  Serial.print(net);
  Serial.print(F(" steps"));

  if (SHOW_DISTANCE)
  {
    Serial.print(F("  ("));
    Serial.print(net / STEPS_PER_UNIT, 3);
    Serial.print(F(" "));
    Serial.print(DISTANCE_UNIT);
    Serial.print(F(")"));
  }
  Serial.println();
}

// ============================================================
// HELP TEXT
// ============================================================

void printInstructions()
{
  Serial.println(F("======================================"));
  Serial.println(F("CNC Grid + BUILD Control - MEGA 2560"));
  Serial.println(F("======================================"));
  Serial.print(F("Jog size: X/Y "));
  Serial.print(stepsPerMove);
  Serial.print(F(" steps @ "));
  Serial.print(STEP_DELAY);
  Serial.print(F(" us  |  Z "));
  Serial.print(stepsPerMoveZ);
  Serial.print(F(" steps @ "));
  Serial.print(STEP_DELAY_Z);
  Serial.println(F(" us"));
  Serial.println(F("--------------------------------------"));
  Serial.println(F("1 = X-   (M1 CW  / M2 CW )  [soft limit]"));
  Serial.println(F("2 = X+   (M1 CCW / M2 CCW)  [limit: pin 30]"));
  Serial.println(F("3 = Y-   (M1 CW  / M2 CCW)  [limit: pin 31]"));
  Serial.println(F("4 = Y+   (M1 CCW / M2 CW )  [soft limit]"));
  Serial.println(F("5 = FULL REPORT (position, counters, stats, build)"));
  Serial.println(F("6 = Reset ALL statistics"));
  Serial.println(F("7 = Disable both motors"));
  Serial.println(F("8 = Zero position (manual, NOT a home)"));
  Serial.println(F("9 = Show ASCII grid map"));
  Serial.println(F("0 = HOME / go to origin (X/Y switches only)"));
  Serial.println(F("0+= FULL RESET: also zero Z and park it at the top"));
  Serial.println(F("--------------------------------------"));
  Serial.println(F("D = Z-   (M3 CW )           [limit: pin 28]"));
  Serial.println(F("U = Z+   (M3 CCW)           [soft limit]"));
  Serial.println(F("--------------------------------------"));
  Serial.println(F("O = Servo OPEN              [pin 6]"));
  Serial.println(F("C = Servo CLOSE             [pin 6]"));
  Serial.println(F("--------------------------------------"));
  Serial.println(F("R  = Aux stepper ~90 deg CW   [28BYJ-48, pins 36-39]"));
  Serial.println(F("RR = Aux stepper ~90 deg CCW  [28BYJ-48, pins 36-39]"));
  Serial.println(F("--------------------------------------"));
  Serial.println(F("G <col> <row>   goto cell, e.g.  G 3 5"));
  Serial.println(F("S <cols> <rows> resize grid, e.g. S 20 39"));
  Serial.println(F("--------------------------------------"));
  Serial.println(F("B <col> <row> <level> [R|RR|NR]   BUILD one block"));
  Serial.println(F("    level 0 = ground, 1 = one block up, 2 = two ..."));
  Serial.println(F("    rotation is optional, default NR (no rotation)"));
  Serial.println(F("    e.g.  B 3 5 2 R     B 4 7 0     B 2 2 3 RR"));
  Serial.println(F("Z               print the Z / build calibration table"));
  Serial.println(F("?               reprint this help"));
  Serial.println(F("(letters and multi-arg commands need a newline / Enter)"));
  Serial.println(F("======================================"));
}

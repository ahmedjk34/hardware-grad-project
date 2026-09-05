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
    0+ = FULL RESET: Z down to its bottom switch, Z up to its TOP
         switch, then home X/Y. Puts the rig in a known state.

    D = Z-   (Motor 3 CW )   <-- physical limit switch, pin 28 (GROUND)
    U = Z+   (Motor 3 CCW)   <-- physical limit switch, pin 29 (TOP)

    O = Servo OPEN   (pin 6)
    C = Servo CLOSE  (pin 6)

    R  = select the VERTICAL grid    (cols 0..6, rows 0..5, block 2.2 x 6.0)
    RR = select the HORIZONTAL grid  (cols 0..2, rows 0..9, block 6.0 x 2.2)
      Gaps are a uniform 1.6 cm on every axis of both grids. Horizontal is
      registered +1.9 cm on BOTH axes (pickup-cell registration). See SECTION 6C.
      These LATCH a grid layout. NEITHER MOVES ANYTHING. Each is refused
      when it is already true, and both need X/Y homed first. The claw's
      rotation is owned entirely by the build cycle.
      THE CLAW'S PHYSICAL ANGLE IS NOT SENSED. You are trusted to start
      with it neutral - 6.0 cm jaw axis along Y. If it is not, every
      placement this session is turned 90 degrees and nothing can tell.

    G <col> <row>   = go to grid cell. e.g.  G 3 5   or  G3,5
      EVERY coordinate is a real block footprint, 0 included, and BOTH axes
      always move. G 0 0 drives to the FEEDER cell centre.
      (This changed: 0 used to mean "leave that axis at the origin", so
      G 5 0 was an X-only move. It is now the cell [5,0].)
    S <cols> <rows> = change the HIGHEST INDEX live, for the ACTIVE grid
      only. The other mode keeps the size it was last given. This is the
      REQUESTED size; a live shiftX/shiftY may clip what is reachable.

    shiftX <cm> / shiftY <cm> = translate the WHOLE placement lattice of the
      ACTIVE grid by <cm>, measured from and including the [0,0] reference,
      in that axis. Decimal and sign allowed; + is away from the home switch.
      shiftX 0 / shiftY 0 clears it. Per mode, like the trims. The PICK-UP is
      NOT shifted - it is a plain home to [0,0], so a build still lifts the
      block off the un-shifted feeder and only the PLACEMENT rides the shift.
      [0,0] stays the feeder and is never built on. The reachable build range
      is recomputed: a shift that pushes the far block past the travel cap
      drops that column/row (shiftX/shiftY 0 restores it); a shift that leaves
      no cell on the machine is refused and reverted.

    B <col> <row> <level>   = BUILD one block   <<< NEW
      B 0 0 is a no-op: [0,0] is the FEEDER in both modes and is never
      built on. Every other cell, row 0 and column 0 included, is a real
      placement.
      There is NO rotation word. The active grid decides how the block is
      laid: vertical places it unrotated, horizontal turns it 90 CW.
    Z               = print the Z / build calibration table  <<< NEW
    ?               = reprint the help text

  Multi-character commands need a newline. Single digit commands
  work with or without one - including 0 and 0+, which are special
  cased in checkSerial() so the '+' has a chance to arrive. D, U, O, C, V, R and Z are letters, so like
  G/S/B/? they need a newline too. RR is two letters and ALSO needs
  a newline - there is no single-character fast path for it.

  ------------------------------------------------------------
  COORDINATE SYSTEM  (this is the important part)
  ------------------------------------------------------------
  SOFT_ZERO_ON_LIMIT_HIT is true, so each HOME switch zeros its own
  axis the moment it trips. The corner where BOTH X/Y switches are
  pressed is therefore machine position (0, 0) = the ORIGIN.

  Each axis travels AWAY from its own home switch. The two switches
  sit at OPPOSITE ends now, so the two axes no longer share a sign:

      X switch at the X+ end  ->  X runs   0  ...  -4550   (soft limit)
      Y switch at the Y- end  ->  Y runs   0  ...  +7600   (soft limit)
      Z switch at the Z- end  ->  Z runs   0  ...  +1350   (TOP SWITCH)

  The current software-safe envelope is 4550 x 7600 steps. The measured
  HOLDER displacement to those caps is 22.8 x 38.0 cm - 199.56 and 200.00
  steps/cm. The active rectangle is
  X in [-4550, 0], Y in [0, +7600]. Grid
  indices hide this sign mess:

      col 0  = nearest the X switch (X = 0 side, the X+ end)
      col N  = far end of X travel  (X = -4750 side)
      row 0  = nearest the Y switch (Y = 0 side)
      row M  = far end of Y travel  (Y = +8250 side)

  Coordinate 0 is a REAL BLOCK whose CENTRE sits on the home corner, so the
  last cell's centre lands exactly on the software cap and cell 0's block
  hangs half a block past the switches. [0,0] is the feeder. See SECTION 6C.

  Generalised in code as: each axis extends from 0 in the direction
  travelEndOf(axis), for axisTravelOf(axis) steps - whether that far
  end is held by a software cap (X/Y) or by a switch (Z). Change the
  step limits and the cm calibration set each axis's steps/cm scale.

  Z works the same way, except that BOTH of its ends are now real
  switches: Z = 0 is the bottom switch on pin 28 (the GROUND / table
  surface, claw all the way down) and the top of travel is the switch
  on pin 29 - roughly +Z_TRAVEL_STEPS, but the switch, not the number,
  is what actually stops the axis. SECTION 6E turns that step range
  into centimetres and then into BLOCK LEVELS.

  ------------------------------------------------------------
  Z+ IS A HARDWARE END STOP NOW  (it used to be a software limit)
  ------------------------------------------------------------
  The Z+ end used to be guarded by a counted software limit, which
  only worked while the step count was trustworthy. It is now a
  physical switch on PIN 29, wired and treated exactly like the X, Y
  and Z- switches, so:

    * Z has NO software limit at all - SECTION 6B disables it.
    * Z_TRAVEL_STEPS (SECTION 6E) survives as a CALIBRATION number:
      it converts steps to centimetres and sizes the homing cap. It
      no longer stops anything.
    * "Z to the top" is now a SEEK - drive up until the switch trips -
      instead of a move to a counted position. It therefore works even
      when Z has never been homed.
    * The rig MEASURES the real switch-to-switch distance whenever it
      runs up from a true zero, and prints it next to Z_TRAVEL_STEPS
      in the full report. If the two disagree, copy the measured
      number into SECTION 6E.

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
    1. Z up to the TOP SWITCH                    (clear of everything)
    2. X/Y home. That IS the feeder: the lattice is centre-anchored, so
       vertical [0,0]'s centre is the home corner. The feeder never
       rotates - it always presents a block standing, in both modes.
    3. Return the claw to neutral (including any manual A jog)
    4. Open the claw
    5. Z down to GROUND (into the Z switch - this also re-zeroes Z)
    6. Close the claw                            (block is now held)
    7. Z up to the TOP SWITCH                    (carry height)
    8. X/Y to the requested cell
    9. Apply the active grid's placement rotation
   10. Z down to the requested BLOCK LEVEL
   11. Open the claw                             (block is placed)

  ...then it PARKS itself, so the rig never sits over the stack with
  an open claw and the next B starts from a known state:

   12. Z up to the TOP SWITCH                    (clear of the block)
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

  So: any new Serial.print of a fixed string MUST B be F("..."), e.g.
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

// The feeder is calibrated for a tighter opening when both X/Y home switches
// are physically active. The home-switch check is made at the instant
// O/openServo() runs.
const int SERVO_HOME_OPEN_ANGLE = 0;
const int SERVO_OPEN_ANGLE = 0;
const int SERVO_CLOSE_ANGLE = 54;

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
// A fourth, independent motor - not part of the X/Y/Z rig. `A <degrees>`
// gives it a signed RELATIVE jog; positive is CW and negative is CCW. There
// is no home switch or mechanical angle reading, so this is never an absolute
// physical angle. R/RR are grid latches, not aux-stepper commands.
//
// ULN2003 connections:
//   IN1 / BLACK -> pin 38
//   IN2 / GREEN -> pin 36
//   IN3 / BLUE  -> pin 39
//   IN4 / RED   -> pin 37
// Power the ULN2003 from a 5V external supply with a shared GND

const int AUX_STEPPER_IN1 = 38;
const int AUX_STEPPER_IN2 = 36;
const int AUX_STEPPER_IN3 = 39;
const int AUX_STEPPER_IN4 = 37;

// Approximate number of steps for one output-shaft revolution.
const int AUX_STEPPER_STEPS_PER_REV = 2048;

// A quarter turn, used by the build's neutral/CW/CCW placement states.
const int AUX_STEPPER_QUARTER_TURN = AUX_STEPPER_STEPS_PER_REV / 4;

// One manual command is deliberately capped at one turn. The aux mechanism
// has no limit switch, so a larger move must be consciously split into
// separate commands rather than silently winding cables or hardware forever.
const int AUX_STEPPER_MAX_MANUAL_DEGREES = 360;

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

// Current angular position reduced to one revolution around the assumed
// power-on neutral. Unlike auxStepperPos, a full 360-degree manual jog lands
// back at zero here. Build rotation uses this so it need not undo a pointless
// whole turn before a pick.
long auxAngleSteps = 0;

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
// two of these, so 2000 us => 4.000 ms per step => ~250 steps/sec.
// RAISE the Z value to slow Z down (more torque, less chance of
// losing steps under load); LOWER it to speed the lift up.
unsigned int STEP_DELAY = 575; // X and Y, 2000 us per half-period

unsigned int STEP_DELAY_Z = 950; // Z only

// How many steps a single MANUAL jog moves.
//   stepsPerMove  -> the 1-4 commands (X/Y)
//   stepsPerMoveZ -> the D/U commands (Z)
// Z is worth setting finer: 150 steps is only ~2.9 cm of X/Y travel
// but is nearly a fifth of the whole Z range.
int stepsPerMove = 150; // X and Y

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
// special-cased: it is read, debounced, counted and obeyed by the
// same code as every other end stop.
//
// ------------------------------------------------------------
//   isHome  -  which switch is an axis' ZERO?
// ------------------------------------------------------------
//   An axis needs exactly one switch that means "you are at position
//   0". That is the one homing drives into, and the one that re-zeros
//   the counter under SOFT_ZERO_ON_LIMIT_HIT.
//
//   Z- is Z's home switch because it is the GROUND reference the
//   block levels are measured from. Z+ is a FAR-END switch: it stops
//   the axis and reports where the top is, but it does not redefine
//   zero. See applyLimitReference().

const int LIMIT_PIN_X = 30;     // X AXIS limit switch
const int LIMIT_PIN_Y = 31;     // Y AXIS limit switch
const int LIMIT_PIN_Z_BOT = 28; // Z AXIS bottom (GROUND) limit switch
const int LIMIT_PIN_Z_TOP = 29; // Z AXIS top limit switch   <<< NEW

struct LimitSwitch
{
  uint8_t axis;
  int8_t end; // DIR_NEG / DIR_POS - which end of the axis it guards
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

// ------------------------------------------------------------
//   WHAT THE Z+ SWITCH DOES TO THE POSITION COUNTER
// ------------------------------------------------------------
//   When Z runs up into the top switch it can either KEEP the step
//   count it just made, or ADOPT Z_TRAVEL_STEPS as its position.
//
//   Keeping the count (false, the default) is more accurate whenever
//   Z already has a true zero from the bottom switch: the count came
//   from the real hardware this run, while Z_TRAVEL_STEPS is a
//   hand-entered constant that may be slightly stale. A build always
//   re-zeros at the bottom before it places anything, so the count is
//   never left to drift for long.
//
//   Set true only if you would rather trust the constant - e.g. if
//   the lift skips steps often enough that the count is the less
//   reliable of the two.
//
//   NOTE: when Z has NO zero at all (never homed), the top switch
//   always adopts Z_TRAVEL_STEPS regardless of this setting - a
//   rough reference beats no reference.
const bool Z_TOP_REFERENCES_POSITION = false;

const unsigned int LIMIT_CONFIRM_US = 200;
const uint8_t LIMIT_CHECK_EVERY_N_STEPS = 1;

// ============================================================
// SECTION 6B - SOFTWARE LIMIT CONFIGURATION
// ============================================================
//
// These numbers define the software-safe size of the grid envelope.
//
// ------------------------------------------------------------
//   Z IS NOT HERE ANY MORE
// ------------------------------------------------------------
//   Z used to be capped by a counted software limit at the Z+ end.
//   That end is now the physical switch on pin 29 (SECTION 6), so the
//   Z software limit is DISABLED and there is no Z travel cap to set.
//
//   The step count that used to live here as SOFT_LIMIT_Z_TRAVEL has
//   moved to SECTION 6E as Z_TRAVEL_STEPS, where it is a CALIBRATION
//   number - it converts steps into centimetres and sizes the Z
//   homing cap. It does not stop the axis; the switch does.
//
//   A soft limit only ever guards the end an axis travels TOWARD,
//   which is always the end away from its home switch. So for every
//   axis, SOFT_LIMIT_*_AT_END == travelEndOf(axis) by construction.

const long SOFT_LIMIT_INFINITE = 0; // sentinel: no cap at all

long SOFT_LIMIT_X_TRAVEL = 4550;                      // X- travel cap, in steps
long SOFT_LIMIT_Y_TRAVEL = 7600;                      // Y+ travel cap, in steps
const long SOFT_LIMIT_Z_TRAVEL = SOFT_LIMIT_INFINITE; // Z: switch, not a cap

// Measured HOLDER displacement from each home switch to the active software
// cap. These are displacements between two holder reference positions, not
// dimensions of the arm or block. The arm-holder offset is intentionally zero
// for now, so it does not participate in either scale.
//
//   X scale = 4750 / 24.3 = 195.4733 steps/cm
//   Y scale = 8250 / 40.0 = 206.2500 steps/cm
float X_TRAVEL_CM = 22.8;
float Y_TRAVEL_CM = 38.0;

const int8_t SOFT_LIMIT_X_AT_END = DIR_NEG; // guards the X- end
const int8_t SOFT_LIMIT_Y_AT_END = DIR_POS; // guards the Y+ end
const int8_t SOFT_LIMIT_Z_AT_END = DIR_POS; // (unused - Z has no cap)

const bool SOFT_LIMIT_X_ENABLED = true;
const bool SOFT_LIMIT_Y_ENABLED = true;
const bool SOFT_LIMIT_Z_ENABLED = false; // pin 29 replaced it

// Re-zero an axis automatically the moment its HOME switch trips.
// REQUIRED for the grid AND for the build levels to mean anything -
// leave this true. Far-end switches (Z+) never re-zero; see
// applyLimitReference().
const bool SOFT_ZERO_ON_LIMIT_HIT = true;

const bool SOFT_LIMIT_VERBOSE = true;

// ============================================================
// SECTION 6C - GRID CONFIGURATION
// ============================================================
//
// TWO GRIDS, BOTH REAL.  A block measures 2.2 x 6.0 cm in plan, and it can be
// laid either way round.  Which way round it is laid decides how many cells
// fit, where they sit, and how far the grid has to be trimmed - so it is not
// one grid with a flag, it is two grids, each with its own complete geometry:
//
//   VERTICAL   (mode 0)  block 2.2 X x 6.0 Y      6 cols x  5 rows
//   HORIZONTAL (mode 1)  block 6.0 X x 2.2 Y      2 cols x 10 rows
//
// ------------------------------------------------------------
//   COORDINATE 0 IS A REAL BLOCK, AND ITS CENTRE IS HOME
// ------------------------------------------------------------
// It used to be the home POINT, with only a gap before cell 1, and the whole
// allocation was then CENTRED in the holder travel. Both of those are gone.
// The lattice is a plain run of centres anchored on the home corner:
//
//       centre(i) = trim + i * pitch          pitch = block + gap
//
// so the LAST centre lands exactly on the software cap, and cell 0's block
// hangs half a block past the home switches:
//
//   vertical    X: 7 cells (0..6)  centres 0 .. 22.8   pitch 3.8
//               Y: 6 cells (0..5)  centres 0 .. 38.0   pitch 7.6
//   horizontal  X: 3 cells (0..2)  centres 1.9 .. 17.1  pitch 7.6
//               Y: 10 cells (0..9) centres 1.9 .. 36.1  pitch 3.8
//
// GRID_COLS / GRID_ROWS hold the HIGHEST INDEX, not a count, which is why they
// read 6/5 and 2/9 - there are 7/6 and 3/10 addressable cells.
//
// Vertical fills its travel exactly on both axes: 6 * 3.8 = 22.8 and
// 5 * 7.6 = 38.0. That is not a coincidence to be tuned away - it is what
// "the build area IS the travel area" means, and it is why vertical X has
// seven columns rather than six.
//
// ------------------------------------------------------------
//   THE GAPS ARE UNIFORM - 1.6 cm, EVERY AXIS, BOTH MODES
// ------------------------------------------------------------
// A vertical block reads 2.2 + 1.6 + 2.2 along its 6.0 cm length, and
// consecutive blocks are also 1.6 cm apart, so the 2.2 cm sub-cells repeat at
// one unbroken 3.8 cm pitch. Measured off the printed sheet: tiles 6.00 cm,
// gaps 1.56 cm, identical on both axes.
//
// An earlier revision had a 0.8 cm block gap, which made the horizontal Y
// lattice alternate 0.8 / 1.6. That alternation was an artefact of the wrong
// gap, not a real feature of the paper. Do not reintroduce it without
// re-measuring the sheet.
//
// ------------------------------------------------------------
//   [0,0] IS THE FEEDER, IN BOTH MODES, AND IS NEVER BUILT ON
// ------------------------------------------------------------
// The feeder never rotates: a block is always presented standing, on the
// VERTICAL [0,0] footprint, whichever mode is latched. Because the lattice is
// centre-anchored, that cell's centre IS the home corner - so a pick-up is a
// plain home with no move afterwards, and the claw, which closes on the middle
// of the block, closes on its centre.
//
// That kills exactly one cell per mode and no more. Every other row-0 /
// column-0 cell is a real placement, so B 0 0 stays the inert no-op it always
// was, while B 0 3 and B 4 0 are ordinary builds rather than the old "move one
// axis only" sentinel.
//
// ------------------------------------------------------------
//   HOW THE TWO GRIDS RELATE
// ------------------------------------------------------------
//   X  a horizontal column covers two vertical columns plus the gap between
//      them: block 6.0 = 2.2 + 1.6 + 2.2, pitch 7.6 = 2 * 3.8.
//   Y  a vertical row is 6.0 cm; a horizontal block laid on it is 2.2 cm.
//   Both axes carry the SAME +1.9 cm registration (GRID_TRIM_{X,Y}_CM): the
//   block is picked up standing at the vertical [0,0] feeder, centred on home,
//   then rotated 90 degrees about the grip. The rotated 6.0 cm face overhangs
//   the 2.2 cm vertical footprint by 6.0/2 - 2.2/2 = 1.9 cm per side, so a
//   +1.9 cm trim on each axis seats horizontal [0,0] flush against the
//   vertical [0,0] block edge (near edge in X, far edge in Y).
//
// Nothing here swaps an X extent for a Y one; see D12 in
// docs/dual-orientation-grid.md.
//
// THE PRINTED SHEET is registered the same way: lay it so the CENTRE of its
// [0,0] block sits on the holder home point, and printed [c,r] is firmware
// [c,r]. Half of that block hangs back past the switches - that is expected.
//
// PHYSICAL RR REGISTRATION (both axes, positive away from the home switch):
//
//    home
//      0        1.9        3.8                 7.6        (cm, either axis)
//      |         |          |                   |
//   [--- vertical [0,0], 6.0 cm centred on 0 ---]        (along its long axis)
//   |<--2.2-->|<---1.6--->|<---2.2--->| ...
//      ^         ^
//      |         h [0,0] centre = 1.9   (the +1.9 GRID_TRIM_{X,Y}_CM)
//      v vertical [0,0] centre = 0 = the feeder / pick-up point
//
// So RR only latches the mode; the next B picks the block up standing at home,
// moves +1.9 cm along BOTH X and Y, rotates 90 degrees CW, then places.
// B 0 0 remains a no-op in both modes.
//
// Targets are computed as absolute physical cell centres and rounded only
// once, so sub-step rounding error never accumulates between cells.
//
// ------------------------------------------------------------
//   WHICH MODE IS THE BOARD IN?
// ------------------------------------------------------------
//   VERTICAL, at every power-on and after every reset.  There is no EEPROM
//   and opening the USB port resets the board, so vertical is simply what the
//   machine is unless something has said otherwise since.  RR latches to
//   horizontal, R latches back; see the mode latch further down.
//
//   NOTHING SENSES THE CLAW'S PHYSICAL ANGLE.  The operator is trusted to
//   start with the claw physically neutral (its 6.0 cm jaw axis along Y).
//   If it is not, every placement in this session is turned 90 degrees and no
//   amount of software can tell.
//
// ------------------------------------------------------------
//   HOW MANY CELLS FIT?
// ------------------------------------------------------------
//   Counts are limited by block-plus-gap pitch, by reachable HOLDER centres,
//   and by each mode's block-edge overhang budget (below).  Command S can
//   choose a smaller centred grid for the ACTIVE mode but cannot squeeze
//   cells or change their footprint.

const uint8_t GRID_MODE_VERTICAL = 0;   // block standing: 6.0 cm along Y
const uint8_t GRID_MODE_HORIZONTAL = 1; // block lying:    6.0 cm along X
const uint8_t GRID_MODE_COUNT = 2;

// The live mode. Compiled default is vertical and every reset returns here.
uint8_t gridMode = GRID_MODE_VERTICAL;

//                                          { vertical, horizontal }
float GRID_BLOCK_X_CM[GRID_MODE_COUNT] = {2.2, 6.0};
float GRID_BLOCK_Y_CM[GRID_MODE_COUNT] = {6.0, 2.2};
float GRID_GAP_X_CM[GRID_MODE_COUNT] = {1.6, 1.6};
float GRID_GAP_Y_CM[GRID_MODE_COUNT] = {1.6, 1.6};

// ------------------------------------------------------------
//   THE FOUR OFFSET FAMILIES, AND WHAT EACH ONE IS FOR
// ------------------------------------------------------------
//   These used to overlap - the horizontal registration was split between a
//   TRIM and a TOOL OFFSET, so tuning either one moved the grid twice. Each
//   name now has exactly one job:
//
//     GRID_BLOCK_* / GRID_GAP_*   the physical lattice. Stated per mode.
//     GRID_TRIM_*                 moves the WHOLE grid against the home
//                                 switches. Vertical is 0.0 on both axes;
//                                 horizontal carries its pickup-cell
//                                 registration here - see below.
//     GRID_ERROR_OFFSET_*         the calibration knob. A CONSTANT per-mode
//                                 nudge; it cannot fix an error that grows
//                                 with distance (that is a steps/cm or pitch
//                                 problem). Start at 0.
//     TOOL_OFFSET_*               purely mechanical: how far the claw's grip
//                                 centre sits from the holder centre in each
//                                 rotation. Nothing to do with the grid.
//
//   THE HORIZONTAL REGISTRATION LIVES IN GRID_TRIM_{X,Y}_CM, +1.9 cm on BOTH
//   axes. The rotated 6.0 cm face overhangs the 2.2 cm vertical footprint by
//   6.0/2 - 2.2/2 = 1.9 cm per side, and trimming +1.9 on each axis seats
//   horizontal [0,0] flush against the vertical [0,0] block edge (near edge in
//   X, far edge in Y). It is applied exactly once, through cellCentreCmOf();
//   nothing adds it structurally.
//
//   TWO CAVEATS, because this constant has been derived two different ways.
//   (a) This block used to say "half the vertical pitch (3.8 / 2)". That
//       agrees numerically only because 3.8 happens to equal 6.0 - 2.2; it is
//       an accident of these dimensions, not a second proof. The overhang
//       derivation above is the real one.
//   (b) The overhang is an EXTENT, and +1.9 is a TRANSLATION. A 90-degree turn
//       about the grip moves the block's centre by zero however far its face
//       overhangs, so the rotation does not by itself justify any trim. What
//       justifies +1.9 is the LAYOUT CHOICE on the line above: horizontal
//       [0,0] is defined edge-flush with vertical [0,0] rather than
//       centre-coincident. The rotation's real, non-zero contribution is the
//       grip-to-rotation-axis swing, and that lives in TOOL_OFFSET_CW_*.

// Signed whole-allocation shift, per mode. Not copied between modes. Vertical
// is anchored on the home corner (0.0 / 0.0); horizontal carries the +1.9 cm
// pickup-cell registration on both axes (see the block above).
float GRID_TRIM_X_CM[GRID_MODE_COUNT] = {0.0, 1.9};
float GRID_TRIM_Y_CM[GRID_MODE_COUNT] = {0.0, 1.9};

// AI AGENT NOTE: For any user-marked "error" offsetting, use these variables.
// They apply exactly like GRID_TRIM_* and shift every grid centre from home.
// Keep these paired with config/rig.json and start new error calibration at 0.
//
// VERTICAL stays 0.0 / 0.0 - the grid was re-anchored on the printed sheet and
// the old 0.15 / 0.05 were measured against the previous CENTRED allocation.
//
// HORIZONTAL IS NOW 0.0 / 0.0 TOO, AND USED NOT TO BE.  It carried +0.5 cm X
// and +0.3 cm Y to absorb the placement error of the 90-degree pickup-rotate.
// That was the wrong knob, and the wrong knob hid a sign error:
//
//   The claw does close on the block's middle.  But that middle does not sit
//   on the AUX STEPPER'S ROTATION AXIS - it is offset by roughly
//   (-0.3, +0.6) cm - so a 90-degree CW turn swings the block centre AROUND
//   that axis instead of spinning it in place.  The swing is a constant
//   X +0.9 (AWAY from home) and Y -0.3 (toward home).  Y's shipped +0.3
//   happened to cancel its half.  X's shipped +0.5 pushed the SAME WAY as the
//   swing, so the two added and placed blocks landed 1.4 cm too far from the
//   X home switch.  The comment that used to sit here said blocks were
//   "landing toward home on each axis": true of Y, backwards for X.
//
// The swing depends on WHICH WAY the claw turns, so the correction belongs in
// TOOL_OFFSET_CW_* - which has a slot per rotation - and not here, which is
// one rotation-blind number per mode and so could not follow when the build
// rotation settled on CW.  See the TOOL_OFFSET_* block below.
//
// Moving it there also returns the LATTICE to trim-only (horizontal X centres
// 1.9 / 9.5 / 17.1), which is where blocks physically land and therefore what
// MachineGrid, the camera overlay and the Studio should draw.  An error offset
// moves cell centres; a tool offset moves only the holder.
float GRID_ERROR_OFFSET_X_CM[GRID_MODE_COUNT] = {0.0, 0.0};
float GRID_ERROR_OFFSET_Y_CM[GRID_MODE_COUNT] = {0.0, 0.0};

// The live GRID SHIFT, per mode. Set by the shiftX / shiftY serial commands,
// cleared to 0 by shiftX 0 / shiftY 0 and by every board reset. It is folded
// into gridTrimCmOf() and so rides through every lattice consumer EXACTLY like
// a trim - cellCentreCmOf(), gridGeometryFits(), gridCountMaxOf(),
// cellTargetPosition(), positionToIndex() - which is what makes the whole grid,
// [0,0] reference included, translate by <cm>.
//
// It is deliberately NOT the same knob as GRID_ERROR_OFFSET_*: that one is a
// calibration nudge that starts at 0 and stays paired with config/rig.json's
// error_offset_*; this one is an operator-driven registration shift the Pi
// pushes from config/rig.json's shift_x_cm / shift_y_cm after the mode latch
// and before S. Keep them separate so a shift never masquerades as calibration.
//
// THE PICK-UP DOES NOT SEE THIS. A build picks up with a plain home to raw
// [0,0] (goToFeeder -> goToOrigin), which touches no lattice math, so the shift
// only ever moves the PLACEMENT. See SECTION 6C header and applyGridShift().
float GRID_SHIFT_X_CM[GRID_MODE_COUNT] = {0.0, 0.0};
float GRID_SHIFT_Y_CM[GRID_MODE_COUNT] = {0.0, 0.0};

// How far past the travel limit this mode lets a placed block's own EDGE sit.
// This is NOT a trim: it moves nothing. It is the budget gridGeometryFits()
// measures the block edges against, and it exists because a centre-only check
// happily accepts a grid whose far block hangs off the machine.
//
// Vertical gets half a block on each axis (block_x/2 = 1.1, block_y/2 = 3.0),
// the overhang a full-travel grid would produce and a safe ceiling for the
// centred grid it ships as.  Horizontal gets zero, because any overhang there
// means the trims are wrong.
// Keep paired with config/rig.json -> grid.modes.*.max_edge_overhang_*_cm.
float GRID_MAX_EDGE_OVERHANG_X_CM[GRID_MODE_COUNT] = {1.1, 3.0};
float GRID_MAX_EDGE_OVERHANG_Y_CM[GRID_MODE_COUNT] = {3.0, 1.1};

// THE HIGHEST VALID INDEX, not a count: vertical addresses columns 0..6 and
// rows 0..5, horizontal columns 0..2 and rows 0..10. gridSlotsOf() adds the
// one. Per mode, so that S applies to the grid the operator is looking at and
// the other mode keeps whatever size it was given.
//
// This is the REQUESTED highest index. A non-zero GRID_SHIFT_* can push the
// far block past the travel cap; gridColsNow() / gridRowsNow() then report the
// clipped, actually-reachable highest index while these keep the request, so
// clearing the shift (shiftX/shiftY 0) restores the full grid with no re-S.
long GRID_COLS[GRID_MODE_COUNT] = {6, 2};
long GRID_ROWS[GRID_MODE_COUNT] = {5, 9};

// Read these rather than indexing the tables. Everything downstream of here
// is written against the ACTIVE mode and never mentions the other one.
//
// The returned value is min(requested, highest index that still fits under the
// live GRID_SHIFT_*). With no shift it is just GRID_COLS/GRID_ROWS[gridMode].
// It can be -1 if a shift leaves not even cell 0 on the machine, which makes
// gridReady() fail loudly rather than silently accepting a broken grid;
// applyGridShift() refuses such a shift up front so this is only transient.
long gridColsNow()
{
  long requested = GRID_COLS[gridMode];
  long fits = gridCountMaxOf(AXIS_X);
  return (fits < requested) ? fits : requested;
}

long gridRowsNow()
{
  long requested = GRID_ROWS[gridMode];
  long fits = gridCountMaxOf(AXIS_Y);
  return (fits < requested) ? fits : requested;
}

const char *gridModeName(uint8_t mode)
{
  return (mode == GRID_MODE_HORIZONTAL) ? "horizontal" : "vertical";
}

// The X/Y counters describe the GANTRY HOLDER, not necessarily the point where
// the claw places a block.  These vectors describe HOLDER -> block centre in
// physical centimetres.  Positive means farther from that axis' home switch.
//
// A cell names the desired block centre.  The firmware subtracts the selected
// vector before moving the holder, so the claw lands on the cell centre:
//
//     holder target = desired block centre - tool offset
//
// Keep these paired with config/rig.json -> tool_offsets.  CW/CCW apply after
// the requested 90-degree claw rotation, which can move an asymmetric tool
// centre.
//
// NEUTRAL IS GENUINELY ZERO: the claw closes on the middle of the block and
// places it without turning, so holder and block centre coincide.
//
// CW CARRIES THE PICKUP-ROTATE SWING, and it is the only rotation a build can
// ask for (buildRotationForMode: horizontal -> ROT_CW).  The grip point sits
// about (-0.3, +0.6) cm off the aux stepper's rotation axis, so the 90-degree
// turn carries the block centre round that axis by X +0.9 / Y -0.3 cm.
// Subtracting this vector sends the holder that far back, and the swing then
// delivers the block onto the cell centre.  Derived from a rig measurement of
// a horizontal placement landing 1.4 cm too far from the X home switch with
// Y dead on; the (0.9, -0.3) pair is the unique fit to those two readings.
//
// NOT to be confused with GRID_ERROR_OFFSET_* (a rotation-blind nudge to the
// cell centres themselves) or with the +1.9 cm GRID_TRIM_* registration (grid
// layout).  This one is claw geometry and nothing else - see D15 in
// docs/dual-orientation-grid.md.
//
// CCW stays zero: no grid or build route requests it, so it has never been
// measured.  The recorded (3.75, 1.40) CCW trial predates the centre-anchored
// lattice and must NOT be copied here.
float TOOL_OFFSET_NEUTRAL_X_CM = 0.0;
float TOOL_OFFSET_NEUTRAL_Y_CM = 0.0;
float TOOL_OFFSET_CW_X_CM = 0.9;
float TOOL_OFFSET_CW_Y_CM = -0.3;
float TOOL_OFFSET_CCW_X_CM = 0.0;
float TOOL_OFFSET_CCW_Y_CM = 0.0;

// The ASCII map is only drawn when the grid is small enough to be
// readable. Bigger grids print a numeric summary instead.
const long GRID_MAP_MAX_COLS = 48;
const long GRID_MAP_MAX_ROWS = 48;

// "Not on a cell at all" - in a gap, or off the grid. It is -1 and NOT 0,
// because 0 is a real cell now (the feeder). Every index that can come back
// from positionToIndex() has to be tested against this, never against 0.
const long GRID_INDEX_NONE = -1;

// Last commanded cell. GRID_INDEX_NONE = unknown / not on a cell.
long curCol = GRID_INDEX_NONE;
long curRow = GRID_INDEX_NONE;

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
//   THE TWO MEASUREMENTS THAT MATTER
// ------------------------------------------------------------
//   Both ends of Z travel are physical switches, so the travel is a
//   fixed property of the hardware. It is described twice - once in
//   steps, once in centimetres - and the ratio is the scale factor
//   the whole build system runs on:
//
//        bottom = the Z- switch, pin 28   (Z = 0 steps, GROUND)
//        top    = the Z+ switch, pin 29   (Z ~ Z_TRAVEL_STEPS)
//
//        steps per cm = Z_TRAVEL_STEPS / Z_TRAVEL_CM
//                     = 1350 / 26.5
//                     = 50.9434 steps per cm approximately
//
//   and one 1.5 cm block is approximately 76.42 steps. The maths
//   below rounds to the nearest step.
//
//   This is computed at RUN TIME by zStepsPerCm(), never hard-coded,
//   so re-measuring the rig is a one-line change. Send  Z  to print
//   the resulting table.
//
// ------------------------------------------------------------
//   YOU DO NOT HAVE TO GUESS Z_TRAVEL_STEPS
// ------------------------------------------------------------
//   Since pin 29 went in, the machine measures the step distance
//   itself: any run up into the top switch that STARTED from a true
//   zero records what it counted. Send 0+ (bottom, then top), then 5,
//   and the report prints the measured value beside this constant.
//   If they disagree, put the measured number here - Z_TRAVEL_CM is
//   still yours to tape-measure.
//
//   Getting it wrong no longer risks a crash, because the switch
//   stops the axis either way. It only skews the cm <-> step scale,
//   which shows up as blocks landing slightly high or low.

// Steps between the two Z switches. CALIBRATION ONLY - the pin 29
// switch is what actually stops the axis at the top.
long Z_TRAVEL_STEPS = 1350;

// What the rig last measured between the switches, 0 = not measured
// yet this session. Recorded by applyLimitReference().
long zTravelMeasured = 0;

// Real-world height of the full Z travel, in centimetres.
float Z_TRAVEL_CM = 26.5;

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

float Z_MARGIN_PER_LEVEL_CM = 0.0; // cm added to EACH level (cumulative)
float Z_MARGIN_FIXED_CM = 0.12;    // cm added ONCE to any level >= 1
long Z_MARGIN_FIXED_STEPS = 0;     // raw step trim, applied last

// ------------------------------------------------------------
//   HOW HIGH ARE WE ALLOWED TO BUILD?
// ------------------------------------------------------------
//   The claw can physically reach Z_TRAVEL_CM (26.5 cm), but building
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
// The claw is assumed to START neutral. A manual `A <degrees>` jog is tracked
// relative to that assumed position; there is no sensor that can prove it.
//
// A horizontal build turns its block 90 CW. That leaves the claw turned too,
// which would be wrong for the NEXT pick-up. So the build sequence always
// returns to neutral while it is over the feeder at 0,0 - before it descends -
// and only then applies THIS grid's placement rotation at the target.
//
//   last build did CW  ->  next build rotates CCW at home (back to 0)
//   last build did CCW ->  next build rotates CW at home  (back to 0)
//   last build did NR  ->  nothing to undo

const int8_t ROT_NONE = 0;
const int8_t ROT_CW = +1;
const int8_t ROT_CCW = -1;

// Where the claw is RIGHT NOW, relative to neutral. A manual angle that is
// not exactly 0/+90/-90 has no calibrated tool offset, so it is marked
// unknown until a build returns it to neutral.
int8_t clawRotation = ROT_NONE;
bool clawRotationKnown = true;

// ============================================================
// SECTION 7 - STEP COUNTER / POSITION CONFIGURATION
// ============================================================

unsigned long stepCounts[MOVE_COUNT] = {0, 0, 0, 0, 0, 0};

long axisPos[AXIS_COUNT] = {0, 0, 0};

// True only after a successful home. Grid moves and builds refuse to
// run before this, because both are nonsense without a real origin.
// (Z is set true the moment its physical switch trips, same as X/Y.)
bool axisHomed[AXIS_COUNT] = {false, false, false};

// Where that position came from: true = the axis' HOME switch set it,
// which is the only reference precise enough to measure against.
//
// Z can also be positioned by its TOP switch, which is a guess taken
// from Z_TRAVEL_STEPS rather than something counted - good enough to
// work with, not good enough to calibrate from. Keeping the two
// apart is what stops a top-switch guess being reported back as a
// measurement of itself. See applyLimitReference().
bool axisRefAtHome[AXIS_COUNT] = {false, false, false};

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
unsigned long statJogs = 0;          // 1-4, D, U
unsigned long statGotos = 0;         // G
unsigned long statHomeCommands = 0;  // 0
unsigned long statBuildCommands = 0; // B (parsed OK, whether or not it ran)
unsigned long statBadCommands = 0;   // unparseable / unknown lines

// --- per axis ---
unsigned long statHomeRuns[AXIS_COUNT] = {0, 0, 0};
unsigned long statHomeFails[AXIS_COUNT] = {0, 0, 0};
unsigned long statSoftBlocks[AXIS_COUNT] = {0, 0, 0}; // soft limit refusals
unsigned long statShortMoves[AXIS_COUNT] = {0, 0, 0}; // moves that stopped early

// --- per SWITCH, not per axis ---
//
// Z has two of them, and "the Z switch was hit" would be an ambiguous
// thing to count. Per-axis totals are summed on demand by
// axisSwitchTrips() for the axis table.
unsigned long statSwitchTrips[LIMIT_COUNT] = {0, 0, 0, 0};

// Edge detection, so one physical trip counts once instead of once
// per step spent sitting on the switch.
bool limitWasActive[LIMIT_COUNT] = {false, false, false, false};
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
// SECTION 7C - MACHINE ACKNOWLEDGEMENTS
// ============================================================
//
// Everything else this sketch prints is written for a human. These
// lines are written for the Raspberry Pi. One per outcome, always
// starting with '@' - a character no other line in this sketch begins
// with, so the Pi filters them out with a single test and a human
// reading the Serial Monitor can ignore them by eye.
//
//     @<seq> <KIND> [reason text | key=value ...]
//
// The human text is NEVER removed. An ack is printed BESIDE it, so a
// Serial Monitor session reads exactly as it always did.
//
// The kinds:
//     OK    finished, block placed, rig parked - safe
//     ERR   refused before anything moved (bad command)
//     SAFE  failed before anything moved
//     HELD  failed PART WAY THROUGH. The claw may still be gripping a
//           block and the position is unknown. NEEDS A HUMAN.
//
// SAFE and HELD are separate KINDS rather than a flag on one kind on
// purpose: it means code on the Pi cannot lump them together with a
// generic "if not ok: retry". The retry is what breaks the rig.
//
// The sequence number is assigned HERE, not by the Pi, so that the
// command grammar stays type-able by hand in a Serial Monitor. The rig
// runs one command at a time, so "the ack after my command" is never
// ambiguous. Seq 0 means nobody asked - BOOT and READY.
//
// F() everywhere, as always - see the note at the top of the file.

uint16_t ackSeq = 0;

void ackStart(const __FlashStringHelper *kind)
{
  Serial.print('@');
  Serial.print(ackSeq);
  Serial.print(' ');
  Serial.print(kind);
}

void ackField(const __FlashStringHelper *name, long value)
{
  Serial.print(' ');
  Serial.print(name);
  Serial.print('=');
  Serial.print(value);
}

// A key=value pair whose value is a WORD rather than a number.
//
// Deliberately not an ackField() overload: an integer literal 0 is also a
// null pointer constant, so ackField(F("level"), 0) would become ambiguous
// and every existing numeric call site is one edit away from that trap.
void ackWord(const __FlashStringHelper *name, const __FlashStringHelper *value)
{
  Serial.print(' ');
  Serial.print(name);
  Serial.print('=');
  Serial.print(value);
}

// ---- STEP: real-time build progress, one line per PHASE ----
//
// A build is ~40 seconds of motion during which the sketch never reads
// serial, so without these the Pi learns nothing between "B sent" and
// the terminal ack. One line per phase - FOURTEEN lines per build, not
// one per motor step. At 9600 baud fourteen lines is about 0.3 s of
// airtime inside a 40 s build; one line per step would be minutes and
// would starve the terminal ack that actually matters.
//
//     @12 STEP step=8 total=14 phase=move_to_target action=move
//         text=Move_XY_to_target status=begin
//
// STEP is NOT terminal. It carries the same ackSeq as the B command it
// belongs to, so the Pi can attribute every phase to one command.
//
//   step    1..BUILD_STEP_COUNT
//   total   BUILD_STEP_COUNT, so the Pi never hard-codes 14
//   phase   a STABLE identifier - the thing UIs switch on. Never
//           reword one of these without changing the Pi with it.
//   action  what the phase is expected to do: move / grip / release /
//           rotate / park. Coarse on purpose; the twin needs to know
//           whether a block is being carried, not which motor turns.
//   text    the human label, underscored so it stays one token
//   status  'begin' before the phase runs. The single 'done' is
//           phase 11, which is the moment the block leaves the claw -
//           see the note at its call site.
//
// Emitted whatever BUILD_VERBOSE says: the prose is for the human and
// may be turned off, but the machine channel is not a debug aid.
void ackStep(uint8_t n,
             const __FlashStringHelper *phase,
             const __FlashStringHelper *action,
             const __FlashStringHelper *label,
             const __FlashStringHelper *status,
             long etaMs)
{
  ackStart(F("STEP"));
  ackField(F("step"), (long)n);
  ackField(F("total"), (long)BUILD_STEP_COUNT);
  ackWord(F("phase"), phase);
  ackWord(F("action"), action);
  ackWord(F("text"), label);
  ackWord(F("status"), status);
  // Omitted rather than sent as zero when this phase has no predictable
  // duration. Absent means "no idea"; 0 would mean "instant", and a UI
  // cannot tell those apart from a number alone.
  if (etaMs > 0)
  {
    ackField(F("ms"), etaMs);
  }
  Serial.println();
}

// One complete ack with a trailing reason. The const char* overload
// takes the SAME pointer the prose above it already printed, so it
// costs no extra SRAM.
void ackReason(const __FlashStringHelper *kind, const char *why)
{
  ackStart(kind);
  Serial.print(' ');
  Serial.println(why);
}

void ackReason(const __FlashStringHelper *kind, const __FlashStringHelper *why)
{
  ackStart(kind);
  Serial.print(' ');
  Serial.println(why);
}

// The first machine line after a reset. Opening the serial port
// reboots the board, so the Pi sees this on every connect - and an
// unexpected one mid-command means the board reset under us.
void ackBoot()
{
  Serial.println(F("@0 BOOT fw=build_test_v1"));
}

// The LAST line of setup(). This is the Pi's sync marker: everything
// before it is banner, everything after it is a response. Matching the
// banner by its wording is what this replaces.
void ackReady()
{
  Serial.print(F("@0 READY grid="));
  Serial.print(gridColsNow());
  Serial.print('x');
  Serial.print(gridRowsNow());
  // The mode is on this line because a reset silently returns the board to
  // vertical. A Pi that believes otherwise would send every coordinate to the
  // wrong grid, so it has to be told on every connect, not asked for later.
  Serial.print(F(" mode="));
  Serial.print(gridModeName(gridMode));
  Serial.println();
}

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
const char CMD_SERVO_ANGLE = 'V'; // V <angle> (0..180 degrees)
const char CMD_AUX_STEPPER_ANGLE = 'A'; // A <degrees> (-360..360, relative)

// R and RR are the GRID MODE LATCH, not a claw jog. R selects the vertical
// grid, RR the horizontal one; neither moves the aux stepper. RR is handled in
// handleLine because it is two characters.
const char CMD_GRID_MODE_VERTICAL = 'R';

const char CMD_BUILD = 'B';   // B <col> <row> <level>
const char CMD_Z_TABLE = 'Z'; // print the Z / build calibration

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

  // The claw is assumed to be physically neutral at power-on.
  auxStepperPos = 0;
  auxAngleSteps = 0;
  clawRotation = ROT_NONE;
  clawRotationKnown = true;

  // Start the statistics window with the machine.
  statsSinceMs = millis();

  Serial.begin(9600);
  delay(1000);

  ackBoot();

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
  Serial.println(F(">> Z+ is a HARDWARE end stop (pin 29), not a soft limit."));

  ackReady();
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

  // shiftX / shiftY are routed here, BEFORE the switch on head, so the leading
  // 'S' never has to be shared with 'S <cols> <rows>'. Two-letter "sh" prefix.
  if ((line[0] == 's' || line[0] == 'S') && (line[1] == 'h' || line[1] == 'H'))
  {
    handleShiftCommand(line);
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
      Serial.println(F("  ERROR - use:  S <cols> <rows>   e.g.  S 20 4"));
    }
    break;

  case CMD_SERVO_ANGLE:
    if (parseNumbers(line + 1, &a, 1, NULL) == 1 && a >= 0 && a <= 180)
    {
      setServoAngle((int)a);
    }
    else
    {
      statBadCommands++;
      Serial.println();
      Serial.println(F("  ERROR - use:  V <angle>   where angle is 0..180 degrees"));
    }
    break;

  case CMD_AUX_STEPPER_ANGLE:
    if (parseSignedDegree(line + 1, &a)
        && a >= -AUX_STEPPER_MAX_MANUAL_DEGREES
        && a <= AUX_STEPPER_MAX_MANUAL_DEGREES)
    {
      rotateAuxStepperDegrees(a);
    }
    else
    {
      statBadCommands++;
      Serial.println();
      Serial.println(F("  ERROR - use:  A <degrees>   where degrees is -360..360"));
      Serial.println(F("  Positive is CW; negative is CCW; this is relative, not absolute."));
    }
    break;

  case CMD_BUILD:
    handleBuildCommand(line + 1);
    break;

  case 'R':
    if (toUpperChar(line[1]) == 'R' && line[2] == '\0')
    {
      // RR: latch the HORIZONTAL grid. Moves nothing - see setGridMode().
      if (!setGridMode(GRID_MODE_HORIZONTAL))
      {
        statBadCommands++;
      }
    }
    else
    {
      statBadCommands++;
      Serial.println();
      Serial.println(F("  ERROR - use:  R (vertical grid) or RR (horizontal grid)"));
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

  case CMD_GRID_MODE_VERTICAL:
    // R: latch the VERTICAL grid. Moves nothing - see setGridMode().
    if (!setGridMode(GRID_MODE_VERTICAL))
    {
      statBadCommands++;
    }
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

// `parseNumbers()` deliberately treats '-' as a separator because G/S/B use
// non-negative coordinates. The manual aux-stepper command is the one place
// a signed value is meaningful, so keep its stricter parser separate.
bool parseSignedDegree(const char *s, long *out)
{
  uint8_t i = 0;
  while (s[i] == ' ' || s[i] == '\t')
  {
    i++;
  }

  bool negative = false;
  if (s[i] == '+' || s[i] == '-')
  {
    negative = (s[i] == '-');
    i++;
  }
  if (s[i] < '0' || s[i] > '9')
  {
    return false;
  }

  long value = 0;
  while (s[i] >= '0' && s[i] <= '9')
  {
    value = value * 10 + (s[i] - '0');
    i++;
  }
  while (s[i] == ' ' || s[i] == '\t')
  {
    i++;
  }
  if (s[i] != '\0')
  {
    return false;
  }

  *out = negative ? -value : value;
  return true;
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
    curCol = GRID_INDEX_NONE;
    curRow = GRID_INDEX_NONE;
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
  const bool atFeederHome = isLimitHitAt(homeLimitIndexOf(AXIS_X)) &&
                            isLimitHitAt(homeLimitIndexOf(AXIS_Y));
  const int openAngle = atFeederHome ? SERVO_HOME_OPEN_ANGLE : SERVO_OPEN_ANGLE;

  gripperServo.write(openAngle);
  servoIsOpen = true;
  statServoOpens++;

  Serial.println();
  Serial.print(F("SERVO: OPEN ("));
  Serial.print(openAngle);
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

void setServoAngle(int angle)
{
  gripperServo.write(angle);
  servoIsOpen = (angle == SERVO_HOME_OPEN_ANGLE || angle == SERVO_OPEN_ANGLE);

  Serial.println();
  Serial.print(F("SERVO: ANGLE ("));
  Serial.print(angle);
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

// Keep the physical angle in (-half turn, +half turn]. The motor has no
// sensor, so this is only as true as the assumed neutral at power-on and the
// steps that have successfully been commanded since then.
long normaliseAuxAngleSteps(long steps)
{
  const long halfTurn = AUX_STEPPER_STEPS_PER_REV / 2;
  while (steps > halfTurn)
  {
    steps -= AUX_STEPPER_STEPS_PER_REV;
  }
  while (steps <= -halfTurn)
  {
    steps += AUX_STEPPER_STEPS_PER_REV;
  }
  return steps;
}

void updateClawRotationKnowledge()
{
  if (auxAngleSteps == 0)
  {
    clawRotation = ROT_NONE;
    clawRotationKnown = true;
  }
  else if (auxAngleSteps == AUX_STEPPER_QUARTER_TURN)
  {
    clawRotation = ROT_CW;
    clawRotationKnown = true;
  }
  else if (auxAngleSteps == -AUX_STEPPER_QUARTER_TURN)
  {
    clawRotation = ROT_CCW;
    clawRotationKnown = true;
  }
  else
  {
    clawRotationKnown = false;
  }
}

void stepAuxStepper(long steps)
{
  if (steps == 0)
  {
    return;
  }
  auxStepper.step(steps);
  auxStepperPos += steps;
  auxAngleSteps = normaliseAuxAngleSteps(auxAngleSteps + steps);
  updateClawRotationKnowledge();
}

long auxStepsForDegrees(long degrees)
{
  long magnitude = degrees < 0 ? -degrees : degrees;
  // Round to the nearest available motor step rather than always making a
  // small requested angle short. 2048 steps/rev gives ~0.176 degrees/step.
  long steps = (magnitude * AUX_STEPPER_STEPS_PER_REV + 180) / 360;
  return degrees < 0 ? -steps : steps;
}

void rotateAuxStepperDegrees(long degrees)
{
  long steps = auxStepsForDegrees(degrees);

  Serial.println();
  Serial.print(F("AUX STEPPER: rotating "));
  Serial.print(degrees);
  Serial.print(F(" deg relative ("));
  Serial.print(steps);
  Serial.print(F(" steps) "));
  Serial.println(degrees < 0 ? F("CCW...") : F("CW..."));

  stepAuxStepper(steps);

  Serial.print(F("AUX STEPPER: done. Tracked angle from power-on neutral: "));
  Serial.print((float)auxAngleSteps * 360.0 / (float)AUX_STEPPER_STEPS_PER_REV, 1);
  Serial.println(F(" deg."));
  if (!clawRotationKnown)
  {
    Serial.println(F("  Grid moves/latches are refused until a B returns the claw to neutral."));
  }
}

void rotateAuxStepperCW()
{
  Serial.println();
  Serial.println(F("AUX STEPPER: rotating ~90 deg CW..."));
  stepAuxStepper(AUX_STEPPER_QUARTER_TURN);
  statRotCW++;
  Serial.println(F("AUX STEPPER: done."));
}

void rotateAuxStepperCCW()
{
  Serial.println();
  Serial.println(F("AUX STEPPER: rotating ~90 deg CCW..."));
  stepAuxStepper(-AUX_STEPPER_QUARTER_TURN);
  statRotCCW++;
  Serial.println(F("AUX STEPPER: done."));
}

// ------------------------------------------------------------
// Rotation as a TRACKED STATE, not a blind jog.        <<< NEW
// ------------------------------------------------------------
// Build rotation is a target angle, not a blind jog. A manual A command may
// leave the claw at an arbitrary tracked angle, so return from that actual
// angle rather than assuming only the three old quarter-turn states exist.

const char *rotationName(int8_t rot)
{
  if (rot == ROT_CW)
  {
    return "CW (+90)";
  }
  if (rot == ROT_CCW)
  {
    return "CCW (-90)";
  }
  return "NR (neutral)";
}

// Turns the claw so it ends up at `target` (ROT_NONE / CW / CCW), whatever it
// is doing now, including a tracked arbitrary manual A angle.
void rotateClawTo(int8_t target)
{
  long targetSteps = (long)target * AUX_STEPPER_QUARTER_TURN;
  long delta = targetSteps - auxAngleSteps;
  if (delta == 0)
  {
    if (BUILD_VERBOSE)
    {
      Serial.print(F("  Claw already at "));
      Serial.print(rotationName(target));
      Serial.println(F(" - no rotation needed."));
    }
    return;
  }

  Serial.print(F("  Rotating claw: "));
  if (clawRotationKnown)
  {
    Serial.print(rotationName(clawRotation));
  }
  else
  {
    Serial.print(F("manual angle"));
  }
  Serial.print(F("  ->  "));
  Serial.println(rotationName(target));

  // One direct correction handles e.g. a manual 45-degree jog. Ordinary
  // quarter-turn build moves keep their existing statistics and diagnostics.
  if ((delta % AUX_STEPPER_QUARTER_TURN) == 0)
  {
    while (delta > 0)
    {
      rotateAuxStepperCW();
      delta -= AUX_STEPPER_QUARTER_TURN;
    }
    while (delta < 0)
    {
      rotateAuxStepperCCW();
      delta += AUX_STEPPER_QUARTER_TURN;
    }
  }
  else
  {
    Serial.print(F("  AUX STEPPER: correcting "));
    Serial.print(delta);
    Serial.println(F(" steps to a calibrated grid angle..."));
    stepAuxStepper(delta);
  }

  clawRotation = target;
  clawRotationKnown = true;
}

// ============================================================
// HOMING / ORIGIN
// ============================================================

long homeMaxStepsOf(uint8_t axis)
{
  long travel = axisTravelOf(axis);

  if (travel <= 0)
  {
    return HOME_MAX_STEPS_FALLBACK; // nothing configured to scale from
  }
  return travel * HOME_MAX_MULTIPLIER + HOME_MAX_SLACK_STEPS;
}

// ------------------------------------------------------------
// Drives toward the switch at ONE END of an axis until it trips.
// ------------------------------------------------------------
// This used to be homeAxis() and could only ever run toward the home
// switch, because that was the only switch an axis had. Z+ on pin 29
// changed that: "go to the top of Z" is now the same operation as
// "home Z", just aimed at the other end, so both go through here.
//
// isPhysicalBlocked() is what notices the contact, and
// applyLimitReference() is what the contact means for the position -
// this function only walks until one of them says stop.
bool seekLimit(uint8_t axis, int8_t end)
{
  int8_t idx = findLimitIndex(axis, end);
  bool isHomeSeek = (idx >= 0) && LIMITS[idx].isHome;

  statHomeRuns[axis]++;

  if (idx < 0 || !LIMITS[idx].enabled)
  {
    Serial.print(F("  CANNOT SEEK "));
    Serial.print(axisName(axis));
    Serial.print(signName(end));
    Serial.println(F(" - no enabled limit switch at that end."));
    if (isHomeSeek)
    {
      axisHomed[axis] = false;
    }
    statHomeFails[axis]++;
    return false;
  }

  long travelled = 0;
  long maxSteps = homeMaxStepsOf(axis);

  if (HOME_VERBOSE)
  {
    if (isHomeSeek)
    {
      Serial.print(F("  Homing "));
    }
    else
    {
      Serial.print(F("  Seeking "));
    }
    Serial.print(axisName(axis));
    Serial.print(signName(end));
    Serial.print(F(" (pin "));
    Serial.print(LIMITS[idx].pin);
    Serial.print(F(") ..."));
  }

  while (travelled < maxSteps)
  {
    if (isPhysicalBlocked(axis, end))
    {
      if (HOME_VERBOSE)
      {
        Serial.print(F(" switch found after "));
        Serial.print(travelled);
        Serial.print(F(" steps. "));
        if (isHomeSeek)
        {
          Serial.println(F("Axis zeroed."));
        }
        else
        {
          Serial.println(F("At the end stop."));
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
      if (isHomeSeek)
      {
        Serial.println(F(" switch found. Axis zeroed."));
      }
      else
      {
        Serial.println(F(" switch found. At the end stop."));
      }
    }
    return true;
  }

  Serial.println();
  Serial.print(F("  SEEK FAILED on "));
  Serial.print(axisName(axis));
  Serial.print(signName(end));
  Serial.print(F(" after "));
  Serial.print(travelled);
  Serial.println(F(" steps - switch never tripped."));
  Serial.println(F("  Check wiring, pin number, and NC/NO setting."));
  if (isHomeSeek)
  {
    axisHomed[axis] = false;
  }
  statHomeFails[axis]++;
  return false;
}

// Drives toward the axis' HOME switch until it trips.
// The switch itself sets axisPos to 0 via isPhysicalBlocked().
bool homeAxis(uint8_t axis)
{
  return seekLimit(axis, homeEndOf(axis));
}

// ------------------------------------------------------------
// 0+  -  the "reset everything" homing.
// ------------------------------------------------------------
// Plain 0 homes X/Y and deliberately leaves Z alone. 0+ resets the
// Z axis as well, which takes two moves rather than one:
//
//   Z DOWN into its BOTTOM switch    - the axis' true zero, and the
//     GROUND the block levels are measured from. Both ends are
//     switches now, so this run is no longer needed to find the top -
//     but it is still needed to know what any height MEANS.
//
//   Z UP into its TOP switch         - where the claw wants to sit
//     between jobs: clear of the bed, clear of anything built, and
//     exactly where a build expects to start from. Doing it in this
//     order also measures the switch-to-switch distance for free.
//
// Z is done BEFORE X/Y so the gantry never drags a low claw across
// the bed - by the time X/Y move, the claw is parked at the top.
bool goToOriginWithZ()
{
  Serial.println();
  Serial.println(F("=== FULL RESET - Z, then X/Y ==="));

  // ---- 1. give Z a real zero ----
  Serial.println(F("  [1/3] Z down into its BOTTOM switch (true zero)..."));
  if (!homeAxis(AXIS_Z))
  {
    Serial.println(F("  ABORTED - Z never found its bottom switch."));
    Serial.println(F("  X/Y were NOT homed: moving now could drag the claw."));
    return false;
  }

  // ---- 2. park it at the top ----
  Serial.println(F("  [2/3] Z up into its TOP switch (pin 29)..."));

  bool okZ = zGoTop();
  if (!okZ)
  {
    // Z has a valid zero and stopped somewhere known, so homing X/Y
    // is still safe and still worth doing. Say so and carry on.
    Serial.println(F("  WARNING - Z never reached the top switch."));
  }
  else
  {
    printZTravelMeasurement();
  }

  // ---- 3. now the claw is high, walk the gantry home ----
  Serial.println(F("  [3/3] Homing X/Y..."));
  bool okXY = goToOrigin();

  Serial.println();
  if (okXY && okZ)
  {
    Serial.println(F("FULL RESET COMPLETE - X/Y at origin, Z on its top switch."));
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
    // Home is (0,0) cm, which is the outer EDGE of cell [0,0] - and therefore
    // inside its footprint, so [0,0] is the honest answer here. Not a sentinel.
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

// Software-safe envelope size and direction of travel for an axis. The grid
// only ever covers X and Y, whose far ends are software limits, so this is
// still the soft cap - taken through axisTravelOf so the two can never drift
// apart.
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
  return (axis == AXIS_X) ? gridColsNow() : gridRowsNow();
}

float xyTravelCmOf(uint8_t axis)
{
  return (axis == AXIS_X) ? X_TRAVEL_CM : Y_TRAVEL_CM;
}

float gridBlockCmOf(uint8_t axis)
{
  return (axis == AXIS_X) ? GRID_BLOCK_X_CM[gridMode] : GRID_BLOCK_Y_CM[gridMode];
}

float gridGapCmOf(uint8_t axis)
{
  return (axis == AXIS_X) ? GRID_GAP_X_CM[gridMode] : GRID_GAP_Y_CM[gridMode];
}

float gridPitchCmOf(uint8_t axis)
{
  return gridBlockCmOf(axis) + gridGapCmOf(axis);
}

// Trim + error offset + live shift, all three of which move the lattice against
// the home switches by exactly the same rule. Folding the shift in here is what
// makes shiftX/shiftY translate every centre, every block edge and the [0,0]
// reference together. gridTrimCmZeroShiftOf() is the same sum with the shift
// left out - used where the PHYSICAL grid size has to be judged (S, mode latch)
// independent of whatever shift happens to be applied right now.
float gridTrimCmZeroShiftOf(uint8_t axis)
{
  return (axis == AXIS_X)
             ? GRID_TRIM_X_CM[gridMode] + GRID_ERROR_OFFSET_X_CM[gridMode]
             : GRID_TRIM_Y_CM[gridMode] + GRID_ERROR_OFFSET_Y_CM[gridMode];
}

float gridShiftCmOf(uint8_t axis)
{
  return (axis == AXIS_X) ? GRID_SHIFT_X_CM[gridMode] : GRID_SHIFT_Y_CM[gridMode];
}

float gridTrimCmOf(uint8_t axis)
{
  return gridTrimCmZeroShiftOf(axis) + gridShiftCmOf(axis);
}

// The ACTIVE mode's block-edge overhang budget. See SECTION 6C for why this is
// per mode and why it is not a trim.
float gridMaxEdgeOverhangCmOf(uint8_t axis)
{
  return (axis == AXIS_X) ? GRID_MAX_EDGE_OVERHANG_X_CM[gridMode]
                          : GRID_MAX_EDGE_OVERHANG_Y_CM[gridMode];
}

float xyStepsPerCmOf(uint8_t axis)
{
  float travelCm = xyTravelCmOf(axis);
  return (travelCm > 0.0) ? (float)gridTravelOf(axis) / travelCm : 0.0;
}

// ------------------------------------------------------------
//   THE LATTICE
// ------------------------------------------------------------
//   Every axis is a run of evenly spaced block CENTRES. The centre of cell 0
//   sits on the home corner itself - not its edge - so a full-travel grid has
//   its last centre exactly on the software limit, and cell 0's block hangs
//   half a block past the home switches. That half block is what
//   GRID_MAX_EDGE_OVERHANG_* budgets for.
//
//       centre(i) = trim + errorOffset + i * pitch
//
//   That is the whole model. There is no leading gap, no trailing gap and no
//   centring: the trim IS the only thing that moves a grid, which is how the
//   horizontal pickup-cell registration (+1.9 cm on both axes) is expressed.
//
//   THE GAPS ARE UNIFORM. A vertical block reads 2.2 + 1.6 + 2.2 along its
//   6.0 cm length, and consecutive blocks are also 1.6 cm apart, so the 2.2 cm
//   sub-cells repeat at one unbroken 3.8 cm pitch. An earlier revision had a
//   0.8 cm block gap, which made the horizontal Y lattice alternate 0.8/1.6;
//   measuring the printed sheet (tiles 6.00 cm, gaps 1.56 cm, identical on
//   both axes) showed the gap is 1.6 everywhere and the alternation was an
//   artefact of the wrong number. Do not reintroduce it without re-measuring.

// Highest index + 1. GRID_COLS/GRID_ROWS hold the highest INDEX.
long gridSlotsOf(uint8_t axis)
{
  return gridCountOf(axis) + 1;
}

// Where the first centre sits: the trim, and nothing else.
float gridLatticeStartCmOf(uint8_t axis)
{
  return gridTrimCmOf(axis);
}

// Near edge of the block on cell `index`, measured from the home switch.
// NEGATIVE for cell 0 on an untrimmed axis - the block overhangs home by half
// its own width, which is exactly the point of a centre-anchored lattice.
float gridSlotBottomCmOf(uint8_t axis, long index)
{
  return cellCentreCmOf(axis, index) - gridBlockCmOf(axis) * 0.5;
}

// The gap between cell `index - 1` and cell `index`. Uniform on every axis.
float gridGapBeforeSlotCmOf(uint8_t axis, long index)
{
  return (index < 1) ? 0.0 : gridGapCmOf(axis);
}

// Home corner to the FAR edge of the last block. Vertical 23.9 x 41.0 cm,
// horizontal 18.2 x 36.9 - both wider than the holder travel, by the half
// block that hangs off each end.
float gridBlockEndCmOf(uint8_t axis, long count)
{
  if (count < 0)
  {
    return gridLatticeStartCmOf(axis);
  }
  return cellCentreCmOf(axis, count) + gridBlockCmOf(axis) * 0.5;
}

// Near edge of cell 0.
float gridBlockStartCmOf(uint8_t axis, long count)
{
  (void)count;
  return gridSlotBottomCmOf(axis, 0);
}

// Blocks plus the gaps between them.
float gridBlockFootprintCmOf(uint8_t axis, long count)
{
  if (count < 0)
  {
    return 0.0;
  }
  return gridBlockEndCmOf(axis, count) - gridBlockStartCmOf(axis, count);
}

// Kept as the name the reports use.
float gridAllocationCmOf(uint8_t axis, long count)
{
  return gridBlockEndCmOf(axis, count);
}

float gridAllocationStartCmOf(uint8_t axis, long count)
{
  (void)count;
  return gridLatticeStartCmOf(axis);
}

// `count` is the HIGHEST INDEX the grid uses, so 0 is a legal one-slot axis.
bool gridGeometryFitsRaw(uint8_t axis, long count)
{
  if (count < 0 || xyStepsPerCmOf(axis) <= 0.0
      || gridBlockCmOf(axis) <= 0.0 || gridGapCmOf(axis) < 0.0)
  {
    return false;
  }
  const float slack = 0.0001;
  float travelCm = xyTravelCmOf(axis);
  float firstCentre = gridSlotBottomCmOf(axis, 0) + gridBlockCmOf(axis) * 0.5;
  float lastCentre = gridSlotBottomCmOf(axis, count) + gridBlockCmOf(axis) * 0.5;

  // Half one: the holder must be able to reach every placement centre.
  if (firstCentre < -slack || lastCentre > travelCm + slack)
  {
    return false;
  }

  // Half two: and the BLOCKS those centres carry must land on the machine.
  // The centre test alone is not enough. A held block naturally extends past
  // the holder-centre envelope, so "the centre is legal" accepts a grid whose
  // far block hangs off the end - which is what a positive X trim on the
  // horizontal grid would produce, pushing its last column edge past the X
  // limit from a perfectly legal centre.
  // Each mode therefore declares how much edge overhang it will tolerate.
  float overhang = gridMaxEdgeOverhangCmOf(axis);
  if (overhang < 0.0)
  {
    return false;
  }
  float nearEdge = gridBlockStartCmOf(axis, count);
  float farEdge = gridBlockEndCmOf(axis, count);
  return nearEdge >= -overhang - slack && farEdge <= travelCm + overhang + slack;
}

// Error offsets correct placement, but must not resize or reject the grid.
// Check the requested lattice against its physical geometry without the
// calibration nudge; cellTargetPosition() still applies the nudge to B/G.
bool gridGeometryFits(uint8_t axis, long count)
{
  float *error = (axis == AXIS_X) ? &GRID_ERROR_OFFSET_X_CM[gridMode]
                                  : &GRID_ERROR_OFFSET_Y_CM[gridMode];
  float saved = *error;
  *error = 0.0;
  bool result = gridGeometryFitsRaw(axis, count);
  *error = saved;
  return result;
}

// The highest INDEX this axis can carry. -1 means not even slot 0 fits.
long gridCountMaxOf(uint8_t axis)
{
  float pitch = gridPitchCmOf(axis);
  if (xyTravelCmOf(axis) <= 0.0 || pitch <= 0.0)
  {
    return -1;
  }
  long plausible = (long)ceil((xyTravelCmOf(axis)
                              + 2.0 * fabs(gridTrimCmOf(axis))
                              + 2.0 * pitch) / pitch);
  long maximum = -1;
  for (long index = 0; index <= plausible; index++)
  {
    if (gridGeometryFits(axis, index))
      maximum = index;
  }
  return maximum;
}

// gridGeometryFits / gridCountMaxOf evaluated with this mode's GRID_SHIFT_*
// momentarily removed. S and the R/RR mode latch judge the PHYSICAL grid -
// "does the size the operator asked for fit the travel at all" - and must not
// be blocked or unblocked by whatever shift is applied at the moment; the live
// shift then clips the usable range in gridColsNow()/gridRowsNow(). The value
// is restored on every path (including the false branch), so this reads the
// geometry without leaving the shift disturbed.
bool physicalGridGeometryFits(uint8_t axis, long count)
{
  float *slot = (axis == AXIS_X) ? &GRID_SHIFT_X_CM[gridMode]
                                 : &GRID_SHIFT_Y_CM[gridMode];
  float saved = *slot;
  *slot = 0.0;
  bool result = gridGeometryFits(axis, count);
  *slot = saved;
  return result;
}

long physicalGridCountMaxOf(uint8_t axis)
{
  float *slot = (axis == AXIS_X) ? &GRID_SHIFT_X_CM[gridMode]
                                 : &GRID_SHIFT_Y_CM[gridMode];
  float saved = *slot;
  *slot = 0.0;
  long result = gridCountMaxOf(axis);
  *slot = saved;
  return result;
}

// Centre of cell `index` (0-based), measured from the home switch corner.
// Cell 0's CENTRE is the home corner itself, so the whole model is one line.
//   vertical   X: 0, 3.8, 7.6, 11.4, 15.2, 19.0, 22.8   (22.8 = the X cap)
//   vertical   Y: 0, 7.6, 15.2, 22.8, 30.4, 38.0        (38.0 = the Y cap)
//   horizontal X: 1.9, 9.5, 17.1                        (the +1.9 registration)
//   horizontal Y: 1.9, 5.7, 9.5 ... 36.1                (the +1.9 registration)
float cellCentreCmOf(uint8_t axis, long index)
{
  return gridTrimCmOf(axis) + (float)index * gridPitchCmOf(axis);
}

float toolOffsetCmOf(uint8_t axis, int8_t rotation)
{
  if (rotation == ROT_CW)
  {
    return (axis == AXIS_X) ? TOOL_OFFSET_CW_X_CM : TOOL_OFFSET_CW_Y_CM;
  }
  if (rotation == ROT_CCW)
  {
    return (axis == AXIS_X) ? TOOL_OFFSET_CCW_X_CM : TOOL_OFFSET_CCW_Y_CM;
  }
  return (axis == AXIS_X) ? TOOL_OFFSET_NEUTRAL_X_CM
                          : TOOL_OFFSET_NEUTRAL_Y_CM;
}

// Convert a desired block centre to a holder position.  The target is refused
// rather than clipped if the calibrated tool offset would put the holder out
// of travel: clipping would silently place a block in the wrong cell.
bool cellTargetPosition(uint8_t axis, long index, int8_t rotation,
                        long *targetPosition)
{
  float holderCm = cellCentreCmOf(axis, index) - toolOffsetCmOf(axis, rotation);
  float travelCm = xyTravelCmOf(axis);
  float scale = xyStepsPerCmOf(axis);
  const float slack = 0.0001;

  if (holderCm < -slack || holderCm > travelCm + slack || scale <= 0.0)
  {
    return false;
  }

  long mag = lround(holderCm * scale);
  long travel = gridTravelOf(axis);
  if (mag < 0 || mag > travel)
  {
    return false;
  }

  *targetPosition = mag * (long)gridDirOf(axis);
  return true;
}

// Centre-to-centre pitch in steps. One number per axis: every lattice here is
// uniform.
float gridPitchStepsOf(uint8_t axis)
{
  return gridPitchCmOf(axis) * xyStepsPerCmOf(axis);
}

// Which physical block footprint the HOLDER/tool position falls in. Adding the
// active tool offset converts the holder counter back into the actual
// placement-centre frame.
//
// Returns GRID_INDEX_NONE for a position in a gap or off the grid entirely.
// That sentinel is -1 rather than 0, because 0 is a REAL cell now - the feeder
// - and reporting "in a gap" as "on the feeder" would be a lie the operator
// could act on.
//
// A scan, not a division: the horizontal Y lattice has no single pitch to
// divide by. Eleven float compares on a MEGA is nothing, and it is the same
// code for both the uniform and the alternating axes.
long positionToIndex(uint8_t axis, long pos, int8_t rotation)
{
  long count = gridCountOf(axis);
  long mag = pos * (long)gridDirOf(axis); // distance from origin
  float scale = xyStepsPerCmOf(axis);

  if (mag < 0 || mag > gridTravelOf(axis) || scale <= 0.0)
  {
    return GRID_INDEX_NONE;
  }

  float cm = (float)mag / scale + toolOffsetCmOf(axis, rotation);
  float halfStepCm = 0.5 / scale;
  float block = gridBlockCmOf(axis);

  for (long index = 0; index <= count; index++)
  {
    float bottom = gridSlotBottomCmOf(axis, index);
    if (cm < bottom - halfStepCm)
    {
      return GRID_INDEX_NONE; // past it already: we are in the gap below
    }
    if (cm <= bottom + block + halfStepCm)
    {
      return index;
    }
  }
  return GRID_INDEX_NONE;
}

bool gridReady()
{
  if (!softEnabledOn(AXIS_X) || !softEnabledOn(AXIS_Y))
  {
    Serial.println(F("  ERROR - grid needs BOTH software limits enabled"));
    Serial.println(F("  and non-zero. Check SECTION 6B."));
    return false;
  }
  if (!gridGeometryFits(AXIS_X, gridColsNow())
      || !gridGeometryFits(AXIS_Y, gridRowsNow()))
  {
    Serial.println(F("  ERROR - grid placement centres/trim do not fit the X/Y holder travel."));
    Serial.println(F("  Check SECTION 6B/6C and send 5 for the calculated geometry."));
    return false;
  }
  return true;
}

// ============================================================
// THE FEEDER
// ============================================================
//
// The feeder does not rotate. A block is always presented STANDING, on the
// VERTICAL [0,0] footprint, whichever grid is latched.
//
// And because the lattice is CENTRE-anchored, vertical [0,0]'s centre IS the
// home corner: picking up is a plain home, with no move out to a cell centre
// afterwards. (An edge-anchored draft of this file walked out to (1.1, 3.0)
// after homing - that was wrong, and it would have gripped every block 1.1 cm
// off along X and 3.0 cm off along Y.)
//
// The claw closes on the middle of the block, which is its centre, so the
// neutral tool offset is genuinely zero rather than merely unmeasured.

bool goToFeeder()
{
  return goToOrigin();
}

// [0,0] is the FEEDER in both modes and is never built on; every other cell,
// including the rest of row 0 and column 0, is a real placement.
bool cellIsFeeder(long col, long row)
{
  return col == 0 && row == 0;
}

// 0 is a real coordinate AND a real block footprint. It no longer means
// "leave that axis alone" - B 0 3 and B 4 0 are ordinary placements now.
bool cellInRange(long col, long row)
{
  if (col < 0 || col > gridColsNow() || row < 0 || row > gridRowsNow())
  {
    Serial.print(F("  ERROR - out of range. Valid: col 0.."));
    Serial.print(gridColsNow());
    Serial.print(F(", row 0.."));
    Serial.println(gridRowsNow());
    return false;
  }
  return true;
}

void setGridSize(long cols, long rows)
{
  Serial.println();

  if (!clawRotationKnown)
  {
    Serial.println(F("  ERROR - claw is at an arbitrary manual A angle."));
    Serial.println(F("  S needs a calibrated 0/+90/-90 angle; run B first."));
    return;
  }

  // These are HIGHEST INDEX, not counts, so 0 is a legal (single-cell) axis.
  // Judged against the PHYSICAL grid (shift removed): S stores the requested
  // size and a live shiftX/shiftY clips what gridColsNow()/gridRowsNow() report,
  // so a shift must not be able to reject a size that genuinely fits the rig.
  if (cols < 0 || rows < 0 ||
      cols > physicalGridCountMaxOf(AXIS_X) || rows > physicalGridCountMaxOf(AXIS_Y) ||
      !physicalGridGeometryFits(AXIS_X, cols) || !physicalGridGeometryFits(AXIS_Y, rows))
  {
    Serial.print(F("  ERROR - highest col index must be 0.."));
    Serial.print(physicalGridCountMaxOf(AXIS_X));
    Serial.print(F(" and highest row index 0.."));
    Serial.print(physicalGridCountMaxOf(AXIS_Y));
    Serial.println(F("."));
    return;
  }

  // Scoped to the ACTIVE mode: the other orientation keeps whatever count it
  // was last given, so latching back and forth does not quietly resize it.
  GRID_COLS[gridMode] = cols;
  GRID_ROWS[gridMode] = rows;

  // Old cell numbers no longer mean the same thing.
  curCol = positionToIndex(AXIS_X, axisPos[AXIS_X], clawRotation);
  curRow = positionToIndex(AXIS_Y, axisPos[AXIS_Y], clawRotation);

  Serial.println(F("GRID RESIZED"));
  printGridConfig();
}

// ============================================================
// GRID MODE LATCH                                      <<< NEW
// ============================================================
//
//   RR  latches vertical -> horizontal
//   R   latches horizontal -> vertical
//
// THIS IS A LATCH, NOT A MOTION. Neither command moves the aux stepper.
// They used to: R and RR were a free 90-degree jog of the claw. That jog is
// gone, because the build cycle already owns claw rotation completely - step 3
// returns to neutral before the pick, step 9 applies the placement rotation,
// step 14 returns to neutral again. Anything a latch did to the claw would be
// undone by the very next build's step 3, so it could only ever look like a
// bug. What these commands change is which GRID the coordinates refer to.
//
// Each command is refused when it is already true: RR in horizontal and R in
// vertical are errors, not no-ops. A latch that silently accepts the state it
// is already in cannot tell a confirmation apart from a mistake.
//
// A mode switch redefines what every coordinate means, so it is also refused
// unless X and Y are homed - curCol/curRow would otherwise be re-read from a
// position whose meaning nobody knows.
//
// NOTHING SENSES THE CLAW'S PHYSICAL ANGLE. The operator is trusted to have
// started with the claw neutral; see SECTION 6C.

bool setGridMode(uint8_t mode)
{
  Serial.println();

  if (mode >= GRID_MODE_COUNT)
  {
    Serial.println(F("  ERROR - unknown grid mode."));
    return false;
  }

  if (mode == gridMode)
  {
    Serial.print(F("  ERROR - already in "));
    Serial.print(gridModeName(gridMode));
    Serial.println(F(" mode."));
    Serial.println(F("  RR selects horizontal, R selects vertical."));
    return false;
  }

  if (!axisHomed[AXIS_X] || !axisHomed[AXIS_Y])
  {
    Serial.println(F("  ERROR - home X/Y first (send 0)."));
    Serial.println(F("  A mode switch redefines every coordinate, so the"));
    Serial.println(F("  current cell has to mean something before it is re-read."));
    return false;
  }

  if (!clawRotationKnown)
  {
    Serial.println(F("  ERROR - claw is at an arbitrary manual A angle."));
    Serial.println(F("  Latching a grid needs a calibrated 0/+90/-90 angle; run B first."));
    return false;
  }

  uint8_t previous = gridMode;
  gridMode = mode;

  // The other mode's counts and trims are now live. If its REQUESTED size does
  // not physically fit (judged with that mode's shift removed), say so and stay
  // where we were rather than latching into an unusable grid. A shift that only
  // clips the far column/row is fine - gridColsNow()/gridRowsNow() absorb it.
  if (!physicalGridGeometryFits(AXIS_X, GRID_COLS[gridMode])
      || !physicalGridGeometryFits(AXIS_Y, GRID_ROWS[gridMode]))
  {
    gridMode = previous;
    Serial.print(F("  ERROR - the "));
    Serial.print(gridModeName(mode));
    Serial.println(F(" grid does not fit the X/Y travel."));
    Serial.println(F("  Staying in the current mode. Check SECTION 6C, send 5."));
    return false;
  }

  // Every old cell number was measured against the other grid's pitch.
  curCol = positionToIndex(AXIS_X, axisPos[AXIS_X], clawRotation);
  curRow = positionToIndex(AXIS_Y, axisPos[AXIS_Y], clawRotation);

  Serial.print(F("GRID MODE: "));
  Serial.print(gridModeName(previous));
  Serial.print(F("  ->  "));
  Serial.println(gridModeName(gridMode));
  Serial.println(F("  The claw did NOT move. The next B turns it at the feeder."));
  printGridConfig();
  return true;
}

// ============================================================
// GRID SHIFT LATCH                                    <<< NEW
// ============================================================
//
//   shiftX <cm> / shiftY <cm>  translate the ACTIVE mode's whole placement
//   lattice - every cell centre, every block edge, and the [0,0] reference the
//   lattice is anchored on - by <cm> along that axis. + is away from the home
//   switch, the same sense as the trims. It is per mode and it is stored in
//   GRID_SHIFT_*_CM, which gridTrimCmOf() folds into the lattice.
//
//   IT MOVES NOTHING and it does NOT touch the pick-up. A build picks up with a
//   plain home to raw [0,0] (goToFeeder -> goToOrigin), which runs no lattice
//   math, so phases 1-7 happen on the un-shifted grid and only the PLACEMENT
//   (phase 8 onward, via cellTargetPosition -> cellCentreCmOf) rides the shift.
//   [0,0] stays the feeder and the inert B 0 0 no-op in both modes.
//
//   The reachable range is recomputed: gridColsNow()/gridRowsNow() clip the
//   requested GRID_COLS/GRID_ROWS to whatever still fits the X/Y travel under
//   the shift, so a shift that pushes the far column/row past the cap simply
//   drops it (shiftX/shiftY 0 brings it back). A shift that leaves not even
//   cell 0 on the machine is refused and the previous value restored.

// A signed decimal number of centimetres: optional +/-, digits, optional
// fractional part. Leading separators are tolerated (the caller passes the
// slice right after the axis letter); a trailing non-space is an error.
bool parseSignedCm(const char *s, float *out)
{
  uint8_t i = 0;
  while (s[i] == ' ' || s[i] == '\t' || s[i] == ',' || s[i] == ':' || s[i] == '=')
  {
    i++;
  }

  bool negative = false;
  if (s[i] == '+' || s[i] == '-')
  {
    negative = (s[i] == '-');
    i++;
  }

  bool sawDigit = false;
  float value = 0.0;
  while (s[i] >= '0' && s[i] <= '9')
  {
    value = value * 10.0 + (float)(s[i] - '0');
    sawDigit = true;
    i++;
  }
  if (s[i] == '.')
  {
    i++;
    float place = 0.1;
    while (s[i] >= '0' && s[i] <= '9')
    {
      value += (float)(s[i] - '0') * place;
      place *= 0.1;
      sawDigit = true;
      i++;
    }
  }

  if (!sawDigit)
  {
    return false;
  }
  while (s[i] == ' ' || s[i] == '\t')
  {
    i++;
  }
  if (s[i] != '\0')
  {
    return false;
  }

  *out = negative ? -value : value;
  return true;
}

// Set the ACTIVE mode's shift on `axis` to `cm` absolute (cm == 0 clears it).
// Refuses - and restores the previous value - if the result leaves no cell on
// the X/Y travel. Never moves the machine.
void applyGridShift(uint8_t axis, float cm)
{
  Serial.println();
  ackSeq++;

  if (!clawRotationKnown)
  {
    Serial.println(F("  ERROR - claw is at an arbitrary manual A angle."));
    Serial.println(F("  shiftX/shiftY needs a calibrated 0/+90/-90 angle; run B first."));
    ackReason(F("ERR"), F("claw angle uncalibrated"));
    return;
  }

  float *slot = (axis == AXIS_X) ? &GRID_SHIFT_X_CM[gridMode]
                                 : &GRID_SHIFT_Y_CM[gridMode];
  float previous = *slot;
  *slot = cm;

  if (gridCountMaxOf(AXIS_X) < 0 || gridCountMaxOf(AXIS_Y) < 0)
  {
    *slot = previous;
    Serial.print(F("  ERROR - a "));
    Serial.print(cm, 3);
    Serial.print(F(" cm "));
    Serial.print((axis == AXIS_X) ? F("X") : F("Y"));
    Serial.println(F(" shift leaves no cell on the X/Y travel. Reverted."));
    ackReason(F("SAFE"), F("shift makes the grid unusable"));
    return;
  }

  // Old cell numbers were measured against the un-shifted lattice.
  curCol = positionToIndex(AXIS_X, axisPos[AXIS_X], clawRotation);
  curRow = positionToIndex(AXIS_Y, axisPos[AXIS_Y], clawRotation);

  Serial.print(F("GRID SHIFT ["));
  Serial.print(gridModeName(gridMode));
  Serial.print(F("] "));
  Serial.print((axis == AXIS_X) ? F("X") : F("Y"));
  Serial.print(F("  "));
  Serial.print(previous, 3);
  Serial.print(F(" -> "));
  Serial.print(cm, 3);
  Serial.println(F(" cm   (pick-up NOT shifted; applied from [0,0])"));

  long req = (axis == AXIS_X) ? GRID_COLS[gridMode] : GRID_ROWS[gridMode];
  long eff = (axis == AXIS_X) ? gridColsNow() : gridRowsNow();
  if (eff < req)
  {
    Serial.print(F("  highest "));
    Serial.print((axis == AXIS_X) ? F("col") : F("row"));
    Serial.print(F(" index clipped to "));
    Serial.print(eff);
    Serial.print(F(" of "));
    Serial.print(req);
    Serial.print(F(" requested  (shift"));
    Serial.print((axis == AXIS_X) ? F("X") : F("Y"));
    Serial.println(F(" 0 restores it)"));
  }

  printGridConfig();
  ackReason(F("OK"), F("grid shifted"));
}

// Parse "shiftX <cm>" / "shiftY <cm>" (any case) and apply it. `line` is the
// whole command line; the caller has already checked it begins "sh".
void handleShiftCommand(const char *line)
{
  const char *tag = "SHIFT";
  for (uint8_t i = 0; i < 5; i++)
  {
    if (toUpperChar(line[i]) != tag[i])
    {
      statBadCommands++;
      Serial.println();
      Serial.println(F("  ERROR - use:  shiftX <cm>   or   shiftY <cm>"));
      return;
    }
  }

  char axisChar = toUpperChar(line[5]);
  uint8_t axis;
  if (axisChar == 'X')
  {
    axis = AXIS_X;
  }
  else if (axisChar == 'Y')
  {
    axis = AXIS_Y;
  }
  else
  {
    statBadCommands++;
    Serial.println();
    Serial.println(F("  ERROR - use:  shiftX <cm>   or   shiftY <cm>   (axis must be X or Y)"));
    return;
  }

  float cm = 0.0;
  if (!parseSignedCm(line + 6, &cm))
  {
    statBadCommands++;
    Serial.println();
    Serial.println(F("  ERROR - use:  shiftX <cm>   e.g.  shiftX 1.6   shiftY -0.8   shiftX 0"));
    return;
  }

  applyGridShift(axis, cm);
}

// ============================================================
// GO TO CELL
// ============================================================

// Homes, then drives Y and X so the selected tool centre lands at the cell.
// `rotation` is the orientation that will exist when the block is placed.
// Returns true only if every axis that was asked to move actually arrived.
//
// Every cell is a real position now, 0 included: both axes always move. G 0 0
// drives to the FEEDER centre rather than to raw home, because that is where
// cell [0,0] actually is.
bool gotoCellForRotation(long col, long row, int8_t rotation)
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

  if (cellIsFeeder(col, row))
  {
    Serial.println(F("  [0,0] is the FEEDER - going to its centre."));
    return goToFeeder();
  }

  long targetX = 0;
  long targetY = 0;
  if (!cellTargetPosition(AXIS_X, col, rotation, &targetX) ||
      !cellTargetPosition(AXIS_Y, row, rotation, &targetY))
  {
    Serial.println(F("  ERROR - tool offset puts the holder outside the X/Y travel."));
    Serial.println(F("  Refusing to clip the target; check tool offset calibration."));
    return false;
  }

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

  curCol = positionToIndex(AXIS_X, axisPos[AXIS_X], clawRotation);
  curRow = positionToIndex(AXIS_Y, axisPos[AXIS_Y], clawRotation);
  Serial.println(F("  MOVE INCOMPLETE - a limit stopped it short."));
  return false;
}

// A manual G command uses the orientation the claw has right now. A build
// supplies its requested final orientation explicitly before it rotates.
bool gotoCell(long col, long row)
{
  if (!clawRotationKnown)
  {
    Serial.println();
    Serial.println(F("  ERROR - claw is at an arbitrary manual A angle."));
    Serial.println(F("  G needs a calibrated 0/+90/-90 angle; run B to return neutral."));
    return false;
  }
  return gotoCellForRotation(col, row, clawRotation);
}

// ------------------------------------------------------------
// DYNAMIC X/Y SKEW COMPENSATION  -  PER MODE, BUILD MOTION ONLY
// ------------------------------------------------------------
//
// Full write-up: docs/X_RAIL_SKEW_COMPENSATION.md
//
// WHY THIS EXISTS - the mechanical cause
// --------------------------------------
// The arm holder (the carriage that rides the X aluminium rod) is not
// supported symmetrically: its mass, the drag of the cable chain, and the
// side load from the belt all pull on ONE side of the holder. That constant
// sideways pull bows / twists the X aluminium rod slightly, so the rod is no
// longer square to Y - it sits at a small angle. The further the carriage is
// driven along X, the more of that angled rod it has travelled over, so the
// carriage also drifts along Y. The drift is therefore proportional to how
// far along X we go: ~0 at column 0, and growing by a fixed amount per column.
//
// We do NOT fix this in hardware (re-machining / re-bracing the rod). We
// cancel it in software here: for a build we deliberately command Y to a
// position that is offset by exactly the drift the slanted rod will add, so
// the two cancel and the block lands where the perfect grid says it should.
//
// WHAT WE MEASURED
// ----------------
// The current measurement finds that moving one cell along X pulls the arm
// ~0.115 cm along Y. It is linear in the column index and there is no
// row dependence (a pure-Y move - same column - has no error at all):
//
//     column 0  ->  +0.00 cm Y   (reference, no X travel)
//     column 1  ->  +0.115 cm Y
//     column 2  ->  +0.230 cm Y
//     column 3  ->  +0.345 cm Y
//     column k  ->  +0.115 * k cm Y
//
// This is now stored separately for EACH target axis and EACH grid mode.  A
// physical error is allowed to have an X and a Y component, and the vertical
// and horizontal grids have distinct pitches and can be calibrated separately.
//
// Both modes presently use the same measured Y/column setting. The horizontal
// slot remains independent: measure horizontal placements before retuning it.
//
// SIGN - "forward" = +Y = further from the Y home switch (row 0 side). The
// nudge is ADDED to the Y target, so selecting cell [1,0] drives the rig
// ~0.115 cm forward, [2,0] ~0.230 cm forward, and so on.
//
//   axisNudge_cm = SKEW_<AXIS>_PER_COL_CM[gridMode]    * col
//                + SKEW_<AXIS>_PER_ROW_CM[gridMode]    * row
//                + SKEW_<AXIS>_PER_COLROW_CM[gridMode] * col * row
//
// This is STATIC in firmware. Nothing supplies it over serial - it is computed
// from the cell indices on every build. The six per-axis tables below are the
// ONLY knobs; re-fit the active mode if the rig is re-measured.
//
// SCOPE - this correction lives here and ONLY here:
//   * It is applied in gotoBuildTarget() alone. The B (BUILD) motion is the
//     only path that gets it.
//   * It is NOT in cellCentreCmOf() / cellTargetPosition() / gridPitch..., so
//     the grid MODEL stays a perfect rectangular lattice.
//   * It is NOT in gotoCellForRotation() (the G command), the grid map, or
//     positionToIndex().
//   * It does not exist in the Python link, the camera grid, the Studio grid,
//     or the 3D grid - every VISUALISATION stays perfectly rectangular. This
//     bends the MOTION so the real bricks come out straight and level.
//   * Either X or Y may be corrected; a zero table leaves that axis unchanged.
//
//                                         { vertical, horizontal }
float SKEW_X_PER_COL_CM[GRID_MODE_COUNT]    = {0.0, 0.0};
float SKEW_X_PER_ROW_CM[GRID_MODE_COUNT]    = {0.0, 0.0};
float SKEW_X_PER_COLROW_CM[GRID_MODE_COUNT] = {0.0, 0.0};
float SKEW_Y_PER_COL_CM[GRID_MODE_COUNT]    = {0.115, 0.13};
float SKEW_Y_PER_ROW_CM[GRID_MODE_COUNT]    = {0.0, 0.0};
float SKEW_Y_PER_COLROW_CM[GRID_MODE_COUNT] = {0.0, 0.0};

// A fixed build-placement correction, independent of cell index. This is
// deliberately firmware-only: unlike GRID_ERROR_OFFSET_* and GRID_SHIFT_*, it
// does not move the grid model, camera overlay, Studio, Twin, or direct G.
// Positive is away from the relevant home switch. Keep every slot zero until
// that mode and axis have been measured.
float BUILD_PLACEMENT_OFFSET_X_CM[GRID_MODE_COUNT] = {0.0, 0.4};
float BUILD_PLACEMENT_OFFSET_Y_CM[GRID_MODE_COUNT] = {0.0, 0.0};

long buildPlacementOffsetSteps(uint8_t axis)
{
  float cm = (axis == AXIS_X) ? BUILD_PLACEMENT_OFFSET_X_CM[gridMode]
                               : BUILD_PLACEMENT_OFFSET_Y_CM[gridMode];
  return lround(cm * xyStepsPerCmOf(axis));
}

// Step offset to add to an X or Y build target for cell [col,row]. Positive
// means farther from that axis's home switch. At the shipped calibration only
// vertical/horizontal Y get +0.115 cm at col 1, +0.230 cm at col 2, etc.; all
// X terms and all row/cross terms are zero until measured.
long buildSkewSteps(uint8_t axis, long col, long row)
{
  float perCol = (axis == AXIS_X) ? SKEW_X_PER_COL_CM[gridMode]
                                  : SKEW_Y_PER_COL_CM[gridMode];
  float perRow = (axis == AXIS_X) ? SKEW_X_PER_ROW_CM[gridMode]
                                  : SKEW_Y_PER_ROW_CM[gridMode];
  float perColRow = (axis == AXIS_X) ? SKEW_X_PER_COLROW_CM[gridMode]
                                     : SKEW_Y_PER_COLROW_CM[gridMode];
  float cm = perCol * (float)col + perRow * (float)row
           + perColRow * (float)col * (float)row;
  return lround(cm * xyStepsPerCmOf(axis));
}

// Kept separate from gotoCellForRotation() because BUILD has its own range and
// lock checks around this call. Both axes always move; [0,0] never reaches
// here, because buildBlock() refuses the feeder before anything picks up.
bool gotoBuildTarget(long col, long row, int8_t rotation)
{
  if (!gridReady() || col < 0 || col > gridColsNow() || row < 0 || row > gridRowsNow())
    return false;

  long targetX = 0;
  long targetY = 0;
  if (!cellTargetPosition(AXIS_X, col, rotation, &targetX) ||
      !cellTargetPosition(AXIS_Y, row, rotation, &targetY))
    return false;

  // Dynamic skew compensation: independently nudge X and Y so the physical
  // brick lands on the rectangular grid. Clamp each target to its own travel
  // so a bad calibration coefficient cannot command beyond a soft limit.
  long *targets[AXIS_COUNT] = {&targetX, &targetY};
  for (uint8_t axis = AXIS_X; axis <= AXIS_Y; axis++)
  {
    long correction = buildPlacementOffsetSteps(axis) + buildSkewSteps(axis, col, row);
    if (correction == 0)
      continue;

    long original = *targets[axis];
    long capped = original + correction;
    long maximum = lround(xyTravelCmOf(axis) * xyStepsPerCmOf(axis));
    if (capped < 0)
      capped = 0;
    else if (capped > maximum)
      capped = maximum;

    Serial.print(F("  Build correction: "));
    Serial.print((axis == AXIS_X) ? F("X ") : F("Y "));
    Serial.print(original);
    Serial.print(F(" -> "));
    Serial.print(capped);
    Serial.print(F(" steps ("));
    Serial.print((float)(capped - original) / xyStepsPerCmOf(axis), 3);
    Serial.println(F(" cm)"));
    *targets[axis] = capped;
  }

  if (!goToOrigin())
    return false;
  bool okY = moveAxisTo(AXIS_Y, targetY);
  bool okX = moveAxisTo(AXIS_X, targetX);
  return okX && okY;
}

// ============================================================
// Z HEIGHT MATH  -  steps <-> cm <-> block levels      <<< NEW
// ============================================================
//
// Nothing below is hard-coded. Every number falls out of the two
// SECTION 6E measurements, Z_TRAVEL_STEPS and Z_TRAVEL_CM.

// The whole conversion, in one place:
//     steps per cm = Z travel in steps / Z travel in cm
float zStepsPerCm()
{
  if (Z_TRAVEL_CM <= 0.0)
  {
    return 0.0;
  }
  return (float)Z_TRAVEL_STEPS / Z_TRAVEL_CM;
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
// Clamped into the known travel so a bad margin cannot ask for a
// height the rig does not have. The top switch would stop the axis
// anyway - this just keeps the reported target honest.
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
  if (steps > Z_TRAVEL_STEPS)
  {
    steps = Z_TRAVEL_STEPS;
  }

  // Z counts UP from its bottom switch, in the travelEndOf direction.
  return steps * (long)travelEndOf(AXIS_Z);
}

// There is deliberately no zTopPosition() any more. The top of Z is
// not a number to move to - it is the pin 29 switch. Use zGoTop().

// ------------------------------------------------------------
// How long a Z move is ABOUT to take, in milliseconds.
// ------------------------------------------------------------
//
// The steppers run at a fixed rate with no acceleration ramp, so a move
// of N steps takes N * stepPeriodMs() plus the one-off direction settle.
// That makes the duration genuinely computable rather than guessed - and
// computing it HERE is the point: Z_TRAVEL_STEPS, BLOCK_HEIGHT_CM and
// STEP_DELAY_Z are firmware-owned (AGENTS.md), so the Pi must never keep
// its own copy of them to work this out. It is told instead, on the STEP
// line, once per phase.
//
// It is a PREDICTION, not a measurement. A stall, a stiff axis or an
// early limit makes the real move longer - never shorter, since nothing
// here goes faster than its step rate. Consumers must therefore treat it
// as a floor, and must never let it stand in for the phase actually
// finishing. See docs/ack-protocol.md.
long zEtaMs(long steps)
{
  if (steps < 0)
  {
    steps = -steps;
  }
  if (steps <= 0)
  {
    return 0;
  }
  return lround((float)steps * stepPeriodMs(AXIS_Z)) + (long)DIR_SETTLE_MS;
}

// Where Z believes it is, in steps from the bottom switch. An unhomed Z
// has no answer, and the callers below deliberately assume the worst
// case (a full travel) rather than reporting a confident wrong number.
long zStepsFromGround()
{
  long here = axisPos[AXIS_Z] * (long)travelEndOf(AXIS_Z);
  if (here < 0)
  {
    here = 0;
  }
  return here;
}

// zGoTop(): a seek UP into the pin 29 switch.
long zEtaToTopMs()
{
  if (!axisHomed[AXIS_Z])
  {
    return zEtaMs(Z_TRAVEL_STEPS);
  }
  return zEtaMs(Z_TRAVEL_STEPS - zStepsFromGround());
}

// zGoGround(): a seek DOWN into the pin 28 switch.
long zEtaToGroundMs()
{
  if (!axisHomed[AXIS_Z])
  {
    return zEtaMs(Z_TRAVEL_STEPS);
  }
  return zEtaMs(zStepsFromGround());
}

// zGoLevel(): level 0 is a ground seek; every other level is an exact
// step target, so its duration is exact too.
long zEtaToLevelMs(long level)
{
  if (level <= 0)
  {
    return zEtaToGroundMs();
  }
  if (!axisHomed[AXIS_Z])
  {
    return zEtaMs(Z_TRAVEL_STEPS);
  }
  long target = levelToZSteps(level) * (long)travelEndOf(AXIS_Z);
  return zEtaMs(zStepsFromGround() - target);
}

// ============================================================
// Z MOVES USED BY THE BUILD                            <<< NEW
// ============================================================

// Raise Z until the TOP SWITCH stops it.
//
// This is the change pin 29 bought us. The old version could not run
// until Z had been homed at the BOTTOM, because "the top" was a count
// of steps and a count needs a zero to start from - so getting clear
// of the bed meant going down into the bed first. Now the top is a
// switch: drive at it and it stops you, homed or not.
bool zGoTop()
{
  Serial.println(F("  Z up to the TOP switch ..."));

  if (!seekLimit(AXIS_Z, travelEndOf(AXIS_Z)))
  {
    Serial.println(F("  !! Z never reached its top switch (pin 29)."));
    return false;
  }
  return true;
}

// Drop Z onto the table - the bottom switch IS ground, so this
// re-zeroes the axis and kills any accumulated Z error every cycle.
bool zGoGround()
{
  Serial.println(F("  Z down to GROUND (into the bottom Z switch) ..."));
  return homeAxis(AXIS_Z);
}

// Drop Z to a computed block level.
bool zGoLevel(long level)
{
  if (level <= 0)
  {
    return zGoGround();
  }

  // Levels are absolute heights above GROUND, so they only mean
  // something once the bottom switch has given Z a zero. The build
  // sequence always grounds first; this catches every other caller.
  if (!axisHomed[AXIS_Z])
  {
    Serial.println(F("  !! Z has no zero - cannot place at a level."));
    Serial.println(F("  !! Send 0+ (or run a build) to reference Z first."));
    return false;
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
//    B <col> <row> <level>
//
// col / row are grid cells, exactly as in the G command. BUILD additionally
// accepts zero as a calibration sentinel: B 0 5 moves only Y, B 17 0 moves
// only X, and B 0 0 is a completely inert successful command.
// level is a BLOCK level: 0 = ground, 1 = 1.5 cm, 2 = 3.0 cm ...
//
// THERE IS NO ROTATION WORD ANY MORE. Rotation is a property of the GRID, not
// of a block: the vertical grid places blocks unrotated, the horizontal grid
// places every block turned 90 degrees CW. Select the grid with R / RR.
//
// It was removed rather than kept as an override because a per-block rotation
// could place a turned block inside a grid whose cells are not shaped for it -
// a 6.0 cm block laid across a 3.8 cm column pitch, silently, with every
// number in the geometry check still agreeing. That is the exact failure the
// two-grid model exists to prevent, so the override had to go with it.

void printBuildUsage()
{
  Serial.println();
  Serial.println(F("  ERROR - use:  B <col> <row> <level>"));
  Serial.print(F("    col   0.."));
  Serial.print(gridColsNow());
  Serial.println(F("      (0 is a real cell)"));
  Serial.print(F("    row   0.."));
  Serial.print(gridRowsNow());
  Serial.println(F("      (0 is a real cell)"));
  Serial.println(F("    [0,0] is the FEEDER and is never built on."));
  if (gridColsNow() < GRID_COLS[gridMode] || gridRowsNow() < GRID_ROWS[gridMode])
  {
    Serial.print(F("    (grid shift clipped this from col 0.."));
    Serial.print(GRID_COLS[gridMode]);
    Serial.print(F(" / row 0.."));
    Serial.print(GRID_ROWS[gridMode]);
    Serial.println(F("; shiftX/shiftY 0 restores it)"));
  }
  Serial.print(F("    level 0.."));
  Serial.print(maxBuildLevel());
  Serial.print(F("   (0 = ground, 1 = "));
  Serial.print(BLOCK_HEIGHT_CM, 2);
  Serial.println(F(" cm, ...)"));
  Serial.print(F("    rotation comes from the grid mode - now "));
  Serial.print(gridModeName(gridMode));
  Serial.print(F(" ("));
  Serial.print(rotationName(buildRotationForMode()));
  Serial.println(F(")"));
  Serial.println(F("    e.g.  B 3 5 2      or   B 3 5 0"));
}

// D7: the placement rotation is derived from the ACTIVE GRID, never passed
// per block. Vertical places a block the way the feeder presents it;
// horizontal places it turned 90 degrees CW. There is deliberately no way to
// ask for CCW: the horizontal grid is defined in terms of one 90-degree turn,
// and a second direction would be a second, uncalibrated grid.
int8_t buildRotationForMode()
{
  return (gridMode == GRID_MODE_HORIZONTAL) ? ROT_CW : ROT_NONE;
}

// True when only separators are left. B takes exactly three numbers now, and
// anything after them is a mistake worth naming rather than ignoring.
bool onlySeparatorsLeft(const char *s)
{
  uint8_t i = 0;
  while (s[i] == ' ' || s[i] == ',' || s[i] == ':' || s[i] == ';' || s[i] == '\t')
  {
    i++;
  }
  return s[i] == '\0';
}

void handleBuildCommand(const char *args)
{
  long v[3] = {0, 0, 0};
  uint8_t endIndex = 0;

  // Every build attempt gets a sequence number, including the ones
  // that turn out to be malformed - otherwise a bad command produces
  // no ack at all and the Pi sits waiting for its timeout.
  ackSeq++;

  if (parseNumbers(args, v, 3, &endIndex) < 3)
  {
    statBadCommands++;
    printBuildUsage();
    ackReason(F("ERR"), F("expected: B <col> <row> <level>"));
    return;
  }

  if (!onlySeparatorsLeft(args + endIndex))
  {
    statBadCommands++;
    Serial.println();
    Serial.println(F("  ERROR - B takes exactly three numbers."));
    Serial.println(F("  The rotation word is gone. Rotation is a property of"));
    Serial.println(F("  the grid: send RR for the horizontal grid, R for the"));
    Serial.println(F("  vertical one, then build."));
    printBuildUsage();
    ackReason(F("ERR"), F("no rotation word - rotation comes from the R/RR grid mode"));
    return;
  }

  statBuildCommands++;

  // Parsed and accepted. Not terminal, and not yet validated - buildBlock()
  // may still reject the cell. This is the line that pins ackSeq to this B
  // for everything that follows, including every STEP.
  ackStart(F("RECV"));
  ackWord(F("cmd"), F("B"));
  ackField(F("col"), v[0]);
  ackField(F("row"), v[1]);
  ackField(F("level"), v[2]);
  Serial.println();

  buildBlock(v[0], v[1], v[2], buildRotationForMode());
}

void buildPause()
{
  if (BUILD_PHASE_PAUSE_MS > 0)
  {
    delay(BUILD_PHASE_PAUSE_MS);
  }
}

// Announce one phase BEFORE it runs: the machine line first, then the
// prose. The machine line goes out even with BUILD_VERBOSE off - see
// ackStep() in SECTION 7C for why, and for the field list.
void buildStep(uint8_t n,
               const __FlashStringHelper *phase,
               const __FlashStringHelper *action,
               const __FlashStringHelper *label,
               const char *what,
               long etaMs)
{
  ackStep(n, phase, action, label, F("begin"), etaMs);

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

  ackReason(F("SAFE"), why);
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

  ackReason(F("HELD"), why);
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
  buildStep(12, F("park_clear"), F("park"),
            F("Raise_Z_clear_of_the_stack"),
            "Raise Z clear of the block just placed",
            zEtaToTopMs());
  if (!zGoTop())
  {
    Serial.println(F("  !! could not raise Z - NOT parking X/Y."));
    Serial.println(F("  !! moving the gantry now could drag through the stack."));
    return false;
  }
  buildPause();

  buildStep(13, F("park_home"), F("park"),
            F("Return_XY_to_the_origin"),
            "Return X/Y to the origin",
            0);
  if (!goToOrigin())
  {
    Serial.println(F("  !! X/Y did not reach the origin."));
    return false;
  }
  buildPause();

  buildStep(14, F("park_rotation"), F("park"),
            F("Return_the_claw_to_neutral"),
            "Return the claw to its original rotation",
            0);
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

  // [0,0] is the FEEDER, in both modes: it is where blocks come FROM, so
  // placing one there would drop it on the stack we are picking off. It stays
  // the inert no-op it has always been. Every OTHER row-0 / column-0 cell is a
  // real placement now - they all clear the feeder footprint.
  if (cellIsFeeder(col, row))
  {
    Serial.println(F("  [0,0] is the feeder - nothing to do."));
    statLastOk = true;
    ackStart(F("OK"));
    ackField(F("col"), col);
    ackField(F("row"), row);
    ackField(F("level"), level);
    Serial.println();
    return true;
  }

  // ---- validation, all of it, before anything moves ----

  if (!gridReady())
  {
    return buildReject("grid needs both X/Y software limits");
  }
  if (col < 0 || col > gridColsNow() || row < 0 || row > gridRowsNow())
  {
    return buildReject("cell out of range");
  }

  // Reject an impossible compensated holder target before the claw picks up a
  // block.  The same check is repeated in gotoCellForRotation() for direct G.
  long holderTargetX;
  long holderTargetY;
  if (!cellTargetPosition(AXIS_X, col, wantRot, &holderTargetX) ||
      !cellTargetPosition(AXIS_Y, row, wantRot, &holderTargetY))
  {
    Serial.println(F("  ERROR - tool offset puts the holder outside the X/Y travel."));
    return buildReject("tool offset target outside X/Y travel");
  }

  // A build needs BOTH Z switches: the bottom one to find GROUND and
  // pick the block up, the top one to fly it over the stack.
  if (!limitEnabledAt(AXIS_Z, homeEndOf(AXIS_Z)))
  {
    Serial.print(F("  ERROR - build needs the BOTTOM Z switch (pin "));
    Serial.print(LIMIT_PIN_Z_BOT);
    Serial.println(F("). Check SECTION 6."));
    return buildReject("bottom Z limit switch disabled");
  }
  if (!limitEnabledAt(AXIS_Z, travelEndOf(AXIS_Z)))
  {
    Serial.print(F("  ERROR - build needs the TOP Z switch (pin "));
    Serial.print(LIMIT_PIN_Z_TOP);
    Serial.println(F("). Check SECTION 6."));
    return buildReject("top Z limit switch disabled");
  }
  if (Z_TRAVEL_STEPS <= 0)
  {
    Serial.println(F("  ERROR - Z_TRAVEL_STEPS must be greater than zero,"));
    Serial.println(F("  it is what scales cm to steps. Check SECTION 6E."));
    return buildReject("Z step calibration is zero");
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

  buildStep(1, F("raise_clear"), F("move"),
            F("Raise_Z_into_the_top_switch"),
            "Raise Z into the top switch (clearance)",
            zEtaToTopMs());
  if (!zGoTop())
  {
    buildAbort("could not raise Z to the top switch");
    return false;
  }
  buildPause();

  // ---- 2. back to the feeder at the origin ----

  // The feeder is the VERTICAL [0,0] cell CENTRE, not raw home - home is that
  // cell's outer corner. Same point in both modes: the feeder never rotates.
  buildStep(2, F("home_feeder"), F("move"),
            F("Home_XY_to_the_feeder"),
            "Home X/Y to the feeder cell [0,0] (its centre IS home)",
            0);
  if (!goToFeeder())
  {
    buildAbort("could not reach the feeder cell");
    return false;
  }
  buildPause();

  // ---- 3. undo the previous build's rotation, while still high ----

  // Normally a no-op, because phase 14 already left the claw neutral.
  // It also corrects a manually requested A angle before a new pickup.
  buildStep(3, F("neutralise_claw"), F("rotate"),
            F("Return_the_claw_to_neutral"),
            "Return the claw to neutral before picking up",
            0);
  rotateClawTo(ROT_NONE);
  buildPause();

  // ---- 4. open the jaws BEFORE descending onto the block ----

  buildStep(4, F("open_claw"), F("release"),
            F("Open_the_claw"),
            "Open the claw",
            0);
  openServoAndWait();
  buildPause();

  // ---- 5. down to ground (this also re-zeroes Z) ----

  buildStep(5, F("lower_to_ground"), F("move"),
            F("Lower_Z_to_the_ground_switch"),
            "Lower Z to GROUND (bottom Z switch)",
            zEtaToGroundMs());
  if (!zGoGround())
  {
    buildAbort("Z never reached the ground switch");
    return false;
  }
  buildPause();

  // ---- 6. grab it ----

  buildStep(6, F("grip"), F("grip"),
            F("Close_the_claw_and_grip"),
            "Close the claw (grip the block)",
            0);
  closeServoAndWait();
  buildPause();

  // ---- 7. lift to carry height ----

  buildStep(7, F("lift_block"), F("move"),
            F("Raise_Z_to_carry_height"),
            "Raise Z into the top switch (carry height)",
            zEtaToTopMs());
  if (!zGoTop())
  {
    buildAbort("could not lift the block to carry height");
    return false;
  }
  buildPause();

  // ---- 8. fly to the target cell ----

  buildStep(8, F("move_to_target"), F("move"),
            F("Move_XY_to_the_target_cell"),
            "Move X/Y to the target cell",
            0);
  if (!gotoBuildTarget(col, row, wantRot))
  {
    buildAbort("could not reach the target cell");
    return false;
  }
  buildPause();

  // ---- 9. turn the block, still above the stack ----

  buildStep(9, F("rotate_to_grid"), F("rotate"),
            F("Apply_the_grid_rotation"),
            "Apply the requested rotation",
            0);
  rotateClawTo(wantRot);
  buildPause();

  // ---- 10. down onto the stack ----

  buildStep(10, F("lower_to_level"), F("move"),
            F("Lower_Z_to_the_target_level"),
            "Lower Z to the target block level",
            zEtaToLevelMs(level));
  if (!zGoLevel(level))
  {
    buildAbort("Z did not reach the target level");
    return false;
  }
  buildPause();

  // ---- 11. let go ----

  buildStep(11, F("release"), F("release"),
            F("Open_the_claw_and_release"),
            "Open the claw (release the block)",
            0);
  openServoAndWait();

  // The ONE 'done' STEP in the protocol. Every other phase is announced
  // before it runs, but this instant - the jaws open and the block is on
  // the stack - is a fact the Pi cannot infer from the next 'begin': with
  // BUILD_PARK_AFTER_PLACE false there is no phase 12 to imply it. It is
  // NOT a terminal ack: the command is still running, the rig still has to
  // park, and only the OK below says the block is finally placed.
  ackStep(11, F("release"), F("release"),
          F("Open_the_claw_and_release"), F("done"), 0);

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
  if (clawRotationKnown)
  {
    Serial.println(rotationName(clawRotation));
  }
  else
  {
    Serial.println(F("MANUAL / uncalibrated (the build returned it to neutral)"));
  }

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

  // Placed but not parked is NOT a success: the block is down, but the
  // rig is somewhere unknown. That is the HELD case, same as an abort.
  if (parked)
  {
    ackStart(F("OK"));
    ackField(F("col"), col);
    ackField(F("row"), row);
    ackField(F("level"), level);
    Serial.println();
  }
  else
  {
    ackReason(F("HELD"), F("block placed but parking failed"));
  }

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
// homing caps, grid maths and the position table, so none of them
// need to care which kind of limit an axis has.
long axisTravelOf(uint8_t axis)
{
  if (axis == AXIS_Z)
  {
    return Z_TRAVEL_STEPS; // calibration, not a cap - see SECTION 6E
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

unsigned long axisSwitchTrips(uint8_t axis)
{
  unsigned long total = 0;
  for (uint8_t i = 0; i < LIMIT_COUNT; i++)
  {
    if (LIMITS[i].axis == axis)
    {
      total += statSwitchTrips[i];
    }
  }
  return total;
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
    // Approaching and still clear - arm the edge detector so the next
    // contact is counted as a fresh trip.
    limitWasActive[idx] = false;
    return false;
  }

  // Count the CONTACT, not the thousand steps spent resting on it.
  if (!limitWasActive[idx])
  {
    limitWasActive[idx] = true;
    statSwitchTrips[idx]++;
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

// One line per switch in the table, so adding a switch adds a line
// here with no extra code. Z prints twice now: Z- and Z+.
void printLimitStatus()
{
  Serial.println();
  Serial.println(F("--- PHYSICAL LIMIT SWITCHES ---"));

  for (uint8_t i = 0; i < LIMIT_COUNT; i++)
  {
    const LimitSwitch &sw = LIMITS[i];

    Serial.print(axisName(sw.axis));
    Serial.print(signName(sw.end));
    Serial.print(F(" (pin "));
    Serial.print(sw.pin);
    Serial.print(F(", "));
    Serial.print(sw.useNC ? "NC" : "NO");
    Serial.print(sw.isHome ? ", HOME/zero" : ", far end");
    Serial.print(F("): "));

    if (!sw.enabled)
      Serial.print(F("DISABLED IN CONFIG"));
    else if (isLimitHitAt((int8_t)i))
      Serial.print(F("*** LIMIT HIT ***"));
    else
      Serial.print(F("clear"));

    Serial.print(F("   "));
    Serial.print(statSwitchTrips[i]);
    Serial.println(F(" trips"));
  }
}

// What the rig last counted between the two Z switches, against what
// SECTION 6E says it should be. This is the calibration feedback the
// top switch made possible - before pin 29 there was nothing at the
// top to measure against.
void printZTravelMeasurement()
{
  if (zTravelMeasured <= 0)
  {
    return;
  }

  long diff = zTravelMeasured - Z_TRAVEL_STEPS;

  Serial.print(F("  Z switch-to-switch: measured "));
  Serial.print(zTravelMeasured);
  Serial.print(F(" steps, configured "));
  Serial.print(Z_TRAVEL_STEPS);
  Serial.print(F("  (diff "));
  if (diff > 0)
  {
    Serial.print(F("+"));
  }
  Serial.print(diff);
  Serial.println(F(")"));

  if (diff != 0)
  {
    Serial.print(F("  -> set Z_TRAVEL_STEPS = "));
    Serial.print(zTravelMeasured);
    Serial.println(F(" in SECTION 6E to match the rig."));
  }
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
    // Z is the deliberate case: its far end is the pin 29 switch, so
    // it is meant to have no software cap at all.
    if (limitEnabledAt(axis, travelEndOf(axis)))
    {
      Serial.print(F("none - hardware switch on pin "));
      Serial.println(LIMITS[findLimitIndex(axis, travelEndOf(axis))].pin);
    }
    else
    {
      Serial.println(F("INFINITE / disabled"));
    }
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
  Serial.println(F("(both ends of Z are real switches - see above)"));
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
  if (clawRotationKnown)
  {
    Serial.print(rotationName(clawRotation));
    if (clawRotation != ROT_NONE)
    {
      Serial.print(F("  <- the next B un-rotates this at the feeder"));
    }
  }
  else
  {
    Serial.print(F("MANUAL / uncalibrated"));
    Serial.print(F("  <- the next B returns it to neutral at the feeder"));
  }
  Serial.println();
}

void printGridConfig()
{
  Serial.println();
  Serial.println(F("--- GRID ---"));

  Serial.print(F("Mode      : "));
  Serial.print(gridModeName(gridMode));
  Serial.print(F("  (block "));
  Serial.print(gridBlockCmOf(AXIS_X), 2);
  Serial.print(F(" X x "));
  Serial.print(gridBlockCmOf(AXIS_Y), 2);
  Serial.print(F(" Y cm)  RR = horizontal, R = vertical"));
  Serial.println();

  Serial.print(F("Software cap: "));
  Serial.print(gridTravelOf(AXIS_X));
  Serial.print(F(" x "));
  Serial.print(gridTravelOf(AXIS_Y));
  Serial.println(F(" steps"));

  Serial.print(F("Holder displacement: "));
  Serial.print(X_TRAVEL_CM, 2);
  Serial.print(F(" x "));
  Serial.print(Y_TRAVEL_CM, 2);
  Serial.println(F(" cm (home -> software cap)"));

  Serial.print(F("Scale    : X "));
  Serial.print(xyStepsPerCmOf(AXIS_X), 4);
  Serial.print(F(" / Y "));
  Serial.print(xyStepsPerCmOf(AXIS_Y), 4);
  Serial.println(F(" steps/cm"));

  Serial.print(F("Block size: "));
  Serial.print(gridBlockCmOf(AXIS_X), 2);
  Serial.print(F(" x "));
  Serial.print(gridBlockCmOf(AXIS_Y), 2);
  Serial.println(F(" cm  (X x Y, this mode)"));

  Serial.print(F("Gap       : "));
  Serial.print(gridGapCmOf(AXIS_X), 2);
  Serial.print(F(" x "));
  Serial.print(gridGapCmOf(AXIS_Y), 2);
  Serial.println(F(" cm  (between neighbouring cells)"));

  Serial.print(F("Pitch     : "));
  Serial.print(gridPitchCmOf(AXIS_X), 2);
  Serial.print(F(" x "));
  Serial.print(gridPitchCmOf(AXIS_Y), 2);
  Serial.println(F(" cm  (block + gap, uniform on both axes)"));

  Serial.print(F("Division : "));
  Serial.print(gridSlotsOf(AXIS_X));
  Serial.print(F(" cols x "));
  Serial.print(gridSlotsOf(AXIS_Y));
  Serial.print(F(" rows  = "));
  Serial.print(gridSlotsOf(AXIS_X) * gridSlotsOf(AXIS_Y) - 1);
  Serial.println(F(" buildable cells (+1 feeder)"));

  Serial.print(F("Coordinates: col 0.."));
  Serial.print(gridColsNow());
  Serial.print(F(" / row 0.."));
  Serial.print(gridRowsNow());
  Serial.println(F("  (0 is a real cell; [0,0] is the feeder)"));

  if (gridColsNow() < GRID_COLS[gridMode] || gridRowsNow() < GRID_ROWS[gridMode])
  {
    Serial.print(F("   (requested col 0.."));
    Serial.print(GRID_COLS[gridMode]);
    Serial.print(F(" / row 0.."));
    Serial.print(GRID_ROWS[gridMode]);
    Serial.println(F(" - clipped by the grid shift; shiftX/shiftY 0 restores it)"));
  }

  Serial.println(F("Feeder cell: [0,0] centre = the home corner (0,0), both modes"));

  Serial.print(F("Block footprint: "));
  Serial.print(gridBlockFootprintCmOf(AXIS_X, gridColsNow()), 2);
  Serial.print(F(" x "));
  Serial.print(gridBlockFootprintCmOf(AXIS_Y, gridRowsNow()), 2);
  Serial.println(F(" cm  (blocks + internal gaps)"));

  Serial.print(F("One grid span: "));
  Serial.print(gridAllocationCmOf(AXIS_X, gridColsNow()), 2);
  Serial.print(F(" x "));
  Serial.print(gridAllocationCmOf(AXIS_Y, gridRowsNow()), 2);
  Serial.println(F(" cm  (gap + blocks, measured from grid origin)"));

  Serial.print(F("Home->far block edge: X "));
  Serial.print(gridBlockEndCmOf(AXIS_X, gridColsNow()), 2);
  Serial.print(F(" cm / Y "));
  Serial.print(gridBlockEndCmOf(AXIS_Y, gridRowsNow()), 2);
  Serial.println(F(" cm  (block may extend past holder-centre travel)"));

  Serial.print(F("First block edge: X "));
  Serial.print(gridBlockStartCmOf(AXIS_X, gridColsNow()), 3);
  Serial.print(F(" cm / Y "));
  Serial.print(gridBlockStartCmOf(AXIS_Y, gridRowsNow()), 3);
  Serial.println(F(" cm from home switches"));

  Serial.print(F("First centre: X "));
  Serial.print(cellCentreCmOf(AXIS_X, 0), 3);
  Serial.print(F(" cm / Y "));
  Serial.print(cellCentreCmOf(AXIS_Y, 0), 3);
  Serial.println(F(" cm  (cell 0, a real block)"));

  Serial.print(F("Last centre : X "));
  Serial.print(cellCentreCmOf(AXIS_X, gridColsNow()), 3);
  Serial.print(F(" cm / Y "));
  Serial.print(cellCentreCmOf(AXIS_Y, gridRowsNow()), 3);
  Serial.println(F(" cm"));

  Serial.print(F("Grid trims : X "));
  Serial.print(GRID_TRIM_X_CM[gridMode], 3);
  Serial.print(F(" cm / Y "));
  Serial.print(GRID_TRIM_Y_CM[gridMode], 3);
  Serial.println(F(" cm  (+ away from home, per mode)"));

  Serial.print(F("Grid shift : X "));
  Serial.print(GRID_SHIFT_X_CM[gridMode], 3);
  Serial.print(F(" cm / Y "));
  Serial.print(GRID_SHIFT_Y_CM[gridMode], 3);
  Serial.println(F(" cm  (shiftX/shiftY; whole lattice, pick-up excluded)"));

  // Per-mode dynamic X/Y skew compensation. Printed here so a flash can be
  // confirmed from the serial console. BUILD motion only - it never touches
  // the grid model above.
  for (uint8_t axis = AXIS_X; axis <= AXIS_Y; axis++)
  {
    const char *name = (axis == AXIS_X) ? "X" : "Y";
    float perCol = (axis == AXIS_X) ? SKEW_X_PER_COL_CM[gridMode]
                                    : SKEW_Y_PER_COL_CM[gridMode];
    float perRow = (axis == AXIS_X) ? SKEW_X_PER_ROW_CM[gridMode]
                                    : SKEW_Y_PER_ROW_CM[gridMode];
    float perColRow = (axis == AXIS_X) ? SKEW_X_PER_COLROW_CM[gridMode]
                                       : SKEW_Y_PER_COLROW_CM[gridMode];
    Serial.print(F("Dynamic skew ["));
    Serial.print(gridModeName(gridMode));
    Serial.print(F("]: "));
    Serial.print(name);
    Serial.print(F(" += "));
    Serial.print(perCol, 3);
    Serial.print(F("*col + "));
    Serial.print(perRow, 3);
    Serial.print(F("*row + "));
    Serial.print(perColRow, 3);
    Serial.println(F("*col*row cm   (BUILD only, + = away from home)"));
    float fixed = (axis == AXIS_X) ? BUILD_PLACEMENT_OFFSET_X_CM[gridMode]
                                   : BUILD_PLACEMENT_OFFSET_Y_CM[gridMode];
    Serial.print(F("Build placement offset ["));
    Serial.print(gridModeName(gridMode));
    Serial.print(F("]: "));
    Serial.print(name);
    Serial.print(F(" += "));
    Serial.print(fixed, 3);
    Serial.println(F(" cm   (BUILD only, + = away from home)"));
    Serial.print(F("             e.g. col "));
    Serial.print(gridColsNow());
    Serial.print(F(" row 0 -> "));
    Serial.print(name);
    Serial.print(F(" += "));
    Serial.print((float)buildSkewSteps(axis, gridColsNow(), 0)
                 / xyStepsPerCmOf(axis), 3);
    Serial.print(F(" cm ("));
    Serial.print(buildSkewSteps(axis, gridColsNow(), 0));
    Serial.println(F(" steps)"));
  }

  Serial.print(F("Edge budget: X "));
  Serial.print(gridMaxEdgeOverhangCmOf(AXIS_X), 3);
  Serial.print(F(" cm / Y "));
  Serial.print(gridMaxEdgeOverhangCmOf(AXIS_Y), 3);
  Serial.println(F(" cm  (how far a block edge may pass the travel cap)"));

  Serial.print(F("Max indices: col 0.."));
  Serial.print(gridCountMaxOf(AXIS_X));
  Serial.print(F(" / row 0.."));
  Serial.print(gridCountMaxOf(AXIS_Y));
  Serial.println(F(" in this mode"));

  Serial.print(F("Pitch steps: ~"));
  Serial.print(gridPitchStepsOf(AXIS_X), 2);
  Serial.print(F(" x "));
  Serial.print(gridPitchStepsOf(AXIS_Y), 2);
  Serial.println(F(" steps (X x Y)"));

  Serial.println(F("col 0 = X switch side, row 0 = Y switch side"));

  Serial.println(F("Tool offsets (holder -> block centre, + away from home):"));
  Serial.print(F("  neutral: X "));
  Serial.print(TOOL_OFFSET_NEUTRAL_X_CM, 3);
  Serial.print(F(" cm / Y "));
  Serial.print(TOOL_OFFSET_NEUTRAL_Y_CM, 3);
  Serial.println(F(" cm"));
  Serial.print(F("  CW (+90): X "));
  Serial.print(TOOL_OFFSET_CW_X_CM, 3);
  Serial.print(F(" cm / Y "));
  Serial.print(TOOL_OFFSET_CW_Y_CM, 3);
  Serial.println(F(" cm"));
  Serial.print(F("  CCW(-90): X "));
  Serial.print(TOOL_OFFSET_CCW_X_CM, 3);
  Serial.print(F(" cm / Y "));
  Serial.print(TOOL_OFFSET_CCW_Y_CM, 3);
  Serial.println(F(" cm"));
}

// Where the machine is in GRID terms - shared by the map and the
// full report, so the two can never disagree.
void printGridPosition()
{
  if (!clawRotationKnown)
  {
    Serial.print(F("Machine pos : X "));
    Serial.print(axisPos[AXIS_X]);
    Serial.print(F("  /  Y "));
    Serial.println(axisPos[AXIS_Y]);
    Serial.println(F("Current cell: UNKNOWN - claw is at an arbitrary manual A angle"));
    Serial.println(F("Last commanded cell: unchanged; run B to return the claw to neutral."));
    return;
  }
  // positionToIndex() now says GRID_INDEX_NONE for itself when the holder is
  // in a gap, so the old "0 really meant nowhere" correction is gone.
  long liveCol = positionToIndex(AXIS_X, axisPos[AXIS_X], clawRotation);
  long liveRow = positionToIndex(AXIS_Y, axisPos[AXIS_Y], clawRotation);

  Serial.print(F("Machine pos : X "));
  Serial.print(axisPos[AXIS_X]);
  Serial.print(F("  /  Y "));
  Serial.println(axisPos[AXIS_Y]);

  Serial.print(F("Current cell: "));
  if (!axisHomed[AXIS_X] || !axisHomed[AXIS_Y])
  {
    Serial.println(F("UNKNOWN - not homed yet (send 0)"));
  }
  else if (liveCol == GRID_INDEX_NONE || liveRow == GRID_INDEX_NONE)
  {
    Serial.println(F("between block footprints / outside the grid"));
  }
  else
  {
    Serial.print(F("["));
    Serial.print(liveCol);
    Serial.print(F(","));
    Serial.print(liveRow);
    Serial.print(F("]"));
    if (cellIsFeeder(liveCol, liveRow))
    {
      Serial.print(F(" FEEDER"));
    }
    Serial.println();
  }

  Serial.print(F("Last commanded cell: "));
  if (curCol != GRID_INDEX_NONE && curRow != GRID_INDEX_NONE)
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
  Serial.print(Z_TRAVEL_STEPS);
  Serial.print(F(" steps  =  "));
  Serial.print(Z_TRAVEL_CM, 2);
  Serial.print(F(" cm  (pin "));
  Serial.print(LIMIT_PIN_Z_BOT);
  Serial.print(F(" -> pin "));
  Serial.print(LIMIT_PIN_Z_TOP);
  Serial.println(F(")"));

  Serial.print(F("Z measured   : "));
  if (zTravelMeasured > 0)
  {
    Serial.print(zTravelMeasured);
    Serial.print(F(" steps between the switches  (diff "));
    if (zTravelMeasured - Z_TRAVEL_STEPS > 0)
    {
      Serial.print(F("+"));
    }
    Serial.print(zTravelMeasured - Z_TRAVEL_STEPS);
    Serial.println(F(")"));
  }
  else
  {
    Serial.println(F("not measured yet - send 0+ to measure it"));
  }

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
    long steps = levelToZSteps(L) * (long)travelEndOf(AXIS_Z);

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

  Serial.println(F("level 0 = the bottom Z switch, not a computed value"));
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

  if (!clawRotationKnown)
  {
    Serial.println();
    Serial.println(F("Map not drawn - claw is at an arbitrary manual A angle."));
    Serial.println(F("Run B to return it to neutral before interpreting cells."));
    Serial.println(F("======================================"));
    return;
  }

  long liveCol = positionToIndex(AXIS_X, axisPos[AXIS_X], clawRotation);
  long liveRow = positionToIndex(AXIS_Y, axisPos[AXIS_Y], clawRotation);
  // No 0-means-nowhere correction needed: positionToIndex() returns
  // GRID_INDEX_NONE itself when the holder is not on a footprint.

  if (gridColsNow() > GRID_MAP_MAX_COLS || gridRowsNow() > GRID_MAP_MAX_ROWS)
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
  Serial.println(F("  # = machine   . = buildable cell   F = feeder"));
  Serial.println(F("  (every cell is a real block; [0,0] is the feeder)"));
  Serial.println();

  for (long r = gridRowsNow(); r >= 0; r--)
  {
    // Right-aligned row label, 3 wide.
    if (r < 100)
      Serial.print(F(" "));
    if (r < 10)
      Serial.print(F(" "));
    Serial.print(r);
    Serial.print(F(" |"));

    for (long c = 0; c <= gridColsNow(); c++)
    {
      if (c == liveCol && r == liveRow && axisHomed[AXIS_X] && axisHomed[AXIS_Y])
      {
        Serial.print(F(" #"));
      }
      else if (cellIsFeeder(c, r))
      {
        Serial.print(F(" F"));
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
  for (long c = 0; c <= gridColsNow(); c++)
  {
    Serial.print(F("--"));
  }
  Serial.println();

  // Column numbers, last digit only (keeps the map aligned).
  Serial.print(F("     "));
  for (long c = 0; c <= gridColsNow(); c++)
  {
    Serial.print(c % 10);
    if (c < gridColsNow())
      Serial.print(F(" "));
  }
  Serial.println();
  Serial.println(F("     ^ [0,0] feeder; every other cell is buildable"));
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
    axisHomed[a] = false;     // a manual zero is NOT a homed origin
    axisRefAtHome[a] = false; // ...and definitely not a switch one
  }
  curCol = GRID_INDEX_NONE;
  curRow = GRID_INDEX_NONE;

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
    long travel = axisTravelOf(a);
    long used = axisPos[a] * (long)travelEndOf(a); // distance from home
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

    if (travel > 0)
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
  Serial.println(F("axis  seeks  failed  switch hits  soft blocks  short moves"));

  for (uint8_t a = 0; a < AXIS_COUNT; a++)
  {
    Serial.print(F("  "));
    Serial.print(axisName(a));
    Serial.print(F("\t "));
    Serial.print(statHomeRuns[a]);
    Serial.print(F("\t "));
    Serial.print(statHomeFails[a]);
    Serial.print(F("\t "));
    Serial.print(axisSwitchTrips(a)); // both Z switches, summed
    Serial.print(F("\t\t "));
    Serial.print(statSoftBlocks[a]);
    Serial.print(F("\t\t "));
    Serial.println(statShortMoves[a]);
  }
  Serial.println(F("(switch hits and soft blocks count ARRIVALS, not steps)"));
  Serial.println(F("(Z seeks include runs to the TOP switch; per-switch hit"));
  Serial.println(F(" counts are in the limit switch section)"));
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
  Serial.print(F("  Quarter turns  : "));
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
    statSoftBlocks[a] = 0;
    statShortMoves[a] = 0;
  }

  for (uint8_t i = 0; i < LIMIT_COUNT; i++)
  {
    statSwitchTrips[i] = 0;
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
  Serial.println(F("0+= FULL RESET: also zero Z and park it on the top switch"));
  Serial.println(F("--------------------------------------"));
  Serial.println(F("D = Z-   (M3 CW )           [limit: pin 28, GROUND]"));
  Serial.println(F("U = Z+   (M3 CCW)           [limit: pin 29, TOP]"));
  Serial.println(F("--------------------------------------"));
  Serial.println(F("O = Servo OPEN              [pin 6]"));
  Serial.println(F("C = Servo CLOSE             [pin 6]"));
  Serial.println(F("V <angle> = Servo angle 0..180 deg [pin 6]"));
  Serial.println(F("A <degrees> = AUX turn -360..360 deg; +CW/-CCW, relative"));
  Serial.println(F("    no aux home sensor: arbitrary A angles block G/R/RR until B"));
  Serial.println(F("--------------------------------------"));
  Serial.println(F("R  = select the VERTICAL grid    [latch only, moves nothing]"));
  Serial.println(F("RR = select the HORIZONTAL grid  [latch only, moves nothing]"));
  Serial.print(F("     now: "));
  Serial.print(gridModeName(gridMode));
  Serial.print(F("  "));
  Serial.print(gridColsNow());
  Serial.print(F(" x "));
  Serial.print(gridRowsNow());
  Serial.println(F("   (needs X/Y homed; refused if already selected)"));
  Serial.println(F("     the claw's real angle is NOT sensed - start it neutral"));
  Serial.println(F("--------------------------------------"));
  Serial.println(F("G <col> <row>   goto cell, e.g.  G 3 5"));
  Serial.println(F("    col/row 0 skips that axis (stays at origin); G 0 0 goes home"));
  Serial.println(F("S <cols> <rows> fixed-pitch count for the ACTIVE grid (requested size)"));
  Serial.println(F("shiftX <cm> / shiftY <cm>  translate the ACTIVE lattice from [0,0]"));
  Serial.println(F("    per mode; + away from home; 0 clears; pick-up is NOT shifted;"));
  Serial.println(F("    a shift past the cap drops the far col/row (0 restores it)"));
  Serial.println(F("--------------------------------------"));
  Serial.println(F("B <col> <row> <level>   BUILD one block"));
  Serial.println(F("    build calibration: col/row 0 skips that axis; B 0 0 is no-op"));
  Serial.println(F("    level 0 = ground, 1 = one block up, 2 = two ..."));
  Serial.println(F("    NO rotation word: the grid mode decides. R / RR select it."));
  Serial.println(F("    e.g.  B 3 5 2     B 4 7 0     B 2 2 3"));
  Serial.println(F("Z               print the Z / build calibration table"));
  Serial.println(F("?               reprint this help"));
  Serial.println(F("(letters and multi-arg commands need a newline / Enter)"));
  Serial.println(F("======================================"));
}

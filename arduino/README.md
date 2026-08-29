# Firmware

## `build_test_v1/` is the sketch on the rig

Flash this one. Everything on the Python side is written against the commands
it accepts and the text it prints back.

```
./scripts/flash.sh            # compile, then upload
./scripts/flash.sh compile    # syntax check only
./scripts/flash.sh boards     # what is actually plugged in
```

The script reads the port, the board FQBN and the sketch path out of
`config/rig.json`, so none of them are written down twice.

Board is an Arduino MEGA 2560. Serial is **9600 baud**. Multi-character
commands need a newline; single digits do not. `V <angle>` sets the gripper
servo to an arbitrary angle from 0 to 180 degrees.

The auxiliary 28BYJ-48 stepper uses these ULN2003 connections:

- IN1 / BLACK -> Mega pin 38
- IN2 / GREEN -> Mega pin 36
- IN3 / BLUE -> Mega pin 39
- IN4 / RED -> Mega pin 37

The build cycle drives it: step 3 returns the claw to neutral before the pick,
step 9 applies the placement rotation, step 14 returns to neutral.

**`R` and `RR` no longer jog it.** They are the grid mode latch — `R` selects
the vertical grid, `RR` the horizontal one — and neither moves anything. See
the next section.

The command list lives in the comment block at the top of the sketch, and the
rig prints it on boot and on `?`.

## X/Y physical grid

The live sketch calibrates motor scale from holder displacement between home
and the active software cap. These are displacement measurements, not arm or
block dimensions:

- X: `24.3 cm = 4750 steps`, so `4750 / 24.3 = 195.4733 steps/cm`
- Y: `40 cm = 8250 steps`, so `8250 / 40 = 206.25 steps/cm`

Firmware derives both ratios; neither is hard-coded. The separately observed
physical build footprint is `24.3 × 43 cm`. The feeder-centre model currently
predicts outer block edges at `25.4 × 43.75 cm`, which needs physical
verification; neither measurement changes the `24.3 × 40 cm` holder span.
Tool offsets remain zero.

A block is `2.2 × 7.5 × 1.5 cm`, and it can be laid either way round. Which
way round decides how many cells fit, so **there are two grids**, each with its
own complete geometry, its own trims and its own calibration:

| mode | block | grid | coordinate map | select with |
| --- | --- | --- | --- | --- |
| vertical | 2.2 X × 7.5 Y cm | `9 × 5` = 45 cells | `10 × 6` | `R` |
| horizontal | 7.5 X × 2.2 Y cm | `3 × 15` = 45 cells | `4 × 16` | `RR` |

The equal cell count is a coincidence. Blocks are separated by `0.5 cm` on both
axes in both modes, and `[0,0]` is the feeder-block centre where the claw picks
up. There is no trailing outer margin inside a grid span:

```text
vertical    X pitch = 2.2 + 0.5 = 2.7 cm;  9 × 2.7 = 24.3 cm
            Y pitch = 7.5 + 0.5 = 8.0 cm;  5 × 8.0 = 40.0 cm
horizontal  X pitch = 7.5 + 0.5 = 8.0 cm;  3 × 8.0 = 24.0 cm
            Y pitch = 2.2 + 0.5 = 2.7 cm; 15 × 2.7 = 40.5 cm

positive footprint  vertical    X: 9 × 2.2 + 8 × 0.5 = 23.8 cm
                                Y: 5 × 7.5 + 4 × 0.5 = 39.5 cm
                    horizontal  X: 3 × 7.5 + 2 × 0.5 = 23.5 cm
                                Y: 15 × 2.2 + 14 × 0.5 = 40.0 cm
```

Vertical begins `1.1 cm` on X (half feeder width) and `3.75 cm` on Y (half
feeder length) from the feeder centre. **Horizontal's trims are `0.0` and
`-0.25`, and must not be copied from vertical's** — at vertical's X trim the
third horizontal column hangs `0.95 cm` off the end of the machine. Each mode
also declares `GRID_MAX_EDGE_OVERHANG_*_CM`, the budget its block *edges* are
checked against; vertical allows half a block, horizontal allows zero.

Horizontal's 15 rows are exactly flush — `15 × 2.2 + 14 × 0.5 = 40.00 cm` into
`40.00 cm` of travel — with no slack at either wall. Measure the real block
width across a stack of 15 before trusting it.

Commands address col `0..cols` and row `0..rows`: `[0,0]` home, `[col,0]`
X-only, and `[0,row]` Y-only. `GRID_TRIM_X_CM[]` and `GRID_TRIM_Y_CM[]` shift
the complete allocation of one mode; after changing one, flash and verify first
and last cells with `G` before using `B`.

**The claw's physical angle is not sensed.** You are trusted to start each
session with it neutral. Nothing in software can detect otherwise.

Command `9` draws the complete convention (`H` home, `+` axis-only, `.` a
positive cell, and `#` the current machine position):

```text
  5 | + . . . . . . . . .
  4 | + . . . . . . . . .
  3 | + . . . . . . . . .
  2 | + . . . . . . . . .
  1 | + . . . . . . . . .
  0 | H + + + + + + + + +
      0 1 2 3 4 5 6 7 8 9
```

For the full grid, cell-centre formulas measured from the feeder/home centre
are:

```text
X centre(col) = 1.1 + 0.5 + 2.2/2 + (col - 1) × 2.7
              = 2.7 + (col - 1) × 2.7

Y centre(row) = 3.75 + 0.5 + 7.5/2 + (row - 1) × 8.0
              = 8.0 + (row - 1) × 8.0
```

Thus first/last centres are X `2.7..24.3 cm` and Y `8.0..40.0 cm`. Final block
edges are X `25.4 cm` and Y `43.75 cm` from the feeder centre; holder caps
apply to placement centres, not to the held block's far edge.
Firmware converts each absolute centre once with `round(cm × steps/cm)`; it
does not accumulate rounded pitch steps from one cell to the next.

## `archive/`

Earlier sketches, kept for reference. **Do not flash these.** They are older
generations of the same rig and several of them disagree with `build_test_v1`
about limit switches, soft limits and Z travel.

| Sketch | What it was |
| --- | --- |
| `build_test_v2` | Newer than v1 — synchronises claw rotation with the Z descent. Frozen out deliberately; v1 is the target. |
| `build_test_v1_soft_z_backup` | v1 from before the Z+ end became a physical switch on pin 29 |
| `position_test_with_always_origin` | X/Y positioning, re-homing every move |
| `position_test_with_servo` | the above plus the gripper servo |
| `position_test_with_z_axis` | the above plus the Z axis |
| `step_counter` | earliest one — step counting only |

## Editing the firmware

There is no local Arduino IDE on the dev machine, so `arduino-cli compile` on
the Pi is the syntax check. A clean compile means it builds — not that it
behaves. Anything touching motion has to be flashed and watched on the rig.

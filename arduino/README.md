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
servo to an arbitrary angle from 0 to 180 degrees. The `O` command checks the
X/Y home switches: when both are active at the feeder it opens to **0 degrees**;
otherwise it opens to the wider **30-degree** position. `C` closes it at
90 degrees.

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
physical build footprint is `24.3 × 43 cm`; it does not change the `24.3 × 40
cm` holder span. The current horizontal-grid CCW tool offset trial is X
`+3.75 cm`, Y `+1.40 cm`; neutral and CW tool offsets remain zero.

A block is `2.2 × 6.0 × 1.5 cm`, and it can be laid either way round. Which
way round decides how many cells fit, so **there are two grids**, each with its
own complete geometry, its own trims and its own calibration:

| mode | block | grid | coordinate map | select with |
| --- | --- | --- | --- | --- |
| vertical | 2.2 X × 6.0 Y cm | `6 × 5` = 30 cells | `7 × 6` | `R` |
| horizontal | 6.0 X × 2.2 Y cm | `2 × 10` = 20 cells | `3 × 11` | `RR` |

Adjacent positive cells are separated by `1.6 cm` along X and `0.8 cm` along Y
in both modes, and `[0,0]` is the feeder-block centre where the claw picks
up. There is no trailing outer margin inside a grid span:

```text
vertical    X pitch = 2.2 + 1.6 = 3.8 cm;  6 × 3.8 = 22.8 cm
            Y pitch = 6.0 + 0.8 = 6.8 cm;  5 × 6.8 = 34.0 cm
horizontal  X pitch = 6.0 + 1.6 = 7.6 cm;  2 × 7.6 = 15.2 cm
            Y pitch = 2.2 + 0.8 = 3.0 cm; 10 × 3.0 = 30.0 cm

positive footprint  vertical    X: 6 × 2.2 + 5 × 1.6 = 21.2 cm
                                Y: 5 × 6.0 + 4 × 0.8 = 33.2 cm
                    horizontal  X: 2 × 6.0 + 1 × 1.6 = 13.6 cm
                                Y: 10 × 2.2 + 9 × 0.8 = 29.2 cm
```

Both `GRID_TRIM_*` ship at `0.0`, so each allocation is centred in travel
until the feeder-centre-to-build-grid offset is re-measured on the rig, per
mode. **Horizontal's trims are still not vertical's and must not be copied** —
a positive X trim there pushes its last column edge off the end of the
machine. Each mode also declares `GRID_MAX_EDGE_OVERHANG_*_CM`, the budget its
block *edges* are checked against; vertical allows half a block (`1.1` / `3.0`),
horizontal allows zero.

At trim `0` neither grid is flush with a wall, so both have slack to absorb
per-block error — but measure a real stack before trusting the last row of
horizontal's 10.

Commands address col `0..cols` and row `0..rows`: `[0,0]` home, `[col,0]`
X-only, and `[0,row]` Y-only. `GRID_TRIM_X_CM[]` and `GRID_TRIM_Y_CM[]` shift
the complete allocation of one mode; after changing one, flash and verify first
and last cells with `G` before using `B`.

**The claw's physical angle is not sensed.** You are trusted to start each
session with it neutral. Nothing in software can detect otherwise.

Command `9` draws the complete convention (`H` home, `+` axis-only, `.` a
positive cell, and `#` the current machine position):

```text
  5 | + . . . . . .
  4 | + . . . . . .
  3 | + . . . . . .
  2 | + . . . . . .
  1 | + . . . . . .
  0 | H + + + + + +
      0 1 2 3 4 5 6
```

For the vertical grid at trim `0`, cell-centre formulas measured from the
feeder/home centre are:

```text
X centre(col) = 0.75 + 1.6 + 2.2/2 + (col - 1) × 3.8
              = 3.45 + (col - 1) × 3.8

Y centre(row) = 3.0 + 0.8 + 6.0/2 + (row - 1) × 6.8
              = 6.8 + (row - 1) × 6.8
```

Thus first/last centres are X `3.45..22.45 cm` and Y `6.8..34.0 cm`. Final block
edges are X `23.55 cm` and Y `37.0 cm` from the feeder centre; holder caps
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

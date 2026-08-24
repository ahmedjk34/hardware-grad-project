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
commands need a newline; single digits do not.

The auxiliary 28BYJ-48 stepper uses these ULN2003 connections:

- IN1 / BLACK -> Mega pin 38
- IN2 / GREEN -> Mega pin 36
- IN3 / BLUE -> Mega pin 39
- IN4 / RED -> Mega pin 37

`R` and `RR` rotate it about 90° clockwise and counter-clockwise respectively.

The command list lives in the comment block at the top of the sketch, and the
rig prints it on boot and on `?`.

## X/Y physical grid

The live sketch calibrates motor scale from holder displacement between home
and the active software cap. These are displacement measurements, not arm or
block dimensions:

- X: `24.3 cm = 4750 steps`, so `4750 / 24.3 = 195.4733 steps/cm`
- Y: `40 cm = 8275 steps`, so `8275 / 40 = 206.875 steps/cm`

Firmware derives both ratios; neither is hard-coded. The separately observed
physical build displacement is `24.3 × 43 cm`, but the extra 3 cm on Y belongs
to the unmodelled arm-holder relationship. Tool offsets remain zero, so the
controlled grid deliberately uses the trustworthy `24.3 × 40 cm` holder span.

One unrotated block is `2.2 cm` X × `7.5 cm` Y × `1.5 cm` Z. Blocks are
separated by `0.5 cm` on both axes. The first gap is between coordinate 0/home
and cell 1; there is no trailing outer margin:

```text
X pitch = 2.2 + 0.5 = 2.7 cm; 9 × 2.7 = 24.3 cm
Y pitch = 7.5 + 0.5 = 8.0 cm; 5 × 8.0 = 40.0 cm

positive footprint =
  X: 9 × 2.2 + 8 × 0.5 = 23.8 cm
  Y: 5 × 7.5 + 4 × 0.5 = 39.5 cm
```

The normal grid is `9 × 5 = 45` positive cells. Commands address col `0..9`
and row `0..5`, so the complete coordinate map is `10 × 6`: `[0,0]` home,
`[col,0]` X-only, and `[0,row]` Y-only. `GRID_TRIM_X_CM` and
`GRID_TRIM_Y_CM` shift the complete allocation; after changing one, flash and
verify first and last cells with `G` before using `B`.

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

For the full grid, cell-centre formulas measured from home are:

```text
X centre(col) = 0.5 + 2.2/2 + (col - 1) × 2.7
              = 1.6 + (col - 1) × 2.7

Y centre(row) = 0.5 + 7.5/2 + (row - 1) × 8.0
              = 4.25 + (row - 1) × 8.0
```

Thus first/last centres are X `1.6..23.2 cm` and Y `4.25..36.25 cm`.
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

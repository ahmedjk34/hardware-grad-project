# Firmware

## Container + belt controller

Flash `belt_v1/belt_v1.ino` to an **Arduino Uno** for the feeder. Its wiring is:

- A4988 belt driver: `DIR = 2`, `STEP = 3`
- A4988 `ENABLE` is not used; connect it to GND
- Exit HC-SR04: `TRIG = 4`, `ECHO = 5`
- Alignment-servo signal: pin `6`
- Pickup/stage IR obstacle sensor: `OUT = 8` (default active-low)
- Container-servo signal: pin `12`

`FEED [id]` (or its `RUN [id]` alias) performs one complete feeder cycle:
close the container to 20°, open it in stages (90° then 160°), wait for the
exit sensor to see a block below 10 cm, run the belt, and stop it only when the
stage IR sensor sees the block. The alignment servo then nudges the block square
and the stage sensor verifies that it remained present.

Every controller command must end in a newline. A feed cycle is identified by
the optional numeric `id` and reports structured telemetry:

```text
@42 RECV cmd=FEED
@42 ACK cmd=FEED accepted=1
@42 STATE state=waiting_for_exit
@42 EVENT phase=waiting_for_exit
@42 STATE state=moving_to_stage
@42 SENSOR sensor=exit distance_cm=7.4 detected=1
@42 EVENT phase=exit_detected_container_closed_belt_running distance_cm=7.4
@42 SENSOR sensor=stage detected=1
@42 EVENT phase=stage_detected_aligning
@42 EVENT phase=block_ready
@42 OK state=block_ready result=staged
```

`@id OK state=block_ready result=staged` is the successful terminal response and means the
Mega may pick from `[0,0]`. `ACK`, `STATE`, `SENSOR`, and `EVENT` are progress
telemetry; `OK` or `ERROR` is terminal. A terminal `@id ERROR
state=... reason=stage_occupied`, `exit_timeout`, `stage_timeout`, or
`cancelled` means it must not. The Uno prints
`@0 READY firmware=belt_v1 protocol=2 board=uno` at boot. See
[the full feeder-controller protocol](../docs/feeder-controller.md) for every
message type and controller recovery rule.

Use `STOP` to cancel a cycle safely. Manual commands are `STATUS` (or `P`),
`OPEN`, `CLOSE`, `ON`, `OFF`, `F`, `B`, `S <speed>`, `US`, and `HELP`. The
default belt speed is 325 steps per second. `US`/`STATUS` read the exit distance
and report the stage IR sensor as `detected` or `clear`.
If the belt turns the wrong physical direction, swap the forward and reverse
direction-level constants in the sketch.

## `build_test_v1/` is the sketch on the rig

Flash this one. Everything on the Python side is written against the commands
it accepts and the text it prints back.

`build_vertical_grid/` and `build_horizontal_grid/` are supervised standalone
level-0 grid-fill sketches. They carry the same gripper, Z-margin, and build
rotation settings as `build_test_v1/`: close **54°**, fixed placement margin
**+0.12 cm**, and a horizontal build turn of **90° CW**.

```
./scripts/flash.sh                    # Mega: compile, then upload
./scripts/flash.sh compile            # Mega syntax check (back-compatible)
./scripts/flash.sh feeder compile     # Uno syntax check
./scripts/flash.sh feeder upload      # Uno upload using feeder.port
./scripts/flash.sh all compile        # syntax-check both production sketches
./scripts/flash.sh boards             # what is actually plugged in
```

The script reads each role's port, FQBN and sketch path from `config/rig.json`,
so none of them are written down twice.

Board is an Arduino MEGA 2560. Serial is **9600 baud**. Multi-character
commands need a newline; single digits do not. `V <angle>` sets the gripper
servo to an arbitrary angle from 0 to 180 degrees. The `O` command checks the
X/Y home switches and opens to **0 degrees**. `C` closes it at
54 degrees.

The firmware keeps the physical block height at **1.5 cm**. Its fixed Z
placement margin is **+0.12 cm**, raising releases at levels 1 and above by
1.2 mm so the claw does not press a block into the stack; level 0 still seats on
the physical ground switch.

The auxiliary 28BYJ-48 stepper uses these ULN2003 connections:

- IN1 / BLACK -> Mega pin 38
- IN2 / GREEN -> Mega pin 36
- IN3 / BLUE -> Mega pin 39
- IN4 / RED -> Mega pin 37

The build cycle drives it: step 3 returns the claw to neutral before the pick,
step 9 applies the placement rotation, step 14 returns to neutral.

### The build talks while it moves

`B` is about forty seconds during which the sketch never reads serial. It is
not silent, though: `buildStep()` prints one machine line per phase, before
that phase runs, beside the `[BUILD n/14]` text a human reads.

```
@12 RECV cmd=B col=3 row=5 level=0
@12 STEP step=8 total=14 phase=move_to_target action=move text=Move_XY_to_the_target_cell status=begin
[BUILD 8/14] Move X/Y to the target cell
...
@12 STEP step=11 total=14 phase=release action=release text=Open_the_claw_and_release status=done
@12 OK col=3 row=5 level=0
```

Fourteen lines, not one per motor step — at 9600 baud that is about 0.3 s of
airtime inside the build, where per-step telemetry would be minutes of it and
would starve the terminal ack. `status=done` appears exactly once, at phase 11,
and means the block has left the claw; it does **not** mean the build finished.
Only the terminal `@n OK` does. `docs/ack-protocol.md` has the full field list
and the fourteen phase identifiers.

**`R` and `RR` no longer jog it.** They are the grid mode latch — `R` selects
the vertical grid, `RR` the horizontal one — and neither moves anything. See
the next section.

The command list lives in the comment block at the top of the sketch, and the
rig prints it on boot and on `?`.

## X/Y physical grid

The live sketch calibrates motor scale from holder displacement between home
and the active software cap. These are displacement measurements, not arm or
block dimensions:

- X: `22.8 cm = 4550 steps`, so `4550 / 22.8 = 199.56 steps/cm`
- Y: `38.0 cm = 7600 steps`, so `7600 / 38.0 = 200.0 steps/cm`

Firmware derives both ratios; neither is hard-coded. The separately observed
physical build footprint is `24.3 × 43 cm`; it does not change the `22.8 × 38.0
cm` holder span. The horizontal build turns 90° CW and uses the measured
`(+0.9, -0.3) cm` CW tool offset. Neutral and CCW remain zero; CCW is not a
build orientation and must remain uncalibrated until physically measured.

A block is `2.2 × 6.0 × 1.5 cm`, and it can be laid either way round. Which
way round decides how many cells fit, so **there are two grids**, each with its
own complete geometry, its own trims and its own calibration:

| mode | block | grid | coordinate map | select with |
| --- | --- | --- | --- | --- |
| vertical | 2.2 X × 6.0 Y cm | `6 × 5` = 30 cells | `7 × 6` | `R` |
| horizontal | 6.0 X × 2.2 Y cm | `2 × 9` = 18 cells | `3 × 10` | `RR` |

Adjacent cells are separated by a uniform `1.6 cm` gap on both axes in both
modes, and `[0,0]` is the feeder-block centre where the claw picks up. The
lattice is centre-anchored:

```text
pitch     = block + gap
centre(i) = trim + error_offset + shift + i * pitch

vertical    centres: X 0.00 → 22.80 cm; Y 0.00 → 38.00 cm
horizontal  centres: X 1.90 → 17.10 cm; Y 1.90 → 36.10 cm
```

Vertical's `GRID_TRIM_*` ship at `0.0` on both axes. Horizontal ships at
`GRID_TRIM_X_CM = GRID_TRIM_Y_CM = +1.9 cm` — the pickup-cell registration: the
block is picked up standing at the vertical `[0,0]` feeder and rotated about the
grip, and the rotated 6.0 cm face overhangs the 2.2 cm vertical footprint by
`6.0/2 − 2.2/2 = 1.9 cm` per side. **Horizontal's trims are still not
vertical's and must not be copied.** Each mode also declares
`GRID_MAX_EDGE_OVERHANG_*_CM`, the budget its block *edges* are checked against;
vertical allows half a block (`1.1` / `3.0`), horizontal allows `3.0` / `1.1`
(the +1.9 cm registration's `−1.1 cm` X near edge sits inside it).

Vertical sits exactly on its cap. Horizontal keeps far-end slack after the
registration — but measure a real stack before trusting its last row.

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

Cell zero is a real centre on the home corner, so its block extends half a
block behind the switches. The per-mode edge-overhang budgets make that legal
without weakening the holder-motion cap. Firmware converts each absolute
centre once with `round(cm × steps/cm)`; it does not accumulate rounded pitch
steps from one cell to the next.

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

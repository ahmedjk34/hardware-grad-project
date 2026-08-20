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

The auxiliary 28BYJ-48 stepper uses the four ULN2003 inputs on pins 36–39
(GREEN, RED, YELLOW, BLUE in IN1–IN4 order). `R` and `RR` rotate it about 90°
clockwise and counter-clockwise respectively.

The command list lives in the comment block at the top of the sketch, and the
rig prints it on boot and on `?`.

## X/Y physical grid

The live sketch maps the tape-measured `34 cm × 40 cm` X/Y envelope to its
`5050 × 7500` step limits at runtime:

- X: `5050 / 34 = 148.5294 steps/cm`
- Y: `7500 / 40 = 187.5 steps/cm`

The supported block orientation is `1.5 cm` along X and `7.5 cm` along Y. A
`22 × 5` grid fits: its `33 × 37.5 cm` footprint is centred, leaving `0.5 cm`
at each X edge and `1.25 cm` at each Y edge. `GRID_TRIM_X_CM` and
`GRID_TRIM_Y_CM` are signed calibration corrections for shifting that complete
footprint; positive is away from the relevant home switch. After changing a
trim, flash and verify corner cells with `G` before using `B`.

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

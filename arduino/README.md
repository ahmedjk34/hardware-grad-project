# Firmware

## `build_test_v1/` is the sketch on the rig

Flash this one. Everything on the Python side is written against the commands
it accepts and the text it prints back.

```
arduino-cli compile --fqbn arduino:avr:mega:cpu=atmega2560 arduino/build_test_v1
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:mega:cpu=atmega2560 arduino/build_test_v1
```

Board is an Arduino MEGA 2560. Serial is **9600 baud**. Multi-character
commands need a newline; single digits do not.

The command list lives in the comment block at the top of the sketch, and the
rig prints it on boot and on `?`.

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

# Uno feeder controller

`arduino/belt_v1/belt_v1.ino` is the firmware for the feeder half of the rig.
It runs on an Arduino Uno and turns a hopper/container, a belt and a small
alignment mechanism into one controlled operation: present **one** block at the
gantry pickup point, then explicitly report whether that succeeded.

The feeder is intentionally separate from the Mega gantry controller. The Uno
only owns the path from the hopper to the fixed pickup location; it never moves
the gantry or decides where a block is placed. The Mega treats its `[0,0]` cell
as the feeder/pickup position. The Pi will eventually coordinate the two, but
that Pi ↔ Uno ↔ Mega integration is not implemented yet.

## What it does

One `FEED` request runs this sequence:

1. Stop the belt, return the alignment arm to rest, and close the container.
2. Refuse the request if the stage sensor already sees a block. This prevents
   a second block from being fed into an occupied pickup point.
3. Wait 500 ms for the container to settle.
4. Open the container in two deliberate stages: 20° closed → 90° → 160°,
   waiting 500 ms at each opening stage. This is intended to queue and release
   blocks more gently than one large movement.
5. Wait up to 10 seconds for the **exit sensor** to see a block leave the
   container and enter the belt.
6. Close the container immediately after that confirmation, then run the belt
   counter-clockwise.
7. Wait up to 15 seconds for the **stage sensor** at the pickup point to see
   the block. Detection stops the belt.
8. Move the alignment servo briefly to nudge the block square, return it to
   rest after 350 ms, and read the stage sensor again.
9. Emit `@id OK state=block_ready` only if the block is still at the stage.
   The controller may now instruct the Mega to pick up from `[0,0]`.

This is sensor-stopped staging, not a fixed belt-duration guess. The exit and
stage observations also distinguish an empty/blocked hopper path from a block
that did not arrive at the pickup point.

## Hardware and wiring

| Part | Uno pins | Notes |
| --- | --- | --- |
| A4988 belt driver | `DIR 2`, `STEP 3` | Tie `ENABLE` low if it is not controlled separately. |
| Exit HC-SR04 | `TRIG 4`, `ECHO 5` | Confirms that a block left the container. |
| Alignment servo | `6` | Rests at 90° and nudges to 120°; tune mechanically. |
| Stage HC-SR04 | `TRIG 8`, `ECHO 9` | Confirms that the pickup position contains a block. |
| Container servo | `12` | Closed 20°, first opening 90°, final opening 160°. |

The sketch uses 9600 baud. All serial commands must end with a newline.

Servos and the A4988 should use power supplies sized for their load; do not
assume the Uno's 5 V pin can power them. The Uno, motor driver, servo supply,
sensors and Pi serial adapter must share a common ground. Verify the belt
direction while unloaded: `BELT_CCW_DIRECTION_LEVEL` is the one firmware
constant intended to be inverted if the installed belt moves physically the
wrong way.

## Serial protocol

The useful controller command is:

```text
FEED <id>\n
```

`RUN <id>` is an alias. `id` is an optional non-negative numeric request ID.
Supplying one lets a controller associate every event and terminal response
with its request. Without one, the firmware allocates the next ID itself.

At boot the Uno prints:

```text
@0 READY firmware=belt_v1 protocol=1 board=uno
```

For `FEED 42`, a normal transaction is:

```text
@42 RECV cmd=FEED
@42 EVENT phase=container_closing
@42 EVENT phase=container_opening_stage_1
@42 EVENT phase=container_opening_stage_2
@42 EVENT phase=waiting_for_exit
@42 EVENT phase=exit_detected_container_closed_belt_running distance_cm=7.4
@42 EVENT phase=stage_detected_aligning distance_cm=8.2
@42 EVENT phase=verifying_stage
@42 EVENT phase=block_ready distance_cm=8.1
@42 OK state=block_ready
```

Only the final `OK` is permission to pick the block up. Events are progress
telemetry, not a success result. A controller should wait for exactly one
terminal line for its active request and should not send the Mega a build/pick
command after an error.

### Terminal failures

| Response | Meaning | Safe controller response |
| --- | --- | --- |
| `@id ERROR reason=stage_occupied` | A block was already at the pickup point before release started. | Do not feed another block. Inspect, pick the staged block, or clear the area. |
| `@id ERROR reason=exit_timeout` | No block was seen leaving the container within 10 seconds. | Check hopper supply, container movement and exit-sensor alignment. |
| `@id ERROR reason=stage_timeout` | A released block did not reach the pickup sensor within 15 seconds. | Stop/inspect for a belt jam, wrong direction or sensor placement. |
| `@id ERROR reason=cancelled` | A running feed was cancelled with `STOP`, or superseded by another `FEED`. | Treat the pickup point as unknown and inspect before retrying. |

An `ERROR unknown_command=...` or `ERROR command_too_long` is a command parser
error and is not a feed transaction result.

### Other commands

| Command | Effect |
| --- | --- |
| `STOP` / `OFF` / `X` | Stop the belt and cancel an active feed cycle. |
| `STATUS` / `P` | Print state, belt/container status and fresh readings from both sensors. |
| `US` | Same sensor/status snapshot as `STATUS`. |
| `OPEN` / `O` | Test-only manual two-stage container opening. It cancels an active cycle. |
| `CLOSE` / `C` | Close the container and stop the belt. |
| `ON` | Run belt in configured CCW direction without a sensor-controlled cycle. |
| `F` | Run belt forward for bench testing. |
| `B`, `R`, `REVERSE` | Run belt in configured backward/CCW direction for bench testing. |
| `S <steps/s>` | Set belt rate; constrained to 10–3000 steps/s. Default: 150. |
| `HELP`, `H`, `?` | Print the command summary. |

Manual motion commands are for commissioning only. They cancel a live feed
request, so an automated controller must not mix them into a production cycle.

## State model and timing

The firmware uses a state machine rather than a multi-second `delay()` belt
run. It continues accepting serial input while a cycle is active, so `STOP` is
available during an exit wait, belt movement, or alignment. HC-SR04 reads use a
30 ms echo timeout, therefore a sensor read can briefly delay belt pulse
generation; this is acceptable for feeder staging but is not precision motion
control.

| State | Belt | Exit sensor | Stage sensor | Exit condition |
| --- | --- | --- | --- | --- |
| `closing` | stopped | — | — | 500 ms elapsed |
| `opening_stage_1` | stopped | — | — | 500 ms elapsed |
| `opening_stage_2` | stopped | — | — | 500 ms elapsed |
| `waiting_for_exit` | stopped | sampled every 100 ms | — | block detected or 10 s timeout |
| `moving_to_stage` | running CCW | — | sampled every 100 ms | block detected or 15 s timeout |
| `aligning` | stopped | — | — | 350 ms elapsed |
| `verifying_stage` | stopped | — | read once after settling | block ready or resume belt |
| `block_ready` | stopped | — | — | terminal success |

A sensor detects an object when it returns a valid distance below `10.0 cm`.
No echo is treated as no detection. The values are installation calibrations:
adjust `DETECT_DISTANCE_CM`, the three servo-angle groups, belt rate, and
timeouts only after testing with the actual hopper and pickup fixture.

## Controller integration contract

The eventual Pi-side orchestrator should use the Uno as a transaction partner:

```text
Pi                    Uno                         Mega
 |--- FEED 42 -------->|                           |
 |<-- @42 EVENT ... ---|                           |
 |<-- @42 OK ----------|                           |
 |-------------------------------- B col row z --->|
 |<-------------------------------- build result --|
```

Important rules:

- Send only one `FEED` at a time and retain its ID until a terminal response.
- Do not infer success from elapsed time, a container-open event, or a belt
  event. Only `OK state=block_ready` proves the feeder sequence completed.
- On any Uno error, do not issue the Mega pick/build command. Surface the
  reason to the operator and require a safe inspection/recovery decision.
- A Mega build removes the staged block. Do not request the next `FEED` until
  that pick/build has safely progressed and the physical pickup area is clear.
- A fresh serial connection resets an Uno. Wait for its `READY` line, then
  treat any previous in-flight request as unknown.

The current Python serial link communicates only with the Mega. Adding an Uno
link should preserve the existing Mega acknowledgement protocol rather than
trying to combine two devices on one serial port.

## Commissioning checklist

1. With power off, verify every connection in the wiring table and a shared
   ground. Keep the A4988 motor supply and servo power appropriate to the
   hardware.
2. Compile for the Uno and upload the sketch. A direct command is:

   ```bash
   arduino-cli compile --fqbn arduino:avr:uno arduino/belt_v1
   ```

3. Open a 9600-baud serial monitor and confirm the `READY` line.
4. Run `STATUS`; with clear sensors it should report distances/no echo rather
   than a false nearby block. Position a block at each sensor separately and
   confirm its reading crosses the 10 cm threshold only where intended.
5. With the belt unloaded, use `F`, `B`, `ON`, and `OFF` to verify direction
   and stop behaviour. If CCW is physically wrong, invert
   `BELT_CCW_DIRECTION_LEVEL`, recompile and reflash.
6. Use `OPEN` and `CLOSE` to confirm container travel. Adjust only the named
   container angles after checking for mechanical interference.
7. Run `FEED 1` with one block. Confirm the exit event, automatic container
   closure, belt stop at the pickup point, alignment movement, and final `OK`.
8. Test every failure deliberately: start with the stage occupied, leave the
   hopper empty, and obstruct the belt. Confirm the relevant terminal error
   and that the belt is stopped.

Do not connect this feeder to automatic gantry builds until those physical
tests have passed repeatedly. Firmware success means the sensors agree with
the configured geometry; it cannot by itself prove that the claw can safely
grip the staged block.

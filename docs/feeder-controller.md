# Uno feeder controller

`arduino/belt_v1/belt_v1.ino` is the firmware for the feeder half of the rig.
It runs on an Arduino Uno and turns a hopper/container, a belt and a small
alignment mechanism into one controlled operation: present **one** block at the
gantry pickup point, then explicitly report whether that succeeded.

The feeder is intentionally separate from the Mega gantry controller. The Uno
only owns the path from the hopper to the fixed pickup location; it never moves
the gantry or decides where a block is placed. The Mega treats its `[0,0]` cell
as the feeder/pickup position. The Pi coordinates both boards over two
independent USB serial ports; the boards never talk directly to one another.

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
9. Emit `@id OK state=block_ready result=staged` only if the block is still at the stage.
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

Protocol 2 is line-oriented ASCII at 9600 baud. Every command and every
response is one newline-terminated line. Responses are deliberately formatted
as space-separated `key=value` fields so a controller can parse them without
depending on prose intended for a human serial monitor.

The main controller command is:

```text
FEED <id>\n
```

`RUN <id>` is an alias. `id` should be a positive numeric request ID chosen by
the controller. It labels every asynchronous response from that feed cycle.
If omitted, the Uno allocates its next ID. An explicit `0` is invalid. `@0` is reserved for
device-level boot, status, configuration and manual-command messages; it is
never a feed transaction ID.

Every protocol response has this envelope:

```text
@<id> <TYPE> key=value key=value ...
```

| Type | Scope | Meaning |
| --- | --- | --- |
| `READY` | `@0` | Boot/reset announcement. Discards any controller assumption about an earlier in-flight request. |
| `RECV` | `@id` | The Uno received a `FEED` line and assigned it this transaction ID. |
| `ACK` | `@id` or `@0` | A command was accepted. For a feed, `accepted=1` means the stage was empty and the cycle has started. |
| `STATE` | `@id` | A feed-state transition. It is the authoritative current state. |
| `SENSOR` | `@id` or `@0` | A named HC-SR04 observation. `detected=1` means the value is below the configured threshold. |
| `EVENT` | `@id` | A meaningful physical milestone within the current state. |
| `STATUS` | `@0` | A requested snapshot of state, active flag, belt, container and speed. It is followed by two `SENSOR` lines. |
| `CONFIG` | `@0` | A manual setting change, currently the belt speed. |
| `OK` | `@id` | Successful terminal result. No more lines for that feed request are expected. |
| `ERROR` | `@id` or `@0` | Terminal feed failure or a malformed/manual command failure. |

At boot the Uno prints:

```text
@0 READY firmware=belt_v1 protocol=2 board=uno
```

For `FEED 42`, a normal transaction is:

```text
@42 RECV cmd=FEED
@42 SENSOR sensor=stage distance_cm=32.6 detected=0
@42 ACK cmd=FEED accepted=1
@42 STATE state=closing
@42 EVENT phase=container_closing
@42 STATE state=opening_stage_1
@42 EVENT phase=container_opening_stage_1
@42 STATE state=opening_stage_2
@42 EVENT phase=container_opening_stage_2
@42 STATE state=waiting_for_exit
@42 EVENT phase=waiting_for_exit
@42 STATE state=moving_to_stage
@42 SENSOR sensor=exit distance_cm=7.4 detected=1
@42 EVENT phase=exit_detected_container_closed_belt_running distance_cm=7.4
@42 STATE state=aligning
@42 SENSOR sensor=stage distance_cm=8.2 detected=1
@42 EVENT phase=stage_detected_aligning distance_cm=8.2
@42 STATE state=verifying_stage
@42 EVENT phase=verifying_stage
@42 STATE state=block_ready
@42 EVENT phase=block_ready distance_cm=8.1
@42 OK state=block_ready result=staged
```

Only the final `OK` is permission to pick the block up. `ACK`, `STATE`,
`SENSOR`, and `EVENT` lines are progress telemetry, not success results. A
controller should wait for exactly one `OK` or `ERROR` for its active request
and should not send the Mega a build/pick command after an error.

`SENSOR` values are reported in centimetres, rounded to one decimal place.
`distance_cm=no_echo` means the HC-SR04 received no echo before its 30 ms
firmware timeout; it is never treated as a detected block. The detection rule
is `distance_cm < 10.0` and is represented explicitly by `detected=0` or `1`.
The firmware reports sensor readings at cycle admission and on detections;
it does not flood the serial port with its 100 ms polling reads.

### Status and manual acknowledgement

`STATUS` (or `P`) creates a complete device snapshot, regardless of whether a
feed request is running:

```text
@0 STATUS state=moving_to_stage active=1 belt=running container=closed speed_steps_s=150
@0 SENSOR sensor=exit distance_cm=21.7 detected=0
@0 SENSOR sensor=stage distance_cm=14.3 detected=0
```

Manual operations also acknowledge their completion on the device channel.
For example, `S 500` returns `@0 CONFIG speed_steps_s=500` followed by
`@0 ACK cmd=S`; `STOP` returns `@0 ACK cmd=STOP`. If `STOP` cancelled a live
feed, its transaction first receives `STATE state=idle`, an `EVENT` describing
the cancellation, and terminal `ERROR state=idle reason=cancelled`.

### Terminal failures

| Response | Meaning | Safe controller response |
| --- | --- | --- |
| `@id ERROR state=fault reason=stage_occupied` | A block was already at the pickup point before release started. | Do not feed another block. Inspect, pick the staged block, or clear the area. |
| `@id ERROR state=fault reason=exit_timeout` | No block was seen leaving the container within 10 seconds. | Check hopper supply, container movement and exit-sensor alignment. |
| `@id ERROR state=fault reason=stage_timeout` | A released block did not reach the pickup sensor within 15 seconds. | Stop/inspect for a belt jam, wrong direction or sensor placement. |
| `@id ERROR state=idle reason=cancelled` | A running feed was cancelled with `STOP`. | Treat the pickup point as unknown and inspect before retrying. |
| `@id ERROR state=... reason=busy` | A second `FEED` arrived while one transaction still owned the stage. The original continues. | Fix the caller; wait for the original terminal result and never queue feeds. |

`@0 ERROR reason=unknown_command command=...` and `@0 ERROR
reason=command_too_long` or `reason=invalid_request_id` are command parser failures, not feed transaction
results. A controller should reject malformed input locally before sending it.

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

## Pi orchestration contract

`python/rig/feeder.py` owns the Uno port and validates the exact protocol-2
`READY` identity before use. `python/rig/link.py` independently owns the Mega
port. `python/rig/orchestrator.py` is the only production handoff between them:

```text
Pi                    Uno                         Mega
 |--- FEED 42 -------->|                           |
 |<-- @42 EVENT ... ---|                           |
 |<-- @42 OK state=block_ready result=staged       |
 |-------------------------------- B col row z --->|
 |<-------------------------- terminal PLACED -----|
```

Important rules:

- Send only one `FEED` at a time and retain its ID until a terminal response.
- Do not infer success from elapsed time, a container-open event, or a belt
  event. Only matching `OK state=block_ready result=staged` proves the feeder
  sequence completed.
- On any Uno error, do not issue the Mega pick/build command. Surface the
  reason to the operator and require a safe inspection/recovery decision.
- A Mega build removes the staged block. Do not request the next `FEED` until
  that exact `B` returns terminal `PLACED`. A Mega rejection is safe for the
  gantry but not for the whole cell: a block was already staged, so the
  controller locks for inspection rather than feeding another.
- A fresh serial connection resets an Uno. Wait for its `READY` line, then
  treat any previous in-flight request as unknown.
- A timeout, disconnect, reset, malformed success, or cancellation has an
  unknown physical outcome. It never authorizes `B` and is never auto-retried;
  on a host timeout the client makes a best-effort `STOP` without treating
  delivery as proof of recovery.
- Operator stop while feeding sends Uno `STOP`. Once Mega placement starts,
  software stop remains stop-after-current because the Mega cannot read serial
  inside `buildBlock()`.

The FastAPI lifespan owns both clients exactly once. `BuildController` and
`BuildJob` remain the outer one-operation guard used by click-to-build and the
Studio runner. Direct Mega paths remain only for deliberate calibration and
commissioning where a person is responsible for staging.

## Commissioning checklist

1. With power off, verify every connection in the wiring table and a shared
   ground. Keep the A4988 motor supply and servo power appropriate to the
   hardware.
2. Discover both boards with `./scripts/flash.sh boards`. Put their stable
   `/dev/serial/by-id/...` paths in `serial.port` and `feeder.port` in
   `config/rig.json`; never rely on `/dev/ttyACM0`/`1` ordering.
3. Compile and upload the Uno using that same config:

   ```bash
   ./scripts/flash.sh feeder compile
   ./scripts/flash.sh feeder upload
   ```

4. Stop the web service, then run
   `.venv/bin/python python/feeder_console.py status` and confirm the validated
   `READY` identity and structured status.
5. With clear sensors, `status` should report distances/no echo rather
   than a false nearby block. Position a block at each sensor separately and
   confirm its reading crosses the 10 cm threshold only where intended.
6. With the belt unloaded, use the CLI's `on`, `off`, and manual controls to verify direction
   and stop behaviour. If CCW is physically wrong, invert
   `BELT_CCW_DIRECTION_LEVEL`, recompile and reflash.
7. Use `open` and `close` to confirm container travel. Adjust only the named
   container angles after checking for mechanical interference.
8. Run `.venv/bin/python python/feeder_console.py feed` with one block. Confirm the exit event, automatic container
   closure, belt stop at the pickup point, alignment movement, and final `OK`.
9. Test every failure deliberately: start with the stage occupied, leave the
   hopper empty, and obstruct the belt. Confirm the relevant terminal error
   and that the belt is stopped.
10. Only after both boards pass commissioning, start the web service and run a
    one-block build while watching `[UNO/FEEDER ...]` then
    `[MEGA/GANTRY ...]` in the operator log. Repeat for a multi-block Studio
    run and confirm no next `FEED` appears before the prior Mega terminal.

The software path is integrated, but do not operate automatic gantry builds
until these physical tests have passed repeatedly. Firmware success means the
sensors agree with the configured geometry; it cannot by itself prove that the
claw can safely grip the staged block.

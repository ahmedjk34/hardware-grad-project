# Raspberry Pi ↔ Arduino Mega communication audit

Repository state inspected: 2026-09-04. This report describes the checked-in
implementation, not generic Arduino serial behavior and not an assumed deployed
state. In particular, the repository itself says that the structured `@` ACK
firmware is compile-verified but has **never been flashed** (`docs/ack-protocol.md:3-7`).

This is a deep audit of the Pi ↔ Mega link only. For the end-to-end pipeline
across both boards, see **[communication-pipeline.md](communication-pipeline.md)**;
for the Uno half, **[feeder-controller.md](feeder-controller.md)**.

## Executive findings

The production path is USB-A on the Raspberry Pi to the Mega's primary USB-B
connector, exposed to Linux by the configured stable udev link
`/dev/serial/by-id/usb-www.Arduino.cc_Arduino_14011-if00`, at **9600 8N1** (the
8N1 defaults come from pyserial because the code does not override them). The
Pi writes UTF-8/ASCII-compatible, newline-terminated command lines. The Mega
accepts either CR or LF as a terminator and emits CRLF through `Serial.println`.

The active application has one owner: FastAPI's lifespan creates one `Rig`, and
`Rig` creates one pyserial object plus one reader thread. A `BuildJob` worker
keeps a blocking build off the event loop; a nonblocking `_inflight` lock in
`Rig` rejects overlapping *waiting* operations. This is good in-process
serialization, but there is no OS-level exclusive lock and `Rig.send()` itself
does not take `_inflight`. Running `rig_console.py`, `servo_test.py`,
`block_grid_calibrate.py`, `rig_build_v1.py`, or another server at the same time
can contend for/reset the same board.

The firmware is fundamentally:

```text
loop → drain bytes → parse a complete command → execute it synchronously
     → return to loop → read more serial
```

All stepper loops, homing, servo settle delays, aux-stepper turns, `G`, `0`,
`0+`, and the complete 14-phase `B` cycle block command reception. A build does
transmit phase messages while moving, but it never calls `checkSerial()` during
the cycle. There is **no Mega STOP command, watchdog, heartbeat, or physical
E-stop represented in this repository**. Browser “stop after this block” stops
the Studio runner from issuing the *next* `B`; it cannot interrupt the current
one. Calibration “cancel” only abandons calibration state when its synchronous
step is no longer occupying the request.

Only `B` has structured command lifecycle messages. `@n RECV` means parsed,
not validated and not moving; `@n STEP ... status=begin` announces a phase
before it runs; phase 11 additionally emits `status=done` after release; only a
terminal `OK`, `ERR`, `SAFE`, or `HELD` ends the command. Other commands are
recognized through human prose and a quiet/settle heuristic.

The largest protocol correctness defect is that `_wait_build()` accepts **any**
terminal ACK; it does not compare `ack.seq` with a sequence associated with the
current request. The Pi does not put a sequence on `B`; the Mega increments its
own counter. The web controller locks after timeout/error, which prevents the
usual stale-ACK reuse, but a direct `Rig` caller that catches a timeout and sends
again can have a late previous terminal ACK complete the new call incorrectly.

## 1. Evidence map and active ownership

### Active production path

| Layer | File and role |
| --- | --- |
| Configuration | `config/rig.json:2-9`: Mega FQBN/sketch, stable port, 9600 baud |
| Transport/protocol | `python/rig/link.py:393-1144`: sole normal serial wrapper, reader, waits, ACK parsing |
| Safety/controller | `python/rig/build_controller.py:16-150`: selection, mode, build, post-error lock |
| Blocking worker | `python/rig/build_job.py:45-103`: one build thread, refuses a second |
| Service owner | `python/web/app.py:200-360`: creates exactly one Rig for app lifespan |
| HTTP commands | `python/web/routes_command.py:87-198`: select/mode/build routes |
| Calibration motion | `python/web/routes_calibration.py:99-248` and `python/rig/block_calibration.py` |
| Browser transport | `web/src/api.ts`; `BuildButton.tsx`; `ModeSwitch.tsx`; Studio runner files |
| Firmware | `arduino/build_test_v1/build_test_v1.ino`, selected by `config/rig.json` |
| Flashing | `scripts/flash.sh:48-74`, reads FQBN/sketch/port from JSON |
| Protocol tests | `python/tests/test_link.py`, `mock_board_test.py`, `web_command_test.py`, build/job/progress tests |
| Simulator | `python/rig/mock_board.py`, pyserial-shaped but not hardware |

The normal server starts the camera pipeline, opens/configures the Mega before
ASGI accepts requests, then starts its camera driver. Shutdown cancels the
driver, waits indefinitely for any build worker, stops the camera, closes the
serial port, and shuts down the camera executor (`web/app.py:328-360`).

### Other live-capable clients

* `python/rig_console.py` uses `Rig`, but its keyboard path calls fire-and-forget
  `send()`, so the console explicitly permits commands during motion.
* `python/camera/rig_build_v1.py` is an older OpenCV operator UI but uses the
  current `Rig`/`BuildController`/`BuildJob` stack.
* `python/camera/block_grid_calibrate.py` is a standalone calibration client and
  opens its own `Rig`.
* `python/servo_test.py` bypasses `Rig`, opens `serial.Serial` directly with a
  0.1 s read timeout and 1 s write timeout, sleeps 2 s for reboot, sends
  `V <angle>\n`, explicitly flushes, and samples whatever output is available.
* Tests inject `MockBoard`; they do not open hardware unless deliberately
  altered.

### Firmware status: current, standalone, prototype, archive

* **Current Mega:** `build_test_v1`; both JSON and `scripts/flash.sh` select it,
  and all current Pi protocol code names it.
* **Standalone Mega grid-fill tools:** `build_vertical_grid` and
  `build_horizontal_grid`. They are large near-copies intended for supervised
  level-0 fills, not selected by the flash config or imported by Python.
* **Current Uno feeder:** `belt_v1`. It has a nonblocking protocol-2
  `FEED`/`STOP` state machine and `@0 READY ... board=uno`. The independent Pi
  client is `rig/feeder.py`; `CellOrchestrator` permits the Mega `B` only after
  exact correlated feeder success. Its STOP must not be attributed to the Mega.
* **Hardware tests:** `container_servo_test`, `uln2003_motor_test`.
* **Archived:** everything under `arduino/archive/`; plans under
  `plans/archive/` describe earlier or proposed states and are not runtime code.

`arduino/README.md`, `AGENTS.md`, JSON, and the live sketch now agree on the
holder travel, gaps, counts, trims, and tool offsets. `python/tests/test_grid.py`
checks the machine-readable pairs; documentation changes still require review.

## 2. Physical and serial connection

| Property | Actual implementation |
| --- | --- |
| Cable/interface | Pi USB host → Mega primary USB serial; firmware uses `Serial`, not `Serial1` |
| Preferred device | Stable `/dev/serial/by-id/usb-www.Arduino.cc_Arduino_14011-if00` |
| Discovery/fallback | `serial_port_candidates()` only swaps ACM0/ACM1 if config literally names one; stable by-id and ttyUSB paths have no fallback; no VID/PID scan or environment override |
| Baud | 9600 in JSON, `Serial.begin(9600)`, and Arduino README |
| Pyserial framing | Defaults: 8 data bits, no parity, 1 stop bit, no flow control |
| Encoding Pi→Mega | `Rig.send`: Python default UTF-8; protocol characters are ASCII subset |
| Encoding Mega→Pi | UTF-8 decode with replacement for invalid bytes |
| Line ending Pi→Mega | `\n` appended after stripping leading/trailing whitespace |
| Mega terminators | either `\n` or `\r`; CRLF is harmless because the empty second terminator is ignored |
| Read timeout | 0.2 s on normal `Rig`; used to let reader observe shutdown |
| Write timeout | unset in `Rig` (pyserial default `None`, potentially unbounded); 1 s only in `servo_test.py` |
| Output flush | no explicit `flush()` in `Rig`; pyserial writes immediately to OS buffer. Servo test does flush |
| Input reset | no `reset_input_buffer()`/output reset; event queue is drained before waiting commands |
| Startup delay | firmware waits 1 s after `Serial.begin`; Pi waits up to 25 s for READY/banner |
| READY | firmware emits `@0 BOOT` near banner start and `@0 READY grid=... mode=...` at its end |
| Old-firmware compatibility | if banner has output but no READY and then is quiet 2 s, connect proceeds with a loud prose-fallback warning |
| Port lock | no explicit `exclusive=True`, flock, lockfile, daemon IPC, or cross-process mutex |

Opening the primary USB port normally toggles DTR and resets the Mega. The code
relies on this behavior but does not explicitly set DTR. Setup initializes pins,
disables the X/Y drivers, attaches and closes the servo, assumes the unsensed
aux claw is physically neutral, starts Serial, delays 1 s, emits BOOT, a long
human banner, then READY (`.ino:1379-1437`). The Pi's reader starts immediately
after open, and `_wait_ready()` consumes until READY. It then optionally homes
X/Y for a requested horizontal mode, synchronizes mode, sends nonzero shifts,
and sends `S` with **highest indices**, not counts. It does not home by default.

The current active vertical connection usually sends only `S 6 5` after READY:
READY already reports vertical and zero shifts are skipped. A horizontal startup
uses `0`, then `RR`, then any shift commands, then `S 2 9`.

## 3. Complete Mega command protocol

All examples below are lines; `Rig.send()` appends LF. Single digits `1..9`
execute immediately even without a terminator. `0` waits for LF/CR, a following
character, or 50 ms idle so it can be distinguished from `0+`. Letters and
multi-character commands require LF/CR.

| Command | Pi path(s) | Firmware dispatch → execution | Physical/result behavior | Completion seen by Pi |
| --- | --- | --- | --- | --- |
| `1` | raw console only | `handleSingleChar` → `executeMove(0)` | X− one configured jog, limit checked | prose only; raw send does not wait |
| `2` | raw console only | same, index 1 | X+ jog | prose only |
| `3` | raw console only | same, index 2 | Y− jog | prose only |
| `4` | raw console only | same, index 3 | Y+ jog | prose only |
| `D` | raw console | single-char → Z negative move | Z− jog toward bottom | prose only |
| `U` | raw console | single-char → Z positive move | Z+ jog toward top | prose only |
| `5` | docs/example raw `Rig.send("5")` | `printFullReport()` | no motion; large status/report dump | no wait |
| `6` | raw console | `resetStatistics()` | clears bookkeeping only | `ALL STATISTICS RESET...`; no structured ACK |
| `7` | raw console | `disableMotors()` | releases X/Y holding torque; does not stop an executing command because it cannot be received then | `MOTORS OFF...` |
| `8` | raw console | `zeroPosition()` | declares current X/Y zero without homing/motion | prose |
| `9` | raw console | `printGrid()` | no motion; ASCII map | prose |
| `?` | raw console | `printInstructions()` | no motion; help/banner | prose |
| `Z` | raw console | prints build config and level table | no motion | prose |
| `O` | raw console | `openServo()` | opens to home-specific 0° or normal open angle | `SERVO: OPEN`; returns before servo settle |
| `C` | raw console | `closeServo()` | closes servo | `SERVO: CLOSE`; returns before servo settle |
| `V <0..180>` | `servo_test.py` or raw console; e.g. `V 45` | `parseNumbers` → `setServoAngle` | arbitrary servo angle | `SERVO: ANGLE`; servo tool sleeps 150 ms but does not validate response |
| `A <-360..360>` | `Rig.rotate_aux`; e.g. `A -45` | strict signed parser → `rotateAuxStepperDegrees` | blocking relative aux turn; no position sensor | waits for prose `AUX STEPPER: done.` up to 30 s |
| `0` | `Rig.home(full=False)`, mode switch pre-home | `goToOrigin()` | blocking Y-home then X-home | waits for `AT ORIGIN` or `ORIGIN NOT REACHED`, then 1 s silence; bool result |
| `0+` | `Rig.home()` | `goToOriginWithZ()` | Z bottom, Z top, then Y/X home | waits for FULL RESET COMPLETE/INCOMPLETE up to 180 s |
| `G <col> <row>` | `Rig.goto`; e.g. `G 3 5` | loose two-number parse → `gotoCell` | validates, homes X/Y, moves Y then X using current calibrated claw rotation | waits for ARRIVED/ALREADY/MOVE INCOMPLETE/ABORTED/ERROR up to 180 s; bool |
| `S <maxCol> <maxRow>` | `Rig.set_grid`; current vertical `S 6 5` | loose two-number parse → `setGridSize` | no motor motion; validates active grid and stores requested highest indices | waits for `GRID RESIZED` or selected errors; no structured ACK |
| `shiftX <cm>` | connect/set_shift; e.g. `shiftX 1.6` | `handleShiftCommand` → `applyGridShift(X)` | no immediate motion; shifts active lattice, may clip far cells | waits for `GRID SHIFT`/error prose |
| `shiftY <cm>` | same | same for Y | same | same |
| `R` | `Rig.set_mode("vertical")` | single-char → `setGridMode(vertical)` | latch only; requires homed X/Y and calibrated aux state | waits for `GRID MODE` or refusal prose; “already in” is treated as success |
| `RR` | `Rig.set_mode("horizontal")` | line parser → `setGridMode(horizontal)` | latch only, no claw movement | same; web explicitly homes X/Y first |
| `B <col> <row> <level>` | `Rig.build`, controller/job, calibration; e.g. `B 3 5 0` | `handleBuildCommand` → `buildBlock` | complete validated 14-phase pick/place/park; active mode chooses rotation | waits up to 300 s for terminal machine ACK, with prose fallback |
| bare `B` | raw console | single-char → `printBuildUsage` | no motion | prose only; importantly, no sequence/ERR ACK on this fast path |

There are no optional arguments in the current `B`. A former rotation word is
explicitly rejected. `parseTwoNumbers()` merely requires two numbers and does
not require the rest of the input to be empty, so `G 3 5 garbage` and
`S 6 5 999` can be accepted using the first two numeric runs. `parseNumbers`
treats punctuation and minus signs as separators, so negative G/S/B inputs are
read as positive magnitudes; Python's higher-level build validation prevents
this for normal builds, but the raw console does not. `B` uniquely checks that
only whitespace/comma/colon/semicolon separators remain after its three values.

### Structured messages emitted by the Mega

| Shape | Timing and meaning |
| --- | --- |
| `@0 BOOT fw=build_test_v1` | setup after the 1 s delay; any unexpected instance means reset |
| `@0 READY grid=6x5 mode=vertical` | last setup line; highest indices, not cell counts |
| `@n ERR <reason>` | malformed B; terminal; parse refusal, nothing moved |
| `@n RECV cmd=B col=… row=… level=…` | B parsed; nonterminal; validation has not completed |
| `@n SAFE <reason>` | B validation rejection; terminal; nothing moved |
| `@n STEP step=… total=14 phase=… action=… text=… status=begin [ms=…]` | phase announced immediately before execution |
| phase-11 STEP with `status=done` | jaws have opened/block released; nonterminal |
| `@n HELD <reason>` | terminal; failure after motion or parking failure; machine/claw may be unknown |
| `@n OK col=… row=… level=…` | terminal after successful parking (or immediate feeder sentinel in firmware) |

`BUSY` is reserved and understood by Python but is not emitted by the current
sketch. There is no asynchronous LIMIT/HOMED/heartbeat message. Limit and
sensor outcomes are human prose generated during the command that encountered
them. Almost all firmware output is unsolicited-looking diagnostic prose, but
it cannot be mistaken for a structured ACK because `parse_ack` requires `@`, an
integer sequence, and a kind token. Prose fallback can, however, break when
human wording changes.

## 4. Arduino receive and parse control flow

1. The AVR USB serial implementation buffers incoming bytes; `loop()` calls
   only `checkSerial()`.
2. `checkSerial()` drains all currently available bytes with `Serial.read()`
   into a fixed 32-byte `lineBuf`, tracking `lineLen`.
3. CR or LF terminates and dispatches a nonempty line. Leading ASCII spaces are
   ignored, but tabs are not ignored at the beginning. `Rig.send().strip()`
   normally removes both before transmission.
4. Digits 1–9 at an empty buffer dispatch immediately. This means `12\n`
   becomes command `1` followed immediately by command `2`, not a line named
   “12”. `0` has its special 50 ms disambiguation.
5. Command heads are case-folded. `shiftX/Y` is detected case-insensitively by
   `sh`; its axis parsing is also case-insensitive. Numeric parsing scans digit
   runs rather than tokenizing conventional fields.
6. On the 32nd nonterminator byte, the partial line is discarded and an error
   is printed. Crucially, bytes after the overflow continue as a fresh line, so
   the tail of one overlong command can be interpreted as another command.
7. CRLF is safe: CR dispatches and LF sees an empty buffer. Multiple complete
   commands already in the buffer are processed in order, but dispatch is
   synchronous. Once one starts motion, unread bytes remain in the AVR's small
   hardware RX ring until it returns.
8. No parser reads serial from a movement loop. A command sent during a long
   build can sit pending, overflow the hardware buffer, become truncated, and
   execute late after the build. The commonly documented AVR serial RX buffer
   is 64 bytes; the repository comments rely on that value, though the exact
   core build configuration ultimately controls it.

Integer accumulation has no explicit overflow check. On AVR, very long digit
runs could overflow `long`, although the 31-character line ceiling bounds the
input. There is no checksum, length field, escaping, command ID supplied by the
sender, or validation of UTF-8 on the firmware side.

## 5. Raspberry Pi send/read control flow

Normal build action:

```text
browser BuildButton/Studio runner
→ POST /api/build with confirm=true and exact displayed command
→ route validates fresh camera, current selection, not running/locked
→ BuildJob.start creates one `rig-build` thread
→ BuildController.build
→ Rig.build validates coordinates and acquires `_inflight` nonblocking
→ drain old Python events; `send("B …")`
→ pyserial.write(UTF-8 bytes ending LF)
→ Mega parser/buildBlock
→ reader thread: readline → UTF-8 replacement decode → log/callback/parse ACK
→ event queue → `_wait_build`
→ BuildResult → controller selection clear or safety lock
→ app pipeline polls job and publishes result/state over WebSocket
```

`send()` strips the command, appends one LF, encodes with default UTF-8, writes
once, logs it, and returns. It neither flushes nor checks the returned byte
count. Normal blocking helpers first acquire `_inflight`, drain the internal
event queue, send, then consume reader events until completion or timeout.
Callbacks execute on the reader thread; the web app immediately forwards them
to the asyncio loop with `call_soon_threadsafe`, preserving wire order and
keeping the sole reader nonblocking.

For non-B commands `_send_and_settle` ignores all structured ACKs except BOOT,
collects prose, marks completion when a substring appears, then requires 1 s of
silence. Configuration-only operations may instead return after 3 s of quiet
with a fallback warning. Moving operations never use the quiet escape hatch.
On timeout the method raises but does not close the port, reset the board, or
drain bytes that arrive later.

For B, terminal ACK is definitive. Otherwise human prose starts a 1.5 s settle
window because `BUILD COMPLETE` appears before a possible parking failure.
Disconnect creates a `_DEAD` event and invokes the error callback. No automatic
reopen occurs.

## 6. ACK semantics and defects

The protocol correctly distinguishes receipt, progress, release, and terminal
completion:

* `RECV`: syntax parsed and sequence assigned; **not accepted for motion**.
* `STEP begin`: a phase is about to run; not proof it completed.
* phase 11 `STEP done`: physical release command and servo-settle completed;
  parking remains.
* `SAFE`/`ERR`: terminal, nothing moved, retry may be safe.
* `HELD`: terminal after/around motion, or placed but failed to park; inspection
  required.
* `OK`: terminal after the full requested outcome and successful park.

ACKs are emitted after blocking work for terminal success/failure, while STEPs
are emitted before each blocking phase. There is no retry anywhere. Retrying B
automatically would risk duplicate placement, so the current “unknown means
lock and inspect” policy is appropriate.

Protections:

* `_drain()` prevents READY/old already-queued output satisfying a new wait.
* `@` isolates machine lines from debug prose.
* a bounded Python event queue (4096, oldest dropped) prevents idle memory growth.
* web state locks on serial error, timeout, worker exception, or HELD.

Weaknesses:

* `_wait_build()` tests `ack.terminal` but never validates sequence or command
  fields. A late ACK arriving after `_drain()` is a stale-answer hazard.
* Sequence is generated by the Mega, not supplied in `B`; the Pi cannot know
  the expected number before `RECV`. A robust current-code check could at least
  latch RECV's seq and require subsequent events to match it.
* The progress callback forwards every STEP regardless of which command the
  UI believes is active.
* A lost terminal ACK causes a 300 s timeout even if the build physically
  succeeded. The session locks, but the result is unknowable without inspection.
* Non-B completion depends on prose substrings and silence. Debug wording or
  extra periodic diagnostics could cause timeouts; wording collisions could
  cause premature completion.
* No write timeout in `Rig` means a pathological device/driver write can block
  its caller indefinitely.

## 7. Blocking and interruptibility

| Operation | Blocking source | Serial serviced while running? | Software interruptible? |
| --- | --- | --- | --- |
| jog 1–4/D/U | fixed pulse loop | no | no; physical/soft limit only |
| `A`/build rotation | `Stepper.step()` | no | no; no aux limit/sensor |
| O/C/V | returns immediately after servo write | loop resumes quickly | next command cannot undo bytes already acted on |
| servo inside B | servo write + `delay(SERVO_SETTLE_MS)` | no | no |
| `0` | bounded chunked Y then X switch seeks | no | no; switch or max-step bound stops each seek |
| `0+` | bounded Z bottom/top and X/Y seeks | no | no |
| `G` | home plus absolute Y/X pulse loops | no | no |
| `B` | validation then 14 synchronous phases | no reads; yes, phase writes | no STOP; limits/bounds can abort individual moves |
| reports/maps | many blocking Serial prints | no new command dispatch | not interruptible; output buffering can block at 9600 |

The Pi can see phase-level liveness during B only if the ACK-enabled firmware
is actually flashed. A phase can still hang/silence until its bounded movement
returns; there is no continuous heartbeat. Homing has maximum-step bounds and
motion checks physical/soft limits, so firmware does not intentionally seek
forever. A mechanical stall is not sensed: step counts advance despite missed
physical steps.

## 8. Concurrency and collisions

Inside the production server, HTTP build calls are protected at three layers:
`require_mutable()` sees `BuildJob.running`, `BuildJob.start()` refuses a second,
and `Rig._inflight` refuses overlapping blocking transactions. Block calibration
uses a separate nonblocking lock for double clicks and also calls
`require_mutable`. Mode changes are synchronous HTTP calls and eventually use
the same Rig lock.

Important holes:

1. `Rig.send()` does not acquire `_inflight`; the interactive console can inject
   commands during a waiting operation.
2. `_inflight` is per `Rig` instance, not process-wide or OS-wide. Multiple
   programs can attempt open. Linux/pyserial generally allows multiple opens of
   a tty unless exclusive locking is requested; reads can be split unpredictably
   and each open may reset the board.
3. The server's standalone calibration path uses the same Rig but its synchronous
   route lock is separate from BuildJob. `require_mutable` prevents a normal job
   already running; while a calibration step runs, another normal build request
   can pass `job.running == false` until it reaches Rig and then fail `RigBusy`.
   The route does not mark the global controller busy for the duration. This is
   protected at transport level but produces a race/409-like failure rather
   than unified state.
4. Direct utility `servo_test.py` bypasses every application lock.

## 9. Connection lifecycle

* **Pi/server startup:** construct config/camera/Rig/controller/job; start camera;
  open serial; start reader; wait for banner; configure mode/shift/counts; then
  accept requests. Default connect does not home.
* **Mega startup/reset:** pins initialize, X/Y motors disable, servo closes,
  claw angle is assumed neutral, all homing knowledge is false/default, 1 s
  delay, BOOT/banner/READY.
* **Normal operation:** serial object persists for app lifespan. One daemon
  reader continuously drains output. Commands are synchronous transactions,
  with builds delegated to one worker.
* **Unplug:** reader catches SerialException/OSError/TypeError, enqueues DEAD,
  notifies UI. An active waiter raises; controller locks. `connected` may still
  report from `is_open` until pyserial state changes; there is no reconnect.
* **Reconnect:** not automatic. Restart the application or explicitly manage a
  new connection. Device by-id should remain stable if the symlink reappears.
* **Unexpected Arduino reset:** BOOT latches `_reset_detected`; an active command
  gets `RigReset`. Future helpers refuse. `recover_after_reset(home=True)` exists
  but web deliberately never calls it: human inspection/authorization is needed.
* **Pi service restart:** closing/opening resets Mega, waits READY, replays
  mode/shift/grid. It cannot know whether a pre-crash motion/place succeeded.
* **Shutdown:** server waits for current build without timeout, then closes.
  Console and standalone tools close in `finally`/context managers. SIGKILL or
  power loss provides no cleanup and does not stop the Mega's current function.

## 10. Major actions end to end

### Home / mode change

The web has no general “Home” API button. Horizontal mode selection is the
normal UI-triggered home path:

```text
ModeSwitch confirm → api.mode("horizontal") → POST /api/mode
→ require not build-running/locked
→ BuildController.set_mode(home_before_horizontal=True)
→ Rig.home(full=False) → "0\n"
→ Mega goToOrigin: seek Y switch, then X; prose completion
→ Rig.set_mode → "RR\n" → Mega validates homed state and latches only
→ Rig sends shift(s) and S for horizontal geometry
→ camera pipeline changes mode → state/WebSocket update
```

Switching back vertical sends `R` without automatic homing from the controller;
firmware still requires X/Y currently homed, so it can refuse if motion has left
the gantry away from home. Normal completed B parks home, making this commonly
work.

### Manual motion/servo/reset

There are no production HTTP routes for raw jog, G, servo, full reset, or motor
disable. They are console/utility operations:

```text
terminal input → rig_console Rig.send → serial.write → Mega parser
→ synchronous hardware function → prose → reader thread prints it
```

Because this path is fire-and-forget, no application state is updated and a
second terminal line can be buffered while the first is executing.

### Single build from web/camera

Selection is camera pixel → current workspace homography → grid cell; level and
selection yield an exact server-owned `B c r l`. The UI requires a second
confirmation and sends that exact string back. The server rejects mismatch,
stale camera, feeder, invalid cell, busy, or locked state. The worker calls
`Rig.build`, which sends B once. Mega validates all geometry, limits and level
before motion, then: raise Z; home feeder; neutralize/open; lower/grip/lift;
move Y/X target; rotate for active mode; lower; release; lift/home/unrotate.
Progress reaches WebSocket/twin in wire order. OK clears selection; SAFE/ERR
leaves it retryable; HELD/timeout/disconnect locks the session.

### Build shape / Studio runner / stop

The browser compiles a model to a sequence of mode effects and single-block
build effects. `runner-driver.ts` performs selections/mode HTTP calls and one
`api.build` at a time, then waits for the durable WebSocket result before the
next. “STOP AFTER THIS BLOCK” sets runner state so no following effect is sent.
It sends no serial STOP and cannot interrupt a Mega call already running.

### Placed-block calibration

Calibrate UI → `/api/calibration/block/start` captures baseline and plans cells;
each `/step` (sync FastAPI worker thread) → `BlockCalibrationRun.step` → the same
`Rig.build` B transaction → capture frame → locate commanded block → accumulate
labelled correspondence. Aborted motion locks the global controller. Undo and
cancel alter observations/session only; they do not move or stop hardware.

### Camera-only calibration

Corner clicks, printed-paper calibration, view toggles, and map reload do not
send serial commands. They affect camera geometry/state only.

## 11. Failure-mode classification

| Failure | Class | Why in this code |
| --- | --- | --- |
| Port-open reset | Already visible | explicitly designed around; READY/config replay |
| Command before boot | Protected in `Rig`; possible in bypass clients | Rig waits banner; servo utility sleeps fixed 2 s |
| wrong ACM number | Protected only for literal ACM0/1 | stable by-id has no fallback; error text misleadingly always names ACM0/1 |
| reconnect changes number | Protected by by-id when same board identity; otherwise possible | no discovery/reconnect |
| port already open/multiple process | Possible | no exclusive OS lock; flash notes collision |
| concurrent normal web builds | Protected | job + Rig locks |
| raw send during build | Possible/likely in console misuse | send bypasses lock; Mega RX can overflow/execute late |
| browser STOP interrupts build | Impossible | no Mega STOP; UI accurately says after current block |
| AVR RX overflow during B | Possible | no reads during ~40 s, small hardware ring |
| 32-byte line overflow | Protected by drop, but unsafe tail behavior possible | emits error then resumes accumulating tail |
| partial message | Protected across reads until CR/LF; reset/overflow remain possible | persistent line buffer |
| concatenated newline commands | Processed sequentially when idle; hazardous during motion | synchronous dispatch and hardware buffering |
| malformed B | Protected | ERR with terminal ACK for line-form malformed B |
| malformed G/S trailing data | Already visible | loose scanner accepts first two numbers |
| stale queued output | Mostly protected | drain before transaction |
| late ACK matched to next B | Possible | no sequence correlation after drain |
| debug output mistaken for ACK | Protected structurally; prose waits remain fragile | `@` parser isolation, substring fallbacks |
| ACK lost | Possible | no retry/query; timeout locks web state |
| Linux permission failure | Possible, diagnosed | open error suggests dialout group |
| disconnect mid-motion | Possible and safety-significant | Pi notices; Mega continues current synchronous command |
| Pi/backend crash mid-motion | Possible and safety-significant | Mega continues; no lease/watchdog |
| Arduino reset mid-motion | Possible; detected if Pi survives | motion stops on reset, state/homing lost, servo closes in setup |
| mechanical stall with step pulses | Possible | open-loop steppers; only switches/commanded counts observed |
| frontend/Wi-Fi loss | Protected from new commands; current command continues | server/Mega independent of browser |
| command hangs forever in firmware | Reduced, not impossible | seeks bounded; pyserial write and shutdown join can be unbounded |
| stale geometry documentation | Already visible | Arduino README conflicts with current paired sources |

## 12. Safety implications

**Software stop capability:** there is no interrupt-current-command capability
on the Mega. The only remotely resembling command, `7`, disables X/Y drivers
but cannot be parsed until current synchronous work returns and does not cover
the independently driven Z/aux/servo in a meaningful emergency-stop design.
Studio stop is sequencing control only. Limits stop travel at configured ends;
they do not constitute an operator emergency stop.

**Physical emergency stop:** no hardwired E-stop, safety relay, power contactor,
or externally interruptible enable chain is described by the communication
implementation. Therefore the repository cannot claim a physical E-stop. USB
disconnect, browser closure, Wi-Fi loss, or Pi crash leave the Mega executing
the already-received command. Pulling Mega power would stop control but is not
equivalent to a designed safe power-removal circuit and may release/leave loads
unpredictably.

On Mega reset, setup disables X/Y motor drivers and commands the servo closed;
the aux angle is merely assumed neutral even if it physically is not. Position
and homing are lost. On Pi crash, the firmware receives no notification. On an
ACK timeout, software state becomes unknown but motors may have completed or
may still be moving. The web appropriately locks further commands, but that is
containment after uncertainty, not a stop.

## 13. Protocol quality review and ranked improvements

### Current assessment

The design is simple and debuggable: line framing, human prose beside isolated
machine records, pre-motion validation, bounded limit seeks, explicit SAFE vs
HELD semantics, one-owner web lifecycle, and conservative post-error locking
are strong choices. Build progress is deterministic at phase granularity and
the mock/test coverage is substantial.

Reliability is limited by mixed structured/prose completion, 9600-baud verbose
output, no sender-correlated transaction ID, no reconnect/status reconciliation,
no write deadline, and total firmware deafness during motion. Physical safety
is limited most seriously by the lack of an independently effective E-stop and
by continued autonomous execution after loss of the Pi/browser link.

### Critical

1. Provide a real, hardwired emergency-stop path that removes hazardous motion
   energy independently of Python, USB, the event loop, and firmware parsing;
   define restart/recovery behavior with the actual electrical design.
2. Make STOP observable during movement: refactor pulse/seeking/build execution
   into a cooperatively serviced state machine or poll a dedicated hardware stop
   input inside every blocking loop. A serial STOP alone is insufficient unless
   reads occur during movement.
3. Correlate every request and terminal response. Prefer Pi-supplied monotonically
   increasing IDs; at minimum latch B's RECV seq and reject mismatched STEP and
   terminal ACKs. Never allow a late response to satisfy a later command.
4. Prevent process-level multiple ownership (`exclusive=True` where supported,
   plus a clear single daemon/lockfile policy). Route utilities through the owner
   or require the server to be stopped explicitly.
5. Change line-overflow handling to discard **until the next terminator**, so an
   overlong command's tail can never become an executable command.

### Important before deployment/demo

1. Flash and hardware-verify the checked-in ACK/STEP firmware, then record the
   deployed firmware/protocol version. Until then production depends on prose.
2. Give every motion/config command a structured RECV/terminal response with
   stable error codes; eliminate silence/prose completion heuristics.
3. Add a finite write timeout and validate write completion; define what happens
   when writing fails after a partial line.
4. Unify busy state across normal builds and block calibration. Make all public
   sends participate in one command arbiter; make raw `send` explicitly unsafe
   or private.
5. Add post-connect and post-reset status reconciliation (firmware version,
   protocol version, mode, grid, homing, claw state) without silently moving.
6. Decide and document safe outputs on reset/link loss. If a communications
   lease/watchdog is introduced, it must lead to a physically safe state and not
   merely reset mid-carry.
7. Update stale `arduino/README.md` geometry and fix the hard-coded ACM0/1 open
   error to report the actual candidates attempted.
8. Reduce/throttle prose at 9600 or raise baud in all three paired locations
   after hardware verification; ensure output cannot delay safety-relevant code.

### Nice to have

1. Publish a generated protocol table/version from firmware constants and test
   it against Python/mock/browser phase copies.
2. Use strict token parsing with exact arity/ranges for every command.
3. Add explicit STATUS/query commands and command history sufficient to resolve
   a reconnect without guessing or replaying motion.
4. Add tests for late/mismatched ACKs, overlong-tail injection, concurrent
   calibration/build requests, partial writes, and disconnect at each phase.
5. Deprecate or clearly fence standalone direct-port utilities, and label the
   near-copy grid sketches with their intended flash/use workflow.

## Bottom line

The current system is a well-instrumented but synchronous single-command serial
controller. The Pi side does a good job preventing normal UI overlap and
refusing to guess after uncertainty. It does **not** make the Mega interruptible,
does not provide physical emergency stopping, and does not fully correlate ACKs
to requests. Those three facts should govern both deployment decisions and the
next protocol work.

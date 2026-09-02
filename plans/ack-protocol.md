# Design note — an acknowledgement protocol

**Status:** the safety subset **and the `STEP` progress channel** are built in
`build_test_v1`. Compile-checked and their output verified byte-for-byte on a
host build — **but never flashed to the board.** The Pi reads them in
`python/rig/link.py`, which falls back to prose matching (loudly) for exactly
that reason. The watchdog is deliberately not built; see below.

`STEP` is the thing this note originally recommended AGAINST building (it was
called `RUN` then) and then changed its mind about. The section "`RUN` and the
watchdog" further down is kept verbatim, because its reasoning is still right:
`STEP` is **a progress feature, not a safety one**. What changed is that the
progress feature became worth having — the web console, its runner and its 3D
twin all had to describe a 40-second silence, and the only honest way to do
that is to have the firmware say what it is doing.

## The problem

The firmware talks to a human. To know whether a build worked, the Pi has to
match prose:

```
BUILD COMPLETE - block placed at [3,5] level 0 (0.00 cm)
```

That works until someone rewords a message. It also cannot answer the two
questions that actually matter during a 40-second build: *is it still alive?*
and *which of my commands is this about?*

## The idea

Keep the prose exactly as it is — it is good, and a human with a Serial Monitor
depends on it. Print **one extra line** beside it, for the machine.

```
======================================
BUILD COMPLETE - block placed at [3,5] level 0 (0.00 cm)   <- human
Place time: 41.2s
======================================
@12 OK col=3 row=5 level=0 ms=41210                        <- machine
```

Two audiences, two lines, neither compromised.

## What is actually built

`SECTION 7C` of `build_test_v1.ino`, plus six one-line call sites:

| Where | Emits |
| --- | --- |
| `setup()`, straight after `Serial.begin` | `@0 BOOT fw=build_test_v1` |
| `setup()`, last line | `@0 READY grid=10x20` |
| `handleBuildCommand()`, two parse failures | `@n ERR <what was expected>` |
| `buildReject()` | `@n SAFE <why>` |
| `buildAbort()` | `@n HELD <why>` |
| `buildBlock()`, at the end | `@n OK col= row= level=` — or `HELD` if parking failed |
| `handleBuildCommand()`, after a clean parse | `@n RECV cmd=B col= row= level=` |
| `buildStep()`, before every phase | `@n STEP step= total= phase= action= text= status=begin` |
| `buildBlock()`, the instant the jaws open | `@n STEP step=11 … status=done` |

Verified output, produced by compiling the real sketch against a host stub and
running it:

```
@0 BOOT fw=build_test_v1
@0 READY grid=10x20
@1 ERR expected: B <col> <row> <level>
@2 SAFE cell out of range
@3 OK col=3 row=5 level=0
@4 HELD Z never reached the ground switch
@5 HELD block placed but parking failed
```

### One deliberate change from the design below

**Reasons are free text, not short codes.** The design proposed `SAFE RANGE`
with a code table. In practice `buildReject()` and `buildAbort()` already take a
runtime `const char *why`, so the ack can print that same pointer — no new
strings, no SRAM cost, and no need to touch thirteen call sites inventing codes.

Nothing is lost: the Pi branches on the **kind**, which is a fixed token. The
reason is for the log and for the human. If a Pi-side branch on a specific
reason is ever needed, codes can be added then.

### Note on `@0 READY grid=10x20`

That reports the grid the board **booted with**, which is the compiled default.
The Pi still pushes `S <cols> <rows>` from `config/rig.json` afterwards. Seeing
the boot value is useful precisely because it is the one the Pi is about to
override.

## `STEP` — real-time build progress

A build is about forty seconds during which `buildBlock()` never reads serial.
Before `STEP` the Pi learned exactly two things in that window: that it had
sent a `B`, and, eventually, how it ended. Everything in between — the claw
reaching the feeder, gripping, carrying, releasing — was invisible, and every
UI that wanted to show it had to invent something.

`buildStep()` already existed and already printed `[BUILD 8/14]` for the human.
It now prints one machine line beside it, before the phase runs:

```
@12 STEP step=8 total=14 phase=move_to_target action=move text=Move_XY_to_the_target_cell status=begin
[BUILD 8/14] Move X/Y to the target cell
```

### The fields

| Field | Meaning |
| --- | --- |
| `<seq>` | the same sequence number as the `B` it belongs to, so every phase is attributable to one command |
| `step` | 1..`total` |
| `total` | `BUILD_STEP_COUNT`, on the wire so nothing downstream hard-codes 14 |
| `phase` | the STABLE identifier UIs switch on. **Renaming one is a protocol change.** |
| `action` | `move` / `grip` / `release` / `rotate` / `park` — coarse on purpose: a consumer needs to know whether a block is being carried, not which motor turns |
| `text` | the human label, underscored so it survives as one whitespace-separated token. The Pi un-underscores it. |
| `status` | `begin` before the phase runs; `done` exactly once — see below |
| `ms` | how long the phase is predicted to take. **Z moves only**, and omitted when unknown — see below |

### The fourteen phases

This table is the contract. `buildStep()`'s call sites in `build_test_v1.ino`
are its source; `MockBoard.BUILD_PHASES` and `web/src/studio/twin.ts`'s
`PHASE_BY_ID` are copies, and `twin.test.ts` fails if the browser's copy grows
or loses a row.

| step | `phase` | `action` | what the machine does |
| --- | --- | --- | --- |
| 1 | `raise_clear` | move | raise Z into the top switch (clearance) |
| 2 | `home_feeder` | move | home X/Y to the feeder cell `[0,0]` |
| 3 | `neutralise_claw` | rotate | return the claw to neutral before picking up |
| 4 | `open_claw` | release | open the claw |
| 5 | `lower_to_ground` | move | lower Z to the bottom switch |
| 6 | `grip` | grip | close the claw — **the block is now in it** |
| 7 | `lift_block` | move | raise Z to carry height |
| 8 | `move_to_target` | move | fly X/Y to the target cell |
| 9 | `rotate_to_grid` | rotate | apply the active grid's rotation |
| 10 | `lower_to_level` | move | lower Z to the target block level |
| 11 | `release` | release | open the claw — **the block leaves it** |
| 12 | `park_clear` | park | raise Z clear of the stack |
| 13 | `park_home` | park | return X/Y to the origin |
| 14 | `park_rotation` | park | return the claw to neutral |

### The one `status=done`

Phase 11 is announced twice: `begin` before the jaws open, and `done` the
instant they have. That second line is the only `done` in the protocol, and it
exists because **nothing else can carry that fact**. Phase 12 beginning would
imply it, but `BUILD_PARK_AFTER_PLACE` can be false, in which case there is no
phase 12 at all.

**`done` is not a terminal ack.** The command is still running, the rig still
has to park, and a parking failure downgrades the whole build to `HELD`. A UI
may stop showing the block in the claw; it may not show the block as placed.
Only `@n OK` says that. See `python/web/progress.py`.

### `ms` — how long the descent will take

The steppers have no acceleration ramp: `moveAxisSteps()` is a fixed-period
pulse loop, so a move of N steps takes `N * stepPeriodMs(axis)` and that is
genuinely computable rather than guessed. `zEtaMs()` does the arithmetic and
`ms=` puts the answer on the four Z phases (1, 5, 7, 10).

For the current calibration — `Z_TRAVEL_STEPS = 1350`, `STEP_DELAY_Z = 950 us`
(so 1.9 ms/step), `Z_TRAVEL_CM = 26.5`, `BLOCK_HEIGHT_CM = 1.5` — that is:

```
full travel          1350 steps          = 2565 ms  (+ DIR_SETTLE_MS = 2570)
one block height     76.4 steps          =  145 ms
descent to level K   1350 - 76.4*K steps = 2565 - 145*K  ms
```

Measured on the rig with a stopwatch: **2.6-2.8 s** for a full top-to-bottom
travel, against 2.57 s predicted. The 35-235 ms gap is the fixed overheads the
model does not carry (`DIR_SETTLE_MS`, the limit-switch confirm), not an error
in the rate.

**Why the firmware sends it rather than the Pi computing it.** `Z_TRAVEL_STEPS`,
`Z_TRAVEL_CM` and `BLOCK_HEIGHT_CM` are on AGENTS.md's "must NOT be copied into
`config/rig.json`" list. A browser that worked the descent out for itself would
need all three, and would silently drift the day someone retunes `STEP_DELAY_Z`.
The board owns the numbers, so the board does the sum. One field on a line that
was being sent anyway; no extra airtime worth measuring.

**It is a FLOOR, not a schedule.** Nothing moves faster than its step rate, so
the real phase can only take LONGER — a stiff axis, a stall, an early limit all
add time. Two rules follow, and both are enforced downstream:

* a consumer may animate from it, but **its expiry means nothing**. Only the
  next `STEP`, or the terminal ack, says a phase is over.
* `ms=0` is never sent. **Absent means "no idea", which is not "instant"** — a
  UI cannot tell those apart from a number, and would draw the second one as an
  arrival that never happened.

The twin uses it for exactly one thing: animating the placement descent, from
the moment the phase-10 event arrived, clamped short of the cell so the block
can only actually land when the release event says it did. See
`web/src/studio/twin.ts` `descentProgress()`.

Phases 2, 3, 4, 6, 8, 9, 11, 13 and 14 send no `ms` at all. X/Y moves could in
principle be predicted the same way, but they are not: the useful case is the
one the eye follows, and adding fields nobody reads costs airtime for nothing.

### `RECV`

`@n RECV cmd=B col=3 row=5 level=0` is printed the moment the arguments parse.
It is not terminal. It pins the sequence number to the command before the
validation that may still reject it, which is what lets the console show
"accepted, validating" as a state distinct from "moving".

### Why one line per PHASE and not per step

At 9600 baud each of these lines is ~20 ms. Fourteen of them is ~0.3 s inside a
40-second build: negligible, and the number this note already worked out when
it was arguing about `RUN`. **One line per motor step would be minutes** — it
would fill the Mega's output buffer, stall `stepMotor()` on a blocking write,
and starve the terminal ack that actually matters.

If continuous position is ever genuinely needed, the rule is: throttle it hard
inside the movement loops — a few events a second, or milestone percentages —
and it is still not a reason to change the baud. Until then, phase-level is all
there is, and **nothing above the firmware may claim to know where the arm is
between phases.**

### Verified host-stub output

Produced by compiling the real sketch against a host Arduino stub and calling
the phase announcements in order (the same technique as the transcript above):

```
@12 RECV cmd=B col=3 row=5 level=0
@12 STEP step=1 total=14 phase=raise_clear action=move text=Raise_Z_into_the_top_switch status=begin
@12 STEP step=2 total=14 phase=home_feeder action=move text=Home_XY_to_the_feeder status=begin
@12 STEP step=3 total=14 phase=neutralise_claw action=rotate text=Return_the_claw_to_neutral status=begin
@12 STEP step=4 total=14 phase=open_claw action=release text=Open_the_claw status=begin
@12 STEP step=5 total=14 phase=lower_to_ground action=move text=Lower_Z_to_the_ground_switch status=begin ms=2570
@12 STEP step=6 total=14 phase=grip action=grip text=Close_the_claw_and_grip status=begin
@12 STEP step=7 total=14 phase=lift_block action=move text=Raise_Z_to_carry_height status=begin
@12 STEP step=8 total=14 phase=move_to_target action=move text=Move_XY_to_the_target_cell status=begin
@12 STEP step=9 total=14 phase=rotate_to_grid action=rotate text=Apply_the_grid_rotation status=begin
@12 STEP step=10 total=14 phase=lower_to_level action=move text=Lower_Z_to_the_target_level status=begin ms=2570
@12 STEP step=11 total=14 phase=release action=release text=Open_the_claw_and_release status=begin
@12 STEP step=11 total=14 phase=release action=release text=Open_the_claw_and_release status=done
@12 STEP step=12 total=14 phase=park_clear action=park text=Raise_Z_clear_of_the_stack status=begin
@12 STEP step=13 total=14 phase=park_home action=park text=Return_XY_to_the_origin status=begin
@12 STEP step=14 total=14 phase=park_rotation action=park text=Return_the_claw_to_neutral status=begin
@12 OK col=3 row=5 level=0
```

### `ackWord`, and a trap worth knowing about

`STEP` needed key=value pairs whose value is a WORD rather than a number, and
the obvious move — an `ackField()` overload taking `const __FlashStringHelper *`
— is a trap: an integer literal `0` is also a null pointer constant, so
`ackField(F("level"), 0)` becomes ambiguous and every existing numeric call
site is one edit away from a compile error. The word form is therefore a
separately named `ackWord()`.

## The sentinel

Every machine line starts with `@`. Nothing the firmware prints today starts
with `@` — checked, zero occurrences — so the Pi's filter is one `startswith`
and a human can ignore them by eye.

```
@<seq> <KIND> [<positional> ...] [key=value ...]
```

Fields are space-separated. No JSON: on an 8 KB AVR at 9600 baud, braces and
quotes cost SRAM and airtime for nothing.

## The library

### Command lifecycle

Every accepted command gets a sequence number and ends in exactly one terminal
event. No exceptions — that is what makes the Pi's wait loop safe.

| Kind | Terminal | Meaning |
| --- | --- | --- |
| `RECV` | no | parsed, accepted, about to run. **Built.** |
| `BUSY` | **yes** | refused — something is already running |
| `ERR` | **yes** | refused — bad syntax or out of range. **Nothing moved.** |
| `STEP` | no | progress: one build phase, before it runs. **Built** — see above. (This is the kind the design below calls `RUN`.) |
| `OK` | **yes** | finished, succeeded |
| `SAFE` | **yes** | failed, and **nothing moved**. Recoverable, retry is fine. |
| `HELD` | **yes** | failed mid-motion. **The claw may still be gripping a block.** |

### Why `SAFE` and `HELD` are different kinds, not a flag

This is the whole reason to build the protocol. The firmware already draws this
line — `buildReject()` prints "Nothing moved", `buildAbort()` prints "The claw
may still be holding a block" — and it is the difference between a typo and a
human walking to the rig. Making it two *kinds* means the Pi cannot handle it
with a generic `if not ok: retry`. You have to write the `HELD` branch.

### Unsolicited events (sequence 0)

Seq `0` means "nobody asked for this".

| Line | When |
| --- | --- |
| `@0 BOOT fw=build_test_v1` | first line after reset |
| `@0 READY grid=10x20 homed=0` | end of the startup banner — **the Pi's sync marker** |
| `@0 LIMIT axis=X` | a switch tripped unexpectedly |
| `@0 NOTE ...` | anything else worth logging |

`@0 READY` replaces the current fragile approach of matching the last banner
line by its wording.

### Reason codes

`ERR`, `SAFE` and `HELD` carry a short token, not a sentence. The sentence is
already on the human line above.

| Code | Meaning |
| --- | --- |
| `ARGS` | could not parse the arguments |
| `RANGE` | col/row/level outside the grid or build ceiling |
| `NOHOME` | position not trustworthy, homing failed |
| `ZCAL` | Z calibration is zero or nonsensical |
| `SWITCH` | a limit switch was not found where expected |
| `PARK` | placed the block but failed to park afterwards |

`PARK` is deliberately a `HELD`, not an `OK`: the block is down, but the rig is
somewhere unknown.

## Who assigns the sequence number

**The Arduino does**, incrementing on each accepted command.

The alternative — the Pi tagging its commands (`B 3 5 0 #12`) — would change the
command grammar and break hand-typing in a Serial Monitor. Since the rig runs
strictly one command at a time, "the seq in the `RECV` that followed my send" is
unambiguous, and the Pi gets correlation for free without touching the grammar.

## `RUN` and the watchdog — recommended AGAINST, for now

The first version of this note argued that `RUN` events turn a blind timeout
into a watchdog. That argument is weaker than it looked, and the reason is worth
writing down.

**The firmware does not hang.** Homing runs `while (travelled < maxSteps)`
(`build_test_v1.ino:1673`), seeks are capped the same way, and a motion that
does not find its switch prints `SEEK FAILED` or `ABORTED` and returns. The rig
reports its own failures. A watchdog would mostly be waiting for something the
firmware is already going to tell us.

**The one failure it would catch is better caught another way.** If the board
browns out or resets mid-build, it does not stall — it reboots and prints
`@0 BOOT`. An unexpected `BOOT` while a command is in flight is a *stronger*
signal than a missed heartbeat, and it costs nothing extra.

**And the airtime argument was wrong.** 14 `RUN` lines at 9600 baud is about
0.3 seconds inside a 40-second build. Negligible. `RUN` is not a reason to move
to 115200.

So what `RUN` actually buys is a **progress bar** — a UX feature, not a safety
one. Worth adding when the viewer wants one. Not worth adding first.

A plain generous timeout, plus "unexpected `@0 BOOT` means the board reset",
covers the safety case.

## Firmware shape

About 40 lines. Every literal in `F()` — the sketch runs at 26% SRAM only
because of that, and it would not boot otherwise.

```c
uint16_t ackSeq = 0;

void ackLine(uint16_t seq, const __FlashStringHelper *kind) {
  Serial.print('@'); Serial.print(seq);
  Serial.print(' '); Serial.print(kind);
}
void ackField(const __FlashStringHelper *name, long value) {
  Serial.print(' '); Serial.print(name); Serial.print('='); Serial.print(value);
}
void ackEnd() { Serial.println(); }

void ackHeld(const __FlashStringHelper *code) {
  ackLine(ackSeq, F("HELD")); Serial.print(' '); Serial.print(code); ackEnd();
}
```

No `String`, no `sprintf`, no buffers — print field by field straight out of
flash. Call sites go next to the existing prose, so the two can never disagree:
one line added inside `buildAbort()`, one inside `buildReject()`, one at the end
of `buildBlock()`.

## Pi shape

```python
@dataclass
class Ack:
    seq: int
    kind: str            # RECV BUSY ERR STEP OK SAFE HELD BOOT READY LIMIT NOTE
    args: list[str]
    fields: dict[str, str]

TERMINAL = {"OK", "SAFE", "HELD", "ERR", "BUSY"}

@dataclass(frozen=True)
class SerialProgress:          # one STEP line, parsed
    seq: int
    step: int
    total: int
    phase: str                 # the stable id
    label: str                 # `text`, un-underscored
    action: str                # move / grip / release / rotate / park
    status: str                # begin | done
    eta_ms: int | None         # predicted duration; Z moves only, never 0
```

`Rig` takes an `on_progress` callback (a `SerialProgress` per `STEP`) and an
`on_ack` callback (every machine line), both called on the reader thread in
wire order. That ordering is what makes "the phases came before the OK" true
for everything downstream — see `web/app.py`, which forwards each with
`loop.call_soon_threadsafe`.

The reader thread parses any line starting with `@` into an `Ack` and prints
everything else unchanged. `link.send_and_wait()` blocks until a terminal kind
with the matching seq arrives, resetting its watchdog on every `RUN`.

## Sample transcript

```
@0 BOOT fw=build_test_v1
@0 READY grid=10x20 homed=0
                                    <- Pi sends: S 10 20
@1 RECV S
@1 OK cols=10 rows=20
                                    <- Pi sends: B 3 5 0
@2 RECV B
@2 RUN 2/14 home
@2 RUN 5/14 descend
@2 RUN 8/14 travel
@2 RUN 11/14 release
@2 OK col=3 row=5 level=0 ms=41210
```

And the one that matters:

```
@3 RECV B
@3 RUN 5/14 descend
@3 HELD SWITCH
```

Three lines, and the Pi knows to stop and put a red banner on the screen.

## Rollout

**Done:** the firmware side, listed above, and the Pi side in
`python/rig/link.py` — `parse_ack()` turns an `@` line into an `Ack`, and
`Rig.build()` waits for a terminal kind. Prose matching is kept as a fallback
and counted in `Rig.prose_fallbacks`; every time it fires it says so on stderr.

**Also done:** the `STEP` progress channel and `RECV`, described above;
`parse_progress()` and `SerialProgress` in `link.py`; `MockBoard` emits the
same stream so the whole console can be exercised off-rig; and the web
console's `/api/events` carries each phase as a `build_step` event with a
server event id (`python/web/events.py`).

**Not done and next:**

1. **Flash it and watch.** `./scripts/flash.sh`, then open `rig_console.py` and
   look for `@0 BOOT` / `@0 READY`. Send a deliberately bad `B 1` and expect an
   `@n ERR`. `link.py` falls back to the prose if they are missing, so this
   step confirms the fast path rather than enabling it.
2. **Delete the fallback** once `prose_fallbacks` has stayed at 0 for a while.
   `_prose_outcome()` and the `done=` strings in `link.py` are the code that
   goes.
3. **Watch the airtime on a real board.** Fourteen `STEP` lines is ~0.3 s of
   9600-baud airtime by arithmetic, and arithmetic is not a measurement. If a
   flashed rig shows the phases arriving late or the terminal ack delayed, the
   fix is fewer fields per line — not more baud, and not fewer phases.

Everything else in this note — `RECV`, `BUSY`, `RUN`, the code table — is
optional and waits for a reason to exist. Prose is never removed.

## Costs

- **Flash:** small, and there is room — the sketch uses 15%.
- **SRAM:** near zero if every literal stays in `F()`. This is the one rule.
- **Airtime:** at 9600 baud an ack line is ~20 ms. Irrelevant either way — the
  banner already costs far more than the acks ever will.
- **Two things to keep in sync:** the kind and code tables here, and the parser
  on the Pi. That makes them a shared value — they get a row in `AGENTS.md`.
- **Three things, now:** the fourteen `phase` identifiers are a shared value
  too. They exist in `buildStep()`'s call sites, in `MockBoard.BUILD_PHASES`
  and in `web/src/studio/twin.ts`'s `PHASE_BY_ID`, and a UI that switches on a
  phase id breaks silently if the sketch renames one.

# Design note — an acknowledgement protocol

**Status:** the safety subset is **built in `build_test_v1`**. Compile-checked
and its output verified byte-for-byte on a host build — **but never flashed to
the board.** The Pi reads it in `python/rig/link.py`, which falls back to prose
matching (loudly) for exactly that reason. The watchdog is deliberately not
built; see below.

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
| `RECV` | no | parsed, accepted, about to run |
| `BUSY` | **yes** | refused — something is already running |
| `ERR` | **yes** | refused — bad syntax or out of range. **Nothing moved.** |
| `RUN` | no | progress: `RUN 8/14 travel` |
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
    kind: str            # RECV BUSY ERR RUN OK SAFE HELD BOOT READY LIMIT NOTE
    args: list[str]
    fields: dict[str, str]

TERMINAL = {"OK", "SAFE", "HELD", "ERR", "BUSY"}
```

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

**Not done and next:**

1. **Flash it and watch.** `./scripts/flash.sh`, then open `rig_console.py` and
   look for `@0 BOOT` / `@0 READY`. Send a deliberately bad `B 1` and expect an
   `@n ERR`. `link.py` falls back to the prose if they are missing, so this
   step confirms the fast path rather than enabling it.
2. **Delete the fallback** once `prose_fallbacks` has stayed at 0 for a while.
   `_prose_outcome()` and the `done=` strings in `link.py` are the code that
   goes.

Everything else in this note — `RECV`, `BUSY`, `RUN`, the code table — is
optional and waits for a reason to exist. Prose is never removed.

## Costs

- **Flash:** small, and there is room — the sketch uses 15%.
- **SRAM:** near zero if every literal stays in `F()`. This is the one rule.
- **Airtime:** at 9600 baud an ack line is ~20 ms. Irrelevant either way — the
  banner already costs far more than the acks ever will.
- **Two things to keep in sync:** the kind and code tables here, and the parser
  on the Pi. That makes them a shared value — they get a row in `AGENTS.md`.

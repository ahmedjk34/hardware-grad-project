# Placement supervision — the build record

**Companion to [placement-supervision.md](placement-supervision.md), which is the
design.** That document says what should be built and why. This one says what
*was* built, what the rig actually measured, which of the design's assumptions
survived contact with it, and what is still open.

Read this before continuing the implementation. Several of the design's numbers
were placeholders and are now measured; two of its decisions were found to be
wrong or under-specified; and one defect in the first implementation would have
stopped the machine permanently on a correct board.

**Status: COMPLETE. Gate 0 passed on the rig. M1, M2, M3a and M3b are built,
wired and tested. All seven P-decisions are resolved. M4 and M5 remain future
work, deliberately.**

> **Nothing here has been watched on hardware.** Every path is tested and Gate
> 0's constants were measured on the rig, but the wired code has never seen a
> real frame — there is no camera on the development desktop. A bench session is
> M2's last open item.

---

## 0. Timeline of what happened

| Stage | Outcome |
| --- | --- |
| Gate 0 script written | `python/tools/measure_quiet_window.py`, analysis half verified on synthetic rows |
| M1 built in parallel | ledger + hook + log + 42 tests, all passing |
| M2 logic built (ungated) | classifier, pixel→cell, hysteresis, ceiling, D10 — 55 tests |
| **Gate 0 run 1 on the rig** | Board hand-scattered. Q1 passed; Q2/Q3 apparently failed |
| Cause diagnosed | The board state was invalid, not the detector — see F4 |
| **Gate 0 run 2 on the rig** | Board rig-placed. Q1/Q2/Q3 all pass decisively |
| Defect found in M2 | `cell_at → None` conflation. Would emit FOREIGN in 99.8% of windows |
| Defect fixed + verified | Replayed the rig CSVs through the real `Supervisor` |
| Constants set from measurement | `0.01 / 3 / 5` |
| M2 tests extended | 63 checks, all passing |
| **P1-P7 put to the user** | P1 yes, P2 yes, P5 left to the user; P3/P4/P6/P7 done in passing |
| P1 + P2 built | `classify()`'s one-sided rows, `note_regime()`; 73 checks |
| P6 + P7 built | CSVs committed, replayed through the real `Supervisor`; 23 checks |
| **M2 wired** | supervisor into `_drive_pipeline`; two defects found (F14, F15) |
| **M3a built** | per-build verdict; two more design corrections (F17, F18) |
| **M3b built** | `SupervisionModel`, the ack route, all four UI surfaces |
| The three "pre-existing" test failures fixed | all three were test bugs (F20); `pytest` is 94/0 |

---

## 1. GATE 0 — the measurement record

**This section is the evidence base for every constant in `rig/supervisor.py`.
Do not change those constants without re-running the script and updating this
section in the same commit.**

### 1.1 Method

`python/tools/measure_quiet_window.py`, run on the Pi with the rig parked.
It opens the camera through `ConsolePipeline` exactly as the console does —
same `camera_settings.json`, same colour correction, same lens map, same 10 Hz
`AnalysisWorker` — so the numbers describe the frames supervision will actually
see. It adds no detector and takes no extra frames.

Per frame it logs the channel-max frame-difference energy fraction (the
`_difference_sightings` pattern, `DIFF_MIN_THRESHOLD = 18` as the per-pixel
level), the detection count, and what `WorkspaceMap.cell_at` assigns each
detection to.

**The pipeline delivers 8.6–8.7 Hz, not the nominal 10.** Every duration below
is computed at the measured rate.

### 1.2 The runs

Four runs across two sessions on 2026-09-07. Session 1 (`09:06`) used a
**hand-scattered** board and is retained here only because its failure is
instructive. Session 2 (`09:26`/`09:33`) used **five rig-placed blocks** at
cells `(0,2) (2,0) (2,1) (3,2) (4,4)` — this is the valid measurement.

| Run | Board | Frames | Duration | Rate |
| --- | --- | --- | --- | --- |
| parked (s1) | hand-scattered | 523 | 60.0 s | 8.7 Hz |
| hand (s1) | hand-scattered | 175 | 20.0 s | 8.8 Hz |
| program (s1) | near-empty, program running | 528 | 59.9 s | 8.8 Hz |
| **parked (s2)** | **5 rig-placed** | **524** | **60.0 s** | **8.7 Hz** |
| **hand (s2)** | **5 rig-placed** | **174** | **19.9 s** | **8.7 Hz** |
| **split (s2)** | **5 rig-placed** | **172** | **20.0 s** | **8.6 Hz** |

`calibrated = True` on every frame of every run. Zero stale frames throughout.

### 1.3 Q1 — does the quiet window ever open?  **YES, decisively**

Frame-difference energy fraction:

| percentile | parked (s2) | hand (s2) | program |
| --- | --- | --- | --- |
| p50 | 0.000000 | **0.070745** | 0.013617 |
| p90 | 0.000031 | 0.105991 | 0.051109 |
| p95 | 0.000089 | 0.114368 | 0.057187 |
| p99 | **0.000573** | 0.129459 | 0.063120 |
| max | **0.003855** | 0.137254 | 0.089039 |

> **A hand over the board reads 105× the parked median.** The still floor and
> the disturbed ceiling are separated by more than an order of magnitude, so the
> threshold sits in a wide empty band rather than on a judgement call.

This is the single most important result in the project's camera work. It
retires the risk that supervision would sit at `BUSY` forever and silently do
nothing.

### 1.4 Threshold selection

| `QUIET_DIFF_FRACTION` | parked quiet | hand quiet | program quiet | program runs ≥5 |
| --- | --- | --- | --- | --- |
| 0.001 | 99.0% | 4.6% | 37.5% | 9 |
| 0.002 | 99.2% | 5.2% | 39.8% | 8 |
| 0.004 | 99.8% | 6.3% | 41.5% | 9 |
| 0.005 | 99.8% | 6.3% | 42.6% | 9 |
| 0.008 | 99.8% | 8.0% | 45.1% | 9 |
| **0.010** | **99.8%** | **8.6%** | **47.3%** | **9** |
| 0.020 | 99.8% | 16.1% | 58.9% | 11 |
| 0.050 | 99.8% | 33.9% | 88.1% | 11 |

**Chosen: `QUIET_DIFF_FRACTION = 0.01`.**

Reasoning, in order:

1. It is **4× above the worst parked maximum observed** (`0.003855`), so a
   slightly different lighting day does not push the still board over it.
   `0.005` was the first candidate and was rejected for exactly this: it sits
   only 1.3× above that maximum, which is not headroom.
2. It is **7× below the median hand disturbance**, so a person reaching into
   the workspace is never mistaken for stillness.
3. Above `0.02` the hand-quiet fraction climbs sharply (16.1%, then 33.9%),
   which is the threshold starting to admit real motion.

The design's placeholder was `0.02`. It works, but sits only 1.5× under the
hand p25 and is the looser of the two.

**The ~6–9% of "quiet" frames in the hand run are not leakage** — they are the
genuinely still moments between waves. Correct behaviour.

### 1.5 Q2 — is detection stable frame to frame?  **YES, when rig-placed**

Parked (s2), five rig-placed blocks, 524 frames:

| cell | frames seen | recall |
| --- | --- | --- |
| (0,2) | 523 | 99.8% |
| (2,1) | 523 | 99.8% |
| (3,2) | 523 | 99.8% |
| (4,4) | 523 | 99.8% |
| (2,0) | 510 | **97.3%** |

Split run (s2), 172 frames: all five cells at **99.4%**, and **171 of 171 quiet
frames matched the expected cell set exactly**. (The single miss in each run is
frame 1, before the analysis worker has produced anything.)

Detections were `6` in 522 of 524 parked frames — stable, no flapping.

### 1.6 Hysteresis, simulated against the real trace

N-of-M evaluated over the actual parked (s2) frame sequence, per cell:

| | worst cell reads occupied | spurious `REMOVED` |
| --- | --- | --- |
| 2 of 3 | 97.70% | 2.30% |
| **3 of 5** | **98.65%** | **1.35%** |
| 4 of 6 | 98.07% | 1.93% |

**Chosen: `SETTLE_N = 3`, `SETTLE_M = 5`** — 0.58 s at the measured 8.6 Hz.

This is a measured optimum, not a default: **both neighbours are worse.** The
design's placeholder happened to be right, which is worth stating explicitly so
nobody later "improves" it to 4-of-6.

On the cleaner split run, 3-of-5 read every cell occupied **100.00%** of the
time.

> **Residual, stated honestly:** 1.35% is not zero. At ~9 windows/minute that is
> roughly one false pause every 8 minutes, so a 40-block build should expect
> ~3 spurious `REMOVED` verdicts. D12's dismissal covers it. It is not free and
> the operator should be told to expect it.

### 1.7 Q3 — do cells assign consistently?  **YES**

- 171/171 quiet frames matched the expected cell set exactly (split run)
- Zero frames ever reported an **extra** cell; the detector under-reports and
  never over-reports
- In the invalid session-1 run, even there, when the block *was* detected it
  mapped to `(3,2)` **99.0%** of the time — cell assignment was never the
  problem, detection was

### 1.8 Timing during a running program

At `0.01`: **47.3% of frames quiet, 9 runs of ≥5 consecutive quiet frames per
60 s.**

> **The quiet window opens roughly every 6–7 seconds during a running program**,
> not merely between whole jobs. Supervision is not restricted to a
> between-jobs activity, and `SETTLE_N = 3` is comfortably achievable mid-run.

This answers M2's own gate question, which the parked runs could not.

### 1.9 End-to-end replay through the real classifier

The rig CSVs were replayed frame by frame through the actual `Supervisor`,
with a ledger primed with the five placed cells:

| run | verdict distribution |
| --- | --- |
| split (clean, 5 detections) | **98.3% VERIFIED**, 1.2% WARMING, 0.6% BUSY, **zero false verdicts** |
| parked (6 detections, one off-board object) | **98.1% VERIFIED**, 1.3% REMOVED, 0.4% WARMING, 0.2% BUSY |
| parked, with the pre-fix merged behaviour | **99.8% FOREIGN** |

The 1.3% `REMOVED` matches the 1.35% predicted from `(2,0)`'s recall — the
model and the rig agree.

---

## 2. FINDINGS

### F1 — The quiet-window interlock works, with an enormous margin

§1.3. Not marginal, not tuned into working. 105× separation.

### F2 — The pipeline runs at 8.6–8.7 Hz, not 10

`analysis_hz` is configured at 10.0 but the delivered rate is consistently
8.6–8.7. Every settle duration must be computed at the measured rate:
`SETTLE_M = 5` is **0.58 s**, not 0.5 s. Not investigated further; it does not
affect any decision here, but a UI that displays a settle countdown must not
assume 10.

### F3 — `_lattice_filter` is not a board-membership test

This is the finding that drove the defect fix, and it contradicts an
assumption implicit throughout the earlier design work.

The filter recovers a lattice **from the detections themselves** and rejects
anything more than `LATTICE_SNAP` (0.34 cells) from an integer site. That
lattice is **infinite** — indices are real numbers extrapolated from
`detections[0]`. An object well off the board can still land within 0.34 of an
integer index and survive.

Evidence: in the parked (s2) run, one off-lattice object persisted in **523 of
524 frames** *with the filter engaged* (6 detections ≥ `MIN_LATTICE_BLOCKS`).
It was not rejected.

> **`_lattice_filter` asks "is this on the lattice", never "is this on the
> board."** Only the calibrated `WorkspaceMap` can answer the second question,
> and supervision must ask it itself.

### F4 — A hand-scattered board measures the detector at its worst

Session 1 appeared to show catastrophic detection: 16.1% of detections landing
on a cell, only one cell ever occupied, and **64.8% recall** on the one block
that mapped.

None of that was a property of the detector. With blocks scattered by hand:

- most blocks sit in the **gaps** between lattice sites, so `cell_at` correctly
  returns `None` for them — they are not on build sites
- detections hovered at 5–6, **flapping across `MIN_LATTICE_BLOCKS` 188 times
  in 522 frames**, so the lattice filter switched on and off frame to frame
- with the filter off there is no rectification, and no shared size or bearing

The correlation is decisive:

| detections | (3,2) present |
| --- | --- |
| 5 (filter OFF) | 43.4% |
| 6 (filter ON) | **99.0%** |

Rig-placed, the same measurement gave 97.3–99.8%.

> **Any future camera measurement must use rig-placed blocks.** A hand-scattered
> board is not a weaker version of the real thing; it is a different regime in
> which the filter cannot function.

### F5 — DEFECT (fixed): `cell_at → None` conflates three different facts

The first `supervisor.py` counted every `cell_at → None` as one `off_lattice`
number and `classify()` read any of it as `FOREIGN`. Its own docstring defended
this, claiming the split "would need the envelope quad".

**Measured consequence: `FOREIGN` in 99.8% of windows on a completely correct
board.** The machine would have stopped permanently.

The split is available from the existing API — `normalized_at()` returns
`(u,v)`. `rig.supervisor.locate()` now mirrors `cell_at`'s own branches:

| placement | meaning | supervision |
| --- | --- | --- |
| `cell` | on a real build site | occupancy |
| `gap` | **inside the envelope AND the grid allocation, between block footprints** | real `FOREIGN` — a block on the board, on no site |
| `margin` | inside the quad, outside the grid's cm allocation | **ignored** |
| `outside` | outside the envelope quad — frame-edge rails, offcuts beside the holder | **ignored** |

Only `gap` is evidence. `Observation` now carries `in_gap` and `off_board`
separately; `classify()` takes `in_gap` and never sees `off_board`.

A regression test asserts an off-board detection never produces `FOREIGN`.

**Note on vertical:** the grid allocation spans −1.10…23.90 cm against a 22.8 cm
envelope — it is *wider* than the frame because of the half-block overhang — so
`margin` is unreachable in vertical mode. Everything is `gap` or `outside`.
That is correct, not a hole in the instrumentation.

### F6 — The off-board object proved removable, and vanished mid-investigation

The persistent object present in 523/524 parked frames was **absent from all
172 frames** of the split run taken seven minutes later, with the same five
blocks in the same five cells.

**It was therefore never classified as `gap` vs `outside`.** The instrument
built to answer that question ran after the object had gone.

This is recorded as an open loop rather than papered over. It does not block
progress: because the object proved removable it is not permanent furniture, and
the split behaves correctly either way — if it returns in a gap, `FOREIGN` is
the right call and the operator clears it; if outside, it is ignored.

### F7 — The filter's 30% self-disable is weakest exactly when the board is most wrong

```python
if len(kept) < 0.7 * len(detections):
    return list(detections), [], None
```

If a recovered lattice would reject more than 30% of what it saw, the filter
concludes it has not found the board's lattice and keeps everything.

That is right for a *drawing* layer. But it means that when several blocks
genuinely move — the `DISAGREES` case — junk rejection **degrades at the exact
moment a clean observed set matters most.** Nothing in the design covers this.
See P4.

### F8 — The `MIN_LATTICE_BLOCKS` boundary is a cliff, and detection counts cross it

The threshold is binary at 6, and it counts **detections, not blocks** — so junk
counts toward reaching it. In the parked (s2) run, 5 blocks + 1 off-board object
= 6 detections: *the offcut is what pushed the filter over its own threshold.*

Rig-placed the count was stable (6 in 522/524). Hand-scattered it flapped 188
times, meaning the *character* of the observed set changed between consecutive
frames that hysteresis treats as comparable evidence. See P2.

### F9 — D10's stated rationale is wrong; its conclusion is right

The design justifies suppressing `FOREIGN` below 6 detections on the grounds
that *"the observed set is unfiltered"*. Per F3 and F5, the lattice filter was
never supervision's defence against junk — `locate()` is, and it works at any
detection count.

The **real** reason to keep D10: AGENTS.md names *"the holder's two small
offcuts beside `[0,0]`"*. Beside `[0,0]` means **on the board** — inside the
envelope — so `locate()` will class them as `gap`, and D9 makes a gap detection
`FOREIGN`. Which is *strictly correct* and *operationally intolerable*: a red
stop-the-program verdict because two offcuts are sitting where they always sit.

D10 is not buying filtering. It is buying **restraint about the loudest verdict
during the phase of every program when the board is emptiest and the
junk-to-block ratio is worst.** Same fail-open instinct as `block_outline`,
pointed the other way: one refuses to hide a block, the other refuses to raise
an alarm.

See P3 — the code comment currently states the wrong reason, and a rule
documented with a reason that does not hold is a rule someone later deletes.

### F10 — `test_grid.py` is failing on an unrelated firmware change

```
FAIL  rig sketch phase 5 uses zGoPickup(), not zGoGround()
```

`test_grid.py` passed 234/0 at the start of this work and now reports 233/1.
The cause is user commits `7983d32` and `26f5ad3`, which changed the firmware:
the sketch now reads *"DISABLED — build phase 5 now goes back to a GROUND seek…
nothing calls `zGoPickup()` any more"*, and `GRID_BLOCKED_COUNT` was cleared
for a variant with no feeder belt.

This is exactly the paired-value drift `test_grid.py` exists to catch. It makes
**AGENTS.md stale in two places**: the "one documented exception" section
explaining `Z_PICKUP_DROP_FROM_TOP_CM`, and §3b-bis's shipped `blocked_cells`
list.

**Not touched by this work** — `arduino/` is out of scope — but recorded because
it is failing now, and because it matters here: if the belt is gone, the cells
around `[0,0]` are buildable again, which changes what supervision expects.

### F12 — Three of the four Gate 0 CSVs predate the gap/margin/outside split

Found while building the replay test (P6). Only `gate0_split.csv` carries
`in_gap`, `margin` and `outside`; `parked`, `hand` and `program` were written by
the earlier version of `measure_quiet_window.py` and log one merged
`off_lattice` column.

This is **F6 restated as a data fact**: the splitting instrument was built after
the off-board object had gone, so the run that contains the object is the run
that cannot classify it. The three older files can never answer "gap or
outside?" and no amount of re-reading them will change that.

`test_supervisor_frames.py` states this rather than working around it. It
replays those runs with `in_gap = 0` — the reading that holds if the object is
off the board — and separately replays the parked run with
`in_gap = off_lattice`, which reproduces the **pre-fix merged behaviour** from
the column the CSV actually has. Measured on replay: **99.4% FOREIGN**, against
the 99.8% recorded in §1.9. The regression is therefore asserted from real
data rather than from a synthetic stand-in.

### F13 — The replay reproduces §1.9 to within a tenth of a percent

`test_supervisor_frames.py` runs all four traces through the shipped
`Supervisor` on every commit. Against §1.9's hand-run figures:

| run | §1.9 recorded | replayed in the test |
| --- | --- | --- |
| split | 98.3% VERIFIED, zero false verdicts | **98.3% VERIFIED, zero false verdicts** |
| parked | 98.1% VERIFIED, 1.3% REMOVED | **98.1% VERIFIED, 1.34% REMOVED** |
| parked, pre-fix merge | 99.8% FOREIGN | **99.4% FOREIGN** |

The residual `REMOVED` verdicts are asserted to name **exactly `(2,0)`** — the
97.3%-recall cell — not merely to be few. A rate assertion would pass on a
board renumbered by one cell.

Two things the trace shows that were previously only argued:

- **The split run sat below `MIN_LATTICE_BLOCKS` for all 172 frames** (5
  detections, filter never engaged) and was still flawless. That is Q6's answer
  measured rather than reasoned.
- **The interlocks are asked before the memory is.** Frame 1 of every run has no
  difference baseline, so it reports `BUSY`, not `NO_MEMORY`. Correct ordering —
  "the scene was not still" precedes "there is nothing to compare it to" — and
  worth knowing before a UI renders the first frame after a restart.

### F19 — D12's dismissal cannot be a per-cell mute, and the code says why

D12 asks for two things that pull against each other: the notification carries
its own dismissal, *and* **"after a dismissal the cell is re-checked in the next
quiet window before the runner continues."**

Implemented as: `POST /api/supervision/ack` sets `acknowledged` **and resets the
supervisor's hysteresis**, and `_note_supervision` clears `acknowledged` the
moment the reading CHANGES — a different verdict, or the same verdict naming a
different cell. So an acknowledgement silences the banner for that event only;
the next window re-judges from scratch, and if the block is still gone the
verdict comes back.

That is the intended behaviour and it is worth stating plainly, because it will
look like a bug the first time someone dismisses a `REMOVED` and watches it
return: **a repair that is not re-verified is a guess with extra steps, and that
applies just as much to a human's repair as to a machine's.** The hysteresis
reset is what stops the re-check being made of frames taken while the
operator's hands were over the board. A persistent "I removed this
deliberately, stop asking" mark is future work, and D12 already says so.

### F17 — The per-build check cannot use a frame difference without Gate 0b

D8a specifies the per-build check as *"a frame difference against the pre-build
frame"*, and it is **not level-blind** because the block just placed is the top
of its stack.

The first half needs a number nobody has measured. Gate 0 measured the
**full-frame** difference fraction that separates a still scene from a
disturbed one; a per-cell "did this cell change enough to be a new block"
threshold is a different quantity on a different denominator — one cell is
~1/42 of the board, so the parked noise floor inside it does not follow from
the full-frame one by any arithmetic. Guessing it would put an unmeasured
threshold on a rig, which is the exact failure `Supervisor.__init__` refuses to
allow for the other three constants.

**Built without it, and the carve-out is honest rather than silent:**

| level | cell reads | reported |
| --- | --- | --- |
| 0 | occupied | `verified in frame at [c,r]` — decisive, the ledger says it was empty |
| 0 | empty | `not detected at [c,r]` — decisive |
| 1-2 | empty | `not detected at [c,r]` — **still decisive; that is a tower that fell** |
| 1-2 | occupied | `unconfirmed` — an overhead camera cannot tell a stack that grew from one that did not |
| ≥ 3 | either | `unchecked — above the detection ceiling` (D6) |

Short towers are mostly level 0, so the feature still earns its place. **Gate 0b
is the measurement that would lift the `unconfirmed` row**: park the rig, log
the per-cell change fraction across a placement at level 1, and find the band
between "nothing happened here" and "a block landed here". Same instrument
shape as `measure_quiet_window.py`, restricted to one cell polygon.

### F18 — §2b's "zero client work" was wrong, and the reason is timing

The design's best piece of news was that the per-build verdict's client path is
wired end to end, so *"publishing one string field from Python lights up the
runner log AND the thesis run report with zero client work."*

Half of it held. **The run-report column is genuinely free** — `run-report.ts`
already emits `RunLogEntry.verification`. **The runner log row was not**, and
the reason is not a gap in the wiring:

`RunnerPanel.tsx` reads `vision_verification` **at the moment of the
`build_result` event** and writes the log row there. But the verdict cannot
exist at that moment. The rig has only just parked; D5 requires a still,
settled scene, which is another ~0.6 s at the measured 8.6-8.7 Hz. At settle
time the field necessarily reads `checking — waiting for a still frame`.

Three ways out were considered. Delaying `build_result` until the check
resolves is unthinkable — it is the terminal event and F15 shows how tight the
ordering around it already is. Leaving the row unverified throws away the
milestone's whole point. So: one `build-verified` RunEvent, ~10 lines in
`runner.ts`, which patches the newest build row in place. The browser still
never derives a verdict — it renders the server's sentence verbatim.

### F14 — DEFECT in the design: D5's "gantry parked" gate does not work

D5 specifies the parked interlock as `not job.running` **and**
`not controller.locked` **and** `cell_phase == "idle"`. The third clause is
wrong, and wrong in the silent direction.

`CellOrchestrator._phase("complete")` is **terminal and sticky** — nothing
resets it. `cell_phase` reads `idle` only before the first cell operation of a
process; from the first placed block onward it reads `complete` until the next
build starts. Gating on `"idle"` would therefore hold supervision at `BUSY` for
the whole of every session after block one, producing no verdicts at all, with
no error and nothing on screen to say so.

Built as `rig.supervisor.PARKED_CELL_PHASES = ("idle", "complete")` — the
phases in which no cell operation is in flight. The complement (`feeding`,
`staging`, `ready_for_pick`, `placing`, `error`) refuses. Conservative on
purpose: a false `BUSY` costs one window out of the ~9 a minute §1.8 measured,
and a false quiet costs a wrong verdict. `web_supervision_test.py` asserts
`complete` is parked, with the reasoning in the test's own docstring.

**This is the third place the design was found wrong on contact with the
code.** Like the other two it was found by reading, not by a rig.

### F15 — Supervision must be the LAST work in the driver loop, not the first

Found by a test regression, and it is an ordering hazard the loop already had
latently.

`_drive_pipeline` calls `job.poll()` and then `_publish_build_result`. Between
those two, `controller.last_result` already reads `placed` while the durable
`build_result` event has not gone out. **Any `await` in that gap** hands the
loop to a queued `_cell_phase` / `_serial_*` callback, each of which calls
`publish_state(app, force=True)` — and a state snapshot then claims
`last_result=placed` before the terminal event. `_cell_phase` has a comment
guarding exactly this, and `web_events_test.py::test_nothing_says_placed_
before_the_terminal_acknowledgement` asserts it.

The hazard pre-dates supervision — the JPEG encode awaits in the same gap — but
only when `stream_subscribers > 0`, which no test exercises. Supervision made
it unconditional: **4 of 6 runs failed** with the call placed after the encode,
**0 of 6** on a clean tree, and **0 of 6** once the call moved after the result
publish.

`_supervise` is now the last thing in the loop turn, which is also the right
priority: the serial stream is the important one, and supervision is the
lowest-value work in the tick.

### F16 — `web_state_test`'s heartbeat flake is ~50%, not "intermittent"

F11 recorded that test as flaky. Measured properly while chasing F15: **5 of 10
runs fail on a clean tree, and 5 of 10 with this work applied.** Identical, so
it is untouched by supervision — but "intermittent" undersells it. It is a
coin-flip, and any future bisect over this suite has to know that.

### F20 — The three "pre-existing" test failures were all test bugs, and are fixed

F11 and F16 recorded these as pre-existing and left them. Asked to fix them, all
three turned out to be defects in the TESTS, not in the code under test. None of
them needed a behaviour change.

**`web_state_test::test_events_send_initial_update_and_heartbeat`** — 5 of 10
runs on a clean tree (F16). It forced a state message and then demanded that the
*very next* frame be a heartbeat. But the pipeline driver is still publishing
geometry snapshots at `geometry_hz`, and with `heartbeat_s=0.02` in that test
one of them lands inside the 20 ms window roughly half the time. That is correct
server behaviour. The test now skips past state snapshots to find the heartbeat.
**0 of 10 after the fix.**

**`mock_camera_test::test_frame_pump_advances_then_becomes_stale_when_mock_is_frozen`**
— a race in the test. `camera.freeze()` cannot un-read a frame the reader thread
is already holding: it can be between `read()` returning and `LatestFramePump`
storing the result, so exactly one more sequence may land after the freeze. The
test sampled its baseline before that frame landed and then asserted "never
advanced again", when the claim it exists to make is "**stops** advancing". It
now lets the in-flight frame settle before taking the baseline.

**`mock_camera_test::test_warm_mock_blocks_are_detected_at_their_real_grid_cells`**
— a bad fixture, and an instructive one. It placed a block at `(3,5)`, which is
the outermost row. The mock maps the whole grid into the frame, so that row's
centre sits half a block from the frame edge: `(3,5)` lands at **y = 14.4 px on
a 720 px frame**, and a 36 px block is clipped by ~4 px, which drops it below
the contour checks. So the test was measuring the frame boundary, not the thing
its name claims. **A real camera sees well past the grid and nothing on the rig
behaves this way** — it is a property of the mock's framing alone. Moved to an
interior cell, with the reason written down so nobody "fixes" the detector for it.

The one failure that remains is **F10**, `test_grid.py`'s `zGoPickup()` check.
That is a firmware/AGENTS.md paired value, it is the user's own change, and
`arduino/` is out of this work's scope — P5, decided.

### F11 — One pytest failure is flaky, not a regression

`web_state_test.py::test_events_send_initial_update_and_heartbeat` fails
intermittently. Verified by stashing all work and running it four times on a
clean tree: it failed once there too. A heartbeat timing test.

---

## 2b. FINDINGS — 2026-09-07, the geometry-layer pass

### F21 — The old CORRECTION `1.2 cm` ceiling was a blunt proxy, and dead

`CORRECT_BAND_MAX_CM = 1.2` refused any `DISPLACED` correction past 1.2 cm on
the grounds the block's edge would foul a neighbour. It never checked whether
the neighbour was *there*, and a `DISPLACED` centroid is already ≥ half a block
off its cell, so the correctable window was ~1 mm in vertical X and **empty in
vertical Y**. Replaced with `placement_geometry.consistency()` (one straight
block, right footprint, not past a neighbour) + `corridor_clear()` (the
drifted-toward neighbour's ledger occupancy, jaw clearance on the drift axis).
`judge_band` keeps only the `0.5 cm` floor. New provisional constants
`SIZE_TOLERANCE_CM = 0.8`, `JAW_CLEARANCE_CM = 0.4` — Stage 15 Stage B.

### F22 — `classify` pairs `DISPLACED` cells by set difference and never checks proximity

One emptied cell + one gap detection → `DISPLACED [a,b]`, even when the gap
detection is a full grid away from `[a,b]`. On the rig this surfaced as a
verdict of "the block reaches 3.67 cm past its neighbour" for a block that
looked fine — the classifier had paired an unrelated gap reading with a cell
emptied elsewhere. `Supervisor.step(grid=…)` now runs
`implausible_displacement()`: `axis_coverage.beyond > PAIRING_BEYOND_CM` (1.0,
provisional) ⇒ the verdict is downgraded to `DISAGREES` with a reason naming
the distance. **A misregistered workspace map trips this on every displacement**
— the intended loud failure, instead of a confident wrong verdict.

### F23 — `_rectify` was erasing the one thing supervision needed

`block_outline._rectify` overwrites `width` / `height` / `angle` with the
population median and lattice bearing — correct for the overlay, wrong for
supervision, because a misplaced block *is* the wrong size or angle. `_rectify`
now copies the pre-rectification values to `BlockDetection.measured_*` first;
`own_size` / `own_angle` read them back. `observe()` uses `own_angle` and
projects `own_size`, not the rectified box. Off-lattice detections reach the
supervisor at all via `detect_aligned_blocks(include_rejected=True)`, which
`console_pipeline` now passes (BLOCK-VISION §2).

### F24 — `include_rejected=True` has an ungated edge: shape junk

Keeping off-lattice detections also keeps whatever the lattice filter rejected
that was *not* a block — a shadow, a rail, half an occluded block — and
`observe()` can count it as `in_gap` evidence, producing spurious FOREIGN /
DISPLACED / DISAGREES on an untidy bench. A block-shape gate for off-lattice
detections in `observe()` (rectangularity + solidity + `own_size` ≈ nominal ±
tolerance) was **proposed and not built** — the reverted change is the design
of record if it is picked up. The **detector itself is not regressed**:
`detect_blocks` / `detect_aligned_blocks` (default) give byte-identical counts
to the pre-pass code on every `python/captures/` image; the "detector broken"
report was a false alarm traced to this intake widening.

### F25 — Advisory residuals, published, rendered nowhere yet

`SupervisionModel` gained `residual_cm` (MOVED / DISPLACED offender distance)
and `max_cell_residual_cm` (worst on-cell drift, present for VERIFIED). Both
gate nothing and take no state colour. `types.ts` matches. **No UI renders them
yet** — they reach the client via `GET /api/state` only. Turning
`max_cell_residual_cm` into a `PLACEMENT_DRIFT` verdict needs the Stage 15 Stage
B placement-repeatability number to set the trigger, so it stays a field.

---

## 3. THE USER'S QUESTIONS — asked, answered, resolved

Recorded because several of them changed the design.

### Q1 — "What's left? Is all the other stuff dependent on Gate 0?"

**Answer.** No. Gate 0 gates two separable things: the **three constants**
(which only `supervisor.py` reads) and the **go/no-go bit** (which gates the
feature existing at all). Roughly three-quarters of the remaining code — the
classifier, pixel→cell, hysteresis, the ceiling, D10, the state model, the
route, all four UI surfaces — depends on neither and is testable from synthetic
cell sets with no camera.

**Resolution.** Built the ungated logic while the measurement was pending, with
the constants left as `None` and `Supervisor` refusing to construct without
explicit values, so nothing could ship a guessed threshold.

### Q2 — "Do you need the CSV or final output only?"

**Answer.** CSVs. The summary's buckets are six guessed candidate thresholds;
the per-frame table allows picking the threshold off the real distribution.

**Resolution.** Vindicated — `0.01` was chosen from the distribution and is not
one of the values the summary would have recommended.

### Q3 — "I placed the blocks by hand — is that the issue in detection failure?"

**Answer.** Partly, and the two halves separate cleanly. Hand-placing explains
the off-lattice flood (blocks in gaps are correctly `None`) and the "only one
cell" result. It does **not** explain the 65% recall — whether a block sits on a
site has no bearing on whether it is *visible*.

The real cause of the recall figure was the detection count flapping across
`MIN_LATTICE_BLOCKS`, so the filter and its rectification were intermittently
absent. See F4.

**Resolution.** Re-ran rig-placed → 97.3–99.8% recall. Q2 passes.

**Correction issued:** an earlier report of "cell assignment failing" was wrong.
When the block was detected it mapped correctly 99.0% of the time. Assignment
was never the problem.

### Q4 — "Why is the threshold 6 blocks? What happens before and after it?"

**Answer.** `_lattice_vectors` recovers the lattice from the blocks' own
pairwise neighbours — there is no external reference — and hard-raises below 4
sightings. Three or four points always define *some* lattice that fits them
perfectly, so "off the lattice" would mean nothing.

- **Below 6:** `return list(detections), [], None` — everything kept, nothing
  rejected, no shared bearing, no rectification.
- **At 6+:** lattice recovered, every detection indexed relative to
  `detections[0]`, anything >0.34 cells off an integer site rejected — then the
  30% self-disable (F7).

### Q5 — "Why did we enforce this boundary in the first place?"

**Answer.** Two different boundaries had been conflated.

`block_outline`'s 6 is a **fail-open safety rule for a drawing layer**: an extra
rectangle on the video is cosmetic, a missing one is a lie, so when the evidence
is thin it refuses to filter rather than filtering badly.

Supervision's D10 inherited that number for a different purpose, and on a
premise that does not hold. See F9.

### Q6 — "The camera has a grid. If I place a block there, it's just there — whether it's 1 or 6 blocks?"

**The most important question asked, and the answer reframed the feature.**

**Yes — for the block you placed, the count is irrelevant.** Confirmed by the
user's own data: the split run was *below* the threshold with the filter off for
all 172 frames, and was flawless.

The distinction the earlier explanations had buried:

> **`cell_at` answers *where*. Nothing in the vision stack answers *what*.**
> The detector segments warm, block-shaped things. An offcut is warm and
> block-shaped. Hand `cell_at` the centre of a shadow and it returns a cell.

Which splits supervision's questions in two:

| question | needs | works with 1 block? |
| --- | --- | --- |
| Is something at a cell **the ledger named**? | the map alone | **yes** |
| Is an object **nothing named** a block? | consistency with a population | **no** |

`VERIFIED` and `REMOVED` are about ledger-named cells and work at any count.
`FOREIGN` and `DISAGREES` are about unnamed objects, and identifying an unnamed
object requires other objects to be consistent with — which is what needs 6.

D10 does not mean "we cannot see your blocks below 6". It means **"below 6 we
will not accuse an unidentified object of being a foreign block, because we
would be guessing and the penalty is stopping your program."**

### Q7 — "What is DISAGREES?"

**Answer.** The classifier declining to guess. With one difference there is an
obvious story (`REMOVED`, or `MOVED` when counts match). With two or more, the
blocks are identical and carry no identity, so any pairing is a guess.

It is also **rarer than it sounds**: at 8.6 Hz with a 0.58 s settle, changes
arrive one at a time and decompose into clean single-cell events. `DISAGREES`
only fires when two changes land inside the *same* window — a person cannot lift
two blocks that fast; a toppling tower can.

Red, not amber: continuing to place into a board you no longer understand is how
the claw hits something.

### Q8 — "But we can tell what happened based on our memory and state, can't we?"

**Answer: yes, more than had been credited — and this question found a real
design error.**

What memory cannot supply is **identity**. The ledger records *"a block was
placed at [3,2]"*, not *"block #17"*. So when two cells empty and two fill in the
same window, memory cannot say whether the new occupant is either old block or
something new. Pairing them by proximity is exactly the data-association guess
D1 rejected.

**But pairing only matters when there is something to pair with.** If two cells
empty and *nothing unexpected appears*, there is no ambiguity at all: memory
says both were ours, the camera says both are gone, and no identity is required.
That claim is fully supported, and reporting `BOARD DISAGREES` there is *less*
informative than the truth.

**Resolution: D9 is over-conservative.** See P1.

---

## 4. DECIDED — the P-items, and what was done about them

**All seven were put to the user on 2026-09-07 and answered.** P1, P2 and P5 needed
a human; P3, P4, P6 and P7 were done in passing. Kept in full rather than
deleted, because the reasoning is the record.

### P1 — Refine D9's `DISAGREES` rows — **DECIDED: yes. Built.**

Arising from Q8.

| observed | design / current code | proposed |
| --- | --- | --- |
| N missing, 0 unexpected | `DISAGREES` | **`REMOVED`, naming all N** (amber) |
| 0 missing, N unexpected | `DISAGREES` | **`FOREIGN`, naming all N** (red) |
| missing **and** unexpected, >1 either side | `DISAGREES` | `DISAGREES` — genuinely ambiguous |

`DISAGREES` then means precisely *"both sides changed and I cannot pair them"* —
the only case that actually needs identity.

The counter-argument considered and rejected: *"several changes at once may mean
something systemic, like a camera bump."* A bump shifts everything — blocks
reappear at shifted cells or land in gaps — so it presents as missing **and**
unexpected, or as `in_gap`. It does not present as clean disappearance with
nothing gained.

**Side benefit:** the sparse-board special case that used to sit in `classify()`
(where multiple missing cells reported `REMOVED` because D10 banned
`DISAGREES`) became the general rule, and the special case is gone.

**Landed.** `classify()`'s two one-sided branches now name every cell on their
side, and `DISAGREES` is reached only when both sides changed by more than one
cell. `docs/features/placement-supervision.md` D9 carries the new table and the
deviation is called out there. `test_supervisor.py` asserts each row on exact
cell sets, including the shifted-board case that must still reach `DISAGREES`.

### P2 — Reset hysteresis on the `MIN_LATTICE_BLOCKS` crossing — **DECIDED: yes. Built.**

Arising from F8. Same argument as D13's mode reset: evidence gathered under one
filtering regime must not judge under another. The hand-scattered run crossed
that boundary 188 times in 522 frames.

**Landed** as `Supervisor.note_regime()`, called from `step()` beside the
existing `note_mode()`. It resets in **both** directions and only on a
crossing — a detection count that moves without crossing does not disturb a
settle in progress, which is asserted. `test_supervisor_frames.py` confirms the
crossing is real in the measured data: 6 crossings in the 174-frame hand run,
1 in the 524-frame rig-placed one.

### P3 — Correct D10's rationale in the code — **DONE**

Arising from F9. The `MIN_LATTICE_BLOCKS` docstring in `supervisor.py` and D10
in the design now both name the holder's offcuts beside `[0,0]` and state what
the rule actually buys — restraint about the loudest verdict when the board is
emptiest — instead of blaming the lattice filter.

The original note: The comment in `supervisor.py` currently blames the lattice
filter. It should name the holder's offcuts beside `[0,0]`. A rule documented
with a reason that does not hold is a rule someone later deletes correctly.

### P4 — Record the 30% self-disable in the design's known limits — **DONE**

Arising from F7. It is now `placement-supervision.md` §9's eighth limit, with
the point F7 makes: supervision does not *depend* on that filter (F3 —
`locate()` is its defence and works at any detection count), so the self-disable
costs the input's tidiness, not the classifier's correctness.

### P5 — The `test_grid.py` firmware drift — **DECIDED: the user is handling it**

Arising from F10. Put to the user, who confirmed they know it is failing and
will resolve it themselves. **Nothing in this feature touches it**, and it is
reported as a known failure in every gate below rather than fixed here.

It still leaves AGENTS.md stale in two places — the `Z_PICKUP_DROP_FROM_TOP_CM`
"one documented exception" section, and §3b-bis's shipped `blocked_cells` list —
and it still matters here: **if the belt is gone, the cells around `[0,0]` are
buildable again, which changes what supervision expects.** That is a fact about
the ledger's input, not about supervision's code, so nothing here needs to
change when it is resolved.

### P6 — `test_supervisor_frames.py` — **DONE, as the CSV replay**

The design's §8 asked for the two reference stills in `python/captures/`. The
rig CSV replay was chosen instead, for the reason §1.9 already implies: it is
stronger evidence and needs no OpenCV. **1398 frames the rig actually produced**
go through the shipped `Supervisor` on every run — real jitter, real dropouts,
real off-board junk — against boards whose contents are known exactly.

It reproduces §1.9 to within a tenth of a percent (F13) and asserts exact cell
sets throughout. The still-image test is **not** ruled out; it would test the
detector's reading of a frame, which is a different question and one no part of
supervision currently depends on.

### P7 — The Gate 0 CSVs — **DONE: committed under `docs/measurements/`**

`gate0_parked.csv`, `gate0_hand.csv`, `gate0_program.csv`, `gate0_split.csv`,
76 KB in total. Committing rather than deleting won on two counts: they are the
evidence behind every constant in §1, and P6 turned them into a **test fixture**
— deleting them would now delete a regression. `test_supervisor_frames.py`
reads them from there.

Note F12 before trusting them: three of the four predate the
`gap`/`margin`/`outside` split and carry one merged `off_lattice` column.

### P8 — Remove D10 / `MIN_LATTICE_BLOCKS` from supervision — **DONE**

The user took the holder off the rig and asked for the threshold gone. F9
already established its only surviving rationale was the holder's offcuts beside
`[0,0]` reading as `gap` → `FOREIGN`; F5's regression was fixed by `locate()`'s
three-way split, not by the count; F8 showed the boundary was a junk-inflated
cliff. With the holder physically gone, none of it holds.

Removed: `MIN_LATTICE_BLOCKS`, the `sparse` branch in `classify()` (and its
`detections` parameter), `Supervisor.note_regime` and `self._sparse`, and the
P2 `_lattice_filter`-crossing hysteresis reset. `Observation.detections` stays
as a display-only field.

Added in the same change: `in_gap` now goes through D7's hysteresis
(`Supervisor._gap_history`, `N of M` judged frames), because it was the one
signal that reached `classify()` straight from the current frame and D10 was
the only thing keeping single-frame centroid jitter from stopping the program
early in a build. Denoising only — it does not name the gap cell and is not the
`MOVED`-lands-in-a-gap fix.

Consequence, accepted with the user: `FOREIGN` / `DISAGREES` are now reachable
from block one, including on a restart with leftover blocks on the board (empty
ledger vs non-empty board). That is a correct verdict, not a false positive.

Re-verified: all four Gate 0 traces replay to **identical verdict tallies**
(`split` 98.3% VERIFIED / zero false verdicts; `parked` 514 VERIFIED / 7 REMOVED
at `(2,0)` / zero FOREIGN; `hand` all BUSY; merged-reading regression still
99.4% FOREIGN). `test_supervisor.py` 82 pass, `test_supervisor_frames.py` 21
pass, `web_supervision_test.py` +1 new (sparse-board FOREIGN through the seam).

### P9 — Split `MOVED` into `MOVED` + `DISPLACED`, keyed to the build area — **DONE**

The user asked for the verdicts to be defined by *where a block is relative to
the build area* (the rectangle of cells + the gaps between them, which
`locate()` already derives from the grid) rather than by bare set arithmetic.

- **`MOVED`** — one cell emptied, one different **cell** filled, no gap
  detection. `cells = (from, to)`.
- **`DISPLACED`** (new, amber) — one cell emptied, **nothing on a cell**,
  exactly one gap detection. The block was knocked off its site but is still in
  the build area. `cells = (from,)`, no arrow. Before this it was a red
  `FOREIGN` that named no cell — the bug the user opened the thread with.
- **`REMOVED`** — cells emptied and nothing arrived *anywhere in the build
  area*. Gained `and in_gap == 0`; copy hedged to "not seen on the build grid"
  because a block off a stack (limit 1) presents the same way.
- **`FOREIGN`** — a block in the build area (cell or gap) that nothing having
  left can explain.
- Ambiguous gap counts (`in_gap >= 2`, or one-in-one-out *and* a gap) →
  `DISAGREES`.

`classify()` lost its `in_gap`-first `FOREIGN` shortcut; the branch order is now
VERIFIED → MOVED → DISPLACED → one-sided FOREIGN → REMOVED → DISAGREES. No new
geometry — `observe()` already returned `in_gap` vs `off_board`. Needs no block
identity: the pairing holds because D5 guarantees the window has no occlusion
([block-identity.md](block-identity.md), written alongside this).

Plumbed through `state.py`, `types.ts`, `SupervisionActivity.tsx`,
`SupervisionBanner.tsx`, `GridOverlay.tsx`, `BuildMode.tsx`. `runner.ts` and the
scene overlays key off `severity`, not the verdict name, so no change there.

Re-verified: Gate 0 non-merged tallies **unchanged** (`in_gap == 0` throughout);
the merged-reading regression shifts 99.4% → 98.1% `FOREIGN` + 0.6% `DISPLACED`,
still stops-or-pauses on ~99% of a correct board. `test_supervisor.py` 89 pass,
`test_supervisor_frames.py` 21 pass, `pytest` 100 pass, `vitest` 556 pass.

---

## 5. What is built, and what is not

### Built and passing

| | |
| --- | --- |
| `python/tools/measure_quiet_window.py` | Gate 0 instrument. Splits `gap`/`margin`/`outside`, logs `(u,v)` |
| `python/rig/placement_ledger.py` | D2/D3/D4/D13 + Stage 15's two predicates. Pure data |
| `python/rig/build_log.py` | third `PlacementLog` sink → `logs/placements.log` |
| `python/rig/build_controller.py` | one call on the `PLACED` branch, behind `ledger=None` |
| `python/rig/supervisor.py` | `locate`, `observe`, `classify`, `verify_placement`, `quiet_fraction`, `_CellHistory`, `Interlocks`, `Supervisor`; **+2026-09-07:** `_detection_size_cm`, `implausible_displacement`, `step(grid=…)` DISPLACED→DISAGREES gate, `Observation.{gap,cell}_sizes_cm` / `cell_residuals_cm` |
| `python/rig/placement_geometry.py` | **+2026-09-07:** `axis_coverage`, `consistency`, `corridor_clear`, `residual_cm`, `drift_axis`, `displacement_cm`. Pure interval maths |
| `python/rig/placement_check.py` | CORRECTION geometry + policy; **+2026-09-07:** `1.2 cm` ceiling replaced by `consistency` + `corridor_clear`, `SIZE_TOLERANCE_CM` / `JAW_CLEARANCE_CM` |
| `python/vision/block_detector.py` `block_outline.py` | **+2026-09-07:** `BlockDetection.measured_*` / `own_size` / `own_angle` / `on_lattice`; `detect_aligned_blocks(include_rejected=True)`, passed by `console_pipeline` |
| `python/web/app.py` | `_supervise`, `_resolve_pending_check`, `_note_supervision`; ledger + supervisor owned by the lifespan; **+2026-09-07:** passes `grid` to `step()`, publishes `residual_cm` / `max_cell_residual_cm` |
| `python/web/state.py` | `SupervisionState`, `SupervisionModel`, `vision_verification`; **+2026-09-07:** `frame_residual_cm`, `worst_cell_residual_cm`, `residual_cm` / `max_cell_residual_cm`, `assess_frame_correction` drift-neighbour occupancy |
| `python/web/routes_command.py` | `POST /api/supervision/ack` (D12) |
| `web/src/components/SupervisionBanner.tsx` | the only surface allowed to alarm |
| `web/src/components/GridOverlay.tsx` | the per-cell verdict mark and the unjudged hatch |
| `web/src/studio/scene/Supervision.tsx` | the twin's overlay layer — not a sixth appearance |
| `web/src/studio/runner.ts` | `board-verdict` and `build-verified` events |
| `web/src/tokens.test.ts` | the contrast bar, read off the real stylesheet |
| `python/tests/web_supervision_test.py` | **26 tests** over the server seam |
| `python/tests/test_placement_ledger.py` | **42 checks** |
| `python/tests/test_supervisor.py` | **83 checks** — P1's rows, P2's crossing and D8a's sentences |
| `python/tests/test_supervisor_frames.py` | **23 checks** — the four rig traces, replayed |
| `docs/measurements/gate0_*.csv` | the four Gate 0 traces, now committed (P7) |

Test gate — M2 build (unchanged):

| suite | result |
| --- | --- |
| `test_placement_ledger.py` | 42 passed, 0 failed |
| `test_supervisor_frames.py` | 23 passed, 0 failed |

Test gate — after the 2026-09-07 geometry-layer pass:

| suite | result |
| --- | --- |
| `test_supervisor.py` | **111 passed, 0 failed** (was 83) |
| `test_placement_geometry.py` | **32 passed, 0 failed** (new) |
| `test_placement_check.py` | **41 passed, 0 failed** |
| `web_supervision_test.py` | **43 passed, 0 failed** (was 26) |
| `test_block_outline.py` / `test_block_detector.py` | all passed |
| `test_grid.py` | 241 passed, **1 failed** — F10, firmware drift, not this work (P5) |
| `npx vitest run` | **42 files, 563 tests, all passed** |
| `pytest tests/` (python) | all passed |

### Not built — the things left

- **A bench session.** The one item that cannot be done from this desk. The
  2026-09-07 camera-path changes (`include_rejected`, `measured_*` through
  `_rectify`, `own_size` box projection, `step(grid=…)`) are **unverified on the
  Pi**.
- **The off-lattice shape gate** (F24) — proposed, reverted, not built.
- **`PLACEMENT_DRIFT`** — a verdict off `max_cell_residual_cm`; needs Stage 15
  Stage B (F25).
- **Stage 15 Stage B bench numbers** — `SIZE_TOLERANCE_CM`, `JAW_CLEARANCE_CM`,
  `PAIRING_BEYOND_CM`, `CORRECT_BAND_MIN_CM` are all provisional (F21, F22).
- **Gate 0b** — the per-cell change threshold for a level-1/2 confirm (F17).
- **M4** — bounded automatic repair, deliberately off.
- **M5** — lifting the level-3 ceiling.
- **F10 / P5** — `test_grid.py`'s firmware drift. Not this feature's, by
  decision.

`docs/CAMERA.md` §0 and §6a **have been corrected**: the camera now makes an
assertion the system acts on, and those sections say so — along with the three
things that did *not* change (it never moves the rig, a verdict never `LOCK`s,
and `vision/` is untouched).

---

## 6. Rules for whoever continues this

1. **The constants in `supervisor.py` are measured.** Changing one means
   re-running `measure_quiet_window.py` on the rig and updating §1 here in the
   same commit.
2. **Any camera measurement uses rig-placed blocks.** F4. A hand-scattered board
   is a different regime, not a weaker one.
3. **`locate()`'s split is load-bearing.** F5. Never collapse `gap` and
   `off_board` back into one number; there is a regression test.
4. **`vision/` is not touched.** No detector, no extra frames.
5. **A verdict never sets `LOCKED`.** Amber pauses, red stops. `LOCKED` means
   the claw's position is unknown and needs a human plus a service restart.
6. **Assert exact cell sets, never counts.** A count assertion passes on a board
   renumbered by one cell.
7. **The frame difference goes on the single-threaded executor**, with the other
   OpenCV work, per AGENTS.md §7. The set maths stays on the event loop.
8. **`docs/measurements/` is evidence, not scratch.** Those four CSVs are now a
   test fixture. Deleting one deletes a regression; adding one means saying in
   §1.2 which board it was taken on and whether it was rig-placed (F4).

# Between-build error calibration — closing the loop on placement

**Status: DEFERRED (2026-09-06). Not a work item.** The project is doing
per-stage placement checkers instead — [stage-15-placement-correction.md](stage-15-placement-correction.md)
and the individual stage checkers — which judge and physically repair *one
outlier block at a time* rather than estimating a population-wide drift and
writing a calibration number back. Read
[§0a — Why this is deferred, and when to un-defer it](#0a-why-this-is-deferred-and-when-to-un-defer-it)
before assuming the per-stage checkers make this redundant: **they cover
outliers, not systematic bias.**

**Original status, still accurate as a description of the code: partially
implemented.** The measurement exists; the feedback path does not, and one of
the two things you might mean by this feature is physically impossible on
today's hardware.

---

## 0. Read the request precisely first

> *"Error calibration based on camera/grid — if a block is outside the grid you
> can move it slightly. This should run between builds and fix any errors before
> the next building process."*

That sentence contains two different features:

| Reading | What it means | Possible today? |
| --- | --- | --- |
| **(a) Correct the machine** | measure where blocks actually land, and move *future* placements so they land on the cell centre | **yes**, and that is what this document designs |
| **(b) Nudge the block** | reach out and physically push/re-place a block that landed badly | **no.** `B` is pick-**from-feeder**-then-place. There is no firmware verb that picks a block up off the board — the same finding as [feature-ideas.md §A.0](../feature-ideas.md#a0-what-already-exists-and-what-does-not) |

Reading (b) needs a new firmware command (`P <col> <row> <level>`, sketched as
Appendix A's milestone M5) and inherits a nasty new failure mode: a claw that
closes on nothing reports success. Do not smuggle it in as part of (a).

**This document is reading (a): a measured, bounded, between-builds correction to
the grid's own origin.** §7 says what it would take to add (b).

---

## 0a. Why this is deferred, and when to un-defer it

The decision (2026-09-06): **work each stage checker individually** instead of
building this. That is the right call *for outliers* and it sidesteps every
hard part of this document — no windowed mean, no deadband against the map's
0.27 cm noise floor, no persistent bias with provenance, no choice between the
three interchangeable-looking knobs (`trim` / `error_offset` / `shift`), and no
new firmware verb. [Stage 15](stage-15-placement-correction.md) judges one block
and takes a *physical* action; nothing is written to the grid.

**What deferring this gives up.** Per-stage / per-block checking catches a block
that landed *wrong once* — knocked, mis-gripped, a single bad placement. It does
**not** catch a *systematic* bias. If the machine lands every block, say,
0.4 cm toward the X home switch, Stage 15 will pick up and re-place block after
block, forever, chasing the same constant error, because it never updates
`error_offset_*`. This document's own §6 Q1 says it directly: *"Is the drift you
are chasing actually constant?"* — a constant offset across the whole board is
exactly what a per-block repair cannot fix and what this feature was for.

**The trigger to un-defer.**
[feature-ideas.md §3.1 — placement repeatability and backlash](../feature-ideas.md#31-placement-repeatability-and-backlash---highest-value-per-line)
is the measurement that says whether a systematic bias exists. If 3.1 comes
back showing a consistent directional offset (rather than symmetric scatter
about the cell centre), this feature comes back off the shelf and **Approach A
(advisory only, §4)** is the first thing to build. Until then it stays here,
unbuilt, as reference — the audit below and the sign-convention worked example
in §2 D5 are still correct and still worth reading before touching any
placement-correction code.

---

## 1. What exists today

| Piece | State | Where |
| --- | --- | --- |
| Machine-driven placed-block calibration, one cell per step | **exists** | [python/rig/block_calibration.py](../../python/rig/block_calibration.py) — `BlockCalibrationRun`, settle wait, abort discipline |
| The fit itself: homography / affine+curvature over placed blocks | **exists** | [python/vision/block_grid.py](../../python/vision/block_grid.py), `fit_block_grid`, `analyse_dense_lattice` |
| Per-cell residuals in pixels | **exists** | `BlockGridReport.residuals`, `mean_residual_px`, `worst_cell` ([block_grid.py:171](../../python/vision/block_grid.py#L171)) |
| Honest error of a *saved* map | **exists** | `workspace_map_error()` — **1.25 px mean / 2.07 px max = 0.27 cm** on the reference board ([block_grid.py:1054](../../python/vision/block_grid.py#L1054)) |
| Per-frame detections at 10 Hz, off-lattice ones rejected | **exists** | `block_outline.detect_aligned_blocks`, `ProcessedFrame.detections` |
| **detections labelled with an integer cell** | **does not exist** — earlier drafts of this table said it did. `_lattice_filter` solves indices *relative to `detections[0]`* only to decide keep/reject, then discards them; a `BlockDetection` carries a pixel centre and no cell. Pixel → cell is `WorkspaceMap.cell_at`, and it is the **consumer's** job. See [placement-supervision.md §2a](placement-supervision.md#2a-three-things-the-earlier-designs-got-wrong) |
| Cell ⇄ pixel geometry | **exists** | `WorkspaceMap`, [python/rig/workspace.py](../../python/rig/workspace.py) |
| Web routes for a calibration run | **exists** | `/api/calibration/block/{start,step,undo,cancel,save,status}` ([routes_calibration.py:179](../../python/web/routes_calibration.py#L179)) |
| `error_offset_x_cm` / `_y_cm` per mode, folded into the lattice origin | **exists** | [rig.json](../../config/rig.json), [grid.py:353](../../python/rig/grid.py#L353), `GRID_ERROR_OFFSET_X_CM[]` in the sketch |
| **px residual → cm correction in machine space** | **does not exist** | nothing converts a fit residual into a knob value |
| **anything writing `error_offset_*` back** | **does not exist** | the knob is hand-edited, in two files, per [AGENTS.md](../../AGENTS.md) |
| **a runtime firmware verb for the error offset** | **does not exist** | `GRID_ERROR_OFFSET_*` is compile-time. `shiftX`/`shiftY` is the *only* runtime lattice knob |
| **a between-builds trigger** | **does not exist** | `BuildController.build()` returns and nothing looks at the board afterwards |

So the calibration that exists answers **"where is the grid in the camera?"**
The feature asked for answers **"where is the grid in the machine?"** — and those
are different questions with a shared measurement.

---

## 2. The seven decisions

### D1 — The error is (commanded cell centre) − (observed block centre)

Both sides already exist. The commanded centre comes from `MachineGrid`
(`origin + i * pitch`, in cm). The observed centre comes from the detection the
vision pipeline already produces, pushed through the `WorkspaceMap` into cm.

Nothing new is measured. This is a **difference between two things the system
already knows**, which is what makes it tractable, and what keeps it out of
`vision/` entirely.

### D2 — The map's own error is the noise floor, and it is 0.27 cm

`workspace_map_error()` reports 1.25 px mean / 2.07 px max mid-grid, which is
0.27 cm on a 2.2 cm block. A four-corner map cannot carry the fit's curvature
([BLOCK-VISION §4](../BLOCK-VISION.md)), so that error is structural, not a bug.

> **A correction smaller than the map's own error is not a correction. It is
> noise with a decimal point.**

Deadband it. `0.3 cm` is the number the existing measurement justifies; measure
it on the real bench before trusting that figure, and print the deadband next to
the suggestion so nobody wonders why a 0.1 cm reading did nothing.

### D3 — A constant translation, and nothing else

Fit **two numbers** — an X offset and a Y offset, the mean over the placements
in the window. Do **not** fit pitch, rotation or scale from build residuals.

Pitch and bearing are what `analyse_dense_lattice` exists for, with a deliberate
dense fill and `MIN_DENSE_OBSERVATIONS` before it will speak. Three or four
opportunistic residuals from a normal build cannot separate a pitch error from
noise, and a per-build pitch fit will walk the whole lattice off the table over
a session. Two numbers is the whole model.

### D4 — Which knob, and the honesty problem

The lattice origin is `trim + error_offset + shift` — [grid.py:353](../../python/rig/grid.py#L353),
[coords.ts:97](../../web/src/studio/coords.ts#L97), and the same line in the
sketch. All three enter identically, which is exactly why they are separate:

> **`error_offset` is "the machine is off by this much". `shift` is "the operator
> wants the structure over there". A measured correction written into `shift`
> is a lie that will survive into the next session and be mistaken for intent.**

That is [AGENTS.md](../../AGENTS.md)'s rule, and it is the constraint that makes
this feature harder than the arithmetic suggests. See §4.

### D5 — Sign, from AGENTS.md Rule 0 and Rule 0a

Every calibration number is a **magnitude from that axis' home switch**:
`+` = away from home, `−` = toward home. `axisPos[]` on X runs the *opposite*
way; cross between the spaces only via `axisPosFromHomeSteps()` /
`axisStepsFromHome()`.

And Rule 0's third clause, which is the one this feature will get wrong:

> **A reported error and a requested placement take opposite signs.** "It landed
> 0.4 cm too close to home" wants `+0.4`. "I want it 0.4 cm toward home" wants
> `−0.4`.

The camera reports an **error**. So the correction is `+` when blocks land short
of the cell centre (toward home) and `−` when they overshoot. Write that as a
comment beside the arithmetic, and assert it in a test with a named, physical
scenario rather than a bare number — a sign bug here is invisible on Y and Z and
inverted on X.

### D6 — Only between builds, parked, quiet

Reuse the interlocks already designed in
[feature-ideas.md §A.4 (D4)](../feature-ideas.md#d4--judge-only-in-the-quiet-window):
gantry parked (`BuildController` idle and unlocked, `BuildJob.running` false),
frame-difference energy under a quiet threshold, and `N of M` settled frames.

Never mid-command. The arm is in the frame and the firmware is deaf.

### D7 — Bounded, opt-in, and it stops rather than saturating

- **Cap the correction.** Something like 1.0 cm. A measured error larger than a
  cap is *not* a bigger offset — it is a wrong mode latch, a knocked rail, a
  stale workspace map, or a block that was never placed. Show it, refuse it.
- **Cap the rate.** One adjustment per session, not per placement. A per-block
  integrator on a 0.27 cm noise floor is a control loop nobody designed.
- **Require an operator to accept it** unless explicitly armed, and log the
  before/after pair with the observations it came from.
- **Re-verify after applying.** A correction that is not re-measured is a guess
  with extra steps.

---

## 3. Where it would live

```
rig/placement_error.py     new   D1-D3 — residuals in cm, the windowed estimate
rig/calibration_bias.py    new   D4/D7 — the applied correction, its provenance,
                                 its caps, and its JSON under logs/
rig/build_controller.py    edit  record commanded cell + result (the ledger from
                                 feature-ideas.md A.1/M1 is the same hook)
rig/console_pipeline.py    edit  hand the quiet-window frame to the estimator
web/routes_calibration.py  edit  suggest / accept / clear
web/state.py               edit  surface the pending suggestion and the applied bias
web/src/…                  edit  a suggestion strip; before/after; provenance
```

`vision/` is **not touched**, on the same layering rule as
[BLOCK-VISION §7](../BLOCK-VISION.md): this is a fourth layer above
`block_outline` that consumes `ProcessedFrame.detections` and the `WorkspaceMap`,
adds no detector, and takes no extra frames.

**The ledger hook is shared with placement supervision, and it is now BUILT.**
`rig/placement_ledger.py` exists, written at the one `BuildController` hook. Do
not build a second one — this feature needs "which cell was
commanded, and did it settle" for exactly the same reason.

---

## 4. Four ways to apply the correction

### Approach A — advisory only *(build this first, always)*

Measure, print, and stop:

```
PLACEMENT DRIFT — 6 observations, vertical grid
  X: +0.34 cm  (deadband 0.30)  → suggest error_offset_x_cm 0.00 → +0.34
  Y: −0.08 cm  (inside deadband — no change)
Edit config/rig.json AND GRID_ERROR_OFFSET_X_CM[] in the sketch, then reflash.
```

**Difficulty 2 / 5.** No firmware change, no new write path, no way to move the
machine wrongly. It is also the part every other approach needs, so it is never
wasted work.

**Limit:** the operator must reflash. Two files, one commit, per AGENTS.md.

### Approach B — apply at runtime through `shiftX` / `shiftY`

It works *today* with no firmware change, because `shift` enters the origin
identically to `error_offset`. It is also the knob AGENTS.md says must never
masquerade as calibration.

If you do it, do it with the two numbers kept apart end to end:

- the server holds `operator_shift` and `calibration_bias` as **separate**
  values;
- what goes to the board is their **sum**, sent as `shiftX` / `shiftY`;
- the UI shows both, labelled, always;
- `config/rig.json`'s `shift_*_cm` is **never** written with a bias.

**Difficulty 3 / 5**, and the cost is real: `config/rig.json` and the board now
legitimately disagree, and `workspace.py`'s map-invalidation check (which
compares the saved map's `shift_*_cm` against the grid's) will trip on a
machine-generated number. Decide what that check should do *before* writing the
code, not after it starts failing.

### Approach C — a new firmware verb `errX <cm>` / `errY <cm>` *(the clean answer)*

Mirror `handleShiftCommand`: parse a signed cm value, write
`GRID_ERROR_OFFSET_*[gridMode]`, re-run the same fit checks `applyGridShift`
runs, answer with a `GRID ERROR OFFSET` line. The parser, the per-mode table,
the validation and the ack shape all already exist to copy.

Then in Python it is one more `_send_and_settle` beside `set_shift`, and
`connect()` replays it in the same mode → offsets → shift → `S` order.

**Difficulty 3 / 5 in code, plus a hardware trip.** There is **no local Arduino
toolchain** in this repo: syntax-check with a stub-Arduino `g++` harness, say
plainly that the result is unflashed, and pair the change in
[AGENTS.md](../../AGENTS.md) and `python/tests/test_grid.py` in the same commit —
`test_grid.py` parses the sketch and is the check that catches a knob edited in
one place only.

### Approach D — a per-cell correction table

Reject for now. The dense-lattice path already measures per-cell truth properly
when you deliberately fill the board; a per-cell table learned from incidental
build residuals needs far more data than a session provides, and it would encode
the workspace map's own 0.27 cm flattening error as if it were machine error.

### The hybrid — and it is the right answer

> **A → C, with B as a clearly-labelled interim.**

1. **A** first, unconditionally. The measurement is the feature; the application
   is plumbing. Ship it advisory, run it for a session, and check its suggestions
   against blocks you have measured with a ruler before anything applies
   anything automatically.
2. **C** when the sketch is next flashed anyway. It is the honest knob, it keeps
   `config/rig.json` and the board describing the same machine, and it is cheap
   in firmware because it is a copy of a pattern already there.
3. **B** only while C is unflashed, only with the two-number separation, and only
   with a visible "APPLIED AS SHIFT — NOT WRITTEN TO CONFIG" banner.

Future AIs: this is deliberately a **staged** hybrid, not a menu. Do not start at
B because it needs no reflash; B without A's measurement discipline is an
unbounded control loop wired to a machine.

---

## 5. Tests

| Suite | Checks |
| --- | --- |
| `tests/test_placement_error.py` (new) | commanded − observed in cm, sign-correct **on X specifically** (opposite `axisPos` direction); the deadband suppresses a sub-0.3 cm reading; the mean is over the window, not the last block; a rejected/aborted build contributes nothing |
| `tests/test_calibration_bias.py` (new) | the cap refuses rather than clamps; one adjustment per session; provenance survives a reload; clearing restores the config value exactly |
| `tests/test_grid.py` | **must be extended** if Approach C lands — it is the firmware ⇄ config pairing check, 221 checks today |
| `tests/test_link.py` | `errX`/`errY` (C) replayed in the right order on connect, and skipped when zero, exactly as `set_shift` is |
| `tests/web_calibration_test.py` | suggest / accept / clear routes; refused while a build is running |
| `web/src/…` | the suggestion strip renders both numbers and the provenance; a bias applied as a shift is visibly labelled as such |

Assert **named physical scenarios**, not bare numbers: *"blocks land 0.4 cm
toward the home switch on X → correction +0.4"*. A test asserting `0.4 == 0.4`
passes just as happily with the sign inverted.

Standard gate afterwards:

```bash
python3 python/tests/test_grid.py
cd web && npx vitest run
cd python && python3 -m pytest tests/
```

Known pre-existing failures (not regressions): `mock_camera_test.py`,
`test_combined_grid`, `test_color_tuning`, `test_camera_performance`,
`test_block_outline`.

---

## 6. Questions to answer before writing code

1. Is the drift you are chasing actually **constant**, or does it grow with
   distance from home? A growing error is a **pitch** error and this feature is
   the wrong tool — it will centre the middle and worsen both ends.
2. Is it the same in both grid modes? The knob is per mode; a single number
   applied to both is wrong by construction.
3. Does it change after a mode latch (which homes X and Y)? If yes, you are
   looking at backlash or a homing repeatability problem, not a lattice offset.
4. How many placements is a trustworthy window — and are you willing to wait
   that many before the first correction?
5. Who accepts a suggestion: the operator, or an armed automatic mode? What
   happens when the two disagree across a restart?
6. When a correction is applied, is the saved workspace map still valid? (It
   encodes `error_offset_*` — [workspace.py:328](../../python/rig/workspace.py#L328) —
   so the answer is "no", and something must say so.)

---

## 7. If you really do want to move the block *(reading (b))*

It is milestone M5 of the placement-supervision design and it is deliberately
last. In outline: a firmware `P <col> <row> <level>` composed of primitives that
already exist — `G` to the cell, the Z level table to descend, `C` at
`SERVO_CLOSE_ANGLE` (52°), lift, return. New command, new ack, and a genuinely
new failure mode: **a claw that closes on nothing reports success, and the
machine then believes it is holding a block it is not.**

Do not start it before the supervision classifier has run for a session and its
verdicts have been checked against what actually happened. See
[feature-ideas.md §A.3](../feature-ideas.md#a3-milestones) and
[removed-block-compensation.md](removed-block-compensation.md).

---

## 8. Difficulty

| Piece | Difficulty |
| --- | --- |
| Residual → cm, windowed, deadbanded (A) | **2 / 5** |
| Quiet-window trigger between builds | **3 / 5** (shared with supervision's D4) |
| Application via `shiftX/Y` with two-number separation (B) | **3 / 5** |
| New `errX`/`errY` firmware verb (C) | **3 / 5** + unflashable locally |
| Getting the sign right on X, and proving it | **4 / 5** |
| The honesty surface — provenance, caps, "not written to config" | **4 / 5** |

**Overall: 4 / 5.** The arithmetic is small. The discipline around it — deadband,
caps, provenance, the right knob, and a sign convention that is inverted on one
axis — is the whole job.

---

## 9. Not doing

- **A continuous integrator.** One bounded adjustment per session, accepted or
  armed. Not a servo loop over a 0.27 cm noise floor.
- **Correcting pitch, rotation or scale from build residuals.** That is what a
  deliberate dense calibration is for.
- **Writing a measured number into `shift_*_cm` in `config/rig.json`.** Ever.
- **Correcting a level.** The camera is above the board and cannot see height;
  see [feature-ideas.md D3](../feature-ideas.md#d3--occupancy-is-a-column-not-a-level).

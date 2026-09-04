# Feature ideas — the software around the rig

A catalogue of everything worth building on top of the gantry, sorted by what it
costs and what it buys. The rig itself already works: a block gets picked from
the feeder and placed at `B <col> <row> <level>`. Everything here is about
making that capability *legible, planned, verified and impressive*.

The headline item — the **3D Build Studio** — is now built (M0–M7); its
living implementation record is [STUDIO.md](STUDIO.md).
Visual language for all of it is in [DESIGN.md](DESIGN.md).

---

## Tier 0 — already supported by the backend, absent from the UI

These cost hours, not days. Every endpoint listed exists and is tested; the
browser simply does not call it.

| # | Feature | What already exists |
| --- | --- | --- |
| 0.1 | **Rig serial log panel** — every line the Mega prints, terminal-styled, `@`-ack lines highlighted | `app.py` broadcasts `{"type":"log","line":…}` on `/api/events`; `web/src/ws.ts` discards it |
| 0.2 | **Overlay view toggles** — grid / detections / printed sheet / overlay | `POST /api/view`, mirrored in `state.views` |
| 0.3 | **Grid mode switch in the browser** — vertical ⇄ horizontal | `POST /api/mode`; needs a confirm step, it homes X/Y first |
| 0.4 | **Camera freshness meter** — `LIVE 42 ms` / `STALE` / `WAITING` | `state.camera`, `state.camera_age_ms` |
| 0.5 | **Direct level entry** instead of only `+`/`−` | `POST /api/level` accepts `{value}` |
| 0.6 | **Axis select** — pick a column and row numerically when the camera tap is imprecise or the gantry occludes the cell | `POST /api/select/axis` |
| 0.7 | **Keyboard control** — arrows nudge the cell, `+`/`−` level, `B` arms, `Enter` confirms, `Esc` deselects | pure client work over existing routes |

Do these first. They make the console look finished before a single new
backend line is written.

---

## Tier 1 — the flagship: design, plan, build, verify

### 1.1 The 3D Build Studio  ★ headline — built

A real 3D modelling environment in the browser. Dark space, orbit with the
mouse, the machine's own lattice on the floor, click to drop an actual 3D block,
stack on top of it, switch orientation and watch the lattice re-form live, shift
the grid live, save models to a library.

Under the hood every model is nothing but an ordered list of
`B <col> <row> <level>` commands separated by `R` / `RR` mode latches — which is
exactly why this is tractable: the hard part is a viewer, not a robot.

**Built, M0–M7.** Living implementation record: [STUDIO.md](STUDIO.md). One
piece remains unbuilt — the "wow pass" (live shift clipping, timeline scrub,
audio, instruction-sheet export, plan-on-video projection) — kept at
[STUDIO.md §12](STUDIO.md#12-not-yet-built--m8-the-wow-pass).

### 1.2 The live digital twin — built

The same 3D engine, read-only, sitting **next to the camera on the index page**.
As the rig places each block the twin fills in, the next target pulses, and the
remaining plan shows as ghosts. Real workspace and virtual workspace, side by
side, in step. This is the single most impressive thing a demo can show.

**Built, Studio milestone M6** — see [STUDIO.md](STUDIO.md).

### 1.3 Plan projection onto the live camera  ★ sleeper hit

You already have a homography from workspace cells to camera pixels
(`WorkspaceMap.target_polygon`, used by `web/geometry.py`). Feed the *planned*
model through it and draw the plan superimposed on the real video: the next
block glowing in the exact place it will physically land, and the rest of the
design faintly behind it. Near-AR, on hardware you already own, with maths that
is already written and tested.

### 1.4 Placement supervision  ★ fully designed, not started

After each `PLACED`, compare the detections against the cell the model expected
to fill: `VERIFIED`, `NOT DETECTED`, `UNEXPECTED BLOCK AT [c,r]`. Run the same
check continuously while the rig is idle and it also catches a **human moving
or removing a block** — the board stops matching the plan, and the console says
which cell.

This closes the loop between the vision pipeline and the motion system, the most
defensible engineering claim in the project, and it reuses the existing lattice
labelling with no new detector and no extra frames.

**Not implemented.** No `rig/placement_ledger.py`, no `rig/supervisor.py`;
`web/state.py` carries no cumulative occupancy record. The only related code
in the repo is the Studio runner's per-step camera-thumbnail capture
(`web/src/studio/run-report.ts`, `runner-driver.ts`) — a raw image embedded in
the Markdown report, not vision-based verification — plus an optional
`vision_verification` field read defensively in
`web/src/components/RunnerPanel.tsx` that the Python backend never populates.
That is the "single-shot half" this design supersedes (see below); it is not
a partial implementation of the ledger/supervisor design.

The full design — every decision, the milestone breakdown and the known
limits — is kept at [Appendix A](#appendix-a--placement-supervision-full-design)
rather than left to rot in a separate plan file.

### 1.5 Colour-aware planning and feeder prompts

Detections already carry a colour name. Let a model assign a colour per block,
then have the console tell the operator which block to load next:
**`FEED: RED`**, with the count remaining per colour. Turns a manual feeder into
a guided one without touching the hardware.

### 1.6 Build execution runner

Given a compiled model, step through it: current command, blocks placed / total,
elapsed and estimated remaining from measured cycle time, per-block confirm or
continuous run, and a clean resume point if a build is rejected. The safety
rules do not change — one command at a time, never queued.

---

## Tier 2 — credibility and polish

| # | Feature | Why it earns its place |
| --- | --- | --- |
| 2.1 | **Session timeline** — every build with timestamp, command, result, duration and a camera thumbnail at completion | Becomes the evidence section of the written report |
| 2.2 | **Time-lapse export** — save a JPEG on every `PLACED`, stitch to GIF/MP4 | Frames already flow through the pipeline; near-free, enormous demo value |
| 2.3 | **Telemetry strip** — builds today, placed/rejected/aborted counts, mean cycle time, camera FPS, socket round-trip | Makes the console feel instrumented rather than decorative |
| 2.4 | **Diagnostics page** — serial port, board FQBN, camera settings in force, calibration age, workspace-map presence, self-test | The page you open when a demo misbehaves in front of an examiner |
| 2.5 | **SIMULATION badge** — the console already runs `--mock` with no hardware; say so unmistakably on screen | Lets you rehearse and present with zero risk, honestly labelled |
| 2.6 | **Audio and haptic result cues** — distinct tones for placed / rejected / locked, `navigator.vibrate` on phones | The operator is looking at the rig, not the screen. This is real usability |
| 2.7 | **Calibration wizard** — stepped four-corner flow with progress, preview and a saved-calibration timestamp | Replaces a row of bare buttons with something an examiner can follow |
| 2.8 | **Control arbitration** — one operator "holds" the rig, others are view-only | Deferred in [CONSOLE.md](CONSOLE.md); cheap to fake convincingly, good safety story |
| 2.9 | **Run report export** — Markdown/PDF of a session: model, commands, results, timings, photos | Straight into the thesis appendix |
| 2.10 | **QR code on screen** to open the console on a phone | Two lines of code, always impresses |
| 2.11 | **Kiosk mode** — fullscreen, no chrome, for a tablet mounted at the rig | Makes the installation look like a product |
| 2.12 | **E-stop status surface** — the hardware interlock is deferred; display `E-STOP: NOT FITTED` honestly, and require the operator to hold the button for unattended runs | Honesty about a known gap reads as engineering maturity, not weakness |

---

## Deliberately not doing

- **Cancel / retry controls.** The firmware is deaf during a build and an
  aborted session has no software recovery. Any button implying otherwise is a
  lie about the machine.
- **Autonomous block-to-target decisions.** Out of scope for the console and
  the Studio alike; the operator or a compiled plan chooses every target.
- **Cloud anything.** The Pi serves this over LAN with no guaranteed internet.
  No CDN assets, no remote APIs, no telemetry leaving the bench.

---

## Appendix A — Placement supervision, full design

This is the complete design for §1.4 above, kept in full rather than left to
rot in a separate, now-deleted plan file. Nothing described here is built —
see §1.4 for exactly what does and does not exist today.

The rig places a block and forgets it. Nothing in the system knows what is
supposed to be on the board, so nothing can notice when it stops being true:
a block that never left the claw, a block that landed on the wrong cell, a
block a hand picked up while the gantry was somewhere else.

Detection is not the hard part — `block_outline.detect_aligned_blocks` already
reads 29/29 on both reference boards, and its lattice filter already labels
every detection with an integer cell. The hard parts are **knowing what the
board should look like**, **knowing when you are allowed to look**, and
**knowing what the machine is physically able to do about it**.

### A.0 What already exists, and what does not

| Piece | State |
| --- | --- |
| per-frame detections labelled to lattice cells | **exists** — `block_outline._lattice_filter`, `LATTICE_SNAP` 0.34 cells |
| cell ⇄ pixel geometry | **exists** — `WorkspaceMap`, `rig/workspace.py` |
| 10 Hz analysis off the live feed | **exists** — `ConsolePipeline`, `ProcessedFrame.detections` |
| per-build text log | **exists** — `rig/build_log.py` (a stopwatch, not a state model) |
| **a server-side record of what has been placed** | **does not exist** — `web/state.py` carries a selection and `last_result`, nothing cumulative |
| **a firmware verb that retrieves an already-placed block** | **does not exist** — `B` is pick-from-feeder-then-place; there is no pick-from-cell |
| client-side model of a structure | exists but is the browser's — `web/src/studio/twin.ts`, not authoritative |

Two of those gaps are the design. The third — retrieval — decides how much of
the repair story is real, and is deliberately the last milestone.

### A.1 The decisions

#### D1 — Occupancy diff, not motion tracking

A moved block is found by comparing **which cells are occupied** against
**which cells should be occupied**. There is no tracker, no per-block identity,
no velocity estimate.

Velocity was the obvious idea and it is the wrong one:

- At `analysis_hz = 10` a hand grabbing a block is 2–4 frames, and during most
  of them the hand covers the block *and its neighbours*. There is no motion
  trace to measure — there is a disappearance and then a hole.
- There is nothing to track. Twenty-nine identical wooden rectangles, and a
  stateless per-frame detector. Data association across frames on identical
  objects fails precisely under occlusion, which is the only case that matters.
- A speed threshold conflates three unrelated things: a hand, the detector's
  own centre jitter (centres are *measured*, never snapped — see
  BLOCK-VISION §2), and the gantry placing a block on purpose.

Motion does earn one job, in D4: as a **gate**, not as a classifier.

#### D2 — The expected set is the ledger, and the ledger is new

`PlacementLedger` (new, `rig/placement_ledger.py`) is the authority: an ordered
record of every cell the machine has been *commanded* to fill, in the mode it
was commanded in, with the result the firmware reported.

```
entry: (mode, col, row, level, result, t)
expected_occupancy(mode) -> set[(col, row)]     # cells with any level placed
expected_height(mode) -> dict[(col,row), int]   # highest level placed
```

It is written by `BuildController.build()` on a settled `PLACED` — the one
place every build already funnels through — and it is a plain JSON file under
`logs/`, reloaded at startup so a server restart mid-structure does not blind
the supervisor.

This is what makes "keeping a memory of block placement" not weird: it is not
remembering pixels or positions, it is remembering **commands the machine
already issued**. Nothing is inferred.

`ProcessedFrame` gains no new fields from vision. The observed set is derived
from the detections it already carries.

#### D3 — Occupancy is a column, not a level

The camera is above the board. A block at level 1 sits directly on top of the
block at level 0 and hides it completely. So vision can answer

> is cell `[c,r]` occupied by *something*

and cannot answer

> is cell `[c,r]` occupied to *level 2*

**Supervision is therefore level-blind.** The ledger's `expected_occupancy` is
the set of cells with *any* block; the observed set is the set of cells with
any detection. A block stolen off the top of a two-high stack leaves the cell
occupied and is invisible to this design. Say so on screen rather than implying
a guarantee that is not there.

Two consolations: level 0 is where every structure starts, and a *toppled*
stack changes the occupied set — the fallen block lands somewhere it should not
be — so the failure that actually endangers the next placement is caught.

#### D4 — Judge only in the quiet window

This is the rule the feature lives or dies on. Never evaluate a diff unless the
board is still and unobstructed.

Three interlocks, all required:

| Interlock | Why | How |
| --- | --- | --- |
| **gantry parked** | the arm crosses the board, occludes cells, and *is* a legitimate change | supervision runs only while `BuildController` is idle and unlocked; `BuildJob.running` freezes it |
| **scene quiet** | a hand is a large moving occluder | channel-max frame difference against the last accepted frame; energy over `QUIET_DIFF_FRACTION` of the frame → discard the frame and restart the settle timer |
| **settled** | one clean frame is not evidence | a cell must read the same way in `N of M` consecutive quiet frames before its state is believed |

The frame-difference test is the same primitive `block_grid`'s labelled route
already uses for its per-placement differencing, and it is cheap. This is where
the "detect that something is moving" instinct belongs: as a reason to *stop
looking*, not as a measurement.

Suggested starting values, to be measured on hardware, not trusted from here:
`QUIET_DIFF_FRACTION = 0.02`, `SETTLE_N = 3`, `SETTLE_M = 5`, evaluated at the
existing 10 Hz — so a verdict costs about half a second of stillness.

#### D5 — Confidence in a cell, not a boolean

Each cell carries a small hysteresis counter rather than a per-frame flag.
Single-frame dropouts are jitter; two consecutive dropouts in a quiet, parked,
settled scene are an event. A cell's state changes only when the counter
saturates, and the counter is **reset, not decayed**, whenever an interlock in
D4 trips — a frame that was not allowed to be judged must not leak partial
evidence into the next verdict.

#### D6 — The classifier is a set difference

Evaluated once per quiet window, comparing `observed` against
`ledger.expected_occupancy(mode)`:

| Condition | Verdict | Severity |
| --- | --- | --- |
| sets equal | `VERIFIED` | — |
| expected cell empty, an unexpected cell occupied, counts equal | `MOVED [a,b] → [c,d]` | repair |
| expected cell empty, no unexpected cell | `REMOVED [a,b]` | repair |
| unexpected cell occupied, nothing missing | `FOREIGN BLOCK AT [c,d]` | stop |
| more than one cell differs either way | `BOARD DISAGREES` | stop |

Note what `MOVED` does **not** claim: that it is the *same* block. Identical
objects, no identity, no proof available. It does not need one — the actionable
fact is "the board no longer matches the plan at these two cells".

`BOARD DISAGREES` is not a failure of the classifier; it is the classifier
declining to guess. Two simultaneous changes in one half-second quiet window
means something happened that this model does not describe, and the honest
response is to stop and show the operator both sets.

#### D7 — Verification after a build is the same machine, run once

A per-build `VERIFIED / NOT DETECTED / UNEXPECTED` check is not a separate
feature. It is D6 evaluated in the first quiet window after the build settles,
with the ledger entry already appended. One implementation, two triggers:

- **on completion** — one evaluation, reported as the build's result;
- **continuous** — every quiet window while idle, reported as a board status.

Continuous mode is what catches the hand. Per-build mode is what catches a
block that never left the claw.

#### D8 — Repair is bounded by what the machine can do

The firmware has no verb that picks a block up off the board. `B` picks from
the feeder. So the repair vocabulary today is exactly one entry:

| Verdict | Repair available now |
| --- | --- |
| `REMOVED [a,b]` | **automatic** — re-issue `B a b <level>`. Feed a block, place it back. Already in the vocabulary. |
| `MOVED [a,b] → [c,d]` | **none.** Stop, name both cells, ask the operator to clear `[c,d]`, re-verify, then re-issue `B a b`. |
| `FOREIGN` / `DISAGREES` | **none, by design.** Stop and show. |

Do not soften this. A `MOVED` block sitting on `[c,d]` may be a cell the plan
needs later, and placing into it is a collision. Half-repairing is worse than
stopping.

**Repair before advancing the plan, and re-verify after.** A repair that is not
re-verified is a guess with extra steps.

Milestone M5 adds the retrieval verb if the hardware turns out to support it —
see §A.3.

#### D9 — Automatic repair is opt-in and rate-limited

`REMOVED` → refeed is the one automatic motion this design can produce, and a
machine that re-places a block a human just deliberately removed is
infuriating. So:

- off by default; an explicit **SUPERVISE: REPAIR** toggle arms it;
- at most one automatic repair per cell per run, then that cell is latched to
  "stop and ask";
- never during a running build — supervision only acts from idle, per D4.

### A.2 Where it lives

```
rig/placement_ledger.py     new  D2 — expected occupancy, JSON-backed
rig/supervisor.py           new  D4-D6 — interlocks, hysteresis, classifier
rig/build_controller.py     edit — append to the ledger on PLACED
rig/console_pipeline.py     edit — hand ProcessedFrame to the supervisor
web/state.py                edit — surface verdict + expected/observed sets
web/routes_command.py       edit — arm/disarm, acknowledge, request repair
web/src/…                   edit — board status strip, verdict banner
```

`vision/` is **not touched.** The supervisor consumes `ProcessedFrame.detections`
and the `WorkspaceMap`; it adds no detector, no second analysis path, and no
extra frames. BLOCK-VISION §2 already measured what "better settings for this
one purpose" costs — up to 3.9 s a frame for zero extra blocks — and that
measurement applies here unchanged.

Nothing is stored as an image. State is a set of cells, a counter per cell, and
timestamps.

The layering rule from BLOCK-VISION §7 holds: **supervision is a fourth layer
above `block_outline`, and reaches past nothing.** It never calls
`detect_blocks` and never writes `workspace_map.json`.

### A.3 Milestones

**M1 — the ledger.** `rig/placement_ledger.py` plus the `BuildController` hook.
No vision. Testable alone: a sequence of builds produces the expected
occupancy set, survives a reload, and keeps the two modes' lattices separate.

**M2 — the observer.** `rig/supervisor.py` turning `ProcessedFrame.detections`
into an observed cell set, with the D4 interlocks and D5 hysteresis. Report
only; no verdicts, no actions. Exposed as a board-status field so the interlock
behaviour can be watched on the real bench before anything depends on it.

**M3 — the classifier.** D6 verdicts and the D7 per-build check, surfaced in
the console. Still no motion produced. **This is the demonstrable milestone** —
lift a block off the board and the console names the cell.

**M4 — bounded repair.** D8's one automatic case plus D9's guards.

**M5 — retrieval, if the hardware allows.** A firmware `P <col> <row> <level>`
that goes to a cell, descends to that level, closes at `SERVO_CLOSE_ANGLE`
(52°), lifts, and returns to the feeder — composed entirely from primitives
that already exist (`G`, the Z level table, `C`/`O`). It is a new command, a new
ack, and a new failure mode: a claw that closes on nothing reports success and
the machine believes a block it does not hold. **Do not start M5 until M3 has
run for a session and its verdicts have been checked against what actually
happened.**

### A.4 Known limits — state these on screen, do not paper over them

- **Level-blind** (D3). A block taken off the top of a stack is not seen.
- **Sub-cell nudges are invisible.** `LATTICE_SNAP` is 0.34 cells, and the
  four-corner `WorkspaceMap` already carries 1.25 px mean / 2.07 px max
  (0.27 cm) of flattening error mid-grid — BLOCK-VISION §4. A block pushed a
  few millimetres still reads as the same cell. Residual distance from the
  fitted centre is available and could raise a **soft warning**, but must never
  trigger a repair at that error budget.
- **Lattice brakes carry over.** `_lattice_filter` skips entirely below
  `MIN_LATTICE_BLOCKS` (6) detections and disables itself if it would reject
  more than 30 %. On a nearly empty board the observed set is unfiltered, so
  the holder's offcuts beside `[0,0]` can read as blocks. Supervision must
  refuse to produce `FOREIGN` verdicts below that threshold — a sparse board
  gets `VERIFIED`/`REMOVED` only.
- **Occlusion is not emptiness.** A cell the gantry, a cable or a hand is
  covering is *unobservable*, not empty. D4 handles the common case by refusing
  to judge at all; a cell under a static occluder will read as `REMOVED`
  forever, which is why the verdict stops the machine rather than driving it.
- **One mode at a time.** The vertical and horizontal grids are different
  lattices with different registration. The ledger is keyed by mode and a mode
  latch invalidates the observed set until the next quiet window.

### A.5 Tests to write alongside it

| Suite | Checks |
| --- | --- |
| `tests/test_placement_ledger.py` | append/reload, per-mode separation, level collapse to a column, `PLACED`-only admission |
| `tests/test_supervisor.py` | every D6 row from synthetic cell sets; hysteresis needs `N of M`; each D4 interlock independently suppresses a verdict; counters reset rather than decay on a tripped interlock |
| `tests/test_supervisor_frames.py` | against the two reference boards in `python/captures/`: full board → `VERIFIED`; one cell erased → `REMOVED [c,r]` naming the **exact** cell, not a count; a block relocated → `MOVED`; the holder's offcuts never produce `FOREIGN` |
| existing | `test_block_outline.py`'s timing guard must still pass — supervision adds no detector work |

Assert exact cell sets, never counts. BLOCK-VISION §0 explains why: a count-only
assertion passes on a board renumbered by one cell, which is the failure that
matters.

### A.6 Not doing

- **Tracking blocks between frames.** D1. Revisit only if a measured failure
  demands it, and bring the measurement.
- **Re-planning around interference.** The machine does not decide to build
  something else because a block moved. It repairs or it stops.
- **Storing frames.** The time-lapse idea (§2.2 above) is a separate feature
  with a separate budget; supervision keeps cells and counters.
- **Verifying during a build.** The firmware is deaf mid-command and the arm is
  in the frame. Supervision is an idle-time activity.

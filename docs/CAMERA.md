# The camera — what it does, where it shows up, and what owns what

**Living record.** This is the map from *camera capability* → *web UI surface*,
and the answer to "who owns which part of the vision stack".

It deliberately does **not** restate detector internals. Those are
[BLOCK-VISION.md](BLOCK-VISION.md), which is the authority on how
`block_detector`, `block_outline`, `block_levels` and `block_grid` actually
work. Read that for *how*; read this for *what, where, and who*.

---

## 0. The one sentence

> **Today the camera is a monitor and a calibration instrument. It never makes
> an assertion the system acts on.**

Detections are *drawn*. Nothing **reads** them. There is no code path in which a
detected block changes what the machine does, or changes what the console says
about whether a build was correct.

That is not an oversight — it is the line the project has not crossed yet.
**Two designed-but-unbuilt features cross it, and both are camera-based:**
[placement supervision](features/placement-supervision.md) (does the board match
the plan?) and [Stage 15](features/stage-15-placement-correction.md) (is that one
block off-centre?). §6 covers both, and how they use the camera differently.

---

## 1. The hardware and the pipeline

One camera. One owner. No second stream, no second analysis path.

| Fact | Detail |
| --- | --- |
| Physical | a single camera above the workspace, looking straight down |
| Owner | `ConsolePipeline` — [python/rig/console_pipeline.py](../python/rig/console_pipeline.py). *"owns exactly one camera source, frame pump, block-analysis worker, and printed-grid tracker"* |
| Threading | one owner thread. `_drive_pipeline` in [web/app.py](../python/web/app.py) sends **all** blocking OpenCV work to a single-threaded executor so the event loop stays free for serial callbacks (AGENTS.md §7) |
| Analysis rate | `analysis_hz = 10.0` — the block detector |
| Sheet-tracking rate | `paper_hz` — the printed-grid tracker, separate and slower |
| Latest-only | `LatestFramePump` + `AnalysisWorker` — a slow frame is dropped, never queued. The overlay is always *recent or marked stale*, never a backlog |
| Settings | [python/config/camera_settings.json](../python/config/camera_settings.json) — capture size, sensor mode, colour correction, fisheye profile, framing ROI |
| Lens profile | `config/lens_profile.json` — **not** config, see [AGENTS.md](../AGENTS.md) |

### Per-frame processing order

```
capture → orientation → colour correction → fisheye undistort (or crop/resize)
       → submit to AnalysisWorker (10 Hz)  → detections
       → submit to PaperGridTracker        → paper status
       → ProcessedFrame
```

## 2. What one frame produces

`ProcessedFrame` ([console_pipeline.py:44](../python/rig/console_pipeline.py#L44))
is the whole camera-side product:

| Field | Meaning |
| --- | --- |
| `view` | the corrected image (what the stream encodes) |
| `detections` | the blocks found, as clean rectangles — **pixel centres, no cell labels** (see §5b) |
| `workspace` | the `WorkspaceMap` in force: cell ⇄ pixel geometry |
| `calibrated` | whether that map is a **saved calibration** or an `approximate_workspace` guess |
| `grid_mode` | which lattice the frame belongs to — vertical or horizontal |
| `stale`, `captured_at`, `sequence`, `image_size`, `paper_status` | freshness and bookkeeping |

**Nothing is stored as an image beyond the latest frame.** There is no frame
history, no recording, no buffer of past boards.

---

## 3. Every camera capability, and where it surfaces

### 3a. The video

| Capability | UI surface | Code |
| --- | --- | --- |
| Live MJPEG stream — undistorted, colour-corrected, ROI-framed | the main camera stage | [web/mjpeg.py](../python/web/mjpeg.py) `GET /api/stream.mjpg`, [CameraView.tsx](../web/src/components/CameraView.tsx) |
| Freshness meter — `LIVE` / `STALE` / `WAITING` + frame age in ms | chip on the camera stage | [CameraChip.tsx](../web/src/components/CameraChip.tsx), from `state.camera` / `camera_age_ms` |

The stream is **raw video only**. Every overlay is drawn client-side as SVG on
top of it — the server never burns graphics into the JPEG. That is why the
overlays are instant and free to toggle.

### 3b. Overlays — four toggles, `POST /api/view`

Defaults: `{"grid": True, "detect": True, "paper": False, "overlay": True}`
([app.py:220](../python/web/app.py#L220)). Drawn by
[GridOverlay.tsx](../web/src/components/GridOverlay.tsx) from
`state.geometry`, built by [web/geometry.py](../python/web/geometry.py).

| Toggle | Draws |
| --- | --- |
| **`grid`** | every cell as its **real block footprint** polygon — via `WorkspaceMap.target_polygon`, so actual gaps are preserved rather than drawing pitch rectangles. Feeder `[0,0]` marked; belt-blocked cells struck through with a cross; cell labels; **`approximate` styling when `calibrated` is false**, so an uncalibrated grid never looks authoritative |
| **`detect`** | every detected block as a clean rectangle, coloured by hue name (red / orange / yellow / green / blue). The rectangle keeps the block's **measured centre** — a misplaced block looks misplaced, deliberately (BLOCK-VISION §2) |
| **`paper`** | printed calibration-sheet tracking. Off by default; toggling it on is what starts the tracker |
| **`overlay`** | master switch for all of the above |
| *(always on)* | hover-cell highlight; selected cell with halo and corner ticks |

### 3c. The camera as an input device

| Capability | UI surface |
| --- | --- |
| **Click a cell on the video to select a build target** | the SVG cell polygons are the hit targets; selection becomes `B <col> <row> <level>` |
| Level, mode, axis, keyboard | [LevelStepper](../web/src/components/LevelStepper.tsx), [ModeSwitch](../web/src/components/ModeSwitch.tsx), [Shortcuts](../web/src/components/Shortcuts.tsx) |

This is the only place today where the camera image **drives** anything — and
note it is the *operator* clicking, not the camera deciding.

### 3d. Calibration — four flows, all camera-driven

[Calibrate.tsx](../web/src/components/Calibrate.tsx) →
[routes_calibration.py](../python/web/routes_calibration.py).

| Flow | What it does | Endpoints |
| --- | --- | --- |
| **Calibrate with blocks** | the rig **places blocks on known cells** and the camera measures where they landed. A stepped wizard: per-cell progress, undo, cancel, save. The most accurate route, and the one BLOCK-VISION §3 argues beats a printed sheet | `/api/calibration/block/{start,step,undo,cancel,save,status}` |
| **Calibrate by corners** | click the four holder limits on the video, in order | `/api/calibration/{start,corner,undo,cancel,save}` |
| **Calibrate from sheet** | detect the printed calibration sheet in the current frame | `/api/calibration/paper` |
| **Reload saved calibration** | pick up a `workspace_map.json` written by Camera Studio or the CLI **without restarting the server** | `/api/calibration/reload` |

The saved artefact is `config/workspace_map.json`. It is **per mode**, and it
is invalidated when the grid geometry it was fitted against changes — trims,
error offsets or shifts (`WorkspaceMap.matches_grid`).

### 3e. Evidence

| Capability | UI surface |
| --- | --- |
| **Per-placement camera thumbnail** in the Studio run report | [RunnerPanel.tsx:183](../web/src/components/RunnerPanel.tsx#L183) — `captureCameraThumbnail` grabs the live `<img>` into a canvas on each settled build; [run-report.ts:55](../web/src/studio/run-report.ts#L55) embeds it in the Markdown |

This is a **raw picture**, not a verification. Nothing looks at it. It is
evidence for a human reader of the report.

### 3f. Off the web UI — the desktop tools

Not part of the console, but the same pipeline, and they write the artefacts the
console reads:

| Tool | Purpose |
| --- | --- |
| `python/camera/camera_studio.py` | the desktop tuning surface — colour, fisheye, framing, block calibration |
| `python/camera/block_grid_calibrate.py` | CLI machine-driven calibration |
| `python/camera/virtual_calibrate.py` | derive the horizontal map from a calibrated vertical one |
| `python/camera/benchmark_camera_pipeline.py`, `camera_perf_check.py` | timing |

Tuning guides: [camera-fisheye-tuning-guide.md](camera-fisheye-tuning-guide.md),
[printed-color-grid.md](printed-color-grid.md),
[grid-capture-calibration-playbook.md](grid-capture-calibration-playbook.md),
[cluster-calibration-grid.md](cluster-calibration-grid.md).

---

## 4. The layering — who owns what

From [BLOCK-VISION §7](BLOCK-VISION.md), and it is load-bearing:

```
 layer 3   block_grid          the calibrator — fits the map, once
 layer 2   block_outline       clean, grid-straight outlines for the live feed
 layer 1.5 block_levels        which block is on top (side-sliver height)
 layer 1   block_detector      what warm shapes are in this frame
 ───────────────────────────────────────────────────────────────────
 rig/      console_pipeline    owns the camera, produces ProcessedFrame
           workspace           cell ⇄ pixel geometry
 web/      geometry.py         → JSON for the browser's SVG
```

Two rules that survive every feature:

1. **Nothing above reaches past `block_outline` into `block_detector`.**
2. **`vision/` is stateless and per-frame.** It answers *"what is in this
   image"*. It knows nothing about builds, modes, plans, or what happened a
   second ago.

---

## 5. "Where is the error detector? Isn't it part of the camera?"

**There isn't one. And when it is built, it will deliberately not live in the
camera.**

### 5a. Why it cannot be part of `vision/`

Detecting an *error* is a **subtraction**:

```
error  =  what SHOULD be on the board  −  what IS on the board
```

The camera can only supply the right-hand operand. The left-hand one is a
**memory of commands the machine issued** — which cell, which level, which mode,
and what the firmware reported back. That memory does not exist today at all
(§5c), and it has nothing to do with pixels.

Put the subtraction inside `vision/` and you get a detector that needs to know
about the ledger, the grid mode, and whether the gantry is parked. That breaks
rule 2 above, makes the detector untestable without a rig, and gives you two
places that can disagree about what a block is.

> **The camera answers "what do I see". The ledger answers "what should be
> there". The error detector is the subtraction — and subtraction belongs to
> neither operand.**

So it lives in `rig/`, one layer above the camera, as a **consumer**. Both
designed error detectors do, for the same reason:

| Module | Feature | `vision/` touched? |
| --- | --- | --- |
| `rig/supervisor.py` | [placement supervision](features/placement-supervision.md) | no — consumes `ProcessedFrame.detections` |
| `rig/stage15.py` + `rig/placement_check.py` | [Stage 15](features/stage-15-placement-correction.md) | no — *"calls the existing detector with different arguments"* |

Neither adds a detector, neither modifies a module in `vision/`, and neither
takes a frame the pipeline was not already producing. **Camera-based does not
mean camera-owned.**

### 5b. Two things that look like an error detector and are not

**1. The calibration residuals in `block_grid`.** `BlockGridReport.residuals`,
`mean_residual_px`, `worst_cell` and `workspace_map_error()` are real error
numbers — **but they measure how well the fitted map describes the board**, not
whether a placement was correct. `workspace_map_error()` reporting 1.25 px mean
/ 2.07 px max (0.27 cm) is the *map's own* flattening error, and it is the
**noise floor** any placement check has to clear, not a placement check itself.
Conflating the two is the easiest mistake available here.

**2. `_lattice_filter` does not label cells.** It rejects detections that are
not on the lattice the other blocks describe — a *filter*, not a *labeller*. It
solves indices relative to `detections[0]` purely to decide keep/reject and then
**discards them**. A `BlockDetection` carries a pixel centre and no cell.

> **Pixel → cell is `WorkspaceMap.cell_at(point, image_size)`, and it is the
> consumer's own work.** It returns `None` both for a point outside the
> quadrilateral *and* for one landing in a deliberate gap between block
> footprints — and that second `None` is **signal**: a block on the board but
> not on a site.

Earlier design drafts asserted the opposite. See
[placement-supervision.md §2a](features/placement-supervision.md#2a-three-things-the-earlier-designs-got-wrong).

### 5c. The gap, stated plainly

| Piece | State |
| --- | --- |
| detections, 10 Hz, off-lattice ones rejected | **exists** |
| cell ⇄ pixel geometry | **exists** |
| a record of what the machine has placed | **does not exist** — `web/state.py` carries a selection and `last_result`, nothing cumulative; `BuildJob` has no history; the firmware's `countPlacedBlock()` is a **histogram** and does not record the cell |
| anything comparing the two | **does not exist** |
| a UI field waiting for the answer | **exists and is never populated** — `vision_verification`, read defensively in [RunnerPanel.tsx:182](../web/src/components/RunnerPanel.tsx#L182), carried through the runner event → log row → run-report column. The whole client path is wired; only the server's opinion is missing |

---

## 6. The two camera-based features, and how they differ

Both are designed, neither is built, and both make the camera assert something.
They are **not** the same feature at different resolutions — they ask different
questions and, crucially, **they get their detections by different routes.**

| | [Placement supervision](features/placement-supervision.md) | [Stage 15](features/stage-15-placement-correction.md) |
| --- | --- | --- |
| **The question** | *is this cell occupied?* | *is that block off-centre, and by how much?* |
| **Granularity** | whole cells — occupancy | sub-cell, centimetres |
| **Detections from** | the **live pipeline** — `ProcessedFrame.detections`, already through `_lattice_filter` **with** a grid | **its own pass** — `detect_aligned_blocks(frame, grid=None)` |
| **Cadence** | 10 Hz, continuously while parked | once per job, between jobs (~84 ms) |
| **What rejects junk** | `_lattice_filter` — needs ≥ 6 blocks, drops the holder's offcuts | **memory-driven matching** — predict where each remembered block should be, match within 1.5 cm, ignore every unmatched detection |
| **Level ceiling** | **level 3** — lattice snap eats the parallax budget | **none** — `grid=None` skips the filter entirely… |
| **…but needs** | nothing extra | **parallax**, to predict where an elevated block will appear |
| **Catches** | removals, foreign blocks, a block that never landed | one badly-placed block |
| **Acts by** | notifying the operator | **physically re-placing the block** |

### The `grid=None` hatch is the whole difference

`_lattice_filter` opens with *"if grid is None … return list(detections)"* —
**with no grid there is no rejection at all**, and the centre is untouched either
way. That is how Stage 15 escapes the level-3 ceiling that constrains
supervision.

The trade is exact: it gives up the offcut rejection, so it must supply its own
filter — and it can, because **it has build memory and the live pipeline does
not**. *"Is it near where memory says a block should be"* is a sharper test than
*"is it roughly on some lattice"*. Supervision runs at 10 Hz off a shared frame
and cannot afford a second pass; Stage 15 runs once a job and can.

> Same camera, same detector, same frame. **Different arguments, different
> filter, different ceiling.**

### "Stage 15" is not a firmware phase — do not add a 15th

The name misleads, and the Stage 15 doc's D2 is emphatic about it. The Mega has
**no camera and no filesystem**; it cannot look at the board, so this can never
be a firmware phase, and phases 1–14 are not modified.

It is tempting to have the Pi synthesise a 15th `@n STEP … phase=` line into the
build-progress stream. **Do not:**

1. The fourteen `phase=` ids are a **protocol mirrored in four places** — the
   sketch's `buildStep()` call sites, `MockBoard.BUILD_PHASES`, `twin.ts`'s
   `PHASE_BY_ID`, and [ack-protocol.md](ack-protocol.md) — and `twin.test.ts`
   asserts the browser's table matches the documented fourteen.
2. The fallback is not graceful. [twin.ts:440](../web/src/studio/twin.ts#L440)
   reads `PHASE_BY_ID[progress.phase] ?? "moving-to-target"`, so an unrecognised
   id makes the 3D twin **draw the gantry flying to a target** — an active
   misstatement of what the machine is doing, not a shrug.

So Stage 15 gets **its own state fields and its own UI strip**, parallel to the
build-phase channel and never inside it. The operator sees "Stage 15 — placement
check" because that is what it is *to them*; the fourteen-phase contract is
untouched.

---

## 6a. Before and after

### The role change

| | today | after |
| --- | --- | --- |
| the camera is a… | monitor + calibration instrument | **instrument that asserts** |
| detections are… | drawn | drawn **and read** |
| a wrong board… | looks wrong to a human who happens to be looking | **stops the machine and names the cell** |
| the run report says… | `placed` — the firmware's own word for it | `placed` **and verified in frame** |

### What supervision adds to the UI

| Feature | Surface |
| --- | --- |
| Per-placement verdict — `verified` / `not detected at [2,2]` / `unchecked — level 3` | runner log row **+ run-report column** (already wired) |
| Supervision banner — verdict, named cells, dismiss | new component |
| Board status — `NO MEMORY` / `NO MAP` / `WARMING` / `BUSY` / `QUIET` / `VERDICT` + why | banner, so "not judging" is never silent |
| **Verdict tint on the cell, on the live video** | `GridOverlay.tsx` — a new per-cell class, exactly as `blocked` already works. **The strongest demo surface**, because the operator is watching the video |
| Verdict tint on the twin | a separate overlay layer — *not* a sixth `TwinAppearance` |
| `unjudged` cells (above the level-3 ceiling) | banner — stated, never silently skipped |
| Expected vs observed sets on `BOARD DISAGREES` | banner |
| Runner pauses / stops on a verdict | runner panel |

### What Stage 15 adds to the UI

| Feature | Surface |
| --- | --- |
| **Its own "Stage 15 — placement check" strip**, parallel to the build-phase channel and never inside it (§6, D2) | new component |
| The finding: which block, by how much, on which level, parallax accounted for | that strip |
| Which levels the pass actually matched | that strip — the honest report while levels > 2 stay unverified |
| The correctable set is smaller than it looks — D5 (buried block) and D6 (taller neighbour) refusals | that strip, surfaced honestly |
| An opt-in toggle, **default off** (D11) | build UI |

### What does **not** change

**No new hardware. No second camera. No change to `vision/`.** Same stream, same
detector, same settings. Supervision adds no frames at all; Stage 15 adds exactly
**one detector call per job** (~84 ms), which is nothing at a between-jobs
cadence.

BLOCK-VISION §2 already measured why the detector is left alone: full-resolution
illumination-flattened settings find **29/29 on both reference boards — exactly
the same as the cheap settings — and cost up to 3.9 s a frame.** The rejection
steps are what buy the accuracy, not the resolution.

---

## 7. What the camera cannot do

Geometry, not effort. State these rather than discovering them in a demo.

| Limit | Why |
| --- | --- |
| **Cannot see a block underneath another** | the view is overhead; a level-1 block hides the level-0 block completely. Occlusion, not resolution |
| **Cannot see a block taken off the top of a stack** | the cell stays occupied, so an occupancy check is unchanged. The only possible fix is `block_levels`' side-sliver height, which is **not validated on real frames** |
| **Cannot see above level 3** | parallax pushes an elevated block past `LATTICE_SNAP` (0.34 cells) and `_lattice_filter` silently discards it. See [features/camera-parallax-and-levels.md](features/camera-parallax-and-levels.md) |
| **Cannot resolve a sub-cell nudge** | 0.34-cell snap plus the map's own 0.27 cm flattening error. A block pushed a few millimetres still reads as the same cell |
| **Is unreliable on a sparse board** | `_lattice_filter` skips entirely below `MIN_LATTICE_BLOCKS` (6) and disables itself if it would reject >30 %. The holder's offcuts beside `[0,0]` can then read as blocks — which is the *common* state early in every build |
| **Cannot see through the gantry** | the arm crosses the board during a build. This is why every check is a between-ops activity |
| **Is worthless without a current map** | with no saved calibration the pipeline falls back to `approximate_workspace`, and `cell_at` will be confidently wrong. Any consumer must refuse to judge when `calibrated` is false |

The named answer to the first two is a **second, side-on camera** — the Pi 5 has
the port. It is out of scope and expensive everywhere (a mount, a second
calibration, a second geometry, double the pipeline cost on an already-timed
Pi). Recorded here so the limit has a known answer and nobody proposes it as if
it were cheap. [feature-ideas.md §3.5](feature-ideas.md).

---

## 8. Status board — what we are adding

**Tick a box when it lands, and in the same commit update the prose above that
it makes false.** §0 says the camera "never makes an assertion the system acts
on" — the first ticked box in M3a makes that sentence wrong, and a living doc
that still says it is worse than no doc.

Plans: [placement-supervision.md](features/placement-supervision.md) ·
**[the build record + Gate 0 measurements](features/placement-supervision-progress.md)** ·
[stage-15-placement-correction.md](features/stage-15-placement-correction.md) ·
[camera-parallax-and-levels.md](features/camera-parallax-and-levels.md)

### Gate 0 — de-risk before building anything

- [x] **Throwaway measurement script**, rig parked, ~60 s. Log per frame: the
      channel-max frame-difference energy fraction, the detection count, and
      what `WorkspaceMap.cell_at` assigns each detection to.
      → `python/tools/measure_quiet_window.py`. **Run on the rig 2026-09-07.**
- [x] **Answer three questions from it.** All three answered on the rig:
      - *Does the quiet window open?* **Yes, decisively.** Parked p99
        `0.000573`, worst max `0.003855`; a hand over the board reads p50
        `0.070745` — **105× the parked median**. The still floor and the
        disturbed ceiling are more than an order of magnitude apart, so the
        threshold sits in a wide empty band, not on a judgement call.
      - *Is detection stable?* **Yes, once blocks are RIG-PLACED.** All five
        cells at 99.4–99.8% recall. An earlier hand-scattered board read 65%,
        which was an artifact of running below `MIN_LATTICE_BLOCKS` where the
        lattice filter cannot engage — not a property of the detector.
      - *Do cells assign consistently?* **Yes.** 171/171 quiet frames matched
        the expected cell set exactly; 3-of-5 windows read every cell occupied
        100.00% of the time.
      → `QUIET_DIFF_FRACTION = 0.01`, `SETTLE_N = 3`, `SETTLE_M = 5`
      (0.58 s at the measured 8.6 Hz — the pipeline delivers 8.6–8.7, not 10).
- [x] **The quiet window opens during a program too**, not only between jobs:
      42–47% of frames quiet, ~9 runs of ≥5 consecutive quiet frames per
      minute. Supervision is not restricted to between-job checks.

### M1 — the memory *(no camera involvement at all)*

- [x] `python/rig/placement_ledger.py` — per cell: mode, col, row, level,
      result, `placed_at`. Pure data, no OpenCV.
- [x] Hook in `BuildController.build()` on the `PLACED` branch only
- [x] `expected_occupancy(mode)`, `expected_top_level(mode)`
- [x] `is_top_of_column()`, `has_taller_neighbour()` — Stage 15's D5/D6 predicates
- [x] Append-only `logs/placements.log`, `build_log.py` conventions
- [x] Refuses to load a reloaded ledger as authority → reports `NO MEMORY`
- [x] `python/tests/test_placement_ledger.py` — 42 checks

### M2 — the observer *(report only, no verdicts)*

- [x] `python/rig/supervisor.py` — carrying Gate 0's **measured** constants
- [x] Interlocks: gantry parked · **`frame.calibrated`** · scene quiet · settled N-of-M
- [x] **pixel → cell via `WorkspaceMap.cell_at`** — real work, not an inherited
      input (§5b); `None` in a gap is *signal*
- [x] **`cell_at → None` is split three ways** — `gap` (on the board, off every
      site: real FOREIGN) vs `margin` / `outside` (rails and offcuts: ignored).
      Measured necessity: one persistent off-board object sat in **523 of 524**
      parked frames, and the merged reading would have held the machine at
      FOREIGN in **99.8%** of windows on a board that was entirely correct
- [x] Frame difference **on the executor**, not the event loop —
      `rig.supervisor.quiet_fraction`, dispatched from `_supervise` in
      `web/app.py` to the same single-threaded executor that owns
      `process_once` and `encode_jpeg` (AGENTS.md §7). The pixel → cell step
      and the set maths stay on the loop
- [x] Wired into `_drive_pipeline` — **last in the loop turn**, after the
      build result is published. Any `await` between `job.poll()` and
      `_publish_build_result` lets a state snapshot claim `last_result=placed`
      before the terminal event (progress.md F15)
- [x] D5's "gantry parked" is `PARKED_CELL_PHASES`, **not** the design's
      `cell_phase == "idle"` — `complete` is terminal and sticky, so `"idle"`
      would wedge supervision at BUSY for every session after the first placed
      block (progress.md F14)
- [x] One step per NEW capture. `process_once` hands back the same frame when
      only staleness changed; stepping on it would difference an array against
      itself and let one capture supply two of the N-of-M readings
- [x] `PlacementLedger` owned by the lifespan and passed to `BuildController`
      as `ledger=` — the controller still knows nothing about OpenCV
- [x] `python/tests/web_supervision_test.py` — 16 tests over the seam
- [x] Per-cell hysteresis; counters **reset**, not decay, on a tripped interlock
- [x] Level-3 ceiling: refuse to judge cells whose expected top level is ≥ 3
- [x] Hysteresis reset on `frame.grid_mode` change
- [ ] Exposed as a state field, watched on the bench for a session — the
      reading is held on `app.state.supervision` and every CHANGE is written to
      `logs/placements.log`, but **nothing is published to the client yet**;
      that is M3b. **Unverified on hardware: there is no camera on the dev
      desktop, so the quiet gate has only ever run on synthetic arrays here**
- [x] `python/tests/test_supervisor.py` — **73 checks**, synthetic cell sets only
- [x] **D9 refined (P1)** — a one-sided change of any size is NAMED, not
      dismissed: N missing with nothing gained is `REMOVED` naming all N, N
      unexpected with nothing missing is `FOREIGN` naming all N. `DISAGREES` is
      now precisely "both sides changed and I cannot pair them", which is the
      only case that actually needs block identity
- [x] **Hysteresis resets on the `MIN_LATTICE_BLOCKS` crossing (P2)**, both
      directions — evidence gathered under one filtering regime must not judge
      under another, which is D13's argument applied to the other boundary
- [x] `python/tests/test_supervisor_frames.py` — **23 checks**. The four Gate 0
      rig traces (`docs/measurements/gate0_*.csv`, 1398 frames the rig actually
      produced) replayed through the shipped `Supervisor`. Chosen over the
      reference stills in `python/captures/`: stronger evidence, no OpenCV.
      Reproduces the measured distribution to within a tenth of a percent, and
      replays the pre-fix merged reading to show it emitting FOREIGN in 99.4%
      of windows on a board that was entirely correct

### M3a — the per-build verdict *(cheapest high-value step)*

- [ ] Classifier triggered at `_publish_build_result`
- [ ] Publish `vision_verification: str | None` on `StateModel`
- [ ] **Verify the free win:** runner log row and run-report column light up
      with **no client change** (§5c)
- [ ] `python/tests/web_state_test.py` extended

### M3b — the continuous verdict *(the demonstrable milestone)*

- [ ] Whole-board occupancy diff in every quiet window while parked
- [ ] D9 verdicts: `VERIFIED` / `NOT_DETECTED` / `REMOVED` / `MOVED` / `FOREIGN` / `DISAGREES`
- [ ] No `FOREIGN` below `MIN_LATTICE_BLOCKS` (6)
- [ ] `SupervisionModel` published; `POST /api/supervision/ack`
- [ ] Runner: `board-verdict` event → pause on amber, stop on red, **never `LOCKED`**
- [ ] **Camera overlay first** — a per-cell class in `GridOverlay.tsx`, exactly
      how `blocked` cells already work. Cheapest surface and the one the
      operator is actually looking at
- [ ] Supervision banner (new component)
- [ ] Twin overlay layer — **not** a sixth `TwinAppearance`
- [ ] `unjudged` cells drawn as a **hatch, not a colour**, with a count and reason
- [ ] `--danger-text: #FF8A8A` token added (measured: `--danger` fails the 7:1
      state-text bar — see the UI section's §6.5)
- [ ] UI tests per the plan's §6.11, including the token contrast unit test
- [ ] **Update §0 and §6a of this file** — the camera now asserts

### Future — recorded, not scheduled

- [ ] **M4** — armed automatic repair on `REMOVED`, off by default, one per cell per run
- [ ] **Parallax** — `camera` section in `config/rig.json`, `parallax_excess()`,
      the ruler-validation gate; lifts the level-3 ceiling
- [ ] **Stage 15 Stage A** — measurement only, no motion
- [ ] **Stage 15 Stage C** — the `P` verb in **both** sketches, unflashable locally
- [ ] **Validated `block_levels`** — the only route to catching a block stolen
      off the top of a stack
- [ ] **[feature-ideas.md §3.1](feature-ideas.md#31-placement-repeatability-and-backlash---highest-value-per-line)**
      — placement repeatability and backlash; gates Stage 15's correction band
      and decides whether between-build calibration comes back off the shelf

---

## 9. If you are extending this

- **Read [BLOCK-VISION.md](BLOCK-VISION.md) first**, especially §7.
- **Do not add a detector.** Every feature so far has been served by
  `ProcessedFrame.detections` plus geometry. Adding a second analysis path costs
  frames on a Pi that is already timed.
- **Do not put state in `vision/`.** If your feature needs to remember something,
  it belongs in `rig/`.
- **Do not burn overlays into the JPEG.** Overlays are client-side SVG; that is
  what makes them free and toggleable.
- **Do not snap detections onto the lattice.** `block_outline` keeps measured
  centres on purpose — a misplaced block must look misplaced.
- **Say what is uncertain, on screen.** The `approximate` grid styling is the
  pattern: when the map is a guess, the UI already looks like a guess.

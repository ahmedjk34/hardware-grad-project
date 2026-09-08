# Placement supervision — the machine knows what it built, and checks

**Status: BUILT. Gate 0 passed on the rig, M1, M2, M3a and M3b are complete
and wired. M4 and M5 remain future work.** This document is now both the plan
and the record of what was built from it — every deviation is marked in place.

> **2026-09-07 — a geometry layer was added on top of M2.** `rig/placement_geometry.py`
> (coverage / consistency / corridor / residual), `Observation` now carries the
> block's own size and per-cell drift, the CORRECTION gate swapped its `1.2 cm`
> ceiling for a consistency + descent-corridor check, and `step()` downgrades a
> geometrically-impossible `DISPLACED` to `DISAGREES`. **No verdict boundary
> moved.** Consolidated in [§2c](#2c-2026-09-07--the-geometry-layer); the
> DISPLACED-pairing check is the note under [D9](#d9--the-classifier-is-a-set-difference-keyed-to-the-build-area).

> **Not yet watched on hardware.** Every path here is tested, and Gate 0's
> constants were measured on the rig — but the wired code has never seen a real
> frame, because there is no camera on the development desktop. M2's last open
> item is a bench session.

> **Read [placement-supervision-progress.md](placement-supervision-progress.md)
> alongside this document.** It is the build record: the Gate 0 measurements
> taken on the rig, **twenty numbered findings**, and the seven P-decisions.
> **Six places in this document were found to be wrong on contact with the rig
> or the code**, and every one of them is corrected in place below:
>
> | | what was wrong | finding |
> | --- | --- | --- |
> | D5 | the placeholder constants | measured — §1 of the record |
> | D5 | `cell_phase == "idle"` never becomes true again after block one | F14 |
> | D8a | wants a per-cell frame-difference threshold nobody has measured | F17 |
> | D9 | `DISAGREES` was over-conservative on one-sided changes | P1 |
> | D10 | the conclusion holds, the reason given does not | F9 / P3 |
> | §2b | "zero client work" — half of it was a timing impossibility | F18 |

This document **merges and supersedes** two earlier descriptions of the same
foundation: [feature-ideas.md §1.4 / Appendix A](../feature-ideas.md#appendix-a--placement-supervision-full-design)
(which called it `PlacementLedger`) and
[stage-15-placement-correction.md §3](stage-15-placement-correction.md)
(which called it "as-built memory"). They are one component. It is built once,
here, and three features consume it.

In one sentence: **the rig places a block and forgets it; this gives it a
memory, a way to look at the board, and the discipline to say when the two
disagree — without ever guessing.**

---

## 1. The shape of the thing

One **substrate**, three **consumers**. The substrate is this document. Two of
the consumers are elsewhere and one is future work.

```
                    ┌───────────────────────────────┐
   BuildController  │  PlacementLedger (M1)         │
   on PLACED  ─────▶│  what the machine was told to │
                    │  place, and what it reported  │
                    └───────────────┬───────────────┘
                                    │
   ConsolePipeline  ┌───────────────▼───────────────┐
   ProcessedFrame ─▶│  Supervisor (M2/M3)           │
                    │  interlocks, observed set,    │
                    │  hysteresis, classifier       │
                    └───────────────┬───────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
  verdicts (M3)              residual_cm                  residual_cm
  THIS DOCUMENT           Stage 15 — pick up          between-build calib
  operator notified       and re-place one            — DEFERRED, averages
                          outlier block               a population
```

Per cell, the substrate holds:

| Field | From | Consumed by |
| --- | --- | --- |
| `(col, row, level)` commanded, per mode | the ledger hook | all three |
| `result` (`placed` / `rejected` / `aborted`) | `BuildResult` | all three |
| `placed_at` | wall clock | run report |
| `observed_centre_px` / `_cm` | the observer | Stage 15, calib |
| `residual_cm` = observed − commanded | the observer | Stage 15, calib |
| `last_seen` / hysteresis counter | the observer | this document |

Supervision itself reads only **occupancy** — which cells hold *something*. The
`residual_cm` column is built now as data and consumed later; it costs nothing
to record and it is the entire input to the other two features.

---

## 2. Audit — what the code actually has

Verified by reading it, not from the previous designs.

### Exists and is reusable

| Piece | Where |
| --- | --- |
| One place every build funnels through | `BuildController.build()`, the `elif str(result) == PLACED:` branch — [build_controller.py:158](../../python/rig/build_controller.py#L158). Console click-to-build **and** the Studio runner both reach it via `/api/build` → `BuildJob` → here |
| A settled-result publish hook | `_publish_build_result` — [app.py:164](../../python/web/app.py#L164) |
| A per-frame hook on the app loop | `_drive_pipeline` — [app.py:135](../../python/web/app.py#L135), already holds `frame` and `job.poll()` each tick |
| 10 Hz detections off the live feed | `ProcessedFrame.detections` — [console_pipeline.py:44](../../python/rig/console_pipeline.py#L44) |
| **pixel → cell** | `WorkspaceMap.cell_at(point, image_size)` — [workspace.py:372](../../python/rig/workspace.py#L372) |
| cell → cm | `MachineGrid.cell_center_cm(col, row)` — [grid.py:432](../../python/rig/grid.py#L432) |
| channel-max frame difference | the pattern at `_difference_sightings` — [block_grid.py:502](../../python/vision/block_grid.py#L502), `cv2.absdiff(frame, baseline).max(axis=2)` |
| append-only `logs/` convention | [build_log.py](../../python/rig/build_log.py) — git-ignored, no-op until `configure()`, which only `web.app.main()` calls, so pytest never writes |
| mode-latch frame invalidation | already handled: `build_state()` nulls the frame when `frame.grid_mode != rig.grid.mode`; `set_grid_mode` clears `_last_frame` |
| **the entire client path for a per-build verdict** | see §2b — it is already wired end to end |

### Does not exist

| Piece | Note |
| --- | --- |
| any server-side record of what was placed | `web/state.py` carries a selection and `last_result`, nothing cumulative. `BuildJob` is a one-block worker with no history |
| `countPlacedBlock()` as a memory | firmware-side it is `statBlocksAtLevel[level]++` — a **histogram**. It does not record the cell |
| the observer, the classifier, the verdict | this document |

### 2a. Three things the earlier designs got wrong

**These matter. Do not carry them forward.**

1. **Detections are NOT labelled with cells.** Appendix A A.0 and
   removed-block §2 both claim *"`block_outline._lattice_filter` already labels
   every detection with an integer cell."* **It does not.** `_lattice_filter`
   solves indices **relative to `detections[0]`** purely to decide keep/reject,
   then throws them away and returns `(kept, rejected, bearing)`.
   `detect_aligned_blocks` returns plain `BlockDetection` objects carrying a
   pixel `center`, `box`, `angle` and `hue` — no cell. `web/geometry.py` sends
   the browser pixel centres, no cells.
   **Consequence: the supervisor does its own pixel → cell step**, via
   `WorkspaceMap.cell_at`. That is a real piece of work M2 owns, not a free
   input it inherits.

2. **`cell_at` returns `None` for a block in a gap, and that is signal.** It
   returns `None` both when the pixel is outside the quadrilateral **and** when
   it lands in one of the deliberate gaps between block footprints
   ([workspace.py:396](../../python/rig/workspace.py#L396)). A block knocked
   half a cell sideways therefore reads as *no cell*, not *wrong cell*.
   Supervision must treat `None` as **"a block is on the board but not on a
   site"** — which is a `FOREIGN`-shaped fact — and never as a dropout.

3. **Rotation is free; it does not need recording.** Stage 15 §3 wants the
   ledger to store the rotation each block was placed with.
   `BuildController.command` says why it need not:
   *"No rotation word: how the block is laid is a property of the active grid."*
   Rotation ≡ mode. The ledger is keyed by mode already, so rotation is
   derivable and storing it separately would be a second copy that can drift.

### 2b. The per-build verdict's UI is already built

This is the single best piece of news in the audit. The client path exists end
to end and **nothing populates it**:

```
RunnerPanel.tsx:182   reads (state as … ).vision_verification ?? undefined
        ↓
runner.ts:111         RunEvent "build-settled" carries  verification?: string
        ↓
runner.ts:42          RunLogEntry.verification
        ↓
run-report.ts:43      already emits it as a Markdown table column
```

**Half of this held, and the half that did not is instructive (F18).**

The **run report is genuinely free** — `run-report.ts` already emits the column.
The **runner log row was not**, and not because the wiring was missing: it is
there and it works. `RunnerPanel` reads `vision_verification` *at the moment of
the `build_result` event*, and **the verdict cannot exist at that moment** — the
rig has only just parked, and D5 requires a still, settled scene, which is
another ~0.6 s at the measured 8.6-8.7 Hz. At settle time the field necessarily
reads `checking — waiting for a still frame`.

Delaying `build_result` until the check resolves was rejected outright: it is
the terminal event and the ordering around it is already tight (F15). So M3a
added one `build-verified` RunEvent, ~10 lines in `runner.ts`, which patches the
newest build row in place. **The browser still never derives a verdict** — it
renders the server's sentence verbatim.

M3a was still far cheaper than it looks, and was still built first.

---

## 2c. 2026-09-07 — the geometry layer

M2 shipped occupancy only: a cell was a boolean, `in_gap` was a count, and a
`DISPLACED` verdict named a cell without ever measuring where the block
actually was. A pass on 2026-09-07 added a **pure geometry module** and wired it
into supervision and the CORRECTION action. **No verdict boundary moved** — the
VERIFIED / DISPLACED / MOVED split is still `WorkspaceMap.cell_at` on the
centroid (§2a.2). Everything below is measurement layered *on top* of that.

### `rig/placement_geometry.py` — separable 1-D block geometry

Pure interval arithmetic, no camera, no numpy. The grid is separable (footprints
and gaps are axis-aligned strips), so each question is one axis at a time.

| Function | Answers |
| --- | --- |
| `axis_coverage()` | splits a block's extent on one axis into the part over its planned footprint / the gap / the neighbour it drifted toward / **`beyond`** (past that neighbour). `beyond ≈ 0` for a real single-cell displacement; it grows once the block and the cell are more than a pitch apart. |
| `consistency()` | is this one axis-aligned block, one displacement off — not two touching blocks (`measured_size` off nominal), not reaching past a neighbour (`beyond`), not rotated. |
| `drift_axes()` | which machine axes carry a displacement over `DIAGONAL_AXIS_TOLERANCE_CM` (0.5 cm, the map's own residual is ~0.27). One axis = a correctable slide; **two axes = a diagonal**, which `neighbourhood_clear()` refuses until its jaw envelope is measured; zero = within noise of the cell. |
| `corridor_clear()` | on one axis: is there room to lower a jaw between the block and the cell it slid toward — nothing if that neighbour is empty; `gap − cov.gap ≥ JAW_CLEARANCE_CM` if it is occupied. |
| `neighbourhood_clear()` | the whole descent decision (item 5 / audit §1 P0): refuse a two-axis drift outright, else sweep the primary neighbour (`corridor_clear`), the cross-axis neighbour **and** the corner cell between them against an authoritative 3×3 occupancy. Off-grid offsets read empty, so an edge/corner pick cell is safe. |
| `residual_cm()` | `hypot` of the observed-minus-planned centre offset — the one "how far off" number. |

### `Observation` now carries the block's own geometry

`observe()` reads **`BlockDetection.own_angle`** (not the rectified lattice
bearing) and projects **`own_size`** to cm (`_detection_size_cm`, built from the
detection's own box corners), adding three parallel fields:

- `gap_sizes_cm` — footprint of each `in_gap` detection, for `consistency()`;
- `cell_sizes_cm` — same, per occupied cell;
- `cell_residuals_cm` — `(cell, residual_cm)` for every occupied cell. **Advisory
  only** — the classifier never branches on it; it exists so a VERIFIED board
  can still report "the worst block is 0.8 cm off its centre".

### The CORRECTION gate stopped being a distance band

`rig/placement_check.assess()` for a `DISPLACED` verdict: the `0.5 cm` **floor**
stays (below it a pick-lift-place adds more error than it removes); the `1.2 cm`
**ceiling is gone**. `CORRECT_BAND_MAX_CM` and `judge_band`'s `REFUSE` branch
were deleted. In their place: `consistency()` + `neighbourhood_clear()`, fed the
block's `own_size` and the full 3×3 of ledger/detection occupancy around the
pick cell. A block displaced far along **one** axis whose neighbours are
**empty** — the whole of vertical Y in a normal build — is still correctable; a
block that drifted on **both** axes at once is refused as an unmeasured diagonal
(item 5). `MOVED` is unchanged (`MOVED_PICK_SANITY_CM`). Provisional constants:
`SIZE_TOLERANCE_CM = 0.8`, `JAW_CLEARANCE_CM = 0.4`,
`DIAGONAL_AXIS_TOLERANCE_CM = 0.5`, `DIAGONAL_CORRECTION_SUPPORTED = False` —
Stage 15 Stage B. Full detail in
[correction-action.md](correction-action.md), 2026-09-07 and 2026-09-08 notes.

### `step()` rejects a `DISPLACED` pairing the geometry cannot support

See the note under **D9** below — `Supervisor.step(grid=…)` runs
`implausible_displacement()` and downgrades to `DISAGREES` when the gap block is
more than `PAIRING_BEYOND_CM` (1.0, provisional) past the cell `classify` paired
it with. This is what surfaces a **misregistered workspace map**: it trips on
every displacement instead of publishing a confident wrong verdict.

### The published model

`SupervisionState` / `SupervisionModel` (§5) gained two **advisory** fields,
`residual_cm` (the MOVED / DISPLACED offender's distance) and
`max_cell_residual_cm` (worst on-cell drift, present for VERIFIED too). Both are
display-only — no state colour, they gate nothing. `web/src/types.ts` matches.

### 2c-bis. 2026-09-08 — one coherent, stable, block-consistent track (audit items 6 + 9)

`observe()` collapsed detections to a set and stored only the **first** per cell,
and the CORRECTION action then took that first candidate from **one frame** for
the pick coordinate. A merged blob, a duplicate hypothesis, a candidate switch
or an unstable track all read as a clean single-block pick.

- **Multiplicity survives.** `Observation.detections_detail` — one
  `DetectionRecord` per detection, in detector order, kept whole — is populated
  by `observe()` before any per-cell collapse. The set verdict is unchanged; the
  multiplicity is now visible to the layer that needs it.
- **`_TrackHistory`** is a sibling of item 7's `_gap_history`: fed from the
  **same** `observation` in the **same** `step()` on the **same** N-of-M quiet
  window, cleared by the **same** `_reset_hysteresis()` primitive — *not* a
  second analysis path or extra frames (audit §2.4). It associates every
  block-shaped detection (cell or gap) frame to frame by cm anchor and fuses the
  matched run: **median** centre, **circular-mean** angle (period 180, so ±180
  wraparound never inflates the scatter), **median** size, with a per-axis and
  radial **dispersion** and a **worst per-frame residual**.
- **The gate.** `Supervisor.track_evidence_at(point_cm)` returns a
  `TrackEvidence`. `assess_frame_correction(..., track=…, require_track=True)` —
  the live `_supervise` path **and** the `/api/supervision/correct` re-check —
  refuses a `MOVED` / `DISPLACED` correction unless that track is `settled`
  (≥ N frames), `consistent` (multiplicity ≤ 1 **and** not an anti-phase
  candidate switch — `_looks_like_switch` tells a switch from a genuine occupied
  neighbour by anti-correlated presence, not distance) and `stable` (centre /
  angle / size dispersion each under its ceiling). When it passes, the fused
  centre / angle / size **replace** the single-frame values the pick offset is
  computed from. `MOVED` now also runs the `consistency()` size/shape gate
  `DISPLACED` already had.
- **Published.** `SupervisionState` / `SupervisionModel` gained advisory
  `localization_sigma_cm`, `localization_residual_cm`, `track_samples`
  (`[frames_seen, window]`) — display-only, no state colour, gate nothing.
- **Provisional constants** (Python-only, no firmware partner), all wanting the
  rig localisation-repeatability run of audit §7.5:
  `TRACK_IDENTITY_MATCH_CM = 1.2` (deliberately tighter than
  `GAP_IDENTITY_MATCH_CM = 2.0` — a track must separate a displaced block from
  its adjacent neighbour cell), `SWITCH_NEIGHBOUR_CM = 3.0`,
  `TRACK_CENTRE_SIGMA_MAX_CM = 0.6`, `TRACK_ANGLE_SIGMA_MAX_DEG = 4.0`,
  `TRACK_SIZE_SIGMA_MAX_CM = 0.8`.

### 2c-ter. 2026-09-08 — refuse diagonal correction; sweep both neighbours + the corner (audit item 5)

The `DISPLACED` descent check took `drift_axis()` — the *larger* of the two
displacement components — and put only that one neighbour's corridor through
`corridor_clear()`. A block shoved **diagonally** into a corner gap narrows two
corridors and the corner between them at once; if the dominant axis' neighbour
happened to be empty, the correction was approved (audit §1 P0).

- **`drift_axes()`** (plural) reports *every* axis carrying more than
  `DIAGONAL_AXIS_TOLERANCE_CM = 0.5` cm — deliberately the correction floor, and
  well above the map's ~0.27 cm flattening residual, so a sub-floor cross
  component is noise, not a second drift direction.
- **`neighbourhood_clear()`** replaces the single `corridor_clear()` call.
  A drift on **both** axes is refused outright — `DIAGONAL_CORRECTION_SUPPORTED
  = False` until the swept jaw envelope for a two-axis approach is bench-measured
  (audit §7.5 `JAW_CLEARANCE_CM`). A one-axis drift is swept against an
  **authoritative** 3×3 occupancy: the primary neighbour (`corridor_clear`), the
  cross-axis neighbour, **and** the corner cell past the primary neighbour (a
  hazard only when the block has closed *both* adjacent gaps to within a jaw
  width). Off-grid offsets read empty, so an edge or corner pick cell is handled
  without an index error and with nothing phantom to foul.
- **`assess()`** refuses a two-axis drift *before* any grid geometry (needs only
  the displacement), so a degenerate no-map path cannot slip one through; the
  reason quotes the per-axis drift and says "clear it by hand". `web/state.py`
  builds and passes the full 3×3 (`_cell_occupied` over detections + ledger
  top-levels). The `diagonal_supported` flag is forced off whenever the caller
  cannot supply that 3×3 — the corner/cross sweep is never run on inferred
  occupancy.
- `MOVED` is untouched: its pick target is a real lattice cell whose gaps are
  clear by definition, not a gap between two blocks.
- **No firmware / `config/rig.json` change**; `DIAGONAL_AXIS_TOLERANCE_CM` and
  `DIAGONAL_CORRECTION_SUPPORTED` are Pi-side supervision policy with no partner.

### The `include_rejected` intake, and its open edge

`console_pipeline.py` now calls the detector with `include_rejected=True`
(BLOCK-VISION §2), so an off-lattice block reaches `observe()` at all. The open
edge: shape junk the lattice filter rejected reaches it too, and can become
spurious `in_gap` evidence on a messy bench. A block-shape gate for off-lattice
detections was proposed and **not built** — progress.md F24.

---

## 3. The decisions

### D1 — Occupancy diff, not motion tracking

A moved block is found by comparing **which cells are occupied** against **which
cells should be occupied**. No tracker, no per-block identity, no velocity.

Twenty-nine identical wooden rectangles and a stateless per-frame detector: data
association across frames fails precisely under occlusion, which is the only
case that matters. A speed threshold would conflate a hand, the detector's own
centre jitter, and the gantry placing a block on purpose. Motion earns exactly
one job, in D5: a **gate**, never a classifier.

The full case — the three tiers of "identity", what each would unblock, why
persistent re-ID is not feasible on this camera, and the cheap window-scoped
tier that most "why not tell them apart?" questions are actually reaching for —
is [block-identity.md](block-identity.md).

### D2 — The ledger records commands, not pixels

`PlacementLedger` is the authority on what *should* be there, and everything in
it is a **command the machine already issued** plus the result the firmware
reported. Nothing is inferred, which is what makes a memory of block placement
defensible rather than hand-wavy.

Written at one hook: `BuildController.build()`, on a settled `PLACED`. Never on
`rejected`, never on `aborted` — a rejected build placed nothing, and an aborted
one means the machine state is unknown, which is a lock, not a ledger entry.

The ledger is **pure data** — cells, levels, modes, timestamps. `BuildController`
"deliberately knows nothing about OpenCV" and this must not change that.

### D3 — Persist for the record, refuse to trust on reload

Two things that sound contradictory and are not:

- **Append to `logs/placements.log` as it goes.** It is thesis evidence and it
  costs nothing. Same conventions as [build_log.py](../../python/rig/build_log.py):
  git-ignored, no-op until configured, never written by pytest.
- **Never reload it as authority.** On startup the memory is empty and
  supervision reports `NO MEMORY — run a job first` and refuses every verdict.

The reason for the asymmetry: a reloaded ledger claims to describe a board no
one has looked at since the process died. Appendix A originally proposed
reloading it; Stage 15 §3 proposed refusing. **Refusing wins**, because the
consumers of this substrate drive a claw.

**Scoped by mode AND board epoch (audit item 8).** `has_memory` is not one
global boolean. Every entry is stamped with the `board_epoch` it was placed in;
`PlacementLedger.new_board_epoch()` — called on a gantry reboot (`@0 BOOT`),
reconnect or operator board swap — starts a fresh epoch. The rows are kept for
the record, but `has_memory(mode, board_epoch)`, `expected_occupancy` and every
derived predicate answer for the *current* epoch and the *active* mode only.
Without this, horizontal-only placements made vertical mode report "memory"
against an empty expected set — `VERIFIED` on an empty view, `FOREIGN` on a real
vertical board — and a settled verdict leaked across a reboot onto the board
that replaced it. The supervisor treats an epoch change exactly like an R/RR
latch: it drops both hysteresis histories through `_reset_hysteresis()`, item
7's one reset primitive, never a second mechanism.

### D4 — Occupancy is a column, not a level

The camera is above the board; a block at level 1 hides the one beneath it. So
the observed set is *cells holding something*, and the expected set is *cells
with any block placed*. Supervision is **level-blind for the idle sweep** and
says so on screen.

Two consolations, and they are real: level 0 is where every structure starts,
and a **toppled** stack changes the occupied set — the fallen block lands
somewhere it should not be — so the failure that endangers the next placement is
caught. Only the tidy theft off the top of a stack is not.

**The per-build check (D8) is a different story and is not level-blind** — see
there.

### D5 — Judge only in the quiet window

The rule the feature lives or dies on. Three interlocks, **all required**:

| Interlock | Why | How |
| --- | --- | --- |
| **gantry parked** | the arm crosses the board, occludes cells, and *is* a legitimate change | `not job.running` **and** `not controller.locked` **and** `cell_phase == "idle"` |
| **map is real** | with no saved calibration the pipeline falls back to `approximate_workspace`, and `cell_at` is then confidently wrong | `frame.calibrated` — refuse every verdict when false, and say so as `NO MAP` |
| **scene quiet** | a hand is a large moving occluder | channel-max frame difference against the last accepted frame; energy over `QUIET_DIFF_FRACTION` → discard the frame and restart the settle timer |
| **settled** | one clean frame is not evidence | a cell must read the same way in `N of M` consecutive quiet frames |

Starting values to be **measured on hardware, not trusted from here**:
`QUIET_DIFF_FRACTION = 0.02`, `SETTLE_N = 3`, `SETTLE_M = 5`, at the existing
10 Hz — about half a second of stillness per verdict.

**Threading.** The set math is trivial and belongs on the event loop with the
rest of `_drive_pipeline`'s bookkeeping. **The frame difference does not** — it
is a full-frame numpy op (~5–15 ms at 1296 px on a Pi 5) and must go to the
same single-threaded executor as the other OpenCV work, per AGENTS.md §7's
one-owner-thread rule. Do not let it run on the loop because it is "only a
subtraction".

### D6 — The level ceiling, and why it is not optional

**Parallax is ignored in v1** (the decision), and
[camera-parallax-and-levels.md §4](camera-parallax-and-levels.md#4-the-price-of-ignoring-it--the-level-ceiling)
is the price. Short version:

`ConsolePipeline` calls the detector **with a grid**, so `_lattice_filter`
drops anything more than `LATTICE_SNAP = 0.34` cells off an integer site.
Parallax eats that budget as levels rise:

| Expected top level | v1 behaviour |
| --- | --- |
| 0, 1, 2 | **safe** — parallax stays inside the budget everywhere |
| 3 | **marginal** — survives rows 1–5, dropped on row 0 |
| ≥ 4 | **invisible everywhere** |

> **Supervision must refuse to judge any cell whose expected top level is ≥ 3,
> and must never emit `NOT DETECTED` or `REMOVED` for one.**

Above the ceiling an absent detection is a *filter artifact*, not a missing
block, and reporting it would be the feature lying. Refused cells are listed on
screen as `unjudged`, not silently skipped.

This is survivable only because the structures being built are **short towers
(2–3 high)**. If that changes, the parallax doc stops being future work.

### D7 — Confidence in a cell, not a boolean

Each cell carries a small hysteresis counter. Single-frame dropouts are jitter;
two consecutive dropouts in a quiet, parked, settled scene are an event. A
cell's state changes only when the counter saturates, and the counter is
**reset, not decayed**, whenever an interlock trips — a frame that was not
allowed to be judged must not leak partial evidence into the next verdict.

### D8 — Two triggers, one classifier

Same machine, run at two moments:

**Per-build (D8a).** One evaluation in the first quiet window after a build
settles, with the ledger entry already appended. Asks a narrow question: *did a
block appear at the cell I just commanded?* This is a **frame difference against
the pre-build frame**, and it is **not level-blind** — the block just placed is
the top of its stack, so it is visible. The block underneath was verified in its
own window. Result is a short string into `vision_verification` (§2b).

**Continuous (D8b).** Every quiet window while parked, whole-board occupancy.
This is the one that catches a hand, and it is level-blind per D4.

Per-build catches a block that never left the claw. Continuous catches a human.
Neither is a special case of the other, and the user asked for both.

### D9 — The classifier is a set difference, keyed to the build area

Evaluated against `ledger.expected_occupancy(mode)`. The **build area** is the
rectangle of cells plus the deliberate gaps between them —
[`locate()`](../../python/rig/supervisor.py) already derives it from the grid,
splitting every detection into `cell` / `gap` (inside it) versus
`margin` / `outside` (not).

| Condition | Verdict | Severity |
| --- | --- | --- |
| sets equal | `VERIFIED` | — |
| one missing, one unexpected **cell**, no gap detection | `MOVED [a,b] → [c,d]` — relocated to a valid site | notify |
| one missing, **nothing** on a cell, exactly one gap detection | `DISPLACED [a,b]` — knocked off its cell into the build area, on no site | notify |
| N cells missing, **nothing** anywhere in the build area | `REMOVED`, naming all N — gone from the build grid | notify |
| N cells unexpected **or** a gap detection, **nothing** missing | `FOREIGN`, naming the cells | stop |
| both sides changed, or the change will not pair one-to-one | `BOARD DISAGREES` | **stop the program** |

> **`MOVED` / `DISPLACED` are one event, split by landing.** A block left the
> cell the plan put it on. It came to rest on another valid cell (`MOVED`,
> `cells = [from, to]`, the overlay draws an arrow) or in the build area on no
> site at all (`DISPLACED`, `cells = [from]`, no arrow). Both are recoverable by
> hand — straighten or re-run — so both **pause**; the split exists because the
> operator does different things about them. Before this, a block nudged into a
> gap was a red `FOREIGN` that named no cell.
>
> **The one-sided rows are a refinement of the originally approved design,
> decided with the user as P1.** The design sent every change of more than one
> cell to `DISAGREES`. `DISAGREES` protects against the absence of **identity**,
> and identity only matters when there is something to pair with. N cells
> emptied with nothing gained anywhere needs none. `test_supervisor.py` asserts
> every row on exact cell sets.

Neither `MOVED` nor `DISPLACED` claims it is the same block — identical objects,
no identity, no proof available ([block-identity.md](block-identity.md)). Neither
needs one: exactly one cell emptied and exactly one thing arriving, in a window
D5 guarantees is free of occlusion, has one story. The actionable fact is where
it ended up.

`DISPLACED` requires **exactly one** gap detection. One cell out with two gap
detections, or one out plus one onto a cell *and* a gap detection, will not pair
cleanly → `DISAGREES`.

> **Update — 2026-09-07: the pairing is now checked geometrically.** `classify`
> matches the one emptied cell to the one gap detection by set difference alone
> — it never checks they are near each other, so a block genuinely removed from
> `[a,b]` plus an unrelated detection reading in a gap far away would still
> publish a confident `DISPLACED [a,b]` and offer a nonsense correction. When
> `Supervisor.step()` is given the mode's `MachineGrid`, `implausible_displacement()`
> projects the gap detection against `[a,b]`'s lattice centre
> (`rig.placement_geometry.axis_coverage`); if the block reaches more than
> `PAIRING_BEYOND_CM` (provisional, 1.0 cm) past `[a,b]`'s neighbour — i.e. the
> two are more than a pitch apart — the verdict is downgraded to `DISAGREES`
> with a reason naming the distance. A misregistered workspace map trips this on
> every displacement, which is the intended loud failure.

`BOARD DISAGREES` is not a failure of the classifier; it is the classifier
declining to guess. A toppled short tower lands here, and it **stops the
program** rather than pausing it — two simultaneous changes in one half-second
window means something happened this model does not describe. After P1 it means
precisely *"both sides changed and I cannot pair them"*, which is the only case
that actually needs identity.

### D10 — Sparse boards get no `FOREIGN` — **REMOVED**

**Deleted from the code when the holder was taken off the rig.** The tombstone
stays because CAMERA.md, feature-ideas.md and §9 all pointed here.

D10 suppressed `FOREIGN` and `DISAGREES` while the frame held fewer than
`MIN_LATTICE_BLOCKS = 6` detections. Two rationales were tried. The first —
"below 6 the observed set is unfiltered because `_lattice_filter` skips" — was
wrong (F9): that filter was never supervision's defence against junk, `locate()`
is, and it classifies by geometry at any detection count. The second (F9 / P3)
was the holder's two offcuts beside `[0,0]`: on the board, inside the envelope,
so `locate()` calls them `gap` and D9 makes a gap detection `FOREIGN` — a red
stop every time two offcuts sit where they always sit.

With the holder physically removed that last rationale is gone, and the
threshold was a hand-me-down constant with a cliff shape and a junk-inflated
input (F8). It is deleted. `classify()` no longer takes a `detections`
argument; `Supervisor.note_regime` and the `_lattice_filter`-crossing hysteresis
reset (P2) went with it.

> **Consequence, deliberate:** `FOREIGN` and `DISAGREES` are now live from the
> first placed block — including on block one after a restart with blocks still
> on the board (an empty ledger against a non-empty board). That is a correct
> verdict, not a bug: there are cells the plan cannot account for. The operator
> dismisses per D12.

To keep that from being noisy, the one signal that used to bypass D7's
hysteresis — `in_gap` — now gets it: a non-zero `in_gap` reaches the classifier
only after `SETTLE_N` of the last `SETTLE_M` judged frames saw a gap detection.
A single frame of centroid jitter across a footprint boundary no longer stops
the program. This is denoising only; it does **not** name the gap cell, and it
is not the fix for a `MOVED` block that lands off a site (that needs per-gap
identity — separate work).

Re-verified against all four Gate 0 traces: verdict tallies are unchanged by the
removal.

### D11 — Notify, never act *automatically*

On any verdict the machine **stops or pauses and tells the operator**. A verdict
never moves the rig **on its own**.

**Carve-out (2026, [CORRECTION action](correction-action.md)):** the operator
may press `RETURN BLOCK TO CELL` on a `MOVED` / `DISPLACED` verdict. That is a
deliberate, confirmed, one-attempt override — the operator acts, not the
verdict — and it is gated server-side (vertical, level 0, axis-aligned, no
taller neighbour, destination clear, band-checked). It drives the firmware `P`
verb via `POST /api/supervision/correct`. A dropped grip **locks** the session
(`HELD` is a machine fact); every other outcome re-verifies per D12 before the
runner resumes. Everything below still holds for the notify-only default.

- `REMOVED` / `MOVED` / `DISPLACED` / `NOT DETECTED` → **pause** the runner, name the cell(s).
- `FOREIGN` / `BOARD DISAGREES` → **stop** the program, show both sets.
- **A supervision verdict never `LOCK`s.** `LOCKED` is reserved for "the claw's
  position is unknown" and needs a human plus a service restart. A verdict is a
  statement about the *board*, not about the *machine*, and conflating them
  would make a recoverable situation look unrecoverable.

**Automatic repair is future work** — see M4. The design for it is kept because
it was decided, not because it is next: `REMOVED` → re-issue `B a b <level>`,
off by default, one per cell per run, never during a running build. It is
deliberately not in v1 because *a machine that re-places a block a human just
deliberately removed is infuriating*, and v1 has no way to tell the two apart.

### D12 — The operator dismisses, and the board is re-checked

The notification carries the dismissal. Acknowledging it means "I have dealt
with this" — whether they put the block back or chose not to.

**After a dismissal the cell is re-checked in the next quiet window before the
runner continues.** A repair that is not re-verified is a guess with extra
steps, and that applies just as much to a human's repair as to a machine's.

(Future: a persistent "I removed this deliberately, stop asking" mark. v1 has
one dismissal and it is per-event.)

### D13 — One mode at a time; pause across a latch

The two grids are different lattices with different registration — 7 × 6 vertical
vs 3 × 10 horizontal. The ledger is keyed by mode.

An `R` / `RR` latch **suspends supervision** until the first quiet window on the
other side. The frame plumbing already helps: `build_state()` nulls the frame
when `frame.grid_mode != rig.grid.mode`, and `set_grid_mode` clears
`_last_frame`. The supervisor additionally **resets its hysteresis counters**
when it sees `frame.grid_mode` change — per D7, evidence gathered under one
lattice must not leak into a verdict about the other.

### D14 — Always on, notify-only

Idle supervision runs whenever the rig is parked and unlocked. No arming toggle,
because it produces no motion and the whole point is that it is watching when
nobody thought to ask it to. The **repair** path (M4) is what gets a toggle.

---

## 4. Where it lives

**Every line of this is now built.** Two files were added that the plan did not
anticipate: `web/src/components/SupervisionBanner.tsx` and
`web/src/studio/scene/Supervision.tsx`.

```
python/rig/placement_ledger.py   NEW   D2/D3 — the memory. Pure, no I/O beyond
                                       the append-only log. No OpenCV.
python/rig/supervisor.py         NEW   D5-D9 — interlocks, pixel→cell, hysteresis,
                                       classifier. Consumes ProcessedFrame +
                                       WorkspaceMap. Adds no detector.
python/rig/build_controller.py   edit  one call on the PLACED branch
python/web/app.py                edit  hand each frame to the supervisor in
                                       _drive_pipeline; per-build trigger in
                                       _publish_build_result
python/web/state.py              edit  + vision_verification, + supervision block
python/web/routes_command.py     edit  POST /api/supervision/ack
web/src/types.ts                 edit  the two new state fields
web/src/studio/runner.ts         edit  a "board-verdict" RunEvent → pause/stop
web/src/components/GridOverlay.tsx  edit  a per-cell class on the LIVE VIDEO —
                                       same mechanism as `blocked` cells today
web/src/components/SupervisionBanner.tsx
                                 NEW   the only surface allowed to alarm
web/src/studio/scene/Supervision.tsx
                                 NEW   the twin's overlay LAYER — not a sixth
                                       TwinAppearance
web/src/components/RunnerPanel.tsx
                                 edit  build-verified + board-verdict dispatch
web/src/style.css                edit  + --danger-text, the cell/hatch/banner
                                       classes, the ONE-SHOT pulse
web/src/tokens.test.ts           NEW   the contrast bar, read off the real
                                       stylesheet so a palette edit cannot
                                       break it in silence
```

**This is the error detector**, and it is deliberately **not** in `vision/`.
Detecting an error is a subtraction — *what should be on the board* minus *what
is on the board* — and the camera can only supply the second operand. The first
is a memory of commands the machine issued, which has nothing to do with pixels.
Putting the subtraction in `vision/` would give you a detector that needs to
know about the ledger, the grid mode and whether the gantry is parked, which
breaks the layering rule and makes it untestable without a rig. See
[CAMERA.md §5](../CAMERA.md#5-where-is-the-error-detector-isnt-it-part-of-the-camera).

**`vision/` is not touched.** The supervisor consumes `ProcessedFrame.detections`
and the `WorkspaceMap`; it adds no detector, no second analysis path, and no
extra frames. BLOCK-VISION §2 already measured what "better settings for this one
purpose" costs — up to 3.9 s a frame for zero extra blocks. The layering rule of
[BLOCK-VISION §7](../BLOCK-VISION.md) holds: **supervision is a fourth layer
above `block_outline` and reaches past nothing.**

Nothing is stored as an image. State is a set of cells, a counter per cell, and
timestamps.

---

## 5. The state model — the server contract

### One field, four readers

The requirement — *appears everywhere and stays in sync* — is met
**structurally, not by discipline**: the server publishes one object and every
surface renders it. **No surface re-derives a verdict locally.** Four renderers
of one field cannot disagree, so "sync" is not a thing anyone has to maintain.

As built, with one field added — `severity`. It is here because **no surface may
re-derive a verdict**, and "is this amber or red" is exactly the kind of thing
four renderers would each work out for themselves and eventually disagree about.
The server decides once.

```python
class SupervisionModel(BaseModel):
    state: Literal["NO_MEMORY", "NO_MAP", "NO_VISION", "WARMING", "BUSY", "QUIET", "VERDICT"]
    verdict: Literal["VERIFIED", "NOT_DETECTED", "REMOVED",
                     "MOVED", "DISPLACED", "FOREIGN", "DISAGREES"] | None
    severity: Literal["none", "amber", "red"]   # ADDED — never "locked"
    cells: list[tuple[int, int]]          # the cells the verdict names
    mode: str                             # which lattice it was judged in
    expected: list[tuple[int, int]]       # both sets, for DISAGREES
    observed: list[tuple[int, int]]
    unjudged: list[tuple[int, int]]       # refused by D6's level ceiling
    reason: str | None                    # why not judging, when state != VERDICT
    judged_at_ms: int | None
    acknowledged: bool
```

Plus the free win from §2b, published beside it:

```python
vision_verification: str | None   # "verified" / "not detected at [2,2]" /
                                  # "unchecked — level 3 above the ceiling"
```

### What this does to the camera's role

Recorded in full in [CAMERA.md §6a](../CAMERA.md#6a-before-and-after) — which
also compares this feature against [Stage 15](stage-15-placement-correction.md),
the *other* camera-based error detector, and explains why they get their
detections by different routes. The short version is the point of this feature:

**Done.** The "after" column is the present tense as of M3a/M3b.

| | before | now |
| --- | --- | --- |
| the camera is a… | monitor + calibration instrument | **instrument that asserts** |
| detections are… | drawn | drawn **and read** |
| a wrong board… | looks wrong to a human who happens to be looking | **stops the machine and names the cell** |
| the run report says… | `placed` — the firmware's own word for it | `placed` **and verified in frame** |

No new hardware, no second camera, no extra frames, and `vision/` is not
touched. The change is entirely one of **who is allowed to have an opinion**.

---

## 6. The UI — how every verdict gets its right treatment

[DESIGN.md](../DESIGN.md) is the authority and nothing here overrides it. This
section is the *application* of that system to one new class of information:
**a machine opinion about the board.**

### 6.0 The one rule this section exists to enforce

DESIGN.md §2: *"Colour is reserved. Green, amber and red mean READY, MOVING and
LOCKED. Nothing decorative is allowed to use them. If a colour appears, it is
telling you about the machine."* And §3.1's semantic split:

> **Amber = degraded but recoverable, or the machine is moving.
> Red = stop, a human is required.**

Every choice below is that sentence applied to six verdicts. Get this wrong and
the console cries wolf; a console that cries wolf during a demo is worse than
one that says nothing.

### 6.1 Four surfaces, four *roles* — they must not all shout

The failure mode of "show it everywhere" is four red things saying one thing.
Each surface answers a different question, and only one of them is an alarm.

| Surface | Answers | Loudness |
| --- | --- | --- |
| **Camera overlay** — `GridOverlay.tsx` | **WHERE** — the spatial answer, on the live video | primary. This is where the operator is already looking |
| **Banner** — new component | **WHAT, and WHAT NOW** — the sentence and the action | the only alarm |
| **Runner panel** — existing | **WHEN** — where in the sequence, and why the run stopped | quiet, historical |
| **Twin** — overlay layer | the plan-space echo | quietest. It is a mirror, not a siren |

The camera overlay is the cheapest *and* the most valuable: `GridOverlay.tsx`
already draws per-cell polygons with per-cell classes — exactly how `blocked`
cells work today — and `geometry.grid` already ships a `target_polygon` per
cell. **One CSS class and one filter over a list the browser already has.**

The twin's rule survives intact: it never invents state, because the verdict is
the server's. And **no sixth `TwinAppearance`** — the twin has exactly five,
`twin.test.ts` asserts them, they are its documented contract. Supervision is a
separate overlay layer keyed by cell, drawn on top.

### 6.2 The verdict → treatment matrix

This is the table that "gives everything its right". Every column is a decision,
not a default.

| Verdict | Word on screen | Icon | Colour | Banner | Camera cell | Runner | Dismiss | ARIA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `VERIFIED` | `VERIFIED` | ● | `--ready` | **none** | one 200 ms pulse, then plain | log row only | n/a | `status` |
| `NOT_DETECTED` | `NOT DETECTED [c,r]` | ▲ | `--motion` | persists | amber outline + fill | **pause** | operator | `status` |
| `REMOVED` | `REMOVED [c,r]` | ▲ | `--motion` | persists | amber outline + fill | **pause** | operator | `status` |
| `MOVED` | `MOVED [a,b] → [c,d]` | ▲ | `--motion` | persists | amber on **both** cells, arrow between | **pause** | operator | `status` |
| `DISPLACED` | `DISPLACED [a,b]` | ▲ | `--motion` | persists | amber outline + fill on the origin cell, no arrow | **pause** | operator | `status` |
| `FOREIGN` | `FOREIGN BLOCK AT [c,r]` | ■ | `--danger` | persists, **cannot dismiss unacknowledged** | red outline + fill | **stop** | explicit ack | `alert` |
| `DISAGREES` | `BOARD DISAGREES` | ■ | `--danger` | persists, **cannot dismiss unacknowledged** | red on every differing cell, expected vs observed keyed | **stop** | explicit ack | `alert` |

**`VERIFIED` gets no banner, deliberately.** A 40-block build would produce 40
green bars. The good case must be *near-silent* — it lives in the log row and
one brief cell pulse. A console that celebrates every success trains the
operator to ignore it, and then the one amber bar that matters is ignored too.

**Why `MOVED` and `DISPLACED` are amber and `FOREIGN` is red**, when all three
involve a block in the wrong place: on `MOVED` / `DISPLACED` exactly one cell
emptied and exactly one thing arrived, so the story is complete and a human can
act on it — recoverable. On `FOREIGN` there is a block the system cannot account
for sitting where the plan may need to place later; doing so is a collision.
That is D9's "stop", and red is D9's severity column rendered.

### 6.3 The observer's own states — and the BUSY trap

The verdict is only half of what the banner shows. The other half is *whether
supervision is even looking*, and this is where a naive implementation ruins
the colour system.

| `state` | Strip reads | Icon | Colour | Note |
| --- | --- | --- | --- | --- |
| `NO_MEMORY` | `NO MEMORY — run a job first` | ○ | `--text-faint` | **not a fault.** Expected after every restart (D3) |
| `NO_MAP` | `NO MAP — calibrate to enable checks` | ▲ | `--motion` | genuinely degraded; the grid overlay already styles itself `approximate` here |
| `NO_VISION` | `NO VISION — the detector could not read this frame` / `CAMERA STALE` | ○ | `--text-dim` | **not a board fault.** The detector raised, or the analysed image aged out before its result landed. Distinct from an empty board (never becomes `REMOVED`) and from `BUSY` (the camera pipeline, not the rig, is the thing at fault). Raised in `web/app.py`'s `_supervise`, not by `Supervisor.step`. |
| `WARMING` | `SETTLING n/3` | ◐ | `--text-dim` | gathering evidence |
| `BUSY` | `RIG MOVING` / `SCENE NOT STILL` | ○ | `--text-dim` | **not a fault** |
| `QUIET` | `WATCHING` | ○ | `--text-dim` | the resting state |
| `VERDICT` | per §6.2 | per §6.2 | per §6.2 | |

> **The trap: `BUSY` is the normal state during a whole build.** Colour it amber
> and the console is amber most of the time, at which point amber has stopped
> meaning "degraded" and the reserved palette is dead. `BUSY` and `QUIET` are
> **`--text-dim`, no state colour at all.** Not looking is not the same as
> finding something wrong.

`NO_MEMORY` is likewise neutral, not a warning — it is the honest, expected
condition after a restart, and DESIGN.md's colour budget should not be spent on
it.

### 6.4 Showing what we *cannot* see — hatch, not colour

Two separate blindnesses have to be visible (D4, D6): cells above the level-3
ceiling and the level-blind idle sweep. Neither is a *machine state*, so
**neither may take a state colour.** (A third — `FOREIGN` suppression on a
sparse board — went away with D10.)

The answer is a **non-colour channel**: a 45° diagonal hatch at low opacity over
the cell, plus a count in the banner strip.

```
UNCHECKED  3 cells above level 2   ⟋⟋⟋
```

- SVG `<pattern>` fill on the cell polygon, `--text-faint` at ~18 % opacity.
- Each hatched cell gets an SVG `<title>`: *"not checked — expected top level 3
  is above the detection ceiling"*.
- The banner names the **count and the reason**, always — never a silent skip.

This satisfies "never colour alone" trivially, because it is not colour, and it
keeps the reserved palette intact for actual machine state. It also directly
serves the thesis point: **the feature states its own limits on screen**, which
is demo beat 6.

### 6.5 Colour and contrast — measured, not assumed

DESIGN.md §7 requires body text ≥ 4.5:1 and **state text ≥ 7:1**, and warns that
*"amber is the one that usually fails."* Computed against `--surface` `#14181C`:

| Token | Hex | vs `--surface` | vs `--void` | Verdict |
| --- | --- | --- | --- | --- |
| `--ready` | `#3DD68C` | **9.51:1** | 10.38:1 | passes 7:1 |
| `--motion` | `#F0A73E` | **8.75:1** | 9.55:1 | passes 7:1 — the warning is wrong |
| `--danger` | `#FF5C5C` | **5.89:1** | 6.43:1 | **fails 7:1** |
| `--text` | `#E6EDF3` | 15.10:1 | — | |
| `--text-dim` | `#9AA7B2` | 7.26:1 | — | |

> **Finding: `--danger` is the token that fails DESIGN.md's own bar, not amber.**
> At `#FF5C5C` red does not reach 7:1 on **any** of the app's dark grounds.

Two fixes, use both:

1. **State colour never carries body copy.** The state is carried by the
   **icon + the plate edge + a bold uppercase chip**; the sentence is `--text`
   at 15:1. A chip at ≥ 18.66 px bold is WCAG "large text" (3:1 bar), and
   `--void` on filled `--ready` / `--motion` / `--danger` plates measures
   10.38 / 9.55 / **6.43:1** — all clear.
2. **Where red genuinely must be text-sized**, add one token:
   `--danger-text: #FF8A8A` → **7.86:1** on `--surface`, 8.58:1 on `--void`.
   Same hue, passes the bar. Do not lighten `--danger` itself — the existing
   `LOCKED` treatment depends on it.

### 6.6 Motion — one pulse, and never on a loop

DESIGN.md §3.4 plus the UX rules: 150–300 ms for micro-interactions, animate
1–2 elements per view maximum, continuous animation for loading indicators
**only**.

| Element | Motion |
| --- | --- |
| Camera cell on a new verdict | fill fades in **200 ms `ease-out`**, then **one** 400 ms pulse. Once. |
| Banner appearing | 200 ms slide+fade from the top edge |
| `VERIFIED` cell | one 200 ms pulse, no persistent mark |
| Everything else | **no motion** |

> **Never loop the alert pulse.** A cell that throbs forever becomes wallpaper
> in about ninety seconds, and the operator stops seeing exactly the thing the
> feature exists to show. The information lives in colour + icon + word; the
> pulse only earns attention at the *moment of change*.

```css
@media (prefers-reduced-motion: reduce) {
  .grid-cell.sv-verdict, .sv-banner { animation: none; transition: none; }
}
```

Under reduced motion the tint appears instantly. **Nothing is conveyed by
motion alone**, so nothing is lost.

### 6.7 Accessibility — the checklist this must pass

| Requirement | How |
| --- | --- |
| **Never colour alone** | every verdict carries a **word** and an **icon shape** — ● verified, ▲ attention, ■ stop, ○ idle, ◐ settling. Matches DESIGN.md §4's existing ● ▲ ■ vocabulary |
| Live regions | amber verdicts `role="status" aria-live="polite"`; red verdicts `role="alert"`. Mirrors the existing result / locked banners |
| SVG is not text | each marked cell gets `<title>`; the **banner is the authoritative text**, never the overlay alone |
| Decorative icons | `aria-hidden="true"` on the icon when the word beside it already says it |
| Dismiss control | a real `<button>`, ≥ 44 × 44 px, `aria-label="Acknowledge REMOVED at column 3 row 1"` — names the cell, not "dismiss" |
| Focus | `outline: 2px solid var(--signal); outline-offset: 2px` via `:focus-visible`. Never removed |
| Keyboard | the banner's dismiss is in tab order the moment it appears; `Esc` does **not** dismiss a red verdict (D11 — acknowledging a stop must be deliberate) |
| Disabled controls | every one states its reason in text, per DESIGN.md §7 |
| Glare | verdict marks are **fills and 2 px+ strokes**, never 1 px hairlines — DESIGN.md §7's field-conditions rule |
| Touch | on a rig-mounted tablet the dismiss target and the hatch tooltips must work on tap, not hover |

### 6.8 Sound and haptics

DESIGN.md §6.9 already asks for this and calls it *"a real usability feature,
not decoration"* — the operator is looking at the **rig**, not the screen, which
is the entire premise of supervision.

- amber verdict → one short mid tone; red verdict → two low tones.
- `navigator.vibrate` on mobile: `[80]` for amber, `[80,60,80]` for red.
- `VERIFIED` is **silent**. See §6.2.
- Mutable, and the choice is remembered.

### 6.9 Copy — write the sentence, not the enum

The banner shows one line, and it must survive being read by an examiner over
someone's shoulder.

| Verdict | Bad | Good |
| --- | --- | --- |
| `REMOVED` | `REMOVED` | `REMOVED [3,1] — a block the plan placed is gone. Put it back, or dismiss to continue without it.` |
| `DISPLACED` | `MOVED` / `illegal` | `DISPLACED [2,1] — a block was knocked off its cell and is sitting in a gap, not on a site. Straighten it, or dismiss to continue. The run is paused.` |
| `NOT_DETECTED` | `verification failed` | `NOT DETECTED [2,2] — the block just placed was not seen. The run is paused.` |
| `FOREIGN` | `FOREIGN` | `FOREIGN BLOCK AT [4,2] — something is on a cell the plan did not fill. Clear it, then acknowledge.` |
| `DISAGREES` | `error` | `BOARD DISAGREES — 3 cells differ. Too much changed at once to name a cause. Expected vs observed below.` |
| `NO_MEMORY` | `no data` | `NO MEMORY — the board is only tracked from the first build after a restart.` |
| `NO_VISION` | `no detections` / `empty` | `NO VISION — the detector could not read this frame. The board is not being checked.` (or the stale-frame variant) — never rendered as an empty board |

Rules: **name the cell in the first four words**; say **what the operator should
do**; never say "error" for something the machine may have got right; never
imply a retry the hardware cannot honour (DESIGN.md §8).

### 6.10 What must not be done

Inheriting DESIGN.md §8, plus this feature's own:

- **No toast/floating notifications.** Banners are full-bleed above the camera;
  a floater can cover the video, which is the one thing the operator needs.
- **No red for `MOVED`, `DISPLACED` or `REMOVED`.** They are recoverable. Red is
  "a human is required and the machine has stopped".
- **No colour on `BUSY` / `QUIET` / `NO_MEMORY` / `NO_VISION`** (§6.3).
- **No banner for `VERIFIED`** (§6.2).
- **No looping animation on a verdict** (§6.6).
- **No client-side verdict.** The browser renders the server's opinion and never
  computes one — DESIGN.md §8's "no client-side safety logic" rule, and the
  reason four surfaces cannot disagree.
- **No _automatic_ "re-place it".** Automatic repair is M4 and needs D9's
  guards; a button implying the machine will fix a verdict on its own is a lie
  about what is built. **Superseded for the operator-initiated case:** the
  [CORRECTION action](correction-action.md) adds a confirm-gated, one-shot
  `RETURN BLOCK TO CELL` control for `MOVED` / `DISPLACED`, shown only when the
  server has judged the pick safe. It is a deliberate operator override, not the
  machine acting on a verdict — see D11.
- **No hiding the unjudged cells** to make the board look fully checked (§6.4).

### 6.11 UI acceptance tests

| Test | Asserts |
| --- | --- |
| `GridOverlay.test.tsx` | a verdict cell gets the right class; hatched cells render for `unjudged`; a `<title>` exists on each marked cell |
| `SupervisionBanner.test.tsx` | amber → `role="status"`, red → `role="alert"`; the dismiss button's `aria-label` names the cell; `Esc` dismisses amber and **not** red |
| `RunnerPanel.test.tsx` | `vision_verification` reaches the log row (extend the existing suite) |
| `runner.test.ts` | `board-verdict` pauses on amber, stops on red, never reaches `locked` |
| contrast check | a unit test over the token file asserting every state colour used as text clears 7:1 on `--surface`, so a future palette edit cannot silently break it |
| `prefers-reduced-motion` | verdict marks still render with animations disabled |

---

## 7. Milestones

### M1 — the memory *(no vision, testable alone)* — **BUILT**

`placement_ledger.py` + the one `BuildController` hook + the append-only log.

```
append(mode, col, row, level, result, t)
has_memory(mode=None, board_epoch=<current>) -> bool   # audit item 8
board_epoch                              -> int   # current physical-board epoch
new_board_epoch()                       -> int   # reboot / reconnect / swap
expected_occupancy(mode, board_epoch=<current>)  -> set[(col, row)]
expected_top_level(mode, board_epoch=<current>)  -> dict[(col,row), int]
is_top_of_column(mode, col, row, level, board_epoch=<current>) -> bool  # D5
has_taller_neighbour(mode, col, row, board_epoch=<current>)    -> bool  # D6
```

`is_top_of_column` / `has_taller_neighbour` are Stage 15's safety predicates,
built here so that feature inherits them rather than writing a second occupancy
model. Every reader takes an optional `board_epoch` — the sentinel default is
the live epoch, `None` is the every-epoch history view.

**Gate:** a sequence of builds produces the right occupancy set, keeps the two
modes' lattices separate, collapses levels to a column correctly, admits only
`PLACED`, reports `NO MEMORY` after a restart, and — audit item 8 — reports
`NO MEMORY` for a mode or board epoch nothing has been placed in while keeping
the superseded epoch's rows for the record.

### M2 — the observer *(report only, no verdicts)* — **BUILT AND WIRED**

`supervisor.py`: the D5 interlocks, the **pixel → cell step via
`WorkspaceMap.cell_at`** (§2a.1 — this is real work, not an inherited input),
the D7 hysteresis, and the D6 ceiling. Publishes `state` and `observed` only.

**Gate: PASSED, on the rig, 2026-09-07.** The quiet window opens in **42-47% of
frames during a running program**, with ~9 runs of ≥5 consecutive quiet frames a
minute — so `SETTLE_N = 3` is comfortably achievable mid-program, not only
between jobs. A hand over the board reads **105× the parked median**, so the
threshold sits in a wide empty band rather than on a judgement call. Full
numbers in the record's §1.

**Two corrections to this milestone, both from the code rather than the rig:**

- D5's parked interlock is `PARKED_CELL_PHASES = ("idle", "complete")`, **not**
  `cell_phase == "idle"`. `CellOrchestrator._phase("complete")` is terminal and
  sticky, so `"idle"` would have wedged supervision at `BUSY` for every session
  after the first placed block — silently (F14).
- `_supervise` runs **last** in the driver loop turn, after the build result is
  published. Any `await` between `job.poll()` and `_publish_build_result` lets a
  state snapshot claim `last_result=placed` before the terminal event (F15).

**Still open:** a bench session. Nothing here has seen a real frame.

### M3a — the per-build verdict *(the cheap, high-value one — do it first)* — **BUILT**

The classifier at one trigger: `_publish_build_result`. Frame-difference against
the pre-build frame, narrow question, `vision_verification` published.

**Free downstream — half of it (F18).** The run-report Markdown column *is*
free: `run-report.ts` already emits `RunLogEntry.verification`. The runner log
row was not, and the reason is timing rather than missing wiring —
`RunnerPanel` reads the field at the `build_result` event, and the verdict
cannot exist then. It needed one `build-verified` RunEvent that patches the row
in place. The browser still derives nothing; it renders the server's sentence.

**And the check is narrower than D8a hoped (F17).** A frame difference against
the pre-build frame needs a per-cell change threshold that has never been
measured, so it was not built. What ships: decisive at level 0, decisive at any
judged level when the cell reads **empty**, `unconfirmed` at levels 1-2 with the
cell occupied — an overhead camera cannot tell a stack that grew from one that
did not — and `unchecked` at the D6 ceiling. **Gate 0b** is the measurement that
would lift the `unconfirmed` row.

### M3b — the continuous verdict *(the demonstrable milestone)* — **BUILT**

Whole-board occupancy in every quiet window while parked. D9 verdicts, D11
pause/stop, D12 dismissal, **all four surfaces per §6** — and build the **camera
overlay first**, because it is the cheapest and the one the operator is
actually looking at.

**This is the one to demo:** lift a block off the board and the cell lights up
on the live video while the console names it.

Built as specified, with `--danger-text: #FF8A8A` added per §6.5 and
`tokens.test.ts` reading the real stylesheet so a future palette edit cannot
break the 7:1 bar in silence.

### M4 — future: bounded automatic repair

`REMOVED` → re-issue `B a b <level>`. Off by default behind a
**SUPERVISE: REPAIR** toggle; at most one per cell per run, then that cell
latches to "stop and ask"; never during a running build. Needs a way for the
operator to say "that was deliberate" first (D12's future note).

### M5 — future: lift the level ceiling

Two independent threads, both documented:
[parallax](camera-parallax-and-levels.md) (arithmetic over measured constants —
do this one first) and side-sliver height inference (an unvalidated detector
claim). Parallax raises the ceiling; height inference is the only thing that
could catch a block stolen off the top of a stack.

---

## 8. Tests

The repo's rule holds: **Python is right, TypeScript is held to it by dumped
fixtures.** Match the neighbouring style — `test_build_controller.py` and
`test_grid.py` are hand-rolled with a `check(name, condition, detail)` helper
and `PASSED`/`FAILED` lists, and `FakeRig` is the pattern (fakes over mocks).

| Suite | Checks |
| --- | --- |
| `tests/test_placement_ledger.py` | append/reload, per-mode separation, level collapse to a column, `PLACED`-only admission, `NO MEMORY` after restart, the two Stage 15 predicates |
| `tests/test_supervisor.py` | every D9 row from synthetic cell sets, incl. `MOVED` vs `DISPLACED` by landing and the ambiguous gap counts that fall through to `DISAGREES`; hysteresis needs `N of M`; each D5 interlock independently suppresses a verdict; counters **reset rather than decay** on a tripped interlock; D6 refuses level ≥ 3; `in_gap` gets `N of M` too (D10 removed); D13 resets on a mode change |
| `tests/test_supervisor_frames.py` | **built differently, and stronger.** Not the reference stills — the **four Gate 0 rig traces** in `docs/measurements/`, 1398 frames the rig actually produced, replayed through the shipped `Supervisor`. Reproduces the measured distribution to within a tenth of a percent, names the exact residual cell `(2,0)`, and replays the pre-fix merged reading to measure it emitting `FOREIGN` in 99.4% of windows on a correct board |
| `tests/web_supervision_test.py` | **new.** The seam: what `web/app.py` hands the supervisor, the mode-latch suspension, the repeated-sequence guard, D5's parked gate including the `complete` trap, and the per-build check's four outcomes |
| `web/src/tokens.test.ts` | **new.** Reads the real stylesheet and asserts every colour that carries a state WORD clears 7:1, and pins the fact that `--danger` itself does not |
| `web/src/components/SupervisionBanner.test.tsx` | **new.** No banner for `VERIFIED`; no state colour for BUSY/QUIET/NO_MEMORY; `role` by severity; the cell named in the dismiss label; the hatch is not a colour; `DISPLACED` is amber, names its cell, and says "straighten it" |
| `tests/web_state_test.py` | `vision_verification` and the supervision block appear in the snapshot and survive a mode latch |
| `web/src/studio/runner.test.ts` | a `board-verdict` event pauses on `REMOVED`, stops on `DISAGREES`, and never reaches `locked` |
| existing | `test_block_outline.py`'s timing guard must still pass — supervision adds no detector work |

**Assert exact cell sets, never counts.** BLOCK-VISION §0 explains why: a
count-only assertion passes on a board renumbered by one cell, which is the
failure that matters.

**Every one of these passes.** Standard gate afterwards:

```bash
python3 python/tests/test_grid.py     # firmware <-> config pairing
cd web && npx vitest run              # Studio / coords / Twin
cd python && python3 -m pytest tests/ # the rest
```

`python/tests/` is **fully green — 94 passed, 0 failed.** The three failures
that used to be waved through as pre-existing were defects in the tests
themselves and were fixed alongside this work (record F20). The one remaining
red is `test_grid.py`'s `zGoPickup()` check — a firmware/AGENTS.md paired value
and not this feature's (F10 / P5).

Still expected to fail on a clean checkout, for missing fixtures:
`test_combined_grid`, `test_color_tuning`, `test_camera_performance`,
`test_block_outline`.

---

## 9. Known limits — put these on screen, do not bury them

1. **Level-blind for the idle sweep** (D4). A block taken off the top of a stack
   leaves the cell occupied and is not seen. Say it in the UI: *"Supervision
   checks which cells are occupied, not how tall each stack is."*
2. **A hard ceiling at level 3** (D6). Cells above it are listed as `unjudged`,
   never as verified and never as missing.
3. **Sub-cell nudges are invisible.** `LATTICE_SNAP` is 0.34 cells and the
   four-corner map carries 0.27 cm of flattening error mid-grid. A block pushed
   a few millimetres still reads as the same cell. That is Stage 15's job, and
   it must never trigger a supervision verdict at this error budget.
3a. **`MOVED` / `DISPLACED` do not prove it is the same block.** The pairing —
   one cell emptied, one thing arrived — is a heuristic that holds because the
   window has no occlusion (D5), not because identity was established. See
   [block-identity.md](block-identity.md). `REMOVED` for a cell that emptied
   with nothing arriving in the build area is an inference too: the block *may*
   have been taken off a stack (limit 1), so the copy says "not seen on the
   build grid", never "outside the build area".
4. **Occlusion is not emptiness.** A cell under the gantry, a cable or a hand is
   *unobservable*, not empty. D5 refuses to judge at all in the common case; a
   cell under a **static** occluder will read as `REMOVED` forever, which is
   exactly why the verdict stops the machine rather than driving it.
5. **`FOREIGN` / `DISAGREES` are live from block one** (D10 removed). Including
   after a restart with blocks still on the board: an empty ledger against a
   non-empty board reads those blocks as unaccounted for, and that is a correct
   red verdict, not a bug. Dismiss per D12. Single-frame gap jitter is filtered
   by `in_gap`'s own `N of M` hysteresis.
6. **No memory after a restart** (D3). Honest and deliberate.
6a. **No verdicts without a saved workspace map** (D5). Uncalibrated, the
   pipeline falls back to `approximate_workspace` and `cell_at` would be
   confidently wrong — so supervision reports `NO MAP` and judges nothing. The
   camera overlay already has the right instinct here: it styles an
   uncalibrated grid as `approximate` so it never looks authoritative.
7. **The mixed-level filter subtlety** — `_lattice_filter` measures indices
   relative to whichever block sorts first, so the ceiling in D6 is *typical*,
   not guaranteed. Reasoned from the code, **not measured**. See
   [parallax §4a](camera-parallax-and-levels.md#4a-a-subtlety-that-makes-the-ceiling-approximate-not-exact).
7b. **A placement at level 1 or 2 can be reported as `unconfirmed`, not
   verified** (F17). The per-build check is decisive at level 0, and decisive at
   any judged level when the cell reads *empty* — that is a tower that fell. But
   a cell that was already occupied stays occupied whether the new block landed
   or not, and an overhead camera cannot tell the two apart. D8a wanted a frame
   difference against the pre-build frame to close this; that needs a per-cell
   change threshold nobody has measured, and a guessed threshold must never
   reach a rig. **Gate 0b** is the measurement that would lift it.
8. **The lattice filter's 30 % self-disable is weakest exactly when the board is
   most wrong** (F7 / P4). `block_outline` keeps every detection when a
   recovered lattice would reject more than 30 % of what it saw
   (`if len(kept) < 0.7 * len(detections): return list(detections), [], None`).
   That is right for a drawing layer, which must never hide a block on thin
   evidence. But it means junk rejection degrades at the moment a clean observed
   set matters most: the `DISAGREES` case, where several blocks genuinely moved.
   Supervision does not *depend* on that filter — F3, `locate()` is its defence
   and works at any detection count — so this costs the input's tidiness, not
   the classifier's correctness. Recorded because nothing else here covered it.

---

## 10. Not doing

- **Tracking blocks between frames** (D1). Revisit only if a measured failure
  demands it, and bring the measurement.
- **Re-planning around interference.** The machine pauses, stops, or (later)
  repairs. It never decides to build something else.
- **Verifying inside a `B`.** The firmware is deaf mid-command and the arm is in
  the frame. Supervision is a between-ops activity — which is enough, because
  the runner already stops after every single block.
- **Storing frames.** Time-lapse ([feature-ideas.md §2.2](../feature-ideas.md))
  is a separate feature with a separate budget. Supervision keeps cells and
  counters.
- **A sixth `TwinAppearance`** (§5). Supervision overlays the twin; it does not
  become part of the twin's own claim.
- **Reloading the ledger as authority** (D3).
- **Letting a verdict `LOCK` the session** (D11).

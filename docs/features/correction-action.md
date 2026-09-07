# The CORRECTION action — an operator button that returns a moved block to its cell

**Status: BUILT on the Pi and in the UI; the firmware `P` verb is written and
stub-syntax-checked but UNFLASHED / UNVERIFIED ON HARDWARE.** Phases 1–3 below
are complete and gated. The two Stage-15 bench measurements (jaw capture
tolerance, placement repeatability) are still not done, so the correction band
bounds are provisional constants and the whole path is conservative and
operator-initiated. `DESIGN.md §8` and `placement-supervision.md §6.10 / D11`
have been amended with the operator-initiated carve-out.

> **Feasibility as built: the button drives a real closed loop — supervision
> verdict → server re-checks safety → firmware `P` verb → re-verify.** It is
> scoped to **vertical mode, level 0, axis-aligned blocks, no taller neighbour,
> destination clear**. `MOVED` (block squarely on the wrong cell) is the clean
> case — the grip happens on a real cell. `DISPLACED` (block in a gap) is
> gated further to a **0.5–1.2 cm displacement band**, which is geometrically
> narrow: a `DISPLACED` centroid is already ≥ half a block off its cell (that is
> what put it in the gap), so in vertical X the correctable window is roughly
> `[1.1, 1.2]` cm and in Y it is empty. Widening it is a bench-measurement call.
> Everything shares [Stage 15](stage-15-placement-correction.md)'s `P` verb,
> `link.replace_block()`, and `PlacementLedger` safety predicates.

> **Before trusting it on hardware:** flash the `P` verb and watch it on the
> rig; do [Stage 15 Stage B](stage-15-placement-correction.md#stage-b--two-bench-measurements-gates-stage-c)'s
> two measurements; then revisit `CORRECT_BAND_MIN_CM` / `CORRECT_BAND_MAX_CM`
> in `python/rig/placement_check.py`.

**Difficulty: 4 / 5**, unevenly distributed — most of the code is easy, nearly
all of the risk sits in two rows.

| Piece | Difficulty | Note |
| --- | --- | --- |
| Retain the pick centroid + target-cell centre through `Observation` → `Verdict` → `SupervisionModel` → `types.ts` → route | **2 / 5** | mechanical plumbing across ~5 layers |
| The map-frame differential + `correctable` gate (level 0, band, angle, neighbours, destination) as a pure function over ledger + observation | **2 / 5** | pure, testable with no camera; the one trap is §B.3's knob double-count |
| The button, confirm dialog, route, one-shot latch, D12 re-verify hook | **3 / 5** | new route + runner-state coupling; mirrors `/api/supervision/ack` |
| The `P` verb in every flashed sketch | **4 / 5** | **no local Arduino toolchain — stub-`g++` only, flashed and watched on the rig is the only real check** |
| Proving the band is not empty (jaw capture tolerance, placement repeatability) | **bench work, unavoidable** | two numbers nobody has measured — Stage 15 §7 |
| Superseding DESIGN.md §8 / placement-supervision.md §6.10 / D11 | **not a code difficulty** — a decision only the user can make |

Shared with [Stage 15 Stage C](stage-15-placement-correction.md#8-the-implementation-plan):
the `P` verb, `link.replace_block()`, `mock_board` `P`, and both bench
measurements. Build Stage 15 first and this is a thin manual entry point onto
it; build it standalone and you are paying Stage 15's hardest rows twice.

**Read first:** [AGENTS.md](../../AGENTS.md) — the calibration knobs and Rule 0 /
0a (every calibration number is a magnitude from a home switch, `+` = away from
home; X's `axisPos[]` runs the opposite way; cross the two spaces only via
`axisPosFromHomeSteps()` / `axisStepsFromHome()`). Then
[stage-15-placement-correction.md](stage-15-placement-correction.md) in full —
this feature is 80 % that document — and
[placement-supervision.md](placement-supervision.md) D9/D11/D12 and its
[build record](placement-supervision-progress.md) F10/F17/F18.

---

## What was built (and two things the earlier audit got wrong)

| Layer | File | What |
| --- | --- | --- |
| pure geometry + policy | `python/rig/placement_check.py` | `assess()`, `judge_band()`, `correction_offset()`, `axis_deviation_deg()`, the `Correction` dataclass. No camera, no rig. `CORRECT_BAND_{MIN,MAX}_CM` are **provisional** — Stage 15 Stage B. |
| supervisor plumbing | `python/rig/supervisor.py` | `Observation` keeps `gap_points_cm` / `cell_points_cm` and their angles for the one moved detection; `point_cm()` exposed. The classifier never looks at them. |
| server assembly | `python/web/state.py` `assess_frame_correction()` | the single source of truth: `web/app.py` calls it per quiet frame to publish `correctable`; the route calls it **again** on the live frame before it moves anything. |
| published state | `SupervisionModel` + `types.ts` | `correctable`, `correction_reason`, `correction_cell`, `correction_level`, `pick_offset_cm` (telemetry only), plus `StateModel.last_correction`. |
| the route | `POST /api/supervision/correct` | confirm-gated, one attempt per verdict event, re-derives safety server-side, drives `rig.replace_block()`, locks on `HELD`, resets hysteresis on success (D12). Sync on a worker thread, like `/mode`. |
| firmware | `arduino/build_test_v1/build_test_v1.ino` | the `P` verb + `gotoBuildTargetOffset()` + an 8-field parser. **Unflashed / unverified.** `arduino/tools/pcheck/check.sh` is the stub-Arduino syntax check. |
| link + mock | `rig/link.py` `replace_block()`, `rig/mock_board.py` `_handle_replace()` | same three-word contract and abort discipline as `build()`. |
| UI | `web/src/components/SupervisionBanner.tsx` | `RETURN BLOCK TO CELL` → a two-step confirm → `POST`. Shown only on `correctable`; otherwise the reason is shown. No state colour — it is an operator action, not a machine state. |

**Correction 1 — `MOVED` is the *safer* case, not the worse one.** The audit
first dismissed `MOVED` as "a full pitch away". That is the *travel* distance;
the *grip* happens where the block sits, which for `MOVED` is squarely on a real
cell (`[c,d]`) — the jaws pit into that cell's own gaps, a clean capture. For
`DISPLACED` the grip is in a 1.6 cm gap, against a neighbour. So the `P` verb
takes **separate pick and place cells**, and `MOVED` is gated only by the safety
predicates (not the band).

**Correction 2 — the `DISPLACED` band is geometrically narrow.** A block only
reads `DISPLACED` when its centroid leaves its cell footprint, i.e. ≥
`block/2` = 1.1 cm off centre in vertical X (≥ 3.0 cm in Y). Stage 15's band
refuses > 1.2 cm. So the vertical-X correctable window is ≈ `[1.1, 1.2]` cm and
the Y window is empty. The feature still ships the `DISPLACED` path — it is
correct, and a bench measurement could widen `CORRECT_BAND_MAX_CM` — but expect
the button to be a "here's why not" reason line far more often than a live
control for `DISPLACED`. `MOVED` is where it earns its place.

---

## 0. What was asked, and what the code actually supports

The request: a `CORRECTION` button on the supervision banner, shown only for
`MOVED` and `DISPLACED`, that drives the claw to pick the errant block up and
re-place it on the cell the ledger says it belongs on.

- **`MOVED [a,b] → [c,d]`** — descend on `[c,d]`, grip, lift, re-place at `[a,b]`.
- **`DISPLACED [a,b]`** — reconstruct the block's true centre from the fractional
  cell/gap coverage the camera sees plus the block/gap dimensions in
  `config/rig.json`; go there, grip, lift, re-place at `[a,b]`.

Every technical claim below was checked against the repo. Where the request and
the code disagree, the code wins and it is called out.

**The single biggest correction to the request: the fractional-coverage
reconstruction is neither necessary nor available.** `BlockDetection` already
carries `.center` — the block's measured pixel centroid — and `.angle`, its
measured orientation ([block-identity.md](block-identity.md) line 72 lists the
full field set: `box, center, width, height, angle, area, rectangularity,
solidity, confidence, hue`). The detector's centroid *is* the block's true
centre in the image, whether the block sits on a site or half in a gap. Nothing
in the pipeline computes a per-cell coverage fraction, and there is no need to:
`detection.center` → workspace cm is one projection call. The user's
reconstruction re-derives, from weaker inputs, a number the detector already
measured directly.

---

## A. Does the input data exist?

### A.1 The detector has it; the supervisor throws it away

| Question | Answer, from the code |
| --- | --- |
| Does `BlockDetection` carry `.center` / `.box` / `.angle`? | **Yes.** All measured, on every detection. `block_outline._rectify` shares size and bearing across the population but **never touches the centre** ([BLOCK-VISION §2](../BLOCK-VISION.md), "The centre is never snapped"). |
| Is the fractional-coverage reconstruction necessary? | **No.** `detection.center` is the true centroid. Coverage fractions are not produced anywhere in `vision/` or `rig/`. |
| Does `rig/supervisor.py` keep any pixel-space or residual data? | **No.** `observe()` calls `locate()` per detection, keeps the resulting `(col,row)` if there is one, and returns `Observation(cells, in_gap, off_board, detections)` — **four fields, all integer counts or cell tuples**. `detection.center` is consumed and discarded. |
| Were the design's `residual_cm` / `observed_centre_px` columns built? | **No.** [placement-supervision.md §1](placement-supervision.md#1-the-shape-of-the-thing)'s substrate table promises `observed_centre_px` / `_cm` and `residual_cm` "consumed by Stage 15, calib". `Observation` has none of them, `Verdict` has none of them (`verdict, cells, mode, expected, observed, unjudged`), and `web/state.py`'s `SupervisionModel` has none of them (cell-tuple lists only). The columns are **design intent that M2 did not build** — M2 built occupancy only, exactly as [D8b](placement-supervision.md#d8--two-triggers-one-classifier) requires and no more. |

### A.2 The plumbing that does not exist

A pick coordinate has to travel: **detector centroid → supervisor → `Verdict`
→ `SupervisionState` → `SupervisionModel` → `types.ts` → a route → `link.py` →
the Mega.** Today it stops at the supervisor. New plumbing:

1. `rig/supervisor.py` — `observe()` must retain the centroid of the detection
   that is `in_gap` (for `DISPLACED`) or on the unexpected cell (for `MOVED`),
   in **workspace cm**, on `Observation`. Then `classify()` / `step()` must
   thread it onto `Verdict` as `pick_cm: tuple[float,float] | None` and a
   `correctable: bool` with a `reason`.
2. `web/state.py` — `SupervisionModel` gains `pick_cm`, `correctable`,
   `correction_reason`. `supervision_model()` folds them in.
3. `web/src/types.ts` — the three new fields on `Supervision`.
4. `web/src/components/SupervisionBanner.tsx` — the button (§F).
5. `python/web/routes_command.py` — `POST /api/supervision/correct`.
6. `python/rig/link.py` — `replace_block(col,row,level,dx_cm,dy_cm)`, beside
   `build()`, same abort discipline (Stage 15 §8 Stage C).
7. `python/rig/mock_board.py` — mock `P` so the path is testable off-rig.
8. Firmware — the `P` verb (§C).

This is the same edit list as [Stage 15 Stage C](stage-15-placement-correction.md#stage-c--the-correction-only-if-a-and-b-come-back-favourable),
plus the supervisor→state pixel-plumbing that Stage 15 avoids by running its own
detection pass with its own matching.

---

## B. Coordinate transforms

### B.1 Pixel → cm for a free point — exists

`WorkspaceMap` has the whole chain for an arbitrary point, not just a cell index:

```
pixel (px,py)
  → normalized_at((px,py), image_size)              # _project(self._to_machine, (px/w, py/h))  → (u,v)
  → x_cm = u * mapped_grid.workspace_width_cm        # free point, not cell-indexed
    y_cm = v * mapped_grid.workspace_height_cm
```

`rig.supervisor.locate()` already runs exactly this for its margin test
([supervisor.py:208–227](../../python/rig/supervisor.py#L208)). So the observed
centre in workspace cm is available with no new geometry — it is one call the
supervisor already makes and then does not keep.

### B.2 cm → machine steps — does NOT exist in Python, by design

`python/rig/grid.py` has **no step counts at all** (`grep steps` in it returns
nothing). `MachineGrid` is centimetre-only and **cell-indexed**:
`cell_center_x_cm(col)`, `cell_center_y_cm(row)`. There is no
`MachineGrid.point_to_steps` and there is no free-point machine-coordinate path
anywhere on the Pi. [AGENTS.md §3a](../../AGENTS.md#3a-xy-physical-grid-geometry--fixed-pitch-block-cells)
states the rule: *"The Pi does not need motor steps to draw or select a cell …
the Arduino alone maps that cell to safe step targets."*

**Consequence:** the correction offset must be sent as **cm magnitudes** and
converted inside the firmware, which is exactly the shape Stage 15 §4 chose for
the `P` verb: `P <col> <row> <level> <dx_cm> <dy_cm>`.

### B.3 The offset is a map-frame differential — and why the first cut is vertical only

**This is the part that goes wrong if you are not careful, and it is exactly the
calibration knobs.** A `DISPLACED` block whose planned cell is `[a,b]`, level 0.

The offset sent to firmware:

```
dx = x_obs − x_map_cell        where
  x_obs      = workspace.normalized_at(centroid, image_size).u  * mapped_grid.workspace_width_cm
  x_map_cell = mapped_grid.cell_center_x_cm(a)      # the map's own lattice — see below
```

both in the map's `(u,v)·workspace_cm` frame, differenced in **magnitude space**
(Rule 0a rule 1). Worked example: the block sits **0.4 cm further from the X home
switch than the map puts its cell** → `x_obs > x_map_cell` → `dx = +0.4` ("away
from home", Rule 0) → on the wire `P a b 0 +0.4 <dy>`.

The `P` verb reuses `gotoBuildTarget()`, so **both** legs already carry the full
calibration chain — `cellTargetPosition()` (`GRID_TRIM_*` + `GRID_ERROR_OFFSET_*`
+ `GRID_SHIFT_*` − `toolOffsetCmOf()`) **plus** `buildPlacementOffsetSteps()`
(`BUILD_PLACEMENT_OFFSET_*`) **plus** `buildSkewSteps()` (`SKEW_*`). `dx` is a
**third term in the same slot** as `buildSkewSteps()`, on the **pick** leg only;
the place leg sends `0`.

**Whether the knobs double-count depends on how the map was calibrated, and this
is the crux:**

- `mapped_grid.cell_center_x_cm(a)` **is** the map's lattice —
  `trim + error_offset + shift + a·pitch`. The saved `workspace_map.json` carries
  **four corners + this formula, no per-cell table** ([BLOCK-VISION §4](../BLOCK-VISION.md)),
  so "the map's cell centre" and "`MachineGrid`'s bare lattice" are the **same
  number**. There is no third frame to reach for.
- **Block-calibrated map** (`block_grid_calibrate.py` / BLOCK CALIBRATION — the
  [primary route](../../AGENTS.md#3d-bis-placed-block-calibration--the-primary-route)):
  the corners are fitted so that *observed placed blocks line up with the
  lattice*. So a **correctly** placed block has `x_obs ≈ x_map_cell` →
  **`dx ≈ 0`** → `P` with `dx ≈ 0` is just a normal placement → **no
  double-count**. A *displaced* block's `dx` is its true displacement from where
  a correct block would sit. This is the case the feature is designed for.
- **Paper-calibrated map** (`color_grid` / printed sheet): the corners are fitted
  to the *sheet*, which is assumed to sit on the lattice. A correctly placed
  block lands offset from the sheet cell by `toolOffset + BUILD_PLACEMENT_OFFSET
  + SKEW`, so `x_obs(correct) ≈ x_map_cell + those` → **`dx` carries that bias**
  and the firmware adds it a second time.
- The two routes **write a byte-identical file** (`test_calibration_parity.py`),
  so the loaded map **cannot say which it was**.

> **DECISION — the first cut is `mode == "vertical"` only, and `correctable` is
> `False` in horizontal.** In vertical: `tool_offsets.neutral = (0, 0)`,
> `BUILD_PLACEMENT_OFFSET_* = 0`, `SKEW_X_* = 0`, and `SKEW_Y_PER_COL_CM =
> 0.115` cm/column is the *only* motion knob. So even on a paper-calibrated map
> the `dx` bias is at most `0.115·col` cm on Y and `≈ 0` on X — within or beside
> the map's own `0.27 cm` flattening error, and `judge_band` (§E.3) refuses
> anything that lands outside `[0.5, 1.2]` cm anyway. **Horizontal carries the
> `cw` tool offset `(+0.9, −0.3)`, `BUILD_PLACEMENT_OFFSET_X = −0.4`, the
> pickup-rotate grip geometry, the paper-map ambiguity above, and an unmeasured
> `blocked_cells` list — every one a reason it is a separate, later piece of
> work.** The server sets `correctable = False, reason = "horizontal correction
> is not supported"` for it.

**`GRID_SHIFT_*` (`shiftX` / `shiftY`):** if a live shift is active, the firmware
applies it in `cellTargetPosition()` on **both** legs; the map (calibrated at a
fixed shift, normally `0`) does not know about it. Keep every Pi-side quantity in
the **map frame**, let the firmware own the shift, and it cancels on the pick leg
exactly as the trim does. Never fold the shift into `dx` on the Pi. If the map's
embedded `shift_*_cm` disagrees with the live grid's, `frame.calibrated` is
already `False` (the `/shift` route re-validates the map) and supervision is
`NO_MAP` — so a shifted-but-uncalibrated state cannot reach a correction.

---

## C. The firmware verb problem — the primary blocker

### C.1 The motion verbs the sketch actually accepts

`arduino/build_test_v1/build_test_v1.ino` (the sketch `config/rig.json → board.sketch`
names), `handleLine()` / `handleSingleChar()`:

| Verb | What it does | Picks a block off the board? | Places the claw's contents at a cell? |
| --- | --- | --- | --- |
| digit `1`–`9` (jog table), `U` / `D` | raw single-axis jogs | no | no |
| `G <col> <row>` → `gotoCell()` | **move the gantry to a cell centre. No grip, no descent-to-grip, no place.** | no | no |
| `B <col> <row> <level>` | 14-phase **feeder** pick → place → park | **no — picks from the feeder** | no (it placed the feeder block) |
| `M <col> <row> <level>` | manual build: same approach, lowers the **open** claw, waits for `C` | no — feeder | no |
| `V <angle>` / `O` / `C` | servo angle / open / close — position-independent | no | no |
| `A <degrees>` | signed **relative** aux-stepper jog, `−360..360` | no | no |
| `S`, `R`, `RR`, `9`, `5`, `Z`, `0`, `0+`, `sh…` | config / report / home / mode latch | no | no |

**[feature-ideas.md D8](../feature-ideas.md#d8--repair-is-bounded-by-what-the-machine-can-do)'s
claim — "the firmware has no verb that picks a block up off the board" — is
CONFIRMED.** `B` and `M` pick from the feeder; `G` moves without gripping; there
is no verb that places whatever the claw is holding.

### C.2 `zGoPickup()` is disabled — CONFIRMED (F10 / P5)

`build_test_v1.ino:4356–4368`: *"DISABLED — build phase 5 now goes back to a
GROUND seek (`zGoGround()`). … nothing calls `zGoPickup()` any more."* The
function body is commented out. `python/tests/test_grid.py` fails on exactly
this drift — `FAIL  rig sketch phase 5 uses zGoPickup(), not zGoGround()` — and
it is the one known-failing check in the gate (234 passed, 1 failed).
[AGENTS.md is stale in two places](placement-supervision-progress.md#f10--test_gridpy-is-failing-on-an-unrelated-firmware-change)
because of it (the `Z_PICKUP_DROP_FROM_TOP_CM` "one documented exception" and
§3b-bis's `blocked_cells`). **Do not try to fix it here — P5, the user owns it.**

**What Z-descent-to-grip exists today:** `zGoLevel(level)` — level 0 is a ground
seek (`zGoGround()`, into the pin-28 switch), every other level is an exact step
count above ground. `buildBlock()` phase 5 (pickup) and the placement phases
both call it. So a grip-height routine exists and is reusable; the missing piece
is the *sequencing verb* around it.

> **DECISION — reuse `zGoLevel(level)`, add no new paired Z constant.** The
> displaced block is at a known level (from the ledger), so descend to that
> level's Z exactly as placement does. This keeps `P` out of the
> `Z_PICKUP_DROP_FROM_TOP_CM` mess and adds nothing to `test_grid.py`'s
> paired-value list beyond the verb's own argument shape.

### C.3 The verb, and its cost

`P <col> <row> <level> <dx_cm> <dy_cm>` — Stage 15 §4's design, unchanged:

1. rotate claw to the mode's rotation (`ROT_NONE` vertical / `ROT_CW` horizontal)
2. open jaws, high
3. move to `(col,row)` **+ (dx,dy)** — where the block actually is
4. `zGoLevel(level)` — descend to the block
5. `C` — close (grip)
6. lift to carry height
7. move to `(col,row)` with **no** offset — where it belongs
8. `zGoLevel(level)`, open, lift, park

- `parseSignedCm` exists (`handleShiftCommand`, `:3300`); a **five-argument
  parser (3 unsigned + 2 signed cm) does not** and must be written.
- **No local Arduino toolchain.** Syntax-check with the stub-`g++` harness only;
  the result is **unflashed and unverified on hardware**, and anything touching
  motion/limits/Z has to be flashed and watched (AGENTS.md).
- **Paired sketches — unresolved discrepancy.** `config/rig.json` names
  `arduino/build_test_v1`. Stage 15 §4 and §8 instead pair
  `build_vertical_grid.ino` + `build_horizontal_grid.ino`. This audit cannot
  tell which is canonical for deployment; `test_grid.py` parses whichever
  `rig.json` names. **Whoever builds this resolves it first** and pairs every
  sketch that is actually flashed, in one commit, with `test_grid.py` extended
  to cover the `P` verb's shape.
- Gripper: `openServo()` / `closeServo()` / `setServoAngle()` (`SERVO_CLOSE_ANGLE`,
  recently tuned) are position-independent — the claw closes wherever it is — so
  they compose at a free XY. But invoking them from the Pi over raw serial
  bypasses `BuildController`'s operation lock, the camera/selection guards and
  the failure lockout, which [AGENTS.md §2a](../../AGENTS.md#2a-uno-feeder-link--independent-port-strict-handoff)
  forbids ("manual feed must never become an unguarded direct-Mega call"). The
  sequence must be **one firmware verb with an `@` ack**, driven by one
  `link.py` method with `build()`'s abort discipline.

---

## D. Physical feasibility — the error budget

### D.1 Position error at the computed pick point (per axis, vertical grid)

| Source | Contribution | Cited from |
| --- | --- | --- |
| Four-corner map flattening, mid-grid | **0.27 cm** mean (2.07 px max) | [BLOCK-VISION §4](../BLOCK-VISION.md#4-saving-and-what-a-saved-map-can-carry); AGENTS.md §3d-ter |
| Detector centroid jitter, rig feed | **≈ 0.15 cm** (ref-board mean residual 0.85 px ≈ 0.05 cm; inflated for the rig's soft, magenta-cast, 8.6 Hz, JPEG feed; `N`-of-`M` settle averages some out) | Gate 0 §1.5–1.6 — `(2,0)` recall 97.3 %, others 99.8 % |
| `normalized_at` projection / clamp rounding | **≈ 0.05 cm** | reasoned, not measured |
| **Sub-total, level 0** | **≈ 0.47 cm linear / 0.31 cm RSS** | |
| Parallax, **uncorrected**, if the block is at level 1 | **+0.32 cm X, +0.90 cm Y** at the grid edge / row 0 | [parallax §3](camera-parallax-and-levels.md); Stage 15 D4 |
| Parallax, uncorrected, at level 2 | **+0.65 cm X, +1.86 cm Y** | same |

`LATTICE_SNAP = 0.34` cells is **not** an error term — centres are never snapped
([BLOCK-VISION §2](../BLOCK-VISION.md)). It is a *detectability bound*: a
`DISPLACED` block only produces a detection at all if its centroid is within
0.34 cells (≈ 1.29 cm X, 2.58 cm Y, vertical) of some integer site, because
`ConsolePipeline` runs the detector **with a grid** and `_lattice_filter` drops
anything further. So the magnitude a `DISPLACED` verdict can even *see* is
already capped near the neighbour-contact limit.

**Supervision applies no parallax correction** (`supervisor.py` has no such
term; it is M5 future work), and it refuses to judge level ≥ 3 (`LEVEL_CEILING`).
So `MOVED` / `DISPLACED` can fire at levels 1–2 carrying **0.9–1.9 cm of
uncorrected, directional parallax** that the pick point would inherit whole.

### D.2 Against the gripper's capture tolerance

Jaw **clearance** is proper — the jaws straddle the 2.2 cm block and pit into
the 1.6 cm gaps (Stage 15 D8, bench-observed). But **how far off-centre the jaws
can close and still grip rather than shove is UNMEASURED** (Stage 15 §5.2:
*"the cheapest high-value experiment available"*). `SERVO_CLOSE_ANGLE` is
calibrated for a block presented squarely by the feeder. Stage 15 estimates the
usable tolerance at **±0.3–0.5 cm**.

| Regime | Pick-point error | vs ±0.3–0.5 cm tolerance |
| --- | --- | --- |
| `DISPLACED`, level 0, near nadir | ≈ 0.3–0.5 cm | **marginal — unproven, needs Stage B bench measurement** |
| `DISPLACED`, level 1–2 | 0.9–1.9 cm (parallax-dominated) | **misses — the jaws hit the block corner and shove it** |
| `MOVED` (block on a valid adjacent cell) | one pitch, 3.8 / 7.6 cm from `[a,b]` | irrelevant to the pick — the pick is at `[c,d]`, which *is* a site, so pick error is the level-0 0.3–0.5 cm; but the **place** into `[a,b]` carries the machine's full placement error again |

### D.3 Orientation — `detection.angle` is measured; the verb ignores it

The user says "assume grid orientation". `detection.angle` **is** measured, so
the assumption is unnecessary and checkable — but the `P` verb as designed
rotates the claw to the *mode's* rotation, not to the block's angle. A displaced
block rotated 15–20°:

- effective width across a grid-aligned jaw axis ≈ `2.2·cos20° + 6.0·sin20°`
  ≈ 2.07 + 2.05 ≈ **4.1 cm** — far beyond jaw capture. The jaws strike a corner
  and rotate/shove the block.
- correcting it would need the verb to also `A`-rotate the claw to
  `detection.angle` before the grip and back after the place — and there is **no
  calibrated tool offset for an arbitrary angle** (AGENTS.md §3c: non-0/±90° has
  no calibrated `TOOL_OFFSET_*`). Out of scope for this verb.

> **DECISION — refuse any `MOVED` / `DISPLACED` whose `detection.angle` is more
> than a few degrees off the mode axis.** The correctable set is
> axis-aligned blocks only, and the verdict path must publish the angle so the
> server can gate on it.

**Cannot verify without the rig:** whether the inter-cell gaps are physical
grooves or flush. `config/rig.json` / AGENTS.md model them as pure 1.6 cm
spacing. If they are grooves, a half-in block tips and rotates, `detection.angle`
≠ 0, the centroid shifts with the tip, and the whole pick-point estimate is
off — which is another reason the angle gate above is mandatory.

### D.4 Collision — the descent corridor and the destination

The `PlacementLedger` already carries [Stage 15's D5/D6 predicates](placement-supervision.md#m1--the-memory-no-vision-testable-alone):
`is_top_of_column(mode, col, row, level)` and
`has_taller_neighbour(mode, col, row)` (built, 42 tests). The correction path
must call them for:

- **every cell the displaced block touches** — its from-cell `[a,b]` and the
  cells flanking the gap it sits in — `has_taller_neighbour` on any of them
  ⇒ **refuse** (the claw would descend a slot flanked by a taller stack, Stage 15
  D6);
- **the from-cell** — `is_top_of_column` false ⇒ **refuse** (something is on top
  of it; it is buried, Stage 15 D5);
- **the destination cell `[a,b]`** — it is **not** guaranteed clear. The plan
  placed a block there and it moved off, so it is *usually* empty, but a later
  build step or a second displaced block can occupy it. The path must confirm
  `[a,b]` reads **empty in the settled observation** before descending to place.
  Not clear ⇒ **refuse** — placing into an occupied cell is a collision, and
  half-repairing is worse than stopping
  ([feature-ideas.md D8](../feature-ideas.md#d8--repair-is-bounded-by-what-the-machine-can-do):
  *"Do not soften this."*).

---

## E. Policy and safety — reconciling with the written rules

### E.1 Three rules this contradicts head-on

| Rule | Where | This feature |
| --- | --- | --- |
| *"No 're-place it' button. … a control implying the machine will fix it is a lie about what exists — the same rule as the banned Retry."* | [DESIGN.md §8](../DESIGN.md#8-what-must-not-be-done) | **adds exactly that button** |
| *"No 're-place it' button in v1. Automatic repair is M4 … a button implying the machine will fix it is a lie about what is built."* | [placement-supervision.md §6.10](placement-supervision.md#610-what-must-not-be-done) | same |
| *"D11 — Notify, never act. … A supervision verdict never moves the rig."* | [placement-supervision.md D11](placement-supervision.md#d11--notify-never-act-for-now) | the button makes a verdict the *trigger* for motion |

The distinguishing argument — and it is thin — is **operator-initiated, not
automatic**. DESIGN.md §8's rule is aimed at a *passive* control that reads as
"the machine handled this" (the banned Retry). An explicit, opt-in button with a
confirm dialog that says *"the claw will pick the block up and set it down —
watch the rig"* is a different speech act. **But the rules as written are
absolute, and this audit does not have standing to supersede them.**

> **DECISION — RECOMMEND: do not ship the button until the user has (a) signed
> off on an operator-initiated carve-out, edited into DESIGN.md §8 and
> placement-supervision.md §6.10 in the same commit; (b) the `P` verb is flashed
> and bench-verified; (c) [Stage 15 Stage B](stage-15-placement-correction.md#stage-b--two-bench-measurements-gates-stage-c)'s
> two measurements — jaw capture tolerance and placement repeatability — come
> back favourable.** Until all three, the button is the lie the rule forbids.

### E.2 The guards (the D11 override spec)

If the user does supersede D11, this action is a *deliberate operator override*
and needs, all of them:

1. **Not during a running build or program.** Refused unless `job` is idle and
   the Studio runner is not in a running phase (`require_mutable` + a runner-state
   check). Same instinct as `rig_build_v1.py`'s `forbidden_during_build`.
2. **Operator-initiated only.** No auto-fire on a verdict, no armed mode. There
   is no `SUPERVISE: REPAIR`-style toggle for this — it is one button press per
   event.
3. **One attempt per verdict event.** A per-event latch (like
   `supervision_acknowledged`), cleared only when `_note_supervision` sees the
   reading change. A second press on the same unchanged verdict is refused.
4. **Confirm dialog** naming both cells and the motion, before the route is
   called. `role="dialog" aria-modal="true"`.
5. **On a failed or dropped grip:** the correction path halts and reverts the
   banner to "stop and ask". It does **not** `LOCK` the session for an ordinary
   miss — [D11](placement-supervision.md#d11--notify-never-act-for-now): a
   verdict never locks. **But a silent-grip failure that leaves the claw holding
   a block at an unknown state is a `HELD` / `ABORTED` condition and *does*
   lock** — that is the `P` verb's own abort discipline (Stage 15 D9), identical
   to `build()`'s. `SAFE` ≠ `HELD` (AGENTS.md §5): keep the branches separate.
6. **Mandatory re-verify (D12).** After the correction, supervision re-judges
   `[a,b]` in the next quiet window before the runner may resume, and the
   hysteresis is reset so the re-check is not made of frames taken while the arm
   was over the board ([F19](placement-supervision-progress.md#f19--d12s-dismissal-cannot-be-a-per-cell-mute-and-the-code-says-why)).
   *"A repair that is not re-verified is a guess with extra steps"* — and a
   silent grip means the machine cannot know it moved anything.

### E.3 Relationship to Stage 15 and to supervision M4 — resolved

| | Trigger | Detections from | Magnitude regime | Verb |
| --- | --- | --- | --- | --- |
| **Supervision M4** | `REMOVED` verdict, when armed | occupancy only | n/a — feeds a **fresh** block | `B a b <level>` (feeder). **Not** this feature. |
| **Stage 15 Stage C** | its own between-jobs detection pass finds one sub-cell outlier in the **0.5–1.2 cm** band | `detect_aligned_blocks(frame, grid=None)` + memory-driven matching | sub-cell, `< 1.2 cm` (`> 1.2 cm` ⇒ Stage 15 **refuses**) | `P <col> <row> <level> <dx> <dy>` |
| **CORRECTION (this)** | operator presses the button on a `MOVED` / `DISPLACED` verdict | supervision's live occupancy + the retained centroid of the one moved detection | **supra-cell** — `DISPLACED` is by definition off its site, often 1–2.5 cm; `MOVED` is ~one pitch | **the same `P` verb** |

> **The resolution the prompt asks for:** CORRECTION and Stage 15 **share the `P`
> verb, the `link.py` method and the `PlacementLedger` predicates, but are
> separate orchestrations.** Stage 15 must never fire on a verdict (its own
> rule); CORRECTION is the *only* verdict-driven path, and it is manual.

> **The collision between the two magnitude regimes is a real blocker, not a
> wording problem.** Stage 15 D8 **refuses** any correction above 1.2 cm,
> because a block 1.6 cm off has its edge against the neighbour and gripping it
> disturbs two blocks. A `DISPLACED` block is off its site — routinely 1–2.5 cm —
> which is *above Stage 15's own refuse threshold*. `MOVED` (a full pitch away)
> is further still. **So CORRECTION is defensible only for the narrow
> `DISPLACED` sub-band, **vertical mode**, 0.5–1.2 cm, at level 0, axis-aligned,
> no taller neighbour, clear destination.** For `MOVED` and for `DISPLACED > 1.2 cm` the
> honest action is [removed-block-compensation Case 2 **P1**](removed-block-compensation.md#3-the-three-cases-and-they-are-genuinely-different)
> — pause, name the cells, ask the operator to move it by hand, re-verify. The
> button should be **hidden**, not merely disabled, outside the correctable
> slice, so it never advertises a capability the machine does not have.

---

## F. UI

- **Where:** `web/src/components/SupervisionBanner.tsx`, inside the loud-verdict
  `<section>`, **only** when `supervision.correctable === true` (a server flag —
  the browser never derives it; [DESIGN.md §8](../DESIGN.md#8-what-must-not-be-done),
  *"No client-side verdict about the board"*). The server sets `correctable`
  only when: **`mode == "vertical"`**; verdict is `DISPLACED`; level 0; magnitude in `[0.5, 1.2]` cm;
  `detection.angle` within a few degrees of the mode axis; `has_taller_neighbour`
  false for every touched cell; `[a,b]` reads empty; the `P` verb / `replace_block`
  is available; and no build/program is running. Otherwise the button is **not
  rendered** (§E.3), and the banner keeps its existing "straighten it by hand"
  copy.
- **The control:** a real `<button type="button">`, ≥ 44 × 44 px, label
  `aria-label="Return the block to column {a} row {b} — the claw will pick it up
  and set it down"`. Text on the button: `RETURN BLOCK TO CELL`. **Never**
  past-tense, never "Fix", never "Correct" — the machine has not done anything
  yet. It sits **after** the existing `DISMISS` in tab order (dismiss is always
  safe; acting is not).
- **Confirm step:** a `role="dialog" aria-modal="true"` panel — *"The claw will
  move to where the block is now, grip it, and place it on [a,b]. Watch the rig.
  This runs once."* Buttons `RUN` / `CANCEL`. `Esc` cancels (unlike the red
  banner, where `Esc` must not dismiss — D11).
- **Route:** `POST /api/supervision/correct`, mirroring `/api/supervision/ack`'s
  shape, guarded by `require_mutable`, `require_fresh_camera`, `_latching`, the
  not-during-run check and the one-attempt-per-event latch. It calls
  `rig.link.Rig.replace_block(...)` on the `BuildJob` worker thread (it blocks
  for tens of seconds) and publishes the result like a build.
- **After:** the banner shows `CORRECTING — watch the rig` (dim, not a state
  colour — it is motion the operator started, like `BUSY`), then on the terminal
  ack either `RE-CHECKING [a,b]` until D12's re-verify resolves, or the `HELD`
  lock treatment if the grip aborted.
- **ARIA / a11y:** inherits [placement-supervision.md §6.7](placement-supervision.md#67-accessibility--the-checklist-this-must-pass).
  The button is not inside the `role="alert"` live region's announced text; its
  own `aria-label` carries the cell. Disabled states are never used here — the
  button is present-and-actionable or absent, so there is no "disabled with
  reason" to render (the *reason it is absent* belongs in the banner sentence:
  *"…straighten it by hand; it is too far off its cell for the claw to grip
  safely."*).

---

## Blockers

1. **No firmware verb picks a block off the board.** · *Blocks:* the entire
   pick-from-observed / place-at-commanded motion is inexpressible — `B`/`M` feed
   from the feeder, `G` does not grip. · *Unblocks:* the `P <col> <row> <level>
   <dx_cm> <dy_cm>` verb (Stage 15 §4) in every flashed sketch, stub-`g++`
   syntax-checked, **flashed and watched on the rig**, `test_grid.py` extended,
   `AGENTS.md §6` + `docs/ack-protocol.md` updated in the same commit.

2. **The observed pick coordinate is discarded before it leaves the supervisor.**
   · *Blocks:* nothing downstream of `observe()` has a centimetre position to
   send. · *Unblocks:* retain the moved detection's centroid in the map's cm
   frame on `Observation` → `Verdict` → `SupervisionModel` → `types.ts` → the
   route; publish `dx`/`dy` as `x_obs − mapped_grid.cell_center_cm([a,b])`; plus
   a server-computed `correctable` + `reason`. **Vertical only** — §B.3 shows the
   `dx` knob-bias is negligible in vertical and material in horizontal, and the
   saved map cannot say whether it was block- or paper-calibrated.

3. **The `DISPLACED` / `MOVED` magnitude is outside the machine's safe
   correction band.** · *Blocks:* Stage 15 D8 refuses corrections `> 1.2 cm`
   because a block ≥ 1.6 cm off touches its neighbour; `DISPLACED` is routinely
   1–2.5 cm and `MOVED` is a full pitch. · *Unblocks:* restrict the button to
   `DISPLACED` in `[0.5, 1.2]` cm at level 0; everything else is P1 "stop and
   ask". Cannot be widened without a hardware change to jaw geometry.

4. **Jaw capture tolerance is unmeasured.** · *Blocks:* whether the claw grips a
   block presented 0.3–0.5 cm off-centre or shoves it is unknown;
   `SERVO_CLOSE_ANGLE` is tuned for a feeder-square block. · *Unblocks:*
   [Stage 15 Stage B.1](stage-15-placement-correction.md#stage-b--two-bench-measurements-gates-stage-c)
   — place a block 0.5 / 0.8 / 1.2 cm off, drive the claw to it, observe.

5. **Placement repeatability is unmeasured.** · *Blocks:* if the re-place is no
   more accurate than the original place (repeatability near 0.5 cm) the
   correctable band is empty and the feature cannot help. · *Unblocks:*
   Stage 15 Stage B.2 — repeat one cell, measure the spread.

6. **Parallax is uncorrected in supervision.** · *Blocks:* a `DISPLACED` /
   `MOVED` verdict at level 1–2 carries 0.9–1.9 cm of directional parallax the
   pick point would inherit. · *Unblocks:* either restrict the button to level 0
   (recommended) or land [parallax](camera-parallax-and-levels.md) M5 and feed
   `parallax_excess()` into the retained centroid before it is published.

7. **`detection.angle` is ignored by the `P` verb.** · *Blocks:* a block rotated
   > ~5° presents a ~4 cm face to a grid-aligned jaw and cannot be gripped;
   there is no calibrated tool offset for an arbitrary angle. · *Unblocks:* gate
   the button on `angle` within a few degrees of the mode axis; a rotated block
   is P1.

8. **Three written rules forbid the button.** · *Blocks:* DESIGN.md §8,
   placement-supervision.md §6.10, D11. · *Unblocks:* the user amends §8 and
   §6.10 with an operator-initiated carve-out and re-scopes D11 to "never acts
   *automatically*", in the same commit as the button.

9. **Which sketch is canonical is unresolved.** · *Blocks:* `config/rig.json`
   names `build_test_v1`; Stage 15 pairs `build_vertical_grid` +
   `build_horizontal_grid`. Pairing the verb into the wrong file ships a verb
   the rig does not have. · *Unblocks:* the user confirms the deployment sketch;
   the verb goes into every sketch that is flashed, `test_grid.py` covers it.

---

## Reconciliation, explicit

- **Stage 15:** CORRECTION reuses Stage 15's `P` verb, `link.replace_block()`
  and `PlacementLedger` D5/D6 predicates verbatim. It differs only in the
  *trigger* (an operator button on a supervision verdict, vs Stage 15's own
  between-jobs outlier pass) and inherits Stage 15's Stage A/B gates. **Stage 15
  must be built first**; CORRECTION is a thin manual entry point onto its
  Stage C. Stage 15's rule that it *"must never fire on a verdict"* is preserved
  — CORRECTION is a separate orchestration, not Stage 15 reacting to a verdict.
- **Supervision M4:** unrelated. M4 is `REMOVED` → feed a **new** block with
  `B`, automatic when armed. CORRECTION never feeds, is never automatic, and
  never touches `REMOVED`.
- **DESIGN.md §8 "no re-place button":** this feature **cannot ship without
  superseding it**, and this audit recommends it not ship until the user does so
  explicitly, alongside the firmware and bench work. An operator-initiated,
  confirm-gated, one-shot button that says "watch the rig" is arguably a
  different speech act from the banned passive Retry — but "arguably" is the
  user's call, in a DESIGN.md edit, not this document's.

---

## If it is built — the phased plan

Gated exactly like [Stage 15 §8](stage-15-placement-correction.md#8-the-implementation-plan);
Stage 15's Stage A/B are shared prerequisites, not repeated here.

### Phase 1 — plumbing only, no motion, no button (safe on a live rig)

| File | Change |
| --- | --- |
| `python/rig/supervisor.py` | `observe()` retains the moved detection's centroid in workspace cm on `Observation`; `classify()` / `step()` put `pick_cm` + `correctable` + `reason` on `Verdict`. Pure; the correctability rules (level 0, band, angle, neighbours, destination) are a pure function over the ledger + observation. |
| `python/web/state.py` | `SupervisionModel` gains `pick_cm`, `correctable`, `correction_reason`; `supervision_model()` folds them. |
| `web/src/types.ts` | the three fields on `Supervision`. |
| `python/tests/test_supervisor.py` | `correctable` is true only for the exact slice; false (with the right `reason`) for level ≥ 1, angle off-axis, taller neighbour, occupied destination, magnitude out of band, `MOVED`. Assert **named physical scenarios**, not bare numbers. |
| `python/tests/web_supervision_test.py` | the new fields survive the seam and a mode latch. |
| `web/src/components/SupervisionBanner.test.tsx` | the button renders **only** on `correctable`; the sentence changes to "by hand" copy otherwise. |

**Gate:** run advisory for a session — do the `correctable` slices the server
picks match what a human would call correctable by eye?

### Phase 2 — the firmware verb (unflashed / unverified locally)

Identical to [Stage 15 Stage C](stage-15-placement-correction.md#stage-c--the-correction-only-if-a-and-b-come-back-favourable):
the `P` verb in every flashed sketch (stub-`g++` only — **unflashed and
unverified on hardware**, flag it every time), `AGENTS.md §6` +
`docs/ack-protocol.md` + `test_grid.py`, `link.replace_block()` with `build()`'s
abort discipline, `mock_board.py` mock `P`, `test_link.py` for the ack shape and
`HELD`/`ABORTED` handling.

**Blocked on** Stage 15 Stage B's two bench measurements coming back favourable,
and on the sketch-canonical question (blocker 9).

### Phase 3 — the button (only after Phase 2 is flashed and §E.1 is superseded)

| File | Change |
| --- | --- |
| `web/src/components/SupervisionBanner.tsx` | the button + confirm dialog (§F). |
| `python/web/routes_command.py` | `POST /api/supervision/correct` — guards, one-shot latch, worker-thread dispatch, D12 re-verify hook. |
| `web/src/studio/runner.ts` | a `correction-started` / `correction-settled` event pair; the runner stays paused through it and only resumes after D12's re-check passes. |
| `web/src/components/RunnerPanel.tsx` | log the correction and its re-verify result — thesis evidence. |
| `python/web/state.py` | `CORRECTING` / `RE-CHECKING` observer sub-states (dim, no state colour). |
| `docs/DESIGN.md §8`, `docs/features/placement-supervision.md §6.10 / D11` | the operator-initiated carve-out — **same commit**, with changelog per the living-doc rule. |
| `docs/STUDIO.md` | if the button lands in the Studio UI — same commit, changelog. |

### Tests

- `test_supervisor.py` — the `correctable` slice, every exclusion with its reason.
- `test_placement_check.py` — the pick offset arithmetic in magnitude space,
  sign correct on X (`assert` a named scenario: *"a block seen 0.4 cm further
  from the X home switch than the map's cell yields `dx = +0.4`"*); a
  correctly-placed block yields `dx ≈ 0` (within the map flattening tolerance);
  and `judge_band` returns `IGNORE` / `CORRECT` / `REFUSE` at 0.3 / 0.9 / 1.5 cm.
- `test_link.py` — `P` ack shape, `HELD` → lock, `ABORTED` → lock, `SAFE` →
  retryable.
- `web_supervision_test.py` — the route's guards: refused during a build,
  refused on a stale camera, refused on a second press of an unchanged verdict,
  D12 re-verify runs before the runner resumes.
- `SupervisionBanner.test.tsx` / `runner.test.ts` — button only on `correctable`;
  confirm dialog `Esc`-cancels; the runner stays paused across the correction
  and resumes only on a passing re-check.
- `test_grid.py` — the `P` verb's argument shape, paired against every flashed
  sketch.
- Standard gate: `python3 python/tests/test_grid.py` (the `zGoPickup()` failure
  is F10/P5, pre-existing, **do not fix here**); `cd web && npx vitest run`;
  `cd python && python3 -m pytest tests/`.

---

## Gate run for this audit (no code changed)

| Suite | Result |
| --- | --- |
| `python3 python/tests/test_grid.py` | **234 passed, 1 failed** — `rig sketch phase 5 uses zGoPickup(), not zGoGround()`, the known F10 / P5 firmware drift, untouched by this audit |
| `cd web && npx vitest run` | **42 files, 556 passed** |
| `cd python && python3 -m pytest tests/` | **100 passed** |

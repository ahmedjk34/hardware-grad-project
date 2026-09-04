# Block vision — the detector, the overlay, and the calibrator

Everything that finds wooden blocks in a camera frame, in one place.
`AGENTS.md` §3d-bis and §3d-ter carry the rules that must not be broken; this
carries the reasoning, the constants, the measured numbers and the failure
modes behind them.

Three layers. They share a segmentation front end and diverge completely after
it, and confusing them is the main way to get a wrong answer.

| Layer | Module | Answers | Runs | May write `workspace_map.json` |
| --- | --- | --- | --- | --- |
| 1 · segmentation | `vision/block_detector.py` | what warm block-shaped things are here | every analysed frame | no |
| 2 · live overlay | `vision/block_outline.py` | which of those are really blocks, and where to draw them | every analysed frame | no |
| 3 · calibration | `vision/block_grid.py` | where the machine's grid is, in pixels | once, deliberately | **yes** |

**Never reach past a layer.** A feed calling `detect_blocks` directly gets the
frame-edge rails and the holder's offcuts. A caller wanting geometry from
`block_outline` gets rectangles with no lattice behind them.

---

## 0. The two reference boards

Both are the vertical grid with **29 blocks** laid from the home corner
(columns 0–6 of rows 0–3, plus the single block on `[0,4]`), leaving **13**
cells unplaced — the far rows, toward y+. Both also carry the **holder's two
thin wooden offcuts beside `[0,0]`**, which are the single most useful thing in
them: they are wooden, roughly block-shaped, and not blocks.

| File | Size | Note |
| --- | --- | --- |
| `python/captures/IMAGE_TO_TEST_BLOCK_CALIBRATION.png` | 410 × 606 | lens160 correction |
| `python/captures/20260903-122957_corrected_…-lens168-…png` | 433 × 520 | lens168, different k |

`tests/test_block_grid.py` §10 and `tests/test_block_outline.py` assert **exact
cell sets** on these, not counts. A count-only assertion passes on a board
renumbered by one cell, which is the failure that matters.

---

## 1. Layer 1 — `block_detector.detect_blocks`

### How it segments

Warm material is found by **red-minus-blue AND red-minus-green** exceeding
thresholds (`color_threshold=8`, `red_green_threshold=3`), never by brightness:
the work surface is overexposed in the captures this was tuned on, so a
brightness cutoff selects the table. `_warm_mask` then opens with a 3×3 and
closes with a 5×5 — both deliberately small, because a large close joins
neighbouring blocks before the splitting step gets a chance.

### How a contour becomes blocks

Three paths, tried in order:

1. **Straight through** — the contour is already one standard-sized,
   sufficiently rectangular, sufficiently solid block.
2. **`_split_touching`** — two blocks meeting leave a deep concave notch on
   each side of the seam. The two deepest convexity defects are connected and
   the component cut in two. Ordinary blocks have shallow defects and pass
   through intact.
3. **`_decompose_compound`** — fits *ideal* block-sized rectangles into a
   merged component, bounded by `MAX_RECTANGLE_HYPOTHESES = 256`.

Path 3 is the source of most downstream trouble and is worth understanding: it
emits synthetic rectangles that are block-*shaped by construction*, whatever
was actually there. That is why a shadow bridging two blocks yields a third
rectangle straddling the seam, and why the holder's offcuts come back at full
block size. **No shape test can reject them** — only position can.

### The size prior, and why it drifts

Block size is estimated from isolated rectangles, falling back to
`frame.shape[1] * 0.144` (long) and `* 0.052` (short). That fallback assumes a
block covers a fixed *share of the frame*, which is true only of the captures
it was fitted to. It is the reason the detector changes its answer between
processing widths. `expected_size=(long_px, short_px)` replaces it with a
measurement; the calibrator supplies one from its own homography.

### Opt-in arguments

All default **off**, so the live feed keeps the behaviour it was tuned for.

| Argument | Effect | Who uses it |
| --- | --- | --- |
| `balance` | `color_grid.white_balance` before segmenting | nobody, by measurement — see §4 |
| `flatten` | `color_grid.flatten_illumination` before segmenting | layer 3 only |
| `expected_size` | replaces the frame-width size guess | layer 3 |

### Known limitations

- The compound decomposition used to over-detect (`synthetic U` 4 for 3,
  `end-to-end pair` 3 for 2); `tests/test_block_detector.py` now passes those at
  3/3 and 2/2. Layer 2's IoU pass still covers any residual over-detection in
  practice.
- One fixed crash: `_geometry` built a hue mask sized to a contour's bounding
  box, but the compound path synthesises rectangles that hang off the frame.
  numpy silently clipped the ROI while the mask kept full size, and `cv2.mean`
  asserted. Both are clipped together now.

---

## 2. Layer 2 — `block_outline.detect_aligned_blocks`

A drop-in replacement for `detect_blocks`, same return type, so the overlay,
hover test and snapshot code are untouched.

### What it fixes

The feeds drew layer 1 directly: each block outlined by its own raw
segmentation contour, in one of six cycling colours. Both halves fail on a full
board. A mask edge wanders a pixel or two all the way round, so twenty-nine
outlines that should read as one grid read as twenty-nine wobbly shapes; and
adjacent outlines in unrelated colours read as unrelated objects.

### The pipeline

```
detect_blocks (ordinary preview settings)
      ↓
_drop_duplicates      IoU > DUPLICATE_IOU (0.30)
      ↓
_inside_frame         box must not run off the frame (EDGE_TOLERANCE_PX = 1.0)
      ↓
_lattice_filter       needs a MachineGrid; drops anything off the lattice
      ↓
_rectify              median size + shared bearing, measured centre kept
```

### Constants

| Constant | Value | Why |
| --- | --- | --- |
| `MIN_POPULATION` | 4 | below this there is no median worth sharing; each box is squared to its own rotated rect |
| `MIN_LATTICE_BLOCKS` | 6 | below this "off the lattice" means nothing |
| `EDGE_TOLERANCE_PX` | 1.0 | a *hard* border test — see below |
| `LATTICE_SNAP` | `block_grid.MAX_INDEX_SNAP` (0.34 cells) | shared with layer 3 on purpose |

### The edge test is deliberately not the calibrator's

Layer 3 requires a block to keep a fifth of its width clear of the frame,
because a clipped block's centroid is dragged inward — 21 px on a 40 px block —
and that would poison a saved map. Layer 2 wants the **opposite**: a block near
the edge should still be *drawn*, because the operator can see it is at the
edge and hiding a real block is the worse failure. Using layer 3's margin here
silently dropped blocks the mock camera legitimately places on the outer row.

So layer 2 rejects only boxes that actually run off the frame — which is what
the purple rails at the left edge do.

### The lattice filter, and its brakes

Given a `MachineGrid`, `_lattice_vectors` recovers the two step vectors from
the blocks' own neighbours, every detection is projected onto that basis, and
anything further than `LATTICE_SNAP` from an integer site is dropped. This is
what removes the holder's offcuts.

Two brakes stop it hiding real blocks:

- fewer than `MIN_LATTICE_BLOCKS` detections → skipped entirely;
- if the recovered lattice would reject **more than 30%** of what it saw, it is
  not the board's lattice → everything kept.

### Rectify keeps the centre

Every survivor is redrawn with the population's median size and the lattice's
bearing. **The centre stays exactly where it was measured.** Snapping positions
onto the lattice would draw a prettier grid and hide a misplaced block, which
is the one thing this overlay exists to show. `tests/test_block_outline.py`
asserts the centres match a same-settings `detect_blocks` run exactly.

### Do not borrow layer 3's detection settings

The obvious "improvement" is full resolution plus `flatten`. Measured on the
reference boards, it finds **not one extra block** at any width, and costs up
to four seconds a frame:

| width | flatten | found | board | 1296 px frame |
| --- | --- | --- | --- | --- |
| 384 | off | 29/29 | 84 ms | 103 ms |
| 384 | on | 29/29 | 291 ms | 221 ms |
| 480 | off | 29/29 | 37 ms | 104 ms |
| 640 | on | 29/29 | 578 ms | 902 ms |
| 1024 | off | 29/29 | 60 ms | 574 ms |
| 1024 | on | 29/29 | 543 ms | **3894 ms** |

Same story for `min_area`: 250 finds nothing extra and doubles the cost,
because every small contour it admits enters the rectangle search (45 ms at the
default 500, 161 ms at 250). **The 33 → 29 improvement is entirely the
rejection steps.** A timing guard in `test_block_outline.py` keeps this from
returning.

### The wrapper must accept `**kwargs`

`AnalysisWorker` calls `analyzer(frame, **request.kwargs)` — the feeds submit
`color_threshold` and `min_area` — and it converts **any exception into
"analysis failed" with zero detections**. A wrapper missing `**kwargs`
therefore shows an empty overlay forever, with the reason visible only in the
worker's error field. This cost real debugging time. Do not simplify the
lambdas in `console_pipeline.py`, `rig_build_v1.py` or `gridded_camera_feed.py`.

### Drawing

`camera_feed.BLOCK_COLOR` is one stroke for every block, over a dark
under-stroke so the edge reads on both the pale surface and the dark hardware.
`BLOCK_HOVER_COLOR` differs by **brightness, not hue**, so the hovered block
reads as "this one" rather than "a different kind of thing". The overlay draws
`detection.box`, never `detection.contour`.

`camera_feed.py` passes **no grid** on purpose — it knows nothing about the rig
— so it gets squared, uniformly-sized outlines without the lattice rejection.

---

## 3. Layer 3 — `block_grid`, the calibrator

Full rules in `AGENTS.md` §3d-bis. What follows is the mechanism.

### Why it beats a printed sheet

Every sheet route measures the **camera against a piece of paper**, then
assumes the paper sits where the firmware's cells are. That assumption is the
entire reason `color_grid.HOME_CONVENTIONS` exists. Here the blocks *are* the
machine's own output, so the thing measured is the thing calibrated — including
backlash, tool offsets and each mode's `error_offset_*_cm`.

### Two ways in

**Labelled (preferred).** `rig/block_calibration.py` issues one
`B <col> <row> 0` per cell and records the sighting against the cell it
*commanded*. Nothing to infer, no origin to guess.

**Unlabelled.** `detect_block_lattice` takes one frame of blocks somebody else
placed, recovers the lattice, and snaps everything onto integer sites. It
**cannot recover the origin** — a regular lattice is identical shifted by a
whole cell. `LATTICE_ANCHORS` supplies it (default `bottom-left`), and a wrong
anchor is *not detectable*: on the reference board, `top-right` relabels
`[0,0]` as `[6,4]` and every gate still passes. The test suite asserts that
failure rather than pretending otherwise.

### Why five placements, not four

Four correspondences fit a homography **exactly** — every residual is zero by
construction and the calibration carries no evidence it is right.
`MIN_OBSERVATIONS = 5` is the smallest set that can disagree with itself, and
therefore the smallest that can be checked. `DEFAULT_OBSERVATIONS = 6`.

### What replaces the chessboard parity gate

The printed sheet gets a free consistency check from its ink colours. Identical
wooden blocks give nothing equivalent, so two **physical** agreements stand in,
both measured against the fitted homography at each cell:

- **footprint** — observed short side vs predicted block width
  (`SIZE_AGREEMENT_RANGE`, 0.60–1.55);
- **bearing** — observed long axis vs the mode's own axis
  (`MAX_ANGLE_DISAGREEMENT_DEG`, 22°).

Between them they catch "a cable was detected instead of a block" and "the
block landed on the wrong cell". A uniformly wrong block scale leaves *every*
residual at zero and is caught only by the footprint check — it is not
redundant.

### Conditioning is numeric, not a cell count

Spread and hull area are necessary and insufficient. A dense plan fills
row-major, so after seven placements the set is six points along row 0 plus one
in row 1: spread 6×1, hull 2.5 cells, and completely degenerate, because every
four-point subset has three collinear.

`dlt_conditioning()` returns the DLT design matrix's second-smallest singular
value over its largest, Hartley-normalised. Measured on this grid:

| configuration | score |
| --- | --- |
| single row | 4e-33 |
| six collinear + 1 | 2e-17 |
| six collinear + 2 | 2e-02 |
| four corners + 2 interior | 3e-01 |

`MIN_DLT_CONDITIONING = 1e-5` sits in a thirty-order-of-magnitude gap. It is
not a tuned number.

### Dense mode — measuring the lattice

Once `MIN_DENSE_OBSERVATIONS = 25` cells of a `DENSE_MODES` grid are occupied,
the fit stops being assumed and starts being tested. Horizontal is excluded: it
is three columns wide, so curvature along X would be fitted from three points.

**Pitch is measured, not derived.** `measure_pitch()` uses only
lattice-*adjacent* pairs, so every sample is exactly one pitch. Reported pooled
*and* per row (for X) and per column (for Y), because "is the gap a static
number or does it depend where you are" is the question a single average hides.
On the reference board: X 29.38 px (sd 1.24, **1.4 %** spread across rows),
Y 69.14 px (sd 1.08, **2.0 %** across columns) — static to within 2 %.

**Four models compete on leave-one-out prediction.** `similarity` (4 dof),
`affine` (6), `homography` (8), `homography+curvature` (10); ties go to the
simpler model. Training error would only ever pick the richest one, and the
whole point of the fit is to place cells no block was ever put on. Fitted by
plain least squares, never `cv2.estimateAffine*`'s robust methods — those
resample, which would make leave-one-out non-deterministic, and there are no
outliers to be robust against once labels are known.

On the reference board:

```
similarity  (4 dof): fit 93.64 px, held-out 101.37 px
affine      (6 dof): fit  1.22 px, held-out   1.38 px
homography  (8 dof): fit  1.01 px, held-out   1.22 px
homography+curvature (10 dof): fit 0.85 px, held-out 1.09 px  <- chosen
```

**Curvature models the machine, not the camera.** A homography already absorbs
perspective and any uniform scale error. What it cannot absorb is an
advance-per-cell that drifts along the travel, which is nonlinear in lattice
coordinates. So the correction is applied *in lattice space*
(`c + a·c²`, `r + b·r²`) **before** projection, and cannot be folded into the
3×3. `BlockGridCalibration` carries it and applies it inside `point_at()` and
`grid_at()` — the two doors every other method goes through — so `cell_quad`,
`outline`, `cell_at` and `workspace_corners` are all correct without knowing it
exists. `_unbend` inverts `x + k·x²` by the root nearest the identity.

The coefficient is recovered only approximately: a quadratic bend is partly
degenerate with a homography's own perspective terms, so the two share the
work. Tests assert **prediction**, not the parameter. The regression must
include `[1, i, i²]` and keep only the quadratic coefficient — fitting `i²`
alone under-estimates the curve by most of its magnitude, because `i²` is
strongly correlated with `i` over a 0..6 range.

**The warning must not blame the belts.** A drifting machine and a lens whose
correction left distortion behind produce the same curve, and one frame cannot
separate them.

### The one non-circular geometry check

`px_per_cm` is *defined* as measured/expected, so comparing the pitch ratio
against the printed ratio after correcting by it is circular — it returns
exactly 2.000 whatever the truth. The real check is `anisotropy_agreement`: the
optical stretch measured from cell **pitches** against the stretch measured
from block **footprints**. Different quantities through one lens; they agree
only if `config/rig.json`'s gaps describe this board. The reference board's
view is genuinely **17.7 % anisotropic** and the two estimates agree to 4 %.

### Virtual cells

The block supply is smaller than the grid, so unreachable cells are filled from
the fitted lattice, marked `full=False` with `area=0`.
`BlockGridCalibration.found_cells` returns **only** measured cells — everything
consuming it (`grid_evidence`'s coverage gates, `color_grid_check`'s
"physically found" count) is asking what was observed. `virtual_cells` is the
other half.

`plan_dense_cells()` fills row-major from the home corner rather than
spreading, the opposite of `plan_calibration_cells()`. A spread set conditions a
homography well but measures pitch badly — every `measure_pitch` sample needs a
lattice-adjacent pair. The `inset` is clamped **per axis**, because horizontal
is three columns wide and a blanket inset of 1 would leave a single column.

### Detection settings — one deliberately backwards

`_colour_sightings` runs `flatten_illumination` but **not** `white_balance`,
the opposite of the sheet detectors. `white_balance` is a white-*patch*
estimator, safe on a frame that is mostly white paper. A board covered in
wooden blocks breaks that assumption — the bright quantile lands partly on wood
and the correction pulls the blocks toward the surface it was meant to separate
them from. Measured: balance on finds 28 of 29, off finds all 29, and off holds
at 29 across every colour threshold from 4 to 8 where on collapses at 4.

### Frame differencing

In the labelled path each capture is differenced against the previous frame, so
the newly placed block is the only change — far stronger than "warm rectangle
on a pale surface", and it survives the magenta cast that red-minus-blue does
not. Channel-max absolute difference, not luminance: pale wood on pale paper
separates better in one channel, and which one depends on the cast. Otsu
floored at `DIFF_MIN_THRESHOLD` so an all-noise difference finds nothing.

A candidate both the difference and the colour detector agree on is promoted to
`source="corroborated"` and wins on that agreement.

---

## 4. Saving, and what a saved map can carry

### Both routes write an identical file

`block_workspace_map()` goes through `ColorGridCalibration.workspace_corners()`
then `WorkspaceMap.from_grid` — the same two calls `paper_workspace_map()`
makes. Given the same calibration and projection they produce a
**byte-identical** `workspace_map.json`. `tests/test_calibration_parity.py`
asserts that field by field, because if they diverge the app adopts one and
silently refuses the other, and the only symptom is "the grid did not change".

### The projection is not optional

Every consumer refuses a map whose `projection` — lens profile, flip/rotate,
correction on/off, framing ROI — differs from its own. A map saved with
`projection: null` is written successfully and refused by **everything**.

Camera Studio is an *editor*: its live geometry drifts from
`camera_settings.json` until SAVE JSON writes it, and the app renders from the
file. `blockcalsave` therefore compares `Studio.projection()` against
`Studio.saved_projection()` and **refuses up front**, naming which of
view/lens/orientation/roi drifted.

### A four-corner map cannot carry the curvature

`WorkspaceMap` stores four envelope corners plus grid geometry — not a per-cell
table — so a consumer spaces cells evenly between them. The corners come back
exact and the error peaks mid-grid, which is that flattening's signature. On
the reference board: **1.25 px mean, 2.07 px max = 0.27 cm** on a 2.2 cm block.
`workspace_map_error()` measures it and `blockcalsave` reports it. Removing it
means widening the format, which touches every consumer.

### A saved map does not reach a running app by itself

The map is read once at `ConsolePipeline.start()` and again only on a mode
change. Calibrating happens in a *separate* process, so:

| Consumer | How to pick up a map saved elsewhere |
| --- | --- |
| `camera/rig_build_v1.py` | press **`L`** |
| web console | **Reload saved calibration**, or `POST /api/calibration/reload` |
| anything embedding `ConsolePipeline` | `reload_workspace()` |

A map present but refused must surface its **sentence** — "no calibration
saved" and "camera lens/orientation/framing changed" need opposite responses,
and silence is indistinguishable from both.

---

## 5. Running it

```bash
# Machine-driven calibration, hardware-free dry run
python/camera/block_grid_calibrate.py --mock --inset 1

# The real thing: 6 spread cells, writing config/workspace_map.json
python/camera/block_grid_calibrate.py --save

# Use every block you own, then fill the rest in
python/camera/block_grid_calibrate.py --supply 29 --save

# Tight framing that cuts off the outer row of blocks
python/camera/block_grid_calibrate.py --inset 1 --save

# An annotated frame per placement — the fastest way to see WHY a run failed
python/camera/block_grid_calibrate.py --trace
```

In Camera Studio: **BLOCK CALIBRATION** → **BLOCK CAL SAVE** (press SAVE JSON
first if any geometry was touched). `blockcal top-right` picks another anchor;
`blockcaloff` clears the overlay.

`--mock` can only dry-run the mode `config/rig.json` calls active — `MockCamera`
reads that global and `ConsolePipeline` gives it no way to be told otherwise.
Both modes are covered properly in `tests/test_block_calibration.py`, which
builds the mock camera directly.

---

## 6. Tests

Counts below are approximate — the plain-assert harness prints "all checks
passed", not a number, and several `check()`s run inside loops.

| Suite | Covers |
| --- | --- |
| `test_block_outline.py` | both boards to exactly 29, square corners, shared size/bearing, centres unmoved, edge and holder rejection, a timing budget. **The timing check ("costs no more than twice the plain detector") is load-sensitive and fails intermittently on a busy machine** |
| `test_block_grid.py` | planning, the fit against known homographies, tilt/perspective/noise, every gate, dense metrology, model selection, virtual fill, the real board's exact cell sets, projection round-trip. Slow (~2 min) |
| `test_block_calibration.py` | the rig-driven run against a mock rig + camera, recovering the mock's own workspace map, and every refusal (rejected, aborted, unseen, clipped) |
| `test_calibration_parity.py` | block and paper routes write a byte-identical file; per-mode saves do not clobber each other |
| `test_workspace_reload.py` | a map saved by another process reaches a running console, and a refused one explains itself |
| `test_block_detector.py` | layer 1; passes (the compound over-detections it once carried are fixed) |

Known failures elsewhere: `mock_camera_test.py` (2 under pytest), unrelated to
this work and unchanged by it.

---

## 7. If you are extending this

- **Adding a rejection rule?** Put it in layer 2 or 3, never layer 1 — layer 1
  must stay a pure shape hypothesis, or the calibrator loses the freedom to
  make its own decisions.
- **Tempted by better detection settings?** Measure the count *and* the time on
  both reference boards first. The table in §2 is what that measurement looked
  like last time, and the answer was "no change, four seconds slower".
- **Changing the lattice maths?** `_lattice_vectors`, `_deduplicate` and
  `MAX_INDEX_SNAP` are shared by layers 2 and 3 deliberately. Fork them and the
  overlay will start disagreeing with the calibration about what a block is.
- **Widening `WorkspaceMap`?** That is the one change that removes the 0.27 cm
  in §4, and it touches every consumer of the format.
- **Touching `AnalysisWorker` wrappers?** Keep `**kwargs`. See §2.

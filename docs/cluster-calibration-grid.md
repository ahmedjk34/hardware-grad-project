# Cluster calibration grid (bordered 3×3 fiducials)

**State: drafted on the desk. No camera has seen the printed sheet. Every
threshold marked `TUNE-WITH-CAPTURE` in `python/vision/cluster_grid.py` is a
guess until a real Pi frame is run through `camera/color_grid_check.py`.**

Built: `vision/cluster_grid.py` (all of C1–C9 below implemented),
`tests/test_cluster_grid.py` passes (23/23, both modes, tilt, three colour
casts, wrong-mode refusal). The printed sheet itself does not exist yet, so
nothing above the synthetic-test line has been checked against reality.

## Context

The green/magenta sheet (`printed-color-grid.md`) and the A2 combined target
print badly on a cheap printer: muted olive/mauve ink and a warm "beige" lane
that the rig camera's uncorrected yellow cast washes out. On the last live
frame the detector confirmed 53 of ~90 blobs and the combined target only
21 of 80 fiducials — not enough to calibrate.

The new sheet trades the muted two-ink chessboard for something a camera can
lock onto regardless of cast:

* every cell has a hard **black border** — a printed line, not an inferred
  edge where ink fades into a white gap;
* cells are grouped into **3×3 clusters**; clusters are separated by a white
  **gutter** on both axes; the sheet is still printed larger than the machine
  grid, so partial clusters at the paper / frame edge are expected;
* the **centre cell of every cluster is white paper** — a built-in centroid
  fiducial;
* the eight coloured cells around it carry saturated ink:
  * **vertical mode** — a shade ramp per cluster: deep / dark / deep of one
    hue (purple *or* green), the ramp running along the cluster's short axis;
  * **horizontal mode** — a transparent-**blue** middle band down the cluster's
    long axis, flanked by the cluster's own ink (green *or* purple). So every
    cluster carries blue (the mode signal) and still has a green/purple
    majority (the parity signal). Whether the two flanks may differ
    (green | blue | purple in one cluster) is a print question to settle on
    paper; the detector only needs "blue present, one dominant ink family".
* clusters alternate purple-dominant / green-dominant like a chessboard, so
  the existing parity gate still has a signal.

One **cluster = one lattice site = one printed `[col,row]`**, exactly like the
combined target's 3-part fiducials (not one-block-per-cell). The complete
coordinate counts are unchanged: **7×6 vertical, 3×10 horizontal** (30 cells
— not 3×11/33; that was a stale carry-over from before the horizontal grid
dropped to 10 rows, see `config/rig.json` and
`vision/color_grid.py:304`'s "No +1" comment).

## Why a new module, not an edit of `color_grid.py`

`color_grid.py` is built around "isolated coloured blob per cell, one uniform
pitch, hue+saturation+Lab segmentation." The new sheet's geometry signal is a
black line lattice and its colour is only used for parity / orientation / mode
cross-check. That is a different pipeline, so it lives in
`python/vision/cluster_grid.py` and the green/magenta detector stays exactly
as it is. `color_grid.detect_color_grids` remains the wired default in every
feed; `cluster_grid.detect_cluster_grids` is opt-in until a real capture
proves it, then the feeds switch by config.

## Requirements

Numbered so a review can point at one.

* **C1 — Find the black lattice by edge detection.** Grayscale →
  `cv2.adaptiveThreshold` (inverted) so the printed borders become the
  foreground → morphological close → `cv2.findContours`. A cluster border is a
  4-vertex convex quad whose `contourArea / minAreaRect area` is near 1 and
  whose size is near the median. Colour is never used to establish geometry.

* **C2 — Fit one homography from cluster centres.** Integer lattice `(i,j)` →
  cluster-centre pixels, `cv2.findHomography(..., RANSAC)`, re-score, refit on
  the survivors. Mean residual must stay ≤ `MAX_MEAN_RESIDUAL_SHORT_SIDE` of a
  cluster's short side (same gate constant family as `color_grid.py`).

* **C3 — Whole clusters only, with a tolerance %.** A cluster counts only if
  `observed border area / homography-predicted area` is within
  `[FILL_TOLERANCE, MAX_FILL]` (default `0.80 .. 1.35`, the `color_grid.py`
  values) **and** it keeps `EDGE_MARGIN` (default 0.5 of its own size) of
  clear space from the frame border. Partial clusters contribute nothing — not
  to the fit, not to numbering, not to coverage. A frame that cannot supply a
  full mode-sized window is refused, never approximated (spec R2).

* **C4 — `[0,0]` is the bottom-left cluster of the selected window.** Both
  indices increase away from it. Columns follow the machine's short (X) side in
  vertical mode and its long side in horizontal mode — decided by
  `spec.short_is_x`, never by image direction. Reuse
  `color_grid._window_transform`.

* **C5 — Every strongly supported mode-sized window is returned.** Swept on
  both axes, ≥ 95 % cluster coverage, ordered bottom-left-first, capped at
  `MAX_WINDOWS` (16). Reuse the `color_grid._choose_windows` logic.

* **C6 — Mode is an explicit input and is cross-checked.** `vertical` expects
  a low-hue-variance shade ramp inside each cluster; `horizontal` expects
  three distinct hues including blue. A sheet whose clusters disagree with the
  requested mode raises `ColorGridError(stage="orientation")`, mirroring
  `combined_grid.py`. Cell counts cross-check the active `MachineGrid` (D18).

* **C7 — Same output contract as `color_grid.py`.** Return
  `tuple[ColorGridCalibration, ...]`; every found cluster becomes a
  `PrintedCell` (`color="green"|"magenta"`, `fill`, `full`, `cell`,
  `edge_clipped`). `combined_grid`, `color_grid_overlay`, `grid_evidence`,
  `gridded_camera_feed`, `rig_build_v1` then work unchanged — they only read
  `.spec`, `.homography`, `.found_cells`, `.metrics`, `.cell_quad()`,
  `.workspace_corners()`.

* **C8 — Never fail silently.** A failed detection still carries its candidate
  quads and the failing `stage` on the `ColorGridError` for the overlay to
  draw (spec R10).

* **C9 — Survive the camera colour cast.** White-balance the frame with
  `color_grid.white_balance` before the colour sampling in C6. The edge stage
  (C1) is on luminance and is cast-independent by construction.

## Deferred

* Real-capture tuning of every `TUNE-WITH-CAPTURE` constant (adaptive-threshold
  block size / C, close kernel, quad-area band, hue centres for blue vs
  purple, ramp-variance thresholds).
* ~~Wiring `cluster_grid` into `gridded_camera_feed` / `rig_build_v1` /
  `console_pipeline` as the selected detector~~ — **partly done already,
  ahead of this list.** `gridded_camera_feed.py` has a `_PAPER_DETECTORS`
  registry (`{"color": ..., "cluster": (detect_cluster_grids,
  detect_cluster_grid)}`) with `set_paper_detector()`, and
  `rig_build_v1.py` exposes `--paper-detector {color,cluster}` on the CLI
  (default stays `color`). Still unwired: `console_pipeline.py` and
  `camera/color_grid_check.py`.
* Evidence pooling is inherited for free (`PaperGridEvidence.add` takes any
  `ColorGridCalibration`); its gates are not re-tuned here.
* The printed artwork / SVG generator for the new sheet.
* Combined single-page version of the cluster sheet.

## Verification

Synthetic, runs on the desk:

```
cd python
../.venv/bin/python tests/test_cluster_grid.py
```

Covers both modes, a tilted sheet, three colour casts, partial-cluster
rejection right at the tolerance boundary, chessboard parity, wrong-mode
refusal, and the edge stage in isolation.

On the Pi, once the sheet is printed:

```
cd python
../.venv/bin/python camera/color_grid_check.py   # after the one-line detector swap
```

Expect a sub-2-px mean residual and all 42 (vertical) / 30 (horizontal)
clusters in the selected window, matching spec R1.

#!/usr/bin/env python3
"""Checks for vision/block_grid.py, the placed-block calibrator.

Run from python/:  ../.venv/bin/python tests/test_block_grid.py

Every frame here is synthesised, so the geometry the test asserts against is
known exactly rather than eyeballed. The one real capture is used for what it
can actually prove: that the detector finds the blocks that are in it.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.grid import MachineGrid                                    # noqa: E402
from vision.color_grid import ColorGridError                        # noqa: E402
from vision.color_grid import ColorGridError                        # noqa: E402
from vision.block_grid import (                                     # noqa: E402
    DEFAULT_OBSERVATIONS,
    block_workspace_map,
    MIN_OBSERVATIONS,
    BlockGridError,
    BlockGridSession,
    BlockObservation,
    BlockSighting,
    fit_block_grid,
    locate_block,
    plan_calibration_cells,
    spec_for_grid,
)

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"ok    {name}")
    else:
        print(f"FAIL  {name}{': ' + detail if detail else ''}")
        failures.append(name)


def expect_error(name, fn, needle=""):
    try:
        fn()
    except ColorGridError as exc:
        if needle and needle.lower() not in str(exc).lower():
            print(f"FAIL  {name}: wrong message {str(exc)[:90]!r}")
            failures.append(name)
        else:
            print(f"ok    {name}")
        return
    except Exception as exc:                                # noqa: BLE001
        print(f"FAIL  {name}: {type(exc).__name__} {str(exc)[:70]}")
        failures.append(name)
        return
    print(f"FAIL  {name}: no error raised")
    failures.append(name)


VERTICAL = MachineGrid.from_config(mode="vertical")
HORIZONTAL = MachineGrid.from_config(mode="horizontal")

# --------------------------------------------------------------------------- #
# a synthetic rig view, with a known ground-truth homography
# --------------------------------------------------------------------------- #

SIZE = (900, 700)          # width, height
TABLE = (232, 226, 220)    # pale BGR work surface
WOOD = (120, 170, 205)     # warm block: red highest, then green, then blue


def truth_homography(grid, *, tilt=0.0, perspective=0.0):
    """Map [col,row] to pixels: scale, centre, optional tilt and perspective."""
    pitch_x, pitch_y = grid.pitch_x_cm, grid.pitch_y_cm
    span_x = max((grid.cols - 1) * pitch_x, 1.0)
    span_y = max((grid.rows - 1) * pitch_y, 1.0)
    # A rotated lattice needs a bigger box than its own width and height, so
    # size the render against the rotated extent. Without this a 12-degree tilt
    # pushes the corner blocks off the frame, and locate_block rightly refuses
    # a clipped block rather than measuring a centre that is not its centre.
    theta = math.radians(tilt)
    reach_x = span_x * abs(math.cos(theta)) + span_y * abs(math.sin(theta))
    reach_y = span_x * abs(math.sin(theta)) + span_y * abs(math.cos(theta))
    scale = min(SIZE[0] * 0.72 / reach_x, SIZE[1] * 0.72 / reach_y)
    rotate = np.array([[math.cos(theta), -math.sin(theta), 0.0],
                       [math.sin(theta), math.cos(theta), 0.0],
                       [0.0, 0.0, 1.0]])
    # cell -> cm -> pixels, y down, centred
    to_cm = np.array([[pitch_x, 0.0, 0.0],
                      [0.0, pitch_y, 0.0],
                      [0.0, 0.0, 1.0]])
    to_px = np.array([[scale, 0.0, SIZE[0] / 2 - scale * span_x / 2],
                      [0.0, -scale, SIZE[1] / 2 + scale * span_y / 2],
                      [0.0, 0.0, 1.0]])
    # A gentle keystone: w = 1 + a*x + b*y in PIXELS, so the coefficients are
    # per-pixel and must be tiny. perspective=20 tilts the far edge by ~15%.
    warp = np.array([[1.0, 0.0, 0.0],
                     [0.0, 1.0, 0.0],
                     [perspective * 1e-5, perspective * 1e-5, 1.0]])
    return warp @ to_px @ rotate @ to_cm, scale


def project(matrix, cell):
    out = matrix @ np.array([float(cell[0]), float(cell[1]), 1.0])
    return float(out[0] / out[2]), float(out[1] / out[2])


def render(grid, matrix, scale, cells, *, noise=0, jitter_cm=0.0, seed=0):
    """Draw a table with a wooden block on each of ``cells``."""
    rng = np.random.default_rng(seed)
    frame = np.full((SIZE[1], SIZE[0], 3), TABLE, np.uint8)
    for cell in cells:
        col, row = cell
        offset = ((rng.normal(0, jitter_cm) / grid.pitch_x_cm,
                   rng.normal(0, jitter_cm) / grid.pitch_y_cm)
                  if jitter_cm else (0.0, 0.0))
        here = (col + offset[0], row + offset[1])
        half_x = grid.block_x_cm / grid.pitch_x_cm / 2
        half_y = grid.block_y_cm / grid.pitch_y_cm / 2
        corners = np.array([
            project(matrix, (here[0] - half_x, here[1] - half_y)),
            project(matrix, (here[0] + half_x, here[1] - half_y)),
            project(matrix, (here[0] + half_x, here[1] + half_y)),
            project(matrix, (here[0] - half_x, here[1] + half_y)),
        ], dtype=np.float32)
        cv2.fillConvexPoly(frame, corners.round().astype(np.int32), WOOD,
                           cv2.LINE_AA)
    if noise:
        frame = np.clip(frame.astype(np.int16)
                        + rng.normal(0, noise, frame.shape), 0, 255).astype(np.uint8)
    return frame


def run_session(grid, *, cells=None, tilt=0.0, perspective=0.0, noise=0,
                jitter_cm=0.0, seed=0):
    """Place blocks one at a time exactly as the rig would, and observe each."""
    matrix, scale = truth_homography(grid, tilt=tilt, perspective=perspective)
    plan = cells or plan_calibration_cells(grid, DEFAULT_OBSERVATIONS)
    session = BlockGridSession(grid, cells=plan)
    session.set_baseline(render(grid, matrix, scale, [], noise=noise, seed=seed))
    placed = []
    for cell in plan:
        placed.append(cell)
        frame = render(grid, matrix, scale, placed, noise=noise,
                       jitter_cm=jitter_cm, seed=seed)
        session.observe(cell, frame)
    return session, matrix, scale


# --------------------------------------------------------------------------- #
# 1. planning
# --------------------------------------------------------------------------- #

for grid in (VERTICAL, HORIZONTAL):
    plan = plan_calibration_cells(grid, DEFAULT_OBSERVATIONS)
    check(f"{grid.mode}: plan has the requested count",
          len(plan) == DEFAULT_OBSERVATIONS, str(len(plan)))
    check(f"{grid.mode}: plan has no duplicates", len(set(plan)) == len(plan))
    check(f"{grid.mode}: plan never uses the feeder", (0, 0) not in plan)
    check(f"{grid.mode}: plan is all buildable",
          all(grid.contains_build_target(*cell) for cell in plan))
    cols = {cell[0] for cell in plan}
    rows = {cell[1] for cell in plan}
    check(f"{grid.mode}: plan spans both axes",
          max(cols) - min(cols) >= 1 and max(rows) - min(rows) >= 1,
          f"cols {sorted(cols)} rows {sorted(rows)}")
    # Farthest-point sampling must take the extremes first, so a run cut short
    # after four placements is still the best-conditioned four available.
    corners = {(0, grid.rows - 1), (grid.cols - 1, 0), (grid.cols - 1, grid.rows - 1)}
    check(f"{grid.mode}: plan opens with the four extreme cells",
          corners <= set(plan[:4]), str(plan[:4]))

expect_error("planning below the checkable floor rejects",
             lambda: plan_calibration_cells(VERTICAL, 3), "at least")

# --------------------------------------------------------------------------- #
# 2. the fit recovers a known homography
# --------------------------------------------------------------------------- #

for grid in (VERTICAL, HORIZONTAL):
    session, matrix, scale = run_session(grid)
    check(f"{grid.mode}: every planned block was observed",
          len(session.observations) == DEFAULT_OBSERVATIONS,
          str(sorted(session.observations)))
    calibration = session.calibration()
    report = calibration.block_report

    # The fit is compared against ground truth at cells it never saw, which is
    # the only test that distinguishes a homography from a lookup table.
    unseen = [cell for cell in
              ((c, r) for r in range(grid.rows) for c in range(grid.cols))
              if cell not in session.observations]
    worst = max(
        math.dist(calibration.point_at(*cell), project(matrix, cell))
        for cell in unseen)
    check(f"{grid.mode}: unobserved cells land within 2 px of truth",
          worst < 2.0, f"{worst:.2f} px over {len(unseen)} cells")
    check(f"{grid.mode}: residual is sub-pixel",
          report.mean_residual_px < 1.0, f"{report.mean_residual_px:.3f}")
    check(f"{grid.mode}: footprint agrees with the prediction",
          0.85 <= report.size_agreement <= 1.15, f"{report.size_agreement:.3f}")
    check(f"{grid.mode}: bearings agree with the mode",
          report.max_bearing_error_deg < 5.0,
          f"{report.max_bearing_error_deg:.1f} deg")
    check(f"{grid.mode}: status reports ready", session.status().ready,
          session.status().describe())

# --------------------------------------------------------------------------- #
# 3. it survives tilt, perspective and sensor noise
# --------------------------------------------------------------------------- #

for label, kwargs in (("tilted 12 deg", {"tilt": 12.0}),
                      ("perspective", {"perspective": 26.0}),
                      ("noisy", {"noise": 4}),
                      ("tilted + perspective + noise",
                       {"tilt": -9.0, "perspective": 18.0, "noise": 3})):
    session, matrix, _scale = run_session(VERTICAL, **kwargs)
    calibration = session.calibration()
    unseen = [(c, r) for r in range(VERTICAL.rows) for c in range(VERTICAL.cols)
              if (c, r) not in session.observations]
    worst = max(math.dist(calibration.point_at(*cell), project(matrix, cell))
                for cell in unseen)
    check(f"{label}: unobserved cells stay within 2 px",
          worst < 2.0, f"{worst:.2f} px")

# --------------------------------------------------------------------------- #
# 4. the safety gates
# --------------------------------------------------------------------------- #

spec = spec_for_grid(VERTICAL)


def sighting_at(matrix, cell, grid, *, offset=(0.0, 0.0), scale_short=1.0,
                angle_delta=0.0):
    """A synthetic sighting consistent with ``matrix`` unless told otherwise."""
    cx, cy = project(matrix, cell)
    half_x = grid.block_x_cm / grid.pitch_x_cm / 2
    half_y = grid.block_y_cm / grid.pitch_y_cm / 2
    left = project(matrix, (cell[0] - half_x, cell[1]))
    right = project(matrix, (cell[0] + half_x, cell[1]))
    low = project(matrix, (cell[0], cell[1] - half_y))
    high = project(matrix, (cell[0], cell[1] + half_y))
    # scale_short deliberately shrinks the SHORT side, whichever axis that is
    # in this mode - it exists to test the footprint gate, not to swap axes.
    short_is_x = grid.block_x_cm < grid.block_y_cm
    block_x = math.dist(left, right) * (scale_short if short_is_x else 1.0)
    block_y = math.dist(low, high) * (1.0 if short_is_x else scale_short)
    long_len, short_len = max(block_x, block_y), min(block_x, block_y)
    # The long axis is Y in vertical mode and X in horizontal, so the bearing
    # has to follow the mode rather than always reading off the row direction.
    head, tail = ((high, low) if grid.block_y_cm >= grid.block_x_cm
                  else (right, left))
    bearing = math.degrees(math.atan2(head[1] - tail[1], head[0] - tail[0]))
    return BlockSighting(
        center=(cx + offset[0], cy + offset[1]),
        quad=np.array([[cx - short_len / 2, cy - long_len / 2],
                       [cx + short_len / 2, cy - long_len / 2],
                       [cx + short_len / 2, cy + long_len / 2],
                       [cx - short_len / 2, cy + long_len / 2]], np.float32),
        long_len=long_len, short_len=short_len,
        angle=bearing + angle_delta,
        area=long_len * short_len, rectangularity=0.97, source="synthetic")


truth, _scale = truth_homography(VERTICAL)
good_cells = plan_calibration_cells(VERTICAL, DEFAULT_OBSERVATIONS)


clean = [BlockObservation(cell=cell, sighting=sighting_at(truth, cell, VERTICAL))
         for cell in good_cells]
check("a clean set fits", fit_block_grid(clean, spec).block_report.observations
      == DEFAULT_OBSERVATIONS)

expect_error(
    "four placements are refused as unprovable",
    lambda: fit_block_grid(clean[:4], spec), "at least")

collinear = [BlockObservation(cell=(col, 3),
                              sighting=sighting_at(truth, (col, 3), VERTICAL))
             for col in range(1, 7)]
expect_error("a single row is refused", lambda: fit_block_grid(collinear, spec),
             "axes")

duplicate = clean + [clean[0]]
expect_error("a repeated cell is refused",
             lambda: fit_block_grid(duplicate, spec), "twice")

# One block on the wrong cell: everything else agrees, so the residual spikes.
displaced = list(clean)
_pitch = math.dist(project(truth, (0, 0)), project(truth, (1, 0)))
displaced[2] = BlockObservation(
    cell=displaced[2].cell,
    sighting=sighting_at(truth, displaced[2].cell, VERTICAL,
                         offset=(_pitch * 0.9, 0.0)))
expect_error("a block on the wrong cell is refused",
             lambda: fit_block_grid(displaced, spec), "residual")

# A detection that is the right shape but the wrong scale everywhere: the
# footprint check is the only thing that can catch this, since a uniformly
# wrong block size leaves every residual at zero.
narrow = [BlockObservation(cell=cell,
                           sighting=sighting_at(truth, cell, VERTICAL,
                                                scale_short=0.35))
          for cell in good_cells]
expect_error("a uniformly wrong footprint is refused",
             lambda: fit_block_grid(narrow, spec), "footprint")

turned = [BlockObservation(cell=cell,
                           sighting=sighting_at(truth, cell, VERTICAL,
                                                angle_delta=42.0))
          for cell in good_cells]
expect_error("blocks lying the wrong way are refused",
             lambda: fit_block_grid(turned, spec), "orientation")

# strict=False is the diagnostic escape hatch and must NOT refuse.
loose = fit_block_grid(displaced, spec, strict=False)
check("strict=False returns the refused fit for display",
      loose.block_report.max_residual_px > 1.0,
      f"{loose.block_report.max_residual_px:.1f}")

# --------------------------------------------------------------------------- #
# 5. the workspace map, and agreement with the printed-sheet convention
# --------------------------------------------------------------------------- #

session, matrix, _scale = run_session(VERTICAL)
workspace = session.workspace_map(SIZE)
check("the workspace map carries the mode", workspace.mode == "vertical")
check("the workspace map carries the machine counts",
      (workspace.cols, workspace.rows) == (VERTICAL.cols, VERTICAL.rows))
check("workspace corners are normalised inside the frame",
      all(0.0 <= value <= 1.0 for point in workspace.corners for value in point),
      str(workspace.corners))

# The home corner of the envelope must land where the machine says cell [0,0]
# is: its centre. That is the one claim the whole calibration exists to make.
home_px = tuple(np.asarray(workspace.corners[0])
                * np.array([SIZE[0], SIZE[1]]))
cell00 = project(matrix, (0, 0))
check("the envelope's home corner sits on cell [0,0]'s centre",
      math.dist(home_px, cell00) < 2.0,
      f"{math.dist(home_px, cell00):.2f} px")

# A calibration fitted for one mode must refuse to describe the other.
expect_error("a vertical fit refuses the horizontal machine grid",
             lambda: session.calibration().workspace_corners(HORIZONTAL),
             "cannot calibrate")

# --------------------------------------------------------------------------- #
# 6. observation-time refusals
# --------------------------------------------------------------------------- #

empty = BlockGridSession(VERTICAL)
blank = np.full((SIZE[1], SIZE[0], 3), TABLE, np.uint8)
empty.set_baseline(blank)
expect_error("an empty capture is refused",
             lambda: empty.observe(empty.planned[0], blank.copy()), "no block")

expect_error("a non-buildable cell is refused",
             lambda: empty.observe((0, 0), blank.copy()), "buildable")

# A block the frame cuts off segments perfectly well; its centre is simply not
# its centre. Refusing it is the whole reason EDGE_MARGIN_FRACTION exists.
clipped_matrix, clipped_scale = truth_homography(VERTICAL)
edge_cell = (3, 5)
# Slide the lattice until this cell's block hangs off the top of the frame by
# about a third of its length - which is what a camera framed tightly to the
# envelope does to a block that legitimately overhangs the travel limit.
_edge_y = project(clipped_matrix, edge_cell)[1]
_block_px = clipped_scale * VERTICAL.block_y_cm
shifted = np.array([[1.0, 0.0, 0.0],
                    [0.0, 1.0, -(_edge_y - _block_px * 0.15)],
                    [0.0, 0.0, 1.0]]) @ clipped_matrix
edge_frame = render(VERTICAL, shifted, clipped_scale, [edge_cell])
edge_session = BlockGridSession(VERTICAL, cells=[edge_cell] + list(good_cells[:5]))
edge_session.set_baseline(render(VERTICAL, shifted, clipped_scale, []))
expect_error("a block clipped by the frame edge is refused",
             lambda: edge_session.observe(edge_cell, edge_frame), "cut off")
check("edge_margin=0 still returns the clipped block for diagnostics",
      locate_block(edge_frame,
                   baseline=render(VERTICAL, shifted, clipped_scale, []),
                   edge_margin=0.0) is not None)

# An inset plan is the way out: the same run, on cells the camera sees whole.
inset_plan = plan_calibration_cells(VERTICAL, DEFAULT_OBSERVATIONS, inset=1)
check("an inset plan avoids the outermost ring",
      all(1 <= col <= VERTICAL.cols - 2 and 1 <= row <= VERTICAL.rows - 2
          for col, row in inset_plan), str(inset_plan))
# Horizontal is only 3 columns wide, so the inset must not collapse that axis.
narrow_plan = plan_calibration_cells(HORIZONTAL, DEFAULT_OBSERVATIONS, inset=1)
check("an inset plan keeps a narrow axis usable",
      len({cell[0] for cell in narrow_plan}) > 1
      and max(cell[0] for cell in narrow_plan)
      - min(cell[0] for cell in narrow_plan) >= 1, str(narrow_plan))
check("an inset plan still spans both axes",
      len({cell[0] for cell in inset_plan}) > 1
      and len({cell[1] for cell in inset_plan}) > 1, str(inset_plan))

# Once the run can predict, a block placed on a cell it was not told about is
# caught by the prediction tolerance rather than silently accepted.
session, matrix, scale = run_session(VERTICAL)
spare = [(col, row)
         for row in range(VERTICAL.rows) for col in range(VERTICAL.cols)
         if VERTICAL.contains_build_target(col, row)
         and (col, row) not in session.observations]
next_cell = spare[0]
wrong_cell = next(cell for cell in spare[1:]
                  if math.dist(project(matrix, cell),
                               project(matrix, next_cell)) > scale)
frame = render(VERTICAL, matrix, scale,
               list(session.observations) + [wrong_cell])
expect_error("a placement that landed on the wrong cell is refused",
             lambda: session.observe(next_cell, frame), "wrong cell")

# --------------------------------------------------------------------------- #
# 7. the real capture: three blocks, found by the enhanced detector
# --------------------------------------------------------------------------- #

captures = Path(__file__).resolve().parents[1] / "captures"
real = next(iter(sorted(captures.glob("*corrected*.png"))), None)
if real is None:
    check("real capture present", False, "no corrected capture in captures/")
else:
    image = cv2.imread(str(real))
    found = locate_block(image, expected_size=(59.0, 19.0))
    check("the real capture yields a block-shaped sighting",
          2.0 <= found.aspect <= 4.5 and 12 <= found.short_len <= 30,
          f"{found.long_len:.0f}x{found.short_len:.0f} aspect {found.aspect:.2f}")
    # Differencing against a copy with one block painted out must find that
    # block and nothing else - the property the whole observe() step rests on.
    painted = image.copy()
    cv2.rectangle(painted, (250, 400), (292, 470), (232, 226, 226), -1)
    moved = locate_block(image, baseline=painted, expected_size=(59.0, 19.0))
    check("differencing isolates the block that appeared",
          math.dist(moved.center, (270.0, 434.0)) < 12.0,
          f"found at {moved.center[0]:.0f},{moved.center[1]:.0f}")



# --------------------------------------------------------------------------- #
# 8. dense mode: measure the real lattice, then fill what was never placed
# --------------------------------------------------------------------------- #
#
# The vertical grid has 41 buildable cells and the block supply is smaller than
# that, so the interesting case is "most of the grid placed, the rest filled
# in". These checks care about two things the plain homography cannot do:
# reporting the pitch the machine actually achieved, and refusing to buy a
# richer model than the data supports.

from vision.block_grid import (                                     # noqa: E402
    DENSE_MODES,
    MIN_DENSE_OBSERVATIONS,
    analyse_dense_lattice,
    choose_lattice_model,
    measure_pitch,
)


def dense_observations(grid, matrix, cells, *, curvature=(0.0, 0.0), jitter=0.0,
                       seed=1):
    """Labelled sightings straight from a known model - no rendering involved."""
    rng = np.random.default_rng(seed)
    made = []
    for col, row in cells:
        a, b = curvature
        bent = (col + a * col * col, row + b * row * row)
        sighting = sighting_at(matrix, bent, grid)
        if jitter:
            sighting = BlockSighting(
                center=(sighting.center[0] + rng.normal(0, jitter),
                        sighting.center[1] + rng.normal(0, jitter)),
                quad=sighting.quad, long_len=sighting.long_len,
                short_len=sighting.short_len, angle=sighting.angle,
                area=sighting.area, rectangularity=sighting.rectangularity,
                source=sighting.source)
        made.append(BlockObservation(cell=(col, row), sighting=sighting))
    return made


# 25 of the 41 buildable vertical cells: rows 0-3 complete, minus the feeder.
buildable = [(col, row) for row in range(VERTICAL.rows)
             for col in range(VERTICAL.cols)
             if VERTICAL.contains_build_target(col, row)]
supply = buildable[:25]
dense_truth, dense_scale = truth_homography(VERTICAL)

flat = dense_observations(VERTICAL, dense_truth, supply)
check("the dense floor is 25 placements", MIN_DENSE_OBSERVATIONS == 25)
check("dense mode is vertical only", DENSE_MODES == ("vertical",))

# --- the measurement the request was actually about ---------------------
px = measure_pitch(flat, spec, "x")
py = measure_pitch(flat, spec, "y")
check("the X pitch is measured from adjacent pairs only",
      px is not None and px.pairs >= 15, str(px and px.pairs))
expected_px_per_cm = dense_scale
check("the measured X pitch recovers the real px/cm",
      abs(px.px_per_cm - expected_px_per_cm) / expected_px_per_cm < 0.02,
      f"{px.px_per_cm:.2f} vs {expected_px_per_cm:.2f} px/cm")
check("the measured Y pitch recovers the real px/cm",
      abs(py.px_per_cm - expected_px_per_cm) / expected_px_per_cm < 0.02,
      f"{py.px_per_cm:.2f} vs {expected_px_per_cm:.2f} px/cm")
check("a uniform lattice reports a near-zero pitch spread",
      px.spread < 0.01 and py.spread < 0.01,
      f"x {px.spread:.3f} y {py.spread:.3f}")
check("the X pitch is reported per row", len(px.by_index) > 1, str(px.by_index))
check("the Y pitch is reported per column", len(py.by_index) > 1, str(py.by_index))

# --- model selection must not buy freedom it does not need --------------
best, candidates = choose_lattice_model(flat)
check("all four candidates are fitted", len(candidates) == 4, str(len(candidates)))
check("a clean affine lattice does not buy curvature",
      best.name != "homography+curvature", best.describe())

noisy = dense_observations(VERTICAL, dense_truth, supply, jitter=0.6, seed=7)
noisy_best, _ = choose_lattice_model(noisy)
check("noise alone does not buy curvature either",
      noisy_best.name != "homography+curvature", noisy_best.describe())

# A machine whose advance per cell drifts along its travel: the one thing a
# homography genuinely cannot absorb, so the extra parameter must be bought.
CURVE = (0.006, 0.004)
curved = dense_observations(VERTICAL, dense_truth, supply, curvature=CURVE,
                            jitter=0.15, seed=3)
curved_best, curved_all = choose_lattice_model(curved)
check("real travel curvature IS bought", curved_best.name == "homography+curvature",
      "; ".join(fit.describe() for fit in curved_all))
# The coefficient is only recovered approximately, and that is expected rather
# than a defect: a quadratic bend in lattice space is partly degenerate with a
# homography's own perspective terms, so the two share the work. What has to be
# true is that the fit lands on the right sign and order of magnitude, and -
# below - that it PREDICTS unseen cells better than a straight homography.
# Prediction is the claim the model exists to make; the parameter is not.
check("the fitted curvature has the right sign and scale",
      all(0.25 <= fitted / real <= 1.75 for fitted, real
          in zip(curved_best.curvature, CURVE)),
      f"{curved_best.curvature} vs {CURVE}")
check("held-out error beats the plain homography on curved data",
      curved_best.loo_residual_px
      < min(fit.loo_residual_px for fit in curved_all
            if fit.name == "homography"),
      "; ".join(fit.describe() for fit in curved_all))

# --- the fill ------------------------------------------------------------
filled = fit_block_grid(flat, spec, image_size=SIZE)
report = filled.block_report
check("the dense report is attached", report.dense is not None)
check("every unplaced cell is filled virtually",
      report.dense.virtual_cells == spec.cols * spec.rows - len(supply),
      f"{report.dense.virtual_cells} filled, "
      f"{spec.cols * spec.rows - len(supply)} expected")
check("found_cells still counts only what was placed",
      len(filled.found_cells) == len(supply), str(len(filled.found_cells)))
check("virtual cells are flagged, never full",
      all(not cell.full and cell.area == 0.0
          for cell in filled.virtual_cells.values()),
      str(len(filled.virtual_cells)))
check("observed and virtual together cover the whole grid",
      len(filled.found_cells) + len(filled.virtual_cells)
      == spec.cols * spec.rows)

# The filled cells have to land where the blocks WOULD have gone, which is the
# only claim that matters. Checked against ground truth, not against the fit.
worst_virtual = max(
    math.dist(filled.cell_center(col, row), project(dense_truth, (col, row)))
    for col, row in filled.virtual_cells)
check("virtual cells land within 2 px of where a block would go",
      worst_virtual < 2.0, f"{worst_virtual:.2f} px")

# ...including on a curved machine, where they are extrapolated through the
# curve rather than a straight homography.
curved_fit = fit_block_grid(curved, spec, image_size=SIZE)
check("a curved fit keeps its curvature", any(curved_fit.curvature),
      str(curved_fit.curvature))
worst_curved = max(
    math.dist(curved_fit.cell_center(col, row),
              project(dense_truth,
                      (col + CURVE[0] * col * col, row + CURVE[1] * row * row)))
    for col, row in curved_fit.virtual_cells)
check("virtual cells follow the machine's curve too",
      worst_curved < 2.5, f"{worst_curved:.2f} px")
straight = fit_block_grid(curved, spec, image_size=SIZE, dense=False)
worst_straight = max(
    math.dist(straight.cell_center(col, row),
              project(dense_truth,
                      (col + CURVE[0] * col * col, row + CURVE[1] * row * row)))
    for col, row in straight.virtual_cells)
check("and they beat what a plain homography would have extrapolated",
      worst_curved < worst_straight * 0.6,
      f"curved {worst_curved:.2f} px vs straight {worst_straight:.2f} px")

# grid_at must invert point_at exactly, curve and all, or cell_at lies.
for cell in ((0, 0), (6, 5), (3, 2)):
    back = curved_fit.grid_at(curved_fit.cell_center(*cell))
    check(f"grid_at inverts point_at at {cell}",
          math.dist(back, cell) < 1e-6, f"{back}")

# --- the guards ----------------------------------------------------------
expect_error("dense analysis refuses too few placements",
             lambda: analyse_dense_lattice(flat[:20], spec), "at least 25")
h_truth, _h_scale = truth_homography(HORIZONTAL)
h_spec = spec_for_grid(HORIZONTAL)
horizontal_dense = dense_observations(
    HORIZONTAL, h_truth,
    [(col, row) for row in range(HORIZONTAL.rows) for col in range(HORIZONTAL.cols)
     if HORIZONTAL.contains_build_target(col, row)][:25])
horizontal_fit = fit_block_grid(horizontal_dense, h_spec, image_size=SIZE)
check("the horizontal grid does not get dense analysis",
      horizontal_fit.block_report.dense is None)
check("but the horizontal grid is still filled",
      len(horizontal_fit.virtual_cells)
      == h_spec.cols * h_spec.rows - len(horizontal_dense),
      str(len(horizontal_fit.virtual_cells)))

check("fill can be turned off",
      not fit_block_grid(flat, spec, fill=False).virtual_cells)




# --------------------------------------------------------------------------- #
# 9. a whole dense run, through the real detector rather than injected sightings
# --------------------------------------------------------------------------- #
#
# Sections above feed fit_block_grid synthetic sightings, which proves the
# maths but not that a run actually produces them. This places 25 rendered
# blocks one at a time exactly as the rig would, detects each, and then asks
# the fitted lattice where the 17 cells nobody could reach are.

dense_session = BlockGridSession(VERTICAL, supply=25)
check("a supply-sized plan is dense, not spread",
      len(dense_session.planned) == 25
      and dense_session.planned[:3] == ((1, 0), (2, 0), (3, 0)),
      str(dense_session.planned[:4]))
check("the unplaced cells are the far rows",
      {cell[1] for cell in
       ((c, r) for r in range(VERTICAL.rows) for c in range(VERTICAL.cols))
       if cell not in dense_session.planned} >= {4, 5},
      "")

dense_matrix, dense_render_scale = truth_homography(VERTICAL)
dense_session.set_baseline(render(VERTICAL, dense_matrix, dense_render_scale, []))
laid = []
for cell in dense_session.planned:
    laid.append(cell)
    dense_session.observe(
        cell, render(VERTICAL, dense_matrix, dense_render_scale, laid))
check("all 25 rendered blocks were detected and labelled",
      len(dense_session.observations) == 25,
      str(len(dense_session.observations)))

run_fit = dense_session.calibration()
run_report = run_fit.block_report.dense
check("a 25-block run triggers the dense analysis", run_report is not None)
check("the run measured both pitches",
      run_report.pitch_x is not None and run_report.pitch_y is not None)
check("the measured pitch matches the rendered scale",
      abs(run_report.pitch_x.px_per_cm - dense_render_scale)
      / dense_render_scale < 0.03,
      f"{run_report.pitch_x.px_per_cm:.2f} vs {dense_render_scale:.2f}")
check("the run filled every cell it could not place on",
      run_report.virtual_cells == VERTICAL.cols * VERTICAL.rows - 25,
      f"{run_report.virtual_cells}")
worst_run = max(
    math.dist(run_fit.cell_center(col, row), project(dense_matrix, (col, row)))
    for col, row in run_fit.virtual_cells)
check("cells extrapolated past the block supply land within 3 px",
      worst_run < 3.0, f"{worst_run:.2f} px over "
                       f"{len(run_fit.virtual_cells)} cells")
# Extrapolation is the risky half: rows 4 and 5 sit beyond every block placed.
beyond = [(col, row) for col, row in run_fit.virtual_cells if row >= 4]
worst_beyond = max(
    math.dist(run_fit.cell_center(col, row), project(dense_matrix, (col, row)))
    for col, row in beyond)
check("including the rows beyond every block that was placed",
      worst_beyond < 3.0, f"{worst_beyond:.2f} px over {len(beyond)} cells")
check("the run still saves a workspace map",
      dense_session.workspace_map(SIZE) is not None)




# --------------------------------------------------------------------------- #
# 10. the real board: unlabelled blocks in one frame, anchored at [0,0]
# --------------------------------------------------------------------------- #
#
# captures/IMAGE_TO_TEST_BLOCK_CALIBRATION.png is a rig photograph of 29 blocks
# on the vertical grid, laid from the home corner, with the holder's two small
# wooden offcuts sitting beside [0,0]. Nothing in it is labelled, so this
# exercises the whole unlabelled path - detect, reject what is not on the
# lattice, recover the two step vectors, anchor, fit, and fill the 13 cells the
# block supply never reached.

from vision.block_grid import detect_block_lattice                  # noqa: E402

board = Path(__file__).resolve().parents[1] / "captures" / \
    "IMAGE_TO_TEST_BLOCK_CALIBRATION.png"
if not board.exists():
    check("the block-calibration board capture is present", False, str(board))
else:
    board_image = cv2.imread(str(board))
    board_cal, board_diag = detect_block_lattice(
        board_image, VERTICAL, anchor="bottom-left",
        max_processing_width=board_image.shape[1])

    physical = set(board_cal.found_cells)
    virtual = set(board_cal.virtual_cells)
    # Laid from home: columns 0-6 for rows 0-3, plus the single block on [0,4].
    expected_physical = {(col, row) for row in range(4) for col in range(7)}
    expected_physical.add((0, 4))

    check("every block on the board is found and labelled",
          physical == expected_physical,
          f"missing {sorted(expected_physical - physical)}, "
          f"extra {sorted(physical - expected_physical)}")
    check("29 physical blocks", len(physical) == 29, str(len(physical)))
    check("13 cells filled virtually", len(virtual) == 13, str(len(virtual)))
    check("physical and virtual together are the whole 7x6 grid",
          physical | virtual == {(c, r) for r in range(VERTICAL.rows)
                                 for c in range(VERTICAL.cols)}
          and not (physical & virtual))
    # The unplaced cells are the far rows, which is what laying from home does.
    check("the filled cells are the far rows, toward y+",
          all(row >= 4 for _col, row in virtual), str(sorted(virtual)))

    # The holder's offcuts sit right beside [0,0] and are the thing most likely
    # to be taken for a block. Nothing may be assigned to a cell because of them.
    check("the holder offcuts beside [0,0] are not mistaken for blocks",
          len(board_cal.found_cells) == board_diag["assigned"] == 29,
          f"assigned {board_diag['assigned']}, "
          f"off-lattice {board_diag['off_lattice']}, "
          f"collisions {board_diag['collisions']}")

    # Every block snapped cleanly onto its site: this is what says the lattice
    # is the board's own and not one that happens to fit a subset.
    check("every block snaps well inside half a cell",
          board_diag["max_snap_cells"] < 0.20,
          f"{board_diag['max_snap_cells']:.3f} cells")
    report = board_cal.block_report
    check("the fitted residual is sub-pixel on the real board",
          report.mean_residual_px < 1.5, f"{report.mean_residual_px:.2f} px")
    check("the measured footprint matches the fitted lattice",
          0.85 <= report.size_agreement <= 1.25, f"{report.size_agreement:.2f}")
    check("the dense analysis ran on the real board",
          report.dense is not None and report.dense.observations == 29)

    # The measured pitch is the number the request was really about. The two
    # axes are measured against different block sides, so they are allowed to
    # disagree - but each must be self-consistent across the board.
    pitch_x, pitch_y = report.dense.pitch_x, report.dense.pitch_y
    check("the X pitch is consistent across every row",
          pitch_x.spread < 0.05, pitch_x.describe())
    check("the Y pitch is consistent across every column",
          pitch_y.spread < 0.05, pitch_y.describe())
    # This view is genuinely anisotropic - 2.35 px of Y pitch per px of X where
    # the print says 2.00 - so the raw ratio cannot be asserted against the
    # printed one. Nor is "correct it by px_per_cm" a check: px_per_cm is
    # defined as measured/expected, so that only ever agrees with itself. The
    # real test is that the stretch measured from the PITCHES matches the
    # stretch measured from the BLOCK FOOTPRINTS - two different quantities
    # through one lens, which agree only if the gaps in config/rig.json
    # describe this board.
    dense = report.dense
    check("the view is measurably anisotropic, and that is reported",
          dense.anisotropy_pitch > 1.05,
          f"{dense.anisotropy_pitch:.3f}")
    check("pitch-measured and block-measured stretch agree, so the config "
          "gaps match the board",
          0.90 <= dense.anisotropy_agreement <= 1.10,
          f"pitches {dense.anisotropy_pitch:.3f} vs blocks "
          f"{dense.anisotropy_block:.3f} = {dense.anisotropy_agreement:.3f}")

    # The anchor is an assertion, not a measurement, and this is the honest
    # test of that: the occupied 7x5 region fits a 7x6 grid from either end, so
    # "top-right" is refused by nothing - it simply renumbers the whole board.
    # Any bound that DID catch it here would only be catching this particular
    # board's shape. This is the structural weakness of reading a lattice out
    # of one frame, and the reason the rig-placed route stays primary.
    flipped, _ = detect_block_lattice(
        board_image, VERTICAL, anchor="top-right",
        max_processing_width=board_image.shape[1])
    check("a wrong anchor is not detectable, it just renumbers the board",
          set(flipped.found_cells) != physical
          and len(flipped.found_cells) == 29,
          f"{len(flipped.found_cells)} cells")
    # Concretely: the block the correct anchor calls [0,0] is relabelled
    # [6,4] - the diagonally opposite corner of the occupied region - and the
    # picture gives no way to know which of the two readings is the real one.
    check("the wrong anchor relabels [0,0] as the opposite corner",
          math.dist(flipped.cell_center(6, 4),
                    board_cal.cell_center(0, 0)) < 6.0,
          f"{flipped.cell_center(6, 4)} vs {board_cal.cell_center(0, 0)}")
    # Asking the wrong GRID, on the other hand, is caught: the horizontal grid
    # expects a 7.6 cm pitch across and 3.8 along, and no such spacing exists
    # on this board. Which mode is being calibrated is checkable; which corner
    # the blocks were laid from is not.
    expect_error("this board is refused as a horizontal grid",
                 lambda: detect_block_lattice(
                     board_image, HORIZONTAL, anchor="bottom-left",
                     max_processing_width=board_image.shape[1]))

    # And the calibration is saveable: this is a real workspace map, not a
    # diagnostic picture.
    board_map = block_workspace_map(board_cal, VERTICAL,
                                    board_image.shape[1::-1])
    check("the real board yields a saveable workspace map",
          board_map.mode == "vertical"
          and all(0.0 <= v <= 1.0 for p in board_map.corners for v in p),
          str(board_map.corners))




# --------------------------------------------------------------------------- #
# 11. a saved map has to be one the consumers will actually adopt
# --------------------------------------------------------------------------- #
#
# Writing workspace_map.json is not the same as calibrating anything. Every
# consumer re-derives its own `projection` - the lens, orientation and framing
# a map is only valid under - and refuses a map whose projection does not
# match. A map saved WITHOUT one is written successfully and then silently
# ignored by everything, which is the worst possible outcome: it looks like it
# worked. That is a real bug this suite exists to keep fixed.

import tempfile                                                     # noqa: E402
from camera.gridded_camera_feed import (                            # noqa: E402
    load_workspace,
    projection_metadata,
)
from camera.camera_feed import (                                    # noqa: E402
    SETTINGS_PATH,
    framing_roi,
    load_settings,
    profile_from_settings,
)
from vision.block_grid import workspace_map_error                   # noqa: E402

if board.exists():
    settings = load_settings(SETTINGS_PATH)
    projection = projection_metadata(
        profile_from_settings(settings), settings.get("capture") or {},
        True, framing_roi(settings))
    board_size = board_image.shape[1::-1]

    scratch = Path(tempfile.mkdtemp())
    without = block_workspace_map(board_cal, VERTICAL, board_size)
    without.save(scratch / "without.json")
    loaded, reason = load_workspace(scratch / "without.json", VERTICAL, projection)
    check("a map saved with no projection is refused by its consumers",
          loaded is None and "camera" in (reason or ""), str(reason))

    withp = block_workspace_map(board_cal, VERTICAL, board_size,
                                projection=projection)
    withp.save(scratch / "with.json")
    adopted, reason = load_workspace(scratch / "with.json", VERTICAL, projection)
    check("a map saved with the projection IS adopted",
          adopted is not None, str(reason))
    check("the adopted map carries the right grid and mode",
          adopted is not None and adopted.matches_grid(VERTICAL)
          and adopted.mode == "vertical")

    # WorkspaceMap stores four corners plus the grid geometry, not a per-cell
    # table, so a consumer spaces cells evenly between those corners and any
    # curvature the fit bought is flattened on the way out. That loss is real
    # and bounded; the point of measuring it is that a caller can report it
    # instead of implying a save is lossless.
    mean_px, max_px, worst = workspace_map_error(
        board_cal, withp, VERTICAL, board_size)
    check("the round trip through a saved map stays inside a third of a block",
          max_px < 0.33 * board_cal.block_report.dense.pitch_x.px_per_cm
          * VERTICAL.block_x_cm,
          f"{mean_px:.2f} px mean / {max_px:.2f} px max at "
          f"[{worst[0]},{worst[1]}]")
    # The corners are pinned by construction, so the flattening shows up in the
    # middle. Asserting that is what would catch the error moving somewhere
    # a four-corner map cannot explain.
    check("the round-trip error peaks away from the pinned corners",
          worst not in {(0, 0), (VERTICAL.cols - 1, 0),
                        (0, VERTICAL.rows - 1),
                        (VERTICAL.cols - 1, VERTICAL.rows - 1)},
          f"worst at [{worst[0]},{worst[1]}]")


print()
if failures:
    print(f"{len(failures)} failing check(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

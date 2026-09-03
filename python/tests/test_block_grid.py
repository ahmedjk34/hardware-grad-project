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
    block_x = math.dist(left, right) * scale_short
    block_y = math.dist(low, high)
    long_len, short_len = max(block_x, block_y), min(block_x, block_y)
    bearing = math.degrees(math.atan2(high[1] - low[1], high[0] - low[0]))
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

print()
if failures:
    print(f"{len(failures)} failing check(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

#!/usr/bin/env python3
"""The block-vs-cell interval geometry — no camera, no rig, no numpy.

Hand-rolled like ``test_placement_check.py``: a ``check`` helper, PASSED/FAILED
lists, named physical scenarios rather than bare numbers. Every case is built
from hand geometry, which is the point — this is what replaces "the centroid
landed in the gap polygon" as supervision's DISPLACED test, so the split has to
be inspectable without a frame.

The worked example the design was argued from: vertical Y, a 6.0 cm block, 1.6
cm gap, 7.6 cm pitch, planned on the cell whose centre is 3.0 cm from home,
found with its centre at 7.4 cm — 4.4 cm off. Coverages must come out 1.6 / 1.6
/ 2.8 with nothing beyond.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.placement_geometry import (  # noqa: E402
    AxisCoverage, Consistency, axis_coverage, consistency, displacement_cm,
    drift_axis, overlap_1d, residual_cm, span,
)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:64} {detail}")


def near(a, b, tol=1e-6):
    return abs(a - b) < tol


# --- overlap_1d / span: the primitives ------------------------------------- #

check("disjoint intervals overlap by 0", overlap_1d((0.0, 1.0), (2.0, 3.0)) == 0.0)
check("touching intervals overlap by 0", overlap_1d((0.0, 1.0), (1.0, 2.0)) == 0.0)
check("a contained interval overlaps by its own length",
      overlap_1d((0.0, 5.0), (1.0, 3.0)) == 2.0)
check("partial overlap is the shared length", overlap_1d((0.0, 2.0), (1.0, 4.0)) == 1.0)
check("span centres a block on a point", span(3.0, 6.0) == (0.0, 6.0))


# --- axis_coverage: the vertical-Y worked example ------------------------------ #

BLOCK_Y, GAP_Y, PITCH_Y = 6.0, 1.6, 7.6
cov = axis_coverage(observed_centre=7.4, planned_centre=3.0,
                    block_len=BLOCK_Y, gap_len=GAP_Y, pitch=PITCH_Y)
check("a block 4.4 cm off toward the next cell -> displacement +4.4",
      near(cov.displacement, 4.4), f"displacement={cov.displacement:.2f}")
check("  ... drift direction is away from home (+1)", cov.direction == 1)
check("  ... 1.6 cm still over its planned footprint", near(cov.origin, 1.6),
      f"origin={cov.origin:.2f}")
check("  ... 1.6 cm over the gap (the whole gap)", near(cov.gap, 1.6),
      f"gap={cov.gap:.2f}")
check("  ... 2.8 cm over the neighbour footprint", near(cov.neighbour, 2.8),
      f"neighbour={cov.neighbour:.2f}")
check("  ... nothing beyond a single displacement", near(cov.beyond, 0.0),
      f"beyond={cov.beyond:.2f}")
check("  ... the four parts sum to the block length",
      near(cov.origin + cov.gap + cov.neighbour + cov.beyond, BLOCK_Y))
check("  ... on-site fraction is 1.6/6.0", near(cov.on_site_fraction, 1.6 / 6.0))


# --- axis_coverage: a squarely placed block --------------------------------- #

square = axis_coverage(observed_centre=3.0, planned_centre=3.0, block_len=BLOCK_Y,
                       gap_len=GAP_Y, pitch=PITCH_Y)
check("a squarely placed block has zero displacement", near(square.displacement, 0.0))
check("  ... direction is 0 (centred)", square.direction == 0)
check("  ... the whole block is on its footprint", near(square.origin, BLOCK_Y))
check("  ... nothing in the gap or beyond",
      near(square.gap, 0.0) and near(square.beyond, 0.0))


# --- axis_coverage: drifted toward home is split the same way -------------- #

back = axis_coverage(observed_centre=3.0 - 4.4, planned_centre=3.0, block_len=BLOCK_Y,
                     gap_len=GAP_Y, pitch=PITCH_Y)
check("a block 4.4 cm off toward home -> displacement -4.4", near(back.displacement, -4.4))
check("  ... direction is toward home (-1)", back.direction == -1)
check("  ... the same 1.6 / 1.6 / 2.8 split on the home side",
      near(back.origin, 1.6) and near(back.gap, 1.6) and near(back.neighbour, 2.8))


# --- axis_coverage: past the neighbour is flagged as `beyond` -------------- #

BLOCK_X, GAP_X, PITCH_X = 2.2, 1.6, 3.8
far = axis_coverage(observed_centre=1.1 + 4.5, planned_centre=1.1, block_len=BLOCK_X,
                    gap_len=GAP_X, pitch=PITCH_X)
check("a 2.2 cm block shoved 4.5 cm leaves nothing on its own footprint",
      near(far.origin, 0.0), f"origin={far.origin:.2f}")
check("  ... and reaches past the neighbour footprint (beyond > 0)", far.beyond > 0.5,
      f"beyond={far.beyond:.2f}")


# --- displacement_cm / drift_axis ----------------------------------------- #

dx, dy = displacement_cm((9.5, 7.6), (9.1, 7.6))
check("displacement_cm is observed - planned, + away from home",
      near(dx, 0.4) and near(dy, 0.0), f"dx={dx:.2f} dy={dy:.2f}")
cx = axis_coverage(observed_centre=2.4, planned_centre=1.1, block_len=BLOCK_X,
                   gap_len=GAP_X, pitch=PITCH_X)
cy = axis_coverage(observed_centre=3.2, planned_centre=3.0, block_len=BLOCK_Y,
                   gap_len=GAP_Y, pitch=PITCH_Y)
check("drift_axis names the axis carrying the displacement", drift_axis(cx, cy) == "x")

check("residual_cm is the hypot of the displacement vector",
      near(residual_cm((10.1, 7.6), (7.6, 7.6)), 2.5))
check("residual_cm of a squarely placed block is 0", residual_cm((7.6, 7.6), (7.6, 7.6)) == 0.0)
check("residual_cm is a magnitude — direction does not matter",
      near(residual_cm((9.0, 9.0), (6.0, 5.0)), 5.0))


# --- consistency: the three ways a detection is not one straight block ------- #

NOMINAL = (6.0, 2.2)
clean = consistency(cov_x=cx, cov_y=cov, measured_size_cm=(6.0, 2.2),
                    nominal_size_cm=NOMINAL, angle_deg=1.5,
                    size_tolerance_cm=0.6, angle_tolerance_deg=6.0)
check("a nominal, axis-aligned, single-displacement block is consistent", clean.ok,
      clean.reason)

merged = consistency(cov_x=cx, cov_y=cov, measured_size_cm=(9.4, 2.3),
                     nominal_size_cm=NOMINAL, angle_deg=0.0,
                     size_tolerance_cm=0.6, angle_tolerance_deg=6.0)
check("an oversized blob (two blocks) is refused", not merged.ok, merged.reason)

reaches = consistency(cov_x=far, cov_y=square, measured_size_cm=(6.0, 2.2),
                      nominal_size_cm=NOMINAL, angle_deg=0.0,
                      size_tolerance_cm=0.4, angle_tolerance_deg=6.0)
check("a block reaching past its neighbour is refused", not reaches.ok, reaches.reason)

rotated = consistency(cov_x=cx, cov_y=cov, measured_size_cm=(6.0, 2.2),
                      nominal_size_cm=NOMINAL, angle_deg=18.0,
                      size_tolerance_cm=0.6, angle_tolerance_deg=6.0)
check("a rotated block is refused", not rotated.ok, rotated.reason)
check("  ... and the angle-off is reported", near(rotated.angle_off_deg, 18.0))


print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

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
    AxisCoverage, Consistency, NeighbourhoodClearance, axis_coverage,
    consistency, displacement_cm, drift_axis, drift_axes, neighbourhood_clear,
    overlap_1d, residual_cm, span,
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


# --- item 5: drift_axes — how many machine axes carry a real displacement ---- #

TOL = 0.5  # DIAGONAL_AXIS_TOLERANCE_CM


def cx_(disp):
    return axis_coverage(observed_centre=10.0 + disp, planned_centre=10.0,
                         block_len=2.2, gap_len=1.6, pitch=3.8)


def cy_(disp):
    return axis_coverage(observed_centre=10.0 + disp, planned_centre=10.0,
                         block_len=6.0, gap_len=1.6, pitch=7.6)


check("drift_axes: a pure-X drift names only x",
      drift_axes(cx_(0.9), cy_(0.0), axis_tolerance_cm=TOL) == ("x",))
check("drift_axes: a pure-Y drift names only y",
      drift_axes(cx_(0.0), cy_(1.5), axis_tolerance_cm=TOL) == ("y",))
check("drift_axes: a cross component within tolerance is not a second axis",
      drift_axes(cx_(0.9), cy_(0.4), axis_tolerance_cm=TOL) == ("x",))
check("drift_axes: a component exactly at the tolerance is still noise (strict >)",
      drift_axes(cx_(0.9), cy_(0.5), axis_tolerance_cm=TOL) == ("x",))
check("drift_axes: a real two-axis drift names both, larger first",
      drift_axes(cx_(1.2), cy_(0.9), axis_tolerance_cm=TOL) == ("x", "y"))
check("drift_axes: the larger axis leads even when it is y",
      drift_axes(cx_(0.9), cy_(1.5), axis_tolerance_cm=TOL) == ("y", "x"))
check("drift_axes: a tie above tolerance still reports both",
      drift_axes(cx_(0.9), cy_(0.9), axis_tolerance_cm=TOL) == ("x", "y"))
check("drift_axes: within noise on both axes is no drift at all",
      drift_axes(cx_(0.3), cy_(0.3), axis_tolerance_cm=TOL) == ())


# --- item 5: neighbourhood_clear — both neighbours + the corner -------------- #

def occ(*cells):
    s = set(cells)
    return lambda dc, dr: (dc, dr) in s


# A genuine two-axis drift is refused before any occupancy is consulted.
nc = neighbourhood_clear(cov_x=cx_(1.2), cov_y=cy_(1.2), gap_x_cm=1.6, gap_y_cm=1.6,
                         jaw_clearance_cm=0.4, axis_tolerance_cm=TOL, occupied=occ())
check("neighbourhood_clear: an unsupported diagonal is refused", not nc.ok, nc.reason)
check("  ... flagged .diagonal, cites 'diagonal', tells the operator 'by hand'",
      nc.diagonal and "diagonal" in nc.reason and "by hand" in nc.reason)
check("  ... and nothing was inspected — occupancy never mattered", nc.checked == ())

# ... and it stays refused-as-diagonal even with the corner cell occupied:
# occupancy cannot turn an unmeasured diagonal into a measured one.
nc = neighbourhood_clear(cov_x=cx_(1.2), cov_y=cy_(1.2), gap_x_cm=1.6, gap_y_cm=1.6,
                         jaw_clearance_cm=0.4, axis_tolerance_cm=TOL,
                         occupied=occ((1, 1), (1, 0), (0, 1)))
check("neighbourhood_clear: a diagonal with a full corner is STILL 'diagonal', not 'past'",
      not nc.ok and nc.diagonal and "past" not in nc.reason, nc.reason)

# A one-axis drift with an empty neighbourhood clears, and the sweep really did
# look at both cross sides and both corners (cross axis centred -> both signs).
nc = neighbourhood_clear(cov_x=cx_(1.9), cov_y=cy_(0.0), gap_x_cm=1.6, gap_y_cm=1.6,
                         jaw_clearance_cm=0.4, axis_tolerance_cm=TOL, occupied=occ())
check("neighbourhood_clear: a one-axis drift into empty space is clear",
      nc.ok and not nc.diagonal, nc.reason)
check("  ... the sweep inspected the primary neighbour, both cross cells, both corners",
      set(nc.checked) == {(1, 0), (0, 1), (0, -1), (1, 1), (1, -1)})

# The primary neighbour it slid toward, occupied and within a jaw width -> no.
nc = neighbourhood_clear(cov_x=cx_(1.5), cov_y=cy_(0.0), gap_x_cm=1.6, gap_y_cm=1.6,
                         jaw_clearance_cm=0.4, axis_tolerance_cm=TOL,
                         occupied=occ((1, 0)))
check("neighbourhood_clear: a closed gap to an occupied primary neighbour -> refused",
      not nc.ok and "no room for the jaw" in nc.reason, nc.reason)

# Far enough that the block edge is inside the occupied neighbour's footprint.
nc = neighbourhood_clear(cov_x=cx_(1.9), cov_y=cy_(0.0), gap_x_cm=1.6, gap_y_cm=1.6,
                         jaw_clearance_cm=0.4, axis_tolerance_cm=TOL,
                         occupied=occ((1, 0)))
check("neighbourhood_clear: a block overlapping an occupied neighbour -> refused",
      not nc.ok and "overlaps an occupied neighbour" in nc.reason, nc.reason)

# The same primary neighbour occupied but the block only 0.9 cm off -> 0.7 cm of
# gap still open, more than the 0.4 cm jaw -> allowed.
nc = neighbourhood_clear(cov_x=cx_(0.9), cov_y=cy_(0.0), gap_x_cm=1.6, gap_y_cm=1.6,
                         jaw_clearance_cm=0.4, axis_tolerance_cm=TOL,
                         occupied=occ((1, 0)))
check("neighbourhood_clear: 0.7 cm of open gap to an occupied neighbour is enough",
      nc.ok, nc.reason)

# Boundary / edge pick cell: the block drifts toward the grid edge, so every
# offset the sweep asks about is off-grid and reads empty -> cleared, no error.
nc = neighbourhood_clear(cov_x=cx_(-1.9), cov_y=cy_(0.0), gap_x_cm=1.6, gap_y_cm=1.6,
                         jaw_clearance_cm=0.4, axis_tolerance_cm=TOL, occupied=occ())
check("neighbourhood_clear: a drift toward an off-grid edge is handled, not an error",
      nc.ok and (-1, 0) in nc.checked, nc.reason)

# --- item 5: the corner sweep itself, exercised via the future diagonal path - #
# `diagonal_supported=True` is reserved for when the jaw envelope is measured;
# these prove the corner / cross-neighbour logic it will rely on is correct.

DX = 1.3  # closes the X gap to 0.3 cm ( < 0.4 jaw )
DY = 1.3  # closes the Y gap to 0.3 cm

nc = neighbourhood_clear(cov_x=cx_(DX), cov_y=cy_(DY), gap_x_cm=1.6, gap_y_cm=1.6,
                         jaw_clearance_cm=0.4, axis_tolerance_cm=TOL,
                         occupied=occ((1, 1)), diagonal_supported=True)
check("neighbourhood_clear: (supported) both gaps closed + corner occupied -> refused",
      not nc.ok and "diagonally past" in nc.reason, nc.reason)
check("  ... the corner cell was in the inspected set", (1, 1) in nc.checked)

nc = neighbourhood_clear(cov_x=cx_(DX), cov_y=cy_(DY), gap_x_cm=1.6, gap_y_cm=1.6,
                         jaw_clearance_cm=0.4, axis_tolerance_cm=TOL,
                         occupied=occ(), diagonal_supported=True)
check("neighbourhood_clear: (supported) the SAME geometry with an empty corner -> clear",
      nc.ok, nc.reason)

nc = neighbourhood_clear(cov_x=cx_(DX), cov_y=cy_(DY), gap_x_cm=1.6, gap_y_cm=1.6,
                         jaw_clearance_cm=0.4, axis_tolerance_cm=TOL,
                         occupied=occ((0, 1)), diagonal_supported=True)
check("neighbourhood_clear: (supported) a closed gap to an occupied CROSS neighbour -> refused",
      not nc.ok and "other axis" in nc.reason, nc.reason)

check("NeighbourhoodClearance is a frozen record",
      isinstance(nc, NeighbourhoodClearance)
      and getattr(NeighbourhoodClearance, "__dataclass_params__").frozen)


print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

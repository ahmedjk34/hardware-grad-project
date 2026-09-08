#!/usr/bin/env python3
"""The CORRECTION action's pure geometry and policy — no camera, no rig.

Hand-rolled like ``test_supervisor.py``: a ``check`` helper, PASSED/FAILED
lists, named physical scenarios rather than bare numbers. Every case here is
built from hand numbers, which is the point — the decision to drive the claw
into a finished structure has to be inspectable without a rig.

Sign discipline (AGENTS.md Rule 0 / 0a) is asserted explicitly: ``dx`` / ``dy``
are magnitudes from each home switch, ``+`` away from home, and a block seen
farther from home than its cell yields a POSITIVE offset.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.grid import MachineGrid  # noqa: E402
from rig.placement_check import (  # noqa: E402
    ANGLE_TOLERANCE_DEG, CORRECT_BAND_MIN_CM, DIAGONAL_AXIS_TOLERANCE_CM,
    DIAGONAL_CORRECTION_SUPPORTED, JAW_CLEARANCE_CM, SIZE_TOLERANCE_CM,
    Correction, assess, axis_deviation_deg, correction_offset, judge_band,
)

GRID = MachineGrid.from_config(mode="vertical")

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:60} {detail}")


# --- judge_band: a floor now, no ceiling -------------------------------------- #

check("a 0.3 cm offset is below the floor -> IGNORE", judge_band(0.3) == "IGNORE")
check("the floor itself is above the floor -> CORRECT",
      judge_band(CORRECT_BAND_MIN_CM) == "CORRECT")
check("a 0.9 cm offset clears the floor -> CORRECT", judge_band(0.9) == "CORRECT")
check("a 1.5 cm offset is NOT refused by distance any more -> CORRECT",
      judge_band(1.5) == "CORRECT")
check("even a 5 cm offset clears the floor -> CORRECT (geometry gates it, not distance)",
      judge_band(5.0) == "CORRECT")


# --- correction_offset: the map-frame differential, with the sign --------------- #

# The map frame is a magnitude from each home switch, + away from home.
dx, dy = correction_offset(observed_cm=(9.5, 7.6), target_cm=(9.1, 7.6))
check("a block 0.4 cm farther from the X home switch than its cell -> dx = +0.4",
      abs(dx - 0.4) < 1e-9 and abs(dy) < 1e-9, f"dx={dx:.3f} dy={dy:.3f}")
dx, dy = correction_offset(observed_cm=(8.7, 7.6), target_cm=(9.1, 7.6))
check("a block 0.4 cm nearer the X home switch than its cell -> dx = -0.4",
      abs(dx + 0.4) < 1e-9, f"dx={dx:.3f}")
dx, dy = correction_offset(observed_cm=(9.1, 7.6), target_cm=(9.1, 7.6))
check("a squarely placed block -> dx = dy = 0 (no double-count of the knobs)",
      abs(dx) < 1e-9 and abs(dy) < 1e-9)


# --- axis_deviation_deg ----------------------------------------------------- #

check("0 deg is on the axis", axis_deviation_deg(0.0) == 0.0)
check("3 deg is 3 deg off the axis", abs(axis_deviation_deg(3.0) - 3.0) < 1e-9)
check("89 deg is 1 deg off the NEAREST axis (90), not 89",
      abs(axis_deviation_deg(89.0) - 1.0) < 1e-9)
check("-2 deg is 2 deg off", abs(axis_deviation_deg(-2.0) - 2.0) < 1e-9)
check("45 deg is the worst case", abs(axis_deviation_deg(45.0) - 45.0) < 1e-9)


# --- assess: the DISPLACED path ------------------------------------------------ #

def displaced(*, offset_cm=0.9, angle=0.0, mode="vertical", plan_level=0,
              plan_clear=True, taller_pick=False, taller_place=False,
              top_of_col=True, grid=GRID, measured_cm=None, drift_occ=False):
    # [2,1] centre in vertical is (7.6, 7.6) cm - matches GRID.cell_center_cm.
    return assess(
        verdict="DISPLACED", mode=mode, plan_cell=(2, 1), plan_level=plan_level,
        where_cell=(2, 1), observed_cm=(7.6 + offset_cm, 7.6),
        map_pick_centre_cm=(7.6, 7.6), angle_deg=angle,
        plan_cell_clear=plan_clear, taller_neighbour_pick=taller_pick,
        taller_neighbour_place=taller_place, pick_is_top_of_column=top_of_col,
        grid=grid, measured_size_cm=measured_cm,
        drift_neighbour_occupied=drift_occ)


corr, reason = displaced(offset_cm=0.9)
check("DISPLACED in the band -> a Correction", isinstance(corr, Correction), reason)
check("DISPLACED correction picks and places the SAME planned cell",
      corr is not None and corr.pick_cell == (2, 1) and corr.place_cell == (2, 1))
check("DISPLACED correction is level 0 on both legs",
      corr is not None and corr.pick_level == 0 and corr.place_level == 0)
check("DISPLACED correction offset is the displacement, sign +away-from-home",
      corr is not None and abs(corr.dx_cm - 0.9) < 1e-9)
check("DISPLACED command_args is the eight-arg P shape",
      corr is not None and corr.command_args == (2, 1, 0, 0.9, 0.0, 2, 1, 0))

corr, reason = displaced(offset_cm=0.3)
check("DISPLACED below the floor -> refused, says 'below'", corr is None and "below" in reason)

# The old 1.2 cm ceiling is gone. A block 1.9 cm off, straight, with an EMPTY
# neighbour is now correctable - the pick is along the axis it drifted and
# nothing is in the way.
corr, reason = displaced(offset_cm=1.9)
check("DISPLACED 1.9 cm off with an empty neighbour -> corrected (no distance ceiling)",
      isinstance(corr, Correction), reason)
check("  ... and the offset carried is the real 1.9 cm displacement",
      corr is not None and abs(corr.dx_cm - 1.9) < 1e-9)

# ... but the SAME displacement with the neighbour occupied fouls the corridor.
corr, reason = displaced(offset_cm=1.9, drift_occ=True)
check("DISPLACED 1.9 cm off toward an OCCUPIED neighbour -> refused, 'by hand'",
      corr is None and "by hand" in reason, reason)

# A detection the wrong size is two touching blocks, not one displaced one.
corr, reason = displaced(offset_cm=0.9, measured_cm=(4.5, 2.3))
check("DISPLACED whose measured footprint is not a block -> refused",
      corr is None and "block" in reason, reason)

corr, reason = displaced(angle=20.0)
check("a rotated DISPLACED block -> refused, says 'rotated'",
      corr is None and "rotated" in reason)
corr, reason = displaced(angle=ANGLE_TOLERANCE_DEG - 0.1)
check("a barely-tilted block is still corrected", isinstance(corr, Correction))
corr, reason = displaced(mode="horizontal")
check("horizontal is refused outright", corr is None and "not supported" in reason)
corr, reason = displaced(plan_level=1)
check("a level-1 block is refused — no parallax correction",
      corr is None and "level 0" in reason)
corr, reason = displaced(plan_level=None)
check("no ledger entry -> refused", corr is None and "no block" in reason)
corr, reason = displaced(taller_pick=True)
check("a taller neighbour at the grip cell -> refused",
      corr is None and "descent corridor" in reason)
corr, reason = displaced(plan_clear=False)
check("the destination cell not clear -> refused",
      corr is None and "not clear" in reason)
corr, reason = displaced(top_of_col=False)
check("something stacked on the block -> refused",
      corr is None and "stacked" in reason)


# --- assess: the MOVED path ------------------------------------------------- #

def moved(*, off_cm=0.4, angle=0.0, sane=True, plan_level=0, plan_clear=True,
          taller_pick=False, taller_place=False):
    where = (3, 1)
    return assess(
        verdict="MOVED", mode="vertical", plan_cell=(2, 1), plan_level=plan_level,
        where_cell=where, observed_cm=(11.4 + off_cm, 7.6),
        map_pick_centre_cm=(11.4, 7.6), angle_deg=angle,
        plan_cell_clear=plan_clear, taller_neighbour_pick=taller_pick,
        taller_neighbour_place=taller_place, pick_is_top_of_column=sane, grid=GRID)


corr, reason = moved(off_cm=0.4)
check("MOVED with the block squarely on the wrong cell -> a Correction",
      isinstance(corr, Correction), reason)
check("MOVED picks the WRONG cell and places the PLANNED cell",
      corr is not None and corr.pick_cell == (3, 1) and corr.place_cell == (2, 1))
check("MOVED grips at level 0 (the block is on the board) and places at the plan level",
      corr is not None and corr.pick_level == 0 and corr.place_level == 0)
check("MOVED is NOT gated by the DISPLACED band — a small pick offset still corrects",
      corr is not None and corr.magnitude_cm < CORRECT_BAND_MIN_CM)
check("MOVED command_args carries both cells",
      corr is not None and corr.command_args == (3, 1, 0, 0.4, 0.0, 2, 1, 0))

corr, reason = moved(off_cm=2.0)
check("MOVED with the block far off the wrong cell -> refused (shaky cell read)",
      corr is None and "too far" in reason)
corr, reason = moved(taller_place=True)
check("MOVED with a taller neighbour at the DESTINATION -> refused",
      corr is None and "descent corridor" in reason)
corr, reason = moved(plan_clear=False)
check("MOVED with the destination occupied -> refused",
      corr is None and "not clear" in reason)


# --- item 5: refuse diagonal correction; both-neighbour + corner clearance -- #

def displaced_xy(*, dx_cm, dy_cm, neighbourhood=None,
                 diagonal_supported=DIAGONAL_CORRECTION_SUPPORTED,
                 angle=0.0, measured_cm=None):
    # [2,1] centre in vertical is (7.6, 7.6) cm.
    return assess(
        verdict="DISPLACED", mode="vertical", plan_cell=(2, 1), plan_level=0,
        where_cell=(2, 1), observed_cm=(7.6 + dx_cm, 7.6 + dy_cm),
        map_pick_centre_cm=(7.6, 7.6), angle_deg=angle,
        plan_cell_clear=True, taller_neighbour_pick=False,
        taller_neighbour_place=False, pick_is_top_of_column=True, grid=GRID,
        measured_size_cm=measured_cm, neighbourhood=neighbourhood,
        diagonal_supported=diagonal_supported)


def full_3x3(*occupied):
    s = set(occupied)
    return {(dc, dr): (dc, dr) in s for dc in (-1, 0, 1) for dr in (-1, 0, 1)}


# A request that drifts on BOTH axes is refused outright — the ceiling was never
# measured for a diagonal approach (audit §1 P0).
corr, reason = displaced_xy(dx_cm=0.9, dy_cm=0.9)
check("a diagonal DISPLACED request -> refused, no Correction", corr is None, reason)
check("  ... the reason names both axes and tells the operator to clear it by hand",
      "both axes" in reason and "by hand" in reason.lower(), reason)
check("  ... and it quotes the actual per-axis drift",
      "+0.90 cm X" in reason and "+0.90 cm Y" in reason, reason)

# The abs(dx)==abs(dy) tie is still a diagonal, not a coin toss onto one axis.
corr, reason = displaced_xy(dx_cm=-0.8, dy_cm=0.8)
check("a 45-degree tie drift is refused as diagonal", corr is None and "both axes" in reason,
      reason)

# A cross-axis component within the noise tolerance is NOT a diagonal — the
# axis-aligned correction is preserved.
corr, reason = displaced_xy(dx_cm=0.9, dy_cm=0.4)
check("an axis-aligned drift with sub-tolerance cross noise -> still corrected",
      isinstance(corr, Correction), reason)
check("  ... the offset carried is the real vector, cross component and all",
      corr is not None and abs(corr.dx_cm - 0.9) < 1e-9 and abs(corr.dy_cm - 0.4) < 1e-9)

corr, reason = displaced_xy(dx_cm=0.9, dy_cm=DIAGONAL_AXIS_TOLERANCE_CM)
check("a cross component exactly at the tolerance is still axis-aligned (strict >)",
      isinstance(corr, Correction), reason)
corr, reason = displaced_xy(dx_cm=0.9, dy_cm=DIAGONAL_AXIS_TOLERANCE_CM + 0.05)
check("one hair over the tolerance on the second axis -> diagonal, refused",
      corr is None and "both axes" in reason, reason)

# Occupancy cannot rescue an unsupported diagonal, and the diagonal refusal
# wins over the corner refusal (it is checked first, before any geometry).
corr, reason = displaced_xy(dx_cm=0.9, dy_cm=0.9, neighbourhood=full_3x3((1, 1)))
check("a diagonal with an occupied corner -> still refused AS a diagonal",
      corr is None and "both axes" in reason and "diagonally past" not in reason, reason)

# "Enable the flag but pass no neighbourhood" must not enable diagonals — the
# corner/cross sweep has no authoritative occupancy to work from.
corr, reason = displaced_xy(dx_cm=0.9, dy_cm=0.9, diagonal_supported=True,
                            neighbourhood=None)
check("diagonal_supported without a neighbourhood -> diagonal still refused (fail-safe)",
      corr is None and "both axes" in reason, reason)

# With the (future) flag AND a full neighbourhood: a clear diagonal is allowed,
# an occupied corner past a doubly-closed gap is refused, an occupied primary
# neighbour in a closed gap is refused. This is the both-neighbour + corner
# sweep running end to end.
corr, reason = displaced_xy(dx_cm=0.9, dy_cm=0.9, diagonal_supported=True,
                            neighbourhood=full_3x3())
check("(supported) a diagonal into a clear neighbourhood -> a Correction",
      isinstance(corr, Correction), reason)
corr, reason = displaced_xy(dx_cm=1.3, dy_cm=1.3, diagonal_supported=True,
                            neighbourhood=full_3x3((1, 1)))
check("(supported) a diagonal with both gaps closed onto an occupied corner -> refused",
      corr is None and "diagonally past" in reason, reason)
corr, reason = displaced_xy(dx_cm=1.5, dy_cm=0.9, diagonal_supported=True,
                            neighbourhood=full_3x3((1, 0)))
check("(supported) a diagonal into an occupied primary neighbour's closed gap -> refused",
      corr is None and "no room for the jaw" in reason, reason)

# The one-axis path through the full-neighbourhood plumbing still works both ways.
corr, reason = displaced_xy(dx_cm=1.9, dy_cm=0.0, neighbourhood=full_3x3())
check("a 1.9 cm axis-aligned drift, empty neighbourhood -> corrected (via the 3x3 path)",
      isinstance(corr, Correction), reason)
corr, reason = displaced_xy(dx_cm=1.9, dy_cm=0.0, neighbourhood=full_3x3((1, 0)))
check("a 1.9 cm axis-aligned drift toward an OCCUPIED neighbour -> refused, 'by hand'",
      corr is None and "by hand" in reason, reason)


# --- the gate constants are provisional, flagged as such ------------------- #

check("the correction floor is the provisional Stage 15 constant",
      CORRECT_BAND_MIN_CM == 0.5)
check("the geometry-gate tolerances are provisional Stage 15 B constants",
      SIZE_TOLERANCE_CM == 0.8 and JAW_CLEARANCE_CM == 0.4)
check("the diagonal-axis tolerance is the provisional correction floor",
      DIAGONAL_AXIS_TOLERANCE_CM == 0.5)
check("diagonal correction ships DISABLED until its jaw clearance is measured",
      DIAGONAL_CORRECTION_SUPPORTED is False)


print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

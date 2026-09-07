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

from rig.placement_check import (  # noqa: E402
    ANGLE_TOLERANCE_DEG, CORRECT_BAND_MAX_CM, CORRECT_BAND_MIN_CM,
    Correction, assess, axis_deviation_deg, correction_offset, judge_band,
)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:60} {detail}")


# --- judge_band --------------------------------------------------------------- #

check("a 0.3 cm offset is below the floor -> IGNORE", judge_band(0.3) == "IGNORE")
check("the floor itself is inside the band -> CORRECT",
      judge_band(CORRECT_BAND_MIN_CM) == "CORRECT")
check("a 0.9 cm offset is inside the band -> CORRECT", judge_band(0.9) == "CORRECT")
check("the ceiling itself is inside the band -> CORRECT",
      judge_band(CORRECT_BAND_MAX_CM) == "CORRECT")
check("a 1.5 cm offset is past the ceiling -> REFUSE", judge_band(1.5) == "REFUSE")


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
              top_of_col=True):
    return assess(
        verdict="DISPLACED", mode=mode, plan_cell=(2, 1), plan_level=plan_level,
        where_cell=(2, 1), observed_cm=(7.6 + offset_cm, 7.6),
        map_pick_centre_cm=(7.6, 7.6), angle_deg=angle,
        plan_cell_clear=plan_clear, taller_neighbour_pick=taller_pick,
        taller_neighbour_place=taller_place, pick_is_top_of_column=top_of_col)


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
corr, reason = displaced(offset_cm=1.9)
check("DISPLACED past the ceiling -> refused, says 'beyond' and 'by hand'",
      corr is None and "beyond" in reason and "by hand" in reason)
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
        taller_neighbour_place=taller_place, pick_is_top_of_column=sane)


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


# --- the band bounds are the provisional constants, flagged as such -------- #

check("the band is the provisional Stage 15 D8 band",
      CORRECT_BAND_MIN_CM == 0.5 and CORRECT_BAND_MAX_CM == 1.2)


print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

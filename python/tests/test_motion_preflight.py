#!/usr/bin/env python3
"""The exact firmware mirror behind the CORRECTION full-motion preflight.

Hand-rolled like ``test_placement_check.py`` / ``test_grid.py``: a ``check``
helper, PASSED / FAILED lists, named physical scenarios.  Two things are being
proved here and they are different:

1. :mod:`rig.motion_preflight` reproduces ``gotoBuildTargetOffset()``'s
   magnitude-space clamp *exactly* — same ``lround`` rounding, the three
   separately-rounded correction terms, the clamp that bites at 0 (home) or at
   the step cap (far end), on BOTH legs of a ``P`` move.
2. Its firmware-only constants (the X/Y step caps, ``SKEW_*``,
   ``BUILD_PLACEMENT_OFFSET_*``) still match ``build_test_v1.ino``.  The Mega
   cannot read ``rig.json`` and these must not be copied into it, so this is
   the drift guard — the same one ``test_grid.py`` puts on the paired values.

Sign discipline (AGENTS.md Rule 0 / 0a) has its own section: the preflight
works only in MAGNITUDE space, so ``+dx`` is away from the home switch on both
axes and the two spaces are never mixed.  Anything tested only on Y proves
nothing about X, so X is exercised at both travel ends explicitly.
"""

from pathlib import Path
import math
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.config import load as load_cfg  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from rig.placement_check import Correction, assess  # noqa: E402
from rig import motion_preflight as mp  # noqa: E402
from rig.motion_preflight import (  # noqa: E402
    preflight_correction, tool_offset_for_mode, steps_per_cm, _lround,
)

GRID = MachineGrid.from_config(mode="vertical")
SPC_X = steps_per_cm("x", GRID)   # 4550 / 22.8 = 199.5614...
SPC_Y = steps_per_cm("y", GRID)   # 7600 / 38.0 = 200.0

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:66} {detail}")


def pick_x_leg(pf):
    return next(l for l in pf.legs if l.leg == "pick" and l.axis == "x")


def pick_y_leg(pf):
    return next(l for l in pf.legs if l.leg == "pick" and l.axis == "y")


def place_y_leg(pf):
    return next(l for l in pf.legs if l.leg == "place" and l.axis == "y")


# ---------------------------------------------------------------------------- #
# 1. _lround is C lround (round half AWAY from zero), not Python's round()
# ---------------------------------------------------------------------------- #
check("_lround(83.5) == 84 (half away from zero, up)", _lround(83.5) == 84)
check("_lround(-83.5) == -84 (half away from zero, down)", _lround(-83.5) == -84)
check("_lround(82.5) == 83, NOT 82 (round() would give 82)", _lround(82.5) == 83)
check("_lround(0.5) == 1", _lround(0.5) == 1)
check("_lround(-0.5) == -1", _lround(-0.5) == -1)
check("_lround(0.4999) == 0", _lround(0.4999) == 0)
check("_lround(-0.4999) == 0", _lround(-0.4999) == 0)


# ---------------------------------------------------------------------------- #
# 2. Firmware-mirror drift guard — the constants must equal the live sketch
# ---------------------------------------------------------------------------- #
SKETCH = (Path(__file__).resolve().parents[2]
          / "arduino" / "build_test_v1" / "build_test_v1.ino").read_text()
_MODE_ORDER = ["vertical", "horizontal"]  # {vertical, horizontal} in the sketch


def fw_number(name):
    m = re.search(
        rf"^\s*(?:const\s+)?(?:int|float|long)\s+{re.escape(name)}\s*=\s*"
        rf"([-+]?\d+(?:\.\d+)?)\s*;",
        SKETCH, re.MULTILINE)
    return float(m.group(1)) if m else None


def fw_mode_table(name):
    m = re.search(
        rf"^\s*(?:float|long)\s+{re.escape(name)}\s*\[[^\]]*\]\s*=\s*\{{([^}}]*)\}}\s*;",
        SKETCH, re.MULTILINE)
    if m is None:
        return None
    values = [float(p.strip()) for p in m.group(1).split(",")]
    return dict(zip(_MODE_ORDER, values)) if len(values) == 2 else None


check("mirror X step cap == firmware SOFT_LIMIT_X_TRAVEL",
      mp.X_TRAVEL_STEPS == fw_number("SOFT_LIMIT_X_TRAVEL") == 4550,
      f"{mp.X_TRAVEL_STEPS} vs {fw_number('SOFT_LIMIT_X_TRAVEL')}")
check("mirror Y step cap == firmware SOFT_LIMIT_Y_TRAVEL",
      mp.Y_TRAVEL_STEPS == fw_number("SOFT_LIMIT_Y_TRAVEL") == 7600,
      f"{mp.Y_TRAVEL_STEPS} vs {fw_number('SOFT_LIMIT_Y_TRAVEL')}")

for const_name, mirror in (
    ("SKEW_X_PER_COL_CM", mp.SKEW_X_PER_COL_CM),
    ("SKEW_X_PER_ROW_CM", mp.SKEW_X_PER_ROW_CM),
    ("SKEW_X_PER_COLROW_CM", mp.SKEW_X_PER_COLROW_CM),
    ("SKEW_Y_PER_COL_CM", mp.SKEW_Y_PER_COL_CM),
    ("SKEW_Y_PER_ROW_CM", mp.SKEW_Y_PER_ROW_CM),
    ("SKEW_Y_PER_COLROW_CM", mp.SKEW_Y_PER_COLROW_CM),
    ("BUILD_PLACEMENT_OFFSET_X_CM", mp.BUILD_PLACEMENT_OFFSET_X_CM),
    ("BUILD_PLACEMENT_OFFSET_Y_CM", mp.BUILD_PLACEMENT_OFFSET_Y_CM),
):
    fw = fw_mode_table(const_name)
    check(f"mirror {const_name} == firmware table (both modes)",
          fw is not None and fw == mirror, f"firmware {fw}, mirror {mirror}")

# The mirror must not have silently gained/dropped a mode key.
check("mirror skew/placement tables key exactly {vertical, horizontal}",
      all(set(t) == {"vertical", "horizontal"} for t in (
          mp.SKEW_Y_PER_COL_CM, mp.BUILD_PLACEMENT_OFFSET_X_CM)))

# steps/cm is DERIVED, never hard-coded — from the cap and the paired
# workspace displacement, exactly like xyStepsPerCmOf().
check("steps/cm X is cap / workspace.width_cm, derived",
      abs(SPC_X - 4550 / 22.8) < 1e-9)
check("steps/cm Y is cap / workspace.height_cm, derived",
      abs(SPC_Y - 7600 / 38.0) < 1e-9)


# ---------------------------------------------------------------------------- #
# 3. A correction well inside the travel passes, all four axis-legs clean
# ---------------------------------------------------------------------------- #
pf = preflight_correction(grid=GRID, mode="vertical",
                          pick_cell=(3, 1), place_cell=(2, 1),
                          dx_cm=-0.42, dy_cm=0.11)
check("mid-grid correction is reachable", pf.ok, pf.reason)
check("mid-grid correction reports no clamped legs", pf.clamped_legs == ())
check("mid-grid correction preflights all four axis-legs",
      len(pf.legs) == 4
      and {(l.leg, l.axis) for l in pf.legs}
          == {("pick", "x"), ("pick", "y"), ("place", "x"), ("place", "y")})

# The pick X leg: cell [3] centre 11.4 cm -> lround(11.4 * SPC_X) steps, then
# + lround(dx * SPC_X). Assert the arithmetic against a hand recompute.
lx = pick_x_leg(pf)
want_mag = _lround(11.4 * SPC_X)
want_corr = _lround(-0.42 * SPC_X)
check("pick X uncompensated magnitude matches cellCentre*spc",
      lx.target_mag == want_mag, f"{lx.target_mag} vs {want_mag}")
check("pick X correction is lround(dx*spc), one term (skew_x/placement_x are 0)",
      lx.correction_steps == want_corr, f"{lx.correction_steps} vs {want_corr}")
check("pick X wanted_from_home = magnitude + correction",
      lx.wanted_from_home == want_mag + want_corr)

# The pick Y leg carries SKEW_Y_PER_COL_CM * col (col = 3 here) as well as dy.
ly = pick_y_leg(pf)
want_y_mag = _lround(7.6 * SPC_Y)
want_y_corr = _lround(0.115 * 3 * SPC_Y) + _lround(0.11 * SPC_Y)
check("pick Y correction sums skew(col=3) and the dy nudge, each lround'd",
      ly.correction_steps == want_y_corr, f"{ly.correction_steps} vs {want_y_corr}")
check("pick Y stays inside the Y step cap",
      0 <= ly.wanted_from_home <= mp.Y_TRAVEL_STEPS and not ly.clamped)

# The place leg carries NO nudge (gotoBuildTarget(qcol,qrow,rot) -> 0,0), but
# still gets the mode skew: place [2] -> skew_y = 0.115 * 2.
ply = place_y_leg(pf)
check("place Y correction is skew only, no nudge",
      ply.correction_steps == _lround(0.115 * 2 * SPC_Y))
check("place X correction is exactly zero -> firmware `continue`, cannot clamp",
      next(l for l in pf.legs if l.leg == "place" and l.axis == "x"
           ).correction_steps == 0)


# ---------------------------------------------------------------------------- #
# 4. Just-inside vs just-outside the FAR travel cap (compensation pushes it)
# ---------------------------------------------------------------------------- #
# Col 6 sits its holder exactly on the X cap: lround(22.8 * SPC_X) == 4550.
check("col 6 holder magnitude is exactly the X step cap",
      _lround(22.8 * SPC_X) == mp.X_TRAVEL_STEPS)

# dx = +0.005 cm -> lround(0.998) == +1 step -> 4551 > 4550 -> CLAMP.
pf_out = preflight_correction(grid=GRID, mode="vertical",
                              pick_cell=(6, 3), place_cell=(2, 3),
                              dx_cm=0.005, dy_cm=0.0)
check("+1 step past the X cap after compensation -> not ok", not pf_out.ok)
check("  ... the failing leg is the pick X leg, marked clamped",
      pick_x_leg(pf_out).clamped and pick_x_leg(pf_out).wanted_from_home == 4551
      and pick_x_leg(pf_out).clamped_from_home == 4550)
check("  ... the reason names the leg, the far cap, and the miss distance",
      "pick X" in pf_out.reason and "far travel cap" in pf_out.reason
      and "cm off" in pf_out.reason, pf_out.reason)

# dx = -0.005 cm -> lround(-0.998) == -1 step -> 4549 <= 4550 -> clean.
pf_in = preflight_correction(grid=GRID, mode="vertical",
                             pick_cell=(6, 3), place_cell=(2, 3),
                             dx_cm=-0.005, dy_cm=0.0)
check("1 step inside the X cap after compensation -> ok", pf_in.ok)
check("  ... pick X wanted is 4549, not clamped",
      pick_x_leg(pf_in).wanted_from_home == 4549
      and not pick_x_leg(pf_in).clamped)

# Landing the compensated target EXACTLY on the cap is allowed (`> maximum`,
# not `>= maximum`). dx chosen so magnitude + correction == 4550 from col 5.
col5_mag = _lround(19.0 * SPC_X)
need = mp.X_TRAVEL_STEPS - col5_mag           # steps of correction to hit the cap
dx_exact = need / SPC_X
pf_edge = preflight_correction(grid=GRID, mode="vertical",
                               pick_cell=(5, 3), place_cell=(2, 3),
                               dx_cm=dx_exact, dy_cm=0.0)
check("compensated target landing exactly on the X cap is NOT clamped",
      pf_edge.ok and pick_x_leg(pf_edge).wanted_from_home == mp.X_TRAVEL_STEPS,
      f"wanted {pick_x_leg(pf_edge).wanted_from_home}")


# ---------------------------------------------------------------------------- #
# 5. Compensation-induced failure with NO nudge — skew alone drives it off
# ---------------------------------------------------------------------------- #
# Vertical col 6 row 5: Y holder on the cap, and SKEW_Y_PER_COL_CM * 6 = 0.69 cm
# = +138 steps -> 7738 > 7600. The block would land 0.69 cm short of the row.
pf_skew = preflight_correction(grid=GRID, mode="vertical",
                               pick_cell=(6, 5), place_cell=(2, 3),
                               dx_cm=0.0, dy_cm=0.0)
check("skew alone (dx=dy=0) at the far corner clamps the pick Y leg",
      not pf_skew.ok and pick_y_leg(pf_skew).clamped
      and pick_y_leg(pf_skew).correction_steps == _lround(0.115 * 6 * SPC_Y)
      and pick_y_leg(pf_skew).wanted_from_home == 7738)
check("  ... miss distance in the reason is ~0.69 cm",
      "0.69 cm off" in pf_skew.reason, pf_skew.reason)


# ---------------------------------------------------------------------------- #
# 6. BOTH legs are checked — a clamp on the PLACE leg is caught too
# ---------------------------------------------------------------------------- #
pf_place = preflight_correction(grid=GRID, mode="vertical",
                                pick_cell=(2, 3), place_cell=(6, 5),
                                dx_cm=0.0, dy_cm=0.0)
check("a clamp on the PLACE leg fails the preflight", not pf_place.ok)
check("  ... it is the place Y leg, and the pick legs are clean",
      place_y_leg(pf_place).clamped
      and not pick_x_leg(pf_place).clamped
      and not pick_y_leg(pf_place).clamped
      and "place Y" in pf_place.reason, pf_place.reason)


# ---------------------------------------------------------------------------- #
# 7. cellTargetPosition() stage — tool offset alone puts the holder off travel
# ---------------------------------------------------------------------------- #
# A negative X tool offset pushes the holder FARTHER from home than the cell
# centre: 22.8 - (-0.6) = 23.4 cm > 22.8 cm travel -> firmware buildReject.
pf_tool = preflight_correction(grid=GRID, mode="vertical",
                               pick_cell=(6, 3), place_cell=(2, 3),
                               dx_cm=0.0, dy_cm=0.0, tool_offset_cm=(-0.6, 0.0))
check("tool offset alone off the holder travel -> not ok, before any nudge",
      not pf_tool.ok and pick_x_leg(pf_tool).target_mag is None
      and "outside the 0..22.80 cm holder travel" in pf_tool.reason, pf_tool.reason)

# A positive X tool offset at col 0 pushes the holder BEFORE home: 0 - 0.6 < 0.
pf_tool0 = preflight_correction(grid=GRID, mode="vertical",
                                pick_cell=(0, 3), place_cell=(2, 3),
                                dx_cm=0.0, dy_cm=0.0, tool_offset_cm=(0.6, 0.0))
check("tool offset pushing the holder before the home switch -> not ok",
      not pf_tool0.ok and pick_x_leg(pf_tool0).target_mag is None)

# The real vertical neutral tool offset IS (0, 0) — so the default is exact.
check("tool_offset_for_mode(cfg, 'vertical') is a genuine (0.0, 0.0)",
      tool_offset_for_mode(load_cfg(), "vertical") == (0.0, 0.0))
check("tool_offset_for_mode(cfg, 'horizontal') is the cw swing (+0.9, -0.3)",
      tool_offset_for_mode(load_cfg(), "horizontal") == (0.9, -0.3))


# ---------------------------------------------------------------------------- #
# 8. X-AXIS SIGN CONVENTION — everything in magnitude space, both ends
# ---------------------------------------------------------------------------- #
# Around a mid cell, +dx and -dx move the wanted magnitude symmetrically:
# there is no travel-direction factor, so X behaves exactly like Y here.
base = preflight_correction(grid=GRID, mode="vertical",
                            pick_cell=(3, 2), place_cell=(3, 2),
                            dx_cm=0.0, dy_cm=0.0)
plus = preflight_correction(grid=GRID, mode="vertical",
                            pick_cell=(3, 2), place_cell=(3, 2),
                            dx_cm=1.0, dy_cm=0.0)
minus = preflight_correction(grid=GRID, mode="vertical",
                             pick_cell=(3, 2), place_cell=(3, 2),
                             dx_cm=-1.0, dy_cm=0.0)
b = pick_x_leg(base).target_mag
step = _lround(1.0 * SPC_X)
check("+dx moves the X target AWAY from home (magnitude up)",
      pick_x_leg(plus).wanted_from_home == b + step)
check("-dx moves the X target TOWARD home (magnitude down)",
      pick_x_leg(minus).wanted_from_home == b - step)
check("the two are symmetric about the uncompensated magnitude",
      (pick_x_leg(plus).wanted_from_home - b)
      == -(pick_x_leg(minus).wanted_from_home - b))
check("neither mid-grid X nudge is clamped", plus.ok and minus.ok)

# +dx at the far cap clamps at the FAR end; -dx at col 0 clamps at the HOME
# end (0). A model that had X's sign inverted would clamp the wrong one.
far = preflight_correction(grid=GRID, mode="vertical",
                           pick_cell=(6, 3), place_cell=(2, 3),
                           dx_cm=1.0, dy_cm=0.0)
check("+dx past the far X cap clamps to the cap, not to 0",
      not far.ok and pick_x_leg(far).clamped_from_home == mp.X_TRAVEL_STEPS
      and "far travel cap" in far.reason, far.reason)
home = preflight_correction(grid=GRID, mode="vertical",
                            pick_cell=(0, 3), place_cell=(2, 3),
                            dx_cm=-0.5, dy_cm=0.0)
check("-dx below the X home switch clamps to 0, not to the cap",
      not home.ok and pick_x_leg(home).clamped_from_home == 0
      and "below the home switch" in home.reason, home.reason)
check("  ... and the raw wanted magnitude is genuinely negative there",
      pick_x_leg(home).wanted_from_home == -_lround(0.5 * SPC_X))


# ---------------------------------------------------------------------------- #
# 8b. Both MODES through the full compensation stack (horizontal is mode-
#     agnostic in the preflight even though placement_check refuses it today —
#     the rig.link guard is not mode-scoped, so it must be exact for both).
# ---------------------------------------------------------------------------- #
HGRID = MachineGrid.from_config(mode="horizontal")
HTOOL = tool_offset_for_mode(load_cfg(), "horizontal")       # cw swing (0.9, -0.3)
HSPC_X = steps_per_cm("x", HGRID)

pf_h = preflight_correction(grid=HGRID, mode="horizontal",
                            pick_cell=(1, 4), place_cell=(1, 4),
                            dx_cm=0.5, dy_cm=-0.3, tool_offset_cm=HTOOL)
check("horizontal mid-grid correction is reachable", pf_h.ok, pf_h.reason)
hlx = pick_x_leg(pf_h)
# holder X = centre(1)=9.5 minus tool_offset_x 0.9 -> 8.6 cm.
check("horizontal pick X folds in the CW tool offset",
      hlx.target_mag == _lround((9.5 - 0.9) * HSPC_X))
# correction X = lround(BUILD_PLACEMENT_OFFSET_X(+1.8)*spc) + skew_x(0) + lround(dx*spc)
check("horizontal pick X correction sums the +1.8 cm placement offset and the nudge",
      hlx.correction_steps == _lround(1.8 * HSPC_X) + _lround(0.5 * HSPC_X))
check("horizontal place X carries the placement offset even with no nudge",
      next(l for l in pf_h.legs if l.leg == "place" and l.axis == "x"
           ).correction_steps == _lround(1.8 * HSPC_X))

# Far horizontal column [2] holder X = 17.1 - 0.9 = 16.2 cm, then +1.8 cm
# placement offset pushes it away from home to ~18.0 cm — still well inside
# the 22.8 cm X travel cap.
pf_hc = preflight_correction(grid=HGRID, mode="horizontal",
                             pick_cell=(2, 9), place_cell=(2, 9),
                             dx_cm=0.0, dy_cm=0.0, tool_offset_cm=HTOOL)
check("horizontal far corner with placement offset + tool offset is reachable",
      pf_hc.ok, pf_hc.reason)
# Horizontal's grid only reaches X = 17.1 cm, so the far X cap is out of a
# legal nudge's reach — the reachable clamp is at the HOME end. Column 0
# holder X = 1.9 - 0.9 = 1.0 cm (~200 steps); the +1.8 cm placement offset
# pushes it out, so a large -2.9 cm inward nudge is needed to drive it below
# the home switch (200 + ~359 - ~579 steps < 0).
pf_ho = preflight_correction(grid=HGRID, mode="horizontal",
                             pick_cell=(0, 4), place_cell=(0, 4),
                             dx_cm=-2.9, dy_cm=0.0, tool_offset_cm=HTOOL)
check("horizontal col 0 + placement offset + inward nudge -> clamped at home",
      not pf_ho.ok and pick_x_leg(pf_ho).clamped
      and pick_x_leg(pf_ho).clamped_from_home == 0
      and "below the home switch" in pf_ho.reason, pf_ho.reason)


# ---------------------------------------------------------------------------- #
# 9. Integration — assess() refuses a correction whose motion would clamp
# ---------------------------------------------------------------------------- #
def displaced_at(cell, offset_cm, *, drift_occ=False):
    cx, cy = GRID.cell_center_cm(*cell)
    return assess(
        verdict="DISPLACED", mode="vertical", plan_cell=cell, plan_level=0,
        where_cell=cell, observed_cm=(cx + offset_cm, cy),
        map_pick_centre_cm=(cx, cy), angle_deg=0.0, plan_cell_clear=True,
        taller_neighbour_pick=False, taller_neighbour_place=False,
        pick_is_top_of_column=True, grid=GRID, measured_size_cm=None,
        drift_neighbour_occupied=drift_occ)

# [4,2] is well inside — a 0.7 cm nudge is above the floor and reachable.
corr, reason = displaced_at((4, 2), 0.7)
check("assess: an in-band, reachable DISPLACED -> a Correction",
      isinstance(corr, Correction), reason)

# [6,2] sits on the X cap; a +0.7 cm outward nudge would be clamped. assess()
# must now refuse it with the preflight's sentence, not hand back a Correction.
corr, reason = displaced_at((6, 2), 0.7)
check("assess: a DISPLACED whose compensated pick would clamp -> refused",
      corr is None and "clamp" in reason and "pick X" in reason, reason)

# The MOVED path is guarded too: block squarely on wrong cell [6,2], small
# offset, but the pick target is on the cap and skew_y/nudge tips it over.
mcx, mcy = GRID.cell_center_cm(6, 2)
corr, reason = assess(
    verdict="MOVED", mode="vertical", plan_cell=(5, 2), plan_level=0,
    where_cell=(6, 2), observed_cm=(mcx + 0.3, mcy), map_pick_centre_cm=(mcx, mcy),
    angle_deg=0.0, plan_cell_clear=True, taller_neighbour_pick=False,
    taller_neighbour_place=False, pick_is_top_of_column=True, grid=GRID)
check("assess: a MOVED pick on the X cap + outward nudge -> refused by preflight",
      corr is None and "clamp" in reason, reason)

# grid=None keeps the old pure-number path working (no geometry to preflight).
corr, reason = assess(
    verdict="DISPLACED", mode="vertical", plan_cell=(2, 1), plan_level=0,
    where_cell=(2, 1), observed_cm=(7.6 + 0.9, 7.6), map_pick_centre_cm=(7.6, 7.6),
    angle_deg=0.0, plan_cell_clear=True, taller_neighbour_pick=False,
    taller_neighbour_place=False, pick_is_top_of_column=True, grid=None)
check("assess: grid=None still returns a Correction (preflight skipped)",
      isinstance(corr, Correction), reason)


print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

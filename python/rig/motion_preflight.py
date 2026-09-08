#!/usr/bin/env python3
"""Exact Python mirror of the firmware's compensated build-motion clamp.

Why this exists (the audit)
---------------------------
`docs/features/block-vision-placement-supervision-audit-2026-09-08.md` §1, the
P0 row "Pi preflight absent":

    The complete target including skew, fixed build offset, tool offset, and
    correction is not proven reachable on the Pi. Firmware clamps a corrected
    edge target, warns, and proceeds.  ...  add a Python-side exact full-motion
    preflight using the active mode and the paired calibration values. Any
    clamp prediction is a hard refusal and a commissioning blocker.

The firmware's `cellTargetPosition()` validates only the **uncompensated**
holder target (cell centre minus tool offset). The per-command correction —
`BUILD_PLACEMENT_OFFSET_*`, `SKEW_*`, and the `P` verb's `(dx,dy)` nudge — is
added *afterwards*, inside `gotoBuildTargetOffset()`, where a target pushed off
the travel is **clamped, warned about on the serial console, and then driven
anyway**.  On the rig that means the claw descends somewhere other than the
displaced block's centre.  Nothing on the Pi predicts it.

This module reproduces `gotoBuildTargetOffset()`'s arithmetic exactly — same
magnitude-space clamp, same `lround` rounding, same three separately-rounded
correction terms — for **both legs** of a `P` correction (the pick leg carries
the `(dx,dy)` nudge; the place leg carries `0,0`), so a correction that would
clamp is refused before a byte is sent.

Firmware-only constants live here on purpose
-------------------------------------------
The Mega cannot read `config/rig.json`, and the X/Y step caps, `SKEW_*` and
`BUILD_PLACEMENT_OFFSET_*` **must not be copied into it** (AGENTS.md "What must
NOT be copied into config/rig.json" / master table rows: those knobs are
`no / no / no`).  They are mirrored below as plain module constants, and
`python/tests/test_motion_preflight.py` parses `build_test_v1.ino` and fails on
any drift — the same guard `test_grid.py` puts on the paired values.  **If you
change one of these in the sketch, change it here in the same commit.**

Sign discipline (AGENTS.md Rule 0 / 0a)
--------------------------------------
Everything here is done in MAGNITUDE space — "steps from the home switch",
always >= 0 inside the travel — exactly as the fixed firmware does it.  There
is no signed `axisPos[]` here and no multiply by a travel direction: `+dx` is
away from the home switch on *both* axes, and the clamp bites at 0 (the home
end) or at the step cap (the far end).  A model that reasoned in signed
positions is what produced the live "every X column collapsed onto X = 0" bug;
this one cannot, because it never leaves magnitude space.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

# --- MIRROR of build_test_v1.ino - keep in sync in the SAME commit ---------- #
# SECTION 6B: the X/Y software travel caps, in steps.  `SOFT_LIMIT_*_TRAVEL`
# / `gridTravelOf()` / `axisTravelOf()`.  Firmware-only; not in rig.json.
X_TRAVEL_STEPS = 4550
Y_TRAVEL_STEPS = 7600

# SECTION 6C: build-motion compensation, per mode, firmware-only.  These bend
# the holder path and never touch the rectangular grid model the Pi/camera
# draw, so they have no rig.json partner - only this mirror and the sketch.
# Order is {vertical, horizontal}; keyed by name here so a swap cannot pass.
SKEW_X_PER_COL_CM = {"vertical": 0.0, "horizontal": 0.0}
SKEW_X_PER_ROW_CM = {"vertical": 0.0, "horizontal": 0.0}
SKEW_X_PER_COLROW_CM = {"vertical": 0.0, "horizontal": 0.0}
SKEW_Y_PER_COL_CM = {"vertical": 0.115, "horizontal": 0.13}
SKEW_Y_PER_ROW_CM = {"vertical": 0.0, "horizontal": 0.0}
SKEW_Y_PER_COLROW_CM = {"vertical": 0.0, "horizontal": 0.0}

# Rig-calibrated. Vertical -0.45 on both axes (placements landed 0.45 cm too far
# from each home switch). Horizontal X: -0.4 -> +1.35 after the 2026 arm re-seat
# -> walked down to +0.6 as it kept landing too far. Horizontal Y: -0.35.
BUILD_PLACEMENT_OFFSET_X_CM = {"vertical": -0.45, "horizontal": 0.6}
BUILD_PLACEMENT_OFFSET_Y_CM = {"vertical": -0.45, "horizontal": -0.35}
# --------------------------------------------------------------------------- #

#: `const float slack = 0.0001;` in `cellTargetPosition()`.
_SLACK_CM = 1e-4

#: Rotation slot each grid mode places in.  `buildRotationForMode()`:
#: horizontal -> ROT_CW, everything else -> ROT_NONE (the `neutral` offset).
_TOOL_OFFSET_SLOT = {"vertical": "neutral", "horizontal": "cw"}


def _lround(value: float) -> int:
    """C `lround`: round half AWAY from zero, to a `long`.

    Python's built-in `round()` is round-half-to-even, which disagrees with the
    firmware at exact half-steps.  Every cm->steps conversion in
    `gotoBuildTargetOffset()` / `buildSkewSteps()` / `buildPlacementOffsetSteps()`
    goes through `lround`, so the preflight must too or it will predict "clamp"
    or "clear" one step off the firmware at a boundary.
    """
    return int(math.floor(value + 0.5)) if value >= 0.0 else int(math.ceil(value - 0.5))


def steps_per_cm(axis: str, grid) -> float:
    """`xyStepsPerCmOf(axis)` = travel-cap steps / holder displacement cm.

    The step cap is firmware-only (above); the cm displacement is its paired
    partner `config/rig.json -> workspace.width_cm / height_cm` (AGENTS.md
    master table: `X_TRAVEL_CM` <-> `workspace.width_cm`), which `MachineGrid`
    already carries.  Never hard-code the ratio - the firmware derives it and
    so does this.
    """
    if axis == "x":
        return X_TRAVEL_STEPS / float(grid.workspace_width_cm)
    return Y_TRAVEL_STEPS / float(grid.workspace_height_cm)


def _travel_steps(axis: str) -> int:
    return X_TRAVEL_STEPS if axis == "x" else Y_TRAVEL_STEPS


def _skew_cm(axis: str, mode: str, col: int, row: int) -> float:
    """`buildSkewSteps()`'s polynomial, in cm, BEFORE the single `lround`.

    Both `col` and `row` feed both axes, exactly as the firmware passes
    `buildSkewSteps(axis, col, row)` unchanged in the X and the Y iteration.
    """
    if axis == "x":
        per_col, per_row, per_colrow = (SKEW_X_PER_COL_CM[mode],
                                        SKEW_X_PER_ROW_CM[mode],
                                        SKEW_X_PER_COLROW_CM[mode])
    else:
        per_col, per_row, per_colrow = (SKEW_Y_PER_COL_CM[mode],
                                        SKEW_Y_PER_ROW_CM[mode],
                                        SKEW_Y_PER_COLROW_CM[mode])
    return per_col * col + per_row * row + per_colrow * col * row


def _placement_offset_cm(axis: str, mode: str) -> float:
    table = BUILD_PLACEMENT_OFFSET_X_CM if axis == "x" else BUILD_PLACEMENT_OFFSET_Y_CM
    return table[mode]


def tool_offset_for_mode(cfg: dict, mode: str) -> tuple[float, float]:
    """`toolOffsetCmOf(axis, buildRotationForMode())` from a loaded config dict.

    Reads (does not load) `config/rig.json -> tool_offsets`.  Vertical's
    `neutral` slot is a genuine `(0.0, 0.0)` - a vertical build never turns -
    so the map-frame differential a `P` correction carries needs no tool term
    in the only mode `placement_check` supports today.  Horizontal's `cw`
    `(+0.9, -0.3)` cm is here for the defence-in-depth guard in
    `rig.link.Rig.replace_block`, which is mode-agnostic.
    """
    slot = _TOOL_OFFSET_SLOT.get(mode, "neutral")
    offs = (cfg.get("tool_offsets") or {}).get(slot) or {}
    return float(offs.get("x_cm", 0.0)), float(offs.get("y_cm", 0.0))


@dataclass(frozen=True)
class AxisLegPreflight:
    """One axis of one leg of a `P` move, run through the firmware clamp.

    ``target_mag`` is the UNCOMPENSATED magnitude `cellTargetPosition()`
    computes (``None`` if that stage itself refuses the holder target).
    ``correction_steps`` is the summed, separately-rounded compensation.
    ``wanted_from_home`` is ``target_mag + correction_steps`` and
    ``clamped_from_home`` is that value forced back onto ``[0, travel_steps]``;
    ``clamped`` is ``True`` exactly when the firmware's clamp would bite and
    the block would NOT land where asked.
    """

    leg: str            # "pick" | "place"
    axis: str           # "x" | "y"
    ok: bool
    reason: str
    holder_cm: float
    travel_cm: float
    travel_steps: int
    target_mag: int | None
    correction_steps: int
    wanted_from_home: int | None
    clamped_from_home: int | None
    clamped: bool


@dataclass(frozen=True)
class MotionPreflight:
    """The verdict for a whole `P` correction: both legs, both axes.

    ``ok`` is ``True`` only when every :class:`AxisLegPreflight` is reachable
    with no clamp.  ``reason`` is a single operator sentence naming the first
    leg/axis that failed and by how much; empty when ``ok``.
    """

    ok: bool
    reason: str
    legs: tuple[AxisLegPreflight, ...]

    @property
    def clamped_legs(self) -> tuple[AxisLegPreflight, ...]:
        return tuple(leg for leg in self.legs if leg.clamped)


def _axis_leg(*, leg: str, axis: str, mode: str, grid,
              cell: tuple[int, int], extra_cm: float,
              tool_offset_cm: float) -> AxisLegPreflight:
    col, row = int(cell[0]), int(cell[1])
    spc = steps_per_cm(axis, grid)
    travel_steps = _travel_steps(axis)
    travel_cm = float(grid.workspace_width_cm if axis == "x"
                      else grid.workspace_height_cm)

    centre_cm = (grid.cell_center_x_cm(col) if axis == "x"
                 else grid.cell_center_y_cm(row))
    holder_cm = centre_cm - tool_offset_cm

    base = dict(leg=leg, axis=axis, holder_cm=holder_cm, travel_cm=travel_cm,
                travel_steps=travel_steps)

    # Stage 1 - cellTargetPosition(): the UNCOMPENSATED holder target. Firmware
    # returns false here (a clean buildReject, no motion) if the tool offset
    # alone puts the holder off the travel.
    if spc <= 0.0 or holder_cm < -_SLACK_CM or holder_cm > travel_cm + _SLACK_CM:
        return AxisLegPreflight(
            **base, ok=False, target_mag=None, correction_steps=0,
            wanted_from_home=None, clamped_from_home=None, clamped=False,
            reason=(f"the {leg} {axis.upper()} target sits at {holder_cm:.2f} cm "
                    f"from home, outside the 0..{travel_cm:.2f} cm holder travel "
                    f"(tool offset included) - the firmware would reject it"))
    target_mag = _lround(holder_cm * spc)
    if target_mag < 0 or target_mag > travel_steps:
        return AxisLegPreflight(
            **base, ok=False, target_mag=target_mag, correction_steps=0,
            wanted_from_home=None, clamped_from_home=None, clamped=False,
            reason=(f"the {leg} {axis.upper()} target is {target_mag} steps from "
                    f"home, outside the 0..{travel_steps} step cap"))

    # Stage 2 - gotoBuildTargetOffset()'s magnitude-space correction + clamp.
    # THREE terms, each lround'd on its own, exactly as the firmware sums
    # buildPlacementOffsetSteps(axis) + buildSkewSteps(axis, col, row)
    # + lround(extraCm * xyStepsPerCmOf(axis)).
    correction = (_lround(_placement_offset_cm(axis, mode) * spc)
                  + _lround(_skew_cm(axis, mode, col, row) * spc)
                  + _lround(extra_cm * spc))
    if correction == 0:
        # `if (correction == 0) continue;` - no clamp possible, target stands.
        return AxisLegPreflight(
            **base, ok=True, target_mag=target_mag, correction_steps=0,
            wanted_from_home=target_mag, clamped_from_home=target_mag,
            clamped=False, reason="")

    wanted = target_mag + correction
    clamped_val = 0 if wanted < 0 else (travel_steps if wanted > travel_steps else wanted)
    bit = clamped_val != wanted
    if bit:
        off_by = wanted - clamped_val
        edge = "past the far travel cap" if wanted > travel_steps else "below the home switch"
        drift_cm = abs(off_by) / spc
        reason = (f"the {leg} {axis.upper()} target compensates to {wanted} steps "
                  f"from home ({edge}); the firmware would clamp it to "
                  f"{clamped_val} and place the block {drift_cm:.2f} cm off the "
                  f"requested point")
    else:
        reason = ""
    return AxisLegPreflight(
        **base, ok=not bit, target_mag=target_mag, correction_steps=correction,
        wanted_from_home=wanted, clamped_from_home=clamped_val, clamped=bit,
        reason=reason)


def preflight_correction(*, grid, mode: str,
                         pick_cell: tuple[int, int],
                         place_cell: tuple[int, int],
                         dx_cm: float, dy_cm: float,
                         tool_offset_cm: tuple[float, float] = (0.0, 0.0)
                         ) -> MotionPreflight:
    """Would the firmware clamp any part of this `P` correction's motion?

    ``grid`` is the :class:`rig.grid.MachineGrid` for ``mode`` (it supplies the
    lattice centres and the paired holder-displacement cm).  ``pick_cell`` is
    where the block is now and carries the ``(dx_cm, dy_cm)`` magnitude nudge;
    ``place_cell`` is where it belongs and carries no nudge, exactly as
    ``replaceBlock()`` calls ``gotoBuildTargetOffset(pcol, prow, rot, dx, dy)``
    then ``gotoBuildTarget(qcol, qrow, rot)``.  ``tool_offset_cm`` is
    ``toolOffsetCmOf`` for the mode's build rotation - ``(0, 0)`` for vertical.

    Returns a :class:`MotionPreflight`.  ``ok`` is ``False`` if the
    uncompensated target is already off the travel OR if the compensation
    (placement offset + skew + nudge) would drive it off and be clamped.
    """
    legs: list[AxisLegPreflight] = []
    for leg, cell, ex, ey in (("pick", pick_cell, float(dx_cm), float(dy_cm)),
                              ("place", place_cell, 0.0, 0.0)):
        for axis, extra in (("x", ex), ("y", ey)):
            legs.append(_axis_leg(
                leg=leg, axis=axis, mode=mode, grid=grid, cell=cell,
                extra_cm=extra, tool_offset_cm=(tool_offset_cm[0] if axis == "x"
                                                else tool_offset_cm[1])))
    bad = next((leg for leg in legs if not leg.ok), None)
    return MotionPreflight(ok=bad is None, reason="" if bad is None else bad.reason,
                           legs=tuple(legs))

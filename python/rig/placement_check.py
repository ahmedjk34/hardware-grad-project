#!/usr/bin/env python3
"""Can the claw safely pick a mis-placed block up and set it on its planned cell?

This is the geometry and the policy for the operator-triggered CORRECTION
action (``docs/features/correction-action.md``). It is **pure** — no camera, no
serial port, no frame, no OpenCV — so it is testable with hand-built numbers,
the same way the pure-geometry helpers in ``rig/`` already are.

It answers one question for a supervision ``MOVED`` or ``DISPLACED`` verdict:
**may the machine pick that block up and put it back, and with what pick
offset?** The answer is a :class:`Correction` or ``None`` with a reason
sentence.

The two verdicts are different corrections
-----------------------------------------
* **MOVED** — the block sits squarely on the WRONG cell ``[c,d]``. Grip there
  (a real cell centre: the jaws pit into ``[c,d]``'s own gaps, a clean
  capture), lift, place on the planned cell ``[a,b]``. This is the *safer*
  case: the pick is not in a gap and does not risk a neighbour.
* **DISPLACED** — the block is in a gap beside its planned cell ``[a,b]``, on no
  site. Grip it where it lies, lift, place back on ``[a,b]``. Marginal: a
  ``DISPLACED`` centroid is already >= half a block off ``[a,b]`` (that is what
  put it in the gap), so it is only correctable in a thin band before its edge
  reaches the neighbour.

Both produce a :class:`Correction` with an explicit **pick** cell+level+offset
and **place** cell+level, so the firmware ``P`` verb does not have to assume
pick and place are the same cell.

Narrow on purpose (the audit)
-----------------------------
1. **Vertical mode only.** In vertical every firmware motion knob that would
   bias the pick offset is zero — ``tool_offsets.neutral``,
   ``BUILD_PLACEMENT_OFFSET_*`` and ``SKEW_X_*`` — leaving only
   ``SKEW_Y_PER_COL_CM`` (0.115 cm/column), inside the map's own 0.27 cm
   flattening error. Horizontal carries the ``cw`` tool offset, a placement
   offset, the pickup-rotate grip geometry and a paper/block map ambiguity that
   the saved file cannot resolve — separate, later work.
2. **Level 0 only.** Supervision applies no parallax correction, so a verdict
   at level 1-2 carries 0.9-1.9 cm of uncorrected, directional parallax that
   the pick point would inherit whole.
3. **A band, not a threshold** (Stage 15 D8), applied to the PICK offset. Below
   :data:`CORRECT_BAND_MIN_CM` a nudge is not worth disturbing a settled block
   for; above :data:`CORRECT_BAND_MAX_CM` a re-place would drag the block's edge
   into its neighbour, so it is a refusal and a human, not a clamp. **Both
   bounds are provisional** — Stage 15 Stage B (jaw capture tolerance,
   placement repeatability) is the bench measurement that would confirm the
   band is not empty. Named here so a measurement changes one line.

The offset is a MAP-FRAME DIFFERENTIAL
-------------------------------------
``dx = x_obs - x_map_pickcell`` where ``x_map_pickcell`` is ``mapped_grid`` 's
own lattice centre for the pick cell. Both are in the map's
``(u,v)*workspace_cm`` frame. On a block-calibrated map a squarely-placed block
reads ``dx ~= 0``, so the firmware's ``P`` verb — same ``gotoBuildTarget()``
chain on both legs — does not double-count the calibration. See
``docs/features/correction-action.md`` §B.3.

Sign convention (AGENTS.md Rule 0 / 0a): ``dx`` / ``dy`` are **magnitudes** from
each home switch, ``+`` away from home. They go on the wire as cm and the
firmware converts once, in ``gotoBuildTarget()``'s offset slot.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

#: The correction band, in cm, applied to the PICK offset magnitude.
#: PROVISIONAL — Stage 15 Stage B measures both bounds.
CORRECT_BAND_MIN_CM = 0.5
CORRECT_BAND_MAX_CM = 1.2

#: A block more than this many degrees off the grid axis cannot be gripped by
#: grid-aligned jaws: a 20 deg rotation presents a ~4 cm face to a 2.2 cm jaw
#: gap. `P` rotates the claw to the mode's rotation, not to the block's angle,
#: so a rotated block is a refusal.
ANGLE_TOLERANCE_DEG = 6.0

#: For a MOVED verdict the block is meant to be squarely on the wrong cell. If
#: its centroid is more than this far from that cell's centre the "it is on
#: [c,d]" reading is not trustworthy enough to grip on — refuse rather than
#: chase a bad cell assignment. Half a block (1.1 cm) plus a little.
MOVED_PICK_SANITY_CM = 1.3

#: The only mode the first cut supports — see the module docstring.
SUPPORTED_MODES = ("vertical",)

#: Stricter than supervision's level-3 ceiling: a correction is level 0 only.
MAX_CORRECTION_LEVEL = 0

Band = str  # "IGNORE" | "CORRECT" | "REFUSE"


@dataclass(frozen=True)
class Correction:
    """A pick-and-re-place the machine is allowed to perform. Frozen.

    ``pick_*`` is where the block is now; ``place_*`` is where it belongs.
    ``dx_cm`` / ``dy_cm`` are the pick nudge in cm magnitudes from each home
    switch (``+`` away from home), added in the firmware's build-offset slot on
    the PICK leg only — the place leg sends ``0, 0``. ``magnitude_cm`` is
    ``hypot(dx, dy)``, the number the band was judged on. ``verdict`` is the
    supervision verdict this came from, for the log and the UI copy.
    """

    verdict: str
    pick_cell: tuple[int, int]
    pick_level: int
    place_cell: tuple[int, int]
    place_level: int
    dx_cm: float
    dy_cm: float
    magnitude_cm: float

    @property
    def command_args(self) -> tuple:
        """The eight ``P`` arguments: pick col/row/level, dx, dy, place col/row/level."""
        return (self.pick_cell[0], self.pick_cell[1], self.pick_level,
                round(self.dx_cm, 3), round(self.dy_cm, 3),
                self.place_cell[0], self.place_cell[1], self.place_level)


def judge_band(magnitude_cm: float) -> Band:
    """Where a pick-offset magnitude falls relative to the correction band."""
    if magnitude_cm < CORRECT_BAND_MIN_CM:
        return "IGNORE"
    if magnitude_cm > CORRECT_BAND_MAX_CM:
        return "REFUSE"
    return "CORRECT"


def correction_offset(observed_cm: tuple[float, float],
                      target_cm: tuple[float, float]) -> tuple[float, float]:
    """``(dx, dy)`` = observed centre - the map's pick-cell centre, magnitude space.

    Both operands are in the workspace map's ``(u,v)*workspace_cm`` frame, which
    is a magnitude from each home switch (``+`` away from home), so the
    subtraction is done directly — Rule 0a rule 1, all offset arithmetic in
    magnitude space, converted to a signed position once and only in firmware.
    """
    return (observed_cm[0] - target_cm[0], observed_cm[1] - target_cm[1])


def axis_deviation_deg(angle_deg: float) -> float:
    """How far a measured block angle is from the nearest grid axis, in [0, 45].

    The detector's angle has no consistent zero across the 0/90/180/-90
    equivalent orientations of a rectangle, so the test is "near ANY multiple
    of 90 degrees", not "near zero".
    """
    return abs((angle_deg + 45.0) % 90.0 - 45.0)


def _reject(reason: str):
    return None, reason


def assess(*, verdict: str, mode: str,
           plan_cell: tuple[int, int], plan_level: int | None,
           where_cell: tuple[int, int], observed_cm: tuple[float, float] | None,
           map_pick_centre_cm: tuple[float, float] | None, angle_deg: float,
           plan_cell_clear: bool, taller_neighbour_pick: bool,
           taller_neighbour_place: bool,
           pick_is_top_of_column: bool) -> tuple[Correction | None, str]:
    """May the claw correct this verdict? Returns ``(Correction | None, reason)``.

    ``plan_cell`` / ``plan_level`` is where the block belongs (the ledger's
    ``[a,b]`` and its top level there). ``where_cell`` is the cell the block is
    physically on or beside — equal to ``plan_cell`` for DISPLACED, the wrong
    cell ``[c,d]`` for MOVED. ``observed_cm`` is the block's measured centre and
    ``map_pick_centre_cm`` is ``mapped_grid.cell_center_cm(where_cell)``.

    ``reason`` is always a sentence: with a :class:`Correction` it says the
    block can be returned and how far it is off; with ``None`` it says exactly
    why not, for the operator. ``/api/supervision/correct`` re-runs this same
    function rather than trusting the published flag — a correction is motion,
    so the client's copy is never authoritative (DESIGN.md §8).
    """
    if verdict not in ("MOVED", "DISPLACED"):
        return _reject("only a MOVED or DISPLACED block can be returned by the claw")
    if mode not in SUPPORTED_MODES:
        return _reject(f"{mode} correction is not supported")
    if observed_cm is None or map_pick_centre_cm is None:
        return _reject("no calibrated map, so the block's position is not known in cm")
    if plan_level is None:
        return _reject(f"the ledger has no block for {list(plan_cell)} to return")
    if plan_level > MAX_CORRECTION_LEVEL:
        return _reject(f"the block for {list(plan_cell)} is at level {plan_level}; "
                       f"only level 0 can be corrected")
    if not pick_is_top_of_column:
        return _reject(f"something is stacked on {list(where_cell)}")
    if taller_neighbour_pick:
        return _reject(f"a neighbouring stack is taller than the descent corridor "
                       f"beside {list(where_cell)}")
    if taller_neighbour_place and where_cell != plan_cell:
        return _reject(f"a neighbouring stack is taller than the descent corridor "
                       f"beside {list(plan_cell)}")
    if not plan_cell_clear:
        return _reject(f"{list(plan_cell)} is not clear to place into")

    deviation = axis_deviation_deg(angle_deg)
    if deviation > ANGLE_TOLERANCE_DEG:
        return _reject(f"the block is rotated {deviation:.0f} deg off the grid; "
                       f"straighten it by hand")

    dx, dy = correction_offset(observed_cm, map_pick_centre_cm)
    magnitude = math.hypot(dx, dy)

    if verdict == "MOVED":
        # The block is meant to be squarely on the wrong cell. A big pick offset
        # means the "it is on [c,d]" reading is shaky — do not grip on it.
        if magnitude > MOVED_PICK_SANITY_CM:
            return _reject(f"the block is {magnitude:.2f} cm off {list(where_cell)}; "
                           f"too far to be sure which cell it is on")
        correction = Correction(
            verdict="MOVED", pick_cell=(int(where_cell[0]), int(where_cell[1])),
            pick_level=0, place_cell=(int(plan_cell[0]), int(plan_cell[1])),
            place_level=int(plan_level), dx_cm=dx, dy_cm=dy, magnitude_cm=magnitude)
        return correction, (f"the block is on {list(where_cell)} instead of "
                            f"{list(plan_cell)}; the claw can move it back")

    # DISPLACED: the block is in a gap beside its own cell. The pick offset is
    # how far it is from that cell centre, and the band gates it.
    band = judge_band(magnitude)
    if band == "IGNORE":
        return _reject(f"the block is only {magnitude:.2f} cm off its cell — below "
                       f"the {CORRECT_BAND_MIN_CM:g} cm floor, not worth disturbing")
    if band == "REFUSE":
        return _reject(f"the block is {magnitude:.2f} cm off its cell — beyond the "
                       f"{CORRECT_BAND_MAX_CM:g} cm limit; its edge is against a "
                       f"neighbour, so clear it by hand")
    correction = Correction(
        verdict="DISPLACED", pick_cell=(int(plan_cell[0]), int(plan_cell[1])),
        pick_level=int(plan_level), place_cell=(int(plan_cell[0]), int(plan_cell[1])),
        place_level=int(plan_level), dx_cm=dx, dy_cm=dy, magnitude_cm=magnitude)
    return correction, (f"the block is {magnitude:.2f} cm off {list(plan_cell)}, "
                        f"in the gap; the claw can pick it up and set it back")

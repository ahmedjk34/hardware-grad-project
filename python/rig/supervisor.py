#!/usr/bin/env python3
"""Does the board match the plan? — the subtraction, and the discipline.

    error  =  what SHOULD be on the board  -  what IS on the board

:mod:`rig.placement_ledger` is the left operand. ``ProcessedFrame.detections``
plus a ``WorkspaceMap`` are the right one. This module is the subtraction, and
it lives in ``rig/`` rather than ``vision/`` for the reason CAMERA.md §5a gives:
it needs the ledger, the grid mode and whether the gantry is parked, none of
which a per-frame detector may know about.

**``vision/`` is not touched.** No detector is added, no second analysis path,
no extra frames. Supervision is a fourth layer above ``block_outline`` and it
reaches past nothing (BLOCK-VISION §7).

Three things here are easy to get wrong and are called out where they happen:

1. **Detections are not labelled with cells.** ``_lattice_filter`` solves
   indices relative to ``detections[0]`` only to decide keep/reject and then
   discards them. Pixel -> cell is :meth:`WorkspaceMap.cell_at` and it is this
   module's own work — see :func:`observe`.
2. **``cell_at`` returning None in a GAP is signal, not a dropout** — a block
   on the board and not on a site, which is FOREIGN-shaped. See :func:`observe`.
3. **Hysteresis counters RESET when an interlock trips**, they do not decay. A
   frame that was not allowed to be judged must not leak partial evidence into
   the next verdict.

A verdict NEVER locks the session. ``LOCKED`` means the claw's position is
unknown and needs a human plus a service restart; a verdict is a statement
about the *board*, not the *machine*. Amber verdicts pause, red ones stop.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import math

import numpy as np

from rig.placement_geometry import axis_coverage, residual_cm as _residual_cm

# ── Gate 0's outputs. MEASURED ON THE RIG, 2026-09-07. ────────────────────── #
#
# Three 60/20 s runs with 5 rig-placed blocks, camera calibrated, at the
# pipeline's measured 8.6-8.7 Hz (not the nominal 10):
#
#   parked, hands off   diff p99 0.000573, worst max across runs 0.003855
#   hand over the board diff p50 0.070745  — 105x the parked median
#   during a program    42-47% of frames quiet, ~9 runs of >=5 quiet frames/min
#
# The still floor and the disturbed ceiling are separated by more than an order
# of magnitude, so the threshold sits in a wide empty band rather than on a
# judgement call. 0.01 is 4x above the worst parked maximum and 7x below the
# median hand disturbance; at it, parked reads quiet 99.8% and a hand 8.6%.
#
# 3-of-5 was simulated against the real parked trace and read the cell occupied
# in 100.00% of windows on all five cells. Both neighbours are worse (2-of-3:
# 97.70%, 4-of-6: 98.07%), so this is a measured optimum, not a default.
QUIET_DIFF_FRACTION = 0.01
SETTLE_N = 3
SETTLE_M = 5

#: Per-pixel level at which a channel-max difference counts as a changed pixel.
#: `vision/block_grid.py`'s DIFF_MIN_THRESHOLD, so the quiet gate is measured
#: on the same footing as the one detector in the repo that already differences
#: frames — and on the same footing as the Gate 0 script.
PIXEL_THRESHOLD = 18

#: D6. Above this expected top level, `_lattice_filter` drops an elevated block
#: because parallax has eaten the 0.34-cell LATTICE_SNAP budget. An absent
#: detection there is a FILTER ARTIFACT, not a missing block, so supervision
#: refuses to judge the cell at all and lists it as `unjudged`. Never report
#: NOT_DETECTED or REMOVED for one — that would be the feature lying.
LEVEL_CEILING = 3

#: D5's "gantry parked" gate, as a set of `CellOrchestrator` phases — and NOT
#: the design's `cell_phase == "idle"`, which does not work.
#:
#: `idle` is only ever the value BEFORE the first cell operation of a process.
#: `CellOrchestrator._phase("complete")` is terminal and sticky: nothing resets
#: it, so after the first placed block `cell_phase` reads `complete` until the
#: next build starts. Gating on `"idle"` would therefore wedge supervision at
#: BUSY for the whole of every session after block one — silently, and in
#: exactly the situation the feature exists for.
#:
#: The complement is the honest question: `feeding`, `staging`, `ready_for_pick`
#: and `placing` are the phases in which a cell operation is IN FLIGHT and the
#: arm may be over the board; `error` is not parked either, whatever else is
#: true. `idle` and `complete` both mean nothing is in flight. Conservative on
#: purpose — a false BUSY costs one missed window out of the ~9 per minute
#: §1.8 measured, and a false QUIET costs a wrong verdict.
PARKED_CELL_PHASES = ("idle", "complete")

#: The observer's own states. BUSY and QUIET and NO_MEMORY are NOT faults and
#: must not take a state colour in the UI: BUSY is the normal condition for the
#: whole of a build, and colouring it amber would leave the console amber most
#: of the time, which kills DESIGN.md's reserved palette.
#:
#: NO_VISION is not produced by :meth:`Supervisor.step` — it is raised one layer
#: up, in ``web/app.py``'s ``_supervise``, when the analysis result carried a
#: detector exception or its source image had already gone stale. It exists so
#: "vision could not observe the board" is never collapsed into "a successful
#: detection that saw zero blocks": the first must never become REMOVED, and the
#: distinction has to survive into the published state, not just the verdict.
STATES = ("NO_MEMORY", "NO_MAP", "NO_VISION", "WARMING", "BUSY", "QUIET",
          "VERDICT")

#: A DISPLACED verdict pairs the ONE emptied cell with the ONE gap detection by
#: pure set difference (`classify`); it never checks the two are near each other.
#: If the gap block sits more than this far PAST the neighbour of the cell it was
#: paired with (`axis_coverage.beyond` — ~0 for a real single-cell displacement,
#: growing once the two are over a pitch apart), the pairing is not credible:
#: the block that left and the block in the gap are probably different blocks, or
#: the workspace map is misregistered to the lattice. `step()` downgrades such a
#: verdict to DISAGREES so the runner stops for a human. PROVISIONAL.
PAIRING_BEYOND_CM = 1.0

#: Amber — degraded but recoverable. The runner pauses.
#:
#: MOVED and DISPLACED are the same event — a block left the cell the plan put
#: it on — split by WHERE it ended up. MOVED landed on another valid cell;
#: DISPLACED is still inside the build area (cells + the gaps between them) but
#: on no site at all, knocked into a gap or against a margin. Both are
#: recoverable by hand, so both pause rather than stop; the split exists because
#: the operator does different things about them (re-run vs. straighten).
AMBER_VERDICTS = ("NOT_DETECTED", "REMOVED", "MOVED", "DISPLACED")
#: Red — stop, a human is required. The runner stops. Still never LOCKED.
RED_VERDICTS = ("FOREIGN", "DISAGREES")

Cell = tuple[int, int]


def _sorted(cells) -> tuple[Cell, ...]:
    return tuple(sorted(cells))


#: Where one detection sits. `cell_at` returns None for THREE different facts
#: and only one of them is evidence about the board — measured on the rig on
#: 2026-09-07, where one persistent off-lattice object appeared in 523 of 524
#: parked frames. A classifier reading every None as FOREIGN would have stopped
#: the machine in 99.8% of windows on a board that was completely correct.
PLACEMENTS = ("cell", "gap", "margin", "outside")


@dataclass(frozen=True)
class DetectionRecord:
    """One detection kept WHOLE — item 6's "preserve per-cell multiplicity".

    :func:`observe` collapses the occupied cells to a set and keeps only the
    FIRST detection per cell for the legacy ``cell_points_cm`` / ``cell_*``
    arrays. This is the parallel, un-deduplicated list — one entry per detection
    in detector order — so the track layer (:class:`_TrackHistory`) can see two
    detections sitting on one cell (a merged blob, a duplicate hypothesis, a
    decomposed compound) instead of silently taking the first and calling it a
    clean block.
    """

    placement: str                        #: one of :data:`PLACEMENTS`
    cell: Cell | None
    centre_cm: tuple[float, float] | None  #: None for "margin" / "outside"
    angle_deg: float
    size_cm: tuple[float, float]           #: ``(long, short)``; ``(0.0, 0.0)`` if unknown


@dataclass(frozen=True)
class Observation:
    """What one accepted frame saw. M2's whole output — no verdict in here."""

    cells: tuple[Cell, ...]
    #: Detections inside the envelope AND inside the grid allocation but in one
    #: of the deliberate gaps between block footprints. THE signal D9 wants: a
    #: block on the board and not on a site.
    in_gap: int = 0
    #: Detections outside the board altogether — the frame-edge rails, the
    #: holder's offcuts, anything beside the envelope. NOT evidence. Counted so
    #: it can be shown, never classified.
    off_board: int = 0
    #: Total detections in the frame, before any of this. Display-only — the
    #: classifier no longer branches on it (D10 removed once the holder was
    #: gone; `locate()` classifies at any count).
    detections: int = 0
    #: Map-frame cm centre and measured angle (deg) of every `in_gap` detection
    #: — parallel arrays, one entry each. Kept ONLY for the operator CORRECTION
    #: action, which needs a pick coordinate for a DISPLACED block
    #: (`rig/placement_check.py`). Empty for every other consumer; the
    #: classifier never looks at them.
    gap_points_cm: tuple[tuple[float, float], ...] = ()
    gap_angles_deg: tuple[float, ...] = ()
    #: Same, for the FIRST detection seen on each occupied cell — `(cell, (x_cm,
    #: y_cm))` pairs and a parallel angle array. The CORRECTION action needs the
    #: centre of the block on the *wrong* cell to correct a MOVED verdict.
    cell_points_cm: tuple[tuple[Cell, tuple[float, float]], ...] = ()
    cell_angles_deg: tuple[float, ...] = ()
    #: Map-frame `(long_cm, short_cm)` footprint of each `in_gap` detection, from
    #: the block's OWN measured box (`BlockDetection.own_size`), NOT the lattice
    #: median — a misplaced block IS the wrong size, and the CORRECTION action's
    #: consistency check needs to see that. Parallel to `gap_points_cm`; `(0, 0)`
    #: when the map cannot project the box. Empty for every other consumer.
    gap_sizes_cm: tuple[tuple[float, float], ...] = ()
    #: Same, for the first detection on each occupied cell. Parallel to
    #: `cell_points_cm`.
    cell_sizes_cm: tuple[tuple[float, float], ...] = ()
    #: ADVISORY. `(cell, residual_cm)` for each occupied cell — how far that
    #: block's centre is from the cell's own lattice centre. The classifier
    #: does NOT branch on this; it exists so a VERIFIED board can still report
    #: "the worst block is 0.8 cm off" ([[placement-drift]]). `()` with no map.
    cell_residuals_cm: tuple[tuple[Cell, float], ...] = ()
    #: ITEM 6. Every detection kept whole and un-deduplicated, in detector
    #: order — the multiplicity the CORRECTION track layer needs and the
    #: collapsed arrays above discard. Empty on hand-built test observations,
    #: which :class:`_TrackHistory` tolerates by falling back to those arrays.
    detections_detail: tuple[DetectionRecord, ...] = ()


@dataclass(frozen=True)
class Verdict:
    """One judgement about the board. Frozen; the server publishes it whole."""

    verdict: str
    cells: tuple[Cell, ...]
    mode: str
    expected: tuple[Cell, ...]
    observed: tuple[Cell, ...]
    unjudged: tuple[Cell, ...]

    @property
    def severity(self) -> str:
        if self.verdict in RED_VERDICTS:
            return "red"
        if self.verdict in AMBER_VERDICTS:
            return "amber"
        return "none"


def quiet_fraction(view, baseline) -> float | None:
    """Fraction of pixels whose channel-max change clears PIXEL_THRESHOLD.

    D5's scene-quiet gate, and the ONLY numpy in this module. It is a
    full-frame op — ~5-15 ms at 1296 px on a Pi 5 — so it must run on the same
    single-threaded executor as ``pipeline.process_once`` and ``encode_jpeg``,
    per AGENTS.md §7's one-owner-thread rule. Do not call it on the event loop
    because it is "only a subtraction". Everything else here is set maths and
    belongs on the loop.

    Channel-max rather than a grey difference, matching
    ``block_grid._difference_sightings`` and Gate 0's own instrument: a pale
    wooden block on pale paper separates far better in one channel than in
    luminance, and which channel that is depends on the cast of the day.
    Measuring the gate on a different footing from the script that chose its
    threshold would make ``QUIET_DIFF_FRACTION`` describe nothing.

    Returns None when there is no usable baseline — the first frame of a
    session, and the frame after a mode latch. :meth:`Supervisor.is_quiet`
    reads None as NOT quiet, which is the fail-closed direction.
    """
    if baseline is None or getattr(baseline, "shape", None) != view.shape:
        return None
    difference = np.abs(view.astype(np.int16) - baseline.astype(np.int16)).max(axis=2)
    return float(np.count_nonzero(difference >= PIXEL_THRESHOLD)) / float(difference.size)


def locate(workspace, point, image_size):
    """Where one detection sits: ``(cell_or_None, placement)``.

    ``WorkspaceMap.cell_at`` collapses three different facts into one None, and
    supervision must not. Mirrors its own branches rather than guessing:

    1. ``normalized_at`` outside [0,1] on either axis  -> ``"outside"``
    2. inside the quad, off the grid's cm allocation   -> ``"margin"``
    3. ``cell_at`` named a cell                        -> ``"cell"``
    4. otherwise                                        -> ``"gap"``

    Only ``"gap"`` is evidence about the board. ``"margin"`` and ``"outside"``
    are the rails and the offcuts, and BLOCK-VISION is explicit that they are
    normal on an untidy bench. This split is what makes supervision's junk
    defence independent of ``block_outline._lattice_filter``: it classifies
    every detection by geometry, at any detection count.
    """
    u, v = workspace.normalized_at(point, image_size)
    epsilon = 1e-9
    if u < -epsilon or v < -epsilon or u > 1 + epsilon or v > 1 + epsilon:
        return None, "outside"

    cell = workspace.cell_at(point, image_size)
    if cell is not None:
        return (int(cell[0]), int(cell[1])), "cell"

    grid = getattr(workspace, "mapped_grid", None)
    if grid is None:
        # No physical grid in the map, so there are no gaps to be in: cell_at's
        # own fallback divides the quad evenly and always answers.
        return None, "margin"
    x_cm = min(max(u, 0.0), 1.0) * grid.workspace_width_cm
    y_cm = min(max(v, 0.0), 1.0) * grid.workspace_height_cm
    if (x_cm < grid.x_start_cm - epsilon or x_cm > grid.x_end_cm + epsilon
            or y_cm < grid.y_start_cm - epsilon or y_cm > grid.y_end_cm + epsilon):
        return None, "margin"
    return None, "gap"


def point_cm(workspace, point, image_size):
    """Workspace-cm centre of an image point, or None with no physical grid.

    The map's ``(u, v)`` times its own ``workspace_*_cm`` — a magnitude from
    each home switch, ``+`` away from home, which is the frame every calibration
    knob in AGENTS.md is written in and the one a displaced block's pick
    coordinate has to be in. :func:`locate` already does this arithmetic
    internally for its margin test; this exposes it for the CORRECTION action.
    """
    grid = getattr(workspace, "mapped_grid", None)
    if grid is None:
        return None
    u, v = workspace.normalized_at(point, image_size)
    return (float(u) * grid.workspace_width_cm, float(v) * grid.workspace_height_cm)


def _detection_size_cm(workspace, detection, image_size):
    """`(long_cm, short_cm)` footprint of a detection, from its OWN measurement.

    Built from ``own_size`` / ``own_angle`` — the block's pre-rectification
    values — so a misplaced block reads as its real size, not the population
    median ``block_outline._rectify`` substitutes for every on-lattice block.
    Falls back to projecting ``detection.box`` when ``own_size`` is absent (a
    bare test double). None when the map has no physical grid or a corner will
    not project. The result is an axis-aligned cm bounding box, which is what
    the CORRECTION action's consistency check wants (it only acts on blocks
    within ``ANGLE_TOLERANCE_DEG`` of the grid anyway).
    """
    own = getattr(detection, "own_size", None)
    if own is not None and own[0] and own[1]:
        long_px, short_px = float(own[0]), float(own[1])
        angle = math.radians(float(getattr(detection, "own_angle", 0.0) or 0.0))
        ux, uy = math.cos(angle), math.sin(angle)         # long axis
        vx, vy = -uy, ux                                  # short axis
        cx, cy = detection.center
        pts = [(cx + sl * ux * long_px / 2 + ss * vx * short_px / 2,
                cy + sl * uy * long_px / 2 + ss * vy * short_px / 2)
               for sl, ss in ((1, 1), (1, -1), (-1, -1), (-1, 1))]
    else:
        box = getattr(detection, "box", None)
        pts = [(float(p[0]), float(p[1])) for p in box] if box is not None else []
    if len(pts) < 4:
        return None
    corners = []
    for px, py in pts:
        cm = point_cm(workspace, (px, py), image_size)
        if cm is None:
            return None
        corners.append(cm)
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    return (max(width, height), min(width, height))


def observe(detections, workspace, image_size) -> Observation:
    """Pixel -> cell for every detection. This is the supervisor's own work.

    ``block_outline._lattice_filter`` does NOT label detections with cells: it
    solves indices relative to ``detections[0]`` purely to decide keep/reject
    and then throws them away, returning plain ``BlockDetection`` objects that
    carry a pixel centre and nothing else. So the only route is
    :meth:`WorkspaceMap.cell_at`.

    ``cell_at`` returns None for two different facts and only one of them is a
    dropout:

    * outside the quadrilateral — not on the board, and not our business;
    * inside it but in one of the deliberate GAPS between block footprints —
      **a block is on the board and is not on a site**. That is a FOREIGN-shaped
      fact, and a block knocked half a cell sideways reads exactly this way.

    An earlier revision counted both as one ``off_lattice`` number and let the
    classifier read it as FOREIGN, on the grounds that separating them "would
    need the envelope quad". It does not — ``normalized_at`` already gives it —
    and the rig measurement showed the merge is not survivable: one persistent
    off-board object sat in 99.8% of parked frames and would have held the
    machine at FOREIGN indefinitely. :func:`locate` does the split.

    Never treat any of this as a dropout.
    """
    cells = []
    gap_points: list[tuple[float, float]] = []
    gap_angles: list[float] = []
    gap_sizes: list[tuple[float, float]] = []
    cell_points: dict[Cell, tuple[float, float]] = {}
    cell_angles: dict[Cell, float] = {}
    cell_sizes: dict[Cell, tuple[float, float]] = {}
    details: list[DetectionRecord] = []
    counts = {name: 0 for name in PLACEMENTS}
    for detection in detections:
        cell, placement = locate(workspace, detection.center, image_size)
        counts[placement] += 1
        # `own_angle` / `own_size` are the block's pre-rectification measurement
        # — `block_outline._rectify` would otherwise hand back the lattice
        # bearing and the population median for every block, correct or not.
        angle = float(getattr(detection, "own_angle", None)
                      if getattr(detection, "own_angle", None) is not None
                      else getattr(detection, "angle", 0.0) or 0.0)
        size = _detection_size_cm(workspace, detection, image_size)
        cm = point_cm(workspace, detection.center, image_size)
        # ITEM 6: record EVERY detection whole, before any per-cell collapse.
        details.append(DetectionRecord(
            placement=placement, cell=cell, centre_cm=cm, angle_deg=angle,
            size_cm=size if size is not None else (0.0, 0.0)))
        if cell is not None:
            cells.append(cell)
            if cell not in cell_points and cm is not None:
                cell_points[cell] = cm
                cell_angles[cell] = angle
                cell_sizes[cell] = size if size is not None else (0.0, 0.0)
        elif placement == "gap":
            # `locate` only returns "gap" when `mapped_grid` is set, so this
            # projection cannot come back None here.
            if cm is not None:
                gap_points.append(cm)
                gap_angles.append(angle)
                gap_sizes.append(size if size is not None else (0.0, 0.0))
    grid = getattr(workspace, "mapped_grid", None)
    cell_residuals: dict[Cell, float] = {}
    if grid is not None:
        for cell, observed in cell_points.items():
            try:
                lattice = grid.cell_center_cm(int(cell[0]), int(cell[1]))
            except ValueError:
                continue
            cell_residuals[cell] = _residual_cm(observed, lattice)

    return Observation(cells=_sorted(set(cells)), in_gap=counts["gap"],
                       off_board=counts["margin"] + counts["outside"],
                       detections=len(detections),
                       gap_points_cm=tuple(gap_points),
                       gap_angles_deg=tuple(gap_angles),
                       gap_sizes_cm=tuple(gap_sizes),
                       cell_points_cm=tuple(cell_points.items()),
                       cell_angles_deg=tuple(cell_angles[c] for c in cell_points),
                       cell_sizes_cm=tuple(cell_sizes[c] for c in cell_points),
                       cell_residuals_cm=tuple(
                           (c, cell_residuals[c]) for c in cell_points
                           if c in cell_residuals),
                       detections_detail=tuple(details))


def verify_placement(cell: Cell, level: int, occupied, *,
                     calibrated: bool = True) -> str:
    """D8a's narrow question: did a block appear at the cell just commanded?

    Returns the short string that becomes ``vision_verification`` — the runner
    log row and the thesis run report's Markdown column. One placement, one
    sentence, and it never claims more than it can see.

    ``occupied`` is whether the cell reads occupied in the settled observation,
    or None when the map refuses to answer.

    THE LEVELS DIFFER, and the difference is not cosmetic:

    * **level 0** — the ledger says the cell was empty before this build, so
      empty -> occupied is decisive in both directions. This is the case the
      run report is really about, and it is most of a short-tower build.
    * **levels 1-2** — the cell was ALREADY occupied, so occupancy cannot
      confirm the new block: an overhead camera sees the top of a stack whether
      that stack grew or not. A cell that reads EMPTY is still decisive — that
      is a tower that fell — so the negative is reported and the positive is
      not. The design wanted a frame difference against the pre-build frame
      here; that needs a measured per-cell change threshold nobody has taken
      (Gate 0b, progress.md F17), and a guessed one must never reach a rig.
    * **level >= 3** — D6. Parallax has eaten ``LATTICE_SNAP``, so an absent
      detection is a filter artifact rather than a missing block. Refused, and
      SAID, never silently skipped.

    Never the word "error": at levels 1-2 the machine may well have got it
    right and simply cannot prove it.
    """
    col, row = cell
    if level >= LEVEL_CEILING:
        return (f"unchecked — level {level} at [{col},{row}] is above the "
                f"detection ceiling")
    if not calibrated:
        return f"unchecked — no map, [{col},{row}] was not verified in frame"
    if occupied is None:
        return f"unchecked — [{col},{row}] did not settle before the next build"
    if not occupied:
        return f"not detected at [{col},{row}]"
    if level == 0:
        return f"verified in frame at [{col},{row}]"
    return (f"unconfirmed — [{col},{row}] holds a stack, and a new top block "
            f"cannot be told from the one under it from above")


def unjudged_cells(top_levels: dict[Cell, int]) -> tuple[Cell, ...]:
    """D6's refusals: cells whose expected top level is at or above the ceiling."""
    return _sorted(cell for cell, level in top_levels.items()
                   if level >= LEVEL_CEILING)


def classify(mode: str, expected, observed, *, top_levels=None,
             in_gap: int = 0) -> Verdict:
    """D9's set difference. Pure — no frames, no time, no I/O.

    ``expected`` is ``ledger.expected_occupancy(mode)``; ``observed`` is
    :attr:`Observation.cells`; ``in_gap`` is the count of detections that are ON
    the board and not on a site — and only that count, never
    :attr:`Observation.off_board`, which is rails and offcuts. The one
    suppression left is D6's level ceiling.

    D10's sparse-board rule was removed once the holder was taken off the rig:
    its only surviving rationale was the holder's offcuts beside ``[0,0]``
    reading as ``gap`` -> FOREIGN, and :func:`locate` already classifies junk
    by geometry at any detection count. The consequence is deliberate — FOREIGN
    and DISAGREES are now live from the first placed block, including on block
    one after a restart with blocks still on the board.

    Neither MOVED nor DISPLACED claims it is the same block. Twenty-nine
    identical wooden rectangles carry no identity and no proof is available
    ([[block-identity]]). Neither needs one: with exactly one cell emptied and
    exactly one thing arriving — on a cell (MOVED) or in the build area off
    every site (DISPLACED) — the only story is that that block moved, and the
    window it is judged in has no occlusion by construction (D5). The actionable
    fact is where it ended up, which is what the split reports.

    THE VERDICTS, keyed to the BUILD AREA — the rectangle of cells plus the
    gaps between them, which `locate()` already draws from the grid:

    * VERIFIED   — the board matches the plan.
    * MOVED      — one cell emptied, one different cell filled. A relocation to
                   a valid site. `cells` = (from, to).
    * DISPLACED  — one cell emptied, one detection is in the build area but on
                   no site (a gap or a margin). Recoverable by hand; the runner
                   pauses. `cells` = (from,).
    * REMOVED    — cells emptied and NOTHING arrived anywhere in the build area.
                   By elimination the block(s) left the build area — or were
                   taken off the top of a stack, the D4 limit. Never asserts
                   more than "not seen on the build grid".
    * FOREIGN    — a block is in the build area (on a cell, or in a gap) that
                   the plan cannot account for by anything having LEFT.
    * DISAGREES  — both sides changed, or the change cannot be paired one to
                   one. The classifier declining to guess. Stops the program.

    ``in_gap`` is the count of detections that are ON the board and not on a
    site — never :attr:`Observation.off_board`, which is rails and offcuts.
    The one suppression left is D6's level ceiling.

    D10's sparse-board rule was removed once the holder was taken off the rig:
    its only surviving rationale was the holder's offcuts beside ``[0,0]``
    reading as ``gap`` -> FOREIGN, and :func:`locate` already classifies junk
    by geometry at any detection count.
    """
    top_levels = top_levels or {}
    refused = set(unjudged_cells(top_levels))
    expected = set(expected) - refused
    observed = set(observed) - refused

    missing = expected - observed
    unexpected = observed - expected

    def made(name, cells):
        return Verdict(verdict=name, cells=_sorted(cells), mode=str(mode),
                       expected=_sorted(expected), observed=_sorted(observed),
                       unjudged=_sorted(refused))

    if not missing and not unexpected and not in_gap:
        return made("VERIFIED", ())

    # One out, one onto a valid cell: a clean relocation. `cells` ordered
    # (from, to) — the UI draws an arrow between them.
    if len(missing) == 1 and len(unexpected) == 1 and not in_gap:
        return made("MOVED", (missing.pop(), unexpected.pop()))

    # One out, exactly one thing in the build area off every site: that block
    # was knocked into a gap. Same event as MOVED, different landing, still
    # recoverable by hand. Needs identity no more than MOVED does — one in, one
    # out, no occlusion in the window. `cells` = (from,); there is no "to" cell.
    if len(missing) == 1 and not unexpected and in_gap == 1:
        return made("DISPLACED", (next(iter(missing)),))

    # ── P1: the ONE-SIDED rows. A refinement of D9, decided with the user.
    #
    # DISAGREES protects against the absence of IDENTITY: two cells empty and
    # two fill and no memory can say which became which. But that only matters
    # when there is something to pair WITH. Nothing arrived anywhere in the
    # build area -> nothing to pair -> naming the emptied cells is strictly
    # more use than declining to. A block in the build area with nothing having
    # left is FOREIGN for the mirror reason: the plan cannot account for it.
    if not missing and (unexpected or in_gap):
        return made("FOREIGN", unexpected)
    if missing and not unexpected and not in_gap:
        return made("REMOVED", missing)

    # BOTH sides changed, or the change will not pair one to one (two out and
    # one in a gap, one out and two in gaps, a shifted board). The case that
    # needs identity and cannot have it — the classifier declining to guess.
    # Stops the program rather than pausing it.
    return made("DISAGREES", missing | unexpected)


def implausible_displacement(grid, plan_cell: Cell, observation: Observation) -> str | None:
    """Why a DISPLACED pairing is not geometrically credible, or None if it is.

    :func:`classify` names ``plan_cell`` (the one emptied cell) as the origin of
    the one gap detection by SET DIFFERENCE alone — it never checks the two are
    near each other. This does: :func:`~rig.placement_geometry.axis_coverage`'s
    ``beyond`` is the cm the gap block reaches PAST the neighbour of
    ``plan_cell`` on each axis, which is ~0 for a real single-cell displacement
    and grows once they are more than a pitch apart. Over
    :data:`PAIRING_BEYOND_CM` the pairing is rejected — different blocks, or a
    misregistered map — and :meth:`Supervisor.step` turns the verdict into
    DISAGREES.
    """
    if not observation.gap_points_cm:
        return None
    try:
        planned = grid.cell_center_cm(int(plan_cell[0]), int(plan_cell[1]))
    except (ValueError, TypeError):
        return None
    observed = observation.gap_points_cm[0]
    cov_x = axis_coverage(observed_centre=observed[0], planned_centre=planned[0],
                          block_len=grid.block_x_cm, gap_len=grid.gap_x_cm,
                          pitch=grid.pitch_x_cm)
    cov_y = axis_coverage(observed_centre=observed[1], planned_centre=planned[1],
                          block_len=grid.block_y_cm, gap_len=grid.gap_y_cm,
                          pitch=grid.pitch_y_cm)
    beyond = max(cov_x.beyond, cov_y.beyond)
    if beyond <= PAIRING_BEYOND_CM:
        return None
    return (f"a block in the gap sits {beyond:.1f} cm past the cell "
            f"[{int(plan_cell[0])},{int(plan_cell[1])}] it was paired with — "
            f"the classifier cannot confirm the same block moved")


class _CellHistory:
    """The last M readings of every cell. D7's confidence, per cell.

    A sliding N-of-M over ALREADY-QUIET frames, deliberately — and this is a
    different question from the quiet gate itself, which tolerates nothing. The
    quiet gate asks "was the scene still", and a busy frame is discarded before
    it ever reaches here. This asks "did the detector agree with itself", where
    D7 explicitly wants tolerance: a single-frame dropout is jitter, two
    consecutive dropouts in a quiet, parked, settled scene are an event.
    """

    def __init__(self, settle_n: int, settle_m: int) -> None:
        self._n = settle_n
        self._m = settle_m
        self._readings: dict[Cell, deque] = {}

    def reset(self) -> None:
        """D7: counters RESET, never decay. Called on every tripped interlock."""
        self._readings.clear()

    def update(self, cells_of_interest, observed) -> None:
        seen = set(observed)
        for cell in cells_of_interest:
            history = self._readings.setdefault(cell, deque(maxlen=self._m))
            history.append(cell in seen)

    def settled(self, cell: Cell) -> bool | None:
        """True/False once N of the last M agree; None while still warming."""
        history = self._readings.get(cell)
        if history is None or len(history) < self._n:
            return None
        occupied = sum(history)
        if occupied >= self._n:
            return True
        if len(history) - occupied >= self._n:
            return False
        return None

    def warming(self, cells_of_interest) -> tuple[Cell, ...]:
        return _sorted(cell for cell in cells_of_interest
                       if self.settled(cell) is None)

    def settled_occupancy(self, cells_of_interest) -> tuple[Cell, ...]:
        return _sorted(cell for cell in cells_of_interest
                       if self.settled(cell) is True)


#: Two gap detections within this cm distance across consecutive judged frames
#: are ONE persistent gap identity; farther apart they are different gaps and
#: each carries its own N-of-M evidence. This is the per-key hysteresis that
#: `_CellHistory` gives a cell and that `in_gap` — a bare per-frame count — used
#: to have no equivalent of: three "a gap exists" votes could come from three
#: different objects or locations, and one gap-free frame cleared a settled gap
#: with no counter-evidence. PROVISIONAL: wants the same rig measurement as
#: :data:`PAIRING_BEYOND_CM` (audit §5.2). Half a vertical pitch is ~1.9 cm, so
#: 2.0 cm keeps one jittering block as one identity while a neighbouring gap a
#: full pitch away reads as a new one.
GAP_IDENTITY_MATCH_CM = 2.0


@dataclass
class _GapTrack:
    """One persistent gap identity: a map-frame cm anchor (None when the frame
    gave only a count) and its last-M occupied/absent readings."""

    anchor: tuple[float, float] | None
    readings: deque


class _GapHistory:
    """The last M readings of every distinct gap identity — `_CellHistory` for gaps.

    ``in_gap`` reaches :func:`classify` as a count, and it used to be hysteresed
    by one global ``deque[bool]``: any frame with a gap appended True, any
    gap-free frame appended False, and the settled verdict was then rendered
    from the CURRENT frame's count regardless of the history. So one detector
    dropout cleared a stable DISPLACED/FOREIGN with no N-of-M, and three votes
    from three different objects settled as though they were one gap.

    Each gap detection now carries a spatial identity (its map-frame cm centre),
    associated frame to frame within :data:`GAP_IDENTITY_MATCH_CM`. A gap is
    reported only once N of its OWN last M frames saw it, and it keeps being
    reported until N of the last M frames agree it is gone — clearing is
    hysteresed exactly like asserting, not read off the current frame. A gap
    whose position jumps past the match radius is a NEW identity that starts its
    N-of-M from nothing; the old one decays and is forgotten, so no evidence is
    inherited across the change.

    Frames that carry a bare ``in_gap`` count with no coordinates (older rig
    instrumentation, synthetic traces) fall back to anonymous slots keyed by
    position in the list: the count still hystereses symmetrically, but with no
    coordinates there is no spatial identity to give it.
    """

    def __init__(self, settle_n: int, settle_m: int,
                 match_cm: float = GAP_IDENTITY_MATCH_CM) -> None:
        self._n = int(settle_n)
        self._m = int(settle_m)
        self._match_cm = float(match_cm)
        self._tracks: list[_GapTrack] = []

    def reset(self) -> None:
        """Counters RESET, never decay — reached through
        :meth:`Supervisor._reset_hysteresis` on every tripped interlock, mode
        latch and memory loss, the SAME primitive `_CellHistory` resets on, so
        gap evidence can never outlive the cell evidence gathered beside it."""
        self._tracks.clear()

    def _state(self, readings) -> bool | None:
        """True/False once N of the last M readings agree; None while warming."""
        if len(readings) < self._n:
            return None
        present = sum(readings)
        if present >= self._n:
            return True
        if len(readings) - present >= self._n:
            return False
        return None

    def update(self, observation) -> None:
        """One judged frame's gap detections, associated to the live identities."""
        points: list = list(observation.gap_points_cm)
        if not points and observation.in_gap > 0:
            points = [None] * int(observation.in_gap)

        matched_tracks: set[int] = set()
        matched_points: set[int] = set()

        # Coordinates -> nearest free anchored track within the match radius,
        # greedy on distance so the closest pairing wins.
        candidates = []
        for pi, p in enumerate(points):
            if p is None:
                continue
            for ti, track in enumerate(self._tracks):
                if track.anchor is None:
                    continue
                distance = math.hypot(p[0] - track.anchor[0],
                                      p[1] - track.anchor[1])
                if distance <= self._match_cm:
                    candidates.append((distance, pi, ti))
        for _distance, pi, ti in sorted(candidates):
            if pi in matched_points or ti in matched_tracks:
                continue
            matched_points.add(pi)
            matched_tracks.add(ti)
            point = points[pi]
            track = self._tracks[ti]
            track.readings.append(True)
            track.anchor = (0.6 * track.anchor[0] + 0.4 * float(point[0]),
                            0.6 * track.anchor[1] + 0.4 * float(point[1]))

        # Bare-count detections -> free anonymous tracks, in list order.
        free_anon = [ti for ti, track in enumerate(self._tracks)
                     if track.anchor is None and ti not in matched_tracks]
        anon_points = [pi for pi, p in enumerate(points) if p is None]
        for slot, pi in enumerate(anon_points):
            if slot >= len(free_anon):
                break
            ti = free_anon[slot]
            matched_points.add(pi)
            matched_tracks.add(ti)
            self._tracks[ti].readings.append(True)

        # Every identity that matched nothing this frame gets a negative reading
        # — this is what makes clearing symmetric with asserting.
        for ti, track in enumerate(self._tracks):
            if ti not in matched_tracks:
                track.readings.append(False)

        # Detections that matched no existing identity open a fresh one.
        for pi, p in enumerate(points):
            if pi in matched_points:
                continue
            self._tracks.append(_GapTrack(
                anchor=(float(p[0]), float(p[1])) if p is not None else None,
                readings=deque([True], maxlen=self._m)))

        # Decay: forget an identity once N of its last M frames say it is gone,
        # so a later reappearance is a new identity warming from nothing.
        self._tracks = [track for track in self._tracks
                        if self._state(track.readings) is not False]

    def settled_gap_count(self) -> int:
        """Distinct gap identities settled OCCUPIED — the ``in_gap`` the
        classifier sees, never the raw per-frame count."""
        return sum(1 for track in self._tracks
                   if self._state(track.readings) is True)


# ── ITEM 6 + 9: one coherent, stable, block-consistent track ────────────── #
#
# audit §1 (MOVED/DISPLACED "collapses detections to a set and stores only the
# first detection per cell"), §2.4 ("fuse centres/angles/sizes over the quiet
# evidence window ... report covariance/dispersion"), §3.2 ("per-cell/per-gap
# candidate lists and persistent tracks"), §6.2 ("a provenance-coherent robust
# track centre ... carry a covariance through the full motion preflight").
#
# `_GapHistory` (item 7) hystereses the CLASSIFIER's `in_gap` count. This is
# its sibling for the operator CORRECTION action: it associates every
# block-shaped detection — on a cell or in a gap — frame to frame across the
# SAME N-of-M quiet window `_CellHistory` already uses (no extra frames, no
# second analysis path, audit §2.4 constraint) and fuses the matched run into
# one robust centre / angle / size with an explicit dispersion and a worst
# per-frame residual. `assess_frame_correction` refuses a MOVED / DISPLACED
# correction unless exactly ONE such track is settled, unambiguous and stable
# at the block's position, and then uses the fused centre in place of the
# single-frame centroid the pick offset was computed from.

#: Two block detections within this cm distance across consecutive judged
#: frames are ONE track identity; a centroid that jumps farther is a candidate
#: switch and starts a NEW track that has to warm from nothing. Deliberately
#: TIGHTER than :data:`GAP_IDENTITY_MATCH_CM` (2.0): that one only has to
#: separate a gap from another gap a full pitch away, whereas a track has to
#: separate a displaced block from its adjacent neighbour cell — only half a
#: pitch (~1.9 cm vertical) away — while still absorbing the sub-cm frame-to-
#: frame centroid jitter the map's 0.27 cm residual produces. PROVISIONAL, same
#: rig-measurement need as :data:`GAP_IDENTITY_MATCH_CM` (audit §5.2 / §7.5).
TRACK_IDENTITY_MATCH_CM = 1.2

#: A track's neighbour within this cm is close enough to be a candidate-switch
#: ALTERNATIVE for the same block rather than a different block. Under one
#: vertical pitch (3.8 cm) so a real neighbour a full cell away never counts;
#: the anti-phase presence test (`_looks_like_switch`) is what actually tells a
#: switch from an occupied neighbour, this only bounds the search. PROVISIONAL.
SWITCH_NEIGHBOUR_CM = 3.0

#: Item 9 uncertainty ceilings for a track to back a correction. Each is a
#: dispersion across the ALREADY-collected quiet window, not a new measurement.
#: PROVISIONAL — they want the localisation-repeatability run audit §7.5 lists
#: under "Local map residual/parallax" and "SIZE_TOLERANCE_CM". A guessed
#: ceiling must fail CLOSED: it can only make a scattered track un-correctable,
#: never turn a scattered one green.
TRACK_CENTRE_SIGMA_MAX_CM = 0.6
TRACK_ANGLE_SIGMA_MAX_DEG = 4.0
TRACK_SIZE_SIGMA_MAX_CM = 0.8


def _median(values) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    return ordered[mid] if n % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])


def _dispersion(values) -> float:
    """Population standard deviation; 0.0 for fewer than two samples."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / n)


def _circular_mean_deg(angles, period: float = 180.0) -> float:
    """Mean orientation of block angles, wraparound-safe.

    A rectangle at ``a`` and one at ``a + 180`` are the SAME orientation, so
    the mean is taken on a circle of period 180°: ``+89`` and ``-89`` average
    to ``±90``, not ``0``, and ``179`` / ``1`` / ``-179`` average near ``0``.
    """
    if not angles:
        return 0.0
    scale = 2.0 * math.pi / period
    s = sum(math.sin(a * scale) for a in angles)
    c = sum(math.cos(a * scale) for a in angles)
    if s == 0.0 and c == 0.0:
        return float(angles[0])
    return math.atan2(s, c) / scale


def _circular_std_deg(angles, period: float = 180.0) -> float:
    """Circular standard deviation in degrees; 0.0 for fewer than two samples."""
    n = len(angles)
    if n < 2:
        return 0.0
    scale = 2.0 * math.pi / period
    s = sum(math.sin(a * scale) for a in angles) / n
    c = sum(math.cos(a * scale) for a in angles) / n
    r = math.hypot(s, c)
    if r >= 1.0:
        return 0.0
    if r <= 1e-12:
        return period / 2.0
    return math.sqrt(-2.0 * math.log(r)) / scale


@dataclass
class _TrackFrame:
    """One frame's contribution to a track: the matched detection, or absence."""

    centre_cm: tuple[float, float] | None
    angle_deg: float
    size_cm: tuple[float, float]
    present: bool
    #: Block-consistent detections that fell on this identity this frame. ``1``
    #: is a clean read; ``>1`` is a merged blob, a duplicate hypothesis or a
    #: candidate switch and makes the whole track ambiguous.
    multiplicity: int


@dataclass
class _Track:
    anchor: tuple[float, float]
    frames: deque  #: of :class:`_TrackFrame`, ``maxlen`` = settle_m


@dataclass(frozen=True)
class TrackEvidence:
    """The fused, stability-gated evidence for ONE block across the quiet window.

    ``ok`` is the gate a MOVED / DISPLACED correction must pass (item 6). The
    rest is the uncertainty / residual the pick offset, the operator and the
    log see (item 9). Nothing here ever loosens a refusal — a missing or
    unstable track only ever blocks a correction.
    """

    ok: bool
    reason: str
    centre_cm: tuple[float, float] | None = None
    angle_deg: float = 0.0
    size_cm: tuple[float, float] = (0.0, 0.0)
    samples: int = 0
    window: int = 0
    #: Radial dispersion of the fused centre, cm (``hypot`` of the per-axis).
    centre_sigma_cm: float = 0.0
    centre_sigma_xy_cm: tuple[float, float] = (0.0, 0.0)
    angle_sigma_deg: float = 0.0
    size_sigma_cm: tuple[float, float] = (0.0, 0.0)
    #: Worst single-frame centroid deviation from the fused centre, cm.
    max_residual_cm: float = 0.0
    #: ``>1`` ⇒ merged blob / duplicate hypothesis / candidate switch.
    multiplicity: int = 1
    settled: bool = False
    consistent: bool = True
    stable: bool = True


class _TrackHistory:
    """:class:`_CellHistory` / :class:`_GapHistory` for the CORRECTION pick target.

    Same N-of-M window, cleared through the same
    :meth:`Supervisor._reset_hysteresis` primitive (item 7). It associates
    every block-shaped detection (cell or gap) frame to frame by cm anchor and
    fuses the matched run; :meth:`evidence_at` answers "is the block near here
    one stable, unambiguous, settled track, and where exactly is it".
    """

    def __init__(self, settle_n: int, settle_m: int,
                 match_cm: float = TRACK_IDENTITY_MATCH_CM) -> None:
        self._n = int(settle_n)
        self._m = int(settle_m)
        self._match_cm = float(match_cm)
        self._tracks: list[_Track] = []

    def reset(self) -> None:
        self._tracks.clear()

    def _records(self, observation) -> list[DetectionRecord]:
        """The frame's block detections, multiplicity preserved."""
        detail = getattr(observation, "detections_detail", ())
        if detail:
            return [r for r in detail if r.centre_cm is not None
                    and r.placement in ("cell", "gap")]
        # Hand-built observations (unit tests, older rig traces) carry only the
        # collapsed parallel arrays. Fall back to them so the track layer still
        # has something to fuse, accepting their pre-existing one-per-cell limit.
        out: list[DetectionRecord] = []
        cps = list(getattr(observation, "cell_points_cm", ()))
        cas = list(getattr(observation, "cell_angles_deg", ()))
        css = list(getattr(observation, "cell_sizes_cm", ()))
        for i, (cell, cm) in enumerate(cps):
            out.append(DetectionRecord(
                "cell", cell, cm, cas[i] if i < len(cas) else 0.0,
                css[i] if i < len(css) else (0.0, 0.0)))
        gps = list(getattr(observation, "gap_points_cm", ()))
        gas = list(getattr(observation, "gap_angles_deg", ()))
        gss = list(getattr(observation, "gap_sizes_cm", ()))
        for i, cm in enumerate(gps):
            out.append(DetectionRecord(
                "gap", None, cm, gas[i] if i < len(gas) else 0.0,
                gss[i] if i < len(gss) else (0.0, 0.0)))
        return out

    def _looks_like_switch(self, best: _Track) -> bool:
        """Is another nearby track ANTI-PHASE with ``best`` — the block's
        detection alternating between two positions across the quiet window
        (a candidate switch), as opposed to a genuine second block that is
        present at the SAME time (an occupied neighbour)."""
        bf = [f.present for f in best.frames]
        for other in self._tracks:
            if other is best:
                continue
            d = math.hypot(best.anchor[0] - other.anchor[0],
                           best.anchor[1] - other.anchor[1])
            if d > SWITCH_NEIGHBOUR_CM:
                continue
            of = [f.present for f in other.frames]
            k = min(len(bf), len(of))
            if k < self._n:
                continue
            b, o = bf[-k:], of[-k:]
            both = sum(1 for i in range(k) if b[i] and o[i])
            either = sum(1 for i in range(k) if b[i] or o[i])
            only_other = sum(1 for i in range(k) if o[i] and not b[i])
            if only_other >= 1 and both == 0 and either >= k - 1:
                return True
        return False

    def _presence_state(self, track: _Track) -> bool | None:
        pres = [f.present for f in track.frames]
        if len(pres) < self._n:
            return None
        seen = sum(pres)
        if seen >= self._n:
            return True
        if len(pres) - seen >= self._n:
            return False
        return None

    def update(self, observation) -> None:
        recs = [r for r in self._records(observation) if r.centre_cm is not None]

        # Greedy nearest 1:1 association to the live anchors.
        pairs = []
        for ri, r in enumerate(recs):
            for ti, t in enumerate(self._tracks):
                d = math.hypot(r.centre_cm[0] - t.anchor[0],
                               r.centre_cm[1] - t.anchor[1])
                if d <= self._match_cm:
                    pairs.append((d, ri, ti))
        rec_to_track: dict[int, int] = {}
        track_to_rec: dict[int, int] = {}
        for _d, ri, ti in sorted(pairs):
            if ri in rec_to_track or ti in track_to_rec:
                continue
            rec_to_track[ri] = ti
            track_to_rec[ti] = ri

        # How many records sit within the match radius of each track this frame
        # — the multiplicity the collapsed observation used to hide.
        near = [0] * len(self._tracks)
        for r in recs:
            for ti, t in enumerate(self._tracks):
                if math.hypot(r.centre_cm[0] - t.anchor[0],
                              r.centre_cm[1] - t.anchor[1]) <= self._match_cm:
                    near[ti] += 1

        for ti, t in enumerate(self._tracks):
            if ti in track_to_rec:
                r = recs[track_to_rec[ti]]
                t.frames.append(_TrackFrame(
                    centre_cm=r.centre_cm, angle_deg=r.angle_deg,
                    size_cm=r.size_cm, present=True,
                    multiplicity=max(1, near[ti])))
                t.anchor = (0.6 * t.anchor[0] + 0.4 * r.centre_cm[0],
                            0.6 * t.anchor[1] + 0.4 * r.centre_cm[1])
            else:
                t.frames.append(_TrackFrame(None, 0.0, (0.0, 0.0), False, 0))

        # Records matching no existing track open new ones. Two unmatched
        # records within the match radius of each other are a merged / duplicate
        # pair and open ONE track already flagged multiplicity 2, so the very
        # first frame of an ambiguous read is never mistaken for a clean one.
        unmatched = [ri for ri in range(len(recs)) if ri not in rec_to_track]
        consumed: set[int] = set()
        for a in unmatched:
            if a in consumed:
                continue
            group = [a]
            for b in unmatched:
                if b <= a or b in consumed:
                    continue
                if math.hypot(recs[a].centre_cm[0] - recs[b].centre_cm[0],
                              recs[a].centre_cm[1] - recs[b].centre_cm[1]) <= self._match_cm:
                    group.append(b)
                    consumed.add(b)
            consumed.add(a)
            r = recs[a]
            self._tracks.append(_Track(
                anchor=(float(r.centre_cm[0]), float(r.centre_cm[1])),
                frames=deque([_TrackFrame(
                    centre_cm=r.centre_cm, angle_deg=r.angle_deg,
                    size_cm=r.size_cm, present=True,
                    multiplicity=len(group))], maxlen=self._m)))

        # Decay: forget a track once N of its last M frames say it is gone, so a
        # later reappearance is a NEW identity warming from nothing.
        self._tracks = [t for t in self._tracks
                        if self._presence_state(t) is not False]

    def evidence_at(self, point_cm) -> TrackEvidence:
        if point_cm is None:
            return TrackEvidence(False, "no block position to anchor a track to",
                                 window=self._m)
        best: _Track | None = None
        best_d: float | None = None
        for t in self._tracks:
            d = math.hypot(point_cm[0] - t.anchor[0], point_cm[1] - t.anchor[1])
            if d <= self._match_cm and (best_d is None or d < best_d):
                best, best_d = t, d
        if best is None:
            return TrackEvidence(
                False,
                f"no block is being tracked within {self._match_cm:g} cm of "
                f"({point_cm[0]:.1f}, {point_cm[1]:.1f}) cm — the detection is "
                f"not consistent frame to frame",
                window=self._m)

        present = [f for f in best.frames if f.present]
        n_present = len(present)
        n_window = len(best.frames)
        centres = [f.centre_cm for f in present if f.centre_cm is not None]
        angles = [f.angle_deg for f in present]
        sizes = [f.size_cm for f in present
                 if f.size_cm and f.size_cm != (0.0, 0.0)]

        cx = _median([c[0] for c in centres]) if centres else float(point_cm[0])
        cy = _median([c[1] for c in centres]) if centres else float(point_cm[1])
        sx = _dispersion([c[0] for c in centres])
        sy = _dispersion([c[1] for c in centres])
        radial = math.hypot(sx, sy)
        f_ang = _circular_mean_deg(angles)
        s_ang = _circular_std_deg(angles)
        if sizes:
            f_size = (_median([s[0] for s in sizes]), _median([s[1] for s in sizes]))
            s_size = (_dispersion([s[0] for s in sizes]),
                      _dispersion([s[1] for s in sizes]))
        else:
            f_size, s_size = (0.0, 0.0), (0.0, 0.0)
        max_resid = max((math.hypot(c[0] - cx, c[1] - cy) for c in centres),
                        default=0.0)
        multiplicity = max((f.multiplicity for f in present), default=1)

        settled = n_present >= self._n
        switched = self._looks_like_switch(best)
        consistent = multiplicity <= 1 and not switched
        size_scatter = max(s_size) if sizes else 0.0
        stable = (radial <= TRACK_CENTRE_SIGMA_MAX_CM
                  and s_ang <= TRACK_ANGLE_SIGMA_MAX_DEG
                  and size_scatter <= TRACK_SIZE_SIGMA_MAX_CM)

        problems: list[str] = []
        if not settled:
            problems.append(
                f"only {n_present} of the last {n_window} quiet frames tracked "
                f"one block here — {self._n} are needed")
        if multiplicity > 1:
            problems.append(
                "more than one block-shaped detection sat on this spot in the "
                "quiet window — a merged blob or a duplicate hypothesis")
        if switched:
            problems.append(
                "the detection alternated between two positions across the "
                "quiet window — a candidate switch, not one settled block")
        if radial > TRACK_CENTRE_SIGMA_MAX_CM:
            problems.append(
                f"the tracked centre scattered {radial:.2f} cm across the window "
                f"(limit {TRACK_CENTRE_SIGMA_MAX_CM:g})")
        if s_ang > TRACK_ANGLE_SIGMA_MAX_DEG:
            problems.append(
                f"the tracked angle scattered {s_ang:.1f} deg across the window "
                f"(limit {TRACK_ANGLE_SIGMA_MAX_DEG:g})")
        if size_scatter > TRACK_SIZE_SIGMA_MAX_CM:
            problems.append(
                f"the tracked footprint scattered {size_scatter:.2f} cm across "
                f"the window (limit {TRACK_SIZE_SIGMA_MAX_CM:g})")

        ok = settled and consistent and stable
        if ok:
            reason = (f"one stable block-consistent track over {n_present}/"
                      f"{n_window} quiet frames: centre ({cx:.2f}, {cy:.2f}) cm "
                      f"±{radial:.2f}, angle {f_ang:+.1f}° ±{s_ang:.1f}")
        else:
            reason = "; ".join(problems)

        return TrackEvidence(
            ok=ok, reason=reason, centre_cm=(cx, cy), angle_deg=f_ang,
            size_cm=f_size, samples=n_present, window=n_window,
            centre_sigma_cm=radial, centre_sigma_xy_cm=(sx, sy),
            angle_sigma_deg=s_ang, size_sigma_cm=s_size,
            max_residual_cm=max_resid, multiplicity=multiplicity,
            settled=settled, consistent=consistent, stable=stable)


@dataclass
class Interlocks:
    """D5's four gates. All required; any one of them refuses every verdict."""

    parked: bool
    calibrated: bool
    quiet: bool

    def refusal(self) -> tuple[str, str] | None:
        """``(state, reason)`` for the first gate that is shut, else None."""
        if not self.calibrated:
            return "NO_MAP", "NO MAP — calibrate to enable checks"
        if not self.parked:
            return "BUSY", "RIG MOVING"
        if not self.quiet:
            return "BUSY", "SCENE NOT STILL"
        return None


class Supervisor:
    """The observer. Holds hysteresis across frames and nothing else.

    ``quiet_diff_fraction``, ``settle_n`` and ``settle_m`` default to the module
    constants, which are Gate 0's MEASURED values — see there for the runs they
    came from. They remain explicit keyword arguments so a test can vary them,
    and None is still refused: an unmeasured threshold must never reach a rig.
    """

    def __init__(self, *, quiet_diff_fraction: float = QUIET_DIFF_FRACTION,
                 settle_n: int = SETTLE_N, settle_m: int = SETTLE_M) -> None:
        if quiet_diff_fraction is None or settle_n is None or settle_m is None:
            raise ValueError(
                "quiet_diff_fraction, settle_n and settle_m are Gate 0's "
                "measurement — run python/tools/measure_quiet_window.py on the "
                "rig rather than guessing them")
        if quiet_diff_fraction <= 0:
            raise ValueError("quiet_diff_fraction must be positive")
        if not 0 < settle_n <= settle_m:
            raise ValueError("need 0 < settle_n <= settle_m")
        self.quiet_diff_fraction = float(quiet_diff_fraction)
        self.settle_n = int(settle_n)
        self.settle_m = int(settle_m)
        self._history = _CellHistory(self.settle_n, self.settle_m)
        #: The (mode, board_epoch) the hysteresis belongs to. A change in
        #: EITHER — an R/RR latch, or a gantry reboot / reconnect / board swap
        #: that bumps `PlacementLedger.board_epoch` (audit item 8) — means the
        #: board the counters describe no longer exists, so both histories are
        #: dropped through `_reset_hysteresis()`, item 7's one reset primitive.
        self._identity: tuple[str | None, int] | None = None
        self._mode: str | None = None
        self._board_epoch: int = 0
        #: D7's hysteresis for the one signal that used to bypass it. `in_gap`
        #: is a per-frame count, so it cannot go through `_CellHistory` by cell;
        #: `_GapHistory` keys it by PERSISTENT GAP IDENTITY instead, so a gap is
        #: asserted and cleared under the same N-of-M and a changed gap does not
        #: inherit the previous one's evidence. See that class for the global
        #: `deque[bool]` it replaced and why.
        self._gap_history = _GapHistory(self.settle_n, self.settle_m)
        #: ITEM 6 + 9. The CORRECTION pick target's fused track, over the same
        #: N-of-M window. Fed from the same `observation` in `step()` as the two
        #: histories above, cleared by the same primitive — never a second
        #: analysis path (audit §2.4). Queried by `track_evidence_at`.
        self._track_history = _TrackHistory(self.settle_n, self.settle_m)

    def reset(self) -> None:
        self._reset_hysteresis()

    def _reset_hysteresis(self) -> None:
        """Clear ALL histories together. Every reset cause — a tripped
        interlock, a mode latch, memory loss, a map-generation change on the
        server — goes through here, so a stale gap verdict or a stale
        correction track can never outlive the cell evidence gathered beside it
        (D7: reset, never decay; audit item 7: no asymmetric or leaky
        clearing)."""
        self._history.reset()
        self._gap_history.reset()
        self._track_history.reset()

    def note_mode(self, mode: str, board_epoch: int = 0) -> None:
        """D13 + audit item 8: evidence gathered under one lattice OR one board
        epoch never judges another.

        The two grids are different lattices with different registration —
        7x6 vertical against 3x10 horizontal — so a counter carried across an
        R/RR latch would be describing a board that no longer exists. The same
        is true across a board-epoch change: a gantry reboot, a reconnect or an
        operator swap means the blocks on the table are no longer the ones the
        earlier ledger entries describe. Either boundary drops BOTH histories,
        through the one reset primitive item 7 established — never a second
        mechanism.
        """
        identity = (mode, int(board_epoch))
        if self._identity is not None and identity != self._identity:
            self._reset_hysteresis()
        self._identity = identity
        self._mode = mode
        self._board_epoch = int(board_epoch)

    def is_quiet(self, diff_fraction: float | None) -> bool:
        """The scene-quiet gate. None (no baseline yet) is NOT quiet."""
        return diff_fraction is not None and diff_fraction <= self.quiet_diff_fraction

    def track_evidence_at(self, point_cm) -> TrackEvidence:
        """ITEM 6 + 9: the fused, stability-gated track for the block at
        ``point_cm`` (map cm frame), from the coherent quiet window
        :meth:`step` accumulates.

        :func:`web.state.assess_frame_correction` calls this to require ONE
        stable, block-consistent track before a MOVED / DISPLACED correction
        and to fuse the pick centroid / angle / size instead of trusting a
        single frame's first candidate. Read-only — it never advances the
        window (that is :meth:`step`'s job, once per coherent analysis result).
        """
        return self._track_history.evidence_at(point_cm)

    def step(self, *, mode: str, ledger, observation: Observation,
             interlocks: Interlocks, grid=None):
        """One frame. Returns ``(state, reason, verdict)``; verdict may be None.

        The set maths here is trivial and belongs on the event loop with the
        rest of ``_drive_pipeline``'s bookkeeping. The FRAME DIFFERENCE that
        feeds ``interlocks.quiet`` does not — it is a full-frame numpy op, and
        AGENTS.md §7's one-owner-thread rule puts it on the same
        single-threaded executor as the other OpenCV work. Do not let it run on
        the loop because it is "only a subtraction".

        ``grid`` is the mode's :class:`rig.grid.MachineGrid`. With it, a
        DISPLACED verdict whose gap detection is not geometrically near the cell
        :func:`classify` paired it with is downgraded to DISAGREES — see
        :func:`implausible_displacement`. Without it (the default) the verdict
        is published exactly as ``classify`` returned it.
        """
        # The board epoch travels on the ledger (audit item 8). A change in it
        # — a gantry reboot / reconnect / board swap — invalidates the live
        # hysteresis exactly like a mode latch does, via `note_mode`.
        epoch = int(getattr(ledger, "board_epoch", 0))
        self.note_mode(mode, epoch)

        refusal = interlocks.refusal()
        if refusal is not None:
            # D7: a frame that was not allowed to be judged must not leave
            # partial evidence behind — cell OR gap. Reset, do not decay.
            self._reset_hysteresis()
            return refusal[0], refusal[1], None

        # Memory is scoped to THIS grid and THIS board epoch. A global
        # `has_memory` let horizontal-only placements make vertical mode report
        # "memory" against an empty expected set — VERIFIED on an empty view,
        # FOREIGN on a real vertical board. Same failure across a board epoch.
        if not ledger.has_memory(mode, epoch):
            self._reset_hysteresis()
            return ("NO_MEMORY",
                    "NO MEMORY — the board is only tracked from the first "
                    "build after a restart", None)

        expected = ledger.expected_occupancy(mode, epoch)
        top_levels = ledger.expected_top_level(mode, epoch)
        interest = set(expected) | set(observation.cells)
        self._history.update(interest, observation.cells)
        self._gap_history.update(observation)
        # ITEM 6 + 9: the CORRECTION pick target's track, from the SAME
        # observation, on the SAME window — no extra frames, no second path.
        self._track_history.update(observation)

        warming = self._history.warming(interest)
        if warming:
            return "WARMING", f"SETTLING — {len(warming)} cells", None

        # D7 for `in_gap`: the classifier sees a gap only once THAT gap's own
        # last-M frames settle it occupied, and keeps seeing it until N of the
        # last M say it is gone. `_GapHistory` keys this per persistent gap
        # identity, not one global boolean (audit item 7 / §5.2), so the count
        # here is distinct settled gaps — never the raw per-frame `in_gap`.
        verdict = classify(
            mode, expected, self._history.settled_occupancy(interest),
            top_levels=top_levels,
            in_gap=self._gap_history.settled_gap_count())

        # A DISPLACED verdict pairs cells by set difference only. If a grid is
        # available, reject the pairing when the gap block is nowhere near the
        # cell it was matched with — different blocks, or a misregistered map.
        if grid is not None and verdict.verdict == "DISPLACED" and len(verdict.cells) == 1:
            reason = implausible_displacement(grid, verdict.cells[0], observation)
            if reason is not None:
                return "VERDICT", reason, replace(verdict, verdict="DISAGREES")

        return "VERDICT", None, verdict

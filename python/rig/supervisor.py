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
from dataclasses import dataclass

import numpy as np

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
STATES = ("NO_MEMORY", "NO_MAP", "WARMING", "BUSY", "QUIET", "VERDICT")

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
    counts = {name: 0 for name in PLACEMENTS}
    for detection in detections:
        cell, placement = locate(workspace, detection.center, image_size)
        counts[placement] += 1
        if cell is not None:
            cells.append(cell)
    return Observation(cells=_sorted(set(cells)), in_gap=counts["gap"],
                       off_board=counts["margin"] + counts["outside"],
                       detections=len(detections))


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
        self._mode: str | None = None
        #: D7's hysteresis, applied to the one signal that used to bypass it.
        #: `in_gap` is a per-frame count with no cell identity, so it cannot go
        #: through `_CellHistory`; instead the last M judged frames each record
        #: whether ANY detection was in a gap, and `classify` sees a non-zero
        #: `in_gap` only once N of them agree. A single frame where a correctly
        #: placed block's centroid crosses a footprint boundary must not stop
        #: the program. NOT the full fix for a MOVED block that lands off-site
        #: (that needs per-gap-cell identity); this is denoising only.
        self._gap_history: deque[bool] = deque(maxlen=self.settle_m)

    def reset(self) -> None:
        self._history.reset()
        self._gap_history.clear()

    def note_mode(self, mode: str) -> None:
        """D13: evidence gathered under one lattice never judges the other.

        The two grids are different lattices with different registration —
        7x6 vertical against 3x10 horizontal — so a counter carried across an
        R/RR latch would be describing a board that no longer exists.
        """
        if self._mode is not None and mode != self._mode:
            self._history.reset()
        self._mode = mode

    def is_quiet(self, diff_fraction: float | None) -> bool:
        """The scene-quiet gate. None (no baseline yet) is NOT quiet."""
        return diff_fraction is not None and diff_fraction <= self.quiet_diff_fraction

    def step(self, *, mode: str, ledger, observation: Observation,
             interlocks: Interlocks):
        """One frame. Returns ``(state, reason, verdict)``; verdict may be None.

        The set maths here is trivial and belongs on the event loop with the
        rest of ``_drive_pipeline``'s bookkeeping. The FRAME DIFFERENCE that
        feeds ``interlocks.quiet`` does not — it is a full-frame numpy op, and
        AGENTS.md §7's one-owner-thread rule puts it on the same
        single-threaded executor as the other OpenCV work. Do not let it run on
        the loop because it is "only a subtraction".
        """
        self.note_mode(mode)

        refusal = interlocks.refusal()
        if refusal is not None:
            # D7: a frame that was not allowed to be judged must not leave
            # partial evidence behind. Reset, do not decay.
            self._history.reset()
            return refusal[0], refusal[1], None

        if not ledger.has_memory:
            self._history.reset()
            return ("NO_MEMORY",
                    "NO MEMORY — the board is only tracked from the first "
                    "build after a restart", None)

        expected = ledger.expected_occupancy(mode)
        top_levels = ledger.expected_top_level(mode)
        interest = set(expected) | set(observation.cells)
        self._history.update(interest, observation.cells)
        self._gap_history.append(observation.in_gap > 0)

        warming = self._history.warming(interest)
        if warming:
            return "WARMING", f"SETTLING — {len(warming)} cells", None

        # D7 for `in_gap`: a non-zero count reaches `classify` only once N of
        # the last M judged frames saw a gap detection — see `_gap_history`.
        gap_settled = (len(self._gap_history) >= self.settle_n
                       and sum(self._gap_history) >= self.settle_n)
        verdict = classify(
            mode, expected, self._history.settled_occupancy(interest),
            top_levels=top_levels,
            in_gap=observation.in_gap if gap_settled else 0)
        return "VERDICT", None, verdict

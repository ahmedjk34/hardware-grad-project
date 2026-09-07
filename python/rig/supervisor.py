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
from dataclasses import dataclass, field

# ── Gate 0's outputs. NOT YET MEASURED. ───────────────────────────────────── #
#
# These three are the quiet-window interlock, and every one of them has to come
# off the rig via `python/tools/measure_quiet_window.py`, not out of a design
# document. The plan's D5 carries 0.02 / 3 / 5 and says outright they are "to
# be measured on hardware, not trusted from here".
#
# They are None on purpose and `Supervisor` REQUIRES them as arguments, so a
# caller cannot start a supervisor on a guessed threshold by forgetting to pass
# one. Fill these in from the measurement, and only then wire the supervisor
# into `web/app.py`.
QUIET_DIFF_FRACTION: float | None = None   # UNMEASURED — Gate 0
SETTLE_N: int | None = None                # UNMEASURED — Gate 0
SETTLE_M: int | None = None                # UNMEASURED — Gate 0

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

#: D10. `block_outline._lattice_filter` skips entirely below this many
#: detections, so on a sparse board the observed set is UNFILTERED and the
#: holder's offcuts beside [0,0] read as blocks. Below it, no FOREIGN and no
#: DISAGREES — ever. Early in every program the board IS sparse, so this is the
#: common path, not an edge case.
MIN_LATTICE_BLOCKS = 6

#: The observer's own states. BUSY and QUIET and NO_MEMORY are NOT faults and
#: must not take a state colour in the UI: BUSY is the normal condition for the
#: whole of a build, and colouring it amber would leave the console amber most
#: of the time, which kills DESIGN.md's reserved palette.
STATES = ("NO_MEMORY", "NO_MAP", "WARMING", "BUSY", "QUIET", "VERDICT")

#: Amber — degraded but recoverable. The runner pauses.
AMBER_VERDICTS = ("NOT_DETECTED", "REMOVED", "MOVED")
#: Red — stop, a human is required. The runner stops. Still never LOCKED.
RED_VERDICTS = ("FOREIGN", "DISAGREES")

Cell = tuple[int, int]


def _sorted(cells) -> tuple[Cell, ...]:
    return tuple(sorted(cells))


@dataclass(frozen=True)
class Observation:
    """What one accepted frame saw. M2's whole output — no verdict in here."""

    cells: tuple[Cell, ...]
    #: Detections whose centre `cell_at` could not place. See :func:`observe`.
    off_lattice: int
    #: Total detections in the frame, before any of this. D10 reads it.
    detections: int


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

    Both arrive here as None, so both are counted in ``off_lattice`` and the
    classifier treats the count as FOREIGN-shaped evidence. Distinguishing them
    would need the envelope quad, and D9 already stops the machine on either.
    Never treat this as a dropout.
    """
    cells, off_lattice = [], 0
    for detection in detections:
        cell = workspace.cell_at(detection.center, image_size)
        if cell is None:
            off_lattice += 1
        else:
            cells.append((int(cell[0]), int(cell[1])))
    return Observation(cells=_sorted(set(cells)), off_lattice=off_lattice,
                       detections=len(detections))


def unjudged_cells(top_levels: dict[Cell, int]) -> tuple[Cell, ...]:
    """D6's refusals: cells whose expected top level is at or above the ceiling."""
    return _sorted(cell for cell, level in top_levels.items()
                   if level >= LEVEL_CEILING)


def classify(mode: str, expected, observed, *, top_levels=None,
             off_lattice: int = 0, detections: int = 0) -> Verdict:
    """D9's set difference. Pure — no frames, no time, no I/O.

    ``expected`` is ``ledger.expected_occupancy(mode)``; ``observed`` is
    :attr:`Observation.cells`. Everything else is the two suppressions that
    keep this honest on a real board: D6's level ceiling and D10's sparse-board
    rule.

    MOVED does not claim it is the same block. Twenty-nine identical wooden
    rectangles carry no identity and no proof is available. It does not need
    one: the actionable fact is that the board no longer matches the plan at
    two cells.
    """
    top_levels = top_levels or {}
    refused = set(unjudged_cells(top_levels))
    expected = set(expected) - refused
    observed = set(observed) - refused

    missing = expected - observed
    unexpected = observed - expected

    # D10. Below the lattice filter's own threshold the observed set is
    # unfiltered, so an "unexpected" cell may be a holder offcut and an
    # off-lattice detection may be a cable. Missing cells are still trustworthy
    # — nothing about a sparse board invents an absence — so REMOVED survives
    # and FOREIGN and DISAGREES do not.
    sparse = detections < MIN_LATTICE_BLOCKS
    if sparse:
        unexpected = set()
        off_lattice = 0

    def made(name, cells):
        return Verdict(verdict=name, cells=_sorted(cells), mode=str(mode),
                       expected=_sorted(expected), observed=_sorted(observed),
                       unjudged=_sorted(refused))

    if not missing and not unexpected and not off_lattice:
        return made("VERIFIED", ())
    # A block on the board and not on any site. Red on its own, whatever else
    # the cell sets say — there is something the plan cannot account for.
    if off_lattice and not sparse:
        return made("FOREIGN", unexpected)
    if len(missing) == 1 and len(unexpected) == 1:
        # Ordered [from, to]: the UI draws an arrow between them.
        return made("MOVED", (missing.pop(), unexpected.pop()))
    if missing and not unexpected:
        # More than one missing cell on a SPARSE board is still REMOVED, not
        # DISAGREES: D10 bans DISAGREES there, and naming the cells is more
        # use to an operator than declining to.
        if len(missing) > 1 and not sparse:
            return made("DISAGREES", missing)
        return made("REMOVED", missing)
    if unexpected and not missing:
        if len(unexpected) > 1:
            return made("DISAGREES", unexpected)
        return made("FOREIGN", unexpected)
    # Both sides differ by more than one cell. Not a failure of the classifier
    # — the classifier declining to guess. Two simultaneous changes in one
    # half-second window means something happened this model does not describe,
    # so it stops the program rather than pausing it.
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

    ``quiet_diff_fraction``, ``settle_n`` and ``settle_m`` are REQUIRED and have
    no defaults, because their values are Gate 0's output and a default here
    would be a guess with the authority of code. See the module constants.
    """

    def __init__(self, *, quiet_diff_fraction: float, settle_n: int,
                 settle_m: int) -> None:
        if quiet_diff_fraction is None or settle_n is None or settle_m is None:
            raise ValueError(
                "quiet_diff_fraction, settle_n and settle_m are Gate 0's "
                "measurement — run python/tools/measure_quiet_window.py on the "
                "rig rather than guessing them")
        if not 0 < settle_n <= settle_m:
            raise ValueError("need 0 < settle_n <= settle_m")
        self.quiet_diff_fraction = float(quiet_diff_fraction)
        self.settle_n = int(settle_n)
        self.settle_m = int(settle_m)
        self._history = _CellHistory(self.settle_n, self.settle_m)
        self._mode: str | None = None

    def reset(self) -> None:
        self._history.reset()

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

        warming = self._history.warming(interest)
        if warming:
            return "WARMING", f"SETTLING — {len(warming)} cells", None

        verdict = classify(
            mode, expected, self._history.settled_occupancy(interest),
            top_levels=top_levels, off_lattice=observation.off_lattice,
            detections=observation.detections)
        return "VERDICT", None, verdict

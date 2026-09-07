#!/usr/bin/env python3
"""What the machine was told to place, and what the firmware said came of it.

The rig places a block and forgets it. This is the memory — the left-hand
operand of the only subtraction that can detect a placement error:

    error  =  what SHOULD be on the board  -  what IS on the board

The camera supplies the right-hand operand and can never supply this one, so
this module contains **no OpenCV, no detector, no pixels and no frames**. It is
a record of commands the machine issued, which is what makes a claim about the
board defensible rather than hand-wavy: nothing here is inferred.

Three rules it exists to enforce, from
``docs/features/placement-supervision.md``:

**PLACED only** (D2). A ``rejected`` build placed nothing. An ``aborted`` one
means the machine's own state is unknown, which is a lock and a human, not a
ledger entry. Neither is admitted, ever.

**Keyed by mode** (D13). Vertical is a 7x6 lattice and horizontal a 3x10 one,
separately registered; ``[2,3]`` is a different physical place in each. Asking
for one mode's occupancy must never return the other's. Rotation is NOT stored
alongside it: how a block is laid is a property of the active grid, so rotation
is identical to mode and a second copy of it would be a copy that drifts.

**Written for the record, never reloaded as authority** (D3). ``configure()``
turns on an append-only ``logs/placements.log`` for the thesis record. Nothing
reads it back. On startup this object is empty, :attr:`has_memory` is False and
every verdict downstream must be refused with ``NO MEMORY`` — because a
reloaded ledger claims to describe a board nobody has looked at since the
process died, and the things consuming this drive a claw.

Thread safety: :meth:`append` is called from the ``BuildJob`` worker thread and
every reader runs on the FastAPI event loop, so the state is guarded by a lock
and every accessor returns a snapshot the caller owns.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time

from rig import build_log
from rig.link import PLACED

#: Neighbours for :meth:`PlacementLedger.has_taller_neighbour`. Orthogonal
#: only: the claw's approach is along the axes, and a diagonal block is a
#: pitch away on both at once.
_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))

#: The height of a cell nothing has been placed on. Not zero — level 0 is a
#: real block sitting on the table, and "empty" has to sort below it.
GROUND = -1


@dataclass(frozen=True)
class Placement:
    """One block the firmware confirmed it placed.

    Frozen, and every field is a number or a mode name. The observer's columns
    from the design's §1 table — ``observed_centre_px``, ``residual_cm`` — are
    deliberately NOT here yet: they are the observer's to record, and Stage 15
    is the feature that consumes them.
    """

    mode: str
    col: int
    row: int
    level: int
    placed_at: float

    @property
    def cell(self) -> tuple[int, int]:
        return self.col, self.row


class PlacementLedger:
    """The as-built memory. Append-only, per mode, PLACED only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._placements: list[Placement] = []

    # -- writing ---------------------------------------------------------- #

    def append(self, mode: str, col: int, row: int, level: int, result,
               placed_at: float | None = None) -> Placement | None:
        """Record one settled build. Returns the entry, or None if refused.

        ``result`` is the ``BuildResult`` the firmware settled on, and it is
        checked here rather than at the call site so that there is exactly one
        place that decides what the memory admits.
        """
        if str(result) != PLACED:
            return None
        placement = Placement(mode=str(mode), col=int(col), row=int(row),
                              level=int(level),
                              placed_at=time.time() if placed_at is None
                              else float(placed_at))
        with self._lock:
            self._placements.append(placement)
        build_log.placements.placed(placement)
        return placement

    # -- reading ---------------------------------------------------------- #

    @property
    def has_memory(self) -> bool:
        """False until the first PLACED of this process.

        The whole of D3 in one property: a fresh process knows nothing about
        the board, and saying so is the honest answer, not a degraded one.
        """
        with self._lock:
            return bool(self._placements)

    def placements(self, mode: str | None = None) -> tuple[Placement, ...]:
        """Every entry, in the order it was placed. One mode's, if given."""
        with self._lock:
            if mode is None:
                return tuple(self._placements)
            wanted = str(mode)
            return tuple(p for p in self._placements if p.mode == wanted)

    def expected_occupancy(self, mode: str) -> frozenset[tuple[int, int]]:
        """The cells holding *something*, at any level (D4).

        Occupancy is a COLUMN, not a level: the camera is above the board, so a
        block at level 1 hides the one beneath it and the only question an
        overhead view can answer is whether a cell holds anything at all.
        """
        return frozenset(p.cell for p in self.placements(mode))

    def expected_top_level(self, mode: str) -> dict[tuple[int, int], int]:
        """The highest level placed on each cell of ``mode``."""
        top: dict[tuple[int, int], int] = {}
        for placement in self.placements(mode):
            cell = placement.cell
            if placement.level > top.get(cell, GROUND):
                top[cell] = placement.level
        return top

    # -- Stage 15's safety predicates ------------------------------------- #
    #
    # Built here, in the substrate, so that feature inherits them instead of
    # writing a second occupancy model that can disagree with this one.

    def is_top_of_column(self, mode: str, col: int, row: int, level: int) -> bool:
        """Is that block the top of its stack — is there nothing on top of it?

        Stage 15's D5. A buried block cannot be picked up and re-placed however
        badly it sits, so a correction must refuse it. False for a cell nothing
        was ever placed on: there is no block there to be the top of.
        """
        top = self.expected_top_level(mode).get((int(col), int(row)))
        return top is not None and top == int(level)

    def has_taller_neighbour(self, mode: str, col: int, row: int) -> bool:
        """Does an orthogonally adjacent cell stack higher than this one?

        Stage 15's D6. The claw has to descend beside the block it is picking,
        so a taller neighbour is a collision. An empty cell sits at
        :data:`GROUND`, below level 0, so any neighbour with a block on it is
        taller than an empty cell — which is the answer that keeps the claw
        safe.
        """
        top = self.expected_top_level(mode)
        here = top.get((int(col), int(row)), GROUND)
        return any(top.get((int(col) + dx, int(row) + dy), GROUND) > here
                   for dx, dy in _NEIGHBOURS)

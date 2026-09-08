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
reads it back. On startup this object is empty, :meth:`has_memory` is False and
every verdict downstream must be refused with ``NO MEMORY`` — because a
reloaded ledger claims to describe a board nobody has looked at since the
process died, and the things consuming this drive a claw.

**Scoped by mode AND board epoch** (D13 + audit item 8). Every entry is stamped
with the :attr:`board_epoch` it was placed in. A gantry reboot, a reconnect or
an operator board swap calls :meth:`new_board_epoch`: the rows are KEPT — they
are the append-only history — but :meth:`has_memory`, :meth:`expected_occupancy`
and every derived predicate answer for the *current* epoch only, which starts
empty. Memory recorded against a superseded board, or against the other grid,
is never read as authority for what is on the table now: the honest answer is
``NO MEMORY``, not a ``VERIFIED`` on an empty view or a ``FOREIGN`` on a real
one. The supervisor treats an epoch change exactly like a mode change and drops
its live hysteresis through the one reset primitive
(:meth:`rig.supervisor.Supervisor._reset_hysteresis`).

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

#: Sentinel for the ``board_epoch`` argument of the readers: "whatever epoch the
#: ledger is in right now". ``None`` there means "every epoch" — the thesis /
#: history view — and an int means that exact epoch.
_CURRENT_EPOCH = object()


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
    #: The board epoch this block was placed in (audit item 8). Defaulted so
    #: every existing construction still type-checks; :meth:`PlacementLedger.append`
    #: always stamps the live epoch.
    board_epoch: int = 0

    @property
    def cell(self) -> tuple[int, int]:
        return self.col, self.row


class PlacementLedger:
    """The as-built memory. Append-only, per mode, PLACED only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._placements: list[Placement] = []
        self._board_epoch = 0

    # -- board epoch (audit item 8) ------------------------------------- #

    @property
    def board_epoch(self) -> int:
        """The current physical-board epoch — bumped by :meth:`new_board_epoch`
        every time the board's correspondence to these records is broken."""
        with self._lock:
            return self._board_epoch

    def new_board_epoch(self) -> int:
        """Start a new board epoch and return it.

        Called when the board on the table can no longer be spoken for by the
        entries already recorded — a gantry reboot, a reconnect, an operator
        board swap. The rows are KEPT (append-only history / thesis record),
        but :meth:`has_memory`, :meth:`expected_occupancy` and every derived
        predicate now answer for the new epoch, which starts empty. No
        ``VERIFIED`` / ``FOREIGN`` / ``MOVED`` verdict can survive the
        transition because the evidence behind it is scoped to the old epoch.
        """
        with self._lock:
            self._board_epoch += 1
            return self._board_epoch

    def _resolve_epoch(self, board_epoch) -> int | None:
        """Caller holds the lock. Sentinel -> live epoch; None -> every epoch."""
        if board_epoch is _CURRENT_EPOCH:
            return self._board_epoch
        return None if board_epoch is None else int(board_epoch)

    # -- writing ---------------------------------------------------------- #

    def append(self, mode: str, col: int, row: int, level: int, result,
               placed_at: float | None = None) -> Placement | None:
        """Record one settled build. Returns the entry, or None if refused.

        ``result`` is the ``BuildResult`` the firmware settled on, and it is
        checked here rather than at the call site so that there is exactly one
        place that decides what the memory admits. The entry is stamped with
        the live :attr:`board_epoch`.
        """
        if str(result) != PLACED:
            return None
        when = time.time() if placed_at is None else float(placed_at)
        with self._lock:
            placement = Placement(mode=str(mode), col=int(col), row=int(row),
                                  level=int(level), placed_at=when,
                                  board_epoch=self._board_epoch)
            self._placements.append(placement)
        build_log.placements.placed(placement)
        return placement

    # -- reading ---------------------------------------------------------- #

    def has_memory(self, mode: str | None = None,
                   board_epoch=_CURRENT_EPOCH) -> bool:
        """Is there recorded memory for this mode and board epoch?

        D3, scoped two ways (audit item 8). A fresh process knows nothing about
        the board; so does a fresh board epoch, and so does a mode nothing has
        been placed in this epoch. Any of those is an honest ``NO MEMORY``, not
        a degraded verdict — the alternative is judging a vertical board
        against a horizontal ledger, or this board against the last one.

        ``mode`` None means any mode. ``board_epoch`` defaults to the live
        epoch; pass ``None`` for the every-epoch (thesis-record) view.
        """
        with self._lock:
            epoch = self._resolve_epoch(board_epoch)
            wanted = None if mode is None else str(mode)
            return any((wanted is None or p.mode == wanted)
                       and (epoch is None or p.board_epoch == epoch)
                       for p in self._placements)

    def placements(self, mode: str | None = None,
                   board_epoch=_CURRENT_EPOCH) -> tuple[Placement, ...]:
        """Entries in placement order, scoped to one mode / board epoch.

        ``mode`` None means every mode; ``board_epoch`` defaults to the live
        epoch, ``None`` means every epoch (the append-only history view).
        """
        with self._lock:
            epoch = self._resolve_epoch(board_epoch)
            wanted = None if mode is None else str(mode)
            return tuple(p for p in self._placements
                         if (wanted is None or p.mode == wanted)
                         and (epoch is None or p.board_epoch == epoch))

    def expected_occupancy(self, mode: str,
                           board_epoch=_CURRENT_EPOCH) -> frozenset[tuple[int, int]]:
        """The cells holding *something*, at any level (D4).

        Occupancy is a COLUMN, not a level: the camera is above the board, so a
        block at level 1 hides the one beneath it and the only question an
        overhead view can answer is whether a cell holds anything at all.
        """
        return frozenset(p.cell for p in self.placements(mode, board_epoch))

    def expected_top_level(self, mode: str,
                           board_epoch=_CURRENT_EPOCH) -> dict[tuple[int, int], int]:
        """The highest level placed on each cell of ``mode`` in this epoch."""
        top: dict[tuple[int, int], int] = {}
        for placement in self.placements(mode, board_epoch):
            cell = placement.cell
            if placement.level > top.get(cell, GROUND):
                top[cell] = placement.level
        return top

    # -- Stage 15's safety predicates ------------------------------------- #
    #
    # Built here, in the substrate, so that feature inherits them instead of
    # writing a second occupancy model that can disagree with this one.

    def is_top_of_column(self, mode: str, col: int, row: int, level: int,
                         board_epoch=_CURRENT_EPOCH) -> bool:
        """Is that block the top of its stack — is there nothing on top of it?

        Stage 15's D5. A buried block cannot be picked up and re-placed however
        badly it sits, so a correction must refuse it. False for a cell nothing
        was ever placed on: there is no block there to be the top of.
        """
        top = self.expected_top_level(mode, board_epoch).get((int(col), int(row)))
        return top is not None and top == int(level)

    def has_taller_neighbour(self, mode: str, col: int, row: int,
                             board_epoch=_CURRENT_EPOCH) -> bool:
        """Does an orthogonally adjacent cell stack higher than this one?

        Stage 15's D6. The claw has to descend beside the block it is picking,
        so a taller neighbour is a collision. An empty cell sits at
        :data:`GROUND`, below level 0, so any neighbour with a block on it is
        taller than an empty cell — which is the answer that keeps the claw
        safe.
        """
        top = self.expected_top_level(mode, board_epoch)
        here = top.get((int(col), int(row)), GROUND)
        return any(top.get((int(col) + dx, int(row) + dy), GROUND) > here
                   for dx, dy in _NEIGHBOURS)

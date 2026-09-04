#!/usr/bin/env python3
"""Safety state for selecting and confirming one camera-driven build."""

from __future__ import annotations

from dataclasses import dataclass

from rig.config import GRID_MODES
from rig.link import ABORTED, PLACED, BuildResult, RigError


class BuildStateError(RuntimeError):
    """The requested UI action is not safe in the controller's current state."""


@dataclass
class BuildController:
    """Turn a camera-grid cell or calibration target into one confirmed build.

    The controller deliberately knows nothing about OpenCV. It enforces the
    pieces that must remain true whichever UI calls it: levels cannot be
    negative, successful builds clear selection to prevent accidental repeats,
    a grid-mode switch clears it too because the coordinates now mean something
    else, and an aborted/unknown serial outcome locks the session until a human
    has inspected the rig and restarts the program.
    """

    rig: object
    level: int = 0
    orchestrator: object | None = None
    selected: tuple[int, int] | None = None
    last_result: BuildResult | None = None
    locked_reason: str | None = None

    def __post_init__(self):
        self.set_level(self.level)

    @property
    def locked(self) -> bool:
        return self.locked_reason is not None

    @property
    def mode(self) -> str | None:
        """Which grid the rig is in. Read from the rig, never cached here.

        A stale copy of this would put a block in the wrong place, so the
        controller does not keep one: it asks the object that owns the grid.
        """
        return getattr(self.rig.grid, "mode", None)

    @property
    def command(self) -> str | None:
        if self.selected is None:
            return None
        col, row = self.selected
        # No rotation word: how the block is laid is a property of the active
        # grid, and the rig already knows which grid it is in.
        return f"B {col} {row} {self.level}"

    def select(self, cell: tuple[int, int]) -> None:
        if self.locked:
            raise BuildStateError(self.locked_reason)
        col, row = (int(value) for value in cell)
        if self.rig.grid.is_feeder(col, row):
            raise BuildStateError(
                "[0,0] is the feeder - it is where blocks are picked up from, "
                "in both modes, and is never built on"
            )
        if not self.rig.grid.contains_build_target(col, row):
            raise BuildStateError(
                f"build target [{col},{row}] is outside "
                f"0..{self.rig.grid.max_col} x 0..{self.rig.grid.max_row}"
            )
        self.selected = col, row

    def clear_selection(self) -> None:
        if not self.locked:
            self.selected = None

    def set_level(self, level: int) -> None:
        level = int(level)
        if level < 0:
            raise BuildStateError("build level cannot be negative")
        self.level = level

    def adjust_level(self, delta: int) -> None:
        self.set_level(max(0, self.level + int(delta)))

    def set_mode(self, mode: str, *, home_before_horizontal: bool = False) -> None:
        """Latch the rig into one of the two grids.

        This is where per-block rotation used to live. It moved here because
        rotation turned out to be a property of the GRID, not of a block: a
        turned block only makes sense inside cells shaped for it. Selecting a
        mode therefore changes the whole coordinate system, which is why it
        goes to the rig instead of being remembered locally, and why any
        pending selection is dropped — `[3,5]` means a different place
        afterwards.
        """
        if self.locked:
            raise BuildStateError(self.locked_reason)
        mode = str(mode).lower()
        if mode not in GRID_MODES:
            raise BuildStateError(f"grid mode must be one of {', '.join(GRID_MODES)}")
        if mode == self.mode:
            return
        if mode == "horizontal" and home_before_horizontal:
            # RR is intentionally rejected until X/Y have a known origin. A
            # request to enter the horizontal layout is an explicit operator
            # action, so home only those two axes here; never make an
            # incidental vertical-mode selection move the rig.
            if not self.rig.home(full=False):
                raise RigError("X/Y home did not reach the origin; horizontal grid was not selected")
        self.rig.set_mode(mode)
        self.selected = None

    def cycle_mode(self, *, home_before_horizontal: bool = False) -> None:
        """Latch the other grid. Two modes, so this is a toggle."""
        current = self.mode
        index = GRID_MODES.index(current) if current in GRID_MODES else 0
        self.set_mode(
            GRID_MODES[(index + 1) % len(GRID_MODES)],
            home_before_horizontal=home_before_horizontal,
        )

    def build(self, timeout: float = 300.0) -> BuildResult:
        """Run one selected cell operation; lock if physical state is unknown."""
        if self.locked:
            raise BuildStateError(self.locked_reason)
        if self.selected is None:
            raise BuildStateError("select a camera grid cell first")

        col, row = self.selected
        try:
            if self.orchestrator is None:
                # Commissioning/tests may still use a staged block and address
                # the Mega directly. Production injects CellOrchestrator.
                result = self.rig.build(col, row, self.level, timeout=timeout)
            else:
                result = self.orchestrator.place_block(
                    col, row, self.level, timeout=timeout)
        except RigError as exc:
            self.locked_reason = (
                f"serial/build state unknown: {exc}; inspect the rig and restart"
            )
            raise

        self.last_result = result
        if str(result) == ABORTED or result.needs_a_human:
            self.locked_reason = (
                result.reason or "build aborted; the claw or machine position may be unknown"
            )
        elif str(result) == PLACED:
            # Requiring a fresh click prevents one Enter key repeat from placing
            # another block into the same occupied cell.
            self.selected = None
        return result

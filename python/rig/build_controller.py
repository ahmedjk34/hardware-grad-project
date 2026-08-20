#!/usr/bin/env python3
"""Safety state for selecting and confirming one camera-driven build."""

from __future__ import annotations

from dataclasses import dataclass

from rig.link import ABORTED, PLACED, BuildResult, RigError


ROTATIONS = ("NR", "R", "RR")


class BuildStateError(RuntimeError):
    """The requested UI action is not safe in the controller's current state."""


@dataclass
class BuildController:
    """Turn a camera-grid cell selection into one explicitly confirmed build.

    The controller deliberately knows nothing about OpenCV. It enforces the
    pieces that must remain true whichever UI calls it: levels cannot be
    negative, successful builds clear selection to prevent accidental repeats,
    and an aborted/unknown serial outcome locks the session until a human has
    inspected the rig and restarts the program.
    """

    rig: object
    level: int = 0
    rotation: str = "NR"
    selected: tuple[int, int] | None = None
    last_result: BuildResult | None = None
    locked_reason: str | None = None

    def __post_init__(self):
        self.set_level(self.level)
        self.set_rotation(self.rotation)

    @property
    def locked(self) -> bool:
        return self.locked_reason is not None

    @property
    def command(self) -> str | None:
        if self.selected is None:
            return None
        col, row = self.selected
        command = f"B {col} {row} {self.level}"
        return command if self.rotation == "NR" else f"{command} {self.rotation}"

    def select(self, cell: tuple[int, int]) -> None:
        if self.locked:
            raise BuildStateError(self.locked_reason)
        col, row = (int(value) for value in cell)
        if not self.rig.grid.contains(col, row):
            raise BuildStateError(
                f"cell [{col},{row}] is outside {self.rig.grid.cols}x{self.rig.grid.rows}"
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

    def set_rotation(self, rotation: str) -> None:
        rotation = str(rotation).upper()
        if rotation not in ROTATIONS:
            raise BuildStateError(f"rotation must be one of {', '.join(ROTATIONS)}")
        self.rotation = rotation

    def cycle_rotation(self) -> None:
        self.rotation = ROTATIONS[(ROTATIONS.index(self.rotation) + 1) % len(ROTATIONS)]

    def build(self, timeout: float = 300.0) -> BuildResult:
        """Send the selected B command once; lock if machine state is unknown."""
        if self.locked:
            raise BuildStateError(self.locked_reason)
        if self.selected is None:
            raise BuildStateError("select a camera grid cell first")

        col, row = self.selected
        try:
            result = self.rig.build(
                col, row, self.level,
                rotation=None if self.rotation == "NR" else self.rotation,
                timeout=timeout,
            )
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

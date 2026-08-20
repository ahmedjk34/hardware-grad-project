#!/usr/bin/env python3
"""The machine's grid, and which way round it sits on the picture.

    from rig.grid import MachineGrid

    grid = MachineGrid.from_config()     # 10 cols x 20 rows, from config/rig.json
    grid.cell_at(0, 19)                  # image cell (left, bottom) -> (1, 1)
    grid.image_cell(3, 5)                # (col, row) -> the image cell to draw in
    print(grid.ascii_map())              # the same picture the rig's '9' prints

Two different grids, and only one of them is real
-------------------------------------------------
The viewers draw an evenly spaced grid over the whole camera frame. The rig
divides its *envelope* into cells. Those are not the same thing and nothing so
far has said how one relates to the other — the viewer's 8x8 was a straightness
ruler, not a map of the machine.

This module fixes the half of that which is knowable without a calibration:
**how many cells there are, how they are numbered, and which corner is [1,1]**.
It does NOT know where the build area sits in the image. Until Plan 2 step 4
clicks four corners, the caller can only spread this grid over the whole frame,
which is very unlikely to be where the build area actually is. Say so on screen.

The numbering, and where it comes from
--------------------------------------
Straight out of `printGrid()` in build_test_v1.ino, which draws this:

      # = machine   . = empty cell
      (top row = far Y end, left col = X switch)

     20 | . . . . . . . . . .
      ...
      1 | . . . . . . . . . .
        +--------------------
         1 2 3 4 5 6 7 8 9 0
         ^ origin corner is bottom-left [1,1]

So: **1-based**, col 1 is the X switch side, row 1 is the Y switch side, and the
machine's own drawing puts [1,1] bottom-left with rows increasing upward. That
is the default here, because a default that matches the rig's picture is the one
you can check by holding the two side by side.

Why the orientation is a setting at all
---------------------------------------
The camera's rotation and mirroring relative to the rig is arbitrary — nobody
has promised that the machine's origin is at the bottom-left of the *image*. So
`origin` names which image corner holds cell [1,1], and `swap_axes` covers a
camera mounted a quarter turn out, where the machine's columns run down the
picture rather than across it. Eight combinations, all reachable, none of them
requiring anyone to think about signs.

Step 4 will derive this from four clicked points instead of from a setting. When
it does, this stays useful as the thing to check the homography against: if the
four clicks disagree with what your eyes say the orientation is, one of them is
wrong and you want to know which.
"""

from __future__ import annotations

from dataclasses import dataclass

from rig.config import load

# Which image corner holds machine cell [1,1].
ORIGIN_CORNERS = ("bottom-left", "bottom-right", "top-left", "top-right")

DEFAULT_ORIGIN = "bottom-left"  # what the firmware's own map draws


@dataclass
class MachineGrid:
    """Cell counts plus the image orientation. No pixels, no OpenCV."""

    cols: int
    rows: int
    origin: str = DEFAULT_ORIGIN
    swap_axes: bool = False

    @classmethod
    def from_config(cls, cfg: dict | None = None, **kwargs) -> "MachineGrid":
        """Read `grid.cols` / `grid.rows` from config/rig.json.

        That block is authoritative at runtime: the Pi pushes it to the board
        with `S <cols> <rows>` on every connect, because opening the port resets
        the board back to its compiled default. See AGENTS.md section 3.
        """
        grid = (cfg if cfg is not None else load())["grid"]
        return cls(cols=int(grid["cols"]), rows=int(grid["rows"]), **kwargs)

    def __post_init__(self):
        if self.origin not in ORIGIN_CORNERS:
            raise ValueError(
                f"origin must be one of {', '.join(ORIGIN_CORNERS)}, not {self.origin!r}"
            )
        if self.cols < 1 or self.rows < 1:
            raise ValueError(f"grid must be at least 1x1, got {self.cols}x{self.rows}")

    # --- how many cells the image is divided into ------------------------

    @property
    def nx(self) -> int:
        """Cells across the image."""
        return self.rows if self.swap_axes else self.cols

    @property
    def ny(self) -> int:
        """Cells down the image."""
        return self.cols if self.swap_axes else self.rows

    @property
    def at_left(self) -> bool:
        return self.origin.endswith("left")

    @property
    def at_bottom(self) -> bool:
        return self.origin.startswith("bottom")

    # --- the mapping ------------------------------------------------------
    # Image cell indices are 0-based with (0, 0) at the TOP-LEFT, because that
    # is where pixels start. Machine cells are 1-based with [1,1] wherever
    # `origin` says. Every sign flip in the project should live in these two
    # methods and nowhere else.

    def cell_at(self, ix: int, iy: int) -> tuple[int, int]:
        """Image cell (ix, iy) -> machine (col, row), both 1-based."""
        if self.swap_axes:
            row = ix + 1 if self.at_left else self.rows - ix
            col = self.cols - iy if self.at_bottom else iy + 1
        else:
            col = ix + 1 if self.at_left else self.cols - ix
            row = self.rows - iy if self.at_bottom else iy + 1
        return col, row

    def image_cell(self, col: int, row: int) -> tuple[int, int]:
        """Machine (col, row) -> image cell (ix, iy). The inverse of cell_at."""
        if self.swap_axes:
            ix = row - 1 if self.at_left else self.rows - row
            iy = self.cols - col if self.at_bottom else col - 1
        else:
            ix = col - 1 if self.at_left else self.cols - col
            iy = self.rows - row if self.at_bottom else row - 1
        return ix, iy

    def contains(self, col: int, row: int) -> bool:
        """The same bounds check `cellInRange()` does on the board."""
        return 1 <= col <= self.cols and 1 <= row <= self.rows

    # --- reporting --------------------------------------------------------

    def matches(self, cfg: dict | None = None) -> bool:
        """Is this still the grid config/rig.json asks for?"""
        grid = (cfg if cfg is not None else load())["grid"]
        return self.cols == int(grid["cols"]) and self.rows == int(grid["rows"])

    def describe(self) -> str:
        turned = ", axes swapped" if self.swap_axes else ""
        return f"{self.cols}x{self.rows} cells, [1,1] at {self.origin}{turned}"

    def ascii_map(self, here: tuple[int, int] | None = None) -> str:
        """Redraw the rig's own `9` map, so the two can be compared line by line.

        Deliberately in the MACHINE's orientation — [1,1] bottom-left, rows
        increasing upward — whatever `origin` says about the camera. The whole
        point is to hold this next to the serial output and see the same
        picture; letting the camera's mounting rotate it would defeat that.

        Byte-for-byte with printGrid(), including the last-digit-only column
        numbers, which the firmware does to keep the map aligned.
        """
        lines = [
            "  # = machine   . = empty cell",
            "  (top row = far Y end, left col = X switch)",
            "",
        ]
        for r in range(self.rows, 0, -1):
            cells = "".join(
                " #" if here == (c, r) else " ."
                for c in range(1, self.cols + 1)
            )
            lines.append(f"{r:>3} |{cells}")
        lines.append("    +" + "--" * self.cols)
        lines.append("     " + " ".join(str(c % 10) for c in range(1, self.cols + 1)) + " ")
        lines.append("     ^ origin corner is bottom-left [1,1]")
        return "\n".join(lines)

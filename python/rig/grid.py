#!/usr/bin/env python3
"""The machine's grid, and which way round it sits on the picture.

    from rig.grid import MachineGrid

    grid = MachineGrid.from_config()     # 9 positive cols x 5 rows
    grid.cell_at(0, 4)                   # image cell (left, bottom) -> (1, 1)
    grid.image_cell(3, 5)                # (col, row) -> the image cell to draw in
    grid.contains_build_target(0, 5)     # calibration target: skip X
    print(grid.ascii_map())              # the same picture the rig's '9' prints

Two different grids, and only one of them is real
-------------------------------------------------
The viewers draw an evenly spaced grid over the whole camera frame. The rig
packs fixed-size block cells inside its motion envelope. Those are not the same
thing and nothing so far has said how one relates to the other — the viewer's
8x8 was a straightness ruler, not a map of the machine.

This module fixes the half of that which is knowable without a calibration:
**how many cells there are, how they are numbered, and which corner is [1,1]**.
It does NOT know where the build area sits in the image. Until Plan 2 step 4
clicks four corners, the caller can only spread this grid over the whole frame,
which is very unlikely to be where the build area actually is. Say so on screen.

The numbering, and where it comes from
--------------------------------------
Straight out of `printGrid()` in build_test_v1.ino: positive block cells are
1-based, while row/col 0 are drawn explicitly as the home and axis-only
coordinates. Col 1 is nearest the X switch and row 1 is nearest the Y switch;
rows increase upward in the machine's own drawing.

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
import math

from rig.config import load

# Which image corner holds machine cell [1,1].
ORIGIN_CORNERS = ("bottom-left", "bottom-right", "top-left", "top-right")

DEFAULT_ORIGIN = "bottom-left"  # what the firmware's own map draws


@dataclass
class MachineGrid:
    """Logical cells plus their physical footprint and image orientation."""

    cols: int
    rows: int
    origin: str = DEFAULT_ORIGIN
    swap_axes: bool = False
    block_width_cm: float | None = None
    block_length_cm: float | None = None
    gap_x_cm: float = 0.0
    gap_y_cm: float = 0.0
    workspace_width_cm: float | None = None
    workspace_height_cm: float | None = None
    trim_x_cm: float = 0.0
    trim_y_cm: float = 0.0

    @classmethod
    def from_config(cls, cfg: dict | None = None, **kwargs) -> "MachineGrid":
        """Read `grid.cols` / `grid.rows` from config/rig.json.

        That block is authoritative at runtime: the Pi pushes it to the board
        with `S <cols> <rows>` on every connect, because opening the port resets
        the board back to its compiled default. See AGENTS.md section 3.
        """
        cfg = cfg if cfg is not None else load()
        grid = cfg["grid"]
        workspace = cfg["workspace"]
        return cls(
            cols=int(grid["cols"]),
            rows=int(grid["rows"]),
            block_width_cm=float(grid["block_width_cm"]),
            block_length_cm=float(grid["block_length_cm"]),
            gap_x_cm=float(grid["gap_x_cm"]),
            gap_y_cm=float(grid["gap_y_cm"]),
            workspace_width_cm=float(workspace["width_cm"]),
            workspace_height_cm=float(workspace["height_cm"]),
            trim_x_cm=float(grid.get("trim_x_cm", 0.0)),
            trim_y_cm=float(grid.get("trim_y_cm", 0.0)),
            **kwargs,
        )

    def __post_init__(self):
        if self.origin not in ORIGIN_CORNERS:
            raise ValueError(
                f"origin must be one of {', '.join(ORIGIN_CORNERS)}, not {self.origin!r}"
            )
        if self.cols < 1 or self.rows < 1:
            raise ValueError(f"grid must be at least 1x1, got {self.cols}x{self.rows}")
        physical = (
            self.block_width_cm,
            self.block_length_cm,
            self.workspace_width_cm,
            self.workspace_height_cm,
        )
        if any(value is not None for value in physical):
            if not all(value is not None and math.isfinite(value) and value > 0
                       for value in physical):
                raise ValueError("block and workspace dimensions must all be positive")
            if not all(math.isfinite(value) and value >= 0
                       for value in (self.gap_x_cm, self.gap_y_cm)):
                raise ValueError("grid gaps must be finite and non-negative")
            if not math.isfinite(self.trim_x_cm) or not math.isfinite(self.trim_y_cm):
                raise ValueError("grid trims must be finite")
            if self.x_first_center_cm < 0 or self.y_first_center_cm < 0 \
                    or self.x_last_center_cm > self.workspace_width_cm \
                    or self.y_last_center_cm > self.workspace_height_cm:
                raise ValueError(
                    f"{self.cols}x{self.rows} block centres do not fit inside "
                    f"the {self.workspace_width_cm:g}x{self.workspace_height_cm:g} cm "
                    "holder-travel envelope"
                )

    @property
    def has_physical_scale(self) -> bool:
        return self.block_width_cm is not None

    @property
    def pitch_x_cm(self) -> float:
        """Centre-to-centre X pitch: 2.2 cm block + 0.5 cm gap = 2.7 cm."""
        return self.block_width_cm + self.gap_x_cm

    @property
    def pitch_y_cm(self) -> float:
        """Centre-to-centre Y pitch: 7.5 cm block + 0.5 cm gap = 8.0 cm."""
        return self.block_length_cm + self.gap_y_cm

    @property
    def packed_width_cm(self) -> float:
        """Positive blocks plus only their eight internal X gaps: 23.8 cm."""
        return self.cols * self.block_width_cm + (self.cols - 1) * self.gap_x_cm

    @property
    def packed_height_cm(self) -> float:
        """Positive blocks plus only their four internal Y gaps: 39.5 cm."""
        return self.rows * self.block_length_cm + (self.rows - 1) * self.gap_y_cm

    @property
    def allocation_width_cm(self) -> float:
        """Home coordinate to the far block edge: 9 * 2.7 = 24.3 cm."""
        return self.cols * self.pitch_x_cm

    @property
    def allocation_height_cm(self) -> float:
        """Home coordinate to the far block edge: 5 * 8.0 = 40.0 cm."""
        return self.rows * self.pitch_y_cm

    @property
    def x_allocation_start_cm(self) -> float:
        return (self.workspace_width_cm - self.allocation_width_cm) / 2 + self.trim_x_cm

    @property
    def y_allocation_start_cm(self) -> float:
        return (self.workspace_height_cm - self.allocation_height_cm) / 2 + self.trim_y_cm

    @property
    def x_start_cm(self) -> float:
        """Near edge of block 1, after the 0-to-1 X gap."""
        return self.x_allocation_start_cm + self.gap_x_cm

    @property
    def y_start_cm(self) -> float:
        """Near edge of row 1, after the 0-to-1 Y gap."""
        return self.y_allocation_start_cm + self.gap_y_cm

    @property
    def x_end_cm(self) -> float:
        return self.x_start_cm + self.packed_width_cm

    @property
    def y_end_cm(self) -> float:
        return self.y_start_cm + self.packed_height_cm

    @property
    def x_first_center_cm(self) -> float:
        return self.x_start_cm + self.block_width_cm / 2

    @property
    def y_first_center_cm(self) -> float:
        return self.y_start_cm + self.block_length_cm / 2

    @property
    def x_last_center_cm(self) -> float:
        return self.x_first_center_cm + (self.cols - 1) * self.pitch_x_cm

    @property
    def y_last_center_cm(self) -> float:
        return self.y_first_center_cm + (self.rows - 1) * self.pitch_y_cm

    def cell_center_cm(self, col: int, row: int) -> tuple[float, float]:
        """Physical centre measured away from the X/Y home-switch corner."""
        if not self.has_physical_scale:
            raise ValueError("this grid has no physical scale")
        if not self.contains(col, row):
            raise ValueError(f"cell [{col},{row}] is outside {self.cols}x{self.rows}")
        return (
            self.x_first_center_cm + (col - 1) * self.pitch_x_cm,
            self.y_first_center_cm + (row - 1) * self.pitch_y_cm,
        )

    def cell_bounds_cm(self, col: int, row: int) -> tuple[float, float, float, float]:
        """Physical block edges, excluding the visible 0.5 cm gaps."""
        cx, cy = self.cell_center_cm(col, row)
        return (
            cx - self.block_width_cm / 2,
            cy - self.block_length_cm / 2,
            cx + self.block_width_cm / 2,
            cy + self.block_length_cm / 2,
        )

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
        """Whether ``[col,row]`` is a real drawable/selectable grid cell."""
        return 1 <= col <= self.cols and 1 <= row <= self.rows

    def contains_build_target(self, col: int, row: int) -> bool:
        """Whether coordinates are valid for the firmware's ``B`` command.

        ``B`` reserves zero independently on each axis for calibration:
        ``B 0 5`` skips X, ``B 9 0`` skips Y, and ``B 0 0`` is a no-op.
        This is deliberately separate from :meth:`contains`, because zero is
        never a camera cell and must not enter image-cell geometry.
        """
        return 0 <= col <= self.cols and 0 <= row <= self.rows

    # --- reporting --------------------------------------------------------

    def matches(self, cfg: dict | None = None) -> bool:
        """Is this still the grid config/rig.json asks for?"""
        other = MachineGrid.from_config(cfg)
        return (
            self.cols == other.cols
            and self.rows == other.rows
            and self.block_width_cm == other.block_width_cm
            and self.block_length_cm == other.block_length_cm
            and self.gap_x_cm == other.gap_x_cm
            and self.gap_y_cm == other.gap_y_cm
            and self.workspace_width_cm == other.workspace_width_cm
            and self.workspace_height_cm == other.workspace_height_cm
            and self.trim_x_cm == other.trim_x_cm
            and self.trim_y_cm == other.trim_y_cm
        )

    def describe(self) -> str:
        turned = ", axes swapped" if self.swap_axes else ""
        physical = ""
        if self.has_physical_scale:
            physical = (
                f", {self.block_width_cm:g}x{self.block_length_cm:g} cm blocks"
                f", {self.gap_x_cm:g}x{self.gap_y_cm:g} cm gaps"
                f", pitch {self.pitch_x_cm:g}x{self.pitch_y_cm:g} cm"
                f", footprint {self.packed_width_cm:g}x{self.packed_height_cm:g} cm"
            )
        return f"{self.cols}x{self.rows} cells{physical}, [1,1] at {self.origin}{turned}"

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
            "  # = machine   . = positive cell   + = axis-only   H = home",
            "  (row/col 0 are real coordinates; positive cells are 1-based)",
            "",
        ]
        for r in range(self.rows, -1, -1):
            cells = ""
            for c in range(0, self.cols + 1):
                if here == (c, r):
                    marker = "#"
                elif c == 0 and r == 0:
                    marker = "H"
                elif c == 0 or r == 0:
                    marker = "+"
                else:
                    marker = "."
                cells += f" {marker}"
            lines.append(f"{r:>3} |{cells}")
        lines.append("    +" + "--" * (self.cols + 1))
        lines.append("     " + " ".join(str(c % 10) for c in range(0, self.cols + 1)))
        lines.append("     ^ [0,0] home; [col,0]/[0,row] are axis-only")
        return "\n".join(lines)

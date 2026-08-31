#!/usr/bin/env python3
"""The machine's grid, and which way round it sits on the picture.

    from rig.grid import MachineGrid

    grid = MachineGrid.from_config()                   # the active mode
    grid = MachineGrid.from_config(mode="horizontal")  # 3 positive cols x 15 rows
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

Two orientations, and both of them are real
-------------------------------------------
A block can stand with its 7.5 cm side along Y (`vertical`, 9 x 5) or lie with
that side along X (`horizontal`, 3 x 15). These are separate grids with
separate counts, separate trims and separate calibrations, and `mode` names
which one this object is. Every mode declares both `block_x_cm` and
`block_y_cm` outright, so nothing in this module swaps an X extent for a Y one
- see plans/dual-orientation-grid.md D12 for why that matters.

`mode` is emphatically NOT `swap_axes`. `swap_axes` is about the CAMERA: it
covers a lens mounted a quarter turn out, where the machine's columns run down
the picture rather than across it. `mode` is about the BLOCK. The two are
independent, and a horizontal grid seen through a turned camera needs both.

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

from rig.config import (active_grid_mode, grid_geometry, load,
                        max_edge_overhang_cm)

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
    # Which block orientation this grid is. None means "nobody said", which is
    # how the count-only/legacy drawings are still constructed.
    mode: str | None = None
    # The block's extent along each machine axis, stated outright per mode.
    block_x_cm: float | None = None
    block_y_cm: float | None = None
    gap_x_cm: float = 0.0
    gap_y_cm: float = 0.0
    workspace_width_cm: float | None = None
    workspace_height_cm: float | None = None
    trim_x_cm: float = 0.0
    trim_y_cm: float = 0.0
    # How far past the travel limit this mode lets a placed block's own EDGE
    # sit. Not a trim: it moves nothing, it is what the geometry check measures
    # the block edges against. None means "do not check edges at all", which is
    # what a count-only grid and a pre-D20 saved calibration get.
    max_edge_overhang_x_cm: float | None = None
    max_edge_overhang_y_cm: float | None = None
    # AI AGENT NOTE: For any user-marked "error" offsetting, use these fields.
    # They apply exactly like trim_x_cm/trim_y_cm and shift every grid centre.
    error_offset_x_cm: float = 0.0
    error_offset_y_cm: float = 0.0
    # --- the derived horizontal Y lattice ---------------------------------
    # A horizontal block is a vertical block turned 90 degrees, so the
    # horizontal Y grid is the vertical Y grid read at DOUBLE density: each
    # vertical row holds two horizontal rows, its lower and upper 2.2 cm.
    # That makes the Y gaps alternate, and it makes row 0 start part-way out.
    # Both are derived from the vertical mode's entry by from_config().
    #
    # None/0.0 means "not derived" and gives a plain uniform lattice, which is
    # what a count-only or directly constructed grid gets.
    gap_y_alt_cm: float | None = None   # the second, wider gap (1.6)
    y_lattice_start_cm: float = 0.0     # how far row 0 sits from home (3.8)

    @classmethod
    def from_config(cls, cfg: dict | None = None, mode: str | None = None,
                    **kwargs) -> "MachineGrid":
        """Read one `grid.modes.<mode>` entry from config/rig.json.

        `mode=None` means the file's own `grid.active_mode`. An unknown name
        raises :class:`rig.config.UnknownGridMode`, not a KeyError.

        That block is authoritative at runtime: the Pi pushes the mode and then
        `S <cols> <rows>` on every connect, because opening the port resets the
        board back to its compiled vertical default. See AGENTS.md section 3.
        """
        cfg = cfg if cfg is not None else load()
        name = active_grid_mode(cfg) if mode is None else str(mode)
        grid = grid_geometry(cfg, name)
        workspace = cfg["workspace"]
        return cls(
            cols=int(grid["cols"]),
            rows=int(grid["rows"]),
            mode=name,
            block_x_cm=float(grid["block_x_cm"]),
            block_y_cm=float(grid["block_y_cm"]),
            gap_x_cm=float(grid["gap_x_cm"]),
            gap_y_cm=float(grid["gap_y_cm"]),
            workspace_width_cm=float(workspace["width_cm"]),
            workspace_height_cm=float(workspace["height_cm"]),
            trim_x_cm=float(grid.get("trim_x_cm", 0.0)),
            trim_y_cm=float(grid.get("trim_y_cm", 0.0)),
            max_edge_overhang_x_cm=max_edge_overhang_cm(grid, "x"),
            max_edge_overhang_y_cm=max_edge_overhang_cm(grid, "y"),
            error_offset_x_cm=float(grid.get("error_offset_x_cm", 0.0)),
            error_offset_y_cm=float(grid.get("error_offset_y_cm", 0.0)),
            **cls._derived_y_lattice(cfg, name, grid),
            **kwargs,
        )

    @staticmethod
    def _derived_y_lattice(cfg: dict, name: str, grid: dict) -> dict:
        """The horizontal Y lattice, read off the VERTICAL mode's geometry.

        Y is derived from Y - no axis is ever swapped for the other, so
        plans/dual-orientation-grid.md D12 still holds. D12 forbids swapping a
        width for a length; it does not forbid one mode's grid being defined in
        terms of the other's, which is a physical fact about a turned block.

        Reads the vertical entry rather than hardcoding 6.0/0.8, so re-measuring
        the block moves both grids together instead of only one of them.
        """
        if name != "horizontal":
            return {}
        try:
            vertical = grid_geometry(cfg, "vertical")
        except Exception:
            # A config with no vertical mode cannot derive one. Fall back to a
            # uniform lattice rather than guessing at the numbers.
            return {}
        vertical_block_y = float(vertical["block_y_cm"])
        block_y = float(grid["block_y_cm"])
        return {
            # what is left of a vertical block once both horizontal rows are out
            "gap_y_alt_cm": vertical_block_y - 2 * block_y,
            # row 0 is the UPPER half of vertical row 0
            "y_lattice_start_cm": vertical_block_y - block_y,
        }

    def __post_init__(self):
        if self.origin not in ORIGIN_CORNERS:
            raise ValueError(
                f"origin must be one of {', '.join(ORIGIN_CORNERS)}, not {self.origin!r}"
            )
        if self.cols < 1 or self.rows < 1:
            raise ValueError(f"grid must be at least 1x1, got {self.cols}x{self.rows}")
        physical = (
            self.block_x_cm,
            self.block_y_cm,
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
            if not all(math.isfinite(value) for value in (
                    self.trim_x_cm, self.trim_y_cm,
                    self.error_offset_x_cm, self.error_offset_y_cm)):
                raise ValueError("grid trims and error offsets must be finite")
            if self.x_first_center_cm < 0 or self.y_first_center_cm < 0 \
                    or self.x_last_center_cm > self.workspace_width_cm \
                    or self.y_last_center_cm > self.workspace_height_cm:
                raise ValueError(
                    f"{self.cols}x{self.rows} block centres do not fit inside "
                    f"the {self.workspace_width_cm:g}x{self.workspace_height_cm:g} cm "
                    "holder-travel envelope"
                )
            self._check_block_edges()

    def _check_block_edges(self) -> None:
        """The other half of the geometry check: where the BLOCKS end up.

        The centre check above asks only whether the holder can reach every
        placement point. That accepts a grid whose far block hangs off the
        machine, because the centre it hangs from is legal — see
        plans/dual-orientation-grid.md R2. This is the firmware's
        `gridGeometryFits` block-edge half, kept identical on purpose.
        """
        slack = 1e-4
        axes = (
            ("X", self.max_edge_overhang_x_cm, self.x_start_cm, self.x_end_cm,
             self.workspace_width_cm),
            ("Y", self.max_edge_overhang_y_cm, self.y_start_cm, self.y_end_cm,
             self.workspace_height_cm),
        )
        for name, budget, near, far, travel in axes:
            if budget is None:
                continue
            if not math.isfinite(budget) or budget < 0:
                raise ValueError("max edge overhang must be finite and non-negative")
            if near < -budget - slack:
                raise ValueError(
                    f"{self.cols}x{self.rows} {name} block edges start "
                    f"{-near:g} cm before home, past this mode's "
                    f"{budget:g} cm overhang budget"
                )
            if far > travel + budget + slack:
                raise ValueError(
                    f"{self.cols}x{self.rows} {name} block edges reach {far:g} cm, "
                    f"past the {travel:g} cm travel limit plus this mode's "
                    f"{budget:g} cm overhang budget"
                )

    @property
    def has_physical_scale(self) -> bool:
        return self.block_x_cm is not None

    # --- the lattice --------------------------------------------------------
    # Mirrors gridSlotBottomCmOf() in build_test_v1.ino exactly. Coordinate 0 is
    # a REAL block whose outer edge sits on the home corner: the lattice is
    # ANCHORED there, not centred in the travel the way it used to be.
    #
    # Three of the four axes are uniform, so slot i sits at i * pitch. The
    # fourth - horizontal Y - is the vertical Y lattice read at double density,
    # and its gaps therefore alternate. See SECTION 6C of the sketch.

    @property
    def max_col(self) -> int:
        """Highest valid column index. The firmware's `S` speaks in these."""
        return self.cols - 1

    @property
    def max_row(self) -> int:
        return self.rows - 1

    @property
    def alternates_y(self) -> bool:
        """Is Y the derived, alternating-gap axis?

        Keyed off the DERIVATION being present, not off the mode name: a
        horizontal grid built without ``gap_y_alt_cm`` (a count-only drawing, a
        legacy saved calibration, or a config with no vertical mode to derive
        from) has a plain uniform lattice and must not pretend otherwise.
        """
        return (self.mode == "horizontal"
                and self.gap_y_alt_cm is not None
                and self.gap_y_alt_cm != self.gap_y_cm)

    @property
    def pitch_x_cm(self) -> float:
        """Centre-to-centre X pitch: block + gap. Vertical 3.8, horizontal 7.6 cm."""
        return self.block_x_cm + self.gap_x_cm

    @property
    def pitch_y_cm(self) -> float:
        """Centre-to-centre Y pitch: block + gap.

        Vertical 6.8 cm. For horizontal this is the *even-row* pitch (3.0) and
        NOT the whole story - see :attr:`mean_pitch_y_cm` and
        :meth:`slot_bottom_y_cm`. Nothing that positions the machine may use it.
        """
        return self.block_y_cm + self.gap_y_cm

    @property
    def inner_gap_y_cm(self) -> float:
        """The second, wider gap on an alternating axis.

        Horizontal Y alternates two gaps: ``gap_y_cm`` (0.8 - between two
        vertical blocks) and this one (1.6 - the middle of a single vertical
        block, what is left once both 2.2 cm horizontal rows are taken out of
        it). :meth:`from_config` derives it from the vertical mode's entry.
        """
        return self.gap_y_alt_cm if self.gap_y_alt_cm is not None else self.gap_y_cm

    @property
    def mean_pitch_y_cm(self) -> float:
        """Reporting only. Horizontal Y steps 3.0, 3.8, 3.0, 3.8 - mean 3.4."""
        if not self.alternates_y:
            return self.pitch_y_cm
        return self.block_y_cm + (self.gap_y_cm + self.inner_gap_y_cm) / 2

    def gap_before_row_cm(self, row: int) -> float:
        """Gap between row-1 and row. Alternates 0.8 / 1.6 on horizontal."""
        if row < 1:
            return 0.0
        if not self.alternates_y:
            return self.gap_y_cm
        # Odd row = a lower half following an upper half = between two vertical
        # blocks. Even row = the two halves of one vertical block.
        return self.gap_y_cm if row % 2 else self.inner_gap_y_cm

    def slot_bottom_x_cm(self, col: int) -> float:
        """Near edge of column `col`, measured from the X home switch."""
        return (self.trim_x_cm + self.error_offset_x_cm
                + col * self.pitch_x_cm)

    def slot_bottom_y_cm(self, row: int) -> float:
        """Near edge of `row`, measured from the Y home switch."""
        base = self.trim_y_cm + self.error_offset_y_cm
        if not self.alternates_y:
            return base + row * self.pitch_y_cm
        # Horizontal row r is sub-slot (r+1) of the vertical lattice: even rows
        # are the UPPER half of a vertical row, odd rows the lower half. One
        # vertical row spans two horizontal rows plus the gap between them.
        vertical_pitch = 2 * self.block_y_cm + self.inner_gap_y_cm + self.gap_y_cm
        whole = (row + 1) // 2
        bottom = whole * vertical_pitch
        if row % 2 == 0:
            bottom += self.y_lattice_start_cm
        return base + bottom

    @property
    def x_start_cm(self) -> float:
        """Near edge of column 0 - on the home corner unless trimmed."""
        return self.slot_bottom_x_cm(0)

    @property
    def y_start_cm(self) -> float:
        """Near edge of row 0. Horizontal starts 3.8 cm out; see above."""
        return self.slot_bottom_y_cm(0)

    @property
    def x_end_cm(self) -> float:
        return self.slot_bottom_x_cm(self.max_col) + self.block_x_cm

    @property
    def y_end_cm(self) -> float:
        return self.slot_bottom_y_cm(self.max_row) + self.block_y_cm

    @property
    def packed_width_cm(self) -> float:
        """Blocks plus the gaps between them: vertical 25.0, horizontal 21.2."""
        return self.x_end_cm - self.x_start_cm

    @property
    def packed_height_cm(self) -> float:
        """Vertical 40.0 cm; horizontal 36.2 cm (11 rows, alternating gaps)."""
        return self.y_end_cm - self.y_start_cm

    @property
    def allocation_width_cm(self) -> float:
        """Home corner to the far X block edge."""
        return self.x_end_cm

    @property
    def allocation_height_cm(self) -> float:
        """Home corner to the far Y block edge. 40.0 cm in BOTH modes."""
        return self.y_end_cm

    @property
    def x_allocation_start_cm(self) -> float:
        return self.x_start_cm

    @property
    def y_allocation_start_cm(self) -> float:
        return self.y_start_cm

    @property
    def x_first_center_cm(self) -> float:
        return self.slot_bottom_x_cm(0) + self.block_x_cm / 2

    @property
    def y_first_center_cm(self) -> float:
        return self.slot_bottom_y_cm(0) + self.block_y_cm / 2

    @property
    def x_last_center_cm(self) -> float:
        return self.slot_bottom_x_cm(self.max_col) + self.block_x_cm / 2

    @property
    def y_last_center_cm(self) -> float:
        return self.slot_bottom_y_cm(self.max_row) + self.block_y_cm / 2

    def cell_center_cm(self, col: int, row: int) -> tuple[float, float]:
        """Physical centre measured away from the X/Y home-switch corner."""
        if not self.has_physical_scale:
            raise ValueError("this grid has no physical scale")
        if not self.contains(col, row):
            raise ValueError(f"cell [{col},{row}] is outside {self.cols}x{self.rows}")
        return (
            self.slot_bottom_x_cm(col) + self.block_x_cm / 2,
            self.slot_bottom_y_cm(row) + self.block_y_cm / 2,
        )

    # --- the feeder ---------------------------------------------------------

    def feeder_center_cm(self) -> tuple[float, float]:
        """Where the claw descends to pick up, in BOTH modes.

        The feeder never rotates: a block is always presented standing, on the
        VERTICAL [0,0] footprint. So this is read off the vertical geometry and
        does not move when the horizontal mode is latched. It is that cell's
        CENTRE, not raw home - home is its outer corner.
        """
        vertical = (self if self.mode != "horizontal"
                    else MachineGrid.from_config(mode="vertical"))
        return (vertical.trim_x_cm + vertical.error_offset_x_cm
                + vertical.block_x_cm / 2,
                vertical.trim_y_cm + vertical.error_offset_y_cm
                + vertical.block_y_cm / 2)

    @staticmethod
    def is_feeder(col: int, row: int) -> bool:
        """[0,0] is the feeder in both modes and is never built on."""
        return col == 0 and row == 0

    def cell_bounds_cm(self, col: int, row: int) -> tuple[float, float, float, float]:
        """Physical block edges, excluding the visible 0.5 cm gaps."""
        cx, cy = self.cell_center_cm(col, row)
        return (
            cx - self.block_x_cm / 2,
            cy - self.block_y_cm / 2,
            cx + self.block_x_cm / 2,
            cy + self.block_y_cm / 2,
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
    # is where pixels start. Machine cells are ALSO 0-based now, with [0,0]
    # wherever `origin` says - coordinate zero is a real block, so it is a
    # drawable camera cell like any other. Every sign flip in the project should
    # live in these two methods and nowhere else.

    def cell_at(self, ix: int, iy: int) -> tuple[int, int]:
        """Image cell (ix, iy) -> machine (col, row), both 0-based."""
        if self.swap_axes:
            row = ix if self.at_left else self.max_row - ix
            col = self.max_col - iy if self.at_bottom else iy
        else:
            col = ix if self.at_left else self.max_col - ix
            row = self.max_row - iy if self.at_bottom else iy
        return col, row

    def image_cell(self, col: int, row: int) -> tuple[int, int]:
        """Machine (col, row) -> image cell (ix, iy). The inverse of cell_at."""
        if self.swap_axes:
            ix = row if self.at_left else self.max_row - row
            iy = self.max_col - col if self.at_bottom else col
        else:
            ix = col if self.at_left else self.max_col - col
            iy = self.max_row - row if self.at_bottom else row
        return ix, iy

    def contains(self, col: int, row: int) -> bool:
        """Whether ``[col,row]`` is a real drawable/selectable grid cell.

        Zero included: it is a real block footprint now, not a bare home point.
        """
        return 0 <= col < self.cols and 0 <= row < self.rows

    def contains_build_target(self, col: int, row: int) -> bool:
        """Whether coordinates are valid for the firmware's ``B`` command.

        Every cell except the feeder. ``[0,0]`` is where blocks come FROM in
        both modes, so ``B 0 0`` stays the inert no-op it has always been -
        but ``B 0 3`` and ``B 4 0`` are ordinary placements now, where they
        used to be the "move one axis only" calibration sentinel.
        """
        return self.contains(col, row) and not self.is_feeder(col, row)

    # --- reporting --------------------------------------------------------

    def matches(self, cfg: dict | None = None) -> bool:
        """Is this still the grid config/rig.json asks for, in this same mode?

        Compared against THIS grid's own mode rather than the config's active
        one, so the question stays "has my geometry drifted" rather than
        turning into "has the operator latched the other orientation".
        """
        other = MachineGrid.from_config(cfg, mode=self.mode)
        return (
            self.mode == other.mode
            and self.cols == other.cols
            and self.rows == other.rows
            and self.block_x_cm == other.block_x_cm
            and self.block_y_cm == other.block_y_cm
            and self.gap_x_cm == other.gap_x_cm
            and self.gap_y_cm == other.gap_y_cm
            and self.workspace_width_cm == other.workspace_width_cm
            and self.workspace_height_cm == other.workspace_height_cm
            and self.trim_x_cm == other.trim_x_cm
            and self.trim_y_cm == other.trim_y_cm
            and self.max_edge_overhang_x_cm == other.max_edge_overhang_x_cm
            and self.max_edge_overhang_y_cm == other.max_edge_overhang_y_cm
            and self.error_offset_x_cm == other.error_offset_x_cm
            and self.error_offset_y_cm == other.error_offset_y_cm
        )

    def describe(self) -> str:
        turned = ", axes swapped" if self.swap_axes else ""
        named = f"{self.mode} " if self.mode else ""
        physical = ""
        if self.has_physical_scale:
            physical = (
                f", {self.block_x_cm:g}x{self.block_y_cm:g} cm blocks"
                f", {self.gap_x_cm:g}x{self.gap_y_cm:g} cm gaps"
                f", pitch {self.pitch_x_cm:g}x{self.pitch_y_cm:g} cm"
                f", footprint {self.packed_width_cm:g}x{self.packed_height_cm:g} cm"
            )
        return (f"{named}{self.cols}x{self.rows} cells{physical}"
                f", [1,1] at {self.origin}{turned}")

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
            "  # = machine   . = buildable cell   F = feeder",
            "  (every cell is a real block; [0,0] is the feeder)",
            "",
        ]
        for r in range(self.max_row, -1, -1):
            cells = ""
            for c in range(0, self.cols):
                if here == (c, r):
                    marker = "#"
                elif self.is_feeder(c, r):
                    marker = "F"
                else:
                    marker = "."
                cells += f" {marker}"
            lines.append(f"{r:>3} |{cells}")
        lines.append("    +" + "--" * self.cols)
        lines.append("     " + " ".join(str(c % 10) for c in range(0, self.cols)))
        lines.append("     ^ [0,0] feeder; every other cell is buildable")
        return "\n".join(lines)

#!/usr/bin/env python3
"""Four-corner camera-to-machine mapping for click-to-build.

The saved points are normalized corrected-image coordinates.  The homography
therefore survives display scaling and output resolution changes; it does not
pretend to survive changing the lens projection/FOV after calibration.

New maps use the real holder-motion rectangle: home/home, far-X/home-Y,
far-X/far-Y, and home-X/far-Y. The mapped dimensions are the 24.3 x 40 cm
holder displacements in rig.json. Positive cells begin after the explicit
0.5 cm home-to-cell-1 gaps and then repeat at block-plus-gap pitch. Coordinate
zero remains the home/axis-only reference; it is not silently converted into
another positive block inside the measured rectangle.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rig.config import DEFAULT_GRID_MODE, GRID_MODES
from rig.grid import MachineGrid


WORKSPACE_MAP_PATH = Path(__file__).resolve().parents[2] / "config" / "workspace_map.json"
CORNER_NAMES = (
    "holder home [0,0]",
    "far-X/home-Y holder limit",
    "far-X/far-Y holder limit",
    "home-X/far-Y holder limit",
)


# Maps saved before plans/dual-orientation-grid.md named the two block extents
# `block_width_cm` / `block_length_cm`. They meant exactly X and Y, so reading
# them under the new names is a rename, not a reinterpretation.
_LEGACY_BLOCK_KEYS = {"x": "block_width_cm", "y": "block_length_cm"}


def _block_cm(geometry: dict, axis: str) -> float:
    key = f"block_{axis}_cm"
    if key in geometry:
        return geometry[key]
    return geometry[_LEGACY_BLOCK_KEYS[axis]]


def _homography(src, dst):
    """Return the projective transform taking four ``src`` points to ``dst``."""
    rows = []
    values = []
    for (x, y), (u, v) in zip(src, dst):
        rows += [[x, y, 1, 0, 0, 0, -u * x, -u * y],
                 [0, 0, 0, x, y, 1, -v * x, -v * y]]
        values += [u, v]
    try:
        h = np.linalg.solve(np.asarray(rows, dtype=float), np.asarray(values, dtype=float))
    except np.linalg.LinAlgError as exc:
        raise ValueError("workspace corners are degenerate; click four distinct corners") from exc
    return np.append(h, 1.0).reshape(3, 3)


def _project(matrix, point):
    out = matrix @ np.asarray((point[0], point[1], 1.0), dtype=float)
    if abs(out[2]) < 1e-12:
        raise ValueError("workspace mapping reaches infinity")
    return float(out[0] / out[2]), float(out[1] / out[2])


@dataclass
class WorkspaceMap:
    """Map corrected-image pixels to the rig's 1-based ``[col,row]`` cells."""

    cols: int
    rows: int
    # Normalized image points in CORNER_NAMES order.
    corners: list[tuple[float, float]]
    projection: dict | None = None
    physical_grid: dict | None = None
    # A calibration belongs to a block orientation as well as a camera.  Flat
    # v2 maps predate that distinction and are migrated as vertical on read.
    mode: str = DEFAULT_GRID_MODE

    def __post_init__(self):
        if self.cols < 1 or self.rows < 1:
            raise ValueError("workspace grid dimensions must be positive")
        if self.mode not in GRID_MODES:
            raise ValueError(
                f"workspace map mode must be one of {', '.join(GRID_MODES)}, "
                f"not {self.mode!r}")
        if len(self.corners) != 4:
            raise ValueError("workspace map needs exactly four corners")
        self.corners = [(float(x), float(y)) for x, y in self.corners]
        if not all(math.isfinite(v) for point in self.corners for v in point):
            raise ValueError("workspace corners must be finite")
        if not all(0.0 <= v <= 1.0 for point in self.corners for v in point):
            raise ValueError("normalized workspace corners must lie inside the image")
        crosses = []
        for index in range(4):
            a, b, c = (np.asarray(self.corners[(index + offset) % 4])
                       for offset in range(3))
            ab, bc = b - a, c - b
            crosses.append(float(ab[0] * bc[1] - ab[1] * bc[0]))
        if min(abs(value) for value in crosses) < 1e-6 or not (
                all(value > 0 for value in crosses) or all(value < 0 for value in crosses)):
            raise ValueError("workspace corners must form one convex quadrilateral in prompt order")
        # Machine coordinates increase from [1,1] along cols, then rows.
        machine_square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        self._to_machine = _homography(self.corners, machine_square)
        self._to_image = _homography(machine_square, self.corners)
        self._grid = None
        if self.physical_grid is not None:
            geometry = self.physical_grid
            self._grid = MachineGrid(
                cols=self.cols,
                rows=self.rows,
                block_x_cm=float(_block_cm(geometry, "x")),
                block_y_cm=float(_block_cm(geometry, "y")),
                gap_x_cm=float(geometry["gap_x_cm"]),
                gap_y_cm=float(geometry["gap_y_cm"]),
                workspace_width_cm=float(geometry["workspace_width_cm"]),
                workspace_height_cm=float(geometry["workspace_height_cm"]),
                trim_x_cm=float(geometry.get("trim_x_cm", 0.0)),
                trim_y_cm=float(geometry.get("trim_y_cm", 0.0)),
                max_edge_overhang_x_cm=(
                    float(geometry["max_edge_overhang_x_cm"])
                    if "max_edge_overhang_x_cm" in geometry else None),
                max_edge_overhang_y_cm=(
                    float(geometry["max_edge_overhang_y_cm"])
                    if "max_edge_overhang_y_cm" in geometry else None),
                error_offset_x_cm=float(geometry.get("error_offset_x_cm", 0.0)),
                error_offset_y_cm=float(geometry.get("error_offset_y_cm", 0.0)),
                mode=self.mode,
            )

    @classmethod
    def from_pixels(cls, cols, rows, corners, image_size, projection=None,
                    mode=DEFAULT_GRID_MODE):
        w, h = image_size
        if w <= 0 or h <= 0:
            raise ValueError("image size must be positive")
        return cls(cols, rows, [(x / w, y / h) for x, y in corners], projection,
                   mode=mode)

    @classmethod
    def from_grid(cls, grid: MachineGrid, corners, image_size, projection=None):
        """Map four camera points around the measured holder-motion rectangle."""
        if not grid.has_physical_scale:
            raise ValueError("workspace mapping needs a physically scaled grid")
        w, h = image_size
        if w <= 0 or h <= 0:
            raise ValueError("image size must be positive")
        geometry = {
            "workspace_width_cm": grid.workspace_width_cm,
            "workspace_height_cm": grid.workspace_height_cm,
            "block_x_cm": grid.block_x_cm,
            "block_y_cm": grid.block_y_cm,
            "gap_x_cm": grid.gap_x_cm,
            "gap_y_cm": grid.gap_y_cm,
            "trim_x_cm": grid.trim_x_cm,
            "trim_y_cm": grid.trim_y_cm,
            "max_edge_overhang_x_cm": grid.max_edge_overhang_x_cm,
            "max_edge_overhang_y_cm": grid.max_edge_overhang_y_cm,
            "error_offset_x_cm": grid.error_offset_x_cm,
            "error_offset_y_cm": grid.error_offset_y_cm,
        }
        return cls(grid.cols, grid.rows, [(x / w, y / h) for x, y in corners],
                   projection, geometry, grid.mode or DEFAULT_GRID_MODE)

    @classmethod
    def load(cls, path=WORKSPACE_MAP_PATH, cols=None, rows=None, *, mode=None):
        path = Path(path)
        data = json.loads(path.read_text())
        version = int(data.get("version", 0))
        wanted = DEFAULT_GRID_MODE if mode is None else str(mode)
        if wanted not in GRID_MODES:
            raise ValueError(
                f"workspace map mode must be one of {', '.join(GRID_MODES)}, "
                f"not {wanted!r}")
        if version == 2:
            # A flat map was necessarily made for the only grid that existed:
            # vertical.  Read it without pretending it calibrated horizontal.
            if wanted != DEFAULT_GRID_MODE:
                raise ValueError(
                    f"legacy workspace map has only a {DEFAULT_GRID_MODE} calibration; "
                    f"no {wanted} calibration is saved")
            entry = data
        elif version == 3:
            modes = data.get("modes")
            if not isinstance(modes, dict):
                raise ValueError("workspace map modes must be an object")
            if wanted not in modes:
                raise ValueError(
                    f"workspace map has no {wanted} calibration; recalibrate that mode")
            entry = modes[wanted]
            if not isinstance(entry, dict):
                raise ValueError(f"workspace map {wanted} calibration must be an object")
        else:
            raise ValueError("workspace map uses obsolete pre-gap geometry; recalibrate")
        result = cls(int(entry["grid"]["cols"]), int(entry["grid"]["rows"]),
                     [tuple(p) for p in entry["corners_normalized"]],
                     entry.get("projection"), entry.get("physical_grid"), wanted)
        if cols is not None and rows is not None and (result.cols, result.rows) != (cols, rows):
            raise ValueError(
                f"workspace map is for {result.cols}x{result.rows}, config is {cols}x{rows}"
            )
        return result

    def _entry(self):
        """The per-mode portion of the v3 JSON document."""
        payload = {
            "grid": {"cols": self.cols, "rows": self.rows},
            "corners_normalized": [[x, y] for x, y in self.corners],
            "projection": self.projection,
        }
        if self.physical_grid is not None:
            payload["physical_grid"] = self.physical_grid
        return payload

    @staticmethod
    def _document_from_legacy(data):
        """Normalize a v2/v3 document without discarding another mode."""
        version = int(data.get("version", 0))
        if version == 3:
            modes = data.get("modes")
            if not isinstance(modes, dict):
                raise ValueError("workspace map modes must be an object")
            return data
        if version == 2:
            entry = {
                key: data[key] for key in
                ("grid", "corners_normalized", "projection", "physical_grid")
                if key in data
            }
            return {
                "version": 3,
                "view": data.get("view", "corrected"),
                "corner_order": data.get("corner_order", list(CORNER_NAMES)),
                "modes": {DEFAULT_GRID_MODE: entry},
            }
        raise ValueError("workspace map uses obsolete pre-gap geometry; recalibrate")

    def save(self, path=WORKSPACE_MAP_PATH, *, mode=None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        wanted = self.mode if mode is None else str(mode)
        if wanted not in GRID_MODES:
            raise ValueError(
                f"workspace map mode must be one of {', '.join(GRID_MODES)}, "
                f"not {wanted!r}")
        if wanted != self.mode:
            raise ValueError(
                f"cannot save a {self.mode} calibration as {wanted}; regenerate it "
                "from that mode's MachineGrid")
        if path.exists():
            document = self._document_from_legacy(json.loads(path.read_text()))
        else:
            document = {
                "version": 3,
                "view": "corrected",
                "corner_order": list(CORNER_NAMES),
                "modes": {},
            }
        document["version"] = 3
        document.setdefault("view", "corrected")
        document.setdefault("corner_order", list(CORNER_NAMES))
        document["modes"][wanted] = self._entry()
        path.write_text(json.dumps(document, indent=2) + "\n")
        return path

    def matches_grid(self, grid: MachineGrid, *, mode=None) -> bool:
        """Whether this calibration was made for the complete current geometry.

        ``mode`` is optional only because ``MachineGrid`` already carries it;
        accepting it makes an accidental caller-side mode mismatch explicit at
        the same seam as :meth:`load` and :meth:`save`.
        """
        if self.physical_grid is None or not grid.has_physical_scale:
            return False
        wanted = grid.mode if mode is None else str(mode)
        if wanted not in GRID_MODES:
            return False
        geometry = self.physical_grid
        return (
            self.mode == wanted
            and grid.mode == wanted
            and
            (self.cols, self.rows) == (grid.cols, grid.rows)
            and float(geometry["workspace_width_cm"]) == grid.workspace_width_cm
            and float(geometry["workspace_height_cm"]) == grid.workspace_height_cm
            and float(_block_cm(geometry, "x")) == grid.block_x_cm
            and float(_block_cm(geometry, "y")) == grid.block_y_cm
            and float(geometry["gap_x_cm"]) == grid.gap_x_cm
            and float(geometry["gap_y_cm"]) == grid.gap_y_cm
            and float(geometry.get("trim_x_cm", 0.0)) == grid.trim_x_cm
            and float(geometry.get("trim_y_cm", 0.0)) == grid.trim_y_cm
            # v2 maps did not record D20's safety budget. Its absence means
            # "unknown", not a different camera mapping, so preserve their
            # vertical migration; new v3 entries compare it exactly.
            and ("max_edge_overhang_x_cm" not in geometry
                 or float(geometry["max_edge_overhang_x_cm"])
                 == grid.max_edge_overhang_x_cm)
            and ("max_edge_overhang_y_cm" not in geometry
                 or float(geometry["max_edge_overhang_y_cm"])
                 == grid.max_edge_overhang_y_cm)
            and float(geometry.get("error_offset_x_cm", 0.0)) == grid.error_offset_x_cm
            and float(geometry.get("error_offset_y_cm", 0.0)) == grid.error_offset_y_cm
        )

    def normalized_at(self, point, image_size):
        w, h = image_size
        return _project(self._to_machine, (point[0] / w, point[1] / h))

    def cell_at(self, point, image_size):
        """Return ``(col,row)`` or None when the pixel is outside the quadrilateral."""
        u, v = self.normalized_at(point, image_size)
        epsilon = 1e-9
        if u < -epsilon or v < -epsilon or u > 1 + epsilon or v > 1 + epsilon:
            return None
        u, v = min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0)
        if self._grid is None:
            return min(int(u * self.cols), self.cols - 1) + 1, \
                   min(int(v * self.rows), self.rows - 1) + 1

        g = self._grid
        x_cm = u * g.workspace_width_cm
        y_cm = v * g.workspace_height_cm
        epsilon = 1e-9
        if x_cm < g.x_start_cm - epsilon or x_cm > g.x_end_cm + epsilon \
                or y_cm < g.y_start_cm - epsilon or y_cm > g.y_end_cm + epsilon:
            return None
        col = min(int((x_cm - g.x_start_cm) / g.pitch_x_cm), self.cols - 1) + 1
        row = min(int((y_cm - g.y_start_cm) / g.pitch_y_cm), self.rows - 1) + 1
        x0, y0, x1, y1 = g.cell_bounds_cm(col, row)
        if not (x0 - epsilon <= x_cm <= x1 + epsilon
                and y0 - epsilon <= y_cm <= y1 + epsilon):
            # The click is in one of the deliberate 0.5 cm gaps.
            return None
        return col, row

    @property
    def has_physical_grid(self) -> bool:
        return self._grid is not None

    @property
    def mapped_grid(self) -> MachineGrid | None:
        """The MachineGrid actually used for this map's pixel<->cm math.

        It is reconstructed from the geometry embedded in the generated map,
        so a saved calibration cannot silently borrow newer block/gap values.
        """
        return self._grid

    def axis_lane_polygon(self, axis, index, image_size):
        """Image polygon for the axis-only lane cell ``[index,0]`` or ``[0,index]``.

        Coordinate zero is a holder-home *axis*, not a second physical block.
        It is drawn as a gap-wide strip immediately outside the holder envelope.
        A full block centred on home overlaps horizontal cell [1,*], whose near
        edge is only 0.65 cm from home.
        """
        if self._grid is None:
            raise ValueError("axis lanes need a physically scaled grid")
        g = self._grid
        if axis == "col":
            x0_cm, _y0, x1_cm, _y1 = g.cell_bounds_cm(index, 1)
            y0_cm, y1_cm = -g.gap_y_cm, 0.0
        elif axis == "row":
            _x0, y0_cm, _x1, y1_cm = g.cell_bounds_cm(1, index)
            x0_cm, x1_cm = -g.gap_x_cm, 0.0
        else:
            raise ValueError("axis must be 'col' or 'row'")
        corners_cm = ((x0_cm, y0_cm), (x1_cm, y0_cm), (x1_cm, y1_cm), (x0_cm, y1_cm))
        return [self.pixel_at(x / g.workspace_width_cm, y / g.workspace_height_cm,
                              image_size) for x, y in corners_cm]

    def origin_polygon(self, image_size):
        """Gap-sized home marker immediately outside real ``[0,0]``."""
        if self._grid is None:
            raise ValueError("the origin cell needs a physically scaled grid")
        g = self._grid
        x0_cm, x1_cm = -g.gap_x_cm, 0.0
        y0_cm, y1_cm = -g.gap_y_cm, 0.0
        corners_cm = ((x0_cm, y0_cm), (x1_cm, y0_cm), (x1_cm, y1_cm), (x0_cm, y1_cm))
        return [self.pixel_at(x / g.workspace_width_cm, y / g.workspace_height_cm,
                              image_size) for x, y in corners_cm]

    def target_polygon(self, col, row, image_size):
        """Image polygon for any valid B/G target - 0 on either axis included.

        Positive cells draw their real block footprint. Zero-axis targets draw
        non-overlapping home-axis strips.
        """
        if col > 0 and row > 0:
            return self.cell_polygon(col, row, image_size)
        if col == 0 and row == 0:
            return self.origin_polygon(image_size)
        if row == 0:
            return self.axis_lane_polygon("col", col, image_size)
        return self.axis_lane_polygon("row", row, image_size)

    def axis_lane_at(self, point, image_size):
        """Return the axis-only target a pixel falls on, or None.

        ``(col, 0)`` in the row-0 lane (Y held at the origin), ``(0, row)``
        in the column-0 lane (X held at the origin), or ``(0, 0)`` where both
        lanes overlap - the machine origin itself.
        Distinct from :meth:`cell_at`, which only returns positive cells.
        """
        if self._grid is None:
            return None
        g = self._grid
        u, v = self.normalized_at(point, image_size)
        x_cm = u * g.workspace_width_cm
        y_cm = v * g.workspace_height_cm
        epsilon = 1e-9
        row0_lane_y0, row0_lane_y1 = -g.gap_y_cm, 0.0
        col0_lane_x0, col0_lane_x1 = -g.gap_x_cm, 0.0
        in_row0_lane_y = row0_lane_y0 - epsilon <= y_cm <= row0_lane_y1 + epsilon
        in_col0_lane_x = col0_lane_x0 - epsilon <= x_cm <= col0_lane_x1 + epsilon
        if in_col0_lane_x and in_row0_lane_y:
            return (0, 0)
        if in_row0_lane_y:
            for col in range(1, g.cols + 1):
                x0, _y0, x1, _y1 = g.cell_bounds_cm(col, 1)
                if x0 - epsilon <= x_cm <= x1 + epsilon:
                    return (col, 0)
        if in_col0_lane_x:
            for row in range(1, g.rows + 1):
                _x0, y0, _x1, y1 = g.cell_bounds_cm(1, row)
                if y0 - epsilon <= y_cm <= y1 + epsilon:
                    return (0, row)
        return None

    def pixel_at(self, u, v, image_size):
        """Project normalized machine-envelope coordinates into image pixels."""
        x, y = _project(self._to_image, (u, v))
        return x * image_size[0], y * image_size[1]

    def cell_polygon(self, col, row, image_size):
        if self._grid is None:
            u0, u1 = (col - 1) / self.cols, col / self.cols
            v0, v1 = (row - 1) / self.rows, row / self.rows
        else:
            x0, y0, x1, y1 = self._grid.cell_bounds_cm(col, row)
            u0, u1 = x0 / self._grid.workspace_width_cm, x1 / self._grid.workspace_width_cm
            v0, v1 = y0 / self._grid.workspace_height_cm, y1 / self._grid.workspace_height_cm
        return [self.pixel_at(u0, v0, image_size), self.pixel_at(u1, v0, image_size),
                self.pixel_at(u1, v1, image_size), self.pixel_at(u0, v1, image_size)]

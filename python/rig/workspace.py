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

from rig.grid import MachineGrid


WORKSPACE_MAP_PATH = Path(__file__).resolve().parents[2] / "config" / "workspace_map.json"
CORNER_NAMES = (
    "holder home [0,0]",
    "far-X/home-Y holder limit",
    "far-X/far-Y holder limit",
    "home-X/far-Y holder limit",
)


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

    def __post_init__(self):
        if self.cols < 1 or self.rows < 1:
            raise ValueError("workspace grid dimensions must be positive")
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
                block_width_cm=float(geometry["block_width_cm"]),
                block_length_cm=float(geometry["block_length_cm"]),
                gap_x_cm=float(geometry["gap_x_cm"]),
                gap_y_cm=float(geometry["gap_y_cm"]),
                workspace_width_cm=float(geometry["workspace_width_cm"]),
                workspace_height_cm=float(geometry["workspace_height_cm"]),
                trim_x_cm=float(geometry.get("trim_x_cm", 0.0)),
                trim_y_cm=float(geometry.get("trim_y_cm", 0.0)),
            )

    @classmethod
    def from_pixels(cls, cols, rows, corners, image_size, projection=None):
        w, h = image_size
        if w <= 0 or h <= 0:
            raise ValueError("image size must be positive")
        return cls(cols, rows, [(x / w, y / h) for x, y in corners], projection)

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
            "block_width_cm": grid.block_width_cm,
            "block_length_cm": grid.block_length_cm,
            "gap_x_cm": grid.gap_x_cm,
            "gap_y_cm": grid.gap_y_cm,
            "trim_x_cm": grid.trim_x_cm,
            "trim_y_cm": grid.trim_y_cm,
        }
        return cls(grid.cols, grid.rows, [(x / w, y / h) for x, y in corners],
                   projection, geometry)

    @classmethod
    def load(cls, path=WORKSPACE_MAP_PATH, cols=None, rows=None):
        path = Path(path)
        data = json.loads(path.read_text())
        if int(data.get("version", 0)) != 2:
            raise ValueError("workspace map uses obsolete pre-gap geometry; recalibrate")
        result = cls(int(data["grid"]["cols"]), int(data["grid"]["rows"]),
                     [tuple(p) for p in data["corners_normalized"]],
                     data.get("projection"), data.get("physical_grid"))
        if cols is not None and rows is not None and (result.cols, result.rows) != (cols, rows):
            raise ValueError(
                f"workspace map is for {result.cols}x{result.rows}, config is {cols}x{rows}"
            )
        return result

    def save(self, path=WORKSPACE_MAP_PATH):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 2,
            "view": "corrected",
            "corner_order": list(CORNER_NAMES),
            "grid": {"cols": self.cols, "rows": self.rows},
            "corners_normalized": [[x, y] for x, y in self.corners],
            "projection": self.projection,
        }
        if self.physical_grid is not None:
            payload["physical_grid"] = self.physical_grid
        path.write_text(json.dumps(payload, indent=2) + "\n")
        return path

    def matches_grid(self, grid: MachineGrid) -> bool:
        """Whether this calibration was made for the complete current geometry."""
        if self.physical_grid is None or not grid.has_physical_scale:
            return False
        geometry = self.physical_grid
        return (
            (self.cols, self.rows) == (grid.cols, grid.rows)
            and float(geometry["workspace_width_cm"]) == grid.workspace_width_cm
            and float(geometry["workspace_height_cm"]) == grid.workspace_height_cm
            and float(geometry["block_width_cm"]) == grid.block_width_cm
            and float(geometry["block_length_cm"]) == grid.block_length_cm
            and float(geometry["gap_x_cm"]) == grid.gap_x_cm
            and float(geometry["gap_y_cm"]) == grid.gap_y_cm
            and float(geometry.get("trim_x_cm", 0.0)) == grid.trim_x_cm
            and float(geometry.get("trim_y_cm", 0.0)) == grid.trim_y_cm
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

        The zero axis is the actual holder-home coordinate. Consequently half
        of the block footprint may project outside the measured motion quad;
        it is not replaced with a fabricated full-pitch lane inside the grid.
        """
        if self._grid is None:
            raise ValueError("axis lanes need a physically scaled grid")
        g = self._grid
        if axis == "col":
            x_center, _ = g.cell_center_cm(index, 1)
            x0_cm = x_center - g.block_width_cm / 2
            x1_cm = x_center + g.block_width_cm / 2
            y0_cm = -g.block_length_cm / 2
            y1_cm = g.block_length_cm / 2
        elif axis == "row":
            _, y_center = g.cell_center_cm(1, index)
            y0_cm = y_center - g.block_length_cm / 2
            y1_cm = y_center + g.block_length_cm / 2
            x0_cm = -g.block_width_cm / 2
            x1_cm = g.block_width_cm / 2
        else:
            raise ValueError("axis must be 'col' or 'row'")
        corners_cm = ((x0_cm, y0_cm), (x1_cm, y0_cm), (x1_cm, y1_cm), (x0_cm, y1_cm))
        return [self.pixel_at(x / g.workspace_width_cm, y / g.workspace_height_cm,
                              image_size) for x, y in corners_cm]

    def origin_polygon(self, image_size):
        """Block-sized visualization centred on the real ``[0,0]`` home."""
        if self._grid is None:
            raise ValueError("the origin cell needs a physically scaled grid")
        g = self._grid
        x0_cm, x1_cm = -g.block_width_cm / 2, g.block_width_cm / 2
        y0_cm, y1_cm = -g.block_length_cm / 2, g.block_length_cm / 2
        corners_cm = ((x0_cm, y0_cm), (x1_cm, y0_cm), (x1_cm, y1_cm), (x0_cm, y1_cm))
        return [self.pixel_at(x / g.workspace_width_cm, y / g.workspace_height_cm,
                              image_size) for x, y in corners_cm]

    def target_polygon(self, col, row, image_size):
        """Image polygon for any valid B/G target - 0 on either axis included.

        Always one block-sized visualization: a positive ``[col,row]`` block,
        a footprint centred on ``[0,0]`` home, or an axis-only target.
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
        row0_lane_y0 = -g.block_length_cm / 2
        row0_lane_y1 = g.block_length_cm / 2
        col0_lane_x0 = -g.block_width_cm / 2
        col0_lane_x1 = g.block_width_cm / 2
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

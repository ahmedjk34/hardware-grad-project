#!/usr/bin/env python3
"""Four-corner camera-to-machine mapping for click-to-build.

The saved points are normalized corrected-image coordinates.  The homography
therefore survives display scaling and output resolution changes; it does not
pretend to survive changing the lens projection/FOV after calibration.

New maps use the four corners of the complete 34 x 40 cm machine envelope and
retain the centred margins around the 33 x 37.5 cm block grid. Count-only maps
remain readable for compatibility, but stretch their cells across the quad.
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
    "machine envelope X/Y home corner",
    "machine envelope far-X/home-Y corner",
    "machine envelope far-X/far-Y corner",
    "machine envelope home-X/far-Y corner",
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
                cell_width_cm=float(geometry["cell_width_cm"]),
                cell_height_cm=float(geometry["cell_height_cm"]),
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
        """Map four camera points around the full physical X/Y envelope.

        Unlike the legacy count-only constructor, this preserves the centred
        leftover strips and the signed X/Y trims instead of stretching the
        packed block grid to fill the complete camera quadrilateral.
        """
        if not grid.has_physical_scale:
            raise ValueError("workspace mapping needs a physically scaled grid")
        w, h = image_size
        if w <= 0 or h <= 0:
            raise ValueError("image size must be positive")
        geometry = {
            "workspace_width_cm": grid.workspace_width_cm,
            "workspace_height_cm": grid.workspace_height_cm,
            "cell_width_cm": grid.cell_width_cm,
            "cell_height_cm": grid.cell_height_cm,
            "trim_x_cm": grid.trim_x_cm,
            "trim_y_cm": grid.trim_y_cm,
        }
        return cls(grid.cols, grid.rows, [(x / w, y / h) for x, y in corners],
                   projection, geometry)

    @classmethod
    def load(cls, path=WORKSPACE_MAP_PATH, cols=None, rows=None):
        path = Path(path)
        data = json.loads(path.read_text())
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
            "version": 1,
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
            and float(geometry["cell_width_cm"]) == grid.cell_width_cm
            and float(geometry["cell_height_cm"]) == grid.cell_height_cm
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

        x_cm = u * self._grid.workspace_width_cm
        y_cm = v * self._grid.workspace_height_cm
        epsilon = 1e-9
        if x_cm < self._grid.x_start_cm - epsilon \
                or x_cm > self._grid.x_end_cm + epsilon \
                or y_cm < self._grid.y_start_cm - epsilon \
                or y_cm > self._grid.y_end_cm + epsilon:
            return None
        col = min(int((x_cm - self._grid.x_start_cm) / self._grid.cell_width_cm),
                  self.cols - 1) + 1
        row = min(int((y_cm - self._grid.y_start_cm) / self._grid.cell_height_cm),
                  self.rows - 1) + 1
        return col, row

    @property
    def has_physical_grid(self) -> bool:
        return self._grid is not None

    def axis_lane_polygon(self, axis, index, image_size):
        """Image polygon for the axis-only lane cell ``[index,0]`` or ``[0,index]``.

        Full block size, one cell-pitch beyond the packed grid's near edge -
        the same size as every other cell, not squeezed into whatever trim
        the calibration happens to have. ``B``/``G``'s axis-only convention
        (0 on one axis means "stay at the origin") lands here, so a build
        site there is exactly as real, and exactly as big, as any other.
        """
        if self._grid is None:
            raise ValueError("axis lanes need a physically scaled grid")
        g = self._grid
        if axis == "col":
            x0_cm = g.x_start_cm + (index - 1) * g.cell_width_cm
            x1_cm = g.x_start_cm + index * g.cell_width_cm
            y1_cm = g.y_start_cm
            y0_cm = y1_cm - g.cell_height_cm
        elif axis == "row":
            y0_cm = g.y_start_cm + (index - 1) * g.cell_height_cm
            y1_cm = g.y_start_cm + index * g.cell_height_cm
            x1_cm = g.x_start_cm
            x0_cm = x1_cm - g.cell_width_cm
        else:
            raise ValueError("axis must be 'col' or 'row'")
        corners_cm = ((x0_cm, y0_cm), (x1_cm, y0_cm), (x1_cm, y1_cm), (x0_cm, y1_cm))
        return [self.pixel_at(x / g.workspace_width_cm, y / g.workspace_height_cm,
                              image_size) for x, y in corners_cm]

    def origin_polygon(self, image_size):
        """Image polygon for the ``[0,0]`` home cell - block-sized, like any other.

        Home is a real place blocks get picked up from, not just a point: one
        cell-pitch back from [1,1] on both axes, where the col-0 and row-0
        lanes overlap.
        """
        if self._grid is None:
            raise ValueError("the origin cell needs a physically scaled grid")
        g = self._grid
        x0_cm, x1_cm = g.x_start_cm - g.cell_width_cm, g.x_start_cm
        y0_cm, y1_cm = g.y_start_cm - g.cell_height_cm, g.y_start_cm
        corners_cm = ((x0_cm, y0_cm), (x1_cm, y0_cm), (x1_cm, y1_cm), (x0_cm, y1_cm))
        return [self.pixel_at(x / g.workspace_width_cm, y / g.workspace_height_cm,
                              image_size) for x, y in corners_cm]

    def target_polygon(self, col, row, image_size):
        """Image polygon for any valid B/G target - 0 on either axis included.

        Always one full block-sized cell: a normal ``[col,row]`` polygon, the
        ``[0,0]`` home cell, or whichever axis-only lane cell the non-zero
        coordinate picks out.
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
        Distinct from :meth:`cell_at`, which only ever returns a real
        1-based block cell. Each lane is a full block-sized cell, so it can
        extend past the calibrated envelope corner when the real trim is
        smaller than one cell pitch; that is fine for hit-testing here even
        though :meth:`cell_at` deliberately refuses points outside the quad.
        """
        if self._grid is None:
            return None
        g = self._grid
        u, v = self.normalized_at(point, image_size)
        x_cm = u * g.workspace_width_cm
        y_cm = v * g.workspace_height_cm
        epsilon = 1e-9
        row0_lane_y0 = g.y_start_cm - g.cell_height_cm
        col0_lane_x0 = g.x_start_cm - g.cell_width_cm
        in_row0_lane_y = row0_lane_y0 - epsilon <= y_cm <= g.y_start_cm + epsilon
        in_col0_lane_x = col0_lane_x0 - epsilon <= x_cm <= g.x_start_cm + epsilon
        if in_col0_lane_x and in_row0_lane_y:
            return (0, 0)
        if in_row0_lane_y and g.x_start_cm - epsilon <= x_cm <= g.x_end_cm + epsilon:
            col = min(int((x_cm - g.x_start_cm) / g.cell_width_cm), g.cols - 1) + 1
            return (col, 0)
        if in_col0_lane_x and g.y_start_cm - epsilon <= y_cm <= g.y_end_cm + epsilon:
            row = min(int((y_cm - g.y_start_cm) / g.cell_height_cm), g.rows - 1) + 1
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
            u0 = (self._grid.x_start_cm
                  + (col - 1) * self._grid.cell_width_cm) \
                 / self._grid.workspace_width_cm
            u1 = (self._grid.x_start_cm + col * self._grid.cell_width_cm) \
                 / self._grid.workspace_width_cm
            v0 = (self._grid.y_start_cm
                  + (row - 1) * self._grid.cell_height_cm) \
                 / self._grid.workspace_height_cm
            v1 = (self._grid.y_start_cm + row * self._grid.cell_height_cm) \
                 / self._grid.workspace_height_cm
        return [self.pixel_at(u0, v0, image_size), self.pixel_at(u1, v0, image_size),
                self.pixel_at(u1, v1, image_size), self.pixel_at(u0, v1, image_size)]

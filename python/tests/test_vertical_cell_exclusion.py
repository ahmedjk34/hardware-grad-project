#!/usr/bin/env python3
"""Geometry regression tests for horizontal-mode vertical-remnant filtering."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.grid import MachineGrid  # noqa: E402
from rig.workspace import WorkspaceMap  # noqa: E402
from vision.vertical_cell_exclusion import (  # noqa: E402
    VERTICAL_CELL_CONTAINMENT_MARGIN_CM,
    exclude_vertical_cell_remnants,
    fully_within_vertical_cell,
)


SIZE = (1000, 800)
VERTICAL = MachineGrid.from_config(mode="vertical")
HORIZONTAL = MachineGrid.from_config(mode="horizontal")
VERTICAL_MAP = WorkspaceMap.from_grid(
    VERTICAL, ((0, 0), (1000, 0), (1000, 800), (0, 800)), SIZE)


def detection_from_cm(corners):
    pixels = [VERTICAL_MAP.pixel_at(x / VERTICAL.workspace_width_cm,
                                    y / VERTICAL.workspace_height_cm, SIZE)
              for x, y in corners]
    box = np.asarray(pixels, dtype=np.float64)
    return SimpleNamespace(box=box, center=tuple(box.mean(axis=0)))


def shifted(bounds, dx=0.0, dy=0.0):
    left, bottom, right, top = bounds
    return ((left + dx, bottom + dy), (right + dx, bottom + dy),
            (right + dx, top + dy), (left + dx, top + dy))


vertical_bounds = VERTICAL.cell_bounds_cm(3, 2)
seated_vertical = detection_from_cm(shifted(vertical_bounds))

assert fully_within_vertical_cell(seated_vertical, VERTICAL_MAP, SIZE)
assert exclude_vertical_cell_remnants([seated_vertical], VERTICAL_MAP, SIZE) == []

# The live outline can redraw ``box`` to the population median.  The feature
# must use its preserved measured dimensions/bearing instead of that display
# rectangle.  Here the displayed box is deliberately too wide to fit while the
# original 2.2 x 6.0 cm vertical footprint does fit.
centre = VERTICAL.cell_center_cm(3, 2)
centre_px = VERTICAL_MAP.pixel_at(centre[0] / VERTICAL.workspace_width_cm,
                                  centre[1] / VERTICAL.workspace_height_cm, SIZE)
rectified_lookalike = SimpleNamespace(
    box=np.asarray(((0, 0), (999, 0), (999, 799), (0, 799)), dtype=np.float64),
    center=centre_px,
    measured_width=VERTICAL.block_x_cm / VERTICAL.workspace_width_cm * SIZE[0],
    measured_height=VERTICAL.block_y_cm / VERTICAL.workspace_height_cm * SIZE[1],
    measured_angle=90.0,
)
assert fully_within_vertical_cell(rectified_lookalike, VERTICAL_MAP, SIZE)

# 2.9 mm past the boundary remains inside the 3 mm acceptance allowance;
# 3.1 mm does not.  The whole footprint is shifted so this tests containment,
# not a single corner's special case.
inside_margin = detection_from_cm(shifted(vertical_bounds,
                                          dx=VERTICAL_CELL_CONTAINMENT_MARGIN_CM - 0.01))
outside_margin = detection_from_cm(shifted(vertical_bounds,
                                           dx=VERTICAL_CELL_CONTAINMENT_MARGIN_CM + 0.01))
assert fully_within_vertical_cell(inside_margin, VERTICAL_MAP, SIZE)
assert not fully_within_vertical_cell(outside_margin, VERTICAL_MAP, SIZE)

# A horizontal block cannot fit a 2.2 cm-wide vertical cell, so a valid
# horizontal target is retained even where the two lattices spatially overlap.
horizontal_bounds = HORIZONTAL.cell_bounds_cm(1, 4)
horizontal_block = detection_from_cm(shifted(horizontal_bounds))
assert not fully_within_vertical_cell(horizontal_block, VERTICAL_MAP, SIZE)
assert exclude_vertical_cell_remnants([seated_vertical, horizontal_block],
                                      VERTICAL_MAP, SIZE) == [horizontal_block]

# Missing/incorrect companion geometry fails open: never hide a block.
assert exclude_vertical_cell_remnants([seated_vertical], None, SIZE) == [seated_vertical]
assert not fully_within_vertical_cell(seated_vertical, object(), SIZE)

print("all vertical-cell exclusion checks passed")

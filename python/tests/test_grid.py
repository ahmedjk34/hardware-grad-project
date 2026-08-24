#!/usr/bin/env python3
"""Check rig/grid.py against the firmware's own grid map.

    cd python
    ../.venv/bin/python tests/test_grid.py

The acceptance criterion for Plan 2 step 3 is "the labels on screen match what
`9` prints on the rig". `9` is `printGrid()` in build_test_v1.ino, and the
expected map below is transcribed from it — so this is the desktop half of that
check, and holding `map` next to a real `9` is the other half.
"""

import os
from pathlib import Path
import math
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rig.grid import ORIGIN_CORNERS, MachineGrid
from rig.config import load
from rig.workspace import WorkspaceMap

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:38} {detail}")


# ------------------------------------------------------------------
# The map, transcribed from printGrid() with GRID_COLS=4, GRID_ROWS=3
# ------------------------------------------------------------------

EXPECTED = """  # = machine   . = positive cell   + = axis-only   H = home
  (row/col 0 are real coordinates; positive cells are 1-based)

  3 | + . . . .
  2 | + . . . .
  1 | + . . . .
  0 | H + + + +
    +----------
     0 1 2 3 4
     ^ [0,0] home; [col,0]/[0,row] are axis-only"""

small = MachineGrid(cols=4, rows=3)
check("ascii_map matches printGrid()", small.ascii_map() == EXPECTED)
if small.ascii_map() != EXPECTED:
    print("--- got ---\n" + small.ascii_map() + "\n--- want ---\n" + EXPECTED)

# The '#' marks the machine, and [1,1] is bottom-left — so it lands on the
# LAST line of cells, not the first.
marked = small.ascii_map(here=(1, 1)).splitlines()
check("'#' at [1,1] is bottom-left", marked[5] == "  1 | + # . . .", repr(marked[5]))
check("home and axis-only row are explicit", marked[6] == "  0 | H + + + +")

# Column numbers are last-digit-only, as the firmware does to keep alignment.
wide = MachineGrid(cols=12, rows=2).ascii_map().splitlines()
check("column numbers are c % 10", wide[-2].strip() == "0 1 2 3 4 5 6 7 8 9 0 1 2",
      repr(wide[-2]))


# ------------------------------------------------------------------
# The image mapping
# ------------------------------------------------------------------

g = MachineGrid(cols=22, rows=5)  # count-only orientation stress case
check("divisions across/down", (g.nx, g.ny) == (22, 5), f"{g.nx}x{g.ny}")

# Default orientation is the rig's own picture: [1,1] bottom-left.
check("[1,1] is bottom-left", g.cell_at(0, 4) == (1, 1), str(g.cell_at(0, 4)))
check("[22,5] is top-right", g.cell_at(21, 0) == (22, 5), str(g.cell_at(21, 0)))
check("col 1 is the left column", g.cell_at(0, 2)[0] == 1)
check("row 1 is the bottom row", g.cell_at(10, 4)[1] == 1)

# Every corner and both axis assignments must round-trip, and must put [1,1]
# in the corner they are named after. This is the whole reason the setting
# exists: eight mountings, no sign-juggling anywhere else in the project.
for origin in ORIGIN_CORNERS:
    for swap in (False, True):
        m = MachineGrid(cols=22, rows=5, origin=origin, swap_axes=swap)

        trips = all(
            m.cell_at(*m.image_cell(c, r)) == (c, r)
            for c in range(1, 23)
            for r in range(1, 6)
        )
        check(f"round-trip {origin}{' swapped' if swap else ''}", trips)

        seen = {m.cell_at(ix, iy) for ix in range(m.nx) for iy in range(m.ny)}
        check(f"covers every cell {origin}{' swapped' if swap else ''}",
              len(seen) == 110)

        ix, iy = m.image_cell(1, 1)
        want = (0 if m.at_left else m.nx - 1, m.ny - 1 if m.at_bottom else 0)
        check(f"[1,1] lands at {origin}{' swapped' if swap else ''}",
              (ix, iy) == want, f"{(ix, iy)} want {want}")

# A quarter-turned camera swaps which way the image is divided.
turned = MachineGrid(cols=22, rows=5, swap_axes=True)
check("swapaxes flips the divisions", (turned.nx, turned.ny) == (5, 22),
      f"{turned.nx}x{turned.ny}")


# ------------------------------------------------------------------
# Config and bounds
# ------------------------------------------------------------------

config = load()
from_cfg = MachineGrid.from_config(config)
check("from_config matches rig.json", from_cfg.matches(), from_cfg.describe())
check("bounds are 1-based, like cellInRange()",
      from_cfg.contains(1, 1) and not from_cfg.contains(0, 1)
      and from_cfg.contains(9, 5) and not from_cfg.contains(10, 5))
check("build target allows zero on either axis",
      from_cfg.contains_build_target(0, 5)
      and from_cfg.contains_build_target(9, 0)
      and from_cfg.contains_build_target(0, 0))
check("build target still rejects negative/outside coordinates",
      not from_cfg.contains_build_target(-1, 1)
      and not from_cfg.contains_build_target(10, 0)
      and not from_cfg.contains_build_target(0, 6))
check("block/internal-gap footprint is 23.8x39.5 cm",
      math.isclose(from_cfg.packed_width_cm, 23.8)
      and math.isclose(from_cfg.packed_height_cm, 39.5))
check("one-grid-span allocation is 24.3x40 cm",
      math.isclose(from_cfg.allocation_width_cm, 24.3)
      and math.isclose(from_cfg.allocation_height_cm, 40.0))
check("full allocation has the measured feeder-to-grid shifts",
      math.isclose(from_cfg.x_allocation_start_cm, 1.1)
      and math.isclose(from_cfg.y_allocation_start_cm, 3.75))
check("first blocks begin after feeder half-size plus the 0.5 cm gap",
      math.isclose(from_cfg.x_start_cm, 1.6)
      and math.isclose(from_cfg.y_start_cm, 4.25))
check("first physical cell centre",
      all(math.isclose(a, b) for a, b in
          zip(from_cfg.cell_center_cm(1, 1), (2.7, 8.0))))
check("last physical cell centre",
      all(math.isclose(a, b) for a, b in
          zip(from_cfg.cell_center_cm(9, 5), (24.3, 40.0))))
check("all placement centres remain inside holder travel",
      from_cfg.x_first_center_cm >= 0 and from_cfg.y_first_center_cm >= 0
      and from_cfg.x_last_center_cm <= from_cfg.workspace_width_cm
      and from_cfg.y_last_center_cm <= from_cfg.workspace_height_cm)
check("block footprint reaches past the last holder centres",
      math.isclose(from_cfg.x_end_cm, 25.4)
      and math.isclose(from_cfg.y_end_cm, 43.75))

# The Mega cannot read rig.json, so its safe manual-monitor defaults are baked
# into the sketch. Keep this executable check beside the AGENTS.md pairing rule
# so an agent changing JSON alone gets a loud failure before flashing.
sketch_path = Path(__file__).resolve().parents[2] / \
    "arduino" / "build_test_v1" / "build_test_v1.ino"
sketch = sketch_path.read_text()


def firmware_number(name):
    match = re.search(
        rf"^\s*(?:float|long)\s+{re.escape(name)}\s*=\s*([-+]?\d+(?:\.\d+)?)\s*;",
        sketch,
        re.MULTILINE,
    )
    return float(match.group(1)) if match else None


paired_values = {
    "GRID_COLS": from_cfg.cols,
    "GRID_ROWS": from_cfg.rows,
    "X_TRAVEL_CM": from_cfg.workspace_width_cm,
    "Y_TRAVEL_CM": from_cfg.workspace_height_cm,
    "GRID_BLOCK_X_CM": from_cfg.block_width_cm,
    "GRID_BLOCK_Y_CM": from_cfg.block_length_cm,
    "GRID_GAP_X_CM": from_cfg.gap_x_cm,
    "GRID_GAP_Y_CM": from_cfg.gap_y_cm,
    "GRID_TRIM_X_CM": from_cfg.trim_x_cm,
    "GRID_TRIM_Y_CM": from_cfg.trim_y_cm,
}
tool_offsets = config["tool_offsets"]
paired_values.update({
    "TOOL_OFFSET_NEUTRAL_X_CM": float(tool_offsets["neutral"]["x_cm"]),
    "TOOL_OFFSET_NEUTRAL_Y_CM": float(tool_offsets["neutral"]["y_cm"]),
    "TOOL_OFFSET_CW_X_CM": float(tool_offsets["cw"]["x_cm"]),
    "TOOL_OFFSET_CW_Y_CM": float(tool_offsets["cw"]["y_cm"]),
    "TOOL_OFFSET_CCW_X_CM": float(tool_offsets["ccw"]["x_cm"]),
    "TOOL_OFFSET_CCW_Y_CM": float(tool_offsets["ccw"]["y_cm"]),
})
for name, expected in paired_values.items():
    actual = firmware_number(name)
    check(f"firmware/config pair {name}", actual == expected,
          f"firmware {actual}, JSON {expected}")

# This is a firmware-only safety setting. It must not be copied into
# rig.json, but the desktop check should still make an accidental change
# of the live Y cap visible before flashing.
y_soft_limit = firmware_number("SOFT_LIMIT_Y_TRAVEL")
check("live Y software limit is 8250 steps", y_soft_limit == 8250,
      f"firmware {y_soft_limit}")
y_steps_per_cm = y_soft_limit / from_cfg.workspace_height_cm
y_row_targets = [round(from_cfg.cell_center_cm(1, row)[1] * y_steps_per_cm)
                 for row in range(1, from_cfg.rows + 1)]
check("Y feeder-centre row targets are 8 cm apart",
      y_row_targets == [1650, 3300, 4950, 6600, 8250],
      f"targets {y_row_targets}")
x_soft_limit = firmware_number("SOFT_LIMIT_X_TRAVEL")
check("live X software limit is 4750 steps", x_soft_limit == 4750,
      f"firmware {x_soft_limit}")

try:
    MachineGrid(cols=22, rows=5, origin="middle")
    check("bad origin is refused", False)
except ValueError:
    check("bad origin is refused", True)


# ------------------------------------------------------------------
# Four-corner workspace mapping (Plan 2 step 4)
# ------------------------------------------------------------------

# Deliberately skewed and rotated: this catches implementations that merely
# use an axis-aligned bounding box instead of a projective mapping.
corners = [(80, 420), (570, 360), (520, 40), (120, 70)]
workspace = WorkspaceMap.from_pixels(10, 20, corners, (640, 480))
for point, expected in zip(corners, ((1, 1), (10, 1), (10, 20), (1, 20))):
    check(f"workspace corner maps to {expected}",
          workspace.cell_at(point, (640, 480)) == expected)

centre = workspace.pixel_at(0.45, 0.225, (640, 480))
check("workspace projective round-trip",
      workspace.cell_at(centre, (640, 480)) == (5, 5), str(centre))
check("workspace rejects outside click",
      workspace.cell_at((0, 0), (640, 480)) is None)

# Physical mapping uses the 24.3x40 cm holder-motion rectangle. The feeder
# centre is home; each grid axis begins after half a feeder block plus the gap.
physical_workspace = WorkspaceMap.from_grid(from_cfg, corners, (640, 480))
check("physical workspace matches grid JSON", physical_workspace.matches_grid(from_cfg))
first_centre = physical_workspace.pixel_at(2.7 / 24.3, 8.0 / 40.0, (640, 480))
last_centre = physical_workspace.pixel_at(24.3 / 24.3, 40.0 / 40.0, (640, 480))
check("physical camera map finds first cell",
      physical_workspace.cell_at(first_centre, (640, 480)) == (1, 1))
check("physical camera map finds last cell",
      physical_workspace.cell_at(last_centre, (640, 480)) == (9, 5))
check("physical camera map preserves home gap",
      physical_workspace.cell_at(corners[0], (640, 480)) is None)
gap_point = physical_workspace.pixel_at(4.05 / 24.3, 8.0 / 40.0, (640, 480))
check("physical camera map preserves internal gap",
      physical_workspace.cell_at(gap_point, (640, 480)) is None)

# Normalized storage makes a simple resolution change harmless.
double_corners = [(x * 2, y * 2) for x, y in corners]
for point, expected in zip(double_corners, ((1, 1), (10, 1), (10, 20), (1, 20))):
    check(f"workspace survives resize {expected}",
          workspace.cell_at(point, (1280, 960)) == expected)

try:
    WorkspaceMap(10, 20, [(0, 0)] * 4)
    check("degenerate workspace refused", False)
except ValueError:
    check("degenerate workspace refused", True)

try:
    WorkspaceMap(10, 20, [(0.1, 0.9), (0.9, 0.1), (0.9, 0.9), (0.1, 0.1)])
    check("crossed workspace refused", False)
except ValueError:
    check("crossed workspace refused", True)

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
sys.exit(1 if FAILED else 0)

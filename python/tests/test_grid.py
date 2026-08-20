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
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rig.grid import ORIGIN_CORNERS, MachineGrid

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:38} {detail}")


# ------------------------------------------------------------------
# The map, transcribed from printGrid() with GRID_COLS=4, GRID_ROWS=3
# ------------------------------------------------------------------

EXPECTED = """  # = machine   . = empty cell
  (top row = far Y end, left col = X switch)

  3 | . . . .
  2 | . . . .
  1 | . . . .
    +--------
     1 2 3 4 
     ^ origin corner is bottom-left [1,1]"""

small = MachineGrid(cols=4, rows=3)
check("ascii_map matches printGrid()", small.ascii_map() == EXPECTED)
if small.ascii_map() != EXPECTED:
    print("--- got ---\n" + small.ascii_map() + "\n--- want ---\n" + EXPECTED)

# The '#' marks the machine, and [1,1] is bottom-left — so it lands on the
# LAST line of cells, not the first.
marked = small.ascii_map(here=(1, 1)).splitlines()
check("'#' at [1,1] is bottom-left", marked[5] == "  1 | # . . .", repr(marked[5]))

# Column numbers are last-digit-only, as the firmware does to keep alignment.
wide = MachineGrid(cols=12, rows=2).ascii_map().splitlines()
check("column numbers are c % 10", wide[-2].strip() == "1 2 3 4 5 6 7 8 9 0 1 2",
      repr(wide[-2]))


# ------------------------------------------------------------------
# The image mapping
# ------------------------------------------------------------------

g = MachineGrid(cols=10, rows=20)  # the real one
check("divisions across/down", (g.nx, g.ny) == (10, 20), f"{g.nx}x{g.ny}")

# Default orientation is the rig's own picture: [1,1] bottom-left.
check("[1,1] is bottom-left", g.cell_at(0, 19) == (1, 1), str(g.cell_at(0, 19)))
check("[10,20] is top-right", g.cell_at(9, 0) == (10, 20), str(g.cell_at(9, 0)))
check("col 1 is the left column", g.cell_at(0, 5)[0] == 1)
check("row 1 is the bottom row", g.cell_at(5, 19)[1] == 1)

# Every corner and both axis assignments must round-trip, and must put [1,1]
# in the corner they are named after. This is the whole reason the setting
# exists: eight mountings, no sign-juggling anywhere else in the project.
for origin in ORIGIN_CORNERS:
    for swap in (False, True):
        m = MachineGrid(cols=10, rows=20, origin=origin, swap_axes=swap)

        trips = all(
            m.cell_at(*m.image_cell(c, r)) == (c, r)
            for c in range(1, 11)
            for r in range(1, 21)
        )
        check(f"round-trip {origin}{' swapped' if swap else ''}", trips)

        seen = {m.cell_at(ix, iy) for ix in range(m.nx) for iy in range(m.ny)}
        check(f"covers every cell {origin}{' swapped' if swap else ''}",
              len(seen) == 200)

        ix, iy = m.image_cell(1, 1)
        want = (0 if m.at_left else m.nx - 1, m.ny - 1 if m.at_bottom else 0)
        check(f"[1,1] lands at {origin}{' swapped' if swap else ''}",
              (ix, iy) == want, f"{(ix, iy)} want {want}")

# A quarter-turned camera swaps which way the image is divided.
turned = MachineGrid(cols=10, rows=20, swap_axes=True)
check("swapaxes flips the divisions", (turned.nx, turned.ny) == (20, 10),
      f"{turned.nx}x{turned.ny}")


# ------------------------------------------------------------------
# Config and bounds
# ------------------------------------------------------------------

from_cfg = MachineGrid.from_config()
check("from_config matches rig.json", from_cfg.matches(), from_cfg.describe())
check("bounds are 1-based, like cellInRange()",
      from_cfg.contains(1, 1) and not from_cfg.contains(0, 1)
      and from_cfg.contains(10, 20) and not from_cfg.contains(11, 20))

try:
    MachineGrid(cols=10, rows=20, origin="middle")
    check("bad origin is refused", False)
except ValueError:
    check("bad origin is refused", True)

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
sys.exit(1 if FAILED else 0)

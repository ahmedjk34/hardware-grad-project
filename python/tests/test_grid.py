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
from rig.config import UnknownGridMode, load
from rig.workspace import WorkspaceMap

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:38} {detail}")


# ------------------------------------------------------------------
# The map, transcribed from printGrid() with GRID_COLS=4, GRID_ROWS=3
# ------------------------------------------------------------------

EXPECTED = """  # = machine   . = buildable cell   F = feeder
  (every cell is a real block; [0,0] is the feeder)

  3 | . . . . .
  2 | . . . . .
  1 | . . . . .
  0 | F . . . .
    +----------
     0 1 2 3 4
     ^ [0,0] feeder; every other cell is buildable"""

small = MachineGrid(cols=5, rows=4)
check("ascii_map matches printGrid()", small.ascii_map() == EXPECTED)
if small.ascii_map() != EXPECTED:
    print("--- got ---\n" + small.ascii_map() + "\n--- want ---\n" + EXPECTED)

# The '#' marks the machine, and [0,0] is bottom-left — so it lands on the
# LAST line of cells, not the first.
marked = small.ascii_map(here=(1, 1)).splitlines()
check("'#' at [1,1] is bottom-left", marked[5] == "  1 | . # . . .", repr(marked[5]))
check("the feeder is marked on the bottom row", marked[6] == "  0 | F . . . .",
      repr(marked[6]))

# Column numbers are last-digit-only, as the firmware does to keep alignment.
wide = MachineGrid(cols=13, rows=3).ascii_map().splitlines()
check("column numbers are c % 10", wide[-2].strip() == "0 1 2 3 4 5 6 7 8 9 0 1 2",
      repr(wide[-2]))


# ------------------------------------------------------------------
# The image mapping
# ------------------------------------------------------------------

g = MachineGrid(cols=22, rows=5)  # count-only orientation stress case
check("divisions across/down", (g.nx, g.ny) == (22, 5), f"{g.nx}x{g.ny}")

# Default orientation is the rig's own picture: [1,1] bottom-left.
check("[0,0] is bottom-left", g.cell_at(0, 4) == (0, 0), str(g.cell_at(0, 4)))
check("[21,4] is top-right", g.cell_at(21, 0) == (21, 4), str(g.cell_at(21, 0)))
check("col 0 is the left column", g.cell_at(0, 2)[0] == 0)
check("row 0 is the bottom row", g.cell_at(10, 4)[1] == 0)

# Every corner and both axis assignments must round-trip, and must put [1,1]
# in the corner they are named after. This is the whole reason the setting
# exists: eight mountings, no sign-juggling anywhere else in the project.
for origin in ORIGIN_CORNERS:
    for swap in (False, True):
        m = MachineGrid(cols=22, rows=5, origin=origin, swap_axes=swap)

        trips = all(
            m.cell_at(*m.image_cell(c, r)) == (c, r)
            for c in range(0, 22)
            for r in range(0, 5)
        )
        check(f"round-trip {origin}{' swapped' if swap else ''}", trips)

        seen = {m.cell_at(ix, iy) for ix in range(m.nx) for iy in range(m.ny)}
        check(f"covers every cell {origin}{' swapped' if swap else ''}",
              len(seen) == 110)

        ix, iy = m.image_cell(0, 0)
        want = (0 if m.at_left else m.nx - 1, m.ny - 1 if m.at_bottom else 0)
        check(f"[0,0] lands at {origin}{' swapped' if swap else ''}",
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
check("bounds are 0-based, like cellInRange()",
      from_cfg.contains(0, 0) and not from_cfg.contains(-1, 0)
      and from_cfg.contains(6, 5) and not from_cfg.contains(7, 5))
check("row 0 and column 0 are ordinary build targets now",
      from_cfg.contains_build_target(0, 5)
      and from_cfg.contains_build_target(6, 0))
check("[0,0] is the feeder and is NOT a build target",
      not from_cfg.contains_build_target(0, 0)
      and from_cfg.is_feeder(0, 0))
check("build target still rejects negative/outside coordinates",
      not from_cfg.contains_build_target(-1, 1)
      and not from_cfg.contains_build_target(7, 0)
      and not from_cfg.contains_build_target(0, 6))
check("block/internal-gap footprint is 25.0x40.0 cm",
      math.isclose(from_cfg.packed_width_cm, 25.0)
      and math.isclose(from_cfg.packed_height_cm, 40.0))
check("the lattice is anchored, so the span reaches the far block edge",
      math.isclose(from_cfg.allocation_width_cm, 25.0)
      and math.isclose(from_cfg.allocation_height_cm, 40.0))
check("the lattice is anchored on the home corner, with both trims zero",
      math.isclose(from_cfg.x_allocation_start_cm, 0.0)
      and math.isclose(from_cfg.y_allocation_start_cm, 0.0))
check("cell 0's outer edge sits on the home corner",
      math.isclose(from_cfg.x_start_cm, 0.0)
      and math.isclose(from_cfg.y_start_cm, 0.0))
check("first physical cell centre",
      all(math.isclose(a, b) for a, b in
          zip(from_cfg.cell_center_cm(0, 0), (1.1, 3.0))))
check("last physical cell centre",
      all(math.isclose(a, b) for a, b in
          zip(from_cfg.cell_center_cm(6, 5), (23.9, 37.0))))
check("the feeder is the vertical [0,0] centre",
      all(math.isclose(a, b) for a, b in
          zip(from_cfg.feeder_center_cm(), (1.1, 3.0))))
check("all placement centres remain inside holder travel",
      from_cfg.x_first_center_cm >= 0 and from_cfg.y_first_center_cm >= 0
      and from_cfg.x_last_center_cm <= from_cfg.workspace_width_cm
      and from_cfg.y_last_center_cm <= from_cfg.workspace_height_cm)
check("the far block edges land on the grid span",
      math.isclose(from_cfg.x_end_cm, 25.0)
      and math.isclose(from_cfg.y_end_cm, 40.0))
check("vertical X overhangs 0.7 cm, inside its 1.1 cm budget",
      from_cfg.x_end_cm - from_cfg.workspace_width_cm > 0
      and (from_cfg.x_end_cm - from_cfg.workspace_width_cm
           <= from_cfg.max_edge_overhang_x_cm))

# ------------------------------------------------------------------
# The dual-orientation numeric contract
# ------------------------------------------------------------------
# Section 3 of plans/dual-orientation-grid.md tabulates every derived
# centimetre for both modes. That table IS the contract between the firmware,
# MachineGrid and the camera overlay, so it is transcribed here rather than
# recomputed: a test that redoes the arithmetic would agree with a bug.
#
#  All rows are at the shipped trim of 0.0, i.e. each allocation centred in the
#  24.3 x 40.0 cm travel. The lattice is ANCHORED on the home corner and
#  coordinate 0 is a REAL block, so counts include it and there is no centring.
#
#  mode        axis  block  gap        pitch  count  span     centres
#  vertical    X     2.2    1.6        3.8      7    25.0     1.10 -> 23.90
#  vertical    Y     6.0    0.8        6.8      6    40.0     3.00 -> 37.00
#  horizontal  X     6.0    1.6        7.6      3    21.2     3.00 -> 18.20
#  horizontal  Y     2.2    0.8/1.6    alt     11    36.2     4.90 -> 38.90
#
#  Horizontal Y is the vertical Y lattice read at double density: its rows are
#  the lower and upper 2.2 cm halves of each vertical row, so its gaps
#  alternate 0.8 (between vertical blocks) and 1.6 (inside one). Its span runs
#  3.8 -> 40.0, ending on the vertical grid's top edge.

SECTION_3 = {
    "vertical": {
        "counts": (7, 6),
        "block": (2.2, 6.0),
        "gap": (1.6, 0.8),
        "pitch": (3.8, 6.8),
        "footprint": (25.00, 40.00),
        "first_centre": (1.10, 3.00),
        "last_centre": (23.90, 37.00),
        "first_edge": (0.00, 0.00),
        "last_edge": (25.00, 40.00),
        "cells": 42,
    },
    "horizontal": {
        "counts": (3, 11),
        "block": (6.0, 2.2),
        "gap": (1.6, 0.8),
        "pitch": (7.6, 3.0),
        "footprint": (21.20, 36.20),
        "first_centre": (3.00, 4.90),
        "last_centre": (18.20, 38.90),
        "first_edge": (0.00, 3.80),
        "last_edge": (21.20, 40.00),
        "cells": 33,
    },
}


def close_pair(actual, expected):
    return all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(actual, expected))


for mode, want in SECTION_3.items():
    m = MachineGrid.from_config(config, mode=mode)

    check(f"{mode}: mode is recorded on the grid", m.mode == mode, m.describe())
    check(f"{mode}: counts", (m.cols, m.rows) == want["counts"],
          f"{m.cols}x{m.rows}")
    check(f"{mode}: block extents stated per axis",
          close_pair((m.block_x_cm, m.block_y_cm), want["block"]),
          f"{m.block_x_cm} x {m.block_y_cm}")
    check(f"{mode}: gaps", close_pair((m.gap_x_cm, m.gap_y_cm), want["gap"]))
    check(f"{mode}: pitch", close_pair((m.pitch_x_cm, m.pitch_y_cm), want["pitch"]),
          f"{m.pitch_x_cm} x {m.pitch_y_cm}")
    check(f"{mode}: footprint",
          close_pair((m.packed_width_cm, m.packed_height_cm), want["footprint"]),
          f"{m.packed_width_cm} x {m.packed_height_cm}")
    check(f"{mode}: first centre",
          close_pair(m.cell_center_cm(0, 0), want["first_centre"]),
          str(m.cell_center_cm(0, 0)))
    check(f"{mode}: last centre",
          close_pair(m.cell_center_cm(m.max_col, m.max_row), want["last_centre"]),
          str(m.cell_center_cm(m.max_col, m.max_row)))
    check(f"{mode}: first block edge",
          close_pair((m.x_start_cm, m.y_start_cm), want["first_edge"]),
          f"{m.x_start_cm} x {m.y_start_cm}")
    check(f"{mode}: last block edge",
          close_pair((m.x_end_cm, m.y_end_cm), want["last_edge"]),
          f"{m.x_end_cm} x {m.y_end_cm}")
    check(f"{mode}: every placement centre is reachable",
          m.x_first_center_cm >= 0 and m.y_first_center_cm >= 0
          and m.x_last_center_cm <= m.workspace_width_cm
          and m.y_last_center_cm <= m.workspace_height_cm)
    check(f"{mode}: build cell count", m.cols * m.rows == want["cells"])
    check(f"{mode}: matches its own config entry", m.matches(config), m.describe())

# The shipped counts are the grids currently printed on paper, not geometric
# maxima. Against the 24.3 x 40.0 cm travel and each mode's overhang
# budget, one more cell on the tightest axis is still refused.
def fits(mode, cols, rows):
    m = MachineGrid.from_config(config, mode=mode)
    try:
        MachineGrid(cols=cols, rows=rows, mode=mode,
                    block_x_cm=m.block_x_cm, block_y_cm=m.block_y_cm,
                    gap_x_cm=m.gap_x_cm, gap_y_cm=m.gap_y_cm,
                    workspace_width_cm=m.workspace_width_cm,
                    workspace_height_cm=m.workspace_height_cm,
                    trim_x_cm=m.trim_x_cm, trim_y_cm=m.trim_y_cm,
                    max_edge_overhang_x_cm=m.max_edge_overhang_x_cm,
                    max_edge_overhang_y_cm=m.max_edge_overhang_y_cm,
                    # carry the derived lattice, or horizontal falls back to a
                    # uniform pitch and accepts rows that do not really fit
                    gap_y_alt_cm=m.gap_y_alt_cm,
                    y_lattice_start_cm=m.y_lattice_start_cm)
        return True
    except ValueError:
        return False

check("a 4th horizontal column cannot fit", not fits("horizontal", 4, 11))
check("the 3rd horizontal column still fits", fits("horizontal", 3, 11))
check("a 12th horizontal row cannot fit", not fits("horizontal", 3, 12))
check("an 8th vertical column cannot fit", not fits("vertical", 8, 6))
check("the 7th vertical column still fits", fits("vertical", 7, 6))
check("a 7th vertical row cannot fit", not fits("vertical", 7, 7))

# Addressable extents including the zero lanes: 7 x 6 and 3 x 11.
vertical_grid = MachineGrid.from_config(config, mode="vertical")
horizontal_grid = MachineGrid.from_config(config, mode="horizontal")
check("vertical addresses a 7 x 6 coordinate grid",
      (vertical_grid.cols, vertical_grid.rows) == (7, 6))
check("horizontal addresses a 3 x 11 coordinate grid",
      (horizontal_grid.cols, horizontal_grid.rows) == (3, 11))
check("horizontal ascii map is 3 wide and 11 tall",
      len(horizontal_grid.ascii_map().splitlines()[3].split()) == 3 + 2
      and horizontal_grid.ascii_map().splitlines()[3].startswith(" 10 |"),
      repr(horizontal_grid.ascii_map().splitlines()[3]))

# D14 / R2: a centre-only validator accepts a grid whose far block hangs off
# the machine, because the centre it hangs from is legal. The per-mode overhang
# budget is what closes that. Horizontal ships a zero budget, so any positive
# X trim that keeps its last centre legal while pushing the block edge past the
# wall must still be refused.


def horizontal_at(trim_x, trim_y, budget=0.0):
    return MachineGrid(
        cols=3, rows=11, mode="horizontal",
        block_x_cm=6.0, block_y_cm=2.2, gap_x_cm=1.6, gap_y_cm=0.8,
        workspace_width_cm=24.3, workspace_height_cm=40.0,
        trim_x_cm=trim_x, trim_y_cm=trim_y,
        max_edge_overhang_x_cm=budget, max_edge_overhang_y_cm=budget,
        # The derived horizontal Y lattice, as from_config() computes it from
        # the vertical entry: gaps alternate 0.8 / 1.6 and row 0 starts 3.8 out.
        gap_y_alt_cm=6.0 - 2 * 2.2, y_lattice_start_cm=6.0 - 2.2,
    )


# Unbudgeted, the bad grid is accepted and its own numbers show why that is wrong.
unchecked = MachineGrid(
    cols=3, rows=11, mode="horizontal",
    block_x_cm=6.0, block_y_cm=2.2, gap_x_cm=1.6, gap_y_cm=0.8,
    workspace_width_cm=24.3, workspace_height_cm=40.0,
    trim_x_cm=3.55, trim_y_cm=0.0,
    max_edge_overhang_x_cm=3.0, max_edge_overhang_y_cm=3.0,
    gap_y_alt_cm=6.0 - 2 * 2.2, y_lattice_start_cm=6.0 - 2.2,
)
check("a +3.55 cm X trim keeps horizontal's last centre legal",
      unchecked.x_last_center_cm <= unchecked.workspace_width_cm,
      f"last centre {unchecked.x_last_center_cm:g} cm")
check("...but pushes the far block edge 0.45 cm past the X limit (R2)",
      math.isclose(unchecked.x_end_cm - unchecked.workspace_width_cm, 0.45,
                   abs_tol=1e-9),
      f"far edge {unchecked.x_end_cm:g} cm vs 24.3 cm travel")

try:
    horizontal_at(3.55, 0.0)
    check("horizontal at a +3.55 cm X trim is refused by the zero budget (R2)",
          False)
except ValueError as exc:
    check("horizontal at a +3.55 cm X trim is refused by the zero budget (R2)",
          "X block edges" in str(exc), str(exc))

check("horizontal at the shipped trims is accepted",
      horizontal_at(0.0, 0.0).mode == "horizontal")
# The old +1.6 cm Y registration trim is now DOUBLE-COUNTING and must be
# refused: horizontal row 0 already starts 3.8 cm out, structurally, because it
# is the upper half of vertical row 0. Adding the trim on top overruns Y.
try:
    horizontal_at(0.0, 1.6)
    check("the old +1.6 cm Y registration trim is now refused", False)
except ValueError as exc:
    check("the old +1.6 cm Y registration trim is now refused", True, str(exc))
check("horizontal row 0 starts 3.8 cm out with no trim at all",
      math.isclose(horizontal_at(0.0, 0.0).y_start_cm, 3.8))
check("horizontal Y gaps alternate 0.8 / 1.6",
      [round(horizontal_at(0.0, 0.0).gap_before_row_cm(r), 3)
       for r in range(1, 11)] == [0.8, 1.6] * 5)

# Vertical keeps its half-block budget (block_x/2 = 1.1, block_y/2 = 3.0).
check("vertical's budget is half a block on each axis",
      (vertical_grid.max_edge_overhang_x_cm,
       vertical_grid.max_edge_overhang_y_cm) == (1.1, 3.0))
check("horizontal's budget is zero on both axes",
      (horizontal_grid.max_edge_overhang_x_cm,
       horizontal_grid.max_edge_overhang_y_cm) == (0.0, 0.0))
try:
    MachineGrid(
        cols=7, rows=6, mode="vertical",
        block_x_cm=2.2, block_y_cm=6.0, gap_x_cm=1.6, gap_y_cm=0.8,
        workspace_width_cm=24.3, workspace_height_cm=40.0,
        trim_x_cm=3.0, trim_y_cm=6.0,
        max_edge_overhang_x_cm=0.0, max_edge_overhang_y_cm=0.0,
    )
    check("a large trim with a zero budget refuses even vertical", False)
except ValueError as exc:
    check("a large trim with a zero budget refuses even vertical",
          "block edges" in str(exc) or "do not fit" in str(exc), str(exc))

# D2 / R6: the two modes are different grids, and a grid must not claim to
# match the config entry for the other one.
check("a horizontal grid does not match the vertical entry",
      not MachineGrid.from_config(config, mode="horizontal").matches(
          {"grid": {"active_mode": "vertical",
                    "modes": {"horizontal": config["grid"]["modes"]["vertical"]}},
           "workspace": config["workspace"]}))

# `mode` is the BLOCK's orientation; `swap_axes` is the CAMERA's. They are
# independent, and neither is allowed to stand in for the other.
turned_horizontal = MachineGrid.from_config(config, mode="horizontal",
                                            swap_axes=True)
check("mode and swap_axes stay independent",
      turned_horizontal.mode == "horizontal" and turned_horizontal.swap_axes
      and (turned_horizontal.nx, turned_horizontal.ny) == (11, 3),
      f"{turned_horizontal.nx}x{turned_horizontal.ny}")
check("a horizontal grid is not axis-swapped by default",
      not horizontal_grid.swap_axes and (horizontal_grid.nx, horizontal_grid.ny) == (3, 11))

# An unknown mode is a readable error rather than a KeyError, at this layer too.
try:
    MachineGrid.from_config(config, mode="diagonal")
    check("MachineGrid refuses an unknown mode", False)
except UnknownGridMode as exc:
    check("MachineGrid refuses an unknown mode", "diagonal" in str(exc), str(exc))


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


def firmware_mode_numbers(name):
    """Read one per-mode table, e.g. `float GRID_TRIM_X_CM[...] = {1.1, 0.0};`.

    Returned keyed by mode NAME, not by index, so a test can never silently
    compare vertical's JSON against horizontal's firmware slot.
    """
    match = re.search(
        rf"^\s*(?:float|long)\s+{re.escape(name)}\s*\[[^\]]*\]\s*=\s*\{{([^}}]*)\}}\s*;",
        sketch,
        re.MULTILINE,
    )
    if match is None:
        return None
    values = [float(part.strip()) for part in match.group(1).split(",")]
    if len(values) != len(FIRMWARE_MODE_ORDER):
        return None
    return dict(zip(FIRMWARE_MODE_ORDER, values))


# The table index each mode occupies in the sketch. Read out of the sketch
# rather than assumed, because everything below depends on it and swapping the
# two initialisers would otherwise pass every check while inverting the rig.
FIRMWARE_MODE_ORDER = [None, None]
for mode_name, constant in (("vertical", "GRID_MODE_VERTICAL"),
                            ("horizontal", "GRID_MODE_HORIZONTAL")):
    found = re.search(rf"const uint8_t {constant} = (\d+);", sketch)
    if found is not None and int(found.group(1)) < 2:
        FIRMWARE_MODE_ORDER[int(found.group(1))] = mode_name
check("firmware mode order is vertical, horizontal",
      FIRMWARE_MODE_ORDER == ["vertical", "horizontal"], str(FIRMWARE_MODE_ORDER))

# D2: the board has no EEPROM and a USB open resets it, so the compiled default
# IS what the machine is at the start of every session.
check("firmware boots vertical (D2)",
      re.search(r"uint8_t gridMode = GRID_MODE_VERTICAL;", sketch) is not None)
check("firmware mode count is 2",
      re.search(r"const uint8_t GRID_MODE_COUNT = 2;", sketch) is not None)

# Every geometry value is now a per-mode table, and BOTH entries have to match
# their config/rig.json partner. Checking only the active mode would let the
# horizontal half of the firmware drift silently until someone sent RR.
per_mode_pairs = {
    "GRID_COLS": "cols",
    "GRID_ROWS": "rows",
    "GRID_BLOCK_X_CM": "block_x_cm",
    "GRID_BLOCK_Y_CM": "block_y_cm",
    "GRID_GAP_X_CM": "gap_x_cm",
    "GRID_GAP_Y_CM": "gap_y_cm",
    "GRID_TRIM_X_CM": "trim_x_cm",
    "GRID_TRIM_Y_CM": "trim_y_cm",
    "GRID_ERROR_OFFSET_X_CM": "error_offset_x_cm",
    "GRID_ERROR_OFFSET_Y_CM": "error_offset_y_cm",
    "GRID_MAX_EDGE_OVERHANG_X_CM": "max_edge_overhang_x_cm",
    "GRID_MAX_EDGE_OVERHANG_Y_CM": "max_edge_overhang_y_cm",
}
for constant, json_key in per_mode_pairs.items():
    actual = firmware_mode_numbers(constant)
    if actual is None:
        check(f"firmware table {constant}", False, "no readable per-mode table")
        continue
    for mode_name in ("vertical", "horizontal"):
        expected = float(config["grid"]["modes"][mode_name][json_key])
        # GRID_COLS/GRID_ROWS are the only pair that are not a straight copy:
        # the firmware stores the HIGHEST INDEX where the JSON stores a COUNT.
        # rig/link.py is the one place that converts, when it sends S.
        if constant in ("GRID_COLS", "GRID_ROWS"):
            expected -= 1
        check(f"firmware/config pair {constant}[{mode_name}]",
              actual[mode_name] == expected,
              f"firmware {actual[mode_name]}, JSON {expected}")

paired_values = {
    "X_TRAVEL_CM": from_cfg.workspace_width_cm,
    "Y_TRAVEL_CM": from_cfg.workspace_height_cm,
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
y_row_targets = [round(from_cfg.cell_center_cm(0, row)[1] * y_steps_per_cm)
                 for row in range(from_cfg.rows)]
# Rows are one Y pitch apart; the firmware rounds each absolute centre once, so
# consecutive gaps differ by at most a step. Assert the spacing rather than a
# fixed list so a future trim measurement does not re-fail this.
expected_gap = round(from_cfg.pitch_y_cm * y_steps_per_cm)
row_gaps = [b - a for a, b in zip(y_row_targets, y_row_targets[1:])]
check("Y row targets are one pitch apart",
      all(abs(gap - expected_gap) <= 1 for gap in row_gaps),
      f"targets {y_row_targets}, gaps {row_gaps}, pitch {expected_gap}")
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
for point, expected in zip(corners, ((0, 0), (9, 0), (9, 19), (0, 19))):
    check(f"workspace corner maps to {expected}",
          workspace.cell_at(point, (640, 480)) == expected)

centre = workspace.pixel_at(0.45, 0.225, (640, 480))
check("workspace projective round-trip",
      workspace.cell_at(centre, (640, 480)) == (4, 4), str(centre))
check("workspace rejects outside click",
      workspace.cell_at((0, 0), (640, 480)) is None)

# Physical mapping uses the 24.3x40 cm holder-motion rectangle. The lattice is
# anchored on the home corner: cell [0,0]'s outer edge sits exactly on it.
physical_workspace = WorkspaceMap.from_grid(from_cfg, corners, (640, 480))
check("physical workspace matches grid JSON", physical_workspace.matches_grid(from_cfg))
w_cm, h_cm = from_cfg.workspace_width_cm, from_cfg.workspace_height_cm
fx, fy = from_cfg.cell_center_cm(0, 0)
lx, ly = from_cfg.cell_center_cm(from_cfg.max_col, from_cfg.max_row)
first_centre = physical_workspace.pixel_at(fx / w_cm, fy / h_cm, (640, 480))
last_centre = physical_workspace.pixel_at(lx / w_cm, ly / h_cm, (640, 480))
check("physical camera map finds first cell",
      physical_workspace.cell_at(first_centre, (640, 480)) == (0, 0))
check("physical camera map finds last cell",
      physical_workspace.cell_at(last_centre, (640, 480))
      == (from_cfg.max_col, from_cfg.max_row))
# A point in the X gap between column 0 and column 1, at row 0's Y.
gap_x_cm = 0.5 * (from_cfg.cell_bounds_cm(0, 0)[2] + from_cfg.cell_bounds_cm(1, 0)[0])
gap_point = physical_workspace.pixel_at(gap_x_cm / w_cm, fy / h_cm, (640, 480))
check("physical camera map preserves internal gap",
      physical_workspace.cell_at(gap_point, (640, 480)) is None)

# Normalized storage makes a simple resolution change harmless.
double_corners = [(x * 2, y * 2) for x, y in corners]
for point, expected in zip(double_corners, ((0, 0), (9, 0), (9, 19), (0, 19))):
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

#!/usr/bin/env python3
"""Generate the Studio's coordinate golden cases from the authoritative lattice.

The browser's `web/src/studio/coords.ts` is a port of `rig/grid.py`, and this is
the bridge that holds it to it: every centre, footprint and AABB below comes out
of `MachineGrid`, and `coords.test.ts` reads them back. Same pattern as
`dump_workspace_fixtures.py` does for the homography. When the two disagree,
this file is right.

Each case carries the WHOLE rig config it was built from, so the test has
nothing to reconstruct - it hands the config to the TypeScript and compares.

Three groups of case:

  shipped   config/rig.json as it ships, both modes, no shift.
  shifted   config/rig.json plus a live grid shift, including shifts that clip
            the reachable grid and one the geometry refuses outright.
  wide      a synthetic 60x60 cm envelope with a generous overhang budget, which
            is the only way to exercise non-zero trims and error offsets: the
            shipped vertical grid sits EXACTLY on its travel cap and its edge
            budget is exactly half a block, so any trim at all is a geometry
            error there rather than a different lattice.

Block height has no partner in config/rig.json - it is the firmware's
BLOCK_HEIGHT_CM - so it is stated once here and once in coords.ts.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rig.config import load
from rig.grid import MachineGrid

OUT = Path(__file__).resolve().parents[2] / "web/src/studio/coords.fixtures.json"

BLOCK_HEIGHT_CM = 1.5  # arduino/build_test_v1: BLOCK_HEIGHT_CM
LEVELS = (0, 3)


def tweak(cfg: dict, mode: str, **values) -> dict:
    """A copy of `cfg` with one mode's geometry keys overridden."""
    out = copy.deepcopy(cfg)
    out["grid"]["active_mode"] = mode
    out["grid"]["modes"][mode].update(values)
    return out


def widen(cfg: dict, mode: str, **values) -> dict:
    """`tweak` on a 60x60 cm envelope with a 10 cm edge budget."""
    out = tweak(cfg, mode, max_edge_overhang_x_cm=10.0,
                max_edge_overhang_y_cm=10.0, **values)
    out["workspace"] = {"width_cm": 60.0, "height_cm": 60.0}
    return out


def case(name: str, mode: str, cfg: dict) -> dict:
    """One fixture row: the config, the clipping verdict and every cell in it."""
    entry = {"name": name, "mode": mode, "config": cfg,
             "requested": {"cols": int(cfg["grid"]["modes"][mode]["cols"]),
                           "rows": int(cfg["grid"]["modes"][mode]["rows"])}}
    try:
        grid = MachineGrid.from_config(cfg, mode=mode)
    except ValueError as exc:
        # A shift no cell survives. The firmware's gridColsNow() would report a
        # highest index of -1 here and applyGridShift() refuses it up front.
        # `reachable` is null rather than 0x0: the refusal is per axis - the
        # firmware's gridColsNow() would report -1 for the axis the shift ruins
        # and the untouched count for the other - and MachineGrid raises before
        # it can say which. The test asserts only that an axis has gone.
        entry.update(refused=True, error=str(exc), reachable=None,
                     bounds=None, cells=[])
        return entry
    entry.update(
        refused=False,
        reachable={"cols": grid.cols, "rows": grid.rows},
        bounds={"x_start_mm": grid.x_start_cm * 10, "y_start_mm": grid.y_start_cm * 10,
                "x_end_mm": grid.x_end_cm * 10, "y_end_mm": grid.y_end_cm * 10,
                "x_first_center_mm": grid.x_first_center_cm * 10,
                "y_first_center_mm": grid.y_first_center_cm * 10,
                "x_last_center_mm": grid.x_last_center_cm * 10,
                "y_last_center_mm": grid.y_last_center_cm * 10},
        block_mm=[grid.block_x_cm * 10, grid.block_y_cm * 10, BLOCK_HEIGHT_CM * 10],
        cells=[cell(grid, col, row, level)
               for level in LEVELS
               for row in range(grid.rows)
               for col in range(grid.cols)],
    )
    return entry


def cell(grid: MachineGrid, col: int, row: int, level: int) -> dict:
    """Centre, footprint and AABB of one cell, in machine-space millimetres."""
    cx, cy = grid.cell_center_cm(col, row)
    x0, y0, x1, y1 = grid.cell_bounds_cm(col, row)
    cz = level * BLOCK_HEIGHT_CM * 10 + BLOCK_HEIGHT_CM * 10 / 2
    half_z = BLOCK_HEIGHT_CM * 10 / 2
    return {"col": col, "row": row, "level": level,
            "feeder": MachineGrid.is_feeder(col, row),
            "center_mm": [cx * 10, cy * 10, cz],
            "footprint_mm": [x0 * 10, y0 * 10, x1 * 10, y1 * 10],
            "aabb_mm": {"min": [x0 * 10, y0 * 10, cz - half_z],
                        "max": [x1 * 10, y1 * 10, cz + half_z]}}


def main() -> None:
    cfg = load()
    cases = [
        case("shipped vertical", "vertical", tweak(cfg, "vertical")),
        case("shipped horizontal", "horizontal", tweak(cfg, "horizontal")),
        # Shifts on the shipped envelope: the far column/row leaves the machine
        # and the reachable grid clips while the request is kept.
        case("vertical shift x 1.2 clips a column", "vertical",
             tweak(cfg, "vertical", shift_x_cm=1.2)),
        case("vertical shift x 3.8 clips a column", "vertical",
             tweak(cfg, "vertical", shift_x_cm=3.8)),
        case("vertical shift y 7.6 clips a row", "vertical",
             tweak(cfg, "vertical", shift_y_cm=7.6)),
        case("horizontal shift x 1.5 fits whole", "horizontal",
             tweak(cfg, "horizontal", shift_x_cm=1.5)),
        case("horizontal shift x 8.0 clips a column", "horizontal",
             tweak(cfg, "horizontal", shift_x_cm=8.0)),
        case("horizontal shift y 1.0 fits whole", "horizontal",
             tweak(cfg, "horizontal", shift_y_cm=1.0)),
        case("horizontal shift y 3.8 clips a row", "horizontal",
             tweak(cfg, "horizontal", shift_y_cm=3.8)),
        case("horizontal shift both clips both", "horizontal",
             tweak(cfg, "horizontal", shift_x_cm=8.0, shift_y_cm=3.8)),
        # A shift the geometry refuses: nothing moves cell 0 back onto the
        # machine, so clipping cannot rescue it.
        case("vertical shift x -1.0 refused", "vertical",
             tweak(cfg, "vertical", shift_x_cm=-1.0)),
        case("horizontal shift y -2.0 refused", "horizontal",
             tweak(cfg, "horizontal", shift_y_cm=-2.0)),
        # Trims and error offsets, which need room to exist at all.
        # Only the far end has slack: the lattice starts on the home corner, so
        # a negative first centre is a geometry error and not a shifted grid.
        case("wide vertical trims", "vertical",
             widen(cfg, "vertical", trim_x_cm=0.7, trim_y_cm=0.3)),
        case("wide vertical trims and error offsets", "vertical",
             widen(cfg, "vertical", trim_x_cm=0.7, trim_y_cm=0.3,
                   error_offset_x_cm=0.15, error_offset_y_cm=0.05)),
        case("wide vertical everything", "vertical",
             widen(cfg, "vertical", trim_x_cm=0.7, trim_y_cm=0.3,
                   error_offset_x_cm=0.15, error_offset_y_cm=0.05,
                   shift_x_cm=1.1, shift_y_cm=0.45)),
        case("wide horizontal everything", "horizontal",
             widen(cfg, "horizontal", trim_x_cm=1.6, trim_y_cm=1.6,
                   error_offset_x_cm=-0.25, error_offset_y_cm=0.3,
                   shift_x_cm=0.9, shift_y_cm=0.75)),
        case("wide horizontal negative error offset", "horizontal",
             widen(cfg, "horizontal", trim_x_cm=0.5, error_offset_x_cm=-0.05,
                   error_offset_y_cm=-0.15, shift_x_cm=2.35)),
    ]
    OUT.write_text(json.dumps(
        {"block_height_cm": BLOCK_HEIGHT_CM, "levels": list(LEVELS),
         "cases": cases}, indent=2) + "\n")
    print(f"{len(cases)} cases, "
          f"{sum(len(c['cells']) for c in cases)} cells -> {OUT}")


if __name__ == "__main__":
    main()

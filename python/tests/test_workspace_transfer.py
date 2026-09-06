#!/usr/bin/env python3
"""A calibrated grid mode's workspace map derives the other mode's - no camera.

Run from python/:  ../.venv/bin/python tests/test_workspace_transfer.py

The two grid modes share a camera and a holder-travel envelope, so the four
corners of config/workspace_map.json are the same image points in both. This
asserts transfer_workspace_map():

  * copies those four corners faithfully into the target mode's entry,
  * pairs them with the target mode's config/rig.json lattice (horizontal's
    +1.9 cm registration and 3x10 counts, not vertical's),
  * leaves the source mode's entry byte-identical,
  * produces a map whose horizontal cells round-trip pixel <-> [col,row],
  * and refuses the cases that cannot be derived (same mode, missing source,
    a source with no projection identity).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.calibration_transfer import (                              # noqa: E402
    CalibrationTransferError,
    transfer_workspace_map,
)
from rig.config import load as load_rig_config                      # noqa: E402
from rig.grid import MachineGrid                                    # noqa: E402
from rig.workspace import WorkspaceMap                              # noqa: E402

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"ok    {name}")
    else:
        print(f"FAIL  {name}{': ' + detail if detail else ''}")
        failures.append(name)


# A plausible projection identity and a convex four-corner quad in
# CORNER_NAMES order (home, far-X/home-Y, far-X/far-Y, home-X/far-Y), image
# y-down. Same shape test_calibration_parity.py uses.
PROJECTION = {
    "view": "corrected",
    "lens": {"model": "rectilinear", "fov_deg": 100.0},
    "orientation": {"flip": "none", "rotate": 0},
    "roi": None,
}
SIZE = (320, 520)
CORNERS_PX = [(12, 500), (300, 500), (300, 40), (12, 40)]


def main():
    cfg = load_rig_config()
    vertical = MachineGrid.from_config(cfg, mode="vertical")
    horizontal = MachineGrid.from_config(cfg, mode="horizontal")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "workspace_map.json"
        WorkspaceMap.from_grid(vertical, CORNERS_PX, SIZE, PROJECTION).save(path)
        before = json.loads(path.read_text())

        derived, report = transfer_workspace_map(
            "vertical", "horizontal", path=path, cfg=cfg)
        after = json.loads(path.read_text())

        check("both mode entries are present after the transfer",
              set(after["modes"]) == {"vertical", "horizontal"},
              str(sorted(after["modes"])))
        check("the vertical (source) entry is untouched, field for field",
              after["modes"]["vertical"] == before["modes"]["vertical"])

        v_corners = after["modes"]["vertical"]["corners_normalized"]
        h_corners = after["modes"]["horizontal"]["corners_normalized"]
        check("horizontal inherits vertical's four corners exactly",
              v_corners == h_corners, f"{v_corners} != {h_corners}")
        check("the report echoes those same corners",
              report.corners_normalized == [list(p) for p in derived.corners]
              == h_corners)
        check("horizontal inherits vertical's projection identity",
              after["modes"]["horizontal"]["projection"] == PROJECTION)

        pg = after["modes"]["horizontal"]["physical_grid"]
        grid_block = after["modes"]["horizontal"]["grid"]
        check("horizontal carries its OWN +1.9 cm registration, not vertical's 0.0",
              pg["trim_x_cm"] == pg["trim_y_cm"] == 1.9
              == horizontal.trim_x_cm == horizontal.trim_y_cm,
              json.dumps(pg))
        check("horizontal carries its own 3x10 counts",
              (grid_block["cols"], grid_block["rows"])
              == (horizontal.cols, horizontal.rows) == (3, 10),
              str(grid_block))
        check("horizontal carries its own block footprint (6.0 x 2.2)",
              (pg["block_x_cm"], pg["block_y_cm"]) == (6.0, 2.2))
        check("horizontal blocked-cell list is config's (empty), not vertical's",
              pg["blocked_cells"]
              == [list(p) for p in sorted(horizontal.blocked)] == [])

        # A horizontal cell centre must round-trip through the derived map.
        loaded = WorkspaceMap.load(path, mode="horizontal")
        for col, row in ((0, 0), (2, 5), (2, 9)):
            cx, cy = horizontal.cell_center_cm(col, row)
            px = loaded.pixel_at(cx / horizontal.workspace_width_cm,
                                 cy / horizontal.workspace_height_cm, SIZE)
            check(f"derived map round-trips horizontal cell [{col},{row}]",
                  loaded.cell_at(px, SIZE) == (col, row),
                  str(loaded.cell_at(px, SIZE)))

        # A click in a deliberate gap is still None (geometry survived).
        gx = (horizontal.slot_bottom_x_cm(0) + horizontal.block_x_cm
              + horizontal.gap_x_cm / 2)
        cy0 = horizontal.cell_center_cm(0, 0)[1]
        gap_px = loaded.pixel_at(gx / horizontal.workspace_width_cm,
                                 cy0 / horizontal.workspace_height_cm, SIZE)
        check("a click in a horizontal column gap resolves to no cell",
              loaded.cell_at(gap_px, SIZE) is None,
              str(loaded.cell_at(gap_px, SIZE)))

        # --- guards ---------------------------------------------------------
        try:
            transfer_workspace_map("vertical", "vertical", path=path, cfg=cfg)
            check("same-mode transfer is refused", False)
        except CalibrationTransferError:
            check("same-mode transfer is refused", True)

        try:
            transfer_workspace_map(
                "vertical", "horizontal", path=Path(tmp) / "absent.json", cfg=cfg)
            check("a missing source map is refused", False)
        except CalibrationTransferError:
            check("a missing source map is refused", True)

        noproj = Path(tmp) / "noproj.json"
        WorkspaceMap.from_grid(vertical, CORNERS_PX, SIZE, None).save(noproj)
        try:
            transfer_workspace_map(
                "vertical", "horizontal", path=noproj, cfg=cfg)
            check("a source map without a projection is refused", False)
        except CalibrationTransferError:
            check("a source map without a projection is refused", True)

        # --- dry run writes nothing ---------------------------------------
        dry_path = Path(tmp) / "dry.json"
        WorkspaceMap.from_grid(vertical, CORNERS_PX, SIZE, PROJECTION).save(dry_path)
        seed = dry_path.read_text()
        _, dry_report = transfer_workspace_map(
            "vertical", "horizontal", path=dry_path, cfg=cfg, save=False)
        check("save=False leaves the file untouched",
              dry_path.read_text() == seed)
        check("save=False still reports the derived geometry",
              dry_report.target_cols == 3 and dry_report.target_rows == 10
              and dry_report.saved is False)

    print()
    if failures:
        print(f"{len(failures)} failing check(s): {', '.join(failures)}")
        raise SystemExit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()

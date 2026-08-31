#!/usr/bin/env python3
"""Exercise the gridded feed geometry without opening a camera or window."""

from pathlib import Path
import json
import sys
import tempfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.gridded_camera_feed import (  # noqa: E402
    approximate_workspace,
    calibration_line_color,
    draw_calibration,
    draw_machine_grid,
    load_workspace,
)
from rig.grid import MachineGrid  # noqa: E402
from rig.workspace import WorkspaceMap  # noqa: E402


PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:42} {detail}")


grid = MachineGrid.from_config()
projection = {"version": 1, "view": "corrected", "test": True}
image_size = (1296, 972)
workspace = approximate_workspace(grid, image_size, projection)

first_pixel = tuple(np.mean(workspace.cell_polygon(1, 1, image_size), axis=0))
frame = np.zeros((image_size[1], image_size[0], 3), dtype=np.uint8)
hovered = draw_machine_grid(frame, workspace, first_pixel, calibrated=False)
check("overlay maps first physical centre", hovered == (1, 1), str(hovered))
check("overlay actually draws pixels", bool(np.any(frame)))
detail_frame = np.zeros_like(frame)
draw_machine_grid(detail_frame, workspace, first_pixel,
                  calibrated=False, detail=True)
check("geometry grid omits detail-mode cell labels",
      not np.array_equal(frame, detail_frame))

calibration = np.zeros((180, 280, 3), dtype=np.uint8)
draw_calibration(calibration, [(30, 150), (250, 150)], (250, 30))
check("calibration joins accepted clicks with a straight line",
      bool(np.any(calibration[150, 80:200])), "edge 1 -> 2")
check("horizontal calibration edge has its own colour",
      calibration_line_color((30, 150), (250, 150)) == (255, 255, 0))
check("vertical calibration edge has its own colour",
      calibration_line_color((250, 150), (250, 30)) == (255, 0, 255))
check("diagonal calibration edge keeps its own colour",
      calibration_line_color((30, 150), (250, 30)) == (255, 180, 30))
check("calibration previews the next straight edge",
      bool(np.any(calibration[70:130, 250])), "cursor preview")
calibration_detail = np.zeros_like(calibration)
draw_calibration(calibration_detail, [(30, 150), (250, 150)], (250, 30),
                 detail=True)
check("geometry calibration omits full corner-name prose",
      not np.array_equal(calibration, calibration_detail))

review = np.zeros((180, 280, 3), dtype=np.uint8)
draw_calibration(review, [(30, 150), (250, 150), (250, 130), (30, 130)])
check("four-corner calibration closes the review outline",
      bool(np.any(review[135:145, 30])), "edge 4 -> 1")

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "workspace_map.json"
    workspace.save(path)
    loaded, reason = load_workspace(path, grid, projection)
    check("matching saved calibration reloads", loaded is not None and reason is None)

    legacy_path = Path(directory) / "workspace_map_v1.json"
    legacy_data = json.loads(path.read_text())
    legacy_data["version"] = 1
    legacy_path.write_text(json.dumps(legacy_data))
    loaded, reason = load_workspace(legacy_path, grid, projection)
    check("pre-gap workspace calibration is invalidated",
          loaded is None and "obsolete" in reason, str(reason))

    loaded, reason = load_workspace(path, grid, {"version": 2})
    check("changed camera projection invalidates map",
          loaded is None and "camera" in reason, str(reason))

    shifted = MachineGrid(
        cols=grid.cols,
        rows=grid.rows,
        block_x_cm=2.1,
        block_y_cm=grid.block_y_cm,
        gap_x_cm=grid.gap_x_cm,
        gap_y_cm=grid.gap_y_cm,
        workspace_width_cm=grid.workspace_width_cm,
        workspace_height_cm=grid.workspace_height_cm,
        trim_x_cm=grid.trim_x_cm,
        trim_y_cm=grid.trim_y_cm,
    )
    loaded, reason = load_workspace(path, shifted, projection)
    check("changed grid JSON invalidates map",
          loaded is None and "grid JSON" in reason, str(reason))

    # One v3 artifact holds both independently calibrated layouts.  Saving the
    # second map must preserve the first, and loading through the wrong mode is
    # a rejection even if callers forgot to look at the count shape first.
    horizontal = MachineGrid.from_config(mode="horizontal")
    horizontal_workspace = approximate_workspace(horizontal, image_size, projection)
    horizontal_workspace.save(path)
    vertical_loaded = WorkspaceMap.load(path, mode="vertical")
    horizontal_loaded = WorkspaceMap.load(path, mode="horizontal")
    check("two-mode workspace map retains vertical calibration",
          vertical_loaded.matches_grid(grid) and vertical_loaded.mode == "vertical")
    check("two-mode workspace map retains horizontal calibration",
          horizontal_loaded.matches_grid(horizontal) and horizontal_loaded.mode == "horizontal")
    check("a workspace calibration from the other mode is refused",
          not vertical_loaded.matches_grid(horizontal)
          and not vertical_loaded.matches_grid(grid, mode="horizontal"))

    # Coordinate zero is a REAL block now, not an axis lane. The old gap-wide
    # strips in negative cm are gone: [c,0] and [0,r] are ordinary cells drawn
    # by cell_polygon(), and [0,0] is the feeder.
    def bounds(polygon):
        points = np.asarray(polygon, dtype=float)
        return (points[:, 0].min(), points[:, 1].min(),
                points[:, 0].max(), points[:, 1].max())

    for target in ((1, 0), (0, 1), (0, 0)):
        centre = np.mean(horizontal_workspace.target_polygon(*target, image_size), axis=0)
        check(f"horizontal cell {target} is an ordinary selectable cell",
              horizontal_workspace.cell_at(centre, image_size) == target,
              str(horizontal_workspace.cell_at(centre, image_size)))
    check("target_polygon is just cell_polygon now",
          np.allclose(horizontal_workspace.target_polygon(0, 0, image_size),
                      horizontal_workspace.cell_polygon(0, 0, image_size)))

    # Flat v2 is the only legacy geometry that may migrate: it was necessarily
    # vertical because no horizontal layout existed when it was written.
    legacy_v2 = Path(directory) / "workspace_map_v2.json"
    entry = vertical_loaded._entry()
    legacy_v2.write_text(json.dumps({
        "version": 2,
        "view": "corrected",
        "corner_order": ["a", "b", "c", "d"],
        **entry,
    }))
    migrated = WorkspaceMap.load(legacy_v2, mode="vertical")
    check("flat v2 workspace map migrates into vertical",
          migrated.matches_grid(grid) and migrated.mode == "vertical")
    try:
        WorkspaceMap.load(legacy_v2, mode="horizontal")
        check("flat v2 map cannot masquerade as horizontal", False)
    except ValueError as exc:
        check("flat v2 map cannot masquerade as horizontal",
              "only a vertical calibration" in str(exc), str(exc))
    migrated.save(legacy_v2)
    migrated_document = json.loads(legacy_v2.read_text())
    check("saving a migrated map writes keyed modes",
          migrated_document["version"] == 3
          and set(migrated_document["modes"]) == {"vertical"})

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

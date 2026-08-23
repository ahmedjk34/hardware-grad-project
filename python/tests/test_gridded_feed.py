#!/usr/bin/env python3
"""Exercise the gridded feed geometry without opening a camera or window."""

from pathlib import Path
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


PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:42} {detail}")


grid = MachineGrid.from_config()
projection = {"version": 1, "view": "corrected", "test": True}
image_size = (1296, 972)
workspace = approximate_workspace(grid, image_size, projection)

first_x, first_y = grid.cell_center_cm(1, 1)
first_pixel = workspace.pixel_at(first_x / grid.workspace_width_cm,
                                 first_y / grid.workspace_height_cm,
                                 image_size)
frame = np.zeros((image_size[1], image_size[0], 3), dtype=np.uint8)
hovered = draw_machine_grid(frame, workspace, grid, first_pixel, calibrated=False)
check("overlay maps first physical centre", hovered == (1, 1), str(hovered))
check("overlay actually draws pixels", bool(np.any(frame)))
detail_frame = np.zeros_like(frame)
draw_machine_grid(detail_frame, workspace, grid, first_pixel,
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

    loaded, reason = load_workspace(path, grid, {"version": 2})
    check("changed camera projection invalidates map",
          loaded is None and "camera" in reason, str(reason))

    shifted = MachineGrid(
        cols=grid.cols,
        rows=grid.rows,
        cell_width_cm=1.9,
        cell_height_cm=grid.cell_height_cm,
        workspace_width_cm=grid.workspace_width_cm,
        workspace_height_cm=grid.workspace_height_cm,
        trim_x_cm=grid.trim_x_cm,
        trim_y_cm=grid.trim_y_cm,
    )
    loaded, reason = load_workspace(path, shifted, projection)
    check("changed grid JSON invalidates map",
          loaded is None and "grid JSON" in reason, str(reason))

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

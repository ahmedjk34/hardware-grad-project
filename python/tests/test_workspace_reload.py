#!/usr/bin/env python3
"""A calibration written by another process must reach a running console.

Run from python/:  ../.venv/bin/python tests/test_workspace_reload.py

The console reads config/workspace_map.json once at startup and again only
when the grid mode changes. On the rig the normal way to calibrate is to run
Camera Studio (BLOCK CAL SAVE) or camera/block_grid_calibrate.py in a SEPARATE
process while the app is up - and until ConsolePipeline.reload_workspace()
existed, that map was invisible until the app was restarted, with nothing
saying so. This is the regression guard for that.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import SETTINGS_PATH                        # noqa: E402
from rig.config import load as load_rig_config                      # noqa: E402
from rig.console_pipeline import ConsolePipeline                    # noqa: E402
from rig.grid import MachineGrid                                    # noqa: E402
from vision.block_grid import (                                     # noqa: E402
    block_workspace_map,
    detect_block_lattice,
)

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"ok    {name}")
    else:
        print(f"FAIL  {name}{': ' + detail if detail else ''}")
        failures.append(name)


def mock_settings(directory: Path) -> Path:
    data = json.loads(SETTINGS_PATH.read_text())
    data["capture"].update({"width": 1296, "height": 972})
    data["correction"]["enabled"] = False
    data["framing"] = {"crops": [], "zoom": 1.0, "pan": [0.5, 0.5]}
    path = directory / "camera_settings.json"
    path.write_text(json.dumps(data))
    return path


def fresh(pipeline, tries=25):
    for _ in range(tries):
        frame = pipeline.process_once()
        if frame is not None and not frame.stale:
            return frame
        time.sleep(0.05)
    raise AssertionError("the mock pipeline produced no fresh frame")


board_path = (Path(__file__).resolve().parents[1] / "captures"
              / "IMAGE_TO_TEST_BLOCK_CALIBRATION.png")
if not board_path.exists():
    raise SystemExit(f"missing {board_path}")

scratch = Path(tempfile.mkdtemp())
map_path = scratch / "workspace_map.json"
pipeline = ConsolePipeline(camera_backend="mock",
                           settings_path=mock_settings(scratch),
                           workspace_map_path=map_path)
pipeline.start()
try:
    frame = fresh(pipeline)
    check("a console with no map on disk is uncalibrated",
          not frame.calibrated and pipeline.saved_workspace is None,
          str(pipeline.workspace_rejection))

    # Another process calibrates and saves, exactly as Camera Studio does.
    grid = MachineGrid.from_config(load_rig_config())
    board = cv2.imread(str(board_path))
    calibration, _diagnostics = detect_block_lattice(
        board, grid, max_processing_width=board.shape[1])
    workspace = block_workspace_map(calibration, grid, board.shape[1::-1],
                                    projection=pipeline.projection)
    workspace.save(map_path)
    check("the other process wrote a map", map_path.exists())

    # The running console has already read the file, so it must not have
    # noticed - this is the behaviour that made a save look like it did
    # nothing, and asserting it is what keeps the reload honest.
    pipeline.process_once()
    check("a running console does NOT pick it up on its own",
          pipeline.saved_workspace is None)

    adopted, rejection = pipeline.reload_workspace()
    frame = fresh(pipeline)
    check("reload_workspace() adopts it", adopted is not None, str(rejection))
    check("and the frame now reports itself calibrated", frame.calibrated)
    check("the adopted map is for the active grid",
          adopted.matches_grid(pipeline.grid)
          and adopted.mode == pipeline.grid.mode)
    check("reloading bumps the map generation so overlays rebuild",
          pipeline._map_generation > 0)

    # A map that is present but wrong must come back as a SENTENCE, never as
    # silence: "nothing happened" and "refused because the lens changed" need
    # completely different responses from an operator.
    stale_projection = dict(pipeline.projection)
    stale_projection["roi"] = [0.1, 0.1, 0.8, 0.8]
    block_workspace_map(calibration, grid, board.shape[1::-1],
                        projection=stale_projection).save(map_path)
    adopted, rejection = pipeline.reload_workspace()
    check("a map saved under other camera geometry is refused with a reason",
          adopted is None and rejection and "camera" in rejection,
          str(rejection))
finally:
    pipeline.stop()

print()
if failures:
    print(f"{len(failures)} failing check(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

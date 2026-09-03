#!/usr/bin/env python3
"""A block calibration must be saved exactly as a paper one is.

Run from python/:  ../.venv/bin/python tests/test_calibration_parity.py

Two routes now write config/workspace_map.json - the printed-sheet detector
(web `/api/calibration/paper`, `paper_workspace_map`) and the placed-block one
(`block_workspace_map`). If those ever produce different artefacts, the app
adopts one and silently refuses the other, and the only symptom is "the grid
did not change". So this asserts the two are the SAME FILE, field for field,
rather than merely both plausible.

It also covers the one place they legitimately differ. The paper route runs
inside the app, so the `projection` it stamps - the lens/orientation/framing
identity a map is only valid under - matches the app's by construction. Camera
Studio does not: it is an editor, and its live geometry drifts from
camera_settings.json until SAVE JSON writes it. A map stamped with unsaved
editor state is refused by everything, correctly, because the frame it was
fitted to is not the frame the app renders.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import (                                    # noqa: E402
    SETTINGS_PATH,
    framing_roi,
    load_settings,
    profile_from_settings,
)
from camera.gridded_camera_feed import (                            # noqa: E402
    load_workspace,
    projection_metadata,
)
from rig.config import load as load_rig_config                      # noqa: E402
from rig.grid import MachineGrid                                    # noqa: E402
from rig.workspace import WorkspaceMap                              # noqa: E402
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


board_path = (Path(__file__).resolve().parents[1] / "captures"
              / "IMAGE_TO_TEST_BLOCK_CALIBRATION.png")
if not board_path.exists():
    raise SystemExit(f"missing {board_path}")

board = cv2.imread(str(board_path))
size = board.shape[1::-1]
grid = MachineGrid.from_config(load_rig_config())
settings = load_settings(SETTINGS_PATH)
correction = settings.get("correction") or {}
projection = projection_metadata(
    profile_from_settings(settings), settings.get("capture") or {},
    bool(correction.get("enabled", True)), framing_roi(settings))

calibration, _diagnostics = detect_block_lattice(
    board, grid, max_processing_width=board.shape[1])

# The block route.
block_map = block_workspace_map(calibration, grid, size, projection=projection)
# The paper route, byte for byte what web/routes_calibration.py::paper does
# via camera.gridded_camera_feed.paper_workspace_map - the same calibration
# object, so any difference in the written file is the ROUTE's doing and not
# the detector's.
paper_map = WorkspaceMap.from_grid(
    grid, calibration.workspace_corners(grid, "firmware"), size, projection)

scratch = Path(tempfile.mkdtemp())
block_map.save(scratch / "block.json")
paper_map.save(scratch / "paper.json")
block_doc = json.loads((scratch / "block.json").read_text())
paper_doc = json.loads((scratch / "paper.json").read_text())

check("both routes write the same document version and header",
      {k: block_doc[k] for k in ("version", "view", "corner_order")}
      == {k: paper_doc[k] for k in ("version", "view", "corner_order")})
check("both routes write the same set of modes",
      set(block_doc["modes"]) == set(paper_doc["modes"]),
      f"{sorted(block_doc['modes'])} vs {sorted(paper_doc['modes'])}")

entry_block = block_doc["modes"][grid.mode]
entry_paper = paper_doc["modes"][grid.mode]
check("the mode entries carry the same fields",
      set(entry_block) == set(entry_paper),
      f"{sorted(entry_block)} vs {sorted(entry_paper)}")
for field in sorted(set(entry_block) | set(entry_paper)):
    check(f"  the {field!r} field is identical",
          entry_block.get(field) == entry_paper.get(field),
          f"block={json.dumps(entry_block.get(field))[:90]} "
          f"paper={json.dumps(entry_paper.get(field))[:90]}")

check("THE WHOLE FILE IS IDENTICAL", block_doc == paper_doc)

# Both must be adopted by a consumer, under the same projection, for the same
# grid. This is the claim that actually matters to an operator.
for name, path in (("block", scratch / "block.json"),
                   ("paper", scratch / "paper.json")):
    adopted, reason = load_workspace(path, grid, projection)
    check(f"the {name} map is adopted by the feed",
          adopted is not None, str(reason))
    check(f"the {name} map is for the active grid and mode",
          adopted is not None and adopted.matches_grid(grid)
          and adopted.mode == grid.mode)

# Saving one mode must not disturb the other's entry: a workspace map holds
# both, and calibrating vertical has never been allowed to drop horizontal.
other = "horizontal" if grid.mode == "vertical" else "vertical"
other_grid = MachineGrid.from_config(load_rig_config(), mode=other)
shared = scratch / "shared.json"
WorkspaceMap.from_grid(
    other_grid, [(10, 500), (300, 500), (300, 60), (10, 60)], size,
    projection).save(shared)
block_map.save(shared)
document = json.loads(shared.read_text())
check("saving one mode leaves the other mode's entry intact",
      set(document["modes"]) == {grid.mode, other},
      str(sorted(document["modes"])))
check("and the mode just saved is the block one",
      document["modes"][grid.mode] == entry_block)

print()
if failures:
    print(f"{len(failures)} failing check(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

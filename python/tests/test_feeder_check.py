#!/usr/bin/env python3
"""`rig.feeder_check.feeder_has_block` — presence only, and fails CLOSED.

Hand-rolled like `test_supervisor.py`: a `check` helper, no pytest. The one job
this module has is "is a block staged at `[0,0]` right now", and every way the
camera could be unsure has to come back False so a caller that acts on True can
only ever close the claw on evidence.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.feeder_check import feeder_has_block  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from rig.supervisor import FEEDER_CELL, FEEDER_RADIUS_CM  # noqa: E402
from rig.workspace import WorkspaceMap  # noqa: E402


PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:58} {detail}")


GRID = MachineGrid.from_config(mode="vertical")
SIZE = (1000, 800)
MAP = WorkspaceMap.from_grid(GRID, ((0, 0), (1000, 0), (1000, 800), (0, 800)), SIZE)
FEEDER = GRID.cell_center_cm(*FEEDER_CELL)
FAR = GRID.cell_center_cm(3, 2)


def px(x_cm, y_cm):
    return MAP.pixel_at(x_cm / GRID.workspace_width_cm,
                        y_cm / GRID.workspace_height_cm, SIZE)


class Det:
    def __init__(self, center):
        self.center = center


class Frame:
    def __init__(self, *, detections=None, workspace=MAP, image_size=SIZE,
                 calibrated=True, analysis_ok=True, stale=False):
        self.detections = detections or []
        self.workspace = workspace
        self.image_size = image_size
        self.calibrated = calibrated
        self.analysis_ok = analysis_ok
        self.stale = stale


present, why = feeder_has_block(Frame(detections=[Det(px(*FEEDER))]))
check("a block on the feeder centre reads present", present, why)

near = (FEEDER[0] + FEEDER_RADIUS_CM * 0.6, FEEDER[1])
check("a hand-fed block a little off centre still reads present",
      feeder_has_block(Frame(detections=[Det(px(*near))]))[0])

far = (FEEDER[0] + FEEDER_RADIUS_CM + 2.0, FEEDER[1])
absent, why = feeder_has_block(Frame(detections=[Det(px(*far))]))
check("a block past the feeder radius does NOT read present", not absent, why)

check("an empty frame reads absent",
      not feeder_has_block(Frame(detections=[]))[0])
check("a block elsewhere on the board reads absent at the feeder",
      not feeder_has_block(Frame(detections=[Det(px(*FAR))]))[0])

# HORIZONTAL mode: the physical feeder is STILL the machine home corner (cm
# (0,0)), NOT horizontal [0,0], which is registered +1.9 cm out on both axes.
HGRID = MachineGrid.from_config(mode="horizontal")
HMAP = WorkspaceMap.from_grid(HGRID, ((0, 0), (1000, 0), (1000, 800), (0, 800)), SIZE)


def hpx(x_cm, y_cm):
    return HMAP.pixel_at(x_cm / HGRID.workspace_width_cm,
                         y_cm / HGRID.workspace_height_cm, SIZE)


hframe = lambda dets: Frame(detections=dets, workspace=HMAP)
check("horizontal: a block at the home corner (0,0) cm reads present",
      feeder_has_block(hframe([Det(hpx(0.0, 0.0))]))[0])
h00 = HGRID.cell_center_cm(0, 0)
check("horizontal: a block on horizontal [0,0] (+1.9 cm out) is NOT the feeder",
      h00 != (0.0, 0.0)
      and not feeder_has_block(hframe([Det(hpx(*h00))]))[0],
      str(h00))

# Fail-closed: every uncertainty is (False, reason), never (True, ...).
staged = [Det(px(*FEEDER))]
for label, frame in [
    ("None frame", None),
    ("uncalibrated", Frame(detections=staged, calibrated=False)),
    ("analysis not ok", Frame(detections=staged, analysis_ok=False)),
    ("stale frame", Frame(detections=staged, stale=True)),
    ("no workspace", Frame(detections=staged, workspace=None)),
]:
    result, reason = feeder_has_block(frame)
    check(f"fails closed: {label}", result is False and isinstance(reason, str), reason)

print()
print(f"{len(PASSED)} passed, {len(FAILED)} failed")
raise SystemExit(1 if FAILED else 0)

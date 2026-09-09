#!/usr/bin/env python3
"""The orientation rule is inside detect_aligned_blocks, before its lattice."""

from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.grid import MachineGrid  # noqa: E402
from rig.workspace import WorkspaceMap  # noqa: E402
from vision.block_detector import BlockDetection  # noqa: E402
from vision.block_outline import detect_aligned_blocks  # noqa: E402
from vision.orientation_filter import local_machine_axis_angles  # noqa: E402


SIZE = (400, 300)
FRAME = np.zeros((SIZE[1], SIZE[0], 3), dtype=np.uint8)
HORIZONTAL = MachineGrid.from_config(mode="horizontal")
VERTICAL = MachineGrid.from_config(mode="vertical")
MAP = WorkspaceMap.from_grid(
    HORIZONTAL, ((20, 280), (380, 265), (350, 25), (40, 35)), SIZE)
CENTER = MAP.pixel_at(0.5, 0.5, SIZE)
X_ANGLE, Y_ANGLE = local_machine_axis_angles(MAP, CENTER, SIZE)


def block(angle):
    cx, cy = CENTER
    box = np.asarray(((cx - 25, cy - 8), (cx + 25, cy - 8),
                      (cx + 25, cy + 8), (cx - 25, cy + 8)), dtype=np.int32)
    return BlockDetection(
        contour=box.reshape(-1, 1, 2), box=box, center=CENTER,
        width=50.0, height=16.0, angle=angle, area=800.0,
        rectangularity=1.0, solidity=1.0, confidence=1.0, hue=20.0)


horizontal, vertical = block(X_ANGLE), block(Y_ANGLE)

# Keep duplicate centres out of one call because duplicate removal correctly
# treats them as one physical object. Each assertion independently proves that
# the active mode accepts its own orientation and rejects the other one.
with patch("vision.block_outline.detect_blocks", return_value=[horizontal]):
    assert detect_aligned_blocks(
        FRAME, grid=HORIZONTAL, orientation_workspace=MAP,
        include_rejected=True, rectify=False) == [horizontal]
with patch("vision.block_outline.detect_blocks", return_value=[vertical]):
    assert detect_aligned_blocks(
        FRAME, grid=HORIZONTAL, orientation_workspace=MAP,
        include_rejected=True, rectify=False) == []
with patch("vision.block_outline.detect_blocks", return_value=[vertical]):
    assert detect_aligned_blocks(
        FRAME, grid=VERTICAL, orientation_workspace=MAP,
        include_rejected=True, rectify=False) == [vertical]

print("all detector-orientation integration checks passed")

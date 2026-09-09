#!/usr/bin/env python3
"""Stack tops are resolved before detect_aligned_blocks filters orientation."""

from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch

import cv2
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

# Named real-frame regression. The top-left pile has one vertical block above
# two horizontal blocks; the scene also contains two-horizontal-on-two-vertical
# piles, a two-vertical cap, and an inverted U with a horizontal cap. Stack
# resolution must keep every block in each highest course, not elect one
# rectangle for the whole connected pile.
capture_path = (Path(__file__).resolve().parents[1] / "captures" /
                "20260909-094841_corrected_equidistant-lens168-out120-"
                "k+0.14_+0.18_+0.03_+0.00-c+0_+0-f1.200_1.105-s+0.042-"
                "p-0.020_+0.008.png")
capture = cv2.imread(str(capture_path))
assert capture is not None
image_size = capture.shape[1::-1]


def full_frame_map(grid):
    width, height = image_size
    return WorkspaceMap.from_grid(
        grid, ((0, height - 1), (width - 1, height - 1),
               (width - 1, 0), (0, 0)), image_size)


vertical_map = full_frame_map(VERTICAL)
horizontal_map = full_frame_map(HORIZONTAL)
vertical_tops = detect_aligned_blocks(
    capture, grid=VERTICAL, orientation_workspace=vertical_map,
    include_rejected=True, rectify=False, stack_aware=True)
horizontal_tops = detect_aligned_blocks(
    capture, grid=HORIZONTAL, orientation_workspace=horizontal_map,
    include_rejected=True, rectify=False, stack_aware=True)

assert len(vertical_tops) == 4
assert len(horizontal_tops) == 5


def centres_near(detections, expected, radius=7):
    return all(any(np.hypot(item.center[0] - x, item.center[1] - y) <= radius
                   for item in detections) for x, y in expected)


assert centres_near(vertical_tops,
                    ((160, 165), (214, 247), (236, 247), (135, 407)))
assert centres_near(horizontal_tops,
                    ((268, 327), (208, 332), (266, 363),
                     (210, 366), (262, 423)))
# Explicit lower-course negatives: matching the count is not enough.
assert all(np.hypot(item.center[0] - 176, item.center[1] - 149) > 7
           for item in horizontal_tops)
assert all(np.hypot(item.center[0] - 176, item.center[1] - 184) > 7
           for item in horizontal_tops)
assert all(np.hypot(item.center[0] - 252, item.center[1] - 345) > 7
           for item in vertical_tops)

print("all detector-orientation and stack-first capture checks passed")

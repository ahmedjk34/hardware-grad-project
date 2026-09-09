#!/usr/bin/env python3
"""Mode-specific block orientation, including projective and stacked shifts."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.grid import MachineGrid  # noqa: E402
from rig.workspace import WorkspaceMap  # noqa: E402
from vision.orientation_filter import (  # noqa: E402
    PICKUP_ORIENTATION_EXEMPT_RADIUS_CM, detection_matches_mode,
    filter_detections_for_mode,
    local_machine_axis_angles,
)


SIZE = (1000, 800)
GRID = MachineGrid.from_config(mode="horizontal")
# Deliberately projective/skewed: classification must use local machine axes,
# not assume screen-horizontal and screen-vertical everywhere.
MAP = WorkspaceMap.from_grid(
    GRID, ((90, 760), (940, 700), (850, 70), (150, 120)), SIZE)


def detection_at(u, v, axis, angle_offset=0.0):
    point = MAP.pixel_at(u, v, SIZE)
    axes = local_machine_axis_angles(MAP, point, SIZE)
    angle = axes[0 if axis == "x" else 1] + angle_offset
    return SimpleNamespace(center=point, angle=angle, own_angle=angle)


horizontal = detection_at(0.45, 0.45, "x")
vertical = detection_at(0.45, 0.45, "y")
assert detection_matches_mode(horizontal, MAP, SIZE, "horizontal")
assert not detection_matches_mode(vertical, MAP, SIZE, "horizontal")
assert detection_matches_mode(vertical, MAP, SIZE, "vertical")
assert not detection_matches_mode(horizontal, MAP, SIZE, "vertical")

# Horizontal pickup is the deliberate exception: blocks are staged standing
# at raw machine home and the auto-pickup gate must still see that detection.
feeder = detection_at(0.0, 0.0, "y")
near_u = (PICKUP_ORIENTATION_EXEMPT_RADIUS_CM * 0.9
          / GRID.workspace_width_cm)
near_feeder = detection_at(near_u, 0.0, "y")
past_u = (PICKUP_ORIENTATION_EXEMPT_RADIUS_CM * 1.1
          / GRID.workspace_width_cm)
past_feeder = detection_at(past_u, 0.0, "y")
assert detection_matches_mode(feeder, MAP, SIZE, "horizontal")
assert detection_matches_mode(near_feeder, MAP, SIZE, "horizontal")
assert not detection_matches_mode(past_feeder, MAP, SIZE, "horizontal")

# A stack-height parallax shift changes where the block is observed, but the
# locally projected axis still identifies it. Test both near and far regions.
for u, v in ((0.15, 0.18), (0.80, 0.72), (0.52, 0.30)):
    raised_horizontal = detection_at(u, v, "x", angle_offset=8.0)
    raised_vertical = detection_at(u, v, "y", angle_offset=-8.0)
    assert detection_matches_mode(raised_horizontal, MAP, SIZE, "horizontal")
    assert not detection_matches_mode(raised_vertical, MAP, SIZE, "horizontal")

# A badly rotated/occluded block in the ambiguity band stays visible so the
# supervisor can call it missing/displaced rather than the detector hiding it.
axes = local_machine_axis_angles(MAP, MAP.pixel_at(0.5, 0.5, SIZE), SIZE)
ambiguous = SimpleNamespace(center=MAP.pixel_at(0.5, 0.5, SIZE),
                            angle=(axes[0] + axes[1]) / 2,
                            own_angle=(axes[0] + axes[1]) / 2)
assert detection_matches_mode(ambiguous, MAP, SIZE, "horizontal")

# No map and off-board points fail open. Input order is preserved.
outside = SimpleNamespace(center=(-500.0, -500.0), angle=90.0, own_angle=90.0)
assert detection_matches_mode(vertical, None, SIZE, "horizontal")
assert detection_matches_mode(outside, MAP, SIZE, "horizontal")
assert filter_detections_for_mode(
    [horizontal, vertical, outside], MAP, SIZE, "horizontal") == [horizontal, outside]

print("all orientation-filter checks passed")

"""Classify block orientation against the camera-projected machine axes.

Block segmentation is deliberately shape-based, so it finds both ways a block
can lie.  A mode-aware feed needs one additional question before lattice
fitting: is the detected block's measured long axis closer to machine X
(``horizontal``) or machine Y (``vertical``)?

The comparison is local to the detection.  A projective workspace map can make
the machine axes converge across the image, so a single screen-space angle is
not sufficient.  Position may move under stack-height parallax; orientation
does not, and the generous angular tolerance absorbs the small perspective and
segmentation error of elevated blocks.
"""

from __future__ import annotations

import math


#: A block confidently belongs to an axis when its measured long edge is no
#: more than this far from that locally projected machine axis.  The two block
#: orientations differ by about 90 degrees, leaving a broad ambiguous band for
#: a badly rotated/occluded block.  Ambiguous detections are retained so
#: supervision can still report a displaced block rather than silently hiding
#: uncertain evidence.
ORIENTATION_AXIS_TOLERANCE_DEG = 35.0

#: The horizontal build still receives a STANDING block at physical home. The
#: autonomous pickup gate reads the detector output, so this one operational
#: region must retain either orientation. This matches the feeder observer's
#: measured radius; it is not a grid/model shift and never applies elsewhere.
PICKUP_ORIENTATION_EXEMPT_RADIUS_CM = 1.6

#: Finite-difference step in normalized workspace coordinates. Large enough to
#: avoid numerical noise, small enough to follow perspective locally.
LOCAL_AXIS_STEP = 0.01


def axis_error_deg(left: float, right: float) -> float:
    """Smallest difference between two unoriented axes, in ``[0, 90]``."""
    return abs((float(left) - float(right) + 90.0) % 180.0 - 90.0)


def _angle(a, b) -> float | None:
    dx, dy = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
    if not (math.isfinite(dx) and math.isfinite(dy)) or math.hypot(dx, dy) < 1e-6:
        return None
    return math.degrees(math.atan2(dy, dx))


def local_machine_axis_angles(workspace, point, image_size):
    """Return local ``(X angle, Y angle)`` in corrected-image pixels.

    ``None`` means the point/map cannot support a safe classification.  Points
    outside the calibrated holder envelope are deliberately left unclassified:
    off-board detections remain available to the existing junk/margin logic.
    """
    if workspace is None or point is None or image_size is None:
        return None
    try:
        u, v = workspace.normalized_at(point, image_size)
        if not (math.isfinite(u) and math.isfinite(v)
                and 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            return None

        x0, x1 = max(0.0, u - LOCAL_AXIS_STEP), min(1.0, u + LOCAL_AXIS_STEP)
        y0, y1 = max(0.0, v - LOCAL_AXIS_STEP), min(1.0, v + LOCAL_AXIS_STEP)
        if x1 <= x0 or y1 <= y0:
            return None
        x_angle = _angle(workspace.pixel_at(x0, v, image_size),
                         workspace.pixel_at(x1, v, image_size))
        y_angle = _angle(workspace.pixel_at(u, y0, image_size),
                         workspace.pixel_at(u, y1, image_size))
    except (AttributeError, TypeError, ValueError, ArithmeticError):
        return None
    if x_angle is None or y_angle is None:
        return None
    return x_angle, y_angle


def detection_matches_mode(detection, workspace, image_size, mode: str) -> bool:
    """Whether a detection should remain visible in ``mode``.

    A confident opposite-axis block is removed. A correct-axis block and any
    ambiguous/unprojectable detection are retained (fail open).
    """
    if mode not in ("vertical", "horizontal"):
        return True
    # Preserve the one intentional opposite-orientation block: horizontal
    # mode is fed a standing block at raw machine home (0, 0). Do this before
    # orientation classification so automatic pickup can still see it.
    try:
        grid = workspace.mapped_grid
        u, v = workspace.normalized_at(getattr(detection, "center", None), image_size)
        x_cm = float(u) * float(grid.workspace_width_cm)
        y_cm = float(v) * float(grid.workspace_height_cm)
        if (math.isfinite(x_cm) and math.isfinite(y_cm)
                and math.hypot(x_cm, y_cm) <= PICKUP_ORIENTATION_EXEMPT_RADIUS_CM):
            return True
    except (AttributeError, TypeError, ValueError, ArithmeticError):
        pass
    axes = local_machine_axis_angles(
        workspace, getattr(detection, "center", None), image_size)
    if axes is None:
        return True
    angle = getattr(detection, "own_angle", None)
    if angle is None:
        angle = getattr(detection, "angle", None)
    try:
        angle = float(angle)
    except (TypeError, ValueError):
        return True
    if not math.isfinite(angle):
        return True

    x_error = axis_error_deg(angle, axes[0])
    y_error = axis_error_deg(angle, axes[1])
    expected, opposite = ((y_error, x_error) if mode == "vertical"
                          else (x_error, y_error))
    if expected <= ORIENTATION_AXIS_TOLERANCE_DEG:
        return True
    if opposite <= ORIENTATION_AXIS_TOLERANCE_DEG and opposite < expected:
        return False
    return True


def filter_detections_for_mode(detections, workspace, image_size, mode: str):
    """Preserve order while removing confidently opposite-orientation blocks."""
    return [item for item in detections
            if detection_matches_mode(item, workspace, image_size, mode)]

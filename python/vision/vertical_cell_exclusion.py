"""Ignore standing-grid remnants while the horizontal grid is active.

The detector intentionally keeps off-lattice blocks for placement supervision.
That is normally the safe choice, but a fully seated vertical block left on the
board is not evidence about a horizontal build.  This module removes only that
specific, measured case at the detector-output boundary.

It receives a *vertical* :class:`rig.workspace.WorkspaceMap` built from the
same calibrated camera-envelope corners as the horizontal frame.  It therefore
uses the detection's original pixel footprint and maps it through the real
camera geometry; it never guesses from an image-space centre or changes the
supervisor's mode-agnostic classification.
"""

from __future__ import annotations

import math

import numpy as np


#: Permit a measured block footprint to extend 3 mm past a vertical cell edge.
#: This is a detection-classification tolerance, not a grid shift or a motion
#: calibration.  It is far below the 1.6 cm inter-cell gap, so it cannot turn a
#: block visibly sitting between vertical cells into an ignored remnant.
VERTICAL_CELL_CONTAINMENT_MARGIN_CM = 0.3


def _measured_box(detection) -> np.ndarray | None:
    """Return the pre-rectification footprint in corrected-image pixels.

    ``block_outline`` preserves these measurements because its drawn box may
    be rectified to a population median.  Bare test doubles and callers that
    do not carry them fall back to ``box``.  An incomplete measurement is not
    grounds to hide a detection, so it returns ``None`` rather than guessing.
    """
    width = getattr(detection, "measured_width", None)
    height = getattr(detection, "measured_height", None)
    angle = getattr(detection, "measured_angle", None)
    centre = getattr(detection, "center", None)
    if (width is not None and height is not None and angle is not None
            and centre is not None
            and all(math.isfinite(float(value)) for value in
                    (width, height, angle, centre[0], centre[1]))
            and float(width) > 0 and float(height) > 0):
        # This is the detector's own rectangle geometry written out so this
        # small physical filter has no OpenCV dependency of its own.  Unlike
        # cv2.minAreaRect's raw angle, ``BlockDetection.angle`` names the LONG
        # side (see ``block_detector._geometry``), hence the long/short split.
        theta = math.radians(float(angle))
        long, short = max(float(width), float(height)), min(float(width), float(height))
        ux, uy = math.cos(theta) * long / 2, math.sin(theta) * long / 2
        vx, vy = -math.sin(theta) * short / 2, math.cos(theta) * short / 2
        cx, cy = float(centre[0]), float(centre[1])
        return np.asarray(((cx + ux + vx, cy + uy + vy),
                           (cx + ux - vx, cy + uy - vy),
                           (cx - ux - vx, cy - uy - vy),
                           (cx - ux + vx, cy - uy + vy)), dtype=np.float64)

    box = getattr(detection, "box", None)
    if box is None:
        return None
    points = np.asarray(box, dtype=np.float64).reshape(-1, 2)
    if len(points) != 4 or not np.isfinite(points).all():
        return None
    return points


def fully_within_vertical_cell(detection, workspace, image_size, *,
                               margin_cm: float = VERTICAL_CELL_CONTAINMENT_MARGIN_CM) -> bool:
    """Whether a measured detection lies wholly inside one vertical cell.

    The margin expands a cell's *acceptance* boundary by 3 mm; it does not
    move either grid.  Every footprint corner must fit the same cell.  Failure
    to project a corner or missing physical geometry is fail-open (``False``).
    """
    if margin_cm < 0 or not math.isfinite(float(margin_cm)):
        raise ValueError("vertical-cell containment margin must be finite and non-negative")
    grid = getattr(workspace, "mapped_grid", None)
    if grid is None or getattr(grid, "mode", None) != "vertical":
        return False
    box = _measured_box(detection)
    if box is None:
        return False

    points_cm = []
    try:
        for px, py in box:
            u, v = workspace.normalized_at((float(px), float(py)), image_size)
            if not (math.isfinite(u) and math.isfinite(v) and 0.0 <= u <= 1.0
                    and 0.0 <= v <= 1.0):
                return False
            points_cm.append((u * grid.workspace_width_cm,
                              v * grid.workspace_height_cm))
    except (TypeError, ValueError, AttributeError):
        return False

    # The first point narrows this to at most one cell in ordinary geometry;
    # scanning deliberately remains correct at the small expanded-edge overlap.
    for col in range(grid.cols):
        for row in range(grid.rows):
            left, bottom, right, top = grid.cell_bounds_cm(col, row)
            if all(left - margin_cm <= x <= right + margin_cm
                   and bottom - margin_cm <= y <= top + margin_cm
                   for x, y in points_cm):
                return True
    return False


def exclude_vertical_cell_remnants(detections, workspace, image_size):
    """Return detections except fully seated vertical remnants.

    Callers pass ``workspace=None`` outside calibrated horizontal mode, making
    this intentionally a no-op.  Preserve the detector's normal list return
    type and its sequence order.
    """
    if workspace is None:
        return detections
    return [detection for detection in detections
            if not fully_within_vertical_cell(detection, workspace, image_size)]

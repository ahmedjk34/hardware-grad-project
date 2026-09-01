"""JSON drawing geometry for the browser-owned SVG overlay."""

from __future__ import annotations

from typing import Any


_STATIC_GRID_CACHE: dict[tuple, tuple[dict[str, Any], ...]] = {}


def _static_grid(workspace, image_size: tuple[int, int]) -> tuple[dict[str, Any], ...]:
    """Project each real block cell once for an unchanged workspace/view size.

    This follows the same coordinate-zero-inclusive iteration as
    ``gridded_camera_feed._grid_geometry``.  It preserves actual block gaps by
    using ``WorkspaceMap.target_polygon`` rather than drawing pitch rectangles.
    """
    grid = workspace.mapped_grid
    key = (image_size, tuple(workspace.corners), grid.mode, grid.cols, grid.rows,
           grid.block_x_cm, grid.block_y_cm, grid.gap_x_cm, grid.gap_y_cm,
           grid.trim_x_cm, grid.trim_y_cm, grid.error_offset_x_cm,
           grid.error_offset_y_cm)
    cached = _STATIC_GRID_CACHE.get(key)
    if cached is not None:
        return cached
    cells = []
    for row in range(grid.rows):
        for col in range(grid.cols):
            polygon = workspace.target_polygon(col, row, image_size)
            cells.append({
                "col": col,
                "row": row,
                "polygon": [[float(x), float(y)] for x, y in polygon],
            })
    cached = tuple(cells)
    if len(_STATIC_GRID_CACHE) >= 16:
        _STATIC_GRID_CACHE.pop(next(iter(_STATIC_GRID_CACHE)))
    _STATIC_GRID_CACHE[key] = cached
    return cached


def _colour_name(hue: float) -> str:
    """Give the browser a stable, small display palette from OpenCV HSV hue."""
    hue = float(hue)
    if hue < 10 or hue >= 170:
        return "red"
    if hue < 25:
        return "orange"
    if hue < 40:
        return "yellow"
    if hue < 85:
        return "green"
    return "blue"


def build_geometry(frame, selected: tuple[int, int] | None) -> dict[str, Any]:
    """Combine cached grid geometry with the frame's dynamic overlay data."""
    workspace = frame.workspace
    image_size = frame.image_size
    selected_geometry = None
    if selected is not None:
        col, row = selected
        if workspace.mapped_grid.contains(col, row):
            selected_geometry = {
                "col": col,
                "row": row,
                "polygon": [[float(x), float(y)] for x, y in
                            workspace.target_polygon(col, row, image_size)],
            }
    detections = []
    for detection in frame.detections:
        detections.append({
            "color": _colour_name(detection.hue),
            "center": [float(detection.center[0]), float(detection.center[1])],
            "box": [[float(x), float(y)] for x, y in detection.box],
        })
    return {
        "image_size": [int(image_size[0]), int(image_size[1])],
        "calibrated": bool(frame.calibrated),
        "grid": list(_static_grid(workspace, image_size)),
        "selected": selected_geometry,
        "detections": detections,
        "paper": None,
    }

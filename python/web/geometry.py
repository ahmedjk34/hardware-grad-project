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
           grid.error_offset_y_cm,
           # The live grid shift moves every drawn cell but the feeder.
           grid.shift_x_cm, grid.shift_y_cm)
    cached = _STATIC_GRID_CACHE.get(key)
    if cached is not None:
        return cached
    cells = []
    for row in range(grid.rows):
        for col in range(grid.cols):
            polygon = workspace.target_polygon(col, row, image_size)
            cell = {
                "col": col,
                "row": row,
                "polygon": [[float(x), float(y)] for x, y in polygon],
            }
            cells.append(cell)
    cached = tuple(cells)
    if len(_STATIC_GRID_CACHE) >= 16:
        _STATIC_GRID_CACHE.pop(next(iter(_STATIC_GRID_CACHE)))
    _STATIC_GRID_CACHE[key] = cached
    return cached


def _feeder_marker(workspace, image_size: tuple[int, int]) -> dict[str, Any] | None:
    """A faint marker at the PHYSICAL feeder — the machine home corner, i.e. the
    VERTICAL grid's `[0,0]`, in BOTH modes.

    In vertical mode it sits under the drawn `[0,0]` cell. In HORIZONTAL mode
    the drawn `[0,0]` cell is registered `+1.9 cm` out (AGENTS.md §3a) but the
    pickup is still "a plain home to raw `[0,0]`", so the true feeder is a
    distinct, otherwise-unmarked point — this is what draws it. The browser
    renders it faintly; it is where a block is hand-fed, never a build target.
    """
    grid = getattr(workspace, "mapped_grid", None)
    if grid is None:
        return None
    from rig.supervisor import FEEDER_RADIUS_CM

    w_cm = float(grid.workspace_width_cm)
    h_cm = float(grid.workspace_height_cm)
    if w_cm <= 0 or h_cm <= 0:
        return None
    r = float(FEEDER_RADIUS_CM)
    corners_cm = ((-r, -r), (r, -r), (r, r), (-r, r))
    polygon = [
        [float(x), float(y)]
        for x, y in (workspace.pixel_at(cx / w_cm, cy / h_cm, image_size)
                     for cx, cy in corners_cm)
    ]
    centre = workspace.pixel_at(0.0, 0.0, image_size)
    # The drawn `[0,0]` cell sits at its registration (`trim + error_offset`)
    # and never rides the live grid shift, so the marker coincides with it iff
    # that registration is zero — vertical today, not horizontal's `+1.9 cm`.
    drawn_zero_cm = (grid.trim_x_cm + grid.error_offset_x_cm,
                     grid.trim_y_cm + grid.error_offset_y_cm)
    return {
        "mode": grid.mode,
        "center": [float(centre[0]), float(centre[1])],
        "polygon": polygon,
        # True when the marker does NOT coincide with the drawn `[0,0]` cell,
        # so the browser labels it as the true, separate feeder point.
        "offset_from_cell": abs(drawn_zero_cm[0]) > 1e-6 or abs(drawn_zero_cm[1]) > 1e-6,
    }


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
        "feeder": _feeder_marker(workspace, image_size),
        "detections": detections,
        "paper": None,
    }

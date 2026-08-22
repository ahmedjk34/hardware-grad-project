#!/usr/bin/env python3
"""The canonical camera feed plus the rig's physical block grid.

This uses exactly the same saved camera settings, correction, framing and block
detection as ``camera_feed.py``. Grid geometry comes from ``config/rig.json``.

The grid opens immediately as an amber, full-frame APPROXIMATION so it is
visible even before calibration. Press ``c`` and click the four complete
machine-envelope corners in the prompted order to make it real. The resulting
four-corner map is saved to ``config/workspace_map.json`` and reloaded on the
next run. A changed lens/framing setup or changed grid JSON invalidates that map
instead of silently drawing an old calibration.

Keys
----
  c       calibrate/recalibrate: click four prompted envelope corners
  Enter   save the reviewed four-corner calibration
  u       undo the most recent calibration corner
  x       cancel an in-progress calibration
  g       toggle grid overlay
  s       save annotated frame and block detection JSON
  q/Esc   quit
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

# This file lives below python/, so make the shared packages importable when it
# is launched from either the repository root or python/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import (  # noqa: E402
    SETTINGS_PATH,
    capture_settings,
    crop_resize,
    draw_block_overlay,
    enhance_for_display,
    frame_orientation,
    framing_roi,
    load_settings,
    profile_from_settings,
    save_detection_snapshot,
    sensor_from_settings,
)
from rig.config import CONFIG_PATH, load as load_rig_config  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from rig.workspace import CORNER_NAMES, WORKSPACE_MAP_PATH, WorkspaceMap  # noqa: E402
from vision.block_detector import detect_blocks  # noqa: E402
from vision.camera_source import open_camera  # noqa: E402
from vision.fisheye import INTERPOLATIONS, build_maps, undistort  # noqa: E402
from vision.overlays import (  # noqa: E402
    GRID_COLOR,
    HOVER_COLOR,
    LABEL_COLOR,
    WARN_COLOR,
    draw_info_box,
)


ENVELOPE_COLOR = (170, 170, 170)
CALIBRATION_COLOR = (255, 180, 30)       # orange: diagonal
CALIBRATION_HORIZONTAL = (255, 255, 0)   # cyan: screen-horizontal
CALIBRATION_VERTICAL = (255, 0, 255)     # magenta: screen-vertical
CALIBRATION_AXIS_TOLERANCE_PX = 2


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH,
                        help=f"camera settings JSON (default: {SETTINGS_PATH})")
    parser.add_argument("--rig-config", type=Path, default=CONFIG_PATH,
                        help=f"grid/workspace JSON (default: {CONFIG_PATH})")
    parser.add_argument("--workspace-map", type=Path, default=WORKSPACE_MAP_PATH,
                        help=f"four-corner calibration JSON (default: {WORKSPACE_MAP_PATH})")
    parser.add_argument("--display-scale", type=float, default=1.0,
                        help="scale only the display window; mapping stays at feed size")
    parser.add_argument("--color-threshold", type=int, default=8,
                        help="minimum red-minus-blue value for a block (default: 8)")
    parser.add_argument("--min-area", type=int, default=500,
                        help="minimum detected block area in feed pixels (default: 500)")
    parser.add_argument("--no-enhance", action="store_true",
                        help="disable display contrast/sharpness enhancement")
    return parser.parse_args()


def projection_metadata(profile, capture, enabled, roi):
    """JSON-stable identity for geometry that invalidates four clicked points."""
    return {
        "version": 1,
        "view": "corrected" if enabled else "framed-raw",
        "lens": asdict(profile),
        "orientation": {
            "flip": capture.get("flip", "none"),
            "rotate": capture.get("rotate", 0),
        },
        "roi": [float(value) for value in roi],
    }


def approximate_workspace(grid, image_size, projection):
    """Full-frame preview only; four real clicks must replace this."""
    w, h = image_size
    corners = [(0, h - 1), (w - 1, h - 1), (w - 1, 0), (0, 0)]
    return WorkspaceMap.from_grid(grid, corners, image_size, projection)


def load_workspace(path, grid, projection):
    """Return a trustworthy saved map, or a concise reason it was rejected."""
    try:
        workspace = WorkspaceMap.load(path)
    except FileNotFoundError:
        return None, "no four-corner calibration saved"
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return None, f"workspace map invalid: {exc}"
    if not workspace.matches_grid(grid):
        return None, "workspace map is for different grid JSON"
    if workspace.projection != projection:
        return None, "camera lens/orientation/framing changed"
    return workspace, None


def _point(workspace, grid, x_cm, y_cm, image_size):
    return workspace.pixel_at(x_cm / grid.workspace_width_cm,
                              y_cm / grid.workspace_height_cm, image_size)


def _pixel(point):
    return tuple(round(value) for value in point)


def draw_machine_grid(frame, workspace, grid, hover_point, calibrated):
    """Draw envelope, fixed-pitch cells, labels and the hovered cell."""
    image_size = frame.shape[1::-1]

    # The four calibration points surround the complete motion envelope. Draw
    # it separately so the unused centred strips are visible around the cells.
    envelope = np.asarray([
        workspace.pixel_at(0.0, 0.0, image_size),
        workspace.pixel_at(1.0, 0.0, image_size),
        workspace.pixel_at(1.0, 1.0, image_size),
        workspace.pixel_at(0.0, 1.0, image_size),
    ], dtype=np.float32).round().astype(np.int32)
    cv2.polylines(frame, [envelope], True, ENVELOPE_COLOR, 2, cv2.LINE_AA)

    # A projective transform keeps each constant-X/Y boundary straight, so one
    # line per boundary is enough and avoids redrawing all 110 cell polygons.
    for col_edge in range(grid.cols + 1):
        x_cm = grid.x_start_cm + col_edge * grid.cell_width_cm
        p0 = _pixel(_point(workspace, grid, x_cm, grid.y_start_cm, image_size))
        p1 = _pixel(_point(workspace, grid, x_cm, grid.y_end_cm, image_size))
        cv2.line(frame, p0, p1, GRID_COLOR if calibrated else WARN_COLOR,
                 1, cv2.LINE_AA)
    for row_edge in range(grid.rows + 1):
        y_cm = grid.y_start_cm + row_edge * grid.cell_height_cm
        p0 = _pixel(_point(workspace, grid, grid.x_start_cm, y_cm, image_size))
        p1 = _pixel(_point(workspace, grid, grid.x_end_cm, y_cm, image_size))
        cv2.line(frame, p0, p1, GRID_COLOR if calibrated else WARN_COLOR,
                 1, cv2.LINE_AA)

    # Label only when the projected cells are large enough to remain readable.
    first = workspace.cell_polygon(1, 1, image_size)
    approx_w = np.linalg.norm(np.asarray(first[1]) - np.asarray(first[0]))
    approx_h = np.linalg.norm(np.asarray(first[3]) - np.asarray(first[0]))
    if approx_w >= 38 and approx_h >= 24:
        for row in range(1, grid.rows + 1):
            for col in range(1, grid.cols + 1):
                x_cm, y_cm = grid.cell_center_cm(col, row)
                x, y = _pixel(_point(workspace, grid, x_cm, y_cm, image_size))
                label = f"{col},{row}"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX,
                                              0.34, 1)
                at = (x - tw // 2, y + th // 2)
                cv2.putText(frame, label, at, cv2.FONT_HERSHEY_SIMPLEX, 0.34,
                            (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(frame, label, at, cv2.FONT_HERSHEY_SIMPLEX, 0.34,
                            LABEL_COLOR, 1, cv2.LINE_AA)

    cell = workspace.cell_at(hover_point, image_size) if hover_point else None
    if cell is not None:
        polygon = np.asarray(workspace.cell_polygon(*cell, image_size),
                             dtype=np.float32).round().astype(np.int32)
        cv2.polylines(frame, [polygon], True, HOVER_COLOR, 3, cv2.LINE_AA)
        x_cm, y_cm = grid.cell_center_cm(*cell)
        lines = [
            f"CELL [{cell[0]},{cell[1]}]",
            f"centre X {x_cm:.2f} cm  Y {y_cm:.2f} cm",
            f"command: G {cell[0]} {cell[1]}",
        ]
        width = min(270, frame.shape[1] - 8)
        draw_info_box(frame, lines,
                      origin=(max(4, frame.shape[1] - width - 4),
                              max(4, frame.shape[0] - 70)),
                      width=width, scale=0.40)
    return cell


def draw_grid_status(frame, grid, calibrated, rejection, correction_enabled):
    if calibrated:
        first = "MACHINE GRID: CALIBRATED"
        reason = "four-corner camera -> cm -> cell mapping"
        highlight = False
    else:
        first = "MACHINE GRID: APPROXIMATION ONLY"
        reason = rejection or "press c and click four envelope corners"
        highlight = True
    correction = "correction ON" if correction_enabled else \
        "WARNING: correction OFF; mapping between corners is approximate"
    lines = [
        first,
        f"{grid.cols}x{grid.rows} | cell {grid.cell_width_cm:g}x"
        f"{grid.cell_height_cm:g} cm | workspace "
        f"{grid.workspace_width_cm:g}x{grid.workspace_height_cm:g} cm",
        reason,
        correction,
        "keys: c calibrate | x cancel | g grid | s save | q quit",
    ]
    width = min(470, frame.shape[1] - 8)
    draw_info_box(frame, lines,
                  origin=(max(4, frame.shape[1] - width - 4), 4),
                  width=width, scale=0.38, highlight_first=highlight)


def calibration_line_color(start, end):
    """Return a clear colour for an axis-aligned screen edge.

    This deliberately classifies camera-image geometry, not physical machine
    axes: perspective may make a physically horizontal rail diagonal on screen.
    Two pixels of tolerance accommodates normal mouse-click imprecision.
    """
    dx = abs(end[0] - start[0])
    dy = abs(end[1] - start[1])
    if dy <= CALIBRATION_AXIS_TOLERANCE_PX and dx > dy:
        return CALIBRATION_HORIZONTAL
    if dx <= CALIBRATION_AXIS_TOLERANCE_PX and dy > dx:
        return CALIBRATION_VERTICAL
    return CALIBRATION_COLOR


def _draw_calibration_line(frame, start, end, thickness):
    cv2.line(frame, start, end, calibration_line_color(start, end), thickness,
             cv2.LINE_AA)


def draw_calibration(frame, points, cursor=None):
    """Draw an explicit, ordered four-corner calibration route.

    Accepted clicks are joined with straight line segments.  A line from the
    last accepted point to the cursor previews the next segment before it is
    committed, so an operator can verify the intended edge while aiming.
    """
    rounded = [(round(x), round(y)) for x, y in points]
    for start, end in zip(rounded, rounded[1:]):
        _draw_calibration_line(frame, start, end, 2)
    if len(rounded) == 4:
        # Completing the outline makes an accidental crossed/crooked route
        # obvious during the review step before it is written to disk.
        _draw_calibration_line(frame, rounded[-1], rounded[0], 2)
    elif rounded and cursor is not None:
        preview = (round(cursor[0]), round(cursor[1]))
        color = calibration_line_color(rounded[-1], preview)
        cv2.line(frame, rounded[-1], preview, color, 1, cv2.LINE_AA)
        cv2.drawMarker(frame, preview, color,
                       cv2.MARKER_TILTED_CROSS, 15, 1, cv2.LINE_AA)

    for index, (x, y) in enumerate(points):
        point = (round(x), round(y))
        cv2.drawMarker(frame, point, CALIBRATION_COLOR, cv2.MARKER_CROSS,
                       22, 3, cv2.LINE_AA)
        cv2.putText(frame, f"{index + 1}: {CORNER_NAMES[index]}",
                    (point[0] + 9, point[1] - 9),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, CALIBRATION_COLOR, 2,
                    cv2.LINE_AA)
    index = len(points)
    if index < 4:
        lines = [
            f"CALIBRATION ACTIVE — NEXT CLICK {index + 1}/4",
            f"NEXT: {CORNER_NAMES[index]}",
            "Order: 1 home/home -> 2 far-X/home-Y",
            "       3 far-X/far-Y -> 4 home-X/far-Y",
            "Cyan = horizontal | magenta = vertical | orange = diagonal.",
            "Solid lines = saved clicks; cursor line = next edge preview.",
            "Click the physical envelope corner | u undo | x cancel",
        ]
    else:
        lines = [
            "CALIBRATION REVIEW — 4/4 CORNERS SELECTED",
            "Verify the closed outline surrounds the complete machine envelope.",
            "Enter saves this map | u undo last corner | x cancel",
        ]
    draw_info_box(frame, lines, origin=(4, 4),
                  width=min(560, frame.shape[1] - 8), scale=0.40,
                  highlight_first=True)


def main():
    args = parse_args()
    if args.display_scale <= 0 or args.min_area <= 0:
        print("--display-scale and --min-area must be positive", file=sys.stderr)
        return 1

    try:
        camera_data = load_settings(args.settings)
        rig_data = load_rig_config(args.rig_config, reload=True)
        grid = MachineGrid.from_config(rig_data)
        backend, device, size = capture_settings(camera_data)
        profile = profile_from_settings(camera_data)
        sensor = sensor_from_settings(camera_data)
        capture = camera_data.get("capture") or {}
        correction = camera_data.get("correction") or {}
        enabled = bool(correction.get("enabled", True))
        interpolation = correction.get("interp", "cubic")
        if interpolation not in INTERPOLATIONS:
            raise RuntimeError(f"camera settings: correction.interp must be one of "
                               f"{tuple(INTERPOLATIONS)}, not {interpolation!r}")
        mip = bool(correction.get("mip", True))
        roi = framing_roi(camera_data)
        projection = projection_metadata(profile, capture, enabled, roi)
    except (RuntimeError, KeyError, TypeError, ValueError, SystemExit) as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        camera = open_camera(backend, size, device)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    applied, skipped = camera.apply(sensor)
    if skipped:
        print("Sensor settings unavailable: " + "; ".join(skipped))
    print(f"Camera: {camera.name}")
    print(f"Loaded camera settings: {args.settings}")
    print(f"Loaded grid config: {args.rig_config}")
    print(f"Grid: {grid.describe()}")
    print(f"Sensor settings: {len(applied)} applied")

    saved_workspace, rejection = load_workspace(args.workspace_map, grid, projection)
    if rejection:
        print(f"Grid calibration unavailable: {rejection}")
        print("Press c in the camera window, then click the four prompted corners.")
    else:
        print(f"Loaded workspace calibration: {args.workspace_map}")

    window = f"Gridded Camera Feed - {camera.name}"
    ui = {
        "hover": None,
        "calibrating": False,
        "calibration_points": [],
        "pending_points": None,
        "show_grid": True,
    }

    def on_mouse(event, x, y, _flags, state):
        point = (x / args.display_scale, y / args.display_scale)
        if event == cv2.EVENT_MOUSEMOVE:
            state["hover"] = point
        elif event == cv2.EVENT_LBUTTONDOWN and state["calibrating"]:
            if len(state["calibration_points"]) < 4:
                state["calibration_points"].append(point)

    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(window, on_mouse, ui)
    maps = None
    input_size = None
    fps = 0.0
    last = time.perf_counter()
    try:
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                print("Failed to read frame from camera.", file=sys.stderr)
                return 1

            frame = frame_orientation(frame, capture)
            if maps is None or frame.shape[1::-1] != input_size:
                maps = build_maps(profile, frame.shape[1::-1], interpolation, mip=mip,
                                  roi=roi)
                input_size = frame.shape[1::-1]

            view = undistort(frame, maps) if enabled else \
                crop_resize(frame, roi, maps.out_size, interpolation)
            image_size = view.shape[1::-1]

            if ui["pending_points"] is not None:
                try:
                    candidate = WorkspaceMap.from_grid(
                        grid, ui["pending_points"], image_size, projection
                    )
                    candidate.save(args.workspace_map)
                    saved_workspace = candidate
                    rejection = None
                    print(f"Saved workspace calibration: {args.workspace_map}")
                except (OSError, ValueError) as exc:
                    rejection = f"calibration rejected: {exc}"
                    print(rejection, file=sys.stderr)
                ui["pending_points"] = None
                ui["calibrating"] = False
                ui["calibration_points"] = []

            workspace = saved_workspace or approximate_workspace(
                grid, image_size, projection
            )
            calibrated = saved_workspace is not None

            now = time.perf_counter()
            dt, last = now - last, now
            if dt > 0:
                instant = 1.0 / dt
                fps = 0.9 * fps + 0.1 * instant if fps else instant
            detections = detect_blocks(view, color_threshold=args.color_threshold,
                                       min_area=args.min_area)
            display = view.copy() if args.no_enhance else enhance_for_display(view)
            display = draw_block_overlay(
                display, detections, ui["hover"], fps,
                "COORDS: corrected pixels + machine-grid mapping",
            )
            if ui["show_grid"]:
                draw_machine_grid(display, workspace, grid, ui["hover"], calibrated)
                draw_grid_status(display, grid, calibrated, rejection, enabled)
            if ui["calibrating"]:
                draw_calibration(display, ui["calibration_points"], ui["hover"])

            if args.display_scale != 1.0:
                shown = cv2.resize(display, None, fx=args.display_scale,
                                   fy=args.display_scale, interpolation=cv2.INTER_AREA)
            else:
                shown = display

            cv2.imshow(window, shown)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                return 0
            if key == ord("c"):
                ui["calibrating"] = True
                ui["calibration_points"] = []
                ui["pending_points"] = None
                print("Calibration started: click the four prompted envelope corners.")
            elif key == ord("x") and ui["calibrating"]:
                ui["calibrating"] = False
                ui["calibration_points"] = []
                ui["pending_points"] = None
                print("Calibration cancelled; previous saved map kept.")
            elif key == ord("u") and ui["calibrating"]:
                if ui["calibration_points"]:
                    ui["calibration_points"].pop()
                    print("Removed the most recent calibration corner.")
                else:
                    print("No calibration corner to undo.")
            elif key in (10, 13) and ui["calibrating"]:
                if len(ui["calibration_points"]) == 4:
                    ui["pending_points"] = list(ui["calibration_points"])
                    print("Saving reviewed four-corner calibration.")
                else:
                    print("Click all four named corners before saving.")
            elif key == ord("g"):
                ui["show_grid"] = not ui["show_grid"]
            elif key == ord("s"):
                image_path, data_path = save_detection_snapshot(display, detections)
                print(f"Saved {image_path} and {data_path}")
            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                return 0
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())

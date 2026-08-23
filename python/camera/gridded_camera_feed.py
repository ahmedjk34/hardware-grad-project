#!/usr/bin/env python3
"""The canonical camera feed plus the rig's physical block grid.

This uses exactly the same saved camera settings, correction, framing and block
detection as ``camera_feed.py``. Grid geometry comes from ``config/rig.json``.

The grid opens immediately as an amber, full-frame APPROXIMATION so it is
visible even before calibration. Press ``c`` and click the four complete
machine-envelope corners in the prompted order to make it real. The resulting
four-corner map is saved to ``config/workspace_map.json`` and reloaded on the
next run. Camera cells remain strictly 1-based: zero is not an image cell.
The firmware's separate build-target convention (zero on either axis for
calibration, including the ``B 0 0`` no-op) is exposed by
``rig_build_v1.py --build-target COL ROW`` and is never invented by a camera
click. A changed lens/framing setup or changed grid JSON invalidates that map
instead of silently drawing an old calibration.

Keys
----
  c       calibrate/recalibrate: click four prompted envelope corners
  Enter   save the reviewed four-corner calibration
  u       undo the most recent calibration corner
  x       cancel an in-progress calibration
  g       toggle grid overlay
  v       toggle block detection on/off
  s       save annotated frame and block detection JSON
  q/Esc   quit
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tkinter as tk
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

# This file lives below python/, so make the shared packages importable when it
# is launched from either the repository root or python/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import (  # noqa: E402
    OVERLAY_MODES,
    SETTINGS_PATH,
    STALE_FRAME_AFTER_S,
    block_hover_text,
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
from camera.snapshot_worker import SnapshotWorker  # noqa: E402
from rig.config import CONFIG_PATH, load as load_rig_config  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from rig.workspace import CORNER_NAMES, WORKSPACE_MAP_PATH, WorkspaceMap  # noqa: E402
from vision.block_detector import detect_blocks  # noqa: E402
from vision.analysis_worker import AnalysisWorker  # noqa: E402
from vision.camera_source import LatestFramePump, open_camera  # noqa: E402
from vision.fisheye import INTERPOLATIONS, build_maps, undistort  # noqa: E402
from vision.overlays import (  # noqa: E402
    GRID_COLOR,
    HOVER_COLOR,
    LABEL_COLOR,
    WARN_COLOR,
)
from vision.performance import RateMeter, StageTimings  # noqa: E402
from camera.tk_camera_window import TkCameraWindow  # noqa: E402


ENVELOPE_COLOR = (170, 170, 170)
CALIBRATION_COLOR = (255, 180, 30)       # orange: diagonal
CALIBRATION_HORIZONTAL = (255, 255, 0)   # cyan: screen-horizontal
CALIBRATION_VERTICAL = (255, 0, 255)     # magenta: screen-vertical
CALIBRATION_AXIS_TOLERANCE_PX = 2
_GRID_GEOMETRY_CACHE = {}


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
    parser.add_argument("--enhance", action="store_true",
                        help="enable costly software contrast/sharpness enhancement")
    parser.add_argument("--no-enhance", action="store_false", dest="enhance",
                        help=argparse.SUPPRESS)
    parser.add_argument("--overlay", choices=OVERLAY_MODES, default="geometry")
    parser.add_argument("--analysis-hz", type=float, default=10.0)
    parser.add_argument("--opencv-threads", type=int, default=2)
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


def _grid_geometry(workspace, grid, image_size):
    """Cache static projected grid geometry; only hover changes per frame."""
    key = (
        image_size, tuple(workspace.corners), grid.cols, grid.rows,
        grid.cell_width_cm, grid.cell_height_cm, grid.workspace_width_cm,
        grid.workspace_height_cm, grid.trim_x_cm, grid.trim_y_cm,
    )
    cached = _GRID_GEOMETRY_CACHE.get(key)
    if cached is not None:
        return cached

    envelope = np.asarray([
        workspace.pixel_at(0.0, 0.0, image_size),
        workspace.pixel_at(1.0, 0.0, image_size),
        workspace.pixel_at(1.0, 1.0, image_size),
        workspace.pixel_at(0.0, 1.0, image_size),
    ], dtype=np.float32).round().astype(np.int32)

    lines = []
    for col_edge in range(grid.cols + 1):
        x_cm = grid.x_start_cm + col_edge * grid.cell_width_cm
        p0 = _pixel(_point(workspace, grid, x_cm, grid.y_start_cm, image_size))
        p1 = _pixel(_point(workspace, grid, x_cm, grid.y_end_cm, image_size))
        lines.append((p0, p1))
    for row_edge in range(grid.rows + 1):
        y_cm = grid.y_start_cm + row_edge * grid.cell_height_cm
        p0 = _pixel(_point(workspace, grid, grid.x_start_cm, y_cm, image_size))
        p1 = _pixel(_point(workspace, grid, grid.x_end_cm, y_cm, image_size))
        lines.append((p0, p1))

    labels = []
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
                labels.append((label, at))

    cached = (envelope, tuple(lines), tuple(labels))
    if len(_GRID_GEOMETRY_CACHE) >= 16:
        _GRID_GEOMETRY_CACHE.pop(next(iter(_GRID_GEOMETRY_CACHE)))
    _GRID_GEOMETRY_CACHE[key] = cached
    return cached


def draw_machine_grid(frame, workspace, grid, hover_point, calibrated, *, detail=False):
    """Draw cached static grid geometry and the dynamic hovered cell."""
    image_size = frame.shape[1::-1]
    envelope, lines, labels = _grid_geometry(workspace, grid, image_size)
    cv2.polylines(frame, [envelope], True, ENVELOPE_COLOR, 2, cv2.LINE_AA)
    color = GRID_COLOR if calibrated else WARN_COLOR
    for p0, p1 in lines:
        cv2.line(frame, p0, p1, color, 1, cv2.LINE_AA)
    if detail:
        for label, at in labels:
            cv2.putText(frame, label, at, cv2.FONT_HERSHEY_SIMPLEX, 0.34,
                        (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(frame, label, at, cv2.FONT_HERSHEY_SIMPLEX, 0.34,
                        LABEL_COLOR, 1, cv2.LINE_AA)

    cell = workspace.cell_at(hover_point, image_size) if hover_point else None
    if cell is not None:
        polygon = np.asarray(workspace.cell_polygon(*cell, image_size),
                             dtype=np.float32).round().astype(np.int32)
        cv2.polylines(frame, [polygon], True, HOVER_COLOR, 3, cv2.LINE_AA)
    return cell


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


def draw_calibration(frame, points, cursor=None, *, detail=False):
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
        label = (f"{index + 1}: {CORNER_NAMES[index]}" if detail
                 else str(index + 1))
        cv2.putText(frame, label,
                    (point[0] + 9, point[1] - 9),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, CALIBRATION_COLOR, 2,
                    cv2.LINE_AA)
def main():
    args = parse_args()
    if (args.display_scale <= 0 or args.min_area <= 0 or args.analysis_hz <= 0
            or args.opencv_threads <= 0):
        print("display/min-area/analysis-hz/opencv-threads values must be positive",
              file=sys.stderr)
        return 1
    cv2.setNumThreads(args.opencv_threads)

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
        "overlay": args.overlay,
        "detect_enabled": True,
        "message": "ready",
    }

    def on_mouse(event, point):
        if point is None:
            return
        if event == "move":
            ui["hover"] = point
        elif event == "click" and ui["calibrating"]:
            if len(ui["calibration_points"]) < 4:
                ui["calibration_points"].append(point)

    try:
        window = TkCameraWindow(
            f"Gridded Camera Feed - {camera.name}", size,
            display_scale=args.display_scale, mouse_callback=on_mouse,
            buttons=(("Overlay (o)", "o"), ("Calibrate (c)", "c"),
                     ("Undo (u)", "u"),
                     ("Save (s)", "s"), ("Grid (g)", "g"),
                     ("Detect (v)", "v"),
                     ("Quit (q)", "q")),
        )
    except (tk.TclError, cv2.error) as exc:
        print(f"Cannot open the camera UI: {exc}", file=sys.stderr)
        camera.release()
        return 1

    frame_pump = LatestFramePump(camera)
    analysis = AnalysisWorker(detect_blocks, max_hz=args.analysis_hz)
    snapshots = SnapshotWorker(save_detection_snapshot)
    frame_pump.start()
    analysis.start()
    maps = None
    input_size = None
    map_generation = 0
    last_sequence = 0
    last_display = None
    image_size = None
    workspace = None
    calibrated = False
    detections = ()
    capture_rate, preview_rate = RateMeter(), RateMeter()
    timings = StageTimings()
    snapshot_count = 0

    def status_lines(snapshot, result):
        age = snapshot.age_s()
        age_text = "waiting" if age is None else f"{age * 1000:.0f} ms"
        camera_state = ("WAITING" if age is None else
                        "STALE" if age >= STALE_FRAME_AFTER_S else "LIVE")
        result_age = result.age_s()
        analysis_text = ("waiting" if result.completed_at is None else
                         f"{result.duration_s * 1000:.1f} ms / "
                         f"age {result_age * 1000:.0f} ms")
        cell = (workspace.cell_at(ui["hover"], image_size)
                if workspace is not None and image_size and ui["hover"] else None)
        calibration_text = (
            ("REVIEW 4/4 — Enter saves" if len(ui["calibration_points"]) == 4 else
             f"active {len(ui['calibration_points'])}/4 — next: "
             f"{CORNER_NAMES[len(ui['calibration_points'])]}")
            if ui["calibrating"] else
            ("CALIBRATED" if calibrated else
             f"APPROXIMATION ONLY ({rejection or 'press c to calibrate'})"))
        size_text = (f"{image_size[0]}x{image_size[1]}" if image_size else "waiting")
        return [
            f"Camera: {camera.name} | {camera_state} | capture "
            f"{capture_rate.rate:5.1f} fps | age {age_text}",
            f"Feed: {size_text} | preview {preview_rate.rate:5.1f} fps | overlay {ui['overlay']}",
            f"Analysis: {'OFF' if not ui['detect_enabled'] else f'{result.rate_hz:4.1f} Hz'} | "
            f"seq {result.source_sequence} | {analysis_text} | blocks {len(detections)} | "
            f"replaced {result.replaced_count} | duplicate {result.duplicate_count}",
            f"Grid: {grid.cols}x{grid.rows} | {calibration_text} | "
            f"hover {f'[{cell[0]},{cell[1]}]' if cell else 'none'}",
            block_hover_text(detections, ui["hover"]),
            f"Stages: remap {timings.ms.get('remap', 0):.1f} ms | "
            f"overlay {timings.ms.get('overlay', 0):.1f} ms | "
            f"grid {timings.ms.get('grid', 0):.1f} ms | "
            f"display {timings.ms.get('display', 0):.1f} ms",
            f"Status: {result.error or snapshot.error or ui['message']}",
            "o overlay | c calibrate | Enter save | u undo | x cancel | g grid | v detect | s snapshot | q quit",
        ]

    def handle_key(key):
        if key in (ord("q"), 27):
            return False
        if key == ord("o"):
            ui["overlay"] = OVERLAY_MODES[
                (OVERLAY_MODES.index(ui["overlay"]) + 1) % len(OVERLAY_MODES)]
            ui["message"] = f"overlay: {ui['overlay']}"
        elif key == ord("c"):
            ui["calibrating"] = True
            ui["calibration_points"] = []
            ui["pending_points"] = None
            ui["message"] = "click the four prompted envelope corners"
        elif key == ord("x") and ui["calibrating"]:
            ui["calibrating"] = False
            ui["calibration_points"] = []
            ui["pending_points"] = None
            ui["message"] = "calibration cancelled; previous map kept"
        elif key == ord("u") and ui["calibrating"]:
            if ui["calibration_points"]:
                ui["calibration_points"].pop()
                ui["message"] = "removed the most recent corner"
            else:
                ui["message"] = "no calibration corner to undo"
        elif key in (10, 13) and ui["calibrating"]:
            if len(ui["calibration_points"]) == 4:
                ui["pending_points"] = list(ui["calibration_points"])
                ui["message"] = "saving reviewed calibration"
            else:
                ui["message"] = "click all four corners before saving"
        elif key == ord("g"):
            ui["show_grid"] = not ui["show_grid"]
        elif key == ord("v"):
            ui["detect_enabled"] = not ui["detect_enabled"]
            ui["message"] = f"block detection {'on' if ui['detect_enabled'] else 'off'}"
        elif key == ord("s"):
            if last_display is None:
                ui["message"] = "no frame is available to save"
            elif snapshots.submit(last_display.copy(), tuple(detections)):
                ui["message"] = "saving snapshot in background"
            else:
                ui["message"] = "snapshot writer busy; try again shortly"
        return True

    try:
        while True:
            snapshot = frame_pump.snapshot()
            result = analysis.snapshot()
            if not ui["detect_enabled"]:
                detections = ()
            elif result.is_current(map_generation):
                detections = result.detections
            saved = snapshots.snapshot()
            if saved.completed_count != snapshot_count:
                snapshot_count = saved.completed_count
                if saved.error:
                    ui["message"] = saved.error
                    print(saved.error, file=sys.stderr)
                elif saved.result:
                    ui["message"] = f"saved {saved.result[0].name} and {saved.result[1].name}"
                    print(f"Saved {saved.result[0]} and {saved.result[1]}")

            if snapshot.frame is None or snapshot.sequence == last_sequence:
                window.pump(status_lines(snapshot, result))
                key = window.poll_key()
                if (key >= 0 and not handle_key(key)) or window.closed:
                    return 0
                continue

            last_sequence = snapshot.sequence
            capture_rate.tick()
            frame = snapshot.frame
            frame = frame_orientation(frame, capture)
            if maps is None or frame.shape[1::-1] != input_size:
                maps = build_maps(profile, frame.shape[1::-1], interpolation, mip=mip,
                                  roi=roi)
                input_size = frame.shape[1::-1]
                map_generation += 1

            started = time.perf_counter()
            view = undistort(frame, maps) if enabled else \
                crop_resize(frame, roi, maps.out_size, interpolation)
            timings.observe("remap", time.perf_counter() - started)
            image_size = view.shape[1::-1]

            if ui["pending_points"] is not None:
                try:
                    candidate = WorkspaceMap.from_grid(
                        grid, ui["pending_points"], image_size, projection
                    )
                    candidate.save(args.workspace_map)
                    saved_workspace = candidate
                    rejection = None
                    ui["message"] = "calibration saved"
                    print(f"Saved workspace calibration: {args.workspace_map}")
                except (OSError, ValueError) as exc:
                    rejection = f"calibration rejected: {exc}"
                    ui["message"] = rejection
                    print(rejection, file=sys.stderr)
                ui["pending_points"] = None
                ui["calibrating"] = False
                ui["calibration_points"] = []

            workspace = saved_workspace or approximate_workspace(
                grid, image_size, projection
            )
            calibrated = saved_workspace is not None
            view.flags.writeable = False
            if ui["detect_enabled"]:
                analysis.submit(view, snapshot.sequence, map_generation,
                                color_threshold=args.color_threshold,
                                min_area=args.min_area)
            display = enhance_for_display(view) if args.enhance else view.copy()
            started = time.perf_counter()
            draw_block_overlay(
                display, detections, ui["hover"], None,
                "COORDS: corrected pixels + machine-grid mapping",
                show_info=False, mode=ui["overlay"],
            )
            timings.observe("overlay", time.perf_counter() - started)
            started = time.perf_counter()
            if ui["show_grid"] and ui["overlay"] != "off":
                draw_machine_grid(
                    display, workspace, grid, ui["hover"], calibrated,
                    detail=ui["overlay"] == "detail")
            if ui["calibrating"]:
                draw_calibration(
                    display, ui["calibration_points"], ui["hover"],
                    detail=ui["overlay"] == "detail")
            timings.observe("grid", time.perf_counter() - started)
            last_display = display
            started = time.perf_counter()
            window.show(display, status_lines(snapshot, result))
            timings.observe("display", time.perf_counter() - started)
            preview_rate.tick()
            key = window.poll_key()
            if (key >= 0 and not handle_key(key)) or window.closed:
                return 0
    finally:
        analysis.stop()
        snapshots.stop(finish=True)
        if frame_pump.stop():
            camera.release()
        window.close()


if __name__ == "__main__":
    raise SystemExit(main())

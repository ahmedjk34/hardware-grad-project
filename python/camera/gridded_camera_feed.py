#!/usr/bin/env python3
"""The canonical camera feed plus the rig's physical block grid.

This uses exactly the same saved camera settings, correction, framing and block
detection as ``camera_feed.py``. Grid geometry comes from ``config/rig.json``.

The grid opens immediately as an amber, full-frame APPROXIMATION so it is
visible even before calibration. Press ``c`` and click the four real holder-
motion corners named by ``rig.workspace.CORNER_NAMES``. The resulting map is
saved to ``config/workspace_map.json`` and reloaded on the next run.

Coordinates span col ``0..9`` and row ``0..5``. ``[0,0]`` is holder home;
``[col,0]``/``[0,row]`` are axis-only targets. Positive cells are separated
2.2x7.5 cm block footprints: each starts after a 0.5 cm gap and repeats at
2.7x8.0 cm pitch. A changed lens/framing setup or changed grid JSON invalidates
the saved map instead of silently drawing old geometry.

There is a second way to calibrate. Press ``p`` to overlay the printed
two-colour sheet (``vision/color_grid.py``) and ``k`` to derive the same four
corners from it and save them. The sheet measures a hundred printed cell edges
instead of asking anyone to aim at an invisible rectangle, so prefer it when
the sheet is in frame; the four clicks remain for when it is not.

Keys
----
  c       calibrate/recalibrate: click the four prompted corners
  Enter   save the reviewed four-corner calibration
  u       undo the most recent calibration corner
  x       cancel an in-progress calibration
  p       toggle the printed colour-grid overlay
  k       calibrate from the printed colour grid and save
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
from vision.color_grid import (  # noqa: E402
    DEFAULT_HOME_CONVENTION,
    HOME_CONVENTIONS,
    ColorGridError,
    ColorGridSpec,
    detect_color_grid,
)
from vision.color_grid_overlay import (  # noqa: E402
    draw_color_grid,
    draw_workspace_corners,
    status_text as paper_status_text,
)
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

# The printed sheet is re-found on a worker thread while its overlay is on.
# 3 Hz is far more than an operator sliding a sheet around needs, and it keeps
# the cost off the preview even on the Pi. The overlay runs at a reduced width
# for that reason; the calibration itself does not.
PAPER_GRID_HZ = 3.0
PAPER_OVERLAY_WIDTH = 1024


def analyze_paper_grid(frame, spec, process_width=PAPER_OVERLAY_WIDTH):
    """AnalysisWorker adapter for the printed sheet.

    Returns one ``(calibration, error)`` pair. AnalysisWorker turns whatever an
    analyzer returns into a tuple of detections, and it swallows exceptions into
    a generic message — so the specific "move the sheet" sentence is returned as
    a value instead of raised, and survives the trip back to the UI intact.
    """
    try:
        return ((detect_color_grid(frame, spec, process_width=process_width), None),)
    except ColorGridError as exc:
        return ((None, str(exc)),)


class PaperGridTracker:
    """Latest printed-sheet detection, found off the preview thread.

    The worker is always running but is only fed while the overlay is on, so a
    session that never presses ``p`` pays nothing but an idle thread.
    """

    def __init__(self, spec, *, max_hz=PAPER_GRID_HZ,
                 process_width=PAPER_OVERLAY_WIDTH):
        self.spec = spec
        self.enabled = False
        self.process_width = process_width
        self._worker = AnalysisWorker(analyze_paper_grid, max_hz=max_hz,
                                      name="paper-grid")
        self._calibration = None
        self._error = "overlay off"

    def start(self):
        self._worker.start()

    def stop(self):
        self._worker.stop()

    def toggle(self):
        self.enabled = not self.enabled
        if not self.enabled:
            self._calibration, self._error = None, "overlay off"
        else:
            self._error = "looking for the sheet"
        return self.enabled

    def submit(self, frame, sequence, generation):
        if self.enabled:
            self._worker.submit(frame, sequence, generation, spec=self.spec,
                                process_width=self.process_width)

    def poll(self, generation):
        """Adopt the newest result that belongs to the current map geometry."""
        if not self.enabled:
            return
        snapshot = self._worker.snapshot()
        if not snapshot.is_current(generation) or not snapshot.detections:
            if snapshot.error:
                self._calibration, self._error = None, snapshot.error
            return
        self._calibration, self._error = snapshot.detections[0]

    @property
    def calibration(self):
        return self._calibration

    @property
    def error(self):
        return self._error

    def status(self):
        return paper_status_text(self._calibration, self._error)


def paper_workspace_map(view, spec, grid, projection, convention):
    """Turn the printed sheet in ``view`` into a saveable :class:`WorkspaceMap`.

    Detection runs at full resolution here: a calibration is written once and
    then lived with, so the extra tens of milliseconds cost nothing and the
    extra precision is the whole point. Raises ``ColorGridError`` when the sheet
    is not usable and ``ValueError`` when the corners it implies fall outside
    the frame — both are sentences worth showing an operator verbatim.
    """
    calibration = detect_color_grid(view, spec, process_width=0)
    corners = calibration.workspace_corners(grid, convention)
    workspace = WorkspaceMap.from_grid(grid, corners, view.shape[1::-1], projection)
    return workspace, calibration


def draw_paper_grid(frame, tracker, hover, grid, convention, *, detail=False):
    """Draw the printed-sheet overlay, plus the envelope it would calibrate to."""
    calibration = tracker.calibration
    if calibration is None:
        return None
    hovered = draw_color_grid(frame, calibration, hover=hover, labels=detail,
                              shade=0.30)
    try:
        draw_workspace_corners(frame, calibration.workspace_corners(grid, convention))
    except (ColorGridError, ValueError):
        pass
    return hovered


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
    parser.add_argument("--home-convention", choices=HOME_CONVENTIONS,
                        default=DEFAULT_HOME_CONVENTION,
                        help="where the machine origin sits on the printed sheet "
                             f"(default: {DEFAULT_HOME_CONVENTION})")
    parser.add_argument("--paper-hz", type=float, default=PAPER_GRID_HZ,
                        help=f"printed-sheet detection rate (default: {PAPER_GRID_HZ})")
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


def _point(workspace, g, x_cm, y_cm, image_size):
    return workspace.pixel_at(x_cm / g.workspace_width_cm,
                              y_cm / g.workspace_height_cm, image_size)


def _pixel(point):
    return tuple(round(value) for value in point)


def _grid_geometry(workspace, image_size):
    """Cache static projected grid geometry; only hover changes per frame.

    Every cm value comes from ``workspace.mapped_grid`` so a loaded map uses
    exactly the geometry embedded when its corners were clicked.
    """
    g = workspace.mapped_grid
    key = (
        image_size, tuple(workspace.corners), g.cols, g.rows,
        g.block_width_cm, g.block_length_cm, g.gap_x_cm, g.gap_y_cm,
        g.workspace_width_cm, g.workspace_height_cm,
        g.trim_x_cm, g.trim_y_cm,
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

    # Draw the actual block rectangles. The space between them is the physical
    # 0.5 cm gap; it is intentionally not swallowed into a pitch-sized cell.
    lines = []
    for row in range(1, g.rows + 1):
        for col in range(1, g.cols + 1):
            polygon = [_pixel(point) for point in
                       workspace.cell_polygon(col, row, image_size)]
            lines.extend(zip(polygon, polygon[1:] + polygon[:1]))

    def _add_label(labels, text, x, y):
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.34, 1)
        labels.append((text, (x - tw // 2, y + th // 2)))

    labels = []
    first = workspace.cell_polygon(1, 1, image_size)
    approx_w = np.linalg.norm(np.asarray(first[1]) - np.asarray(first[0]))
    approx_h = np.linalg.norm(np.asarray(first[3]) - np.asarray(first[0]))
    show_labels = approx_w >= 38 and approx_h >= 24
    if show_labels:
        for row in range(1, g.rows + 1):
            for col in range(1, g.cols + 1):
                x_cm, y_cm = g.cell_center_cm(col, row)
                x, y = _pixel(_point(workspace, g, x_cm, y_cm, image_size))
                _add_label(labels, f"{col},{row}", x, y)

    # Axis-only targets are centred on the real zero axes. Their polygons may
    # extend outside the holder-motion envelope rather than being shifted into
    # a fabricated extra pitch.
    extra_polygons = []
    for axis, count, label_fmt in (("col", g.cols, "{},0"),
                                   ("row", g.rows, "0,{}")):
        for index in range(1, count + 1):
            polygon = np.asarray(
                workspace.axis_lane_polygon(axis, index, image_size),
                dtype=np.float32).round().astype(np.int32)
            extra_polygons.append(polygon)
            if show_labels:
                x, y = polygon.mean(axis=0).astype(int)
                _add_label(labels, label_fmt.format(index), x, y)
    origin_polygon = np.asarray(
        workspace.origin_polygon(image_size),
        dtype=np.float32).round().astype(np.int32)
    extra_polygons.append(origin_polygon)
    if show_labels:
        x, y = origin_polygon.mean(axis=0).astype(int)
        _add_label(labels, "0,0", x, y)

    cached = (envelope, tuple(lines), tuple(labels), tuple(extra_polygons))
    if len(_GRID_GEOMETRY_CACHE) >= 16:
        _GRID_GEOMETRY_CACHE.pop(next(iter(_GRID_GEOMETRY_CACHE)))
    _GRID_GEOMETRY_CACHE[key] = cached
    return cached


def draw_machine_grid(frame, workspace, hover_point, calibrated, *, detail=False):
    """Draw cached static grid geometry and the dynamic hovered cell.

    Positive cells are their actual separated block rectangles. Axis-only
    target footprints are centred on row/col 0, and [0,0] marks holder home.
    All geometry comes from ``workspace.mapped_grid``.
    """
    image_size = frame.shape[1::-1]
    envelope, lines, labels, extra_polygons = _grid_geometry(workspace, image_size)
    cv2.polylines(frame, [envelope], True, ENVELOPE_COLOR, 2, cv2.LINE_AA)
    color = GRID_COLOR if calibrated else WARN_COLOR
    for p0, p1 in lines:
        cv2.line(frame, p0, p1, color, 1, cv2.LINE_AA)
    for polygon in extra_polygons:
        cv2.polylines(frame, [polygon], True, color, 1, cv2.LINE_AA)
    if detail:
        for label, at in labels:
            cv2.putText(frame, label, at, cv2.FONT_HERSHEY_SIMPLEX, 0.34,
                        (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(frame, label, at, cv2.FONT_HERSHEY_SIMPLEX, 0.34,
                        LABEL_COLOR, 1, cv2.LINE_AA)

    cell = workspace.cell_at(hover_point, image_size) if hover_point else None
    if cell is None and hover_point and workspace.has_physical_grid:
        cell = workspace.axis_lane_at(hover_point, image_size)
    if cell is not None:
        polygon = np.asarray(workspace.target_polygon(*cell, image_size),
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
            or args.opencv_threads <= 0 or args.paper_hz <= 0):
        print("display/min-area/analysis-hz/paper-hz/opencv-threads values must "
              "be positive", file=sys.stderr)
        return 1
    cv2.setNumThreads(args.opencv_threads)

    try:
        camera_data = load_settings(args.settings)
        rig_data = load_rig_config(args.rig_config, reload=True)
        grid = MachineGrid.from_config(rig_data)
        paper_spec = ColorGridSpec.from_config(rig_data)
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
        "paper_calibrate": False,
        "message": "ready",
    }
    paper = PaperGridTracker(paper_spec, max_hz=args.paper_hz)

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
                     ("Paper grid (p)", "p"), ("Paper calib (k)", "k"),
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
    paper.start()
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
            f"{paper.status()} | home {args.home_convention} | k calibrates from it",
            block_hover_text(detections, ui["hover"]),
            f"Stages: remap {timings.ms.get('remap', 0):.1f} ms | "
            f"overlay {timings.ms.get('overlay', 0):.1f} ms | "
            f"grid {timings.ms.get('grid', 0):.1f} ms | "
            f"display {timings.ms.get('display', 0):.1f} ms",
            f"Status: {result.error or snapshot.error or ui['message']}",
            "o overlay | c calibrate | Enter save | u undo | x cancel | g grid | v detect",
            "p paper overlay | k paper calibrate | s snapshot | q quit",
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
            ui["message"] = "click the four prompted corners"
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
        elif key == ord("p"):
            ui["message"] = ("printed-sheet overlay on" if paper.toggle()
                             else "printed-sheet overlay off")
        elif key == ord("k"):
            # Deferred to the frame loop, which is the only place that holds a
            # corrected view; the key handler runs between frames.
            ui["paper_calibrate"] = True
            ui["message"] = "calibrating from the printed sheet"
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

            if ui["paper_calibrate"]:
                ui["paper_calibrate"] = False
                try:
                    candidate, found = paper_workspace_map(
                        view, paper_spec, grid, projection, args.home_convention)
                    candidate.save(args.workspace_map)
                    saved_workspace = candidate
                    rejection = None
                    ui["message"] = f"calibrated from the sheet: {found.describe()}"
                    print(f"Saved workspace calibration from the printed sheet: "
                          f"{args.workspace_map}")
                    print(f"  {found.describe()} "
                          f"({args.home_convention} home convention)")
                except (ColorGridError, OSError, ValueError) as exc:
                    rejection = f"sheet calibration rejected: {exc}"
                    ui["message"] = rejection
                    print(rejection, file=sys.stderr)

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
            paper.submit(view, snapshot.sequence, map_generation)
            paper.poll(map_generation)
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
                    display, workspace, ui["hover"], calibrated,
                    detail=ui["overlay"] == "detail")
            if paper.enabled:
                draw_paper_grid(display, paper, ui["hover"], grid,
                                args.home_convention,
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
        paper.stop()
        snapshots.stop(finish=True)
        if frame_pump.stop():
            camera.release()
        window.close()


if __name__ == "__main__":
    raise SystemExit(main())

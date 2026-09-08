#!/usr/bin/env python3
"""The canonical camera feed plus the rig's physical block grid.

This uses exactly the same saved camera settings, correction, framing and block
detection as ``camera_feed.py``. Grid geometry comes from ``config/rig.json``.

The grid opens immediately as an amber, full-frame APPROXIMATION so it is
visible even before calibration. Press ``c`` and click the four real holder-
motion corners named by ``rig.workspace.CORNER_NAMES``. The resulting map is
saved to ``config/workspace_map.json`` and reloaded on the next run.

Coordinates span `0..9` x `0..5` in vertical mode and `0..3` x `0..15` in
horizontal. ``[0,0]`` is holder home; ``[col,0]``/``[0,row]`` are axis-only
targets. The selected mode supplies its own block footprint and pitch. A changed
lens/framing setup or changed grid JSON invalidates that mode's saved map
instead of silently drawing old geometry.

There are two printed-sheet routes.  Press ``p`` to overlay the two-colour
sheet (``vision/color_grid.py``) and ``k`` to calibrate from one complete
frame.  When the gantry hides cells, press ``e`` to start **Evidence-Assisted
Printed-Grid Calibration**, accept several unobstructed portions with Space,
then press ``k`` only once its coverage report says READY TO SAVE.  The latter
uses only whole physical cells and virtualises missing *interior* cells after
the multi-frame fit has passed its edge/corner safety gates.

Keys
----
  c       calibrate/recalibrate: click the four prompted corners
  Enter   save the reviewed four-corner calibration
  u       undo the most recent calibration corner
  x       cancel an in-progress calibration
  p       toggle the printed colour-grid overlay
  , / .   select the previous / next detected printed-grid window
  k       save a complete-sheet calibration, or a ready evidence session
  e       start/replace an evidence session for gantry-occluded sheets
  Space   accept the current frame as evidence
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
    colour_from_settings,
    frame_orientation,
    framing_roi,
    load_settings,
    profile_from_settings,
    save_detection_snapshot,
    sensor_from_settings,
)
from camera.snapshot_worker import SnapshotWorker  # noqa: E402
from rig.config import CONFIG_PATH, GRID_MODES, load as load_rig_config  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from rig.workspace import CORNER_NAMES, WORKSPACE_MAP_PATH, WorkspaceMap  # noqa: E402
from vision.block_outline import detect_aligned_blocks  # noqa: E402
from vision.analysis_worker import AnalysisWorker  # noqa: E402
from vision.color_grid import (  # noqa: E402
    DEFAULT_EDGE_MARGIN,
    DEFAULT_HOME_CONVENTION,
    HOME_CONVENTIONS,
    ColorGridError,
    ColorGridSpec,
)
from vision.combined_grid import (  # noqa: E402
    PrintedGridEvidence,
    detect_printed_grid,
    detect_printed_grids,
)
from vision.cluster_grid import (  # noqa: E402
    detect_cluster_grid,
    detect_cluster_grids,
)
from vision.color_grid_overlay import (  # noqa: E402
    draw_candidates,
    draw_color_grid,
    draw_grid_alternatives,
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

# Which printed-sheet detector `p` (overlay) and `k` (calibrate) use.
#   "color"   - the shipped green/magenta sheet + A2 combined target
#               (vision/combined_grid.py)
#   "cluster" - the black-bordered 3x3 cluster sheet
#               (vision/cluster_grid.py, docs/cluster-calibration-grid.md);
#               geometry from the printed border by edge detection.
# Each entry is (multi-window fn, single-window fn); both share the
# ColorGridCalibration output contract so the overlay and the map writer do not
# care which one produced a result.
_PAPER_DETECTORS = {
    "color": (detect_printed_grids, detect_printed_grid),
    "cluster": (detect_cluster_grids, detect_cluster_grid),
}
_paper_detector_name = "color"


def set_paper_detector(name):
    """Select the printed-sheet detector by name (see ``_PAPER_DETECTORS``)."""
    if name not in _PAPER_DETECTORS:
        raise ValueError(f"unknown paper detector {name!r}; choose from "
                         f"{', '.join(sorted(_PAPER_DETECTORS))}")
    global _paper_detector_name
    _paper_detector_name = name


def paper_detector_name():
    """The currently selected printed-sheet detector name."""
    return _paper_detector_name


def analyze_paper_grid(frame, spec, process_width=PAPER_OVERLAY_WIDTH,
                       edge_margin=DEFAULT_EDGE_MARGIN,
                       page_plane_min=None, min_saturation=None):
    """AnalysisWorker adapter for the printed sheet.

    Returns one ``(calibration, error)`` pair. AnalysisWorker turns whatever an
    analyzer returns into a tuple of detections, and it swallows exceptions into
    a generic message — so the specific "move the sheet" sentence is returned as
    a value instead of raised, and survives the trip back to the UI intact.
    """
    multi, _single = _PAPER_DETECTORS[_paper_detector_name]
    kwargs = {}
    if _paper_detector_name == "color":
        if page_plane_min is not None:
            kwargs["page_plane_min"] = page_plane_min
        if min_saturation is not None:
            kwargs["min_saturation"] = min_saturation
    try:
        return ((multi(frame, spec, process_width=process_width,
                       edge_margin=edge_margin, **kwargs), None),)
    except ColorGridError as exc:
        return ((None, exc),)


class PaperGridTracker:
    """Latest printed-sheet detection, found off the preview thread.

    The worker is always running but is only fed while the overlay is on, so a
    session that never presses ``p`` pays nothing but an idle thread.
    """

    def __init__(self, spec, *, max_hz=PAPER_GRID_HZ,
                 process_width=PAPER_OVERLAY_WIDTH,
                 edge_margin=DEFAULT_EDGE_MARGIN,
                 page_plane_min=None, min_saturation=None):
        self.spec = spec
        self.enabled = False
        self.process_width = process_width
        self.edge_margin = edge_margin
        self.page_plane_min = page_plane_min
        self.min_saturation = min_saturation
        self._worker = AnalysisWorker(analyze_paper_grid, max_hz=max_hz,
                                      name="paper-grid")
        self._calibration = None
        self._calibrations = ()
        self._selection = 0
        self._error = "overlay off"
        self._failure = None

    def start(self):
        self._worker.start()

    def stop(self):
        self._worker.stop()

    def toggle(self):
        self.enabled = not self.enabled
        if not self.enabled:
            self._calibration, self._calibrations = None, ()
            self._error, self._failure = "overlay off", None
        else:
            self._error = "looking for the sheet"
        return self.enabled

    def set_spec(self, spec):
        """Change layouts without allowing an old worker result to leak across."""
        self.spec = spec
        self._calibration, self._calibrations = None, ()
        self._selection = 0
        self._failure = None
        self._error = "looking for the sheet" if self.enabled else "overlay off"

    def submit(self, frame, sequence, generation):
        if self.enabled:
            self._worker.submit(frame, sequence, generation, spec=self.spec,
                                process_width=self.process_width,
                                edge_margin=self.edge_margin,
                                page_plane_min=self.page_plane_min,
                                min_saturation=self.min_saturation)

    def poll(self, generation):
        """Adopt the newest result that belongs to the current map geometry."""
        if not self.enabled:
            return
        snapshot = self._worker.snapshot()
        if not snapshot.is_current(generation) or not snapshot.detections:
            if snapshot.error:
                self._calibration, self._error = None, snapshot.error
                self._failure = None
            return
        calibrations, failure = snapshot.detections[0]
        self._calibrations = tuple(calibrations or ())
        if self._selection < len(self._calibrations):
            self._calibration = self._calibrations[self._selection]
            self._error = None
        elif self._calibrations:
            self._calibration = None
            self._error = (f"selected grid {self._selection + 1} is temporarily "
                           f"unavailable; {len(self._calibrations)} detected")
        else:
            self._calibration = None
        self._failure = None if self._calibration is not None else failure
        if failure is not None:
            self._error = str(failure)

    @property
    def calibration(self):
        return self._calibration

    @property
    def calibrations(self):
        return self._calibrations

    @property
    def selection(self):
        return self._selection

    def cycle(self, delta):
        """Select another overlapping grid; returns whether selection changed."""
        if not self._calibrations:
            return False
        previous = self._selection
        self._selection = (self._selection + delta) % len(self._calibrations)
        self._calibration = self._calibrations[self._selection]
        self._error = None
        return self._selection != previous

    @property
    def error(self):
        return self._error

    @property
    def failure(self):
        """The last :class:`ColorGridError`, for drawing what it did find."""
        return self._failure

    def status(self):
        return paper_status_text(self._calibration, self._error)


def paper_workspace_map(view, spec, grid, projection, convention, window_index=0):
    """Turn the printed sheet in ``view`` into a saveable :class:`WorkspaceMap`.

    Detection runs at full resolution here: a calibration is written once and
    then lived with, so the extra tens of milliseconds cost nothing and the
    extra precision is the whole point. Raises ``ColorGridError`` when the sheet
    is not usable and ``ValueError`` when the corners it implies fall outside
    the frame — both are sentences worth showing an operator verbatim.
    """
    _multi, single = _PAPER_DETECTORS[_paper_detector_name]
    calibration = single(view, spec, process_width=0, window_index=window_index)
    corners = calibration.workspace_corners(grid, convention)
    workspace = WorkspaceMap.from_grid(grid, corners, view.shape[1::-1], projection)
    return workspace, calibration


def draw_paper_grid(frame, tracker, hover, grid, convention, *, detail=False):
    """Draw the printed-sheet overlay, plus the envelope it would calibrate to."""
    calibration = tracker.calibration
    if calibration is None:
        # A refusal still draws its blobs. Pressing p and seeing nothing change
        # is indistinguishable from p not working.
        if tracker.failure is not None:
            draw_candidates(frame, tracker.failure, labels=detail)
        return None
    draw_grid_alternatives(frame, tracker.calibrations, tracker.selection)
    hovered = draw_color_grid(frame, calibration, hover=hover, labels=detail,
                              shade=0.30)
    try:
        draw_workspace_corners(frame, calibration.workspace_corners(grid, convention))
    except (ColorGridError, ValueError):
        pass
    return hovered


def _dashed_polyline(frame, quad, color, *, dash=8, thickness=1):
    """Draw a virtual cell distinctly from a physically observed one."""
    points = np.asarray(quad, dtype=np.float32).round().astype(np.int32)
    for start, end in zip(points, np.roll(points, -1, axis=0)):
        vector = end.astype(float) - start
        length = float(np.linalg.norm(vector))
        if length < 1:
            continue
        direction = vector / length
        for offset in np.arange(0, length, dash * 2):
            a = start + direction * offset
            b = start + direction * min(offset + dash, length)
            cv2.line(frame, tuple(np.round(a).astype(int)), tuple(np.round(b).astype(int)),
                     color, thickness, cv2.LINE_AA)


def draw_paper_evidence(frame, evidence, *, detail=False):
    """Show measured cells green and inferred-only cells amber/dashed."""
    calibration = evidence.calibration
    if calibration is None:
        return
    observed = evidence.observed_cells
    tinted = frame.copy()
    for row in range(calibration.spec.rows):
        for col in range(calibration.spec.cols):
            quad = calibration.cell_quad(col, row).round().astype(np.int32)
            if (col, row) in observed:
                cv2.fillPoly(tinted, [quad], (100, 235, 100))
    cv2.addWeighted(tinted, 0.25, frame, 0.75, 0, frame)
    for row in range(calibration.spec.rows):
        for col in range(calibration.spec.cols):
            quad = calibration.cell_quad(col, row)
            if (col, row) in observed:
                cv2.polylines(frame, [quad.round().astype(np.int32)], True,
                              (100, 255, 100), 1, cv2.LINE_AA)
            else:
                _dashed_polyline(frame, quad, WARN_COLOR)
            if detail:
                centre = tuple(round(value) for value in calibration.cell_center(col, row))
                label = (calibration.pattern_label(col, row)
                         if getattr(calibration, "is_combined", False)
                         else f"{col},{row}")
                cv2.putText(frame, label, centre,
                            cv2.FONT_HERSHEY_SIMPLEX, 0.32,
                            (20, 20, 20), 3, cv2.LINE_AA)
                cv2.putText(frame, label, centre,
                            cv2.FONT_HERSHEY_SIMPLEX, 0.32,
                            (100, 255, 100) if (col, row) in observed else WARN_COLOR,
                            1, cv2.LINE_AA)


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH,
                        help=f"camera settings JSON (default: {SETTINGS_PATH})")
    parser.add_argument("--rig-config", type=Path, default=CONFIG_PATH,
                        help=f"grid/workspace JSON (default: {CONFIG_PATH})")
    parser.add_argument("--mode", choices=GRID_MODES, default=None,
                        help="grid and printed sheet to calibrate (default: "
                             "rig.json's grid.active_mode)")
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
    parser.add_argument("--edge-margin", type=float, default=DEFAULT_EDGE_MARGIN,
                        metavar="F",
                        help="printed-sheet: clear space a whole cell must keep "
                             "from the frame border, as a fraction of its own "
                             f"size (default: {DEFAULT_EDGE_MARGIN}; 0 disables)")
    parser.add_argument("--page-plane-min", type=int, default=None, metavar="N",
                        help="combined A2 target: fiducials needed to support the "
                             "page plane before it calibrates (default 76/80)")
    parser.add_argument("--min-saturation", type=int, default=None, metavar="S",
                        help="combined A2 target: ink saturation floor for the "
                             "faded passes; lower (e.g. 8) for a strong camera cast")
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
        workspace = WorkspaceMap.load(path, mode=grid.mode)
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
        g.block_x_cm, g.block_y_cm, g.gap_x_cm, g.gap_y_cm,
        g.workspace_width_cm, g.workspace_height_cm,
        g.trim_x_cm, g.trim_y_cm,
        g.error_offset_x_cm, g.error_offset_y_cm,
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
    for row in range(g.rows):
        for col in range(g.cols):
            polygon = [_pixel(point) for point in
                       workspace.cell_polygon(col, row, image_size)]
            lines.extend(zip(polygon, polygon[1:] + polygon[:1]))

    def _add_label(labels, text, x, y):
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.34, 1)
        labels.append((text, (x - tw // 2, y + th // 2)))

    labels = []
    first = workspace.cell_polygon(0, 0, image_size)
    approx_w = np.linalg.norm(np.asarray(first[1]) - np.asarray(first[0]))
    approx_h = np.linalg.norm(np.asarray(first[3]) - np.asarray(first[0]))
    show_labels = approx_w >= 38 and approx_h >= 24
    if show_labels:
        for row in range(g.rows):
            for col in range(g.cols):
                x_cm, y_cm = g.cell_center_cm(col, row)
                x, y = _pixel(_point(workspace, g, x_cm, y_cm, image_size))
                _add_label(labels, f"{col},{row}", x, y)

    # No axis-only strips any more. Row 0 and column 0 are ordinary cells with
    # real footprints and are drawn by the loop above; [0,0] is the feeder.
    extra_polygons = []

    cached = (envelope, tuple(lines), tuple(labels), tuple(extra_polygons))
    if len(_GRID_GEOMETRY_CACHE) >= 16:
        _GRID_GEOMETRY_CACHE.pop(next(iter(_GRID_GEOMETRY_CACHE)))
    _GRID_GEOMETRY_CACHE[key] = cached
    return cached


def draw_machine_grid(frame, workspace, hover_point, calibrated, *, detail=False):
    """Draw cached static grid geometry and the dynamic hovered cell.

    Every cell is its actual separated block rectangle, coordinate zero
    included - [0,0] is the feeder. All geometry comes from
    ``workspace.mapped_grid``.
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
        grid = MachineGrid.from_config(rig_data, mode=args.mode)
        paper_spec = ColorGridSpec.from_config(rig_data, mode=grid.mode)
        backend, device, size = capture_settings(camera_data)
        profile = profile_from_settings(camera_data)
        sensor = sensor_from_settings(camera_data)
        capture = camera_data.get("capture") or {}
        colour = colour_from_settings(camera_data)
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
        "evidence_active": False,
        "evidence_capture": False,
        "message": "ready",
    }
    paper = PaperGridTracker(paper_spec, max_hz=args.paper_hz,
                             edge_margin=args.edge_margin,
                             page_plane_min=args.page_plane_min,
                             min_saturation=args.min_saturation)
    evidence = PrintedGridEvidence(paper_spec)

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
                     ("Grid choice < (,)", ","), ("Grid choice > (.)", "."),
                     ("Evidence (e)", "e"), ("Accept frame (Space)", " "),
                     ("Quit (q)", "q")),
        )
    except (tk.TclError, cv2.error) as exc:
        print(f"Cannot open the camera UI: {exc}", file=sys.stderr)
        camera.release()
        return 1

    frame_pump = LatestFramePump(camera)
    # Grid-aware: lets the overlay reject block-shaped things that are not
    # on the lattice (the holder's offcuts beside [0,0]) and draw every
    # rectangle on one shared bearing. The lambda re-reads `grid`, which
    # the mode switch rebinds, so no worker restart is needed.
    analysis = AnalysisWorker(
        lambda frame, **kwargs: detect_aligned_blocks(frame, grid=grid, **kwargs),
        max_hz=args.analysis_hz)
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
            f"Grid: {grid.mode} {grid.cols}x{grid.rows} | {calibration_text} | "
            f"hover {f'[{cell[0]},{cell[1]}]' if cell else 'none'}",
            f"{paper.status()} | ,/. choose | home {args.home_convention} | k saves it",
            (f"Evidence: {evidence.status.describe()}"
             if ui["evidence_active"] else
             "Evidence: off | e starts a gantry-occlusion session"),
            block_hover_text(detections, ui["hover"]),
            f"Stages: remap {timings.ms.get('remap', 0):.1f} ms | "
            f"overlay {timings.ms.get('overlay', 0):.1f} ms | "
            f"grid {timings.ms.get('grid', 0):.1f} ms | "
            f"display {timings.ms.get('display', 0):.1f} ms",
            f"Status: {result.error or snapshot.error or ui['message']}",
            "o overlay | c calibrate | Enter save | u undo | x cancel | g grid | v detect",
            "p paper | ,/. choose grid | e evidence | Space accept | "
            "k save map | s snapshot | q quit",
        ]

    def handle_key(key):
        if key in (ord("q"), 27):
            return False
        if key == ord("o"):
            ui["overlay"] = OVERLAY_MODES[
                (OVERLAY_MODES.index(ui["overlay"]) + 1) % len(OVERLAY_MODES)]
            ui["message"] = f"overlay: {ui['overlay']}"
        elif key == ord("c"):
            if ui["evidence_active"]:
                ui["evidence_active"] = False
                evidence.clear()
            ui["calibrating"] = True
            ui["calibration_points"] = []
            ui["pending_points"] = None
            ui["message"] = "click the four prompted corners"
        elif key == ord("x"):
            if ui["evidence_active"]:
                ui["evidence_active"] = False
                ui["evidence_capture"] = False
                evidence.clear()
                ui["message"] = "evidence session cancelled; previous map kept"
            elif ui["calibrating"]:
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
            if ui["evidence_active"]:
                ui["message"] = "the paper overlay stays on during evidence collection"
            else:
                ui["message"] = ("printed-sheet overlay on" if paper.toggle()
                                 else "printed-sheet overlay off")
        elif key in (ord(","), ord(".")):
            if paper.cycle(-1 if key == ord(",") else 1):
                ui["message"] = (f"selected printed grid {paper.selection + 1}/"
                                 f"{len(paper.calibrations)}")
            else:
                ui["message"] = "only one printed-grid candidate is available"
        elif key == ord("e"):
            if ui["calibrating"]:
                ui["message"] = "finish or cancel the four-corner calibration first"
            else:
                evidence.clear()
                ui["evidence_active"] = True
                if not paper.enabled:
                    paper.toggle()
                ui["message"] = ("evidence session started: keep camera and sheet fixed; "
                                 "Space accepts a clear gantry position")
        elif key == ord(" "):
            if not ui["evidence_active"]:
                ui["message"] = "press e to start an evidence session first"
            else:
                # Deferred to the corrected-view loop, just like k.  A single
                # accepted snapshot is intentional; continuous frames in one
                # gantry position add no independent evidence.
                ui["evidence_capture"] = True
                ui["message"] = "checking this evidence frame"
        elif key == ord("k"):
            # Deferred to the frame loop, which is the only place that holds a
            # corrected view; the key handler runs between frames.
            ui["paper_calibrate"] = True
            ui["message"] = ("saving evidence calibration" if ui["evidence_active"]
                             else "calibrating from the printed sheet")
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
            frame = colour.apply(frame_orientation(frame, capture))
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

            if ui["evidence_capture"]:
                ui["evidence_capture"] = False
                try:
                    found = detect_printed_grid(
                        view, paper_spec, process_width=0, evidence=True)
                    status = evidence.add(found)
                    ui["message"] = ("evidence accepted: " + status.describe())
                    print("Evidence frame accepted: " + status.describe())
                except ColorGridError as exc:
                    ui["message"] = f"evidence frame rejected: {exc}"
                    print(ui["message"], file=sys.stderr)

            if ui["paper_calibrate"]:
                ui["paper_calibrate"] = False
                try:
                    if ui["evidence_active"]:
                        status = evidence.status
                        if not status.ready or evidence.calibration is None:
                            raise ColorGridError("evidence is not ready: " +
                                                 "; ".join(status.reasons))
                        found = evidence.calibration
                        corners = found.workspace_corners(grid, args.home_convention)
                        candidate = WorkspaceMap.from_grid(
                            grid, corners, view.shape[1::-1], projection)
                    else:
                        candidate, found = paper_workspace_map(
                            view, paper_spec, grid, projection,
                            args.home_convention, paper.selection)
                    candidate.save(args.workspace_map)
                    saved_workspace = candidate
                    rejection = None
                    ui["message"] = ("calibrated from evidence: " + evidence.status.describe()
                                     if ui["evidence_active"] else
                                     f"calibrated from the sheet: {found.describe()}")
                    ui["evidence_active"] = False
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
                if ui["evidence_active"]:
                    if evidence.calibration is not None:
                        draw_paper_evidence(display, evidence,
                                            detail=ui["overlay"] == "detail")
                    else:
                        # Before the first accepted frame, keep the usual
                        # candidate/error drawing visible for diagnosis.
                        draw_paper_grid(display, paper, ui["hover"], grid,
                                        args.home_convention,
                                        detail=ui["overlay"] == "detail")
                else:
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

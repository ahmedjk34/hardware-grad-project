#!/usr/bin/env python3
"""The config-driven camera feed — the foundation for the vision pipeline.

This is the normal runtime entry point for the camera. It reads the settings
written by ``camera_studio.py``, opens the configured source, applies the saved
sensor controls and orientation, and displays the saved corrected/framed feed.
Future detection, calibration and robot-coordinate stages should build from
the frame produced here rather than opening the camera a second time.

    python camera_feed.py
    python camera_feed.py --settings ../config/my_camera.json

Press ``q`` or Esc in the window to quit. ``camera_studio.py`` is the editor for
the settings; this script is their consumer. Move the mouse over a block for
pixel coordinates, and press ``s`` to save the annotated frame plus detection
metadata in ``captures/``. Press ``v`` to toggle block detection on/off.
"""

import argparse
import json
import sys
import time
import tkinter as tk
from dataclasses import fields
from pathlib import Path

import cv2
import numpy as np

# This tool lives one folder down, so python/ is not on the import path when it
# is run directly from either the repo root or python/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.camera_source import (  # noqa: E402
    AUTO,
    DEFAULT_SIZE,
    LatestFramePump,
    SENSOR_CONTROLS,
    open_camera,
)
from vision.analysis_worker import AnalysisWorker  # noqa: E402
from vision.block_detector import BlockDetection  # noqa: E402
from vision.block_outline import detect_aligned_blocks  # noqa: E402
from vision.fisheye import (  # noqa: E402
    INTERPOLATIONS,
    LensProfile,
    build_maps,
    undistort,
)
from vision.overlays import draw_info_box  # noqa: E402
from vision.performance import RateMeter, StageTimings  # noqa: E402
from camera.snapshot_worker import SnapshotWorker  # noqa: E402
from camera.tk_camera_window import TkCameraWindow  # noqa: E402


SETTINGS_PATH = Path(__file__).resolve().parents[1] / "config" / "camera_settings.json"
CAPTURE_DIR = Path(__file__).resolve().parents[1] / "captures"
VALID_BACKENDS = ("auto", "picamera2", "v4l2", "mock")
VALID_FLIPS = ("none", "h", "v", "both")
VALID_ROTATIONS = (0, 90, 180, 270)


def load_settings(path: Path) -> dict:
    """Load one camera settings file and give useful errors for bad JSON."""
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise RuntimeError(f"Camera settings not found: {path}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Camera settings are not valid JSON: {path}: {exc}")
    if not isinstance(data, dict):
        raise RuntimeError(f"Camera settings must contain a JSON object: {path}")
    return data


def _choice(section: dict, name: str, choices: tuple, default):
    value = section.get(name, default)
    if value not in choices:
        raise RuntimeError(f"camera settings: {name!r} must be one of {choices}, "
                           f"not {value!r}")
    return value


def capture_settings(data: dict) -> tuple[str, str | None, tuple[int, int]]:
    """Return backend, optional V4L2 device, and configured capture size."""
    capture = data.get("capture") or {}
    backend = _choice(capture, "backend", VALID_BACKENDS, "auto")
    device = capture.get("device")
    if device is not None and not isinstance(device, str):
        raise RuntimeError("camera settings: capture.device must be a path or null")

    try:
        width = int(capture.get("width") or DEFAULT_SIZE[0])
        height = int(capture.get("height") or DEFAULT_SIZE[1])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("camera settings: capture.width and height must be integers") from exc
    if width < 2 or height < 2:
        raise RuntimeError("camera settings: capture dimensions must be at least 2x2")
    return backend, device, (width, height)


def profile_from_settings(data: dict) -> LensProfile:
    """Build the lens profile from the settings file's saved lens block."""
    lens = data.get("lens") or {}
    known = {field.name: lens[field.name] for field in fields(LensProfile)
             if field.name in lens}
    profile = LensProfile(**known)
    profile.clamp()
    return profile


def sensor_from_settings(data: dict) -> dict:
    """Return only known sensor controls, preserving ``auto`` values."""
    sensor = data.get("sensor") or {}
    return {name: sensor.get(name, AUTO) for name in SENSOR_CONTROLS}


def colour_from_settings(data: dict):
    """Build the saved software colour correction, or a disabled identity.

    Applied before the lens correction, next to the orientation, because it is a
    property of the captured picture rather than of the geometry. Every tool
    built on this feed inherits it by calling this and applying the result — the
    rig's camera has a strong enough colour cast to break block detection and
    the printed-grid detector alike, and fixing it once here is what stops each
    of those having to defend itself separately.
    """
    from vision.color_correction import ColorCorrection
    return ColorCorrection.from_settings(data)


def frame_orientation(frame, capture: dict):
    """Apply the saved flip/rotation before correction sees the frame."""
    if capture.get("swap_rb", False):
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    flip = _choice(capture, "flip", VALID_FLIPS, "none")
    if flip in ("h", "both"):
        frame = cv2.flip(frame, 1)
    if flip in ("v", "both"):
        frame = cv2.flip(frame, 0)

    rotate = capture.get("rotate", 0)
    if rotate not in VALID_ROTATIONS:
        raise RuntimeError(f"camera settings: rotate must be one of {VALID_ROTATIONS}, "
                           f"not {rotate!r}")
    if rotate:
        frame = cv2.rotate(frame, {
            90: cv2.ROTATE_90_CLOCKWISE,
            180: cv2.ROTATE_180,
            270: cv2.ROTATE_90_COUNTERCLOCKWISE,
        }[rotate])
    return frame


def crop_rect(crops) -> tuple[float, float, float, float]:
    """Compose the saved crop stack into one full-output rectangle."""
    x0, y0, x1, y1 = 0.0, 0.0, 1.0, 1.0
    for crop in crops or []:
        if len(crop) != 4:
            raise RuntimeError("camera settings: every framing crop needs four values")
        a, b, c, d = (float(value) for value in crop)
        width, height = x1 - x0, y1 - y0
        x0, y0, x1, y1 = x0 + a * width, y0 + b * height, \
            x0 + c * width, y0 + d * height
    return x0, y0, x1, y1


def framing_roi(data: dict) -> tuple[float, float, float, float]:
    """Resolve saved crops, zoom and pan into the ROI rendered by the feed."""
    framing = data.get("framing") or {}
    x0, y0, x1, y1 = crop_rect(framing.get("crops", []))
    zoom = max(1.0, float(framing.get("zoom", 1.0)))
    pan = framing.get("pan", (0.5, 0.5))
    if len(pan) != 2:
        raise RuntimeError("camera settings: framing.pan needs two values")
    cx, cy = float(pan[0]), float(pan[1])
    width, height = (x1 - x0) / zoom, (y1 - y0) / zoom
    cx = min(max(cx, x0 + width / 2), x1 - width / 2)
    cy = min(max(cy, y0 + height / 2), y1 - height / 2)
    return cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2


def crop_resize(frame, roi, out_size, interpolation):
    """Crop and resize the raw frame when correction is disabled."""
    h, w = frame.shape[:2]
    x0 = min(max(round(roi[0] * w), 0), w - 1)
    y0 = min(max(round(roi[1] * h), 0), h - 1)
    x1 = min(max(round(roi[2] * w), x0 + 1), w)
    y1 = min(max(round(roi[3] * h), y0 + 1), h)
    sub = frame[y0:y1, x0:x1]
    if (sub.shape[1], sub.shape[0]) == tuple(out_size):
        return sub
    shrinking = out_size[0] < sub.shape[1]
    kernel = cv2.INTER_AREA if shrinking else INTERPOLATIONS[interpolation]
    return cv2.resize(sub, tuple(out_size), interpolation=kernel)


# One colour for every block. The old six-colour cycle was meant to separate
# adjacent blocks, but on a full board it did the opposite: neighbouring
# outlines in unrelated colours read as unrelated objects, when the thing worth
# seeing is that they form one grid. A single high-contrast stroke against the
# pale work surface, plus the dark under-stroke below, keeps every edge
# readable without implying a difference that is not there.
BLOCK_COLOR = (90, 255, 90)
# The hovered block is the only one that differs, and by BRIGHTNESS rather than
# hue, so it reads as "this one" instead of "a different kind of thing".
BLOCK_HOVER_COLOR = (255, 255, 255)
OVERLAY_MODES = ("off", "geometry", "detail")
STALE_FRAME_AFTER_S = 0.75
_DISPLAY_CLAHE = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))


def enhance_for_display(frame):
    """Increase local contrast and edge crispness without changing detection data."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    lightness, a_channel, b_channel = cv2.split(lab)
    lightness = _DISPLAY_CLAHE.apply(lightness)
    enhanced = cv2.cvtColor(cv2.merge((lightness, a_channel, b_channel)),
                            cv2.COLOR_LAB2BGR)
    soft = cv2.GaussianBlur(enhanced, (0, 0), 1.0)
    return cv2.addWeighted(enhanced, 1.22, soft, -0.22, 0)


def _block_color_name(detection: BlockDetection) -> str:
    """Give the current warm block material a human-readable colour name."""
    hue = detection.hue
    if hue >= 165 or hue < 8:
        return "pink/red"
    if hue < 24:
        return "orange/tan"
    if hue < 42:
        return "yellow"
    if hue < 90:
        return "green/cyan"
    if hue < 140:
        return "blue"
    return "violet"


def hovered_block(detections, point):
    """Return the detection index under a corrected-feed pixel, if any."""
    if point is None:
        return None
    x, y = point
    for index, detection in enumerate(detections):
        if cv2.pointPolygonTest(detection.contour, (float(x), float(y)), False) >= 0:
            return index
    return None


def block_hover_text(detections, point):
    """Detailed hover diagnostics for Tk, never for the default image overlay."""
    index = hovered_block(detections, point)
    if index is None:
        return "Hovered block: none"
    detection = detections[index]
    cx, cy = (round(v) for v in detection.center)
    return (f"Hovered block: #{index + 1} | {_block_color_name(detection)} | "
            f"center {cx},{cy} px | size {detection.size[0]:.0f}x"
            f"{detection.size[1]:.0f} px | angle {detection.angle:.1f}° | "
            f"edge confidence {detection.confidence * 100:.0f}%")


def draw_block_overlay(frame, detections, hover_point=None, fps=None,
                       coordinates_label="COORDS: corrected-image pixels (machine mapping pending)",
                       show_info=True, mode=None):
    """Draw clean colour-coded edges, boxes, IDs, centres and hover details."""
    if mode is None:
        mode = "detail" if show_info else "geometry"
    if mode not in OVERLAY_MODES:
        raise ValueError(f"overlay mode must be one of {OVERLAY_MODES}")
    if mode == "off" or not detections:
        return frame

    # Blend only each block's small bounding ROI. The former full-frame copy +
    # blend paid for every pixel even when no blocks were visible.
    for detection in detections:
        color = BLOCK_COLOR
        x, y, w, h = cv2.boundingRect(detection.box)
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(frame.shape[1], x + w), min(frame.shape[0], y + h)
        if x1 <= x0 or y1 <= y0:
            continue
        roi = frame[y0:y1, x0:x1]
        fill = roi.copy()
        local_box = detection.box - np.array((x0, y0), dtype=np.int32)
        cv2.fillPoly(fill, [local_box], color)
        cv2.addWeighted(fill, 0.12, roi, 0.88, 0, roi)

    hovered = hovered_block(detections, hover_point)
    for index, detection in enumerate(detections):
        color = BLOCK_HOVER_COLOR if index == hovered else BLOCK_COLOR
        thickness = 3 if index == hovered else 2
        # The rotated BOX, never the segmentation contour. A mask edge wanders
        # a pixel or two all the way round, so a board of contours reads as a
        # board of different wobbly shapes; a board of rectangles reads as the
        # grid it is. vision/block_outline.py is what makes the box worth
        # trusting - it shares one size and one bearing across the population.
        outline = np.asarray(detection.box, dtype=np.int32).reshape(-1, 1, 2)
        # Dark under-stroke keeps the edge readable on both the pale work
        # surface and the dark hardware behind it.
        cv2.polylines(frame, [outline], True, (20, 20, 20), thickness + 3,
                      cv2.LINE_AA)
        cv2.polylines(frame, [outline], True, color, thickness, cv2.LINE_AA)
        cx, cy = (round(v) for v in detection.center)
        cv2.drawMarker(frame, (cx, cy), color, cv2.MARKER_CROSS, 11, 1, cv2.LINE_AA)

        if mode == "detail":
            label = f"#{index + 1} ({cx},{cy})"
            x = max(3, int(detection.box[:, 0].min()))
            y = max(16, int(detection.box[:, 1].min()) - 5)
            cv2.putText(frame, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                        (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(frame, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                        color, 1, cv2.LINE_AA)

    if mode != "detail":
        return frame

    rate = f"  |  {fps:4.1f} fps" if fps is not None else ""
    hud = [
        f"BLOCKS: {len(detections)}{rate}  |  hover for details",
        "ALIGNED BLOCK RECTANGLES + CENTRES",
        coordinates_label,
    ]
    draw_info_box(frame, hud, width=min(360, frame.shape[1] - 8), scale=0.40)

    if hovered is not None:
        detection = detections[hovered]
        cx, cy = (round(v) for v in detection.center)
        long_side, short_side = detection.size
        lines = [
            f"BLOCK #{hovered + 1}  {_block_color_name(detection)}",
            f"centre  x {cx}px  y {cy}px",
            f"size    {long_side:.0f} x {short_side:.0f}px",
            f"angle   {detection.angle:.1f} deg",
            f"edge confidence {detection.confidence * 100:.0f}%",
        ]
        draw_info_box(frame, lines, origin=(6, frame.shape[0] - 104),
                      width=min(280, frame.shape[1] - 12), scale=0.40,
                      highlight_first=True)
        cv2.drawMarker(frame, (round(hover_point[0]), round(hover_point[1])),
                       (255, 255, 255), cv2.MARKER_CROSS, 20, 2, cv2.LINE_AA)
    elif hover_point is not None:
        x, y = (round(v) for v in hover_point)
        if 0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]:
            cv2.drawMarker(frame, (x, y), (210, 210, 210), cv2.MARKER_CROSS,
                           12, 1, cv2.LINE_AA)
            draw_info_box(frame, [f"cursor  x {x}px  y {y}px"],
                          origin=(6, frame.shape[0] - 32), width=180, scale=0.40)
    return frame


def save_detection_snapshot(frame, detections):
    """Save the visible annotated frame and machine-readable block geometry."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    image_path = CAPTURE_DIR / f"{stamp}_blocks.png"
    data_path = CAPTURE_DIR / f"{stamp}_blocks.json"
    cv2.imwrite(str(image_path), frame)
    data_path.write_text(json.dumps([
        {
            "id": index + 1,
            "center_px": [round(d.center[0], 2), round(d.center[1], 2)],
            "box_px": d.box.tolist(),
            "size_px": [round(v, 2) for v in d.size],
            "angle_deg": round(d.angle, 2),
            "area_px": round(d.area, 2),
            "confidence": round(d.confidence, 4),
            "hue": round(d.hue, 2),
        }
        for index, d in enumerate(detections)
    ], indent=2) + "\n")
    return image_path, data_path


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH,
                        help=f"camera settings JSON (default: {SETTINGS_PATH})")
    parser.add_argument("--display-scale", type=float, default=1.0,
                        help="scale only the display window; detection stays at source size")
    parser.add_argument("--color-threshold", type=int, default=8,
                        help="minimum red-minus-blue value for a block (default: 8)")
    parser.add_argument("--min-area", type=int, default=500,
                        help="minimum detected block area in feed pixels (default: 500)")
    parser.add_argument("--enhance", action="store_true",
                        help="enable costly software contrast/sharpness enhancement")
    parser.add_argument("--no-enhance", action="store_false", dest="enhance",
                        help=argparse.SUPPRESS)
    parser.add_argument("--overlay", choices=OVERLAY_MODES, default="geometry",
                        help="preview overlay detail (default: geometry)")
    parser.add_argument("--analysis-hz", type=float, default=10.0,
                        help="maximum block-analysis rate (default: 10)")
    parser.add_argument("--opencv-threads", type=int, default=2,
                        help="OpenCV worker threads (default: 2)")
    return parser.parse_args()


def main():
    args = parse_args()
    if (args.display_scale <= 0 or args.min_area <= 0 or args.analysis_hz <= 0
            or args.opencv_threads <= 0):
        print("display/min-area/analysis-hz/opencv-threads values must be positive",
              file=sys.stderr)
        return 1
    cv2.setNumThreads(args.opencv_threads)
    try:
        data = load_settings(args.settings)
        backend, device, size = capture_settings(data)
        profile = profile_from_settings(data)
        sensor = sensor_from_settings(data)
        capture = data.get("capture") or {}
        colour = colour_from_settings(data)
        correction = data.get("correction") or {}
        enabled = bool(correction.get("enabled", True))
        interpolation = correction.get("interp", "cubic")
        if interpolation not in INTERPOLATIONS:
            raise RuntimeError(f"camera settings: correction.interp must be one of "
                               f"{tuple(INTERPOLATIONS)}, not {interpolation!r}")
        mip = bool(correction.get("mip", True))
        roi = framing_roi(data)
    except (RuntimeError, TypeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        camera = open_camera(backend, size, device)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    # Apply the complete saved sensor block after opening. This works for both
    # Picamera2 and V4L2; Picamera2 filters controls against the sensor's actual
    # capabilities and V4L2 reports controls its driver refused.
    applied, skipped = camera.apply(sensor)
    if skipped:
        print("Sensor settings unavailable: " + "; ".join(skipped))
    print(f"Camera: {camera.name}")
    print(f"Loaded settings: {args.settings}")
    print(f"Sensor settings: {len(applied)} applied")

    ui = {"hover": None, "overlay": args.overlay, "detect_enabled": True,
          "message": "ready"}

    def on_mouse(event, point):
        if event == "move":
            ui["hover"] = point

    try:
        window = TkCameraWindow(
            f"Camera Feed - {camera.name}", size,
            display_scale=args.display_scale, mouse_callback=on_mouse,
            buttons=(("Overlay (o)", "o"), ("Detect (v)", "v"),
                     ("Save snapshot", "s"), ("Quit", "q")),
        )
    except (tk.TclError, cv2.error) as exc:
        print(f"Cannot open the camera UI: {exc}", file=sys.stderr)
        camera.release()
        return 1

    frame_pump = LatestFramePump(camera)
    # No MachineGrid here on purpose - camera_feed knows nothing about the
    # rig. The outlines are still squared up and given one shared size and
    # bearing; only the lattice-based rejection needs a grid.
    analysis = AnalysisWorker(detect_aligned_blocks,
                              max_hz=args.analysis_hz)
    snapshots = SnapshotWorker(save_detection_snapshot)
    frame_pump.start()
    analysis.start()
    maps = None
    input_size = None
    map_generation = 0
    last_sequence = 0
    last_display = None
    detections = ()
    capture_rate = RateMeter()
    preview_rate = RateMeter()
    timings = StageTimings()
    snapshot_count = 0

    def status_lines(snapshot, analysis_snapshot):
        age = snapshot.age_s()
        age_text = "waiting" if age is None else f"{age * 1000:.0f} ms"
        camera_state = ("WAITING" if age is None else
                        "STALE" if age >= STALE_FRAME_AFTER_S else "LIVE")
        analysis_age = analysis_snapshot.age_s()
        analysis_text = ("waiting" if analysis_snapshot.completed_at is None else
                         f"{analysis_snapshot.duration_s * 1000:.1f} ms, "
                         f"age {analysis_age * 1000:.0f} ms")
        hover_text = block_hover_text(detections, ui["hover"])
        feed_text = "waiting for first corrected frame"
        if last_display is not None:
            feed_text = f"Feed: {last_display.shape[1]}x{last_display.shape[0]}"
        return [
            f"Camera: {camera.name} | {camera_state} | capture "
            f"{capture_rate.rate:5.1f} fps | age {age_text}",
            f"{feed_text} | preview {preview_rate.rate:5.1f} fps | overlay {ui['overlay']}",
            f"Analysis: {'OFF' if not ui['detect_enabled'] else f'{analysis_snapshot.rate_hz:4.1f} Hz'} | "
            f"seq {analysis_snapshot.source_sequence} | {analysis_text} | blocks {len(detections)} | "
            f"replaced {analysis_snapshot.replaced_count} | duplicate "
            f"{analysis_snapshot.duplicate_count}",
            f"Stages: remap {timings.ms.get('remap', 0):.1f} ms | "
            f"overlay {timings.ms.get('overlay', 0):.1f} ms | "
            f"display {timings.ms.get('display', 0):.1f} ms",
            hover_text,
            f"Status: {analysis_snapshot.error or snapshot.error or ui['message']}",
            "o overlay | v detect | s snapshot | q/Esc quit",
        ]

    def handle_key(key):
        if key in (ord("q"), 27):
            return False
        if key == ord("o"):
            index = (OVERLAY_MODES.index(ui["overlay"]) + 1) % len(OVERLAY_MODES)
            ui["overlay"] = OVERLAY_MODES[index]
            ui["message"] = f"overlay: {ui['overlay']}"
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
            analysis_snapshot = analysis.snapshot()
            if not ui["detect_enabled"]:
                detections = ()
            elif analysis_snapshot.is_current(map_generation):
                detections = analysis_snapshot.detections

            snapshot_state = snapshots.snapshot()
            if snapshot_state.completed_count != snapshot_count:
                snapshot_count = snapshot_state.completed_count
                if snapshot_state.error:
                    ui["message"] = snapshot_state.error
                    print(snapshot_state.error, file=sys.stderr)
                elif snapshot_state.result:
                    image_path, data_path = snapshot_state.result
                    ui["message"] = f"saved {image_path.name} and {data_path.name}"
                    print(f"Saved {image_path} and {data_path}")

            if snapshot.frame is None or snapshot.sequence == last_sequence:
                window.pump(status_lines(snapshot, analysis_snapshot))
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
            view.flags.writeable = False
            if ui["detect_enabled"]:
                analysis.submit(view, snapshot.sequence, map_generation,
                                color_threshold=args.color_threshold,
                                min_area=args.min_area)
            display = enhance_for_display(view) if args.enhance else view.copy()
            started = time.perf_counter()
            draw_block_overlay(display, detections, ui["hover"], None,
                               show_info=False, mode=ui["overlay"])
            timings.observe("overlay", time.perf_counter() - started)
            last_display = display
            started = time.perf_counter()
            window.show(display, status_lines(snapshot, analysis_snapshot))
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

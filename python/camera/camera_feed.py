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
metadata in ``captures/``.
"""

import argparse
import json
import sys
import time
from dataclasses import fields
from pathlib import Path

import cv2

# This tool lives one folder down, so python/ is not on the import path when it
# is run directly from either the repo root or python/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.camera_source import (  # noqa: E402
    AUTO,
    DEFAULT_SIZE,
    SENSOR_CONTROLS,
    open_camera,
)
from vision.block_detector import BlockDetection, detect_blocks  # noqa: E402
from vision.fisheye import (  # noqa: E402
    INTERPOLATIONS,
    LensProfile,
    build_maps,
    undistort,
)
from vision.overlays import draw_info_box  # noqa: E402


SETTINGS_PATH = Path(__file__).resolve().parents[1] / "config" / "camera_settings.json"
CAPTURE_DIR = Path(__file__).resolve().parents[1] / "captures"
VALID_BACKENDS = ("auto", "picamera2", "v4l2")
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


# Distinct BGR colours make adjacent blocks easy to tell apart. The palette is
# intentionally high-contrast against the pale work surface and repeats only
# after six detections.
BLOCK_COLORS = (
    (255, 80, 40),    # blue-orange
    (40, 210, 255),   # yellow
    (90, 255, 90),    # green
    (255, 80, 220),   # pink
    (255, 180, 40),   # cyan
    (180, 80, 255),   # purple
)


def enhance_for_display(frame):
    """Increase local contrast and edge crispness without changing detection data."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    lightness, a_channel, b_channel = cv2.split(lab)
    lightness = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(lightness)
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


def draw_block_overlay(frame, detections, hover_point=None):
    """Draw clean colour-coded edges, boxes, IDs, centres and hover details."""
    fill = frame.copy()
    for index, detection in enumerate(detections):
        color = BLOCK_COLORS[index % len(BLOCK_COLORS)]
        cv2.fillPoly(fill, [detection.box], color)
    cv2.addWeighted(fill, 0.12, frame, 0.88, 0, frame)

    hovered = hovered_block(detections, hover_point)
    for index, detection in enumerate(detections):
        color = BLOCK_COLORS[index % len(BLOCK_COLORS)]
        thickness = 4 if index == hovered else 3
        # Dark under-stroke makes the coloured edge readable on both white
        # surfaces and dark hardware, while the anti-aliased colour stroke says
        # which block the edge belongs to.
        cv2.polylines(frame, [detection.contour], True, (20, 20, 20), thickness + 3,
                      cv2.LINE_AA)
        cv2.polylines(frame, [detection.contour], True, color, thickness, cv2.LINE_AA)
        cv2.polylines(frame, [detection.box], True, (255, 255, 255), 1, cv2.LINE_AA)
        cx, cy = (round(v) for v in detection.center)
        cv2.drawMarker(frame, (cx, cy), color, cv2.MARKER_CROSS, 16, 2, cv2.LINE_AA)

        label = f"#{index + 1} ({cx},{cy})"
        x = max(3, int(detection.box[:, 0].min()))
        y = max(16, int(detection.box[:, 1].min()) - 5)
        cv2.putText(frame, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    color, 1, cv2.LINE_AA)

    hud = [
        f"BLOCKS: {len(detections)}  |  move mouse over a block",
        "COLOUR EDGES + ROTATED BOXES + CENTRES",
        "COORDS: corrected-image pixels (machine mapping pending)",
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
    parser.add_argument("--no-enhance", action="store_true",
                        help="disable display contrast/sharpness enhancement")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.display_scale <= 0 or args.min_area <= 0:
        print("--display-scale and --min-area must be positive", file=sys.stderr)
        return 1
    try:
        data = load_settings(args.settings)
        backend, device, size = capture_settings(data)
        profile = profile_from_settings(data)
        sensor = sensor_from_settings(data)
        capture = data.get("capture") or {}
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

    window = f"Camera Feed - {camera.name}"
    ui = {"hover": None}

    def on_mouse(event, x, y, _flags, state):
        if event == cv2.EVENT_MOUSEMOVE:
            state["hover"] = (x / args.display_scale, y / args.display_scale)

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
            detections = detect_blocks(view, color_threshold=args.color_threshold,
                                       min_area=args.min_area)
            display = view if args.no_enhance else enhance_for_display(view)
            display = draw_block_overlay(display, detections, ui["hover"])
            now = time.perf_counter()
            dt, last = now - last, now
            if dt > 0:
                instant = 1.0 / dt
                fps = 0.9 * fps + 0.1 * instant if fps else instant
            draw_info_box(display, [
                f"{camera.name}  {fps:5.1f} fps",
                f"{'CORRECTED' if enabled else 'RAW'}  {view.shape[1]}x{view.shape[0]}",
                f"settings {args.settings.name}",
            ], origin=(display.shape[1] - min(330, display.shape[1] - 8) - 4, 4),
                           width=min(330, display.shape[1] - 8), scale=0.38)
            if args.display_scale != 1.0:
                shown = cv2.resize(display, None, fx=args.display_scale,
                                   fy=args.display_scale, interpolation=cv2.INTER_AREA)
            else:
                shown = display

            cv2.imshow(window, shown)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                return 0
            if key == ord("s"):
                image_path, data_path = save_detection_snapshot(display, detections)
                print(f"Saved {image_path} and {data_path}")
            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                return 0
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())

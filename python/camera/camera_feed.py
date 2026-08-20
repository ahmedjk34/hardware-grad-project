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
the settings; this script is their consumer.
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
from vision.fisheye import (  # noqa: E402
    INTERPOLATIONS,
    LensProfile,
    build_maps,
    undistort,
)
from vision.overlays import draw_info_box  # noqa: E402


SETTINGS_PATH = Path(__file__).resolve().parents[1] / "config" / "camera_settings.json"
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


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH,
                        help=f"camera settings JSON (default: {SETTINGS_PATH})")
    return parser.parse_args()


def main():
    args = parse_args()
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
            now = time.perf_counter()
            dt, last = now - last, now
            if dt > 0:
                instant = 1.0 / dt
                fps = 0.9 * fps + 0.1 * instant if fps else instant
            draw_info_box(view, [
                "CONFIG-DRIVEN CAMERA FEED",
                f"{camera.name}  {fps:5.1f} fps",
                f"{'CORRECTED' if enabled else 'RAW'}  output {view.shape[1]}x{view.shape[0]}",
                f"settings {args.settings.name}",
            ], highlight_first=False)

            cv2.imshow(window, view)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                return 0
            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                return 0
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())

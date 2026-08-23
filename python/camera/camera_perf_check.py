#!/usr/bin/env python3
"""Read-only camera/Pi performance and configuration diagnostic."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import (  # noqa: E402
    SETTINGS_PATH,
    capture_settings,
    framing_roi,
    load_settings,
    profile_from_settings,
)
from vision.camera_source import open_camera  # noqa: E402
from vision.fisheye import build_maps, sampling_stats  # noqa: E402


def _vcgencmd(*args):
    executable = shutil.which("vcgencmd")
    if executable is None:
        return "unavailable (normal away from Raspberry Pi OS)"
    try:
        result = subprocess.run(
            [executable, *args], check=False, capture_output=True, text=True,
            timeout=2.0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"failed: {exc}"
    return (result.stdout or result.stderr).strip() or f"exit {result.returncode}"


def _temperature():
    path = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        return f"{float(path.read_text().strip()) / 1000.0:.1f} °C"
    except (OSError, ValueError):
        return "unavailable"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH)
    parser.add_argument("--probe-camera", action="store_true",
                        help="briefly open the configured camera and report its actual backend")
    parser.add_argument("--opencv-threads", type=int, default=2)
    args = parser.parse_args()
    if args.opencv_threads <= 0:
        parser.error("--opencv-threads must be positive")
    cv2.setNumThreads(args.opencv_threads)

    data = load_settings(args.settings)
    backend, device, size = capture_settings(data)
    correction = data.get("correction") or {}
    maps = build_maps(
        profile_from_settings(data), size,
        correction.get("interp", "cubic"),
        mip=bool(correction.get("mip", True)), roi=framing_roi(data))
    stats = sampling_stats(maps)

    print("System")
    print(f"  platform: {platform.platform()}")
    print(f"  machine: {platform.machine()} | CPU count: {os.cpu_count()}")
    print(f"  Python: {sys.version.split()[0]} ({sys.executable})")
    print(f"  OpenCV: {cv2.__version__} ({Path(cv2.__file__).resolve()})")
    print(f"  NumPy: {np.__version__} ({Path(np.__file__).resolve()})")
    print(f"  OpenCV threads: {cv2.getNumThreads()}")
    print(f"  DISPLAY: {os.environ.get('DISPLAY', '(unset)')}")
    print(f"  session: {os.environ.get('XDG_SESSION_TYPE', '(unset)')} | "
          f"desktop: {os.environ.get('XDG_CURRENT_DESKTOP', '(unset)')}")

    print("Camera configuration")
    print(f"  settings: {args.settings.resolve()}")
    print(f"  configured backend: {backend} | device: {device or '(automatic)'}")
    print(f"  capture: {size[0]}x{size[1]}")
    print(f"  corrected output: {maps.out_size[0]}x{maps.out_size[1]}")
    print(f"  interpolation: {correction.get('interp', 'cubic')} | "
          f"mip levels: {stats['mip_levels']}")
    print(f"  sampling centre/edge: {stats['centre']:.2f}/{stats['edge']:.2f} "
          f"| magnified: {stats['upscaled_fraction'] * 100:.0f}%")

    print("Raspberry Pi health")
    print(f"  temperature: {_temperature()}")
    print(f"  throttled: {_vcgencmd('get_throttled')}")
    print(f"  ARM clock: {_vcgencmd('measure_clock', 'arm')}")

    if args.probe_camera:
        camera = None
        try:
            camera = open_camera(backend, size, device)
            print("Camera probe")
            print(f"  actual source: {camera.name}")
            print(f"  actual size: {camera.size[0]}x{camera.size[1]}")
        finally:
            if camera is not None:
                camera.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


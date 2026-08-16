#!/usr/bin/env python3
"""Live fisheye-corrected preview for the OV5647 160deg lens.

Camera -> estimated fisheye undistortion -> rectilinear preview. No cropping to
the workspace, no detection, no mapping. The lens parameters are ESTIMATES from
the vendor FOV spec (see fisheye_undistort.py) - tune them by eye with the keys
below, then press 'w' to write them to config/lens_profile.json.

Keys:
  q / ESC   quit                     u  toggle correction on/off
  [ / ]     lens FOV -/+ 2 deg       b  toggle raw|corrected side by side
  - / =     output FOV -/+ 5 deg     g  toggle grid overlay (judge straightness)
  m         cycle projection model   s  save a raw+corrected snapshot
  r         reset to defaults        w  write current params to the profile
"""

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from camera_source import DEFAULT_SIZE, open_camera
from fisheye_undistort import (
    MODEL_NAMES,
    PROFILE_PATH,
    LensProfile,
    build_maps,
    undistort,
)
from grid_viewer import draw_grid

CAPTURE_DIR = Path(__file__).resolve().parent.parent / "captures"
HUD_COLOR = (255, 255, 255)
WARN_COLOR = (0, 200, 255)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--backend", choices=["auto", "picamera2", "v4l2"], default="auto")
    p.add_argument("--device", help="V4L2 device path, e.g. /dev/video0 (skips the picker)")
    p.add_argument("--width", type=int, default=DEFAULT_SIZE[0])
    p.add_argument("--height", type=int, default=DEFAULT_SIZE[1])
    p.add_argument("--lens-fov", type=float, help="quoted lens FOV in degrees (default 160)")
    p.add_argument("--fov-reference", choices=["diagonal", "horizontal"],
                   help="whether --lens-fov is the diagonal or horizontal FOV")
    p.add_argument("--model", choices=MODEL_NAMES, help="assumed fisheye projection curve")
    p.add_argument("--output-fov", type=float,
                   help="diagonal FOV of the rectilinear output, degrees (default 120)")
    p.add_argument("--output-scale", type=float,
                   help="output size relative to input; >1 keeps centre detail at wide output FOV")
    p.add_argument("--display-scale", type=float, default=1.0,
                   help="scale the window only; does not affect processing")
    p.add_argument("--profile", type=Path, default=PROFILE_PATH,
                   help="lens profile JSON to load (and write with 'w')")
    p.add_argument("--swap-rb", action="store_true", help="fix inverted red/blue channels")
    return p.parse_args()


def profile_from_args(args):
    profile = LensProfile.load(args.profile)
    for attr, value in (
        ("lens_fov_deg", args.lens_fov),
        ("fov_reference", args.fov_reference),
        ("model", args.model),
        ("output_fov_deg", args.output_fov),
        ("output_scale", args.output_scale),
    ):
        if value is not None:
            setattr(profile, attr, value)
    profile.clamp()
    return profile


def draw_hud(frame, lines, warn=False):
    pad, line_h = 6, 18
    box_h = pad * 2 + line_h * len(lines)
    box_w = max(220, 9 * max(len(line) for line in lines))
    box_w = min(box_w, frame.shape[1] - 8)

    overlay = frame.copy()
    cv2.rectangle(overlay, (4, 4), (4 + box_w, 4 + box_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    for i, line in enumerate(lines):
        color = WARN_COLOR if warn and i == 0 else HUD_COLOR
        y = 4 + pad + line_h * (i + 1) - 4
        cv2.putText(frame, line, (4 + pad, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


def side_by_side(raw, corrected):
    """Stack raw and corrected at a common height for an A/B comparison."""
    h = min(raw.shape[0], corrected.shape[0])
    def fit(img):
        scale = h / img.shape[0]
        return cv2.resize(img, (max(1, round(img.shape[1] * scale)), h), interpolation=cv2.INTER_AREA)
    left, right = fit(raw), fit(corrected)
    pair = np.hstack([left, right])
    cv2.line(pair, (left.shape[1], 0), (left.shape[1], h), (0, 255, 0), 1)
    return pair


def save_snapshot(raw, corrected, profile):
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tag = f"{profile.model}-lens{profile.lens_fov_deg:.0f}-out{profile.output_fov_deg:.0f}"
    raw_path = CAPTURE_DIR / f"{stamp}_raw.png"
    fixed_path = CAPTURE_DIR / f"{stamp}_undistorted_{tag}.png"
    cv2.imwrite(str(raw_path), raw)
    cv2.imwrite(str(fixed_path), corrected)
    print(f"Saved {raw_path.name} and {fixed_path.name} in {CAPTURE_DIR}")


def handle_key(key, profile):
    """Return True if the remap tables need rebuilding."""
    if key == ord("["):
        profile.lens_fov_deg -= 2
    elif key == ord("]"):
        profile.lens_fov_deg += 2
    elif key == ord("-"):
        profile.output_fov_deg -= 5
    elif key in (ord("="), ord("+")):
        profile.output_fov_deg += 5
    elif key == ord("m"):
        profile.model = MODEL_NAMES[(MODEL_NAMES.index(profile.model) + 1) % len(MODEL_NAMES)]
    else:
        return False
    profile.clamp()
    return True


def main():
    args = parse_args()
    profile = profile_from_args(args)

    camera = open_camera(args.backend, (args.width, args.height), args.device)
    print(f"Camera: {camera.name}")

    maps = build_maps(profile, camera.size)
    print(f"Estimated source focal length: {maps.source_focal_px:.1f} px")
    print(f"Output: {maps.out_size[0]}x{maps.out_size[1]} rectilinear, f={maps.output_focal_px:.1f} px")
    if not profile.calibrated:
        print("Profile is ESTIMATED (no checkerboard calibration) - visually straight, not metric.")
    print(__doc__.split("Keys:")[1])

    window = "Undistorted Preview (q/ESC to quit, h-less HUD on screen)"
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)

    show_corrected, show_pair, show_grid = True, False, False
    fps = 0.0
    last = time.perf_counter()

    try:
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                print("Failed to read frame from camera.")
                break
            if args.swap_rb:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            if frame.shape[1::-1] != camera.size:
                # Driver handed back a different size than requested; re-fit maps.
                camera.size = frame.shape[1::-1]
                maps = build_maps(profile, camera.size)

            corrected = undistort(frame, maps)

            if show_pair:
                view = side_by_side(frame, corrected)
            else:
                view = corrected.copy() if show_corrected else frame.copy()

            if show_grid:
                draw_grid(view, 8, 8)

            now = time.perf_counter()
            dt = now - last
            last = now
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt

            mode = "RAW|CORRECTED" if show_pair else ("CORRECTED" if show_corrected else "RAW")
            draw_hud(view, [
                f"PROFILE: {'CALIBRATED' if profile.calibrated else 'ESTIMATED (uncalibrated)'}",
                f"lens FOV {profile.lens_fov_deg:.0f}deg ({profile.fov_reference})  model {profile.model}",
                f"output FOV {profile.output_fov_deg:.0f}deg  {maps.out_size[0]}x{maps.out_size[1]}  scale {profile.output_scale:.2f}",
                f"in {camera.size[0]}x{camera.size[1]}  {fps:5.1f} fps  view {mode}",
            ], warn=not profile.calibrated)

            if args.display_scale != 1.0:
                view = cv2.resize(view, None, fx=args.display_scale, fy=args.display_scale,
                                  interpolation=cv2.INTER_AREA)

            cv2.imshow(window, view)
            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), 27):
                break
            if handle_key(key, profile):
                maps = build_maps(profile, camera.size)
            elif key == ord("u"):
                show_corrected = not show_corrected
            elif key == ord("b"):
                show_pair = not show_pair
            elif key == ord("g"):
                show_grid = not show_grid
            elif key == ord("s"):
                save_snapshot(frame, corrected, profile)
            elif key == ord("r"):
                profile = LensProfile()
                maps = build_maps(profile, camera.size)
            elif key == ord("w"):
                print(f"Wrote lens profile to {profile.save(args.profile)}")

            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Live fisheye-corrected preview — the main camera tool.

Pipeline: camera -> fisheye correction -> rectilinear preview. Nothing else. No
cropping to the workspace, no block detection, no robot coordinates.

The lens parameters are ESTIMATES derived from the vendor's "160 degree" FOV
spec, not a calibration (see vision/fisheye.py for exactly what is assumed). The
HUD says ESTIMATED in amber until real calibration data exists. Tune the
estimates by eye with the keys below, then press 'w' to save them.

    python undistorted_viewer.py
    python undistorted_viewer.py --hq                 # sharpest: full sensor in
    python undistorted_viewer.py --output-fov 140 --output-scale 1.5
    python undistorted_viewer.py --backend v4l2 --device /dev/video0

Keys
----
  q / Esc   quit                        u  toggle correction on/off
  [ / ]     lens FOV -/+ 2 deg          b  toggle raw|corrected side by side
  - / =     output FOV -/+ 5 deg        g  toggle grid overlay (straightness ruler)
  m         cycle projection model      s  save a raw+corrected snapshot
  , / .     output scale -/+ 0.1        i  cycle interpolation kernel
  r         reset to defaults           w  write current params to the profile

Tuning rule: if edges still bow OUTWARD press ']'; if they bow INWARD (over-
corrected) press '['. Get that right before touching 'm'.

Reading the SAMPLE line on the HUD
----------------------------------
It reports source pixels per output pixel: 1.00 is a clean 1:1 transfer, 0.33
means each output pixel was interpolated from a third of a source pixel — empty
magnification, and the reason a corrected frame looks softer than the raw one.
Rectilinear projection stretches the frame edges by roughly 3x at the default
settings, so `edge` is always the number that hurts.

Three things move it, in order of effect:

  1. `--hq` captures the full 2592x1944 sensor readout and renders a 1296x972
     output from it. Same field of view, but twice the linear detail arriving at
     the edges, so `edge` roughly doubles. Costs frame rate (the sensor caps at
     ~15 fps there) and is the only change that adds real detail rather than
     redistributing it.
  2. lowering `--output-scale` (or raising it, if the display is what limits
     you) trades output size against sharpness directly.
  3. `--interp cubic` (the default) resolves an upscale visibly better than
     linear does; `lanczos4` is a smaller step again.

If `raw` already looks soft when you press 'u', none of this will help — check
the lens focus ring and the light level first.
"""

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# This tool lives one folder down, so python/ is not on the import path when it
# is run directly. Put it there before the shared libraries below are imported —
# without this, `python grid/grid_viewer.py` dies on `import vision`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.camera_source import (
    DEFAULT_SIZE,
    FULL_RES_SIZE,
    build_controls,
    describe_sensor_modes,
    open_camera,
)
from vision.fisheye import (
    DEFAULT_INTERPOLATION,
    INTERPOLATIONS,
    MODEL_NAMES,
    PROFILE_PATH,
    LensProfile,
    build_maps,
    sampling_stats,
    undistort,
)
from vision.overlays import draw_grid, draw_info_box
from camera.tk_camera_window import TkCameraWindow

INTERP_NAMES = list(INTERPOLATIONS)

CAPTURE_DIR = Path(__file__).resolve().parents[1] / "captures"


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--backend", choices=["auto", "picamera2", "v4l2"], default="auto")
    parser.add_argument("--device", help="V4L2 path, e.g. /dev/video0 (skips the picker)")
    parser.add_argument("--width", type=int,
                        help=f"capture width (default {DEFAULT_SIZE[0]})")
    parser.add_argument("--height", type=int,
                        help=f"capture height (default {DEFAULT_SIZE[1]})")
    parser.add_argument("--hq", action="store_true",
                        help=f"capture the full {FULL_RES_SIZE[0]}x{FULL_RES_SIZE[1]} "
                             "sensor readout and render a half-size output from it: "
                             "same field of view, ~2x the real detail at the frame "
                             "edges, ~15 fps")
    parser.add_argument("--lens-fov", type=float,
                        help="quoted lens FOV in degrees (default 160)")
    parser.add_argument("--fov-reference", choices=["diagonal", "horizontal"],
                        help="whether --lens-fov is the diagonal or horizontal FOV")
    parser.add_argument("--model", choices=MODEL_NAMES,
                        help="assumed fisheye projection curve (default equidistant)")
    parser.add_argument("--output-fov", type=float,
                        help="diagonal FOV of the rectilinear output, degrees (default 120)")
    parser.add_argument("--output-scale", type=float,
                        help="output size relative to input; >1 keeps centre detail "
                             "when rendering a wide output FOV")
    parser.add_argument("--display-scale", type=float, default=1.0,
                        help="scale the window only; does not affect processing")
    parser.add_argument("--profile", type=Path, default=PROFILE_PATH,
                        help="lens profile JSON to load (and to write with 'w')")
    parser.add_argument("--swap-rb", action="store_true",
                        help="fix inverted red/blue channels")

    quality = parser.add_argument_group(
        "resampling", "how the correction turns source pixels into output pixels")
    quality.add_argument("--interp", choices=INTERP_NAMES, default=DEFAULT_INTERPOLATION,
                         help=f"interpolation kernel (default {DEFAULT_INTERPOLATION})")
    quality.add_argument("--no-mip", action="store_true",
                         help="skip pyramid filtering of the regions the correction "
                              "shrinks. Faster, but those regions alias — visible as "
                              "shimmering on fine texture and on checkerboards")

    sensor = parser.add_argument_group(
        "image quality (Picamera2 only)",
        "controls that decide how much real detail reaches the correction")
    sensor.add_argument("--sharpness", type=float,
                        help="ISP sharpening, 0 = off, 1.0 = default. Worth lowering: "
                             "the correction magnifies sharpening halos too")
    sensor.add_argument("--denoise", choices=["off", "fast", "hq"],
                        help="'fast' (the video default) blurs fine texture away; "
                             "'hq' keeps much more of it")
    sensor.add_argument("--shutter", type=int, metavar="US",
                        help="fixed exposure time in microseconds (disables auto "
                             "exposure). Long auto exposures in dim light are a "
                             "common cause of a mushy preview")
    sensor.add_argument("--gain", type=float,
                        help="fixed analogue gain (disables auto exposure). Pin low "
                             "and add light instead")
    sensor.add_argument("--awb", help="white balance preset, e.g. auto, tungsten, "
                                      "fluorescent, indoor, daylight, cloudy")
    sensor.add_argument("--list-modes", action="store_true",
                        help="print the sensor's modes and exit")
    return parser.parse_args()


def capture_size(args):
    """Resolve the capture resolution from --hq and any explicit --width/--height."""
    default = FULL_RES_SIZE if args.hq else DEFAULT_SIZE
    return (args.width or default[0], args.height or default[1])


def profile_from_args(args):
    """Load the saved profile, then let any explicit CLI flag override it."""
    profile = LensProfile.load(args.profile)
    if args.hq and args.output_scale is None:
        # Render half the capture resolution, so --hq keeps the familiar
        # 1296x972 output but feeds it from four times as many sensor pixels.
        profile.output_scale = 0.5
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


def side_by_side(raw, corrected):
    """Stack raw and corrected at a common height for an A/B comparison.

    They can differ in size when output_scale != 1, so both are fitted to the
    shorter height rather than assumed to match.
    """
    h = min(raw.shape[0], corrected.shape[0])

    def fit(img):
        scale = h / img.shape[0]
        return cv2.resize(img, (max(1, round(img.shape[1] * scale)), h),
                          interpolation=cv2.INTER_AREA)

    left, right = fit(raw), fit(corrected)
    pair = np.hstack([left, right])
    cv2.line(pair, (left.shape[1], 0), (left.shape[1], h), (0, 255, 0), 1)
    return pair


def save_snapshot(raw, corrected, profile):
    """Write both images to captures/, tagging the corrected one with its params.

    The tag matters: comparing several tuning attempts later is impossible if the
    filenames don't record what produced them.
    """
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tag = f"{profile.model}-lens{profile.lens_fov_deg:.0f}-out{profile.output_fov_deg:.0f}"
    raw_path = CAPTURE_DIR / f"{stamp}_raw.png"
    fixed_path = CAPTURE_DIR / f"{stamp}_undistorted_{tag}.png"
    cv2.imwrite(str(raw_path), raw)
    cv2.imwrite(str(fixed_path), corrected)
    print(f"Saved {raw_path.name} and {fixed_path.name} in {CAPTURE_DIR}")


def handle_param_key(key, profile, state):
    """Apply parameter-changing keys. Returns True if the maps need rebuilding.

    `state` carries the settings that live outside the lens profile (currently
    just the interpolation kernel), since those also invalidate the maps.
    """
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
    elif key == ord(","):
        profile.output_scale -= 0.1
    elif key == ord("."):
        profile.output_scale += 0.1
    elif key == ord("i"):
        state["interp"] = INTERP_NAMES[
            (INTERP_NAMES.index(state["interp"]) + 1) % len(INTERP_NAMES)]
    else:
        return False
    profile.clamp()
    return True


def describe_sampling(maps):
    """The HUD's SAMPLE line: where the corrected image loses its sharpness.

    Both numbers are source pixels per output pixel (1.00 = clean 1:1). `edge`
    is the 1st percentile, i.e. the most magnified part of the frame — that is
    what sets how soft the result looks, and it is almost always the corners.
    """
    st = sampling_stats(maps)
    mips = f"  mip x{st['mip_levels']}" if st["mip_levels"] > 1 else ""
    return (f"SAMPLE src px/out px: centre {st['centre']:.2f}  edge {st['edge']:.2f}"
            f"  ({st['upscaled_fraction'] * 100:.0f}% magnified){mips}")


def main():
    args = parse_args()
    profile = profile_from_args(args)
    state = {"interp": args.interp}

    controls = build_controls(args.sharpness, args.denoise, args.shutter,
                              args.gain, args.awb)
    try:
        camera = open_camera(args.backend, capture_size(args), args.device, controls)
    except RuntimeError as exc:
        print(exc)
        sys.exit(1)

    if args.list_modes:
        print("\n".join(describe_sensor_modes(getattr(camera, "sensor_modes", None))))
        camera.release()
        return

    maps = build_maps(profile, camera.size, state["interp"], mip=not args.no_mip)
    print(f"Camera: {camera.name}")
    print(f"Estimated source focal length: {maps.source_focal_px:.1f} px")
    print(f"Output: {maps.out_size[0]}x{maps.out_size[1]} rectilinear, "
          f"f={maps.output_focal_px:.1f} px, {state['interp']} interpolation")
    print(describe_sampling(maps))
    if not args.hq and sampling_stats(maps)["edge"] < 0.5:
        print("Hint: the frame edges are being magnified more than 2x. Try --hq to "
              "feed the correction the full sensor readout instead.")
    if not profile.calibrated:
        print("Profile is ESTIMATED (no checkerboard calibration) — "
              "visually straight, not metric.")
    print(__doc__.split("Keys\n----")[1].split("Tuning rule")[0])

    window = TkCameraWindow(
        "Undistorted Preview", maps.out_size,
        buttons=(("Correction (u)", "u"), ("Raw/Corrected (b)", "b"),
                 ("Grid (g)", "g"), ("Save (s)", "s"),
                 ("Reset (r)", "r"), ("Write profile (w)", "w"),
                 ("Quit (q)", "q")),
    )

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

            # The driver can hand back a size we didn't ask for; the maps are
            # built for one exact input size, so rebuild if it ever changes.
            if frame.shape[1::-1] != camera.size:
                camera.size = frame.shape[1::-1]
                maps = build_maps(profile, camera.size, state["interp"],
                                  mip=not args.no_mip)

            corrected = undistort(frame, maps)

            if show_pair:
                view = side_by_side(frame, corrected)
            else:
                # copy() so the overlays never contaminate the snapshot images.
                view = corrected.copy() if show_corrected else frame.copy()

            if show_grid:
                draw_grid(view, 8, 8)

            # Exponential moving average: a raw instantaneous rate is too jumpy
            # to read off the screen.
            now = time.perf_counter()
            dt, last = now - last, now
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt

            mode = "RAW|CORRECTED" if show_pair else ("CORRECTED" if show_corrected else "RAW")
            window.show(view, [
                f"Profile: {'CALIBRATED' if profile.calibrated else 'ESTIMATED (uncalibrated)'}",
                f"Lens: {profile.lens_fov_deg:.0f}° {profile.fov_reference} | model {profile.model}",
                f"Output: {maps.out_size[0]}x{maps.out_size[1]} | FOV {profile.output_fov_deg:.0f}° | scale {profile.output_scale:.2f}",
                f"Input: {camera.size[0]}x{camera.size[1]} | {fps:5.1f} fps | {state['interp']} | view {mode}",
                describe_sampling(maps),
                "[ / ] lens FOV | -/= output FOV | m model | ,/. scale | i interpolation",
                "u correction | b raw/corrected | g grid | s snapshot | r reset | w write | q/Esc quit",
            ])

            key = window.poll_key()

            if key in (ord("q"), 27):
                break
            if handle_param_key(key, profile, state):
                maps = build_maps(profile, camera.size, state["interp"],
                                  mip=not args.no_mip)
            elif key == ord("u"):
                show_corrected = not show_corrected
            elif key == ord("b"):
                show_pair = not show_pair
            elif key == ord("g"):
                show_grid = not show_grid
            elif key == ord("s"):
                save_snapshot(frame, corrected, profile)
            elif key == ord("r"):
                # Defaults, but keep the framing --hq launched with — resetting
                # to output_scale 1.0 there would resize the window to the full
                # 2592x1944 capture, which is never what 'r' is reached for.
                profile = LensProfile()
                if args.hq and args.output_scale is None:
                    profile.output_scale = 0.5
                maps = build_maps(profile, camera.size, state["interp"],
                                  mip=not args.no_mip)
            elif key == ord("w"):
                print(f"Wrote lens profile to {profile.save(args.profile)}")

            if window.closed:
                break
    finally:
        camera.release()
        window.close()


if __name__ == "__main__":
    main()

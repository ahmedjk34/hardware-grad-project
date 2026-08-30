#!/usr/bin/env python3
"""Look at the printed calibration sheet and prove the grid lands on it.

This is the sheet's equivalent of what ``camera_feed.py`` does for blocks: one
window, the canonical camera pipeline, and an overlay whose only job is to make
a wrong answer obvious. Every mapped cell is tinted and stamped with its
``col,row``; whole cells outside the chosen 10x6 window are outlined in dull
yellow, and cells clipped by the paper edge or the frame edge in red. If the
tint ever drifts off the ink, the calibration is wrong there — which is exactly
what you cannot tell from a residual number alone.

It also runs on a still image, which is how the two training captures were
checked without a rig:

    python/camera/color_grid_check.py --image captures/grid_training/original_image_VERTICAL.jpeg
    python/camera/color_grid_check.py --image ... --save /tmp/checked.png

The camera path uses the same saved settings, lens correction and framing as
``camera_feed.py``, so what this measures is what the other tools see. It never
writes ``config/workspace_map.json`` — calibrating is a deliberate act and
lives behind the ``k`` key in the gridded feed and Rig Build V1.

Keys
----
  l       toggle the col,row labels
  r       toggle the rejected/extra cell outlines
  t       cycle the cell tint: 35% -> 60% -> off
  w       toggle the holder-envelope corners a calibration would save
  h       switch the home convention: firmware <-> printed
  , / .   select the previous / next detected grid window
  s       save the annotated frame next to the captures
  q/Esc   quit
"""

from __future__ import annotations

import argparse
import sys
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import (  # noqa: E402
    CAPTURE_DIR,
    SETTINGS_PATH,
    capture_settings,
    crop_resize,
    colour_from_settings,
    frame_orientation,
    framing_roi,
    load_settings,
    profile_from_settings,
    sensor_from_settings,
)
from camera.tk_camera_window import TkCameraWindow  # noqa: E402
from rig.config import CONFIG_PATH, GRID_MODES, load as load_rig_config  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from vision.camera_source import LatestFramePump, open_camera  # noqa: E402
from vision.color_grid import (  # noqa: E402
    DEFAULT_EDGE_MARGIN,
    DEFAULT_HOME_CONVENTION,
    HOME_CONVENTIONS,
    ColorGridError,
    ColorGridSpec,
)
from vision.combined_grid import detect_printed_grids  # noqa: E402
from vision.color_grid_overlay import (  # noqa: E402
    draw_candidates,
    draw_color_grid,
    draw_grid_alternatives,
    draw_workspace_corners,
    status_text,
)
from vision.fisheye import INTERPOLATIONS, build_maps, undistort  # noqa: E402
from vision.performance import RateMeter  # noqa: E402


TINTS = (0.35, 0.60, 0.0)


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--image", type=Path,
                        help="check a still image instead of opening the camera")
    parser.add_argument("--save", type=Path,
                        help="with --image: write the annotated result here and exit")
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH,
                        help=f"camera settings JSON (default: {SETTINGS_PATH})")
    parser.add_argument("--rig-config", type=Path, default=CONFIG_PATH,
                        help=f"grid geometry JSON (default: {CONFIG_PATH})")
    parser.add_argument("--mode", choices=GRID_MODES, default=None,
                        help="printed-sheet layout to check (default: "
                             "rig.json's grid.active_mode)")
    parser.add_argument("--home-convention", choices=HOME_CONVENTIONS,
                        default=DEFAULT_HOME_CONVENTION,
                        help="where the machine origin sits on the sheet "
                             f"(default: {DEFAULT_HOME_CONVENTION})")
    parser.add_argument("--grid-window", type=int, default=1, metavar="N",
                        help="initial detected grid window, 1-based (default: 1)")
    parser.add_argument("--edge-margin", type=float, default=DEFAULT_EDGE_MARGIN,
                        metavar="F",
                        help="legacy plain sheet: how far a whole cell must stay "
                             "from the frame border, as a fraction of its own "
                             f"size (default: {DEFAULT_EDGE_MARGIN}); 0 keeps every cell")
    parser.add_argument("--page-plane-min", type=int, default=None, metavar="N",
                        help="combined A2 target: fiducials that must support the "
                             "page plane before it can calibrate (default 76/80); "
                             "lower it for a rig that always crops the outer ring")
    parser.add_argument("--min-saturation", type=int, default=None, metavar="S",
                        help="combined A2 target: ink saturation floor for the "
                             "faded passes; lower it (e.g. 8) for a strong "
                             "uncorrected camera cast")
    parser.add_argument("--process-width", type=int, default=0,
                        help="detection working width; 0 uses the full frame "
                             "(default: 0 for stills, 1024 for the camera)")
    parser.add_argument("--detect-hz", type=float, default=4.0,
                        help="how often to re-detect the sheet (default: 4)")
    parser.add_argument("--display-scale", type=float, default=1.0)
    parser.add_argument("--opencv-threads", type=int, default=2)
    return parser.parse_args()


def combined_kwargs(args):
    """Combined-A2 knobs, passed only when the operator overrode a default."""
    kwargs = {}
    if args.min_saturation is not None:
        kwargs["min_saturation"] = args.min_saturation
    if args.page_plane_min is not None:
        kwargs["page_plane_min"] = args.page_plane_min
    return kwargs


def report(calibration, grid, convention):
    """Print the numbers a human needs to decide whether to trust the fit."""
    metrics = calibration.metrics
    sheet_description = getattr(calibration, "target_description", None)
    if sheet_description is None:
        sheet_description = calibration.spec.describe()
    lattice_summary = (
        f"{metrics.components} colour blobs, {metrics.assigned} assigned; "
        f"8x10 projected map, {len(calibration.found_cells)} physically found"
        if getattr(calibration, "is_combined", False) else
        f"{metrics.components} colour blobs, {metrics.assigned} on the lattice, "
        f"{metrics.lattice_shape[0]}x{metrics.lattice_shape[1]} whole"
    )
    lines = [
        f"Sheet: {sheet_description}",
        f"Fit:   {calibration.describe()}",
        f"       {lattice_summary}",
        f"       measured cell aspect {metrics.measured_aspect:.3f} "
        f"(printed {max(calibration.spec.block_x_cm, calibration.spec.block_y_cm) / min(calibration.spec.block_x_cm, calibration.spec.block_y_cm):.3f})",
        f"       processing size {metrics.processing_size[0]}x{metrics.processing_size[1]}"
        f" of {metrics.input_size[0]}x{metrics.input_size[1]}",
    ]
    if getattr(calibration, "is_combined", False):
        votes = calibration.orientation_votes
        lines.append(
            f"       decoded orientation {calibration.orientation}; "
            f"cells vertical={votes['vertical']}, "
            f"horizontal={votes['horizontal']}, "
            f"ambiguous={votes['ambiguous']}; "
            f"confidence={calibration.orientation_confidence * 100:.1f}%"
        )
        pattern_line = (
            f"       measured {grid.mode} patterns="
            f"{len(calibration.patterns)}/80; "
            f"unobserved/partial={calibration.unobserved_patterns}"
        )
        if grid.mode == "horizontal":
            pattern_line += (
                f"; fallback beige middles="
                f"{calibration.inferred_horizontal_cells}")
        lines.append(pattern_line)
        requested_count = votes[grid.mode]
        lines.append(
            f"       requested {grid.mode} layer: present "
            f"({requested_count} exclusive fiducials)"
        )
    try:
        corners = calibration.workspace_corners(grid, convention)
    except ColorGridError as exc:
        lines.append(f"Envelope: NOT CALIBRATABLE FROM THIS FRAME — {exc}")
    else:
        lines.append(f"Envelope corners ({convention} home convention):")
        for name, point in zip(("home [0,0]", "far-X/home-Y", "far-X/far-Y",
                                "home-X/far-Y"), corners):
            lines.append(
                f"       {name:>14}  ({point[0]:8.2f}, {point[1]:8.2f}) px")
    for line in lines:
        print(line)


def annotate(frame, calibration, grid, ui, hover=None):
    """Draw the whole overlay onto a copy of ``frame`` and return it."""
    display = frame.copy()
    draw_grid_alternatives(display, ui.get("calibrations", ()),
                           ui.get("selection", 0))
    hovered = draw_color_grid(display, calibration, hover=hover,
                              labels=ui["labels"], shade=TINTS[ui["tint"]],
                              show_rejected=ui["rejected"])
    if ui["envelope"]:
        try:
            draw_workspace_corners(
                display, calibration.workspace_corners(grid, ui["convention"]))
        except ColorGridError:
            pass
    return display, hovered


def run_still(args, spec, grid):
    frame = cv2.imread(str(args.image))
    if frame is None:
        print(f"Cannot read {args.image}", file=sys.stderr)
        return 1
    print(f"{args.image.name}: {frame.shape[1]}x{frame.shape[0]}")
    ui = {"labels": True, "rejected": True, "tint": 0, "envelope": True,
          "convention": args.home_convention, "selection": args.grid_window - 1}
    try:
        calibrations = detect_printed_grids(
            frame, spec, process_width=args.process_width,
            edge_margin=args.edge_margin, **combined_kwargs(args))
        if ui["selection"] >= len(calibrations):
            raise ColorGridError(
                f"grid window {args.grid_window} requested, but only "
                f"{len(calibrations)} candidate(s) were detected",
                stage="selection")
        ui["calibrations"] = calibrations
        calibration = calibrations[ui["selection"]]
    except ColorGridError as exc:
        # Still render. A refusal with the blobs drawn says which of "no sheet",
        # "wrong colours" and "not enough whole cells" happened; a bare error
        # line and a blank window do not.
        print(f"REFUSED at the {exc.stage} stage: {exc}", file=sys.stderr)
        display = frame.copy()
        failed_calibration = getattr(exc, "calibration", None)
        if failed_calibration is not None:
            # Geometry and stripe decoding succeeded; only mode authorization
            # failed. Show the actual mutually exclusive signatures instead of
            # degrading this into a generic contour-failure picture.
            draw_color_grid(display, failed_calibration, labels=True, shade=0.0)
        else:
            draw_candidates(display, exc)
        if args.save:
            args.save.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(args.save), display)
            print(f"Saved the failed detection to {args.save}")
        else:
            _show(display)
        return 1
    report(calibration, grid, args.home_convention)

    display, _ = annotate(frame, calibration, grid, ui)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.save), display)
        print(f"Saved {args.save}")
        return 0

    _show(display)
    return 0


def _show(display, window="Printed grid check"):
    cv2.imshow(window, display)
    while True:
        key = cv2.waitKey(50) & 0xFF
        if key in (ord("q"), 27):
            break
        if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
            break
    cv2.destroyAllWindows()


def run_camera(args, spec, grid):
    try:
        camera_data = load_settings(args.settings)
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
    print(f"Sheet:  {spec.describe()}")

    ui = {"labels": True, "rejected": True, "tint": 0, "envelope": True,
          "convention": args.home_convention, "hover": None, "message": "looking",
          "selection": args.grid_window - 1, "calibrations": ()}

    def on_mouse(event, point):
        if event == "move" and point is not None:
            ui["hover"] = point

    try:
        window = TkCameraWindow(
            f"Printed Grid Check - {camera.name}", size,
            display_scale=args.display_scale, mouse_callback=on_mouse,
            buttons=(("Labels (l)", "l"), ("Rejected (r)", "r"),
                     ("Tint (t)", "t"), ("Envelope (w)", "w"),
                     ("Home mode (h)", "h"), ("Save (s)", "s"),
                     ("Grid choice < (,)", ","), ("Grid choice > (.)", "."),
                     ("Quit (q)", "q")),
        )
    except (tk.TclError, cv2.error) as exc:
        print(f"Cannot open the camera UI: {exc}", file=sys.stderr)
        camera.release()
        return 1

    pump = LatestFramePump(camera)
    pump.start()
    maps = None
    input_size = None
    last_sequence = 0
    calibration = None
    failure = None
    error = "waiting for a frame"
    last_detect = 0.0
    interval = 1.0 / max(args.detect_hz, 0.1)
    process_width = args.process_width or 1024
    rate = RateMeter()
    last_display = None

    def status_lines(hovered):
        return [
            f"Camera: {camera.name} | preview {rate.rate:5.1f} fps | "
            f"detect {args.detect_hz:.1f} Hz target",
            status_text(calibration, error),
            f"Home convention: {ui['convention']} | envelope "
            f"{'shown' if ui['envelope'] else 'hidden'} | tint "
            f"{TINTS[ui['tint']]:.0%} | labels {'on' if ui['labels'] else 'off'}",
            f"Hover: {f'[{hovered[0]},{hovered[1]}]' if hovered else 'none'} | "
            f"{ui['message']}",
            "l labels | r rejected | t tint | w envelope | h home | ,/. grid | s save | q quit",
        ]

    def handle_key(key):
        if key in (ord("q"), 27):
            return False
        if key == ord("l"):
            ui["labels"] = not ui["labels"]
        elif key == ord("r"):
            ui["rejected"] = not ui["rejected"]
        elif key == ord("t"):
            ui["tint"] = (ui["tint"] + 1) % len(TINTS)
        elif key == ord("w"):
            ui["envelope"] = not ui["envelope"]
        elif key == ord("h"):
            index = HOME_CONVENTIONS.index(ui["convention"])
            ui["convention"] = HOME_CONVENTIONS[(index + 1) % len(HOME_CONVENTIONS)]
            ui["message"] = f"home convention: {ui['convention']}"
        elif key in (ord(","), ord(".")):
            if not ui["calibrations"]:
                ui["message"] = "no grid candidate is available"
            else:
                delta = -1 if key == ord(",") else 1
                ui["selection"] = (ui["selection"] + delta) % len(ui["calibrations"])
                ui["message"] = (f"selected grid {ui['selection'] + 1}/"
                                 f"{len(ui['calibrations'])}")
        elif key == ord("s"):
            if last_display is None:
                ui["message"] = "no frame to save"
            else:
                CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                path = CAPTURE_DIR / f"{stamp}_paper_grid.png"
                if not cv2.imwrite(str(path), last_display):
                    ui["message"] = f"save failed: {path}"
                    print(f"Could not save {path}", file=sys.stderr)
                else:
                    path = path.resolve()
                    ui["message"] = f"saved: {path}"
                    print(f"Saved {path}")
        return True

    try:
        while True:
            snapshot = pump.snapshot()
            if snapshot.frame is None or snapshot.sequence == last_sequence:
                window.pump(status_lines(None))
                key = window.poll_key()
                if (key >= 0 and not handle_key(key)) or window.closed:
                    return 0
                continue
            last_sequence = snapshot.sequence

            frame = colour.apply(frame_orientation(snapshot.frame, capture))
            if maps is None or frame.shape[1::-1] != input_size:
                maps = build_maps(profile, frame.shape[1::-1], interpolation,
                                  mip=mip, roi=roi)
                input_size = frame.shape[1::-1]
            view = (undistort(frame, maps) if enabled
                    else crop_resize(frame, roi, maps.out_size, interpolation))

            now = time.monotonic()
            if now - last_detect >= interval:
                last_detect = now
                try:
                    calibrations = detect_printed_grids(
                        view, spec, process_width=process_width,
                        edge_margin=args.edge_margin, **combined_kwargs(args))
                    ui["calibrations"] = calibrations
                    if ui["selection"] < len(calibrations):
                        calibration = calibrations[ui["selection"]]
                        error, failure = None, None
                    else:
                        calibration, failure = None, None
                        error = (f"selected grid {ui['selection'] + 1} temporarily "
                                 f"unavailable; {len(calibrations)} detected")
                except ColorGridError as exc:
                    calibration, failure = None, exc
                    error = str(exc)

            hovered = None
            if calibration is not None:
                display, hovered = annotate(view, calibration, grid, ui, ui["hover"])
            else:
                # Never show a bare frame. Whatever the detector did find is
                # drawn, so "nothing happens" can never be the whole report.
                display = view.copy()
                if failure is not None:
                    draw_candidates(display, failure, labels=ui["labels"])
            last_display = display
            window.show(display, status_lines(hovered))
            rate.tick()
            key = window.poll_key()
            if (key >= 0 and not handle_key(key)) or window.closed:
                return 0
    finally:
        if pump.stop():
            camera.release()
        window.close()


def main():
    args = parse_args()
    if args.save and not args.image:
        print("--save only applies with --image", file=sys.stderr)
        return 1
    if (args.display_scale <= 0 or args.opencv_threads <= 0
            or args.detect_hz <= 0 or args.grid_window <= 0):
        print("display-scale, opencv-threads and detect-hz must be positive",
              file=sys.stderr)
        return 1
    if not 0 <= args.edge_margin <= 1:
        print("edge-margin must be between 0 and 1", file=sys.stderr)
        return 1
    cv2.setNumThreads(args.opencv_threads)

    try:
        rig_data = load_rig_config(args.rig_config, reload=True)
        grid = MachineGrid.from_config(rig_data, mode=args.mode)
        spec = ColorGridSpec.from_config(rig_data, mode=grid.mode)
    except (KeyError, TypeError, ValueError, SystemExit) as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.image:
        return run_still(args, spec, grid)
    return run_camera(args, spec, grid)


if __name__ == "__main__":
    raise SystemExit(main())

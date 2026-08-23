#!/usr/bin/env python3
"""Rig Build V1: camera grid cell selection -> confirmed Arduino B command.

This combines ``gridded_camera_feed.py`` with ``rig.link.Rig``. A left click on
a grid selects one cell; it does not move the machine. Press Enter or
``b`` to send the exact command shown in the build panel, normally
``B <col> <row> <level>``. The firmware performs the pick-and-place sequence.
For motor calibration, ``--build-target 0 5`` skips X and ``--build-target
17 0`` skips Y; ``--build-target 0 0`` is an inert firmware no-op.

Safety rules
------------
* The built-in approximate grid is immediately selectable; ``c`` is optional.
* Click selects; Enter/``b`` is the separate confirmation that moves hardware.
* The build runs on its own worker thread so the camera keeps streaming, but the
  UI refuses every state change until that build reports back: clicks and
  commands still cannot queue mid-build, and only one build exists at a time.
* ABORTED, cable/reset, or timeout locks the session. Inspect the rig and restart;
  this program never retries or automatically homes an unknown machine.

Keys
----
  c       calibrate/recalibrate the four machine-envelope corners
  Enter   save the reviewed four-corner calibration
  u       undo the most recent calibration corner
  x       cancel calibration without deleting the previous map
  g       toggle grid
  [ / ]   build level down/up
  o       cycle rotation: NR -> R -> RR
  d       clear selected cell
  b/Enter confirm the displayed B command
  s       save annotated frame and block detection JSON
  q/Esc   quit (only while no build is running)
"""

from __future__ import annotations

import argparse
import sys
import time
import tkinter as tk
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import (  # noqa: E402
    SETTINGS_PATH,
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
from camera.gridded_camera_feed import (  # noqa: E402
    approximate_workspace,
    draw_machine_grid,
    load_workspace,
    projection_metadata,
)
from camera.tk_camera_window import TkCameraWindow  # noqa: E402
from rig.build_controller import (  # noqa: E402
    BuildController,
    BuildStateError,
    ROTATIONS,
)
from rig.build_job import BUSY_MESSAGE, BuildJob  # noqa: E402
from rig.config import CONFIG_PATH, load as load_rig_config  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from rig.link import ABORTED, PLACED, REJECTED, Rig, RigError  # noqa: E402
from rig.workspace import CORNER_NAMES, WORKSPACE_MAP_PATH, WorkspaceMap  # noqa: E402
from vision.block_detector import detect_blocks  # noqa: E402
from vision.camera_source import LatestFramePump, open_camera  # noqa: E402
from vision.fisheye import INTERPOLATIONS, build_maps, undistort  # noqa: E402


SELECTED_COLOR = (255, 80, 255)
CAMERA_STALE_AFTER_S = 0.75


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH,
                        help=f"camera settings JSON (default: {SETTINGS_PATH})")
    parser.add_argument("--rig-config", type=Path, default=CONFIG_PATH,
                        help=f"serial/grid/workspace JSON (default: {CONFIG_PATH})")
    parser.add_argument("--workspace-map", type=Path, default=WORKSPACE_MAP_PATH,
                        help=f"four-corner calibration JSON (default: {WORKSPACE_MAP_PATH})")
    parser.add_argument("--level", type=int, default=0,
                        help="initial build level Z argument (default: 0/ground)")
    parser.add_argument("--rotation", choices=ROTATIONS, default="NR",
                        help="initial optional rotation (default: NR)")
    parser.add_argument("--build-target", nargs=2, type=int, metavar=("COL", "ROW"),
                        help="initial B target; each coordinate allows 0 for "
                             "calibration (0 0 is a no-op)")
    parser.add_argument("--connect-timeout", type=float, default=25.0,
                        help="seconds to wait for the Mega boot banner")
    parser.add_argument("--build-timeout", type=float, default=300.0,
                        help="maximum seconds to wait for one complete build")
    parser.add_argument("--display-scale", type=float, default=1.0,
                        help="scale only the display window; mapping stays at feed size")
    parser.add_argument("--color-threshold", type=int, default=8,
                        help="minimum red-minus-blue value for a block (default: 8)")
    parser.add_argument("--min-area", type=int, default=500,
                        help="minimum detected block area in feed pixels (default: 500)")
    parser.add_argument("--no-enhance", action="store_true",
                        help="disable display contrast/sharpness enhancement")
    return parser.parse_args()


def draw_selected_cell(frame, workspace, selected):
    # Zero is a valid firmware calibration coordinate, but it is not a camera
    # cell and therefore has no polygon to draw.
    if selected is None or 0 in selected:
        return
    polygon = np.asarray(
        workspace.cell_polygon(*selected, frame.shape[1::-1]),
        dtype=np.float32,
    ).round().astype(np.int32)
    cv2.polylines(frame, [polygon], True, SELECTED_COLOR, 4, cv2.LINE_AA)


def camera_state(snapshot, now):
    """Short, operator-facing truth about camera freshness."""
    age = snapshot.age_s(now)
    if age is None:
        return "WAITING FOR FIRST FRAME"
    if age >= CAMERA_STALE_AFTER_S:
        return f"STALE — last frame {age:.1f}s ago (#{snapshot.sequence})"
    return f"LIVE #{snapshot.sequence} ({age * 1000:.0f} ms old)"


def camera_is_live(snapshot, now):
    """Whether this image is recent enough to safely choose a machine cell."""
    age = snapshot.age_s(now)
    return age is not None and age < CAMERA_STALE_AFTER_S


def result_message(result):
    if str(result) == PLACED:
        return "PLACED safely; select the next cell"
    if str(result) == REJECTED:
        return f"REJECTED safely: {result.reason or 'firmware refused the command'}"
    if str(result) == ABORTED:
        return f"ABORTED: {result.reason or 'machine state unknown'}"
    return f"firmware returned {result!r}"


def outcome_message(outcome, controller):
    """One status line for a finished :class:`BuildJob`."""
    if outcome.result is not None:
        return result_message(outcome.result)
    return controller.locked_reason or str(outcome.error)


def main():
    args = parse_args()
    if (args.level < 0 or args.display_scale <= 0 or args.min_area <= 0
            or args.connect_timeout <= 0 or args.build_timeout <= 0):
        print("level must be >= 0 and timeout/display/min-area values must be positive",
              file=sys.stderr)
        return 1

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

    rig = Rig(
        cfg=rig_data,
        on_line=lambda line: print(f"[rig] {line}"),
        on_error=lambda error: print(f"[rig error] {error}", file=sys.stderr),
    )
    try:
        print(f"Connecting to rig at {rig.port_name} / {rig.baud} baud...")
        rig.connect(timeout=args.connect_timeout)
    except RigError as exc:
        print(f"Cannot start Rig Build V1: {exc}", file=sys.stderr)
        rig.close()
        return 1

    controller = BuildController(rig, level=args.level, rotation=args.rotation)
    job = BuildJob(controller, args.build_timeout)

    try:
        camera = open_camera(backend, size, device)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        rig.close()
        return 1

    applied, skipped = camera.apply(sensor)
    if skipped:
        print("Sensor settings unavailable: " + "; ".join(skipped))
    print(f"Camera: {camera.name}")
    print(f"Loaded camera settings: {args.settings}")
    print(f"Loaded rig config: {args.rig_config}")
    print(f"Grid: {grid.describe()}")
    print(f"Sensor settings: {len(applied)} applied")

    # Keep the potentially blocking Picamera2/V4L2 read out of this UI thread.
    # A motor-induced CSI stall must leave the operator with a responsive window
    # and an explicit stale-frame warning, not a silent frozen image.
    frame_pump = LatestFramePump(camera)
    frame_pump.start()

    saved_workspace, rejection = load_workspace(args.workspace_map, grid, projection)
    if rejection:
        print(f"Grid calibration unavailable: {rejection}")
        print("Using the selectable approximate grid; press c only to refine it.")
    else:
        print(f"Loaded workspace calibration: {args.workspace_map}")

    window = f"Rig Build V1 - {camera.name} - {rig.port_name}"
    ui = {
        "hover": None,
        "pending_select": None,
        "calibrating": False,
        "calibration_points": [],
        "pending_points": None,
        "show_grid": True,
        "message": "connected; click a grid cell",
    }
    if args.build_target is not None:
        try:
            controller.select(tuple(args.build_target))
        except BuildStateError as exc:
            print(f"Invalid --build-target: {exc}", file=sys.stderr)
            rig.close()
            return 1
        ui["message"] = (f"calibration target [{args.build_target[0]},"
                          f"{args.build_target[1]}] selected; confirm command")

    def allow_window_close():
        if job.running:
            ui["message"] = "build in progress; cannot quit until it reports"
            return False
        return True

    def on_mouse(event, point):
        if point is None:
            return
        if event == "move":
            ui["hover"] = point
        elif event == "click":
            if ui["calibrating"]:
                if len(ui["calibration_points"]) < 4:
                    ui["calibration_points"].append(point)
            else:
                ui["pending_select"] = point

    try:
        window = TkCameraWindow(
            f"Rig Build V1 - {camera.name} - {rig.port_name}", size,
            display_scale=args.display_scale, mouse_callback=on_mouse,
            close_request=allow_window_close,
            buttons=(("Calibrate (c)", "c"), ("Undo (u)", "u"),
                     ("Grid (g)", "g"), ("Level - ([)", "["),
                     ("Level + (])", "]"), ("Rotate (o)", "o"),
                     ("Deselect (d)", "d"), ("BUILD (b)", "b"),
                     ("Save (s)", "s"), ("Quit (q)", "q")),
        )
    except tk.TclError as exc:
        print(f"Cannot open the Tk rig window: {exc}", file=sys.stderr)
        if frame_pump.stop():
            camera.release()
        rig.close()
        return 1
    maps = None
    input_size = None
    fps = 0.0
    last = time.perf_counter()
    status = 0
    try:
        while True:
            snapshot = frame_pump.snapshot()
            now = time.monotonic()
            frame = snapshot.frame
            if frame is None:
                # The capture thread may be blocked in its first camera read.
                # Keep this window alive so the condition is visible and it can
                # still be closed safely rather than appearing to have hung.
                w, h = camera.size
                waiting = np.zeros((h, w, 3), dtype=np.uint8)
                window.show(waiting, [
                    f"Camera: {camera.name}",
                    f"Camera: {camera_state(snapshot, now)}",
                    f"Error: {snapshot.error or 'waiting for first frame'}",
                    f"Rig: {rig.port_name} | build: {'running' if job.running else 'idle'}",
                    "q/Esc quits when no build is running",
                ])
                key = window.poll_key()
                if key in (ord("q"), 27) or window.closed:
                    if job.running:
                        ui["message"] = "build in progress; cannot quit until it reports"
                    else:
                        break
                continue

            finished = job.poll()
            if finished is not None:
                ui["message"] = outcome_message(finished, controller)
                print(f"[build] {'LOCKED: ' if finished.locked else ''}{ui['message']}",
                      file=sys.stderr if finished.locked else sys.stdout)
            building = job.running

            frame = frame_orientation(frame, capture)
            if maps is None or frame.shape[1::-1] != input_size:
                maps = build_maps(profile, frame.shape[1::-1], interpolation,
                                  mip=mip, roi=roi)
                input_size = frame.shape[1::-1]

            view = undistort(frame, maps) if enabled else \
                crop_resize(frame, roi, maps.out_size, interpolation)
            image_size = view.shape[1::-1]

            if ui["pending_points"] is not None:
                try:
                    if not camera_is_live(snapshot, now):
                        raise ValueError("calibration paused: camera feed is stale")
                    candidate = WorkspaceMap.from_grid(
                        grid, ui["pending_points"], image_size, projection
                    )
                    candidate.save(args.workspace_map)
                    saved_workspace = candidate
                    rejection = None
                    controller.clear_selection()
                    ui["message"] = "calibration saved; click a grid cell"
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

            if ui["pending_select"] is not None:
                point = ui["pending_select"]
                ui["pending_select"] = None
                try:
                    if building:
                        raise BuildStateError(BUSY_MESSAGE)
                    if not camera_is_live(snapshot, now):
                        raise BuildStateError(
                            "camera feed is stale; wait for live frames before selecting"
                        )
                    if not ui["show_grid"]:
                        raise BuildStateError("grid is hidden; press g before selecting")
                    cell = workspace.cell_at(point, image_size)
                    if cell is None:
                        raise BuildStateError("click is outside the packed block grid")
                    controller.select(cell)
                    ui["message"] = f"selected [{cell[0]},{cell[1]}]; confirm shown command"
                except BuildStateError as exc:
                    ui["message"] = str(exc)

            fps_now = time.perf_counter()
            dt, last = fps_now - last, fps_now
            if dt > 0:
                instant = 1.0 / dt
                fps = 0.9 * fps + 0.1 * instant if fps else instant
            detections = detect_blocks(view, color_threshold=args.color_threshold,
                                       min_area=args.min_area)
            display = view.copy() if args.no_enhance else enhance_for_display(view)
            display = draw_block_overlay(
                display, detections, ui["hover"], None,
                "COORDS: corrected pixels + selectable machine grid",
                show_info=False,
            )
            if ui["show_grid"]:
                draw_machine_grid(display, workspace, grid, ui["hover"], calibrated)
                draw_selected_cell(display, workspace, controller.selected)
            # Calibration/build/camera-health feedback is shown in the Tk panel;
            # only grid, selected-cell, and block geometry remain on the image.

            selected = controller.selected
            selected_text = (
                f"Selected: [{selected[0]},{selected[1]}] | command: {controller.command}"
                if selected is not None else "Selected: none")
            last_result = controller.last_result
            result_text = f"Last result: {last_result}" if last_result else "Last result: none"
            lock_text = controller.locked_reason if controller.locked else "unlocked"
            window.show(display, [
                f"Camera: {camera.name} | feed {image_size[0]}x{image_size[1]} | {fps:5.1f} fps",
                f"Camera state: {camera_state(snapshot, now)} | blocks detected: {len(detections)}",
                f"Grid: {grid.cols}x{grid.rows} | {'CALIBRATED' if calibrated else 'APPROXIMATION ONLY'}",
                f"Rig: {rig.port_name} | level {controller.level} | rotation {controller.rotation}",
                selected_text,
                f"Build state: {'RUNNING' if building else ('LOCKED' if controller.locked else 'READY')} | {ui['message']}",
                result_text,
                (f"Calibration: REVIEW 4/4 — press Enter to save"
                 if ui["calibrating"] and len(ui["calibration_points"]) == 4 else
                 (f"Calibration: active {len(ui['calibration_points'])}/4; next: "
                  f"{CORNER_NAMES[len(ui['calibration_points'])]}"
                  if ui["calibrating"] else "Calibration: inactive")
                 + f" | {lock_text}"),
                "c calibrate | Enter save | u undo | x cancel | g grid | [/] level | o rotate | d deselect",
                "b/Enter BUILD | s snapshot | q/Esc quit when safe",
            ])
            key = window.poll_key()
            if key in (ord("q"), 27):
                if building:
                    ui["message"] = "build in progress; cannot quit until it reports"
                else:
                    break
            elif key == ord("c"):
                if building:
                    ui["message"] = BUSY_MESSAGE
                elif not camera_is_live(snapshot, now):
                    ui["message"] = "camera feed is stale; cannot calibrate"
                elif controller.locked:
                    ui["message"] = controller.locked_reason
                else:
                    controller.clear_selection()
                    ui["calibrating"] = True
                    ui["calibration_points"] = []
                    ui["pending_points"] = None
                    ui["message"] = "click the four prompted envelope corners"
            elif key == ord("x") and ui["calibrating"]:
                ui["calibrating"] = False
                ui["calibration_points"] = []
                ui["pending_points"] = None
                ui["message"] = "calibration cancelled; previous map retained"
            elif key == ord("u") and ui["calibrating"]:
                if ui["calibration_points"]:
                    ui["calibration_points"].pop()
                    ui["message"] = "removed the most recent calibration corner"
                else:
                    ui["message"] = "no calibration corner to undo"
            elif key in (10, 13) and ui["calibrating"]:
                if len(ui["calibration_points"]) == 4:
                    ui["pending_points"] = list(ui["calibration_points"])
                    ui["message"] = "saving reviewed four-corner calibration"
                else:
                    ui["message"] = "click all four named corners before saving"
            elif key == ord("g"):
                ui["show_grid"] = not ui["show_grid"]
            elif key in (ord("["), ord("-")):
                if building:
                    ui["message"] = BUSY_MESSAGE
                else:
                    controller.adjust_level(-1)
                    ui["message"] = f"build level set to {controller.level}"
            elif key in (ord("]"), ord("+"), ord("=")):
                if building:
                    ui["message"] = BUSY_MESSAGE
                else:
                    controller.adjust_level(1)
                    ui["message"] = f"build level set to {controller.level}"
            elif key == ord("o"):
                if building:
                    ui["message"] = BUSY_MESSAGE
                else:
                    controller.cycle_rotation()
                    ui["message"] = f"rotation set to {controller.rotation}"
            elif key == ord("d"):
                if building:
                    ui["message"] = BUSY_MESSAGE
                else:
                    controller.clear_selection()
                    ui["message"] = "selection cleared"
            elif key == ord("s"):
                image_path, data_path = save_detection_snapshot(display, detections)
                print(f"Saved {image_path} and {data_path}")
            elif key in (ord("b"), 10, 13):
                try:
                    if building:
                        raise BuildStateError(BUSY_MESSAGE)
                    if not camera_is_live(snapshot, now):
                        raise BuildStateError(
                            "camera feed is stale; restore live frames before building"
                        )
                    if ui["calibrating"]:
                        raise BuildStateError("finish or cancel (x) calibration first")
                    command = controller.command
                    job.start()
                    ui["message"] = f"BUILDING: {command}"
                    print(f"[build] sending {command}")
                except BuildStateError as exc:
                    ui["message"] = str(exc)

            if window.closed:
                break
    finally:
        if job.running:
            print("Waiting for the in-flight build before closing the serial port...")
            job.join()
            finished = job.poll()
            if finished is not None:
                print(f"[build] {outcome_message(finished, controller)}")
        if frame_pump.stop():
            camera.release()
        else:
            # Releasing Picamera2 while its capture thread is stuck can itself
            # hang or crash.  It is a daemon thread, so process shutdown is the
            # safer owner of this exceptional cleanup path.
            print("Camera capture is still blocked; leaving it for process shutdown.",
                  file=sys.stderr)
        window.close()
        rig.close()
    return status


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Rig Build V1: calibrated camera cell selection -> confirmed Arduino B command.

This combines ``gridded_camera_feed.py`` with ``rig.link.Rig``. A left click on
a CALIBRATED grid selects one cell; it does not move the machine. Press Enter or
``b`` to send the exact command shown in the build panel, normally
``B <col> <row> <level>``. The firmware performs the pick-and-place sequence.

Safety rules
------------
* An amber approximate grid cannot select a build target. Calibrate with ``c``.
* Click selects; Enter/``b`` is the separate confirmation that moves hardware.
* The build call is synchronous, so clicks and commands cannot queue mid-build.
* ABORTED, cable/reset, or timeout locks the session. Inspect the rig and restart;
  this program never retries or automatically homes an unknown machine.

Keys
----
  c       calibrate/recalibrate the four machine-envelope corners
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
    draw_calibration,
    draw_grid_status,
    draw_machine_grid,
    load_workspace,
    projection_metadata,
)
from rig.build_controller import (  # noqa: E402
    BuildController,
    BuildStateError,
    ROTATIONS,
)
from rig.config import CONFIG_PATH, load as load_rig_config  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from rig.link import ABORTED, PLACED, REJECTED, Rig, RigError  # noqa: E402
from rig.workspace import WORKSPACE_MAP_PATH, WorkspaceMap  # noqa: E402
from vision.block_detector import detect_blocks  # noqa: E402
from vision.camera_source import open_camera  # noqa: E402
from vision.fisheye import INTERPOLATIONS, build_maps, undistort  # noqa: E402
from vision.overlays import HOVER_COLOR, draw_info_box  # noqa: E402


SELECTED_COLOR = (255, 80, 255)


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
    if selected is None:
        return
    polygon = np.asarray(
        workspace.cell_polygon(*selected, frame.shape[1::-1]),
        dtype=np.float32,
    ).round().astype(np.int32)
    cv2.polylines(frame, [polygon], True, SELECTED_COLOR, 4, cv2.LINE_AA)


def draw_build_panel(frame, controller, port_name, message, building=False):
    if controller.locked:
        state = "LOCKED — HUMAN INSPECTION REQUIRED"
    elif building:
        state = "BUILDING — SERIAL INPUT LOCKED"
    elif controller.selected is not None:
        state = "SELECTED — PRESS b OR ENTER TO CONFIRM"
    else:
        state = "READY — CLICK A CALIBRATED CELL"

    command = controller.command or "B <select col> <select row> <level>"
    last = "none"
    if controller.last_result is not None:
        last = str(controller.last_result)
        if controller.last_result.reason:
            last += f": {controller.last_result.reason}"
    lines = [
        f"RIG BUILD V1: {state}",
        f"serial {port_name} | level {controller.level} | rotation {controller.rotation}",
        f"next command: {command}",
        f"status: {message}",
        f"last result: {last}",
        "[ / ] level | o rotation | d deselect | b/Enter BUILD",
    ]
    width = min(600, frame.shape[1] - 8)
    draw_info_box(
        frame,
        lines,
        origin=(4, max(4, frame.shape[0] - 116)),
        width=width,
        scale=0.39,
        highlight_first=controller.locked or building,
    )


def result_message(result):
    if str(result) == PLACED:
        return "PLACED safely; select the next cell"
    if str(result) == REJECTED:
        return f"REJECTED safely: {result.reason or 'firmware refused the command'}"
    if str(result) == ABORTED:
        return f"ABORTED: {result.reason or 'machine state unknown'}"
    return f"firmware returned {result!r}"


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

    saved_workspace, rejection = load_workspace(args.workspace_map, grid, projection)
    if rejection:
        print(f"Grid calibration unavailable: {rejection}")
        print("Press c and click the four prompted corners before selecting a build.")
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
        "message": "connected; select a calibrated cell",
    }

    def on_mouse(event, x, y, _flags, state):
        point = (x / args.display_scale, y / args.display_scale)
        if event == cv2.EVENT_MOUSEMOVE:
            state["hover"] = point
        elif event == cv2.EVENT_LBUTTONDOWN:
            if state["calibrating"]:
                if len(state["calibration_points"]) < 4:
                    state["calibration_points"].append(point)
                if len(state["calibration_points"]) == 4:
                    state["pending_points"] = list(state["calibration_points"])
            else:
                state["pending_select"] = point

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
                maps = build_maps(profile, frame.shape[1::-1], interpolation,
                                  mip=mip, roi=roi)
                input_size = frame.shape[1::-1]

            view = undistort(frame, maps) if enabled else \
                crop_resize(frame, roi, maps.out_size, interpolation)
            image_size = view.shape[1::-1]

            if ui["pending_points"] is not None:
                try:
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
                    if not ui["show_grid"]:
                        raise BuildStateError("grid is hidden; press g before selecting")
                    cell = workspace.cell_at(point, image_size)
                    if cell is None:
                        raise BuildStateError("click is outside the packed block grid")
                    controller.select(cell, calibrated=calibrated)
                    ui["message"] = f"selected [{cell[0]},{cell[1]}]; confirm shown command"
                except BuildStateError as exc:
                    ui["message"] = str(exc)

            now = time.perf_counter()
            dt, last = now - last, now
            if dt > 0:
                instant = 1.0 / dt
                fps = 0.9 * fps + 0.1 * instant if fps else instant
            detections = detect_blocks(view, color_threshold=args.color_threshold,
                                       min_area=args.min_area)
            display = view.copy() if args.no_enhance else enhance_for_display(view)
            display = draw_block_overlay(
                display, detections, ui["hover"], fps,
                "COORDS: corrected pixels + selectable machine grid",
            )
            if ui["show_grid"]:
                draw_machine_grid(display, workspace, grid, ui["hover"], calibrated)
                draw_selected_cell(display, workspace, controller.selected)
                draw_grid_status(display, grid, calibrated, rejection, enabled)
            if ui["calibrating"]:
                draw_calibration(display, ui["calibration_points"])
            else:
                draw_build_panel(display, controller, rig.port_name, ui["message"])

            shown = cv2.resize(
                display, None, fx=args.display_scale, fy=args.display_scale,
                interpolation=cv2.INTER_AREA,
            ) if args.display_scale != 1.0 else display

            cv2.imshow(window, shown)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                return 0
            if key == ord("c"):
                if controller.locked:
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
            elif key == ord("g"):
                ui["show_grid"] = not ui["show_grid"]
            elif key in (ord("["), ord("-")):
                controller.adjust_level(-1)
                ui["message"] = f"build level set to {controller.level}"
            elif key in (ord("]"), ord("+"), ord("=")):
                controller.adjust_level(1)
                ui["message"] = f"build level set to {controller.level}"
            elif key == ord("o"):
                controller.cycle_rotation()
                ui["message"] = f"rotation set to {controller.rotation}"
            elif key == ord("d"):
                controller.clear_selection()
                ui["message"] = "selection cleared"
            elif key == ord("s"):
                image_path, data_path = save_detection_snapshot(display, detections)
                print(f"Saved {image_path} and {data_path}")
            elif key in (ord("b"), 10, 13):
                try:
                    command = controller.command
                    if command is None:
                        raise BuildStateError("select a calibrated grid cell first")
                    ui["message"] = f"BUILDING: {command}"
                    busy_display = view.copy() if args.no_enhance else \
                        enhance_for_display(view)
                    busy_display = draw_block_overlay(
                        busy_display, detections, ui["hover"], fps,
                        "COORDS: corrected pixels + selectable machine grid",
                    )
                    if ui["show_grid"]:
                        draw_machine_grid(
                            busy_display, workspace, grid, ui["hover"], calibrated
                        )
                        draw_selected_cell(busy_display, workspace, controller.selected)
                        draw_grid_status(
                            busy_display, grid, calibrated, rejection, enabled
                        )
                    draw_build_panel(
                        busy_display, controller, rig.port_name, ui["message"],
                        building=True,
                    )
                    busy_shown = cv2.resize(
                        busy_display, None, fx=args.display_scale,
                        fy=args.display_scale, interpolation=cv2.INTER_AREA,
                    ) if args.display_scale != 1.0 else busy_display
                    cv2.imshow(window, busy_shown)
                    cv2.waitKey(1)
                    print(f"[build] sending {command}")
                    result = controller.build(timeout=args.build_timeout)
                    ui["message"] = result_message(result)
                    print(f"[build] {ui['message']}")
                except BuildStateError as exc:
                    ui["message"] = str(exc)
                except RigError as exc:
                    ui["message"] = controller.locked_reason or str(exc)
                    print(f"[build] LOCKED: {ui['message']}", file=sys.stderr)

            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                return 0
    finally:
        camera.release()
        cv2.destroyAllWindows()
        rig.close()


if __name__ == "__main__":
    raise SystemExit(main())

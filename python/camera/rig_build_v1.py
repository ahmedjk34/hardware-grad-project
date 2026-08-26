#!/usr/bin/env python3
"""Rig Build V1: camera grid cell selection -> confirmed Arduino B command.

This combines ``gridded_camera_feed.py`` with ``rig.link.Rig``. A left click on
a grid cell selects it; it does not move the machine. Press Enter or ``b`` to
send the exact command shown in the build panel, normally
``B <col> <row> <level>``. The firmware performs the pick-and-place sequence.

Coordinates span col ``0..9`` and row ``0..5``. ``[1,1]`` through
``[9,5]`` are separated block footprints; ``[0,0]``/``[col,0]``/``[0,row]``
are holder home and its two axis-only target families. ``0`` on an axis means
"leave that axis at the origin" - the firmware's own single-axis move:
``B 0 5`` skips X, ``B 9 0`` skips Y,
``G 0 0`` is the home command, and ``B 0 0`` is an inert no-op. ``x``/``y``
type the same targets from the keyboard as an alternative to clicking.

Safety rules
------------
* The built-in approximate grid is immediately selectable; ``c`` is optional.
* Either calibration route may refine it: ``c`` with four clicks, or ``k`` from
  the printed two-colour sheet. Both write the same ``config/workspace_map.json``
  and both are refused while a build is running.
* Click selects; Enter/``b`` is the separate confirmation that moves hardware.
* The build runs on its own worker thread so the camera keeps streaming, but the
  UI refuses every state change until that build reports back: clicks and
  commands still cannot queue mid-build, and only one build exists at a time.
* ABORTED, cable/reset, or timeout locks the session. Inspect the rig and restart;
  this program never retries or automatically homes an unknown machine.

Keys
----
  c       calibrate/recalibrate: click the four prompted corners
  Enter   save the reviewed four-corner calibration
  u       undo the most recent calibration corner
  x       cancel calibration (while calibrating); otherwise pick an X-only
          build target: type a column, Enter confirms B <col> 0, any other
          key cancels the entry
  y       pick a Y-only build target: type a row, Enter confirms B 0 <row>,
          any other key cancels the entry
  p       toggle the printed colour-grid overlay
  , / .   select the previous / next detected printed-grid window
  k       calibrate from the printed colour grid and save
  g       toggle grid
  v       toggle block detection on/off
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
from camera.gridded_camera_feed import (  # noqa: E402
    PAPER_GRID_HZ,
    PaperGridTracker,
    approximate_workspace,
    draw_calibration,
    draw_machine_grid,
    draw_paper_grid,
    load_workspace,
    paper_workspace_map,
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
from vision.analysis_worker import AnalysisWorker  # noqa: E402
from vision.block_detector import detect_blocks  # noqa: E402
from vision.camera_source import LatestFramePump, open_camera  # noqa: E402
from vision.color_grid import (  # noqa: E402
    DEFAULT_HOME_CONVENTION,
    HOME_CONVENTIONS,
    ColorGridError,
    ColorGridSpec,
)
from vision.fisheye import INTERPOLATIONS, build_maps, undistort  # noqa: E402
from vision.performance import RateMeter, StageTimings  # noqa: E402


SELECTED_COLOR = (255, 80, 255)
CAMERA_STALE_AFTER_S = STALE_FRAME_AFTER_S


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
    parser.add_argument("--enhance", action="store_true",
                        help="enable costly software contrast/sharpness enhancement")
    parser.add_argument("--no-enhance", action="store_false", dest="enhance",
                        help=argparse.SUPPRESS)
    parser.add_argument("--overlay", choices=OVERLAY_MODES, default="geometry")
    parser.add_argument("--home-convention", choices=HOME_CONVENTIONS,
                        default=DEFAULT_HOME_CONVENTION,
                        help="where the machine origin sits on the printed sheet "
                             f"(default: {DEFAULT_HOME_CONVENTION})")
    parser.add_argument("--paper-hz", type=float, default=PAPER_GRID_HZ,
                        help=f"printed-sheet detection rate (default: {PAPER_GRID_HZ})")
    parser.add_argument("--analysis-hz", type=float, default=10.0)
    parser.add_argument("--opencv-threads", type=int, default=2)
    return parser.parse_args()


def draw_selected_cell(frame, workspace, selected):
    """Highlight the pending build target - always one full block-sized cell.

    Positive selections use the exact 2.2x7.5 cm block footprint. Axis-only
    selections are centred on their real zero axis; [0,0] visualizes home.
    """
    if selected is None:
        return
    col, row = selected
    image_size = frame.shape[1::-1]
    polygon = np.asarray(
        workspace.target_polygon(col, row, image_size),
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
            or args.connect_timeout <= 0 or args.build_timeout <= 0
            or args.analysis_hz <= 0 or args.opencv_threads <= 0
            or args.paper_hz <= 0):
        print("level must be >= 0 and timeout/display/min-area/rate values must "
              "be positive", file=sys.stderr)
        return 1
    cv2.setNumThreads(args.opencv_threads)

    try:
        camera_data = load_settings(args.settings)
        rig_data = load_rig_config(args.rig_config, reload=True)
        grid = MachineGrid.from_config(rig_data)
        paper_spec = ColorGridSpec.from_config(rig_data)
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
        "overlay": args.overlay,
        "detect_enabled": True,
        "axis_pick": None,
        "axis_buffer": "",
        "paper_calibrate": False,
        "message": "connected; click a grid cell",
    }
    paper = PaperGridTracker(paper_spec, max_hz=args.paper_hz)
    if args.build_target is not None:
        try:
            controller.select(tuple(args.build_target))
        except BuildStateError as exc:
            print(f"Invalid --build-target: {exc}", file=sys.stderr)
            if frame_pump.stop():
                camera.release()
            rig.close()
            return 1
        ui["message"] = (f"calibration target [{args.build_target[0]},"
                          f"{args.build_target[1]}] selected; confirm command")

    def allow_window_close():
        if job.running:
            ui["message"] = "build in progress; cannot quit until it reports"
            return False
        return True

    forbidden_during_build = {
        ord("c"), ord("k"), ord("u"), ord("x"), ord("y"), ord("["), ord("-"),
        ord("]"), ord("+"), ord("="), ord("o"), ord("d"), ord(","), ord("."),
        ord("b"), ord("q"), 10, 13, 27,
    }

    def allow_key(key):
        if job.running and key in forbidden_during_build:
            ui["message"] = ("build in progress; cannot quit until it reports"
                             if key in (ord("q"), 27) else BUSY_MESSAGE)
            return False
        return True

    def on_mouse(event, point):
        if point is None:
            return
        if event == "move":
            ui["hover"] = point
        elif event == "click":
            # Reject at callback time, not one loop later. Otherwise a click in
            # the final milliseconds of a build could remain pending until
            # job.poll() marks it finished and then become a real selection.
            if job.running:
                ui["message"] = BUSY_MESSAGE
                return
            if controller.locked:
                ui["message"] = controller.locked_reason
                return
            if ui["calibrating"]:
                if len(ui["calibration_points"]) < 4:
                    ui["calibration_points"].append(point)
            else:
                ui["pending_select"] = point

    try:
        window = TkCameraWindow(
            f"Rig Build V1 - {camera.name} - {rig.port_name}", size,
            display_scale=args.display_scale, mouse_callback=on_mouse,
            close_request=allow_window_close, key_filter=allow_key,
            buttons=(("Overlay (i)", "i"), ("Calibrate (c)", "c"),
                     ("Undo (u)", "u"),
                     ("Grid (g)", "g"), ("Detect (v)", "v"),
                     ("Level - ([)", "["),
                     ("Level + (])", "]"), ("Rotate (o)", "o"),
                     ("Deselect (d)", "d"), ("X-only (x)", "x"),
                     ("Y-only (y)", "y"),
                     ("Paper grid (p)", "p"), ("Paper calib (k)", "k"),
                     ("Grid choice < (,)", ","), ("Grid choice > (.)", "."),
                     ("BUILD (b)", "b"),
                     ("Save (s)", "s"), ("Quit (q)", "q")),
        )
    except (tk.TclError, cv2.error) as exc:
        print(f"Cannot open the rig camera UI: {exc}", file=sys.stderr)
        if frame_pump.stop():
            camera.release()
        rig.close()
        return 1
    analysis = AnalysisWorker(detect_blocks, max_hz=args.analysis_hz)
    snapshots = SnapshotWorker(save_detection_snapshot)
    analysis.start()
    paper.start()
    maps = None
    input_size = None
    image_size = None
    workspace = None
    calibrated = False
    map_generation = 0
    last_sequence = 0
    last_display = None
    detections = ()
    capture_rate, preview_rate = RateMeter(), RateMeter()
    timings = StageTimings()
    snapshot_count = 0
    status = 0

    def reject_mutation_if_unsafe():
        if job.running:
            raise BuildStateError(BUSY_MESSAGE)
        if controller.locked:
            raise BuildStateError(controller.locked_reason)

    DIGIT_KEYS = tuple(ord(d) for d in "0123456789")

    def handle_key(key, snapshot, now):
        if key in (ord("q"), 27):
            if job.running:
                ui["message"] = "build in progress; cannot quit until it reports"
                return True
            return False
        if ui["axis_pick"] is not None:
            if key in DIGIT_KEYS:
                if len(ui["axis_buffer"]) < 3:
                    ui["axis_buffer"] += chr(key)
                return True
            if key == 8:  # Backspace
                ui["axis_buffer"] = ui["axis_buffer"][:-1]
                return True
            if key in (10, 13):
                axis = ui["axis_pick"]
                ui["axis_pick"] = None
                try:
                    reject_mutation_if_unsafe()
                    if not ui["axis_buffer"]:
                        raise BuildStateError("type a column/row number before Enter")
                    value = int(ui["axis_buffer"])
                    cell = (value, 0) if axis == "col" else (0, value)
                    controller.select(cell)
                    ui["message"] = f"selected [{cell[0]},{cell[1]}]; confirm shown command"
                except BuildStateError as exc:
                    ui["message"] = str(exc)
                ui["axis_buffer"] = ""
                return True
            # Any other key abandons the in-progress entry.
            ui["axis_pick"] = None
            ui["axis_buffer"] = ""
            ui["message"] = "axis entry cancelled"
        if key == ord("i"):
            ui["overlay"] = OVERLAY_MODES[
                (OVERLAY_MODES.index(ui["overlay"]) + 1) % len(OVERLAY_MODES)]
            ui["message"] = f"overlay: {ui['overlay']}"
        elif key == ord("g"):
            ui["show_grid"] = not ui["show_grid"]
        elif key == ord("v"):
            ui["detect_enabled"] = not ui["detect_enabled"]
            ui["message"] = f"block detection {'on' if ui['detect_enabled'] else 'off'}"
        elif key == ord("p"):
            ui["message"] = ("printed-sheet overlay on" if paper.toggle()
                             else "printed-sheet overlay off")
        elif key in (ord(","), ord(".")):
            try:
                reject_mutation_if_unsafe()
                if paper.cycle(-1 if key == ord(",") else 1):
                    controller.clear_selection()
                    ui["message"] = (f"selected printed grid {paper.selection + 1}/"
                                     f"{len(paper.calibrations)}")
                else:
                    ui["message"] = "only one printed-grid candidate is available"
            except BuildStateError as exc:
                ui["message"] = str(exc)
        elif key == ord("k"):
            # Same guards as the four-click route: it replaces the very map the
            # operator is about to select build targets on.
            try:
                reject_mutation_if_unsafe()
                if not camera_is_live(snapshot, now):
                    raise BuildStateError("camera feed is stale; cannot calibrate")
                if ui["calibrating"]:
                    raise BuildStateError("finish or cancel (x) the click "
                                          "calibration first")
                controller.clear_selection()
                ui["paper_calibrate"] = True
                ui["message"] = "calibrating from the printed sheet"
            except BuildStateError as exc:
                ui["message"] = str(exc)
        elif key == ord("c"):
            try:
                reject_mutation_if_unsafe()
                if not camera_is_live(snapshot, now):
                    raise BuildStateError("camera feed is stale; cannot calibrate")
                controller.clear_selection()
                ui["calibrating"] = True
                ui["calibration_points"] = []
                ui["pending_points"] = None
                ui["message"] = "click the four prompted corners"
            except BuildStateError as exc:
                ui["message"] = str(exc)
        elif key == ord("x") and ui["calibrating"]:
            if job.running:
                ui["message"] = BUSY_MESSAGE
            else:
                ui["calibrating"] = False
                ui["calibration_points"] = []
                ui["pending_points"] = None
                ui["message"] = "calibration cancelled; previous map retained"
        elif key == ord("u") and ui["calibrating"]:
            if job.running:
                ui["message"] = BUSY_MESSAGE
            elif ui["calibration_points"]:
                ui["calibration_points"].pop()
                ui["message"] = "removed the most recent calibration corner"
            else:
                ui["message"] = "no calibration corner to undo"
        elif key in (10, 13) and ui["calibrating"]:
            if job.running:
                ui["message"] = BUSY_MESSAGE
            elif len(ui["calibration_points"]) == 4:
                ui["pending_points"] = list(ui["calibration_points"])
                ui["message"] = "saving reviewed four-corner calibration"
            else:
                ui["message"] = "click all four named corners before saving"
        elif key == ord("x") and not ui["calibrating"]:
            try:
                reject_mutation_if_unsafe()
                ui["axis_pick"] = "col"
                ui["axis_buffer"] = ""
                ui["message"] = (f"type X-only column (0..{grid.cols}), Enter "
                                 "confirms, any other key cancels")
            except BuildStateError as exc:
                ui["message"] = str(exc)
        elif key == ord("y"):
            try:
                reject_mutation_if_unsafe()
                ui["axis_pick"] = "row"
                ui["axis_buffer"] = ""
                ui["message"] = (f"type Y-only row (0..{grid.rows}), Enter "
                                 "confirms, any other key cancels")
            except BuildStateError as exc:
                ui["message"] = str(exc)
        elif key in (ord("["), ord("-"), ord("]"), ord("+"), ord("=")):
            try:
                reject_mutation_if_unsafe()
                delta = -1 if key in (ord("["), ord("-")) else 1
                controller.adjust_level(delta)
                ui["message"] = f"build level set to {controller.level}"
            except BuildStateError as exc:
                ui["message"] = str(exc)
        elif key == ord("o"):
            try:
                reject_mutation_if_unsafe()
                controller.cycle_rotation()
                ui["message"] = f"rotation set to {controller.rotation}"
            except BuildStateError as exc:
                ui["message"] = str(exc)
        elif key == ord("d"):
            try:
                reject_mutation_if_unsafe()
                controller.clear_selection()
                ui["message"] = "selection cleared"
            except BuildStateError as exc:
                ui["message"] = str(exc)
        elif key == ord("s"):
            if last_display is None:
                ui["message"] = "no frame is available to save"
            elif snapshots.submit(last_display.copy(), tuple(detections)):
                ui["message"] = "saving snapshot in background"
            else:
                ui["message"] = "snapshot writer busy; try again shortly"
        elif key in (ord("b"), 10, 13):
            try:
                reject_mutation_if_unsafe()
                if not camera_is_live(snapshot, now):
                    raise BuildStateError(
                        "camera feed is stale; restore live frames before building")
                if ui["calibrating"]:
                    raise BuildStateError("finish or cancel (x) calibration first")
                command = controller.command
                job.start()
                ui["message"] = f"BUILDING: {command}"
                print(f"[build] sending {command}")
            except BuildStateError as exc:
                ui["message"] = str(exc)
        return True

    def status_lines(snapshot, result, now):
        selected = controller.selected
        selected_text = (f"[{selected[0]},{selected[1]}] | {controller.command}"
                         if selected is not None else "none")
        result_age = result.age_s(now)
        analysis_text = ("waiting" if result.completed_at is None else
                         f"{result.duration_s * 1000:.1f} ms / "
                         f"age {result_age * 1000:.0f} ms")
        size_text = f"{image_size[0]}x{image_size[1]}" if image_size else "waiting"
        calibration_text = (
            ("REVIEW 4/4 — Enter saves" if len(ui["calibration_points"]) == 4 else
             f"active {len(ui['calibration_points'])}/4 — next: "
             f"{CORNER_NAMES[len(ui['calibration_points'])]}")
            if ui["calibrating"] else "inactive")
        build_state = ("RUNNING" if job.running else
                       ("LOCKED" if controller.locked else "READY"))
        axis_text = ("inactive" if ui["axis_pick"] is None else
                     f"{'X-only col' if ui['axis_pick'] == 'col' else 'Y-only row'} "
                     f"= {ui['axis_buffer'] or '_'}")
        return [
            f"Camera: {camera.name} | {camera_state(snapshot, now)} | capture {capture_rate.rate:5.1f} fps",
            f"Feed: {size_text} | preview {preview_rate.rate:5.1f} fps | overlay {ui['overlay']}",
            f"Analysis: {'OFF' if not ui['detect_enabled'] else f'{result.rate_hz:4.1f} Hz'} | "
            f"seq {result.source_sequence} | {analysis_text} | blocks {len(detections)} | "
            f"replaced {result.replaced_count} | duplicate {result.duplicate_count}",
            f"Grid: {grid.cols}x{grid.rows} | {'CALIBRATED' if calibrated else 'APPROXIMATION ONLY'}",
            f"{paper.status()} | ,/. choose | home {args.home_convention}",
            f"Rig: {rig.port_name} | level {controller.level} | rotation {controller.rotation}",
            f"Selected: {selected_text}",
            block_hover_text(detections, ui["hover"]),
            f"Build: {build_state} | {ui['message']}",
            f"Calibration: {calibration_text} | "
            f"{controller.locked_reason or 'session unlocked'}",
            f"Axis-only pick: {axis_text}",
            f"Stages: remap {timings.ms.get('remap', 0):.1f} ms | "
            f"overlay {timings.ms.get('overlay', 0):.1f} ms | "
            f"grid {timings.ms.get('grid', 0):.1f} ms | "
            f"display {timings.ms.get('display', 0):.1f} ms",
            "i overlay | c calibrate | g grid | v detect | [/] level | o rotate | d deselect",
            "p paper | ,/. choose grid | k paper calibrate | x X-only | y Y-only",
            "b/Enter BUILD | s snapshot | q/Esc quit when safe",
        ]

    try:
        while True:
            snapshot = frame_pump.snapshot()
            now = time.monotonic()
            finished = job.poll()
            if finished is not None:
                ui["message"] = outcome_message(finished, controller)
                print(f"[build] {'LOCKED: ' if finished.locked else ''}{ui['message']}",
                      file=sys.stderr if finished.locked else sys.stdout)

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

            new_frame = snapshot.frame is not None and snapshot.sequence != last_sequence
            if new_frame:
                last_sequence = snapshot.sequence
                capture_rate.tick()
                frame = colour.apply(frame_orientation(snapshot.frame, capture))
                if maps is None or frame.shape[1::-1] != input_size:
                    maps = build_maps(profile, frame.shape[1::-1], interpolation,
                                      mip=mip, roi=roi)
                    input_size = frame.shape[1::-1]
                    map_generation += 1
                started = time.perf_counter()
                view = undistort(frame, maps) if enabled else \
                    crop_resize(frame, roi, maps.out_size, interpolation)
                timings.observe("remap", time.perf_counter() - started)
                image_size = view.shape[1::-1]
                workspace = saved_workspace or approximate_workspace(
                    grid, image_size, projection)
                calibrated = saved_workspace is not None
                view.flags.writeable = False
                if ui["detect_enabled"]:
                    analysis.submit(view, snapshot.sequence, map_generation,
                                    color_threshold=args.color_threshold,
                                    min_area=args.min_area)
                paper.submit(view, snapshot.sequence, map_generation)
            paper.poll(map_generation)

            if ui["paper_calibrate"]:
                ui["paper_calibrate"] = False
                try:
                    reject_mutation_if_unsafe()
                    if image_size is None or not camera_is_live(snapshot, now):
                        raise ValueError("calibration paused: camera feed is stale")
                    candidate, found = paper_workspace_map(
                        view, paper_spec, grid, projection,
                        args.home_convention, paper.selection)
                    candidate.save(args.workspace_map)
                    saved_workspace = candidate
                    workspace = candidate
                    calibrated = True
                    rejection = None
                    controller.clear_selection()
                    ui["message"] = f"sheet calibration saved: {found.describe()}"
                    print(f"Saved workspace calibration from the printed sheet: "
                          f"{args.workspace_map}")
                    print(f"  {found.describe()} "
                          f"({args.home_convention} home convention)")
                except (BuildStateError, ColorGridError, OSError, ValueError) as exc:
                    rejection = f"sheet calibration rejected: {exc}"
                    ui["message"] = rejection
                    print(rejection, file=sys.stderr)

            if ui["pending_points"] is not None and image_size is not None:
                try:
                    reject_mutation_if_unsafe()
                    if not camera_is_live(snapshot, now):
                        raise ValueError("calibration paused: camera feed is stale")
                    candidate = WorkspaceMap.from_grid(
                        grid, ui["pending_points"], image_size, projection)
                    candidate.save(args.workspace_map)
                    saved_workspace = candidate
                    workspace = candidate
                    calibrated = True
                    rejection = None
                    controller.clear_selection()
                    ui["message"] = "calibration saved; click a grid cell"
                    print(f"Saved workspace calibration: {args.workspace_map}")
                except (BuildStateError, OSError, ValueError) as exc:
                    rejection = f"calibration rejected: {exc}"
                    ui["message"] = rejection
                    print(rejection, file=sys.stderr)
                ui["pending_points"] = None
                ui["calibrating"] = False
                ui["calibration_points"] = []

            if ui["pending_select"] is not None and workspace is not None:
                point = ui["pending_select"]
                ui["pending_select"] = None
                try:
                    reject_mutation_if_unsafe()
                    if not camera_is_live(snapshot, now):
                        raise BuildStateError(
                            "camera feed is stale; wait for live frames before selecting")
                    if not ui["show_grid"]:
                        raise BuildStateError("grid is hidden; press g before selecting")
                    cell = workspace.cell_at(point, image_size)
                    if cell is None and workspace.has_physical_grid:
                        # The origin margin: [col,0], [0,row] or [0,0] - not a
                        # block cell, but a real B/G axis-only target.
                        cell = workspace.axis_lane_at(point, image_size)
                    if cell is None:
                        raise BuildStateError("click is outside the grid or its origin margin")
                    controller.select(cell)
                    ui["message"] = f"selected [{cell[0]},{cell[1]}]; confirm shown command"
                except BuildStateError as exc:
                    ui["message"] = str(exc)

            if new_frame:
                display = enhance_for_display(view) if args.enhance else view.copy()
                started = time.perf_counter()
                draw_block_overlay(
                    display, detections, ui["hover"], None,
                    "COORDS: corrected pixels + selectable machine grid",
                    show_info=False, mode=ui["overlay"])
                timings.observe("overlay", time.perf_counter() - started)
                started = time.perf_counter()
                if ui["show_grid"] and ui["overlay"] != "off":
                    draw_machine_grid(
                        display, workspace, ui["hover"], calibrated,
                        detail=ui["overlay"] == "detail")
                    draw_selected_cell(display, workspace, controller.selected)
                if paper.enabled:
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
                window.show(display, status_lines(snapshot, result, now))
                timings.observe("display", time.perf_counter() - started)
                preview_rate.tick()
            else:
                window.pump(status_lines(snapshot, result, now))

            key = window.poll_key()
            if key >= 0 and not handle_key(key, snapshot, now):
                break
            if window.closed:
                break
    finally:
        if job.running:
            print("Waiting for the in-flight build before closing the serial port...")
            job.join()
            finished = job.poll()
            if finished is not None:
                print(f"[build] {outcome_message(finished, controller)}")
        analysis.stop()
        paper.stop()
        snapshots.stop(finish=True)
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

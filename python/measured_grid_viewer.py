#!/usr/bin/env python3
"""Grid overlay labelled in real-world CENTIMETRES instead of pixels.

Assumes the full camera frame spans a known physical rectangle, then converts
pixel bounds to cm/m by simple linear scaling. Hovering a cell shows its pixel
bounds plus real-world start/end and size per axis.

    python measured_grid_viewer.py                          # uses the defaults below
    python measured_grid_viewer.py --frame-width-cm 60 --frame-height-cm 30

IMPORTANT — this is only valid on an undistorted image
------------------------------------------------------
Linear pixels-to-cm scaling assumes the camera is an ideal flat projection. The
raw 160-degree fisheye is nothing of the sort: centimetres per pixel grows
sharply toward the edges, so numbers away from the centre will read short. Treat
these figures as approximate, and as meaningless at the frame edges until the
feed is both undistorted and properly calibrated.

(Was tests/grid_viewer_35cm_vertical_20cm_horizontal.py — it is a measurement
tool rather than a test, so it now lives with the other tools.)
"""

import argparse
import sys

import cv2

from rig import config as rig_config
from vision.camera_source import DEFAULT_SIZE, open_camera
from vision.overlays import draw_cell_info, draw_grid, hovered_cell

# Physical span of the *whole frame*, measured by hand. Edit it in
# config/rig.json (or pass the flags) whenever the camera height or mounting
# changes — undistorted_grid_viewer.py reads the same two numbers.
FRAME_CM = rig_config.load()["frame"]

state = {"mouse_x": -1, "mouse_y": -1}


def on_mouse(event, x, y, flags, userdata):
    state["mouse_x"] = x
    state["mouse_y"] = y


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--backend", choices=["auto", "picamera2", "v4l2"], default="auto")
    parser.add_argument("--device", help="V4L2 path, e.g. /dev/video0 (skips the picker)")
    parser.add_argument("--width", type=int, default=DEFAULT_SIZE[0])
    parser.add_argument("--height", type=int, default=DEFAULT_SIZE[1])
    parser.add_argument("--rows", type=int, default=8)
    parser.add_argument("--cols", type=int, default=8)
    parser.add_argument("--frame-width-cm", type=float, default=FRAME_CM["width_cm"])
    parser.add_argument("--frame-height-cm", type=float, default=FRAME_CM["height_cm"])
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        camera = open_camera(args.backend, (args.width, args.height), args.device)
    except RuntimeError as exc:
        print(exc)
        sys.exit(1)

    window = (
        f"Grid Viewer [{args.frame_width_cm:.0f}cm x {args.frame_height_cm:.0f}cm] "
        f"- {camera.name}"
    )
    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)

    print(f"Camera: {camera.name}")
    print(f"Grid calibrated to {args.frame_width_cm}cm (X) x {args.frame_height_cm}cm (Y).")
    print("Hover a cell to inspect it, 'q'/Esc to quit.")

    try:
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                print("Failed to read frame from camera.")
                break

            h, w = frame.shape[:2]
            cell_w, cell_h = draw_grid(frame, args.rows, args.cols)

            # Recomputed each frame: the driver may hand back a different size
            # than requested, which would change the scale factor.
            cm_per_px_x = args.frame_width_cm / w
            cm_per_px_y = args.frame_height_cm / h

            cell = hovered_cell(state["mouse_x"], state["mouse_y"],
                                w, h, cell_w, cell_h, args.rows, args.cols)
            if cell:
                row, col, x1, y1, x2, y2 = cell
                x1_cm, x2_cm = x1 * cm_per_px_x, x2 * cm_per_px_x
                y1_cm, y2_cm = y1 * cm_per_px_y, y2 * cm_per_px_y
                w_cm, h_cm = x2_cm - x1_cm, y2_cm - y1_cm

                draw_cell_info(frame, cell, [
                    f"cell (row={row}, col={col})",
                    f"px:  ({x1},{y1}) -> ({x2},{y2})",
                    f"X: {x1_cm:.2f}cm -> {x2_cm:.2f}cm  (w={w_cm:.2f}cm / {w_cm / 100:.4f}m)",
                    f"Y: {y1_cm:.2f}cm -> {y2_cm:.2f}cm  (h={h_cm:.2f}cm / {h_cm / 100:.4f}m)",
                ], width=320)

            cv2.imshow(window, frame)
            if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                break
            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

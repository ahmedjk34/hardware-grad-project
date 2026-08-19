#!/usr/bin/env python3
"""Camera preview with a hoverable grid overlay, labelled in PIXELS.

Splits the frame into an 8x8 grid; hovering a cell reports its row/col index and
pixel bounds. Useful for reading off image coordinates and for eyeballing how
badly the fisheye bends straight edges.

For real-world centimetres instead of pixels, use measured_grid_viewer.py.

    python grid_viewer.py
    python grid_viewer.py --rows 6 --cols 12

Press 'q' or Esc in the window to quit.
"""

import argparse
import sys
from pathlib import Path

import cv2

# This tool lives one folder down, so python/ is not on the import path when it
# is run directly. Put it there before the shared libraries below are imported —
# without this, `python grid/grid_viewer.py` dies on `import vision`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.camera_source import DEFAULT_SIZE, open_camera
from vision.overlays import draw_cell_info, draw_grid, hovered_cell

# OpenCV mouse callbacks can't return values, so the cursor position is parked
# here for the render loop to pick up.
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
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        camera = open_camera(args.backend, (args.width, args.height), args.device)
    except RuntimeError as exc:
        print(exc)
        sys.exit(1)

    window = f"Grid Viewer - {camera.name}"
    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)

    print(f"Camera: {camera.name}")
    print("Streaming with grid overlay... hover a cell to inspect it, 'q'/Esc to quit.")

    try:
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                print("Failed to read frame from camera.")
                break

            h, w = frame.shape[:2]
            cell_w, cell_h = draw_grid(frame, args.rows, args.cols)

            cell = hovered_cell(state["mouse_x"], state["mouse_y"],
                                w, h, cell_w, cell_h, args.rows, args.cols)
            if cell:
                row, col, x1, y1, x2, y2 = cell
                draw_cell_info(frame, cell, [
                    f"cell (row={row}, col={col})",
                    f"start: ({x1}, {y1})",
                    f"end:   ({x2}, {y2})",
                    f"size:  {x2 - x1} x {y2 - y1}",
                ], width=220)

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

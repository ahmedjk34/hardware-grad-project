#!/usr/bin/env python3
"""Grid viewer calibrated to a known physical frame size.

Assumes the full camera frame spans FRAME_WIDTH_CM across X (horizontal)
and FRAME_HEIGHT_CM across Y (vertical). Hovering a block shows its pixel
bounds plus real-world start/end and size in cm and meters, for both axes.
"""

import sys
from pathlib import Path

import cv2

DEBUGGING_DIR = Path(__file__).resolve().parent.parent / "debugging"
sys.path.insert(0, str(DEBUGGING_DIR))

from camera_viewer import list_camera_devices, choose_device
from grid_viewer import draw_grid, hovered_cell, GRID_ROWS, GRID_COLS, HOVER_COLOR, TEXT_COLOR, TEXT_BG_COLOR

FRAME_WIDTH_CM = 20.0   # horizontal (X) span of the full frame
FRAME_HEIGHT_CM = 35.0  # vertical (Y) span of the full frame

state = {"mouse_x": -1, "mouse_y": -1}


def on_mouse(event, x, y, flags, userdata):
    state["mouse_x"] = x
    state["mouse_y"] = y


def px_to_cm(px, total_px, total_cm):
    return px / total_px * total_cm


def draw_hover_info(frame, cell, cm_per_px_x, cm_per_px_y):
    row, col, x1, y1, x2, y2 = cell
    cv2.rectangle(frame, (x1, y1), (x2 - 1, y2 - 1), HOVER_COLOR, 2)

    x1_cm, x2_cm = x1 * cm_per_px_x, x2 * cm_per_px_x
    y1_cm, y2_cm = y1 * cm_per_px_y, y2 * cm_per_px_y
    w_cm, h_cm = x2_cm - x1_cm, y2_cm - y1_cm

    lines = [
        f"cell (row={row}, col={col})",
        f"px:  ({x1},{y1}) -> ({x2},{y2})",
        f"X: {x1_cm:.2f}cm -> {x2_cm:.2f}cm  (w={w_cm:.2f}cm / {w_cm / 100:.4f}m)",
        f"Y: {y1_cm:.2f}cm -> {y2_cm:.2f}cm  (h={h_cm:.2f}cm / {h_cm / 100:.4f}m)",
    ]

    pad = 6
    line_h = 18
    box_w = 320
    box_h = pad * 2 + line_h * len(lines)

    bx = min(max(x1, 0), frame.shape[1] - box_w)
    by = y1 - box_h - 8
    if by < 0:
        by = y2 + 8

    overlay = frame.copy()
    cv2.rectangle(overlay, (bx, by), (bx + box_w, by + box_h), TEXT_BG_COLOR, -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    for i, line in enumerate(lines):
        ty = by + pad + line_h * (i + 1) - 4
        cv2.putText(frame, line, (bx + pad, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.45, TEXT_COLOR, 1, cv2.LINE_AA)


def main():
    devices = list_camera_devices()
    if not devices:
        print("No camera devices found.")
        sys.exit(1)

    dev_path = choose_device(devices)
    cap = cv2.VideoCapture(dev_path, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"Failed to open {dev_path}")
        sys.exit(1)

    window_name = (
        f"Grid Viewer [{FRAME_WIDTH_CM:.0f}cm x {FRAME_HEIGHT_CM:.0f}cm] - "
        f"{dev_path} (press 'q' or ESC to quit)"
    )
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, on_mouse)

    print(
        f"Streaming with grid overlay, calibrated to {FRAME_WIDTH_CM}cm (X) x "
        f"{FRAME_HEIGHT_CM}cm (Y)... hover a block to inspect it, 'q'/ESC to quit."
    )

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Failed to read frame from camera.")
                break

            h, w = frame.shape[:2]
            cell_w, cell_h = draw_grid(frame, GRID_ROWS, GRID_COLS)
            cm_per_px_x = FRAME_WIDTH_CM / w
            cm_per_px_y = FRAME_HEIGHT_CM / h

            cell = hovered_cell(state["mouse_x"], state["mouse_y"], w, h, cell_w, cell_h, GRID_ROWS, GRID_COLS)
            if cell:
                draw_hover_info(frame, cell, cm_per_px_x, cm_per_px_y)

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

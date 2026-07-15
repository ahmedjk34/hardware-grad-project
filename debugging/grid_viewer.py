#!/usr/bin/env python3
"""Open the camera and overlay an equal-sized grid; hover a block to inspect its bounds."""

import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from camera_viewer import list_camera_devices, choose_device

GRID_ROWS = 8
GRID_COLS = 8
GRID_COLOR = (0, 255, 0)
HOVER_COLOR = (0, 165, 255)
TEXT_COLOR = (255, 255, 255)
TEXT_BG_COLOR = (0, 0, 0)

state = {"mouse_x": -1, "mouse_y": -1}


def on_mouse(event, x, y, flags, userdata):
    state["mouse_x"] = x
    state["mouse_y"] = y


def draw_grid(frame, rows, cols):
    h, w = frame.shape[:2]
    cell_w = w / cols
    cell_h = h / rows

    for c in range(1, cols):
        x = round(c * cell_w)
        cv2.line(frame, (x, 0), (x, h), GRID_COLOR, 1)
    for r in range(1, rows):
        y = round(r * cell_h)
        cv2.line(frame, (0, y), (w, y), GRID_COLOR, 1)

    return cell_w, cell_h


def hovered_cell(mouse_x, mouse_y, w, h, cell_w, cell_h, rows, cols):
    if not (0 <= mouse_x < w and 0 <= mouse_y < h):
        return None
    col = min(int(mouse_x // cell_w), cols - 1)
    row = min(int(mouse_y // cell_h), rows - 1)
    x1 = round(col * cell_w)
    y1 = round(row * cell_h)
    x2 = round((col + 1) * cell_w)
    y2 = round((row + 1) * cell_h)
    return row, col, x1, y1, x2, y2


def draw_hover_info(frame, cell):
    row, col, x1, y1, x2, y2 = cell
    cv2.rectangle(frame, (x1, y1), (x2 - 1, y2 - 1), HOVER_COLOR, 2)

    lines = [
        f"cell (row={row}, col={col})",
        f"start: ({x1}, {y1})",
        f"end:   ({x2}, {y2})",
        f"size:  {x2 - x1} x {y2 - y1}",
    ]

    pad = 6
    line_h = 18
    box_w = 220
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
        cv2.putText(frame, line, (bx + pad, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.5, TEXT_COLOR, 1, cv2.LINE_AA)


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

    window_name = f"Grid Viewer - {dev_path} (press 'q' or ESC to quit)"
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, on_mouse)

    print("Streaming with grid overlay... hover a block to inspect it, 'q'/ESC to quit.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Failed to read frame from camera.")
                break

            h, w = frame.shape[:2]
            cell_w, cell_h = draw_grid(frame, GRID_ROWS, GRID_COLS)

            cell = hovered_cell(state["mouse_x"], state["mouse_y"], w, h, cell_w, cell_h, GRID_ROWS, GRID_COLS)
            if cell:
                draw_hover_info(frame, cell)

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

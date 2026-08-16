#!/usr/bin/env python3
"""Shared OpenCV drawing helpers for the preview tools.

All of these draw onto the frame IN PLACE and return either nothing or a small
piece of geometry. Keeping them here means the grid tools and the undistortion
tool render their overlays identically, and the info-box layout only exists once.
"""

import cv2

GRID_COLOR = (0, 255, 0)
HOVER_COLOR = (0, 165, 255)
TEXT_COLOR = (255, 255, 255)
TEXT_BG_COLOR = (0, 0, 0)
WARN_COLOR = (0, 200, 255)   # amber: "these numbers are estimates"

FONT = cv2.FONT_HERSHEY_SIMPLEX
LINE_HEIGHT = 18
PADDING = 6


def draw_grid(frame, rows, cols, color=GRID_COLOR):
    """Draw an evenly spaced rows x cols grid. Returns (cell_w, cell_h) in pixels.

    Cell size is kept as a float and only rounded when drawing, so the last row
    and column stay the same size as the rest instead of absorbing the remainder.

    Doubles as the straightness reference for the undistortion tool: line up a
    real straight edge against a grid line and the residual bow is obvious.
    """
    h, w = frame.shape[:2]
    cell_w = w / cols
    cell_h = h / rows

    for c in range(1, cols):
        x = round(c * cell_w)
        cv2.line(frame, (x, 0), (x, h), color, 1)
    for r in range(1, rows):
        y = round(r * cell_h)
        cv2.line(frame, (0, y), (w, y), color, 1)

    return cell_w, cell_h


def hovered_cell(mouse_x, mouse_y, w, h, cell_w, cell_h, rows, cols):
    """Which grid cell is under the cursor?

    Returns (row, col, x1, y1, x2, y2) in pixels, or None when the cursor is
    outside the frame (which is what OpenCV reports before the first mouse move).
    """
    if not (0 <= mouse_x < w and 0 <= mouse_y < h):
        return None
    # min() guards the exact right/bottom edge, where the division lands one
    # cell past the end.
    col = min(int(mouse_x // cell_w), cols - 1)
    row = min(int(mouse_y // cell_h), rows - 1)
    return (
        row, col,
        round(col * cell_w), round(row * cell_h),
        round((col + 1) * cell_w), round((row + 1) * cell_h),
    )


def draw_info_box(frame, lines, origin=(4, 4), width=None, scale=0.45,
                  highlight_first=False):
    """Draw a translucent black panel of text at `origin`, clipped to the frame.

    `width` defaults to a rough estimate from the longest line. Set
    `highlight_first` to render the first line in amber — used to keep the
    "these parameters are estimated" warning visible at all times.
    """
    if width is None:
        width = max(220, int(9 * scale / 0.45 * max(len(line) for line in lines)))
    width = min(width, frame.shape[1] - 8)
    box_h = PADDING * 2 + LINE_HEIGHT * len(lines)

    x, y = origin
    # Keep the whole panel on screen even when anchored near an edge.
    x = min(max(x, 0), max(0, frame.shape[1] - width))
    y = min(max(y, 0), max(0, frame.shape[0] - box_h))

    # Blend rather than fill, so the image stays readable underneath.
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + width, y + box_h), TEXT_BG_COLOR, -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    for i, line in enumerate(lines):
        color = WARN_COLOR if (highlight_first and i == 0) else TEXT_COLOR
        ty = y + PADDING + LINE_HEIGHT * (i + 1) - 4
        cv2.putText(frame, line, (x + PADDING, ty), FONT, scale, color, 1, cv2.LINE_AA)

    return width, box_h


def draw_cell_info(frame, cell, lines, width=320):
    """Outline a hovered grid cell and label it with an info box.

    The box sits above the cell, flipping to below when there is no room — so it
    never gets clipped off the top of the frame.
    """
    _, _, x1, y1, x2, y2 = cell
    cv2.rectangle(frame, (x1, y1), (x2 - 1, y2 - 1), HOVER_COLOR, 2)

    box_h = PADDING * 2 + LINE_HEIGHT * len(lines)
    by = y1 - box_h - 8
    if by < 0:
        by = y2 + 8
    draw_info_box(frame, lines, origin=(x1, by), width=width)

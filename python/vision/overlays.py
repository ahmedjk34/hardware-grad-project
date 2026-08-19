#!/usr/bin/env python3
"""Shared OpenCV drawing helpers for the preview tools.

All of these draw onto the frame IN PLACE and return either nothing or a small
piece of geometry. Keeping them here means the grid tools and the undistortion
tool render their overlays identically, and the info-box layout only exists once.
"""

import math

import cv2

GRID_COLOR = (0, 255, 0)
HOVER_COLOR = (0, 165, 255)
TEXT_COLOR = (255, 255, 255)
TEXT_BG_COLOR = (0, 0, 0)
WARN_COLOR = (0, 200, 255)   # amber: "these numbers are estimates"
OK_COLOR = (120, 255, 120)   # green: a command or key was accepted
ERR_COLOR = (80, 80, 255)    # red: it was not
HINT_COLOR = (190, 190, 190) # grey: static guidance, not feedback
PROMPT_COLOR = (255, 220, 120)
LABEL_COLOR = (255, 255, 0)

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


def draw_text_panel(frame, entries, anchor="bottom-left", scale=0.45,
                    width=None, margin=6):
    """A translucent panel of individually coloured lines, pinned to a corner.

    `entries` is a list of (text, colour) pairs. draw_info_box covers the fixed
    single-colour HUD; this one exists for the command console, where each line
    needs its own colour because green/red is how the user tells an accepted
    command from a rejected one at a glance.

    Anchors: "top-left", "top-right", "bottom-left", "bottom-right".
    """
    if not entries:
        return None

    if width is None:
        width = max(180, int(9 * scale / 0.45 * max(len(t) for t, _ in entries)))
    width = min(width, frame.shape[1] - 2 * margin)
    box_h = PADDING * 2 + LINE_HEIGHT * len(entries)

    x = margin if anchor.endswith("left") else max(margin, frame.shape[1] - width - margin)
    y = margin if anchor.startswith("top") else max(margin, frame.shape[0] - box_h - margin)

    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + width, y + box_h), TEXT_BG_COLOR, -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    for i, (text, color) in enumerate(entries):
        ty = y + PADDING + LINE_HEIGHT * (i + 1) - 4
        cv2.putText(frame, text, (x + PADDING, ty), FONT, scale, color, 1, cv2.LINE_AA)

    return x, y, width, box_h


def draw_grid_labels(frame, rows, cols, cm_per_px_x=None, cm_per_px_y=None):
    """Label the grid lines along the top and left edges.

    Without the cm scales this reads out pixels; with them, centimetres — which
    are only meaningful on a corrected frame, so the caller decides. Labels sit
    just inside the frame so they survive being pushed against the edge.
    """
    h, w = frame.shape[:2]
    cell_w, cell_h = w / cols, h / rows

    def fmt(px, cm_per_px):
        return f"{px * cm_per_px:.1f}" if cm_per_px else str(int(px))

    for c in range(cols + 1):
        x = min(round(c * cell_w), w - 1)
        cv2.putText(frame, fmt(x, cm_per_px_x), (max(2, x + 3), 14),
                    FONT, 0.38, LABEL_COLOR, 1, cv2.LINE_AA)
    for r in range(rows + 1):
        y = min(round(r * cell_h), h - 1)
        cv2.putText(frame, fmt(y, cm_per_px_y), (3, max(12, y - 3)),
                    FONT, 0.38, LABEL_COLOR, 1, cv2.LINE_AA)


def draw_measure(frame, points, cm_per_px_x=None, cm_per_px_y=None):
    """Mark clicked points and, once there are two, the distance between them.

    Distance is reported in pixels always, and in centimetres when the scales
    are supplied. The cm figure inherits every caveat the cm grid has: it is a
    flat-plane approximation, valid only on a corrected frame and only for
    things lying in the plane the frame span was measured against.
    """
    for i, (x, y) in enumerate(points):
        cv2.drawMarker(frame, (int(x), int(y)), HOVER_COLOR, cv2.MARKER_CROSS, 14, 2)
        cv2.putText(frame, "AB"[i], (int(x) + 8, int(y) - 8),
                    FONT, 0.5, HOVER_COLOR, 1, cv2.LINE_AA)
    if len(points) < 2:
        return None

    (x1, y1), (x2, y2) = points[:2]
    cv2.line(frame, (int(x1), int(y1)), (int(x2), int(y2)), HOVER_COLOR, 1, cv2.LINE_AA)
    dx, dy = x2 - x1, y2 - y1
    label = f"{math.hypot(dx, dy):.1f} px"
    if cm_per_px_x and cm_per_px_y:
        label += f"  =  {math.hypot(dx * cm_per_px_x, dy * cm_per_px_y):.2f} cm"

    # Well clear of the line itself, so the label does not sit on top of the
    # measurement it describes (or on a grid line running through it).
    mid = (int((x1 + x2) / 2) + 12, int((y1 + y2) / 2) - 16)
    cv2.putText(frame, label, mid, FONT, 0.5, TEXT_BG_COLOR, 3, cv2.LINE_AA)
    cv2.putText(frame, label, mid, FONT, 0.5, HOVER_COLOR, 1, cv2.LINE_AA)
    return label

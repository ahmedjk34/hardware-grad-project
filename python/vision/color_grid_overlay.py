#!/usr/bin/env python3
"""Drawing for the printed colour-grid calibration sheet.

Split out of ``color_grid.py`` so the detector stays pure geometry and every
tool that shows the sheet — the standalone checker, the gridded feed, Rig
Build V1 — draws it identically. Like the rest of ``vision``, this touches
NumPy arrays only: no window, no camera, no argument parsing.

The colour scheme is doing a job, not decorating. Cells the fit is built from
are filled and labelled; cells that were found but rejected are outlined in
red, so a sheet that is drifting out of frame looks obviously wrong before it
silently degrades the calibration.
"""

from __future__ import annotations

import cv2
import numpy as np

from vision.color_grid import ColorGridCalibration
from vision.overlays import FONT, TEXT_BG_COLOR

MAPPED_COLOR = (120, 255, 120)      # a cell that is part of the [col,row] grid
EXTRA_COLOR = (200, 200, 90)        # a whole cell outside the chosen window
PARTIAL_COLOR = (80, 80, 255)       # clipped by the paper edge or the frame
OUTLINE_COLOR = (255, 180, 30)      # the grid's own outer boundary
ALTERNATE_COLOR = (220, 120, 255)    # valid, but not currently selected
ORIGIN_COLOR = (255, 80, 255)       # cell [0,0]
HOVER_COLOR = (0, 165, 255)

MIN_LABEL_PX = 26                   # below this a "9,5" label is a smear


def _quad(points) -> np.ndarray:
    return np.asarray(points, dtype=np.float32).round().astype(np.int32)


def _stamp(frame, text, at, color, scale=0.36):
    # These labels sit on live camera image, not on a panel, so every one gets
    # a dark outline first. The outline has to thicken with the text or it
    # disappears behind it at large scales.
    thickness = max(1, round(scale * 2))
    cv2.putText(frame, text, at, FONT, scale, TEXT_BG_COLOR, thickness + 2, cv2.LINE_AA)
    cv2.putText(frame, text, at, FONT, scale, color, thickness, cv2.LINE_AA)


def draw_color_grid(frame: np.ndarray, calibration: ColorGridCalibration, *,
                    hover=None, labels=True, shade=0.35, show_rejected=True):
    """Draw the fitted grid over ``frame`` in place; returns the hovered cell.

    ``shade`` tints each mapped cell so the *fitted* rectangle can be compared
    against the printed block underneath it. That comparison is the entire
    point of the overlay: if the tint and the ink disagree anywhere, the
    calibration is wrong there and nothing else on screen would have said so.
    """
    spec = calibration.spec
    found = calibration.found_cells

    if show_rejected:
        for cell in calibration.cells:
            if cell.cell is None:
                color = EXTRA_COLOR if cell.full else PARTIAL_COLOR
                cv2.polylines(frame, [_quad(cell.quad)], True, color, 1, cv2.LINE_AA)

    quads = {}
    for row in range(spec.rows):
        for col in range(spec.cols):
            quads[(col, row)] = _quad(calibration.cell_quad(col, row))

    if shade > 0:
        tinted = frame.copy()
        for key, quad in quads.items():
            color = ORIGIN_COLOR if key == (0, 0) else MAPPED_COLOR
            cv2.fillPoly(tinted, [quad], color)
        cv2.addWeighted(tinted, shade, frame, 1 - shade, 0, frame)

    for key, quad in quads.items():
        colour = ORIGIN_COLOR if key == (0, 0) else MAPPED_COLOR
        cv2.polylines(frame, [quad], True, colour, 1, cv2.LINE_AA)

    cv2.polylines(frame, [_quad(calibration.outline())], True, OUTLINE_COLOR, 2,
                  cv2.LINE_AA)

    if labels:
        sample = quads[(0, 0)]
        span = min(np.linalg.norm(sample[1] - sample[0]),
                   np.linalg.norm(sample[3] - sample[0]))
        if span >= MIN_LABEL_PX:
            # Grow the text with the cells. A fixed 0.36 is right on a 640-wide
            # preview and unreadable on a 2048-wide capture, and this overlay is
            # used at both.
            scale = min(1.2, max(0.36, span / 60))
            for (col, row), quad in quads.items():
                prefix = "F" if getattr(calibration, "is_combined", False) else ""
                text = f"{prefix}{col},{row}"
                (width, height), _ = cv2.getTextSize(text, FONT, scale, 1)
                x, y = quad.mean(axis=0)
                colour = ORIGIN_COLOR if (col, row) == (0, 0) else MAPPED_COLOR
                _stamp(frame, text,
                       (round(x - width / 2), round(y + height / 2)), colour,
                       scale)

    hovered = calibration.cell_at(hover) if hover is not None else None
    if hovered is not None:
        cv2.polylines(frame, [quads[hovered]], True, HOVER_COLOR, 3, cv2.LINE_AA)
    return hovered


def draw_grid_alternatives(frame: np.ndarray, calibrations, selected_index: int):
    """Outline every non-selected valid window and label its selection number."""
    for index, calibration in enumerate(calibrations):
        if index == selected_index:
            continue
        outline = _quad(calibration.outline())
        cv2.polylines(frame, [outline], True, ALTERNATE_COLOR, 2, cv2.LINE_AA)
        x, y = outline.mean(axis=0).astype(int)
        _stamp(frame, f"GRID {index + 1}", (x - 28, y), ALTERNATE_COLOR, 0.5)


def draw_candidates(frame: np.ndarray, error, *, labels=True):
    """Draw what a *failed* detection did find, so the failure is diagnosable.

    A blank frame is the least informative thing a checker can show: "no
    overlay" looks identical whether the sheet is out of shot, the camera's
    white balance has swallowed one of the inks, or the code never ran at all.
    :class:`ColorGridError` carries its candidate blobs for exactly this, and
    the difference between "hundreds of blobs, none on a lattice" and "four
    blobs" tells you which problem you have without touching the code.
    """
    candidates = getattr(error, "candidates", ())
    lattice = getattr(error, "lattice", ())
    if not candidates:
        return 0
    on_lattice = {tuple(np.round(box.mean(axis=0), 1)) for box in lattice}
    for box in candidates:
        key = tuple(np.round(np.asarray(box).mean(axis=0), 1))
        colour = MAPPED_COLOR if key in on_lattice else PARTIAL_COLOR
        cv2.polylines(frame, [_quad(box)], True, colour, 1, cv2.LINE_AA)
    if labels:
        _stamp(frame, f"{len(candidates)} colour blobs, {len(lattice)} on a lattice",
               (8, 22), PARTIAL_COLOR, 0.5)
        _stamp(frame, f"stage: {getattr(error, 'stage', '?')}", (8, 44),
               PARTIAL_COLOR, 0.5)
    return len(candidates)


def draw_workspace_corners(frame: np.ndarray, corners, color=OUTLINE_COLOR):
    """Mark the four holder-envelope corners a detection would save.

    Drawn separately from the grid because they are a *different* rectangle:
    under the default home convention the envelope runs from the far corner of
    printed ``[0,0]`` to the far corner of printed ``[9,5]``, so it is inset
    from the printed outline by half a cell on two sides. Seeing both at once
    is how that offset gets checked rather than assumed.
    """
    quad = _quad(corners)
    cv2.polylines(frame, [quad], True, color, 2, cv2.LINE_AA)
    for index, point in enumerate(quad):
        cv2.drawMarker(frame, tuple(point), color, cv2.MARKER_CROSS, 18, 2,
                       cv2.LINE_AA)
        _stamp(frame, str(index + 1), (point[0] + 8, point[1] - 8), color, 0.5)


def status_text(calibration: ColorGridCalibration | None, error: str | None = None):
    """One line for a HUD: what was found, or why nothing was."""
    if calibration is None:
        return f"paper grid: {error or 'not detected'}"
    metrics = calibration.metrics
    if getattr(calibration, "is_combined", False):
        return (f"combined sheet: {metrics.full_cells} fiducials, "
                f"residual {metrics.residual_px:.2f} px, "
                f"parity {metrics.parity_agreement * 100:.0f}%")
    return (f"paper grid: {metrics.full_cells} whole cells, "
            f"window {metrics.window_index + 1}/{metrics.window_candidates} "
            f"({metrics.window_observed}/{calibration.spec.cols * calibration.spec.rows}), "
            f"lattice {metrics.lattice_shape[0]}x{metrics.lattice_shape[1]}, "
            f"residual {metrics.residual_px:.2f} px, "
            f"parity {metrics.parity_agreement * 100:.0f}%")

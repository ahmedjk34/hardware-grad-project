#!/usr/bin/env python3
"""Detect the bordered-cluster calibration sheet by its black line lattice.

See ``docs/cluster-calibration-grid.md`` for the sheet design and the
numbered requirements C1-C9 this module implements.

Why this exists, next to ``color_grid.py``
------------------------------------------
``color_grid.py`` segments a muted green/magenta chessboard by hue, saturation
and Lab, then treats each connected ink blob as a cell. That sheet prints
badly and the rig camera's yellow cast eats the green. The new sheet keeps a
**hard black border** around every cell and groups cells into **3x3 clusters**
separated by a white gutter, with the cluster's centre cell left white as a
built-in fiducial. One cluster is one printed ``[col,row]`` - the same
"fiducial, not one-block-per-cell" model the A2 combined target uses.

The geometry signal here is the printed black lattice, recovered by
:func:`cluster_borders` with ``cv2.adaptiveThreshold`` on luminance - which is
colour-cast independent by construction. Colour is sampled afterwards only to
label each cluster green/magenta for the chessboard parity gate and to
cross-check the requested vertical/horizontal mode (C6).

Everything downstream is unchanged: this returns the same
``ColorGridCalibration`` tuple as :func:`color_grid.detect_color_grids`, so
``combined_grid``, ``color_grid_overlay``, ``grid_evidence`` and the feeds
consume it without edits (C7).

Constants marked ``TUNE-WITH-CAPTURE`` are desk guesses. They must be checked
against a real Pi frame through ``camera/color_grid_check.py`` before this
module is wired in as a feed's default detector.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from vision.color_grid import (
    DEFAULT_EDGE_MARGIN,
    DEFAULT_PROCESS_WIDTH,
    FULL_CELL_FILL,
    GREEN_HUE,
    MAGENTA_HUE,
    MAX_FULL_CELL_FILL,
    MAX_MEAN_RESIDUAL_SHORT_SIDE,
    MAX_WINDOWS,
    MIN_PARITY_AGREEMENT,
    ColorGridCalibration,
    ColorGridError,
    ColorGridMetrics,
    ColorGridSpec,
    PrintedCell,
    white_balance,
    _choose_windows,
    _fit,
    _parity_agreement,
    _score_fullness,
    _walk_lattice,
    _window_transform,
)

# --------------------------------------------------------------------------- #
# tuning
# --------------------------------------------------------------------------- #

# C1. Adaptive threshold that turns the printed black borders into the
# foreground. block_size is forced odd; it must be a few times the border
# width in the working-resolution frame. C is the bias subtracted from the
# local mean - higher rejects faint grey, lower keeps thin ink.
BORDER_BLOCK_FRACTION = 0.06      # of the short frame side  # TUNE-WITH-CAPTURE
BORDER_BLOCK_MIN = 9                                          # TUNE-WITH-CAPTURE
BORDER_C = 8                                                  # TUNE-WITH-CAPTURE
BORDER_CLOSE = 3                  # close kernel, px          # TUNE-WITH-CAPTURE

# C1. A contour is a cluster border if it reduces to four convex vertices and
# is close to a filled rectangle. minAreaRect fill = contourArea / (w*h).
QUAD_MIN_RECTANGULARITY = 0.72                                # TUNE-WITH-CAPTURE
QUAD_APPROX_FRACTION = 0.04       # of the contour perimeter
CLUSTER_ASPECT_RANGE = (0.35, 2.85)   # observed long/short, generous for tilt
CLUSTER_AREA_RANGE = (0.35, 2.8)      # of the median cluster area
MIN_CLUSTERS = 6                       # below this the frame is refused early
MIN_COLOR_PURITY = 0.60               # ring agreement needed to vote a colour

# C6. Hue windows in OpenCV's 0..179 space, applied after white balance. Green
# and magenta reuse color_grid's windows; the transparent-blue middle band of
# the horizontal sheet gets its own. A periwinkle blue under a magenta cast
# drifts toward magenta, so this window stops short of MAGENTA_HUE[0].
BLUE_HUE = (95, 128)                                          # TUNE-WITH-CAPTURE
RING_WHITE_SAT = 55              # a ring sub-cell above this sat carries ink   # TUNE-WITH-CAPTURE
RING_WHITE_VALUE = 165          # centre fiducial: below this it is not white   # TUNE-WITH-CAPTURE
RING_MIN_VALUE = 35

# C6. A horizontal sheet shows blue in most clusters; a vertical sheet in
# none. These are the fractions of accepted clusters that decide a mismatch.
HORIZONTAL_BLUE_FRACTION = 0.35                               # TUNE-WITH-CAPTURE
VERTICAL_BLUE_FRACTION = 0.15                                 # TUNE-WITH-CAPTURE


# --------------------------------------------------------------------------- #
# C1 - the black lattice
# --------------------------------------------------------------------------- #

def cluster_borders(frame: np.ndarray, *,
                    block_fraction: float = BORDER_BLOCK_FRACTION,
                    block_min: int = BORDER_BLOCK_MIN,
                    bias: int = BORDER_C,
                    close: int = BORDER_CLOSE) -> tuple[np.ndarray, list[dict]]:
    """Return ``(border_mask, quads)`` for the printed black cluster borders.

    ``border_mask`` is the inverted adaptive threshold (borders white). Each
    entry in ``quads`` is a dict in the shape :func:`color_grid._walk_lattice`
    and friends expect: ``center``, ``quad`` (4x2), ``area``, ``long_len``,
    ``short_len``, ``long_axis``, ``short_axis``, ``clipped``. Colour fields
    are added later by :func:`_label_clusters`.
    """
    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    short_side = min(gray.shape[:2])
    block = max(block_min, int(round(block_fraction * short_side)) | 1)
    if block % 2 == 0:
        block += 1
    mask = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV,
        block, bias)
    if close > 1:
        kernel = np.ones((close, close), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    height, width = gray.shape[:2]
    # RETR_EXTERNAL: the black border of one cluster is a single connected ring
    # whose OUTER contour is the cluster rectangle. The 3x3 sub-cell divisions
    # are interior contours and are ignored - we want one quad per cluster, not
    # nine per cluster.
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    quads: list[dict] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 16:
            continue
        approx = cv2.approxPolyDP(
            contour, QUAD_APPROX_FRACTION * cv2.arcLength(contour, True), True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        (cx, cy), (w, h), angle = cv2.minAreaRect(contour)
        if w < 4 or h < 4:
            continue
        if area / (w * h) < QUAD_MIN_RECTANGULARITY:
            continue
        box = cv2.boxPoints(((cx, cy), (w, h), angle)).astype(np.float32)
        theta = math.radians(angle)
        axis_w = np.array([math.cos(theta), math.sin(theta)])
        axis_h = np.array([-math.sin(theta), math.cos(theta)])
        if w >= h:
            long_len, short_len, long_axis, short_axis = w, h, axis_w, axis_h
        else:
            long_len, short_len, long_axis, short_axis = h, w, axis_h, axis_w
        clipped = bool(
            box[:, 0].min() <= 1 or box[:, 1].min() <= 1
            or box[:, 0].max() >= width - 2 or box[:, 1].max() >= height - 2)
        quads.append({
            "center": (float(cx), float(cy)),
            "quad": box,
            "area": float(abs(cv2.contourArea(box))),
            "long_len": float(long_len),
            "short_len": float(short_len),
            "long_axis": long_axis.astype(float),
            "short_axis": short_axis.astype(float),
            "clipped": clipped,
        })
    return mask, _dedupe_quads(quads)


def _dedupe_quads(quads: list[dict]) -> list[dict]:
    """Drop the outer of two near-concentric quads (border has two contours)."""
    if not quads:
        return quads
    order = sorted(range(len(quads)), key=lambda k: quads[k]["area"])
    kept: list[dict] = []
    for index in order:
        here = quads[index]
        cx, cy = here["center"]
        span = 0.25 * here["short_len"]
        if any(math.hypot(cx - k["center"][0], cy - k["center"][1]) < span
               for k in kept):
            continue
        kept.append(here)
    return kept


# --------------------------------------------------------------------------- #
# C6 - colour label per cluster
# --------------------------------------------------------------------------- #

def _sub_cell_samples(frame_bgr: np.ndarray, hsv: np.ndarray,
                      quad: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """3x3x3 median BGR and HSV of the cluster's sub-cells."""
    height, width = hsv.shape[:2]
    corners = quad.astype(np.float32)
    bgr_out = np.zeros((3, 3, 3), np.float32)
    hsv_out = np.zeros((3, 3, 3), np.float32)
    for r in range(3):
        for c in range(3):
            u, v = (c + 0.5) / 3.0, (r + 0.5) / 3.0
            top = corners[0] * (1 - u) + corners[1] * u
            bottom = corners[3] * (1 - u) + corners[2] * u
            px, py = top * (1 - v) + bottom * v
            x0, x1 = int(np.clip(px - 2, 0, width - 1)), int(np.clip(px + 3, 1, width))
            y0, y1 = int(np.clip(py - 2, 0, height - 1)), int(np.clip(py + 3, 1, height))
            if x1 > x0 and y1 > y0:
                bgr_out[r, c] = np.median(
                    frame_bgr[y0:y1, x0:x1].reshape(-1, 3), axis=0)
                hsv_out[r, c] = np.median(
                    hsv[y0:y1, x0:x1].reshape(-1, 3), axis=0)
    return bgr_out, hsv_out


def _classify(hsv: np.ndarray, bgr: np.ndarray) -> str:
    """Bucket one sub-cell. Hue window first, channel order as the cast fallback."""
    h, s, v = float(hsv[0]), float(hsv[1]), float(hsv[2])
    b, g, r = float(bgr[0]), float(bgr[1]), float(bgr[2])
    if v < RING_MIN_VALUE:
        return "other"
    if s < RING_WHITE_SAT and v >= RING_WHITE_VALUE:
        return "white"
    # The transparent-blue band and green ink overlap in hue (a balanced green
    # can sit at 100-110, inside a periwinkle-blue window). The channel ORDER
    # separates them cleanly and survives a residual cast: the blue band is the
    # only ring colour with B > G > R; green ink leads on G; magenta/purple has
    # G as the minimum with B and R both above it.
    if b > g > r and (b - r) > 20:
        return "blue"
    if GREEN_HUE[0] <= h <= GREEN_HUE[1] or (g >= b and g >= r):
        return "green"
    if (MAGENTA_HUE[0] <= h <= MAGENTA_HUE[1] or h <= 8 or h >= 172
            or (g <= b and g <= r)):
        return "magenta"
    if BLUE_HUE[0] <= h <= BLUE_HUE[1]:
        return "blue"
    return "other"


def _label_clusters(frame: np.ndarray, quads: list[dict]) -> None:
    """Attach ``color``, ``color_purity`` and ``has_blue`` to every quad."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    for quad in quads:
        bgr_grid, hsv_grid = _sub_cell_samples(frame, hsv, quad["quad"])
        ring = [(r, c) for r in range(3) for c in range(3) if (r, c) != (1, 1)]
        labels = [_classify(hsv_grid[r, c], bgr_grid[r, c]) for r, c in ring]
        green = labels.count("green")
        magenta = labels.count("magenta")
        blue = labels.count("blue")
        ink = green + magenta
        quad["color"] = "green" if green >= magenta else "magenta"
        quad["color_purity"] = (max(green, magenta) / ink) if ink else 0.0
        quad["has_blue"] = blue >= 1
        quad["ink_labels"] = labels


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #

def detect_cluster_grids(frame: np.ndarray, spec: ColorGridSpec | None = None, *,
                         process_width: int = DEFAULT_PROCESS_WIDTH,
                         fill_tolerance: float = FULL_CELL_FILL,
                         max_fill: float = MAX_FULL_CELL_FILL,
                         edge_margin: float = DEFAULT_EDGE_MARGIN,
                         max_windows: int = MAX_WINDOWS,
                         balance: bool = True,
                         evidence: bool = False) -> tuple[ColorGridCalibration, ...]:
    """Fit the bordered-cluster sheet. One tuple entry per mode-sized window.

    Mirrors :func:`color_grid.detect_color_grids` in signature intent and
    output type. ``spec`` carries the explicit vertical/horizontal mode (C6);
    ``fill_tolerance`` / ``max_fill`` are the whole-cluster band (C3).
    """
    spec = spec or ColorGridSpec()
    if frame is None or frame.size == 0:
        raise ColorGridError("empty frame", stage="detect")

    working = frame
    scale = 1.0
    if process_width and frame.shape[1] > process_width:
        scale = process_width / frame.shape[1]
        working = cv2.resize(frame, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_AREA)
    work_size = (working.shape[1], working.shape[0])

    # C1/C9: geometry comes off raw luminance, which a colour cast barely
    # moves. White balance is only for the colour label further down, and a
    # cast that clips a channel would make white_balance itself unstable.
    mask, quads = cluster_borders(working)
    if len(quads) < MIN_CLUSTERS:
        raise ColorGridError(
            f"found {len(quads)} cluster borders; need at least {MIN_CLUSTERS}",
            stage="segment", candidates=[q["quad"] / scale for q in quads])

    # Drop borders that are not cluster-sized before they can steer the walk.
    areas = np.array([q["area"] for q in quads])
    median_area = float(np.median(areas))
    quads = [q for q in quads
             if CLUSTER_AREA_RANGE[0] * median_area <= q["area"]
             <= CLUSTER_AREA_RANGE[1] * median_area
             and CLUSTER_ASPECT_RANGE[0]
             <= q["long_len"] / max(q["short_len"], 1e-6)
             <= CLUSTER_ASPECT_RANGE[1]]
    if len(quads) < MIN_CLUSTERS:
        raise ColorGridError(
            f"only {len(quads)} cluster-sized borders survived the size filter",
            stage="segment", candidates=[q["quad"] / scale for q in quads])

    # Geometry must not depend on colour (C1). Give the lattice walk a neutral
    # placeholder so its parity-based clutter rejection stays a no-op; the real
    # green/magenta label is attached after the fit, from the balanced frame.
    for quad in quads:
        quad["color"], quad["color_purity"] = "green", 1.0

    coords = _walk_lattice(quads, spec, aspect_range=CLUSTER_ASPECT_RANGE)
    if len(coords) < 4:
        raise ColorGridError(
            f"the black lattice only connected {len(coords)} clusters",
            stage="lattice", candidates=[q["quad"] / scale for q in quads])

    matrix, mean_error, _max = _fit(coords, quads, lambda i: quads[i]["seed"])
    if matrix is None:
        matrix, mean_error, _max = _fit(coords, quads, lambda i: True)
    if matrix is None:
        raise ColorGridError("could not fit a homography to the clusters",
                             stage="fit",
                             candidates=[q["quad"] / scale for q in quads])

    _score_fullness(coords, quads, matrix, spec, None,
                    (fill_tolerance, max_fill), edge_margin=0.0)
    refit, refit_error, _ = _fit(coords, quads, lambda i: quads[i]["full"])
    if refit is not None:
        matrix, mean_error = refit, refit_error
    _score_fullness(coords, quads, matrix, spec, work_size,
                    (fill_tolerance, max_fill), edge_margin=edge_margin)

    # Now colour: label the accepted clusters off the white-balanced frame (C9).
    balanced = white_balance(working) if balance else working
    _label_clusters(balanced, quads)
    _cross_check_mode(spec, coords, quads)
    _quality_gate(spec, coords, quads, matrix, mean_error,
                  [q["quad"] / scale for q in quads])

    need_i, need_j = spec.lattice_counts
    windows = _choose_windows(coords, quads, need_i, need_j, work_size, matrix)
    if not windows:
        raise ColorGridError(
            "no mode-sized window has full cluster coverage; the sheet is not "
            "whole enough in this frame", stage="window",
            candidates=[q["quad"] / scale for q in quads])
    windows = windows[:max_windows]

    unscale = np.array([[1 / scale, 0, 0], [0, 1 / scale, 0], [0, 0, 1]])
    calibrations: list[ColorGridCalibration] = []
    for order, (origin, corner, observed) in enumerate(windows):
        transform = _window_transform(origin, corner, need_i, need_j, spec)
        cell_matrix = unscale @ matrix @ transform
        inverse_t = np.linalg.inv(transform)
        cells: list[PrintedCell] = []
        for index, (i, j) in coords.items():
            lat = inverse_t @ np.array([i, j, 1.0])
            col, row = lat[0] / lat[2], lat[1] / lat[2]
            key = (int(round(col)), int(round(row)))
            inside = (0 <= key[0] < spec.cols and 0 <= key[1] < spec.rows
                      and abs(col - key[0]) < 0.25 and abs(row - key[1]) < 0.25)
            quad = quads[index]
            cells.append(PrintedCell(
                lattice=(i, j),
                center=(quad["center"][0] / scale, quad["center"][1] / scale),
                quad=quad["quad"] / scale,
                color=quad["color"],
                area=quad["area"] / (scale * scale),
                fill=quad.get("fill", 0.0),
                full=bool(quad.get("full", False)),
                cell=key if (inside and quad.get("full", False)) else None,
                edge_clipped=bool(quad.get("edge_clipped", False)),
            ))
        metrics = _metrics(spec, coords, quads, matrix, mean_error, work_size,
                           frame.shape, order, len(windows), observed)
        calibrations.append(ColorGridCalibration(
            spec=spec, homography=cell_matrix, cells=cells, metrics=metrics))
    return tuple(calibrations)


def detect_cluster_grid(frame: np.ndarray, spec: ColorGridSpec | None = None, *,
                        window_index: int = 0, **kwargs) -> ColorGridCalibration:
    """Single-window wrapper, matching :func:`color_grid.detect_color_grid`."""
    calibrations = detect_cluster_grids(frame, spec, **kwargs)
    if not 0 <= window_index < len(calibrations):
        raise ColorGridError(
            f"window {window_index} of {len(calibrations)} detected",
            stage="selection")
    return calibrations[window_index]


# --------------------------------------------------------------------------- #
# gates
# --------------------------------------------------------------------------- #

def _cross_check_mode(spec, coords, quads) -> None:
    """C6: refuse a sheet whose clusters disagree with the requested mode."""
    accepted = [quads[i] for i in coords if quads[i].get("full")]
    if len(accepted) < 4:
        return
    blue = sum(1 for q in accepted if q.get("has_blue")) / len(accepted)
    if spec.mode == "vertical" and blue > VERTICAL_BLUE_FRACTION:
        raise ColorGridError(
            "detected horizontal cluster colouring (transparent-blue middle "
            "band) but the requested mode is vertical", stage="orientation")
    if spec.mode == "horizontal" and blue < HORIZONTAL_BLUE_FRACTION:
        raise ColorGridError(
            "detected vertical cluster colouring (single-hue shade ramp, no "
            "blue band) but the requested mode is horizontal",
            stage="orientation")


def _quality_gate(spec, coords, quads, matrix, mean_error, candidates) -> None:
    full_keys = [coords[idx] for idx in coords if quads[idx]["full"]]
    if len(full_keys) < 4:
        raise ColorGridError("fewer than four whole clusters after scoring",
                             stage="quality", candidates=candidates)
    parity = _parity_agreement(
        {idx: coords[idx] for idx in coords if quads[idx]["full"]}, quads)
    if parity < MIN_PARITY_AGREEMENT:
        raise ColorGridError(
            f"cluster colour parity is only {parity:.0%}; the green/magenta "
            "chessboard is broken", stage="quality", candidates=candidates)
    shorts = np.array([quads[idx]["short_len"] for idx in coords
                       if quads[idx]["full"]])
    short_med = float(np.median(shorts)) if len(shorts) else 1.0
    if mean_error > MAX_MEAN_RESIDUAL_SHORT_SIDE * short_med * 4:
        raise ColorGridError(
            f"mean residual {mean_error:.2f}px is too large for the cluster "
            "pitch", stage="quality", candidates=candidates)


def _metrics(spec, coords, quads, matrix, mean_error, work_size, input_shape,
             order, window_count, observed) -> ColorGridMetrics:
    full_keys = [coords[idx] for idx in coords if quads[idx]["full"]]
    i_vals = [k[0] for k in coords.values()]
    j_vals = [k[1] for k in coords.values()]
    parity = _parity_agreement(
        {idx: coords[idx] for idx in coords if quads[idx]["full"]}, quads)
    longs = [quads[idx]["long_len"] for idx in coords if quads[idx]["full"]]
    shorts = [quads[idx]["short_len"] for idx in coords if quads[idx]["full"]]
    aspect = (float(np.median(longs)) / float(np.median(shorts))
              if longs and shorts else 0.0)
    return ColorGridMetrics(
        input_size=(input_shape[1], input_shape[0]),
        processing_size=work_size,
        components=len(quads),
        assigned=len(coords),
        full_cells=len(full_keys),
        lattice_shape=((max(i_vals) - min(i_vals) + 1) if i_vals else 0,
                       (max(j_vals) - min(j_vals) + 1) if j_vals else 0),
        residual_px=float(mean_error),
        max_residual_px=float(mean_error),
        parity_agreement=float(parity),
        measured_aspect=aspect,
        window_candidates=window_count,
        window_index=order,
        window_observed=observed,
    )

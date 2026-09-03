#!/usr/bin/env python3
"""Calibrate the workspace from blocks the rig places at cells it was told.

Why this exists, next to ``color_grid.py`` and ``cluster_grid.py``
------------------------------------------------------------------
Every printed-sheet detector measures the *camera against a piece of paper*,
and then has to assume the paper sits where the machine thinks its cells are.
That assumption is the whole reason :data:`color_grid.HOME_CONVENTIONS` exists:
the sheet prints a real block at coordinate zero, the firmware does not, and
somebody has to decide which is right. It is also why the sheet detector has to
work so hard - it is handed an unlabelled lattice and must infer which blob is
cell ``[0,0]`` from a colour chessboard, a size prior and a window search.

Here the rig itself puts a block on cell ``[3,2]``. There is nothing to infer:
the correspondence ``[3,2] -> (px, py)`` is *labelled at the source*. The
lattice walk, the colour-parity gate, the full/partial fill scoring and the
window search all become unnecessary, and what is left is one homography fit
over known correspondences. Better still, it measures the real pick-and-place
chain - backlash, tool offsets, the mode's ``error_offset_*_cm`` - rather than
the camera's view of a printed approximation of it.

What the residual means here, and why it is not an optical number
-----------------------------------------------------------------
A sheet detector's residual is measurement error: the paper is rigid, so
anything left over is optics and segmentation. This one's residual also
contains **where the machine actually put the block**. That is a feature - it
is the number an operator actually wants - but it means the gates below are
looser than :data:`color_grid.MAX_MEAN_RESIDUAL_SHORT_SIDE` on purpose, and a
large residual here should be read as "the rig or the map is off", not
"the camera is blurry".

What replaces the colour-parity gate
------------------------------------
The printed sheet gets a free consistency check from its chessboard: cell
``(i+j)`` parity must agree with the ink colour for 95% of cells, which catches
an index assignment that is self-consistent but shifted. Identical wooden
blocks offer nothing equivalent, so two *physical* agreements take its place,
checked per observation against the fitted homography:

* **footprint** - the observed block's short side must match the block width
  the homography predicts at that cell (:data:`SIZE_AGREEMENT_RANGE`);
* **bearing** - the observed block's long axis must point along the machine
  axis the active mode says it should (:data:`MAX_ANGLE_DISAGREEMENT_DEG`).

Either one catches "a cable was detected instead of the block" and "the block
was placed on the wrong cell", which are the two failures that matter.

Four points fit a homography exactly, which is why the floor is five
--------------------------------------------------------------------
With four correspondences the fit is exact and every residual is zero by
construction - the calibration would carry no evidence at all that it is right.
:data:`MIN_OBSERVATIONS` is therefore five, so at least one degree of freedom
is left over to disagree, and :data:`DEFAULT_OBSERVATIONS` is six.

The module is deliberately rig-free and camera-free: it takes frames and cell
indices and returns geometry, so the whole safety decision is testable without
hardware. ``rig/block_calibration.py`` is the part that drives the machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math

import cv2
import numpy as np

from rig.grid import MachineGrid
from rig.workspace import WorkspaceMap
from vision.block_detector import detect_blocks
from vision.color_grid import (
    DEFAULT_HOME_CONVENTION,
    ColorGridCalibration,
    ColorGridError,
    ColorGridMetrics,
    ColorGridSpec,
    PrintedCell,
)


# Four points fit a homography exactly. Five is the smallest set that can
# disagree with itself, and therefore the smallest that can be *checked*.
MIN_OBSERVATIONS = 5
DEFAULT_OBSERVATIONS = 6

# Residual gates, as a fraction of the shorter cell pitch measured in pixels at
# the middle of the fitted lattice. Deliberately looser than the printed
# sheet's: see the module docstring - this residual includes where the machine
# physically put the block, not only where the camera saw it.
MAX_MEAN_RESIDUAL_PITCH = 0.10
MAX_RESIDUAL_PITCH = 0.28

# Conditioning. Correspondences strung along a line, or crowded into one corner,
# fit a homography that is excellent locally and wild everywhere else. The hull
# area is in cell units, so one unit is one pitch by one pitch.
MIN_AXIS_SPREAD_CELLS = 1.0
MIN_HULL_AREA_CELLS = 1.5

# The two checks that replace the printed chessboard's parity gate. Both are
# measured against the fitted homography's own prediction at that cell, so they
# scale with perspective instead of assuming a constant px/cm.
SIZE_AGREEMENT_RANGE = (0.60, 1.55)
MAX_ANGLE_DISAGREEMENT_DEG = 22.0

# Frame differencing. The block is the only thing that changed between the
# baseline and the capture, which is a far stronger signal than "warm-coloured
# rectangle on a pale surface" - it survives the rig camera's magenta cast,
# which is exactly what red-minus-blue segmentation does not. The floor stops
# Otsu from finding structure in an all-noise difference.
DIFF_MIN_THRESHOLD = 18
DIFF_BLUR_SIGMA = 2.0
DIFF_CLOSE = 5
MIN_DIFF_AREA_FRACTION = 0.25   # of the predicted block footprint

# How far from the homography's prediction a sighting may sit and still be
# accepted as that cell's block, as a fraction of the shorter pitch. Only
# applied once there are enough observations to predict at all.
PREDICTION_TOLERANCE = 0.60

# How much clear space a sighting must keep between its own edge and the frame
# border, as a fraction of its short side. A block the frame cuts in half still
# segments cleanly - it just is not the shape it appears to be, and its
# centroid is dragged inwards by however much was lost. On the mock camera,
# whose envelope reaches 96% of the frame, that bias is 21 px on a 40 px block:
# far too large to fit and far too small to look obviously wrong. This is the
# same guard as color_grid's DEFAULT_EDGE_MARGIN, for the same reason.
EDGE_MARGIN_FRACTION = 0.25


class BlockGridError(ColorGridError):
    """A placed-block calibration could not be produced.

    Subclasses :class:`~vision.color_grid.ColorGridError` on purpose: every
    caller that already handles a failed sheet detection handles this too,
    and ``stage`` keeps saying how far the attempt got.
    """


@dataclass(frozen=True)
class BlockSighting:
    """One block found in one frame, in pixels of the frame handed in."""

    center: tuple[float, float]
    quad: np.ndarray                 # 4x2, the observed rotated rectangle
    long_len: float
    short_len: float
    angle: float                     # long-axis bearing, degrees, [-90, 90)
    area: float
    rectangularity: float
    source: str                      # "difference", "colour" or "corroborated"
    score: float = 0.0

    @property
    def aspect(self) -> float:
        return self.long_len / self.short_len if self.short_len else 0.0


@dataclass(frozen=True)
class BlockObservation:
    """A sighting with the cell the rig was *told* to place it on."""

    cell: tuple[int, int]
    sighting: BlockSighting

    @property
    def center(self) -> tuple[float, float]:
        return self.sighting.center


@dataclass
class BlockGridReport:
    """The honest per-fit numbers, which ``ColorGridMetrics`` has no slots for.

    Attached to the returned calibration as ``block_report``. The generic
    metrics object is still filled in so ``describe()`` and the existing
    overlays keep working, but its ``parity_agreement`` is vacuous here - the
    cell colours are synthesised from ``(i+j)`` parity rather than measured -
    and the fields below are what actually gate a save.
    """

    observations: int = 0
    mean_residual_px: float = 0.0
    max_residual_px: float = 0.0
    worst_cell: tuple[int, int] | None = None
    short_pitch_px: float = 0.0
    hull_area_cells: float = 0.0
    size_agreement: float = 0.0      # observed short side / predicted, median
    max_bearing_error_deg: float = 0.0
    residuals: dict = field(default_factory=dict)   # cell -> px

    def describe(self) -> str:
        worst = "-" if self.worst_cell is None else f"[{self.worst_cell[0]},{self.worst_cell[1]}]"
        return (f"{self.observations} placed blocks, residual "
                f"{self.mean_residual_px:.2f} px mean / {self.max_residual_px:.2f} px "
                f"max at {worst}, footprint {self.size_agreement:.2f}x predicted, "
                f"bearing off by up to {self.max_bearing_error_deg:.1f} deg, "
                f"spread {self.hull_area_cells:.1f} cells^2")


# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #

def spec_for_grid(grid: MachineGrid) -> ColorGridSpec:
    """The :class:`ColorGridSpec` that exactly describes ``grid``.

    Built from the machine grid rather than re-read from config, so the spec
    and the grid cannot drift apart and
    :meth:`ColorGridCalibration._check_geometry_matches` cannot fail on a
    calibration this module produced.
    """
    if not grid.has_physical_scale:
        raise BlockGridError(
            "a placed-block calibration needs a physically scaled MachineGrid",
            stage="spec")
    if grid.mode is None:
        raise BlockGridError(
            "the machine grid does not say which block orientation it is; "
            "construct it with MachineGrid.from_config(mode=...)", stage="spec")
    return ColorGridSpec(
        cols=grid.cols, rows=grid.rows,
        block_x_cm=grid.block_x_cm, block_y_cm=grid.block_y_cm,
        gap_x_cm=grid.gap_x_cm, gap_y_cm=grid.gap_y_cm,
        mode=grid.mode,
    )


def _project(matrix: np.ndarray, points) -> np.ndarray:
    """Project Nx2 grid coordinates through a 3x3 homography."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    homogeneous = np.hstack([pts, np.ones((len(pts), 1))])
    out = homogeneous @ matrix.T
    w = out[:, 2:3]
    if np.any(np.abs(w) < 1e-12):
        raise BlockGridError("the fitted grid mapping reaches infinity",
                             stage="fit")
    return out[:, :2] / w


def _local_scale(matrix: np.ndarray, spec: ColorGridSpec,
                 cell) -> tuple[float, float, float, float]:
    """Pixel geometry the fit predicts at ``cell``.

    Returns ``(pitch_x_px, pitch_y_px, block_x_px, block_y_px)``, all measured
    as central differences so a perspective-heavy view is described where the
    block actually is rather than at the lattice origin.
    """
    col, row = float(cell[0]), float(cell[1])
    half_x, half_y = spec.fill_x / 2.0, spec.fill_y / 2.0
    probes = _project(matrix, [
        (col - 0.5, row), (col + 0.5, row),
        (col, row - 0.5), (col, row + 0.5),
        (col - half_x, row), (col + half_x, row),
        (col, row - half_y), (col, row + half_y),
    ])
    pitch_x = float(np.linalg.norm(probes[1] - probes[0]))
    pitch_y = float(np.linalg.norm(probes[3] - probes[2]))
    block_x = float(np.linalg.norm(probes[5] - probes[4]))
    block_y = float(np.linalg.norm(probes[7] - probes[6]))
    return pitch_x, pitch_y, block_x, block_y


def _bearing(matrix: np.ndarray, spec: ColorGridSpec, cell) -> float:
    """Where the fit says this cell's block long axis points, in degrees.

    Unoriented: the block is symmetric, so only the line matters, and the
    result is normalised into ``[-90, 90)`` to match
    :class:`~vision.block_detector.BlockDetection.angle`.
    """
    col, row = float(cell[0]), float(cell[1])
    if spec.block_y_cm >= spec.block_x_cm:
        ends = _project(matrix, [(col, row - 0.5), (col, row + 0.5)])
    else:
        ends = _project(matrix, [(col - 0.5, row), (col + 0.5, row)])
    delta = ends[1] - ends[0]
    return _normalise_angle(math.degrees(math.atan2(delta[1], delta[0])))


def _normalise_angle(angle: float) -> float:
    while angle >= 90.0:
        angle -= 180.0
    while angle < -90.0:
        angle += 180.0
    return angle


def _angle_gap(first: float, second: float) -> float:
    return abs(_normalise_angle(first - second))


def _hull_area(points) -> float:
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    if len(pts) < 3:
        return 0.0
    return float(abs(cv2.contourArea(cv2.convexHull(pts))))


# --------------------------------------------------------------------------- #
# planning which cells to place on
# --------------------------------------------------------------------------- #

def plan_calibration_cells(grid: MachineGrid,
                           count: int = DEFAULT_OBSERVATIONS,
                           *, inset: int = 0) -> tuple:
    """Choose ``count`` buildable cells that span the envelope as widely as possible.

    Farthest-point sampling in **centimetres**, not cell indices, so the spread
    is physical: the two modes have very different pitches on each axis, and a
    set that looks even in index space would bunch up in one of them.

    The feeder ``[0,0]`` is excluded because the firmware refuses to build on it
    (:meth:`MachineGrid.contains_build_target`), which is also why the home
    corner of the envelope is always extrapolated rather than measured. That is
    the one structural weakness of this method and it is why the plan starts
    from the corners: the extrapolation is short.

    ``inset`` drops that many outermost rings of cells. A block on the extreme
    row hangs up to ``max_edge_overhang_y_cm`` past the travel limit, and a
    camera framed tightly to the envelope cuts it off - at which point
    :func:`locate_block` rightly refuses it. ``inset=1`` trades the widest
    possible spread for cells the camera can certainly see whole.
    """
    count = int(count)
    if count < MIN_OBSERVATIONS:
        raise BlockGridError(
            f"a placed-block calibration needs at least {MIN_OBSERVATIONS} "
            f"cells to be checkable, not {count}", stage="plan")
    if not grid.has_physical_scale:
        raise BlockGridError("planning needs a physically scaled MachineGrid",
                             stage="plan")

    inset = int(inset)
    if inset < 0:
        raise BlockGridError("inset cannot be negative", stage="plan")
    # Clamp per axis. The horizontal grid is only 3 columns wide, so a blanket
    # inset of 1 would leave a single column and every fit would then be
    # refused for spanning no X at all. An axis that cannot afford the inset
    # keeps its full range instead - the narrow axis is the one least likely to
    # run off the frame anyway.
    inset_col = min(inset, max(0, (grid.cols - 2) // 2))
    inset_row = min(inset, max(0, (grid.rows - 2) // 2))
    low_col, high_col = inset_col, grid.cols - 1 - inset_col
    low_row, high_row = inset_row, grid.rows - 1 - inset_row
    buildable = [(col, row)
                 for row in range(grid.rows)
                 for col in range(grid.cols)
                 if grid.contains_build_target(col, row)
                 and low_col <= col <= high_col and low_row <= row <= high_row]
    if len(buildable) < count:
        raise BlockGridError(
            f"the {grid.mode} grid offers only {len(buildable)} buildable "
            f"cells at inset {inset_col}x{inset_row}, fewer than the {count} "
            f"requested", stage="plan")

    centres = np.array([grid.cell_center_cm(col, row) for col, row in buildable])

    # The four extreme cells first, explicitly. Plain farthest-point sampling
    # is not quite the same thing: from two opposite corners it will sometimes
    # prefer a far edge cell over the remaining corner, because that maximises
    # the minimum distance. A homography is conditioned by the area its
    # correspondences enclose, so the corners are what it wants - and taking
    # them first is what makes a run abandoned at four placements still the
    # best-conditioned four available.
    chosen: list[int] = []
    for corner in ((low_col, low_row), (high_col, low_row),
                   (high_col, high_row), (low_col, high_row)):
        wanted = np.array([grid.cell_center_x_cm(corner[0]),
                           grid.cell_center_y_cm(corner[1])])
        ranked = np.argsort(np.linalg.norm(centres - wanted, axis=1))
        for index in ranked:
            if int(index) not in chosen:
                chosen.append(int(index))
                break
        if len(chosen) >= count:
            break

    # Then farthest-point sampling for the interior: each new cell is the one
    # whose nearest already chosen neighbour is furthest away. Measured in
    # centimetres, not cell indices - the two modes have very different pitches
    # on each axis, and an index-even spread bunches up in one of them.
    if len(chosen) < count:
        distances = np.min(
            [np.linalg.norm(centres - centres[index], axis=1) for index in chosen],
            axis=0)
        while len(chosen) < count:
            nxt = int(np.argmax(distances))
            chosen.append(nxt)
            distances = np.minimum(distances,
                                   np.linalg.norm(centres - centres[nxt], axis=1))
    return tuple(buildable[index] for index in chosen[:count])


# --------------------------------------------------------------------------- #
# finding the block that just appeared
# --------------------------------------------------------------------------- #

def _difference_sightings(frame: np.ndarray, baseline: np.ndarray,
                          min_area: float) -> list[BlockSighting]:
    """Rotated rectangles for whatever changed between two frames.

    Channel-max absolute difference rather than a grey one: a pale wooden block
    on pale paper separates far better in one channel than in luminance, and
    which channel that is depends on the cast of the day.
    """
    if baseline is None or baseline.shape != frame.shape:
        return []
    diff = cv2.absdiff(frame, baseline).max(axis=2)
    diff = cv2.GaussianBlur(diff, (0, 0), DIFF_BLUR_SIGMA)
    otsu, _ = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    level = max(float(otsu), float(DIFF_MIN_THRESHOLD))
    mask = cv2.compare(diff, level, cv2.CMP_GE)
    if DIFF_CLOSE > 1:
        kernel = np.ones((DIFF_CLOSE, DIFF_CLOSE), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    sightings = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area:
            continue
        (cx, cy), (w, h), angle = cv2.minAreaRect(contour)
        if w < 3 or h < 3:
            continue
        long_len, short_len = max(w, h), min(w, h)
        if w < h:
            angle += 90.0
        sightings.append(BlockSighting(
            center=(float(cx), float(cy)),
            quad=cv2.boxPoints(((cx, cy), (w, h), angle if w >= h else angle - 90.0)
                               ).astype(np.float32),
            long_len=float(long_len), short_len=float(short_len),
            angle=_normalise_angle(float(angle)), area=area,
            rectangularity=float(min(1.0, area / max(w * h, 1.0))),
            source="difference",
        ))
    return sightings


def _colour_sightings(frame: np.ndarray, expected_size, min_area: float,
                      **detector_kwargs) -> list[BlockSighting]:
    """Rotated rectangles from the warm-colour detector, at full resolution.

    ``balance`` and ``flatten`` are on here where the live feed leaves them off:
    a calibration is fitted once and then lived with, so the extra passes over
    the frame cost nothing worth counting and they are what make the mask stop
    changing its mind between processing widths.
    """
    kwargs = {
        "balance": True,
        "flatten": True,
        "expected_size": expected_size,
        "min_area": max(int(min_area), 1),
        "max_processing_width": max(frame.shape[1], 1),
    }
    kwargs.update(detector_kwargs)
    detections = detect_blocks(frame, **kwargs)
    return [
        BlockSighting(
            center=detection.center,
            quad=np.asarray(detection.box, dtype=np.float32),
            long_len=max(detection.width, detection.height),
            short_len=min(detection.width, detection.height),
            angle=_normalise_angle(detection.angle),
            area=detection.area,
            rectangularity=detection.rectangularity,
            source="colour",
        )
        for detection in detections
    ]


def _score_sighting(sighting: BlockSighting, *, expected_size,
                    expected_angle, predicted_center, tolerance_px) -> float:
    """How well one sighting matches what a block at this cell should look like.

    Every term is a ratio or an angle, never an absolute pixel count, so the
    same weights work at any camera distance.
    """
    score = 0.30 * min(1.0, sighting.rectangularity / 0.85)
    if expected_size is not None:
        long_expected, short_expected = expected_size
        long_ratio = sighting.long_len / long_expected if long_expected else 0.0
        short_ratio = sighting.short_len / short_expected if short_expected else 0.0
        # A symmetric penalty: 2x too big is as wrong as half the size.
        def closeness(ratio):
            return 0.0 if ratio <= 0 else 1.0 / (1.0 + abs(math.log(ratio)))
        score += 0.30 * (closeness(long_ratio) + closeness(short_ratio)) / 2.0
    if expected_angle is not None:
        gap = _angle_gap(sighting.angle, expected_angle)
        score += 0.15 * max(0.0, 1.0 - gap / 90.0)
    if predicted_center is not None and tolerance_px:
        distance = math.hypot(sighting.center[0] - predicted_center[0],
                              sighting.center[1] - predicted_center[1])
        score += 0.25 * max(0.0, 1.0 - distance / tolerance_px)
    else:
        score += 0.25 * 0.5     # nothing to corroborate against, stay neutral
    return score


def _clear_of_border(sighting: BlockSighting, shape,
                     margin_fraction: float) -> bool:
    """Whether the whole block is comfortably inside the frame."""
    if margin_fraction <= 0:
        return True
    height, width = shape[:2]
    margin = margin_fraction * sighting.short_len
    corners = np.asarray(sighting.quad, dtype=np.float64)
    return bool(corners[:, 0].min() >= margin
                and corners[:, 1].min() >= margin
                and corners[:, 0].max() <= width - 1 - margin
                and corners[:, 1].max() <= height - 1 - margin)


def locate_block(frame: np.ndarray, *, baseline: np.ndarray | None = None,
                 expected_size=None, expected_angle: float | None = None,
                 predicted_center=None, tolerance_px: float | None = None,
                 min_area: float | None = None,
                 edge_margin: float = EDGE_MARGIN_FRACTION,
                 **detector_kwargs) -> BlockSighting:
    """Find the one block in ``frame``, preferring what changed since ``baseline``.

    Two independent front ends are run and pooled: frame differencing against
    the baseline, and the warm-colour detector. A candidate that both agree on
    is promoted to ``source="corroborated"`` and wins on the strength of that
    agreement rather than on either detector's own confidence, which is the
    point of running both.

    Raises :class:`BlockGridError` rather than returning a best guess. A
    calibration built from a wire that looked block-shaped is worse than a
    calibration the operator was told to retry. A block the frame cuts off is
    refused for the same reason: it is measurable, but what it measures is not
    where the block is. Pass ``edge_margin=0`` to keep such a sighting anyway,
    which is for diagnostics, not for saving.
    """
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        raise BlockGridError("a three-channel BGR frame is required",
                             stage="observe")
    if expected_size is not None:
        long_px, short_px = (float(value) for value in expected_size)
        if long_px < short_px:
            long_px, short_px = short_px, long_px
        expected_size = (long_px, short_px)
        floor = MIN_DIFF_AREA_FRACTION * long_px * short_px
    else:
        floor = 200.0
    if min_area is not None:
        floor = float(min_area)

    difference = _difference_sightings(frame, baseline, floor)
    colour = _colour_sightings(frame, expected_size, floor, **detector_kwargs)

    # Promote agreements. "Same block" is judged against the block's own short
    # side, so the test does not need a pixel scale from anywhere else.
    pooled = list(difference)
    for warm in colour:
        near = None
        for index, other in enumerate(pooled):
            span = 0.75 * max(other.short_len, warm.short_len, 1.0)
            if math.hypot(other.center[0] - warm.center[0],
                          other.center[1] - warm.center[1]) <= span:
                near = index
                break
        if near is None:
            pooled.append(warm)
        else:
            # Keep the colour geometry: it is fitted to the block's own edges,
            # while a difference blob also carries the block's cast shadow.
            pooled[near] = replace(warm, source="corroborated")

    inside = [item for item in pooled
              if _clear_of_border(item, frame.shape, edge_margin)]
    if pooled and not inside:
        raise BlockGridError(
            "the only block in view is cut off by the frame edge. A clipped "
            "block's centre is not its centre, so it cannot anchor a "
            "calibration - re-frame the camera so the whole block, including "
            "the part that overhangs the envelope, is visible, or calibrate on "
            "cells further from the edge",
            stage="observe")
    pooled = inside

    if not pooled:
        raise BlockGridError(
            "no block found in the capture: nothing changed since the baseline "
            "and no block-coloured rectangle is in view. Did the placement "
            "actually happen, and is the gantry clear of the camera?",
            stage="observe")

    scored = []
    for sighting in pooled:
        score = _score_sighting(
            sighting, expected_size=expected_size, expected_angle=expected_angle,
            predicted_center=predicted_center, tolerance_px=tolerance_px)
        if sighting.source == "corroborated":
            score += 0.15
        scored.append(replace(sighting, score=score))
    best = max(scored, key=lambda item: item.score)

    if expected_size is not None:
        long_px, short_px = expected_size
        ratio = best.short_len / short_px if short_px else 0.0
        low, high = SIZE_AGREEMENT_RANGE
        if not (low <= ratio <= high):
            raise BlockGridError(
                f"the best candidate is {ratio:.2f}x the expected block width "
                f"({best.short_len:.0f} px against {short_px:.0f} predicted); "
                f"that is not a block", stage="observe")
    if predicted_center is not None and tolerance_px:
        distance = math.hypot(best.center[0] - predicted_center[0],
                              best.center[1] - predicted_center[1])
        if distance > tolerance_px:
            raise BlockGridError(
                f"the block was found {distance:.0f} px from where the "
                f"calibration so far predicts this cell (tolerance "
                f"{tolerance_px:.0f} px). Either it was placed on the wrong "
                f"cell or something else was detected", stage="observe")
    return best


# --------------------------------------------------------------------------- #
# the fit
# --------------------------------------------------------------------------- #

def fit_block_grid(observations, spec: ColorGridSpec, *,
                   image_size=None, strict: bool = True) -> ColorGridCalibration:
    """Fit ``[col,row] -> pixel`` from labelled placements.

    ``observations`` is any iterable of :class:`BlockObservation`. ``strict``
    off skips the quality gates and is for diagnostics only - it exists so a
    tool can *show* an operator the bad fit that was refused, never so a caller
    can save one.
    """
    items = list(observations)
    if len(items) < MIN_OBSERVATIONS:
        raise BlockGridError(
            f"{len(items)} placed block(s) recorded; a checkable fit needs at "
            f"least {MIN_OBSERVATIONS}. Four would fit exactly and prove "
            f"nothing", stage="fit")
    cells = {}
    for item in items:
        if item.cell in cells:
            raise BlockGridError(
                f"cell [{item.cell[0]},{item.cell[1]}] was observed twice; each "
                f"cell may contribute one placement", stage="fit")
        cells[item.cell] = item

    source = np.array([[float(c), float(r)] for c, r in cells], dtype=np.float64)
    target = np.array([item.center for item in cells.values()], dtype=np.float64)

    spread = source.max(axis=0) - source.min(axis=0)
    hull = _hull_area(source)
    if strict:
        if spread[0] < MIN_AXIS_SPREAD_CELLS or spread[1] < MIN_AXIS_SPREAD_CELLS:
            raise BlockGridError(
                f"the placed cells span {spread[0]:.0f}x{spread[1]:.0f} cells; "
                f"both axes need at least {MIN_AXIS_SPREAD_CELLS:g}. A fit from "
                f"one row or one column cannot describe the other axis",
                stage="fit")
        if hull < MIN_HULL_AREA_CELLS:
            raise BlockGridError(
                f"the placed cells enclose only {hull:.1f} square cells and are "
                f"nearly collinear; spread them across the envelope",
                stage="fit")

    matrix, _mask = cv2.findHomography(source, target, 0)
    if matrix is None:
        raise BlockGridError(
            "no homography fits the placed blocks; the correspondences are "
            "degenerate", stage="fit")
    matrix = np.asarray(matrix, dtype=np.float64)

    projected = _project(matrix, source)
    errors = np.linalg.norm(projected - target, axis=1)
    order = list(cells)
    residuals = {cell: float(errors[index]) for index, cell in enumerate(order)}
    worst_index = int(np.argmax(errors))

    mid = (float(np.mean(source[:, 0])), float(np.mean(source[:, 1])))
    pitch_x_px, pitch_y_px, _bx, _by = _local_scale(matrix, spec, mid)
    short_pitch = min(pitch_x_px, pitch_y_px)

    size_ratios, bearing_errors = [], []
    for cell, item in cells.items():
        _px, _py, block_x_px, block_y_px = _local_scale(matrix, spec, cell)
        predicted_short = min(block_x_px, block_y_px)
        if predicted_short > 0:
            size_ratios.append(item.sighting.short_len / predicted_short)
        bearing_errors.append(
            _angle_gap(item.sighting.angle, _bearing(matrix, spec, cell)))

    report = BlockGridReport(
        observations=len(cells),
        mean_residual_px=float(errors.mean()),
        max_residual_px=float(errors.max()),
        worst_cell=order[worst_index],
        short_pitch_px=float(short_pitch),
        hull_area_cells=float(hull),
        size_agreement=float(np.median(size_ratios)) if size_ratios else 0.0,
        max_bearing_error_deg=float(max(bearing_errors)) if bearing_errors else 0.0,
        residuals=residuals,
    )

    if strict:
        problems = []
        if short_pitch <= 0:
            problems.append("the fit predicts a zero-sized cell")
        else:
            if report.mean_residual_px > MAX_MEAN_RESIDUAL_PITCH * short_pitch:
                problems.append(
                    f"mean residual {report.mean_residual_px:.2f} px is more than "
                    f"{MAX_MEAN_RESIDUAL_PITCH:.0%} of a {short_pitch:.0f} px pitch")
            if report.max_residual_px > MAX_RESIDUAL_PITCH * short_pitch:
                worst = order[worst_index]
                problems.append(
                    f"cell [{worst[0]},{worst[1]}] sits {report.max_residual_px:.2f} px "
                    f"from where the other placements predict it")
        low, high = SIZE_AGREEMENT_RANGE
        if size_ratios and not (low <= report.size_agreement <= high):
            problems.append(
                f"the blocks measure {report.size_agreement:.2f}x the footprint the "
                f"fit predicts, so the scale disagrees with config/rig.json")
        if report.max_bearing_error_deg > MAX_ANGLE_DISAGREEMENT_DEG:
            problems.append(
                f"a block's long axis is {report.max_bearing_error_deg:.0f} deg off the "
                f"{spec.mode} orientation; is the rig in the mode being calibrated?")
        if problems:
            raise BlockGridError("; ".join(problems), stage="quality")

    printed = []
    for cell, item in cells.items():
        col, row = cell
        sighting = item.sighting
        _px, _py, block_x_px, block_y_px = _local_scale(matrix, spec, cell)
        predicted_area = max(block_x_px * block_y_px, 1.0)
        clipped = False
        if image_size is not None:
            width, height = image_size
            corners = np.asarray(sighting.quad, dtype=np.float64)
            clipped = bool(corners[:, 0].min() < 0 or corners[:, 1].min() < 0
                           or corners[:, 0].max() > width
                           or corners[:, 1].max() > height)
        printed.append(PrintedCell(
            lattice=cell,
            center=sighting.center,
            quad=np.asarray(sighting.quad, dtype=np.float32),
            # Synthesised from parity so the existing overlays keep drawing a
            # chessboard. It is not a measurement and nothing checks it here -
            # see BlockGridReport for what actually gated this fit.
            color="green" if (col + row) % 2 == 0 else "magenta",
            area=sighting.area,
            fill=float(sighting.area / predicted_area),
            full=True,
            cell=cell,
            edge_clipped=clipped,
        ))
    printed.sort(key=lambda entry: entry.cell)

    metrics = ColorGridMetrics(
        input_size=tuple(image_size) if image_size else (0, 0),
        processing_size=tuple(image_size) if image_size else (0, 0),
        components=len(cells),
        assigned=len(cells),
        full_cells=len(cells),
        lattice_shape=(int(spread[0]) + 1, int(spread[1]) + 1),
        residual_px=report.mean_residual_px,
        max_residual_px=report.max_residual_px,
        # Vacuous by construction: the colours above were derived from the very
        # parity this would check. The real gates are in BlockGridReport.
        parity_agreement=1.0,
        measured_aspect=(max(spec.block_x_cm, spec.block_y_cm)
                         / min(spec.block_x_cm, spec.block_y_cm)),
        window_candidates=1,
        window_index=0,
        window_observed=len(cells),
    )
    calibration = ColorGridCalibration(spec=spec, homography=matrix,
                                       cells=printed, metrics=metrics)
    calibration.block_report = report
    return calibration


def block_workspace_map(calibration: ColorGridCalibration, grid: MachineGrid,
                        image_size, projection=None,
                        convention: str = DEFAULT_HOME_CONVENTION) -> WorkspaceMap:
    """Turn a fitted placed-block calibration into a saveable :class:`WorkspaceMap`.

    Reuses :meth:`ColorGridCalibration.workspace_corners` rather than
    recomputing the envelope: the sheet path's "sheet centimetres" and this
    module's machine centimetres put the envelope's home corner at the same
    lattice coordinate, ``-cell_center_x_cm(0) / pitch_x_cm``, so the two agree
    outright and there is no second implementation to keep in step. Its
    geometry cross-check against ``grid`` is worth having either way.
    """
    corners = calibration.workspace_corners(grid, convention)
    return WorkspaceMap.from_grid(grid, corners, image_size, projection)


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class BlockGridStatus:
    """What a UI needs to draw the calibration run's progress."""

    mode: str
    planned: tuple
    observed: tuple
    remaining: tuple
    ready: bool
    reasons: tuple
    report: BlockGridReport | None = None

    def describe(self) -> str:
        state = "READY TO SAVE" if self.ready else "; ".join(self.reasons)
        detail = f" - {self.report.describe()}" if self.report else ""
        return (f"{self.mode} placed-block calibration: {len(self.observed)}/"
                f"{len(self.planned)} cells - {state}{detail}")


class BlockGridSession:
    """One calibration run: a plan, a baseline, and the placements so far.

    Deliberately step-wise rather than one blocking routine. A full run is
    several minutes of machine motion, and an operator who has to abandon it
    halfway should keep the placements already made - so should a UI that wants
    to show progress, and so should a test that wants to feed it still frames.
    """

    def __init__(self, grid: MachineGrid, *, cells=None,
                 count: int = DEFAULT_OBSERVATIONS, inset: int = 0,
                 baseline=None):
        self.grid = grid
        self.spec = spec_for_grid(grid)
        self.inset = int(inset)
        if cells is None:
            self.planned = plan_calibration_cells(grid, count, inset=inset)
        else:
            planned = tuple((int(col), int(row)) for col, row in cells)
            for col, row in planned:
                if not grid.contains_build_target(col, row):
                    raise BlockGridError(
                        f"[{col},{row}] is not a buildable cell of the "
                        f"{grid.mode} grid", stage="plan")
            if len(set(planned)) != len(planned):
                raise BlockGridError("the plan repeats a cell", stage="plan")
            self.planned = planned
        self.baseline = None if baseline is None else np.asarray(baseline).copy()
        self.observations: dict = {}
        self.image_size = None

    # --- frames --------------------------------------------------------

    def set_baseline(self, frame: np.ndarray) -> None:
        """Record the empty workspace. Every later capture is differenced to it."""
        if frame is None or frame.ndim != 3:
            raise BlockGridError("the baseline must be a BGR frame",
                                 stage="observe")
        self.baseline = np.asarray(frame).copy()
        self.image_size = (frame.shape[1], frame.shape[0])

    # --- prediction, which sharpens as the run goes on ------------------

    def _provisional(self):
        """The best fit available from what has been observed so far, or None.

        Gates off: this is used to *aim* the next search, and refusing to aim
        because the fit is not yet good enough would be backwards.
        """
        if len(self.observations) < MIN_OBSERVATIONS:
            return None
        try:
            return fit_block_grid(self.observations.values(), self.spec,
                                  image_size=self.image_size, strict=False)
        except BlockGridError:
            return None

    def expected_size_px(self, cell=None):
        """The block's predicted ``(long, short)`` pixel size, if it is knowable."""
        provisional = self._provisional()
        if provisional is None:
            return None
        target = cell or self.planned[0]
        _px, _py, block_x, block_y = _local_scale(
            provisional.homography, self.spec, target)
        return (max(block_x, block_y), min(block_x, block_y))

    def predict(self, cell):
        """Where a block on ``cell`` should appear, from the run so far."""
        provisional = self._provisional()
        if provisional is None:
            return None
        return tuple(_project(provisional.homography, [cell])[0])

    # --- the placements ------------------------------------------------

    def observe(self, cell, frame: np.ndarray, **kwargs) -> BlockObservation:
        """Record the block the rig has just placed on ``cell``.

        The frame is searched with whatever the run already knows: once five
        placements are in, the size, the bearing and the position are all
        predicted, and a sighting that disagrees is refused instead of dragging
        the fit. Early on there is nothing to predict from and the search falls
        back to differencing plus shape alone.
        """
        cell = (int(cell[0]), int(cell[1]))
        if not self.grid.contains_build_target(*cell):
            raise BlockGridError(
                f"[{cell[0]},{cell[1]}] is not a buildable cell of the "
                f"{self.grid.mode} grid", stage="observe")
        if frame is None or frame.ndim != 3:
            raise BlockGridError("a BGR frame is required", stage="observe")
        self.image_size = (frame.shape[1], frame.shape[0])

        provisional = self._provisional()
        expected_size = expected_angle = predicted = tolerance = None
        if provisional is not None:
            matrix = provisional.homography
            pitch_x, pitch_y, block_x, block_y = _local_scale(
                matrix, self.spec, cell)
            expected_size = (max(block_x, block_y), min(block_x, block_y))
            expected_angle = _bearing(matrix, self.spec, cell)
            predicted = tuple(_project(matrix, [cell])[0])
            tolerance = PREDICTION_TOLERANCE * min(pitch_x, pitch_y)

        kwargs.setdefault("expected_size", expected_size)
        kwargs.setdefault("expected_angle", expected_angle)
        kwargs.setdefault("predicted_center", predicted)
        kwargs.setdefault("tolerance_px", tolerance)
        sighting = locate_block(frame, baseline=self.baseline, **kwargs)
        observation = BlockObservation(cell=cell, sighting=sighting)
        self.observations[cell] = observation
        # The block stays on the table, so it belongs to the next capture's
        # baseline. Without this every later difference would light up every
        # block placed so far and the newest one would have to win on shape.
        self.baseline = np.asarray(frame).copy()
        return observation

    def drop(self, cell) -> bool:
        """Forget one placement. Returns whether there was one to forget."""
        return self.observations.pop((int(cell[0]), int(cell[1])), None) is not None

    @property
    def remaining(self) -> tuple:
        return tuple(cell for cell in self.planned if cell not in self.observations)

    # --- results -------------------------------------------------------

    def calibration(self, *, strict: bool = True) -> ColorGridCalibration:
        return fit_block_grid(self.observations.values(), self.spec,
                              image_size=self.image_size, strict=strict)

    def workspace_map(self, image_size=None, projection=None,
                      convention: str = DEFAULT_HOME_CONVENTION) -> WorkspaceMap:
        size = image_size or self.image_size
        if size is None:
            raise BlockGridError("no frame has been observed yet",
                                 stage="fit")
        return block_workspace_map(self.calibration(), self.grid, size,
                                   projection, convention)

    def status(self) -> BlockGridStatus:
        reasons, report, ready = [], None, False
        if len(self.observations) < MIN_OBSERVATIONS:
            reasons.append(
                f"{len(self.observations)}/{MIN_OBSERVATIONS} placements recorded")
        else:
            try:
                calibration = self.calibration()
                report = calibration.block_report
                ready = True
            except BlockGridError as exc:
                report = getattr(exc, "report", None)
                reasons.append(str(exc))
        return BlockGridStatus(
            mode=self.grid.mode or "unknown",
            planned=self.planned,
            observed=tuple(sorted(self.observations)),
            remaining=self.remaining,
            ready=ready,
            reasons=tuple(reasons),
            report=report,
        )

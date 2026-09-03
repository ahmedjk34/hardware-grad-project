#!/usr/bin/env python3
"""Clean, grid-straight block outlines for the live feed.

Why this exists, next to ``block_detector.py``
----------------------------------------------
``block_detector.detect_blocks`` answers "what warm shapes are in this frame",
and the feeds drew its answer directly: every block outlined by its own raw
segmentation contour, each in a different colour. That is honest about what was
segmented and bad at everything else. A mask edge wanders by a pixel or two all
the way round a block, so twenty-eight outlines that ought to look like one grid
look like twenty-eight different wobbly shapes; and three colour-cycled outlines
on adjacent blocks read as three unrelated objects.

Meanwhile ``block_grid.py`` draws the same blocks beautifully, because it is not
drawing the segmentation at all - it draws a lattice. This module gives the live
feed the same advantage without making it a calibration:

1. **Throw out what is not a block.** Duplicates from the compound
   decomposition, anything touching the frame border, and - the reason this
   module knows about lattices at all - objects that are wooden and
   block-shaped but do not sit where the grid says a block goes. The holder's
   two thin offcuts beside ``[0,0]`` are exactly that.
2. **Draw a rectangle, not a contour.** Every surviving block is redrawn as a
   true rectangle with the population's own size. A recovered lattice supplies
   its bearing; without one, each block keeps its measured bearing.

Note what is NOT on that list: detecting harder. The obvious move was to borrow
the calibrator's full-resolution, illumination-flattened settings, and measured
against the reference boards it buys nothing at all - every processing width
from 384 to 1024, flattened or not, finds all 29 blocks. It costs up to four
seconds a frame. The 33 -> 29 improvement is entirely the rejection steps, so
this runs the plain detector at its ordinary preview budget. See
``detect_aligned_blocks`` for the numbers.

What is deliberately NOT done
-----------------------------
The rectangle keeps each block's **measured centre**. It would be easy to snap
positions onto the fitted lattice and get a perfect grid picture, and it would
be a lie: this overlay's entire job is to show where blocks actually are, and a
misplaced block must look misplaced. Only the size is always shared. The angle
is shared only when the detections actually support a lattice; loose blocks
must keep their individual angles.
"""

from __future__ import annotations

from dataclasses import replace
import math

import cv2
import numpy as np

from vision.block_detector import BlockDetection, detect_blocks
from vision.block_grid import (
    DUPLICATE_IOU,
    MAX_INDEX_SNAP,
    BlockGridError,
    _deduplicate,
    _lattice_vectors,
    spec_for_grid,
)


# Below this many blocks there is no population to speak of: the median size is
# one or two samples and no lattice can be recovered, so the outlines fall back
# to each block's own rotated rectangle. Still straight - just not shared.
MIN_POPULATION = 4

# A lattice needs enough blocks that "off the lattice" means something. Under
# this the holder-rejection step is skipped rather than guessed at.
MIN_LATTICE_BLOCKS = 6

# How far a detection's box may reach past the frame border, in pixels, before
# it is dropped. The purple rails at the left edge segment as three block-sized
# rectangles whose boxes run off the frame entirely; nothing about their shape
# says they are not blocks, only their position does.
#
# Deliberately a HARD border test rather than the calibrator's "keep a fifth of
# a block clear". The two want opposite things from a clipped block: a
# calibration must refuse it, because a cut-off block's centroid is not its
# centre, while a live overlay should still draw it - the operator can see it
# is at the edge, and hiding a real block is the worse failure. A 20% margin
# here silently dropped blocks the mock camera legitimately places on the
# outermost row.
EDGE_TOLERANCE_PX = 1.0

# How far a detection may sit from an integer lattice site and still be a block
# on that site. Same threshold, and the same reasoning, as block_grid's.
LATTICE_SNAP = MAX_INDEX_SNAP


def _sighting_view(detection: BlockDetection):
    """The minimal shape ``block_grid``'s helpers need from a detection."""
    long_len, short_len = detection.size
    return type("_S", (), {
        "center": detection.center,
        "quad": np.asarray(detection.box, dtype=np.float32),
        "long_len": long_len,
        "short_len": short_len,
        "angle": detection.angle,
        "area": detection.area,
        "rectangularity": detection.rectangularity,
    })()


def _inside_frame(detection: BlockDetection, shape, tolerance: float) -> bool:
    """Whether the box lies within the frame rather than running off it."""
    if tolerance < 0:
        return True
    height, width = shape[:2]
    box = np.asarray(detection.box, dtype=np.float64)
    return bool(box[:, 0].min() >= -tolerance and box[:, 1].min() >= -tolerance
                and box[:, 0].max() <= width - 1 + tolerance
                and box[:, 1].max() <= height - 1 + tolerance)


def _drop_duplicates(detections):
    """Collapse detections that are the same block seen twice.

    ``block_detector``'s compound decomposition proposes overlapping ideal
    rectangles inside one colour component, so a block joined to its neighbour
    by a shadow can produce a third rectangle straddling the seam. Reuses
    ``block_grid``'s IoU pass so the two paths cannot drift apart.
    """
    views = [_sighting_view(item) for item in detections]
    kept = _deduplicate(views, DUPLICATE_IOU)
    keep_centres = {tuple(round(v, 3) for v in item.center) for item in kept}
    return [item for item in detections
            if tuple(round(v, 3) for v in item.center) in keep_centres]


def _lattice_filter(detections, grid):
    """Drop anything that is not on the grid the other blocks describe.

    Returns ``(kept, rejected, bearing)``. ``bearing`` is the lattice's own
    long-axis direction in degrees, which is what makes every drawn rectangle
    agree with every other one instead of each carrying its own measurement
    noise.
    """
    if grid is None or len(detections) < MIN_LATTICE_BLOCKS:
        return list(detections), [], None
    try:
        spec = spec_for_grid(grid)
        views = [_sighting_view(item) for item in detections]
        step_x, step_y, _samples = _lattice_vectors(views, spec)
    except (BlockGridError, ValueError, np.linalg.LinAlgError):
        return list(detections), [], None

    basis = np.column_stack([step_x, step_y])
    if abs(float(np.linalg.det(basis))) < 1e-6:
        return list(detections), [], None
    centres = np.array([item.center for item in detections], dtype=np.float64)
    try:
        raw = np.linalg.solve(basis, (centres - centres[0]).T).T
    except np.linalg.LinAlgError:
        return list(detections), [], None
    error = np.abs(raw - np.round(raw)).max(axis=1)

    kept, rejected = [], []
    for index, detection in enumerate(detections):
        (kept if error[index] <= LATTICE_SNAP else rejected).append(detection)
    # If the "lattice" rejects most of what it saw, it is not the board's
    # lattice - keep everything rather than hide real blocks.
    if len(kept) < 0.7 * len(detections):
        return list(detections), [], None

    # The block's long side lies along the machine axis the mode names, so the
    # bearing comes from the matching step vector.
    step = step_y if spec.block_y_cm >= spec.block_x_cm else step_x
    bearing = math.degrees(math.atan2(float(step[1]), float(step[0])))
    while bearing >= 90.0:
        bearing -= 180.0
    while bearing < -90.0:
        bearing += 180.0
    return kept, rejected, bearing


def _rectify(detections, bearing):
    """Give every block the population's size and a justified angle.

    The centre stays exactly where it was measured. Sharing only the size and
    a recovered lattice bearing makes a board read as one grid. When no lattice
    bearing was recovered, there is no evidence that the blocks are parallel:
    keep each detection's own angle instead of manufacturing a grid from the
    population median.
    """
    if len(detections) < MIN_POPULATION:
        # Not a population - still square each box up to its own rotated rect,
        # which is straighter than the segmentation contour it replaces.
        return [replace(item, contour=np.asarray(item.box, dtype=np.int32)
                        .reshape(-1, 1, 2))
                for item in detections]

    long_med = float(np.median([item.size[0] for item in detections]))
    short_med = float(np.median([item.size[1] for item in detections]))
    out = []
    for item in detections:
        item_bearing = item.angle if bearing is None else bearing
        # minAreaRect's angle names the WIDTH side, and the rectangle below is
        # built long-side-first, so the bearing is offset by a quarter turn.
        rect = (tuple(item.center), (short_med, long_med), item_bearing - 90.0)
        box = cv2.boxPoints(rect)
        out.append(replace(
            item,
            box=box.round().astype(np.int32),
            contour=box.round().astype(np.int32).reshape(-1, 1, 2),
            width=short_med, height=long_med, angle=item_bearing,
        ))
    return out


def detect_aligned_blocks(frame: np.ndarray, *, grid=None,
                          edge_tolerance: float = EDGE_TOLERANCE_PX,
                          rectify: bool = True,
                          **detector_kwargs) -> list[BlockDetection]:
    """Detect blocks and return them as clean, grid-aligned rectangles.

    A drop-in replacement for :func:`block_detector.detect_blocks` - same type
    out, so the feeds' overlay, hover test and snapshot code are unchanged.

    ``grid`` is an optional :class:`rig.grid.MachineGrid`. With one, detections
    that do not sit on the lattice the other blocks describe are dropped, and
    every rectangle is drawn on the recovered lattice bearing. Without a
    recovered lattice the outlines are still squared up and given a common
    size, but each keeps its measured angle.
    """
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("detect_aligned_blocks expects a BGR colour image")

    # Deliberately the plain detector's own working width and no illumination
    # flattening - this runs on every analysed frame on a Pi, and both of those
    # were measured to buy nothing here:
    #
    #   width  flatten   blocks found   board ms   1296px frame ms
    #     384      off        29 / 29         84             103
    #     384       on        29 / 29        291             221
    #    1024      off        29 / 29         60             574
    #    1024       on        29 / 29        543            3894
    #
    # Every setting finds all 29. The 33 -> 29 improvement comes entirely from
    # the rejection steps below, not from resolution or preprocessing, and
    # full-resolution flattening would have cost the live overlay four seconds
    # a frame for exactly nothing. (The CALIBRATOR still flattens: it runs once
    # and its frames are not always this cooperative.)
    #
    # min_area is left alone for the same reason. Lowering it to 250 finds no
    # extra blocks and doubles the cost, because every small contour it admits
    # goes through the compound decomposition's rectangle search: 45 ms at the
    # default, 161 ms at 250.
    kwargs = {}
    kwargs.update(detector_kwargs)
    detections = detect_blocks(frame, **kwargs)
    if not detections:
        return []

    detections = _drop_duplicates(detections)
    detections = [item for item in detections
                  if _inside_frame(item, frame.shape, edge_tolerance)]
    if not detections:
        return []

    detections, _rejected, bearing = _lattice_filter(detections, grid)
    if rectify:
        detections = _rectify(detections, bearing)
    return sorted(detections, key=lambda item: (item.center[1], item.center[0]))

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

1. **Detect properly.** Full resolution, illumination flattened, and a size
   prior once the population says what a block measures here. These are the
   settings the calibrator uses and the live feed did not.
2. **Throw out what is not a block.** Duplicates from the compound
   decomposition, anything touching the frame border, and - the reason this
   module knows about lattices at all - objects that are wooden and
   block-shaped but do not sit where the grid says a block goes. The holder's
   two thin offcuts beside ``[0,0]`` are exactly that.
3. **Draw a rectangle, not a contour.** Every surviving block is redrawn as a
   true rectangle with the population's own size and the lattice's own bearing.

What is deliberately NOT done
-----------------------------
The rectangle keeps each block's **measured centre**. It would be easy to snap
positions onto the fitted lattice and get a perfect grid picture, and it would
be a lie: this overlay's entire job is to show where blocks actually are, and a
misplaced block must look misplaced. Only the size and the angle are shared.
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

# Clearance a detection must keep from the frame border, as a fraction of its
# own short side. The live feed's 384 px working width turns the purple rails
# at the left edge into three block-sized rectangles; they are not blocks, and
# nothing about their shape says so - only their position does.
EDGE_MARGIN = 0.20

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


def _clear_of_border(detection: BlockDetection, shape, margin: float) -> bool:
    if margin <= 0:
        return True
    height, width = shape[:2]
    _long, short = detection.size
    clearance = margin * short
    box = np.asarray(detection.box, dtype=np.float64)
    return bool(box[:, 0].min() >= clearance and box[:, 1].min() >= clearance
                and box[:, 0].max() <= width - 1 - clearance
                and box[:, 1].max() <= height - 1 - clearance)


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
    """Give every block the population's size and one shared angle.

    The centre stays exactly where it was measured. Sharing only the size and
    the bearing is what turns a scatter of individually-fitted boxes into
    something that reads as a grid, without moving any outline off the block it
    belongs to.
    """
    if len(detections) < MIN_POPULATION:
        # Not a population - still square each box up to its own rotated rect,
        # which is straighter than the segmentation contour it replaces.
        return [replace(item, contour=np.asarray(item.box, dtype=np.int32)
                        .reshape(-1, 1, 2))
                for item in detections]

    long_med = float(np.median([item.size[0] for item in detections]))
    short_med = float(np.median([item.size[1] for item in detections]))
    if bearing is None:
        # Median of the measured angles, taken on the doubled angle so that
        # -89 and +89 average to 90 rather than to 0.
        radians = [math.radians(2.0 * item.angle) for item in detections]
        bearing = math.degrees(math.atan2(
            float(np.mean([math.sin(a) for a in radians])),
            float(np.mean([math.cos(a) for a in radians])))) / 2.0

    out = []
    for item in detections:
        # minAreaRect's angle names the WIDTH side, and the rectangle below is
        # built long-side-first, so the bearing is offset by a quarter turn.
        rect = (tuple(item.center), (short_med, long_med), bearing - 90.0)
        box = cv2.boxPoints(rect)
        out.append(replace(
            item,
            box=box.round().astype(np.int32),
            contour=box.round().astype(np.int32).reshape(-1, 1, 2),
            width=short_med, height=long_med, angle=bearing,
        ))
    return out


def detect_aligned_blocks(frame: np.ndarray, *, grid=None,
                          edge_margin: float = EDGE_MARGIN,
                          rectify: bool = True,
                          min_area: int = 250,
                          **detector_kwargs) -> list[BlockDetection]:
    """Detect blocks and return them as clean, grid-aligned rectangles.

    A drop-in replacement for :func:`block_detector.detect_blocks` - same type
    out, so the feeds' overlay, hover test and snapshot code are unchanged.

    ``grid`` is an optional :class:`rig.grid.MachineGrid`. With one, detections
    that do not sit on the lattice the other blocks describe are dropped, and
    every rectangle is drawn on the lattice's own bearing. Without one the
    outlines are still squared up and given a common size, just not checked
    against a grid.
    """
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("detect_aligned_blocks expects a BGR colour image")

    kwargs = {
        # The live feed's 384 px default is a preview budget that predates this
        # overlay caring about precision, and at that width the frame edge
        # produces block-sized false positives. Flattening is what the
        # calibrator uses and is why it segments this board cleanly.
        "max_processing_width": max(frame.shape[1], 1),
        "flatten": True,
        "min_area": int(min_area),
    }
    kwargs.update(detector_kwargs)
    detections = detect_blocks(frame, **kwargs)
    if not detections:
        return []

    detections = _drop_duplicates(detections)
    detections = [item for item in detections
                  if _clear_of_border(item, frame.shape, edge_margin)]
    if not detections:
        return []

    detections, _rejected, bearing = _lattice_filter(detections, grid)
    if rectify:
        detections = _rectify(detections, bearing)
    return sorted(detections, key=lambda item: (item.center[1], item.center[0]))

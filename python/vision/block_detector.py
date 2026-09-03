#!/usr/bin/env python3
"""Block segmentation and geometry extraction for the main camera feed.

The current blocks are pale, warm-coloured pieces on a pale work surface. Their
red-minus-blue response is more stable than brightness, so colour starts the
segmentation and geometry finishes it. The returned contours are the block
edges: the feed draws those contours and the fitted rectangles with
anti-aliased lines so the overlay stays clean without outlining every wire and
shadow in the room.

The detector is deliberately independent of a camera or a window. It can be
used by the live feed now and by later placement/mapping code without opening a
second camera stream.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np

from vision.color_grid import flatten_illumination, white_balance


MAX_PROCESSING_WIDTH = 384
MAX_RECTANGLE_HYPOTHESES = 256
_OPEN_KERNEL = np.ones((3, 3), np.uint8)
_CLOSE_KERNEL = np.ones((5, 5), np.uint8)
_EDGE_KERNEL = np.ones((3, 3), np.uint8)
_NEAR_KERNEL = np.ones((5, 5), np.uint8)


@dataclass
class BlockDetection:
    """One detected block, in pixels of the corrected feed image."""

    contour: np.ndarray
    box: np.ndarray
    center: tuple[float, float]
    width: float
    height: float
    angle: float
    area: float
    rectangularity: float
    solidity: float
    confidence: float
    hue: float

    @property
    def size(self) -> tuple[float, float]:
        return max(self.width, self.height), min(self.width, self.height)


@dataclass
class DetectionMetrics:
    input_size: tuple[int, int] = (0, 0)
    processing_size: tuple[int, int] = (0, 0)
    contours: int = 0
    compound_components: int = 0
    rectangle_hypotheses: int = 0
    exhausted_components: int = 0


@dataclass
class _RectangleCandidate:
    """One standard-block hypothesis inside a compound colour component."""

    box: np.ndarray
    center: tuple[float, float]
    angle: float
    score: float
    mask: np.ndarray


@dataclass
class _CandidateBudget:
    remaining: int = MAX_RECTANGLE_HYPOTHESES
    evaluated: int = 0

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        self.evaluated += 1
        return True


def _warm_mask(frame: np.ndarray, color_threshold: int,
               red_green_threshold: int) -> np.ndarray:
    """Return the warm-block candidate mask.

    Red-minus-blue is used instead of a fixed brightness threshold because the
    work surface is overexposed in the supplied captures. The second channel
    check rejects neutral highlights that happen to be bright.
    """
    blue, green, red = cv2.split(frame)
    # Saturating uint8 subtraction is equivalent here: both thresholds are
    # non-negative, so negative channel differences should fail either way.
    red_blue = cv2.subtract(red, blue)
    red_green = cv2.subtract(red, green)
    mask = cv2.bitwise_and(
        cv2.compare(red_blue, int(color_threshold), cv2.CMP_GE),
        cv2.compare(red_green, int(red_green_threshold), cv2.CMP_GE),
    )

    # Remove single-pixel noise while joining the small gaps in a block's
    # shaded edge. These kernels are intentionally small: a large close would
    # join neighbouring blocks before the touch-splitting step gets a chance.
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _OPEN_KERNEL)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _CLOSE_KERNEL)


def _split_touching(contour: np.ndarray, min_area: float) -> list[np.ndarray]:
    """Split a concave two-block blob along its two deepest edge defects.

    The angled pair in the captures is one connected colour component, but the
    two blocks leave a deep concave notch on each side of their shared seam.
    Connecting those notch points cuts the component into two clean pieces.
    Ordinary rectangular blocks have shallow defects and pass through intact.
    """
    area = cv2.contourArea(contour)
    hull_area = cv2.contourArea(cv2.convexHull(contour))
    if hull_area <= 0 or area / hull_area >= 0.93:
        return [contour]

    hull = cv2.convexHull(contour, returnPoints=False)
    defects = cv2.convexityDefects(contour, hull)
    if defects is None:
        return [contour]

    # A real seam is much deeper than the small mask imperfections around a
    # single block. Scale the cutoff gently with object size, but never below
    # 12 px at the default feed resolution.
    cutoff = max(12.0, np.sqrt(area) * 0.08)
    deep = []
    for start, end, far, depth in defects.reshape(-1, 4):
        if depth / 256.0 >= cutoff:
            deep.append((float(depth), tuple(map(int, contour[int(far), 0]))))
    if len(deep) < 2:
        return [contour]

    # The farthest pair is the seam in a compound blob. This avoids choosing
    # two defects on the same side when a rough edge contributes extras.
    points = [point for _, point in sorted(deep, reverse=True)]
    best = max(
        ((points[i], points[j]) for i in range(len(points))
         for j in range(i + 1, len(points))),
        key=lambda pair: (pair[0][0] - pair[1][0]) ** 2 +
                         (pair[0][1] - pair[1][1]) ** 2,
    )

    x, y, w, h = cv2.boundingRect(contour)
    local = np.zeros((h + 2, w + 2), dtype=np.uint8)
    shifted = contour - np.array([[[x - 1, y - 1]]], dtype=np.int32)
    cv2.drawContours(local, [shifted], -1, 255, -1)
    p0 = (best[0][0] - x + 1, best[0][1] - y + 1)
    p1 = (best[1][0] - x + 1, best[1][1] - y + 1)
    cv2.line(local, p0, p1, 0, 3, cv2.LINE_AA)

    pieces, labels, stats, _ = cv2.connectedComponentsWithStats(local)
    result = []
    for label in range(1, pieces):
        piece_area = stats[label, cv2.CC_STAT_AREA]
        if piece_area < max(min_area * 0.5, 250):
            continue
        piece_mask = np.uint8(labels == label) * 255
        contours, _ = cv2.findContours(piece_mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            piece = max(contours, key=cv2.contourArea)
            piece[:, 0, 0] += x - 1
            piece[:, 0, 1] += y - 1
            result.append(piece)

    # If the proposed seam produced an implausible result, keep the original
    # detection rather than making a false pair of blocks.
    if len(result) == 2 and all(cv2.contourArea(piece) >= min_area * 0.5
                                for piece in result):
        return result
    return [contour]


def _normal_angle(angle: float) -> float:
    """Normalise an unoriented line angle to [-90, 90)."""
    while angle >= 90.0:
        angle -= 180.0
    while angle < -90.0:
        angle += 180.0
    return angle


def _angle_distance(a: float, b: float) -> float:
    return abs(_normal_angle(a - b))


def _rotated_kernel(length: float, width: float, angle: float) -> np.ndarray:
    """Binary morphology kernel shaped like a rotated short block segment."""
    side = int(math.ceil(math.hypot(length, width))) | 1
    kernel = np.zeros((side, side), dtype=np.uint8)
    box = cv2.boxPoints(((side // 2, side // 2), (length, width), angle))
    cv2.fillConvexPoly(kernel, box.round().astype(np.int32), 1)
    return kernel


def _line_orientations(component: np.ndarray, block_length: float,
                       block_width: float) -> list[float]:
    """Find distinct long-edge directions on a compound component."""
    edges = cv2.Canny(component, 50, 150)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180.0,
        threshold=max(8, int(round(block_length * 0.17))),
        minLineLength=max(10, int(round(block_length * 0.30))),
        maxLineGap=max(4, int(round(block_width * 0.30))),
    )
    if lines is None:
        return []

    weighted = []
    for x0, y0, x1, y1 in lines.reshape(-1, 4):
        dx, dy = float(x1 - x0), float(y1 - y0)
        weighted.append((math.hypot(dx, dy),
                         _normal_angle(math.degrees(math.atan2(dy, dx)))))
    weighted.sort(reverse=True)

    # Long edges dominate the sorted list. Keep genuinely different block
    # directions; repeated lines from the two sides of one block collapse.
    result = []
    for _length, angle in weighted:
        if all(_angle_distance(angle, existing) > 12.0 for existing in result):
            result.append(angle)
        if len(result) == 4:
            break
    return result


def _rectangle_mask(shape, center, length, width, angle, *, outline=False):
    mask = np.zeros(shape, dtype=np.uint8)
    box = cv2.boxPoints((center, (length, width), angle)).round().astype(np.int32)
    if outline:
        cv2.polylines(mask, [box], True, 255, 1, cv2.LINE_AA)
    else:
        cv2.fillConvexPoly(mask, box, 255)
    return mask, box


def _seed_centers(eroded: np.ndarray, block_length: float, block_width: float,
                  angle: float) -> list[tuple[tuple[float, float], bool]]:
    """Turn oriented erosion islands into one or more standard-block centres.

    A two-block end-to-end union leaves one long erosion island; side-by-side
    blocks leave one wide island. Reconstructing the island's pre-erosion span
    tells us how many standard lengths/widths fit, so both cases yield multiple
    seeds even when the colour mask has no concavity at all.
    """
    count, labels, stats, _ = cv2.connectedComponentsWithStats(eroded)
    radians = math.radians(angle)
    along = np.array((math.cos(radians), math.sin(radians)), dtype=np.float32)
    across = np.array((-along[1], along[0]), dtype=np.float32)
    kernel_length = block_length * 0.58
    kernel_width = block_width * 0.58
    seeds = []

    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] < 4:
            continue
        ys, xs = np.nonzero(labels == label)
        points = np.column_stack((xs, ys)).astype(np.float32)
        p_along = points @ along
        p_across = points @ across
        centre_along = float((p_along.min() + p_along.max()) * 0.5)
        centre_across = float((p_across.min() + p_across.max()) * 0.5)
        total_length = float(p_along.max() - p_along.min() + kernel_length)
        total_width = float(p_across.max() - p_across.min() + kernel_width)
        n_along = max(1, min(6, int(round(total_length / block_length))))
        n_across = max(1, min(4, int(round(total_width / block_width))))
        multiple = n_along * n_across > 1

        for row in range(n_across):
            across_pos = centre_across + (row - (n_across - 1) / 2) * block_width
            for col in range(n_along):
                along_pos = centre_along + (col - (n_along - 1) / 2) * block_length
                center = along * along_pos + across * across_pos
                seeds.append(((float(center[0]), float(center[1])), multiple))
    return seeds


def _best_rectangle(component: np.ndarray, edge_support: np.ndarray,
                    seed: tuple[float, float], multiple: bool,
                    block_length: float, block_width: float,
                    angle: float, budget: _CandidateBudget) -> _RectangleCandidate | None:
    """Slide one standard rectangle near a seed and maximise fill + edge support."""
    radians = math.radians(angle)
    ux, uy = math.cos(radians), math.sin(radians)
    nx, ny = -uy, ux
    # A single erosion island can be biased by a perpendicular arm, as in an L;
    # let it search farther. Multi-block seeds are already deliberately spaced,
    # so a narrow search prevents them collapsing onto one optimum.
    along_radius = block_length * (0.16 if multiple else 0.35)
    across_radius = block_width * (0.12 if multiple else 0.18)
    best = None

    # Five samples on each axis keep each seed bounded to 25 hypotheses. Local
    # masks make every score proportional to this component, not to the full
    # camera frame.
    for along_shift in np.linspace(-along_radius, along_radius, 5):
        for across_shift in np.linspace(-across_radius, across_radius, 5):
            if not budget.take():
                return best
            center = (
                float(seed[0] + along_shift * ux + across_shift * nx),
                float(seed[1] + along_shift * uy + across_shift * ny),
            )
            filled, box = _rectangle_mask(
                component.shape, center, block_length, block_width, angle)
            pixels = max(cv2.countNonZero(filled), 1)
            inside = cv2.countNonZero(cv2.bitwise_and(filled, component)) / pixels
            outline, _ = _rectangle_mask(
                component.shape, center, block_length, block_width, angle,
                outline=True)
            edge_pixels = max(cv2.countNonZero(outline), 1)
            edge = cv2.countNonZero(cv2.bitwise_and(outline, edge_support)) / edge_pixels
            score = 0.62 * inside + 0.38 * edge
            if best is None or score > best.score:
                best = _RectangleCandidate(box, center, angle, float(score), filled)
    return best


def _box_iou(a: _RectangleCandidate, b: _RectangleCandidate) -> float:
    area_a = abs(cv2.contourArea(a.box))
    area_b = abs(cv2.contourArea(b.box))
    intersection, _ = cv2.intersectConvexConvex(
        a.box.astype(np.float32), b.box.astype(np.float32))
    union = area_a + area_b - intersection
    return float(intersection / union) if union > 0 else 0.0


def _decompose_compound(frame: np.ndarray, hsv: np.ndarray, contour: np.ndarray,
                        block_length: float, block_width: float,
                        min_area: float,
                        metrics: DetectionMetrics | None = None
                        ) -> list[BlockDetection]:
    """Explain one irregular colour blob as standard four-sided blocks."""
    x, y, w, h = cv2.boundingRect(contour)
    pad = max(4, int(round(block_width * 0.25)))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1 = min(frame.shape[1], x + w + pad)
    y1 = min(frame.shape[0], y + h + pad)
    offset = np.array([[[x0, y0]]], dtype=np.int32)
    local_contour = contour - offset
    component = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    cv2.drawContours(component, [local_contour], -1, 255, -1)
    orientations = _line_orientations(component, block_length, block_width)
    if not orientations:
        return []

    # Outer colour boundaries and internal grayscale seams both matter. The
    # latter are what separate aligned blocks whose union has no concavity.
    boundary = cv2.morphologyEx(component, cv2.MORPH_GRADIENT, _EDGE_KERNEL)
    local_frame = frame[y0:y1, x0:x1]
    gray = cv2.cvtColor(local_frame, cv2.COLOR_BGR2GRAY)
    image_edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 20, 60)
    near = cv2.dilate(component, _NEAR_KERNEL)
    edge_support = cv2.bitwise_or(boundary, cv2.bitwise_and(image_edges, near))
    edge_support = cv2.dilate(edge_support, _EDGE_KERNEL)

    candidates = []
    budget = _CandidateBudget()
    if metrics is not None:
        metrics.compound_components += 1
    # Find every cheap erosion-derived seed first, then spend the bounded
    # rectangle-scoring budget on the most plausible ones. Distance from the
    # component boundary is a useful, allocation-free proxy for block support;
    # multi-block lattice seeds win ties because they encode the dimensions of
    # the complete connected union rather than one possibly biased centroid.
    distance = cv2.distanceTransform(component, cv2.DIST_L2, 3)
    ranked_seeds = []
    for angle in orientations:
        kernel = _rotated_kernel(block_length * 0.58, block_width * 0.58, angle)
        eroded = cv2.erode(component, kernel)
        for seed, multiple in _seed_centers(
                eroded, block_length, block_width, angle):
            sx = min(component.shape[1] - 1, max(0, round(seed[0])))
            sy = min(component.shape[0] - 1, max(0, round(seed[1])))
            ranked_seeds.append((bool(multiple), float(distance[sy, sx]),
                                 seed, angle))
    ranked_seeds.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for multiple, _support, seed, angle in ranked_seeds:
        candidate = _best_rectangle(
            component, edge_support, seed, multiple,
            block_length, block_width, angle, budget)
        if candidate is not None and candidate.score >= 0.80:
            candidates.append(candidate)
        if budget.remaining <= 0:
            break
    if metrics is not None:
        metrics.rectangle_hypotheses += budget.evaluated
        metrics.exhausted_components += int(budget.remaining <= 0)

    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    selected = []
    covered = np.zeros_like(component)
    standard_area = block_length * block_width
    # The ceiling already gives overlapping blocks one block of headroom: any
    # positive remainder admits the next hypothesis. Dividing by 0.80 as well
    # double-counted that allowance and let seam-straddling rectangles turn a
    # two-block row into three detections (and a three-block U into four).
    estimated_count = max(2, min(12, int(math.ceil(
        cv2.contourArea(contour) / max(standard_area, 1.0)))))
    for candidate in candidates:
        if any(_box_iou(candidate, existing) > 0.45 for existing in selected):
            continue
        new_pixels = cv2.countNonZero(cv2.bitwise_and(
            candidate.mask, cv2.bitwise_and(component, cv2.bitwise_not(covered))))
        if new_pixels < standard_area * 0.30:
            continue
        selected.append(candidate)
        covered = cv2.bitwise_or(covered, candidate.mask)
        if len(selected) >= estimated_count:
            break

    explained = cv2.countNonZero(cv2.bitwise_and(covered, component))
    component_pixels = max(cv2.countNonZero(component), 1)
    if len(selected) < 2 or explained / component_pixels < 0.68:
        return []

    detections = []
    for candidate in selected:
        ideal_contour = (candidate.box.reshape(-1, 1, 2).astype(np.int32)
                         + offset)
        detection = _geometry(frame, ideal_contour, hsv)
        detection.confidence = candidate.score
        detections.append(detection)
    return detections


def _geometry(frame: np.ndarray, contour: np.ndarray,
              hsv: np.ndarray | None = None) -> BlockDetection:
    area = float(cv2.contourArea(contour))
    rect = cv2.minAreaRect(contour)
    (cx, cy), (rw, rh), angle = rect
    width, height = float(rw), float(rh)
    # OpenCV reports the angle of the rectangle's short-side representation.
    # Present the long-side orientation instead, normalised to [-90, 90), so a
    # horizontal block reads near 0° and a vertical block near +/-90°.
    if width < height:
        angle += 90.0
    if angle >= 90.0:
        angle -= 180.0
    box = cv2.boxPoints(rect).round().astype(np.int32)
    box_area = max(width * height, 1.0)
    hull_area = max(cv2.contourArea(cv2.convexHull(contour)), 1.0)
    rectangularity = min(1.0, area / box_area)
    solidity = min(1.0, area / hull_area)
    # This is a visual quality estimate, not a probability. It remains useful
    # in the HUD when a shadow or stray warm object gets near the threshold.
    confidence = float(np.clip(0.55 * rectangularity + 0.45 * solidity, 0, 1))

    if hsv is None:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    x, y, w, h = cv2.boundingRect(contour)
    local_mask = np.zeros((h, w), dtype=np.uint8)
    local_contour = contour - np.array([[[x, y]]], dtype=np.int32)
    cv2.drawContours(local_mask, [local_contour], -1, 255, -1)
    # The compound path synthesises an *ideal* rectangle, which can hang off
    # the frame. numpy would silently clip the hue ROI while the mask kept its
    # full size, and cv2.mean asserts on the mismatch. Clip both together.
    frame_h, frame_w = hsv.shape[:2]
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, frame_w), min(y + h, frame_h)
    if x1 <= x0 or y1 <= y0:
        hue = 0.0
    else:
        hue = float(cv2.mean(hsv[y0:y1, x0:x1, 0],
                             mask=local_mask[y0 - y:y1 - y, x0 - x:x1 - x])[0])
    return BlockDetection(
        contour=contour,
        box=box,
        center=(float(cx), float(cy)),
        width=width,
        height=height,
        angle=float(angle),
        area=area,
        rectangularity=rectangularity,
        solidity=solidity,
        confidence=confidence,
        hue=hue,
    )


def _detect_blocks_native(frame: np.ndarray, *, color_threshold: int,
                          red_green_threshold: int, min_area: float,
                          max_area: float | None,
                          metrics: DetectionMetrics | None = None,
                          balance: bool = False, flatten: bool = False,
                          expected_size: tuple[float, float] | None = None,
                          ) -> list[BlockDetection]:
    """Detector implementation at its bounded working resolution."""
    # Segment on a corrected copy but measure hue on the original: the caller
    # asked about the block in front of the camera, not about our stand-in for
    # a colour matrix. Red-minus-blue is what the rig's magenta cast attacks
    # hardest, so this is the difference between a stable mask and one that
    # changes its mind between two processing widths.
    source = frame
    if balance:
        source = white_balance(source)
    if flatten:
        source = flatten_illumination(source)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = _warm_mask(source, int(color_threshold), int(red_green_threshold))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    contours = [contour for contour in contours
                if cv2.contourArea(contour) >= min_area]
    if metrics is not None:
        metrics.processing_size = frame.shape[1::-1]
        metrics.contours = len(contours)

    # The blocks have one physical size. Derive its image size from isolated
    # rectangles when possible, with a resolution-scaled fallback that matches
    # the supplied captures. Merged rectangles stay out of this estimate.
    # Block plan is 2.2 x 6.0 cm (aspect ~2.73); the short side is unchanged
    # from the earlier 7.5 cm block, the long side scaled by 6.0 / 7.5.
    #
    # ``expected_size`` replaces that guess with a measurement. The fraction
    # below assumes the block covers a fixed share of the frame, which is true
    # only of the captures it was fitted to; a caller that knows the real
    # px/cm - the calibrator does, from its own homography - should say so
    # rather than let the frame width stand in for a camera distance.
    if expected_size is not None:
        default_length, default_width = (float(value) for value in expected_size)
        if not (default_length > 0 and default_width > 0):
            raise ValueError("expected_size must be two positive lengths in pixels")
        if default_length < default_width:
            default_length, default_width = default_width, default_length
    else:
        default_length = frame.shape[1] * 0.144
        default_width = frame.shape[1] * 0.052
    records = [(contour, _geometry(frame, contour, hsv)) for contour in contours]
    size_sources = []
    for _contour, detection in records:
        long_side, short_side = detection.size
        if detection.rectangularity < 0.80 or detection.solidity < 0.82:
            continue
        if not (default_length * 0.70 <= long_side <= default_length * 1.30):
            continue
        if not (default_width * 0.65 <= short_side <= default_width * 1.30):
            continue
        size_sources.append((long_side, short_side))
    if size_sources:
        block_length = float(np.median([size[0] for size in size_sources]))
        block_width = float(np.median([size[1] for size in size_sources]))
    else:
        block_length, block_width = default_length, default_width

    def standard_sized(detection):
        long_side, short_side = detection.size
        return (block_length * 0.67 <= long_side <= block_length * 1.35 and
                block_width * 0.58 <= short_side <= block_width * 1.50)

    detections = []
    for contour, original in records:
        pieces = _split_touching(contour, min_area)
        split_detections = [_geometry(frame, piece, hsv) for piece in pieces]
        split_is_valid = len(split_detections) > 1 and all(
            standard_sized(detection) and
            detection.rectangularity >= 0.72 and detection.solidity >= 0.75
            for detection in split_detections)

        if split_is_valid:
            candidates = split_detections
        elif (standard_sized(original) and original.rectangularity >= 0.72 and
              original.solidity >= 0.75):
            candidates = [original]
        else:
            candidates = _decompose_compound(
                frame, hsv, contour, block_length, block_width, min_area, metrics)

        for detection in candidates:
            if detection.area < min_area:
                continue
            if max_area is not None and detection.area > max_area:
                continue
            detections.append(detection)

    return sorted(detections, key=lambda d: (d.center[1], d.center[0]))


def _rescale_detection(detection: BlockDetection, sx: float,
                       sy: float) -> BlockDetection:
    contour = detection.contour.astype(np.float32)
    contour[:, :, 0] *= sx
    contour[:, :, 1] *= sy
    contour = contour.round().astype(np.int32)
    rect = cv2.minAreaRect(contour)
    (cx, cy), (rw, rh), angle = rect
    if rw < rh:
        angle += 90.0
    if angle >= 90.0:
        angle -= 180.0
    box = cv2.boxPoints(rect).round().astype(np.int32)
    area = float(cv2.contourArea(contour))
    box_area = max(float(rw * rh), 1.0)
    hull_area = max(float(cv2.contourArea(cv2.convexHull(contour))), 1.0)
    return BlockDetection(
        contour=contour, box=box, center=(float(cx), float(cy)),
        width=float(rw), height=float(rh), angle=float(angle), area=area,
        rectangularity=min(1.0, area / box_area),
        solidity=min(1.0, area / hull_area),
        confidence=detection.confidence, hue=detection.hue,
    )


def detect_blocks(frame: np.ndarray, *, color_threshold: int = 8,
                  red_green_threshold: int = 3, min_area: int = 500,
                  max_area: int | None = None,
                  max_processing_width: int = MAX_PROCESSING_WIDTH,
                  metrics: DetectionMetrics | None = None,
                  balance: bool = False, flatten: bool = False,
                  expected_size: tuple[float, float] | None = None,
                  ) -> list[BlockDetection]:
    """Detect warm rectangular blocks in one corrected BGR frame.

    Results are sorted top-to-bottom then left-to-right, making the displayed
    IDs stable and making hover information easy to compare frame to frame.
    Thresholds are arguments so a later camera position or block colour can be
    tuned without changing the detector's geometry code.

    ``balance`` and ``flatten`` run :func:`color_grid.white_balance` and
    :func:`color_grid.flatten_illumination` over the segmentation copy first.
    ``expected_size`` is ``(long_px, short_px)`` for one block and replaces the
    frame-width size guess. All three default off, so the live feed keeps the
    behaviour it was tuned for; :mod:`vision.block_grid` turns them on, where
    one wrong answer is written to disk instead of redrawn 30 times a second.
    """
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("detect_blocks expects a BGR colour image")
    if min_area <= 0 or max_processing_width <= 0:
        raise ValueError("min_area and max_processing_width must be positive")

    original_h, original_w = frame.shape[:2]
    if metrics is not None:
        metrics.processing_size = (0, 0)
        metrics.contours = 0
        metrics.compound_components = 0
        metrics.rectangle_hypotheses = 0
        metrics.exhausted_components = 0
        metrics.input_size = (original_w, original_h)
    if original_w <= max_processing_width:
        return _detect_blocks_native(
            frame, color_threshold=int(color_threshold),
            red_green_threshold=int(red_green_threshold),
            min_area=float(min_area),
            max_area=None if max_area is None else float(max_area),
            metrics=metrics, balance=balance, flatten=flatten,
            expected_size=expected_size)

    scale = max_processing_width / original_w
    work_h = max(1, round(original_h * scale))
    work = cv2.resize(frame, (max_processing_width, work_h),
                      interpolation=cv2.INTER_AREA)
    sx, sy = original_w / work.shape[1], original_h / work.shape[0]
    area_scale = sx * sy
    # The size prior is stated in input-frame pixels, so it has to come down to
    # the working resolution with everything else. Both axes shrink by the same
    # factor here, so one scale is enough.
    work_expected = None if expected_size is None else (
        float(expected_size[0]) / sx, float(expected_size[1]) / sy)
    detections = _detect_blocks_native(
        work, color_threshold=int(color_threshold),
        red_green_threshold=int(red_green_threshold),
        min_area=float(min_area) / area_scale,
        max_area=None if max_area is None else float(max_area) / area_scale,
        metrics=metrics, balance=balance, flatten=flatten,
        expected_size=work_expected)
    return sorted((_rescale_detection(detection, sx, sy)
                   for detection in detections),
                  key=lambda d: (d.center[1], d.center[0]))

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

import cv2
import numpy as np


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


def _warm_mask(frame: np.ndarray, color_threshold: int,
               red_green_threshold: int) -> np.ndarray:
    """Return the warm-block candidate mask.

    Red-minus-blue is used instead of a fixed brightness threshold because the
    work surface is overexposed in the supplied captures. The second channel
    check rejects neutral highlights that happen to be bright.
    """
    blue, green, red = cv2.split(frame)
    red_blue = red.astype(np.int16) - blue.astype(np.int16)
    red_green = red.astype(np.int16) - green.astype(np.int16)
    mask = ((red_blue >= color_threshold) &
            (red_green >= red_green_threshold)).astype(np.uint8) * 255

    # Remove single-pixel noise while joining the small gaps in a block's
    # shaded edge. These kernels are intentionally small: a large close would
    # join neighbouring blocks before the touch-splitting step gets a chance.
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))


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


def _geometry(frame: np.ndarray, contour: np.ndarray) -> BlockDetection:
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

    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hue = float(cv2.mean(hsv[:, :, 0], mask=mask)[0])
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


def detect_blocks(frame: np.ndarray, *, color_threshold: int = 8,
                  red_green_threshold: int = 3, min_area: int = 500,
                  max_area: int | None = None) -> list[BlockDetection]:
    """Detect warm rectangular blocks in one corrected BGR frame.

    Results are sorted top-to-bottom then left-to-right, making the displayed
    IDs stable and making hover information easy to compare frame to frame.
    Thresholds are arguments so a later camera position or block colour can be
    tuned without changing the detector's geometry code.
    """
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("detect_blocks expects a BGR colour image")

    mask = _warm_mask(frame, int(color_threshold), int(red_green_threshold))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    detections = []
    for contour in contours:
        if cv2.contourArea(contour) < min_area:
            continue
        pieces = _split_touching(contour, min_area)
        for piece in pieces:
            area = cv2.contourArea(piece)
            if area < min_area or (max_area is not None and area > max_area):
                continue
            detection = _geometry(frame, piece)
            # Warm hardware and cables can pass the colour test, especially at
            # the bottom edge of a wide-angle frame. Blocks are substantially
            # more rectangular than those fragments, so reject poor geometry
            # before they reach the overlay or hover picker.
            if detection.rectangularity < 0.72 or detection.solidity < 0.75:
                continue
            detections.append(detection)

    return sorted(detections, key=lambda d: (d.center[1], d.center[0]))

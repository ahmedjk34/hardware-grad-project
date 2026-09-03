#!/usr/bin/env python3
"""Run the block detector against the committed camera captures.

    cd python
    ../.venv/bin/python tests/test_block_detector.py

These are image fixtures, not a substitute for checking the live Pi feed. They
protect the useful baseline: every listed raw capture has its hand-counted
number of blocks and synthetic touching-block unions do not collapse into one
detection or grow an extra seam-straddling block.
"""

from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.block_detector import detect_blocks


CAPTURES = Path(__file__).resolve().parents[1] / "captures"
paths = sorted(CAPTURES.glob("*corrected*.png"))
if not paths:
    raise SystemExit(f"no corrected captures found in {CAPTURES}")

# How many blocks are actually in each capture, counted by eye. The glob used to
# assert a blanket 6, which was the count in one older scene: every capture
# added since has failed for having a different number of blocks in it rather
# than for anything the detector did. A capture with no entry here is only
# checked for not crashing, so dropping a new file in stays cheap.
EXPECTED_BLOCKS = {
    "20260902-165930_corrected_equidistant-lens160-out120-k+0.04_+0.00_+0.02_"
    "+0.00-c+0_+0-f1.200_1.000-s+0.000-p-0.028_+0.000.png": 3,
}

failed = False
for path in paths:
    image = cv2.imread(str(path))
    detections = detect_blocks(image)
    expected = EXPECTED_BLOCKS.get(path.name)
    if expected is None:
        print(f"ok    {path.name}: {len(detections)} blocks (count not asserted)")
        continue
    ok = len(detections) == expected
    print(f"{'ok  ' if ok else 'FAIL'}  {path.name}: "
          f"{len(detections)}/{expected} blocks")
    failed |= not ok

# The loose-block source image is deliberately outside the corrected-image
# glob. Its overlaid partner is not an input fixture: feeding annotations back
# through colour segmentation tests the green ink, not the wooden blocks.
for filename, expected in (
        ("WITHOUT_BLOCK_DETECTOR_ON_EXAMPLE.png", 10),):
    path = CAPTURES / filename
    image = cv2.imread(str(path))
    detections = [] if image is None else detect_blocks(image)
    ok = len(detections) == expected
    print(f"{'ok  ' if ok else 'FAIL'}  {filename}: "
          f"{len(detections)}/{expected} blocks")
    failed |= not ok


def paint_block(image, center, angle=0):
    box = cv2.boxPoints((center, (69, 20), angle)).round().astype(np.int32)
    cv2.fillConvexPoly(image, box, (210, 215, 235))
    # A real block contributes a dark perimeter/internal seam even when its
    # colour mask merges perfectly with the next block.
    cv2.polylines(image, [box], True, (170, 175, 195), 2)


# Protect the topology cases the geometry fitter is designed for, including
# unions with no concavity at all (straight rows and side-by-side blocks).
synthetic_cases = []
image = np.full((440, 384, 3), 230, np.uint8)
paint_block(image, (180, 180), 0)
paint_block(image, (146, 205), 90)
synthetic_cases.append(("synthetic L", image, 2))

image = np.full((440, 384, 3), 230, np.uint8)
paint_block(image, (180, 220), 0)
paint_block(image, (146, 186), 90)
paint_block(image, (214, 186), 90)
synthetic_cases.append(("synthetic U", image, 3))

image = np.full((440, 384, 3), 230, np.uint8)
paint_block(image, (150, 180), 0)
paint_block(image, (219, 180), 0)
synthetic_cases.append(("end-to-end pair", image, 2))

image = np.full((440, 384, 3), 230, np.uint8)
paint_block(image, (180, 170), 0)
paint_block(image, (180, 190), 0)
synthetic_cases.append(("side-by-side pair", image, 2))

image = np.full((440, 384, 3), 230, np.uint8)
paint_block(image, (190, 200), 0)
paint_block(image, (190, 200), 90)
synthetic_cases.append(("crossed pair", image, 2))

for name, image, expected in synthetic_cases:
    # The renderer knows the exact synthetic footprint. Supplying it avoids
    # testing the capture-specific frame-width size fallback instead of the
    # compound decomposition this section is about.
    found = len(detect_blocks(
        image, min_area=400, expected_size=(69, 20)))
    ok = found == expected
    print(f"{'ok  ' if ok else 'FAIL'}  {name}: {found}/{expected} blocks")
    failed |= not ok

raise SystemExit(1 if failed else 0)

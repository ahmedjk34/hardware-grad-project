#!/usr/bin/env python3
"""Run the block detector against the committed camera captures.

    cd python
    ../.venv/bin/python tests/test_block_detector.py

These are image fixtures, not a substitute for checking the live Pi feed. They
protect the useful baseline: the original views contain six blocks, V2's L and
U unions decompose correctly, and synthetic end-to-end/side-by-side unions do
not collapse into one detection.
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

failed = False
for path in paths:
    image = cv2.imread(str(path))
    detections = detect_blocks(image)
    ok = len(detections) == 6
    print(f"{'ok  ' if ok else 'FAIL'}  {path.name}: {len(detections)} blocks")
    failed |= not ok


# V2 are desktop screenshots of the live window, so recover the displayed
# 384x440 feed first. Existing coloured overlays contaminate the isolated
# blocks; the regions below deliberately test only the previously MISSED raw
# compound shape in the middle: an L made of two blocks, then a U made of three.
v2 = CAPTURES / "v2"
v2_cases = (
    (v2 / "20260820_13h14m38s_grim.png", (180, 200, 285, 295), 2, "V2 L pair"),
    (v2 / "20260820_13h16m07s_grim.png", (160, 115, 270, 230), 3, "V2 U triple"),
)
for path, (x0, y0, x1, y1), expected, name in v2_cases:
    screenshot = cv2.imread(str(path))
    if screenshot is None:
        print(f"FAIL  {name}: missing {path}")
        failed = True
        continue
    feed = cv2.resize(screenshot[102:881, 380:1060], (384, 440),
                      interpolation=cv2.INTER_AREA)
    detections = detect_blocks(feed)
    found = sum(x0 <= d.center[0] <= x1 and y0 <= d.center[1] <= y1
                for d in detections)
    ok = found == expected
    print(f"{'ok  ' if ok else 'FAIL'}  {name}: {found}/{expected} blocks")
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
    found = len(detect_blocks(image, min_area=400))
    ok = found == expected
    print(f"{'ok  ' if ok else 'FAIL'}  {name}: {found}/{expected} blocks")
    failed |= not ok

raise SystemExit(1 if failed else 0)

#!/usr/bin/env python3
"""Run the block detector against the committed camera captures.

    cd python
    ../.venv/bin/python tests/test_block_detector.py

These are image fixtures, not a substitute for checking the live Pi feed. They
protect the useful baseline: the three captured views contain six blocks,
including the two touching angled pieces, and the warm hardware at the bottom
is not reported as a block.
"""

from pathlib import Path
import sys

import cv2

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

raise SystemExit(1 if failed else 0)

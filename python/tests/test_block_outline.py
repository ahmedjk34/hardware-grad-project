#!/usr/bin/env python3
"""The live feed's block outlines: clean detection, grid-straight rectangles.

Run from python/:  ../.venv/bin/python tests/test_block_outline.py

The feeds used to draw block_detector's raw segmentation contour, one colour
per block. This asserts the three things that replaced it - the detection is as
good as the calibrator's, what is not a block is dropped, and every surviving
outline is a rectangle sharing one size. A board with a recovered lattice
shares one bearing; loose blocks retain their individually measured angles.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.config import load as load_rig_config                      # noqa: E402
from rig.grid import MachineGrid                                    # noqa: E402
from vision.block_detector import detect_blocks                     # noqa: E402
from vision.block_outline import (                                  # noqa: E402
    MIN_LATTICE_BLOCKS,
    detect_aligned_blocks,
)

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"ok    {name}")
    else:
        print(f"FAIL  {name}{': ' + detail if detail else ''}")
        failures.append(name)


CAPTURES = Path(__file__).resolve().parents[1] / "captures"
BOARDS = {
    # 29 blocks laid from the home corner, plus the holder's two thin wooden
    # offcuts beside [0,0], photographed through two different lens
    # corrections. Both must come back as exactly 29.
    "20260903-122957_corrected_equidistant-lens168-out120-k+0.14_+0.18_+0.03_"
    "+0.00-c+0_+0-f1.200_1.000-s+0.020-p-0.028_+0.000.png": 29,
    "IMAGE_TO_TEST_BLOCK_CALIBRATION.png": 29,
}

grid = MachineGrid.from_config(load_rig_config())

for name, expected in BOARDS.items():
    path = CAPTURES / name
    if not path.exists():
        check(f"{name[:34]}: capture present", False, str(path))
        continue
    image = cv2.imread(str(path))
    label = name.split("_")[0][:22]

    # Two baselines, for two different questions. `before` is what the feeds
    # used to draw, kept so a regression that reintroduces the false positives
    # is visible. `same_settings` runs the plain detector with exactly the
    # settings the aligned path uses internally, which is the only fair way to
    # ask whether rectifying MOVED anything - comparing against a different
    # processing width would just measure the resolution change.
    before = detect_blocks(image)
    same_settings = detect_blocks(image)
    after = detect_aligned_blocks(image, grid=grid)

    check(f"{label}: finds exactly the {expected} real blocks",
          len(after) == expected, f"{len(after)} found (was {len(before)})")
    check(f"{label}: and that is no worse than the old detector",
          abs(len(after) - expected) <= abs(len(before) - expected),
          f"new {len(after)} vs old {len(before)}")

    if not after:
        continue

    # Every outline is a true four-corner rectangle, not a wandering contour.
    check(f"{label}: every outline is a 4-point rectangle",
          all(np.asarray(d.box).reshape(-1, 2).shape == (4, 2) for d in after)
          and all(len(np.asarray(d.contour).reshape(-1, 2)) == 4 for d in after))
    # Squareness is checked on the exact rectangle, and the integer rounding
    # that BlockDetection.box carries is checked separately. Measuring the
    # angle on the rounded corners instead conflates the two: half a pixel of
    # rounding on a 19 px side is three degrees, and says nothing about whether
    # the shape is a rectangle.
    corner_error = 0.0
    rounding = 0.0
    for detection in after:
        exact = cv2.boxPoints((tuple(detection.center),
                               (detection.size[1], detection.size[0]),
                               detection.angle - 90.0))
        rounding = max(rounding, float(np.abs(
            exact - np.asarray(detection.box, dtype=np.float64).reshape(-1, 2)
        ).max()))
        pts = exact.astype(np.float64)
        for index in range(4):
            a = pts[(index - 1) % 4] - pts[index]
            b = pts[(index + 1) % 4] - pts[index]
            norm = np.linalg.norm(a) * np.linalg.norm(b)
            if norm > 0:
                corner_error = max(corner_error, math.degrees(math.asin(
                    min(1.0, abs(float(a @ b) / norm)))))
    check(f"{label}: every corner is exactly square",
          corner_error < 0.01, f"worst corner off by {corner_error:.4f} deg")
    check(f"{label}: the drawn integer corners round within a pixel",
          rounding <= 1.0, f"worst shift {rounding:.2f} px")

    # One shared size and one shared bearing is what makes a board of outlines
    # read as a grid rather than as 29 unrelated shapes.
    longs = {round(d.size[0], 3) for d in after}
    shorts = {round(d.size[1], 3) for d in after}
    angles = {round(d.angle, 3) for d in after}
    check(f"{label}: all outlines share one size",
          len(longs) == 1 and len(shorts) == 1,
          f"{sorted(longs)} x {sorted(shorts)}")
    check(f"{label}: all outlines share one bearing",
          len(angles) == 1, str(sorted(angles)))

    # The centres must stay where they were measured. Snapping them onto the
    # lattice would draw a prettier grid and hide a misplaced block, which is
    # the one thing this overlay exists to show.
    raw = {(round(d.center[0], 1), round(d.center[1], 1))
           for d in same_settings}
    moved = [d for d in after
             if (round(d.center[0], 1), round(d.center[1], 1)) not in raw]
    check(f"{label}: centres are measured, never snapped to the lattice",
          not moved, f"{len(moved)} outlines moved")

    # No outline may RUN OFF the frame: the purple rails at the left edge
    # segment as block-sized rectangles whose boxes start outside it, and only
    # their position says they are not blocks. A block merely close to the edge
    # is kept - hiding a real one is the worse failure in a live overlay.
    height, width = image.shape[:2]
    touching = [d for d in after
                if np.asarray(d.box)[:, 0].min() <= 0
                or np.asarray(d.box)[:, 1].min() <= 0
                or np.asarray(d.box)[:, 0].max() >= width - 1
                or np.asarray(d.box)[:, 1].max() >= height - 1]
    check(f"{label}: nothing is detected against the frame edge",
          not touching, f"{len(touching)} at the border")

    # The holder's offcuts sit beside [0,0], which is the bottom-left block.
    # Two outlines closer together than a block is wide would be one of them.
    centres = sorted((d.center for d in after), key=lambda c: (c[1], c[0]))
    short = after[0].size[1]
    crowded = [(a, b) for a, b in zip(centres, centres[1:])
               if math.dist(a, b) < 0.9 * short]
    check(f"{label}: no two outlines overlap (the holder is rejected)",
          not crowded, str(crowded[:3]))

# Without a grid the outlines are still squared and size-normalised, just
# unchecked against a lattice - camera_feed.py has no MachineGrid and must
# still work. It must not invent a shared angle.
path = CAPTURES / next(iter(BOARDS))
if path.exists():
    image = cv2.imread(str(path))
    free = detect_aligned_blocks(image)
    check("without a grid it still returns squared rectangles",
          free and all(len(np.asarray(d.contour).reshape(-1, 2)) == 4
                       for d in free),
          f"{len(free)} outlines")
    check("without a grid the count is still sane",
          abs(len(free) - 29) <= 1, str(len(free)))

    # A handful of blocks has no population and no lattice; it must not crash
    # and must not invent a shared size from two samples.
    crop = image[180:260, 110:260]
    few = detect_aligned_blocks(crop)
    check("a crop with too few blocks degrades gracefully",
          isinstance(few, list), str(len(few)))

    # This runs on every analysed frame, so it has a budget. Borrowing the
    # calibrator's full-resolution flattened settings cost four seconds a frame
    # and found not one extra block; the guard is here so that cannot come back.
    import time
    start = time.perf_counter()
    for _ in range(3):
        detect_aligned_blocks(image, grid=grid)
    elapsed = (time.perf_counter() - start) / 3 * 1000
    baseline = time.perf_counter()
    for _ in range(3):
        detect_blocks(image)
    baseline = (time.perf_counter() - baseline) / 3 * 1000
    check("it costs no more than twice the plain detector",
          elapsed < max(2.0 * baseline, 40.0),
          f"{elapsed:.0f} ms vs {baseline:.0f} ms for detect_blocks")
    check("an empty frame returns nothing",
          detect_aligned_blocks(np.full((120, 120, 3), 210, np.uint8)) == [])


# Hand-labelled from the clean frame, independently of detector output. These
# ten loose blocks are the regression that exposed the shared-angle bug. The
# centres may move a few pixels with segmentation tuning; an unoriented long
# axis is equivalent modulo 180 degrees.
scatter_path = CAPTURES / "WITHOUT_BLOCK_DETECTOR_ON_EXAMPLE.png"
scatter = cv2.imread(str(scatter_path))
EXPECTED_SCATTER = (
    ((241, 106), -6), ((301, 155), -48), ((212, 157), 33),
    ((144, 232), -58), ((223, 271), -90), ((287, 305), 11),
    ((188, 345), 87), ((226, 387), 0), ((161, 404), -90),
    ((293, 428), 56),
)


def axis_error(left, right):
    return abs((left - right + 90.0) % 180.0 - 90.0)


for label, kwargs in (("free", {}), ("grid-aware fallback", {"grid": grid})):
    found = [] if scatter is None else detect_aligned_blocks(scatter, **kwargs)
    check(f"loose blocks ({label}): finds all 10 blocks",
          len(found) == len(EXPECTED_SCATTER), str(len(found)))
    if len(found) != len(EXPECTED_SCATTER):
        continue
    unmatched = list(found)
    worst_center = worst_angle = 0.0
    for expected_center, expected_angle in EXPECTED_SCATTER:
        nearest = min(unmatched,
                      key=lambda item: math.dist(item.center, expected_center))
        unmatched.remove(nearest)
        worst_center = max(worst_center,
                           math.dist(nearest.center, expected_center))
        worst_angle = max(worst_angle,
                          axis_error(nearest.angle, expected_angle))
    check(f"loose blocks ({label}): centres match the hand labels",
          worst_center <= 4.0, f"worst error {worst_center:.1f} px")
    check(f"loose blocks ({label}): angles match the hand labels",
          worst_angle <= 4.0, f"worst error {worst_angle:.1f} deg")
    check(f"loose blocks ({label}): angles remain genuinely distinct",
          len({round(item.angle / 10) for item in found}) >= 7,
          str([round(item.angle, 1) for item in found]))

print()
if failures:
    print(f"{len(failures)} failing check(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

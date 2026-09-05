#!/usr/bin/env python3
"""Draw what block_levels sees on a capture: surfaces, heights, and what is on top.

    cd python
    ../.venv/bin/python tools/annotate_levels.py captures/*.png --out /tmp/levels

Writes one annotated PNG per input, plus a side-by-side surface-split image when
``--masks`` is given. This is the fastest way to see WHY a level came out the way
it did -- the same role ``--annotate`` plays for the block calibrator.

``--camera-height`` unlocks level numbers and the parallax correction. Without
it the tool still shows which block is on top of which, which is the part that
does not need a calibrated camera. See docs/BLOCK-VISION.md section 6.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.block_levels import (                                   # noqa: E402
    LevelMetrics,
    detect_leveled_blocks,
    height_map,
    split_surfaces,
)

TOP_COLOR = (120, 240, 120)
COVERED_COLOR = (90, 90, 220)
GROUND_COLOR = (240, 200, 90)


def annotate(frame, blocks, metrics, *, show_ground):
    canvas = frame.copy()
    for index, block in enumerate(blocks):
        colour = TOP_COLOR if block.on_top else COVERED_COLOR
        cv2.drawContours(canvas, [block.detection.box], -1, colour, 2,
                         cv2.LINE_AA)
        if show_ground and block.height_cm is not None:
            # Where the footprint actually is, versus where the block appears.
            ground = block.ground_box.round().astype(np.int32)
            cv2.drawContours(canvas, [ground], -1, GROUND_COLOR, 1, cv2.LINE_AA)
            cv2.line(canvas,
                     tuple(np.round(block.detection.center).astype(int)),
                     tuple(np.round(block.ground_center).astype(int)),
                     GROUND_COLOR, 1, cv2.LINE_AA)

        label = f"{index}"
        if block.level is not None:
            label += f" L{block.level}"
        elif block.height_ratio is not None:
            label += f" q{block.height_ratio:.3f}"
        if not block.on_top:
            label += f" <{block.covered_by}"
        if block.inherited:
            label += " ~"
        x, y = np.round(block.detection.center).astype(int)
        cv2.putText(canvas, label, (x - 18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                    (20, 20, 20), 3, cv2.LINE_AA)
        cv2.putText(canvas, label, (x - 18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                    colour, 1, cv2.LINE_AA)

    height = ("declined" if metrics.camera_height_cm is None
              else f"{metrics.camera_height_cm:.1f}cm"
                   + ("*" if metrics.self_calibrated else ""))
    lines = [
        f"blocks {len(blocks)}  tops {sum(b.on_top for b in blocks)}"
        f"  stacks {metrics.stacks}  covered {metrics.suppressed}",
        f"measured {metrics.measured}  inherited {metrics.inherited}"
        f"  split {'ok' if metrics.split_ok else 'REFUSED'}"
        f" ({metrics.separability:.2f})",
        f"camera {height}",
    ]
    for row, text in enumerate(lines):
        origin = (8, 18 + row * 16)
        cv2.putText(canvas, text, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (20, 20, 20), 3, cv2.LINE_AA)
        cv2.putText(canvas, text, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (250, 250, 250), 1, cv2.LINE_AA)
    return canvas


def surfaces_image(frame, masks):
    painted = np.zeros((*masks.top.shape, 3), np.uint8)
    painted[masks.top > 0] = (90, 230, 90)
    painted[masks.side > 0] = (70, 70, 230)
    painted[masks.solid_side > 0] = (240, 120, 60)
    painted = cv2.resize(painted, (frame.shape[1], frame.shape[0]),
                         interpolation=cv2.INTER_NEAREST)
    return np.hstack([frame, painted])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=Path("."),
                        help="directory for the annotated PNGs")
    parser.add_argument("--block-height", type=float, required=True,
                        metavar="CM",
                        help="firmware BLOCK_HEIGHT_CM; the Pi keeps no copy, "
                             "so it must be given")
    parser.add_argument("--camera-height", type=float, default=None,
                        metavar="CM",
                        help="measured camera height above the table; unlocks "
                             "level numbers and the parallax correction")
    parser.add_argument("--self-calibrate", action="store_true",
                        help="fit a camera height from the frame instead "
                             "(provisional; see docs/BLOCK-VISION.md)")
    parser.add_argument("--masks", action="store_true",
                        help="also write the surface split")
    parser.add_argument("--width", type=int, default=384,
                        help="processing width (default 384)")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    for path in args.images:
        frame = cv2.imread(str(path))
        if frame is None:
            print(f"  skip {path}: unreadable")
            continue
        metrics = LevelMetrics()
        blocks = detect_leveled_blocks(
            frame, block_height_cm=args.block_height,
            camera_height_cm=args.camera_height,
            self_calibrate=args.self_calibrate,
            max_processing_width=args.width, metrics=metrics)

        target = args.out / f"{path.stem}_levels.png"
        cv2.imwrite(str(target), annotate(
            frame, blocks, metrics,
            show_ground=metrics.camera_height_cm is not None))
        print(f"  {path.name}: {len(blocks)} blocks, "
              f"{sum(b.on_top for b in blocks)} on top, "
              f"{metrics.suppressed} covered -> {target}")
        for entry in height_map(blocks, block_height_cm=args.block_height):
            print(f"      stack {entry['stack']:>2}  "
                  f"({entry['center'][0]:6.1f},{entry['center'][1]:6.1f})  "
                  f"level {entry['level']}  "
                  f"{'measured' if entry['measured'] else 'inferred'}")

        if args.masks:
            masks = split_surfaces(frame, max_processing_width=args.width,
                                   flatten=True)
            mask_target = args.out / f"{path.stem}_surfaces.png"
            cv2.imwrite(str(mask_target), surfaces_image(frame, masks))
            print(f"      surfaces -> {mask_target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Reproducible, camera-free benchmark for correction and block analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time
import tracemalloc

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import (  # noqa: E402
    SETTINGS_PATH,
    crop_resize,
    draw_block_overlay,
    enhance_for_display,
    frame_orientation,
    framing_roi,
    load_settings,
    profile_from_settings,
)
from camera.gridded_camera_feed import (  # noqa: E402
    approximate_workspace,
    draw_machine_grid,
    projection_metadata,
)
from rig.config import load as load_rig_config  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from vision.block_detector import DetectionMetrics, detect_blocks  # noqa: E402
from vision.fisheye import build_maps, undistort  # noqa: E402


CAPTURES = Path(__file__).resolve().parents[1] / "captures"


def _measure(function, iterations):
    samples = []
    value = None
    for _ in range(2):
        value = function()
    for _ in range(iterations):
        started = time.perf_counter()
        value = function()
        samples.append((time.perf_counter() - started) * 1000.0)
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return value, {
        "median_ms": statistics.median(samples),
        "p95_ms": p95,
        "mean_ms": statistics.mean(samples),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path,
                        default=next(iter(sorted(CAPTURES.glob("*corrected*.png"))), None))
    parser.add_argument("--raw", type=Path,
                        help="raw capture for remap/grid stages; inferred from --image timestamp")
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--opencv-threads", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.image is None or not args.image.exists():
        parser.error("no corrected capture is available; pass --image")
    if args.iterations <= 0 or args.opencv_threads <= 0:
        parser.error("iterations and OpenCV threads must be positive")
    cv2.setNumThreads(args.opencv_threads)
    frame = cv2.imread(str(args.image))
    if frame is None:
        parser.error(f"cannot read {args.image}")

    metrics = DetectionMetrics()
    detections, detection_time = _measure(
        lambda: detect_blocks(frame, metrics=metrics), args.iterations)
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    detect_blocks(frame)
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    after = tracemalloc.take_snapshot()
    allocation_count = sum(
        stat.count_diff for stat in after.compare_to(before, "lineno")
        if stat.count_diff > 0)
    tracemalloc.stop()
    _, enhancement_time = _measure(
        lambda: enhance_for_display(frame), args.iterations)

    stage_times = {}
    raw_path = args.raw
    if raw_path is None:
        stamp = args.image.name.split("_", 1)[0]
        candidate = CAPTURES / f"{stamp}_raw.png"
        raw_path = candidate if candidate.exists() else None
    if raw_path is not None:
        raw = cv2.imread(str(raw_path))
        if raw is None:
            parser.error(f"cannot read raw capture {raw_path}")
        data = load_settings(args.settings)
        capture = data.get("capture") or {}
        oriented = frame_orientation(raw, capture)
        correction = data.get("correction") or {}
        interpolation = correction.get("interp", "cubic")
        roi = framing_roi(data)
        profile = profile_from_settings(data)
        maps = build_maps(
            profile, oriented.shape[1::-1], interpolation,
            mip=bool(correction.get("mip", True)), roi=roi)
        enabled = bool(correction.get("enabled", True))

        def remap_stage():
            return (undistort(oriented, maps) if enabled else
                    crop_resize(oriented, roi, maps.out_size, interpolation))

        canonical, stage_times["remap"] = _measure(remap_stage, args.iterations)
        canonical_detections = detect_blocks(canonical)

        def overlay_stage():
            output = canonical.copy()
            draw_block_overlay(output, canonical_detections, mode="geometry")
            return output

        _, stage_times["overlay"] = _measure(overlay_stage, args.iterations)
        grid = MachineGrid.from_config(load_rig_config(reload=True))
        projection = projection_metadata(profile, capture, enabled, roi)
        workspace = approximate_workspace(grid, canonical.shape[1::-1], projection)

        def grid_stage():
            output = canonical.copy()
            draw_machine_grid(output, workspace, None, calibrated=False)
            return output

        _, stage_times["grid"] = _measure(grid_stage, args.iterations)
    report = {
        "image": str(args.image),
        "size": list(frame.shape[1::-1]),
        "opencv_threads": cv2.getNumThreads(),
        "detections": len(detections),
        "detection": detection_time,
        "enhancement": enhancement_time,
        "stages": stage_times,
        "detector_work": {
            "processing_size": list(metrics.processing_size),
            "contours": metrics.contours,
            "compound_components": metrics.compound_components,
            "rectangle_hypotheses": metrics.rectangle_hypotheses,
            "exhausted_components": metrics.exhausted_components,
            "python_allocations": allocation_count,
            "python_peak_bytes": peak_bytes,
        },
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Image: {args.image} ({frame.shape[1]}x{frame.shape[0]})")
        print(f"OpenCV threads: {cv2.getNumThreads()}")
        print(f"Detection: {len(detections)} blocks | median "
              f"{detection_time['median_ms']:.2f} ms | p95 {detection_time['p95_ms']:.2f} ms")
        print(f"Enhancement: median {enhancement_time['median_ms']:.2f} ms | "
              f"p95 {enhancement_time['p95_ms']:.2f} ms")
        for stage, timing in stage_times.items():
            print(f"{stage.title()}: median {timing['median_ms']:.2f} ms | "
                  f"p95 {timing['p95_ms']:.2f} ms")
        print("Detector work: " + json.dumps(report["detector_work"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

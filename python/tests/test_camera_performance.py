#!/usr/bin/env python3
"""Regression coverage for bounded camera processing and canonical geometry."""

from collections import deque
from pathlib import Path
import sys
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import (  # noqa: E402
    draw_block_overlay,
    framing_roi,
    load_settings,
    profile_from_settings,
)
from camera.camera_studio import Studio, apply_overrides, parse_args  # noqa: E402
from camera.tk_camera_window import TkCameraWindow  # noqa: E402
from vision.block_detector import DetectionMetrics, detect_blocks  # noqa: E402
from vision.fisheye import build_maps, sampling_stats  # noqa: E402


PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:58} {detail}")


root = Path(__file__).resolve().parents[1]
settings_path = root / "config" / "camera_settings.json"
data = load_settings(settings_path)
profile = profile_from_settings(data)
correction = data["correction"]
feed_maps = build_maps(
    profile, (data["capture"]["width"], data["capture"]["height"]),
    correction["interp"], mip=correction["mip"], roi=framing_roi(data))

with patch.object(sys, "argv", ["camera_studio.py", "--settings", str(settings_path)]):
    args = parse_args()
studio = Studio(args, profile_from_settings(data))
studio.capture_size = (data["capture"]["width"], data["capture"]["height"])
studio.read_settings(settings_path)
apply_overrides(studio, args)
studio_maps = studio.rebuild(
    (data["capture"]["width"], data["capture"]["height"]))
check("Studio opens at canonical feed output size",
      studio_maps.out_size == feed_maps.out_size,
      f"{studio_maps.out_size} vs {feed_maps.out_size}")
check("Studio/feed fixed-point map1 tables are identical",
      np.array_equal(studio_maps.map1, feed_maps.map1))
check("Studio/feed fixed-point map2 tables are identical",
      np.array_equal(studio_maps.map2, feed_maps.map2))

with patch.object(sys, "argv", [
        "camera_studio.py", "--settings", str(settings_path),
        "--window", "1600x900", "--display-scale", "1.5"]):
    display_args = parse_args()
display_studio = Studio(display_args, profile_from_settings(data))
display_studio.capture_size = studio.capture_size
display_studio.read_settings(settings_path)
apply_overrides(display_studio, display_args)
display_maps = display_studio.rebuild(studio.capture_size)
check("Studio window/scale options cannot change processing size",
      display_maps.out_size == feed_maps.out_size)
check("Studio window/scale options cannot change remap tables",
      np.array_equal(display_maps.map1, feed_maps.map1)
      and np.array_equal(display_maps.map2, feed_maps.map2))

first_stats = sampling_stats(feed_maps)
second_stats = sampling_stats(feed_maps)
check("sampling statistics are cached on the map object",
      first_stats is second_stats)

capture = next(iter(sorted((root / "captures").glob("*corrected*.png"))))
base = cv2.imread(str(capture))
reference = detect_blocks(base)
check("reference capture still contains six blocks", len(reference) == 6)
for scale in (2, 3):
    enlarged = cv2.resize(base, None, fx=scale, fy=scale,
                          interpolation=cv2.INTER_NEAREST)
    metrics = DetectionMetrics()
    found = detect_blocks(enlarged, metrics=metrics)
    centres_ok = len(found) == len(reference) and all(
        np.linalg.norm(np.asarray(a.center) / scale - np.asarray(b.center)) < 3.0
        for a, b in zip(found, reference))
    check(f"{scale}x detector result rescales to reference geometry", centres_ok,
          f"{len(found)} blocks; work {metrics.processing_size}")
    check(f"{scale}x detector normalizes work to <=384 px wide",
          metrics.processing_size[0] <= 384, str(metrics.processing_size))
    check(f"{scale}x compound search respects per-component budget",
          metrics.rectangle_hypotheses
          <= metrics.compound_components * 256,
          f"{metrics.rectangle_hypotheses}/{metrics.compound_components}")

clean = base.copy()
draw_block_overlay(clean, reference, mode="off")
check("overlay off leaves every camera pixel unchanged",
      np.array_equal(clean, base))
empty = base.copy()
draw_block_overlay(empty, (), mode="detail")
check("empty overlay returns without touching frame pixels",
      np.array_equal(empty, base))
geometry = base.copy()
draw_block_overlay(geometry, reference, mode="geometry")
check("geometry overlay draws block outlines", not np.array_equal(geometry, base))
detail = base.copy()
draw_block_overlay(detail, reference, mode="detail")
check("detail overlay adds diagnostics beyond geometry",
      not np.array_equal(detail, geometry))

# A deliberately enormous connected warm component creates far more seeds than
# the search is allowed to score. It must fail closed at the exact budget,
# never enter an unbounded combinatorial search or call the union one block.
pathological = np.zeros((400, 500, 3), np.uint8)
cv2.rectangle(pathological, (30, 30), (470, 370), (40, 90, 220), -1)
pathological_metrics = DetectionMetrics()
pathological_found = detect_blocks(
    pathological, min_area=100, metrics=pathological_metrics)
check("pathological compound search stops at 256 hypotheses",
      pathological_metrics.rectangle_hypotheses == 256
      and pathological_metrics.exhausted_components == 1,
      str(pathological_metrics.rectangle_hypotheses))
check("budget-exhausted compound fails closed as uncertain",
      not pathological_found)

# Exercise coordinate mapping and merged key order without opening a desktop.
events = []
hybrid = TkCameraWindow.__new__(TkCameraWindow)
hybrid._mouse_callback = lambda event, point: events.append((event, point))
hybrid._shown_size = (200, 100)
hybrid._source_size = (400, 200)
hybrid._opencv_mouse(cv2.EVENT_MOUSEMOVE, 50, 25, 0)
check("HighGUI mouse coordinates map back to source pixels",
      events[-1][0] == "move" and np.allclose(events[-1][1], (100, 50)))
hybrid._keys = deque()
hybrid._closed = False
hybrid._key_filter = None
hybrid.push_key("q")
hybrid._keys.append(27)
check("Tk and OpenCV keys share one ordered queue",
      hybrid.poll_key() == ord("q") and hybrid.poll_key() == 27)

hybrid._key_filter = lambda key: key != ord("b")
hybrid.push_key("b")
hybrid.push_key("g")
check("event-time key filter prevents queued forbidden mutations",
      hybrid.poll_key() == ord("g") and hybrid.poll_key() == -1)

denied = TkCameraWindow.__new__(TkCameraWindow)
denied._close_request = lambda: False
denied.close = lambda: setattr(denied, "closed_by_test", True)
denied.closed_by_test = False
check("a denied Rig Build close leaves the UI alive",
      denied._request_close() is False and not denied.closed_by_test)

denied._closed = False
denied.root = type("FakeRoot", (), {"update": lambda self: None})()
denied._keys = deque()
denied.preview_title = "test-preview"
denied._preview_created = True
denied._preview_was_presented = True
with patch.object(cv2, "waitKey", return_value=-1), \
        patch.object(cv2, "getWindowProperty", return_value=0.0):
    denied.pump()
check("denied preview closure schedules its recreation",
      not denied._closed and not denied._preview_created)
denied._display_scale = 1.0
denied._source_size = (20, 10)
denied._shown_size = (20, 10)
with patch.object(TkCameraWindow, "_create_preview",
                  lambda self: setattr(self, "_preview_created", True)), \
        patch.object(cv2, "imshow"):
    denied.present(np.zeros((10, 20, 3), np.uint8))
check("next frame recreates a build-locked preview", denied._preview_created)

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

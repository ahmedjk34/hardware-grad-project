"""Off-rig coverage for the simulated workspace camera."""

from __future__ import annotations

from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import STALE_FRAME_AFTER_S  # noqa: E402
from vision.block_detector import detect_blocks  # noqa: E402
from vision.camera_source import LatestFramePump, open_camera  # noqa: E402
from vision.mock_camera import MockCamera  # noqa: E402


def wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    return None


def test_open_camera_mock_has_the_standard_source_surface():
    camera = open_camera("mock", size=(640, 480))
    try:
        ok, frame = camera.read()
        assert ok is True
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8
        assert camera.size == (640, 480)
        assert camera.name.startswith("mock")
        assert camera.apply({"gain": 1.0}) == ([], [])
    finally:
        camera.release()


def test_frame_pump_advances_then_becomes_stale_when_mock_is_frozen():
    camera = MockCamera(size=(640, 480), fps_cap=60)
    pump = LatestFramePump(camera)
    pump.start()
    try:
        first = wait_for(lambda: pump.snapshot().sequence >= 1)
        assert first is not None
        sequence = pump.snapshot().sequence
        assert wait_for(lambda: pump.snapshot().sequence > sequence) is not None

        camera.freeze()
        # `freeze()` cannot un-read a frame the reader thread is already
        # holding: it can be between `read()` returning and the pump storing
        # the result, so ONE more sequence may land after the freeze. Sampling
        # `frozen_sequence` before that lands is what made this test fail — it
        # asserted "never advances again" when the claim is "STOPS advancing".
        # Let the in-flight frame settle, then take the reading.
        time.sleep(0.1)
        frozen_sequence = pump.snapshot().sequence
        time.sleep(STALE_FRAME_AFTER_S + 0.1)
        snapshot = pump.snapshot()
        assert snapshot.sequence == frozen_sequence
        assert snapshot.age_s() is not None
        assert snapshot.age_s() >= STALE_FRAME_AFTER_S
    finally:
        assert pump.stop()
        camera.release()


def test_warm_mock_blocks_are_detected_at_their_real_grid_cells():
    # INTERIOR cells only, and that is a property of the mock rather than of
    # the detector. The mock maps the whole grid into the frame, so the
    # outermost row's centre sits half a block from the frame edge — (3,5)
    # lands at y = 14.4 px on a 720 px frame and a 36 px block is clipped by
    # ~4 px, which drops it below the contour checks. A real camera sees well
    # past the grid, so nothing on the rig behaves this way. Using an edge cell
    # here tested the frame boundary, not the claim in this test's name.
    camera = MockCamera(
        size=(960, 720),
        blocks=((3, 4, "red"), (2, 2, "red")),
        draw_printed_grid=False,
    )
    try:
        ok, frame = camera.read()
        assert ok
        detections = detect_blocks(frame, color_threshold=8, min_area=500)
        assert len(detections) >= 2
        expected = [
            np.mean(camera.workspace.target_polygon(col, row, camera.size), axis=0)
            for col, row, _colour in camera.blocks
        ]
        for centre in expected:
            assert min(np.linalg.norm(np.asarray(d.center) - centre)
                       for d in detections) < 20
    finally:
        camera.release()

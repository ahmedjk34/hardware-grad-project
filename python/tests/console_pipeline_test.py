"""Headless camera pipeline coverage using the supported mock camera."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import SETTINGS_PATH, STALE_FRAME_AFTER_S  # noqa: E402
from rig.console_pipeline import ConsolePipeline  # noqa: E402
from rig.workspace import WorkspaceMap  # noqa: E402


def settings_for_mock(tmp_path: Path) -> Path:
    data = json.loads(SETTINGS_PATH.read_text())
    data["capture"].update({"width": 640, "height": 480})
    data["correction"]["enabled"] = False
    data["framing"] = {"crops": [], "zoom": 1.0, "pan": [0.5, 0.5]}
    path = tmp_path / "camera_settings.json"
    path.write_text(json.dumps(data))
    return path


def next_frame(pipeline: ConsolePipeline, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = pipeline.process_once()
        if result is not None:
            return result
        time.sleep(0.005)
    raise AssertionError("mock pipeline did not yield a processed frame")


def test_mock_pipeline_processes_latest_frames_and_stops_idempotently(tmp_path):
    pipeline = ConsolePipeline(
        camera_backend="mock", settings_path=settings_for_mock(tmp_path),
        workspace_map_path=tmp_path / "missing_workspace_map.json", analysis_hz=30,
    )
    pipeline.start()
    try:
        first = next_frame(pipeline)
        second = next_frame(pipeline)
        assert second.sequence > first.sequence
        assert first.view.flags.writeable is False
        assert first.calibrated is False

        # Freeze and drain an already in-flight source frame; a repeated call
        # then has no new capture to process.
        pipeline.camera.freeze()
        deadline = time.monotonic() + 0.2
        while pipeline.process_once() is not None and time.monotonic() < deadline:
            pass
        assert pipeline.process_once() is None
    finally:
        pipeline.stop()
        pipeline.stop()


def test_mock_pipeline_reports_stale_frames_and_async_detections(tmp_path):
    pipeline = ConsolePipeline(
        camera_backend="mock", settings_path=settings_for_mock(tmp_path),
        workspace_map_path=tmp_path / "missing_workspace_map.json", analysis_hz=30,
    )
    pipeline.start()
    try:
        frame = next_frame(pipeline)
        deadline = time.monotonic() + 2.0
        while not frame.detections and time.monotonic() < deadline:
            frame = next_frame(pipeline)
        assert frame.detections

        pipeline.camera.freeze()
        time.sleep(STALE_FRAME_AFTER_S + 0.1)
        stale = next_frame(pipeline)
        assert stale.stale is True
    finally:
        pipeline.stop()


def test_set_workspace_marks_the_current_mode_calibrated(tmp_path):
    pipeline = ConsolePipeline(
        camera_backend="mock", settings_path=settings_for_mock(tmp_path),
        workspace_map_path=tmp_path / "missing_workspace_map.json",
    )
    pipeline.start()
    try:
        frame = next_frame(pipeline)
        corners = [(0, frame.image_size[1] - 1), (frame.image_size[0] - 1,
                   frame.image_size[1] - 1), (frame.image_size[0] - 1, 0), (0, 0)]
        workspace = WorkspaceMap.from_grid(
            pipeline.grid, corners, frame.image_size, pipeline.projection)
        pipeline.set_workspace(workspace)
        calibrated = next_frame(pipeline)
        assert calibrated.calibrated is True
        assert calibrated.workspace is workspace
    finally:
        pipeline.stop()

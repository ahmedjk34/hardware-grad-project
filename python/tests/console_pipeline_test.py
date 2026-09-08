"""Headless camera pipeline coverage using the supported mock camera."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import sys
import threading
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import SETTINGS_PATH, STALE_FRAME_AFTER_S  # noqa: E402
from rig.console_pipeline import (  # noqa: E402
    ConsolePipeline,
    FrameAnalysisContext,
)
from rig.workspace import WorkspaceMap  # noqa: E402
from vision.analysis_worker import AnalysisSnapshot  # noqa: E402


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


def completed(context, *, source=None, sequence=None, generation=None,
              detections=("detection",), count=1):
    """Build one completed worker result for provenance boundary tests."""
    now = time.monotonic()
    return AnalysisSnapshot(
        detections=detections,
        source=context.view if source is None else source,
        context=context,
        source_sequence=context.sequence if sequence is None else sequence,
        map_generation=(context.map_generation if generation is None
                        else generation),
        submitted_at=now - 0.02,
        completed_at=now,
        duration_s=0.02,
        rate_hz=10.0,
        error=None,
        completed_count=count,
        replaced_count=0,
        duplicate_count=0,
    )


def context(*, sequence=12, generation=4, captured_at=None, workspace=None):
    image = np.full((3, 4, 3), sequence, dtype=np.uint8)
    image.flags.writeable = False
    return FrameAnalysisContext(
        view=image,
        sequence=sequence,
        captured_at=(time.monotonic() if captured_at is None else captured_at),
        image_size=(4, 3),
        workspace=object() if workspace is None else workspace,
        calibrated=True,
        paper_status="bound",
        grid_mode="vertical",
        map_generation=generation,
    )


def test_completed_analysis_binds_detections_image_sequence_and_map():
    pipeline = ConsolePipeline()
    pipeline._map_generation = 4
    workspace = object()
    bound = context(workspace=workspace)

    frame = pipeline._coherent_frame(completed(bound, detections=("from-12",)))

    assert frame is not None
    assert frame.view is bound.view
    assert frame.sequence == bound.sequence
    assert frame.detections == ("from-12",)
    assert frame.workspace is workspace
    assert frame.map_generation == bound.map_generation


def test_a_detector_exception_publishes_NO_VISION_not_zero_detections():
    """The worker catches the exception, empties the tuple and sets `error`.
    `_coherent_frame` must carry that through as `analysis_ok=False` and force
    `detections` empty — a consumer must be able to tell "vision failed" from
    "a clean frame that saw nothing"."""
    pipeline = ConsolePipeline()
    pipeline._map_generation = 4
    bound = context(workspace=object())

    result = dataclasses.replace(
        completed(bound, detections=("stale-leftover",)),
        error="analysis failed: boom", detections=())
    frame = pipeline._coherent_frame(result)

    assert frame is not None
    assert frame.analysis_ok is False
    assert frame.analysis_error == "analysis failed: boom"
    assert frame.detections == ()


def test_a_successful_empty_frame_stays_analysis_ok():
    pipeline = ConsolePipeline()
    pipeline._map_generation = 4
    bound = context(workspace=object())

    frame = pipeline._coherent_frame(completed(bound, detections=()))

    assert frame is not None
    assert frame.analysis_ok is True
    assert frame.analysis_error is None
    assert frame.detections == ()


def test_mismatched_source_sequence_is_never_published():
    pipeline = ConsolePipeline()
    pipeline._map_generation = 4
    bound = context(sequence=12, generation=4)

    assert pipeline._coherent_frame(completed(bound, sequence=11)) is None


def test_result_from_an_old_map_generation_is_never_published():
    pipeline = ConsolePipeline()
    pipeline._map_generation = 5
    bound = context(sequence=12, generation=4)

    assert pipeline._coherent_frame(completed(bound)) is None


def test_analysis_staleness_uses_the_bound_source_capture_time():
    pipeline = ConsolePipeline()
    pipeline._map_generation = 4
    bound = context(
        generation=4,
        captured_at=time.monotonic() - STALE_FRAME_AFTER_S - 0.05,
    )

    frame = pipeline._coherent_frame(completed(bound))

    assert frame is not None and frame.stale is True


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


def test_delayed_analysis_keeps_detections_on_their_exact_source_view(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def delayed_analyzer(source, **_kwargs):
        entered.set()
        release.wait(2.0)
        return (id(source),)

    pipeline = ConsolePipeline(
        camera_backend="mock", settings_path=settings_for_mock(tmp_path),
        workspace_map_path=tmp_path / "missing_workspace_map.json",
        analysis_hz=1000,
    )
    pipeline.start()
    pipeline.analysis._analyzer = delayed_analyzer
    try:
        deadline = time.monotonic() + 2.0
        while not entered.is_set() and time.monotonic() < deadline:
            pipeline.process_once()
            time.sleep(0.005)
        assert entered.is_set()

        # Let capture advance and replace queued requests while the first
        # detector call is held.  This is the production mismatch scenario.
        active_sequence = pipeline._last_sequence
        while (pipeline._last_sequence < active_sequence + 3
               and time.monotonic() < deadline):
            pipeline.process_once()
            time.sleep(0.005)

        release.set()
        analyzed = next_frame(pipeline)
        assert analyzed.detections == (id(analyzed.view),)
        assert analyzed.sequence <= pipeline._last_sequence
    finally:
        release.set()
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
        previous_generation = pipeline.map_generation
        pipeline.set_workspace(workspace)
        assert pipeline.map_generation == previous_generation + 1
        calibrated = next_frame(pipeline)
        assert calibrated.calibrated is True
        assert calibrated.workspace is workspace
        assert calibrated.map_generation == pipeline.map_generation
    finally:
        pipeline.stop()

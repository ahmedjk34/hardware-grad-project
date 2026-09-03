"""Headless capture, remap, and analysis pipeline for the web console.

This is the non-Tk portion of ``camera.rig_build_v1``.  It owns exactly one
camera source, frame pump, block-analysis worker, and printed-grid tracker;
the web service owns the serial ``Rig`` separately.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from camera.camera_feed import (
    SETTINGS_PATH,
    STALE_FRAME_AFTER_S,
    capture_settings,
    colour_from_settings,
    crop_resize,
    frame_orientation,
    framing_roi,
    load_settings,
    profile_from_settings,
    sensor_from_settings,
)
from camera.gridded_camera_feed import (
    PAPER_GRID_HZ,
    PaperGridTracker,
    approximate_workspace,
    load_workspace,
    projection_metadata,
)
from rig.config import CONFIG_PATH, load as load_rig_config
from rig.grid import MachineGrid
from rig.workspace import WORKSPACE_MAP_PATH, WorkspaceMap
from vision.analysis_worker import AnalysisWorker
from vision.block_outline import detect_aligned_blocks
from vision.camera_source import LatestFramePump, open_camera
from vision.color_grid import ColorGridSpec
from vision.fisheye import INTERPOLATIONS, build_maps, undistort


@dataclass(frozen=True)
class ProcessedFrame:
    """The most recent corrected feed image and the state derived from it."""

    view: np.ndarray
    sequence: int
    captured_at: float
    image_size: tuple[int, int]
    stale: bool
    detections: tuple
    workspace: WorkspaceMap
    calibrated: bool
    paper_status: str
    grid_mode: str


class ConsolePipeline:
    """Own the single camera processing pipeline used by the operator console."""

    def __init__(self, *, camera_backend: str | None = None,
                 settings_path: Path = SETTINGS_PATH,
                 rig_config_path: Path = CONFIG_PATH,
                 workspace_map_path: Path = WORKSPACE_MAP_PATH,
                 mode: str | None = None, analysis_hz: float = 10.0,
                 paper_hz: float = PAPER_GRID_HZ, color_threshold: int = 8,
                 min_area: int = 500):
        if analysis_hz <= 0 or paper_hz <= 0:
            raise ValueError("analysis_hz and paper_hz must be positive")
        if min_area <= 0:
            raise ValueError("min_area must be positive")
        self.camera_backend = camera_backend
        self.settings_path = Path(settings_path)
        self.rig_config_path = Path(rig_config_path)
        self.workspace_map_path = Path(workspace_map_path)
        self.requested_mode = mode
        self.analysis_hz = float(analysis_hz)
        self.paper_hz = float(paper_hz)
        self.color_threshold = int(color_threshold)
        self.min_area = int(min_area)

        self.camera = None
        self.frame_pump = None
        self.analysis = None
        self.paper = None
        self.grid = None
        self.projection = None
        self.saved_workspace = None
        self.workspace_rejection = None
        self._maps = None
        self._input_size = None
        self._map_generation = 0
        self._last_sequence = 0
        self._last_stale = None
        self._last_frame: ProcessedFrame | None = None
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    @property
    def latest(self) -> ProcessedFrame | None:
        return self._last_frame

    def start(self) -> None:
        """Open the source and start the latest-only worker threads once."""
        if self._started:
            return
        settings = load_settings(self.settings_path)
        rig_data = load_rig_config(self.rig_config_path, reload=True)
        self.grid = MachineGrid.from_config(rig_data, mode=self.requested_mode)
        backend, device, size = capture_settings(settings)
        profile = profile_from_settings(settings)
        sensor = sensor_from_settings(settings)
        capture = settings.get("capture") or {}
        correction = settings.get("correction") or {}
        enabled = bool(correction.get("enabled", True))
        interpolation = correction.get("interp", "cubic")
        if interpolation not in INTERPOLATIONS:
            raise ValueError(
                f"camera settings: correction.interp must be one of "
                f"{tuple(INTERPOLATIONS)}, not {interpolation!r}")

        self._capture = capture
        self._colour = colour_from_settings(settings)
        self._profile = profile
        self._enabled = enabled
        self._interpolation = interpolation
        self._mip = bool(correction.get("mip", True))
        self._roi = framing_roi(settings)
        self.projection = projection_metadata(profile, capture, enabled, self._roi)
        self.paper = PaperGridTracker(
            ColorGridSpec.from_config(rig_data, mode=self.grid.mode),
            max_hz=self.paper_hz,
        )
        # Grid-aware on purpose: with a MachineGrid the overlay can drop
        # detections that are not on the lattice the other blocks describe -
        # the holder's offcuts beside [0,0] - and draw every rectangle on the
        # lattice's own bearing. Read through a lambda so a mode switch is
        # picked up without rebuilding the worker.
        self.analysis = AnalysisWorker(
            lambda frame: detect_aligned_blocks(frame, grid=self.grid),
            max_hz=self.analysis_hz)
        self.camera = open_camera(self.camera_backend or backend, size, device)
        self.camera.apply(sensor)
        self.frame_pump = LatestFramePump(self.camera)

        try:
            self.saved_workspace, self.workspace_rejection = load_workspace(
                self.workspace_map_path, self.grid, self.projection)
            self.analysis.start()
            self.paper.start()
            self.frame_pump.start()
        except Exception:
            self.stop()
            raise
        self._started = True

    def stop(self) -> None:
        """Stop consumers before capture; release only after a clean pump stop."""
        if not any((self._started, self.analysis, self.paper, self.frame_pump, self.camera)):
            return
        if self.analysis is not None:
            self.analysis.stop()
        if self.paper is not None:
            self.paper.stop()
        pump_stopped = True
        if self.frame_pump is not None:
            pump_stopped = self.frame_pump.stop()
        if pump_stopped and self.camera is not None:
            self.camera.release()
        self._started = False
        if pump_stopped:
            # A second normal stop is genuinely a no-op.  Retain a wedged pump
            # reference only for the exceptional path where retrying stop is
            # still useful and releasing the camera would be unsafe.
            self.analysis = None
            self.paper = None
            self.frame_pump = None
            self.camera = None

    def reload_workspace(self):
        """Re-read ``workspace_map.json`` from disk for the active grid.

        The map is otherwise read once at :meth:`start` and again only when the
        grid mode changes, so a calibration written by ANOTHER process - Camera
        Studio's BLOCK CAL SAVE, or ``camera/block_grid_calibrate.py`` - stayed
        invisible to an already-running console until it was restarted. That is
        the normal way to calibrate on the rig, so it needs a door.

        Returns ``(workspace, rejection)``; the rejection is a sentence saying
        why a map on disk was refused, which is far more useful to an operator
        than the map silently not appearing.
        """
        if not self._started:
            raise RuntimeError("start the pipeline before reloading its workspace")
        self.saved_workspace, self.workspace_rejection = load_workspace(
            self.workspace_map_path, self.grid, self.projection)
        self._map_generation += 1
        self._last_frame = None
        self._last_stale = None
        return self.saved_workspace, self.workspace_rejection

    def set_workspace(self, workspace: WorkspaceMap) -> None:
        """Adopt a just-saved calibration for the active grid only."""
        if self.grid is None:
            raise RuntimeError("start the pipeline before setting its workspace")
        if not workspace.matches_grid(self.grid):
            raise ValueError("workspace map does not match the active grid")
        if workspace.projection != self.projection:
            raise ValueError("workspace map was made for another camera projection")
        self.saved_workspace = workspace
        self.workspace_rejection = None

    def set_grid_mode(self, mode: str, grid: MachineGrid | None = None) -> None:
        """Switch all per-mode camera state after the controller latches the rig."""
        if not self._started:
            raise RuntimeError("start the pipeline before changing grid mode")
        if grid is None:
            rig_data = load_rig_config(self.rig_config_path, reload=True)
            grid = MachineGrid.from_config(rig_data, mode=mode)
        if grid.mode != mode:
            raise ValueError("grid does not belong to the requested mode")
        self.grid = grid
        rig_data = load_rig_config(self.rig_config_path, reload=True)
        self.paper.set_spec(ColorGridSpec.from_config(rig_data, mode=mode))
        self.saved_workspace, self.workspace_rejection = load_workspace(
            self.workspace_map_path, self.grid, self.projection)
        self._map_generation += 1
        self._last_frame = None
        self._last_stale = None

    def process_once(self) -> ProcessedFrame | None:
        """Process one new capture, or report the one-time fresh→stale change."""
        if not self._started or self.frame_pump is None:
            raise RuntimeError("start the pipeline before processing frames")
        snapshot = self.frame_pump.snapshot()
        stale = bool(snapshot.age_s() is not None
                     and snapshot.age_s() >= STALE_FRAME_AFTER_S)
        if snapshot.frame is None or snapshot.sequence == self._last_sequence:
            if self._last_frame is not None and stale != self._last_stale:
                self._last_stale = stale
                self._last_frame = replace(self._last_frame, stale=stale)
                return self._last_frame
            return None

        self._last_sequence = snapshot.sequence
        frame = self._colour.apply(frame_orientation(snapshot.frame, self._capture))
        if self._maps is None or frame.shape[1::-1] != self._input_size:
            self._maps = build_maps(self._profile, frame.shape[1::-1],
                                    self._interpolation, mip=self._mip,
                                    roi=self._roi)
            self._input_size = frame.shape[1::-1]
            self._map_generation += 1
        view = (undistort(frame, self._maps) if self._enabled else
                crop_resize(frame, self._roi, self._maps.out_size,
                            self._interpolation))
        image_size = view.shape[1::-1]
        workspace = self.saved_workspace or approximate_workspace(
            self.grid, image_size, self.projection)
        view.flags.writeable = False
        self.analysis.submit(view, snapshot.sequence, self._map_generation,
                             color_threshold=self.color_threshold,
                             min_area=self.min_area)
        self.paper.submit(view, snapshot.sequence, self._map_generation)
        self.paper.poll(self._map_generation)
        analysis_snapshot = self.analysis.snapshot()
        detections = (analysis_snapshot.detections
                      if analysis_snapshot.is_current(self._map_generation) else ())
        stale = bool(snapshot.age_s() is not None
                     and snapshot.age_s() >= STALE_FRAME_AFTER_S)
        self._last_stale = stale
        self._last_frame = ProcessedFrame(
            view=view,
            sequence=snapshot.sequence,
            captured_at=snapshot.captured_at,
            image_size=image_size,
            stale=stale,
            detections=detections,
            workspace=workspace,
            calibrated=self.saved_workspace is not None,
            paper_status=self.paper.status(),
            grid_mode=self.grid.mode,
        )
        return self._last_frame

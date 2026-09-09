"""Headless capture, remap, and analysis pipeline for the web console.

This is the non-Tk portion of ``camera.rig_build_v1``.  It owns exactly one
camera source, frame pump, block-analysis worker, and printed-grid tracker;
the web service owns the serial ``Rig`` separately.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import threading
import time

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
from vision.vertical_cell_exclusion import exclude_vertical_cell_remnants


@dataclass(frozen=True)
class ProcessedFrame:
    """One coherent, completed analysis and the exact image it analyzed."""

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
    map_generation: int
    analysis_result_id: int
    analysis_completed_at: float
    #: Whether the analyzer returned a real observation for this frame. False
    #: when the detector raised (the worker caught it, emptied the detections,
    #: and left the reason in ``analysis_error``). A consumer MUST treat an
    #: ``analysis_ok=False`` frame as "vision could not see the board", never as
    #: an empty board: ``detections`` is forced to ``()`` here precisely so a
    #: caller that ignores this flag still cannot read a spurious REMOVED out of
    #: it, but the flag is the real signal and ``stale`` is its sibling.
    analysis_ok: bool = True
    analysis_error: str | None = None


@dataclass(frozen=True)
class FrameAnalysisContext:
    """Immutable non-detector inputs bound to one submitted source image."""

    view: np.ndarray
    sequence: int
    captured_at: float
    image_size: tuple[int, int]
    workspace: WorkspaceMap
    calibrated: bool
    paper_status: str
    grid_mode: str
    map_generation: int


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
        # Web calibration/mode routes run on worker threads while process_once
        # runs on the dedicated pipeline executor.  A map transition and a
        # frame submission must be indivisible or old workspace geometry can
        # be labelled with the new generation.
        self._state_lock = threading.RLock()

    @property
    def started(self) -> bool:
        return self._started

    @property
    def latest(self) -> ProcessedFrame | None:
        return self._last_frame

    @property
    def map_generation(self) -> int:
        return self._map_generation

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
        #
        # **kwargs is load-bearing: AnalysisWorker forwards whatever submit()
        # was given (color_threshold, min_area) to the analyzer, and it turns
        # any exception into "analysis failed" with zero detections. A wrapper
        # that did not accept them would therefore show an EMPTY overlay
        # forever, with the reason only in the worker's error field.
        # `include_rejected`: off-lattice detections stay in the list, tagged
        # `on_lattice=False`. Supervision needs them - a block knocked off its
        # site is the whole point of a DISPLACED verdict - and with the holder
        # gone from the rig there is nothing off the lattice that is not a real
        # block. The overlay draws them at their measured position, unnormalised.
        self.analysis = AnalysisWorker(
            lambda frame, vertical_workspace=None, image_size=None, **kwargs:
                exclude_vertical_cell_remnants(
                    detect_aligned_blocks(
                        frame, grid=self.grid, include_rejected=True, **kwargs),
                    vertical_workspace, image_size),
            max_hz=self.analysis_hz, consume_each=True)
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
        with self._state_lock:
            return self._reload_workspace()

    def _reload_workspace(self):
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
        with self._state_lock:
            self._set_workspace(workspace)

    def _set_workspace(self, workspace: WorkspaceMap) -> None:
        if self.grid is None:
            raise RuntimeError("start the pipeline before setting its workspace")
        if not workspace.matches_grid(self.grid):
            raise ValueError("workspace map does not match the active grid")
        if workspace.projection != self.projection:
            raise ValueError("workspace map was made for another camera projection")
        self.saved_workspace = workspace
        self.workspace_rejection = None
        # A workspace is part of the pixel-to-cell evidence map.  Results
        # submitted under the previous workspace must not be interpreted with
        # this one, even when the camera rectification itself did not change.
        self._map_generation += 1
        self._last_frame = None
        self._last_stale = None

    def set_grid_mode(self, mode: str, grid: MachineGrid | None = None) -> None:
        """Switch all per-mode camera state after the controller latches the rig."""
        with self._state_lock:
            self._set_grid_mode(mode, grid)

    def _set_grid_mode(self, mode: str,
                       grid: MachineGrid | None = None) -> None:
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
        """Submit a capture and return each coherent analysis result once.

        Capture remains latest-only and non-blocking.  A returned frame is not
        necessarily the newest capture: it is the exact immutable image whose
        detections just completed, paired with the workspace/map generation
        that existed when that image was submitted.
        """
        with self._state_lock:
            return self._process_once()

    def _process_once(self) -> ProcessedFrame | None:
        if not self._started or self.frame_pump is None:
            raise RuntimeError("start the pipeline before processing frames")
        snapshot = self.frame_pump.snapshot()
        if snapshot.frame is not None and snapshot.sequence != self._last_sequence:
            self._last_sequence = snapshot.sequence
            frame = self._colour.apply(
                frame_orientation(snapshot.frame, self._capture))
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
            # A calibrated horizontal map describes the same fixed camera /
            # holder envelope as the vertical grid.  Reuse its four corners to
            # classify a detected footprint against vertical cells before that
            # detection reaches the overlay or supervision.  No saved map (or
            # an unexpected map error) is fail-open: retain every detection.
            vertical_workspace = None
            if self.grid.mode == "horizontal" and self.saved_workspace is not None:
                try:
                    vertical_grid = MachineGrid.from_config(
                        load_rig_config(self.rig_config_path, reload=True),
                        mode="vertical")
                    vertical_workspace = WorkspaceMap.from_grid_normalized(
                        vertical_grid, workspace.corners, workspace.projection)
                except (TypeError, ValueError):
                    vertical_workspace = None
            view.flags.writeable = False
            context = FrameAnalysisContext(
                view=view,
                sequence=snapshot.sequence,
                captured_at=snapshot.captured_at,
                image_size=image_size,
                workspace=workspace,
                calibrated=self.saved_workspace is not None,
                paper_status=self.paper.status(),
                grid_mode=self.grid.mode,
                map_generation=self._map_generation,
            )
            self.analysis.submit(
                view, snapshot.sequence, self._map_generation, context=context,
                color_threshold=self.color_threshold, min_area=self.min_area,
                vertical_workspace=vertical_workspace, image_size=image_size)
            self.paper.submit(view, snapshot.sequence, self._map_generation)

        self.paper.poll(self._map_generation)
        completed = self.analysis.consume()
        if completed is not None:
            coherent = self._coherent_frame(completed)
            if coherent is not None:
                self._last_frame = coherent
                self._last_stale = coherent.stale
                return coherent

        # Staleness belongs to the analyzed source image, not to a newer raw
        # capture that may currently be queued or in flight.
        if self._last_frame is not None:
            stale = ((time.monotonic() - self._last_frame.captured_at)
                     >= STALE_FRAME_AFTER_S)
            if stale != self._last_stale:
                self._last_stale = stale
                self._last_frame = replace(self._last_frame, stale=stale)
                return self._last_frame
        return None

    def _coherent_frame(self, completed) -> ProcessedFrame | None:
        """Validate and materialize one worker result without mutable joins."""
        context = completed.context
        if not isinstance(context, FrameAnalysisContext):
            return None
        if (completed.source is not context.view
                or completed.source_sequence != context.sequence
                or completed.map_generation != context.map_generation
                or completed.map_generation != self._map_generation):
            return None
        stale = ((time.monotonic() - context.captured_at)
                 >= STALE_FRAME_AFTER_S)
        # A detector exception reaches here as `completed.error` set and
        # `completed.detections` already emptied by the worker. Publish the
        # frame anyway - supervision needs to SEE the failure and fall to
        # NO_VISION - but never let the empty tuple read as "board is clear".
        analysis_ok = completed.error is None
        detections = completed.detections if analysis_ok else ()
        return ProcessedFrame(
            view=context.view,
            sequence=context.sequence,
            captured_at=context.captured_at,
            image_size=context.image_size,
            stale=stale,
            detections=detections,
            workspace=context.workspace,
            calibrated=context.calibrated,
            paper_status=context.paper_status,
            grid_mode=context.grid_mode,
            map_generation=context.map_generation,
            analysis_result_id=completed.completed_count,
            analysis_completed_at=completed.completed_at,
            analysis_ok=analysis_ok,
            analysis_error=completed.error,
        )

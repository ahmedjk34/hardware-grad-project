"""A deterministic, no-hardware camera source for the operator console.

The mock draws its blocks through the same :class:`WorkspaceMap` that maps a
real camera click to a rig cell.  It is therefore useful for overlay and
selection work, not merely for checking that an image-shaped array exists.
"""

from __future__ import annotations

import threading
import time

import cv2
import numpy as np

from rig.config import load as load_rig_config
from rig.grid import MachineGrid
from rig.workspace import WorkspaceMap
from vision.camera_source import DEFAULT_SIZE


_BLOCK_COLOURS = {
    # BGR — warm colours are deliberately detectable by block_detector.
    "red": (35, 35, 235),
    "orange": (25, 105, 240),
    "yellow": (20, 190, 245),
    # Cool choices remain useful for visual/manual overlay work, even though
    # the real detector intentionally focuses on the warm material.
    "green": (50, 220, 50),
    "blue": (230, 70, 35),
}


class MockCamera:
    """Render a synthetic top-down workspace with the normal source API."""

    def __init__(self, size=DEFAULT_SIZE, *,
                 blocks=((3, 5, "red"), (2, 2, "red")),
                 draw_printed_grid: bool = True, perspective: float = 0.0,
                 fps_cap: float = 30, mode: str | None = None):
        width, height = (int(value) for value in size)
        if width < 2 or height < 2:
            raise ValueError("size must be at least 2x2")
        if not 0.0 <= float(perspective) < 0.4:
            raise ValueError("perspective must be in 0.0..0.4")
        if fps_cap <= 0:
            raise ValueError("fps_cap must be positive")

        self.size = width, height
        self.name = f"mock workspace @ {width}x{height}"
        self.draw_printed_grid = bool(draw_printed_grid)
        self.perspective = float(perspective)
        self.fps_cap = float(fps_cap)
        self._lock = threading.Lock()
        self._released = False
        self._frozen = False
        self._frame_counter = 0
        self._last_read_at = 0.0
        self.blocks = ()

        self.grid = MachineGrid.from_config(load_rig_config(), mode=mode)
        self.workspace = WorkspaceMap.from_grid(
            self.grid, self._workspace_corners(), self.size,
            projection={"mock": 1, "perspective": self.perspective},
        )
        self.set_blocks(blocks)

    def _workspace_corners(self):
        width, height = self.size
        # Preserve the physical 24.3x40 cm envelope's aspect ratio.  The
        # detector uses the known long/short block shape, so stretching the
        # workspace to fill an arbitrary video aspect would make its planted
        # blocks physically implausible and rightly get them rejected.
        max_width, max_height = width * 0.96, height * 0.96
        aspect = self.grid.workspace_width_cm / self.grid.workspace_height_cm
        workspace_height = min(max_height, max_width / aspect)
        workspace_width = workspace_height * aspect
        left = (width - workspace_width) / 2
        top = (height - workspace_height) / 2
        skew = self.perspective * workspace_width * 0.15
        # CORNER_NAMES order: home/home, far-X/home-Y, far-X/far-Y, home-X/far-Y.
        return (
            (left, top + workspace_height),
            (left + workspace_width, top + workspace_height),
            (left + workspace_width - skew, top),
            (left + skew, top),
        )

    def set_blocks(self, blocks) -> None:
        """Replace the visible ``(col, row, colour)`` block set."""
        normalized = []
        for item in blocks:
            if len(item) != 3:
                raise ValueError("every block must be (col, row, colour)")
            col, row, colour = int(item[0]), int(item[1]), str(item[2]).lower()
            if not self.workspace.mapped_grid.contains(col, row):
                raise ValueError(f"mock block [{col},{row}] is outside the grid")
            if colour not in _BLOCK_COLOURS:
                raise ValueError(f"unknown mock block colour {colour!r}")
            normalized.append((col, row, colour))
        with self._lock:
            self.blocks = tuple(normalized)

    def freeze(self) -> None:
        """Stop delivering frames, simulating a stalled capture backend."""
        with self._lock:
            self._frozen = True

    def resume(self) -> None:
        with self._lock:
            self._frozen = False

    def read(self):
        with self._lock:
            if self._released:
                return False, None
            if self._frozen:
                # Avoid a hot loop while letting LatestFramePump's captured_at
                # age naturally into its truthful stale state.
                time.sleep(min(0.02, 1.0 / self.fps_cap))
                return False, None
            elapsed = time.monotonic() - self._last_read_at
            remaining = (1.0 / self.fps_cap) - elapsed
            if remaining > 0:
                time.sleep(min(remaining, 0.03))
            self._last_read_at = time.monotonic()
            self._frame_counter += 1
            counter = self._frame_counter
            blocks = self.blocks
        return True, self._render(counter, blocks)

    def apply(self, settings):
        """The simulated sensor has no adjustable hardware controls."""
        return [], []

    def release(self) -> None:
        with self._lock:
            self._released = True

    def _render(self, counter: int, blocks):
        width, height = self.size
        frame = np.full((height, width, 3), 82, dtype=np.uint8)
        envelope = np.asarray(self._workspace_corners(), dtype=np.int32)
        cv2.fillConvexPoly(frame, envelope, (145, 145, 145), cv2.LINE_AA)
        cv2.polylines(frame, [envelope], True, (190, 190, 190), 2, cv2.LINE_AA)
        if self.draw_printed_grid:
            self._draw_printed_grid(frame)
        for col, row, colour in blocks:
            polygon = np.asarray(
                self.workspace.target_polygon(col, row, self.size), dtype=np.float32
            ).round().astype(np.int32)
            cv2.fillConvexPoly(frame, polygon, _BLOCK_COLOURS[colour], cv2.LINE_AA)
            cv2.polylines(frame, [polygon], True, (25, 25, 25), 2, cv2.LINE_AA)
        cv2.putText(frame, f"MOCK {counter:05d}", (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (225, 225, 225), 2,
                    cv2.LINE_AA)
        return frame

    def _draw_printed_grid(self, frame):
        """Draw a lightweight visual stand-in for the physical sheet lattice.

        It intentionally does not claim to be a calibratable replacement for
        the high-fidelity combined printed sheet.  Step 10 will add that
        detector-targeted artwork; this supplies useful visual structure now.
        """
        grid = self.workspace.mapped_grid
        for row in range(grid.rows):
            for col in range(grid.cols):
                polygon = np.asarray(
                    self.workspace.target_polygon(col, row, self.size), dtype=np.float32
                ).round().astype(np.int32)
                cv2.polylines(frame, [polygon], True, (190, 125, 35), 1, cv2.LINE_AA)

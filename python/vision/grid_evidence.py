"""Evidence-assisted calibration for an occluded printed colour grid.

The printed sheet remains a measurement target: only complete, detected cells
are ever observations.  This module merely allows observations from several
static-camera frames to be pooled when a gantry hides different *interior*
cells in each frame.  It is deliberately camera/window free so the same safety
decision can be tested without hardware.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

import cv2
import numpy as np

from vision.color_grid import ColorGridCalibration, ColorGridError, ColorGridMetrics, PrintedCell


MIN_FRAMES = 2
MIN_CELLS = 36                       # 60% of the 10x6 printed map
MIN_EDGE_CELLS = 3
MIN_FRAME_OVERLAP = 4
MAX_MEAN_RESIDUAL_PX = 2.0
MAX_RESIDUAL_PX = 6.0
MAX_FRAME_RESIDUAL_PX = 3.0
MAX_CELL_SPREAD_PX = 3.0


@dataclass(frozen=True)
class EvidenceStatus:
    frames: int
    verified_cells: int
    virtual_cells: int
    corner_anchors: int
    edge_cells: tuple[int, int, int, int]  # left, right, bottom, top
    mean_residual_px: float
    max_residual_px: float
    max_cell_spread_px: float
    ready: bool
    reasons: tuple[str, ...]

    def describe(self) -> str:
        edges = "/".join(str(value) for value in self.edge_cells)
        state = "READY TO SAVE" if self.ready else "; ".join(self.reasons)
        return (f"evidence {self.frames} frame{'s' if self.frames != 1 else ''}, "
                f"{self.verified_cells} physical / {self.virtual_cells} virtual, "
                f"corners {self.corner_anchors}/4, edges L/R/B/T {edges}, "
                f"fit {self.mean_residual_px:.2f}px (max {self.max_residual_px:.2f}), "
                f"spread {self.max_cell_spread_px:.2f}px — {state}")


class PaperGridEvidence:
    """Pool sparse, individually valid sheet observations across accepted frames.

    A successful :meth:`add` does *not* mean a map is safe to save.  It only
    records whole cells from one manually accepted frame.  :attr:`status`
    applies the deliberately stricter cross-frame and boundary-coverage rules.
    """

    def __init__(self, spec):
        self.spec = spec
        self._observations = defaultdict(list)
        self._frames = []
        self._calibration = None
        self._status = self._empty_status()

    def _empty_status(self):
        return EvidenceStatus(0, 0, self.spec.cols * self.spec.rows, 0,
                              (0, 0, 0, 0), 0.0, 0.0, 0.0, False,
                              (f"capture {MIN_FRAMES} accepted frames",))

    @property
    def frames(self):
        return len(self._frames)

    @property
    def calibration(self):
        """Merged calibration, or ``None`` before one usable frame is accepted."""
        return self._calibration

    @property
    def observed_cells(self):
        return frozenset(self._observations)

    @property
    def status(self):
        return self._status

    def clear(self):
        self._observations.clear()
        self._frames.clear()
        self._calibration = None
        self._status = self._empty_status()

    def add(self, calibration: ColorGridCalibration):
        """Accept one sparse evidence calibration and return its new status.

        The caller must use ``detect_color_grid(..., evidence=True)``.  We
        refuse noisy/parity-inconsistent frames here, before they can pollute
        the pooled geometry.
        """
        if calibration.spec != self.spec:
            raise ValueError("evidence frame uses a different printed-grid geometry")
        metrics = calibration.metrics
        if metrics.full_cells < 12:
            raise ColorGridError("evidence frame has fewer than 12 whole cells")
        if metrics.parity_agreement < 0.95:
            raise ColorGridError(
                f"evidence frame parity is only {metrics.parity_agreement:.0%}; "
                "clear scene-coloured clutter before accepting it")
        if metrics.residual_px > MAX_FRAME_RESIDUAL_PX:
            raise ColorGridError(
                f"evidence frame fit residual {metrics.residual_px:.2f} px exceeds "
                f"the {MAX_FRAME_RESIDUAL_PX:g} px frame limit")

        cells = calibration.found_cells
        if not cells:
            raise ColorGridError("evidence frame contains no whole cells in the selected grid")
        # Sparse windows can select a different 10x6 candidate while the
        # gantry moves.  The first accepted view establishes the image-space
        # [0,0] convention; subsequent observations are snapped to that fixed
        # virtual grid by their *measured pixel centres*, not trusted merely
        # because their temporary lattice index happened to match.
        reference = self._calibration
        aligned = {}
        for key, cell in cells.items():
            if reference is not None:
                u, v = reference.grid_at(cell.center)
                mapped = (round(u), round(v))
                if not (0 <= mapped[0] < self.spec.cols and
                        0 <= mapped[1] < self.spec.rows):
                    continue
                if np.hypot(u - mapped[0], v - mapped[1]) > 0.30:
                    continue
                key = mapped
            aligned[key] = cell
        if not aligned:
            raise ColorGridError(
                "evidence frame does not overlap the established sheet window; "
                "keep the camera and paper fixed and expose an adjacent part of it")
        if reference is not None:
            overlap = sum(key in self._observations for key in aligned)
            if overlap < MIN_FRAME_OVERLAP:
                raise ColorGridError(
                    f"evidence frame overlaps only {overlap} previously verified cells; "
                    f"need {MIN_FRAME_OVERLAP} to verify the camera and sheet stayed fixed")
        for key, cell in aligned.items():
            self._observations[key].append(cell)
        self._frames.append(calibration)
        self._calibration = self._merge()
        self._status = self._assess()
        return self._status

    def _merge(self):
        keys = sorted(self._observations)
        source = np.float32(keys)
        destinations = np.float32([
            np.mean([cell.center for cell in self._observations[key]], axis=0)
            for key in keys
        ])
        if len(source) < 4:
            raise ColorGridError("evidence needs four non-collinear cells")
        matrix, _ = cv2.findHomography(source, destinations, cv2.RANSAC, 3.0)
        if matrix is None:
            raise ColorGridError("accepted evidence cells are degenerate")
        projected = cv2.perspectiveTransform(source.reshape(-1, 1, 2), matrix).reshape(-1, 2)
        residual = np.linalg.norm(projected - destinations, axis=1)
        first = self._frames[-1].metrics
        metrics = ColorGridMetrics(
            input_size=first.input_size,
            processing_size=first.processing_size,
            components=sum(frame.metrics.components for frame in self._frames),
            assigned=sum(frame.metrics.assigned for frame in self._frames),
            full_cells=len(keys),
            lattice_shape=(self.spec.cols, self.spec.rows),
            residual_px=float(residual.mean()),
            max_residual_px=float(residual.max()),
            parity_agreement=min(frame.metrics.parity_agreement for frame in self._frames),
            measured_aspect=float(np.mean([frame.metrics.measured_aspect for frame in self._frames])),
        )
        merged = ColorGridCalibration(self.spec, matrix, [], metrics=metrics)
        cells = []
        for key in keys:
            observations = self._observations[key]
            centre = tuple(np.mean([cell.center for cell in observations], axis=0))
            colours = Counter(cell.color for cell in observations)
            cells.append(PrintedCell(
                lattice=key, center=centre, quad=merged.cell_quad(*key),
                color=colours.most_common(1)[0][0],
                area=float(np.mean([cell.area for cell in observations])),
                fill=float(np.mean([cell.fill for cell in observations])),
                full=True, cell=key,
            ))
        return ColorGridCalibration(self.spec, matrix, cells, metrics=metrics)

    def _assess(self):
        observed = self.observed_cells
        cols, rows = self.spec.cols, self.spec.rows
        edges = (
            sum(col == 0 for col, _row in observed),
            sum(col == cols - 1 for col, _row in observed),
            sum(row == 0 for _col, row in observed),
            sum(row == rows - 1 for _col, row in observed),
        )
        corners = ((0, 0), (cols - 1, 0), (cols - 1, rows - 1), (0, rows - 1))
        anchors = sum(any(abs(col - cx) <= 1 and abs(row - cy) <= 1
                          for col, row in observed) for cx, cy in corners)
        spreads = []
        for cells in self._observations.values():
            if len(cells) > 1:
                centres = np.asarray([cell.center for cell in cells], dtype=float)
                spreads.append(float(np.max(np.linalg.norm(centres - centres.mean(axis=0), axis=1))))
        spread = max(spreads, default=0.0)
        metrics = self._calibration.metrics
        reasons = []
        if self.frames < MIN_FRAMES:
            reasons.append(f"capture {MIN_FRAMES - self.frames} more accepted frame")
        if len(observed) < MIN_CELLS:
            reasons.append(f"need {MIN_CELLS - len(observed)} more verified cells")
        if anchors < 4:
            reasons.append(f"need {4 - anchors} more corner-region anchor")
        if any(count < MIN_EDGE_CELLS for count in edges):
            missing = ", ".join(name for name, count in zip(("left", "right", "bottom", "top"), edges)
                                if count < MIN_EDGE_CELLS)
            reasons.append(f"observe {missing} outer edge")
        if metrics.residual_px > MAX_MEAN_RESIDUAL_PX or metrics.max_residual_px > MAX_RESIDUAL_PX:
            reasons.append("merged fit residual is too high")
        if spread > MAX_CELL_SPREAD_PX:
            reasons.append("camera or sheet moved between accepted frames")
        return EvidenceStatus(
            self.frames, len(observed), cols * rows - len(observed), anchors, edges,
            metrics.residual_px, metrics.max_residual_px, spread, not reasons, tuple(reasons),
        )

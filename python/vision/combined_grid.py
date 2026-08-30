#!/usr/bin/env python3
"""Detect the one-sheet target carrying both machine-grid orientations.

The artwork is an A2 landscape page.  Its coloured bars form an 8 x 10
fiducial lattice even though the green/magenta/beige accents inside each bar
make the two block orientations visible to a person.  Detection deliberately
uses only the chromatic green/magenta evidence: beige is too close to white
paper to remain dependable after printing, shadows and camera white balance.

The fiducial lattice describes page centimetres, not either block layout.  One
homography therefore measures the shared 24.3 x 40.0 cm holder plane; the
active :class:`rig.grid.MachineGrid` still decides which cells are drawn and
which coordinates the firmware accepts.  The two modes remain separately
saved in ``workspace_map.json``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import cv2
import numpy as np

from vision.color_grid import (
    ColorGridCalibration,
    ColorGridError,
    ColorGridSpec,
    DEFAULT_HOME_CONVENTION,
    DEFAULT_PROCESS_WIDTH,
    HOME_CONVENTIONS,
    MAGENTA_HUE,
    color_masks,
    detect_color_grids,
    white_balance,
)
from vision.grid_evidence import PaperGridEvidence


# Physical artwork coordinates from the PNG's 37.79 px/cm A2 export.
PAGE_WIDTH_CM = 59.4
PAGE_HEIGHT_CM = 42.0
FIDUCIAL_COLS = 8
FIDUCIAL_ROWS = 10
FIDUCIAL_BLOCK_X_CM = 6.0
FIDUCIAL_BLOCK_Y_CM = 2.2
FIDUCIAL_GAP_X_CM = 0.8
FIDUCIAL_GAP_Y_CM = 1.6
FIDUCIAL_LEFT_CM = 0.8
FIDUCIAL_BOTTOM_CM = 4.8

# The new olive inks are hue 44/48 in the supplied digital artwork.  The old
# sheet's balanced green lives at 80..101.  This wider window is scoped to this
# detector so scene clutter cannot weaken the established legacy path.
COMBINED_GREEN_HUE = (32, 115)
RELAXED_GREEN_HUE = (24, 125)
RELAXED_MAGENTA_HUE = (124, 179)
COMBINED_MIN_AREA = 80
FULL_BAR_CLOSE_PX = 5
RELAXED_BAR_CLOSE_PX = 7
STRIPE_ASPECT_RANGE = (1.0, 2.2)


def combined_fiducial_spec() -> ColorGridSpec:
    """Geometry of the coloured measurement lattice, independent of rig mode."""
    return ColorGridSpec(
        cols=FIDUCIAL_COLS,
        rows=FIDUCIAL_ROWS,
        block_x_cm=FIDUCIAL_BLOCK_X_CM,
        block_y_cm=FIDUCIAL_BLOCK_Y_CM,
        gap_x_cm=FIDUCIAL_GAP_X_CM,
        gap_y_cm=FIDUCIAL_GAP_Y_CM,
        # The bars' long side is paper X, matching ColorGridSpec's horizontal
        # axis rule.  This is artwork orientation, not a firmware mode latch.
        mode="horizontal",
    )


def combined_stripe_spec() -> ColorGridSpec:
    """Geometry of the saturated centre stripe inside each full fiducial."""
    return ColorGridSpec(
        cols=FIDUCIAL_COLS,
        rows=FIDUCIAL_ROWS,
        block_x_cm=1.6,
        block_y_cm=FIDUCIAL_BLOCK_Y_CM,
        gap_x_cm=5.2,
        gap_y_cm=FIDUCIAL_GAP_Y_CM,
        mode="vertical",
    )


@dataclass
class CombinedGridCalibration:
    """A detected combined target with page-centimetre projection helpers."""

    lattice: ColorGridCalibration
    method: str = "full bars"
    is_combined = True

    @property
    def target_description(self):
        return (
            "combined A2 target, 8x10 chromatic fiducials, "
            "one holder-plane fit for both grid modes"
        )

    @property
    def spec(self):
        return self.lattice.spec

    @property
    def homography(self):
        return self.lattice.homography

    @property
    def cells(self):
        return self.lattice.cells

    @property
    def metrics(self):
        # The legacy lattice kernel reports (short-axis, long-axis) spread.
        # This target's public coordinates are paper (X, Y), hence 8 x 10.
        return replace(
            self.lattice.metrics,
            lattice_shape=(FIDUCIAL_COLS, FIDUCIAL_ROWS),
        )

    @property
    def found_cells(self):
        return self.lattice.found_cells

    def point_at(self, col, row):
        return self.lattice.point_at(col, row)

    def cell_center(self, col, row):
        return self.lattice.cell_center(col, row)

    def cell_quad(self, col, row):
        return self.lattice.cell_quad(col, row)

    def cell_at(self, point):
        return self.lattice.cell_at(point)

    def outline(self):
        return self.lattice.outline()

    def page_point(self, x_cm: float, y_cm: float):
        """Project an A2 page coordinate (origin at physical bottom-left)."""
        spec = self.spec
        first_x = FIDUCIAL_LEFT_CM + FIDUCIAL_BLOCK_X_CM / 2
        first_y = FIDUCIAL_BOTTOM_CM + FIDUCIAL_BLOCK_Y_CM / 2
        col = (float(x_cm) - first_x) / spec.pitch_x_cm
        row = (float(y_cm) - first_y) / spec.pitch_y_cm
        return self.lattice.point_at(col, row)

    def workspace_corners(self, grid, convention=DEFAULT_HOME_CONVENTION):
        """Return the shared holder envelope inferred from the A2 page plane."""
        if convention not in HOME_CONVENTIONS:
            raise ValueError(
                f"convention must be one of {HOME_CONVENTIONS}, not {convention!r}")
        if convention != "firmware":
            raise ColorGridError(
                "the combined sheet is registered directly to holder home; "
                "use the firmware home convention")
        if not grid.has_physical_scale:
            raise ColorGridError("mapping to the envelope needs a scaled MachineGrid")
        if (grid.workspace_width_cm > PAGE_WIDTH_CM
                or grid.workspace_height_cm > PAGE_HEIGHT_CM):
            raise ColorGridError(
                "the configured holder envelope does not fit on the combined A2 target")
        corners = [
            self.page_point(0.0, 0.0),
            self.page_point(grid.workspace_width_cm, 0.0),
            self.page_point(grid.workspace_width_cm, grid.workspace_height_cm),
            self.page_point(0.0, grid.workspace_height_cm),
        ]
        # A full-page raster necessarily rounds a physical page edge to the
        # nearest pixel. The source PNG consequently projects X=0 roughly half
        # a pixel outside its own array. Accept only that rasterisation sliver;
        # a genuinely cropped workspace remains a hard WorkspaceMap refusal.
        width, height = self.metrics.input_size
        bounded = []
        for x, y in corners:
            if -1.5 <= x <= width + 0.5:
                x = min(max(x, 0.0), float(width))
            if -1.5 <= y <= height + 0.5:
                y = min(max(y, 0.0), float(height))
            bounded.append((x, y))
        return bounded

    def describe(self):
        m = self.metrics
        physical = len(self.found_cells)
        confirmed = m.window_observed or m.full_cells
        count = (f"{physical} physical + {confirmed - physical} pixel-confirmed"
                 if confirmed > physical else f"{physical}")
        return (
            f"combined A2 8x10 fiducial grid from "
            f"{count}/80 cells, residual "
            f"{m.residual_px:.2f} px (max {m.max_residual_px:.2f}), "
            f"parity {m.parity_agreement * 100:.0f}%, {self.method}"
        )


def _strong_stripe_frame(frame: np.ndarray) -> np.ndarray:
    """Keep the saturated centre accents when muted bar ink has disappeared.

    Thresholds are learned from the two inks in this frame, not copied from the
    digital artwork. That lets a faded print retain its dark accents without
    promoting gray paper or beige to ink.
    """
    balanced = white_balance(frame)
    green, magenta = color_masks(
        balanced,
        min_saturation=12,
        green_hue=RELAXED_GREEN_HUE,
        magenta_hue=RELAXED_MAGENTA_HUE,
        balance=False,
    )
    hsv = cv2.cvtColor(balanced, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    if not (green.any() or magenta.any()):
        return balanced

    # Each ink gets its own bimodal threshold. A channel cast can make the
    # darkest green stripe less saturated than the palest magenta bar (or the
    # reverse), so one global percentile either loses that corner or retains
    # whole bars. Otsu separates muted fill from dark accent independently and
    # automatically follows print density and exposure.
    strong = np.zeros(saturation.shape, dtype=bool)
    local_saturation = cv2.GaussianBlur(
        saturation.astype(np.float32), (0, 0), sigmaX=9.0, sigmaY=9.0)
    for ink in (green, magenta):
        values = saturation[ink]
        if values.size == 0:
            continue
        threshold, _ = cv2.threshold(
            values.reshape(-1, 1), 0, 255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )
        # A flat low-saturation distribution means there is no credible dark
        # accent. Keep the floor high enough that JPEG chroma noise cannot turn
        # beige or gray paper into thousands of tiny candidates.
        threshold = max(42, int(round(threshold)))
        global_core = ink & (saturation >= threshold)
        local_core = (ink & (saturation >= 42)
                      & (saturation.astype(np.float32)
                         >= local_saturation + 18.0))
        strong |= global_core | local_core
    isolated = np.full_like(balanced, 255)
    isolated[strong] = balanced[strong]
    return isolated


def _promote_stripes(calibration: ColorGridCalibration) -> ColorGridCalibration:
    """Give a stripe-centre fit the full-bar geometry used by overlays."""
    full_spec = combined_fiducial_spec()
    metrics = replace(
        calibration.metrics,
        measured_aspect=FIDUCIAL_BLOCK_X_CM / FIDUCIAL_BLOCK_Y_CM,
    )
    return ColorGridCalibration(
        spec=full_spec,
        homography=calibration.homography,
        cells=calibration.cells,
        metrics=metrics,
    )


def _error_rank(error: ColorGridError):
    stages = {name: index for index, name in enumerate(
        ("segment", "lattice", "fit", "quality", "window", "selection"))}
    return (stages.get(error.stage, -1), len(error.lattice), len(error.candidates))


def detect_combined_grids(frame: np.ndarray, *,
                          process_width: int = DEFAULT_PROCESS_WIDTH,
                          evidence: bool = False):
    """Return every valid target placement using progressively safer fallbacks."""
    errors = []
    passes = (
        ("full bars", frame, combined_fiducial_spec(), {
            "min_area": COMBINED_MIN_AREA,
            "green_hue": COMBINED_GREEN_HUE,
            "magenta_hue": MAGENTA_HUE,
            "component_close": FULL_BAR_CLOSE_PX,
        }),
        ("relaxed faded bars", frame, combined_fiducial_spec(), {
            "min_area": COMBINED_MIN_AREA,
            "min_saturation": 18,
            "green_hue": RELAXED_GREEN_HUE,
            "magenta_hue": RELAXED_MAGENTA_HUE,
            "component_close": RELAXED_BAR_CLOSE_PX,
        }),
        ("dark centre stripes", _strong_stripe_frame(frame), combined_stripe_spec(), {
            "min_area": max(40, COMBINED_MIN_AREA // 2),
            "min_saturation": 12,
            "green_hue": RELAXED_GREEN_HUE,
            "magenta_hue": RELAXED_MAGENTA_HUE,
            "use_opponent": False,
            "component_close": FULL_BAR_CLOSE_PX,
            "lattice_aspect_range": STRIPE_ASPECT_RANGE,
            # The relative-saturation stencil intentionally keeps only the
            # stripe cores. Blur and dot gain can therefore shrink or expand
            # their contour without moving their centres; geometry and colour
            # parity remain the safety gates for this pass.
            "full_fill_range": (0.25, 1.90),
            "recovery_fill_range": (0.22, 2.00),
            "balance": False,
        }),
    )
    for method, candidate, spec, options in passes:
        try:
            found = detect_color_grids(
                candidate,
                spec,
                process_width=process_width,
                evidence=evidence,
                **options,
            )
            if method == "dark centre stripes":
                found = tuple(_promote_stripes(item) for item in found)
            return tuple(CombinedGridCalibration(item, method) for item in found)
        except ColorGridError as exc:
            errors.append(exc)
    raise max(errors, key=_error_rank)


def detect_printed_grids(frame: np.ndarray, legacy_spec: ColorGridSpec, *,
                         process_width: int = DEFAULT_PROCESS_WIDTH,
                         evidence: bool = False):
    """Detect the combined target first, retaining both legacy sheet formats."""
    combined_error = None
    try:
        return detect_combined_grids(
            frame, process_width=process_width, evidence=evidence)
    except ColorGridError as exc:
        combined_error = exc
    try:
        return detect_color_grids(
            frame, legacy_spec, process_width=process_width, evidence=evidence)
    except ColorGridError as legacy_error:
        # Prefer the failure that got farther through the pipeline; it produces
        # the most useful candidate overlay and operator instruction.
        if _error_rank(combined_error) > _error_rank(legacy_error):
            raise combined_error
        raise legacy_error


def detect_printed_grid(frame: np.ndarray, legacy_spec: ColorGridSpec, *,
                        process_width: int = DEFAULT_PROCESS_WIDTH,
                        evidence: bool = False,
                        window_index: int = 0):
    calibrations = detect_printed_grids(
        frame, legacy_spec, process_width=process_width, evidence=evidence)
    if not 0 <= window_index < len(calibrations):
        raise ColorGridError(
            f"grid window {window_index + 1} was requested but only "
            f"{len(calibrations)} candidate(s) were detected",
            stage="selection",
        )
    return calibrations[window_index]


class PrintedGridEvidence:
    """Evidence collector that locks onto combined or legacy at first capture."""

    def __init__(self, legacy_spec: ColorGridSpec):
        self.legacy_spec = legacy_spec
        self._kind = None
        self._method = None
        self._evidence = PaperGridEvidence(legacy_spec)

    @property
    def calibration(self):
        calibration = self._evidence.calibration
        if calibration is None:
            return None
        return (CombinedGridCalibration(calibration, self._method or "full bars")
                if self._kind == "combined" else calibration)

    @property
    def observed_cells(self):
        return self._evidence.observed_cells

    @property
    def status(self):
        return self._evidence.status

    def clear(self):
        self._kind = None
        self._method = None
        self._evidence = PaperGridEvidence(self.legacy_spec)

    def add(self, calibration):
        combined = isinstance(calibration, CombinedGridCalibration)
        kind = "combined" if combined else "legacy"
        if self._kind is None:
            self._kind = kind
            if combined:
                self._method = calibration.method
                self._evidence = PaperGridEvidence(calibration.spec)
        elif self._kind != kind:
            raise ColorGridError(
                "evidence changed printed-target designs; clear it and keep one "
                "sheet fixed for the whole session")
        measured = calibration.lattice if combined else calibration
        return self._evidence.add(measured)

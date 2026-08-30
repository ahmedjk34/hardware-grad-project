#!/usr/bin/env python3
"""Detect and decode the woven one-sheet orientation target.

Pixel inspection of the supplied 2245 x 1587 PNG shows an exact 37.79 px/cm
raster.  Every 6.0 x 2.2 cm chromatic bar is split along its long axis into
2.2 + 1.6 + 2.2 cm runs (about 83 + 60 + 83 pixels): muted ink, dark ink,
muted ink.  Those are the vertical-pattern fiducials.  Each paired row is
separated by 1.6 cm of gray/beige in its two 2.2 cm outer lanes and white in
its 1.6 cm centre lane.  Read perpendicular to the chromatic bars, each outer
lane is therefore muted colour + beige + the opposite muted colour: a separate
horizontal-pattern fiducial.  The four other row intervals are plain paper.

This is a woven design, not one fiducial voting twice.  The 8 x 10 chromatic
lattice supplies geometry; 80 bar patterns and 80 perpendicular bridge
patterns carry mutually exclusive orientation classifications. The requested
mode selects exactly one family for aggregation, reporting and overlay; the
inactive family is never returned. Beige is a real part of the horizontal
signature, but beige alone can never establish a sheet or a horizontal vote:
both coloured end thirds must also agree.

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
    ColorRegionStats,
    color_masks,
    detect_color_grids,
    lab_distance,
    sample_color_region,
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

# Exact internal geometry measured from the supplied 2245 x 1587 raster and
# matched by plans/assets/combined-calibration-grid.svg. At 37.79 px/cm the
# solid runs are approximately 83, 60, 83 px across each 227 px bar.
OUTER_THIRD_CM = 2.2
CENTER_THIRD_CM = 1.6
INTERNAL_GAP_CM = 1.6
SUBREGION_INSET_CM = 0.16
MIN_ORIENTATION_VOTE_FRACTION = 0.60
ORIENTATION_SCORE_MIN = 0.64
ORIENTATION_MARGIN_MIN = 0.12
BEIGE_ROW_CONTRAST_MIN = 0.10
MIN_VISIBLE_PATTERN_FRACTION = 0.20
MIN_PAGE_PLANE_OBSERVATIONS = 76  # 95% of the 8x10 geometry lattice


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
        block_x_cm=CENTER_THIRD_CM,
        block_y_cm=FIDUCIAL_BLOCK_Y_CM,
        gap_x_cm=FIDUCIAL_BLOCK_X_CM + FIDUCIAL_GAP_X_CM - CENTER_THIRD_CM,
        gap_y_cm=FIDUCIAL_GAP_Y_CM,
        mode="vertical",
    )


@dataclass(frozen=True)
class FiducialPattern:
    """One complete physical fiducial and its single decoded class."""

    fiducial_id: str
    cell: tuple[int, int]
    thirds: tuple[str, str, str]
    quad: np.ndarray
    vertical_score: float
    horizontal_score: float
    orientation: str
    confidence: float
    inferred: bool = False
    kind: str = "bar"

    @property
    def signature(self) -> str:
        codes = {"green": "G", "purple": "P", "gray": "B",
                 "unknown": "?"}
        parts = "-".join(codes.get(label, "?") for label in self.thirds)
        prefix = {"vertical": "V", "horizontal": "H"}.get(
            self.orientation, "?")
        if self.inferred and prefix != "?":
            prefix += "~"
        return f"{prefix}: {parts}"


@dataclass
class CombinedGridCalibration:
    """A detected combined target with page-centimetre projection helpers."""

    lattice: ColorGridCalibration
    method: str = "full bars"
    patterns: tuple[FiducialPattern, ...] = ()
    inferred_orientation: str = "unknown"
    orientation_confidence: float = 0.0
    requested_mode: str | None = None
    is_combined = True

    @property
    def target_description(self):
        return (
            "combined A2 target, 8x10 chromatic fiducials, "
            f"internal orientation encoding {self.orientation}"
        )

    @property
    def orientation(self):
        return self.inferred_orientation

    @property
    def orientations(self):
        """Orientation classes present, retained for older UI consumers."""
        return ((self.orientation,) if self.orientation in
                ("vertical", "horizontal") else ())

    @property
    def orientation_votes(self):
        return {
            "vertical": sum(pattern.orientation == "vertical"
                            for pattern in self.patterns),
            "horizontal": sum(pattern.orientation == "horizontal"
                              for pattern in self.patterns),
            "ambiguous": sum(pattern.orientation == "unknown"
                             for pattern in self.patterns),
        }

    @property
    def inferred_horizontal_cells(self):
        return sum(pattern.orientation == "horizontal" and pattern.inferred
                   for pattern in self.patterns)

    @property
    def ambiguous_cells(self):
        return self.orientation_votes["ambiguous"]

    @property
    def unobserved_patterns(self):
        # One mode exposes one 80-fiducial family at a time.
        return max(0, 80 - len(self.patterns))

    @property
    def pattern_map(self):
        return {pattern.cell: pattern for pattern in self.patterns
                if pattern.kind == "bar"}

    def pattern_label(self, col: int, row: int) -> str:
        pattern = self.pattern_map.get((col, row))
        return (f"{pattern.signature}" if pattern
                else f"F{col},{row} ?")

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
        if self.lattice.metrics.window_observed < MIN_PAGE_PLANE_OBSERVATIONS:
            raise ColorGridError(
                "orientation was decoded from a cropped partial sheet, but the "
                "holder envelope cannot be calibrated until at least "
                f"{MIN_PAGE_PLANE_OBSERVATIONS}/80 lattice sites support the "
                "page plane; move the camera back or use evidence-assisted "
                "calibration across multiple fixed-camera frames",
                stage="window",
                calibration=self,
            )
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
            f"parity {m.parity_agreement * 100:.0f}%, orientation "
            f"{self.orientation} ({self.orientation_confidence * 100:.1f}%; "
            f"V/H/? {self.orientation_votes['vertical']}/"
            f"{self.orientation_votes['horizontal']}/"
            f"{self.orientation_votes['ambiguous']}), {self.method}"
        )


def _region_quad(calibration, col, row, x0_cm, x1_cm, y0_cm, y1_cm):
    """Project one artwork-local rectangle through the fitted homography."""
    pitch_x = calibration.spec.pitch_x_cm
    pitch_y = calibration.spec.pitch_y_cm
    return np.asarray([
        calibration.point_at(col + x0_cm / pitch_x, row + y0_cm / pitch_y),
        calibration.point_at(col + x1_cm / pitch_x, row + y0_cm / pitch_y),
        calibration.point_at(col + x1_cm / pitch_x, row + y1_cm / pitch_y),
        calibration.point_at(col + x0_cm / pitch_x, row + y1_cm / pitch_y),
    ], dtype=np.float32)


def _strength_threshold(samples: list[ColorRegionStats]) -> float:
    """Adaptive neutral/ink split over all projected subregion medians."""
    values = np.clip(
        np.asarray([sample.strength for sample in samples]) * 255.0,
        0, 255,
    ).astype(np.uint8)
    if not len(values):
        return 0.12
    threshold, _ = cv2.threshold(
        values.reshape(-1, 1), 0, 255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )
    return float(np.clip(threshold / 255.0, 0.055, 0.34))


def _median_lab(samples: list[ColorRegionStats]):
    return np.median(np.asarray([sample.lab for sample in samples]), axis=0)


def _classify_region(sample: ColorRegionStats, threshold: float,
                     green_lab, magenta_lab, gray_lab) -> str:
    """Classify by adaptive chroma, normalized channels and Lab prototypes."""
    lab = np.asarray(sample.lab)
    distances = {
        "green": float(np.linalg.norm(lab - green_lab)),
        "purple": float(np.linalg.norm(lab - magenta_lab)),
        "gray": float(np.linalg.norm(lab - gray_lab)),
    }
    nearest_ink = min(distances["green"], distances["purple"])
    # A live green print can have less HSV saturation than the surrounding
    # blue-cast paper.  Low saturation is therefore supporting evidence for
    # neutral, never a veto on an ink prototype that is much closer in Lab.
    if (distances["gray"] + 3.0 < nearest_ink
            and (sample.strength < threshold * 1.7
                 or distances["gray"] < nearest_ink * 0.72)):
        return "gray"

    # Relative channel relationships survive a multiplicative shadow better
    # than hue. Lab distance resolves weak/tinted samples where both opponent
    # scores are close to zero.
    opponent_margin = sample.green_opponent - sample.magenta_opponent
    if opponent_margin > 0.012 and distances["green"] <= distances["purple"] + 8:
        return "green"
    if opponent_margin < -0.012 and distances["purple"] <= distances["green"] + 8:
        return "purple"
    return min(("green", "purple"), key=distances.get)


def _complete_quad(frame: np.ndarray, quad, border: float = 2.0) -> bool:
    """True only when a projected physical fiducial is wholly measurable."""
    points = np.asarray(quad, dtype=np.float32)
    height, width = frame.shape[:2]
    return bool(
        abs(cv2.contourArea(points)) >= 24.0
        and np.all(points[:, 0] >= border)
        and np.all(points[:, 1] >= border)
        and np.all(points[:, 0] <= width - 1 - border)
        and np.all(points[:, 1] <= height - 1 - border)
    )


def _ink_distance(sample: ColorRegionStats, paper: ColorRegionStats) -> float:
    """Local paper-normalized ink evidence in the range 0..1."""
    lab = lab_distance(sample, paper)
    luma = abs(float(sample.lab[0]) - float(paper.lab[0]))
    chroma = abs(sample.green_opponent - paper.green_opponent)
    chroma += abs(sample.magenta_opponent - paper.magenta_opponent)
    return float(np.clip(
        0.50 * (lab - 1.5) / 22.0
        + 0.25 * (luma - 0.5) / 20.0
        + 0.25 * chroma / 0.16,
        0.0, 1.0,
    ))


def _beige_distance(sample: ColorRegionStats, paper: ColorRegionStats) -> float:
    """Neutral ink versus adjacent white paper, without an absolute RGB."""
    lab = lab_distance(sample, paper)
    dark = float(paper.lab[0]) - float(sample.lab[0])
    neutrality = 1.0 - min(1.0, sample.strength / max(paper.strength + 0.16, 0.20))
    return float(np.clip(
        0.48 * (lab - 0.8) / 12.0
        + 0.34 * (dark - 0.3) / 11.0
        + 0.18 * neutrality,
        0.0, 1.0,
    ))


def _decode_patterns(frame: np.ndarray, lattice: ColorGridCalibration,
                     method: str, requested_mode: str):
    """Decode the two perpendicular fiducial families without shared votes."""
    sample_frame = white_balance(frame)
    inset = SUBREGION_INSET_CM
    half_x = FIDUCIAL_BLOCK_X_CM / 2
    half_y = FIDUCIAL_BLOCK_Y_CM / 2
    centre_left = -half_x + OUTER_THIRD_CM
    centre_right = half_x - OUTER_THIRD_CM
    x_ranges = (
        (-half_x + inset, centre_left - inset),
        (centre_left + inset, centre_right - inset),
        (centre_right + inset, half_x - inset),
    )
    bar_y = (-half_y + inset, half_y - inset)
    gap_y = (half_y + inset, half_y + INTERNAL_GAP_CM - inset)

    # Horizontal bars: the three long-axis regions are one vertical-pattern
    # fiducial.  Projected bars outside the frame (including the user's clipped
    # bottom row) are intentionally absent, not virtually counted.
    bar_samples = {}
    bar_paper = {}
    bar_quads = {}
    for row in range(FIDUCIAL_ROWS):
        for col in range(FIDUCIAL_COLS):
            cell = (col, row)
            quad = _region_quad(
                lattice, col, row, -half_x, half_x, -half_y, half_y)
            if not _complete_quad(sample_frame, quad):
                continue
            thirds = tuple(sample_color_region(
                sample_frame, _region_quad(lattice, col, row, x0, x1, *bar_y))
                for x0, x1 in x_ranges)
            paper_x = ((half_x + inset,
                        half_x + FIDUCIAL_GAP_X_CM - inset)
                       if col < FIDUCIAL_COLS - 1 else
                       (-half_x - FIDUCIAL_GAP_X_CM + inset,
                        -half_x - inset))
            paper_quad = _region_quad(
                lattice, col, row, *paper_x, *bar_y)
            if not _complete_quad(sample_frame, paper_quad, border=0.5):
                continue
            bar_samples[cell] = thirds
            bar_paper[cell] = sample_color_region(sample_frame, paper_quad)
            bar_quads[cell] = quad

    # Perpendicular outer lanes: colour + beige + opposite colour.  Sample all
    # nine row intervals first; beige contrast identifies which alternating
    # parity contains the five real bridges and which four are plain separators.
    bridge_raw = {}
    bridge_paper = {}
    bridge_quads = {}
    lane_ranges = (
        ("L", -half_x + inset, centre_left - inset),
        ("R", centre_right + inset, half_x - inset),
    )
    upper_y = (FIDUCIAL_GAP_Y_CM + half_y + inset,
               FIDUCIAL_GAP_Y_CM + 3 * half_y - inset)
    for row in range(FIDUCIAL_ROWS - 1):
        for col in range(FIDUCIAL_COLS):
            for lane, x0, x1 in lane_ranges:
                key = (col, row, lane)
                quad = _region_quad(
                    lattice, col, row, x0, x1, -half_y, upper_y[1])
                if not _complete_quad(sample_frame, quad):
                    continue
                thirds = (
                    sample_color_region(sample_frame, _region_quad(
                        lattice, col, row, x0, x1, *bar_y)),
                    sample_color_region(sample_frame, _region_quad(
                        lattice, col, row, x0, x1, *gap_y)),
                    sample_color_region(sample_frame, _region_quad(
                        lattice, col, row, x0, x1, *upper_y)),
                )
                paper_x = (centre_left + inset, centre_right - inset)
                paper_quad = _region_quad(
                    lattice, col, row, *paper_x, *gap_y)
                if not _complete_quad(sample_frame, paper_quad, border=0.5):
                    continue
                bridge_raw[key] = thirds
                bridge_paper[key] = sample_color_region(sample_frame, paper_quad)
                bridge_quads[key] = quad

    minimum_visible = int(np.ceil(
        MIN_VISIBLE_PATTERN_FRACTION * FIDUCIAL_COLS * FIDUCIAL_ROWS))
    if len(bar_samples) < minimum_visible:
        raise ColorGridError(
            f"the lattice fit extrapolates correctly, but only {len(bar_samples)} "
            f"complete chromatic fiducials are measurable; {minimum_visible} "
            "are required (frame-edge partials do not count)",
            stage="orientation",
            lattice=[cell.quad for cell in lattice.cells if cell.full],
        )

    # Parity supplies two camera-adapted ink clusters.  Naming the cluster with
    # the larger Lab a*/magenta-opponent response purple avoids fixed hue or RGB
    # assumptions and keeps the nearly gray live green cluster usable.
    parity_samples = {0: [], 1: []}
    for (col, row), thirds in bar_samples.items():
        parity_samples[(col + row) % 2].extend(thirds)
    if not all(parity_samples.values()):
        raise ColorGridError(
            "complete fiducials cover only one colour parity; expose more of "
            "the checkerboard before decoding orientation",
            stage="orientation",
            lattice=[cell.quad for cell in lattice.cells if cell.full],
        )
    parity_lab = {key: _median_lab(value)
                  for key, value in parity_samples.items()}
    purple_parity = max(parity_lab, key=lambda key: parity_lab[key][1])
    green_samples = parity_samples[1 - purple_parity]
    purple_samples = parity_samples[purple_parity]
    neutral_samples = list(bar_paper.values()) + list(bridge_paper.values())
    all_samples = green_samples + purple_samples + neutral_samples
    all_samples.extend(sample for thirds in bridge_raw.values()
                       for sample in thirds)
    threshold = _strength_threshold(all_samples)
    prototypes = (_median_lab(green_samples), _median_lab(purple_samples),
                  _median_lab(neutral_samples))

    def classify(thirds):
        return tuple(_classify_region(sample, threshold, *prototypes)
                     for sample in thirds)

    def signature_scores(thirds, labels, paper):
        coloured = ("green", "purple")
        outer_coloured = float(labels[0] in coloured and labels[2] in coloured)
        same_outer = float(outer_coloured and labels[0] == labels[2])
        opposite_outer = float(outer_coloured and labels[0] != labels[2])
        centre_same = float(labels[1] in coloured and labels[1] == labels[0]
                            and labels[1] == labels[2])
        centre_neutral = float(labels[1] == "gray")
        side_strength = (thirds[0].strength + thirds[2].strength) / 2.0
        strength_accent = float(np.clip(
            (thirds[1].strength - side_strength - 0.012) / 0.16, 0, 1))
        lab_accent = float(np.clip(
            ((lab_distance(thirds[1], thirds[0])
              + lab_distance(thirds[1], thirds[2])) / 2.0 - 2.0) / 24.0,
            0, 1))
        # Darkness by itself is not enough: the centre must retain the same
        # chromatic class as both muted outer thirds.
        accent = centre_same * (0.58 * strength_accent + 0.42 * lab_accent)
        ink = float(np.mean([_ink_distance(sample, paper)
                             for sample in thirds]))
        vertical = float(
            0.28 * same_outer + 0.22 * centre_same
            + 0.38 * accent + 0.12 * ink)
        beige = _beige_distance(thirds[1], paper)
        # Beige must modulate the direct horizontal score. Otherwise a plain
        # white separator between two opposite-colour rows is indistinguishable
        # from the encoded bridge and every interval would falsely vote H.
        horizontal_direct = float(
            (0.45 + 0.55 * beige)
            * (0.48 * opposite_outer + 0.26 * centre_neutral
               + 0.26 * min(1.0, (_ink_distance(thirds[0], paper)
                                  + _ink_distance(thirds[2], paper)) / 1.2)))
        return vertical, horizontal_direct, beige, opposite_outer, centre_neutral

    def exclusive(vertical, horizontal):
        best = max(vertical, horizontal)
        margin = abs(vertical - horizontal)
        if best < ORIENTATION_SCORE_MIN or margin < ORIENTATION_MARGIN_MIN:
            return "unknown", float(np.clip(best * margin, 0, 1))
        orientation = "vertical" if vertical > horizontal else "horizontal"
        confidence = float(np.clip(0.55 * best + 0.45 * margin, 0, 1))
        return orientation, confidence

    patterns = []
    valid_bars = set()
    for cell, thirds in sorted(bar_samples.items(), key=lambda item: item[0][::-1]):
        labels = list(classify(thirds))
        ink_evidence = [_ink_distance(sample, bar_paper[cell])
                        for sample in thirds]
        # A sparse/evidence homography may project unobserved lattice sites onto
        # visible blank paper. They are virtual geometry, not ambiguous physical
        # fiducials. At least two thirds must carry locally normalized ink.
        observed = cell in lattice.found_cells
        if (not observed
                and (sum(label in ("green", "purple") for label in labels) < 2
                     or sum(value >= 0.16 for value in ink_evidence) < 2)):
            continue
        expected = ("purple" if (cell[0] + cell[1]) % 2 == purple_parity
                    else "green")
        # When geometry physically observed this bar, a gray label in one
        # blurred third is a missing colour measurement, not proof that the
        # printed checkerboard changed parity. Retain the raw score evidence,
        # but fill its categorical signature from the two agreeing thirds and
        # the sheet-wide alternating parity.
        if observed and sum(label == expected for label in labels) >= 1:
            labels = [expected if label == "gray" else label for label in labels]
        labels = tuple(labels)
        vertical, horizontal, _beige, _opposite, _neutral = signature_scores(
            thirds, labels, bar_paper[cell])
        orientation, confidence = exclusive(vertical, horizontal)
        valid_bars.add(cell)
        patterns.append(FiducialPattern(
            fiducial_id=f"V[{cell[0]},{cell[1]}]",
            cell=cell,
            thirds=labels,
            quad=bar_quads[cell],
            vertical_score=vertical,
            horizontal_score=horizontal,
            orientation=orientation,
            confidence=confidence,
            kind="bar",
        ))

    bridge_features = {}
    for key, thirds in bridge_raw.items():
        labels = classify(thirds)
        bridge_features[key] = (
            labels,
            *signature_scores(thirds, labels, bridge_paper[key]),
        )
    row_beige = {}
    for row in range(FIDUCIAL_ROWS - 1):
        values = [feature[3] for key, feature in bridge_features.items()
                  if key[1] == row]
        if values:
            row_beige[row] = float(np.median(values))
    parity_beige = {
        parity: float(np.median([
            value for row, value in row_beige.items() if row % 2 == parity
        ]))
        for parity in (0, 1)
        if any(row % 2 == parity for row in row_beige)
    }
    encoded_parity = (max(parity_beige, key=parity_beige.get)
                      if parity_beige else 0)
    other_value = parity_beige.get(1 - encoded_parity, 0.0)
    encoded_value = parity_beige.get(encoded_parity, 0.0)
    structural = (encoded_value >= 0.12
                  and encoded_value >= other_value + BEIGE_ROW_CONTRAST_MIN)

    # A weak individual beige middle may be filled only after other lanes have
    # established the alternating beige parity. Coloured, opposite end thirds
    # remain mandatory. This is the requested "fill in the blank" fallback.
    for key, thirds in sorted(bridge_raw.items(),
                              key=lambda item: (item[0][1], item[0][0], item[0][2])):
        col, row, lane = key
        if row % 2 != encoded_parity:
            continue
        # Both complete chromatic bars are physical anchors. This rejects a
        # bridge that merely has one narrow lane inside the image while the
        # full bottom bar is clipped by the camera edge.
        if (col, row) not in valid_bars or (col, row + 1) not in valid_bars:
            continue
        labels, _vertical, _direct, beige, _opposite, _centre_neutral = \
            bridge_features[key]
        labels = list(labels)
        expected_lower = ("purple" if (col + row) % 2 == purple_parity
                          else "green")
        expected_upper = ("purple" if (col + row + 1) % 2 == purple_parity
                          else "green")
        if labels[0] == "gray":
            labels[0] = expected_lower
        if labels[2] == "gray":
            labels[2] = expected_upper
        labels = tuple(labels)
        vertical, direct, beige, opposite, centre_neutral = signature_scores(
            thirds, labels, bridge_paper[key])
        fallback = 0.0
        if structural and opposite:
            fallback = float(
                0.50 * opposite + 0.12 * centre_neutral
                + 0.20 * min(1.0, encoded_value / 0.35)
                + 0.08 * beige + 0.10)
        horizontal = max(direct, fallback)
        inferred = direct < ORIENTATION_SCORE_MIN <= fallback
        orientation, confidence = exclusive(vertical, horizontal)
        pair_index = (row - encoded_parity) // 2
        horizontal_row = pair_index * 2 + (1 if lane == "R" else 0)
        logical_cell = (col, horizontal_row)
        patterns.append(FiducialPattern(
            fiducial_id=f"H[{logical_cell[0]},{logical_cell[1]}]",
            cell=logical_cell,
            thirds=labels,
            quad=bridge_quads[key],
            vertical_score=vertical,
            horizontal_score=horizontal,
            orientation=orientation,
            confidence=confidence,
            inferred=inferred and orientation == "horizontal",
            kind="bridge",
        ))

    bar_patterns = [pattern for pattern in patterns if pattern.kind == "bar"]
    bridge_patterns = [pattern for pattern in patterns if pattern.kind == "bridge"]
    vertical_votes = sum(pattern.orientation == "vertical"
                         for pattern in bar_patterns)
    horizontal_votes = sum(pattern.orientation == "horizontal"
                           for pattern in bridge_patterns)
    vertical_support = vertical_votes / max(1, len(bar_patterns))
    horizontal_support = horizontal_votes / max(1, len(bridge_patterns))
    has_vertical = (len(bar_patterns) >= minimum_visible
                    and vertical_support >= MIN_ORIENTATION_VOTE_FRACTION)
    has_horizontal = (len(bridge_patterns) >= minimum_visible
                      and horizontal_support >= MIN_ORIENTATION_VOTE_FRACTION)
    # Mode is a decoder selector, not a post-decode label. Both pattern
    # families may be sampled internally because they share one homography and
    # colour model, but callers receive only the requested family's cells.
    # Consequently one run can never report or draw both V and H patterns.
    if requested_mode == "vertical":
        selected_patterns = bar_patterns
        requested_present = has_vertical
        support = vertical_support
    else:
        selected_patterns = bridge_patterns
        requested_present = has_horizontal
        support = horizontal_support
    winning = [pattern for pattern in selected_patterns
               if pattern.orientation == requested_mode]
    if requested_present:
        inferred_orientation = requested_mode
    elif has_vertical:
        inferred_orientation = "vertical"
    elif has_horizontal:
        inferred_orientation = "horizontal"
    else:
        inferred_orientation = "unknown"
    mean_confidence = (float(np.mean([pattern.confidence for pattern in winning]))
                       if winning else 0.0)
    orientation_confidence = float(
        np.clip(0.62 * support + 0.38 * mean_confidence, 0, 1))
    calibration = CombinedGridCalibration(
        lattice=lattice,
        method=method,
        patterns=tuple(selected_patterns),
        inferred_orientation=inferred_orientation,
        orientation_confidence=orientation_confidence,
        requested_mode=requested_mode,
    )
    votes = calibration.orientation_votes
    detail = (f"vertical={votes['vertical']}, horizontal={votes['horizontal']}, "
              f"ambiguous={votes['ambiguous']}, confidence="
              f"{orientation_confidence * 100:.1f}%")
    if inferred_orientation == "unknown":
        raise ColorGridError(
            "the 8x10 chromatic lattice is valid, but its mutually exclusive "
            f"internal signatures are ambiguous ({detail})",
            stage="orientation",
            lattice=[cell.quad for cell in lattice.cells if cell.full],
            calibration=calibration,
        )
    if not requested_present:
        raise ColorGridError(
            f"detected {inferred_orientation} block orientation, but requested "
            f"{requested_mode} block orientation ({detail})",
            stage="orientation",
            lattice=[cell.quad for cell in lattice.cells if cell.full],
            calibration=calibration,
        )
    return calibration


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
        ("segment", "lattice", "fit", "quality", "window", "selection",
         "orientation"))}
    return (stages.get(error.stage, -1), len(error.lattice), len(error.candidates))


def detect_combined_grids(frame: np.ndarray, *,
                          process_width: int = DEFAULT_PROCESS_WIDTH,
                          evidence: bool = False,
                          requested_mode: str = "vertical"):
    """Decode only ``requested_mode`` using progressively safer fallbacks."""
    if requested_mode not in ("vertical", "horizontal"):
        raise ValueError("requested_mode must be 'vertical' or 'horizontal'")
    errors = []
    passes = (
        ("full bars", frame, combined_fiducial_spec(), {
            "min_area": COMBINED_MIN_AREA,
            "green_hue": COMBINED_GREEN_HUE,
            "magenta_hue": MAGENTA_HUE,
            "component_close": FULL_BAR_CLOSE_PX,
            "neighbour_hops": (1, 2),
        }),
        ("relaxed faded bars", frame, combined_fiducial_spec(), {
            "min_area": COMBINED_MIN_AREA,
            "min_saturation": 18,
            "green_hue": RELAXED_GREEN_HUE,
            "magenta_hue": RELAXED_MAGENTA_HUE,
            "component_close": RELAXED_BAR_CLOSE_PX,
            "neighbour_hops": (1, 2),
        }),
        ("dark centre stripes", _strong_stripe_frame(frame), combined_stripe_spec(), {
            "min_area": max(40, COMBINED_MIN_AREA // 2),
            "min_saturation": 12,
            "green_hue": RELAXED_GREEN_HUE,
            "magenta_hue": RELAXED_MAGENTA_HUE,
            "use_opponent": False,
            "component_close": FULL_BAR_CLOSE_PX,
            "neighbour_hops": (1, 2),
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
                # Combined targets may be camera-cropped. The lattice stage is
                # allowed to extrapolate an 8x10 homography from a broad partial
                # view; the decoder above still counts only fully visible,
                # locally ink-supported fiducials. Legacy calibration sheets
                # retain their strict full-window behavior.
                evidence=True,
                **options,
            )
            if method == "dark centre stripes":
                found = tuple(_promote_stripes(item) for item in found)
            return tuple(_decode_patterns(frame, item, method, requested_mode)
                         for item in found)
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
            frame, process_width=process_width, evidence=evidence,
            requested_mode=legacy_spec.mode)
    except ColorGridError as exc:
        combined_error = exc
    try:
        return detect_color_grids(
            frame, legacy_spec, process_width=process_width, evidence=evidence)
    except ColorGridError as legacy_error:
        # A plain legacy sheet can form a chromatic lattice of the combined
        # target's shape and then fail only its woven-orientation decode. When
        # the legacy detector also fails, that combined "orientation" error is
        # usually the more informative one; otherwise prefer whichever failure
        # got farther through its own pipeline.
        if combined_error.stage == "orientation" or (
                _error_rank(combined_error) > _error_rank(legacy_error)):
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
        self._patterns = ()
        self._orientation = "unknown"
        self._orientation_confidence = 0.0
        self._requested_mode = None
        self._evidence = PaperGridEvidence(legacy_spec)

    @property
    def calibration(self):
        calibration = self._evidence.calibration
        if calibration is None:
            return None
        return (CombinedGridCalibration(
                    lattice=calibration,
                    method=self._method or "full bars",
                    patterns=self._patterns,
                    inferred_orientation=self._orientation,
                    orientation_confidence=self._orientation_confidence,
                    requested_mode=self._requested_mode)
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
        self._patterns = ()
        self._orientation = "unknown"
        self._orientation_confidence = 0.0
        self._requested_mode = None
        self._evidence = PaperGridEvidence(self.legacy_spec)

    def add(self, calibration):
        combined = isinstance(calibration, CombinedGridCalibration)
        kind = "combined" if combined else "legacy"
        if self._kind is None:
            self._kind = kind
            if combined:
                self._method = calibration.method
                self._patterns = calibration.patterns
                self._orientation = calibration.orientation
                self._orientation_confidence = calibration.orientation_confidence
                self._requested_mode = calibration.requested_mode
                self._evidence = PaperGridEvidence(calibration.spec)
        elif self._kind != kind:
            raise ColorGridError(
                "evidence changed printed-target designs; clear it and keep one "
                "sheet fixed for the whole session")
        measured = calibration.lattice if combined else calibration
        return self._evidence.add(measured)

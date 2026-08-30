#!/usr/bin/env python3
"""Detect and decode the one-sheet target carrying both grid orientations.

The A2 artwork is not merely an alternating 8 x 10 colour lattice. Each
6.0 x 2.2 cm chromatic bar is split across X as 2.2 + 1.6 + 2.2 cm: muted
green/purple outer regions and a darker same-colour centre encode the vertical
block orientation. Five pairs of neighbouring chromatic rows have a 1.6 cm
interval whose outer 2.2 cm regions are beige/gray while its centre 1.6 cm is
white; those beige/white/beige intervals encode the horizontal orientation.
The remaining four row intervals are plain white separators.

Geometry is still established only by chromatic evidence. Orientation is a
second, sheet-level decision combining that geometry and colour parity with
the internal chromatic and gray subregions. Gray is therefore meaningful but
can never establish a sheet by itself.

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
VERTICAL_SCORE_MIN = 0.68
HORIZONTAL_SCORE_MIN = 0.72


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
    """Decoded thirds and orientation votes for one chromatic fiducial."""

    cell: tuple[int, int]
    thirds: tuple[str, str, str]
    gap_thirds: tuple[str, str, str] | None
    vertical_score: float
    horizontal_score: float
    horizontal_inferred: bool = False

    @property
    def signature(self) -> str:
        codes = {"green": "G", "purple": "P", "gray": "B"}
        bar = "".join(codes[label] for label in self.thirds)
        gap = ("".join(codes[label] for label in self.gap_thirds)
               if self.gap_thirds else "---")
        horizontal = ("H~" if self.horizontal_inferred
                      else "H" if self.horizontal_score >= HORIZONTAL_SCORE_MIN
                      else "-")
        votes = (("V" if self.vertical_score >= VERTICAL_SCORE_MIN else "-")
                 + horizontal)
        return f"{bar}/{gap}:{votes}"


@dataclass
class CombinedGridCalibration:
    """A detected combined target with page-centimetre projection helpers."""

    lattice: ColorGridCalibration
    method: str = "full bars"
    patterns: tuple[FiducialPattern, ...] = ()
    orientations: tuple[str, ...] = ()
    is_combined = True

    @property
    def target_description(self):
        orientation = "+".join(self.orientations) or "undecoded"
        return (
            "combined A2 target, 8x10 chromatic fiducials, "
            f"internal orientation encoding {orientation}"
        )

    @property
    def orientation(self):
        return "+".join(self.orientations) or "unknown"

    @property
    def orientation_votes(self):
        return {
            "vertical": sum(pattern.vertical_score >= VERTICAL_SCORE_MIN
                            for pattern in self.patterns),
            "horizontal": sum(pattern.horizontal_score >= HORIZONTAL_SCORE_MIN
                              for pattern in self.patterns),
        }

    @property
    def inferred_horizontal_cells(self):
        return sum(pattern.horizontal_inferred for pattern in self.patterns)

    @property
    def pattern_map(self):
        return {pattern.cell: pattern for pattern in self.patterns}

    def pattern_label(self, col: int, row: int) -> str:
        pattern = self.pattern_map.get((col, row))
        return (f"F{col},{row} {pattern.signature}" if pattern
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
            f"{self.orientation}, {self.method}"
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
    if (sample.strength < threshold
            or (distances["gray"] + 4.0 < min(distances["green"],
                                               distances["purple"])
                and sample.strength < threshold * 1.45)):
        return "gray"

    # Relative channel relationships survive a multiplicative shadow better
    # than hue. Lab distance resolves weak/tinted samples where both opponent
    # scores are close to zero.
    opponent_margin = sample.green_opponent - sample.magenta_opponent
    if opponent_margin > 0.012:
        return "green"
    if opponent_margin < -0.012:
        return "purple"
    return min(("green", "purple"), key=distances.get)


def _decode_patterns(frame: np.ndarray, lattice: ColorGridCalibration,
                     method: str, requested_mode: str | None):
    """Decode all internal thirds and return a mode-validated calibration."""
    # Use the same white-patch normalization that established the chromatic
    # lattice. Region decisions remain relative/local below, but removing the
    # global cast first keeps neutral beige from being mislabeled as purple.
    sample_frame = white_balance(frame)
    inset = SUBREGION_INSET_CM
    half_width = FIDUCIAL_BLOCK_X_CM / 2
    center_left = -half_width + OUTER_THIRD_CM
    center_right = half_width - OUTER_THIRD_CM
    x_ranges = (
        (-half_width + inset, center_left - inset),
        (center_left + inset, center_right - inset),
        (center_right + inset, half_width - inset),
    )
    bar_y = (-FIDUCIAL_BLOCK_Y_CM / 2 + inset,
             FIDUCIAL_BLOCK_Y_CM / 2 - inset)
    gap_y = (FIDUCIAL_BLOCK_Y_CM / 2 + inset,
             FIDUCIAL_BLOCK_Y_CM / 2 + INTERNAL_GAP_CM - inset)

    bar_samples = {}
    for row in range(FIDUCIAL_ROWS):
        for col in range(FIDUCIAL_COLS):
            bar_samples[(col, row)] = tuple(
                sample_color_region(
                    sample_frame,
                    _region_quad(lattice, col, row, x0, x1, *bar_y),
                )
                for x0, x1 in x_ranges
            )
    gap_samples = {}
    paper_samples = {}
    for row in range(FIDUCIAL_ROWS - 1):
        for col in range(FIDUCIAL_COLS):
            gap_samples[(col, row)] = tuple(
                sample_color_region(
                    sample_frame,
                    _region_quad(lattice, col, row, x0, x1, *gap_y),
                )
                for x0, x1 in x_ranges
            )
            # The 0.8 cm X interval beside a fiducial is unprinted paper at
            # exactly the same Y and almost the same illumination. It is a far
            # safer beige reference than a global RGB constant or page corner.
            if col < FIDUCIAL_COLS - 1:
                paper_x = (half_width + inset,
                           half_width + FIDUCIAL_GAP_X_CM - inset)
            else:
                paper_x = (-half_width - FIDUCIAL_GAP_X_CM + inset,
                           -half_width - inset)
            paper_samples[(col, row)] = sample_color_region(
                sample_frame,
                _region_quad(lattice, col, row, *paper_x, *gap_y),
            )

    found = lattice.found_cells
    parity_votes = [
        (((col + row) % 2 == 0) == (cell.color == "green"))
        for (col, row), cell in found.items()
    ]
    even_is_green = sum(parity_votes) >= len(parity_votes) / 2

    def expected_color(cell):
        col, row = cell
        green = (((col + row) % 2 == 0) == even_is_green)
        return "green" if green else "purple"

    green_samples, magenta_samples = [], []
    for cell, thirds in bar_samples.items():
        observed = found.get(cell)
        target = observed.color if observed is not None else None
        if target == "green":
            green_samples.extend((thirds[0], thirds[2]))
        elif target == "magenta":
            magenta_samples.extend((thirds[0], thirds[2]))
    all_gap = [sample for thirds in gap_samples.values() for sample in thirds]
    all_samples = [sample for thirds in bar_samples.values() for sample in thirds]
    all_samples.extend(all_gap)
    all_samples.extend(paper_samples.values())
    threshold = _strength_threshold(all_samples)
    if not green_samples or not magenta_samples or not all_gap:
        raise ColorGridError(
            "the chromatic lattice was fitted, but too few internal green, "
            "purple and gray regions remain to decode its orientation",
            stage="orientation",
        )
    neutral_pool = sorted(all_gap + list(paper_samples.values()),
                          key=lambda sample: sample.strength)
    neutral_pool = neutral_pool[:max(8, len(neutral_pool) // 2)]
    prototypes = (_median_lab(green_samples), _median_lab(magenta_samples),
                  _median_lab(neutral_pool))

    classes = {
        cell: tuple(_classify_region(sample, threshold, *prototypes)
                    for sample in thirds)
        for cell, thirds in bar_samples.items()
    }
    gap_classes = {
        cell: tuple(_classify_region(sample, threshold, *prototypes)
                    for sample in thirds)
        for cell, thirds in gap_samples.items()
    }

    vertical_scores = {}
    for cell, thirds in bar_samples.items():
        expected = expected_color(cell)
        labels = classes[cell]
        center_match = float(labels[1] == expected)
        side_compatible = sum(label in (expected, "gray")
                              for label in (labels[0], labels[2])) / 2.0
        side_strength = (thirds[0].strength + thirds[2].strength) / 2.0
        strength_delta = thirds[1].strength - side_strength
        accent_lab = (lab_distance(thirds[1], thirds[0])
                      + lab_distance(thirds[1], thirds[2])) / 2.0
        accent = (0.60 * np.clip((strength_delta - 0.025) / 0.24, 0, 1)
                  + 0.40 * np.clip((accent_lab - 2.0) / 28.0, 0, 1))
        # The outer thirds are intentionally gray-mixed ink and can become
        # neutral on a faded print. The same-colour centre plus a measurable
        # local accent is mandatory; gray-compatible sides are supporting
        # evidence, never a substitute for that chromatic centre.
        vertical_scores[cell] = float(
            0.45 * center_match + 0.15 * side_compatible + 0.40 * accent)

    gap_direct_scores = {}
    gap_beige_scores = {}
    gap_anchor_scores = {}
    for cell, thirds in gap_samples.items():
        labels = gap_classes[cell]
        gray_fraction = sum(label == "gray" for label in labels) / 3.0
        paper = paper_samples[cell]
        outer_lab = (np.asarray(thirds[0].lab) + np.asarray(thirds[2].lab)) / 2.0
        center_lab = np.asarray(thirds[1].lab)
        paper_lab = np.asarray(paper.lab)

        # Primary beige detector: both outer thirds must differ from nearby
        # paper, yet remain much less chromatic than the colored rows. Lab
        # distance catches tint, L catches near-neutral ink density, and HSV /
        # opponent strength supplies the neutrality term.
        outer_deltas = [
            np.linalg.norm(np.asarray(thirds[0].lab) - paper_lab),
            np.linalg.norm(np.asarray(thirds[2].lab) - paper_lab),
        ]
        outer_delta = float(np.mean(outer_deltas))
        weaker_outer_delta = float(min(outer_deltas))
        outer_dark = float(paper_lab[0] - outer_lab[0])
        col, row = cell
        lower = classes[(col, row)]
        upper = classes[(col, row + 1)]
        colored_anchor = (
            sum(label == expected_color((col, row)) for label in lower)
            + sum(label == expected_color((col, row + 1)) for label in upper)
        ) / 6.0
        neighbor_strength = float(np.mean([
            sample.strength
            for neighbor in (bar_samples[(col, row)],
                             bar_samples[(col, row + 1)])
            for sample in neighbor
        ]))
        outer_strength = (thirds[0].strength + thirds[2].strength) / 2.0
        neutrality = float(np.clip(
            1.0 - outer_strength / max(neighbor_strength * 0.85, 0.08), 0, 1))
        beige_separation = float(
            0.45 * np.clip((outer_delta - 1.5) / 14.0, 0, 1)
            + 0.25 * np.clip((weaker_outer_delta - 1.5) / 14.0, 0, 1)
            + 0.30 * np.clip((outer_dark - 0.5) / 14.0, 0, 1))
        # Neutrality can confirm off-white ink, but blank white paper must stay
        # zero no matter how perfectly neutral it is.
        beige = beige_separation * (0.75 + 0.25 * neutrality)
        center_delta = float(np.linalg.norm(center_lab - paper_lab))
        center_blank = float(np.clip(1.0 - (center_delta - 1.0) / 11.0, 0, 1))
        direct = float(
            0.35 * beige + 0.35 * center_blank
            + 0.20 * colored_anchor + 0.10 * gray_fraction)
        gap_beige_scores[cell] = beige
        gap_anchor_scores[cell] = colored_anchor
        gap_direct_scores[cell] = direct

    # Structural fallback. The artwork has five encoded row intervals and four
    # plain separators, so the encoded gaps occupy one alternating parity. If
    # that parity has a strong sheet-wide beige separation, a washed-out,
    # shadowed or overprinted 1.6 cm center may be filled in from its two outer
    # thirds and its opposite-colour neighbors. No outer beige or no chromatic
    # anchors means no inference.
    row_beige = {
        row: float(np.median([
            gap_beige_scores[(col, row)] for col in range(FIDUCIAL_COLS)
        ]))
        for row in range(FIDUCIAL_ROWS - 1)
    }
    parity_strength = {
        parity: float(np.median([
            score for row, score in row_beige.items() if row % 2 == parity
        ]))
        for parity in (0, 1)
    }
    encoded_parity = max(parity_strength, key=parity_strength.get)
    other_parity = 1 - encoded_parity
    structural = (parity_strength[encoded_parity] >= 0.42
                  and parity_strength[encoded_parity]
                  >= parity_strength[other_parity] + 0.16)

    gap_scores = {}
    gap_inferred = {}
    for cell, direct in gap_direct_scores.items():
        col, row = cell
        fallback = 0.0
        if structural and row % 2 == encoded_parity:
            fallback = float(
                0.55 * gap_beige_scores[cell]
                + 0.30 * gap_anchor_scores[cell]
                + 0.15)
        gap_scores[cell] = max(direct, fallback)
        gap_inferred[cell] = (direct < HORIZONTAL_SCORE_MIN
                              <= fallback)

    horizontal_by_cell = {(col, row): 0.0
                          for row in range(FIDUCIAL_ROWS)
                          for col in range(FIDUCIAL_COLS)}
    gap_by_cell = {}
    inferred_by_cell = {}
    for (col, row), score in gap_scores.items():
        if score < HORIZONTAL_SCORE_MIN:
            continue
        for neighbor in ((col, row), (col, row + 1)):
            if score > horizontal_by_cell[neighbor]:
                horizontal_by_cell[neighbor] = score
                gap_by_cell[neighbor] = gap_classes[(col, row)]
                inferred_by_cell[neighbor] = gap_inferred[(col, row)]

    patterns = tuple(
        FiducialPattern(
            cell=(col, row),
            thirds=classes[(col, row)],
            gap_thirds=gap_by_cell.get((col, row)),
            vertical_score=vertical_scores[(col, row)],
            horizontal_score=horizontal_by_cell[(col, row)],
            horizontal_inferred=inferred_by_cell.get((col, row), False),
        )
        for row in range(FIDUCIAL_ROWS)
        for col in range(FIDUCIAL_COLS)
    )
    required = int(np.ceil(MIN_ORIENTATION_VOTE_FRACTION * len(patterns)))
    vertical_votes = sum(pattern.vertical_score >= VERTICAL_SCORE_MIN
                         for pattern in patterns)
    horizontal_votes = sum(pattern.horizontal_score >= HORIZONTAL_SCORE_MIN
                           for pattern in patterns)
    orientations = tuple(
        mode for mode, votes in (("vertical", vertical_votes),
                                 ("horizontal", horizontal_votes))
        if votes >= required
    )
    if not orientations:
        raise ColorGridError(
            "the 8x10 chromatic lattice is valid, but its internal thirds do "
            f"not encode a supported orientation (vertical votes "
            f"{vertical_votes}/80, horizontal votes {horizontal_votes}/80)",
            stage="orientation",
            lattice=[cell.quad for cell in lattice.cells if cell.full],
        )
    if requested_mode is not None and requested_mode not in orientations:
        detected = "+".join(orientations)
        raise ColorGridError(
            f"detected {detected} block orientation, but requested "
            f"{requested_mode} block orientation",
            stage="orientation",
            lattice=[cell.quad for cell in lattice.cells if cell.full],
        )
    return CombinedGridCalibration(
        lattice=lattice,
        method=method,
        patterns=patterns,
        orientations=orientations,
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
        ("segment", "lattice", "fit", "quality", "window", "selection",
         "orientation"))}
    return (stages.get(error.stage, -1), len(error.lattice), len(error.candidates))


def detect_combined_grids(frame: np.ndarray, *,
                          process_width: int = DEFAULT_PROCESS_WIDTH,
                          evidence: bool = False,
                          requested_mode: str | None = None):
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
        if exc.stage == "orientation":
            raise
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
        self._patterns = ()
        self._orientations = ()
        self._evidence = PaperGridEvidence(legacy_spec)

    @property
    def calibration(self):
        calibration = self._evidence.calibration
        if calibration is None:
            return None
        return (CombinedGridCalibration(
                    calibration, self._method or "full bars",
                    self._patterns, self._orientations)
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
        self._orientations = ()
        self._evidence = PaperGridEvidence(self.legacy_spec)

    def add(self, calibration):
        combined = isinstance(calibration, CombinedGridCalibration)
        kind = "combined" if combined else "legacy"
        if self._kind is None:
            self._kind = kind
            if combined:
                self._method = calibration.method
                self._patterns = calibration.patterns
                self._orientations = calibration.orientations
                self._evidence = PaperGridEvidence(calibration.spec)
        elif self._kind != kind:
            raise ColorGridError(
                "evidence changed printed-target designs; clear it and keep one "
                "sheet fixed for the whole session")
        measured = calibration.lattice if combined else calibration
        return self._evidence.add(measured)

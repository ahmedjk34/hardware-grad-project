#!/usr/bin/env python3
"""Find the printed two-colour calibration sheet and turn it into a grid.

Why this exists
---------------
Clicking four envelope corners by hand (``rig/workspace.py``) asks an operator
to guess where an invisible rectangle is, on a lens that still bows slightly
after correction. The printed sheet replaces the guess with something the
camera can measure: one alternating green/magenta block per grid cell, printed
at the rig's real ``2.2 x 7.5 cm`` block footprint with the real ``0.5 cm``
gap between neighbours. Every cell edge is then a measurement, and a hundred of
them are averaged into one homography instead of four clicks being trusted
absolutely.

The detector is deliberately independent of a camera, a window and the rig. It
takes a BGR frame and returns geometry. ``camera/color_grid_check.py`` drives
it live, the gridded feed and Rig Build V1 use it for their overlay and their
calibrate button, and the tests run it on still captures.

What "full cell" means, and why partials are dropped
----------------------------------------------------
The sheet is printed larger than the machine's grid, so the camera always sees
cells that run off the edge of the paper or the edge of the frame. Those are
**not** part of the project: their centres are wrong, their sizes are wrong,
and feeding them to the homography drags the whole map. So every detected
block is scored against the size the current lattice predicts for it, and only
blocks that are essentially whole (:data:`FULL_CELL_FILL`) are allowed to
define geometry. The outer white margin of the sheet is likewise never
measured — it is simply whatever lies beyond the last full cell.

How the lattice is found
------------------------
0. The frame is white balanced. This is not cosmetic — see :func:`white_balance`
   for the live frame where skipping it made every green cell invisible.
1. Two hue windows segment green and magenta. Their union is "some cell".
2. Each connected component becomes a rotated rectangle. Plausible cell shapes
   establish the median size and long-axis direction; scene-coloured rails and
   walls remain visible diagnostics but cannot steer the geometry.
3. Breadth-first walks are tried from every plausible seed. Each walk uses the
   current cell's own measured size and the known pitch/block ratio, then a
   provisional homography recovers physical cells beyond missed local hops.
   Hypotheses are ranked by coverage, colour parity and residual.
4. A homography is fitted from integer lattice indices to cell centres, every
   cell is re-scored against it, and the fit is repeated on the survivors.
   Parity, aspect and normalized residual gates refuse a plausible-looking but
   unsafe result.

Steps 3 and 4 are the whole trick. Residuals on the two supplied captures are
around one pixel at 2048 px wide, including the badly tilted one.

Which axis is X
---------------
Never from the image. The ``2.2 cm`` side and the ``7.5 cm`` side are 3.4:1
apart, so the axis with the shorter pitch is the machine's X and the other is
Y, whichever way round the sheet was photographed. That much is orientation
free and is what makes the module reusable when the camera is remounted.

The sheet may describe either calibrated machine layout.  In vertical mode the
machine X side is the short block side; in horizontal mode it is the long one.
The mode is an explicit input — the detector never guesses it from a partial
sheet — and the complete coordinate counts cross-check that the sheet and the
machine grid agree.  See ``plans/dual-orientation-grid.md`` D18.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math

import cv2
import numpy as np

from rig.config import (GRID_MODES, active_grid_mode, grid_geometry,
                        load as load_rig_config)


# The sheet is printed at the rig's own block geometry, so the ratio between a
# block and its pitch is fixed and known. Everything below is expressed in
# those ratios rather than in centimetres, which keeps the detector working at
# any camera distance without a scale calibration.  These are machine layouts,
# not camera rotations: a quarter-turned photograph is valid in either mode.
SUPPORTED_LAYOUTS = {
    "vertical": "y-along-block-length",
    "horizontal": "x-along-block-length",
}
# Compatibility name for callers that only ever dealt with the original sheet.
SUPPORTED_LAYOUT = SUPPORTED_LAYOUTS["vertical"]

# Hue windows, in OpenCV's 0..179 space, applied AFTER the white balance below.
# The training captures put green at 80-88 and magenta at 150-162. A live rig
# frame under a heavy magenta cast puts the same inks at 101 and 155 once
# balanced, and at 120 and 153 if it is not — which is how a green cell ends up
# looking cyan and vanishing. The windows are sized for the balanced range with
# room to spare, and the two never touch.
GREEN_HUE = (58, 115)
MAGENTA_HUE = (130, 178)

# Saturation floor. The rig's own lighting can leave the green ink at 48 while
# white paper sits at 15, so the floor lives between those rather than at the
# 50 the studio captures allowed. Anything below it is paper, not ink.
MIN_SATURATION = 32
MIN_VALUE = 40

# Shadow fallback in raw, normalized BGR chromaticity.  Multiplying a patch by
# an illumination gain changes neither score, unlike an absolute Value cutoff.
# The thresholds are conservative because this mask is ORed with HSV: it exists
# to reconnect ink at a dark edge, while the lattice/shape gates reject rails
# and other similarly coloured scene objects.
GREEN_OPPONENT_MIN = 0.035
MAGENTA_OPPONENT_MIN = 0.055
GREEN_CHANNEL_SPREAD_MIN = 10
MAGENTA_CHANNEL_SPREAD_MIN = 12

# Channel-ordering classifier, for an uncorrected rig camera where the yellow
# cast has pulled the paper and the green ink to nearly the same hue AND left
# the paper more saturated than the ink, so neither a hue window nor a
# saturation floor can separate them. What still holds under any single global
# cast is the ORDER of the channels: the green ink is the only material whose
# green channel is the largest; magenta is the only one whose green channel is
# the smallest with both others clearly above it. Margins are in 8-bit counts.
CHANNEL_ORDER_GREEN_MARGIN = 4
CHANNEL_ORDER_MAGENTA_B_MARGIN = 6
CHANNEL_ORDER_MAGENTA_R_MARGIN = 4

# The bright quantile that :func:`white_balance` drives to neutral. High enough
# to land on the sheet's white paper, low enough not to chase one specular
# highlight. Estimated on a subsampled frame; the scaling is applied to all of it.
WHITE_PATCH_QUANTILE = 0.92
_BALANCE_STRIDE = 8
_BALANCE_DEADBAND = 0.02        # below this the cast is not worth a pass over the frame

# Illumination flattening: divide the frame by a heavily blurred copy of itself,
# per channel, then re-mean. This removes the low-frequency part of a colour
# cast AND lens vignetting in one pass, which is what lets ink survive on the
# rig camera, where an uncorrected yellow cast leaves the paper MORE saturated
# than the green ink and at nearly the same hue. It is a coarse stand-in for a
# real `colourcal` matrix, not a replacement for one.
_FLATTEN_BLUR_FRACTION = 0.18   # sigma as a fraction of the short frame side
_FLATTEN_MIN_SIGMA = 9.0

# A block whose observed area is at least this fraction of the area the lattice
# predicts for it is whole. The captures put real cells at 0.93-1.03 and every
# clipped one below 0.7, so the cutoff is nowhere near either population.
FULL_CELL_FILL = 0.80
MAX_FULL_CELL_FILL = 1.35

# Seeds for the lattice walk must be this close to the median cell size. Only
# used to pick cells that are allowed to *propagate*; the real full/partial
# decision is made later against the fitted lattice.
SEED_SIZE_TOLERANCE = 0.28

# Raw hue masks on the live rig also contain rails, cables and parts of the
# wall.  They remain useful diagnostics, but they must not vote on the grid's
# dominant direction or median cell size.  These deliberately broad limits are
# only a pre-lattice plausibility filter; perspective-aware footprint scoring
# below makes the final whole/partial decision.
LATTICE_ASPECT_RANGE = (1.65, 7.0)
LATTICE_AREA_RANGE = (0.35, 2.8)
MIN_COLOR_PURITY = 0.65

# How far from the predicted position a neighbour may sit, as a fraction of the
# smaller pitch. Generous enough for a tilted sheet, far below half a pitch so
# it can never grab the cell after next.
NEIGHBOUR_TOLERANCE = 0.40

# Once one connected patch establishes a homography, project every other
# plausible component back into lattice space.  This reconnects real cells
# beyond a locally missed hop without inventing covered cells: only physical
# colour components close to an integer site are admitted.
RECOVERY_TOLERANCE = 0.34
RECOVERY_FILL_RANGE = (0.55, 1.45)
RECOVERY_PASSES = 3

# A complete rectangle is necessary but not sufficient for a calibration.
# These gates keep a regular-looking collection of scene clutter, a badly bowed
# lens fit, or a broken chessboard parity from becoming a workspace map.
MIN_PARITY_AGREEMENT = 0.95
VALID_ASPECT_FACTOR = (0.58, 1.75)
MAX_MEAN_RESIDUAL_SHORT_SIDE = 0.12
MAX_RESIDUAL_SHORT_SIDE = 0.45

# Working width for detection. The homography is fitted over ~100 cells, so
# sub-pixel loss from the downscale averages out, and this keeps a live overlay
# affordable on the Pi. Pass ``process_width=0`` to work at full resolution.
DEFAULT_PROCESS_WIDTH = 1024

# How much clear space a whole cell must keep between its own projected edge and
# the frame border, as a fraction of that cell's own projected size. A cell that
# comes closer than this - or crosses the border - is treated as clipped and can
# neither anchor the fit nor count toward a window's coverage. The default is
# deliberately aggressive: a sheet photographed to the frame edge loses its
# outermost ring rather than calibrating off half-visible blocks. Pass
# ``edge_margin=0`` to keep only the hard "contour actually overruns" test.
DEFAULT_EDGE_MARGIN = 0.5

# Upper bound on how many overlapping mode-sized windows a single detection
# offers the operator to cycle through. They are ranked bottom-left-first, so
# the cut only drops the farthest, least likely alternatives.
MAX_WINDOWS = 16

# A single evidence frame is allowed to have gantry-shaped holes.  Twelve
# cells is enough to establish both lattice axes and reject scene clutter; it
# is deliberately *not* enough to save a workspace map on its own.  That
# decision belongs to PaperGridEvidence, which combines accepted frames and
# applies coverage gates before a map can be written.
MIN_EVIDENCE_FRAME_FRACTION = 0.20


def min_evidence_frame_cells(spec) -> int:
    """Whole cells needed to fit one evidence frame for this sheet layout."""
    return math.ceil(MIN_EVIDENCE_FRAME_FRACTION * spec.cols * spec.rows)

# A mode-sized window may lose one or two cells to a lighting falloff at the
# edge of the sheet without losing its geometry: the homography is supported by
# the rest of the larger lattice.  This is deliberately much stricter than the
# evidence mode.  Every row and column must still contain observations, and
# nearly all of each.  ``_choose_windows`` returns every window that clears this
# on both axes; the frame-border ``edge_margin`` (below) is what stops a
# half-visible outer ring from anchoring one.
MIN_WINDOW_COVERAGE = 0.95

# A cell can remain plainly visible while a fixed colour threshold captures
# only part of its ink.  This happens in the live rig capture on the dim side
# of the sheet: magenta fills remain near 100%, while valid green fills fall as
# low as 24% (and to roughly 2% in the deliberately severe shadow regression).
# Such a fragment must not steer the homography (its contour centre can be
# biased), but pixels of the expected chessboard colour inside a
# homography-predicted footprint are still evidence that the physical cell
# exists.  This is only a coverage vote inside an already fitted lattice: the
# window still needs 95% support and paper/gantry occlusions contribute zero.
MIN_PREDICTED_INK_COVERAGE = 0.015

# How far a blob's long/short ratio may sit from the printed 3.41 and still be
# treated as a cell. Only used when sampling colour, where there is no lattice
# to fall back on and a mis-sampled wall would silently poison a calibration.
SHEET_ASPECT_RANGE = (2.2, 5.2)

MIN_COMPONENT_AREA = 250
_OPEN_KERNEL = np.ones((3, 3), np.uint8)


class ColorGridError(Exception):
    """The sheet could not be turned into a usable grid.

    Carries whatever geometry the failed attempt did produce. A tool that shows
    nothing at all when detection fails is the hardest possible thing to debug —
    "no overlay" looks identical whether the sheet is out of frame, the colours
    are wrong, or the code never ran. ``candidates`` lets the checker draw the
    colour blobs it did find, and ``stage`` says how far it got.
    """

    def __init__(self, message, *, stage="detect", candidates=(), lattice=(),
                 calibration=None):
        super().__init__(message)
        self.stage = stage
        self.candidates = tuple(candidates)   # Nx4x2 boxes, input-frame pixels
        self.lattice = tuple(lattice)         # the subset that joined a lattice
        # Orientation can fail only *after* a sound geometric calibration and
        # all internal stripes have been decoded.  Keeping that non-authorized
        # calibration on the exception lets diagnostic tools annotate the
        # conflicting signatures without accidentally returning it as usable.
        self.calibration = calibration


@dataclass(frozen=True)
class ColorGridSpec:
    """The printed sheet's geometry, which is the rig's block geometry.

    ``cols``/``rows`` are the *complete* coordinate map including zero — 7 x 6
    in vertical mode and 3 x 10 in horizontal — because the sheet prints a real
    block at every coordinate, coordinate zero included. The machine counts the
    same cells; the two differ only over which part of cell [0,0] the home
    corner sits on, which is why the mapping back onto the machine envelope is
    an explicit convention rather than an assumption.
    See :meth:`ColorGridCalibration.workspace_corners`.

    The gaps are a uniform 1.6 cm on both axes: a vertical block reads
    2.2 + 1.6 + 2.2 along its 6.0 cm length and consecutive blocks are also
    1.6 apart, so the 2.2 cm sub-cells repeat at one unbroken 3.8 cm pitch.
    Measured off the printed sheet - tiles 6.00 cm, gaps 1.56 cm, identical on
    both axes. Keep paired with config/rig.json.
    """

    cols: int = 7
    rows: int = 6
    block_x_cm: float = 2.2
    block_y_cm: float = 6.0
    gap_x_cm: float = 1.6
    gap_y_cm: float = 1.6
    mode: str = "vertical"

    @classmethod
    def from_config(cls, cfg: dict | None = None, mode: str | None = None) -> "ColorGridSpec":
        """Build one mode's printed map from ``config/rig.json``.

        ``mode`` is deliberately explicit at this seam.  A partial sheet does
        not contain enough information to infer a layout safely, while a UI
        already knows which machine grid it is calibrating.
        """
        cfg = cfg if cfg is not None else load_rig_config()
        name = active_grid_mode(cfg) if mode is None else str(mode)
        grid = grid_geometry(cfg, name)
        return cls(
            # No +1: the machine grid counts a real block at coordinate zero,
            # exactly as the sheet prints one, so the two counts agree outright.
            cols=int(grid["cols"]),
            rows=int(grid["rows"]),
            block_x_cm=float(grid["block_x_cm"]),
            block_y_cm=float(grid["block_y_cm"]),
            gap_x_cm=float(grid["gap_x_cm"]),
            gap_y_cm=float(grid["gap_y_cm"]),
            mode=name,
        )

    def __post_init__(self):
        values = (self.block_x_cm, self.block_y_cm, self.gap_x_cm, self.gap_y_cm)
        if not all(math.isfinite(v) and v > 0 for v in values[:2]):
            raise ValueError("printed block dimensions must be positive")
        if not all(math.isfinite(v) and v >= 0 for v in values[2:]):
            raise ValueError("printed gaps must be finite and non-negative")
        if self.cols < 2 or self.rows < 2:
            raise ValueError("the printed grid needs at least 2x2 coordinates")
        if self.mode not in GRID_MODES:
            raise ValueError(
                f"printed grid mode must be one of {', '.join(GRID_MODES)}, "
                f"not {self.mode!r}")
        if abs(self.block_x_cm - self.block_y_cm) < 1e-9:
            raise ValueError(
                "square cells give no way to tell the X side from the Y side"
            )

    @property
    def pitch_x_cm(self) -> float:
        return self.block_x_cm + self.gap_x_cm

    @property
    def pitch_y_cm(self) -> float:
        return self.block_y_cm + self.gap_y_cm

    @property
    def fill_x(self) -> float:
        """Block as a fraction of pitch along X: 2.2 / 3.8 (vertical)."""
        return self.block_x_cm / self.pitch_x_cm

    @property
    def fill_y(self) -> float:
        """Block as a fraction of pitch along Y: 6.0 / 6.8 (vertical)."""
        return self.block_y_cm / self.pitch_y_cm

    @property
    def short_is_x(self) -> bool:
        return self.block_x_cm < self.block_y_cm

    @property
    def layout(self) -> str:
        return SUPPORTED_LAYOUTS[self.mode]

    @property
    def lattice_counts(self) -> tuple[int, int]:
        """Required cells along the physical short and long block sides."""
        return ((self.cols, self.rows) if self.short_is_x
                else (self.rows, self.cols))

    def matches_grid(self, grid) -> bool:
        """Whether this sheet was made for exactly this machine layout."""
        return (
            self.mode == grid.mode
            and (self.cols, self.rows) == (grid.cols, grid.rows)
            and self.block_x_cm == grid.block_x_cm
            and self.block_y_cm == grid.block_y_cm
            and self.gap_x_cm == grid.gap_x_cm
            and self.gap_y_cm == grid.gap_y_cm
        )

    def describe(self) -> str:
        return (f"{self.mode} {self.cols}x{self.rows} printed coordinates, "
                f"{self.block_x_cm:g}x{self.block_y_cm:g} cm cells, "
                f"{self.gap_x_cm:g}x{self.gap_y_cm:g} cm inner margins, "
                f"pitch {self.pitch_x_cm:g}x{self.pitch_y_cm:g} cm")


@dataclass
class PrintedCell:
    """One block found on the sheet, in pixels of the frame that was passed in."""

    lattice: tuple[int, int]
    center: tuple[float, float]
    quad: np.ndarray                    # observed rotated rectangle, 4x2
    color: str                          # "green" or "magenta"
    area: float
    fill: float                         # observed area / lattice-predicted area
    full: bool
    cell: tuple[int, int] | None = None  # [col,row] once a window is chosen
    edge_clipped: bool = False           # too close to the frame border to trust


@dataclass
class ColorGridMetrics:
    input_size: tuple[int, int] = (0, 0)
    processing_size: tuple[int, int] = (0, 0)
    components: int = 0
    assigned: int = 0
    full_cells: int = 0
    lattice_shape: tuple[int, int] = (0, 0)
    residual_px: float = 0.0
    max_residual_px: float = 0.0
    parity_agreement: float = 0.0
    measured_aspect: float = 0.0
    window_candidates: int = 1
    window_index: int = 0
    window_observed: int = 0


# Where the machine's origin sits on the printed sheet. The sheet prints a real
# block at coordinate zero; the firmware treats coordinate zero as a bare point
# with only a 0.5 cm gap before cell 1. The two therefore cannot both be right,
# and picking one is a decision about the physical rig, not about the picture.
#
#   "firmware"  cells [1,1]..[9,5] on the paper land exactly on the firmware's
#               own cells. The machine envelope runs from the far corner of
#               printed [0,0] to the far corner of printed [9,5]. The printed
#               row/column-zero blocks are then only an anchor: they are not
#               where the firmware draws its axis-only lanes.
#
#   "printed"   the machine origin is the centre of printed cell [0,0], and
#               every printed cell is taken at face value. Positive cells then
#               sit half a block plus a gap further from home than the firmware
#               puts them: 1.1 cm on X and 3.75 cm on Y.
HOME_CONVENTIONS = ("firmware", "printed")
DEFAULT_HOME_CONVENTION = "firmware"


@dataclass
class ColorGridCalibration:
    """A fitted printed grid: ``[col,row]`` in, image pixels out.

    ``[0,0]`` is the cell nearest the bottom-left of the image, columns run
    along the short (X) cell side and rows along the long (Y) side. Everything
    is in pixels of the frame handed to :func:`detect_color_grid`.
    """

    spec: ColorGridSpec
    homography: np.ndarray              # [col,row,1] -> pixel, 3x3
    cells: list[PrintedCell]
    metrics: ColorGridMetrics = field(default_factory=ColorGridMetrics)
    layout: str | None = None

    def __post_init__(self):
        self.homography = np.asarray(self.homography, dtype=np.float64)
        if self.homography.shape != (3, 3):
            raise ValueError("homography must be 3x3")
        try:
            self._inverse = np.linalg.inv(self.homography)
        except np.linalg.LinAlgError as exc:
            # Degenerate rather than merely inaccurate: the cells the fit was
            # built from are collinear. Say that instead of leaking a linear
            # algebra message into an operator's status line.
            raise ColorGridError(
                "the detected cells are degenerate; the sheet is edge-on or "
                "only one row of it is in view") from exc
        if self.layout is None:
            self.layout = self.spec.layout
        elif self.layout != self.spec.layout:
            raise ValueError(
                f"printed grid layout {self.layout!r} disagrees with "
                f"the {self.spec.mode!r} sheet")

    # --- forward geometry -------------------------------------------------

    def point_at(self, col: float, row: float) -> tuple[float, float]:
        """Project continuous grid coordinates, cell centres at integers."""
        out = self.homography @ np.array([col, row, 1.0])
        if abs(out[2]) < 1e-12:
            raise ColorGridError("the printed grid mapping reaches infinity")
        return float(out[0] / out[2]), float(out[1] / out[2])

    def cell_center(self, col: int, row: int) -> tuple[float, float]:
        self._check(col, row)
        return self.point_at(col, row)

    def cell_quad(self, col: int, row: int) -> np.ndarray:
        """The printed block's four image corners, gaps excluded."""
        self._check(col, row)
        hx, hy = self.spec.fill_x / 2, self.spec.fill_y / 2
        corners = ((col - hx, row - hy), (col + hx, row - hy),
                   (col + hx, row + hy), (col - hx, row + hy))
        return np.array([self.point_at(u, v) for u, v in corners], dtype=np.float32)

    def outline(self) -> np.ndarray:
        """The four outer corners of the whole grid, no outer margin included.

        Deliberately the outer edges of the corner *blocks*, not a pitch-sized
        border: the sheet has no outer margin that belongs to the project, so
        the grid ends where the last block ends.
        """
        hx, hy = self.spec.fill_x / 2, self.spec.fill_y / 2
        c, r = self.spec.cols - 1, self.spec.rows - 1
        corners = ((-hx, -hy), (c + hx, -hy), (c + hx, r + hy), (-hx, r + hy))
        return np.array([self.point_at(u, v) for u, v in corners], dtype=np.float32)

    # --- inverse geometry -------------------------------------------------

    def grid_at(self, point) -> tuple[float, float]:
        """Pixel -> continuous grid coordinates."""
        out = self._inverse @ np.array([point[0], point[1], 1.0])
        if abs(out[2]) < 1e-12:
            raise ColorGridError("the printed grid mapping reaches infinity")
        return float(out[0] / out[2]), float(out[1] / out[2])

    def cell_at(self, point) -> tuple[int, int] | None:
        """Which printed block a pixel is on, or None for a gap/outside.

        Returns None inside the 0.5 cm inner margins on purpose: they are real
        white paper, not a rounding artefact, and reporting the nearer cell
        would quietly widen every block by a quarter of a gap.
        """
        u, v = self.grid_at(point)
        col, row = round(u), round(v)
        if not (0 <= col < self.spec.cols and 0 <= row < self.spec.rows):
            return None
        if abs(u - col) > self.spec.fill_x / 2 or abs(v - row) > self.spec.fill_y / 2:
            return None
        return col, row

    # --- mapping back onto the machine envelope ---------------------------

    def workspace_corners(self, grid, convention: str = DEFAULT_HOME_CONVENTION):
        """The four holder-envelope corners, in ``rig.workspace.CORNER_NAMES`` order.

        ``grid`` is a physically scaled :class:`rig.grid.MachineGrid`. The result
        is exactly what ``WorkspaceMap.from_grid`` wants, so a detected sheet can
        replace four clicked points without any other part of the pipeline
        learning that the sheet exists.

        See :data:`HOME_CONVENTIONS` for what the two conventions mean; they
        differ by one block plus one gap on each axis, which is the disagreement
        between a sheet that prints a block at coordinate zero and firmware that
        does not.
        """
        if convention not in HOME_CONVENTIONS:
            raise ValueError(
                f"convention must be one of {HOME_CONVENTIONS}, not {convention!r}")
        if not grid.has_physical_scale:
            raise ColorGridError("mapping to the envelope needs a scaled MachineGrid")
        self._check_geometry_matches(grid)

        # Printed-sheet centimetres, measured from the outer corner of printed
        # cell [0,0]: block `c` spans [c*pitch, c*pitch + block].
        if convention == "firmware":
            # Printed cell c coincides with firmware cell c, for every c
            # INCLUDING zero: the machine's coordinate 0 is a real block whose
            # outer edge sits on the home corner, exactly as the sheet prints
            # it. With the shipped zero trims this puts home on the outer
            # corner of printed [0,0] and the two conventions collapse to one
            # block-half apart, rather than the block-plus-gap they used to be.
            x0 = -grid.x_start_cm
            y0 = -grid.y_start_cm
        else:
            x0 = self.spec.block_x_cm / 2
            y0 = self.spec.block_y_cm / 2
        x1 = x0 + grid.workspace_width_cm
        y1 = y0 + grid.workspace_height_cm

        def to_grid(x_cm, y_cm):
            return ((x_cm - self.spec.block_x_cm / 2) / self.spec.pitch_x_cm,
                    (y_cm - self.spec.block_y_cm / 2) / self.spec.pitch_y_cm)

        corners_cm = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        return [self.point_at(*to_grid(x, y)) for x, y in corners_cm]

    def _check_geometry_matches(self, grid):
        if self.spec.mode != grid.mode:
            raise ColorGridError(
                f"the {self.spec.mode} printed sheet cannot calibrate the "
                f"{grid.mode} machine grid; select the {grid.mode} sheet")
        # No +1 any more: the machine grid counts a real block at coordinate
        # zero, exactly as the sheet prints it, so the two agree outright.
        expected_counts = (grid.cols, grid.rows)
        if (self.spec.cols, self.spec.rows) != expected_counts:
            raise ColorGridError(
                f"the {self.spec.mode} printed sheet maps "
                f"{self.spec.cols}x{self.spec.rows} coordinates, but the "
                f"{grid.mode} machine grid requires {expected_counts[0]}x"
                f"{expected_counts[1]}")
        pairs = ((self.spec.block_x_cm, grid.block_x_cm, "block X"),
                 (self.spec.block_y_cm, grid.block_y_cm, "block Y"),
                 (self.spec.gap_x_cm, grid.gap_x_cm, "gap X"),
                 (self.spec.gap_y_cm, grid.gap_y_cm, "gap Y"))
        for printed, machine, name in pairs:
            if abs(printed - machine) > 1e-6:
                raise ColorGridError(
                    f"the sheet was detected as {name} {printed:g} cm but the rig "
                    f"config says {machine:g} cm; reprint the sheet or fix rig.json")
        if (self.spec.cols, self.spec.rows) != (grid.cols, grid.rows):
            raise ColorGridError(
                f"the sheet grid is {self.spec.cols}x{self.spec.rows} coordinates "
                f"but the rig config asks for {grid.cols}x{grid.rows}")

    # --- reporting --------------------------------------------------------

    def _check(self, col, row):
        if not (0 <= col < self.spec.cols and 0 <= row < self.spec.rows):
            raise ValueError(
                f"[{col},{row}] is outside the printed "
                f"{self.spec.cols}x{self.spec.rows} grid")

    @property
    def found_cells(self) -> dict[tuple[int, int], PrintedCell]:
        return {cell.cell: cell for cell in self.cells if cell.cell is not None}

    def describe(self) -> str:
        m = self.metrics
        return (f"{self.spec.cols}x{self.spec.rows} printed grid from "
                f"{m.window_observed or m.full_cells}/{self.spec.cols * self.spec.rows} "
                f"window cells ({m.full_cells} lattice cells, {m.components} blobs), "
                f"candidate {m.window_index + 1}/{m.window_candidates}, residual "
                f"{m.residual_px:.2f} px (max {m.max_residual_px:.2f}), "
                f"parity {m.parity_agreement * 100:.0f}%")


# ---------------------------------------------------------------------------
# measuring the sheet's colours
# ---------------------------------------------------------------------------


def sample_ink_colors(frame: np.ndarray, *, min_saturation: int = MIN_SATURATION,
                      min_value: int = MIN_VALUE, min_pixels: int = 200):
    """Mean colour of the green ink, the magenta ink and the sheet's white paper.

    Returned as a :class:`vision.color_correction.ColorSamples`, which is what a
    colour calibration is fitted from.

    Deliberately independent of :func:`detect_color_grid`. Colour needs three
    materials measured, not a grid solved, and demanding a complete 10x6 fit
    first would refuse exactly the badly-framed, badly-tinted frames a colour
    calibration exists to fix. Any view with some of the sheet in it is enough.

    The masks are found on a white-balanced frame, because a cast bad enough to
    need correcting is bad enough to hide the ink from a fixed hue window; the
    *colours* are then read from the original, because the whole point is to
    measure the cast rather than to remove it twice.

    Paper is read from the ring immediately around the ink — the printed inner
    margins. That ring is the one white surface guaranteed to be lit exactly
    like the ink beside it, which a sheet corner, the bench or the wall behind
    the rig emphatically are not.
    """
    from vision.color_correction import ColorSamples

    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        raise ColorGridError("a three-channel BGR frame is required")
    height, width = frame.shape[:2]
    balanced = white_balance(frame)

    def cell_blobs(**mask_kwargs):
        """Cell-shaped green/magenta blobs, filtered to one modal area."""
        g, m = color_masks(balanced, min_value=min_value, balance=False,
                           **mask_kwargs)
        # Only sample things shaped like a printed cell. Under a bad enough cast
        # the wall behind the rig lands inside the magenta window, far larger
        # than every real cell put together — averaging it in would measure the
        # wall and call it ink. Shape is what tells them apart.
        blobs = [rect for rect in _components(g, m, MIN_COMPONENT_AREA,
                                              (width, height))
                 if SHEET_ASPECT_RANGE[0]
                 <= rect["long_len"] / max(rect["short_len"], 1e-6)
                 <= SHEET_ASPECT_RANGE[1]]
        # Reject outliers against each ink's OWN modal area, not a shared one:
        # under a cast one ink often fragments into smaller pieces than the
        # other, and a shared median would then drop every blob of the weaker
        # colour and leave the sampler with two of the three materials.
        kept = []
        for colour in ("green", "magenta"):
            same = [rect for rect in blobs if rect["color"] == colour]
            if not same:
                continue
            median = float(np.median([rect["area"] for rect in same]))
            kept += [rect for rect in same
                     if 0.5 * median <= rect["area"] <= 1.8 * median]
        return kept

    # First the plain hue window. If a strong camera cast has hidden one ink -
    # which is exactly the frame `colourcal` exists to fix, so it cannot just be
    # refused - ADD (never replace) blobs of the missing colour from the
    # cast-invariant channel-order classifier at a low saturation floor.
    keep = cell_blobs(min_saturation=min_saturation)
    missing_inks = {"green", "magenta"} - {rect["color"] for rect in keep}
    if missing_inks:
        extra = cell_blobs(min_saturation=max(6, min_saturation // 4),
                           channel_order=True)
        keep += [rect for rect in extra if rect["color"] in missing_inks]
    if not keep:
        raise ColorGridError(
            "nothing on the sheet is shaped like a printed cell; is the sheet "
            "in frame, roughly in focus, and filling most of the view? A "
            "strong uncorrected camera cast can also hide it — try `wb` first, "
            "or point the camera at a few big solid green/magenta swatches")

    cores = {}
    for name in ("green", "magenta"):
        mask = np.zeros((height, width), np.uint8)
        boxes = [rect["box"] for rect in keep if rect["color"] == name]
        if boxes:
            cv2.fillPoly(mask, [box.astype(np.int32) for box in boxes], 255)
        # Erode well inside the blocks: the ink's printed edge is soft and the
        # lens leaves a halo on it, and both drag the mean toward the paper.
        cores[name] = cv2.erode(mask, np.ones((5, 5), np.uint8),
                                iterations=2).astype(bool)

    ink = np.zeros((height, width), np.uint8)
    cv2.fillPoly(ink, [rect["box"].astype(np.int32) for rect in keep], 255)
    ink_bool = ink.astype(bool)

    # Grid-structure recovery. When one ink is so badly cast that it reads as
    # neutral grey — the rig camera turns the olive green to (b>g=r), invisible
    # to every hue window AND to the channel-order test — the OTHER ink's cells
    # still lay out the grid. The missing ink's cells are then "inside the sheet
    # the visible ink defines, not that ink, and darker than the paper". This is
    # deliberately the last resort: it locates the cells by structure and reads
    # whatever colour is physically there, which is the whole point for a
    # calibration that has to learn `grey -> green`.
    hsv0 = cv2.cvtColor(balanced, cv2.COLOR_BGR2HSV)
    sat0, val0 = hsv0[:, :, 1], hsv0[:, :, 2]
    for missing, present in (("green", "magenta"), ("magenta", "green")):
        if cores[missing].any() or not cores[present].any():
            continue
        span = int(round(1.4 * math.sqrt(max(1.0, float(np.median(
            [r["long_len"] * r["short_len"]
             for r in keep if r["color"] == present]))))))
        span = max(9, span | 1)
        sheet = cv2.dilate((cores[present] | ink_bool).astype(np.uint8),
                           np.ones((span, span), np.uint8), 1)
        sheet = cv2.erode(sheet, np.ones(((span // 2) | 1,) * 2, np.uint8), 1)
        inside = sheet.astype(bool)
        bright = inside & (sat0 < 25) & (val0 > 170)
        if bright.sum() < min_pixels:
            continue
        paper_val = float(np.median(val0[bright]))
        guess = (inside & ~ink_bool
                 & (val0 < paper_val - 20) & (sat0 < 70))
        guess = cv2.erode(guess.astype(np.uint8), np.ones((7, 7), np.uint8),
                          iterations=2).astype(bool)
        if guess.sum() < min_pixels:
            continue
        cand = frame[guess].astype(np.float64).mean(axis=0)
        paper_bgr = frame[inside & (sat0 < 18) & (val0 >= paper_val - 6)]
        other = frame[cores[present]].astype(np.float64).mean(axis=0)
        # Only accept a structural guess that is a genuinely distinct material:
        # clearly darker than paper and not just the visible ink again. If it is
        # not, leave the ink unsampled — an honest two-colour set drives a
        # constrained gain/affine fit, which is all a green-blind frame supports.
        if len(paper_bgr) >= min_pixels:
            if float(np.linalg.norm(cand - paper_bgr.mean(axis=0))) < 14.0:
                continue
        if float(np.linalg.norm(cand - other)) < 12.0:
            continue
        cores[missing] = guess
    # The margins: a ring around the ink that is itself not ink. A wider ring
    # than the paper needs, so the warm "beige" band that the combined target
    # prints between perpendicular fiducials falls inside it too.
    ring = cv2.dilate(ink, np.ones((15, 15), np.uint8), iterations=1).astype(bool)
    hsv = cv2.cvtColor(balanced, cv2.COLOR_BGR2HSV)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]
    pale = (sat < min_saturation) & (val >= min_value)
    outside = ring & ~ink_bool & (val >= min_value)
    paper_core = outside & pale
    # Beige: pale but not neutral, and warm (red clearly the strongest channel
    # in BOTH the raw and the balanced frame, so a cast cannot fake it). The
    # combined sheet's off-white lanes; a distinct tone from true paper.
    b_raw, g_raw, r_raw = (frame[:, :, i].astype(np.int16) for i in range(3))
    b_bal, g_bal, r_bal = (balanced[:, :, i].astype(np.int16) for i in range(3))
    warm = ((r_raw - b_raw) >= 10) & (r_raw >= g_raw) & ((r_bal - b_bal) >= 4)
    beige_core = outside & warm & (sat < min_saturation + 12)
    green_core, magenta_core = cores["green"], cores["magenta"]

    colors, counts, spread = {}, {}, {}

    def take(name, mask, floor=min_pixels):
        pixels = frame[mask]
        if len(pixels) < floor:
            return
        values = pixels.astype(np.float64)
        mean = values.mean(axis=0)
        colors[name] = tuple(float(v) for v in mean)
        counts[name] = int(len(values))
        spread[name] = float(np.sqrt(np.mean(np.sum((values - mean) ** 2, axis=1))))

    take("paper", paper_core)
    for name, mask in (("green", green_core), ("magenta", magenta_core)):
        take(name, mask)
        # An ink sample that came out indistinguishable from the paper is not a
        # measurement of that ink - it is stray near-white pixels the cast
        # let through. Drop it rather than feed a false correspondence to the
        # fit; a genuine two-colour set is the honest input for that frame.
        if (name in colors and "paper" in colors
                and float(np.linalg.norm(np.array(colors[name])
                                         - np.array(colors["paper"]))) < 16.0):
            del colors[name], counts[name], spread[name]

    # Best-effort EXTRA correspondences. Each printed fiducial has a dark accent
    # third and two muted "off-white-ish" thirds blended toward the paper, and
    # the combined sheet prints a warm beige lane. More non-degenerate colour
    # pairs make the 3x3 fit a real least squares rather than an exactly
    # determined one. Only kept when they are meaningfully different from a
    # colour already sampled - a duplicate adds nothing and can rank-degrade the
    # matrix, and a flat solid swatch legitimately has no sub-tones.
    def take_distinct(name, mask, floor):
        take(name, mask, floor)
        if name not in colors:
            return
        here = np.array(colors[name])
        if any(float(np.linalg.norm(here - np.array(colors[other]))) < 8.0
               for other in colors if other != name):
            del colors[name], counts[name], spread[name]

    take_distinct("beige", beige_core, min_pixels)
    for base, core in (("green", green_core), ("magenta", magenta_core)):
        core_vals = val[core]
        if core_vals.size < 4 * min_pixels:
            continue
        dark_cut = float(np.percentile(core_vals, 35))
        muted_cut = float(np.percentile(core_vals, 60))
        take_distinct(f"{base}_dark", core & (val <= dark_cut), min_pixels // 2)
        take_distinct(f"{base}_muted", core & (val >= muted_cut), min_pixels // 2)

    if len({n for n in colors if n in ("green", "magenta", "paper")}) < 2:
        raise ColorGridError(
            f"only found {', '.join(colors) or 'nothing'} on the sheet; at least "
            f"two of green ink, magenta ink and paper have to be visible")
    return ColorSamples(colors=colors, counts=counts, spread=spread)


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------


def white_balance(frame: np.ndarray,
                  quantile: float = WHITE_PATCH_QUANTILE) -> np.ndarray:
    """Scale each channel so the frame's bright quantile is neutral.

    Absolute hue windows cannot survive an arbitrary camera white balance, and
    the rig's camera does not have a good one: on a live frame the whole scene
    carried a magenta cast strong enough to move the green ink to hue 120 with
    saturation 49 — outside the green window *and* under the saturation floor,
    so half of every sheet disappeared and no lattice could form.

    White-patch rather than grey-world on purpose. The sheet's white paper is
    the brightest large thing in a frame that is mostly sheet, which makes the
    bright quantile a real white reference; grey-world would instead be dragged
    around by how much of the frame the pink inks happen to cover.
    """
    sample = frame[::_BALANCE_STRIDE, ::_BALANCE_STRIDE].reshape(-1, 3)
    references = np.percentile(sample, quantile * 100.0, axis=0)
    target = float(references.mean())
    if target <= 0:
        return frame
    scale = target / np.maximum(references, 1e-6)
    if np.allclose(scale, 1.0, atol=_BALANCE_DEADBAND):
        return frame
    # A lookup table, not a float multiply over the whole frame: this runs on
    # every analysed frame on a Pi, and the float round trip costs more than
    # the rest of the detector put together.
    ramp = np.arange(256, dtype=np.float32)
    table = np.clip(ramp[None, :] * scale[:, None], 0, 255).astype(np.uint8)
    return cv2.LUT(frame, np.ascontiguousarray(table.T.reshape(1, 256, 3)))


def flatten_illumination(frame: np.ndarray,
                         blur_fraction: float = _FLATTEN_BLUR_FRACTION) -> np.ndarray:
    """Divide out the low-frequency lighting/cast, per channel, and re-mean.

    ``blurred`` is a very soft Gaussian: everything slower than a cell. Dividing
    by it turns "ink on cast-tinted, unevenly lit paper" into "ink on flat
    neutral paper", which is the difference between the rig camera's green ink
    being findable and not. High-frequency detail (the ink itself, the printed
    gaps) is untouched because it is not in the blur.

    Cheap enough for a live Pi frame: one separable blur plus a divide on the
    working-resolution image.
    """
    if frame is None or frame.ndim != 3:
        return frame
    short_side = min(frame.shape[:2])
    sigma = max(_FLATTEN_MIN_SIGMA, blur_fraction * short_side)
    blurred = cv2.GaussianBlur(frame.astype(np.float32), (0, 0),
                               sigmaX=sigma, sigmaY=sigma)
    blurred = np.maximum(blurred, 1.0)
    ratio = frame.astype(np.float32) / blurred
    # Re-mean each channel to the frame's own mid so downstream Value floors and
    # the overlay still see a normally exposed image.
    target = float(np.mean(frame))
    flat = ratio * target
    return np.clip(flat, 0, 255).astype(np.uint8)


@dataclass(frozen=True)
class ColorRegionStats:
    """Robust colour measurements for one projected artwork subregion.

    The three representations are intentionally retained together. HSV
    saturation separates ink from neutral paper, Lab distance survives modest
    exposure changes, and normalized opponent channels remain useful in deep
    shadows where hue becomes noisy.
    """

    bgr: tuple[float, float, float]
    hsv: tuple[float, float, float]
    lab: tuple[float, float, float]
    green_opponent: float
    magenta_opponent: float
    strength: float
    pixels: int


def sample_color_region(frame: np.ndarray, polygon) -> ColorRegionStats:
    """Measure a projected polygon with channel, HSV and Lab robust medians."""
    points = np.asarray(polygon, dtype=np.float32).round().astype(np.int32)
    x, y, width, height = cv2.boundingRect(points)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(frame.shape[1], x + width), min(frame.shape[0], y + height)
    if x1 <= x0 or y1 <= y0:
        pixels = np.empty((0, 3), np.uint8)
    else:
        local = points - np.int32((x0, y0))
        mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillConvexPoly(mask, local, 255, cv2.LINE_AA)
        pixels = frame[y0:y1, x0:x1][mask >= 192]
    if len(pixels) < 9:
        raise ColorGridError(
            "an internal fiducial subregion projects to too few pixels; move "
            "the camera closer or use a higher-resolution frame",
            stage="orientation",
        )
    bgr = np.median(pixels.astype(np.float32), axis=0)
    hsv_pixels = cv2.cvtColor(pixels.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV)
    lab_pixels = cv2.cvtColor(pixels.reshape(-1, 1, 3), cv2.COLOR_BGR2LAB)
    hsv = np.median(hsv_pixels.astype(np.float32), axis=0).reshape(3)
    lab = np.median(lab_pixels.astype(np.float32), axis=0).reshape(3)
    b, g, r = (float(value) for value in bgr)
    total = b + g + r + 12.0
    green_opponent = (g - (r + b) * 0.5) / total
    magenta_opponent = ((r + b) * 0.5 - g) / total
    spread = (max(b, g, r) - min(b, g, r)) / max(max(b, g, r), 12.0)
    lab_chroma = float(np.linalg.norm(lab[1:] - 128.0)) / 100.0
    strength = float(np.clip(
        0.45 * hsv[1] / 255.0 + 0.30 * spread + 0.25 * lab_chroma,
        0.0, 1.5,
    ))
    return ColorRegionStats(
        bgr=tuple(float(value) for value in bgr),
        hsv=tuple(float(value) for value in hsv),
        lab=tuple(float(value) for value in lab),
        green_opponent=green_opponent,
        magenta_opponent=magenta_opponent,
        strength=strength,
        pixels=int(len(pixels)),
    )


def lab_distance(first: ColorRegionStats, second: ColorRegionStats) -> float:
    """Euclidean OpenCV-Lab distance between two robust region samples."""
    return float(np.linalg.norm(
        np.asarray(first.lab, dtype=np.float32)
        - np.asarray(second.lab, dtype=np.float32)))


def channel_order_masks(frame: np.ndarray, min_value: int = MIN_VALUE
                        ) -> tuple[np.ndarray, np.ndarray]:
    """Cast-invariant green/magenta masks from the ORDER of the BGR channels.

    Green ink is the only sheet material whose green channel is the maximum;
    magenta is the only one whose green channel is the minimum with both blue
    and red clearly above it. Paper - even a strongly yellow-cast paper that a
    hue window and a saturation floor both mistake for green ink - has blue as
    its maximum and green above red, so it is neither. This survives any single
    global colour cast, which is exactly the failure mode of an uncalibrated
    rig camera.
    """
    b, g, r = (channel.astype(np.int16) for channel in cv2.split(frame))
    value = np.maximum.reduce((b, g, r))
    lit = value >= min_value
    other_max = np.maximum(b, r)
    green = (g >= b) & (g >= r) & ((g - other_max) >= CHANNEL_ORDER_GREEN_MARGIN) & lit
    magenta = (((b - g) >= CHANNEL_ORDER_MAGENTA_B_MARGIN)
               & ((r - g) >= CHANNEL_ORDER_MAGENTA_R_MARGIN) & lit)
    return green, magenta


def color_masks(frame: np.ndarray, *, min_saturation: int = MIN_SATURATION,
                min_value: int = MIN_VALUE, green_hue=GREEN_HUE,
                magenta_hue=MAGENTA_HUE,
                use_opponent: bool = True,
                balance: bool = True,
                flatten: bool = False,
                channel_order: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Return the (green, magenta) boolean masks for one BGR frame.

    Hue plus a saturation floor, not brightness: the two inks stay a long way
    apart in hue under any light, while their brightness does not. ``balance``
    neutralises the camera's colour cast first — see :func:`white_balance` for
    why that is not optional in practice. ``flatten`` additionally divides out
    the low-frequency lighting/cast (:func:`flatten_illumination`) first.
    ``channel_order`` unions in :func:`channel_order_masks`, the cast-invariant
    classifier for a camera that has not been colour-calibrated yet.
    """
    if flatten:
        frame = flatten_illumination(frame)
    raw = frame
    balanced = white_balance(frame) if balance else frame
    hsv = cv2.cvtColor(balanced, cv2.COLOR_BGR2HSV)
    hue, sat, val = cv2.split(hsv)
    strong = (sat >= min_saturation) & (val >= min_value)
    green = (hue >= green_hue[0]) & (hue <= green_hue[1]) & strong
    magenta = (hue >= magenta_hue[0]) & (hue <= magenta_hue[1]) & strong

    if channel_order:
        order_green, order_magenta = channel_order_masks(raw, min_value)
        green = green | order_green
        magenta = magenta | order_magenta

    # A second, illumination-invariant vote.  Use the raw frame so a global
    # white-patch estimate cannot amplify one shadow differently from another.
    # Adding a small denominator pedestal suppresses quantisation noise in very
    # dark near-black pixels.
    if use_opponent:
        b, g, r = np.moveaxis(raw.astype(np.float32), 2, 0)
        total = b + g + r + 12.0
        spread = np.maximum.reduce((b, g, r)) - np.minimum.reduce((b, g, r))
        weak_chroma = sat >= max(8, min_saturation // 2)
        green |= (((g - r) / total >= GREEN_OPPONENT_MIN)
                  & (spread >= GREEN_CHANNEL_SPREAD_MIN)
                  & weak_chroma & (hue >= green_hue[0] - 8)
                  & (hue <= green_hue[1] + 8))
        magenta |= ((((r + b) * 0.5 - g) / total >= MAGENTA_OPPONENT_MIN)
                    & (spread >= MAGENTA_CHANNEL_SPREAD_MIN)
                    & weak_chroma & (hue >= magenta_hue[0] - 8))
    return green, magenta


def _components(green, magenta, min_area, size, close_size=0):
    """Rotated rectangles for every colour blob, with a global axis sense."""
    mask = (green | magenta).astype(np.uint8) * 255
    if close_size:
        close_size = max(3, int(close_size) | 1)
        close_kernel = np.ones((close_size, close_size), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel, iterations=1)
    mask = cv2.morphologyEx(mask,
                            cv2.MORPH_OPEN, _OPEN_KERNEL, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    width, height = size
    found = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        box = cv2.boxPoints(cv2.minAreaRect(contour))
        edge_a, edge_b = box[1] - box[0], box[2] - box[1]
        len_a, len_b = np.linalg.norm(edge_a), np.linalg.norm(edge_b)
        if min(len_a, len_b) < 2:
            continue
        if len_a >= len_b:
            long_axis, long_len, short_axis, short_len = edge_a / len_a, len_a, edge_b / len_b, len_b
        else:
            long_axis, long_len, short_axis, short_len = edge_b / len_b, len_b, edge_a / len_a, len_a
        center = box.mean(axis=0)
        x0, y0, box_width, box_height = cv2.boundingRect(contour)
        local = np.zeros((box_height, box_width), np.uint8)
        shifted = contour - np.array([[[x0, y0]]], dtype=contour.dtype)
        cv2.drawContours(local, [shifted], -1, 1, cv2.FILLED)
        green_count = int(np.count_nonzero(green[y0:y0 + box_height,
                                                x0:x0 + box_width] & local.astype(bool)))
        magenta_count = int(np.count_nonzero(magenta[y0:y0 + box_height,
                                                    x0:x0 + box_width] & local.astype(bool)))
        color_total = green_count + magenta_count
        found.append({
            "center": center, "box": box, "area": area,
            "long_axis": long_axis, "long_len": long_len,
            "short_axis": short_axis, "short_len": short_len,
            "color": "green" if green_count >= magenta_count else "magenta",
            "color_purity": (max(green_count, magenta_count) / color_total
                             if color_total else 0.0),
            "clipped": bool(box[:, 0].min() < 2 or box[:, 1].min() < 2
                            or box[:, 0].max() > width - 3
                            or box[:, 1].max() > height - 3),
        })
    if not found:
        return found

    # One shared sense for "along the long side" and "along the short side".
    # Without this the per-rectangle axes point in arbitrary directions and the
    # walk below assigns two neighbours the same index. Doubling the angles
    # before averaging makes the mean insensitive to a 180 degree flip.
    angles = np.array([math.atan2(r["long_axis"][1], r["long_axis"][0]) for r in found])
    mean = 0.5 * math.atan2(float(np.mean(np.sin(2 * angles))),
                            float(np.mean(np.cos(2 * angles))))
    ref_long = np.array([math.cos(mean), math.sin(mean)])
    ref_short = np.array([-ref_long[1], ref_long[0]])
    for rect in found:
        if rect["long_axis"] @ ref_long < 0:
            rect["long_axis"] = -rect["long_axis"]
        if rect["short_axis"] @ ref_short < 0:
            rect["short_axis"] = -rect["short_axis"]
    return found


def _prepare_lattice_candidates(found, aspect_range=LATTICE_ASPECT_RANGE):
    """Mark cell-like components and give their axes one robust global sense.

    The colour mask intentionally over-detects.  The live scene can contain a
    magenta wall and long aluminium rails, so using every blob to establish the
    median dimensions and direction lets background geometry steer the walk.
    Keep those blobs for the failure overlay, but exclude implausible shapes
    from lattice voting.
    """
    plausible = []
    for index, rect in enumerate(found):
        aspect = rect["long_len"] / max(rect["short_len"], 1e-6)
        rect["plausible"] = (
            aspect_range[0] <= aspect <= aspect_range[1]
            and rect.get("color_purity", 1.0) >= MIN_COLOR_PURITY
        )
        if rect["plausible"] and not rect["clipped"]:
            plausible.append(index)
    if not plausible:
        for rect in found:
            rect["seed"] = False
        return []

    areas = np.array([found[index]["area"] for index in plausible], dtype=float)
    area_med = float(np.median(areas))
    size_like = [index for index in plausible
                 if LATTICE_AREA_RANGE[0] * area_med <= found[index]["area"]
                 <= LATTICE_AREA_RANGE[1] * area_med]
    if not size_like:
        size_like = plausible

    # Recompute the shared direction from cell-like components only.  The axes
    # returned by minAreaRect are mod 180 degrees, hence the doubled angles.
    angles = np.array([
        math.atan2(found[index]["long_axis"][1], found[index]["long_axis"][0])
        for index in size_like
    ])
    mean = 0.5 * math.atan2(float(np.mean(np.sin(2 * angles))),
                            float(np.mean(np.cos(2 * angles))))
    ref_long = np.array([math.cos(mean), math.sin(mean)])
    ref_short = np.array([-ref_long[1], ref_long[0]])
    for rect in found:
        if rect["long_axis"] @ ref_long < 0:
            rect["long_axis"] = -rect["long_axis"]
        if rect["short_axis"] @ ref_short < 0:
            rect["short_axis"] = -rect["short_axis"]

    long_med = float(np.median([found[index]["long_len"] for index in size_like]))
    short_med = float(np.median([found[index]["short_len"] for index in size_like]))
    eligible = []
    for index, rect in enumerate(found):
        area_ok = (LATTICE_AREA_RANGE[0] * area_med <= rect["area"]
                   <= LATTICE_AREA_RANGE[1] * area_med)
        rect["eligible"] = bool(rect["plausible"] and area_ok)
        rect["seed"] = bool(
            rect["eligible"]
            and abs(rect["long_len"] - long_med) < SEED_SIZE_TOLERANCE * long_med
            and abs(rect["short_len"] - short_med) < SEED_SIZE_TOLERANCE * short_med
            and not rect["clipped"]
        )
        if rect["eligible"]:
            eligible.append(index)
    return eligible


def _walk_from(start, found, eligible, short_ratio, long_ratio, centers,
               neighbour_hops=(1,)):
    """One local neighbour walk, rooted at a particular plausible cell."""
    allowed = np.zeros(len(found), dtype=bool)
    allowed[eligible] = True
    coords = {start: (0, 0)}
    taken = {(0, 0): start}
    queue = [start]
    while queue:
        index = queue.pop(0)
        rect = found[index]
        i, j = coords[index]
        step_short = rect["short_len"] * short_ratio
        step_long = rect["long_len"] * long_ratio
        hops = []
        for hop in neighbour_hops:
            hops.extend((
                ((hop, 0), rect["short_axis"] * step_short * hop),
                ((-hop, 0), -rect["short_axis"] * step_short * hop),
                ((0, hop), rect["long_axis"] * step_long * hop),
                ((0, -hop), -rect["long_axis"] * step_long * hop),
            ))
        for (di, dj), offset in hops:
            target = (i + di, j + dj)
            if target in taken:
                continue
            distance = np.linalg.norm(centers - (rect["center"] + offset), axis=1)
            distance[~allowed] = np.inf
            distance[list(coords)] = np.inf
            best = int(np.argmin(distance))
            if (not math.isfinite(float(distance[best]))
                    or distance[best] > NEIGHBOUR_TOLERANCE * min(step_short, step_long)):
                continue
            coords[best] = target
            taken[target] = best
            if found[best]["seed"]:
                queue.append(best)
    return coords


def _parity_agreement(coords, found):
    if not coords:
        return 0.0
    votes = [((i + j) % 2 == 0) == (found[index]["color"] == "green")
             for index, (i, j) in coords.items()]
    agreement = sum(votes)
    return max(agreement, len(votes) - agreement) / len(votes)


def _predicted_cell_area(matrix, key, spec):
    i, j = key
    half = np.float32([[-spec.fill_x / 2, -spec.fill_y / 2],
                       [spec.fill_x / 2, -spec.fill_y / 2],
                       [spec.fill_x / 2, spec.fill_y / 2],
                       [-spec.fill_x / 2, spec.fill_y / 2]])
    if not spec.short_is_x:
        half = half[:, ::-1].copy()
    quad = cv2.perspectiveTransform(
        (half + np.float32([i, j])).reshape(-1, 1, 2), matrix).reshape(-1, 2)
    return abs(cv2.contourArea(quad.astype(np.float32)))


def _recover_lattice(coords, found, eligible, spec,
                     fill_range=RECOVERY_FILL_RANGE):
    """Attach physical cells missed by the local walk using grid-space residuals."""
    coords = dict(coords)
    for _ in range(RECOVERY_PASSES):
        matrix, _mean, _maximum = _fit(coords, found, lambda _index: True)
        if matrix is None:
            break
        try:
            inverse = np.linalg.inv(matrix)
        except np.linalg.LinAlgError:
            break

        # Establish whether even lattice parity is green or magenta from the
        # current physical observations; the repeating colours then reject many
        # scene blobs for free.
        even_green = sum(
            (((i + j) % 2 == 0) == (found[index]["color"] == "green"))
            for index, (i, j) in coords.items()
        ) >= len(coords) / 2

        proposals = []
        for index in eligible:
            point = inverse @ np.array([*found[index]["center"], 1.0])
            if abs(point[2]) < 1e-12:
                continue
            lattice = point[:2] / point[2]
            key = tuple(int(round(value)) for value in lattice)
            error = float(np.linalg.norm(lattice - np.asarray(key)))
            if error > RECOVERY_TOLERANCE:
                continue
            expected_green = (((key[0] + key[1]) % 2 == 0) == even_green)
            if (found[index]["color"] == "green") != expected_green:
                continue
            predicted = _predicted_cell_area(matrix, key, spec)
            fill = found[index]["area"] / predicted if predicted > 0 else 0.0
            if not (fill_range[0] <= fill <= fill_range[1]):
                continue
            proposals.append((error + abs(fill - 1.0) * 0.08, index, key))

        # One physical component per lattice site.  Resolve collisions by the
        # best normalized centre/area agreement, not contour discovery order.
        # Never erase observations that established the hypothesis merely
        # because parity is poor; the quality gate must see and reject that
        # disagreement.  Parity is used only to stop new scene clutter joining.
        claimed = {key: (-1.0, index) for index, key in coords.items()}
        for score, index, key in sorted(proposals):
            if key not in claimed:
                claimed[key] = (score, index)
        recovered = {index: key for key, (_score, index) in claimed.items()}
        if recovered == coords:
            break
        coords = recovered
    return coords


def _walk_lattice(found, spec, aspect_range=LATTICE_ASPECT_RANGE,
                  recovery_fill_range=RECOVERY_FILL_RANGE,
                  neighbour_hops=(1,)):
    """Fit the strongest lattice hypothesis, then recover disconnected cells.

    Index ``i`` counts along the short cell side and ``j`` along the long one.
    Starting from every plausible seed avoids committing to whichever blob lies
    nearest the mean of a cluttered frame.  Equivalent walks are deduplicated,
    expanded through the fitted homography, and ranked by physical coverage,
    chessboard parity and fit quality.
    """
    eligible = _prepare_lattice_candidates(found, aspect_range)
    seeds = [index for index in eligible if found[index]["seed"]]
    if not seeds:
        return {}
    if spec.short_is_x:
        short_ratio, long_ratio = 1 / spec.fill_x, 1 / spec.fill_y
    else:
        short_ratio, long_ratio = 1 / spec.fill_y, 1 / spec.fill_x
    centers = np.array([rect["center"] for rect in found])

    hypotheses = []
    seen = set()
    for start in seeds:
        walked = _walk_from(
            start, found, eligible, short_ratio, long_ratio, centers,
            neighbour_hops)
        identity = frozenset(walked)
        if len(walked) < 4 or identity in seen:
            continue
        seen.add(identity)
        recovered = _recover_lattice(
            walked, found, eligible, spec, recovery_fill_range)
        matrix, mean_error, _max_error = _fit(recovered, found, lambda _index: True)
        if matrix is None:
            continue
        seed_count = sum(found[index]["seed"] for index in recovered)
        score = (len(recovered), _parity_agreement(recovered, found),
                 seed_count, -mean_error)
        hypotheses.append((score, recovered))
    return max(hypotheses, key=lambda item: item[0])[1] if hypotheses else {}


def _fit(coords, found, keep):
    src = np.float32([coords[i] for i in coords if keep(i)])
    dst = np.float32([found[i]["center"] for i in coords if keep(i)])
    if len(src) < 4:
        return None, 0.0, 0.0
    matrix, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if matrix is None:
        return None, 0.0, 0.0
    projected = cv2.perspectiveTransform(src.reshape(-1, 1, 2), matrix).reshape(-1, 2)
    error = np.linalg.norm(projected - dst, axis=1)
    return matrix, float(error.mean()), float(error.max())


def _score_fullness(coords, found, matrix, spec, image_size=None,
                    fill_range=(FULL_CELL_FILL, MAX_FULL_CELL_FILL),
                    edge_margin=DEFAULT_EDGE_MARGIN):
    """Mark each assigned rectangle full or partial against the fitted lattice.

    Local by construction: the predicted footprint at one corner of a tilted
    sheet is smaller than at the other, and comparing each block only with its
    own prediction is what lets a single threshold work across the frame.

    When ``image_size`` is given, a cell whose *full* projected footprint comes
    within ``edge_margin`` of its own size of the frame border - or crosses it -
    is flagged ``edge_clipped`` and cannot be full. That is stricter than the
    ``clipped`` flag from :func:`_components`, which only fires once the observed
    contour itself runs off the array.
    """
    half = np.float32([[-spec.fill_x / 2, -spec.fill_y / 2],
                       [spec.fill_x / 2, -spec.fill_y / 2],
                       [spec.fill_x / 2, spec.fill_y / 2],
                       [-spec.fill_x / 2, spec.fill_y / 2]])
    cell_box = np.float32([[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]])
    if not spec.short_is_x:
        half = half[:, ::-1].copy()
        cell_box = cell_box[:, ::-1].copy()
    check_edges = image_size is not None and edge_margin > 0
    if check_edges:
        width, height = image_size
    for index, (i, j) in coords.items():
        quad = cv2.perspectiveTransform(
            (half + np.float32([i, j])).reshape(-1, 1, 2), matrix).reshape(-1, 2)
        predicted = abs(cv2.contourArea(quad.astype(np.float32)))
        rect = found[index]
        rect["fill"] = rect["area"] / predicted if predicted > 0 else 0.0

        edge_clipped = False
        if check_edges:
            cq = cv2.perspectiveTransform(
                (cell_box + np.float32([i, j])).reshape(-1, 1, 2),
                matrix).reshape(-1, 2)
            margin_x = edge_margin * (cq[:, 0].max() - cq[:, 0].min())
            margin_y = edge_margin * (cq[:, 1].max() - cq[:, 1].min())
            edge_clipped = bool(
                cq[:, 0].min() < margin_x or cq[:, 1].min() < margin_y
                or cq[:, 0].max() > width - margin_x
                or cq[:, 1].max() > height - margin_y)
        rect["edge_clipped"] = edge_clipped
        rect["full"] = (fill_range[0] <= rect["fill"] <= fill_range[1]
                        and not rect["clipped"] and not edge_clipped)


def _largest_solid_block(full):
    """Biggest all-full axis-aligned rectangle in the lattice, as (di, dj).

    The bounding box of the whole cells is not the useful number: a cable lying
    across the sheet, or a frame edge clipping one row, leaves a bounding box
    that looks big enough and a solid block that is not. Reporting both is what
    turns "cannot hold the grid" into something an operator can act on.
    """
    if not full:
        return (0, 0)
    i_values = sorted({key[0] for key in full})
    j_values = sorted({key[1] for key in full})
    best = (0, 0)
    # Heights of the run of full cells ending at each (i, j), then the standard
    # largest-rectangle-in-histogram scan across each row.
    heights = {}
    for i in i_values:
        for j in j_values:
            heights[(i, j)] = (heights.get((i - 1, j), 0) + 1) if (i, j) in full else 0
        stack = []
        for index, j in enumerate(j_values + [None]):
            height = 0 if j is None else heights[(i, j)]
            start = index
            while stack and stack[-1][1] >= height:
                start, tall = stack.pop()
                if tall * (index - start) > best[0] * best[1]:
                    best = (tall, index - start)
            stack.append((start, height))
    return best


def _predicted_ink_cells(coords, found, matrix, spec, green, magenta):
    """Confirm weak cells from pixels without letting them bend the fit.

    The fitted lattice comes exclusively from geometrically whole contours.
    Here it is used as a measuring stencil over the two colour masks.  This
    recovers underlit/fragmented ink, while a paper-coloured occluder contributes
    no expected-colour pixels and therefore remains a real hole.
    """
    full = {coords[index] for index in coords if found[index]["full"]}
    if not full:
        return set()

    even_green = sum(
        (((i + j) % 2 == 0) == (found[index]["color"] == "green"))
        for index, (i, j) in coords.items()
        if found[index]["full"]
    ) >= len(full) / 2
    i_values = [key[0] for key in full]
    j_values = [key[1] for key in full]
    half = np.float32([
        [-spec.fill_x / 2, -spec.fill_y / 2],
        [spec.fill_x / 2, -spec.fill_y / 2],
        [spec.fill_x / 2, spec.fill_y / 2],
        [-spec.fill_x / 2, spec.fill_y / 2],
    ])
    if not spec.short_is_x:
        half = half[:, ::-1].copy()

    supported = set(full)
    height, width = green.shape
    for i in range(min(i_values), max(i_values) + 1):
        for j in range(min(j_values), max(j_values) + 1):
            key = (i, j)
            if key in supported:
                continue
            quad = cv2.perspectiveTransform(
                (half + np.float32(key)).reshape(-1, 1, 2), matrix
            ).reshape(-1, 2)
            x, y, w, h = cv2.boundingRect(quad.astype(np.float32))
            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(width, x + w), min(height, y + h)
            if x0 >= x1 or y0 >= y1:
                continue
            stencil = np.zeros((y1 - y0, x1 - x0), np.uint8)
            local_quad = np.rint(quad - np.float32([x0, y0])).astype(np.int32)
            cv2.fillConvexPoly(stencil, local_quad, 1)
            footprint = int(np.count_nonzero(stencil))
            if footprint == 0:
                continue
            expected_green = (((i + j) % 2 == 0) == even_green)
            ink = green if expected_green else magenta
            coverage = np.count_nonzero(
                ink[y0:y1, x0:x1] & stencil.astype(bool)) / footprint
            if coverage >= MIN_PREDICTED_INK_COVERAGE:
                supported.add(key)
    return supported


def _choose_windows(coords, found, need_i, need_j, image_size, matrix,
                    observed_cells=None):
    """Return every strongly supported mode-sized window in the fitted lattice.

    An oversized physical sheet contains more than one overlapping copy of the
    mode's coordinate map.  The larger fitted lattice supplies the geometry and
    each candidate window supplies its own coverage: a window needs at least
    95% physical coverage, at most one missing observation per row and column,
    and observations on every boundary.

    Every window that clears those gates is returned, swept across BOTH axes -
    not just short-axis shifts off one anchored long edge - so the operator can
    pick any sub-grid of an oversized sheet.  They are ordered by the distance
    from image bottom-left to the window corner nearest it, so index 0 stays the
    bottom-left-most choice the single-window callers have always taken, and the
    later indices are the shifted alternatives.
    """
    full = {coords[i]: i for i in coords if found[i]["full"]}
    if not full:
        return []
    observed_cells = set(full) if observed_cells is None else set(observed_cells)
    width, height = image_size
    bottom_left = np.array([0.0, height], dtype=float)
    i_values = [key[0] for key in full]
    j_values = [key[1] for key in full]

    minimum = math.ceil(MIN_WINDOW_COVERAGE * need_i * need_j - 1e-9)
    choices = []
    for i0 in range(min(i_values), max(i_values) - need_i + 2):
        for j0 in range(min(j_values), max(j_values) - need_j + 2):
            block = [(i0 + di, j0 + dj)
                     for di in range(need_i) for dj in range(need_j)]
            observed = sum(key in observed_cells for key in block)
            if observed < minimum:
                continue

            # Missing cells may be isolated shadow failures, never an absent
            # strip.  Requiring all rows/columns and nearly all of each makes a
            # regular patch of scene clutter unable to borrow the lattice fit.
            row_counts = [sum((i0 + di, j0 + dj) in observed_cells
                              for di in range(need_i))
                          for dj in range(need_j)]
            col_counts = [sum((i0 + di, j0 + dj) in observed_cells
                              for dj in range(need_j))
                          for di in range(need_i)]
            if (min(row_counts) < need_i - 1
                    or min(col_counts) < need_j - 1):
                continue

            corners = ((i0, j0), (i0 + need_i - 1, j0),
                       (i0, j0 + need_j - 1),
                       (i0 + need_i - 1, j0 + need_j - 1))
            # All corners are projectable even when the physical ink in one was
            # underlit; the homography came from the larger accepted lattice.
            projected = cv2.perspectiveTransform(
                np.float32(corners).reshape(-1, 1, 2),
                matrix,
            ).reshape(-1, 2)
            corner_index = int(np.argmin(np.linalg.norm(projected - bottom_left,
                                                         axis=1)))
            corner = corners[corner_index]
            distance = float(np.linalg.norm(projected[corner_index] - bottom_left))
            choices.append((distance, -observed, (i0, j0), corner, observed))

    choices.sort(key=lambda item: (item[0], item[1], item[2]))
    return [(origin, corner, observed)
            for _distance, _negative_observed, origin, corner, observed in choices]


def _choose_window(coords, found, need_i, need_j, image_size):
    """Compatibility helper returning the first candidate, when one exists."""
    matrix, _mean, _maximum = _fit(
        coords, found, lambda index: found[index]["full"])
    if matrix is None:
        return None
    choices = _choose_windows(coords, found, need_i, need_j, image_size, matrix)
    return choices[0][:2] if choices else None


def _choose_evidence_window(coords, found, need_i, need_j, image_size, matrix, spec):
    """Choose a 10x6 window despite holes caused by a known occluder.

    This is intentionally only for the evidence collector.  Unlike
    :func:`_choose_window`, it does not claim that every cell in the selected
    window was measured; it merely establishes a stable ``[0,0]`` convention
    so individually verified cells from several frames can be pooled.  The
    collector later requires broad edge/corner coverage before it can save.
    """
    full = {coords[i]: i for i in coords if found[i]["full"]}
    minimum_cells = min_evidence_frame_cells(spec)
    if len(full) < minimum_cells:
        return None
    i_values = [key[0] for key in full]
    j_values = [key[1] for key in full]
    width, height = image_size
    bottom_left = np.array([0.0, height], dtype=float)
    best = None
    # A single gantry position can leave only the upper or lower part of the
    # selected grid connected.  Let this *temporary* window extend around that
    # component so its cells still acquire stable image-bottom-left indices.
    # It is not a calibration permission: PaperGridEvidence rejects saving
    # until later accepted frames physically observe every boundary.
    for i0 in range(min(i_values) - need_i + 1, max(i_values) + 1):
        for j0 in range(min(j_values) - need_j + 1, max(j_values) + 1):
            inside = [key for key in full
                      if i0 <= key[0] < i0 + need_i and j0 <= key[1] < j0 + need_j]
            if len(inside) < minimum_cells:
                continue
            corners = ((i0, j0), (i0 + need_i - 1, j0),
                       (i0, j0 + need_j - 1), (i0 + need_i - 1, j0 + need_j - 1))
            projected = cv2.perspectiveTransform(
                np.float32(corners).reshape(-1, 1, 2), matrix
            ).reshape(-1, 2)
            corner = corners[int(np.argmin(np.linalg.norm(projected - bottom_left,
                                                            axis=1)))]
            distance = float(np.min(np.linalg.norm(projected - bottom_left, axis=1)))
            # Keep as many physical observations as possible; this is the
            # point of evidence mode.  Bottom-left breaks ties, retaining R4's
            # deterministic origin convention for an oversized sheet.
            score = (-len(inside), distance, i0, j0)
            if best is None or score < best[0]:
                best = (score, (i0, j0), corner)
    if best is None:
        return None
    return best[1], best[2]


def _window_transform(origin, corner, need_i, need_j, spec):
    """Matrix taking ``[col,row,1]`` to lattice ``[i,j,1]``.

    ``corner`` is the lattice index of the window corner chosen as ``[0,0]``,
    so the signs fall out of which corner won rather than out of a guess about
    the camera's mounting.
    """
    i0, j0 = origin
    ci, cj = corner
    sign_i = 1 if ci == i0 else -1
    sign_j = 1 if cj == j0 else -1
    # Columns follow whichever lattice axis carries the machine's X side.
    if spec.short_is_x:
        col_axis, row_axis = (sign_i, 0), (0, sign_j)
    else:
        col_axis, row_axis = (0, sign_j), (sign_i, 0)
    return np.array([
        [col_axis[0], row_axis[0], ci],
        [col_axis[1], row_axis[1], cj],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)


def detect_color_grids(frame: np.ndarray, spec: ColorGridSpec | None = None, *,
                       process_width: int = DEFAULT_PROCESS_WIDTH,
                       min_area: int = MIN_COMPONENT_AREA,
                       min_saturation: int = MIN_SATURATION,
                       min_value: int = MIN_VALUE,
                       green_hue=GREEN_HUE,
                       magenta_hue=MAGENTA_HUE,
                       use_opponent: bool = True,
                       component_close: int = 0,
                       lattice_aspect_range=LATTICE_ASPECT_RANGE,
                       full_fill_range=(FULL_CELL_FILL, MAX_FULL_CELL_FILL),
                       recovery_fill_range=RECOVERY_FILL_RANGE,
                       neighbour_hops=(1,),
                       balance: bool = True,
                       flatten: bool = False,
                       channel_order: bool = False,
                       edge_margin: float = DEFAULT_EDGE_MARGIN,
                       max_windows: int = MAX_WINDOWS,
                       evidence: bool = False) -> tuple[ColorGridCalibration, ...]:
    """Find every strongly supported grid window in ``frame``.

    Raises :class:`ColorGridError` with a sentence an operator can act on when
    the sheet is missing, cropped, or too small to hold the whole grid. It never
    returns a partial or approximate result: a wrong calibration written to disk
    is worse than no calibration.  Multiple overlapping windows are ordered by
    proximity to image bottom-left, so index zero is the absolute-left choice in
    the normal rig view and later indices are the shifted alternatives.
    """
    spec = spec or ColorGridSpec()
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        raise ColorGridError("a three-channel BGR frame is required")
    height, width = frame.shape[:2]
    metrics = ColorGridMetrics(input_size=(width, height))

    scale = 1.0
    working = frame
    if process_width and width > process_width:
        scale = process_width / width
        working = cv2.resize(frame, (process_width, round(height * scale)),
                             interpolation=cv2.INTER_AREA)
    work_size = working.shape[1::-1]
    metrics.processing_size = work_size

    green, magenta = color_masks(working, min_saturation=min_saturation,
                                 min_value=min_value, green_hue=green_hue,
                                 magenta_hue=magenta_hue,
                                 use_opponent=use_opponent, balance=balance,
                                 flatten=flatten, channel_order=channel_order)
    close_size = round(component_close * scale) if component_close else 0
    found = _components(green, magenta, min_area * scale * scale, work_size,
                        close_size=close_size)
    metrics.components = len(found)

    def boxes(subset=None):
        source = found if subset is None else [found[i] for i in subset]
        return [np.asarray(rect["box"], dtype=np.float32) / scale for rect in source]

    # Strong contours only establish the lattice; weak expected-colour pixels
    # can confirm the rest after that lattice is fitted.  Requiring one strong
    # component per final cell here made the later recovery stage unreachable
    # on otherwise obvious, unevenly lit sheets.
    required_components = min_evidence_frame_cells(spec)
    if len(found) < required_components:
        needed = f"lattice fit needs at least {required_components}"
        raise ColorGridError(
            f"only {len(found)} coloured blocks visible; the {needed}"
            + (". Is the sheet in frame, and is the camera's white balance sane?"
               if len(found) < 8 else ""),
            stage="segment", candidates=boxes())

    if (not neighbour_hops or any(int(hop) != hop or hop < 1
                                  for hop in neighbour_hops)):
        raise ValueError("neighbour_hops must contain positive integers")
    coords = _walk_lattice(
        found, spec, lattice_aspect_range, recovery_fill_range,
        tuple(int(hop) for hop in neighbour_hops))
    metrics.assigned = len(coords)
    if len(coords) < 4:
        raise ColorGridError(
            f"{len(found)} coloured blocks found but they do not form a regular "
            f"lattice; the sheet may be folded, or something else in view is the "
            f"same colour as the ink",
            stage="lattice", candidates=boxes())

    matrix, mean_error, max_error = _fit(coords, found, lambda i: found[i]["seed"])
    if matrix is None:
        raise ColorGridError("not enough whole blocks to fit the sheet",
                             stage="fit", candidates=boxes(),
                             lattice=boxes(coords))
    # First pass has no edge check: the refit below needs whole-cell anchors,
    # and an aggressive margin on a still-rough matrix could starve it.
    _score_fullness(coords, found, matrix, spec, None, full_fill_range,
                    edge_margin=0.0)
    matrix, mean_error, max_error = _fit(coords, found, lambda i: found[i]["full"])
    if matrix is None:
        raise ColorGridError(
            "no whole cells: every block in view is clipped by the paper edge, "
            "the frame edge, or something lying across the sheet",
            stage="fit", candidates=boxes(), lattice=boxes(coords))
    # Second pass, on the refined matrix, is the authoritative one: it drives
    # _choose_windows, the ink-recovery stencil, the metrics and every returned
    # cell. The frame-border margin belongs here.
    _score_fullness(coords, found, matrix, spec, work_size, full_fill_range,
                    edge_margin=edge_margin)

    metrics.residual_px = mean_error / scale
    metrics.max_residual_px = max_error / scale
    metrics.full_cells = sum(1 for i in coords if found[i]["full"])
    full_coords = [coords[i] for i in coords if found[i]["full"]]
    if full_coords:
        i_values = [c[0] for c in full_coords]
        j_values = [c[1] for c in full_coords]
        metrics.lattice_shape = (max(i_values) - min(i_values) + 1,
                                 max(j_values) - min(j_values) + 1)
    full_indices = [i for i in coords if found[i]["full"]]
    measured = [found[i] for i in full_indices] or [found[i] for i in coords]
    long_med = float(np.median([r["long_len"] for r in measured]))
    short_med = float(np.median([r["short_len"] for r in measured]))
    metrics.measured_aspect = long_med / short_med if short_med else 0.0

    # Printed cells alternate colour, so (i + j) parity is a free check that the
    # lattice indices are consistent rather than merely self-consistent.
    if metrics.full_cells:
        parities = [((coords[i][0] + coords[i][1]) % 2, found[i]["color"])
                    for i in coords if found[i]["full"]]
        agree = sum(1 for p, c in parities if (p == 0) == (c == "green"))
        metrics.parity_agreement = max(agree, len(parities) - agree) / len(parities)

    expected_aspect = max(spec.block_x_cm, spec.block_y_cm) / min(
        spec.block_x_cm, spec.block_y_cm)
    aspect_low = expected_aspect * VALID_ASPECT_FACTOR[0]
    aspect_high = expected_aspect * VALID_ASPECT_FACTOR[1]
    quality_errors = []
    if metrics.parity_agreement < MIN_PARITY_AGREEMENT:
        quality_errors.append(
            f"colour parity is {metrics.parity_agreement:.0%}, below the "
            f"{MIN_PARITY_AGREEMENT:.0%} safety threshold")
    if not (aspect_low <= metrics.measured_aspect <= aspect_high):
        quality_errors.append(
            f"measured cell aspect {metrics.measured_aspect:.2f} does not match "
            f"the printed {expected_aspect:.2f}")
    if short_med > 0:
        if mean_error > MAX_MEAN_RESIDUAL_SHORT_SIDE * short_med:
            quality_errors.append(
                f"mean lattice residual {mean_error / scale:.2f} px is too large")
        if max_error > MAX_RESIDUAL_SHORT_SIDE * short_med:
            quality_errors.append(
                f"maximum lattice residual {max_error / scale:.2f} px is too large")
    if quality_errors:
        raise ColorGridError(
            "; ".join(quality_errors), stage="quality", candidates=boxes(),
            lattice=boxes(full_indices))

    need_i, need_j = spec.lattice_counts
    predicted_ink = _predicted_ink_cells(
        coords, found, matrix, spec, green, magenta)
    windows = _choose_windows(
        coords, found, need_i, need_j, work_size, matrix, predicted_ink)
    if max_windows and len(windows) > max_windows:
        windows = windows[:max_windows]
    if not windows and evidence:
        evidence_window = _choose_evidence_window(
            coords, found, need_i, need_j, work_size, matrix, spec)
        if evidence_window is not None:
            origin, corner = evidence_window
            observed = sum(
                found[index]["full"]
                for index, (i, j) in coords.items()
                if origin[0] <= i < origin[0] + need_i
                and origin[1] <= j < origin[1] + need_j
            )
            windows = [(origin, corner, observed)]
    if not windows:
        # Say which of the two failures this is. "Not enough cells in view" and
        # "enough cells but something punched holes in them" need opposite
        # responses from the operator, and the counts alone do not distinguish
        # them: the bounding spread can look ample while no solid block exists.
        solid = _largest_solid_block({coords[i] for i in coords if found[i]["full"]})
        short_side, long_side = ((spec.block_x_cm, spec.block_y_cm) if spec.short_is_x
                                 else (spec.block_y_cm, spec.block_x_cm))
        axes = (
            (solid[0], need_i, metrics.lattice_shape[0], f"{short_side:g} cm"),
            (solid[1], need_j, metrics.lattice_shape[1], f"{long_side:g} cm"),
        )
        lacking = [f"{have} whole cells along the {name} side where {want} are needed"
                   for have, want, _spread, name in axes if have < want]
        occluded = all(spread >= want for _have, want, spread, _name in axes)
        message = "; and ".join(lacking) or "the whole cells do not form a block"
        if occluded:
            message += (". The sheet is big enough in view, so the gaps are "
                        "holes: something is lying across it, or a row is clipped")
        else:
            message += ". Move the sheet or the camera so more of it is in view"
        message += (f". The selected {spec.mode} layout needs a "
                    f"{spec.cols}x{spec.rows} coordinate map")
        raise ColorGridError(
            message, stage="window", candidates=boxes(),
            lattice=boxes(i for i in coords if found[i]["full"]))
    unscale = np.diag([1 / scale, 1 / scale, 1.0])
    calibrations = []
    for window_index, (origin, corner, observed) in enumerate(windows):
        transform = _window_transform(origin, corner, need_i, need_j, spec)
        cell_matrix = unscale @ matrix @ transform
        inverse_transform = np.linalg.inv(transform)

        cells = []
        for index, (i, j) in coords.items():
            rect = found[index]
            grid_ij = inverse_transform @ np.array([i, j, 1.0])
            col, row = int(round(grid_ij[0])), int(round(grid_ij[1]))
            inside = 0 <= col < spec.cols and 0 <= row < spec.rows
            cells.append(PrintedCell(
                lattice=(i, j),
                center=tuple(np.asarray(rect["center"]) / scale),
                quad=np.asarray(rect["box"], dtype=np.float32) / scale,
                color=rect["color"],
                area=rect["area"] / (scale * scale),
                fill=rect.get("fill", 0.0),
                full=bool(rect.get("full", False)),
                cell=(col, row) if inside and rect.get("full") else None,
                edge_clipped=bool(rect.get("edge_clipped", False)),
            ))
        cells.sort(key=lambda c: (c.cell is None, c.cell or (0, 0)))
        candidate_metrics = replace(
            metrics,
            window_candidates=len(windows),
            window_index=window_index,
            window_observed=observed,
        )
        calibrations.append(ColorGridCalibration(
            spec=spec, homography=cell_matrix, cells=cells,
            metrics=candidate_metrics,
        ))
    return tuple(calibrations)


def detect_color_grid(frame: np.ndarray, spec: ColorGridSpec | None = None, *,
                      process_width: int = DEFAULT_PROCESS_WIDTH,
                      min_area: int = MIN_COMPONENT_AREA,
                      min_saturation: int = MIN_SATURATION,
                      min_value: int = MIN_VALUE,
                      green_hue=GREEN_HUE,
                      magenta_hue=MAGENTA_HUE,
                      use_opponent: bool = True,
                      component_close: int = 0,
                      lattice_aspect_range=LATTICE_ASPECT_RANGE,
                      full_fill_range=(FULL_CELL_FILL, MAX_FULL_CELL_FILL),
                      recovery_fill_range=RECOVERY_FILL_RANGE,
                      neighbour_hops=(1,),
                      balance: bool = True,
                      edge_margin: float = DEFAULT_EDGE_MARGIN,
                      max_windows: int = MAX_WINDOWS,
                      evidence: bool = False,
                      window_index: int = 0) -> ColorGridCalibration:
    """Find one printed-grid window, selected from all valid candidates.

    ``window_index=0`` preserves the historical image-bottom-left default.
    Interactive callers should expose the other indices rather than silently
    committing the first one.
    """
    calibrations = detect_color_grids(
        frame, spec, process_width=process_width, min_area=min_area,
        min_saturation=min_saturation, min_value=min_value,
        green_hue=green_hue, magenta_hue=magenta_hue,
        use_opponent=use_opponent, component_close=component_close,
        lattice_aspect_range=lattice_aspect_range,
        full_fill_range=full_fill_range,
        recovery_fill_range=recovery_fill_range,
        neighbour_hops=neighbour_hops, balance=balance,
        edge_margin=edge_margin, max_windows=max_windows,
        evidence=evidence,
    )
    if not 0 <= window_index < len(calibrations):
        raise ColorGridError(
            f"grid window {window_index + 1} was requested but only "
            f"{len(calibrations)} candidate(s) were detected",
            stage="selection",
        )
    return calibrations[window_index]

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
2. Each connected component becomes a rotated rectangle. The median long-axis
   direction (circular, mod 180 degrees) fixes a global sense for "along the
   7.5 cm side", so neighbouring cells cannot disagree about which way is up.
3. A breadth-first walk hops from cell to cell using *that cell's own* measured
   size times the known pitch/block ratio, and hands out integer lattice
   indices. Only near-median cells are allowed to propagate the walk, so a
   clipped block cannot steer it. Local hops are what makes this survive
   perspective: nothing ever compares a cell at one edge of the frame with a
   cell at the other.
4. A homography is fitted from integer lattice indices to cell centres, every
   cell is re-scored against it, and the fit is repeated on the survivors.

Steps 3 and 4 are the whole trick. Residuals on the two supplied captures are
around one pixel at 2048 px wide, including the badly tilted one.

Which axis is X
---------------
Never from the image. The ``2.2 cm`` side and the ``7.5 cm`` side are 3.4:1
apart, so the axis with the shorter pitch is the machine's X and the other is
Y, whichever way round the sheet was photographed. That much is orientation
free and is what makes the module reusable when the camera is remounted.

What is NOT handled yet is the sheet laid out so the machine's own X runs along
the 7.5 cm cell side — a genuinely rotated *machine*, not a rotated camera.
:data:`SUPPORTED_LAYOUT` names the one supported layout and
``detect_color_grid`` refuses anything else rather than guessing. See
``plans/printed-color-grid.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import cv2
import numpy as np

from rig.config import load as load_rig_config


# The sheet is printed at the rig's own block geometry, so the ratio between a
# block and its pitch is fixed and known. Everything below is expressed in
# those ratios rather than in centimetres, which keeps the detector working at
# any camera distance without a scale calibration.
SUPPORTED_LAYOUT = "y-along-block-length"

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

# The bright quantile that :func:`white_balance` drives to neutral. High enough
# to land on the sheet's white paper, low enough not to chase one specular
# highlight. Estimated on a subsampled frame; the scaling is applied to all of it.
WHITE_PATCH_QUANTILE = 0.92
_BALANCE_STRIDE = 8
_BALANCE_DEADBAND = 0.02        # below this the cast is not worth a pass over the frame

# A block whose observed area is at least this fraction of the area the lattice
# predicts for it is whole. The captures put real cells at 0.93-1.03 and every
# clipped one below 0.7, so the cutoff is nowhere near either population.
FULL_CELL_FILL = 0.80

# Seeds for the lattice walk must be this close to the median cell size. Only
# used to pick cells that are allowed to *propagate*; the real full/partial
# decision is made later against the fitted lattice.
SEED_SIZE_TOLERANCE = 0.20

# How far from the predicted position a neighbour may sit, as a fraction of the
# smaller pitch. Generous enough for a tilted sheet, far below half a pitch so
# it can never grab the cell after next.
NEIGHBOUR_TOLERANCE = 0.40

# Working width for detection. The homography is fitted over ~100 cells, so
# sub-pixel loss from the downscale averages out, and this keeps a live overlay
# affordable on the Pi. Pass ``process_width=0`` to work at full resolution.
DEFAULT_PROCESS_WIDTH = 1024

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

    def __init__(self, message, *, stage="detect", candidates=(), lattice=()):
        super().__init__(message)
        self.stage = stage
        self.candidates = tuple(candidates)   # Nx4x2 boxes, input-frame pixels
        self.lattice = tuple(lattice)         # the subset that joined a lattice


@dataclass(frozen=True)
class ColorGridSpec:
    """The printed sheet's geometry, which is the rig's block geometry.

    ``cols``/``rows`` are the *complete* coordinate map including zero — 10 x 6
    for the shipped 9 x 5 positive grid — because the sheet prints a real block
    at every coordinate, coordinate zero included. That is the one place the
    paper and the firmware disagree, and it is why the mapping back onto the
    machine envelope is an explicit convention rather than an assumption. See
    :meth:`ColorGridCalibration.workspace_corners`.
    """

    cols: int = 10
    rows: int = 6
    block_x_cm: float = 2.2
    block_y_cm: float = 7.5
    gap_x_cm: float = 0.5
    gap_y_cm: float = 0.5

    @classmethod
    def from_config(cls, cfg: dict | None = None) -> "ColorGridSpec":
        """Build from ``config/rig.json``, adding coordinate zero to the counts."""
        cfg = cfg if cfg is not None else load_rig_config()
        grid = cfg["grid"]
        return cls(
            cols=int(grid["cols"]) + 1,
            rows=int(grid["rows"]) + 1,
            block_x_cm=float(grid["block_width_cm"]),
            block_y_cm=float(grid["block_length_cm"]),
            gap_x_cm=float(grid["gap_x_cm"]),
            gap_y_cm=float(grid["gap_y_cm"]),
        )

    def __post_init__(self):
        values = (self.block_x_cm, self.block_y_cm, self.gap_x_cm, self.gap_y_cm)
        if not all(math.isfinite(v) and v > 0 for v in values[:2]):
            raise ValueError("printed block dimensions must be positive")
        if not all(math.isfinite(v) and v >= 0 for v in values[2:]):
            raise ValueError("printed gaps must be finite and non-negative")
        if self.cols < 2 or self.rows < 2:
            raise ValueError("the printed grid needs at least 2x2 coordinates")
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
        """Block as a fraction of pitch along X: 2.2 / 2.7."""
        return self.block_x_cm / self.pitch_x_cm

    @property
    def fill_y(self) -> float:
        """Block as a fraction of pitch along Y: 7.5 / 8.0."""
        return self.block_y_cm / self.pitch_y_cm

    @property
    def short_is_x(self) -> bool:
        return self.block_x_cm < self.block_y_cm

    def describe(self) -> str:
        return (f"{self.cols}x{self.rows} printed coordinates, "
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
    layout: str = SUPPORTED_LAYOUT

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
            # Printed cell c (c >= 1) is made to coincide with firmware cell c.
            x0 = self.spec.pitch_x_cm - grid.x_start_cm
            y0 = self.spec.pitch_y_cm - grid.y_start_cm
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
        pairs = ((self.spec.block_x_cm, grid.block_width_cm, "block X"),
                 (self.spec.block_y_cm, grid.block_length_cm, "block Y"),
                 (self.spec.gap_x_cm, grid.gap_x_cm, "gap X"),
                 (self.spec.gap_y_cm, grid.gap_y_cm, "gap Y"))
        for printed, machine, name in pairs:
            if abs(printed - machine) > 1e-6:
                raise ColorGridError(
                    f"the sheet was detected as {name} {printed:g} cm but the rig "
                    f"config says {machine:g} cm; reprint the sheet or fix rig.json")
        if (self.spec.cols, self.spec.rows) != (grid.cols + 1, grid.rows + 1):
            raise ColorGridError(
                f"the sheet grid is {self.spec.cols}x{self.spec.rows} coordinates "
                f"but the rig config asks for {grid.cols + 1}x{grid.rows + 1}")

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
                f"{m.full_cells} full cells of {m.components} found, residual "
                f"{m.residual_px:.2f} px (max {m.max_residual_px:.2f}), "
                f"parity {m.parity_agreement * 100:.0f}%")


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


def color_masks(frame: np.ndarray, *, min_saturation: int = MIN_SATURATION,
                min_value: int = MIN_VALUE,
                balance: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Return the (green, magenta) boolean masks for one BGR frame.

    Hue plus a saturation floor, not brightness: the two inks stay a long way
    apart in hue under any light, while their brightness does not. ``balance``
    neutralises the camera's colour cast first — see :func:`white_balance` for
    why that is not optional in practice.
    """
    if balance:
        frame = white_balance(frame)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hue, sat, val = cv2.split(hsv)
    strong = (sat >= min_saturation) & (val >= min_value)
    green = (hue >= GREEN_HUE[0]) & (hue <= GREEN_HUE[1]) & strong
    magenta = (hue >= MAGENTA_HUE[0]) & (hue <= MAGENTA_HUE[1]) & strong
    return green, magenta


def _components(green, magenta, min_area, size):
    """Rotated rectangles for every colour blob, with a global axis sense."""
    mask = cv2.morphologyEx((green | magenta).astype(np.uint8) * 255,
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
        x, y = int(np.clip(center[0], 0, width - 1)), int(np.clip(center[1], 0, height - 1))
        found.append({
            "center": center, "box": box, "area": area,
            "long_axis": long_axis, "long_len": long_len,
            "short_axis": short_axis, "short_len": short_len,
            "color": "green" if green[y, x] else "magenta",
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


def _walk_lattice(found, spec):
    """Hand out integer lattice indices by hopping between neighbours.

    Index ``i`` counts along the short cell side, ``j`` along the long one. Only
    near-median rectangles propagate the walk, and each hop is predicted from
    the size of the cell it starts at, so a tilted or mildly barrelled sheet
    never accumulates error across the frame.
    """
    long_med = float(np.median([r["long_len"] for r in found]))
    short_med = float(np.median([r["short_len"] for r in found]))
    for rect in found:
        rect["seed"] = (
            abs(rect["long_len"] - long_med) < SEED_SIZE_TOLERANCE * long_med
            and abs(rect["short_len"] - short_med) < SEED_SIZE_TOLERANCE * short_med
            and not rect["clipped"]
        )
    if not any(r["seed"] for r in found):
        return {}

    # Pitch as a multiple of the observed block, per axis.
    if spec.short_is_x:
        short_ratio, long_ratio = 1 / spec.fill_x, 1 / spec.fill_y
    else:
        short_ratio, long_ratio = 1 / spec.fill_y, 1 / spec.fill_x

    centers = np.array([r["center"] for r in found])
    middle = centers.mean(axis=0)
    start = min((i for i, r in enumerate(found) if r["seed"]),
                key=lambda i: float(np.linalg.norm(centers[i] - middle)))

    coords = {start: (0, 0)}
    taken = {(0, 0): start}
    queue = [start]
    while queue:
        index = queue.pop(0)
        rect = found[index]
        i, j = coords[index]
        step_short = rect["short_len"] * short_ratio
        step_long = rect["long_len"] * long_ratio
        hops = (((1, 0), rect["short_axis"] * step_short),
                ((-1, 0), -rect["short_axis"] * step_short),
                ((0, 1), rect["long_axis"] * step_long),
                ((0, -1), -rect["long_axis"] * step_long))
        for (di, dj), offset in hops:
            target = (i + di, j + dj)
            if target in taken:
                continue
            distance = np.linalg.norm(centers - (rect["center"] + offset), axis=1)
            distance[list(coords)] = np.inf
            best = int(np.argmin(distance))
            if distance[best] > NEIGHBOUR_TOLERANCE * min(step_short, step_long):
                continue
            coords[best] = target
            taken[target] = best
            if found[best]["seed"]:
                queue.append(best)
    return coords


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


def _score_fullness(coords, found, matrix, spec):
    """Mark each assigned rectangle full or partial against the fitted lattice.

    Local by construction: the predicted footprint at one corner of a tilted
    sheet is smaller than at the other, and comparing each block only with its
    own prediction is what lets a single threshold work across the frame.
    """
    half = np.float32([[-spec.fill_x / 2, -spec.fill_y / 2],
                       [spec.fill_x / 2, -spec.fill_y / 2],
                       [spec.fill_x / 2, spec.fill_y / 2],
                       [-spec.fill_x / 2, spec.fill_y / 2]])
    if not spec.short_is_x:
        half = half[:, ::-1].copy()
    for index, (i, j) in coords.items():
        quad = cv2.perspectiveTransform(
            (half + np.float32([i, j])).reshape(-1, 1, 2), matrix).reshape(-1, 2)
        predicted = abs(cv2.contourArea(quad.astype(np.float32)))
        rect = found[index]
        rect["fill"] = rect["area"] / predicted if predicted > 0 else 0.0
        rect["full"] = rect["fill"] >= FULL_CELL_FILL and not rect["clipped"]


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


def _choose_window(coords, found, need_i, need_j, image_size):
    """Pick the need_i x need_j block of full cells nearest the image's bottom-left.

    The sheet is bigger than the machine's grid, so a window has to be chosen.
    Anchoring it at the bottom-left of the picture is what makes ``[0,0]`` land
    where the operator expects without another setting to get wrong.
    """
    full = {coords[i]: i for i in coords if found[i]["full"]}
    if not full:
        return None
    width, height = image_size
    bottom_left = np.array([0.0, height], dtype=float)

    best = None
    for (i0, j0) in full:
        block = [(i0 + di, j0 + dj) for di in range(need_i) for dj in range(need_j)]
        if any(key not in full for key in block):
            continue
        # Score by the corner of the candidate window that is nearest the
        # bottom-left of the frame; the winner is the window whose own corner
        # sits closest to it.
        corners = ((i0, j0), (i0 + need_i - 1, j0), (i0, j0 + need_j - 1),
                   (i0 + need_i - 1, j0 + need_j - 1))
        for corner in corners:
            distance = float(np.linalg.norm(
                np.asarray(found[full[corner]]["center"]) - bottom_left))
            if best is None or distance < best[0]:
                best = (distance, (i0, j0), corner)
    if best is None:
        return None
    _, origin, corner = best
    return origin, corner


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


def detect_color_grid(frame: np.ndarray, spec: ColorGridSpec | None = None, *,
                      process_width: int = DEFAULT_PROCESS_WIDTH,
                      min_area: int = MIN_COMPONENT_AREA,
                      min_saturation: int = MIN_SATURATION,
                      min_value: int = MIN_VALUE,
                      balance: bool = True) -> ColorGridCalibration:
    """Find the printed sheet in ``frame`` and fit a grid to it.

    Raises :class:`ColorGridError` with a sentence an operator can act on when
    the sheet is missing, cropped, or too small to hold the whole grid. It never
    returns a partial or approximate result: a wrong calibration written to disk
    is worse than no calibration, and the callers all have an existing map to
    fall back on.
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
                                 min_value=min_value, balance=balance)
    found = _components(green, magenta, min_area * scale * scale, work_size)
    metrics.components = len(found)

    def boxes(subset=None):
        source = found if subset is None else [found[i] for i in subset]
        return [np.asarray(rect["box"], dtype=np.float32) / scale for rect in source]

    if len(found) < spec.cols * spec.rows:
        raise ColorGridError(
            f"only {len(found)} coloured blocks visible; the "
            f"{spec.cols}x{spec.rows} grid needs at least {spec.cols * spec.rows}"
            + (". Is the sheet in frame, and is the camera's white balance sane?"
               if len(found) < 8 else ""),
            stage="segment", candidates=boxes())

    coords = _walk_lattice(found, spec)
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
    _score_fullness(coords, found, matrix, spec)
    matrix, mean_error, max_error = _fit(coords, found, lambda i: found[i]["full"])
    if matrix is None:
        raise ColorGridError(
            "no whole cells: every block in view is clipped by the paper edge, "
            "the frame edge, or something lying across the sheet",
            stage="fit", candidates=boxes(), lattice=boxes(coords))
    _score_fullness(coords, found, matrix, spec)

    metrics.residual_px = mean_error / scale
    metrics.max_residual_px = max_error / scale
    metrics.full_cells = sum(1 for i in coords if found[i]["full"])
    full_coords = [coords[i] for i in coords if found[i]["full"]]
    if full_coords:
        i_values = [c[0] for c in full_coords]
        j_values = [c[1] for c in full_coords]
        metrics.lattice_shape = (max(i_values) - min(i_values) + 1,
                                 max(j_values) - min(j_values) + 1)
    long_med = float(np.median([r["long_len"] for r in found]))
    short_med = float(np.median([r["short_len"] for r in found]))
    metrics.measured_aspect = long_med / short_med if short_med else 0.0

    # Printed cells alternate colour, so (i + j) parity is a free check that the
    # lattice indices are consistent rather than merely self-consistent.
    if metrics.full_cells:
        parities = [((coords[i][0] + coords[i][1]) % 2, found[i]["color"])
                    for i in coords if found[i]["full"]]
        agree = sum(1 for p, c in parities if (p == 0) == (c == "green"))
        metrics.parity_agreement = max(agree, len(parities) - agree) / len(parities)

    need_i, need_j = ((spec.cols, spec.rows) if spec.short_is_x
                      else (spec.rows, spec.cols))
    window = _choose_window(coords, found, need_i, need_j, work_size)
    if window is None:
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
        raise ColorGridError(
            message, stage="window", candidates=boxes(),
            lattice=boxes(i for i in coords if found[i]["full"]))
    origin, corner = window
    transform = _window_transform(origin, corner, need_i, need_j, spec)

    unscale = np.diag([1 / scale, 1 / scale, 1.0])
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
        ))
    cells.sort(key=lambda c: (c.cell is None, c.cell or (0, 0)))
    return ColorGridCalibration(spec=spec, homography=cell_matrix, cells=cells,
                                metrics=metrics)

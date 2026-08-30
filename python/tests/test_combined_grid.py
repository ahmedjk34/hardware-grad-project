#!/usr/bin/env python3
"""Regression checks for the one-page vertical/horizontal calibration target."""

from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.config import load as load_rig_config
from rig.grid import MachineGrid
from rig.workspace import WorkspaceMap
from vision.color_grid import ColorGridError, ColorGridSpec
from vision.combined_grid import (
    FIDUCIAL_BLOCK_X_CM,
    FIDUCIAL_BLOCK_Y_CM,
    FIDUCIAL_BOTTOM_CM,
    FIDUCIAL_COLS,
    FIDUCIAL_GAP_X_CM,
    FIDUCIAL_GAP_Y_CM,
    FIDUCIAL_LEFT_CM,
    FIDUCIAL_ROWS,
    PAGE_HEIGHT_CM,
    PAGE_WIDTH_CM,
    CombinedGridCalibration,
    PrintedGridEvidence,
    detect_combined_grids,
    detect_printed_grid,
)
from vision.color_grid_overlay import draw_color_grid


GREEN = (72, 124, 100)      # supplied artwork's muted olive, BGR
MAGENTA = (150, 72, 157)    # supplied artwork's muted purple, BGR
DARK_GREEN = (0, 85, 34)
DARK_MAGENTA = (128, 0, 128)
PAPER = (255, 255, 255)
BEIGE = (227, 227, 234)
PX_PER_CM = 12.0
failed = False


def check(name, condition, detail=""):
    global failed
    print(f"{'ok  ' if condition else 'FAIL'}  {name}"
          + (f": {detail}" if detail else ""))
    failed |= not condition


def render_target(warp=None, out_size=None, fade=0.0, encoding="combined",
                  beige_fade=0.0, missing_horizontal_center=False):
    width = round(PAGE_WIDTH_CM * PX_PER_CM)
    height = round(PAGE_HEIGHT_CM * PX_PER_CM)
    image = np.full((height, width, 3), PAPER, np.uint8)
    pitch_x = FIDUCIAL_BLOCK_X_CM + FIDUCIAL_GAP_X_CM
    pitch_y = FIDUCIAL_BLOCK_Y_CM + FIDUCIAL_GAP_Y_CM
    for row in range(FIDUCIAL_ROWS):
        for col in range(FIDUCIAL_COLS):
            x0 = FIDUCIAL_LEFT_CM + col * pitch_x
            y0 = FIDUCIAL_BOTTOM_CM + row * pitch_y
            x1 = x0 + FIDUCIAL_BLOCK_X_CM
            y1 = y0 + FIDUCIAL_BLOCK_Y_CM
            is_green = (col + row) % 2 == 0
            colour = GREEN if is_green else MAGENTA
            if fade:
                colour = tuple(round((1 - fade) * value + fade * paper)
                               for value, paper in zip(colour, PAPER))
            cv2.rectangle(
                image,
                (round(x0 * PX_PER_CM), height - round(y1 * PX_PER_CM)),
                (round(x1 * PX_PER_CM) - 1, height - round(y0 * PX_PER_CM) - 1),
                colour,
                -1,
            )
            stripe_x0 = x0 + 2.2
            stripe_x1 = stripe_x0 + 1.6
            stripe = ((DARK_GREEN if is_green else DARK_MAGENTA)
                      if encoding in ("vertical", "combined") else colour)
            cv2.rectangle(
                image,
                (round(stripe_x0 * PX_PER_CM), height - round(y1 * PX_PER_CM)),
                (round(stripe_x1 * PX_PER_CM) - 1,
                 height - round(y0 * PX_PER_CM) - 1),
                stripe,
                -1,
            )
            # Every other 1.6 cm row interval is an encoded horizontal band:
            # beige outer thirds and a white centre. The neighboring chromatic
            # rows are still required, so gray can never establish the target.
            if encoding in ("horizontal", "combined") and row % 2 == 0 \
                    and row + 1 < FIDUCIAL_ROWS:
                gap_y0 = y1
                gap_y1 = y0 + pitch_y
                beige = tuple(round((1 - beige_fade) * value
                                    + beige_fade * paper)
                              for value, paper in zip(BEIGE, PAPER))
                for gap_x0, gap_x1 in ((x0, x0 + 2.2),
                                       (x0 + 3.8, x1)):
                    # Erase a quarter of the difficult 1.6 cm beige middles.
                    # Other lanes establish the encoded row parity, after
                    # which opposite-colour end thirds may fill these blanks.
                    lane_beige = (PAPER if missing_horizontal_center
                                  and (col + row) % 4 == 0 else beige)
                    cv2.rectangle(
                        image,
                        (round(gap_x0 * PX_PER_CM),
                         height - round(gap_y1 * PX_PER_CM)),
                        (round(gap_x1 * PX_PER_CM) - 1,
                         height - round(gap_y0 * PX_PER_CM) - 1),
                        lane_beige,
                        -1,
                    )
    if warp is None:
        return image
    size = out_size or (width, height)
    return cv2.warpPerspective(image, warp, size, borderValue=PAPER)


rig_data = load_rig_config()
legacy = ColorGridSpec.from_config(rig_data, mode="vertical")
legacy_horizontal = ColorGridSpec.from_config(rig_data, mode="horizontal")

# The printable vector and detector constants are one physical contract.
asset = Path(__file__).resolve().parents[2] / "plans" / "assets" / \
    "combined-calibration-grid.svg"
root = ET.parse(asset).getroot()
namespace = {"svg": "http://www.w3.org/2000/svg"}
bars = [node for node in root.findall("svg:rect", namespace)
        if node.get("width") == "6" and node.get("height") == "2.2"]
beige_regions = [node for node in root.findall("svg:rect", namespace)
                 if node.get("width") == "2.2"
                 and node.get("height") == "1.6"]
check("canonical SVG is A2 landscape",
      root.get("width") == f"{PAGE_WIDTH_CM:g}cm"
      and root.get("height") == f"{PAGE_HEIGHT_CM:g}cm")
check("canonical SVG carries the detector's 8x10 lattice",
      len(bars) == FIDUCIAL_COLS * FIDUCIAL_ROWS, f"{len(bars)} bars")
check("canonical SVG carries 40 beige/white/beige horizontal bands",
      len(beige_regions) == 80, f"{len(beige_regions)} beige outer thirds")
check("canonical SVG retains the configured fiducial origin",
      np.isclose(min(float(node.get("x")) for node in bars), FIDUCIAL_LEFT_CM)
      and np.isclose(min(float(node.get("y")) for node in bars), PAGE_HEIGHT_CM - (
          FIDUCIAL_BOTTOM_CM
          + FIDUCIAL_ROWS * FIDUCIAL_BLOCK_Y_CM
          + (FIDUCIAL_ROWS - 1) * FIDUCIAL_GAP_Y_CM)))

image = render_target(encoding="combined")
found = detect_printed_grid(image, legacy, process_width=0)
check("combined target is selected before the legacy detector",
      isinstance(found, CombinedGridCalibration), found.describe())
check("all 80 chromatic fiducials are measured",
      len(found.found_cells) == 80 and found.metrics.parity_agreement == 1.0,
      found.describe())
check("combined synthetic target is reported as mixed",
      found.orientation == "mixed", found.describe())
check("160 distinct fiducials have exclusive three-part signatures",
      len(found.patterns) == 160
      and all(len(pattern.thirds) == 3 for pattern in found.patterns)
      and all(pattern.orientation in ("vertical", "horizontal", "unknown")
              for pattern in found.patterns)
      and found.orientation_votes == {
          "vertical": 80, "horizontal": 80, "ambiguous": 0},
      found.patterns[0].signature)
check("no physical fiducial can vote for both orientations",
      all(not (pattern.vertical_score >= 0.64
                   and pattern.horizontal_score >= 0.64)
              for pattern in found.patterns))
check("clear beige centers use primary horizontal detection",
      found.inferred_horizontal_cells == 0)

muted_beige = render_target(encoding="combined", beige_fade=0.70)
muted_fit = detect_printed_grid(
    muted_beige, legacy_horizontal, process_width=0)
check("primary detector keeps very muted beige outer thirds",
      muted_fit.orientation == "mixed"
      and muted_fit.orientation_votes["horizontal"] == 80
      and muted_fit.inferred_horizontal_cells == 0,
      muted_fit.describe())

# If the difficult 1.6 cm center becomes indistinguishable from its off-white
# neighbors, the two beige outer thirds plus alternating opposite-color rows
# reconstruct it. The annotation marks this H~ rather than pretending it was
# directly measured.
missing_centers = render_target(
    encoding="combined", beige_fade=0.35,
    missing_horizontal_center=True)
filled_fit = detect_printed_grid(
    missing_centers, legacy_horizontal, process_width=0)
inferred = filled_fit.inferred_horizontal_cells
check("horizontal center blanks are filled from outer thirds and neighbors",
      filled_fit.orientation == "mixed" and inferred >= 16
      and any(pattern.signature.startswith("H~:")
              for pattern in filled_fit.patterns),
      f"{inferred}/80 inferred; {filled_fit.describe()}")

# Single-layer variants make mode validation observable: a requested mode is
# accepted only if its own internal composition has sheet-level consensus.
vertical_only = render_target(encoding="vertical")
vertical_fit = detect_printed_grid(
    vertical_only, legacy, process_width=0)
check("vertical-only thirds pass vertical mode",
      vertical_fit.orientation == "vertical"
      and vertical_fit.orientation_votes["vertical"] == 80
      and vertical_fit.orientation_votes["horizontal"] == 0,
      vertical_fit.describe())
try:
    detect_printed_grid(vertical_only, legacy_horizontal, process_width=0)
    check("vertical-only thirds refuse horizontal mode", False)
except ColorGridError as exc:
    check("vertical-only thirds refuse horizontal mode",
          exc.stage == "orientation"
          and "detected vertical" in str(exc)
          and "requested horizontal" in str(exc), str(exc))

horizontal_only = render_target(encoding="horizontal")
horizontal_fit = detect_printed_grid(
    horizontal_only, legacy_horizontal, process_width=0)
check("horizontal-only thirds pass horizontal mode",
      horizontal_fit.orientation == "horizontal"
      and horizontal_fit.orientation_votes["vertical"] == 0
      and horizontal_fit.orientation_votes["horizontal"] == 80,
      horizontal_fit.describe())
try:
    detect_printed_grid(horizontal_only, legacy, process_width=0)
    check("horizontal-only thirds refuse vertical mode", False)
except ColorGridError as exc:
    check("horizontal-only thirds refuse vertical mode",
          exc.stage == "orientation"
          and "detected horizontal" in str(exc)
          and "requested vertical" in str(exc), str(exc))

annotated = image.copy()
draw_color_grid(annotated, found, labels=True, shade=0.0)
check("annotated output includes decoded per-cell patterns",
      np.count_nonzero(annotated != image) > 1000
      and "V" in found.pattern_label(0, 0)
      and any(pattern.signature.startswith("H:")
              for pattern in found.patterns),
      found.pattern_label(0, 0))

mode_corners = {}
for mode in ("vertical", "horizontal"):
    grid = MachineGrid.from_config(rig_data, mode=mode)
    corners = found.workspace_corners(grid)
    workspace = WorkspaceMap.from_grid(
        grid, corners, image.shape[1::-1], {"test": "combined"})
    mode_corners[mode] = workspace.corners
    check(f"combined target produces a valid {mode} map",
          workspace.matches_grid(grid))
    centre_cm = grid.cell_center_cm(1, 1)
    pixel = workspace.pixel_at(
        centre_cm[0] / grid.workspace_width_cm,
        centre_cm[1] / grid.workspace_height_cm,
        image.shape[1::-1],
    )
    check(f"combined target maps {mode} cell [1,1]",
          workspace.cell_at(pixel, image.shape[1::-1]) == (1, 1))

check("both modes share the measured holder envelope",
      np.allclose(mode_corners["vertical"], mode_corners["horizontal"], atol=1e-9))

evidence = PrintedGridEvidence(legacy)
first = evidence.add(found)
second = evidence.add(found)
check("combined target participates in evidence-assisted calibration",
      not first.ready and second.ready
      and isinstance(evidence.calibration, CombinedGridCalibration),
      second.describe())

try:
    found.workspace_corners(MachineGrid.from_config(rig_data), "printed")
    check("combined target refuses the obsolete printed-zero convention", False)
except ColorGridError as exc:
    check("combined target refuses the obsolete printed-zero convention",
          "firmware home convention" in str(exc), str(exc))

# Perspective is the real reason to fit the whole lattice rather than infer a
# page rectangle from four thresholded corners.
h, w = image.shape[:2]
src = np.float32(((0, 0), (w, 0), (w, h), (0, h)))
dst = np.float32(((30, 45), (w - 25, 10), (w - 55, h - 25), (45, h - 5)))
matrix = cv2.getPerspectiveTransform(src, dst)
warped = render_target(matrix, (w, h), encoding="combined")
tilted = detect_combined_grids(warped, process_width=0)[0]
check("combined target survives perspective",
      len(tilted.found_cells) == 80 and tilted.metrics.residual_px < 1.0
      and tilted.orientation == "mixed"
      and tilted.orientation_votes["ambiguous"] == 0,
      tilted.describe())

# A poor printer can reduce the muted fill almost to paper while leaving the
# saturated centre accents recognizable. This must exercise the independent
# stripe fallback rather than merely lower a global saturation threshold.
faded = render_target(fade=0.93, encoding="combined")
faded = cv2.GaussianBlur(faded, (5, 5), 1.2)
faded_found = detect_combined_grids(faded, process_width=0)[0]
check("dark stripes recover an almost desaturated print",
      len(faded_found.found_cells) == 80
      and faded_found.method == "dark centre stripes",
      faded_found.describe())

# Compound camera abuse: illumination falloff, channel cast, sensor noise,
# blur, JPEG artifacts and a smaller source image. The target need not use the
# same fallback on every OpenCV build; it must still pass the safety gates.
abused = render_target(fade=0.68, encoding="combined")
height, width = abused.shape[:2]
yy, xx = np.mgrid[:height, :width]
illumination = 0.38 + 0.62 * (0.55 * xx / width + 0.45 * yy / height)
abused = np.clip(abused.astype(np.float32)
                  * illumination[..., None]
                  * np.float32((1.22, 0.78, 1.12)), 0, 255)
rng = np.random.default_rng(7)
abused += rng.normal(0, 4.0, abused.shape)
abused = np.clip(abused, 0, 255).astype(np.uint8)
abused = cv2.GaussianBlur(abused, (3, 3), 0.8)
abused = cv2.resize(abused, (round(width * 0.72), round(height * 0.72)),
                     interpolation=cv2.INTER_AREA)
ok, encoded = cv2.imencode(".jpg", abused, [cv2.IMWRITE_JPEG_QUALITY, 50])
assert ok
abused = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
abused_found = detect_combined_grids(abused, process_width=0)[0]
check("combined target survives compound print/camera degradation",
      abused_found.metrics.window_observed == 80
      and len(abused_found.found_cells) >= 78
      and abused_found.metrics.parity_agreement == 1.0
      and abused_found.orientation == "mixed"
      and abused_found.orientation_votes["ambiguous"] == 0,
      abused_found.describe())

# The user's supplied PNG is an optional local capture rather than a committed
# fixture. Exercise it whenever it is present without making a clean checkout
# depend on a captures/ file.
capture = Path(__file__).resolve().parents[1] / "captures" / \
    "grad project grid white background.png"
if capture.exists():
    real = cv2.imread(str(capture))
    # Exact source-raster geometry: first bar starts at x=31, with 83 px muted,
    # 60 px dark and 84 px muted after inclusive raster rounding. Its paired
    # perpendicular bridge is 83 px colour, 60 px beige and 83 px colour.
    check("supplied PNG retains measured 2.2+1.6+2.2 stripe boundaries",
          np.all(real[50, 32:113] == GREEN)
          and np.all(real[50, 115:173] == DARK_GREEN)
          and np.all(real[50, 175:257] == GREEN)
          and np.all(real[32:113, 50] == GREEN)
          and np.all(real[115:173, 50] == BEIGE)
          and np.all(real[175:256, 50] == MAGENTA))
    detected = detect_combined_grids(real, process_width=0)[0]
    check("supplied combined artwork fits all fiducials",
          len(detected.found_cells) == 80
          and detected.metrics.parity_agreement == 1.0
          and detected.metrics.residual_px < 1.0
          and detected.orientation == "mixed"
          and detected.orientation_votes == {
              "vertical": 80, "horizontal": 80, "ambiguous": 0},
          detected.describe())
    for requested in ("vertical", "horizontal"):
        matched = detect_combined_grids(
            real, process_width=0, requested_mode=requested)[0]
        check(f"supplied artwork satisfies requested {requested} mode",
              requested in matched.orientations, matched.describe())
else:
    print("skip  supplied combined artwork: captures file not present")

# The two camera captures contain six complete rows and a seventh row clipped
# by the bottom image edge. The partial lattice may establish/extrapolate the
# 8x10 homography, but only the 48 complete bars and their 48 complete woven
# bridges may vote. LIVE_WITH_GRID also proves existing UI lines do not poison
# the local colour measurements.
captures = Path(__file__).resolve().parents[1] / "captures"
for live_name in ("LIVE_RAW.png", "LIVE_WITH_GRID.png"):
    live_path = captures / live_name
    if not live_path.exists():
        print(f"skip  {live_name}: capture not present")
        continue
    live = cv2.imread(str(live_path))
    live_fit = detect_combined_grids(live, process_width=0)[0]
    bar_patterns = [pattern for pattern in live_fit.patterns
                    if pattern.kind == "bar"]
    check(f"{live_name} recovers every complete visible fiducial",
          live_fit.metrics.lattice_shape == (FIDUCIAL_COLS, FIDUCIAL_ROWS)
          and live_fit.orientation == "mixed"
          and live_fit.orientation_votes == {
              "vertical": 48, "horizontal": 48, "ambiguous": 0},
          live_fit.describe())
    check(f"{live_name} disqualifies the clipped bottom row",
          len(bar_patterns) == 48
          and all(np.max(pattern.quad[:, 1]) <= live.shape[0] - 3
                  for pattern in bar_patterns),
          f"{len(bar_patterns)} complete bars")

raise SystemExit(1 if failed else 0)

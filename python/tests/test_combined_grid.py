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


GREEN = (72, 124, 100)      # supplied artwork's muted olive, BGR
MAGENTA = (150, 72, 157)    # supplied artwork's muted purple, BGR
DARK_GREEN = (0, 85, 34)
DARK_MAGENTA = (128, 0, 128)
PAPER = (255, 255, 255)
PX_PER_CM = 12.0
failed = False


def check(name, condition, detail=""):
    global failed
    print(f"{'ok  ' if condition else 'FAIL'}  {name}"
          + (f": {detail}" if detail else ""))
    failed |= not condition


def render_target(warp=None, out_size=None, fade=0.0):
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
            stripe = DARK_GREEN if is_green else DARK_MAGENTA
            cv2.rectangle(
                image,
                (round(stripe_x0 * PX_PER_CM), height - round(y1 * PX_PER_CM)),
                (round(stripe_x1 * PX_PER_CM) - 1,
                 height - round(y0 * PX_PER_CM) - 1),
                stripe,
                -1,
            )
    if warp is None:
        return image
    size = out_size or (width, height)
    return cv2.warpPerspective(image, warp, size, borderValue=PAPER)


rig_data = load_rig_config()
legacy = ColorGridSpec.from_config(rig_data, mode="vertical")

# The printable vector and detector constants are one physical contract.
asset = Path(__file__).resolve().parents[2] / "plans" / "assets" / \
    "combined-calibration-grid.svg"
root = ET.parse(asset).getroot()
namespace = {"svg": "http://www.w3.org/2000/svg"}
bars = [node for node in root.findall("svg:rect", namespace)
        if node.get("width") == "6" and node.get("height") == "2.2"]
check("canonical SVG is A2 landscape",
      root.get("width") == f"{PAGE_WIDTH_CM:g}cm"
      and root.get("height") == f"{PAGE_HEIGHT_CM:g}cm")
check("canonical SVG carries the detector's 8x10 lattice",
      len(bars) == FIDUCIAL_COLS * FIDUCIAL_ROWS, f"{len(bars)} bars")
check("canonical SVG retains the configured fiducial origin",
      np.isclose(min(float(node.get("x")) for node in bars), FIDUCIAL_LEFT_CM)
      and np.isclose(min(float(node.get("y")) for node in bars), PAGE_HEIGHT_CM - (
          FIDUCIAL_BOTTOM_CM
          + FIDUCIAL_ROWS * FIDUCIAL_BLOCK_Y_CM
          + (FIDUCIAL_ROWS - 1) * FIDUCIAL_GAP_Y_CM)))

image = render_target()
found = detect_printed_grid(image, legacy, process_width=0)
check("combined target is selected before the legacy detector",
      isinstance(found, CombinedGridCalibration), found.describe())
check("all 80 chromatic fiducials are measured",
      len(found.found_cells) == 80 and found.metrics.parity_agreement == 1.0,
      found.describe())

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
warped = render_target(matrix, (w, h))
tilted = detect_combined_grids(warped, process_width=0)[0]
check("combined target survives perspective",
      len(tilted.found_cells) == 80 and tilted.metrics.residual_px < 1.0,
      tilted.describe())

# A poor printer can reduce the muted fill almost to paper while leaving the
# saturated centre accents recognizable. This must exercise the independent
# stripe fallback rather than merely lower a global saturation threshold.
faded = render_target(fade=0.93)
faded = cv2.GaussianBlur(faded, (5, 5), 1.2)
faded_found = detect_combined_grids(faded, process_width=0)[0]
check("dark stripes recover an almost desaturated print",
      len(faded_found.found_cells) == 80
      and faded_found.method == "dark centre stripes",
      faded_found.describe())

# Compound camera abuse: illumination falloff, channel cast, sensor noise,
# blur, JPEG artifacts and a smaller source image. The target need not use the
# same fallback on every OpenCV build; it must still pass the safety gates.
abused = render_target(fade=0.68)
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
      and abused_found.metrics.parity_agreement == 1.0,
      abused_found.describe())

# The user's supplied PNG is an optional local capture rather than a committed
# fixture. Exercise it whenever it is present without making a clean checkout
# depend on a captures/ file.
capture = Path(__file__).resolve().parents[1] / "captures" / \
    "grad project grid white background.png"
if capture.exists():
    real = cv2.imread(str(capture))
    detected = detect_combined_grids(real, process_width=0)[0]
    check("supplied combined artwork fits all fiducials",
          len(detected.found_cells) == 80
          and detected.metrics.parity_agreement == 1.0
          and detected.metrics.residual_px < 1.0,
          detected.describe())
else:
    print("skip  supplied combined artwork: captures file not present")

raise SystemExit(1 if failed else 0)

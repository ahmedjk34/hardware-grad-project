#!/usr/bin/env python3
"""Synthetic checks for vision/cluster_grid.py.

Run from python/:  ../.venv/bin/python tests/test_cluster_grid.py

No camera, no capture files. A sheet is drawn in-process the same way
tests/test_color_grid.py draws the green/magenta sheet, then the bordered
cluster detector is run on it. See docs/cluster-calibration-grid.md.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np

from vision.color_grid import ColorGridError, ColorGridSpec
from vision.cluster_grid import (cluster_borders, detect_cluster_grid,
                                 detect_cluster_grids)

failed = False


def check(name, condition, detail=""):
    global failed
    mark = "ok  " if condition else "FAIL"
    if not condition:
        failed = True
    print(f"{mark} {name}" + (f"   [{detail}]" if detail else ""))


# --------------------------------------------------------------------------- #
# synthetic sheet
# --------------------------------------------------------------------------- #

PAPER = (245, 245, 245)
BORDER = (18, 18, 18)
TABLE = (188, 196, 201)
WHITE_CENTRE = (244, 244, 244)

INK = {
    ("vertical", "green"): [(58, 150, 58), (30, 92, 30), (58, 150, 58)],
    ("vertical", "magenta"): [(168, 58, 168), (104, 30, 104), (168, 58, 168)],
    ("horizontal", "green"): [(58, 150, 58), (208, 168, 138), (58, 150, 58)],
    ("horizontal", "magenta"): [(168, 58, 168), (208, 168, 138), (168, 58, 168)],
}


def render_cluster_sheet(spec, cols, rows, *, px_per_cm=11.0, margin_cm=2.0,
                         gutter_cm=None, border_px=2, clip_cm=(0.0, 0.0),
                         warp=None, size=None, cast=None):
    """Draw a bordered 3x3-cluster sheet; one cluster per lattice site."""
    gx = spec.gap_x_cm if gutter_cm is None else gutter_cm
    gy = spec.gap_y_cm if gutter_cm is None else gutter_cm
    pitch_x = spec.block_x_cm + gx
    pitch_y = spec.block_y_cm + gy
    width_cm = cols * pitch_x - gx + 2 * margin_cm
    height_cm = rows * pitch_y - gy + 2 * margin_cm
    w = round(width_cm * px_per_cm)
    h = round(height_cm * px_per_cm)
    sheet = np.full((h, w, 3), PAPER, np.uint8)

    centres = {}
    for row in range(rows):
        for col in range(cols):
            x0 = (margin_cm - clip_cm[0] + col * pitch_x) * px_per_cm
            y0_top = h - (margin_cm - clip_cm[1] + row * pitch_y
                          + spec.block_y_cm) * px_per_cm
            bw = spec.block_x_cm * px_per_cm
            bh = spec.block_y_cm * px_per_cm
            parity = "green" if (col + row) % 2 == 0 else "magenta"
            ramp = INK[(spec.mode, parity)]
            for sr in range(3):
                for sc in range(3):
                    cx0 = round(x0 + sc / 3 * bw)
                    cx1 = round(x0 + (sc + 1) / 3 * bw)
                    cy0 = round(y0_top + sr / 3 * bh)
                    cy1 = round(y0_top + (sr + 1) / 3 * bh)
                    if (sr, sc) == (1, 1):
                        colour = WHITE_CENTRE
                    elif spec.mode == "vertical":
                        colour = ramp[sc]
                    else:
                        colour = ramp[sc]
                    cv2.rectangle(sheet, (cx0, cy0), (cx1 - 1, cy1 - 1),
                                  colour, -1)
                    cv2.rectangle(sheet, (cx0, cy0), (cx1 - 1, cy1 - 1),
                                  BORDER, border_px)
            centres[(col, row)] = (x0 + bw / 2, y0_top + bh / 2)

    if cast is not None:
        sheet = np.clip(sheet.astype(np.float32)
                        * np.float32(cast)[::-1], 0, 255).astype(np.uint8)
    if warp is None:
        return sheet, centres
    out = size or (w, h)
    scene = np.full((out[1], out[0], 3), TABLE, np.uint8)
    warped = cv2.warpPerspective(sheet, warp, out,
                                 borderMode=cv2.BORDER_TRANSPARENT, dst=scene)
    moved = {k: tuple(cv2.perspectiveTransform(
                np.float32([[p]]), warp).reshape(2)) for k, p in centres.items()}
    return warped, moved


def perspective(w, h, *, rot=0.0, shear=0.0, scale=1.0, tx=0.0, ty=0.0):
    cx, cy = w / 2, h / 2
    c, s = np.cos(rot), np.sin(rot)
    rotate = np.array([[c, -s, cx - c * cx + s * cy],
                       [s, c, cy - s * cx - c * cy], [0, 0, 1]], np.float64)
    warp = np.array([[scale, shear, tx], [0.0, scale, ty],
                     [4e-5, 6e-5, 1.0]], np.float64)
    return warp @ rotate


VERTICAL = ColorGridSpec.from_config(mode="vertical")
HORIZONTAL = ColorGridSpec.from_config(mode="horizontal")


# --------------------------------------------------------------------------- #
# C1  edge stage
# --------------------------------------------------------------------------- #

image, _ = render_cluster_sheet(VERTICAL, 9, 8)
mask, quads = cluster_borders(image)
check("C1 adaptive threshold finds one quad per drawn cluster",
      70 <= len(quads) <= 72, f"{len(quads)} quads for 72 clusters")
areas = np.array([q["area"] for q in quads])
check("C1 cluster quads are uniform in size",
      float(areas.std() / areas.mean()) < 0.05,
      f"cv {areas.std() / areas.mean():.3f}")


# --------------------------------------------------------------------------- #
# C2-C5  vertical, upright, oversized
# --------------------------------------------------------------------------- #

image, centres = render_cluster_sheet(VERTICAL, 9, 8, clip_cm=(1.3, 0.0))
cals = detect_cluster_grids(image, VERTICAL, process_width=0)
cal = cals[0]
check("C2 vertical sheet fits a homography with sub-pixel residual",
      cal.metrics.residual_px < 1.5, f"{cal.metrics.residual_px:.3f} px")
mapped = cal.found_cells
check("C4 vertical selected window maps the whole 7x6 coordinate grid",
      len(mapped) == VERTICAL.cols * VERTICAL.rows, str(len(mapped)))
check("C3 every mapped cluster is whole",
      all(c.full for c in mapped.values()))
check("C3 clipped edge clusters never enter the map",
      all(not c.edge_clipped for c in mapped.values()))
origin = cal.cell_center(0, 0)
corners = {"[6,0]": cal.cell_center(6, 0), "[0,5]": cal.cell_center(0, 5),
           "[6,5]": cal.cell_center(6, 5)}
check("C4 [0,0] is the bottom-left cluster",
      all(p[0] >= origin[0] - 1 and p[1] <= origin[1] + 1
          for p in corners.values()), str(corners))
step_col = np.subtract(cal.cell_center(1, 0), origin)
step_row = np.subtract(cal.cell_center(0, 1), origin)
check("C4 the two grid axes are square",
      abs(float(step_col @ step_row))
      / (np.linalg.norm(step_col) * np.linalg.norm(step_row)) < 0.05)
check("C5 an oversized sheet offers more than one window",
      len(cals) > 1, f"{len(cals)} windows")
check("parity of the green/magenta cluster chessboard is clean",
      cal.metrics.parity_agreement == 1.0,
      f"{cal.metrics.parity_agreement:.0%}")


# --------------------------------------------------------------------------- #
# C2  tilted
# --------------------------------------------------------------------------- #

flat, cflat = render_cluster_sheet(VERTICAL, 8, 7)
warp = perspective(flat.shape[1], flat.shape[0], rot=0.05, shear=0.06,
                   scale=0.9, tx=30, ty=20)
tilted, tcent = render_cluster_sheet(VERTICAL, 8, 7, warp=warp,
                                     size=(flat.shape[1], flat.shape[0]))
tcal = detect_cluster_grid(tilted, VERTICAL, process_width=0)
check("C2 tilted sheet still fits every mapped cluster",
      len(tcal.found_cells) == VERTICAL.cols * VERTICAL.rows,
      tcal.describe())
check("C2 tilted sheet residual stays small",
      tcal.metrics.residual_px < 2.0, f"{tcal.metrics.residual_px:.3f} px")
worst = max(np.linalg.norm(np.subtract(tcal.cell_center(*k), tcent[k]))
           for k in tcal.found_cells if k in tcent)
check("C2 fitted centres land on the drawn clusters", worst < 3.0,
      f"{worst:.2f} px")


# --------------------------------------------------------------------------- #
# C9  colour cast
# --------------------------------------------------------------------------- #

for name, gains in (("magenta", (1.16, 0.80, 1.18)),
                    ("blue", (1.22, 0.96, 0.82)),
                    ("warm", (0.82, 0.96, 1.20))):
    casty, _ = render_cluster_sheet(VERTICAL, 9, 9, margin_cm=3.5, cast=gains)
    try:
        fit = detect_cluster_grid(casty, VERTICAL, process_width=0, edge_margin=0)
        ok = len(fit.found_cells) == VERTICAL.cols * VERTICAL.rows
    except ColorGridError as exc:
        ok, exc_detail = False, str(exc)[:60]
    else:
        exc_detail = fit.describe()
    check(f"C9 detection survives a {name} cast", ok, exc_detail)


# --------------------------------------------------------------------------- #
# C3  partial-cluster tolerance boundary
# --------------------------------------------------------------------------- #

image, _ = render_cluster_sheet(VERTICAL, 9, 9, margin_cm=3.5)
loose = detect_cluster_grid(image, VERTICAL, process_width=0, edge_margin=0,
                            fill_tolerance=0.80)
strict = detect_cluster_grid(image, VERTICAL, process_width=0, edge_margin=0,
                             fill_tolerance=0.999)
check("C3 a tolerance near 1.0 keeps the whole clusters",
      len(strict.found_cells) == VERTICAL.cols * VERTICAL.rows,
      f"{len(strict.found_cells)} kept")
check("C3 the tolerance is an actual knob (loose keeps >= strict)",
      len(loose.found_cells) >= len(strict.found_cells))


# --------------------------------------------------------------------------- #
# C6  horizontal mode + wrong-mode refusal
# --------------------------------------------------------------------------- #

himage, _ = render_cluster_sheet(HORIZONTAL, 6, 14, clip_cm=(0.5, 0.0))
hcal = detect_cluster_grid(himage, HORIZONTAL, process_width=0)
check("C6 horizontal sheet maps the whole 3x10 coordinate grid",
      len(hcal.found_cells) == HORIZONTAL.cols * HORIZONTAL.rows,
      str(len(hcal.found_cells)))
check("C6 horizontal layout string is x-along-block-length",
      hcal.layout == "x-along-block-length", str(hcal.layout))

try:
    detect_cluster_grid(himage, VERTICAL, process_width=0)
    check("C6 a horizontal sheet is refused in vertical mode", False)
except ColorGridError as exc:
    check("C6 a horizontal sheet is refused in vertical mode",
          exc.stage == "orientation", str(exc)[:70])

vimage, _ = render_cluster_sheet(VERTICAL, 8, 7)
try:
    detect_cluster_grid(vimage, HORIZONTAL, process_width=0)
    check("C6 a vertical sheet is refused in horizontal mode", False)
except ColorGridError as exc:
    check("C6 a vertical sheet is refused in horizontal mode",
          exc.stage == "orientation", str(exc)[:70])


# --------------------------------------------------------------------------- #
# C8  failure carries candidates
# --------------------------------------------------------------------------- #

try:
    detect_cluster_grids(np.full((300, 300, 3), TABLE, np.uint8), VERTICAL,
                         process_width=0)
    check("C8 a blank frame is refused", False)
except ColorGridError as exc:
    check("C8 a blank frame is refused with a stage", bool(exc.stage),
          exc.stage)


raise SystemExit(1 if failed else 0)

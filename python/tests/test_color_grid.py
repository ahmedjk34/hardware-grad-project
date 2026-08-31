#!/usr/bin/env python3
"""Hold the printed colour-grid detector to the behaviour the rig depends on.

    cd python
    ../.venv/bin/python tests/test_color_grid.py

Most of this runs on synthetic sheets rendered at a known homography, because
that is the only way to check the answer rather than check that the answer
looks plausible: the true cell centres are known to the pixel, so the tests can
assert on them. The two training captures in ``captures/grid_training`` are
used as well when they are present — that directory is gitignored, so their
absence is a skip, not a failure.

What is actually being protected
--------------------------------
* whole cells define the fit and partial ones never do;
* ``[0,0]`` lands on the cell nearest the bottom-left of the image;
* columns follow the 2.2 cm cell side whichever way the sheet is turned;
* a sheet that cannot hold the whole grid is refused rather than approximated;
* under the default home convention, printed cell ``[c,r]`` lands exactly on
  the firmware's own cell ``[c,r]``. That last one is the whole reason the
  sheet exists, and it is the one that would silently misplace blocks.
"""

from pathlib import Path
import sys
import tempfile
import time

from dataclasses import replace

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.config import load as load_rig_config
from rig.grid import MachineGrid
from rig.workspace import WorkspaceMap
from vision.color_grid import (
    ColorGridError,
    ColorGridSpec,
    color_masks,
    detect_color_grid,
    detect_color_grids,
    white_balance,
)


GREEN_BGR = (150, 190, 90)      # roughly the printed inks, in BGR
MAGENTA_BGR = (190, 140, 200)
PAPER_BGR = (245, 245, 245)
TABLE_BGR = (185, 195, 200)

failed = False


def check(name, ok, detail=""):
    global failed
    print(f"{'ok  ' if ok else 'FAIL'}  {name}{': ' + detail if detail else ''}")
    failed |= not ok
    return ok


def render_sheet(spec, cols, rows, *, px_per_cm=14.0, margin_cm=1.6,
                 clip_cm=(0.0, 0.0), warp=None, size=None,
                 green=GREEN_BGR, magenta=MAGENTA_BGR, paper=PAPER_BGR):
    """Draw a printed sheet, optionally clipped at two edges and warped.

    ``clip_cm`` shifts the paper so that the first column/row is cut in half,
    which is what a real photo of an oversized sheet looks like and what the
    partial-cell rejection has to survive. Cell ``[c,r]`` is drawn with its
    lower-left corner at ``(c * pitch_x, r * pitch_y)`` in paper centimetres.
    """
    width_cm = cols * spec.pitch_x_cm - spec.gap_x_cm + 2 * margin_cm
    height_cm = rows * spec.pitch_y_cm - spec.gap_y_cm + 2 * margin_cm
    width = round(width_cm * px_per_cm)
    height = round(height_cm * px_per_cm)
    sheet = np.full((height, width, 3), paper, np.uint8)

    centers = {}
    for row in range(rows):
        for col in range(cols):
            x0 = margin_cm - clip_cm[0] + col * spec.pitch_x_cm
            y0 = margin_cm - clip_cm[1] + row * spec.pitch_y_cm
            x1, y1 = x0 + spec.block_x_cm, y0 + spec.block_y_cm
            colour = green if (col + row) % 2 == 0 else magenta
            # Paper y grows upward; image y grows down.
            top = height - y1 * px_per_cm
            bottom = height - y0 * px_per_cm
            cv2.rectangle(sheet, (round(x0 * px_per_cm), round(top)),
                          (round(x1 * px_per_cm) - 1, round(bottom) - 1),
                          colour, -1)
            centers[(col, row)] = ((x0 + x1) / 2 * px_per_cm,
                                   height - (y0 + y1) / 2 * px_per_cm)

    if warp is None:
        return sheet, centers
    out_size = size or (width, height)
    scene = np.full((out_size[1], out_size[0], 3), TABLE_BGR, np.uint8)
    warped = cv2.warpPerspective(sheet, warp, out_size, borderMode=cv2.BORDER_TRANSPARENT,
                                 dst=scene)
    moved = {}
    for key, point in centers.items():
        projected = cv2.perspectiveTransform(
            np.float32([[point]]), warp).reshape(2)
        moved[key] = (float(projected[0]), float(projected[1]))
    return warped, moved


def perspective(width, height, shear=0.0, squeeze=0.0, angle=0.0, scale=1.0,
                offset=(0.0, 0.0)):
    """A homography with a bit of everything a hand-held photo has."""
    source = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    destination = np.float32([
        [0, squeeze * height],
        [width, 0],
        [width * (1 - shear), height],
        [shear * width, height * (1 - squeeze)],
    ])
    rotation = cv2.getRotationMatrix2D((width / 2, height / 2), angle, scale)
    matrix = np.vstack([rotation, [0, 0, 1]]).astype(np.float32)
    matrix[0, 2] += offset[0]
    matrix[1, 2] += offset[1]
    return matrix @ cv2.getPerspectiveTransform(source, destination)


def corner_cells(calibration):
    spec = calibration.spec
    return {name: calibration.cell_center(col, row) for name, (col, row) in (
        ("[0,0]", (0, 0)),
        ("[max,0]", (spec.cols - 1, 0)),
        ("[0,max]", (0, spec.rows - 1)),
        ("[max,max]", (spec.cols - 1, spec.rows - 1)),
    )}


spec = ColorGridSpec()
grid = MachineGrid.from_config()
print(f"sheet: {spec.describe()}")


# --- 0. the horizontal sheet is a first-class detector layout ---------------

rig_config = load_rig_config()
horizontal_spec = ColorGridSpec.from_config(rig_config, mode="horizontal")
# The lattice is ANCHORED on the home corner now, so the shipped 0.0 trims are
# already feeder-adjacent. The old -4.55/-5.0 override existed only to undo the
# centring the geometry used to apply, and would now push the grid off the rig.
horizontal_grid = MachineGrid.from_config(rig_config, mode="horizontal")
H_COLS, H_ROWS = horizontal_spec.cols, horizontal_spec.rows       # 3 x 11
H_CELLS = H_COLS * H_ROWS                                         # 33
check("horizontal sheet maps the complete 3x11 coordinate grid",
      (horizontal_spec.mode, horizontal_spec.cols, horizontal_spec.rows)
      == ("horizontal", 3, 11), horizontal_spec.describe())

# The real horizontal paper has spare width.  Five long-side columns gives the
# detector that same window-search problem while retaining the 3x11 mapped
# extent; thirteen short-side rows give overlapping choices there too.
horizontal_image, horizontal_centres = render_sheet(
    horizontal_spec, 6, 16, clip_cm=(0.6, 0.0), margin_cm=2.0)
horizontal = detect_color_grid(horizontal_image, horizontal_spec, process_width=0)
check(f"horizontal sheet fits all {H_CELLS} mapped cells",
      len(horizontal.found_cells) == H_CELLS
      and horizontal.layout == "x-along-block-length",
      horizontal.describe())
check("horizontal partial edge blocks never enter the map",
      all(cell.full for cell in horizontal.found_cells.values()),
      f"{len(horizontal.found_cells)} whole mapped cells")
horizontal_choices = detect_color_grids(horizontal_image, horizontal_spec, process_width=0)
check("horizontal sheet retains operator-selectable overlapping windows",
      len(horizontal_choices) > 1,
      f"{len(horizontal_choices)} choices")

# Leave only a tiny, correctly coloured island in three cells.  Those islands
# are too small to be geometry anchors, but the already-fitted horizontal
# lattice must still confirm that ink is physically present rather than turn
# the cells into holes.  This protects the same dim-ink recovery used by the
# live vertical capture without baking a vertical-only axis assumption into it.
horizontal_dim = horizontal_image.copy()
for key in ((2, 5), (3, 8), (4, 11)):
    cx, cy = (round(value) for value in horizontal_centres[key])
    half_w = round(horizontal_spec.block_x_cm * 14.0 / 2)
    half_h = round(horizontal_spec.block_y_cm * 14.0 / 2)
    ink = tuple(int(value) for value in horizontal_dim[cy, cx])
    cv2.rectangle(horizontal_dim, (cx - half_w, cy - half_h),
                  (cx + half_w, cy + half_h), PAPER_BGR, -1)
    cv2.rectangle(horizontal_dim, (cx - max(1, half_w // 5),
                                   cy - max(1, half_h // 5)),
                  (cx + max(1, half_w // 5),
                   cy + max(1, half_h // 5)), ink, -1)
horizontal_dim_choices = detect_color_grids(
    horizontal_dim, horizontal_spec, process_width=0)
check("horizontal mode recovers weak ink without bending the fit",
      len(horizontal_dim_choices) > 1
      and all(choice.metrics.window_observed == H_CELLS
              for choice in horizontal_dim_choices),
      f"{len(horizontal_dim_choices)} choices with "
      f"{[choice.metrics.window_observed for choice in horizontal_dim_choices]}")
# The horizontal sheet model has not caught up with the machine's alternating
# Y lattice yet, so calibrating a horizontal map must REFUSE rather than write
# a map that is 7.8 cm out by row 10.
try:
    horizontal.workspace_corners(horizontal_grid, "firmware")
    check("horizontal sheet calibration is refused until the sheet model "
          "learns the alternating Y lattice", False)
except ColorGridError as exc:
    check("horizontal sheet calibration is refused until the sheet model "
          "learns the alternating Y lattice", "ALTERNATING" in str(exc), str(exc))

try:
    # The explicit count/layout cross-check protects a caller that accidentally
    # feeds a vertical calibration into a horizontal machine map.
    horizontal.workspace_corners(grid, "firmware")
    check("wrong-mode sheet is refused before calibration", False)
except ColorGridError as exc:
    check("wrong-mode sheet is refused before calibration",
          "horizontal printed sheet" in str(exc), str(exc))


# --- 1. an upright sheet, printed oversized and clipped on two edges --------

image, centers = render_sheet(spec, 9, 8, clip_cm=(1.2, 4.0))
calibration = detect_color_grid(image, spec, process_width=0)
try:
    detect_color_grid(image, horizontal_spec, process_width=0)
    check("a vertical sheet offered in horizontal mode is refused", False)
except ColorGridError as exc:
    check("a vertical sheet offered in horizontal mode is refused",
          "selected horizontal layout" in str(exc), str(exc)[:120])
check("upright sheet fits the 7x6 grid",
      (calibration.spec.cols, calibration.spec.rows) == (7, 6),
      calibration.describe())
check("upright sheet has a sub-pixel residual",
      calibration.metrics.residual_px < 1.0,
      f"{calibration.metrics.residual_px:.3f} px")
check("colour parity is consistent",
      calibration.metrics.parity_agreement == 1.0,
      f"{calibration.metrics.parity_agreement:.0%}")

corners = corner_cells(calibration)
origin = corners["[0,0]"]
check("[0,0] is the bottom-left corner cell",
      all(origin[0] <= point[0] + 1 and origin[1] >= point[1] - 1
          for name, point in corners.items() if name != "[0,0]"),
      ", ".join(f"{n}=({p[0]:.0f},{p[1]:.0f})" for n, p in corners.items()))
# Which screen direction is "along columns" depends on how the sheet was laid
# down, and both are legal. What must hold is that [0,0] is the corner: raising
# either index moves away from the bottom-left, and the two axes are square.
step_col = np.array(calibration.cell_center(1, 0)) - origin
step_row = np.array(calibration.cell_center(0, 1)) - origin
away = np.array([1.0, -1.0])          # right and up, in image pixels
check("raising either index moves away from the bottom-left",
      float(step_col @ away) > 0 and float(step_row @ away) > 0,
      f"col step {step_col.round(1)}, row step {step_row.round(1)}")
check("the two grid axes are square to each other",
      abs(float(step_col @ step_row)) /
      (np.linalg.norm(step_col) * np.linalg.norm(step_row)) < 0.05)

# The clipped half-cells sit outside the chosen window; nothing that touches
# the paper edge may have been used.
mapped = calibration.found_cells
check("every mapped cell is a whole cell", len(mapped) == spec.cols * spec.rows, str(len(mapped)))
check("every mapped cell is whole", all(cell.full for cell in mapped.values()))


# --- 2. the same sheet, tilted and in perspective ---------------------------

warp = perspective(600, 900, shear=0.05, squeeze=0.04, angle=7.0, scale=0.82,
                   offset=(40, 30))
image, centers = render_sheet(spec, 9, 8, clip_cm=(1.2, 4.0), warp=warp,
                              size=(760, 1000))
calibration = detect_color_grid(image, spec, process_width=0)
check("tilted sheet still fits the grid",
      len(calibration.found_cells) == spec.cols * spec.rows, calibration.describe())
check("tilted sheet residual stays small",
      calibration.metrics.residual_px < 1.5,
      f"{calibration.metrics.residual_px:.3f} px")

# The synthetic centres are known exactly, so this is a real accuracy check
# rather than a self-consistency one. Which drawn cell is [0,0] depends on how
# the window landed, so compare the fitted grid against the drawn lattice by
# looking for the drawn cell nearest each fitted centre.
drawn = np.array(list(centers.values()))
worst = 0.0
for (col, row) in mapped:
    fitted = np.array(calibration.cell_center(col, row))
    worst = max(worst, float(np.min(np.linalg.norm(drawn - fitted, axis=1))))
check("every fitted centre lands on a drawn cell", worst < 2.0, f"{worst:.2f} px")


# --- 2b. scene-coloured clutter must not steer the lattice -----------------

sheet, _ = render_sheet(spec, 9, 8, clip_cm=(1.2, 4.0))
cluttered = np.full((sheet.shape[0], sheet.shape[1] + 360, 3), TABLE_BGR, np.uint8)
cluttered[:, 180:180 + sheet.shape[1]] = sheet
# Rails/walls in the live capture occupy the same hue windows as the ink. They
# are deliberately numerous here so a global direction/size vote over every
# colour component would follow the scene instead of the paper.
for y in range(18, cluttered.shape[0] - 40, 70):
    cv2.rectangle(cluttered, (8, y), (160, y + 18), MAGENTA_BGR, -1)
for y in range(42, cluttered.shape[0] - 40, 82):
    cv2.rectangle(cluttered,
                  (cluttered.shape[1] - 160, y),
                  (cluttered.shape[1] - 8, y + 16), GREEN_BGR, -1)
try:
    found = detect_color_grid(cluttered, spec, process_width=0)
    check("rail-shaped colour clutter cannot steer the sheet lattice",
          len(found.found_cells) == spec.cols * spec.rows and found.metrics.parity_agreement == 1.0,
          found.describe())
except ColorGridError as exc:
    check("rail-shaped colour clutter cannot steer the sheet lattice", False,
          str(exc)[:90])


# A geometrically perfect but single-colour array is not the printed target.
# Parity is an acceptance gate, not merely a number in the status bar.
monochrome, _ = render_sheet(spec, 9, 8, clip_cm=(1.2, 4.0),
                             green=GREEN_BGR, magenta=GREEN_BGR)
try:
    detect_color_grid(monochrome, spec, process_width=0)
    check("a lattice with broken colour parity is refused", False, "it was accepted")
except ColorGridError as exc:
    check("a lattice with broken colour parity is refused",
          exc.stage == "quality" and "parity" in str(exc), str(exc)[:90])


# --- 3. the sheet turned a quarter turn -------------------------------------

image, _ = render_sheet(spec, 9, 8, clip_cm=(1.2, 4.0))
turned = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
calibration = detect_color_grid(turned, spec, process_width=0)
check("a quarter-turned sheet is still 7 columns x 6 rows",
      len(calibration.found_cells) == spec.cols * spec.rows, calibration.describe())
quad = calibration.cell_quad(0, 0)
short = min(np.linalg.norm(quad[1] - quad[0]), np.linalg.norm(quad[3] - quad[0]))
long = max(np.linalg.norm(quad[1] - quad[0]), np.linalg.norm(quad[3] - quad[0]))
check("columns follow the short cell side whichever way the sheet is turned",
      abs(long / short - spec.block_y_cm / spec.block_x_cm) < 0.25,
      f"aspect {long / short:.2f}")
corners = corner_cells(calibration)
origin = corners["[0,0]"]
check("[0,0] is still the bottom-left corner cell after the turn",
      all(origin[0] <= point[0] + 1 and origin[1] >= point[1] - 1
          for name, point in corners.items() if name != "[0,0]"))


# --- 4. a sheet that cannot hold the grid is refused ------------------------

image, _ = render_sheet(spec, 22, 4)
try:
    # edge_margin=0 isolates the "physically too short" path from the separate
    # frame-border discard behaviour, which section 8 covers.
    detect_color_grid(image, spec, process_width=0, edge_margin=0)
    check("a sheet with too few rows is refused", False, "it was accepted")
except ColorGridError as exc:
    check("a sheet with too few rows is refused",
          "4 whole cells along the 6 cm side where 6 are needed" in str(exc),
          str(exc)[:80])

blank = np.full((400, 600, 3), TABLE_BGR, np.uint8)
try:
    detect_color_grid(blank, spec, process_width=0)
    check("an empty frame is refused", False, "it was accepted")
except ColorGridError as exc:
    check("an empty frame is refused", True, str(exc)[:70])


# --- 5. gaps are gaps -------------------------------------------------------

image, _ = render_sheet(spec, 9, 8, clip_cm=(1.2, 4.0))
calibration = detect_color_grid(image, spec, process_width=0)
inside = calibration.cell_at(calibration.cell_center(3, 2))
between = calibration.cell_at(calibration.point_at(3.5, 2))
check("a pixel on a block reports that block", inside == (3, 2), str(inside))
check("a pixel in the inner margin reports nothing", between is None, str(between))


# --- 6. the mapping back onto the machine envelope --------------------------

size = image.shape[1::-1]
workspace = WorkspaceMap.from_grid(
    grid, calibration.workspace_corners(grid, "firmware"), size, {"test": 1})
worst = 0.0
mismatched = []
for col in range(grid.cols):
    for row in range(grid.rows):
        printed = np.array(calibration.cell_center(col, row))
        if workspace.cell_at(printed, size) != (col, row):
            mismatched.append((col, row))
        x_cm, y_cm = grid.cell_center_cm(col, row)
        machine = np.array(workspace.pixel_at(x_cm / grid.workspace_width_cm,
                                              y_cm / grid.workspace_height_cm, size))
        worst = max(worst, float(np.linalg.norm(machine - printed)))
check("every printed cell reports its own machine cell", not mismatched,
      f"{len(mismatched)} mismatched")
check("printed and firmware cell centres coincide under the default convention",
      worst < 0.5, f"max offset {worst:.3f} px")

# The other convention is not wrong, it is a different decision — and it must
# differ by exactly the block-plus-gap the paper adds at coordinate zero.
other = WorkspaceMap.from_grid(
    grid, calibration.workspace_corners(grid, "printed"), size, {"test": 1})
x_cm, y_cm = grid.cell_center_cm(1, 1)
shifted = np.array(other.pixel_at(x_cm / grid.workspace_width_cm,
                                  y_cm / grid.workspace_height_cm, size))
printed = np.array(calibration.cell_center(1, 1))
px_per_cm = np.linalg.norm(
    np.array(calibration.point_at(1, 0)) - np.array(calibration.point_at(0, 0))
) / spec.pitch_x_cm
offset_cm = np.linalg.norm(shifted - printed) / px_per_cm
# Derived, not hard-coded: the two conventions place the machine origin at
# `-start` (the outer corner of printed [0,0]) and at `block / 2` (its centre)
# in printed centimetres, so the gap between them moves with grid.trim_*.
# Pinning a number here would just re-fail every time a trim is measured.
#
# Coordinate zero being a real block collapsed this from a block-plus-gap to
# exactly half a block on each axis: the firmware and the sheet now disagree
# only about which part of cell [0,0] home sits on, not about whether it
# exists at all.
expected_cm = float(np.hypot(
    -grid.x_start_cm - spec.block_x_cm / 2,
    -grid.y_start_cm - spec.block_y_cm / 2))
check("the two home conventions differ by exactly what the geometry says",
      abs(offset_cm - expected_cm) < 0.15,
      f"{offset_cm:.2f} cm, expected {expected_cm:.2f} cm "
      f"(trim {grid.trim_x_cm:g},{grid.trim_y_cm:g})")


# --- 6b. a camera colour cast, which is what broke this on the real rig ------
#
# A live frame from the rig arrived with a magenta cast strong enough to move
# the green ink to hue 120 / saturation 49 — outside the green window and under
# the saturation floor — so half of every sheet vanished and nothing detected
# at all. This reproduces that kind of cast and holds the white balance to
# fixing it.

def cast(image, gains):
    """Push a frame's channels around the way a bad camera white balance does."""
    return np.clip(image.astype(np.float32) * np.float32(gains), 0, 255).astype(np.uint8)


image, _ = render_sheet(spec, 9, 8, clip_cm=(1.2, 4.0))
for name, gains in (("magenta cast", (1.18, 0.72, 1.24)),
                    ("blue cast", (1.35, 0.95, 0.72)),
                    ("warm cast", (0.70, 0.95, 1.30))):
    tinted = cast(image, gains)
    try:
        found = detect_color_grid(tinted, spec, process_width=0)
        check(f"detection survives a {name}", len(found.found_cells) == spec.cols * spec.rows,
              found.describe())
    except ColorGridError as exc:
        check(f"detection survives a {name}", False, str(exc)[:70])

# The synthetic inks above are more saturated than real print under the rig's
# own lighting, so they survive a cast on the widened hue windows alone. Repeat
# the check with the colours actually measured off the live rig frame - green
# ink BGR (168,136,136), magenta (153,99,160), paper (195,167,183) - which is
# where the balance stops being a nicety.
faded = render_sheet(spec, 9, 8, clip_cm=(1.2, 4.0), green=(168, 136, 136),
                     magenta=(153, 99, 160), paper=(195, 167, 183))[0]
unbalanced, _ = color_masks(faded, balance=False)
balanced, _ = color_masks(faded, balance=True)
check("without balancing, real rig ink colours lose the green cells",
      unbalanced.sum() < balanced.sum() / 4,
      f"{int(unbalanced.sum())} px unbalanced vs {int(balanced.sum())} balanced")
try:
    found = detect_color_grid(faded, spec, process_width=0)
    check("with balancing, real rig ink colours still fit the grid",
          len(found.found_cells) == spec.cols * spec.rows, found.describe())
except ColorGridError as exc:
    check("with balancing, real rig ink colours still fit the grid", False,
          str(exc)[:70])

check("a neutral frame is left alone by the balance",
      np.array_equal(white_balance(image), image))


# --- 7. the feed helpers, without a camera or a window ----------------------
#
# Camera code cannot be verified on this machine, so exercise everything in the
# live path that does not actually need a camera: the background tracker, the
# overlay draw, and the calibrate-and-save that the k key triggers.

from camera.gridded_camera_feed import (  # noqa: E402
    PaperGridTracker,
    draw_paper_evidence,
    draw_paper_grid,
    paper_workspace_map,
)
from vision.grid_evidence import PaperGridEvidence  # noqa: E402

image, _ = render_sheet(spec, 9, 8, clip_cm=(1.2, 4.0))
size = image.shape[1::-1]

tracker = PaperGridTracker(spec, max_hz=60.0, process_width=0)
tracker.start()
try:
    tracker.poll(1)
    check("an off tracker reports nothing", tracker.calibration is None)
    tracker.toggle()
    deadline = time.monotonic() + 5.0
    while tracker.calibration is None and time.monotonic() < deadline:
        tracker.submit(image, 1, 1)
        time.sleep(0.02)
        tracker.poll(1)
    check("the tracker finds the sheet off the preview thread",
          tracker.calibration is not None, tracker.status())
    initial_origin = tracker.calibration.cell_center(0, 0)
    check("the tracker retains every overlapping window",
          len(tracker.calibrations) > 1, str(len(tracker.calibrations)))
    changed = tracker.cycle(1)
    check("the operator can select a different detected window",
          changed and tracker.selection == 1
          and tracker.calibration.cell_center(0, 0) != initial_origin,
          tracker.status())
    tracker.cycle(-1)

    frame = image.copy()
    hovered = draw_paper_grid(frame, tracker, tracker.calibration.cell_center(4, 3),
                              grid, "firmware", detail=True)
    check("the overlay reports the hovered cell", hovered == (4, 3), str(hovered))
    check("the overlay actually draws pixels", not np.array_equal(frame, image))
finally:
    tracker.stop()

with tempfile.TemporaryDirectory() as directory:
    target = Path(directory) / "workspace_map.json"
    saved, found = paper_workspace_map(image, spec, grid, {"test": 1}, "firmware")
    saved.save(target)
    reloaded = WorkspaceMap.load(target, grid.cols, grid.rows)
    check("the sheet writes a map the loader accepts",
          reloaded.matches_grid(grid), f"{len(found.found_cells)} cells")
    printed = found.cell_center(4, 3)
    check("the reloaded map agrees with the sheet it came from",
          reloaded.cell_at(printed, size) == (4, 3),
          str(reloaded.cell_at(printed, size)))


# --- 7b. gantry-occluded frames can be pooled, never blindly completed ------

image, centres = render_sheet(spec, 9, 8)

def hide_cells(source, row, columns):
    """Hide an interior gantry-shaped band without touching sheet boundaries."""
    result = source.copy()
    y = round(centres[(6, row)][1])
    left = round(centres[(min(columns), row)][0] - 18)
    right = round(centres[(max(columns), row)][0] + 18)
    cv2.rectangle(result, (left, y - 54), (right, y + 54), PAPER_BGR, -1)
    return result


first = hide_cells(image, 3, range(3, 9))
second = hide_cells(image, 3, range(3, 9))
try:
    detect_color_grid(first, spec, process_width=0)
    check("a gantry-split frame stays refused in strict mode", False)
except ColorGridError:
    check("a gantry-split frame stays refused in strict mode", True)

try:
    first_sparse = detect_color_grid(first, spec, process_width=0, evidence=True)
    second_sparse = detect_color_grid(second, spec, process_width=0, evidence=True)
    evidence = PaperGridEvidence(spec)
    first_status = evidence.add(first_sparse)
    final_status = evidence.add(second_sparse)
    check("one sparse frame cannot save a map", not first_status.ready,
          first_status.describe())
    check("two consistent gantry frames produce ready evidence", final_status.ready,
          final_status.describe())
    check("evidence preserves physical/virtual distinction",
          final_status.verified_cells < spec.cols * spec.rows,
          f"{final_status.verified_cells} physical")
    evidence_workspace = WorkspaceMap.from_grid(
        grid, evidence.calibration.workspace_corners(grid, "firmware"),
        image.shape[1::-1], {"test": "evidence"})
    check("ready evidence produces a normal workspace map",
          evidence_workspace.cell_at(evidence.calibration.cell_center(4, 3),
                                    image.shape[1::-1]) == (4, 3))
    evidence_view = image.copy()
    draw_paper_evidence(evidence_view, evidence, detail=True)
    check("evidence overlay draws measured and virtual cells",
          not np.array_equal(evidence_view, image))
except ColorGridError as exc:
    check("complementary gantry evidence is accepted", False, str(exc))


# The same evidence and partial-cell rules are not vertical special cases.
# Horizontal's long stack is the harder layout: its left/right boundaries span
# 16 short-side cells, so the scaled evidence gate needs eight real anchors on
# each instead of reusing vertical's literal three.
horizontal_evidence_image, horizontal_evidence_centres = render_sheet(
    horizontal_spec, 6, 18)

def hide_horizontal_cells(source, row, columns):
    result = source.copy()
    y = round(horizontal_evidence_centres[(3, row)][1])
    left = round(horizontal_evidence_centres[(min(columns), row)][0] - 62)
    right = round(horizontal_evidence_centres[(max(columns), row)][0] + 62)
    cv2.rectangle(result, (left, y - 22), (right, y + 22), PAPER_BGR, -1)
    return result


horizontal_sparse_image = hide_horizontal_cells(
    horizontal_evidence_image, 8, range(1, 5))
try:
    detect_color_grid(horizontal_sparse_image, horizontal_spec, process_width=0)
    check("horizontal gantry-split frame stays refused in strict mode", False)
except ColorGridError:
    check("horizontal gantry-split frame stays refused in strict mode", True)
try:
    horizontal_sparse = detect_color_grid(
        horizontal_sparse_image, horizontal_spec, process_width=0, evidence=True)
    horizontal_evidence = PaperGridEvidence(horizontal_spec)
    first_status = horizontal_evidence.add(horizontal_sparse)
    final_status = horizontal_evidence.add(horizontal_sparse)
    check("horizontal evidence keeps its scaled 64-cell coverage gates",
          not first_status.ready and final_status.ready,
          final_status.describe())
    check("horizontal evidence requires eight anchors on each long edge",
          final_status.edge_cells[:2] >= (8, 8), final_status.describe())
except ColorGridError as exc:
    check("horizontal evidence pooling is accepted", False, str(exc))


# --- 7b. multi sub-grid selection and frame-border discard -----------------

from vision.color_grid import DEFAULT_EDGE_MARGIN  # noqa: E402

# An oversized sheet: three spare columns AND three spare rows past the 7x6
# vertical map. The window search must offer sub-grids shifted on BOTH axes,
# not just short-axis shifts anchored to one long edge.
big_image, _big_centres = render_sheet(spec, 10, 9, margin_cm=2.0)
big_windows = detect_color_grids(big_image, spec, process_width=0, edge_margin=0)
check("an oversized sheet yields several sub-grid windows",
      len(big_windows) >= 4, f"{len(big_windows)} windows")
big_origins = {w.cell_center(0, 0) for w in big_windows}
_ox = {round(p[0], 1) for p in big_origins}
_oy = {round(p[1], 1) for p in big_origins}
check("sub-grid windows are offset on both axes",
      len(_ox) > 1 and len(_oy) > 1,
      f"{len(_ox)} distinct X origins, {len(_oy)} distinct Y origins")
check("window 0 is the one nearest image bottom-left",
      big_windows[0].cell_center(0, 0)[0] <= min(p[0] for p in big_origins) + 1
      and big_windows[0].cell_center(0, 0)[1] >= max(p[1] for p in big_origins) - 1,
      str(big_windows[0].cell_center(0, 0)))
check("a max_windows cap bounds the choice list",
      len(detect_color_grids(big_image, spec, process_width=0, edge_margin=0,
                             max_windows=3)) == 3)

# Exactly the 7x6 map, printed so its outer ring sits ~0.3 cm from the frame
# edge. At edge_margin=0 it calibrates; at the aggressive default the border
# cells are discarded and no full window survives.
tight_image, _tc = render_sheet(spec, spec.cols, spec.rows, margin_cm=0.3)
tight_ok = detect_color_grid(tight_image, spec, process_width=0, edge_margin=0)
check("a frame-filling sheet calibrates with the border margin off",
      len(tight_ok.found_cells) == spec.cols * spec.rows,
      f"{len(tight_ok.found_cells)} cells")
try:
    detect_color_grid(tight_image, spec, process_width=0,
                      edge_margin=DEFAULT_EDGE_MARGIN)
    check("the aggressive border margin refuses a frame-filling sheet", False,
          "it was accepted")
except ColorGridError as exc:
    check("the aggressive border margin refuses a frame-filling sheet",
          exc.stage in ("window", "fit"), str(exc)[:80])

# A sheet with a comfortable border keeps every cell even at the aggressive
# default: the margin discards cells near the FRAME edge, not interior ones.
roomy_image, _rc = render_sheet(spec, spec.cols, spec.rows, margin_cm=6.0)
roomy = detect_color_grid(roomy_image, spec, process_width=0,
                          edge_margin=DEFAULT_EDGE_MARGIN)
check("a well-framed sheet keeps every cell at the aggressive default",
      len(roomy.found_cells) == spec.cols * spec.rows
      and not any(c.edge_clipped for c in roomy.found_cells.values()),
      f"{len(roomy.found_cells)} cells")


# --- 8. the training captures, when they are there --------------------------

# The user's root-level live capture intentionally has no overlay baked into
# it.  It is an 11-column physical sheet, so there must be two overlapping
# 10-column choices.  The absolute-left choice loses one underlit edge contour;
# the larger lattice still constrains it, and both choices must be exposed.
capture_dir = Path(__file__).resolve().parents[1] / "captures"
live_raw = next((path for path in (
    capture_dir / "RAW.png",
    capture_dir / "live_feed_no_grid.png",
) if path.exists()), None)
if live_raw is not None:
    raw = cv2.imread(str(live_raw))
    try:
        choices = detect_color_grids(raw, spec, process_width=0)
        check("raw live capture exposes exactly two 7x6 windows",
              len(choices) == 2, f"found {len(choices)}")
        if len(choices) >= 2:
            left, shifted = choices[:2]
            check("raw candidate 1 is the absolute-left grid",
                  left.cell_center(0, 0)[0] < shifted.cell_center(0, 0)[0],
                  f"origins {left.cell_center(0, 0)}, {shifted.cell_center(0, 0)}")
            overlap_error = max(
                np.linalg.norm(np.asarray(left.cell_center(col + 1, row))
                               - np.asarray(shifted.cell_center(col, row)))
                for col in range(spec.cols - 1) for row in range(spec.rows)
            )
            check("the two raw candidates agree on their nine-column overlap",
                  overlap_error < 0.75, f"max {overlap_error:.3f} px")
            check("the underlit left window retains strong physical coverage",
                  left.metrics.window_observed >= 59,
                  f"{left.metrics.window_observed}/60")
            left_map, left_saved = paper_workspace_map(
                raw, spec, grid, {"test": "left-choice"}, "firmware", 0)
            shifted_map, shifted_saved = paper_workspace_map(
                raw, spec, grid, {"test": "shifted-choice"}, "firmware", 1)
            check("the map writer honours the selected detected window",
                  left_saved.metrics.window_index == 0
                  and shifted_saved.metrics.window_index == 1
                  and left_map.corners != shifted_map.corners)

        # A multiplicative illumination gradient preserves ink chromaticity but
        # used to erase the absolute-left window through its fixed brightness
        # and all-60-cells gates.  Darken image top-left to 35% and demand the
        # same two choices.
        height, width = raw.shape[:2]
        yy, xx = np.mgrid[:height, :width]
        radius = np.sqrt((xx / max(width - 1, 1)) ** 2
                         + (yy / max(height - 1, 1)) ** 2)
        illumination = 0.35 + 0.65 * np.clip(radius / 1.1, 0.0, 1.0)
        shadowed = np.clip(raw.astype(np.float32) * illumination[..., None],
                           0, 255).astype(np.uint8)
        shadow_choices = detect_color_grids(shadowed, spec, process_width=0)
        check("both grids survive a severe top-left lighting gradient",
              len(shadow_choices) == 2,
              f"found {len(shadow_choices)} with "
              f"{[c.metrics.window_observed for c in shadow_choices]} cells")
    except ColorGridError as exc:
        check("raw live capture multi-window detection", False, str(exc))
else:
    print("skip  RAW.png: not present (captures/ is gitignored)")


# --- 9. older training captures, when they are there ------------------------
#
# These JPEGs are photographs of the PRE-6cm printed sheet (2.2 x 7.5 cm blocks,
# 0.5 cm gaps, many more coordinates). They cannot match the current 7x6 / 3x11
# specs and are kept only as a skip until a new sheet is printed and shot. When
# a new capture lands, drop this guard and restore the fit/refuse assertions.

training = Path(__file__).resolve().parents[1] / "captures" / "grid_training"
cases = (
    ("original_image_VERTICAL.jpeg", True),
    ("original_image_HORZONTIAL.jpeg", False),
)
for name, should_fit in cases:
    path = training / name
    if not path.exists():
        print(f"skip  {name}: not present (captures/ is gitignored)")
        continue
    print(f"skip  {name}: photograph of the pre-6cm sheet; reshoot after reprint")

raise SystemExit(1 if failed else 0)

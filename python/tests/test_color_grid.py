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

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.grid import MachineGrid
from rig.workspace import WorkspaceMap
from vision.color_grid import (
    ColorGridError,
    ColorGridSpec,
    color_masks,
    detect_color_grid,
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


# --- 1. an upright sheet, printed oversized and clipped on two edges --------

image, centers = render_sheet(spec, 13, 8, clip_cm=(1.2, 4.0))
calibration = detect_color_grid(image, spec, process_width=0)
check("upright sheet fits the 10x6 grid",
      (calibration.spec.cols, calibration.spec.rows) == (10, 6),
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
check("exactly 60 cells are mapped", len(mapped) == 60, str(len(mapped)))
check("every mapped cell is whole", all(cell.full for cell in mapped.values()))


# --- 2. the same sheet, tilted and in perspective ---------------------------

warp = perspective(600, 900, shear=0.05, squeeze=0.04, angle=7.0, scale=0.82,
                   offset=(40, 30))
image, centers = render_sheet(spec, 13, 8, clip_cm=(1.2, 4.0), warp=warp,
                              size=(760, 1000))
calibration = detect_color_grid(image, spec, process_width=0)
check("tilted sheet still fits the grid",
      len(calibration.found_cells) == 60, calibration.describe())
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

sheet, _ = render_sheet(spec, 13, 8, clip_cm=(1.2, 4.0))
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
          len(found.found_cells) == 60 and found.metrics.parity_agreement == 1.0,
          found.describe())
except ColorGridError as exc:
    check("rail-shaped colour clutter cannot steer the sheet lattice", False,
          str(exc)[:90])


# A geometrically perfect but single-colour array is not the printed target.
# Parity is an acceptance gate, not merely a number in the status bar.
monochrome, _ = render_sheet(spec, 13, 8, clip_cm=(1.2, 4.0),
                             green=GREEN_BGR, magenta=GREEN_BGR)
try:
    detect_color_grid(monochrome, spec, process_width=0)
    check("a lattice with broken colour parity is refused", False, "it was accepted")
except ColorGridError as exc:
    check("a lattice with broken colour parity is refused",
          exc.stage == "quality" and "parity" in str(exc), str(exc)[:90])


# --- 3. the sheet turned a quarter turn -------------------------------------

image, _ = render_sheet(spec, 13, 8, clip_cm=(1.2, 4.0))
turned = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
calibration = detect_color_grid(turned, spec, process_width=0)
check("a quarter-turned sheet is still 10 columns x 6 rows",
      len(calibration.found_cells) == 60, calibration.describe())
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
    detect_color_grid(image, spec, process_width=0)
    check("a sheet with too few rows is refused", False, "it was accepted")
except ColorGridError as exc:
    check("a sheet with too few rows is refused",
          "4 whole cells along the 7.5 cm side where 6 are needed" in str(exc),
          str(exc)[:80])

blank = np.full((400, 600, 3), TABLE_BGR, np.uint8)
try:
    detect_color_grid(blank, spec, process_width=0)
    check("an empty frame is refused", False, "it was accepted")
except ColorGridError as exc:
    check("an empty frame is refused", True, str(exc)[:70])


# --- 5. gaps are gaps -------------------------------------------------------

image, _ = render_sheet(spec, 13, 8, clip_cm=(1.2, 4.0))
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
for col in range(1, grid.cols + 1):
    for row in range(1, grid.rows + 1):
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
# `pitch - start` and at `block / 2` in printed centimetres, so the gap between
# them moves with grid.trim_*. Pinning a number here would just re-fail every
# time a trim is measured on the rig.
expected_cm = float(np.hypot(
    spec.pitch_x_cm - grid.x_start_cm - spec.block_x_cm / 2,
    spec.pitch_y_cm - grid.y_start_cm - spec.block_y_cm / 2))
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


image, _ = render_sheet(spec, 13, 8, clip_cm=(1.2, 4.0))
for name, gains in (("magenta cast", (1.18, 0.72, 1.24)),
                    ("blue cast", (1.35, 0.95, 0.72)),
                    ("warm cast", (0.70, 0.95, 1.30))):
    tinted = cast(image, gains)
    try:
        found = detect_color_grid(tinted, spec, process_width=0)
        check(f"detection survives a {name}", len(found.found_cells) == 60,
              found.describe())
    except ColorGridError as exc:
        check(f"detection survives a {name}", False, str(exc)[:70])

# The synthetic inks above are more saturated than real print under the rig's
# own lighting, so they survive a cast on the widened hue windows alone. Repeat
# the check with the colours actually measured off the live rig frame - green
# ink BGR (168,136,136), magenta (153,99,160), paper (195,167,183) - which is
# where the balance stops being a nicety.
faded = render_sheet(spec, 13, 8, clip_cm=(1.2, 4.0), green=(168, 136, 136),
                     magenta=(153, 99, 160), paper=(195, 167, 183))[0]
unbalanced, _ = color_masks(faded, balance=False)
balanced, _ = color_masks(faded, balance=True)
check("without balancing, real rig ink colours lose the green cells",
      unbalanced.sum() < balanced.sum() / 4,
      f"{int(unbalanced.sum())} px unbalanced vs {int(balanced.sum())} balanced")
try:
    found = detect_color_grid(faded, spec, process_width=0)
    check("with balancing, real rig ink colours still fit the grid",
          len(found.found_cells) == 60, found.describe())
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

image, _ = render_sheet(spec, 13, 8, clip_cm=(1.2, 4.0))
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

image, centres = render_sheet(spec, 13, 8)

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


# --- 8. the training captures, when they are there --------------------------

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
    frame = cv2.imread(str(path))
    try:
        found = detect_color_grid(frame, spec, process_width=0)
        check(f"{name} fits the grid" if should_fit
              else f"{name} is refused", should_fit,
              found.describe())
        if should_fit:
            check(f"{name} residual is small",
                  found.metrics.residual_px < 2.0,
                  f"{found.metrics.residual_px:.2f} px")
            check(f"{name} colour parity is consistent",
                  found.metrics.parity_agreement == 1.0)
    except ColorGridError as exc:
        check(f"{name} fits the grid" if should_fit
              else f"{name} is refused", not should_fit, str(exc)[:70])

raise SystemExit(1 if failed else 0)

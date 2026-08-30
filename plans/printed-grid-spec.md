# The printed calibration grid — required behaviour

What the printed colour grid is **supposed to do**, written as checkable
requirements rather than as a description of the code. This is the spec.
[printed-color-grid.md](printed-color-grid.md) is the companion: how it
actually works, and the measurements behind it.

Read this one when deciding whether a change is still correct. Read that one
when working out why the code does something.

---

## 1. The problem this exists to solve

Calibrating the overhead camera against the rig by hand does not work well
enough. The lens is a 160° fisheye and still carries a slight bow after
correction, so lining the camera up with the Arduino's grid by eye is somewhere
between very difficult and impossible — and the four-clicked-corners route
(`rig/workspace.py`) asks an operator to aim at a rectangle that is not visible
in the picture at all.

The fix is to make the rectangle visible: print the machine's own grid, put it
in the work area, and let the camera measure it.

---

## 2. The physical artefact

The current artefact is one A2 landscape combined target. Its 8 × 10
chromatic fiducial lattice is defined in `vision/combined_grid.py`: 6.0 × 2.2
cm bars, 0.8 cm X gaps, 1.6 cm Y gaps, starting 0.8 cm from page left and 4.8
cm from page bottom. The physical lower-left page corner is placed at holder
home. One page-plane fit calibrates either mode; the active `MachineGrid` and
mode-keyed workspace-map entry remain separate. Beige is nonessential visual
information and calibration must survive its disappearance into white paper.

The following is the retained legacy-sheet contract. These sheets remain a
fallback and the evidence-assisted route still uses them.

A printed sheet of alternating **green** and **magenta** blocks on white paper.

| property | value | why |
| --- | --- | --- |
| cell size | vertical **2.2 × 7.5 cm**; horizontal **7.5 × 2.2 cm** | that mode's own `grid.modes.<mode>.block_x_cm` × `block_y_cm` |
| inner margin | **0.5 cm** between any two blocks | that mode's `gap_x_cm` / `gap_y_cm` |
| colours | strong green and strong magenta, alternating like a chessboard | far apart in hue; the alternation is a free consistency check |
| size | **larger than the grid**, deliberately | so it works at any camera height without reprinting |

Training captures live in `python/captures/grid_training/` (gitignored):
`original_image_VERTICAL.jpeg` and `original_image_HORZONTIAL.jpeg` — the same
A2 sheet photographed two ways round.

---

## 3. Required behaviour

### R1 — Detect the sheet and fit a grid to it

Given any frame containing the sheet, produce a mapping from `[col,row]` to
image pixels and back.

**Accept when:** `detect_color_grid()` returns a calibration whose cell
polygons land on the printed blocks, at sub-2-pixel mean residual on the
training capture.

### R2 — Full-sized cells only

Only whole printed cells may take part in calibration or in the grid's maths.
Cells clipped by the edge of the paper or the edge of the frame are **not part
of the project** and must contribute nothing — not to the fit, not to the
numbering, not to the geometry. A gantry-covered cell is equally not an
observation.

**Accept when:** the strict single-frame route maps only whole cells; partial
cells are detected, classified as partial, and excluded. A frame that cannot
supply enough whole cells is **refused**, never approximated. The separate
evidence route in R12 may pool whole cells from several fixed-camera frames;
its virtual cells are permitted only after the boundary/coverage gates there
pass.

### R3 — Margins

- The **inner** 0.5 cm margins are real white paper and must be reproduced by
  the virtual grid. A pixel in a gap belongs to no cell.
- The **outer** margin of the sheet is not part of the project and is never
  measured. The grid ends at the outer edge of the last whole block, with no
  trailing margin — the same way the machine's grid ends at the last block edge.

**Accept when:** `cell_at()` returns `None` inside an inner margin, and
`outline()` traces the outer edges of the corner blocks rather than a
pitch-sized border.

### R4 — Grid size and origin

Vertical is **10 columns × 6 rows** (`0..9`, `0..5`); horizontal is **4 columns
× 16 rows** (`0..3`, `0..15`). Both are the complete coordinate map including
zero, matching the active firmware layout. A sheet starts at `[0,0]` with **no
outer margin**, with inner margins between every pair of neighbours.

`[0,0]` is the cell nearest the **bottom-left of the image**. Both indices
increase away from that corner.

**Accept when:** exactly 60 vertical or 64 horizontal cells are mapped,
`[0,0]` is the bottom-left corner cell, and raising either index moves away
from it.

### R5 — Which axis is X

Decided by **the explicit mode plus cell size, never by image direction**. The
2.2 cm and 7.5 cm sides are 3.4:1 apart. Vertical maps the short side to X
(10) and the long side to Y (6); horizontal maps the long side to X (4) and
the short side to Y (16). A quarter-turned camera changes neither assignment.

**Accept when:** rotating the input frame 90° leaves the column/row assignment
unchanged.

### R6 — A modular core, reusable on any camera feed

The detector must be a library like `vision/block_detector.py`: no camera, no
window, no argument parsing. Takes a frame, returns geometry.

**Accept when:** `vision/color_grid.py` imports nothing that opens a device,
and the same function serves the still-image tool, the live tool, both feeds
and the tests.

### R7 — A dedicated verification tool

A script that opens the camera, colours every detected cell and labels it with
its `[col,row]`, so detection can be confirmed by eye.

**Accept when:** `camera/color_grid_check.py` runs live *and* on a still
(`--image`), tints and labels every mapped cell, distinguishes whole cells
outside the chosen window from clipped ones, and never writes a calibration.

### R8 — Overlay mode in every grid-based camera tool

Any tool that draws the machine grid must be able to show the printed-sheet
overlay too, so the fitted grid can be compared against the ink underneath it.

**Accept when:** `p` toggles the overlay in both `gridded_camera_feed.py` and
`rig_build_v1.py`, drawn by the same shared code as the standalone tool.

### R9 — A calibrate button

A separate control that derives the calibration from the physical sheet and
saves it.

**Accept when:** `k` writes the same `config/workspace_map.json` that the
four-click route writes, in the same format, with the same invalidation rules —
nothing downstream learns that the sheet exists. In `rig_build_v1.py` it
carries every guard `c` carries: refused during a build, refused on a stale
camera, and it clears the current selection.

### R10 — Never fail silently

A refusal must still show what was found and say what to do about it.

**Accept when:** a failed detection still draws its candidate blobs (green for
those that reached a lattice, red for those that did not) with the failing
stage, and the message names which axis is short and whether the cause is
framing or occlusion.

### R11 — Survive the camera's colour

The rig's camera has a colour cast strong enough to move the green ink to hue
120 — cyan — below the saturation floor, making half of every sheet invisible.
Detection must not depend on the camera having been colour-calibrated first,
because the state someone is in when they first reach for this tool is exactly
"nothing is calibrated".

**Accept when:** the detector white balances internally before segmenting, and
a synthetic sheet under a magenta, blue or warm cast still fits the grid.

### R12 — Evidence-assisted calibration through a gantry occlusion

The gantry is allowed to hide *interior* cells. The non-moving gridded camera
feed must be able to collect whole detected cells from multiple manually
accepted frames while the camera and paper remain fixed, then fit the unseen
interior cells virtually.

**Accept when:** `e` starts a fresh session, Space accepts one frame, and `k`
writes the ordinary mode-keyed `workspace_map.json` only after at least two
accepted frames (each later frame overlapping four earlier physical cells), at
least 60% of that mode's physical cells (36/60 vertical; 39/64 horizontal), all
four corner regions, at least half of each short edge and 30% of each long edge,
<=2 px mean / <=6 px max merged residual and <=3 px cross-frame spread.
Physical cells are solid green; virtual cells are amber and dashed. `x`
abandons the session without changing the previously saved map. The feature
must never command the rig.

---

## 4. Explicitly out of scope

These are **not** bugs. They were specified as excluded.

| thing | why |
| --- | --- |
| partial cells | not part of the project; see R2 |
| the sheet's outer margin | not accounted for at all; see R3 |
| making a bad frame work anyway | a wrong calibration written to disk is worse than no calibration; refusing is correct |
| cells covered by something in a single frame | strict detection cannot invent them; use R12 only when the outer boundaries can be observed across evidence frames |

---

## 5. Two machine layouts, not camera rotations

The detector supports both calibrated machine layouts. `ColorGridSpec` takes a
mode explicitly and `SUPPORTED_LAYOUTS` records vertical's
`y-along-block-length` and horizontal's `x-along-block-length`; neither is
inferred from a partial view. Its count and geometry must agree with the active
`MachineGrid` before a workspace map can be made. This is distinct from a
rotated camera, which the homography handles in either mode.

---

## 6. Ambiguities in the spec, and how they were resolved

Recording these because each one could reasonably have gone the other way, and
a future reader will otherwise assume the current answer was obvious.

### A1 — Which training image is "the vertical one"

The spec said *"only calibrate on the vertical"* and also *"the 7.5 cm is on
the Y side"*, and the two filenames appear to say the opposite of each other.

Resolved by geometry, not by the filename. A 10 × 6 grid needs **6 whole cells
along the 7.5 cm axis**. `original_image_VERTICAL.jpeg` has 7; the horizontal
one has 5. Only one of the two can hold the grid at all, and it is the one the
spec named. The rule *"the 7.5 cm side is Y"* is what the code implements; the
filenames are not consulted.

### A2 — The sheet and the firmware lay out coordinate zero differently

**The single most important thing in this document.**

The sheet prints a real 2.2 × 7.5 cm block at coordinate zero. The firmware
does not: its zero is the home *point*, with only a 0.5 cm gap before cell 1.

```text
sheet X = 10 × 2.2 + 9 × 0.5 = 26.5 cm      rig X = 9 × 2.7 = 24.3 cm
sheet Y =  6 × 7.5 + 5 × 0.5 = 47.5 cm      rig Y = 5 × 8.0 = 40.0 cm
```

So the printed grid is one block wider on X and one block taller on Y than the
machine's grid. Laying the sheet's `[0,0]` on the machine's home and expecting
`[5,3]` to match puts every block **1.1 cm out on X and 3.75 cm out on Y**.

Resolved by making it an **explicit, switchable convention** rather than an
assumption, defaulting to the one that makes the rig place blocks where the
paper says:

| `--home-convention` | machine origin at | effect |
| --- | --- | --- |
| `firmware` *(default)* | the far corner of printed `[0,0]` | printed `[c,r]` lands exactly on the firmware's `[c,r]` for all 45 positive cells |
| `printed` | the centre of printed `[0,0]` | every printed cell taken at face value; positive cells sit 1.1 cm (X) / 3.75 cm (Y) further from home |

**Since then**, `config/rig.json` gained `grid.trim_y_cm = 3.75`, which shifts
the machine's grid to agree with the sheet on Y and collapses the disagreement
to the 1.1 cm on X. The two conventions therefore now differ by whatever the
trims say, not by a fixed number — which is why
`tests/test_color_grid.py` derives the expected offset from the grid rather
than hard-coding it.

### A3 — Which 10 × 6 window of an oversized sheet

The sheet holds far more cells than the grid needs. Resolved by taking the
block of whole cells whose corner is nearest the **bottom-left of the image**,
which makes `[0,0]` land where an operator expects without another setting to
get wrong.

---

## 7. Where each requirement lives

| | implemented in |
| --- | --- |
| R1, R2, R3, R4, R5, R11 | `python/vision/color_grid.py` |
| R6 | the same file — no camera, window or argv anywhere in it |
| R7 | `python/camera/color_grid_check.py` |
| R8, R10 | `python/vision/color_grid_overlay.py`, driven from all three tools |
| R9 | `paper_workspace_map()` in `python/camera/gridded_camera_feed.py`, used by both feeds |
| R12 | `vision/grid_evidence.py` and the `e` / Space / `k` flow in `gridded_camera_feed.py` |
| two layouts | `SUPPORTED_LAYOUTS`, `ColorGridSpec.mode`, and the count/geometry refusal |
| A2 | `ColorGridCalibration.workspace_corners()` |

Rules that must not drift: **AGENTS.md §3d** (the sheet carries a copy of the
block geometry and must be reprinted when that changes) and **§3e** (the camera
colour correction is applied in four places).

---

## 8. Status

Verified on the training captures, on synthetic sheets rendered at known
homographies, and on one real frame from the rig.

| requirement | status |
| --- | --- |
| R1 detect and fit | done — 1.13 px mean residual on the training capture |
| R2 whole cells only | done — partials excluded; short frames refused |
| R3 margins | done — inner margins return `None`, outer never measured |
| R4 10 × 6 / 4 × 16, `[0,0]` bottom-left | done |
| R5 axis from explicit mode + cell size | done — survives a 90° input rotation |
| R6 modular core | done |
| R7 verification tool | done — live path **not verified on hardware** |
| R8 overlay in both feeds | done — live path **not verified on hardware** |
| R9 calibrate button | done — live path **not verified on hardware** |
| R10 never fail silently | done |
| R11 survive the colour cast | done |
| R12 evidence-assisted gantry occlusion | done — synthetic occlusion test; live Pi path needs hardware verification |
| two machine layouts | done — synthetic horizontal checks; Pi camera path unverified |

**What is not verified:** anything that needs the Pi's camera. Camera code
cannot be exercised on the dev desktop (AGENTS.md, "Environment rules"), so the
live paths in `color_grid_check.py`, `gridded_camera_feed.py` and
`rig_build_v1.py` are checked by importing them, by driving their helpers
headlessly in `tests/test_color_grid.py`, and by running the detector on real
captured frames — not by running them against a camera.

**The known blocker on the rig right now:** the captures show a gantry/cables
and clipped sheet boundaries. R12 can tolerate an interior occlusion, but it
will still refuse until evidence frames physically cover all four workspace
edges and corner regions. See
[Evidence-Assisted Printed-Grid Calibration](evidence-assisted-printed-grid-calibration.md).

---

## 9. Related

- [printed-color-grid.md](printed-color-grid.md) — how the detection works, the
  colour measurements, and the reading of a bad result
- `python/GUIDE.md` → `color_grid_check.py` — how to run it
- AGENTS.md §3a — the block/gap geometry both the sheet and the firmware copy
- AGENTS.md §3d — reprinting the sheet when that geometry changes
- AGENTS.md §3e — the camera colour correction, which grew out of R11

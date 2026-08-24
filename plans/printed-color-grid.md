# The printed colour calibration grid

A sheet of alternating green and magenta blocks, printed at the rig's own cell
geometry, that the camera can measure instead of an operator having to aim at
an invisible rectangle.

Implemented by `python/vision/color_grid.py` (geometry),
`python/vision/color_grid_overlay.py` (drawing),
`python/camera/color_grid_check.py` (a tool that does nothing but prove it
works), and the `p`/`k` keys in `camera/gridded_camera_feed.py` and
`camera/rig_build_v1.py`.

---

## The sheet

Each printed cell is **7.5 × 2.2 cm** with **0.5 cm** of white between
neighbours — the block footprint and gap from `config/rig.json`, so the paper
and the machine are describing the same grid. Colours alternate like a
chessboard, which costs nothing to print and gives the detector a free
consistency check: if a cell's colour disagrees with the parity of its index,
the indices are wrong.

The sheet is deliberately printed **larger than the machine's grid**. An A2
print holds roughly 22 × 5 cells one way round and 15 × 7 the other, and the
machine needs 10 × 6. That surplus is what makes the sheet usable at any camera
height without reprinting it — and it is why choosing which cells count is half
the problem.

### What is not part of the project

* **Partial cells.** Any block clipped by the edge of the paper or the edge of
  the frame. Their centres and sizes are both wrong, so they are excluded from
  the fit entirely rather than down-weighted.
* **The outer white margin.** The sheet has one; the grid does not. The grid
  ends at the outer edge of the last whole block, with no trailing margin, the
  same way the machine's grid ends at the last block edge.
* **Inner margins are real.** The 0.5 cm between blocks is white paper, not a
  rounding artefact. `cell_at()` returns `None` there instead of naming the
  nearer block, because quietly absorbing the gap would widen every cell by a
  quarter of a gap.

---

## How the fit works

0. **The frame is white balanced first**, driving its bright quantile to
   neutral. See [Colour, and why this is not optional](#colour-and-why-this-is-not-optional).
1. **Two hue windows** segment the inks. Hue plus a saturation floor rather
   than brightness: the two inks stay far apart in hue (green at 80-88 in
   OpenCV's 0-179 scale in a clean capture, 101 in a balanced rig frame;
   magenta at 150-162; nothing in between).
2. **Each blob becomes a rotated rectangle.** Their long-axis directions are
   averaged as doubled angles, which is insensitive to a 180° flip, giving one
   global sense for "along the 7.5 cm side". Without this, neighbouring cells
   disagree about which way is up and the walk below breaks.
3. **A breadth-first walk** hands out integer lattice indices, hopping from
   cell to cell using *that cell's own* measured size times the known
   pitch/block ratio. Only near-median cells propagate the walk, so a clipped
   block cannot steer it. Everything is local, which is why perspective does
   not accumulate across the frame.
4. **A homography is fitted** from integer indices to cell centres; every cell
   is re-scored against the footprint the fit predicts *for it*; the fit is
   repeated on the survivors. A local prediction is what lets one fullness
   threshold work across a tilted sheet where cells at one edge are genuinely
   smaller than at the other.
5. **A 10 × 6 window of whole cells is chosen**, anchored at the corner nearest
   the bottom-left of the image. That corner becomes `[0,0]`.

### Which axis is X

Never from the image. The 2.2 cm and 7.5 cm sides are 3.4:1 apart, so the axis
with the shorter pitch is the machine's X and the other is Y, whichever way the
sheet was photographed. Columns therefore follow the 2.2 cm side and rows the
7.5 cm side even when the camera is remounted a quarter turn out.

### What is deliberately not handled yet

The sheet laid out so the **machine's** X runs along the 7.5 cm cell side — a
rotated machine, not a rotated camera. `SUPPORTED_LAYOUT` names the one
supported layout and detection refuses anything else rather than guessing.
Adding it means deciding what the firmware's `B <col> <row>` should mean in
that orientation, which is a rig decision and not a vision one.

---

## Colour, and why this is not optional

The first live frame from the rig detected **nothing at all**, and it is worth
recording why, because the failure was invisible from the outside.

The camera's white balance had put a heavy magenta cast over the whole scene.
Measured off that frame:

| what | HSV, raw | HSV, white balanced |
| --- | --- | --- |
| green ink | **(120, 49, 168)** | (101, 48, 160) |
| magenta ink | (153, 97, 160) | (155, 75, 153) |
| white paper | (137, 37, 195) | (98, 15, 186) |
| the wall behind the rig | (139, 78, 176) | (135, 53, 168) |

The green ink had moved to hue **120 — cyan, not green** — with saturation 49.
It missed the green hue window *and* fell under the saturation floor, so half
of every sheet was simply not there. Worse, the pink **wall** landed inside the
magenta window with saturation 78, so the frame had plenty of "ink" in it, none
of it on the sheet.

Absolute hue windows cannot survive an arbitrary camera white balance, so the
detector now normalises first. `white_balance()` scales each channel so the
frame's 92nd-percentile brightness is neutral — white-patch rather than
grey-world, because the sheet's white paper is the brightest large thing in
frame and therefore a real white reference, whereas grey-world would be dragged
around by how much of the frame the pink ink happens to cover. It costs ~3 ms
on a 1296 × 972 frame (a lookup table, not a float pass), and it no-ops on a
frame that is already neutral.

The thresholds moved with it: green `(58, 115)`, magenta `(130, 178)`,
saturation floor `32`. The floor sits between the rig's green ink at 48 and its
white paper at 15.

The wall and the aluminium rails still register as "magenta" under that cast.
That is left alone deliberately — they are not a lattice of 2.2 × 7.5 cm
blocks, so the lattice walk discards them, and an over-inclusive mask costs
nothing while an under-inclusive one costs everything.

**This is worth fixing at the camera too.** A cast that severe also degrades
`block_detector.py`, which keys on red-minus-blue. `camera_studio.py` is where
the white balance and gains are tuned and saved.

---

## The one place the paper and the firmware disagree

**This is worth reading before trusting a saved calibration.**

The sheet prints a real block at every coordinate, coordinate zero included, so
its 10 × 6 layout is 10 blocks across:

```text
sheet X:  |block|gap|block|gap| ... |block|      = 10 x 2.2 + 9 x 0.5 = 26.5 cm
sheet Y:  same with 7.5/0.5                      =  6 x 7.5 + 5 x 0.5 = 47.5 cm
```

The firmware's coordinate zero is not a block. It is the home *point*, with
only the 0.5 cm gap between it and cell 1:

```text
rig X:    |0|gap|block|gap| ... |block|          = 9 x 2.7 = 24.3 cm
rig Y:    same with 7.5/0.5                      = 5 x 8.0 = 40.0 cm
```

So the printed sheet is one block wider on X and one block taller on Y than the
machine's grid. Laying the sheet's `[0,0]` block on the machine's home and
expecting cell `[5,3]` to land on the sheet's `[5,3]` block puts every block
**1.1 cm out on X and 3.75 cm out on Y**.

`workspace_corners()` therefore takes an explicit convention rather than
assuming one:

| convention | machine origin sits at | effect |
| --- | --- | --- |
| `firmware` *(default)* | the far corner of printed `[0,0]` | printed `[c,r]` lands exactly on the firmware's `[c,r]` for all 45 positive cells. Printed row/column zero are an anchor only — they are **not** where the firmware draws its axis-only lanes. |
| `printed` | the centre of printed `[0,0]` | every printed cell is taken at face value; positive cells sit 1.1 cm (X) and 3.75 cm (Y) further from home than the firmware puts them. |

Measured on the real capture, the `firmware` convention puts all 45 printed
cell centres within **0.0 px** of the machine's own cell centres, and the
`printed` convention offsets them by up to **131 px ≈ 3.9 cm**. The default is
the one that makes the rig place blocks where the paper says.

Switch with `--home-convention`, or with `h` in `color_grid_check.py`.

---

## Measured on the training captures

`python/captures/grid_training/` is gitignored, so these are recorded here
rather than in a test's expected output.

| capture | result |
| --- | --- |
| `original_image_VERTICAL.jpeg` (2048 × 1466) | 128 blobs, 111 on the lattice, **15 × 7 whole cells**, 10 × 6 grid fitted, mean residual **1.13 px** (max 5.67), colour parity **100 %** |
| `original_image_HORZONTIAL.jpeg` (1920 × 1061) | 132 blobs, **22 × 5 whole cells** — refused: 5 whole cells along the 7.5 cm axis cannot hold 6 rows |

A first live frame from the rig (1296 × 972, corrected feed) found 89 blobs
with 53 on the lattice, spread over 11 × 6 — but with holes from a cable lying
diagonally across the sheet and from the frame clipping the outer columns, so
the largest unbroken block was only 6 × 3. Refused, correctly. The sheet needs
to be moved into full view with the cable off it; the detector cannot invent
cells that are covered up.

The refusal is correct, not a limitation: that photo genuinely does not contain
six whole rows. The sheet is the same A2 print in both, just laid down the other
way, and only one of the two orientations has room for the grid. A live camera
looking straight down from 50 cm sees far more forgiving geometry than either.

---

## Using it

```bash
cd python

# prove the detection on a still, or live on the camera
../.venv/bin/python camera/color_grid_check.py --image captures/grid_training/original_image_VERTICAL.jpeg
../.venv/bin/python camera/color_grid_check.py

# the two feeds: p overlays the sheet, k calibrates from it and saves
../.venv/bin/python camera/gridded_camera_feed.py
../.venv/bin/python camera/rig_build_v1.py
```

`k` writes the same `config/workspace_map.json` the four-click route writes, in
the same format, with the same invalidation rules. Nothing downstream knows the
sheet exists. In `rig_build_v1.py` it is guarded exactly like `c`: refused
during a build, refused on a stale camera, and it clears the current selection.

The overlay tints every mapped cell and stamps its `col,row`; whole cells
outside the chosen window are outlined dull yellow and clipped ones red. Watch
the tint against the ink — a residual number cannot tell you *where* a fit went
wrong, and the tint can.

### Reading a bad result

**A refusal always still draws what it found** — the blobs that joined a
lattice in green, the ones that did not in red, with the count and the stage in
the corner. A blank window would make "the sheet is out of shot", "the colours
are wrong" and "the code never ran" look identical, which is precisely how the
first live attempt was reported as *no detection, no overlay, nothing*.

| what you see | what it means |
| --- | --- |
| `N whole cells along the 2.2 cm side where 10 are needed … Move the sheet or the camera` | genuinely not enough sheet in view. The named side says which way to move. |
| `… The sheet is big enough in view, so the gaps are holes` | enough cells, but something punched holes in them — a cable lying across the sheet, or an edge clipping a row. Clear the sheet rather than moving it. |
| `only N coloured blocks visible` | the sheet is not in frame, or the colours are being lost. Look at the drawn blobs: many blobs means a colour problem, almost none means a framing one. |
| `they do not form a regular lattice` | blobs found, but not in a grid. Usually something else in view is ink-coloured and the sheet is mostly out of shot. |
| red blobs all over the walls and rails | normal under a colour cast; the lattice discards them. Only a problem if they outnumber the sheet. |
| parity below 100 % | the lattice indices are inconsistent. Distrust the fit even if the residual looks fine. |
| tint drifting off the ink at one corner | residual lens distortion, or the sheet is not flat. |
| `normalized workspace corners must lie inside the image` | the envelope the sheet implies runs off the frame. The sheet is too close to an edge to calibrate from. |

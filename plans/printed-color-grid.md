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

1. **Two hue windows** segment the inks. Hue plus a saturation floor rather
   than brightness: the two inks stay far apart in hue (green clusters at 80-88
   in OpenCV's 0-179 scale, magenta at 150-162, nothing in between) under
   whatever light the rig has.
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

| what you see | what it means |
| --- | --- |
| `cannot hold the 10x6 grid` | not enough whole cells in view. Move the sheet or the camera; the count in the message says which axis is short. |
| `only N coloured blocks visible` | the sheet is not in frame, or the light has pushed the inks below the saturation floor. |
| parity below 100 % | the lattice indices are inconsistent. Distrust the fit even if the residual looks fine. |
| tint drifting off the ink at one corner | residual lens distortion, or the sheet is not flat. |
| `normalized workspace corners must lie inside the image` | the envelope the sheet implies runs off the frame. The sheet is too close to an edge to calibrate from. |

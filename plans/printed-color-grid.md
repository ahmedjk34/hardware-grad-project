# The printed colour calibration grid

A sheet of alternating green and magenta blocks, printed at the rig's own cell
geometry, that the camera can measure instead of an operator having to aim at
an invisible rectangle.

**The required behaviour is specified in
[printed-grid-spec.md](printed-grid-spec.md)** — read that to decide whether a
change is still correct. This document is how it works and what was measured.

Implemented by `python/vision/color_grid.py` (geometry),
`python/vision/combined_grid.py` (the one-page target and legacy fallback),
`python/vision/color_grid_overlay.py` (drawing),
`python/camera/color_grid_check.py` (a tool that does nothing but prove it
works), the strict `p`/`k` routes in `camera/gridded_camera_feed.py` and
`camera/rig_build_v1.py`, and the evidence collector
`python/vision/grid_evidence.py`. The latter lives only in the non-moving
gridded feed: `e` starts it, Space accepts a frame and `k` saves once its
coverage gates pass. See
[Evidence-Assisted Printed-Grid Calibration](evidence-assisted-printed-grid-calibration.md).

---

## The current one-page target

The current printable artefact is
[`assets/combined-calibration-grid.svg`](assets/combined-calibration-grid.svg),
one A2 landscape page carrying both visible
block orientations. Detection treats its saturated green/magenta portions as
an **8 × 10 fiducial lattice**, not as 80 machine blocks:

| property | value |
| --- | --- |
| page | 59.4 × 42.0 cm, A2 landscape |
| fiducial bar | 6.0 × 2.2 cm, X thirds 2.2 + 1.6 + 2.2 cm |
| fiducial gaps | 0.8 cm X, 1.6 cm Y |
| lattice | 8 columns × 10 rows |
| first outer edge | 0.8 cm from page left, 4.8 cm from page bottom |
| machine registration | physical lower-left page corner = holder home |

The supplied `grad project grid white background.png` is 2245 × 1587 px
(37.79 px/cm). Away from one-pixel antialiased edges, a composite tile measures
227–228 px square. Its X runs are approximately 83 px muted chromatic/beige,
60 px dark chromatic or white, and 83 px muted chromatic/beige. Its Y runs are
approximately 83 px chromatic, 60 px beige/white/beige, and 83 px opposite
chromatic. Tiles repeat every 257 px in X (about 0.8 cm white separation) and
287 px in Y (the extra 60 px is the plain-white 1.6 cm separator). This measured
raster geometry is the source of the 2.2 + 1.6 + 2.2 cm internal model; it is
not inferred from the old detector comments.

The olive shades use a detector-local wider green hue window. The exact raster
is an 8 × 5 array of 6.0 × 6.0 cm composite tiles: two chromatic 2.2 cm bands
around one 1.6 cm interval. Dark same-colour center thirds in all 80 chromatic
bars encode vertical. Beige outer thirds with a white center in five sets of
row intervals encode horizontal, but only when valid opposite-colour rows
bracket them. The other four intervals are plain-white tile separators.

Detection first uses the full chromatic bars, then retries faded/cracked ink
with stronger mask closing. If those fills have nearly disappeared, the dark
centre accents are isolated with separate green and magenta Otsu thresholds
plus local saturation contrast. After fitting the homography it samples every
projected subregion and classifies green, purple or beige/gray using normalized
channel opponents, HSV saturation, Lab prototype distances and locally
adaptive thresholds. Decisions are aggregated across at least 60% of the 80
fiducials. Gray alone cannot vote: the fallback still has to pass the complete
8 × 10 chromatic geometry, alternating-colour parity, aspect and residual
gates. All 80
chromatic bars fit one page-coordinate homography; that same
fit yields the shared 24.3 × 40.0 cm holder envelope for either active mode.
The resulting `WorkspaceMap` is still saved under the active mode and embeds
that mode's independent block/gap/trim geometry.

The `firmware` home convention is mandatory for the combined target. The
`printed` convention below belongs only to the legacy real-block sheets.

`detect_printed_grids()` tries this target first and falls back to the two
legacy sheets. `PrintedGridEvidence` locks onto whichever target the first
accepted frame used, so the existing evidence-assisted route works for the
combined page too without mixing observations from two designs. Overlay labels
`Fcol,row` name fiducials rather than build cells.

Horizontal decoding uses the nearby 0.8 cm white X gap at the same image row as
a local paper reference. Both 2.2 cm outer thirds must separate from that paper
in Lab/density while staying weaker than their chromatic neighbors. The 1.6 cm
white center is checked directly first. If it is washed out, shadowed or
overprinted, it may be inferred only when the two outer thirds remain present,
the adjacent rows carry the expected opposite colors, and the same gap parity
wins across the sheet's five encoded intervals against its four plain
separators. Inferred cells are annotated `H~`; directly measured ones are `H`.

---

## The sheet

Each printed cell has the active mode's block footprint with **0.5 cm** of
white between neighbours: vertical is **2.2 × 7.5 cm**, horizontal is
**7.5 × 2.2 cm**. Both come from `config/rig.json`, so the paper and the
machine are describing the same grid. Colours alternate like a
chessboard, which costs nothing to print and gives the detector a free
consistency check: if a cell's colour disagrees with the parity of its index,
the indices are wrong.

The sheet is deliberately printed **larger than the machine's grid**. An A2
print holds more cells than the mapped window. Vertical maps 10 × 6; the
horizontal sheet maps 4 × 16 and is deliberately wider than that mapped extent.
That surplus is what makes the sheet usable at any camera height without
reprinting it — and it is why choosing which cells count is half the problem.

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
2. **Each blob becomes a rotated rectangle.** Broad aspect, area and colour-
   purity checks decide which rectangles may vote on the median size and
   long-axis direction. Rejected scene blobs are still drawn for diagnosis.
3. **Multiple breadth-first walks** hand out integer lattice indices, hopping
   from cell to cell using *that cell's own* measured size times the known
   pitch/block ratio. Each connected hypothesis is fitted provisionally, then
   other physical blobs close to its integer grid sites are recovered. This
   bridges a missed local hop without inventing an occluded cell. Hypotheses
   are ranked by coverage, chessboard parity and residual.
4. **A homography is fitted** from integer indices to cell centres; every cell
   is re-scored against the footprint the fit predicts *for it*; the fit is
   repeated on the survivors. Both an upper and lower fill bound reject clipped
   and merged cells. Colour parity, measured aspect, mean residual and maximum
   residual are hard acceptance gates rather than status-only measurements.
5. **Every strongly supported mode-sized window is retained** (10 × 6 vertical,
   4 × 16 horizontal). The long-axis span
   is anchored at the lattice edge nearest the bottom-left of the image, while
   an oversized short axis may produce overlapping horizontal choices. A
   window needs at least 95% physical coverage and every row/column must remain
   supported, so one underlit edge cell does not move the calibration but a
   clipped strip still cannot pass. The operator selects among candidates with
   `,` / `.` before `k` saves the map; candidate 1 is the absolute-left window.

### Which axis is X

Never from the image alone. The explicit mode decides which physical side is
machine X: vertical maps 2.2 cm to X; horizontal maps 7.5 cm to X. The detected
short/long lattice axes then follow that declared geometry, whichever way the
sheet was photographed. `ColorGridSpec.mode` and the 10 × 6 / 4 × 16 complete
counts cross-check the `MachineGrid` before calibration; a partial sheet never
causes an orientation guess.

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

The wall and the aluminium rails can still register as "magenta" under that
cast. They remain in the failure overlay, but broad shape/area/purity filters
exclude them from the direction and size vote before the lattice hypotheses
are built. An over-inclusive hue mask is useful, but its clutter is not allowed
to influence the fitted grid.

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
| `original_image_VERTICAL.jpeg` (2048 × 1466) | 130 blobs, 111 on the lattice, **15 × 7 whole cells**, 10 × 6 grid fitted, mean residual **1.13 px** (max 5.59), colour parity **100 %** |
| `original_image_HORZONTIAL.jpeg` (1920 × 1061) | 133 blobs, 110 on the lattice, **22 × 5 whole cells** — refused: 5 whole cells along the 7.5 cm axis cannot hold 6 rows |

A first live frame from the rig (1296 × 972, corrected feed) found 89 blobs
with 53 on the lattice, spread over 11 × 6 — but with holes from a cable lying
diagonally across the sheet and from the frame clipping the outer columns, so
the largest unbroken block was only 6 × 3. The strict one-frame route refuses
that correctly. Evidence-Assisted Printed-Grid Calibration can use the whole
cells it sees across several gantry positions, but only if those frames expose
every outer edge and corner region; it still cannot invent a permanently hidden
workspace boundary.

The refusal is correct, not a limitation: that photo genuinely does not contain
six whole rows. The sheet is the same A2 print in both, just laid down the other
way, and only one of the two orientations has room for the grid. A live camera
looking straight down from 50 cm sees far more forgiving geometry than either.

---

## Using it

```bash
cd python

# prove the detection on a still, or live on the camera
../.venv/bin/python camera/color_grid_check.py --image captures/grid_training/original_image_VERTICAL.jpeg --mode vertical
../.venv/bin/python camera/color_grid_check.py --mode horizontal

# the two feeds: p overlays the sheet, k calibrates from it and saves
../.venv/bin/python camera/gridded_camera_feed.py --mode horizontal
../.venv/bin/python camera/rig_build_v1.py
```

`k` writes the same mode-keyed `config/workspace_map.json` the four-click route
writes. Recalibrating one layout preserves the other; loading a map through the
wrong mode is refused. Nothing downstream knows the sheet exists. In
`rig_build_v1.py` it is guarded exactly like `c`: refused during a build,
refused on a stale camera, and it clears the current selection.

The overlay tints every mapped cell and stamps its `col,row`; whole cells
outside the chosen window are outlined dull yellow and clipped ones red. Watch
the tint against the ink — a residual number cannot tell you *where* a fit went
wrong, and the tint can.

If the gantry hides an interior strip, use Evidence-Assisted Printed-Grid
Calibration in `gridded_camera_feed.py`: `e`, then Space for each useful safe
gantry position, then `k` only at **READY TO SAVE**. It keeps physical evidence
green and inferred-only interior cells amber/dashed; it never allows a virtual
outer boundary. The full procedure and gates are in
[evidence-assisted-printed-grid-calibration.md](evidence-assisted-printed-grid-calibration.md).

### Reading a bad result

**A refusal always still draws what it found** — the blobs that joined a
lattice in green, the ones that did not in red, with the count and the stage in
the corner. A blank window would make "the sheet is out of shot", "the colours
are wrong" and "the code never ran" look identical, which is precisely how the
first live attempt was reported as *no detection, no overlay, nothing*.

| what you see | what it means |
| --- | --- |
| `N whole cells along the 2.2 cm side where 10 are needed … Move the sheet or the camera` | genuinely not enough sheet in view. The named side says which way to move. |
| `… The sheet is big enough in view, so the gaps are holes` | enough cells, but something punched holes in them — a cable lying across the sheet, or an edge clipping a row. The strict route refuses; Evidence-Assisted calibration can cover an interior hole from other safe gantry positions. |
| `only N coloured blocks visible` | the sheet is not in frame, or the colours are being lost. Look at the drawn blobs: many blobs means a colour problem, almost none means a framing one. |
| `they do not form a regular lattice` | blobs found, but not in a grid. Usually something else in view is ink-coloured and the sheet is mostly out of shot. |
| red blobs all over the walls and rails | normal under a colour cast; the lattice discards them. Only a problem if they outnumber the sheet. |
| parity below 100 % | the lattice indices are inconsistent. Distrust the fit even if the residual looks fine. |
| tint drifting off the ink at one corner | residual lens distortion, or the sheet is not flat. |
| `normalized workspace corners must lie inside the image` | the envelope the sheet implies runs off the frame. The sheet is too close to an edge to calibrate from. |

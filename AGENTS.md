# AGENTS.md

Rules for anyone — human or agent — editing this repo.

The rig is two machines that have to agree with each other: a Raspberry Pi 5
running Python, and an Arduino MEGA 2560 running compiled C++. **The Arduino
cannot read `config/rig.json`.** It has no filesystem. Its numbers are baked in
at flash time. So a handful of values genuinely exist in two places, and this
file is the list of them.

**If you change one of these, change its partner in the same commit.**

---

## The shared values

### 1. Serial baud — must match exactly or nothing works

| Where | What |
| --- | --- |
| `config/rig.json` → `serial.baud` | what the Pi opens the port at |
| `arduino/build_test_v1/build_test_v1.ino:898` | `Serial.begin(9600)` |
| `arduino/README.md` | states the baud in prose |

A mismatch does not error. You get garbage bytes or silence, which reads like a
dead cable. Change all three together.

Python serial clients try `/dev/ttyACM0` first and automatically fall back to
`/dev/ttyACM1` when the preferred ACM port cannot be opened. The configured
port remains the preferred port and the upload script still uses it directly.

### 2. Serial port and board — single source, keep it that way

| Where | What |
| --- | --- |
| `config/rig.json` → `serial.port` | what the Pi opens, **and** what `scripts/flash.sh` uploads to |
| `config/rig.json` → `board.fqbn` / `board.sketch` | what `scripts/flash.sh` compiles |

These are deliberately in one place only. `scripts/flash.sh` reads them, so do
not paste an `arduino-cli` command with a literal `-p /dev/ttyACM0` into a
README or a script — that is how the duplicate comes back.

A genuine Mega enumerates as `/dev/ttyACM0`; a CH340 clone as `/dev/ttyUSB0`.
Switching boards is then a one-line edit to `rig.json`.

### 3. Grid dimensions — the one the firmware forgets

| Where | What |
| --- | --- |
| `config/rig.json` → `grid.modes.<mode>.cols` / `.rows` | **authoritative at runtime** |
| `config/rig.json` → `grid.active_mode` | which of the two grids the rig should be in |
| `build_test_v1.ino` SECTION 6C | `GRID_COLS[]` / `GRID_ROWS[]` — per-mode compiled defaults |
| `build_test_v1.ino` `gridMode` | the live mode; compiled default is vertical |
| `python/rig/grid.py` | `MachineGrid.from_config(mode=...)` — what the viewers draw |

**There are two grids, not one.** A block is 2.2 × 6.0 cm in plan and can be
laid either way round, and which way round decides how many cells fit and where
they sit. So each orientation is a complete, separately calibrated grid:

| mode | block | grid | addressable with zero lanes |
| --- | --- | --- | --- |
| `vertical` | 2.2 X × 6.0 Y cm | **6 cols × 5 rows = 30 cells** | 7 × 6 |
| `horizontal` | 6.0 X × 2.2 Y cm | **2 cols × 10 rows = 20 cells** | 3 × 11 |

These counts are the grids currently printed on paper, not geometric maxima:
at trim 0 the 24.3 × 40.0 cm holder travel would take a 6th vertical Y row, a
3rd horizontal X column and up to 13 horizontal Y rows before `gridGeometryFits`
refuses. The travel is physical and does **not** change with the mode — see §3a.

The sketch uses no EEPROM, so nothing survives a reset — and opening the USB
port resets the board. Every session therefore starts at the compiled default,
which is **vertical**, at that mode's compiled `GRID_COLS[]` / `GRID_ROWS[]`.
The Pi pushes the mode it wants **and then** `S <cols> <rows>` on connect to
overwrite both. The order matters: `S` is validated against the active mode's
geometry, so pushing it first validates the counts against the wrong grid.

The mode is latched from the serial console with `RR` (vertical → horizontal)
and `R` (horizontal → vertical). Neither moves the aux stepper and neither is
accepted unless X and Y are homed; see §3c.

The firmware defaults should still be kept equal to the config, for **both**
modes, so that a manual Arduino Serial Monitor session behaves the same as a
Pi-driven one. Editing only the sketch is the trap: the Pi will silently
overwrite the active mode on the next connect. Checking only the active mode is
the newer trap: the horizontal half can drift unnoticed until someone sends
`RR`.

This applies to AI agents as well as humans: **an agent changing a paired grid
value must edit both the Raspberry Pi JSON/Python side and the live Arduino
sketch in the same change.** Run `python/tests/test_grid.py`; it parses the live
sketch's per-mode tables and fails if any listed pair differs from `rig.json`,
in either mode.

`S <cols> <rows>` is scoped to the **active** mode and revalidated against that
mode's geometry. The other mode keeps whatever count it was last given, so
latching back and forth does not quietly resize the grid you are not looking at.

### 3a. X/Y physical grid geometry — fixed-pitch block cells

Everything in this table except the physical envelope is **per mode**. On the
Pi side that is `grid.modes.<mode>.<key>`; on the firmware side it is a
two-element table indexed by `gridMode`, ordered `{vertical, horizontal}`.

| Meaning | Per mode? | Pi / camera side | Firmware side |
| --- | --- | --- | --- |
| physical envelope | no | `rig.json` → `workspace.width_cm` / `height_cm` | `X_TRAVEL_CM` / `Y_TRAVEL_CM` |
| one block footprint | yes | `grid.modes.*.block_x_cm` / `block_y_cm` | `GRID_BLOCK_X_CM[]` / `GRID_BLOCK_Y_CM[]` |
| gap before each positive cell | yes | `grid.modes.*.gap_x_cm` / `gap_y_cm` | `GRID_GAP_X_CM[]` / `GRID_GAP_Y_CM[]` |
| signed complete-grid shift | yes | `grid.modes.*.trim_x_cm` / `trim_y_cm` | `GRID_TRIM_X_CM[]` / `GRID_TRIM_Y_CM[]` |
| signed error correction shift | yes | `grid.modes.*.error_offset_x_cm` / `error_offset_y_cm` | `GRID_ERROR_OFFSET_X_CM[]` / `GRID_ERROR_OFFSET_Y_CM[]` |
| permitted block-edge overhang | yes | `grid.modes.*.max_edge_overhang_x_cm` / `_y_cm` | `GRID_MAX_EDGE_OVERHANG_X_CM[]` / `_Y_CM[]` |
| live operator grid shift | yes | `grid.modes.*.shift_x_cm` / `shift_y_cm` | `GRID_SHIFT_X_CM[]` / `GRID_SHIFT_Y_CM[]` |

The shift is pushed by `rig/link.py` as `shiftX` / `shiftY` after the mode latch
and before `S` on every connection, because a port-open reset clears it. It
enters the lattice exactly like a trim but is **not** calibration: a shift that
pushes the far block past the travel cap CLIPS the reachable grid
(`gridColsNow()` / `gridRowsNow()`, `MachineGrid.requested_cols` / `_rows`)
while keeping the request, so clearing it restores the full grid with no re-`S`.
The pick-up never rides it — that is a plain home to raw `[0,0]`.

**Each mode declares both block extents outright.** Nothing in this project
swaps a width for a length. A swap would have to be performed identically in
the firmware, in `MachineGrid` and in the camera overlay — three chances to get
an axis backwards, for no gain.

`rig.json` → `observed_build_area` is a measurement record only. It has no
firmware partner and never replaces the holder travel cap in `workspace`.

These centimetre measurements are **holder displacements**, not pure object
dimensions: they compare the holder reference at home with that same reference
at the active software cap. The live calibration is:

- X: **24.3 cm holder displacement = 4750 steps**, so `4750 / 24.3 =
  195.4733 steps/cm`;
- Y: **40 cm holder displacement = 8250 steps**, so `8250 / 40 =
  206.25 steps/cm`.

Never hard-code those ratios; firmware derives them from the cap and measured
displacement. A separate physical observation found a **24.3 × 43 cm build
footprint**; it does not change the 24.3 × 40 cm holder-centre motion cap. The
measured horizontal CCW tool offset is X `+3.75 cm`, Y `+1.40 cm`; neutral and
CW remain zero.

A block is **2.2 × 6.0 × 1.5 cm**. Which of its two plan dimensions lies along
X is what the mode decides. `[0,0]` is the feeder-block centre where the claw
picks up. **The gaps are a uniform 1.6 cm on every axis of both modes** —
measuring the printed sheet (6.00 cm tiles, 1.56 cm gaps, identical on both
axes) settled that; an earlier revision claimed 0.8 cm along Y and it was
wrong. The whole lattice is one line, and it is CENTRE-ANCHORED:

```text
pitch     = block + gap
centre(i) = trim + error_offset + shift + i * pitch
```

Cell indices are **0-based** and cell 0's CENTRE sits on the home corner, so
cell 0's block hangs half a block back past the switches and a full-travel grid
lands its last centre exactly on the software cap. There is no leading gap, no
trailing gap and no centring: the trim is the only thing that moves a grid.
That half-block overhang is what `GRID_MAX_EDGE_OVERHANG_*` budgets for.

Worked out for both at the shipped calibration:

| mode | axis | block | gap | pitch | count | footprint | centres | block edges |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| vertical | X | 2.2 | 1.6 | 3.8 | **7** | 25.00 | 0.00 → 22.80 | −1.10 → 23.90 |
| vertical | Y | 6.0 | 1.6 | 7.6 | **6** | 44.00 | 0.00 → 38.00 | −3.00 → 41.00 |
| horizontal | X | 6.0 | 1.6 | 7.6 | **3** | 21.20 | 2.40 → 17.60 | −0.60 → 20.60 |
| horizontal | Y | 2.2 | 1.6 | 3.8 | **10** | 36.40 | 2.20 → 36.40 | 1.10 → 37.50 |

Horizontal's centres above are `trim (+1.9 / +1.9)` **plus its shipped
`error_offset` of `+0.5 cm` X / `+0.3 cm` Y** — a measured constant per-mode
placement error (blocks were landing that far toward home; rotation slop from
the 90° CCW pickup-rotate). The registration trim alone would put the centres
at `1.90 → 17.10` (X) and `1.90 → 36.10` (Y). The error offset corrects
placement but never resizes the grid: `gridGeometryFits` / `_assert_fits`
strip it.

`count` is a COUNT; the firmware's `S` and `GRID_COLS` / `GRID_ROWS` speak in
highest indices, one less. `python/rig/grid.py` is the authoritative statement
of all of this and `web/src/studio/coords.ts` is its browser port, held to it
by fixtures (`python/tools/dump_grid_fixtures.py`).

The vertical grid ships at `trim_x = trim_y = 0` and sits EXACTLY on its travel
cap and edge budget on both axes, so any trim at all is a geometry error there
rather than a moved grid. The horizontal grid ships with
`trim_x = trim_y = +1.9 cm`: the block is picked up standing at the vertical
feeder `[0,0]`, centred on home, then rotated 90° about the grip. The rotated
6.0 cm face overhangs the 2.2 cm vertical footprint by `6.0/2 − 2.2/2 = 1.9 cm`
per side, so a +1.9 cm trim on each axis seats horizontal `[0,0]` flush against
the vertical `[0,0]` block edge (near edge in X, far edge in Y). This is a
mode-specific grid registration shift, positive away from each home switch; it
is not a tool offset and must not be added to `tool_offsets.ccw`.
**Horizontal's trims are still not vertical's and must not be copied from
them.**

#### Pickup-cell registration diagram — do not remove

The feeder/pickup area is physically a vertical block cell. When the build is
switched to `RR`, the horizontal layout does not use the bare home point as its
reference: it is registered +1.9 cm on BOTH axes from the vertical pickup cell.
Along either axis the relationship is the same:

```text
                    positive / away from the home switch →

        vertical pickup cell [0,0]       horizontal grid reference
        ┌──────────────────────┐         ┌──────────────────────┐
        │                      │         │                      │
        │  vertical [0,0]      │ 1.9 cm  │  horizontal [0,0]    │
        │  centre = 0          │<------->│  centre = +1.9       │
        │                      │         │                      │
        └──────────────────────┘         └──────────────────────┘

        The horizontal registration shift is +1.9 cm in X AND in Y.
```

This `1.9 cm` is not the ordinary cell gap. `gap_{x,y}_cm = 1.6` remains the
repeat spacing between horizontal cells and the gap before positive cell 1.
`horizontal.trim_x_cm = horizontal.trim_y_cm = +1.9` is a separate registration
of the whole horizontal allocation relative to the feeder. Do not replace one
with the other, and do not add this 1.9 cm to the CCW arm offset.

The physical build sequence is:

```text
1. Home X/Y at the vertical feeder reference.
2. Pick up the block while the claw is neutral.
3. Move to the horizontal target using the horizontal grid coordinates.
4. Rotate the claw 90 degrees CCW for RR mode.
5. Lower and release at the shifted horizontal grid location.
```

`RR` itself only latches the coordinate system; it does not move the claw or
apply the shift immediately. The shift is applied when horizontal cell centres
are calculated for a build. `B 0 0 <level>` remains a no-op calibration
sentinel; it does not pick up a block or physically move to the horizontal
reference.

The correction categories must remain separate:

```text
horizontal.trim_x_cm       = registration between feeder and RR grid
tool_offsets.ccw.x_cm       = holder-to-block-centre geometry after rotation
error_offset_x_cm           = measured whole-grid placement error
gap_x_cm                    = repeated spacing between cells
```

The same separation applies on Y (`horizontal.trim_y_cm` carries the identical
+1.9 cm). A future rig measurement may refine the registration magnitude per
axis (`horizontal.trim_{x,y}_cm`) or, for a measured constant placement error on
top of it, `horizontal.error_offset_{x,y}_cm` (shipped at `+0.5` / `+0.3 cm` —
see the table note above); either way do not silently move it into
`tool_offsets`.

Each mode also declares `max_edge_overhang_x_cm` / `_y_cm`: the budget the
block **edges** are checked against, on both machines. It is not a trim and
moves nothing.

- vertical allows half a block on each axis (`1.1` / `3.0` = block_x/2 /
  block_y/2), the overhang a full-travel grid would produce;
- horizontal allows `3.0` / `1.1` (block_x/2 on Y, block_y/2 on X are the
  half-block figures; horizontal's are `max_edge_overhang_x_cm = 3.0`,
  `_y_cm = 1.1`), which the +1.9 cm registration's `−1.1 cm` X near edge needs.

**Vertical sits exactly on its cap; horizontal keeps far-end slack after the
+1.9 cm registration and its `+0.5` / `+0.3 cm` error offset** (X last centre
17.6 into 22.8, Y 36.4 into 38.0). Measure a real stack before trusting
horizontal's last row.

The firmware owns the step counts and derives both steps/cm ratios at runtime;
never hard-code either ratio and do not copy the `4750 × 8250` safety envelope
into JSON. Neither the step envelope nor either steps/cm ratio is per mode:
they describe the machine, and a block lying down does not move a limit switch. The Pi does not need motor steps to draw or select a cell: it maps
camera pixel → physical cm → `[col,row]`, and the Arduino alone maps that cell
to safe step targets. The Pi needs the centimetre geometry to interpret camera
scale, while the firmware needs it to turn cell centres into steps, so those
centimetre values genuinely have partners on both machines. Change both
partners in the same commit. Positive trim moves the entire grid away from its
home/feeder reference; negative trim moves it toward that reference. The
shipped vertical trims are `0.0` on both axes; horizontal `trim_x` and `trim_y`
are both `+1.9 cm` for the pickup-cell-to-horizontal-grid registration
described above.
The shipped vertical error offsets are `-0.3 cm` on X and `-0.4 cm` on Y,
moving placements toward the home switches to correct the measured error.
Horizontal remains at `0.0` on both axes until it is measured. Start any new
error calibration from these current values.
For any user-marked **error offsetting**, use `error_offset_x_cm` and
`error_offset_y_cm` (and the paired firmware variables) as an additional
signed shift exactly like the grid trim.

### 3b. Grid NUMBERING — the convention, not the count

| Where | What |
| --- | --- |
| `build_test_v1.ino` `printGrid()` | draws the map that `9` prints |
| `python/rig/grid.py` | `cell_at()` / `image_cell()` / `ascii_map()` |
| `python/tests/test_grid.py` | holds the two to the same map |

Block cells are **0-based and every one of them is a real block**, coordinate
zero included. Col 0 is the X switch side, row 0 is the Y switch side, rows
increase upward and columns rightward. `[0,0]` is the **feeder** in both modes —
where blocks are picked up from, never built on — so `B 0 0 <level>` stays an
inert no-op, while `B 0 3` and `B 4 0` are ordinary placements (they used to be
the "move one axis only" sentinel). Cells are written `[col,row]`, the same
order as the arguments to `G` and `B`.

**The convention holds in both modes; only the map's dimensions change.**
Vertical draws 7 wide × 6 tall, horizontal draws 3 wide × 10 tall. `9` prints
the active mode's name above the map, so a map with the wrong shape for what
you expected is a mode you did not expect, not a numbering change.

`ascii_map()` reproduces `printGrid()` byte for byte on purpose, so a change to
either can be caught by diffing them rather than by noticing that the claw went
to the wrong place. If you reword that map, run `python/tests/test_grid.py`.

Where the grid sits **on the camera image** is NOT part of this numbering
convention. `gridded_camera_feed.py` derives it from four clicked envelope
corners and saves `workspace_map.json`; `MachineGrid.origin` / `swap_axes`
remain useful only for count-only/legacy drawings without that homography.

### 3c. Tool-centre offsets — holder position is not block position

| Where | What |
| --- | --- |
| `config/rig.json` → `tool_offsets.neutral/cw/ccw` | editable calibration record, in cm |
| `build_test_v1.ino` `TOOL_OFFSET_*_CM` | compiled values used to move the holder |
| `python/tests/test_grid.py` | verifies every JSON/firmware pair |

The X/Y counters describe the gantry holder. Each offset is the signed vector
**from holder reference to actual block-placement centre**, where positive is
away from that axis's home switch. The Arduino subtracts that vector from the
selected grid-cell centre before moving, so the tool — not its holder — reaches
the requested cell. `neutral` is the vertical grid's placement orientation and `ccw` is the
horizontal grid's; a `G` command uses the claw's current orientation, a `B`
command uses the active grid's.

**`cw` is not a grid/build orientation and is kept anyway.** `B` has no
rotation word, and the mode latch derives placement from the grid — vertical →
none, horizontal → 90° CCW. There is no clockwise grid because that would be a
second, separately calibrated layout that nobody has measured. An explicit
manual `A 90` can put the claw in the CW state for a bench `G` test, but it
does not create a CW placement mode and its offset is uncalibrated. The `cw`
entry stays in both JSON and firmware because `toolOffsetCmOf()` is written
over the three rotation states; deleting one leg would make it no longer line
up with `ROT_CW` / `ROT_NONE` / `ROT_CCW`. Leave it at zero unless it is
measured; do not read it as a hint that a clockwise grid exists.

`ccw` is calibrated for the current horizontal-grid trial at X `+3.75 cm`,
Y `+1.40 cm`; this remains an on-hardware trial and must be remeasured if the
holder/claw geometry changes.

The neutral and CW offsets remain **zero** as intentional no-ops. The horizontal
CCW values are an entered measured trial. Keep measured values paired in both
places in the same commit. Do not compensate this by moving the camera grid or
changing `grid.trim_*`: those define the block grid itself, not the
holder-to-tool geometry. Targets that would put the holder outside its safe
X/Y envelope are refused, never silently clipped.

#### 3d. The printed colour calibration sheet — geometry it must be reprinted for

| Where | What |
| --- | --- |
| `python/vision/combined_grid.py` | the current A2 page/fiducial dimensions and page-to-holder registration |
| the current physical print | A2 landscape; 8 x 10 chromatic fiducials; lower-left page corner is holder home |
| `config/rig.json` -> `grid.modes.<mode>.*` | applied after the shared page-plane fit; still stored separately per mode |
| the two legacy physical sheets | vertical: 2.2 x 6.0 cm; horizontal: 6.0 x 2.2 cm; 1.6 cm inner margin along X, 0.8 cm along Y |
| `python/vision/color_grid.py` | detects legacy sheets and refuses a measured geometry mismatch |
| `plans/printed-color-grid.md` | the full treatment, including the layout disagreement below |

The current combined sheet measures the page plane independently of either
block layout. It uses 6.0 x 2.2 cm fiducial bars, 0.8 cm X gaps and 1.6 cm Y
gaps on a 59.4 x 42.0 cm A2 page, with the lattice starting 0.8 cm from page
left and 4.8 cm from page bottom. Each 6.0 cm bar is split across X as 2.2 +
1.6 + 2.2 cm. The artwork is woven: its 80 muted/dark/muted chromatic bars are
vertical-pattern fiducials, while the two perpendicular outer lanes in each of
the 40 paired-row intervals are 80 separate colour/beige/opposite-colour
horizontal-pattern fiducials. A decoded fiducial is exactly one of vertical,
horizontal or unknown; the same chromatic bar must never inherit the vote of a
neighboring beige interval. The active mode selects the one family decoded and
returned: vertical reports `V/H/? = 80/0/0`, horizontal reports `0/80/0`.
Both expose the same logical 8x10 `(col,row)` address set. Neither overlays nor
counts may contain the inactive family. These numbers and the physical artwork
are a pair:
changing one requires reprinting and updating `combined_grid.py` in the same
change. Beige carries horizontal-orientation information, but it must never
establish the lattice alone: both opposite-colour end thirds are mandatory.
An unreadable beige middle may be inferred only after other directly measured
bridges establish the five-interval alternating parity; those cells are `H~`.
For diagnostics, a cropped frame may decode orientation from complete visible
patterns and extrapolate the 8x10 lattice. It must not produce workspace
corners unless at least 76/80 lattice sites support the page plane; clipped
bars never count, and a partial-frame orientation result is not calibration.

The physical lower-left page corner is the holder-home reference. The combined
route therefore accepts only the `firmware` home convention. It yields the
same holder-envelope corners for both modes, but `WorkspaceMap.from_grid()`
still embeds and saves each mode's distinct grid geometry. Changing block or
gap geometry invalidates the saved mode entry but does not require reprinting
the combined page.

The paragraphs below describe the retained legacy sheets. A legacy sheet is a
**physical artefact carrying a copy of block geometry**. If a legacy mode's
`block_*_cm` or `gap_*_cm` changes, that sheet must be reprinted;
`ColorGridCalibration._check_geometry_matches` refuses a stale one.

`ColorGridSpec.from_config(mode=...)` reads that mode's `cols + 1` and `rows +
1`: each sheet prints a real block at **every** coordinate, coordinate zero
included. The vertical sheet maps the complete 7 x 6 map, not the 6 x 5
positive one; the horizontal sheet maps 3 x 11, not 2 x 10. Mode is explicit:
the detector does not infer it from a partial sheet, and it refuses a sheet/map
count or geometry mismatch.

**The sheet and the firmware do not lay coordinate zero out the same way.** The
sheet puts a whole 2.2 x 6.0 cm block there; the firmware puts a bare point with
only the gap before cell 1. The printed grid is therefore one block wider on X
and one block taller on Y than the machine's grid, and aligning them is an
explicit decision, not an assumption (rig X/Y below are at trim 0):

```text
vertical sheet X = 7 x 2.2 + 6 x 1.6 = 25.0 cm    rig X = 6 x 3.8 = 22.8 cm
vertical sheet Y = 6 x 6.0 + 5 x 0.8 = 40.0 cm    rig Y = 5 x 6.8 = 34.0 cm
horizontal sheet X = 3 x 6.0 + 2 x 1.6 = 21.2 cm  rig X = 2 x 7.6 = 15.2 cm
horizontal sheet Y = 11 x 2.2 + 10 x 0.8 = 32.2 cm rig Y = 10 x 3.0 = 30.0 cm
```

`ColorGridCalibration.workspace_corners()` takes a `convention`. The default
`"firmware"` puts the machine origin at the far corner of printed `[0,0]`, which
makes printed `[c,r]` coincide exactly with the firmware's `[c,r]` for all
positive cells. `"printed"` takes the paper at face value and lands every
positive cell one `block/2 − (pitch − grid.x_start)` further from home on each
axis. Do not add a third convention without a row here and a note in the plan.

#### 3d-bis. Placed-block calibration — the primary route

| Where | What |
| --- | --- |
| `python/vision/block_grid.py` | all the geometry: the fit, the lattice metrology, the model choice, the virtual fill, every gate |
| `python/rig/block_calibration.py` | drives the machine: one `B <col> <row> 0` per step, parks, captures, observes |
| `python/vision/block_detector.py` | the front end; `flatten` / `expected_size` are turned on for this path only |
| `python/camera/block_grid_calibrate.py` | the terminal driver; `--mock` is a hardware-free dry run |
| `camera_studio.py` `blockcal` / `blockcalsave` | the BLOCK CALIBRATION buttons — read the grid off the board as it stands |
| `POST /api/calibration/block/{start,step,undo,cancel,save}` | the console routes |
| `web/src/components/Calibrate.tsx` | the operator UI; placed blocks is the first choice offered |
| `python/captures/IMAGE_TO_TEST_BLOCK_CALIBRATION.png` | the reference board: 29 blocks, 13 cells filled, asserted in `tests/test_block_grid.py` |

Every sheet route (§3d) measures the **camera against a piece of paper** and
then assumes the paper sits where the firmware's cells are. That assumption is
the entire reason §3d needs `HOME_CONVENTIONS` and a geometry cross-check.
This route uses the blocks themselves, so the thing being measured *is* the
thing being calibrated — and it measures the real pick-and-place chain
(backlash, tool offsets, each mode's `error_offset_*_cm`) instead of a printed
approximation of it.

##### The two ways in, and why one is safer

**Labelled — the rig places them.** `BlockCalibrationRun` issues one `B` per
cell and records the sighting against the cell it *commanded*. The
correspondence is labelled at the source: there is nothing to infer, no origin
to guess, and no way for the board to be renumbered.

**Unlabelled — the board is already full.** `detect_block_lattice` takes one
frame of blocks somebody else placed, recovers the two lattice step vectors
from the blocks' own neighbours, and snaps everything onto integer sites. It
cannot recover the ORIGIN: a regular lattice is identical under a whole-cell
shift. `LATTICE_ANCHORS` supplies it, defaulting to `bottom-left`, and **a
wrong anchor is not detectable from the picture** — on the reference board,
`top-right` relabels `[0,0]` as `[6,4]` and every gate still passes. The test
suite asserts this failure rather than pretending otherwise. Prefer the
labelled route whenever the rig is available.

##### Rules that must survive an edit

- **Five placements minimum, six planned.** Four correspondences fit a
  homography exactly, so every residual is zero by construction and the
  calibration carries no evidence it is right. `MIN_OBSERVATIONS = 5` exists
  for that reason alone; do not lower it to get a quicker run.
- **The residual is not an optical number.** It includes where the machine
  physically put the block, which is why the gates are looser than
  `MAX_MEAN_RESIDUAL_SHORT_SIDE`. A large residual means the rig or the map is
  off, not that the camera is blurry.
- **Two checks replace the printed chessboard's parity gate.** Identical wooden
  blocks carry no colour signal, so `fit_block_grid` instead requires each
  observed block's short side to match the footprint the homography predicts at
  that cell (`SIZE_AGREEMENT_RANGE`) and its long axis to point along the
  mode's own axis (`MAX_ANGLE_DISAGREEMENT_DEG`). Between them they catch "a
  cable was detected instead of the block" and "the block landed on the wrong
  cell". A uniformly wrong block scale leaves *every* residual at zero and is
  caught only by the footprint check — do not drop it as redundant.
- **Conditioning is checked numerically, not by counting cells.** Spread and
  hull area are necessary and not sufficient: a dense plan fills row-major, so
  after seven placements the set is six points along row 0 plus one in row 1 —
  spread 6x1, hull 2.5 cells, and completely degenerate, because every
  four-point subset has three collinear. `dlt_conditioning()` returns the DLT
  design matrix's second-smallest singular value over its largest.
  Degenerate configurations score 1e-17 and below; usable ones score above
  1e-2. `MIN_DLT_CONDITIONING = 1e-5` sits in a thirty-order-of-magnitude gap
  and is not a tuned number.
- **A clipped block is refused, never measured.** A block the frame cuts off
  still segments cleanly; its centroid is simply dragged inwards by whatever
  was lost — 21 px on a 40 px block at MockCamera's framing. Use `--inset 1`
  (or the route's `inset`) when the camera cannot see the outermost ring whole,
  rather than relaxing `EDGE_MARGIN_FRACTION`.
- **The rig's mode must match the grid being calibrated.** The machine lays a
  block along whichever axis its active mode says, and nothing downstream can
  tell a correct vertical block from a horizontal one in the right spot — the
  bearing check cannot catch it, because the blocks would all agree with each
  other. `BlockCalibrationRun` refuses the mismatch up front.
- **`aborted` ends the run.** The claw may still be holding a block, so
  `BlockCalibrationAborted` is a distinct type, the console locks, and there is
  no retry and no automatic home. `rejected` moved nothing and stays
  retryable — it usually means the feeder at `[0,0]` is empty.
- **The build area must be clear at `start()`.** The first frame is the
  baseline every later capture is differenced against; a block already on the
  table is invisible to that difference and can only be found by shape.
- Calibration always builds at **level 0**. Nothing here ever stacks.

##### Dense mode: measuring the lattice instead of assuming it

Once `MIN_DENSE_OBSERVATIONS = 25` cells of a `DENSE_MODES` grid are occupied,
`analyse_dense_lattice()` stops trusting a homography and starts testing it.
Horizontal is excluded: it is three columns wide, so curvature along X would be
fitted from three points, which is an interpolation with nothing left over to
check it.

* **The pitch is measured, not derived.** `measure_pitch()` uses only
  lattice-ADJACENT pairs, so every sample is exactly one pitch and no average
  has to guess how many it just crossed. It is reported pooled *and* per row
  (for X) and per column (for Y), because "is the gap a static number or does
  it depend where you are" is exactly the question a single average hides. On
  the reference board: X 29.38 px (sd 1.24, 1.4% spread across rows), Y 69.14 px
  (sd 1.08, 2.0% across columns) — static to within 2%, so on this rig the
  answer is "one number per axis".
* **Four models compete on held-out error.** `similarity` (4 dof), `affine`
  (6), `homography` (8) and `homography+curvature` (10), ranked by
  leave-one-out prediction, ties going to the simpler one. Training error would
  only ever pick the richest model — the point of the fit is to place cells no
  block was ever put on, so predicting an unseen point is the question that
  matters. Fitted by plain least squares, never `cv2.estimateAffine*`'s robust
  methods: those resample, which would make leave-one-out non-deterministic,
  and there are no outliers to be robust against once labels are known.
* **Curvature models the machine, not the camera.** A homography already
  absorbs perspective and any uniform scale error. What it cannot absorb is an
  advance-per-cell that drifts along the travel, which is nonlinear in lattice
  coordinates — so the correction is applied *in lattice space*
  (`c + a·c²`, `r + b·r²`) before projection, and cannot be folded into the
  3x3. `BlockGridCalibration` carries it and applies it inside `point_at()` and
  `grid_at()`, the two doors every other method goes through, so `cell_quad`,
  `outline`, `cell_at` and `workspace_corners` are all correct without knowing
  it exists. The coefficient is recovered only approximately — a quadratic bend
  is partly degenerate with a homography's own perspective terms, so the two
  share the work — which is why the tests assert *prediction*, not the
  parameter. **The warning it emits must not blame the belts:** a drifting
  machine and a lens whose correction left distortion behind produce the same
  curve, and one frame cannot separate them.
* **The one non-circular geometry check.** `px_per_cm` is *defined* as
  measured/expected, so comparing the pitch ratio against the printed ratio
  after correcting by it is circular and always returns exactly 2.000. The real
  check is `anisotropy_agreement`: the optical stretch measured from cell
  PITCHES against the stretch measured from block FOOTPRINTS — different
  quantities through one lens, which agree only if the gaps in `config/rig.json`
  describe this board. The reference board's view is genuinely 17.7%
  anisotropic and the two estimates agree to 4%.

##### Virtual cells — a grid bigger than the block supply

The block supply is smaller than the grid, so the cells nobody could reach must
still be drawn. `fit_block_grid(..., fill=True)` adds every unplaced cell from
the fitted lattice, marked `full=False` with `area=0` and `fill=0`.

`BlockGridCalibration` overrides `found_cells` to return **only** what was
measured, because everything consuming it — `grid_evidence`'s coverage gates,
`color_grid_check`'s "physically found" count — is asking what was observed and
must never be handed a synthesised cell as if it were one. `virtual_cells` is
the other half. The overlay tints measured cells and outlines virtual ones,
reusing the same treatment `color_grid_overlay` already gives a projected-but-
unseen cell.

`plan_dense_cells()` fills row-major from the home corner rather than spreading,
which is the opposite of `plan_calibration_cells()`. A spread set conditions a
homography well but measures pitch badly — every `measure_pitch` sample needs a
lattice-ADJACENT pair, and a thin spread has almost none. With 25+ of 41 cells
the dense region still spans most of the grid, so conditioning survives, and
the unplaced cells end up as the tail of the build order: the far rows, toward
y+.

##### Detection settings, and one that is deliberately backwards

`_colour_sightings` runs `flatten_illumination` but **not** `white_balance`,
which is the opposite of what the sheet detectors do. `white_balance` is a
white-PATCH estimator and its own docstring says why that is safe there: the
sheet's white paper is the brightest large thing in a frame that is mostly
sheet. A board covered in wooden blocks breaks that assumption — the bright
quantile lands partly on wood, and the correction then pulls the blocks toward
the surface it was supposed to separate them from. Measured on the reference
board: balance on finds 28 of 29, off finds all 29, and off stays at 29 across
every colour threshold from 4 to 8 where on collapses at 4.
`flatten_illumination` removes the same cast without needing a white reference.

Two things on a real board are not blocks and must not be treated as such.
Overlapping detections (block_detector's compound decomposition proposes
overlapping ideal rectangles inside one colour component) are collapsed by IoU
in `_deduplicate`. Objects that are wooden and roughly block-shaped but **not
on the lattice** — the holder's two small offcuts beside `[0,0]` on the
reference board — are discarded by `MAX_INDEX_SNAP` rather than raising, since
an untidy board is normal. If more than `MIN_ON_LATTICE_FRACTION` of detections
fail to snap, the lattice vectors themselves are wrong and that *is* an error:
keeping the minority that happened to fit would renumber the whole grid.

##### Saving is not the same as calibrating

`workspace_map.json` is only adopted by a consumer whose **projection** — lens
profile, flip/rotate, correction on/off, framing ROI — matches the one embedded
in the map. `gridded_camera_feed.load_workspace()` refuses a mismatch with
"camera lens/orientation/framing changed", and a map saved with `projection:
null` is refused by *everything*: it is written successfully and then silently
ignored, which looks exactly like it worked. Every writer must pass a real
projection. `tests/test_block_grid.py` §11 asserts both halves of this, because
nothing else fails when it regresses.

A saved map also cannot carry the full fit. `WorkspaceMap` stores four envelope
corners plus the grid geometry — not a per-cell table — so whoever loads it
spaces cells evenly between those corners, and the curvature term is flattened
on the way out. The corners come back exact and the error peaks mid-grid, which
is that flattening's signature. On the reference board it is 1.25 px mean /
2.07 px max = **0.27 cm on a 2.2 cm block**. `workspace_map_error()` measures
it and `blockcalsave` reports it; do not let a caller imply a save is lossless.
Widening `WorkspaceMap` to carry a per-cell table would remove this, and would
touch every consumer of the format.

##### A block calibration is saved exactly as a paper one

Both routes write the same artefact. `block_workspace_map()` deliberately goes
through `ColorGridCalibration.workspace_corners()` and `WorkspaceMap.from_grid`
- the same two calls `paper_workspace_map()` makes - so given the same
calibration and projection the two produce a **byte-identical**
`workspace_map.json`: same `corners_normalized`, `grid`, `physical_grid`,
`projection`, same per-mode entry, and saving one mode leaves the other's entry
alone. `tests/test_calibration_parity.py` asserts that field by field, because
if they ever diverge the app adopts one and silently refuses the other, and the
only symptom is "the grid did not change".

The one place they legitimately differ is **which projection gets stamped**.
The paper route runs inside the app, so its projection matches the app's by
construction. Camera Studio does not: it is an editor, and its live lens, crop,
zoom, flip and correction switch drift from `camera_settings.json` until SAVE
JSON writes them. A map stamped with unsaved editor state is refused by every
consumer — correctly, because the frame it was fitted to is not the frame the
app renders. So `blockcalsave` compares `Studio.projection()` against
`Studio.saved_projection()` (rebuilt from the file) and **refuses up front**,
naming which of view/lens/orientation/roi drifted, instead of letting the app
reject the map later with no clue which knob did it.

##### A saved map does not reach a running app by itself

`config/workspace_map.json` is read **once at startup**, and again only when
the grid mode changes. On the rig the normal way to calibrate is to run Camera
Studio or `camera/block_grid_calibrate.py` in a *separate* process while the
console is up — so until there was a reload door, a freshly saved calibration
was invisible until the app was restarted, and nothing said so. Saving looked
like it did nothing.

| Consumer | How to pick up a map saved elsewhere |
| --- | --- |
| `camera/rig_build_v1.py` | press **`L`** |
| web console | **Reload saved calibration** in the Calibration panel, or `POST /api/calibration/reload` |
| anything embedding `ConsolePipeline` | `reload_workspace()` |

`reload_workspace()` returns `(workspace, rejection)` and bumps
`_map_generation` so overlays rebuild. A map that is on disk but refused must
surface its **sentence** — "camera lens/orientation/framing changed" and "no
calibration saved" need opposite responses from an operator, and silence is
indistinguishable from both. `tests/test_workspace_reload.py` asserts the whole
sequence, including that a running console does *not* pick a map up on its own.

Camera Studio's `blockcalsave` names the file and the grid mode in its
confirmation for the same reason: that window's other SAVE writes
`camera_settings.json`, so an unqualified "saved" is genuinely ambiguous.

##### What the reference board proves

`tests/test_block_grid.py` §10 runs the whole unlabelled path on
`captures/IMAGE_TO_TEST_BLOCK_CALIBRATION.png` and asserts the exact cell sets:
29 physical (columns 0-6 of rows 0-3, plus `[0,4]`) and 13 virtual (the rest of
rows 4 and 5), max snap 0.08 cells, mean residual 0.85 px. Keep it exact — a
count-only assertion would pass on a board shifted by one cell.


### 3e. Camera colour correction — one transform, applied in four places

| Where | What |
| --- | --- |
| `python/config/camera_settings.json` -> `colour` | the saved transform; the only copy |
| `python/vision/color_correction.py` | the model, the fit, and what is wrong with a fit |
| `camera_studio.py` COLOUR section | the only thing that writes it |
| `camera_feed.py` `colour_from_settings()` | how every consumer reads it |

The rig's camera has a colour cast strong enough to turn the printed sheet's
green ink cyan. That breaks `vision/color_grid.py` outright and degrades
`vision/block_detector.py`, which keys on red-minus-blue. The correction is
therefore applied **once, at the captured frame**, immediately after
`frame_orientation()` — not inside each detector.

Four tools apply it: `camera_feed.py`, `gridded_camera_feed.py`,
`rig_build_v1.py` and `color_grid_check.py`. **A new tool that reads
`camera_settings.json` must apply it too**, or it will silently see different
pixels from every other tool. The one line is:

```python
frame = colour.apply(frame_orientation(snapshot.frame, capture))
```

It is deliberately **not** part of `projection_metadata()`. Colour changes no
geometry, so recolouring must not invalidate a saved `workspace_map.json`.

`vision/color_grid.py` keeps its own internal `white_balance()` regardless.
That is not a duplicate: it defends the sheet detector on a camera nobody has
calibrated yet, which is exactly the state someone is in when they first go
looking for the COLOUR section.

**Do not name a new constant `FIT_MODES` in `camera_studio.py`.** That name is
already the crop sizing tuple `("fit", "native")`, and the colour fit modes are
imported as `COLOUR_FIT_MODES` because the module-level assignment silently
shadowed them once already.

## 4. Frame span in centimetres

| Where | What |
| --- | --- |
| `config/rig.json` → `frame` | the only copy |
| `grid/undistorted_grid_viewer.py`, `grid/measured_grid_viewer.py` | read it via `rig.config.load()` |

Already centralised. The rule here is: **do not reintroduce a module-level
constant.** Both viewers used to carry their own copy and drifted. This is the
physical span of the complete camera image and is deliberately separate from
the machine envelope in `workspace`.

### 5. The `@` acknowledgement lines

| Where | What |
| --- | --- |
| `build_test_v1.ino` SECTION 7C | emits `@<seq> <KIND> ...` |
| `python/rig/link.py` | parses them — `parse_ack()`, `parse_progress()`, `_KIND_TO_OUTCOME` |
| `python/rig/mock_board.py` | a fake board that must speak the same protocol |
| `plans/ack-protocol.md` | the kind list, the phase table, and the reasoning |

`OK`, `ERR`, `SAFE`, `HELD`, `BOOT`, `READY`, `RECV`, `STEP`. **`SAFE` and
`HELD` are not interchangeable**: `SAFE` means nothing moved, `HELD` means the
claw may still be gripping a block at an unknown position. Never collapse them
into one "failed" branch on the Pi.

`RECV` and `STEP` are NOT terminal. A waiter that returned on either would hand
back an answer while the rig was still moving.

Adding a kind means updating the firmware, the Pi parser and that document
together. Every ack literal is `F()`, like everything else the sketch prints.

**Do not add an `ackField()` overload taking a flash string.** An integer
literal `0` is also a null pointer constant, so `ackField(F("level"), 0)` would
become ambiguous and every existing numeric call site is one edit away from a
compile error. The word form is separately named `ackWord()`.

### 5a. The fourteen build PHASE identifiers

| Where | What |
| --- | --- |
| `build_test_v1.ino` `buildStep()` call sites | the authoritative fourteen `phase=` ids |
| `python/rig/mock_board.py` `MockBoard.BUILD_PHASES` | the off-rig copy that lets the whole console be tested |
| `web/src/studio/twin.ts` `PHASE_BY_ID` | what the 3D twin draws for each one |
| `plans/ack-protocol.md` | the table, with what each phase physically does |

`B` prints one `@n STEP step= total= phase= action= text= status=` line per
phase, **before that phase runs**. `phase` is a stable machine identifier that
UIs switch on, so **renaming one is a protocol change, not a wording change** —
and a silent one, because a browser that does not recognise an id falls back to
a generic "moving" rather than crashing. Change all three places together;
`twin.test.ts` asserts the browser's table matches the documented fourteen.

One phase is announced twice: **phase 11 gets a second line with
`status=done`**, the instant the jaws open and the block is on the stack. It is
the only `done` in the protocol and it exists because nothing else can carry
that fact — `BUILD_PARK_AFTER_PLACE` can be false, so there may be no phase 12
to imply it. **It is not a terminal ack.** The command is still running, the
rig still has to park, and a parking failure downgrades the build to `HELD`.
Only `@n OK` means the block is placed. `python/web/progress.py` is where that
distinction is enforced on the Pi.

The Z phases also carry `ms=`, the firmware's own prediction of how long that
move takes (`zEtaMs()`: exact step count x `stepPeriodMs(AXIS_Z)`). **It is on
the wire precisely because `Z_TRAVEL_STEPS`, `Z_TRAVEL_CM` and
`BLOCK_HEIGHT_CM` may not be copied into `config/rig.json`** — see the
"must NOT be copied" list below. A UI that worked the descent out for itself
would need all three and would drift the day `STEP_DELAY_Z` is retuned. It is a
FLOOR, not a schedule: the real move can only take longer, so nothing may treat
its expiry as the phase having finished. `ms=0` is never sent — absent means
"no idea", which is not "instant".

**One line per phase, never one per motor step.** Fourteen lines is ~0.3 s of
9600-baud airtime inside a 40-second build; per-step telemetry would be minutes
of it and would starve the terminal ack. If continuous position is ever wanted,
throttle it hard inside the movement loops — and it is still not a reason to
change the baud.

### 6. Firmware command vocabulary

The sketch's commands (`B`, `G`, `S`, `0`, `0+`, `5`, `9`, `Z`, `U`, `D`, `O`,
`C`, `V`, `A`, `R`, `RR`) are the contract between the two machines. `V <angle>`
sets the gripper servo to an integer angle from 0 to 180 degrees. `A <degrees>`
is a signed, **relative** auxiliary-stepper jog: `-360..360`, positive CW and
negative CCW. It cannot be an absolute angle because that motor has no home
switch or angle sensor.

Two of these changed meaning and one lost an argument:

- **`R` and `RR` are the grid mode latch, not a claw jog.** `R` selects the
  vertical grid, `RR` the horizontal one. Neither moves the aux stepper.
  Neither is accepted unless X and Y are homed, and each is refused when it is
  already true — a latch that confirms a state nobody asked for cannot tell a
  confirmation from a mistake. `python/rig/link.py` sends them through
  `set_mode()`, matching the prose `GRID MODE:` and `ERROR - already in`.
- **`A <degrees>` is manual bench rotation, not a new grid orientation.** A
  non-0/+90/-90 command has no calibrated tool offset, so manual `G` and an
  `R`/`RR` latch are refused until a `B` returns the claw to neutral. `B`
  explicitly corrects the tracked manual angle at its feeder-safe step 3.
- **`B` no longer takes a rotation word.** `B <col> <row> <level>`, three
  numbers, nothing after them. How the block is laid comes from the active
  grid. A fourth word is a parse error that names the latch.
- **`@0 READY` carries `mode=` beside `grid=`.** A reset silently returns the
  board to vertical, so the Pi is told rather than left to assume.

If you rename a command, change its arguments, or change the text it prints on
success or failure, **grep `python/` for the old form first.** `B` has an `@`
ack and is safe from rewording, but `S`, `G`, `0` and `0+` do not — for those,
`link.py` waits on the prose. The strings it matches are all in one place,
`_prose_outcome()` and the `done=` arguments in `python/rig/link.py`.

### 7. The studio's shipped defaults and the main camera feed

| Where | What |
| --- | --- |
| `python/config/camera_settings.json` | the committed default settings |
| `camera_studio.py` `Studio.__init__` | the built-in defaults `--fresh` and `reset` use |
| `camera/camera_feed.py` | the canonical runtime feed that consumes the saved settings |
| `camera/gridded_camera_feed.py` | the same runtime feed plus machine-grid calibration/overlay |
| `camera/rig_build_v1.py` | camera-grid cell selection plus confirmed serial build |
| `camera/color_grid_check.py` | the printed-sheet detector on its own, live or on a still |
| `camera/block_grid_calibrate.py` | the placed-block calibrator (§3d-bis); `--mock` is a hardware-free dry run |
| `python/config/camera_settings.json` -> `colour` | the software colour correction all of the above apply |
| `rig/build_job.py` | the worker thread that keeps that camera live during a build |
| `camera/undistorted_viewer.py` | the standalone lens-tuning viewer |

`camera_studio.py` is supposed to open showing **exactly what
`camera_feed.py` renders** from the committed settings — same remap table, same
output size, correction on, no zoom or crop. That is three things agreeing, and
nothing enforces it at runtime.

`camera/camera_feed.py` is the main camera script. It must load
`python/config/camera_settings.json` (or an explicitly supplied settings path),
apply its capture and sensor values, then produce the configured camera frame.
Future vision stages build from this feed instead of opening the camera a second
time. The feed owns the first block-detection pass: clean contours, colour-coded
rotated boxes, centres, hover coordinates and saved detection metadata. Later
mapping code should consume those detections. `camera_studio.py` is the editor
that writes the file; it is not the runtime pipeline entry point.

`camera/gridded_camera_feed.py` is an alternate presentation of that canonical
pipeline, not a second interpretation of camera settings. It imports the feed's
settings, correction, enhancement, detection and snapshot helpers. Keep those
shared rather than letting the gridded version drift. Its grid comes only from
`config/rig.json`, and its four clicked envelope corners are saved as the
generated `config/workspace_map.json`. Before calibration it may show only an
explicitly amber **APPROXIMATION ONLY** grid; never display a full-frame guess
as calibrated. A change to lens geometry, orientation, framing, cell geometry
or grid trims must invalidate the saved workspace map.

`camera/rig_build_v1.py` is the first hardware-moving camera UI. Preserve all
of these rules when editing it:

- Both the amber approximate map and a saved calibrated `WorkspaceMap` may
  select a build target. Calibration refines the camera mapping but is optional.
- A click selects and shows the exact `B <col> <row> <level>` command;
  it never moves hardware. `b`/Enter is the separate confirmation.
- Send builds only through `rig.link.Rig.build()`, never a second raw serial
  connection. That call blocks for minutes, so `rig/build_job.py` runs it on one
  worker thread and the camera loop keeps drawing. The UI must refuse every
  controller mutation — select, level, rotation, deselect, calibrate, build,
  quit — while `BuildJob.running`, so clicks still cannot queue while the Mega
  is deaf during motion. Never run two builds at once, and never close the
  serial port with one in flight: join the job first.
- A successful build clears selection so key repeat cannot place twice in one
  cell. A safe rejection may retain it. `ABORTED`, reset, timeout or cable loss
  locks the session: no retry, no automatic home, no further build. A human
  inspects the claw/rig and restarts.
- The UI's `level` is the firmware's block-stack level (the fourth `B` token),
  not raw Z steps or centimetres. Firmware remains authoritative for its range.

The printed-sheet calibration (`p` overlay, `k` calibrate) is a **second route
to the same artefact**, not a second artefact. Both feeds must keep writing the
identical `config/workspace_map.json` through `WorkspaceMap.from_grid`, with the
same projection identity and the same invalidation rules — nothing downstream
of the map is allowed to learn that the sheet exists. `PaperGridTracker`,
`paper_workspace_map` and `draw_paper_grid` live in `gridded_camera_feed.py` and
are imported by `rig_build_v1.py`; keep them shared rather than letting the two
drift, the same way `draw_machine_grid` already is. In `rig_build_v1.py` the
`k` key carries every guard `c` carries: refused during a build (it is in
`forbidden_during_build`), refused on a stale camera, and it clears the current
selection.

`vision/block_detector.py` must not assume one connected colour component is
one block. Touching standard blocks produce L, U, cross, side-by-side and
end-to-end unions. Colour proposes the component; straight edges, internal
seams and the standard four-sided block dimensions decompose it into individual
rectangles. Keep `tests/test_block_detector.py` covering those combinations.

The `lens` block in `camera_settings.json` is consumed by `camera_feed.py` so a
saved studio setup is reproducible. `config/lens_profile.json` remains the
separate generated profile used by the standalone lens/grid viewers, and the
studio's `lens` command keeps those two lens artefacts in sync.

If you change a `LensProfile` default, a `Studio.__init__` default, or the
committed JSON, check the other consumers too. The check is cheap and exact —
build the studio/feed maps for the same input size and compare the tables:

```python
from vision.fisheye import LensProfile, build_maps
import numpy as np
a = build_maps(LensProfile.load(), (1296, 972), "cubic", mip=True)   # the viewer
# ... studio's maps after read_settings + apply_overrides ...
np.array_equal(a.levels[0][0], b.levels[0][0])      # must be True
```

The JSON is not hand-written: regenerate it from `Studio(args, LensProfile())`
and strip `saved_at`, `camera` and `derived`, so it cannot drift from the code
it is meant to mirror.

**The lens trims `k1`, `k2`, `centre_dx`, `centre_dy` default to zero and that
zero is load-bearing.** They are an exact no-op at zero, which is what lets
`fisheye.py` grow them without changing what every existing tool renders. If you
ever give one a non-zero default, the grid viewers' geometry moves with it.

---

## What must NOT be copied into `config/rig.json`

These are physical facts about the machine. Nothing can push them over serial,
so a copy in the JSON would be a lie that nobody notices until the rig crashes
into something.

- firmware-only X/Y software caps (`X = 4750`, `Y = 8250`)
- `Z_TRAVEL_CM`, `Z_TRAVEL_STEPS`, `BLOCK_HEIGHT_CM`, build ceiling
- pin assignments, servo angles, motor direction polarity

The firmware owns all of it. If the Pi needs one of these numbers, it parses the
`5` report — it does not keep its own copy.

**The dividing line:** `rig.json` owns what can change without reflashing. The
firmware owns what cannot.

## `config/lens_profile.json` is not config

It is a *generated artefact*. The viewers write it with their `save` command
(`camera_studio.py` calls the same thing `lens`), and one day a checkerboard
calibration will. Never merge it into `rig.json` — a calibration run would then
be able to silently rewrite your serial port. It is referenced by path, not by
value.

`python/config/camera_settings.json` is the same kind of thing, one layer out:
`camera_studio.py` reads it at startup and its `save` writes it, and it holds
the lens block **plus** the sensor controls, the crop stack and the frame
orientation. Same rules — generated, not hand-authored, referenced by path. It
is not the source of the lens parameters the other tools read;
`lens_profile.json` still is, and the studio's `lens` command copies one into
the other.

`config/workspace_map.json` is also generated. The gridded feed writes it after
four prompted clicks around the complete machine envelope. It contains the
camera projection identity and the physical grid geometry it was made against;
do not hand-edit it or treat normalized corner pixels as portable across lens,
orientation, crop or grid changes.

---

## Environment rules that will bite you

**On the Pi, numpy and OpenCV come from apt. Everything else goes in the venv.**
The venv is built with `--system-site-packages` so it can see the apt
`python3-picamera2` and `python3-opencv`, which are compiled against the system
numpy. Pip-installing `numpy` or `opencv-python` shadows that and breaks
`import picamera2` with an ABI error.

Every other dependency installs into the venv normally, on both machines. The
test for a new package is: **pure Python, no compiled extension, no numpy
dependency?** Then it goes in `requirements.txt`. Otherwise it goes in
`requirements-dev.txt` and the Pi gets it from apt instead.

    pip show <pkg> | grep Requires      # what it drags in
    find .venv/lib/*/site-packages/<pkg> -name "*.so"   # compiled? then no

**The two machines disagree about `python` vs `python3`.** The Pi has `python`;
the x86 desktop has `python3`. This matters in exactly one place — the command
that *creates* the venv. Everywhere else, invoke `.venv/bin/python` or
`.venv/bin/pip`, which exist on both. Never hardcode `python3` in a script that
runs on the Pi: `scripts/flash.sh` detects the interpreter instead, and anything
new should do the same.

**There is no Arduino toolchain on the dev desktop.** `arduino-cli compile` runs
on the Pi and is the only real syntax check. Locally, a `.ino` edit can be
checked with a stub-Arduino g++ harness — that proves it parses, not that it
builds for AVR and definitely not that it behaves.

**A clean compile is not a test.** Anything touching motion, limits or Z has to
be flashed and watched on the physical rig.

**Camera code cannot be verified on the desktop.** The Pi 5's CSI camera is
reachable only through Picamera2. Keep the V4L2 fallback working, and say
plainly which paths are untested when handing work over.

---

## `arduino/archive/` is dead code

Do not flash it, do not fix bugs in it, do not update it to match a change made
in `build_test_v1`. Several archived sketches disagree with the live one about
limit switches and Z travel. `build_test_v1` is the only sketch that matters.

---

## Adding a new shared value

If you add something that has to exist on both sides, **add a row to this file
in the same commit.** A shared value that is not listed here is a shared value
that will drift.

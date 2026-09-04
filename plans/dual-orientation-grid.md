# Dual-orientation grid — vertical and horizontal, both calibrated

**State:** built on the desk — all eight steps have regression coverage; camera
and hardware verification remain. See §10 for exactly what has and has not run.
**Blocked on:** nothing; §4 was answered (see §4)

The rig currently knows one grid: blocks standing with their 7.5 cm side along
Y, packed 9 × 5. This plan adds a second, equally valid grid where the block
lies with its 7.5 cm side along X, packed 3 × 15 — and makes both of them
first-class, separately calibrated, and separately stored.

The change is larger than it looks. Every centimetre constant in the project
silently assumes the vertical layout, on both machines. This plan's real work
is introducing **mode** as a dimension that the geometry, the firmware, the
camera calibration and the printed sheet all agree on.

---

## 1. Locked decisions

Every row here was decided deliberately. Do not re-litigate them mid-
implementation; if one turns out to be wrong, stop and say so rather than
quietly working around it.

| # | Decision | Rationale |
| --- | --- | --- |
| D1 | Vertical is 9 × 5. Horizontal is 3 × 15. | Derived in §3. Both are hard geometric maxima. |
| D2 | The build **always starts vertical**. | No EEPROM; a USB open resets the board. Vertical is the compiled default. |
| D3 | `RR` switches vertical → horizontal. `R` switches horizontal → vertical. | The operator's mental model. |
| D4 | `RR` is rejected when already horizontal; `R` is rejected when already vertical. | No free-running jog. The command is a latch, not a motion. |
| D5 | **`R`/`RR` never move the aux stepper.** They set grid layout only. | The claw must return to neutral to grip from the feeder anyway (D6), so any turn at latch time is undone by the next build's step 3. A motion here would be purely cosmetic and would read as a bug. |
| D6 | The build cycle's rotation handling is **unchanged**. Step 3 goes neutral to pick, step 9 rotates to place, step 14 returns to neutral. | The feeder presents blocks in one fixed orientation. The claw physically cannot hold a rotation across a pickup. |
| D7 | `wantRot` is **derived from the active mode**, not passed per block. Vertical → `ROT_NONE`, horizontal → `ROT_CW`. | Follows from D5 + D6. |
| D8 | The rotation word is **removed** from `B <col> <row> <level>`. | Rotation is now a property of the grid, not of a block. A per-block rotation could place a block rotated inside a grid whose cell geometry does not match it — the exact failure this plan exists to prevent. |
| D9 | Mode switching is **refused unless X/Y are homed**. | A mode switch redefines what every coordinate means. `curCol`/`curRow` become meaningless mid-travel; homing makes the reindex unambiguous. |
| D10 | The operator is trusted to start with the claw physically vertical. **Document this loudly.** | Nothing senses claw angle. There is no way to verify it in software. |
| D11 | `rig.json` gains `grid.modes.{vertical,horizontal}`, each **self-contained**. | See D12. |
| D12 | Each mode declares `block_x_cm` and `block_y_cm` outright. There is no shared `block_width`/`block_length` that gets swapped. | A swap has to be performed identically in the firmware, in `MachineGrid`, and in the camera overlay. Three chances to get a sign or an axis backwards. Declaring both per mode removes the operation entirely. |
| D13 | Trims, error offsets and gaps are **per mode per axis**. | X and Y were already separate. Mode is the missing dimension. |
| D14 | Horizontal ships at `trim_x = +1.9 cm`, `trim_y = +1.9 cm`; vertical trims remain zero. **Do not copy vertical's trims.** | The horizontal origin is registered from the pickup cell: the block is picked up standing at vertical `[0,0]` (centred on home) and rotated 90° about the grip. The rotated 6.0 cm face overhangs the 2.2 cm vertical footprint by `6.0/2 − 2.2/2 = 1.9 cm` per side, so a +1.9 cm trim on each axis seats horizontal `[0,0]` flush against the vertical `[0,0]` block edge. This is a grid-registration trim, not a tool offset. |
| D15 | `tool_offsets` stays **separate** from trims and keeps its `neutral`/`cw`/`ccw` shape. `cw` has no grid/build route but stays in the schema. | Trim moves cell *centres* (grid layout). Tool offset moves the *holder* for a given centre (claw asymmetry). Conflating them makes calibration unfalsifiable — two knobs that both look like "shift everything". |
| D16 | `S <cols> <rows>` survives, **scoped to the active mode** and revalidated against that mode's geometry. | Keeps the bring-up path and the reconnect handshake. |
| D17 | One `config/workspace_map.json`, with both calibrations under keyed modes. Old flat files migrate into `modes.vertical` on read. | Keeps the two calibrations visibly in sync in one artifact. |
| D18 | The detector takes mode as an **explicit input**, and uses cell counts as a **cross-check that refuses a mismatch**. | A partially visible sheet cannot be counted reliably, so inference is unsafe. But 10 short / 6 long vs 16 short / 4 long is unmistakable when fully visible, so it makes a free guard against calibrating with the wrong sheet. |
| D19 | All existing detector robustness is retained for horizontal: multi-grid detection with operator selection, partial-cell rejection, evidence pooling across frames. | Non-negotiable. Horizontal is not a degraded mode. |
| D20 | `gridGeometryFits` gains a **block-edge** check alongside its centre check, measured against a **per-mode overhang budget** that each mode declares. | See R2, and the amendment below. |
| D21 | `A <degrees>` is a signed, relative manual aux-stepper jog (`-360..360`, positive CW). It is never a grid mode or a build rotation choice. | The aux motor has neither a home switch nor an absolute angle sensor. An arbitrary manual angle has no calibrated tool offset, so `G`, `S` and `R`/`RR` refuse it; a build returns it to neutral at its feeder-safe step 3. |

> **D20 was amended during implementation (§8 rule 5).** As first written, D20
> said only "add a block-edge check". No such check can be written: the rule
> has to reject horizontal at `trim_x = 1.1`, whose far edge is 0.95 cm past
> the X limit, while accepting the shipped vertical grid, whose far edge is
> **1.10 cm** past that same limit. The overhang is always
> `(last_centre − travel) + block/2`, so vertical — which puts its last centre
> exactly on the travel limit — has the *largest* overhang of the three, and
> every monotone "edge ≤ limit" rule rejects it too.
>
> The fix is to make the tolerated overhang an explicit per-mode number rather
> than something inferred: `max_edge_overhang_x_cm` / `_y_cm`, added to §5's
> config shape and to the firmware's SECTION 6C tables. Vertical declares half
> a block on each axis (1.1 / 3.75); horizontal declares zero. A mode that
> omits the pair gets half a block, which makes the new check exactly as
> permissive as the old centre-only one — so no legacy config starts failing.
>
> This adds one config/firmware pair that §5 and D11/D12 did not list. D12's
> principle is unharmed: the budget is stated outright per mode and nothing
> swaps or derives it.

---

## 2. Files this touches

Nothing outside this list should change. If the work wants to touch something
else, that is a signal to stop and re-read the plan.

### Firmware — `arduino/build_test_v1/build_test_v1.ino`

| Region | What changes |
| --- | --- |
| SECTION 6C, ~L532-547 | `GRID_BLOCK_*`, `GRID_GAP_*`, `GRID_TRIM_*`, `GRID_ERROR_OFFSET_*`, `GRID_COLS`/`GRID_ROWS` become per-mode tables, not scalars |
| L2013-2033 | `gridBlockCmOf` / `gridGapCmOf` / `gridTrimCmOf` — **the single seam.** Make these read the active mode and most downstream maths follows unchanged |
| L2081-2095 | `gridGeometryFits` — add the block-edge check (D20) |
| L2098-2119 | `gridCountMaxOf` — revalidate under the active mode |
| L2249+ | `setGridSize` — scope to active mode (D16) |
| L1236, L1325 | The `'R'` handler and `CMD_AUX_STEPPER_CW` — replace free jog with the latch (D3, D4, D5, D9) |
| L2575-2677 | `B` command parsing — remove the rotation word (D8) |
| ~L2921, ~L2974, ~L2783 | Build steps 3 / 9 / 14 — unchanged behaviour, but `wantRot` now comes from mode (D7) |
| L3624+, L3903-3965 | `printGridConfig` and `printGrid()` — report the active mode; the map becomes 4 wide × 16 tall |
| L42, L2581-2588, L4616 | Help text — document the latch, D10's trust assumption, and the removed rotation word |

### Config

- `config/rig.json` — the `grid` block is restructured (§5)
- `config/workspace_map.json` — two keyed modes (D17)

### Python core

- `python/rig/config.py` — schema plus a mode accessor
- `python/rig/grid.py` — `MachineGrid.from_config()` takes a mode. **Do not overload `swap_axes`**; it means camera-vs-machine image orientation, which is a genuinely different concept from block orientation
- `python/rig/workspace.py` — `load` / `save` / `matches_grid` (L142-186) gain a mode; migration for flat files
- `python/rig/link.py` — mode command, `set_grid` (L558), `build()` loses its rotation arg (L604-635), reconnect handshake pushes mode **before** `S`
- `python/rig/build_controller.py` — `ROTATIONS` / `set_rotation` / `cycle_rotation` (L11-83) become mode selection, not per-block rotation
- `python/rig/build_job.py` — drop rotation from job entries

### Vision / calibration

- `python/vision/color_grid.py` — `SUPPORTED_LAYOUT` (L80) becomes two supported layouts; the pitch→axis rule (R5) inverts per mode; add the count cross-check (D18)
- `python/vision/grid_evidence.py` — `MIN_CELLS` (L23) and the coverage gates become per-mode
- `python/vision/color_grid_overlay.py`, `python/vision/overlays.py` — per-mode cell aspect
- `python/camera/color_grid_check.py`, `python/camera/gridded_camera_feed.py`, `python/camera/rig_build_v1.py` — mode selection in the calibration UI
- `python/grid/undistorted_grid_viewer.py`

### Tests

`test_grid.py` (parses live sketch constants — will need per-mode pairs),
`test_link.py`, `test_build_controller.py`, `test_build_job.py`,
`test_color_grid.py`, `test_gridded_feed.py`, `test_block_detector.py`.

### Docs — see §8, this is not optional

`AGENTS.md` §3, §3a, §3b, §3c, §3d; `plans/README.md`;
`plans/printed-grid-spec.md` R5/R6 and the "vertical only" section (L198-203);
`plans/printed-color-grid.md`; `plans/evidence-assisted-printed-grid-calibration.md`;
`plans/plan-2-click-to-build.md`; `python/GUIDE.md`; `python/README.md`;
`arduino/README.md`.

---

## 3. The math, verified

> **Superseded geometry (block/gap change).** The block plan is now
> **2.2 × 6.0 cm** with gaps **1.6 cm along X, 0.8 cm along Y** in both modes;
> `BLOCK_HEIGHT_CM` stays 1.5. Vertical is **6 × 5**, horizontal is **2 × 10**.
> Vertical trims remain zero; horizontal ships at `trim_x = trim_y = +1.9 cm`
> for the pickup-cell registration described in D14 (later revised from the
> single-axis `trim_y = +1.6` this note originally quoted; `config/rig.json` and
> `python/tests/test_grid.py` `SECTION_3` are authoritative). Horizontal also
> **shipped** a measured `error_offset_x = +0.5`, `error_offset_y = +0.3` cm
> for the pickup-rotate slop. **That was corrected — both are now 0.** The
> swing is claw geometry, so per D15 it belongs in `tool_offsets.cw`, which is
> now `(+0.9, −0.3) cm`; `error_offset` is rotation-blind and its X sign was
> measured under CCW while the build rotates CW, which placed horizontal blocks
> 1.4 cm too far from the X home switch. Horizontal centres are therefore
> trim-only: X `1.9 → 17.1`, Y `1.9 → 36.1`. Vertical error
> offsets ship at
> `(+0.15, +0.05) cm` for X/Y after incremental correction: the prior
> `(+0.15, -0.45) cm` was increased by the newly measured `0.5 cm`
> toward-home Y error. The tables below are recomputed
> at the shipped calibration. The decision log (D1–D20) and §4–§8 below are the
> original record and still describe the *mechanism*; only the numbers moved.
> `python/tests/test_grid.py` `SECTION_3` mirrors the tables here.

Travel is physical and **mode-independent**: X = 24.3 cm, Y = 40.0 cm.

The firmware model:

```text
pitch      = block + gap
allocation = count * pitch
start      = (travel - allocation) / 2 + trim + error_offset
firstCentre= start + gap + block/2
lastCentre = firstCentre + (count - 1) * pitch
footprint  = count * block + (count - 1) * gap
```

### Vertical — 6 × 5, shipped calibration

| axis | block | gap | pitch | count | footprint | centres | block edges |
| --- | --- | --- | --- | --- | --- | --- | --- |
| X | 2.2 | 1.6 | 3.8 | **6** | 21.20 | 3.60 → 22.60 | 2.50 → 23.70 |
| Y | 6.0 | 0.8 | 6.8 | **5** | 33.20 | 6.35 → 33.55 | 3.35 → 36.55 |

30 build cells; 7 × 6 addressable including the zero lanes. Block edges beyond
travel are **expected and safe** — the holder only needs to reach each *centre*,
and the held block overhangs. Vertical keeps a half-block overhang budget
(`1.1` / `3.0`).

### Horizontal — 2 × 10, shipped calibration

X and Y swap their block dimensions. Horizontal has `trim_x = trim_y = +1.9 cm`
for the pickup-cell registration (this sub-table's numbers below predate that
and the block-edge budget amendment in D20 — see `config/rig.json` and
`test_grid.py` `SECTION_3` for the shipped values).

| axis | block | gap | pitch | count | footprint | centres | block edges |
| --- | --- | --- | --- | --- | --- | --- | --- |
| X | 6.0 | 1.6 | 7.6 | **2** | 13.60 | 9.15 → 16.75 | 6.15 → 19.75 |
| Y | 2.2 | 0.8 | 3.0 | **10** | 29.20 | 8.50 → 35.50 | 7.40 → 36.60 |

20 build cells; 3 × 11 addressable including the zero lanes.

**These counts are the printed grids, not maxima.** Against the 24.3 × 40.0 cm
travel at trim 0, vertical could take a 6th Y row and horizontal a 3rd X column
/ up to 13 Y rows before `gridGeometryFits` refuses the next cell. A 7th
vertical column (`7 × 3.8` allocation, last centre 24.35 cm) and a 4th
horizontal column (`4 × 7.6`, last centre 24.35 cm) are both refused.

**Why trims cannot be copied between modes.** Once measured, the feeder-centre
shift is a property of how each grid sits relative to the pickup point. A
positive `trim_x` on the horizontal grid that keeps its last *centre* legal
still pushes the last block *edge* past the X wall, and `gridGeometryFits`
catches that only through the per-mode zero overhang budget. This is R2.

**Pickup-cell registration (current hardware behavior).** The feeder is a
vertical pickup cell, not a bare mathematical point. The block is picked up
standing at vertical `[0,0]`, centred on home, then rotated 90° about the grip
for `RR`. The rotated 6.0 cm face overhangs the 2.2 cm vertical footprint by
`6.0/2 − 2.2/2 = 1.9 cm` per side, so horizontal `[0,0]` is registered +1.9 cm
from the feeder on BOTH axes:

```text
positive / away from the home switch →

vertical pickup [0,0]       1.9 cm       horizontal [0,0] reference
┌──────────────────────┐                 ┌──────────────────────┐
│  centre = 0          │<--------------->│  centre = +1.9        │
│   pickup reference   │   (same on X    │   RR reference        │
└──────────────────────┘    and on Y)    └──────────────────────┘
```

That whole-layout relationship is represented by
`horizontal.trim_x_cm = horizontal.trim_y_cm = +1.9`, not by `gap_*_cm` and not
by `tool_offsets.ccw`. `RR` only latches the mode. A build homes at the feeder,
picks up neutral, travels using the shifted horizontal centres, rotates 90°
CW at the target, and releases. `B 0 0 <level>` remains an inert sentinel and
does not physically test this reference. A future rig measurement may refine
the magnitude per axis; keep any such correction in `horizontal.trim_{x,y}_cm`
and never hide it inside the rotation/tool offset.

**Tolerance note.** The +1.9 cm registration plus the shipped `+0.5 / +0.3 cm`
error offset leaves horizontal far-end slack on each axis (X last centre 17.6
into 22.8, Y 36.4 into 38.0) and a −0.6 cm X near edge, inside its
`max_edge_overhang_x_cm = 3.0` budget. Measure a real stack before trusting the
last row of horizontal's 10.

---

## 4. Open input — ANSWERED

**The horizontal sheet maps 4 columns x 16 rows = 64 cells**, the same
convention as the existing 10 x 6 = 60: the positive grid plus the zero lanes.
The printed sheet is wider than its mapped extent (the operator reports about
1.5 wasted columns), which is exactly the case the detector's window search
already handles — it locates the mapped window inside a larger printed lattice,
as it does today on the vertical sheet. The paper size is therefore not needed
as a gate; if a horizontal capture turns out to need it, ask then.

The original question, kept for the record:

## 4 (original). Open input — required before Step 6

**The printed horizontal calibration sheet's layout: how many columns × rows of
printed cells, on what paper size?**

The existing sheet is 10 × 6 = 60 cells — the 9 × 5 grid *plus the zero lanes*
(`printed-grid-spec.md:84`). Under the same convention horizontal wants
**4 × 16 = 64**. The operator has stated a new sheet exists and wastes about
1.5 columns, so its printed extent is wider than its mapped extent — both
numbers are needed.

Three gates depend on it and must not be guessed:

- `printed-grid-spec.md` R6 asserts "exactly 60 cells are mapped" as acceptance
- `grid_evidence.py:23` hardcodes `MIN_CELLS = 36`, commented "60% of the 10x6 printed map"
- the evidence-route edge/coverage gates are all scaled to that map

Steps 1-5 do not depend on this. **Do not block the whole plan on it** —
implement through Step 5, then ask.

---

## 5. Target config shape

```json
"grid": {
  "active_mode": "vertical",
  "modes": {
    "vertical": {
      "cols": 9, "rows": 5,
      "block_x_cm": 2.2, "block_y_cm": 7.5,
      "gap_x_cm": 0.5, "gap_y_cm": 0.5,
      "trim_x_cm": 1.1, "trim_y_cm": 3.75,
      "max_edge_overhang_x_cm": 1.1, "max_edge_overhang_y_cm": 3.75,
      "error_offset_x_cm": 0.0, "error_offset_y_cm": 0.0
    },
    "horizontal": {
      "cols": 3, "rows": 15,
      "block_x_cm": 7.5, "block_y_cm": 2.2,
      "gap_x_cm": 0.5, "gap_y_cm": 0.5,
      "trim_x_cm": 0.0, "trim_y_cm": -0.25,
      "max_edge_overhang_x_cm": 0.0, "max_edge_overhang_y_cm": 0.0,
      "error_offset_x_cm": 0.0, "error_offset_y_cm": 0.0
    }
  }
}
```

`workspace`, `observed_build_area`, `tool_offsets`, `serial`, `board` and
`frame` are **unchanged** — travel and claw geometry are physical, not per-mode.

---

## 6. Risks to design against

- **R1 — Silent axis swap.** The most likely bug is one of the three consumers
  (firmware / `MachineGrid` / camera overlay) swapping block dimensions while
  another does not. Mitigated by D12: nothing swaps, each mode states both.
- **R2 — A validator that accepts an out-of-bounds grid.** `gridGeometryFits`
  checks centres only. Both wrong-trim cases in §3 pass it. D20 fixes this, and
  it must be implemented **before** any horizontal geometry is flashed.
- **R3 — Calibrating with the wrong sheet.** Mitigated by D18's count cross-check.
- **R4 — Mode desync across the reset boundary.** A USB open resets the Arduino
  to vertical. If Python believes horizontal, every coordinate is wrong. The
  reconnect handshake must push mode **before** `S`, and re-push after any reset.
- **R5 — Zero margin at row 15.** See §3's tolerance warning.
- **R6 — Stale calibration.** A `workspace_map.json` calibrated for one mode
  must never be applied to the other. `matches_grid` must compare mode too.

---

## 7. Implementation steps

Work them in order. Each step ends in a committable, testable state. **Do not
start a step until the previous one's acceptance passes.**

### Step 1 — Config schema and migration

Restructure `config/rig.json` to §5. Update `python/rig/config.py` with a mode
accessor and a loader that raises clearly on an unknown mode. Provide migration
so a flat legacy `grid` block reads as `modes.vertical`.

*Acceptance:* `rig.config.load()` returns both modes; a legacy-shaped file still
loads; an unknown mode name raises a readable error, not a `KeyError`.

### Step 2 — `MachineGrid` per mode

`MachineGrid.from_config(mode=...)`. Keep `swap_axes` meaning exactly what it
means today (camera-vs-machine image orientation) — **do not** reuse it for
block orientation. All the `*_cm` properties follow from the per-mode fields
with no swapping logic.

*Acceptance:* the §3 tables reproduce exactly from `MachineGrid` for both modes —
every footprint, first centre, last centre and block edge. Add these as test
cases; they are the plan's numeric contract.

### Step 3 — Firmware geometry per mode

Convert the SECTION 6C scalars to per-mode tables. Route everything through
`gridBlockCmOf` / `gridGapCmOf` / `gridTrimCmOf`. Add D20's block-edge check to
`gridGeometryFits`. Update `printGridConfig` and `printGrid()`.

*Acceptance:* `test_grid.py` passes with per-mode JSON/firmware pairs. `9`
prints a 4 × 16 map in horizontal. `gridGeometryFits` now **rejects** horizontal
at `trim_x = 1.1` — verify this explicitly; it is R2's regression test.

> No local Arduino toolchain exists. Syntax-check `.ino` edits with a
> stub-Arduino `g++` harness before handing them over, and say plainly that
> nothing was flashed or run on hardware.

### Step 4 — The mode latch

Replace the free `R`/`RR` jog with the latch: `RR` only from vertical, `R` only
from horizontal, both refused unless X/Y are homed (D9), **neither moving the
aux stepper** (D5). On switch, reload counts and geometry and reindex
`curCol`/`curRow`. Update help text with D10's trust assumption.

*Acceptance:* `RR` from horizontal errors; `R` from vertical errors; a switch
while un-homed errors; the aux stepper does not move on either command; `9`
reflects the new geometry immediately after a switch.

### Step 5 — Remove per-block rotation

Drop the rotation word from `B` parsing. Derive `wantRot` from the active mode
(D7). Build steps 3 / 9 / 14 keep their current behaviour. Update
`link.build()`, `build_controller`, `build_job` and their tests.

*Acceptance:* `B 1 1 0 RR` is now a parse error with a message naming the mode
latch. A horizontal build still rotates at step 9 and returns to neutral at 14.

### Step 6 — Detector, both layouts *(needs §4)*

Two supported layouts. Invert the pitch→axis rule per mode. Add the count
cross-check (D18). Per-mode `MIN_CELLS` and coverage gates. **Every robustness
feature listed in D19 must work identically in horizontal** — multi-grid
detection with operator selection, partial-cell rejection, evidence pooling.

*Acceptance:* a horizontal capture calibrates; a vertical sheet offered in
horizontal mode is **refused** with a clear reason; multi-grid selection and
partial-cell rejection demonstrably work on a horizontal capture.

### Step 7 — Two-mode workspace map

`workspace_map.json` gains keyed modes. `load` / `save` / `matches_grid` take a
mode; `matches_grid` compares mode (R6). Migrate flat files into
`modes.vertical`. Update every calibration UI to select and label a mode.

*Acceptance:* both modes calibrate and persist independently; recalibrating one
leaves the other untouched; a legacy file migrates; a map from the wrong mode is
refused.

### Step 8 — Link handshake

Push mode before `S` on connect and after any detected reset (R4).

*Acceptance:* connecting while config says horizontal leaves the firmware in
horizontal with 3 × 15; a mid-session reset is detected and re-synced.

---

## 8. Documentation obligations — treat as part of every step

This repo's core rule is that paired values on the Pi and the Arduino change
**in the same commit** (`AGENTS.md`). This plan creates many new pairs, so doc
drift here is not cosmetic — it is how the two machines stop agreeing.

**Rules for the implementing agent:**

1. **No step is complete until its docs are updated in the same commit.** Not
   at the end of the plan. Each step.
2. **`AGENTS.md` is the priority.** §3, §3a, §3b, §3c and §3d all currently
   state single-mode facts as absolutes. Every one needs a mode dimension:
   - §3 — the "Current default: 9 × 5" statement and the `S`-on-connect account
   - §3a — the whole geometry table, plus the worked pitch/footprint block
   - §3b — numbering holds for both modes, but the map dimensions differ
   - §3c — `cw` has no grid/build route; say why it is retained and how the
     explicit manual `A 90` bench state is guarded
   - §3d — the sheet section needs the second sheet and the new layout rule
3. **Update the `plans/README.md` row** for this plan as its state changes
   (`draft` → `active` → `built`).
4. **`printed-grid-spec.md` R5 and R6 are now wrong** in the general case, and
   its "vertical only" section (L198-203) explicitly defers exactly what this
   plan builds. Rewrite all three rather than appending a note.
5. **If a decision in §1 changes during implementation, edit this file** to
   record what changed and why, in the same commit. A plan that no longer
   matches the code is worse than no plan.
6. **State plainly what was not verified on hardware.** Nothing here can be
   flashed or camera-tested from the dev machine. Every acceptance criterion
   involving the rig or the camera is a desk check until the Pi runs it.

---

## 9. What this plan does not do

- Records the historical horizontal-grid `ccw` tool-offset trial as X
  `+3.75 cm`, Y `+1.40 cm`. **Superseded — do not copy these in.** They predate
  the centre-anchored lattice, and the build rotation is `ROT_CW`, not CCW.
  `ccw` and `neutral` are zero; `cw` now carries the measured pickup-rotate
  swing `(+0.9, −0.3) cm`. See the §3 note on the error-offset correction.
- Does not change travel, step envelopes, Z levels or the feeder.
- Does not add a third orientation, or any rotation other than 90° CCW.
- Does not auto-detect the claw's physical angle. Nothing senses it (D10).
- Does not verify that the block is really 2.2 cm to within the tolerance that
  15 rows demands (§3).

---

## 10. Where the work stopped

**Built, with tests passing on the desk:**

- **Step 1** — `config/rig.json` restructured to §5 (plus D20's amended
  overhang budget). `python/rig/config.py` gained `GRID_MODES`,
  `active_grid_mode()`, `grid_geometry()`, `max_edge_overhang_cm()`,
  `UnknownGridMode` and `migrate_grid()` for legacy flat files.
  New test: `python/tests/test_config_modes.py` (23 checks).
- **Step 2** — `MachineGrid` takes `mode`, its block fields were renamed
  `block_x_cm` / `block_y_cm` (D12), and it validates block edges against the
  per-mode budget. §3's tables are transcribed into `test_grid.py` as the
  numeric contract, both modes, every footprint / centre / edge.
- **Step 3** — firmware SECTION 6C is per-mode tables indexed by `gridMode`;
  `gridColsNow()` / `gridRowsNow()` replaced the scalars; `gridGeometryFits`
  gained the block-edge half; `printGridConfig` reports the mode, its edge
  budget and its max counts. `test_grid.py` now pairs BOTH modes against the
  sketch's tables.
- **Step 4** — the mode latch. `setGridMode()` refuses when already in that
  mode, when un-homed, and when the target geometry does not fit; it reindexes
  `curCol`/`curRow` and moves nothing. `S` is scoped per mode. `@0 READY` now
  carries `mode=`.
- **Step 5** — the rotation word is gone from `B`; `buildRotationForMode()`
  derives `wantRot` (vertical → `ROT_NONE`, horizontal → `ROT_CW`); build
  steps 3/9/14 are untouched. `link.build()` lost its rotation argument and
  gained `set_mode()` / `sync_mode()`; `BuildController`'s rotation state
  became mode selection; `rig_build_v1.py`'s `o` key latches the grid.

**Docs updated in step:** AGENTS.md §3, §3a, §3b, §3c, §6; `arduino/README.md`;
`python/README.md`; `python/GUIDE.md`; `plans/ack-protocol.md`;
`plans/README.md` (draft → active). D20's amendment is recorded in §1.

**Step 6 is built and desk-tested.** `ColorGridSpec` takes an explicit mode;
vertical maps 10 x 6 printed coordinates and horizontal maps 4 x 16. The
pitch-to-axis mapping follows that mode, not the image. Count and physical
geometry are cross-checked before a sheet map can be applied to a
`MachineGrid`. Horizontal synthetic tests cover 64 mapped cells, overlapping
operator-selectable windows, partial-cell rejection, wrong-layout refusal and
the evidence collector's scaled coverage gates.

**Step 7 is built and desk-tested.** `workspace_map.json` version 3 stores
per-mode entries in `modes.vertical` / `modes.horizontal`; saving one preserves
the other. Flat version-2 maps migrate as vertical only, and a map is refused
if its stored mode differs from the current `MachineGrid`. All calibration
entry points select the mode (`--mode` in the non-moving feeds; the rig UI
rebuilds the sheet tracker and reloads that mode's map when `o` latches it).

**Step 8 is built and desk-tested.** The connect-time half remains mode then
`S`; `test_link.py` asserts `RR` precedes `S 3 15`. An unexpected `BOOT` now
latches a reset state so an idle reset cannot be drained by a later command.
`recover_after_reset(home=True)` explicitly homes and then replays mode before
`S`. It is intentionally not automatic: reset loses X/Y homing and D9 forbids
the horizontal latch until after home; the hardware-moving UI still locks the
session for a human inspection rather than invoking recovery itself.

**Docs updated with these steps:** AGENTS.md §3d;
`plans/printed-grid-spec.md`, `plans/printed-color-grid.md` and
`plans/evidence-assisted-printed-grid-calibration.md` now describe both sheets
and per-mode evidence gates; `plans/plan-2-click-to-build.md`, `python/GUIDE.md`
and `python/README.md` describe the keyed workspace map and reset recovery.

### Verification honesty

Nothing here has been flashed or run on hardware, and no camera has seen any of
it. The firmware was checked two ways on the dev desktop, both of which prove
the code and neither of which proves the rig:

- a stub-Arduino `g++` harness that hoists prototypes the way the Arduino
  preprocessor does, for a parse and type check;
- a second harness that compiles the real sketch and calls `gridGeometryFits`,
  `gridCountMaxOf`, `setGridMode`, `setGridSize` and `printGrid` directly. It
  reproduced every number in §3's tables, confirmed R2's regression (horizontal
  at `trim_x = 1.1` is rejected, and `gridCountMaxOf` drops to 2 columns),
  confirmed `trim_y = 3.75` allows only 12 rows, and printed the 4 x 16 map.

Both harnesses live in this session's scratchpad, not in the repo. Whoever
picks this up should expect to rebuild them, or to flash and check on the rig.

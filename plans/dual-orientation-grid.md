# Dual-orientation grid — vertical and horizontal, both calibrated

**State:** active — **steps 1-5 built and tested; steps 6, 7 and part of 8
remain.** See §10 for exactly where the work stopped.
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
| D7 | `wantRot` is **derived from the active mode**, not passed per block. Vertical → `ROT_NONE`, horizontal → `ROT_CCW`. | Follows from D5 + D6. |
| D8 | The rotation word is **removed** from `B <col> <row> <level>`. | Rotation is now a property of the grid, not of a block. A per-block rotation could place a block rotated inside a grid whose cell geometry does not match it — the exact failure this plan exists to prevent. |
| D9 | Mode switching is **refused unless X/Y are homed**. | A mode switch redefines what every coordinate means. `curCol`/`curRow` become meaningless mid-travel; homing makes the reindex unambiguous. |
| D10 | The operator is trusted to start with the claw physically vertical. **Document this loudly.** | Nothing senses claw angle. There is no way to verify it in software. |
| D11 | `rig.json` gains `grid.modes.{vertical,horizontal}`, each **self-contained**. | See D12. |
| D12 | Each mode declares `block_x_cm` and `block_y_cm` outright. There is no shared `block_width`/`block_length` that gets swapped. | A swap has to be performed identically in the firmware, in `MachineGrid`, and in the camera overlay. Three chances to get a sign or an axis backwards. Declaring both per mode removes the operation entirely. |
| D13 | Trims, error offsets and gaps are **per mode per axis**. | X and Y were already separate. Mode is the missing dimension. |
| D14 | Horizontal seeds at `trim_x = 0.0`, `trim_y = -0.25`. **Do not copy vertical's trims.** | Copying produces an out-of-bounds grid that the current validator accepts — see R2 in §6. |
| D15 | `tool_offsets` stays **separate** from trims and keeps its `neutral`/`cw`/`ccw` shape. `cw` becomes unreachable but stays in the schema. | Trim moves cell *centres* (grid layout). Tool offset moves the *holder* for a given centre (claw asymmetry). Conflating them makes calibration unfalsifiable — two knobs that both look like "shift everything". |
| D16 | `S <cols> <rows>` survives, **scoped to the active mode** and revalidated against that mode's geometry. | Keeps the bring-up path and the reconnect handshake. |
| D17 | One `config/workspace_map.json`, with both calibrations under keyed modes. Old flat files migrate into `modes.vertical` on read. | Keeps the two calibrations visibly in sync in one artifact. |
| D18 | The detector takes mode as an **explicit input**, and uses cell counts as a **cross-check that refuses a mismatch**. | A partially visible sheet cannot be counted reliably, so inference is unsafe. But 10 short / 6 long vs 16 short / 4 long is unmistakable when fully visible, so it makes a free guard against calibrating with the wrong sheet. |
| D19 | All existing detector robustness is retained for horizontal: multi-grid detection with operator selection, partial-cell rejection, evidence pooling across frames. | Non-negotiable. Horizontal is not a degraded mode. |
| D20 | `gridGeometryFits` gains a **block-edge** check alongside its centre check, measured against a **per-mode overhang budget** that each mode declares. | See R2, and the amendment below. |

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

Travel is physical and **mode-independent**: X = 24.3 cm, Y = 40.0 cm.

The firmware model (`build_test_v1.ino:2045-2125`):

```text
pitch      = block + gap
allocation = count * pitch
start      = (travel - allocation) / 2 + trim
firstCentre= start + gap + block/2
lastCentre = firstCentre + (count - 1) * pitch
footprint  = count * block + (count - 1) * gap
```

### Vertical — 9 × 5, unchanged

| axis | block | gap | pitch | count | footprint | centres | block edges |
| --- | --- | --- | --- | --- | --- | --- | --- |
| X | 2.2 | 0.5 | 2.7 | **9** | 23.80 | 2.70 → 24.30 | 1.60 → 25.40 |
| Y | 7.5 | 0.5 | 8.0 | **5** | 39.50 | 8.00 → 40.00 | 4.25 → 43.75 |

45 build cells; 10 × 6 addressable including the zero lanes. The block edges
exceeding travel is **expected and safe** — the holder only needs to reach each
*centre*, and the held block overhangs. This is already documented in AGENTS.md §3a.

### Horizontal — 3 × 15

X and Y swap their block dimensions. `trim_x = 0.0`, `trim_y = -0.25`.

| axis | block | gap | pitch | count | footprint | centres | block edges |
| --- | --- | --- | --- | --- | --- | --- | --- |
| X | 7.5 | 0.5 | 8.0 | **3** | 23.50 | 4.40 → 20.40 | 0.65 → 24.15 |
| Y | 2.2 | 0.5 | 2.7 | **15** | 40.00 | 1.10 → 38.90 | 0.00 → 40.00 |

45 build cells; 4 × 16 addressable including the zero lanes. The same cell count
as vertical, by coincidence.

**Why these counts are maxima.** 4 columns needs `4 × 7.5 + 3 × 0.5 = 31.5 cm`
into a 24.3 cm axis — impossible. 16 rows needs
`16 × 2.2 + 15 × 0.5 = 42.7 cm` into 40.0 cm — impossible.

**Why 15 rows is exact.** `15 × 2.2 + 14 × 0.5 = 33.0 + 7.0 = 40.00 cm`, into
40.00 cm of travel. Zero slack at both walls, and the home-to-row-1 gap
collapses to zero. This is real but unforgiving:

- at `trim_y = 0.0` the far block overhangs the limit by 0.25 cm
- at `trim_y = -0.25` it is flush at both ends — **use this**
- at `trim_y = 3.75` (vertical's value) only 12 rows fit

**Why trims cannot be copied.** At vertical's `trim_x = 1.1`, horizontal's
columns sit at 1.75 → 25.25, putting column 3's far edge **0.95 cm past the X
limit** — and `gridGeometryFits` accepts it, because the *centre* at 21.5 is
legal. This is R2.

**Tolerance warning.** At 15 rows there is no margin to absorb error. A 1 mm
per-block error accumulates to 1.5 cm and costs a row. Measure the real block
width across a stack of 15 before trusting the horizontal Y calibration.

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
   - §3c — `cw` is now unreachable; say so and say why it is retained
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

- Does not calibrate `tool_offsets`. They stay zero. Horizontal placement
  accuracy is unverified until `ccw` is measured on hardware.
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
  derives `wantRot` (vertical → `ROT_NONE`, horizontal → `ROT_CCW`); build
  steps 3/9/14 are untouched. `link.build()` lost its rotation argument and
  gained `set_mode()` / `sync_mode()`; `BuildController`'s rotation state
  became mode selection; `rig_build_v1.py`'s `o` key latches the grid.

**Docs updated in step:** AGENTS.md §3, §3a, §3b, §3c, §6; `arduino/README.md`;
`python/README.md`; `python/GUIDE.md`; `plans/ack-protocol.md`;
`plans/README.md` (draft → active). D20's amendment is recorded in §1.

**Step 8 is half done.** The connect-time half of R4 is built and tested:
`connect()` calls `sync_mode()` and then `set_grid()`, in that order, and
`test_link.py` asserts `RR` precedes `S 3 15` on the wire. The mid-session
half is NOT: `RigReset` is still raised and left to the caller, with nothing
re-pushing the mode after it.

**Not started: steps 6 and 7**, and their doc obligations —
`plans/printed-grid-spec.md` R5/R6 and its "vertical only" section are still
wrong in the general case, and AGENTS.md §3d still describes one sheet.

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

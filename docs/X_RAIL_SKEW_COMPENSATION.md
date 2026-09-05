# Build-motion compensation: dynamic X/Y skew and fixed placement offset

## Symptom

When a block is placed with pure Y motion (same column, e.g. `B 0 3 0`) it lands
exactly where the grid says. When the placement involves X motion, the block is
off along **Y** — and the error grows with how far along X the rig travels. It is
**not** a constant offset.

Measured on the rig:

| Column index | Y error introduced |
| ------------ | ------------------ |
| 0            | 0.00 cm (no X travel) |
| 1            | 0.115 cm |
| 2            | 0.230 cm |
| 3            | 0.345 cm |
| k            | 0.115 × k cm |

Linear in the column index, with **no row dependence**.

## Mechanical cause

The arm holder is the carriage that rides the X aluminium rod. It is not
supported symmetrically: its own mass, the drag of the cable chain, and the side
load from the belt all pull on **one side** of the holder. That constant sideways
pull bows / twists the X aluminium rod slightly, so the rod is no longer square
to Y — it sits at a small angle.

The further the carriage is driven along X, the more of that angled rod it has
travelled over, so the carriage also drifts along Y. The drift is therefore
proportional to X travel: ~0 at column 0, growing by a fixed amount per column.

## Why we fix it in software

Re-machining or re-bracing the rod to remove the slant is out of scope for this
build. Instead we cancel the drift in firmware: for a build we deliberately
command Y to a position offset by exactly the drift the slanted rod will add, so
the two cancel and the block lands where the perfect grid says it should.

## The correction

In [`arduino/build_test_v1/build_test_v1.ino`](../arduino/build_test_v1/build_test_v1.ino),
just above `gotoBuildTarget()`:

```c
//                                      { vertical, horizontal }
float SKEW_X_PER_COL_CM[GRID_MODE_COUNT]    = {0.0f, 0.0f};
float SKEW_X_PER_ROW_CM[GRID_MODE_COUNT]    = {0.0f, 0.0f};
float SKEW_X_PER_COLROW_CM[GRID_MODE_COUNT] = {0.0f, 0.0f};
float SKEW_Y_PER_COL_CM[GRID_MODE_COUNT]    = {0.115f, 0.130f};
float SKEW_Y_PER_ROW_CM[GRID_MODE_COUNT]    = {0.0f, 0.0f};
float SKEW_Y_PER_COLROW_CM[GRID_MODE_COUNT] = {0.0f, 0.0f};

float BUILD_PLACEMENT_OFFSET_X_CM[GRID_MODE_COUNT] = {0.0f, -0.4f};
float BUILD_PLACEMENT_OFFSET_Y_CM[GRID_MODE_COUNT] = {0.0f, 0.0f};

long buildSkewSteps(uint8_t axis, long col, long row)
{
  float perCol = (axis == AXIS_X) ? SKEW_X_PER_COL_CM[gridMode]
                                  : SKEW_Y_PER_COL_CM[gridMode];
  float perRow = (axis == AXIS_X) ? SKEW_X_PER_ROW_CM[gridMode]
                                  : SKEW_Y_PER_ROW_CM[gridMode];
  float perColRow = (axis == AXIS_X) ? SKEW_X_PER_COLROW_CM[gridMode]
                                     : SKEW_Y_PER_COLROW_CM[gridMode];
  float cm = perCol * (float)col + perRow * (float)row
           + perColRow * (float)col * (float)row;
  return lround(cm * xyStepsPerCmOf(axis));
}

long buildPlacementOffsetSteps(uint8_t axis)
{
  float cm = (axis == AXIS_X) ? BUILD_PLACEMENT_OFFSET_X_CM[gridMode]
                               : BUILD_PLACEMENT_OFFSET_Y_CM[gridMode];
  return lround(cm * xyStepsPerCmOf(axis));
}
```

`buildSkewSteps(axis, col, row)` is independently **added** to each X and Y
build target inside `gotoBuildTarget()`, after `cellTargetPosition()` and before
the move. Each result is clamped to that axis's travel so a bad coefficient
cannot drive the carriage past a soft limit (`moveAxisTo()` still enforces the
limit as well).

**Sign** — "forward" = **+Y** = further from the Y home switch (the row 0 side).
The nudge is positive, so selecting cell `[1,0]` drives the rig ~0.115 cm forward,
`[2,0]` ~0.230 cm, `[k,r]` ~0.115·k cm (row `r` does not matter).

This is **static in firmware** — nothing supplies it over serial; it is computed
from the cell indices on every build. There are now separate coefficient tables
for X and Y, with one slot each for vertical and horizontal. Re-fit only the
mode and axis that were measured.

The shipped skew values are `vertical Y += 0.115 * col` and `horizontal Y +=
0.130 * col`; all X, row, and cross terms are zero.

`BUILD_PLACEMENT_OFFSET_*` is the separate fixed-error correction. It is per
axis and per mode, defaults to zero, and is added once to a `B` target before
the dynamic skew. Use it only for a measured constant release-position error;
The current measured fixed residual is horizontal X: placements land 0.4 cm
too far from the X home switch, so `BUILD_PLACEMENT_OFFSET_X_CM[horizontal]`
is `-0.4`. The negative command moves the holder toward home and cancels that
away-from-home error. The other three slots remain zero until measured.

## Scope — where this lives, and where it must never leak

It is applied in **`gotoBuildTarget()` alone** — the `B` (BUILD) motion is the
only path that gets it.

It is **not** in:

- `cellCentreCmOf()` / `cellTargetPosition()` / `gridPitch…` — the grid **model**
  stays a perfect rectangular lattice.
- `gotoCellForRotation()` (the `G` command), the grid map, `positionToIndex()`.
- the Python link ([`python/rig/link.py`](../python/rig/link.py) still sends
  `B {col} {row} {level}`, three tokens, unchanged).
- the camera grid, the Studio grid, or the 3D grid.

Every **representation** of the grid stays perfectly rectangular and level. This
correction bends only the physical **motion**, so the real bricks come out
straight.

## Confirming the board was flashed with this firmware

The correction is printed in `printGridConfig()`, so it shows up in the serial
console under both:

- **`5`** — full report
- **`9`** — grid config + map

Look for the four per-mode lines (two coefficient lines and two examples):

```
Dynamic skew [vertical]: X += 0.000*col + 0.000*row + 0.000*col*row cm   (BUILD only, + = away from home)
Dynamic skew [vertical]: Y += 0.115*col + 0.000*row + 0.000*col*row cm   (BUILD only, + = away from home)
             e.g. col 6 row 0 -> Y += 0.690 cm (<steps> steps)
Build placement offset [vertical]: Y += 0.000 cm   (BUILD only, + = away from home)
Dynamic skew [horizontal]: Y += 0.130*col + 0.000*row + 0.000*col*row cm   (BUILD only, + = away from home)
             e.g. col 2 row 0 -> Y += 0.260 cm (<steps> steps)
Build placement offset [horizontal]: X += -0.400 cm   (BUILD only, + = away from home)
```

If those lines are **absent**, the board is still running old firmware — re-flash.

During an actual build, `gotoBuildTarget()` also logs the correction per cell as
it is applied:

```
  Build correction: Y 1234 -> 1257 steps (0.115 cm)
```

(No correction line is printed when both the fixed offset and dynamic skew are zero.)

## Verification status

Syntax-checked with the stub-Arduino g++ harness (no Arduino toolchain on the dev
machine); compiles clean, identical to the unchanged control. **Untested on
hardware.** To confirm: flash the Mega and measure vertical and horizontal
placements independently. Update only the corresponding `SKEW_<AXIS>_*` table
slot when a residual is measured.

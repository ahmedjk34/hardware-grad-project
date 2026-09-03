# X-rail skew compensation (Y axis, build motion only)

## Symptom

When a block is placed with pure Y motion (same column, e.g. `B 0 3 0`) it lands
exactly where the grid says. When the placement involves X motion, the block is
off along **Y** — and the error grows with how far along X the rig travels. It is
**not** a constant offset.

Measured on the rig:

| Column index | Y error introduced |
| ------------ | ------------------ |
| 0            | 0.00 cm (no X travel) |
| 1            | 0.10 cm |
| 2            | 0.20 cm |
| 3            | 0.30 cm |
| k            | 0.10 × k cm |

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
float SKEW_Y_PER_COL_CM    = 0.1f;  // measured: ~0.1 cm Y pull per column of X travel
float SKEW_Y_PER_ROW_CM    = 0.0f;  // no row dependence measured (pure-Y is clean)
float SKEW_Y_PER_COLROW_CM = 0.0f;  // cross term, if the pull ever grows with row

long buildYSkewSteps(long col, long row)
{
  float cm = SKEW_Y_PER_COL_CM    * (float)col
           + SKEW_Y_PER_ROW_CM    * (float)row
           + SKEW_Y_PER_COLROW_CM * (float)col * (float)row;
  return lround(cm * xyStepsPerCmOf(AXIS_Y));
}
```

`buildYSkewSteps(col, row)` is **added** to the Y build target inside
`gotoBuildTarget()`, after `cellTargetPosition()` and before the move. The result
is clamped to the Y travel so a bad coefficient can never drive the carriage past
a soft limit (`moveAxisTo()` still enforces the limit as well).

**Sign** — "forward" = **+Y** = further from the Y home switch (the row 0 side).
The nudge is positive, so selecting cell `[1,0]` drives the rig ~0.10 cm forward,
`[2,0]` ~0.20 cm, `[k,r]` ~0.10·k cm (row `r` does not matter).

This is **static in firmware** — nothing supplies it over serial; it is computed
from the cell indices on every build. The three `SKEW_Y_*` coefficients are the
only knob. Re-fit them if the rig is re-measured.

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
straight. **X is never touched.**

## Confirming the board was flashed with this firmware

The correction is printed in `printGridConfig()`, so it shows up in the serial
console under both:

- **`5`** — full report
- **`9`** — grid config + map

Look for these two lines:

```
X-rail skew: Y += 0.100*col + 0.000*row + 0.000*col*row  cm   (BUILD only, +Y = away from home)
             e.g. col 6 row 0 -> Y += 0.600 cm (<steps> steps)
```

If those lines are **absent**, the board is still running old firmware — re-flash.

During an actual build, `gotoBuildTarget()` also logs the correction per cell as
it is applied:

```
  X-rail skew: Y 1234 -> 1264 steps (0.100 cm, col skew)
```

(no line is printed for column 0, where the nudge is exactly 0).

## Verification status

Syntax-checked with the stub-Arduino g++ harness (no Arduino toolchain on the dev
machine); compiles clean, identical to the unchanged control. **Untested on
hardware.** To confirm: flash the Mega and check that `B 3 0 0` lands level with
`B 0 3 0`. If a residual remains, `SKEW_Y_PER_COL_CM` is the one number to
re-tune.

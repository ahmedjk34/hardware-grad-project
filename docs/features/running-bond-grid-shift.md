# Running-bond grid shift — brick-laid courses on both machines

**Status: being implemented.** The pure-geometry half already existed (`Shift`,
`latticeOf(mode, shift)`, `clippedCells`, the firmware's `shiftX` / `shiftY`);
this feature adds the *per-level* half, the Studio control, the Twin plumbing,
the compiler's shift latches and the `POST /api/shift` route — and folds in the
older [grid-shift-in-the-twin](grid-shift-in-the-twin.md) design, which is the
"publish the live shift" subset of it.

In one sentence: **a level can carry a half-pitch offset on the run axis so a
block bridges the joint of the two beneath it, centred, equal overlap each
side — and the Studio, the Twin, the compiled program and the rig all agree on
where that block goes.**

---

## 1. The geometry, settled

**The bond course applies to the HORIZONTAL grid only.** The vertical grid is
never shifted by this feature — one gate, `BOND_MODE` in `resolveShift`, and the
compiler, validator, Twin and Studio all follow it. The Studio panel is inert in
vertical mode and says so.

A block is `2.2 × 6.0 × 1.5 cm`. The horizontal grid lays its `6.0 cm` face
along **X** — the direction blocks run end to end and where a straddling course
bridges a joint:

| grid | run axis | block on run axis | gap | **pitch** | half pitch = **the increment** |
| --- | --- | --- | --- | --- | --- |
| horizontal | **X** | 6.0 | 1.6 | 7.6 cm | **3.8 cm** ≈ 758 steps (X, 199.56 st/cm) |

For a level-1 block to sit centred on the joint between two level-0 blocks, its
centre must land on the **midpoint of the two lower centres**. Adjacent cells
are one pitch apart, so that midpoint is at **pitch ÷ 2**. Half-pitch is the
unique offset that makes every "equal each side" measure true at once:

- overlap with each lower block: `2.2 cm` (symmetric)
- unsupported span over the joint gap: `1.6 cm` → supported length `4.4 / 6.0 =
  73 %`, over the `SUPPORT_RATIO` of `0.55`
- inset from the outer edges of the two-block group: `3.8 cm` each side

The incrementer steps by `±3.8 cm`, clamped to one step (`{−3.8, 0, +3.8}`). A
full pitch is a whole-cell re-index and is not offered.

### What clips

The horizontal grid's X centres run `1.90 → 17.10` with the cap at `22.8` and a
`3.0 cm` X overhang budget, so a **single `+3.8 cm` course keeps all 3 columns**
— the shipped geometry has the slack. `clippedByShift` / `CLIPPED_BY_SHIFT` stay
wired as the safety net for any larger offset: a block a course pushes past the
cap is marked (an `error` in `validate.ts`), never deleted, and RUN is blocked
until it moves.

### `[0,0]` never moves

Already true on both machines and kept that way:

- firmware — *"the pick-up never rides it… a plain home to raw `[0,0]`"*
  (`build_test_v1.ino`, `applyGridShift` header).
- web — `coords.ts` `feederCentre()` / `isFeeder()`: *"no shift, no tool
  offset"*, and `latticeCells` keeps `kind:"feeder"` in every shift state.

The per-level bond offset is skipped for `level ≤ 0` and never applies to the
feeder cell.

---

## 2. The model — one new field

A model gains **`bondShifts`**: an author field beside `blocks` / `order` (not
in the `rig` snapshot — it is intent, not recorded geometry). Per mode, a map
from **level index** to an `[x_cm, y_cm]` offset added **on top of** the rig's
live shift. Absent level, `level ≤ 0`, or a `vertical` entry ⇒ `[0, 0]` — only
the `horizontal` submap is ever consulted.

**No schema bump.** `bondShifts` is additive and optional: a `rigmodel/1` file
with no `bondShifts` correctly means "no bond", exactly as an older file with no
`colour` means white — the established repair-don't-refuse pattern in
`rigmodel.ts`. `parseBondShifts` drops any malformed entry rather than failing
the whole document.

```jsonc
"bondShifts": {
  "horizontal": { "1": [3.8, 0], "3": [3.8, 0], "5": [3.8, 0] }
}
```

- The **Running bond** button fills the alternating pattern (`1, 3, 5, …` up to
  the model's highest level) on the current mode's run axis.
- The `−▏0▕+` stepper writes / clears one level's entry, quantised to `±3.8 cm`
  on the run axis only.
- Storing a map, not a parity rule, keeps the door open for corbels / leans
  without another schema change; the preset is the common path.

### Resolution — the single new function

`resolveShift(block, ctx)` in `coords.ts`:

```
base  = ctx.shifts?.[block.mode]                    // the live rig / operator shift
bond  = ctx.bondShifts?.[block.mode]?.[block.level]  // this level's offset, or [0,0]
return base + bond                                   // componentwise; undefined if both zero
```

Every current `ctx.shifts?.[block.mode]` / `shiftFor(block, ctx)` site in
`geometry.ts`, `validate.ts`, `compile.ts` and `lattice.ts` routes through it.
Returning `undefined` when the sum is zero keeps unbonded models byte-identical
in the fixtures.

---

## 3. The compiler — shift latches beside the mode latches

`compile.ts` gains a `ShiftOp`:

```ts
{ op: "shift"; mode: ModeName; axis: "x" | "y"; cm: number; text: "shiftY 3.8" }
```

`emitOps` tracks the applied `[x, y]` per mode (the firmware's shift is
per-mode). Before each build it computes `resolveShift` for that block; if the
run-axis component differs from what is applied, it emits one `ShiftOp`
(`shiftX` / `shiftY` with the composed absolute value — base + bond). A mode
latch re-asserts the target mode's shift, because `R` / `RR` resets the board
to that mode's compiled `0`.

`applyGridShift()` in the firmware **moves nothing, never re-homes, does not
need `S` re-sent** — it re-clips `gridColsNow()` / `gridRowsNow()` internally —
so a mid-program `shiftY 3.8` … `shiftY 0` between courses is cheap and safe. It
does require a calibrated claw angle (`B` has run once); the runner's first
`shift` therefore never precedes the first `B`.

`summarise` counts `shift` ops in a new `shifts` stat; the estimate adds
`settings.shiftSeconds` (a small constant — the command is a latch that moves
nothing).

---

## 4. The Twin — follow the live shift, ghost the plan

Two shift sources, and they are not the same question:

- **What the rig is on now** — `state.shift_cm`, published by the server
  (§5). The Twin's **base-course lattice** and any **off-model** rig block are
  drawn from this (`liveShiftOf(state)` → `<Lattice shift>`).
- **Where the plan goes** — the model's `bondShifts`. Every **model block** —
  ghost, target, placed, building — is positioned by
  `resolveShift(block, undefined, bondShifts)` (`TwinBlock.shift`, applied by
  `BlockBatch`'s new `shiftOf`), so a bonded structure is drawn brick-laid even
  mid-build while `state.shift_cm` is oscillating `0 → 3.8 → 0` between courses.
  When the model has **no** `bondShifts`, model blocks follow `state.shift_cm`
  instead (a plain operator re-registration).

`GEOMETRY_DRIFT` already fires when the model's stored shift ≠ the live shift,
which catches a bonded model run against a rig carrying a stuck manual shift.
`bondShifts` is deliberately **not** in the drift snapshot: it is a plan, not a
geometry the rig has to match.

Traps carried over from [grid-shift-in-the-twin.md](grid-shift-in-the-twin.md)
§4: the shift is per mode; `twinSignature` includes `state.shift_cm` and the
bond-map hash; a shift moves the lattice, never the cell indices; no sign flip
in the scene layer; clipped cells are struck through, not deleted; a shift
change invalidates the saved workspace
map.

---

## 5. The server — publish it, and let the browser set it

**Publish** (`web/state.py`): `shift_cm: tuple[float, float]` (the active mode's
live pair) and `reachable: tuple[int, int]` (cols, rows after firmware
clipping), both read off `rig.grid`, which `build_state()` already holds.

**Write** (`web/routes_command.py`): `POST /api/shift {mode, x_cm, y_cm}` →
`Rig.set_shift(x_cm=…, y_cm=…)`. Refused while a build runs (same guard as every
other mutation). Preserves the connect-time order — the mode must be latched,
then the shift, then `S` re-sent, because `S` validates against the shifted
lattice. Invalidates the saved workspace map and says so in the response.

`config/rig.json → shift_*_cm` and the AGENTS.md meaning of `GRID_SHIFT_*`
("operator re-registration, this run only") are **not** changed: the shipped
config stays `0.0`, and bond is a model concept that *compiles down to*
`shiftX` / `shiftY`. The operator's manual shift and the compiled bond latches
share the firmware transport; the runner composes `base + bond` so a manual
re-registration is preserved through a bonded build, and restores `base` at the
end.

---

## 6. Where it lives — as built

```
docs/features/running-bond-grid-shift.md   this file
config — unchanged (shipped shift stays 0.0)
arduino/build_test_v1/build_test_v1.ino    unchanged; shiftX/shiftY already do the work
python/rig/mock_board.py                   + _handle_shift so the mock echoes GRID SHIFT
python/rig/link.py                         set_shift rebuilds rig.grid on an explicit shift
python/web/state.py                        + shift_cm, + reachable, + requested
python/web/routes_command.py               + POST /api/shift (guards, mode check, map re-validate)
python/tests/web_state_test.py             asserts shift_cm / reachable / requested
python/tests/test_shift_route.py           new — apply+clip, wrong-mode 409, unseat 409
web/src/types.ts + test-state.ts           StateModel gains shift_cm / reachable / requested
web/src/studio/coords.ts                   + resolveShift, runAxisOf, bondIncrementCm, BondShifts
web/src/studio/validate.ts                 ValidationContext.bondShifts; shiftFor via resolveShift
web/src/studio/compile.ts                  + ShiftOp, cmWord, emitOps latch state, summarise.shifts
web/src/studio/settings.ts                 + shiftLatchSeconds
web/src/studio/model.ts                    Model.bondShifts, setBond edit, carried through edits
web/src/studio/rigmodel.ts                 StudioModel.bondShifts, parseBondShifts (no schema bump)
web/src/studio/runner.ts / runner-driver.ts + shift Effect/RunEvent, issueShift, api.shift
web/src/api.ts                             + shift(mode, x_cm, y_cm)
web/src/studio/twin.ts                     liveShiftOf; per-block TwinBlock.shift; signature
web/src/studio/scene/{Blocks,BlockShadows,Twin}.tsx  BlockBatch.shiftOf; <Lattice shift>
web/src/components/TwinPanel.tsx            bond-map hash into twinSignature
web/src/routes/Studio.tsx                  bondShifts into validate/compile; previewShift; <GridShift>
web/src/studio/panels/GridShift.tsx        new — the control window
web/src/style.css                          .studio-gridshift*, .studio-program-shift
web/src/studio/bond.test.ts                new — resolver, compiler latches, edit, roundtrip, clip
web/src/studio/panels/GridShift.test.tsx   new — the panel
web/src/studio/runner.test.ts              + running-bond shift latch cases
```

Not done, and why:

- **`dump_twin_states.py` regen** — the checked-in `twin.fixtures.json` is
  already stale against the current server (missing `feeder_*`, `hardware_ready`
  fields), so a regen is a 20k-line diff of unrelated drift. `twin.test.ts`
  passes with the old fixture because `liveShiftOf` treats a missing `shift_cm`
  as no shift. Regenerate it in a dedicated fixture-refresh change.
- **`dump_grid_fixtures.py` per-level cases** — the existing shifted-lattice
  fixtures already exercise the mechanism (bond composes to a plain `Shift`);
  `bond.test.ts` covers the per-level composition against the live `latticeOf`.
- **`S` re-send after a runtime shift** — not needed. `applyGridShift` re-clips
  `gridColsNow()` / `gridRowsNow()` in place; `set_shift` rebuilds `rig.grid`
  the same way. Verified in `test_shift_route.py`.

## 7. Difficulty — as it landed

| Piece | Difficulty | Notes |
| --- | --- | --- |
| `resolveShift` + threading it | 2 / 5 | every consumer already took `Shift` |
| Publish the shift + Twin plumbing | 2 / 5 | `BlockBatch.shiftOf` was the one new seam |
| `bondShifts` on the model, no schema bump | 2 / 5 | additive optional field, `parseBondShifts` repairs |
| `ShiftOp` + `emitOps` latch state machine | 3 / 5 | per-mode re-assert after `R`/`RR` was the trap |
| The Studio panel | 2 / 5 | lattice already redraws from `latticeOf(mode, shift)` |
| `POST /api/shift` + runner latches + mock | 3 / 5 | no `S` re-send needed; MockBoard `_handle_shift` added |

**Overall: 3–4 / 5.** The firmware is untouched; the weight is in the model
schema bump, the compiler state machine and the write-path safety.

## 8. Not doing

- A native firmware "bond" term. The compiler emits `shiftX` / `shiftY`; the
  firmware already clips and already exempts `[0,0]`.
- Arbitrary per-level shifts in the UI. The map can hold them; the panel only
  writes `±3.8` on the run axis and the preset.
- Animating the lattice as a course shifts. The rig does not slide when a shift
  is applied.
- Letting the Twin latch a shift. Read-only, same rule as the mode indicator.

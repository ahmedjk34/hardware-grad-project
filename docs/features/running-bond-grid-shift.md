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

A block is `2.2 × 6.0 × 1.5 cm`. The **run axis** of a mode is the one its
`6.0 cm` face lies along — the direction blocks are laid end to end and where a
straddling course bridges a joint:

| mode | run axis | block on run axis | gap | **pitch** | half pitch = **the increment** |
| --- | --- | --- | --- | --- | --- |
| vertical | **Y** | 6.0 | 1.6 | 7.6 cm | **3.8 cm** = 760 steps (Y, 200.0 st/cm) |
| horizontal | **X** | 6.0 | 1.6 | 7.6 cm | **3.8 cm** ≈ 758 steps (X, 199.56 st/cm) |

For a level-1 block to sit centred on the joint between two level-0 blocks, its
centre must land on the **midpoint of the two lower centres**. Adjacent cells
are one pitch apart, so that midpoint is at **pitch ÷ 2**. Half-pitch is the
unique offset that makes every "equal each side" measure true at once:

- overlap with each lower block: `2.2 cm` (symmetric)
- unsupported span over the joint gap: `1.6 cm` → supported length `4.4 / 6.0 =
  73 %`, over the `SUPPORT_RATIO` of `0.55`
- inset from the outer edges of the two-block group: `3.8 cm` each side

The increment set on the run axis is `{−3.8, 0, +3.8}`, single step. A full
pitch is just a whole-cell re-index and is not offered.

### What clips

The shifted lattice pushes `+3.8 cm` toward the far end:

- **vertical / Y** sits exactly on its Y cap (`centres 0.00 → 38.00`), so a
  shifted course **loses its last row** — `7 × 6` becomes `7 × 5`. Row 0 moves
  to `y = 3.8`, clearer of the home-switch overhang.
- **horizontal / X** has `5.7 cm` of far-end slack (`centres 1.90 → 17.10`,
  cap `22.8`), so a shifted course **keeps all 3 columns**.

Blocks left sitting on a clipped cell are marked, not deleted (`CLIPPED_BY_SHIFT`
already exists as an `error` in `web/src/studio/validate.ts`); RUN is blocked
until they are moved or removed.

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

`rigmodel/2` adds `bond_shift_cm`: per mode, a map from **level index** to a
`[x_cm, y_cm]` offset added **on top of** the rig's live shift. Absent level ⇒
`[0, 0]`. `rigmodel/1` files migrate with an empty map (no behaviour change).

```jsonc
"bond_shift_cm": {
  "vertical":   { "1": [0, 3.8], "3": [0, 3.8], "5": [0, 3.8] },
  "horizontal": {}
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
  (§5). The Twin's placed blocks and its lattice are drawn from this. During a
  bonded RUN it oscillates `0 → 3.8 → 0` as courses go up and the Twin just
  follows; the Twin needs no per-level knowledge for built blocks.
- **Where the unbuilt plan goes** — the model's `bond_shift_cm`. The ghost
  blocks and the target pulse use `resolveShift` so the plan preview shows the
  brick pattern before it is built.

`GEOMETRY_DRIFT` already fires when the model's stored shift ≠ the live shift;
`bond_shift_cm` joins the snapshot so a model authored bonded and run against a
rig with a stuck manual shift is caught before RUN.

Traps carried over from [grid-shift-in-the-twin.md](grid-shift-in-the-twin.md)
§4: the shift is per mode; `twinSignature` must include it; a shift moves the
lattice, never the cell indices; no sign flip in the scene layer; clipped cells
are struck through, not deleted; a shift change invalidates the saved workspace
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

## 6. Where it lives

```
docs/features/running-bond-grid-shift.md   this file
config — unchanged (shipped shift stays 0.0)
arduino/build_test_v1/build_test_v1.ino    unchanged; shiftX/shiftY already do the work
python/web/state.py                        + shift_cm, + reachable
python/web/routes_command.py               + POST /api/shift
python/rig/link.py                         set_shift already takes x_cm / y_cm
python/tests/web_state_test.py             shift_cm is the active mode's, changes on latch
python/tests/test_shift_route.py           new — the route's guards and ordering
web/src/studio/coords.ts                   + resolveShift, + BondShifts type
web/src/studio/geometry.ts                 aabbOf via resolveShift
web/src/studio/lattice.ts                  per-level cells for the ghost
web/src/studio/validate.ts                 clippedByShift / drift via resolveShift + bond snapshot
web/src/studio/compile.ts                  + ShiftOp, emitOps latch state, summarise
web/src/studio/model.ts                    + bondShifts on Model, + setBond edit
web/src/studio/rigmodel.ts                 rigmodel/2, migration, (de)serialise
web/src/studio/runner*.ts                  send shift ops during RUN
web/src/studio/panels/GridShift.tsx        new — the control window
web/src/studio/scene/Twin.tsx / Lattice    thread shift + bondShifts
web/src/components/TwinPanel.tsx            prop reaches <Twin>, no-state fallback labelled
web/src/studio/*.test.ts(x)                 new cases per file
python/tools/dump_grid_fixtures.py         per-level shifted cases
python/tools/dump_twin_states.py            re-run for the new state field
```

## 7. Difficulty

| Piece | Difficulty | Why |
| --- | --- | --- |
| `resolveShift` + threading it | 2 / 5 | every consumer already takes `Shift` |
| Publish the shift, thread to the Twin | 2 / 5 | the [older doc](grid-shift-in-the-twin.md)'s work |
| `bond_shift_cm` in `rigmodel/2` + migration | 3 / 5 | the migration hook exists; a schema bump touches (de)serialise + fixtures |
| `ShiftOp` in the compiler + latch state machine | 3 / 5 | mirrors the mode-latch state machine, per-mode re-assert is the trap |
| The Studio panel | 2 / 5 | lattice already redraws from `latticeOf(mode, shift)` |
| `POST /api/shift` + runner emits latches + on-rig | 4 / 5 | map invalidation, `S` re-send, ordering, build-lock, base+bond composition |
| Fixture regeneration, both languages | 3 / 5 | recorded from a live mock server, not hand-written |

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

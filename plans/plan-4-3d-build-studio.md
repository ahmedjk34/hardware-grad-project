# Plan 4 — The 3D Build Studio and the live digital twin

**One-line goal.** A real 3D modelling environment in the browser where you
design a block structure by clicking in space, save it to a library, and press
go — while the same 3D engine, running read-only beside the camera on the index
page, shows the structure filling in block by block as the rig actually builds
it.

This plan is written for someone who has not read the rest of the repository.
Read *§0 The development rule*, *§1 The idea*, *§2 The one thing that makes this
tractable* and *§3 The seven facts* first; everything after them assumes those.

**This plan is test-driven. §0 is not advisory.**

Milestone-by-milestone prompts for handing this to an agent:
[plan-4-milestone-prompts.md](plan-4-milestone-prompts.md).
**What the Studio actually is today, kept current:
[docs/STUDIO.md](../docs/STUDIO.md).** This plan states the intent and is not
rewritten as the work lands; that document is the living record, and where the
two disagree it is the one describing the code.
Visual language: [docs/DESIGN.md](../docs/DESIGN.md).
The console this attaches to: [plan-3-web-operator-console.md](plan-3-web-operator-console.md).
The wider feature catalogue: [docs/feature-ideas.md](../docs/feature-ideas.md).

---

## 0. The development rule: tests first

**Every milestone in this plan is developed test-first.** This is the same rule
Plan 3 was built under ([plan-3-web-operator-console.md](plan-3-web-operator-console.md)
§6) and it carries over unchanged.

For **every** deliverable: write the test file, run it, watch it fail *for the
right reason*, then write the implementation until it passes, then clean up. The
test and its implementation are committed together, **test first in the diff**.

"Tests first" is not "tests eventually". If you find yourself writing
implementation with no failing test pointing at it, stop and write the test.

### 0.1 Why this plan in particular

The Studio is a 3D application, and 3D applications tempt people into judging
correctness by eye. That temptation is exactly what this plan is arranged to
resist. Plan 4 is deliberately layered so that **the parts that must be correct
are the parts that need no browser and no GPU**:

- `coords.ts`, `geometry.ts`, `validate.ts`, `model.ts`, `compile.ts` and
  `library.ts` are pure TypeScript with no React and no three.js in them. All of
  them are fully testable in Vitest, headless, in milliseconds.
- Only `scene/` and `panels/` touch the renderer, and they hold no rules — they
  read from the pure layer and draw.

If a rule about the machine ends up inside a component, it has escaped the test
suite. Move it down into the pure layer and test it there.

### 0.2 What "the right reason" means here

A test that fails because a module does not exist yet has failed for the right
reason. A test that fails because of a typo in the test has not. Read the
failure before writing the fix — on a coordinate-heavy project, a test that
passes for the wrong reason is worse than no test, because it will be believed.

### 0.3 The three kinds of test in this plan

1. **Fixture tests against Python.** The coordinate maths must agree with
   `python/rig/grid.py` to 1e-6. Fixtures are dumped from Python and committed;
   the TypeScript is written to match them. `web/src/lib/workspace.test.tsx`
   already establishes this pattern for the homography port — follow it.
   **When the two disagree, Python is right.**
2. **Pure unit tests.** Every validation rule (§6.4) gets at least one passing
   and one failing case. Every compiler ordering constraint (§6.2) gets a test
   that fails when that constraint is removed — a constraint with no such test
   is not actually being enforced, it is just being hoped for.
3. **State-mapping tests.** The twin (§9) and the runner (§10) are driven by
   fixture server-state payloads, not by a live rig. Rendering needs no GPU
   test; the mapping from state to behaviour does, and that is where the bugs
   that matter will be.

### 0.4 What is not worth testing

Do not write tests that assert on pixel output, camera angles, material colours
or animation timings. They are slow, brittle, and they test three.js rather than
this project. Judge the look by eye; judge the *rules* by test.

### 0.5 The existing suite is a gate, not a suggestion

`cd web && npm test` must be green at the end of every milestone, including the
console's own `step7`, `step9`, `step10` and `lib/workspace.test.tsx`. Nothing
in Plan 4 is permitted to regress Plan 3. If a legitimate markup change breaks a
test's DOM query, update the query — **never the guard it is checking**.

---

## 1. The idea

Open the Studio. You get a dark, infinite space. The rig's real motion envelope
is drawn as a faint wireframe cage on the floor, and inside it the machine's
actual block lattice glows — 7 × 6 cells in vertical mode, each cell exactly one
block's footprint, with the real 1.6 cm gaps between them.

Orbit with the mouse. Hover a cell and a translucent ghost block snaps into it.
Click and a **real 3D block** — 2.2 × 6.0 × 1.5 cm, correctly proportioned,
lit, casting a shadow — drops into place with a short settle animation. Hover
the top of that block and the ghost rises to level 1. Click again and you have a
stack.

Press `M`. The lattice **morphs live**: the 7 × 6 vertical grid dissolves and
the 3 × 10 horizontal grid grows in its place, the ghost block rotates 90°, and
every block you have already placed stays exactly where it is in real
centimetres — because it is in real centimetres. You are now placing blocks
lying the other way, in the same physical space, on top of the ones already
there. Blocks that would collide light up red before you commit.

Grab the grid-shift handle and drag. The whole lattice slides in real
millimetres, the readout says `shiftX +1.20 cm`, and the far column turns amber
and drops out as it leaves the machine's travel envelope — which is exactly what
the firmware would do.

Save it. It lands in your library as a card with a rendered thumbnail. Load it
on the index page and the console builds it, one `B` at a time, with the twin
beside the camera filling in as the real blocks land.

---

## 2. The one thing that makes this tractable

**A structure is nothing but an ordered list of two commands.** Everything the
rig can build is expressible as:

```text
R                 # latch the vertical grid
B 1 0 0           # column 1, row 0, ground level
B 1 1 0
B 1 0 1           # on top of the first one
RR                # latch the horizontal grid
B 0 3 1
```

There is no path planning, no inverse kinematics, no trajectory, no collision
solver on the machine side. The firmware owns all of that. The browser's entire
job is to be a **good editor and a good renderer for a list of integers**.

That is why this is a UI project wearing a robotics project's clothes, and why
it is achievable inside a graduation timeline.

### 2.1 The one correction to the obvious mental model

It is tempting to think of the command as `B <col> <row> <level> <orientation>`.
It is not. From [AGENTS.md](../AGENTS.md) §6:

> **`B` no longer takes a rotation word.** `B <col> <row> <level>`, three
> numbers, nothing after them. How the block is laid comes from the active
> grid. A fourth word is a parse error that names the latch.

Orientation is a **mode latch** (`R` = vertical, `RR` = horizontal) that changes
the entire coordinate system, and it has teeth:

- it is **refused unless X and Y are homed**, so a latch means physical motion;
- it is **refused if the board is already in that mode** — a latch that confirms
  a state nobody asked for cannot tell a confirmation from a mistake;
- a board reset silently returns to `vertical`, which is why `@0 READY` reports
  `mode=`.

So a mixed-orientation model is not a flat list. It is a list that must be
**sorted into mode runs**, where each run costs a homing move. Producing a
valid, cheap ordering from a pile of blocks is a real compilation problem — and
a genuinely good thing to have in a dissertation.

---

## 3. The seven facts the engine must respect

Get these wrong and the Studio will produce beautiful models that the machine
cannot build.

1. **Cell indices are 0-based and `[0,0]` is the feeder.** In *both* modes.
   `[0,0]` is where blocks are picked up from and is never built on. Cell 0's
   centre sits exactly on the home corner. Source: `python/rig/grid.py`,
   `BuildController.select()`.

2. **The lattice formula is six lines and it is centre-anchored.**
   ```text
   pitch       = block + gap
   centre(i)   = trim + error_offset + shift + i * pitch
   ```
   There is no leading gap, no trailing gap and no centring. Cell 0's block
   hangs half a block back past the switches. Do not invent a different layout;
   port this formula exactly.

3. **The two modes are different grids, not a rotated one.** Each declares both
   block extents outright — nothing in this project swaps a width for a length.

   | mode | block X | block Y | gap X | gap Y | pitch X | pitch Y | cols | rows | X centres | Y centres |
   | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
   | vertical | 2.2 | 6.0 | 1.6 | 1.6 | 3.8 | 7.6 | 7 | 6 | 0 → 22.8 | 0 → 38.0 |
   | horizontal | 6.0 | 2.2 | 1.6 | 1.6 | 7.6 | 3.8 | 3 | 10 | 1.9 → 17.1 | 1.9 → 36.1 |

   Horizontal ships with `trim_x = trim_y = +1.9 cm` — the pickup-cell
   registration (the rotated 6.0 cm face overhangs the 2.2 cm vertical
   footprint by 1.9 cm per side), a mode-specific registration shift, not a
   tool offset. **Read all of these from `config/rig.json` at runtime — never
   hard-code the table above.**

4. **A level is 1.5 cm, measured from ground.** `level 0` = the block sits on
   the surface, `level 1` = 1.5 cm, `level 2` = 3.0 cm. The firmware derives
   this from `Z_TRAVEL_STEPS` / `Z_TRAVEL_CM` (currently 1350 steps / 26.5 cm),
   so the theoretical level ceiling is ~17. The *practical* ceiling is far
   lower and is an operator setting, not a physical constant.

5. **Grid shift is a live, firmware-backed operator knob.** `shift_x_cm` /
   `shift_y_cm` per mode in `config/rig.json`; `rig/link.py` pushes them as
   `shiftX` / `shiftY` after the mode latch and before `S` on every connection,
   because a port-open reset clears them. They translate the whole placement
   lattice — the `[0,0]` reference included — but **never the pick-up**, which
   is a plain home to raw `[0,0]`. A non-zero shift can push the far block past
   the travel cap, and the firmware then reports a *clipped* reachable grid
   while keeping the requested one. The Studio must reproduce that clipping
   visually, and it must never let a shift masquerade as calibration
   (`error_offset_*` is the separate calibration knob).

6. **Cells never touch within a mode, so a block cannot bridge two cells of its
   own grid.** The 1.6 cm gap guarantees it. But the two modes interleave in
   real space: a horizontal block is 6.0 cm along X while the vertical pitch is
   3.8 cm, so **a horizontal block can physically bridge two vertical stacks**.
   That is the most interesting structural possibility in the whole machine and
   the Studio should make it discoverable.

7. **Every safety rule lives on the server and stays there.** The Studio is a
   design tool. Nothing it produces bypasses `BuildController`, `BuildJob` or
   the guarded routes in `python/web/routes_command.py`. A compiled program is
   executed one `B` at a time through the existing `/api/build`, with the
   existing two-step confirmation, and the existing lock-on-abort behaviour.

---

## 4. Three coordinate spaces, and the conversions between them

Almost every bug in a project like this is a coordinate-space bug. Name the
spaces, convert only at the boundaries, and write the conversions once.

| Space | Units | Origin | Used by |
| --- | --- | --- | --- |
| **Cell space** | integers `(mode, col, row, level)` | feeder at `[0,0]` | the model file, the compiler, the `B` command |
| **Machine space** | millimetres, `X` right, `Y` away from Y-home, `Z` up | home corner, ground | collision, support, envelope checks, the shift readout |
| **Scene space** | three.js units, 1 unit = 10 mm, `Y` up | scene centre | rendering only |

```ts
// cell → machine, per mode, read from config/rig.json
centreX_mm = (trim_x + error_offset_x + shift_x + col * pitch_x) * 10
centreY_mm = (trim_y + error_offset_y + shift_y + row * pitch_y) * 10
centreZ_mm = level * 15 + 7.5           // block centre, not its base

// machine → scene: one group, one transform, applied once
sceneGroup.rotation.x = -Math.PI / 2     // machine Z becomes screen up
sceneGroup.scale.setScalar(0.1)          // mm → scene units
```

**Rule:** no component may do its own axis juggling. A single `coords.ts`
module exports `cellToMachine`, `machineToScene`, `blockExtents(mode)` and
`latticeBounds(mode)`, `geometry.ts` exports `aabbOf(block)`, and everything
else calls them. This module is the direct counterpart of `python/rig/grid.py`
and is tested against fixtures dumped from it by
`python/tools/dump_grid_fixtures.py` — the pattern
`python/tools/dump_workspace_fixtures.py` set for the homography port in
`web/src/lib/workspace.ts`.

**Shipped in M0** (`web/src/studio/`):

| module | exports |
| --- | --- |
| `coords.ts` | `setRigConfig` / `rigConfig` / `activeMode`, `latticeOf`, `cellToMachine`, `blockExtents`, `levelBaseZ` / `levelCentreZ`, `latticeBounds`, `cellCount`, `isFeeder`, `feederCentre`, `machineToScene` / `sceneToMachine`, `axisFits`, `reachableCells` |
| `geometry.ts` | `aabbOf`, `intersects`, `footprintOverlapArea`, `footprintArea`, `topFaceZ`, `clippedCells`, `latticeFootprint` |

Geometry is read from `config/rig.json` itself at runtime — the browser imports
the same file the Pi does (`vite.config.ts` → `server.fs.allow`), so there is no
second copy of the table in §3 anywhere. Machine space is **millimetres**; the
config and the internal lattice are in centimetres and convert only in
`coords.ts`. Block height (1.5 cm) is the one number with no `rig.json` partner:
it lives in the firmware's `BLOCK_HEIGHT_CM` and is named once in `coords.ts`
as `BLOCK_HEIGHT_CM`, with an optional `block_z_cm` config override honoured if
one is ever added.

---

## 5. The model format

A model is a plain JSON document. Human-readable, diffable, importable,
emailable, and small enough to sit in `localStorage`.

```jsonc
{
  "schema": "rigmodel/1",
  "id": "0f4c…",                    // uuid, stable across renames
  "name": "Bridged arch",
  "description": "Two towers with a horizontal span",
  "created": "2026-09-01T14:02:11Z",
  "modified": "2026-09-01T14:40:05Z",

  // What geometry this model was authored against. If the live rig.json
  // disagrees, the Studio warns loudly rather than silently rebuilding.
  "rig": {
    "workspace_cm": [22.8, 38.0],
    "modes": {
      "vertical":   { "cols": 7, "rows": 6, "block_cm": [2.2, 6.0, 1.5], "pitch_cm": [3.8, 7.6] },
      "horizontal": { "cols": 3, "rows": 10, "block_cm": [6.0, 2.2, 1.5], "pitch_cm": [7.6, 3.8] }
    },
    "shift_cm": { "vertical": [0.0, 0.0], "horizontal": [0.0, 0.0] }
  },

  "blocks": [
    { "id": "b1", "mode": "vertical",   "col": 1, "row": 1, "level": 0, "colour": "red" },
    { "id": "b2", "mode": "vertical",   "col": 1, "row": 1, "level": 1, "colour": "red" },
    { "id": "b3", "mode": "vertical",   "col": 3, "row": 1, "level": 0, "colour": "blue" },
    { "id": "b4", "mode": "horizontal", "col": 0, "row": 2, "level": 2, "colour": "yellow" }
  ],

  // Author's preferred order. The compiler may reorder within the constraints
  // in §6 but never silently violates this where it is still valid.
  "order": ["b1", "b3", "b2", "b4"],

  "thumbnail": "data:image/webp;base64,…"   // rendered from the viewport on save
}
```

Design notes:

- **Geometry and order are separate.** Dragging a block in the timeline must not
  touch its coordinates, and moving a block must not reshuffle the build order.
- **Colour is authoring intent, not a promise.** The feeder is manual; colour
  drives the *"FEED: RED"* prompt, nothing more.
- **`rig` is a snapshot, not a dependency.** It exists so that opening a model
  authored before a geometry change produces a clear warning
  (`this model was designed for a 7 × 6 vertical grid; the rig is now 7 × 5`)
  instead of a wrong build.

---

## 6. The compiler — model to command program

This is the intellectual core of the plan and it deserves its own module,
`web/src/studio/compile.ts`, with heavy unit tests and no React in it.

### 6.1 Output

```jsonc
{
  "valid": true,
  "program": [
    { "op": "mode",  "mode": "vertical" },
    { "op": "build", "id": "b1", "col": 1, "row": 1, "level": 0, "text": "B 1 1 0" },
    { "op": "build", "id": "b3", "col": 3, "row": 1, "level": 0, "text": "B 3 1 0" },
    { "op": "build", "id": "b2", "col": 1, "row": 1, "level": 1, "text": "B 1 1 1" },
    { "op": "mode",  "mode": "horizontal", "cost": "homes X and Y" },
    { "op": "build", "id": "b4", "col": 0, "row": 2, "level": 2, "text": "B 0 2 2" }
  ],
  "stats": { "blocks": 4, "modeSwitches": 1, "estimateSeconds": 176 },
  "diagnostics": []
}
```

### 6.2 Ordering constraints, in priority order

1. **Support before supported.** A block at level `L` may not be placed before
   everything it rests on. This is a partial order, not a total one.
2. **Bottom-up.** Within the remaining freedom, sort by level ascending. This is
   both physically necessary and the cheapest for claw clearance.
3. **Minimise mode latches.** Each latch homes X and Y — seconds of motion and a
   refusal risk. Group same-mode blocks into runs *within* each level band.
4. **Respect the author's order** wherever it does not violate 1–3. If the
   author dragged block `b7` to the front and it is legal there, it goes there.
5. **Tie-break deterministically** (by `col`, then `row`, then `id`) so the same
   model always compiles to the same program. Non-determinism here would make
   the tests useless and the demo unrepeatable.

Implementation: a Kahn topological sort over the support graph with a priority
queue keyed on `(level, currentModeFirst, authorIndex, col, row, id)`.

### 6.3 The mode-latch state machine

- The board boots in `vertical`. The compiler's initial state is therefore
  `vertical`, **unless** the live `state.mode` says otherwise, in which case it
  starts from that.
- Emit a `mode` op only on an actual change — the firmware refuses a redundant
  latch.
- Every `mode` op is annotated `homes X and Y` so the runner can warn the
  operator that the rig is about to move without a `B`.

### 6.4 Validation passes

Every pass produces structured diagnostics: `{ severity, code, blockId,
message, fix? }`. `error` blocks compilation; `warning` does not.

| Code | Severity | Rule |
| --- | --- | --- |
| `FEEDER_CELL` | error | `[0,0]` is the pick-up cell in both modes and is never a target |
| `OUT_OF_GRID` | error | `col`/`row` outside `0..cols-1` / `0..rows-1` for that mode |
| `CLIPPED_BY_SHIFT` | error | the active shift pushes this cell past the travel cap — mirror the firmware's `gridColsNow()` clipping |
| `EDGE_OVERHANG` | error | the block's own edge exceeds `max_edge_overhang_*_cm` for its mode |
| `LEVEL_CEILING` | warning | above the operator's configured practical stacking limit |
| `DUPLICATE_CELL` | error | two blocks in the same `(mode, col, row, level)` |
| `COLLISION` | error | two blocks' machine-space AABBs intersect — the cross-mode case that cells alone cannot catch |
| `UNSUPPORTED` | error | a block at level > 0 with insufficient support beneath it (§6.5) |
| `CLAW_CLEARANCE` | warning | a taller neighbour intrudes into the descent prism above this target (§6.6) |
| `GEOMETRY_DRIFT` | warning | the model's `rig` snapshot disagrees with the live `config/rig.json` |
| `ISLAND` | warning | a connected component that touches nothing else — legal, but usually a mistake |

### 6.5 The support rule

Not "is there a block in the same cell one level down" — that would forbid the
cross-mode bridging that is the machine's most interesting trick.

```text
footprint  = the block's XY rectangle in machine space
beneath    = union of XY rectangles of all blocks whose top face is at this
             block's base Z, intersected with footprint
supported  = area(beneath) / area(footprint)

valid when supported >= SUPPORT_RATIO (default 0.55)
             AND the footprint centroid lies inside `beneath`
```

Both constants are Studio settings with a plain-language explanation in the UI,
because they encode a guess about friction and claw precision that only physical
testing can settle. Ship them conservative, show them, and record what the rig
actually tolerated in the run report.

### 6.6 The claw-clearance rule

The claw descends vertically into the target cell. Model the descent as a prism
over the target footprint, inflated by `CLAW_MARGIN_MM` (default 8 mm per side),
extending from the target's top face up to the travel height. Any already-placed
block intruding into that prism is a `CLAW_CLEARANCE` warning with a suggested
reorder ("place `b9` after `b4`").

This is a warning rather than an error because the margin is a guess until
somebody measures the claw. Make that explicit in the UI copy.

---

## 7. Architecture

```text
web/src/
  studio/
    coords.ts          # cell ⇄ machine ⇄ scene. The only place axes are handled
    model.ts           # rigmodel schema, validation, migration, (de)serialise
    compile.ts         # §6 — pure, no React, no three.js
    library.ts         # localStorage CRUD, import/export, thumbnails
    geometry.ts        # AABBs, support/clearance/collision predicates
    lattice.ts         # WHICH cells are drawn and what each one is
    view.ts            # envelope box, snap poses, framing, orbit constraint
    scene/
      theme.ts         # DESIGN.md tokens read off the document, as three colours
      Viewport.tsx     # <Canvas>, camera rig, lights, environment
      Lattice.tsx      # the active grid, its gaps, the feeder marker
      Envelope.tsx     # travel-cap cage + clipped-cell shading
      Blocks.tsx       # instanced meshes for placed blocks
      Ghost.tsx        # hover preview, valid/invalid materials
      ShiftHandle.tsx  # live grid-shift drag gizmo
      Twin.tsx         # read-only variant used on the index page
    panels/
      Palette.tsx      Timeline.tsx   Diagnostics.tsx
      LibraryDrawer.tsx  Inspector.tsx  ProgramView.tsx
  routes/
    Root.tsx           # hash routing: the console at #/, the Studio at #/studio
    Console.tsx        # the existing index page + the twin (still App.tsx today)
    Studio.tsx         # the full editor
```

**One correction to the sketch in §4.** That section shows the machine-to-scene
transform as a group on the scene (`rotation.x = -π/2`, `scale 0.1`). It is not
built that way: `coords.machineToScene()` performs that conversion in the pure
layer, where it is fixture-tested, and hands `scene/` coordinates that are
already in scene space. A group transform on top of it would apply the rotation
twice. The rule §4 states is the one that matters and it still holds —
**the axes are handled in exactly one place** — that place is just `coords.ts`
rather than a `<group>`.

**Library choice: `three` + `@react-three/fiber` + `@react-three/drei`.**
R3F is the mature React binding for three.js; `drei` supplies the orbit
controls, gizmos, instancing helpers and post-processing that would otherwise be
a fortnight of work. Pin exact versions, install locally, **bundle them** — the
Pi serves this over LAN with no guaranteed internet, so no CDN, ever
(see [DESIGN.md](../docs/DESIGN.md) §3.2). Code-split the Studio route so the
console's first paint does not pay for three.js.

**Everything in `studio/` above `scene/` is framework-free and unit-tested.**
The compiler and the coordinate maths must be verifiable without a browser or a
GPU — that is what makes the claims about them defensible.

---

## 8. The Studio interface

### 8.1 Layout

```text
┌──────────────────────────────────────────────────────────────────────┐
│  ◀ CONSOLE   Bridged arch •            VERTICAL 7×6   shift +0.0,+0.0│
├────────────┬──────────────────────────────────────┬──────────────────┤
│ LIBRARY    │                                      │ INSPECTOR        │
│ ┌────────┐ │                                      │  cell [1,1]      │
│ │ thumb  │ │        3D VIEWPORT                   │  level 1         │
│ │ Arch   │ │        orbit / pan / zoom            │  mode vertical   │
│ └────────┘ │        ghost block follows cursor    │  colour ● red    │
│ ┌────────┐ │                                      │  B 1 1 1         │
│ │ Tower  │ │                                      ├──────────────────┤
│ └────────┘ │                                      │ DIAGNOSTICS      │
│            │                                      │ ⚠ b7 unsupported │
│ + New      │  ┌ level scrubber ┐   [V|H] [shift]  │ ⚠ 1 mode switch  │
├────────────┴──────────────────────────────────────┴──────────────────┤
│ TIMELINE  ▸ b1 ▸ b3 ▸ b2 │ RR │ ▸ b4        4 blocks · 1 latch · ~2:56│
├──────────────────────────────────────────────────────────────────────┤
│                                     [ SEND TO CONSOLE ]  [ SAVE ]    │
└──────────────────────────────────────────────────────────────────────┘
```

Same tokens, same type scale, same reserved state colours as the console. The
Studio must feel like the same instrument, not a second application.

### 8.2 The viewport

- **Ground**: `--void`, with a subtle radial vignette so the model reads as
  lit from above. No infinite checkerboard — it is visual noise.
- **Envelope cage**: the 22.8 × 38.0 cm travel cap as a thin `--line-strong`
  wireframe box, with cm rulers along two edges. This is the machine's real
  limit and it should always be visible.
- **Lattice**: each addressable cell drawn as its true footprint rectangle with
  the true gaps. Cells are `--signal` at 30% opacity, the feeder `[0,0]` is
  hatched and labelled `FEED`, and cells clipped out by the current shift are
  `--motion` and crossed through.
- **Lighting**: one key directional light with soft shadows, one dim fill, a
  faint hemisphere for the ambient. Contact shadows under blocks
  (`drei/ContactShadows`) — this single effect is what makes the blocks look
  *placed* rather than floating.
- **Camera**: perspective, orbit-constrained to above the ground plane, with
  snap buttons for **top / front / side / iso** and a smooth tween between
  them. Top view aligns with the camera's own view of the rig, which matters
  for §10.

### 8.3 Placement interaction

The whole thing hinges on one gesture being perfect.

- **Hover** raycasts against the lattice plane *and* against the top faces of
  placed blocks. Whichever is hit determines the target cell and level, so
  hovering the top of a stack naturally means "on top of this".
- The **ghost block** is translucent `--signal` when the placement is legal,
  translucent `--danger` with a red outline when it is not, and its exact
  failure reason appears as a small label beside the cursor — *"[0,0] is the
  feeder"*, *"would collide with b4"*, *"unsupported: 30% contact"*.
- **Click** commits with a 140 ms drop-and-settle. **Alt-click** removes.
  **Shift-click** starts a drag to fill a run of cells.
- **Level scrubber** on the left of the viewport: hold a level and the ghost
  locks to it regardless of what is beneath, so you can plan overhangs before
  their supports exist. Blocks above the held level fade to 15% so you can see
  what you are doing — an *x-ray by level* that costs one uniform.
- **Undo/redo** is a plain command stack over the model, `Ctrl-Z` / `Ctrl-Shift-Z`,
  minimum depth 100. Non-negotiable for a modelling tool.

### 8.4 Live mode switching

Pressing `M` or hitting the `[V|H]` segmented control:

1. The current lattice fades and contracts over 250 ms while the new one grows
   in — the two grids genuinely overlap in space, so the transition should show
   that rather than cutting.
2. The ghost block rotates 90° in the same tween.
3. **Placed blocks do not move.** They are stored in cell space *with their own
   mode*, so they resolve to the same machine-space position regardless of what
   is currently latched.
4. The header readout swaps to the new grid's dimensions and shift.

In the Studio this is free — it is a view change. On the index page's twin it is
tied to the real `POST /api/mode`, which homes the rig. **The two must not be
confused**, so the twin's mode indicator is a read-only mirror of `state.mode`
and switching there goes through the console's confirm dialog.

### 8.5 Live grid shift

Drag the shift gizmo, or type into the `shiftX` / `shiftY` fields:

- The lattice translates in real time in true millimetres.
- The readout shows `shiftX +1.20 cm  shiftY −0.40 cm` in mono.
- Cells whose block edge exceeds `max_edge_overhang_*_cm` turn amber and are
  struck through, live, exactly reproducing the firmware's clipping — **watching
  the far column drop out as you drag is the single most convincing "this is
  modelling the real machine" moment in the whole app.**
- Snap increments: 0.1 cm by default, 0.5 cm with `Shift`, free with `Alt`.
- Shift is **per mode**, matching `config/rig.json`.
- Applying a shift to the *rig* (as opposed to previewing it) is a separate,
  explicit, confirmed action with copy explaining that it moves every placement
  including the `[0,0]` reference but never the pick-up, and that it is a
  registration shift, not calibration.

### 8.6 The timeline

A horizontal strip of block chips in compiled order, with mode-latch dividers
drawn as full-height amber bars labelled `R` / `RR`. Drag to reorder — illegal
drops are refused with a shake and the constraint that blocked them. Scrub the
playhead and the viewport shows the structure as of that step, with future
blocks as faint ghosts. This *is* the build preview, the review tool and the
replay control, all from one component.

### 8.7 The model library

- Cards with a rendered WebP thumbnail, name, block count, estimated build time,
  mode-latch count, and modified date.
- `localStorage` first — no server needed, works offline, survives a Pi restart
  on the operator's own device. Namespaced under `rig.studio.models.v1` with a
  size guard, because thumbnails add up.
- **Export / import** as `.rigmodel.json`, single or as a zip of the library.
  Drag a file onto the window to import.
- Duplicate, rename, delete with undo.
- **Optional server persistence** (`GET/PUT /api/models`) as a later milestone,
  so models follow the rig rather than the browser. Keep `localStorage` as the
  source of truth until then; do not build a sync engine for a class project.
- Ship **three built-in example models** — a tower, a two-column bridge using a
  cross-mode horizontal span, and a stepped pyramid. They demonstrate every
  feature, they make an empty library not look broken, and they are the demo
  you fall back on if something goes wrong on the day.

---

## 9. The live digital twin on the index page

The same engine, `Twin.tsx`, in read-only mode, beside the camera.

### 9.1 Layout

On desktop the camera and the twin sit side by side, equal width, sharing one
top-aligned row — **real workspace and virtual workspace, in step**. On a phone
they become a two-tab switcher above the action sheet, defaulting to the camera,
because the camera is what you must be watching.

### 9.2 Behaviour

| Event | Twin response |
| --- | --- |
| a model is loaded | remaining blocks appear as 20%-opacity wireframe ghosts |
| the next command is chosen | that ghost pulses in `--signal` and its cell is labelled `NEXT · B 1 1 0` |
| `build_state` → `RUNNING` | the target block turns `--motion` and animates descending from travel height, roughly in step with the real cycle |
| `last_result` → `placed` | it snaps solid, in its authored colour, with a brief contact flash |
| `last_result` → `rejected` | it returns to a ghost and flashes `--motion`; the reason is shown on the block |
| `build_state` → `LOCKED` | the whole twin desaturates and a red `SESSION LOCKED` plate covers it. No further animation — the machine's real state is unknown, and the twin must not pretend to know it |
| vision verification (§ feature 1.4) | verified blocks get a small green tick badge; missing ones get an amber outline |

That last row is the point of the whole exercise: **the twin is a claim about
reality, and the camera is what checks it.**

### 9.3 View sync

A `SYNC VIEW` toggle snaps the twin's camera to top-down and matches its framing
to the real camera's workspace rectangle, so the two panels show the same thing
from the same angle. Cheap to implement, and side-by-side identical framings are
what make a demo land.

### 9.4 The stretch goal: project the plan onto the video  ★

`WorkspaceMap.target_polygon(col, row, image_size)` already maps any cell to its
pixel polygon in the camera image — it is how `web/geometry.py` draws the grid
overlay today, and it is already ported to TypeScript and fixture-tested in
`web/src/lib/workspace.ts`.

Feed the planned model through it and draw the plan **on the live video**: the
next block's footprint glowing on the real surface, the rest of the design faint
behind it. Level can be faked convincingly by offsetting the polygon toward the
image centre proportional to height (a pinhole camera 50 cm up produces a
predictable parallax) — or done properly once the homography is extended with a
height term.

This is as close to augmented reality as this project needs to get, it runs on
hardware you already own, and the hard maths is already written and tested.

---

## 10. Running a model

The runner turns a compiled program into real builds without weakening a single
existing guard.

- **Every step is still `POST /api/build` with the exact displayed command**,
  which the server re-checks against `controller.command`. Nothing is queued —
  the Arduino is deaf during a build, and that fact does not change because a
  program exists.
- Each step is: `POST /api/select/axis` (or `/select`) → verify `state.command`
  matches the compiled `text` → `POST /api/build`. If they ever disagree,
  **stop**, and say why. A mismatch means the model and the rig disagree about
  the world.
- A `mode` op calls `POST /api/mode`, which homes X and Y. In **RUN** and
  **DRY RUN** it proceeds as part of the compiled program; **STEP** warns and
  requires confirmation because the rig moves without a `B`.
- Three run styles: **step** (confirm each block), **run** (continuous, with a
  prominent stop-after-this-block that is honest about not interrupting the
  block in flight), and **dry run** (no serial at all; the twin animates the
  whole program in ~20 seconds — the demo mode, and the rehearsal mode).
- **Feeder prompts.** The feeder is manual, so before each block the runner
  shows `FEED: RED · block 7 of 24`. With colour planning this becomes a
  genuine guided assembly.
- `REJECTED` pauses the run and keeps the position. `ABORTED` locks everything,
  per the existing rules, and the program state is preserved read-only so you
  can see exactly how far it got.
- On completion: a run report — commands sent, results, per-block durations,
  total time, camera thumbnails, and vision verification if enabled. Exportable
  as Markdown. That is your dissertation's evidence chapter, generated.

---

## 11. Wow factors, ranked by impact per hour

1. **Side-by-side twin and camera building in step.** (§9) The whole demo.
2. **Live grid shift clipping the reachable cells as you drag.** (§8.5) Proves
   the model is the real machine, in one gesture.
3. **Plan projected onto the live video.** (§9.4) Near-AR, on existing maths.
4. **Cross-mode bridging** — a horizontal block spanning two vertical towers,
   validated by real footprint-overlap support maths. (§6.5) Nobody expects the
   machine to be able to do this; the Studio makes it obvious that it can.
5. **Timeline scrub and replay**, with the compiled `R`/`RR` latches visible as
   dividers. (§8.6) Shows the audience the *program*, not just the picture.
6. **Dry run** — the whole structure assembling in twenty seconds. (§10) Also
   your insurance policy if the hardware misbehaves on presentation day.
7. **Time-lapse export** stitched from real `PLACED` frames, played beside the
   dry run. Real and virtual, same structure, same order.
8. **Instruction-sheet export** — a printable IKEA-style step-by-step of the
   model, rendered from the timeline. Cheap, and it reads as a finished product.
9. **Ambient audio** — a soft tick per placed block, a chord on completion.
   Sound is disproportionately convincing in a live demo. Mutable, remembered.
10. **A `?` shortcut overlay** listing every key. Small, but it is the
    difference between "a student project" and "a tool".

---

## 12. Milestones

Each milestone is independently demonstrable. Do not start the next until the
current one is committed and its tests pass. **Every one of them is written
test-first, per §0** — the "done when" column below describes a state the test
suite proves, not one you confirm by looking at the screen.

| # | Milestone | Done when |
| --- | --- | --- |
| **M0** ✅ | **Coordinates and fixtures.** `coords.ts` + `geometry.ts`, ported from `rig/grid.py`, with fixtures dumped from Python via `python/tools/dump_grid_fixtures.py` | **done** — 17 fixture cases / 980 cells, both modes, across trims, error offsets and shifts, matching to 1e-6 |
| **M1** | **Static viewport.** R3F canvas, envelope cage, lattice for both modes, feeder marker, orbit + view snaps | it looks like the machine, from any angle, with correct proportions |
| **M2** | **Placement.** Ghost, raycast to lattice and to block tops, click/alt-click, undo stack, level scrubber | you can build a tower and a bridge by hand and it feels good |
| **M3** | **Validation.** All of §6.4 as pure functions + the diagnostics panel with per-block markers | every rule has a unit test and a way to see it fire in the UI |
| **M4** | **The compiler.** `compile.ts`, topological order, mode runs, program view, deterministic output | a mixed-mode model produces a correct, minimal-latch, repeatable program |
| **M5** | **Library.** localStorage CRUD, thumbnails, import/export, three built-in examples | you can close the tab and come back to your models |
| **M6** | **The twin.** `Twin.tsx` on the index page, driven by live `/api/events` state | a `--mock` build session fills the twin in correctly, including the locked case |
| **M7** | **The runner.** Step / run / dry-run, feeder prompts, run report | a full model builds end to end against `--mock`, and every failure path behaves |
| **M8** | **Wow pass.** Live shift clipping, timeline scrub, sync view, audio, instruction sheet, video projection | the demo script in §13 runs start to finish without a stumble |

M0–M5 need **no hardware and no Pi**. M6–M7 run entirely against
`python -m web --mock`. **No milestone requires a real camera.** `MockCamera`
serves a genuine MJPEG stream of a synthetic workspace through the same
`/api/stream.mjpg` endpoint, so even M8's plan-projection overlay is developed
and tested entirely against the mock. A real camera is wanted once, at the very
end, only to confirm the projection lands on the physical bench where the maths
says it should.

---

## 13. The demo script this plan is designed to enable

Rehearse this. It is five minutes and it lands every claim.

1. Open the console. Camera live, grid overlay on, rig log ticking. *"This is
   the real machine, right now."*
2. Open the Studio. Orbit around the empty envelope. *"And this is the same
   machine, to scale."*
3. Build a two-tower bridge by hand. Press `M` mid-way — the lattice morphs,
   the block turns, the span drops across both towers. *"The two orientations
   are different grids in the same space, and the software knows it."*
4. Drag the grid shift. The far column drops out. *"That is the firmware's own
   travel limit, computed in the browser."*
5. Show the compiled program: `R`, three `B`s, `RR`, one `B`. *"Underneath, the
   whole thing is five lines of serial."*
6. Dry run — twenty seconds, the structure assembles in the twin.
7. Send to console. Real build, side by side with the twin, one block at a time.
8. Show the run report and the time-lapse.

---

## 14. Risks and how they are handled

| Risk | Handling |
| --- | --- |
| three.js is heavy on a phone over LAN | code-split the Studio route; the console's first paint never loads it. Instanced meshes for blocks. The twin uses a reduced scene: no shadows, no post-processing |
| Coordinate drift between TS and Python | M0's fixture test is the gate. It is the first milestone for a reason |
| The support and clearance constants are guesses | they are surfaced as visible settings with honest copy, and the run report records what the machine actually tolerated |
| A model outlives a geometry change in `rig.json` | the `rig` snapshot in the model file and the `GEOMETRY_DRIFT` warning |
| Scope | M0–M4 alone is already an impressive, self-contained deliverable that needs no hardware. Everything after it degrades gracefully |
| The demo depends on hardware behaving | dry run (M7) reproduces the entire experience with zero hardware, and is labelled `SIMULATION` per DESIGN.md |

---

## 15. Explicitly not in this plan

- Any change to firmware, to `BuildController`, `BuildJob` or `link.py`. This
  plan is additive and lives in `web/` plus optional read-only backend routes.
- Autonomous target selection. The operator or a compiled model chooses every
  block.
- Physics simulation beyond the static support and collision predicates in §6.
  No rigid-body solver; the machine cannot place a block that falls over anyway.
- Multi-user editing, cloud sync, accounts.
- A cancel or retry control anywhere in the runner. The firmware is deaf during
  a build and an aborted session has no software recovery.

---

## 16. Open questions to settle before M4

1. What is the practical level ceiling? The Z axis allows ~17; the claw and the
   blocks will allow fewer. Measure it and set the `LEVEL_CEILING` default.
2. What is the real claw footprint, for `CLAW_MARGIN_MM`?
3. Does a horizontal block resting on two vertical blocks actually hold? If yes,
   §6.5's ratio rule stands as the headline structural feature. If not, the rule
   stays but the default ratio goes to 1.0 and bridging becomes a warning.
4. Should the runner be allowed to issue `POST /api/mode` unattended, given that
   a latch homes the rig? Current assumption: only with the operator watching,
   and only after an explicit confirm.

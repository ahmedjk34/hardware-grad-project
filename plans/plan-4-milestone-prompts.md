# Plan 4 — milestone prompts

One self-contained prompt per milestone from
[plan-4-3d-build-studio.md](plan-4-3d-build-studio.md). Paste the block below
the rule into a fresh agent session that has this repository checked out.

**Work them in order.** Each assumes the previous milestone is committed and its
tests pass. Do not start M<sub>n+1</sub> before M<sub>n</sub> is green — the
whole plan is built so that every milestone is independently demonstrable, and
skipping ahead loses that.

**Every prompt repeats five constraints on purpose.** They are the ones an agent
that has not read the repository will otherwise get wrong:

1. Read `plans/plan-4-3d-build-studio.md` fully before writing code.
2. **Test-driven development. Tests first, always** — Plan 4 §0.
3. Nothing bypasses the server's safety model.
4. No CDN assets — everything bundles and works offline over LAN.
5. Geometry comes from `config/rig.json` at runtime, never hard-coded.

### The rule that applies to all nine

Write the test file, run it, watch it fail *for the right reason*, then write the
implementation until it passes, then clean up. Test and implementation are
committed together, **test first in the diff**. "Tests first" is not "tests
eventually" — if you are writing implementation with no failing test pointing at
it, stop and write the test.

Plan 4 is layered so this is practical: `coords.ts`, `geometry.ts`, `model.ts`,
`validate.ts`, `compile.ts` and `library.ts` contain every rule and contain no
React and no three.js, so they test headless in milliseconds. `scene/` and
`panels/` only draw. **If a rule about the machine ends up in a component, it
has escaped the test suite** — move it down and test it there. Do not write
tests that assert on pixels, camera angles or animation timings; judge the look
by eye and the rules by test.

---

## M0 — Coordinates and fixtures ✅ DELIVERED

**Shipped.** `web/src/studio/coords.ts` + `geometry.ts`, fixtures dumped by
`python/tools/dump_grid_fixtures.py` into `web/src/studio/coords.fixtures.json`
(17 cases, 980 cells: both modes, shipped and clipped and refused shifts, plus
trims and error offsets on a synthetic envelope), checked at 1e-6 by
`coords.test.ts` and `geometry.test.ts`. `cd web && npm test` is green at 75
tests across 7 files. Notes worth carrying into later milestones:

- The browser imports `config/rig.json` directly; `vite.config.ts` gained
  `server.fs.allow: [".."]` so the dev server can reach it. No second copy of
  the geometry anywhere.
- Machine space is **millimetres**. The config and the internal lattice are in
  centimetres, and `coords.ts` is the only place that converts.
- Block height (1.5 cm) has no `rig.json` partner — it is the firmware's
  `BLOCK_HEIGHT_CM`, named once in `coords.ts`.
- `latticeBounds()` reports the REACHABLE grid by default (what a shift has
  clipped), matching `MachineGrid`; pass `"requested"` for the grid the operator
  asked for, which is what M8's amber clipped-cell shading wants.
- `AGENTS.md` §3a and §3b were stale against `grid.py` and the firmware and have
  since been corrected in the same pass.

The prompt as issued:

```text
Read `plans/plan-4-3d-build-studio.md` in full before writing any code, and read
it carefully — §2, §3 and §4 in particular. It is long on purpose; the whole
milestone depends on facts stated there that you cannot infer from the code in
an afternoon. Then read `python/rig/grid.py` (all of it, including the module
docstring, which is the specification), `python/rig/workspace.py`,
`config/rig.json`, and `AGENTS.md` §3a and §3b.

HOW TO WORK — TEST FIRST, NOT TESTS EVENTUALLY
This plan is test-driven; read Plan 4 §0 before anything else and follow it.
For every deliverable below: write the test, run it, watch it fail for the right
reason, then implement until it passes, then clean up. Test and implementation
are committed together, test first in the diff. If you are writing
implementation with no failing test pointing at it, stop and write the test.
A test that fails because the module does not exist yet has failed for the right
reason; one that fails on a typo in the test has not — read the failure before
writing the fix.
`cd web && npm test` must be green when you finish, INCLUDING the console's
existing `step7`, `step9`, `step10` and `lib/workspace.test.tsx`. Nothing in
Plan 4 may regress Plan 3.
Write the fixture dumper and `coords.test.ts` BEFORE `coords.ts`. The fixtures
are the specification for this milestone — generate them from Python first, look
at the numbers, and only then write TypeScript to match. When the two disagree,
Python is right.

TASK
Build the coordinate and geometry foundation for the 3D Build Studio:
`web/src/studio/coords.ts` and `web/src/studio/geometry.ts`. Pure TypeScript.
No React, no three.js, no DOM. This is the layer every later milestone stands
on, so it is worth being slow and exact here.

WHY THIS IS FIRST
Almost every bug in a project like this is a coordinate-space bug. Plan 4 §4
names three spaces — cell space, machine space (millimetres), scene space — and
requires that axis handling exists in exactly one module. This milestone creates
that module and proves it agrees with Python to 1e-6.

DELIVERABLES

1. `web/src/studio/coords.ts`
   - Load the per-mode lattice geometry from the rig config. Read it at runtime;
     never hard-code the numbers in Plan 4 §3's table — that table is there so
     you can sanity-check your output, not so you can paste it.
   - `cellToMachine(mode, col, row, level) -> {x, y, z}` in millimetres,
     implementing the six-line formula in Plan 4 §3 fact 2 exactly:
     `centre(i) = trim + error_offset + shift + i * pitch`, `pitch = block + gap`.
     Cell 0's centre sits on the home corner. There is no leading gap, no
     trailing gap and no centring. Z is the block CENTRE: `level * 15 + 7.5`.
   - `blockExtents(mode) -> {x, y, z}` in mm, reading `block_x_cm` / `block_y_cm`
     per mode. Never swap a width for a length — Plan 4 §3 fact 3, and
     `grid.py`'s docstring, both explain why this matters.
   - `machineToScene()` and the single scene transform from Plan 4 §4.
   - `latticeBounds(mode)`, `cellCount(mode)`, `isFeeder(col, row)`.

2. `web/src/studio/geometry.ts`
   - `aabbOf(block)` in machine space.
   - `intersects(a, b)`, `footprintOverlapArea(a, b)`, `topFaceZ(block)`.
   - `clippedCells(mode, shift)` — which cells the current shift pushes past the
     travel cap. Mirror the firmware's behaviour described in Plan 4 §3 fact 5
     and in `build_test_v1.ino`'s `GRID_SHIFT_X_CM` header comment: the
     requested grid is kept, the reachable grid is clipped, and clearing the
     shift restores it. Check against `max_edge_overhang_*_cm`, per mode.

3. A fixture bridge. `python/tools/dump_workspace_fixtures.py` already
   establishes this pattern for the homography port in `web/src/lib/workspace.ts`
   — follow it rather than inventing a second mechanism. Add a dumper that emits
   cell centres, footprints and AABBs from `MachineGrid` for both modes across a
   spread of trims, error offsets and shifts, into a JSON fixture under
   `web/src/studio/`.

4. `web/src/studio/coords.test.ts` — Vitest, comparing every fixture row to the
   TypeScript output to within 1e-6.

CONSTRAINTS
- Geometry is read from `config/rig.json` at runtime. If a value moves, nothing
  in this module needs editing.
- No dependency on three.js yet. `machineToScene` returns plain numbers.
- This module is the TypeScript counterpart of `python/rig/grid.py`. When the
  two disagree, Python is right.

DONE WHEN
Every cell centre, footprint and AABB matches Python for both modes, across all
fixture trims and shifts, to 1e-6. `cd web && npm test` passes.

REPORT BACK
The fixture coverage (how many cases, which parameters varied), anything where
the Python behaviour was ambiguous and how you resolved it, and any place
`grid.py` and `build_test_v1.ino` appear to disagree — that last one is worth
knowing about regardless of this milestone.
```

---

## M1 — Static viewport ✅ DELIVERED

**Shipped.** The Studio route renders the machine to scale in a dark space:
travel-cap cage with centimetre rulers, the active mode's lattice at its true
footprints and gaps, the hatched `FEED` cell, four snap views and an orbit that
cannot go under the floor. `cd web && npm test` is green at **102 tests across
9 files** (75 before, 27 new).

New pure modules, both written test-first and both holding rules that would
otherwise have hidden in a component:

- `web/src/studio/view.ts` — the travel envelope in scene units, `frameDistance`
  (how far back a camera must stand for the envelope to fit a given aspect),
  `viewPose` for top / front / side / iso, `screenAxes`, `clampAboveGround` and
  `tweenMs`. `view.test.ts` re-derives the perspective projection itself and
  asserts every corner of the envelope lands inside every snap's frustum at
  16:9, 4:3 and a 0.5 portrait phone.
- `web/src/studio/lattice.ts` — `latticeCells(mode, shift)` decides WHICH cells
  are drawn and what each one is (`feeder` / `cell` / `clipped`), and
  `rulerTicks` places the envelope's centimetre marks. `lattice.test.ts` holds
  both to `coords.ts` and `geometry.clippedCells()`.

Renderer files, which hold no rules: `studio/scene/Viewport.tsx` (canvas, camera
rig, lights, contact shadows), `Envelope.tsx`, `Lattice.tsx` and `theme.ts`.
Route chrome: `routes/Studio.tsx` and `routes/Root.tsx`.

Notes worth carrying into later milestones:

- **There is no scene-group transform.** Plan §4 sketches one
  (`rotation.x = -π/2`, `scale 0.1`), but `coords.machineToScene()` already
  returns scene space and is fixture-tested, so applying a group transform on
  top of it would convert twice. `scene/` draws the numbers the pure layer hands
  it. Keep it that way — a component that starts rotating things is the bug.
- **Routing is hash-based.** `routes/Root.tsx` renders the console at `#/` and
  lazily imports the Studio at `#/studio`. A hash route needs no server rewrite,
  which keeps the static-file serve and the PWA offline shell working. The
  console's rail carries the link.
- **No text in the WebGL context.** drei's `<Text>` is troika, which fetches a
  default font from a CDN — forbidden by DESIGN.md §3.2. Labels are drei
  `<Html>`, so the ruler numbers and `FEED` use the real type tokens.
- **`scene/theme.ts` reads the CSS custom properties off the document** and
  turns them into three.js colours, so DESIGN.md §3.1's "no raw hex in a
  component" holds inside the canvas too. An unreadable token stays three's own
  default rather than becoming a literal nobody designed.
- **`frameloop="demand"`.** DESIGN.md §3.4 forbids motion on an idle screen; an
  idle Studio issues no draw calls at all. The view tween calls `invalidate()`
  per frame while it runs, and `prefers-reduced-motion` makes `tweenMs()` zero,
  which snaps instead.
- **The cage's height is the firmware's `Z_TRAVEL_CM` (26.5 cm)**, named once in
  `view.ts` — `rig.json` has no Z partner, exactly as with `BLOCK_HEIGHT_CM`.
- **Top view's up vector is `(0, 0, −1)`**, which puts machine +X to the right
  and machine +Y up the screen. That is the framing M6 lays the twin against, so
  it is asserted in `view.test.ts` rather than left to taste.
- **Not verified by eye.** The suite and `npm run build` are green and the
  chunking was checked in the built output, but no browser render of this
  milestone has been seen — headless Chrome could not reach the preview server
  from this environment. Look at `#/studio` before building M2 on top of it.

Dependencies, pinned exact, installed locally, no CDN:
`three@0.185.1`, `@react-three/fiber@9.7.0`, `@react-three/drei@10.7.8`, and
`@types/three@0.185.0` as a dev dependency.

Bundle sizes from `npm run build`, before and after the split:

| chunk | before | after |
| --- | --- | --- |
| console entry | 216.92 kB (68.24 kB gzip) | 218.36 kB (68.77 kB gzip) |
| `Studio-*.js` (lazy, `#/studio` only) | — | 919.98 kB (246.12 kB gzip) |
| CSS | 20.46 kB (5.10 kB gzip) | 22.62 kB (5.47 kB gzip) |

The console's first paint pays **1.44 kB** for the Studio existing — the lazy
import and the hash router. `grep -c WebGLRenderer` on the console chunk is 0
and on the Studio chunk is 6.

**Frame rate on a mid-range phone: an estimate, not a measurement.** The scene
is one line geometry for the cage, one for the rulers, two for the lattice
outlines, and one flat mesh per cell (42 vertical / 30 horizontal) — well under
a hundred draw calls with no per-frame work, and with `frameloop="demand"` a
still viewport costs nothing at all. The cost is concentrated in the one-off
1024² shadow map and `ContactShadows` at `frames={1}`. Orbiting should hold 60
fps; if a phone struggles, drop `dpr` to `[1, 1.5]` and the contact-shadow
resolution to 512 before touching anything else.

The prompt as issued:

```text
Read `plans/plan-4-3d-build-studio.md` in full and carefully — §4, §7, §8.1 and
§8.2 especially. Also read `docs/DESIGN.md` §3 (tokens) and §8 (what must not be
done); the Studio has to feel like the same instrument as the operator console,
not a second application. M0 is complete: `web/src/studio/coords.ts` and
`geometry.ts` exist and are fixture-tested against Python. Use them. Do not
recompute a single coordinate yourself.

HOW TO WORK — TEST FIRST, NOT TESTS EVENTUALLY
This plan is test-driven; read Plan 4 §0 before anything else and follow it.
For every deliverable below: write the test, run it, watch it fail for the right
reason, then implement until it passes, then clean up. Test and implementation
are committed together, test first in the diff. If you are writing
implementation with no failing test pointing at it, stop and write the test.
A test that fails because the module does not exist yet has failed for the right
reason; one that fails on a typo in the test has not — read the failure before
writing the fix.
`cd web && npm test` must be green when you finish, INCLUDING the console's
existing `step7`, `step9`, `step10` and `lib/workspace.test.tsx`. Nothing in
Plan 4 may regress Plan 3.
This milestone is mostly rendering, which Plan 4 §0.4 explicitly says not to
unit-test: no assertions on pixels, camera angles, materials or tween timings.
What IS testable and must be written test-first: the view-snap camera target
maths, the orbit constraint (never below the ground plane), and any lattice
data-preparation function that decides WHICH cells to draw. If you find yourself
about to put a geometry decision in a component, move it into the pure layer and
test it there.

TASK
Stand up the 3D viewport: a dark space containing an accurate, to-scale,
non-interactive render of the machine — the travel envelope, the active mode's
lattice, and the feeder cell. Orbit, pan, zoom, and snap views.

DELIVERABLES

1. Dependencies: `three`, `@react-three/fiber`, `@react-three/drei`. Pin exact
   versions and install them locally. NO CDN — the Pi serves this over LAN with
   no guaranteed internet (see `docs/DESIGN.md` §3.2). Code-split the Studio
   route so the console's first paint does not pay for three.js.

2. `web/src/routes/Studio.tsx` and `web/src/studio/scene/Viewport.tsx` — the R3F
   canvas, camera rig, lighting per Plan 4 §8.2 (one key directional with soft
   shadows, one dim fill, faint hemisphere, and contact shadows under geometry;
   that last effect is what will later make blocks look *placed* rather than
   floating).

3. `Envelope.tsx` — the travel cap as a thin wireframe box with centimetre
   rulers on two edges. This is the machine's real limit and should always be
   visible.

4. `Lattice.tsx` — every addressable cell as its true footprint with the true
   gaps. Feeder `[0,0]` hatched and labelled `FEED`. Renders both modes
   correctly; which one is shown is a prop for now.

5. View snaps — top / front / side / iso, with a smooth tween. Top view must
   frame the workspace the same way the overhead camera does; M6 depends on it.

6. Orbit constrained to above the ground plane.

CONSTRAINTS
- Colours, spacing and type come from the `docs/DESIGN.md` tokens. No raw hex.
- No infinite checkerboard ground — Plan 4 §8.2 rules it out as visual noise.
- Nothing animates on an idle screen (`docs/DESIGN.md` §3.4).
- Honour `prefers-reduced-motion` for the view tweens.

DONE WHEN
It looks like the machine, from any angle, with correct proportions, in both
modes. `npm run build` succeeds and the console route's bundle does not include
three.js.

REPORT BACK
Bundle sizes before and after with the split in place, the exact dependency
versions pinned, and a note on frame rate on a mid-range phone if you can
estimate it.
```

---

## M2 — Placement

```text
Read `plans/plan-4-3d-build-studio.md` in full and carefully — §8.3 is the heart
of this milestone, plus §3 facts 1, 4 and 6, and §4. M0 and M1 are complete: the
coordinate module is fixture-tested and the viewport renders the envelope,
lattice and feeder. Use `coords.ts` for every position; never juggle axes in a
component.

HOW TO WORK — TEST FIRST, NOT TESTS EVENTUALLY
This plan is test-driven; read Plan 4 §0 before anything else and follow it.
For every deliverable below: write the test, run it, watch it fail for the right
reason, then implement until it passes, then clean up. Test and implementation
are committed together, test first in the diff. If you are writing
implementation with no failing test pointing at it, stop and write the test.
A test that fails because the module does not exist yet has failed for the right
reason; one that fails on a typo in the test has not — read the failure before
writing the fix.
`cd web && npm test` must be green when you finish, INCLUDING the console's
existing `step7`, `step9`, `step10` and `lib/workspace.test.tsx`. Nothing in
Plan 4 may regress Plan 3.
Write `model.test.ts` before `model.ts`: every mutation, the undo/redo stack to
depth 100, and the guarantee that moving a block does not reorder it and
reordering does not move it. Write tests for the cell-resolution maths — given a
raycast hit point, which cell and level — before wiring the raycaster. The
raycasting itself needs no GPU test; the maths behind it does.

TASK
Make the Studio a modelling tool. Hover a cell and a ghost block snaps into it;
click and a real 3D block appears; hover the top of that block and the ghost
rises a level. This one gesture has to be perfect — everything else in Plan 4
is scaffolding around it.

DELIVERABLES

1. `web/src/studio/model.ts` — the in-memory model: a list of
   `{id, mode, col, row, level, colour}` plus an `order` array, per the schema in
   Plan 4 §5. Geometry and order are SEPARATE: moving a block must not reorder
   it, reordering must not move it.

2. `Blocks.tsx` — placed blocks as instanced meshes, correctly proportioned per
   mode (a vertical block is 2.2 × 6.0 × 1.5 cm; a horizontal one is
   6.0 × 2.2 × 1.5 — different grids, not a rotated one), lit with contact
   shadows.

3. `Ghost.tsx` — the hover preview. Raycast against BOTH the lattice plane and
   the top faces of placed blocks; whichever is hit determines the target cell
   and level, so hovering a stack naturally means "on top of this". Translucent
   `--signal` when legal, translucent `--danger` with an outline when not.

4. Interactions: click commits with a ~140 ms drop-and-settle; alt-click
   removes; shift-drag fills a run of cells.

5. Level scrubber (Plan 4 §8.3): hold a level and the ghost locks to it
   regardless of what is beneath, so overhangs can be planned before their
   supports exist. Blocks above the held level fade to ~15% — an x-ray by level
   that costs one uniform.

6. Undo/redo as a command stack over the model. `Ctrl-Z` / `Ctrl-Shift-Z`,
   depth ≥ 100. Non-negotiable for a modelling tool.

7. Vitest coverage for `model.ts` mutations and the undo stack. The raycasting
   itself does not need a GPU test; the cell-resolution maths does.

CONSTRAINTS
- Only the cheap, local checks belong here: `[0,0]` is the feeder and is never a
  target, and a cell is inside the grid. The full validation suite is M3 — do
  not start writing support and collision rules in this milestone.
- Blocks are stored in cell space WITH their own mode, so they resolve to the
  same machine-space position regardless of what is latched later (Plan 4 §8.4
  point 3). Getting this wrong now breaks M4 badly.

DONE WHEN
You can build a tower and a two-column bridge by hand, undo the whole thing, and
redo it. It feels good — the ghost never lags, never flickers between cells, and
never lands somewhere the cursor was not pointing.

REPORT BACK
How the raycast resolves ambiguity when the lattice plane and a block top are
both under the cursor, and anything about the placement feel you would want a
second pass on.
```

---

## M3 — Validation

```text
Read `plans/plan-4-3d-build-studio.md` in full and carefully — §6.4, §6.5 and
§6.6 are this milestone, and §3's seven facts are the reasoning behind them.
M0–M2 are complete: coordinates are fixture-tested, the viewport renders, and
placement works. Use `geometry.ts` for every predicate.

HOW TO WORK — TEST FIRST, NOT TESTS EVENTUALLY
This plan is test-driven; read Plan 4 §0 before anything else and follow it.
For every deliverable below: write the test, run it, watch it fail for the right
reason, then implement until it passes, then clean up. Test and implementation
are committed together, test first in the diff. If you are writing
implementation with no failing test pointing at it, stop and write the test.
A test that fails because the module does not exist yet has failed for the right
reason; one that fails on a typo in the test has not — read the failure before
writing the fix.
`cd web && npm test` must be green when you finish, INCLUDING the console's
existing `step7`, `step9`, `step10` and `lib/workspace.test.tsx`. Nothing in
Plan 4 may regress Plan 3.
This is the milestone where test-first matters most, and it is also the easiest
place to apply it: every rule in Plan 4 §6.4 is a pure function. Write the whole
table as failing tests FIRST — one passing case and one failing case per rule —
then implement until they go green. The cross-mode bridging case for the support
rule (§6.5) gets its own explicit test, because the naive implementation would
forbid it and you want that failure to be loud.

TASK
Implement every validation rule as a pure function, then surface it in the UI so
an operator sees why a placement is illegal before committing it.

DELIVERABLES

1. `web/src/studio/validate.ts` — pure, no React, no three.js. Every rule from
   Plan 4 §6.4's table: FEEDER_CELL, OUT_OF_GRID, CLIPPED_BY_SHIFT,
   EDGE_OVERHANG, LEVEL_CEILING, DUPLICATE_CELL, COLLISION, UNSUPPORTED,
   CLAW_CLEARANCE, GEOMETRY_DRIFT, ISLAND. Each returns structured diagnostics:
   `{severity, code, blockId, message, fix?}`.

2. The support rule per Plan 4 §6.5 — footprint-overlap AREA, not "same cell one
   level down". Read that section carefully and understand why: within one mode
   the 1.6 cm gaps make bridging impossible, but a horizontal block is 6.0 cm
   along X while the vertical pitch is 3.8 cm, so a horizontal block CAN span
   two vertical stacks. That cross-mode bridging is the machine's most
   interesting structural capability and the naive rule would forbid it.
   `supported = area(beneath ∩ footprint) / area(footprint)`, valid at
   `>= SUPPORT_RATIO` (default 0.55) AND with the footprint centroid over
   supported area.

3. The claw-clearance rule per §6.6 — a descent prism over the target footprint
   inflated by `CLAW_MARGIN_MM` (default 8), from the target's top face up to
   travel height. A warning, not an error, and the UI copy must say plainly that
   the margin is a guess until somebody measures the claw.

4. `SUPPORT_RATIO`, `CLAW_MARGIN_MM` and `LEVEL_CEILING` as visible Studio
   settings with honest plain-language explanations. They encode guesses about
   friction and claw precision that only physical testing can settle. Ship them
   conservative and show them.

5. `panels/Diagnostics.tsx` — the list, grouped by severity, each row clicking
   through to select and frame its block. Per-block markers in the viewport.

6. Ghost integration: the invalid ghost shows its exact failure reason as a
   label beside the cursor — "[0,0] is the feeder", "would collide with b4",
   "unsupported: 30% contact".

7. Vitest: EVERY rule gets at least one passing and one failing case, and the
   support rule gets the cross-mode bridging case explicitly.

CONSTRAINTS
- Pure functions, testable with no browser and no GPU. This is what makes the
  claims about the validator defensible in a write-up.
- `CLIPPED_BY_SHIFT` must reproduce the firmware's clipping, not approximate it.
  M0's `clippedCells()` already does the work; use it.

DONE WHEN
Every rule has a unit test and a way to make it fire in the UI by hand.

REPORT BACK
Which defaults you chose for the three constants and why, and which rules you
believe will need physical measurement to settle (Plan 4 §16 lists the open
questions — say whether your implementation changed any of them).
```

---

## M4 — The compiler

```text
Read `plans/plan-4-3d-build-studio.md` in full and carefully. §6 is this
milestone in its entirety, and §2.1 explains the constraint that makes it
non-trivial — read that one twice. Also read `AGENTS.md` §6 (firmware command
vocabulary) and `python/rig/link.py`'s `set_mode()`.

HOW TO WORK — TEST FIRST, NOT TESTS EVENTUALLY
This plan is test-driven; read Plan 4 §0 before anything else and follow it.
For every deliverable below: write the test, run it, watch it fail for the right
reason, then implement until it passes, then clean up. Test and implementation
are committed together, test first in the diff. If you are writing
implementation with no failing test pointing at it, stop and write the test.
A test that fails because the module does not exist yet has failed for the right
reason; one that fails on a typo in the test has not — read the failure before
writing the fix.
`cd web && npm test` must be green when you finish, INCLUDING the console's
existing `step7`, `step9`, `step10` and `lib/workspace.test.tsx`. Nothing in
Plan 4 may regress Plan 3.
Write the compiler's tests before a line of `compile.ts`. Each ordering
constraint in §6.2 needs a test THAT FAILS WHEN THAT CONSTRAINT IS REMOVED — a
constraint with no such test is not enforced, it is only hoped for. Prove that
by deleting each constraint in turn and confirming exactly the expected test
goes red.
The determinism test is not optional: compile the same model twenty times and
assert byte-identical output. Non-deterministic ordering would make every other
test here worthless and the demo unrepeatable.

TASK
Turn a model into an ordered command program. This is the intellectual core of
Plan 4 and the part most worth doing well.

THE CONSTRAINT THAT MAKES IT INTERESTING
`B` takes three numbers — `B <col> <row> <level>` — and nothing else. Block
orientation is NOT an argument; it comes from a mode latch, `R` (vertical) or
`RR` (horizontal), which:
  - is refused unless X and Y are homed, so a latch means physical motion;
  - is refused if the board is ALREADY in that mode;
  - resets to `vertical` on a board reset, which is why `@0 READY` reports
    `mode=`.
So a mixed-orientation model is not a flat list. It must be sorted into mode
runs, and each run costs a homing move.

DELIVERABLES

1. `web/src/studio/compile.ts` — pure TypeScript. No React, no three.js.
   Output shape exactly as Plan 4 §6.1: `{valid, program, stats, diagnostics}`,
   where `program` is a list of `mode` and `build` ops each carrying its literal
   command text.

2. Ordering per §6.2, in that priority order:
     1. support before supported (a partial order over the support graph);
     2. bottom-up by level;
     3. minimise mode latches by grouping same-mode runs within each level band;
     4. respect the author's order wherever it does not violate 1–3;
     5. deterministic tie-break by col, then row, then id.
   Implementation: Kahn topological sort with a priority queue keyed on
   `(level, currentModeFirst, authorIndex, col, row, id)`.

3. The mode-latch state machine per §6.3. Initial state is `vertical` unless the
   live `state.mode` says otherwise. Emit a `mode` op ONLY on an actual change —
   the firmware refuses a redundant latch. Annotate every `mode` op with
   `homes X and Y`.

4. `panels/ProgramView.tsx` — the compiled program as readable serial text, with
   latches visually separated from builds.

5. Estimated duration from a configurable per-block cycle time plus a per-latch
   homing cost.

6. Heavy Vitest coverage: a pure-vertical model, a pure-horizontal model, an
   interleaved model that forces multiple latches, a model where the author's
   order is legal and must be preserved, one where it is not and must be
   overridden, and a determinism test that compiles the same model twenty times
   and asserts identical output.

CONSTRAINTS
- DETERMINISM IS A REQUIREMENT, not a nicety. Non-deterministic output makes the
  tests worthless and the demo unrepeatable.
- The compiler never emits anything that the M3 validator would reject. If the
  model is invalid, `valid` is false and `program` is empty.
- No React, no DOM, no three.js in this module.

DONE WHEN
A mixed-mode model compiles to a correct, minimal-latch, repeatable program, and
every ordering constraint has a test that fails when the constraint is removed.

REPORT BACK
The worst case your ordering heuristic produces (a model that forces many
latches), whether a cheaper ordering exists for it, and whether you found any
model that is valid but uncompilable.
```

---

## M5 — Library

```text
Read `plans/plan-4-3d-build-studio.md` in full and carefully — §5 (the model
file format) and §8.7 (the library) are this milestone. M0–M4 are complete:
coordinates, viewport, placement, validation and the compiler all work.

HOW TO WORK — TEST FIRST, NOT TESTS EVENTUALLY
This plan is test-driven; read Plan 4 §0 before anything else and follow it.
For every deliverable below: write the test, run it, watch it fail for the right
reason, then implement until it passes, then clean up. Test and implementation
are committed together, test first in the diff. If you are writing
implementation with no failing test pointing at it, stop and write the test.
A test that fails because the module does not exist yet has failed for the right
reason; one that fails on a typo in the test has not — read the failure before
writing the fix.
`cd web && npm test` must be green when you finish, INCLUDING the console's
existing `step7`, `step9`, `step10` and `lib/workspace.test.tsx`. Nothing in
Plan 4 may regress Plan 3.
Write the round-trip tests first: model → JSON → model is lossless; a corrupt
file is rejected with a useful message rather than a crash; a full or
unavailable `localStorage` degrades gracefully instead of breaking the Studio.
Then write `library.ts`. The three built-in example models are fixtures as well
as demos — assert that each one loads, validates clean, and compiles.

TASK
Persistence. Save models, load them, name them, export them, import them, and
ship three built-in examples so an empty library never looks broken.

DELIVERABLES

1. `web/src/studio/library.ts` — CRUD over `localStorage`, namespaced
   `rig.studio.models.v1`, with a size guard because thumbnails add up. Wrap
   every read and write in try/catch: storage can be unavailable or full, and
   the Studio must still work with no persistence at all.

2. The `rigmodel/1` file format exactly as Plan 4 §5 specifies — including the
   `rig` snapshot block. That snapshot is not a dependency; it exists so that
   opening a model authored before a geometry change produces a clear
   `GEOMETRY_DRIFT` warning (already implemented in M3) instead of a wrong
   build. Wire the two together.

3. Schema validation and a migration hook on load. Version 1 is the only version
   today; the hook exists so version 2 is not a crisis.

4. Thumbnails: render the viewport to WebP on save. Keep them small.

5. `panels/LibraryDrawer.tsx` — cards with thumbnail, name, block count,
   estimated build time, mode-latch count, modified date. Duplicate, rename,
   delete with undo.

6. Export / import as `.rigmodel.json`, single file or a zip of the whole
   library. Drag a file onto the window to import.

7. THREE BUILT-IN EXAMPLE MODELS, shipped in the bundle:
     - a simple tower (single cell, several levels);
     - a two-column bridge using a cross-mode horizontal span — this one
       demonstrates the machine's most interesting capability and exercises the
       compiler's mode-latch logic;
     - a stepped pyramid.
   These are also your fallback demo if something goes wrong on presentation
   day, so make them good.

8. Vitest for the round trip: model → JSON → model is lossless; a corrupt file
   is rejected with a useful message, not a crash; a full `localStorage` is
   handled gracefully.

CONSTRAINTS
- `localStorage` is the source of truth for now. Do NOT build a sync engine.
  Server persistence (`GET/PUT /api/models`) is noted in Plan 4 §8.7 as a later
  option; leave a clean seam for it and nothing more.
- Everything works offline. No network call in this milestone.

DONE WHEN
You can close the tab, reopen it, and your models are there. Import and export
round-trip cleanly. The three examples load and compile.

REPORT BACK
The storage budget you settled on, what happens when it is exceeded, and the
compiled program for the bridge example (it is the interesting one).
```

---

## M6 — The twin

```text
Read `plans/plan-4-3d-build-studio.md` in full and carefully — §9 is this
milestone. Also read `plans/plan-3-web-operator-console.md` §2's eight facts,
`docs/DESIGN.md` §4 (the state model IS the design), `python/web/state.py` and
`python/web/app.py`. M0–M5 are complete.

HOW TO WORK — TEST FIRST, NOT TESTS EVENTUALLY
This plan is test-driven; read Plan 4 §0 before anything else and follow it.
For every deliverable below: write the test, run it, watch it fail for the right
reason, then implement until it passes, then clean up. Test and implementation
are committed together, test first in the diff. If you are writing
implementation with no failing test pointing at it, stop and write the test.
A test that fails because the module does not exist yet has failed for the right
reason; one that fails on a typo in the test has not — read the failure before
writing the fix.
`cd web && npm test` must be green when you finish, INCLUDING the console's
existing `step7`, `step9`, `step10` and `lib/workspace.test.tsx`. Nothing in
Plan 4 may regress Plan 3.
Write the state → twin mapping tests first, driven by fixture `/api/events`
payloads covering every row of Plan 4 §9.2's table: ghosts, next-target,
RUNNING, placed, rejected, and LOCKED. The LOCKED case deserves its own explicit
assertion that the twin STOPS animating — after an abort the machine's real
state is unknown and the twin must not pretend to know it.
Rendering needs no GPU test. The mapping does, and that is where the bugs that
matter will be.

TASK
Put the same 3D engine, read-only, on the index page beside the live camera, and
drive it from real server state. Real workspace and virtual workspace, in step.
This is the demo.

DELIVERABLES

1. `web/src/studio/scene/Twin.tsx` — a reduced-cost variant of the viewport: no
   shadows, no post-processing, instanced blocks. It runs beside a live MJPEG
   stream on a phone, so it must be cheap.

2. Index layout: camera and twin side by side, equal width, top-aligned, on
   desktop. On a phone they become a two-tab switcher above the action sheet,
   DEFAULTING TO THE CAMERA — the camera is what the operator must be watching.

3. Every state response from Plan 4 §9.2's table, driven by the existing
   `/api/events` state: remaining blocks as ghosts, the next target pulsing and
   labelled, RUNNING animating a descent, `placed` snapping solid, `rejected`
   returning to a ghost with its reason, and LOCKED desaturating the whole twin
   under a red plate with NO further animation. That last one matters: after an
   abort the machine's real state is unknown, and the twin must not pretend to
   know it.

4. `SYNC VIEW` toggle (§9.3) — snap the twin's camera to top-down and match its
   framing to the camera's workspace rectangle so both panels show the same
   thing from the same angle.

5. Mode handling: the twin's mode indicator is a READ-ONLY mirror of
   `state.mode`. Switching modes on the index page goes through the console's
   existing confirmed `POST /api/mode`, which homes the rig. The Studio's free,
   instant mode morph and the console's physical mode latch must never be
   confused with each other.

6. Vitest coverage for the state → twin mapping, driven by fixture state
   payloads. The rendering does not need a GPU test; the mapping does.

CONSTRAINTS
- The twin is READ-ONLY. No placement, no editing, no gizmos.
- It never invents state. If the server has not said a block was placed, the
  twin does not show it placed.
- Do not regress anything in the console. `npm test` must stay green, including
  `step7`, `step9`, `step10` and `lib/workspace.test.tsx`.

VERIFICATION
Run `cd python && ../.venv/bin/python -m web --mock` and `cd web && npm run dev`.
The mock board produces placed, rejected and aborted outcomes — drive all three
plus the locked banner, and confirm the twin responds correctly to each. Check
the layout at 390px, 768px and 1440px.

DONE WHEN
A full mock build session fills the twin in correctly, including the locked case.

REPORT BACK
Frame rate with the MJPEG stream and the twin both running, and how the twin
behaves if the socket drops mid-build.
```

---

## M7 — The runner

```text
Read `plans/plan-4-3d-build-studio.md` in full and carefully — §10 is this
milestone, and §3 fact 7 plus `plans/plan-3-web-operator-console.md` §2's eight
facts are the safety reasoning you must not violate. Also read
`python/web/routes_command.py`, `python/rig/build_controller.py` and
`python/rig/build_job.py`. M0–M6 are complete.

HOW TO WORK — TEST FIRST, NOT TESTS EVENTUALLY
This plan is test-driven; read Plan 4 §0 before anything else and follow it.
For every deliverable below: write the test, run it, watch it fail for the right
reason, then implement until it passes, then clean up. Test and implementation
are committed together, test first in the diff. If you are writing
implementation with no failing test pointing at it, stop and write the test.
A test that fails because the module does not exist yet has failed for the right
reason; one that fails on a typo in the test has not — read the failure before
writing the fix.
`cd web && npm test` must be green when you finish, INCLUDING the console's
existing `step7`, `step9`, `step10` and `lib/workspace.test.tsx`. Nothing in
Plan 4 may regress Plan 3.
Write the runner state machine's tests first, against a mocked API, covering
every path before you write the runner: the happy path, command-mismatch stop,
rejection-pause, abort-lock, and a mode op. Include a test asserting that the
runner NEVER has two builds in flight and never issues a command while
`build_state` is RUNNING — that is the safety property this milestone exists to
preserve, so it gets an explicit test rather than a careful implementation and
a hopeful comment.

TASK
Execute a compiled program against the rig, one block at a time, without
weakening a single existing guard.

DELIVERABLES

1. The runner: for each step, `POST /api/select` or `/api/select/axis`, then
   VERIFY that `state.command` matches the compiled op's command text, then
   `POST /api/build`. If they ever disagree, STOP and say why — a mismatch means
   the model and the rig disagree about the world, and continuing would place a
   block somewhere nobody asked for.

2. A `mode` op calls `POST /api/mode`. That homes X and Y, so warn first, every
   time — the rig moves without a `B`.

3. Three run styles per §10:
     - STEP: confirm each block.
     - RUN: continuous, with a stop-after-this-block control that is HONEST
       about not interrupting the block in flight.
     - DRY RUN: no serial at all, the twin animates the whole program in ~20
       seconds. This is the demo mode and the rehearsal mode; make it good.

4. Feeder prompts: `FEED: RED · block 7 of 24` before each block, from the
   model's colour intent. The feeder is manual and this turns the runner into
   guided assembly.

5. Failure handling: `REJECTED` pauses the run and keeps position. `ABORTED`
   locks everything per the existing rules, and the program state is preserved
   READ-ONLY so you can see exactly how far it got.

6. Run report: commands sent, results, per-block durations, total time, camera
   thumbnails, and vision verification if present. Exportable as Markdown.

7. Vitest for the runner state machine against a mocked API — every path,
   including mismatch-stop, rejection-pause and abort-lock.

CONSTRAINTS — READ THESE TWICE
- NOTHING IS QUEUED. The Arduino is deaf during a build and a second command
  sits in a 64-byte buffer to arrive late and out of context. One command at a
  time, always, no exceptions, even though a program exists.
- NO CANCEL AND NO RETRY CONTROL, ANYWHERE. The firmware cannot honour a cancel,
  and an aborted session has no software recovery — a human inspects the rig and
  restarts the service. Any button implying otherwise is a lie about the machine.
- Every guard stays server-side. The runner is a client of the existing routes
  and adds no new authority. Do not add a batch endpoint.

VERIFICATION
Against `python -m web --mock`: a full model builds end to end; every failure
path behaves; the dry run completes with no serial traffic at all.

DONE WHEN
A complete model builds end to end against the mock, and each of rejection,
abort and command-mismatch does the right thing.

REPORT BACK
The exact request sequence per block, how you verified no command can be queued,
and the measured mean cycle time from the mock (it feeds the ETA estimate).
```

---

## M8 — Wow pass

```text
Read `plans/plan-4-3d-build-studio.md` in full and carefully — §8.5, §8.6, §9.4,
§11 and §13 are this milestone. Also read `docs/DESIGN.md` throughout. M0–M7 are
complete: the Studio designs, validates, compiles, saves and runs models, and
the twin mirrors real builds.

HOW TO WORK — TEST FIRST, NOT TESTS EVENTUALLY
This plan is test-driven; read Plan 4 §0 before anything else and follow it.
For every deliverable below: write the test, run it, watch it fail for the right
reason, then implement until it passes, then clean up. Test and implementation
are committed together, test first in the diff. If you are writing
implementation with no failing test pointing at it, stop and write the test.
A test that fails because the module does not exist yet has failed for the right
reason; one that fails on a typo in the test has not — read the failure before
writing the fix.
`cd web && npm test` must be green when you finish, INCLUDING the console's
existing `step7`, `step9`, `step10` and `lib/workspace.test.tsx`. Nothing in
Plan 4 may regress Plan 3.
Most of this milestone is look and feel, which §0.4 says not to unit-test. The
exceptions are real and must still be written test-first: the shift-clipping
predicate (which cells drop out at a given shift — extend M0's `clippedCells()`
tests rather than writing new maths), the timeline's legal-reorder predicate,
and the cell → pixel projection for the video overlay, which is fixture-tested
against `web/src/lib/workspace.ts` exactly as M0 was tested against Python.
Everything else here you judge by eye.

TASK
The features that turn a working tool into a demo people remember. Plan 4 §11
ranks them by impact per hour — work that order, and stop when the demo script
in §13 runs start to finish without a stumble.

DELIVERABLES, IN PRIORITY ORDER

1. LIVE GRID SHIFT WITH CLIPPING (§8.5). Drag the shift gizmo and the lattice
   translates in true millimetres, with a mono readout. Cells whose block edge
   exceeds `max_edge_overhang_*_cm` turn amber and strike through, LIVE — this
   reproduces the firmware's own clipping (`gridColsNow()` reports the reachable
   grid while the requested one is kept) and watching the far column drop out as
   you drag is the most convincing single moment in the whole app. Snap 0.1 cm,
   0.5 cm with Shift, free with Alt. Shift is PER MODE.
   Applying a shift to the rig, as opposed to previewing it, is a separate
   explicit confirmed action, with copy explaining that it moves every placement
   including the `[0,0]` reference but NEVER the pick-up, and that it is a
   registration shift, not calibration (`error_offset_*` is the separate
   calibration knob — never let one masquerade as the other).

2. TIMELINE SCRUB AND REPLAY (§8.6). Block chips in compiled order, mode-latch
   dividers as full-height amber bars labelled R / RR, drag to reorder with
   illegal drops refused and the blocking constraint named, and a playhead that
   shows the structure as of that step with future blocks as ghosts. This one
   component is the build preview, the review tool and the replay control.

3. PLAN PROJECTION ONTO THE VIDEO (§9.4). `WorkspaceMap.target_polygon()` maps
   any cell to its pixel polygon and is ALREADY ported and fixture-tested in
   `web/src/lib/workspace.ts` — this is why the feature is affordable. Draw the
   planned model on the live stream: the next block's footprint glowing on the
   surface, the rest faint behind it. Fake level with a parallax offset toward
   the image centre proportional to height; a pinhole camera 50 cm up makes that
   predictable. Document the approximation honestly in the code.
   NOTE: you do NOT need a real camera. `MockCamera` serves a genuine MJPEG
   stream of a synthetic workspace through the same `/api/stream.mjpg`, so build
   and test this entirely against `python -m web --mock`.

4. Sync view polish, ambient audio (a soft tick per placed block, a chord on
   completion — mutable, remembered), and the `?` shortcut overlay.

5. Instruction-sheet export — a printable step-by-step of the model rendered
   from the timeline.

6. Rehearse the demo script in §13 end to end and fix whatever stumbles.

CONSTRAINTS
- `docs/DESIGN.md` §8 still applies: nothing loops on an idle screen, no
  decorative use of the reserved state colours, no motion that implies the rig
  is moving when it is not. Honour `prefers-reduced-motion` everywhere.
- Audio is off by default until the operator enables it, and the choice is
  remembered.
- No new backend authority. Everything here is client-side or reads existing
  state.

DONE WHEN
The §13 demo script runs start to finish, on mock hardware, without a stumble.

REPORT BACK
Which items you completed and which you left, a frank assessment of which ones
actually landed versus which looked better on paper, and the open questions from
Plan 4 §16 that this milestone's work has now answered.
```

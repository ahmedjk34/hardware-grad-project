# The 3D Build Studio — living record

**What this document is.** The single, current, complete description of the
Studio as it actually exists in the repository. Plan 4
([plans/plan-4-3d-build-studio.md](../plans/plan-4-3d-build-studio.md)) says what
the Studio is *for* and is deliberately not rewritten as the work lands; the
milestone prompts file records what each milestone was *asked* for. **This file
records what is true right now** — every module, every exported function, every
decision that a future reader would otherwise have to reverse-engineer from the
code.

**How to keep it.** Update it in the same commit as the change it describes.
Anything that would surprise someone reading the code cold belongs here: a
decision that contradicts the plan, a constant with no home in `rig.json`, a
library that had to be used a particular way. §11 is the changelog; add to it
every time. If this file and the code disagree, the code is right and this file
is a bug.

Related: [DESIGN.md](DESIGN.md) (the visual language, shared with the console),
[AGENTS.md](../AGENTS.md) §3a/§3b (the machine's grid geometry, authoritative),
[plan-3-web-operator-console.md](../plans/plan-3-web-operator-console.md) (the
console this attaches to).

---

## 1. Status at a glance

| Milestone | State | What it delivered |
| --- | --- | --- |
| M0 — Coordinates and fixtures | ✅ delivered | `coords.ts`, `geometry.ts`, fixtures dumped from Python |
| M1 — Static viewport | ✅ delivered | `view.ts`, `lattice.ts`, `scene/`, the `#/studio` route |
| M2 — Placement | ✅ delivered | ghost, top picking, click/alt/shift-drag, undo/redo, level x-ray |
| M3 — Validation | ✅ delivered | one pure validator, live settings, diagnostics, ghost reasons and block markers |
| M4 — The compiler | ✅ delivered | `compile.ts` (support graph, Kahn order, latch state machine, deterministic), `panels/ProgramView.tsx`, per-block/per-latch estimate settings |
| M5 — Library | not started | model document metadata, `library.ts`, thumbnails |
| M6 — The twin | not started | read-only scene beside the camera |
| M7 — The runner | not started | executing a compiled program through `/api/build` |
| M8 — Wow pass | not started | shift gizmo, x-ray by level, cross-mode bridging |

**Test suite.** `cd web && npm test` — **214 tests across 23 files**, all green.

| file | tests | what it holds |
| --- | --- | --- |
| `studio/coords.test.ts` | 41 | the port of `python/rig/grid.py`, against dumped fixtures at 1e-6 |
| `studio/geometry.test.ts` | 12 | AABBs, overlap, the firmware's clipping |
| `studio/lattice.test.ts` | 14 | which cells are drawn, and in what state |
| `studio/view.test.ts` | 27 | envelope/block framing, the four snaps, the orbit floor, the opening move |
| `studio/validate.test.ts` | 27 | every §6.4 rule, modified configs, bridge scan, centroid and build order |
| `studio/compile.test.ts` | 25 | the four steps in isolation, one red-when-removed test per ordering constraint, the latch state machine, twenty-compile determinism |
| `studio/settings.test.ts` | 4 | conservative defaults, timing-field backfill, guarded versioned persistence |
| `studio/panels/ProgramView.test.tsx` | 4 | serial-log rendering, latch dividers, line selection, clipboard copy |
| `studio/model.test.ts` | 7 | immutable mutations; geometry/order separation |
| `studio/history.test.ts` | 4 | generic undo/redo, branching and the 100-entry cap |
| `studio/pick.test.ts` | 6 | cell/level resolution, gaps, hit priority and straight runs |
| `studio/placement.test.ts` | 4 | M2's feeder, grid and occupied-slot gate |
| `studio/interaction.test.ts` | 5 | click slop, hover deduplication and keyboard interpretation |
| `studio/motion.test.ts` | 4 | fade/drop curves, reduced motion and row sequencing |
| `studio/panels/LevelScrubber.test.tsx` | 2 | accessible level hold/release controls |
| `studio/panels/Diagnostics.test.tsx` | 2 | severity grouping, selection, hover and fixes |
| `studio/panels/Settings.test.tsx` | 2 | visible estimates, copy and immediate edits |
| `routes/preload.test.ts` | 1 | one cached route import shared by every preload trigger |
| `redesign.test.tsx` | 10 | Plan 3 console |
| `step7` / `step9` / `step10` | 5 / 4 / 1 | Plan 3 console guards — must never regress |
| `lib/workspace.test.tsx` | 3 | the homography port |

**Bundle**, from `npm run build` at the end of M4:

| chunk | size | notes |
| --- | --- | --- |
| console entry `index-*.js` | 218.73 kB (68.89 kB gzip) | contains **no** three.js; includes the tiny preload trigger. Unchanged by M4 — the compiler is pure and rides only the lazy chunk |
| `Studio-*.js` | 975.72 kB (263.21 kB gzip) | lazy; preloaded on idle or navigation intent. +6.5 kB for `compile.ts` and `ProgramView.tsx` |
| `index-*.css` | 29.59 kB (6.52 kB gzip) | console and Studio share one stylesheet |

Before the Studio existed the console entry was 216.92 kB (68.24 kB gzip), so
the console's first paint pays **1.81 kB** for the lazy route, hash router and
preload trigger. Three.js remains absent from first paint. Check the split with:

```sh
cd web && npm run build
grep -c WebGLRenderer dist/assets/index-*.js    # must be 0
```

**Dependencies**, pinned exact, installed locally, never a CDN (DESIGN.md §3.2 —
the Pi serves this over LAN with no guaranteed internet):

```
three@0.185.1  @react-three/fiber@9.7.0  @react-three/drei@10.7.8
@types/three@0.185.0 (dev)
```

---

## 2. Running it

```sh
cd web && npm run dev      # then open http://localhost:5173/#/studio
cd web && npm test         # the gate; must be green at every milestone
cd web && npm run build    # tsc -b, then vite build
```

The console is at `/`; its right-hand rail carries a link to the Studio. The dev
server proxies `/api` to `127.0.0.1:8000` and `server.fs.allow: [".."]` lets the
browser import `config/rig.json` directly, so there is no second copy of the
machine's geometry anywhere.

---

## 3. The layering rule

This is the whole architecture in one sentence: **the parts that must be correct
are the parts that need no browser and no GPU.**

```
studio/coords.ts geometry.ts lattice.ts view.ts model.ts history.ts pick.ts placement.ts interaction.ts motion.ts validate.ts settings.ts
                                                        ← pure. Every rule. Tested.
studio/scene/*.tsx panels/*.tsx routes/*.tsx             ← draws. No rules.
```

A component that decides something about the machine — which cells exist, where
a block sits, whether a placement is legal, how far back the camera must stand —
has taken a rule out of the test suite. Move it down and test it there. Plan 4
§0.1 states this; M1 followed it by inventing `lattice.ts` and `view.ts` rather
than putting either decision inside `Lattice.tsx` or `Viewport.tsx`.

```
web/src/
  studio/
    coords.ts            cell ⇄ machine ⇄ scene — the only place axes are handled
    geometry.ts          AABBs, overlap, the firmware's grid clipping
    lattice.ts           WHICH cells are drawn and what each one is
    view.ts              the envelope box, the snap poses, the orbit floor
    model.ts             immutable cell-space blocks + separate author order
    history.ts           generic bounded undo/redo
    pick.ts              raycast point → active-mode cell and stack level
    placement.ts         compatibility wrapper around the one M3 validator
    interaction.ts       click slop and keyboard gesture interpretation
    motion.ts            row sequencing + fade/downward arrival curves
    validate.ts          the one §6.4 rule table; model and ghost entry points
    compile.ts           model → ordered B/R/RR program; support graph, Kahn order, latch state machine
    settings.ts          versioned physical estimates + the two estimate-timing constants, guarded localStorage I/O
    coords.fixtures.json 17 cases / 980 cells dumped from Python
    scene/
      theme.ts           DESIGN.md tokens read off the document, as three colours
      Viewport.tsx       <Canvas>, camera rig, lights, contact shadows
      Envelope.tsx       the travel cap + its centimetre rulers
      Lattice.tsx        the active grid, the gaps, the hatched feeder
      Blocks.tsx         rounded instanced blocks, split by mode and x-ray state
      Ghost.tsx          exact legal/illegal hover preview
      DiagnosticMarkers.tsx static severity rings on offending top faces
      surface.ts         cell-space payload shared by raycast surfaces
    panels/
      LevelScrubber.tsx  explicit click/drag level hold
      Diagnostics.tsx    grouped output + select/frame/fix dispatch
      Settings.tsx       the five visible physical estimates
      ProgramView.tsx    the compiled program as a serial log, latches set apart, copy-to-clipboard
  routes/
    Root.tsx             hash routing + the lazy Studio import
    preload.ts           generic one-promise import cache
    studio-loader.ts     shared idle/intent/navigation Studio import
    Studio.tsx           the Studio route (chrome + viewport)
  App.tsx                the operator console (Plan 3), still the console route
```

---

## 4. The three coordinate spaces

| Space | Units | Origin | Used by |
| --- | --- | --- | --- |
| **Cell** | integers `(mode, col, row, level)` | feeder at `[0,0]` | the model file, the compiler, the `B` command |
| **Machine** | **millimetres**, X right, Y away from Y-home, Z up | home corner, ground | collision, support, envelope checks, readouts |
| **Scene** | three.js units, 1 unit = 10 mm, Y up | machine home corner | rendering only |

The config and the lattice formula speak **centimetres**, because that is what
the machine's own numbers are. `coords.ts` is the only module that converts, and
everything it hands out is millimetres or scene units.

```
pitch     = block + gap
centre(i) = trim + error_offset + shift + i * pitch
```

Centre-anchored, 0-based, no leading gap, no trailing gap, no centring. Cell 0's
centre sits exactly on the home corner and its block hangs half a block back past
the switches. `[0,0]` is the feeder in **both** modes and is never built on.

### 4.1 The one correction to Plan 4 §4

§4 sketches the machine→scene conversion as a `<group>` transform
(`rotation.x = -π/2`, `scale 0.1`). **It is not built that way.**
`coords.machineToScene()` performs the conversion in the pure layer, where it is
fixture-tested, and hands `scene/` coordinates that are already in scene space —
`(x, y, z)ₘ → (x, z, −y) / 10`. A group transform on top of that would apply the
rotation twice. The rule §4 actually cares about is unchanged and absolute:
**the axes are handled in exactly one place.** That place is `coords.ts`, not a
group. `SCENE_ROTATION_X` is still exported for anyone who needs the number.

---

## 5. The pure layer, module by module

### 5.1 `studio/coords.ts` — the port of `python/rig/grid.py`

Held to Python at 1e-6 by `coords.test.ts` against `coords.fixtures.json`, dumped
by `python/tools/dump_grid_fixtures.py` (17 cases, 980 cells: both modes, shipped
and clipped and refused shifts, plus trims and error offsets on a synthetic
envelope). **When the two disagree, Python is right.**

| export | does |
| --- | --- |
| `setRigConfig` / `rigConfig` / `activeMode` / `modeGeometry` | swap in and read the live config; a test, a preview, or a model's own snapshot |
| `latticeOf(mode, shift?)` | one mode's resolved lattice in cm: counts, block extents, pitches, `origin = trim + error_offset + shift` |
| `cellToMachine(...)` / `cellToScene(...)` | cell → machine mm / complete scene position. Z is the block **centre** |
| `levelBaseZ` / `levelCentreZ` | ground → base / centre of a level |
| `blockExtents(mode)` / `blockSceneSize(mode)` | machine / scene-axis extents. **Never a component swap** |
| `cellCount(mode)` | the requested grid |
| `reachableCells(mode, shift?)` | what the live shift actually leaves reachable — the firmware's `gridColsNow()`/`gridRowsNow()` as counts |
| `axisFits(mode, axis, index, shift?)` | the firmware's `gridGeometryFits()`, kept identical on purpose |
| `latticeBounds(mode, shift?, counts?)` | block edges and first/last centres in mm; **reachable by default**, `"requested"` for the grid the operator asked for |
| `isFeeder` / `feederCentre` | `[0,0]`; the pick-up is a plain home to raw `[0,0]` — no shift, no tool offset |
| `machineToScene` / `sceneToMachine` | the whole of the axis juggling |

Constants: `MM_PER_CM`, `BLOCK_HEIGHT_CM = 1.5`, `BLOCK_HEIGHT_MM`,
`SCENE_UNITS_PER_MM = 0.1`, `SCENE_ROTATION_X`.

**`BLOCK_HEIGHT_CM` has no `rig.json` partner.** It is the firmware's
`BLOCK_HEIGHT_CM` from `arduino/build_test_v1`, stated once here and once in
`python/tools/dump_grid_fixtures.py`. See also `ENVELOPE_Z_CM` in §5.4.

### 5.2 `studio/geometry.ts` — machine-space predicates

`aabbOf(block)`, `topFaceZ`, `intersects` (touching faces are **not** a
collision — a stack is legal), `footprintOverlapArea`, `footprintArea`,
`latticeFootprint`, and:

`clippedCells(mode, shift?)` → `{ requested, reachable, cells, refused }` —
which cells a shift pushes past the travel cap, exactly as the firmware reports
it: the **requested** grid is kept, the **reachable** grid is clipped, clearing
the shift restores the request with no re-`S`, and `refused: true` is the shift
`applyGridShift()` would reject outright. Judged against each mode's own
`max_edge_overhang_*_cm`, because a centre-only check happily accepts a grid
whose far block hangs off the machine.

### 5.3 `studio/lattice.ts` — which cells get drawn

```ts
latticeCells(mode, shift?) → LatticeCell[]
  { col, row, kind: "feeder" | "cell" | "clipped", centre: Vec3, sizeX, sizeZ }
rulerTicks(lengthCm, stepCm = 1, majorEvery = 5) → { cm, major, at }[]
```

Everything is in **scene units**, converted only by `machineToScene`, so
`Lattice.tsx` draws the list and computes nothing. The **requested** grid always
comes back whole: a shift clips what the machine can reach without changing what
was asked for, and the Studio draws clipped cells struck through rather than
deleting them. **The feeder outranks clipping** — `[0,0]` reads as the feeder in
every state, including one a shift has put out of reach, because it is never
built on either way.

### 5.4 `studio/view.ts` — where the camera stands

Plan 4 §0.4 rules out testing camera angles by rendering them. The arithmetic
that *produces* a snap is not a rendering question, so it lives here and is
tested headlessly.

| export | does |
| --- | --- |
| `envelopeBoxScene()` | the travel cap as a scene-space box: X and Y from `workspace` in `rig.json`, Z from `ENVELOPE_Z_CM` |
| `boxCentre(box)` | what every snap aims at |
| `frameDistance(halfW, halfH, fov, aspect, margin)` | how far back a perspective camera must stand for a rectangle to fit. On a portrait phone the *horizontal* half-extent is usually what binds |
| `viewPose(view, aspect, box?)` | `{ position, target, up }` for `top` / `front` / `side` / `iso` |
| `screenAxes(pose)` | the pose's screen basis, built exactly as three.js builds a camera's |
| `clampAboveGround(position, minY?)` | the orbit constraint as arithmetic |
| `tweenMs(reducedMotion)` | `0` under `prefers-reduced-motion`, else `TWEEN_MS` |
| `cameraTransitionMs(initialized, explicit, reduced)` | the one place that decides whether a camera move animates at all |
| `introPose(final, t)` | the opening move as a function of progress `t ∈ [0,1]` |
| `introMs(reducedMotion)` | `0` under `prefers-reduced-motion`, else `INTRO_MS` |
| `easeInOut(t)` | cubic ease-in-out; no jump at either end, no jerk in the middle |

Constants: `ENVELOPE_Z_CM = 26.5`, `FOV_DEG = 35`, `FRAME_MARGIN = 1.12`,
`MIN_CAMERA_Y = 0.2`, `MAX_POLAR_ANGLE = π/2`, `TWEEN_MS = 260`,
`INTRO_MS = 880`, `INTRO_START_DISTANCE_RATIO = 0.32`,
`INTRO_SWEEP_RAD = 0.85`, `INTRO_START_ELEVATION_RATIO = 0.45`, `VIEWS`.

#### The opening move

`introPose()` works in the final pose's own orbit frame: it decomposes
`position − target` into a distance and two angles, then interpolates distance
`0.32 → 1`, elevation `0.45 → 1` and azimuth `final − 0.85 rad → final`, all on
one `easeInOut` curve. The target never moves, so the machine stays centred
while the camera pulls back and swings round it — the reveal is that this is a
3D object, not a picture of one.

`t >= 1` returns the `final` object *itself* rather than recomputing it, so the
intro cannot leave the camera a rounding error away from the pose the snap
buttons use, and the envelope is exactly framed the moment it lands. The
pull-back is asserted monotonic in `view.test.ts`: an intro that zoomed out and
back in would fail there rather than in somebody's eyes.

**`ENVELOPE_Z_CM` is the firmware's `Z_TRAVEL_CM` (26.5 cm)** and has no
`rig.json` partner, exactly as with `BLOCK_HEIGHT_CM`. It is the cage's height —
the machine's travel — *not* a build ceiling; the practical level ceiling is an
operator setting.

**Framing.** `top`, `front` and `side` are framed to the box face they look at,
plus that view's own depth half-extent so the near corners cannot fall outside
the frustum. `iso` is off-axis, so it frames the bounding **sphere** instead:
that holds at every orbit angle and cannot clip a corner.

**Top view carries a requirement beyond taste.** Its up vector is `(0, 0, −1)`,
which puts machine **+X to the right and +Y up the screen**. M6 lays the twin
against the overhead camera's own image, so this is asserted in `view.test.ts`
rather than left to whoever next edits the file.

**The orbit floor is enforced twice**: `maxPolarAngle` on the drei controls stops
an orbit going under the horizon, and `clampAboveGround` runs per frame in
`Viewport.tsx` because a *pan* can still drag the camera below the floor.

### 5.5 `studio/model.ts` and `studio/history.ts` — editing without coupling

`Model` is `{ blocks, order }`. A block is `{ id, mode, col, row, level,
colour }`; its own mode is permanent geometry, so changing the active lattice
cannot move it. `applyEdit()` is the only mutation boundary: `place`,
`placeRun`, `remove`, `move`, `recolour`, `reorder`. Moving preserves both list
and author order; reordering preserves the geometry list byte-for-byte.

`history.ts` is generic and knows nothing about blocks. It stores complete
immutable values, clears redo on a new branch and retains 100 undo entries by
default. A shift-drag calls `applyEdit(placeRun)` once and therefore occupies
one history entry, regardless of its length.

### 5.6 `studio/pick.ts`, `placement.ts` and `interaction.ts`

`pick.ts` inverts the centre-anchored lattice through `coords.ts`. A ray point
must fall inside the actual block footprint; the 1.6 cm gap returns `null`, not
the nearest cell. Ground hits resolve to level 0. Block tops take their level
from `geometry.topFaceZ()` matched against `coords.levelBaseZ()`, but resolve X/Y
in the **currently active mode**. Nearest hit wins and a top wins an exact tie.
Shift-drag runs are constrained to the dominant axis.

`placement.ts` is intentionally separate from `model.ts`: the model mutates;
the placement gate answers whether a proposed edit is locally legal. M2 checks
only `[0,0]`, the active mode's requested bounds and an occupied same-mode slot.
Support, collision, edge and shift validation remain M3.

`interaction.ts` owns the 4 px click slop and keyboard mapping. Undo is
Ctrl/Cmd-Z; redo is Ctrl/Cmd-Shift-Z or Ctrl/Cmd-Y. Inputs and editable elements
are ignored. Escape releases a held level, digits 0–9 hold one, and `M` toggles
the authoring lattice.

### 5.7 `studio/motion.ts` — one arrival, two explanations

`arrivalFrame()` combines two independent cues: opacity explains the block
spawning into the model, while a downward offset explains the machine placing
it. The fade is a 130 ms smoothstep. The 8 mm drop is a 220 ms quintic ease-out,
long enough to read cleanly without making the editor wait. Reduced motion
returns the final frame immediately.

`rowArrivalDelays()` handles multi-cell gestures. Blocks on the same row start
together; each distinct row in gesture order starts 34 ms after the previous
one. A single placement always has delay zero, regardless of its machine row.
The maths is pure and tested; `Blocks.tsx` only applies its result.

### 5.8 `studio/compile.ts` — model to command program

The intellectual core of Plan 4. `compile(model, { mode, settings, shifts?,
rigSnapshot? })` returns `{ valid, program, stats, diagnostics }` exactly as
Plan 4 §6.1. `mode` is the starting board mode — the live `state.mode` when
there is one, `vertical` otherwise, because a board reset returns to vertical.

**Why it is not a flat list.** `B <col> <row> <level>` carries no orientation;
how a block is laid comes from a mode latch (`R` vertical, `RR` horizontal)
which homes X and Y, is refused mid-air, and is refused if the board is already
in that mode. A mixed-orientation model is therefore a partial order sorted into
same-mode runs, each run costing a homing move.

Four named steps, each its own exported function so a test points at one claim:

| step | does |
| --- | --- |
| `supportGraph(model, shifts?)` | `id → the ids it rests on`, from machine-space footprint overlap at the matching base/top Z. Cross-mode: a horizontal span depends on every vertical stack under it. Built by iterating `model.blocks`, never a `Set`'s order |
| `orderBlocks(model, graph, startingMode, terms?)` | Kahn's algorithm; the ready array is re-sorted on every pop by a comparator chain, `O(n² log n)` on a list that never exceeds a few hundred and obviously deterministic |
| `emitOps(ordered, startingMode)` | the latch state machine — one variable, the board mode. Emits a `mode` op **only on an actual change** and annotates it `{ cost: "homes X and Y" }`. Kept separate from ordering: a different kind of correctness |
| `summarise(ops, settings)` | `{ blocks, latches, modeSwitches, levels, estimateSeconds }`. `modeSwitches` is an alias of `latches` for the §6.1 shape |

**The comparator, in priority order** — each an exported term composed by
`chain()`, listed in `ORDER_TERMS`:

    byLevel        bottom-up; a block can never precede its support
    byCurrentMode  prefer the latched mode. STATEFUL — recomputed each pop
                   against the mode the emitter would be in by then
    byAuthorIndex  the author's order, wherever it is still legal
    byCell         column, then row
    byId           the total order, so ties cannot exist

`orderBlocks` and `comparatorFor` both take an optional `terms` list. Removing a
constraint is then deleting one term (or passing `new Map()` for the support
graph), and `compile.test.ts` has one test per constraint that goes red when it
is removed. Confirmed by deleting each in turn:

| removed | test that fails |
| --- | --- |
| support graph (`new Map()`) | `supportGraph` edge tests + `CONSTRAINT 1, support before supported` |
| `byLevel` | `CONSTRAINT 2, bottom-up` (and, cascading, 3) |
| `byCurrentMode` | `CONSTRAINT 3 + the stateful comparator` |
| `byAuthorIndex` | `CONSTRAINT 4, author order wins where legal` |
| `byCell` | `CONSTRAINT 5, deterministic tie-break` |
| `byId` | `CONSTRAINT 5` (byId sub-assertion) + `ORDER_TERMS` |

**Serial text is built in one place**, `commandText(op)` → `"B 3 2 1" | "R" |
"RR"`. `ProgramView` and the future M7 runner both consume `op.text`; a second
formatter is how `B 3 2 1 ccw` reaches a firmware that reads a fourth word as a
parse error.

**Invalid models compile to nothing.** `compile` runs M3's `validateModel`
itself — it never re-implements a rule. Any `error` diagnostic → `{ valid:
false, program: [], stats: all-zero, diagnostics }`. A half-program is the
single most dangerous artefact this codebase could produce. Warnings do not
block.

**Determinism** is a requirement, not a nicety: `compile.test.ts` compiles the
same model twenty times and asserts byte-identical output, and separately that
the program depends only on `model.order`, not the `blocks` array order. Every
collection is built from model order; every comparator chain ends in `byId`.
(The `diagnostics` array still reflects `model.blocks` order, which is M3's
behaviour, so the byte-identical program/stats check excludes it.)

**The estimate** is `blocks × blockCycleSeconds + latches × latchHomingSeconds`,
both named constants in `settings.ts` (`BLOCK_CYCLE_SECONDS = 40` from
`rig/link.py`'s "~40 s", `LATCH_HOMING_SECONDS = 16`) and both editable in the
`ESTIMATES — NOT MEASUREMENTS` settings block. `estimateLabel(stats)` renders
`4 blocks · 1 latch · ~2:56` — the `~` is always shown. M7 measures the real
mean against `--mock`; when it does, the constant moves and this changelog
records that it came from a measurement.

**Report-back (from the milestone prompt).**
- *Worst case.* The heuristic re-homes once per mode transition per level band.
  A model that alternates orientation on every level — a vertical block, then a
  horizontal block resting on it, then a vertical block resting on that, all the
  way up — forces one latch per block after the first: `n` blocks, `n − 1`
  latches. That is genuinely minimal for that structure: bottom-up ordering is
  forced by support, and within each single-block level band there is only one
  block to place, so no grouping can remove a transition.
- *A cheaper ordering.* None exists for the true alternating-stack case above.
  For the common case — several blocks per level band, mixed orientation — the
  `byCurrentMode` grouping already achieves the minimum of one latch per
  orientation change per band, and re-keying on the live mode means a band that
  ends horizontal is entered horizontal by the next.
- *Valid but uncompilable.* None found. Every model the M3 validator accepts
  (no cycle is possible — support always points strictly downward in Z) produces
  a total order and a program.

---

## 6. The scene layer

Nothing in `scene/` decides anything. If you are about to write arithmetic here,
it belongs in §5.

### 6.1 `scene/Viewport.tsx`

The `<Canvas>`, the camera rig, the lights, the contact shadows and the orbit
controls. It receives the immutable model, hover target/status, held level and
cell-space surface callbacks in addition to `{ mode, shift?, view, nonce? }`.
`nonce` is bumped by the caller to re-snap to the view already selected.

- **Lighting**: one key directional, one dim fill and a faint hemisphere. The
  continuously-updated 1024² directional shadow map was removed in the
  performance pass; the grounding cue is a 512² `<ContactShadows frames={1}>`
  keyed by block geometry. A placement/removal regenerates it once while an
  idle stage still draws nothing.
- **No ground plane.** Plan 4 §8.2 rules out an infinite checkerboard as visual
  noise. The lit-from-above read comes from a CSS radial vignette behind the
  canvas (`--vignette`), which costs nothing to render.
- **`frameloop="demand"`.** DESIGN.md §3.4 forbids motion on an idle screen, and
  an idle Studio issues no draw calls at all. The intro and the view tween call
  `invalidate()` once per frame while they run and then stop; nothing in the
  camera path holds the loop open afterwards. `prefers-reduced-motion` makes
  `introMs()` and `tweenMs()` zero, which snaps to the destination instead of
  animating to it.
- **The intro runs once per mount**, guarded by a `phase` **ref**
  (`"pending" → "intro" → "live"`), never by React state. The camera effect
  reruns on every size change, so without that guard a settling
  `ResizeObserver`, a browser-zoom change or an ordinary rerender each restarted
  the pull-back — which is what the "zooms in, then zooms out again" bug was. A
  resize *during* the intro updates the destination pose in place and leaves the
  clock alone, so the move stays continuous and still lands correctly framed.
  Touching the orbit controls lands the intro immediately; the operator wins.
- **Pixel cost is capped** at DPR 1.5 and the WebGL context requests the
  high-performance adapter. This keeps fill rate bounded on the Pi display and
  high-DPI phones without making ordinary desktop output soft.
- **Camera work happens in refs inside `useFrame`**, never through React state:
  no scene rerender, no geometry, material, light or mesh is rebuilt while the
  camera moves, and only position, orbit target and up are touched.
- **The tween** interpolates position, orbit target and the camera's up vector
  with a cubic ease-out. Up is interpolated because `top` uses a different one;
  the path between `(0,1,0)` and `(0,0,−1)` never passes through zero length.

### 6.2 `scene/Envelope.tsx`

The travel cap as a thin `--line-strong` wireframe box, with centimetre rulers
along two edges — the X edge at machine Y = 0 and the Y edge at machine X = 0,
each tick major every 5 cm, majors labelled. This is the machine's real limit and
it is always visible. It is never inferred from the lattice: it comes from
`workspace` in `rig.json` by way of `envelopeBoxScene()`.

### 6.3 `scene/Lattice.tsx`

Every addressable cell at its true footprint with the true gaps: `--signal` fills
at 30 % with outlines, the feeder hatched and labelled `FEED`, and cells the live
shift has clipped in `--motion`, crossed through. Plain fills and clipped fills
are one instanced draw each instead of one mesh/draw per cell. Cell outlines and
crosses remain one merged line geometry each.

Which cells those are, and which is which, is `latticeCells()` — see §5.3.

### 6.4 `scene/theme.ts`

DESIGN.md §3.1 says nothing in a component carries a raw colour value, and that
rule does not stop at the edge of a WebGL canvas. `cssToken(name)` reads a custom
property off the document (memoised), `tokenColor(name)` returns a cached
`THREE.Color`, and `hatchTexture(token)` draws the feeder's stripes into a
canvas at runtime rather than shipping an asset. **An unreadable token stays
three.js's own default** rather than falling back to a literal nobody designed.

### 6.5 Text in the scene

**drei's `<Text>` is not used and must not be.** It is troika, which fetches a
default font from a CDN — forbidden by DESIGN.md §3.2, and it would fail silently
on a Pi with no internet. Scene labels (ruler numbers, `FEED`) are drei `<Html>`,
so they are real DOM and use the real type tokens (`.studio-tick`, `.studio-tag`
in `style.css`).

### 6.6 `scene/Blocks.tsx`, `Ghost.tsx` and placement surfaces

Placed geometry is rounded by 0.6 mm and instanced with 512 slots of headroom.
There is a separate physical geometry for each mode; the held-level x-ray splits
each into solid and 15%-opacity batches. Instance colour comes from the five
original `--block-*` tokens plus `--block-white`; new blocks default to white.
A new block fades over 130 ms while settling from +8 mm over 220 ms. Distinct
rows in one run start 34 ms apart. Per-instance opacity keeps the whole gesture
in one arriving draw, while the solid/x-ray split remains ordinary materials.
Arrival state, matrices and opacity live in refs; `useFrame` exits before doing
any matrix work when no arrival exists, and `invalidate()` runs only while one
is active. Reduced motion places immediately.

Instanced batches mount empty, so the first colour attribute appears only when a
block is placed. `Blocks.tsx` explicitly recompiles that material once when the
attribute is created; without it, Three.js retains its empty-batch program and
renders the missing vertex colour black. White receives a small token-derived
emissive lift so it remains visibly white against the dark stage.

`Ghost.tsx` uses the active mode's same rounded dimensions at 35% `--signal`, or
30% `--danger` with a solid edge and one reason label. It has no raycast of its
own and disappears when the surface target is null.

After a commit, the old hover target is cleared. This prevents an occupied-cell
danger ghost from masking the newly placed white block while the pointer is
stationary; the next pointer movement resolves the real top face normally.

The lattice planes and block instances translate R3F hits through `pick.ts` and
emit `SurfacePointer`; they never edit the model. Block tops stop propagation,
so the nearest top wins over the lattice beneath it. X/Y resolves in the active
mode even when the hit block belongs to the other mode. Alt-pointer events may
remove from any visible block face; ordinary placement accepts only top faces.

### 6.7 The level scrubber

The left rail exposes levels 0–17 as real DOM buttons and supports pointer drag.
A held level overrides ground/top-derived height, is repeated in the header, and
fades every block above it to 15%. Escape or the rail's explicit `ESC` control
releases it. The current 17-level ceiling is the theoretical travel ceiling;
M3 promotes the practical operator limit to a visible setting.

### 6.8 `panels/ProgramView.tsx`

The compiled program drawn as a serial log — the register this console speaks
in. Mono throughout: line numbers `--text-faint`, command text `--text`, block
id `--text-dim` right-aligned. Line numbers count build ops only, so they run
continuously past a latch. A latch is a full-width row — an amber `--motion`
chip (`R` / `RR`) on the left, a 1px `--motion` rule, `homes X and Y` in
`--text-dim` on the right — full-width because the cost is a whole-machine
event. Selecting a line calls the same `onSelect` the diagnostics panel uses, so
it selects and frames the block in the viewport. A copy control writes every
`op.text`, one per line, to the clipboard for pasting into a serial monitor. The
component only draws; ordering, latches and the estimate are all `compile.ts`.
`Studio.tsx` compiles in a `useMemo` over `{ model, mode, settings, rigSnapshot }`
and renders it between the diagnostics and settings panels.

---

## 7. Routing and code-splitting

`routes/Root.tsx` is the whole of the routing: the console at `#/`, the Studio at
`#/studio`, with `React.lazy` around the Studio import so three.js lands in its
own chunk. **Hash routing, deliberately** — it needs no server rewrite, which
matters because the Pi serves this as static files and the PWA offline shell has
to keep working.

The import is cached by `createPreloader()`. `App.tsx` starts it when the browser
is idle and immediately on pointer-enter, focus or pointer-down over the Studio
link; `React.lazy` consumes the same promise on navigation. This moves download,
parse and module initialization away from the click without pulling Three.js
back into the console's initial bundle. Touch, keyboard and mouse intent all
take the same path.

`App.tsx` is still the console; Plan 4 §7's `routes/Console.tsx` has not been
split out, because moving it would churn the Plan 3 tests for no benefit until
the twin (M6) needs it.

The console's rail links to the Studio. `main.tsx` renders `<Root/>`; the Plan 3
tests import `<App/>` directly and are untouched by the routing.

---

## 8. The visual language inside a canvas

The Studio must feel like the same instrument as the console, not a second
application, so it takes the console's tokens unchanged (DESIGN.md §3). In
practice:

- Colours come from `theme.ts` (in the scene) or CSS custom properties (in the
  chrome). No hex anywhere in `studio/` or `routes/`.
- `--signal` is interaction, never a machine state. `--motion` amber means
  *degraded but recoverable* — which is exactly what a clipped cell is. `--danger`
  red is reserved for *stop, a human is required*; M2 uses it only for the
  invalid ghost and its reason label.
- Type is the console's five sizes; every numeric readout is `tabular-nums`.
- Motion: `--fast` / `--base` for chrome, `TWEEN_MS` for the camera, nothing on
  an idle screen, and `prefers-reduced-motion` honoured.
- One token was added for the Studio: `--vignette`, the wash behind the 3D stage.
- The performance/UI pass added `--block-white`, the default placed-block colour.

---

## 9. What is tested, and what is deliberately not

**Tested, headlessly, in milliseconds:** every coordinate and geometry
predicate; lattice state; camera arithmetic; every model mutation; bounded
undo/redo; ray point → cell/level resolution including real gaps and hit ties;
local legality; click/keyboard interpretation; and the scrubber's accessible
control contract. `view.test.ts` re-derives the perspective projection itself
and checks every envelope corner rather than trusting the implementation.

**Not tested, on purpose** (Plan 4 §0.4): pixels, materials, light positions,
tween timings, anything that would be testing three.js rather than this project.
Judge the look by eye; judge the rules by test.

**The working rule.** Write the test, run it, watch it fail *for the right
reason* — a missing module is the right reason, a typo in the test is not — then
implement until it passes. Test and implementation land in the same commit, test
first in the diff.

---

## 10. Known gaps and things to watch

- **The optimized M2 scene and a real placement have been smoke-rendered** at
  1440 × 900 in headless Chrome with software WebGL. The test clicked a known
  top-view cell, observed `1 BLOCKS`, exercised the per-instance fade shader and
  confirmed the final block is visibly white. A human browser pass should still
  judge pointer feel on the target Pi/display; pixels remain outside Vitest.
- **`ContactShadows frames={1}` plus `frameloop="demand"`** remains intentional.
  The contact component is keyed by geometry, so block changes remount its one
  frame without turning the idle stage into a loop.
- **Shift is a prop that nothing sets yet.** `Viewport`, `Lattice` and
  `latticeCells` all take one and honour it; the gizmo and the readout that drive
  it are M8. The header currently reads the shipped `shift_*_cm` out of the
  config.
- **The authoring mode is local route state; every block stores its own mode.**
  The M6 twin's mode will instead be a read-only mirror of `state.mode`. Never
  confuse them: a real latch homes X and Y, a Studio mode switch moves nothing.
- **`@react-three/drei` is a large dependency.** It remains confined to the lazy
  Studio chunk; the production console chunk still contains no `WebGLRenderer`.

---

## 11. Changelog

Newest first. One entry per landed change; note anything that contradicts the
plan or that a future reader could not infer.

### M4 — The compiler

- Added `studio/compile.ts`: `supportGraph → orderBlocks → emitOps →
  summarise`, and one public `compile(model, { mode, settings, shifts?,
  rigSnapshot? }) → { valid, program, stats, diagnostics }` (Plan 4 §6.1).
- The ordering is Kahn's algorithm with the ready array re-sorted on every pop
  by `chain(byLevel, byCurrentMode, byAuthorIndex, byCell, byId)`. Each term is
  exported; `orderBlocks`/`comparatorFor` take an optional `terms` list, and
  `supportGraph` can be replaced with `new Map()`, so "remove a constraint" is a
  one-line experiment. `compile.test.ts` has one red-when-removed test per
  constraint (mapping table in §5.8), verified by deleting each in turn.
- `byCurrentMode` is **stateful** — recomputed each pop against the mode the
  emitter would be in by then. A static preference (computed once from the
  starting mode) re-homes on every level band; the determinism/latch test pins
  the dynamic behaviour at 2 latches vs a static 4 for the interleaved fixture.
- `emitOps` is the latch state machine and the **only** place a `mode` op is
  produced — emitted solely on an actual change, annotated `{ cost: "homes X
  and Y" }`, initial state the caller's `mode` (live `state.mode`, else
  `vertical`). `commandText(op)` is the **only** place serial text is built:
  `"B c r l" | "R" | "RR"`.
- Invalid models compile to `{ valid: false, program: [], stats: all-zero }`.
  `compile` runs M3's `validateModel` itself and never re-implements a rule;
  `error` blocks, `warning` does not. No partial programs, ever.
- Determinism test: twenty compiles byte-identical, plus program/stats
  independent of `blocks` array order. `diagnostics` order still tracks
  `model.blocks` (M3 behaviour) so it is excluded from that byte check.
- Added `panels/ProgramView.tsx` — the program as a serial log, latches as
  full-width `--motion` dividers, line selection wired to the viewport, and a
  copy-to-clipboard of the exact `op.text` lines. New `.studio-program-*` CSS.
- `settings.ts` gained `blockCycleSeconds` (40, from `rig/link.py`'s "~40 s")
  and `latchHomingSeconds` (16), both visible and editable in the `ESTIMATES —
  NOT MEASUREMENTS` block. `STUDIO_SETTINGS_KEY` stays `v1`: a pre-existing blob
  missing the two fields **backfills** the defaults rather than being rejected.
  `estimateLabel` renders `4 blocks · 1 latch · ~2:56`, `~` always shown. M7
  moves these constants once it times the real mean against `--mock`.
- `Studio.tsx` compiles in a `useMemo` and renders `ProgramView` between the
  diagnostics and settings panels.
- Fixed a pre-existing `Diagnostics.test.tsx` query (`"1 ERROR"` is split across
  `<b>`/`<span>`); the guard it checks is unchanged.
- Suite 184→214 across 21→23 files. Console entry unchanged (compiler is pure,
  lazy-chunk only); `Studio-*.js` +6.5 kB.
- Report-back (worst case, cheaper ordering, uncompilable models) recorded in
  §5.8: the true alternating-orientation stack forces `n − 1` latches and that
  is minimal; no valid-but-uncompilable model exists (support is acyclic in Z).

### M2 — The opening move

- Restored the cinematic mount intro in `view.ts` as pure arithmetic
  (`introPose`, `introMs`, `easeInOut`): 880 ms, from 0.32× the framing distance
  out to the framed pose, sweeping 0.85 rad of azimuth and rising in elevation
  on one cubic ease-in-out. Nine headless cases, including that the pull-back is
  monotonic and that `t >= 1` returns the framed pose itself.
- Fixed the double-zoom: the intro is guarded by a one-time `phase` ref in
  `CameraRig`, so resize, browser zoom, rerender and reframe cannot restart it.
  A resize mid-intro retargets the move rather than replaying it.
- `cameraTransitionMs` keeps its job — the *first* pose is now the intro's, and
  size-only reframes still snap.
- Corrected a stale `TWEEN_MS = 420` in §5.4; it has been 260 since M1.

### M2 — Performance and placement-motion pass

- Added one-promise Studio preloading on browser idle and mouse, keyboard or
  touch intent. The console bundle remains free of `WebGLRenderer`.
- Deduplicated same-cell hover state and memoised the heavy lattice/block trees,
  so pointer samples within one target do not rerender the scene.
- Replaced per-cell fill meshes with two instanced fills, cached token colours,
  capped DPR at 1.5 and requested the high-performance WebGL adapter.
- Removed the continuously-updated directional shadow map and reduced the
  one-shot contact texture from 1024² to 512².
- Stopped block `useFrame` work completely when no arrival is active and marked
  the changing arrival buffers for dynamic GPU upload.
- Replaced the 140/90 ms arrival with a smoother 220 ms quintic 8 mm settle plus
  130 ms smoothstep fade. Multi-row runs stagger distinct rows by 34 ms.
- Added an efficient per-instance arrival-opacity shader while retaining the
  requested ordinary solid/x-ray material split.
- Added `--block-white`; new blocks are white with a small emissive lift. Fixed
  the empty-instance shader recompile that previously rendered their colour
  black, and clear stale hover previews after a commit.
- Added six pure tests for motion, row sequencing, hover deduplication and the
  cached preload path; the suite is now 136 tests across 17 files.

### M2 — Placement

- Added immutable `model.ts` and generic `history.ts`; geometry and order cannot
  mutate each other, history retains 100 entries, and a run is one entry.
- Added `pick.ts`: footprint-aware inverse lattice, active-mode top resolution,
  nearest-hit/top-tie priority and dominant-axis run cells, all GPU-free tests.
- Kept M2 legality in a separate `placement.ts`; support/collision remain M3.
- Added rounded, colour-instanced blocks per mode, keyed contact-shadow refresh
  and reduced-motion snapping; current arrival timing is documented above.
- Added the legal/illegal ghost, any-face alt removal, 4 px click guard and
  click-on-pointerup semantics.
- Added the level 0–17 rail, held-level header state, keyboard jumps and 15%
  above-level x-ray batches.
- Smoke-rendered the whole stage under software WebGL at 1440 × 900.

### M1 — Static viewport

- Added the pure `view.ts` and `lattice.ts` rather than putting the framing
  arithmetic or the cell-state decision inside a component.
- **Corrected Plan 4 §4**: no scene-group transform; `coords.machineToScene()`
  already returns scene space (§4.1 above).
- Chose hash routing and a lazy Studio import; console entry grew 1.44 kB.
- Pinned `three@0.185.1`, `@react-three/fiber@9.7.0`, `@react-three/drei@10.7.8`.
- Ruled out drei `<Text>` (troika fetches a font from a CDN); scene labels are
  `<Html>`.
- Added `scene/theme.ts` so the "no raw hex" rule reaches inside the canvas, and
  the `--vignette` token for the stage background.
- `ENVELOPE_Z_CM = 26.5` named once in `view.ts`, the firmware's `Z_TRAVEL_CM`.

### M0 — Coordinates and fixtures

- `coords.ts` + `geometry.ts`, held to `python/rig/grid.py` at 1e-6 by fixtures
  dumped by `python/tools/dump_grid_fixtures.py`.
- The browser imports `config/rig.json` directly; `vite.config.ts` gained
  `server.fs.allow: [".."]`. No second copy of the geometry.
- Machine space is millimetres; `coords.ts` is the only converter.
- `BLOCK_HEIGHT_CM` (1.5) has no `rig.json` partner — it is the firmware's.
- `latticeBounds()` reports the **reachable** grid by default, matching
  `MachineGrid`; pass `"requested"` for the operator's grid.
- `AGENTS.md` §3a and §3b were stale against `grid.py` and the firmware and were
  corrected in the same pass.

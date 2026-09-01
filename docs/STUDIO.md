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
| M5 — Library | ✅ delivered | `rigmodel.ts` (the `rigmodel/1` file), `library.ts` (Result CRUD, 4 MB budget), `thumbnail.ts` + `scene/Capture.tsx`, `panels/LibraryDrawer.tsx`, three built-in examples |
| M6 — The twin | ✅ delivered | `twin.ts` (the whole state→picture mapping, fixture-tested against recorded server sessions), `scene/Twin.tsx`, `components/TwinPanel.tsx` + `Instrument.tsx` on the index page, SYNC VIEW, a read-only mode mirror |
| M7 — The runner | not started | executing a compiled program through `/api/build` |
| M8 — Wow pass | not started | shift gizmo, x-ray by level, cross-mode bridging |

**Test suite.** `cd web && npm test` — **347 tests across 30 files**, all green.

| file | tests | what it holds |
| --- | --- | --- |
| `studio/coords.test.ts` | 41 | the port of `python/rig/grid.py`, against dumped fixtures at 1e-6 |
| `studio/geometry.test.ts` | 12 | AABBs, overlap, the firmware's clipping |
| `studio/lattice.test.ts` | 14 | which cells are drawn, and in what state |
| `studio/view.test.ts` | 30 | envelope/block framing, the four snaps, the orbit floor, the opening move |
| `studio/validate.test.ts` | 27 | every §6.4 rule, modified configs, bridge scan, centroid and build order |
| `studio/compile.test.ts` | 25 | the four steps in isolation, one red-when-removed test per ordering constraint, the latch state machine, twenty-compile determinism |
| `studio/rigmodel.test.ts` | 19 | lossless round trip, eight named corrupt-file refusals, the migration hook, the library array file |
| `studio/library.test.ts` | 20 | CRUD, index/body split, one corrupt body costing one card, unavailable and full storage, the budget refusal, export/import |
| `studio/examples.test.ts` | 23 | the three examples as fixtures — round trip, no errors, compiled program, grid bounds, author order |
| `studio/twin.test.ts` | 39 | every row of Plan 4 §9.2, LOCKED's explicit `animating === false`, the confirmation fold, and three **recorded** `/api/events` sessions (placed, rejected, aborted) |
| `components/TwinPanel.test.tsx` | 6 | the read-only mode label, SYNC VIEW, the locked/stale/rejected banners, the model picker, and the desktop/phone instrument layout |
| `studio/thumbnail.test.ts` | 5 | the bottom-up row flip, the 16:10 sizes, graceful absence of `OffscreenCanvas` |
| `studio/panels/LibraryDrawer.test.tsx` | 18 | cards and meta line, inline rename, duplicate, delete with a real undo, the storage strip, the budget refusal, drop-import confirmation |
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

**Bundle**, from `npm run build` at the end of M6:

| chunk | size | notes |
| --- | --- | --- |
| console entry `index-*.js` | 254.93 kB (81.61 kB gzip) | still contains **no** three.js. **+36.2 kB over M5**, and all of it is the twin: `twin.ts` pulls in `library.ts` / `examples.ts` / `rigmodel.ts`, and `library.ts` statically imports `compile.ts` and `validate.ts` to build a card. That is the price of the model picker being on the index page; splitting it would put the picker behind a second async import for ~13 kB gzip |
| `BlockShadows-*.js` | 917.35 kB (245.23 kB gzip) | the three.js/drei chunk, now **shared** by the Studio and the twin and lazily loaded by whichever arrives first. The name is Rolldown's pick of a shared entry point, not a claim about its contents |
| `Studio-*.js` | 52.08 kB (16.54 kB gzip) | the Studio route alone, once three.js is shared out |
| `Twin-*.js` | 3.40 kB (1.60 kB gzip) | `scene/Twin.tsx`, lazily imported by `TwinPanel` |
| `index-*.css` | 36.09 kB (7.48 kB gzip) | +1.9 kB for the instrument, the tabs and the twin's plates |

Three.js is still absent from first paint: the twin's canvas is a `React.lazy`
import behind `routes/twin-loader.ts`, exactly as the Studio route is. Check with:

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
    twin.ts              §9's whole state → picture mapping; the confirmation fold
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
      Twin.tsx           the read-only, reduced-cost variant on the index page
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
    twin-loader.ts       shared lazy import of the twin's canvas
  components/
    Instrument.tsx       camera + twin: two columns, or a phone tab switcher
    TwinPanel.tsx        the twin's chrome: mode mirror, SYNC VIEW, banners, picker
  media.ts               the phone breakpoint, reduced motion, page visibility
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

### 5.9 `studio/rigmodel.ts` — the `rigmodel/1` file

The one place a stranger's JSON is allowed to become a model. Nothing throws:
every entry point returns `Result<T> = {ok: true, value} | {ok: false, reason}`,
and `reason` is a sentence an operator can act on.

| export | does |
| --- | --- |
| `SCHEMA` | `"rigmodel/1"` |
| `StudioModel` | the whole document in memory: id, name, description, created, modified, `rig`, `blocks`, `order`, optional `thumbnail` |
| `serialiseModel` / `parseModel` | two-space JSON out, `Result<StudioModel>` in |
| `serialiseLibrary` / `parseLibraryFile` | the whole library as one array; a single-model file is also accepted |
| `documentOf` / `structureOf` | document ⇄ the editable `{blocks, order}` |
| `snapshotFileRig` / `toFileRig` / `fromFileRig` / `shiftsOf` | the `rig` block, both directions |
| `MIGRATIONS` / `migrate` | the version hook |
| `repairOrder` | an order that disagrees with the blocks is repaired, not refused |

**Import order is fixed, and it is the whole safety argument:** validate the
schema → run the migration hook → validate the structure → let the caller warn
on drift. A migration that ran after structural validation would be validating
the wrong document. **The file is never rewritten on open.**

**Why it is a separate module from `model.ts`.** Plan 4 §7 sketches the file
format inside `model.ts`. The `rig` snapshot has to be converted to and from
`validate.ts`'s `RigGeometrySnapshot`, and `validate.ts` already imports
`model.ts`; putting the conversion in `model.ts` would make that a runtime
import cycle. `rigmodel.ts` depends on both and nothing depends on it except
`library.ts` and the drawer.

**One deviation from Plan 4 §5, recorded here as house style requires.** §5's
`rig` example lists `cols`, `rows`, `block_cm` and `pitch_cm` per mode. The file
also writes `trim_cm`, `error_offset_cm` and `max_edge_overhang_cm`. Drift is
detected by comparing against `snapshotRigGeometry()`, which carries all of
them; a snapshot missing those fields would have to invent zeros and would then
report drift on every model the moment anyone set a non-zero trim. The `rig`
block is otherwise exactly §5, `shift_cm` included.

### 5.10 `studio/library.ts` — CRUD that cannot throw

`localStorage` is genuinely unavailable in a private window, genuinely full at
about 5 MB, and in some browsers genuinely throws on **access** rather than on
write. Every function therefore returns a `Result` and every touch of the store
is wrapped.

```text
listModels()          → Result<ModelCard[]>      readModel(id)      → Result<StudioModel>
writeModel(model)     → Result<{bytes, remaining}>  removeModel(id) → Result<void>
duplicateModel(id)    → Result<StudioModel>      renameModel(id, name) → Result<StudioModel>
exportModel(model)    → string                   importModel(text)  → Result<StudioModel>
exportLibrary()       → Result<string>           importLibrary(text)→ Result<StudioModel[]>
storageReport()       → StorageReport            acceptsDroppedFile(name) → Result<void>
```

**Cards are separate from bodies.** `rig.studio.models.v1.index` holds the cards
(id, name, block count, latch count, estimate, modified, bytes, thumbnail);
`rig.studio.models.v1.<id>` holds each body. The drawer renders without parsing
a single model, and a corrupt body costs **one card**, not the library. A
corrupt *index* degrades to "no cards" with every body left on disk.

**The budget is 4 MB of an assumed 5, and it refuses.** `writeModel` measures
the whole namespace from the store's own keys — so a body orphaned by an
interrupted write still counts — and when a write would exceed the budget it
returns a reason naming the three largest models. **Nothing is ever evicted
automatically.** Silently deleting saved work to make room for a save is the
kind of behaviour that ends trust in a tool permanently, and this is a tool
people use the night before a demo. The write order is body first, then index;
if the index write fails the new body is removed again.

**The server seam** for Plan 4 §8.7's optional `GET/PUT /api/models` is the
four-method `LibraryStorage` interface this module is written against. That is
the entire seam. There is no sync engine and M5 makes no network call.

**One deviation from Plan 4 §8.7, recorded here.** "A zip of the whole library"
is instead a single `.rigmodels.json` array. A zip would mean either a new
dependency in a bundle served off a Pi or a hand-written stored-entry writer, to
produce a file that is harder to inspect, diff and email than the JSON inside
it. `parseLibraryFile` accepts a single-model file too, so an operator dragging
one file in never has to know which kind it is.

### 5.11 `studio/thumbnail.ts` — and the trap it exists for

The frameloop is `demand` and the canvas has no `preserveDrawingBuffer`, so
calling `toDataURL` in a save handler returns a **transparent rectangle**: the
backbuffer has already been cleared. Turning `preserveDrawingBuffer` on globally
would fix it at the cost of every frame of the whole application, for a feature
used once per save. So `scene/Capture.tsx` renders the same scene into an
off-screen `WebGLRenderTarget` and this module turns the pixels into a WebP.

- `flipRows` — WebGL reads a framebuffer bottom-up, images are top-down. Pure,
  and tested, because it is the part that would fail silently.
- `THUMBNAIL` — rendered 640 × 400, stored 320 × 200, WebP quality 0.7. About
  10–20 kB each, which is what makes the 4 MB budget hold ~200 models.
- `encodeThumbnail` returns `undefined` rather than throwing where
  `OffscreenCanvas` does not exist. A missing thumbnail is a plain card; a
  thrown one would be a save the operator cannot complete.

### 5.12 `studio/examples.ts` — three models that are also fixtures

| id | name | shape |
| --- | --- | --- |
| `example-tower` | Single tower | vertical `[3,2]`, levels 0–4. No latch, five `B`s |
| `example-bridge` | Two towers, one span | vertical `[2,2]` and `[3,2]` at levels 0–1, horizontal `[1,4]` at level 2. **One latch** |
| `example-pyramid` | Stepped pyramid | 5 / 3 / 1 in vertical mode, every course resting fully on the one below |

`examples.test.ts` asserts each one round-trips, validates with **no errors**,
and compiles — so a geometry change in `rig.json` breaks a test rather than the
presentation. They are listed in the drawer above the saved models and are
**never written to storage**: they cost no budget and cannot be deleted.

**The bridge carries `shiftX +1.00 cm` on the horizontal grid, and that is the
finding of this milestone.** With the shipped `rig.json` and the default 0.55
support ratio, *no* unshifted cross-mode bridge is legal. The vertical pitch is
3.8 cm and the horizontal 7.6 cm, so a horizontal block always lands over the
1.6 cm gap between two vertical stacks: the best available contact is 46.7% of
its footprint (three vertical piers), under the ratio. The reverse — a vertical
block on two horizontal piers — reaches 68.3% but puts its centroid in the gap,
which §6.5's centroid rule refuses. A search over every (tower pair, span cell,
shift in 1 mm steps) triple through `validateModel` found the legal shifts to be
**+0.8…+1.1 cm and +2.7…+3.0 cm**; +1.0 is the round one, and `v[2,2] v[3,2]`
with `h[1,4]` is its central case. All of that is recorded in
`examples.ts`'s docstring and pinned by a test.

Because the rig is not applying that shift, the bridge opens with a
`GEOMETRY_DRIFT` warning naming it. **That warning is the feature**: it is the
difference between an operator pushing `shiftX 1.0` before the build and
watching a block fall between two towers.

The pyramid opens with `ISLAND` warnings, and they are also correct: inside one
grid the 1.6 cm gaps mean no two cells ever touch, so five stacks side by side
really are five separate structures. That is Plan 4 §3 fact 6 stated from the
other direction, and it is why the bridge exists.

### 5.13 `studio/twin.ts` — the mapping that is the twin

Plan 4 §9's twin is a **claim about the machine**, so the whole of it is one
pure function and the component draws the object it returns:

```ts
twinScene(state, model, progress, options) → {
  blocks: { id, mode, col, row, level, appearance, token, mix, opacity, label, reason }[],
  banner: "none" | "running" | "rejected" | "locked" | "stale",
  bannerText: string | null,
  animating: boolean,
  desaturate: boolean,
  mode: ModeName | null,     // a READ-ONLY mirror of state.mode
  targetId: string | null,
}
```

**DEVIATION from the milestone prompt**, which specified
`twinScene(state, model, confirmed)`. `progress` *is* the confirmed set — plus
the rejection the server reported, which arrives by the same route and which the
component would otherwise have to remember on its own. Remembering is a rule.

**The two rules that are the whole design.**

*It never invents state.* A block is `placed` because its id is in
`progress.confirmed`, and it gets there only through `foldTwinProgress`, which
reads the server's `last_result`. There is no optimistic placement.
`BuildController.build()` clears `selected` on PLACED, and that clearing is how
the fold knows which block a result belongs to: **a `placed` result arriving
with a selection still set is ignored**, which is exactly the payload a page
load lands on when the previous build has already finished. The fold is
idempotent, so the server repeating its last result twenty times a second, and
React StrictMode invoking the effect twice, both cost nothing.

*After an abort it stops.* LOCKED sets `animating: false`, `desaturate: true`,
`targetId: null`, lerps every block's colour toward `--text-faint` by
`LOCKED_MIX` **in the mapping, where it is asserted**, and demotes every
unconfirmed block to a ghost. The machine's real state is unknown after an
abort; a twin still rendering the plan is at its most misleading exactly when
misleading is most expensive.

| appearance | token | opacity | when |
| --- | --- | --- | --- |
| `ghost` | `--text-faint` | 0.2 | remaining work |
| `target` | `--signal` | 0.45 | the server's current selection, labelled `B 3 2 0` |
| `building` | `--motion` | 0.85 | that block while `build_state` is RUNNING |
| `placed` | the block's own `--block-*` | 1 | the server said PLACED |
| `rejected` | `--text-faint` | 0.2 | the server said REJECTED, with its reason |

Two more deviations, both deliberate:

- **Ghosts are 20%, not the prompt's 12%.** That is Plan 4 §9.2's own number.
  At 12% against `--void`, at the twin's default framing, a ghost is not
  visible at all.
- **The `rejected` BANNER does not require the rejected cell to be in the
  model.** The rig refused; that is worth saying either way. Only the block-level
  `rejected` appearance needs an identified block.

`banner` precedence is `locked` → `stale` → `running` → `rejected` → `none`.
**LOCKED beats a dropped socket on purpose:** a locked session that has also
lost its socket is still a locked session, and that is the more expensive fact.

`twinSignature(state, progress, options)` is the other rule in here. The pipeline
driver notifies on every camera frame, so `/api/events` delivers ~20 states a
second that differ only in `camera_age_ms`; the signature states exactly what the
picture depends on, and `TwinPanel` recomputes the scene — and therefore redraws
the canvas — only when it changes.

`descentOffsetScene()` is **an illustration of a descent, not a telemetry
read-out**: the Arduino is deaf while `buildBlock()` runs and reports nothing
until it is done, so the loop is timed against nothing in particular. Reduced
motion returns exactly 0.

`twin.fixtures.json` is dumped by `python/tools/dump_twin_states.py` from
`web.app` running against `MockBoard`: three sessions — placed, rejected,
aborted — one entry per state the socket would have delivered. The mapping is
tested against what the server actually sends, not against payloads the test
invented. Same bridge as the coordinate fixtures: **when the two disagree,
Python is right.**

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

### 6.9 `scene/Capture.tsx` and `panels/LibraryDrawer.tsx`

`Capture` fills a ref with a thumbnail function while the canvas is mounted. It
renders the **same scene** into a `WebGLRenderTarget` with a camera of its own,
posed by `view.viewPose("iso", aspect, box)` on the **model's** bounding box
(`view.modelBoxScene`), not the envelope — cards that all show the same empty
cage are worse than no thumbnails. The envelope is still in the scene, so it
renders faintly behind for scale. The visible camera is never moved.

`LibraryDrawer` slides from the left at `--z-drawer` **over** the viewport, not
beside it: the viewport is the point of this application and it is not squeezed
to 288 px to list files. It only draws; every failure it can meet arrives as a
`Result` reason it puts on screen. Three interaction choices worth recording:

- **Rename is an inline edit on double-click**, not a modal. A modal for
  renaming a local file is friction with no safety in it.
- **Delete is immediate, with a six-second undo toast** (`UNDO_MS`). A confirm
  dialog asks somebody to be careful; an undo lets them be wrong. The test
  proves the undo really restores the body, and that letting it lapse stands.
- **Import never lands silently.** A dropped file is gated by
  `acceptsDroppedFile` (`.json` only, and a rejection names the file), parsed,
  then shown in a confirm sheet with each model's name, block count and any
  drift warning. A file that appeared in your library without being read is a
  file you cannot trust. The drop listener is on the `window` and lives whether
  the drawer is open or not.

The card is a 16:10 thumbnail on `--sunken`, the name in `--t-md`, and one mono
`--t-xs` meta line in `--text-dim`: `12 blocks · 1 latch · ~4:10 · 2d ago`. The
selected card takes a `--signal` 1 px border and never a fill.

### 6.10 `scene/Twin.tsx`, `TwinPanel.tsx` and `Instrument.tsx`

`Twin.tsx` renders the `TwinScene` object and holds no logic. It is the same
engine as the Studio and deliberately the cheap variant, because it shares a
phone with a live MJPEG stream and **the camera is what the operator must be
watching**:

- `frameloop="demand"`, `dpr={[1, 1.5]}`, `antialias: false`,
  `powerPreference: "low-power"`, and `frameloop="never"` whenever the panel is
  off screen (a phone tab switched to the camera unmounts it; `document.hidden`
  stops it).
- `invalidate()` only when the mapping's answer changes (see `twinSignature`) or
  while a descent is genuinely in flight.
- No shadow maps and no post-processing. `BlockShadows`' instanced ellipses are
  the whole grounding cue, as in the Studio.
- **`Blocks.tsx`'s `BlockBatch` is reused, not forked** — two block renderers
  would drift. It became generic over anything carrying a cell address, takes a
  `colourOf(block)` from the caller and gained a `quality` prop: `"twin"` drops
  the arrival pass and its custom shader, the shadow receiver, every pointer
  handler, and swaps the standard material for a lambert one. One instanced
  batch per (mode, appearance); the single block in flight is one plain mesh,
  because the machine builds one at a time.

`TwinPanel.tsx` is the chrome. **Its mode indicator is the trap in this
milestone.** In the Studio a mode switch is free and instant, because there it
is a view change; on the index page it is a physical latch that homes X and Y.
So the twin's indicator is a plain read-only label mirroring `state.mode` —
never the Studio's `[V|H]` segmented control — and there is no control in the
panel that could latch anything. Mode changes go through the console's existing
confirmed `POST /api/mode` in the rail, unchanged. `TwinPanel.test.tsx` asserts
the label is not a button and that rendering the panel posts no mode at all.

`SYNC VIEW` is `viewPose("top", aspect, workspaceBoxScene())` — the ground
rectangle the overhead camera frames, from straight above, machine +X right and
+Y up the screen. M1 chose the top view's up vector for exactly this. While it
is on the orbit is **disabled** and the chip's neighbour says `synced to
camera`: an orbit that silently broke the sync would be a control that lies.
Unsynced, the twin frames the envelope once on mount and then leaves the camera
alone — a resize must never yank a view the operator orbited to.

`Instrument.tsx` is the layout: on desktop the camera and the twin are equal
columns inside **one** `--r-lg` border, top-aligned, so they read as one
instrument; below 899px they become a two-tab switcher **defaulting to CAMERA**.
BUILD cannot move: on desktop it is in the rail, a separate grid column, and on
a phone it is in the sticky action sheet below the tabs.

The model the twin shows is chosen in the panel — the three built-in examples
plus whatever is in the library — and remembered in
`rig.console.twin.model.v1`. Nothing is loaded by default: a model appearing
that the operator did not choose is the same class of mistake as a block
appearing that the rig did not place.

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

`routes/twin-loader.ts` gives the twin's canvas the same treatment through the
same `createPreloader()`, so the index page's first paint does not wait on
three.js either. Both lazy chunks now share one Three.js chunk.

`App.tsx` is still the console; Plan 4 §7's `routes/Console.tsx` has still not
been split out. M6 was expected to force it and did not: the twin went in as two
components (`Instrument`, `TwinPanel`) that `App.tsx` composes, which left every
Plan 3 test untouched.

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
local legality; click/keyboard interpretation; the scrubber's accessible
control contract; the file format's round trip and its eight named refusals;
storage that is absent, throwing, full or over budget; and the three examples as
fixtures. `view.test.ts` re-derives the perspective projection itself
and checks every envelope corner rather than trusting the implementation.
For the twin: every row of Plan 4 §9.2, the confirmation fold, the signature
that decides when it may redraw, and three **recorded** server sessions replayed
through the mapping — including the assertion the milestone exists for, that
LOCKED sets `animating` to `false`.

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
- **Shift now comes from the open model's own `rig` snapshot.** `Studio.tsx`
  derives `shiftsOf(document.rig)` and threads it into the viewport, the
  validator and the compiler, so a model that needs a shift renders where it
  will really be built and says so through `GEOMETRY_DRIFT`. The **gizmo** that
  edits a shift interactively, and the header readout that follows it, are still
  M8; the header currently reads the shipped `shift_*_cm` out of the config.
- **Thumbnails have not been seen on a GPU.** `flipRows` and `encodeThumbnail`
  are tested headlessly and `Capture` follows the documented
  `WebGLRenderTarget` → `readRenderTargetPixels` → `OffscreenCanvas` path, but
  jsdom has no WebGL, so the first real capture is a browser check. Every
  failure path returns `undefined` and the save still completes.
- **The 4 MB budget assumes a 5 MB quota.** Browsers differ, and a real
  `QuotaExceededError` under the budget is handled separately from the budget
  refusal — different message, different remedy — but the number itself is a
  convention, not a measurement.
- **The authoring mode is local route state; every block stores its own mode.**
  The twin's mode is instead a read-only mirror of `state.mode`. Never confuse
  them: a real latch homes X and Y, a Studio mode switch moves nothing.
- **The twin was driven against `--mock` in headless Chrome** (software WebGL,
  1440 × 900 and 760 × 900) for the ghost, target, `NEXT B 3 2 0` label, SYNC
  VIEW and LOCKED states, and against recorded server sessions in Vitest for all
  of them. **STALE was not confirmed by eye** — a headless screenshot latches
  before a killed socket propagates — only by test. A human browser pass on the
  Pi should judge it, and should judge frame rate with a real MJPEG stream.
- **Ghosts read faintly at the default framing.** The twin frames the whole
  travel envelope, which is 26.5 cm of mostly empty cage, so a five-block tower
  is small. SYNC VIEW or an orbit in makes it plain. Framing on the model
  instead was rejected: the twin is a picture of the machine, and matching the
  camera is what §9 is for.
- **`confirmed` starts empty on every page load.** The twin credits only the
  builds it watched, because a `last_result` already on screen when the console
  connects cannot be attributed to a block. Reloading mid-session therefore
  loses the fill-in so far. Persisting it would mean persisting a claim about
  the machine that nothing re-checks; M7's runner owns the program state
  instead.
- **`@react-three/drei` is a large dependency.** It remains confined to the lazy
  Studio chunk; the production console chunk still contains no `WebGLRenderer`.

---

## 11. Changelog

Newest first. One entry per landed change; note anything that contradicts the
plan or that a future reader could not infer.

### M6 — The twin

- Added `studio/twin.ts`: the whole of Plan 4 §9 as one pure mapping —
  `twinScene()`, the `foldTwinProgress()` confirmation fold, `twinSignature()`
  and `descentOffsetScene()`. No React and no three.js in it; `scene/Twin.tsx`
  draws what it returns and decides nothing.
- Added `python/tools/dump_twin_states.py` and `studio/twin.fixtures.json`:
  three real `/api/events` sessions (placed, rejected, aborted) recorded from
  `web.app` against `MockBoard`, one entry per state the socket would deliver.
  The mapping is tested against what the server sends, not against invented
  payloads. The recording confirmed the load-bearing fact the fold rests on:
  `selected` survives RUNNING and is cleared by `BuildController.build()` on
  PLACED — and that the state right after a build carries `last_result: placed`
  alongside the *next* selection, which is exactly what an optimistic twin
  would place wrongly.
- Added `scene/Twin.tsx`, `components/TwinPanel.tsx` and
  `components/Instrument.tsx`; the index page now shows camera and twin as equal
  columns in one border, and a CAMERA/TWIN tab switcher below 899px that
  defaults to the camera.
- **`Blocks.tsx`'s `BlockBatch` was generalised rather than forked**: generic
  over any cell-addressed block, a caller-supplied `colourOf`, and a `quality`
  prop whose `"twin"` setting drops the arrival shader, the shadow receiver,
  every pointer handler and the standard material. Plan 4 asked for exactly
  this; two block renderers would drift.
- Added `view.workspaceBoxScene()` for SYNC VIEW — the envelope's ground plane,
  with none of the cage's height — with three tests in `view.test.ts`, including
  that the synced pose keeps machine +X to the right and +Y up the screen at
  every aspect ratio.
- Added `media.ts` (phone breakpoint, reduced motion, page visibility). It
  replaces the copy of the breakpoint in `App.tsx` and the copy of the
  reduced-motion query in `scene/Viewport.tsx`; two copies of a breakpoint is
  how a layout ends up disagreeing with itself at 899px.
- `store.ts` now records `updatedAt` on each state message, which is what the
  STALE banner counts from.
- Deviations, all argued in §5.13 and §6.10: the mapping's signature takes
  `progress` rather than a bare `confirmed` set; ghosts are Plan 4 §9.2's 20%
  rather than the prompt's 12%; the rejected banner does not require the
  rejected cell to be in the loaded model; LOCKED outranks STALE.
- The console entry grew 36.2 kB (12.7 kB gzip) because `twin.ts` reaches
  `library.ts`, and `library.ts` statically reaches `compile.ts` and
  `validate.ts`. Three.js is still absent from first paint.
- `npm test`: **347 tests across 30 files**. Plan 3's `step7`, `step9`, `step10`
  and `lib/workspace.test.tsx` are untouched and green.

### M5 — The library

- Added `studio/rigmodel.ts`: the `rigmodel/1` document, `Result`-returning
  parse/serialise, the migration hook, and the `rig` snapshot in both
  directions. **Deviates from Plan 4 §7** by living outside `model.ts` (a
  runtime import cycle through `validate.ts` otherwise) and **from §5** by also
  writing `trim_cm`, `error_offset_cm` and `max_edge_overhang_cm` per mode, so
  `GEOMETRY_DRIFT` compares the same fields it snapshots. Both are argued in
  §5.9. On import: schema → migration → structure → drift, in that order, and
  the file is never rewritten on open.
- Added `studio/library.ts`: `localStorage` CRUD where nothing throws, the card
  index kept separate from the bodies, and a **4 MB budget that refuses** and
  names the three largest models rather than evicting anything. Handles storage
  that is absent, that throws on access, and that returns a real
  `QuotaExceededError` — three distinct messages, because they have three
  distinct remedies. `LibraryStorage` is the only seam left for Plan 4 §8.7's
  optional server persistence; no sync engine, no network call.
- **Deviates from Plan 4 §8.7** by exporting the whole library as one
  `.rigmodels.json` array rather than a zip — the reasoning is in §5.10.
- Added `studio/thumbnail.ts` and `scene/Capture.tsx`. `preserveDrawingBuffer`
  stays **off**; the capture renders the scene into a 640 × 400
  `WebGLRenderTarget`, flips the rows, and encodes a 320 × 200 WebP at 0.7.
  Framed on `view.modelBoxScene()` — the model's own box, added this milestone —
  so cards do not all show the same empty cage.
- Added `panels/LibraryDrawer.tsx`: cards over the viewport at `--z-drawer`,
  inline rename on double-click, duplicate, delete with a real six-second undo,
  export one or all, and a drop-import that shows what is about to be added with
  its block count and drift warning before anything is written.
- Added three built-in examples, listed but never stored, so an empty library
  never looks broken and there is a demo to fall back on.
- **Finding: with the shipped `rig.json` and the default 0.55 support ratio, no
  UNSHIFTED cross-mode bridge is legal.** The best available contact for a
  horizontal block over two vertical stacks is 46.7% of its footprint; the
  reverse reaches 68.3% but puts its centroid in the 1.6 cm gap, which §6.5
  refuses. A sweep of every (tower pair, span cell, shift) triple through
  `validateModel` found the legal horizontal shifts to be +0.8…+1.1 and
  +2.7…+3.0 cm. "Two towers, one span" carries **+1.00 cm**, and therefore opens
  with a `GEOMETRY_DRIFT` warning naming it. This is Plan 4 §16 open question 3
  answered from the geometry: bridging works, but only with a registration
  shift, and the Studio has to say so. **No rule and no default was changed to
  make the example pass.**
- Improved `GEOMETRY_DRIFT` to name what actually differs — the mode, the knob
  and both values (`describeDrift`) — instead of "the geometry changed". A model
  that opens saying only that leaves somebody diffing two JSON files; one that
  says which knob moved is a single instruction. This is the only M3 change in
  the milestone and no M3 test's guard was weakened.
- `Studio.tsx` now holds the open document, derives the shift and the drift
  snapshot from **its** `rig` block, and threads both into the viewport, the
  validator and the compiler. Loading a model resets history, selection and the
  block-id counter past whatever the file used.
- Suite grew from 214 tests / 23 files to **302 / 28**. The console entry is
  unchanged at 218.73 kB; the lazy Studio chunk grew 20.7 kB and the shared
  stylesheet 4.6 kB.

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

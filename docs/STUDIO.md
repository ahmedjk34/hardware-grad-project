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
| M7 — The runner | ✅ delivered | pure exhaustive runner reducer, guarded effect driver, STEP/RUN/DRY RUN, feeder guidance, failure lock/pause, Markdown evidence report |
| M8 — Wow pass | not started | shift gizmo, x-ray by level, cross-mode bridging |

**Test suite.** `cd web && npm test` — **489 tests across 38 files**, all green.
(The per-file table below is maintained for the Studio's own files; a few rows
have drifted behind the total as unrelated console work landed.)

| file | tests | what it holds |
| --- | --- | --- |
| `studio/coords.test.ts` | 41 | the port of `python/rig/grid.py`, against dumped fixtures at 1e-6 |
| `studio/geometry.test.ts` | 17 | AABBs, overlap, the firmware's clipping, the convex-hull support polygon |
| `studio/lattice.test.ts` | 14 | which cells are drawn, and in what state |
| `studio/view.test.ts` | 30 | envelope/block framing, the four snaps, the orbit floor, the opening move |
| `studio/validate.test.ts` | 28 | every §6.4 rule, modified configs, bridge scan, the centre-of-mass toppling test |
| `studio/compile.test.ts` | 25 | the four steps in isolation, one red-when-removed test per ordering constraint, the latch state machine, twenty-compile determinism |
| `studio/rigmodel.test.ts` | 19 | lossless round trip, eight named corrupt-file refusals, the migration hook, the library array file |
| `studio/library.test.ts` | 20 | CRUD, index/body split, one corrupt body costing one card, unavailable and full storage, the budget refusal, export/import |
| `studio/examples.test.ts` | 23 | the three examples as fixtures — round trip, no errors, compiled program, grid bounds, author order |
| `studio/twin.test.ts` | 60 | every row of Plan 4 §9.2, LOCKED's explicit `animating === false`, the confirmation fold, all fourteen firmware phase ids, "exports no descent timer", and three **recorded** `/api/events` sessions (placed, rejected, aborted) replayed through the real store |
| `studio/runner.test.ts` | 25 | every named transition, serial phases that never advance the cursor, socket-loss pause and phase-driven resume, HELD locks / SAFE does not, feeder sequencing, abort program position, elapsed/ETA arithmetic, plus an exhaustive all-event walk proving no second build and no serial effect while RUNNING |
| `studio/runner-driver.test.ts` | 7 | the level/select/verify/build/mode request sequence against a mocked API, axis selection, zero-API dry transport and the defensive RUNNING refusal |
| `studio/run-report.test.ts` | 2 | deterministic event-derived Markdown, verbatim failures, durations, verification and camera evidence |
| `components/RunnerPanel.test.tsx` | 8 | full dry tower with no API traffic, mismatch stop, honest stop copy, rejected pause and abort lock, the rig's own phase readout, fourteen phases advancing nothing, stale-on-disconnect |
| `store.test.ts` | 20 | `build_step` applied with no timer advanced, id deduplication, phase/snapshot tie-breaks, the reconnect cursor, terminal-only `placed` |
| `ws.test.ts` | 7 | immediate delivery against a fake socket, the `?after=` cursor, replay envelope, backoff, unparseable frames |
| `blockCalibration.test.tsx` | 4 | the placed-block calibration panel — the plan walked cell by cell, SAVE disabled until the backend calls the fit ready, a refused step kept retryable, an abort disabling further steps, and a refusal to start leaving the other two routes reachable |
| `components/TwinPanel.test.tsx` | 7 | the read-only mode label, SYNC VIEW, locked/stale/rejected banners, controlled model picker, and desktop/phone instrument layout |
| `studio/thumbnail.test.ts` | 5 | the bottom-up row flip, the 16:10 sizes, graceful absence of `OffscreenCanvas` |
| `studio/panels/LibraryDrawer.test.tsx` | 21 | cards and meta line, inline rename, duplicate, delete with a real undo, the storage strip, the budget refusal, drop-import confirmation, delegated-save re-list, no-`storage`-prop lists real `localStorage` |
| `studio/settings.test.ts` | 4 | conservative defaults, timing-field backfill, guarded versioned persistence |
| `studio/panels/ProgramView.test.tsx` | 4 | serial-log rendering, latch dividers, line selection, clipboard copy |
| `studio/model.test.ts` | 7 | immutable mutations; geometry/order separation |
| `studio/history.test.ts` | 4 | generic undo/redo, branching and the 100-entry cap |
| `studio/pick.test.ts` | 6 | cell/level resolution, gaps, hit priority and straight runs |
| `studio/placement.test.ts` | 4 | M2's feeder, grid and occupied-slot gate |
| `studio/interaction.test.ts` | 6 | click slop, hover deduplication, keyboard interpretation, the Ctrl/Cmd-S save mapping |
| `studio/motion.test.ts` | 4 | fade/drop curves, reduced motion and row sequencing |
| `studio/panels/LevelScrubber.test.tsx` | 2 | accessible level hold/release controls |
| `studio/panels/Diagnostics.test.tsx` | 2 | severity grouping, selection, hover and fixes |
| `studio/panels/Settings.test.tsx` | 2 | visible estimates, copy and immediate edits |
| `routes/preload.test.ts` | 1 | one cached route import shared by every preload trigger |
| `redesign.test.tsx` | 10 | Plan 3 console |
| `step7` / `step9` / `step10` | 5 / 4 / 1 | Plan 3 console guards — must never regress |
| `lib/workspace.test.tsx` | 3 | the homography port |

**Bundle**, from `npm run build` at the end of M7:

| chunk | size | notes |
| --- | --- | --- |
| console entry `index-*.js` | 273.50 kB (86.75 kB gzip) | still contains **no** three.js. M7 adds the reducer, guarded driver, report exporter and runner chrome to the console entry; the compiler/model code was already reachable through the M6 twin picker |
| `BlockShadows-*.js` | 917.35 kB (245.23 kB gzip) | the three.js/drei chunk, now **shared** by the Studio and the twin and lazily loaded by whichever arrives first. The name is Rolldown's pick of a shared entry point, not a claim about its contents |
| `Studio-*.js` | 52.13 kB (16.56 kB gzip) | the Studio route alone, once three.js is shared out |
| `Twin-*.js` | 3.40 kB (1.60 kB gzip) | `scene/Twin.tsx`, lazily imported by `TwinPanel` |
| `index-*.css` | 39.36 kB (8.06 kB gzip) | M7's feeder plate, failure/report strip and responsive runner layout |

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
    runner.ts            §10's pure program state machine and exhaustive safety surface
    runner-driver.ts     one reducer-described effect → existing guarded API route
    run-report.ts        event-derived Markdown and camera evidence capture
    compile.ts           model → ordered B/R/RR program; support graph, Kahn order, latch state machine
    settings.ts          versioned physical estimates + the two estimate-timing constants, guarded localStorage I/O
    coords.fixtures.json 17 cases / 1040 cells dumped from Python
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
    Root.tsx             hash routing (#/, #/build, #/studio) + the one connectEvents
    preload.ts           generic one-promise import cache
    studio-loader.ts     shared idle/intent/navigation Studio import
    Studio.tsx           the Studio route (chrome + viewport)
    twin-loader.ts       shared lazy import of the twin's canvas
  components/
    Instrument.tsx       camera + twin: two columns, or a phone tab switcher
    TwinPanel.tsx        the twin's chrome: mode mirror, SYNC VIEW, banners, picker
    RunnerPanel.tsx      STEP/RUN/DRY RUN chrome; executes effects, owns no rules
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
by `python/tools/dump_grid_fixtures.py` (17 cases, 1040 cells: both modes, shipped
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
`footprintContains`, `latticeFootprint`, `EPS_MM` (the one millimetre-slack
constant every "touching" comparison here and in `validate.ts` shares), and:

`convexHull(points)` → the counter-clockwise hull by Andrew's monotone chain,
collinear points dropped. `supportPolygonContains(boxes, clip, x, y)` clips each
box to `clip`, hulls the corners and asks whether `(x, y)` is inside — the
toppling test: a rigid block stays put only while its centre of mass projects
into the convex hull of everything it rests on, which is why a span across a gap
is supported with nothing under its middle and a one-sided overhang is not. One
support reduces it to "the centre sits on that footprint".

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

`validate.ts` reports two independent things about a placement. `ratio` is the
union of all beneath footprints clipped to the candidate, over the candidate
area, and the configured `supportRatio` (default 0.55) is its minimum — a
friction / claw-release proxy. `centreStable` is the physics: the candidate's
centre of mass (its footprint centroid) must project into the **convex hull of
its contact patches** (`geometry.supportPolygonContains`). `UNSUPPORTED` fires
unless **both** hold. A span carried on two towers with nothing under its middle
is stable; a block with plenty of contact but its centre of mass out past the
last support edge is not. This is a truer reading of Plan 4 §6.5's centroid
clause than the old fixed 70% contact bypass, which was both too strict (it
rejected a stable low-contact bridge) and too loose (it passed a high-contact
overhang).

`interaction.ts` owns the 4 px click slop and keyboard mapping. Undo is
Ctrl/Cmd-Z; redo is Ctrl/Cmd-Shift-Z or Ctrl/Cmd-Y. **Ctrl/Cmd-S is `"save"`**
and the Studio route calls `preventDefault()` on it like every other action, so
the browser's own save dialog never appears. Inputs and editable elements are
ignored. Escape releases a held level, digits 0–9 hold one, and `M` toggles
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
"RR"`. `ProgramView` and the M7 runner both consume `op.text`; a second
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
both named constants in `settings.ts`. M7 replaced the M4 guess with
`BLOCK_CYCLE_SECONDS = 2.115`, the mean of five complete guarded cycles against
`python -m web --mock` (2.113 / 2.108 / 2.112 / 2.104 / 2.140 s).
`LATCH_HOMING_SECONDS = 16` remains a visible guess. The mock mean times the
demo/rehearsal transport, **not the physical arm**; the setting copy says so and
the value remains editable for a hardware measurement. With those defaults
`estimateLabel(stats)` renders `4 blocks · 1 latch · ~0:24` — the `~` is always
shown. The runner uses the same values for its count / elapsed / ETA readout;
there is no predictive progress bar.

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

**The bridge needs no operator shift.** With the shipped `rig.json`
(horizontal registered +1.9 cm on both axes), the span sits over the 1.6 cm gap
between two vertical stacks with **73.3% union contact**, and its centre of mass
rides between the two towers — inside the convex hull of the two contact patches.
Both support tests pass, so the built-in bridge opens with no `UNSUPPORTED` or
`GEOMETRY_DRIFT` diagnostic and `BRIDGE_SHIFT_CM` is pinned to zero.

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
| `ghost` | `--block-wood-soft` | 0.6 | remaining work |
| `target` | `--signal` | 0.62 | the server's current selection, labelled `B 3 2 0` |
| `building` | `--motion` | 0.9 | that block while `build_state` is RUNNING |
| `placed` | the block's own `--block-*` (default `--block-white`, pale birch) | 1 | the server said PLACED |
| `rejected` | `--text-faint` | 0.34 | the server said REJECTED, with its reason |

Under LOCKED the mapping forces every token to `--text-faint` explicitly (not
by relying on where each appearance's token points), so "an abort freezes the
picture" survives the appearance tokens changing.

Two more deviations, both deliberate:

- **Ghosts are woodish and 60%, not 12% / 20% / 40%.** Plan 4 §9.2's 12% and
  the later 20% were chosen against `--text-faint`; even the first woodish pass
  at 0.4 read as too faint on the rig display. A translucent block over `--void`
  loses lightness *and* chroma to the black it composites over, so the ghost has
  to start high: `--block-wood-soft` (luminous tan) at **0.6**, plus a warmer
  `--block-wood` emissive on the material (0.16 twin / 0.13 solid) which lifts
  the fragment before the alpha blend. It still sits visibly under the placed
  block's 1.0 — a plan, not a placement. `target` 0.62, `rejected` 0.34 (dimmer
  than a live ghost, still grey — inert, not pending).
- **The `rejected` BANNER does not require the rejected cell to be in the
  model.** The rig refused; that is worth saying either way. Only the block-level
  `rejected` appearance needs an identified block.

`banner` precedence is `locked` → `stale` → `running` → `rejected` → `none`.
**LOCKED beats a dropped socket on purpose:** a locked session that has also
lost its socket is still a locked session, and that is the more expensive fact.

`twinSignature(state, progress, options, build)` is the other rule in here. The
server now publishes a state snapshot only when something semantic changes, and
throttles camera-geometry-only snapshots to ~5 Hz, but the signature stays: it
states exactly what the picture depends on — including the build phase — and
`TwinPanel` recomputes the scene, and therefore redraws the canvas, only when it
changes.

### The twin is phase-driven, and there is no descent timer

`twinScene(..., build)` takes the `BuildProgress` the store folded out of
`build_step` events, and `twinPhase()` maps the firmware's phase id to one of
seventeen visual states. `PHASE_BY_ID` is the whole mapping and `twin.test.ts`
asserts every row of it against the fourteen ids in `plans/ack-protocol.md`.

`descentOffsetScene()` **is gone.** It interpolated a looping 1.6-second descent
off `performance.now()` and returned a height nobody had measured — and it
looped, so a forty-second build showed twenty-five descents that had never
happened. It was honest about being an illustration in its own docstring, and it
was still the thing on screen that an operator would read as position.

What replaced it says only what the firmware said:

- `blockOffset` is `phaseOffsetScene(phase)` and has **exactly two values**:
  travel height while the rig is carrying (`lift_block`, `move_to_target`,
  `rotate_to_grid`, `lower_to_level`), and zero otherwise. It drops to zero on
  the release event, which is a fact.
- `descent` is the one animation a clock drives, and only during
  `lowering-to-level`. `descentProgress(elapsed, etaMs)` interpolates
  `blockOffset` down toward the cell over the duration the FIRMWARE sent as
  `ms=` — for the shipped calibration, `2565 - 145*K` ms for level K, measured
  on the rig at 2.6-2.8 s for a full travel against 2.57 s predicted. Four
  fences make it a claim rather than a fiction: it starts from the moment the
  phase event ARRIVED, its duration is the machine's own arithmetic (the
  browser keeps no copy of `Z_TRAVEL_STEPS` or `BLOCK_HEIGHT_CM` — AGENTS.md
  forbids one), it is clamped at `DESCENT_CLAMP = 0.92` so it **cannot reach
  the cell**, and with no `etaMs` it does nothing at all rather than guessing a
  duration. If Z jams, the block glides down, stops just short and sits there
  visibly not landing — which is the truth.
- `indicator` says the phase is motion, and the component pulses OPACITY for
  it. An opacity pulse cannot be misread as a position; an interpolated height
  can.
- `carrying` runs from `grip` to `release`, and drops the moment phase 11's
  `status=done` arrives.
- `released` is that same `done`. It is **not** `placed`: the block is on the
  stack but the command is still running and the rig still has to park. Only
  the terminal `build_result` sets `phase: "placed"`.
- A dead socket freezes everything: the last phase stays on screen, because it
  is the last thing known, and `animating`/`indicator` both go false, because
  "still going" is exactly what nobody can tell.
- `LOCKED`/aborted beats every phase, stops the animation dead, and never
  places anything.

If exact continuous motion is ever wanted it has to come from throttled
firmware telemetry inside the movement loops — never from a clock in a browser,
and never by raising the baud.

`twin.fixtures.json` is dumped by `python/tools/dump_twin_states.py` from
`web.app` running against `MockBoard`: three sessions — placed, rejected,
aborted — one entry per state the socket would have delivered. The mapping is
tested against what the server actually sends, not against payloads the test
invented. Same bridge as the coordinate fixtures: **when the two disagree,
Python is right.**

---

### 5.14 `studio/runner.ts` — the program is not a queue

`step(runState, event) → { state, effects }` is the whole runner. Its phase is
the named union from Plan 4 §10: `idle`, `arming`, `verifying`,
`awaiting-confirm`, `building`, `settled`, `rejected`, `aborted`, `paused`,
`stopped-mismatch`, `locked`, `done`. `inFlight`, the last observed server
`buildState`, and connection state are explicit fields; none is inferred from
three unrelated booleans in a component.

Effects are descriptions only: `select`, `verify`, `build`, `mode`, `warn`.
The normal build transition is exactly:

```text
POST /api/level only when the level differs
POST /api/select for a camera-mapped cell, or /api/select/axis for a zero-axis cell
verify returned state.command byte-for-byte against op.text
POST /api/build { confirm: true, command: op.text }
wait for RUNNING → terminal server state before advancing
```

There is no effect for a batch, cancellation or retry. A mismatch becomes
`stopped-mismatch`, preserves `program` and both strings verbatim, sets the run
read-only and emits nothing. `REJECTED` keeps `cursor` on the same op and offers
only continue/end. `ABORTED` becomes `locked`, leaves the reached step visible
and has no outgoing recovery transition. Socket loss becomes `paused` at once;
reconnection does not resume automatically, but allows a deliberate continue
only after state messages are audible again.

The safety test walks every candidate event out of every reachable canonical
state for STEP, RUN and DRY RUN. It fails immediately if a turn emits more than
one `build`, emits a second one while `inFlight`, or describes a real
select/build/mode while the resulting state still says `RUNNING`. This is the
proof M7 exists to supply; `routes_command.require_mutable`, `BuildJob.start`
and `BuildController` still repeat the guard server-side.

Feeder guidance is pure too. Before START it shows the first block. Once a
build is in flight that block has already left the feeder, so the prompt uses
the otherwise-dead motion window to show the next block's colour and command.
Repeated colour becomes the quiet `SAME COLOUR` line. That is how continuous
RUN remains compatible with a manual feeder instead of flashing an instruction
after it is too late to act on it.

### 5.15 `runner-driver.ts` and `run-report.ts`

`executeEffect` is the thin transport. Real effects check the latest observed
state immediately before calling the existing functions in `api.ts`; the
backend remains authoritative. An arbitrary cell uses the centre of the
server-supplied camera polygon. Row-zero/column-zero targets use the existing
axis route. A build request returns only `build-running`; the WebSocket state,
not the POST response, supplies the terminal result.

DRY RUN executes the same reducer with fake select/mode/build transport. It
never calls an API method; a fake build settles after 600 ms. A 24-block build
therefore rehearses in about 14.4 seconds plus mode effects and UI scheduling,
inside the plan's approximate twenty-second target.

The report is built only from `RunLogEntry` values produced by terminal events,
never from intended program lines. Its deterministic Markdown table records
command/result/duration and optional vision verification; totals and failures
follow, including verbatim mismatch strings. On each real terminal result the
driver attempts a 320 px WebP capture of the live MJPEG image. Capture failure
is non-fatal and simply leaves that evidence row without a thumbnail.

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
each into solid and 42%-opacity batches. Instance colour comes from the five
original `--block-*` tokens plus `--block-white`; new blocks default to white
(now a warm `#F0E7D5` birch, not the old cold near-white).
A new block fades over 130 ms while settling from +8 mm over 220 ms. Distinct
rows in one run start 34 ms apart. Per-instance opacity keeps the whole gesture
in one arriving draw, while the solid/x-ray split remains ordinary materials.
Arrival state, matrices and opacity live in refs; `useFrame` exits before doing
any matrix work when no arrival exists, and `invalidate()` runs only while one
is active. Reduced motion places immediately.

Instanced batches mount empty, so the first colour attribute appears only when a
block is placed. `Blocks.tsx` explicitly recompiles that material once when the
attribute is created; without it, Three.js retains its empty-batch program and
renders the missing vertex colour black. Every block carries a faint
`--block-wood` emissive (intensity 0.1 solid / 0.06 twin) and a matte
`roughness` of 0.72 — a warm timber undertone that reads as a solid object, not
the lit-from-within plastic the old cold-white emissive at 0.22 gave.

`Ghost.tsx` uses the active mode's same rounded dimensions. A clean preview is
`--block-wood-soft` at 62% — the wood the block will actually be — while a
warning stays `--motion` and an illegal placement `--danger` at 50%, each with a
solid edge and one reason label. Severity keeps the reserved state colours; only
the "this is fine" case went woodish. It has no raycast of its own and
disappears when the surface target is null.

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
selected card takes a `--signal` 1 px border and never a fill, and — when it is
the build the editor is actually tracking — a small `CURRENT` tag after its
name. Hover lifts the border to `--line-strong`.

#### Saving a build — `Studio.tsx` owns it, the drawer delegates

Saving used to be a single unlabelled button inside the library drawer, with a
silent success and no first-save name. The route now owns the whole flow:

- **`SAVE` is in the toolbar** next to `LIBRARY`, plus **Ctrl/Cmd-S**
  (`interaction.ts`, §5.6). The drawer keeps its own `SAVE` button but it just
  calls the route's `onSave`; its self-contained `save()` path survives only as
  the fallback when no `onSave` is passed, which is what `LibraryDrawer.test.tsx`
  exercises.
- **`savedId: string \| null` is the identity the editor tracks.** `null` means
  "never saved" — a blank build, or one opened from a built-in example
  (`isExampleId`), so the next save **mints a fresh id** and asks for a name in
  a small centred sheet rather than overwriting anything. A tracked build
  overwrites itself with no prompt.
- **`dirty`** is `signatureOf(blocks, order, name) !== savedSignature`, guarded
  so an empty never-saved build is not "unsaved work". It drives a `--signal`
  dot on both `SAVE` buttons and an `— unsaved` tag after the model name, and
  arms a `beforeunload` confirm — the only `beforeunload` in the Studio.
- **Success is a toast, never silent** (`--ready`, auto-dismiss 2.4 s):
  `Saved "name"`. A refusal — storage unavailable, over budget — is an amber
  toast (5.2 s) that **also opens the library**, because the full remedy with
  its "delete the three largest" controls already lives in the drawer strip.
- `openDocument` resets `savedId` and `savedSignature` together with history, so
  a freshly opened model reads as clean and an opened example reads as a new
  unsaved build.
- **The drawer's card list stays live across a delegated save.** Because the
  write now happens in the route, not in the drawer, the drawer would otherwise
  never re-`listModels()` — a card saved from the toolbar or Ctrl/⌘S only
  appeared after a remount. `Studio.tsx` bumps a `savedTick` counter on every
  successful write and passes it down; the drawer re-reads storage on that, on
  `open` going true, and on mount. Deleting a design is the per-card `DELETE`
  with its six-second undo, unchanged — it just now shows up on a design you
  saved a moment ago instead of after a reload.

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

### 6.11 `RunnerPanel.tsx`

The runner sits below the camera/twin instrument. It compiles the model already
chosen in the twin; while any non-terminal-safe run state is preserved, that
picker is disabled so the picture and program cannot diverge. The component is
a driver and a drawing surface: it applies reducer turns, executes their effect
descriptions, and folds WebSocket terminal state back into events. It does not
decide ordering, commands, feeder sequence, ETA or failure policy.

STEP reuses the console's existing `BuildButton`, including its expiring
two-tap arm; `BuildButton` gained only an optional callback at the point where
it would otherwise call `api.build`. RUN exposes `STOP AFTER THIS BLOCK`, and
the always-visible line underneath says `the block in flight will finish — the
rig cannot be interrupted`. Pressing it changes the disabled control to
`STOPPING AFTER THIS BLOCK`; it does not alter the current effect. DRY RUN keeps
`DRY RUN — no serial traffic` in `--motion` for the full session.

Mode ops always stop at `awaiting-confirm` and render the X/Y homing warning
before the driver may call `/api/mode`, in all three styles. Amber is used for
recoverable rejection/staleness and the dry label; red is reserved for command
mismatch and the locked abort. Reduced motion disables every runner transition
or animation; the console's RUNNING banner remains the only ambient motion.

---

## 7. Routing and code-splitting

`routes/Root.tsx` is the whole of the routing: the console at `#/`, building
mode at `#/build`, the Studio at `#/studio`, with `React.lazy` around the Studio
import so three.js lands in its own chunk. Building mode is **not** lazy — it
reuses the console's own components and pulls no three.js of its own (its twin
lazy-loads the canvas the same way the console's does). **Hash routing,
deliberately** — it needs no server rewrite, which matters because the Pi serves
this as static files and the PWA offline shell has to keep working.

`Root.tsx` also owns the single `connectEvents` subscription for the life of the
page, reading the `consoleStore.ts` module singleton, so moving between `#/` and
`#/build` never drops the socket.

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
- The performance/UI pass added `--block-white`, the default placed-block colour;
  a later pass warmed it to birch and added `--block-wood` / `--block-wood-soft`
  for the material undertone and the ghost/preview boxes. All three are object
  colours, not state — the reserved `--ready` / `--motion` / `--danger` are
  untouched.

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

- **The full five-block tower was exercised through a real `python -m web
  --mock` process and the guarded HTTP routes**, including level, selection,
  exact command verification, build and terminal polling. The five cycles were
  2.113 / 2.108 / 2.112 / 2.104 / 2.140 s (mean 2.115 s). This confirms the
  backend sequence and supplies the estimate constant. It is not a browser E2E
  test and not a physical-rig measurement; Vitest covers the browser driver
  against the same API shapes.
- **Camera thumbnails are best-effort browser evidence.** A same-origin MJPEG
  frame is copied into a 320 px canvas after each terminal result. jsdom tests
  the sizing/encoding contract, but a headless browser was not used to inspect
  the resulting pixels. A tainted or unavailable canvas omits the thumbnail
  rather than losing the run report.
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

### Stable instanced blocks and explicit wheel zoom

The Studio and twin refresh Three.js's cached `InstancedMesh` bounding sphere
whenever block, shadow or lattice instance matrices are rewritten. Previously
the stale initial bound could hide a batch whose blocks were still visibly
inside the view, depending on camera angle and distance. Correct bounds retain
normal frustum culling, so a genuinely off-screen batch still costs no fragment
work. Animated arrivals refresh only while their existing short animation loop
is active; static scenes add no frame-loop work.

`scene/RigOrbitControls.tsx` now owns the canvases' wheel contract. It handles
the wheel at capture time and calls the controls' public dolly methods directly:
wheel down (positive `deltaY`) always zooms out and wheel up always zooms in.
The outward limit is 700 scene units instead of 260; the camera far plane
remains 800. SYNC VIEW in the twin still disables orbit and zoom intentionally.

### Woodish blocks; ghosts you can actually see

The blocks read as timber now, and the whole opacity ladder went up.

- **New object tokens** in `style.css`: `--block-wood` (`#D49A5A`, solid oak)
  and `--block-wood-soft` (`#EFC48C`, luminous tan). `--block-white` was warmed
  from the cold `#F4F7FA` to `#F0E7D5` birch — it is still the default block
  name and the feeder swatch. The five saturated `--block-*` hues are untouched:
  they still mirror `web/geometry.py` `_colour_name()` for the camera overlay,
  and `_colour_name()` never returns white, so warming it costs no parity. These
  are workpiece colours, in the same non-state family as the detection hues, so
  DESIGN.md §2's "saturated colour is reserved" still holds — the state colours
  `--ready` / `--motion` / `--danger` / `--signal` were not touched or reused.
- **The 3D material** (`Blocks.tsx`) drops the cold-white emissive for a
  `--block-wood` one at intensity 0.13 (0.16 twin) and raises `roughness` to
  0.72. Placed blocks were already fully opaque (`opacity 1`, `depthWrite`
  true); the change is that they now look it — matte timber, not backlit
  plastic — and the warmer emissive lifts every block clear of `--void`.
- **Opacities up** (`twin.ts`): remaining-work ghost `0.2 → 0.6` and recoloured
  `--text-faint → --block-wood-soft` (a translucent block over `--void` bleeds
  lightness and chroma into the black, so it has to start high); `target`
  `0.45 → 0.62`; `building` `0.85 → 0.9`; held-level x-ray batch `0.15 → 0.42`.
  `rejected` split off its own `REJECTED_OPACITY = 0.34` and stays grey — inert,
  still dimmer than a live ghost. New exported constants: `GHOST_TOKEN`,
  `REJECTED_OPACITY`.
- **Twin lighting** (`scene/Twin.tsx`) up: hemisphere `0.5 → 0.62`, key
  directional `1.1 → 1.4`, so blocks read against the dark stage without leaning
  entirely on opacity.
- **LOCKED** now forces every token to `--text-faint` explicitly in the mapping
  rather than leaning on `TOKEN.ghost` pointing there, so the freeze survives
  the ghost token changing.
- **`Ghost.tsx`** clean-preview colour `--signal → --block-wood-soft` at
  `0.35 → 0.62`; illegal `0.30 → 0.5`. Warning/error keep `--motion` / `--danger`.
- `twin.test.ts` tracks the two renamed constants; all 489 web tests stay green.

### The live block overlay: one colour, one rectangle, one bearing

The feeds drew `block_detector`'s raw segmentation contour, one of six cycling
colours per block. On a full board both halves worked against the operator: a
mask edge wanders a pixel or two all the way round, so twenty-nine outlines that
should read as one grid read as twenty-nine wobbly shapes, and adjacent
outlines in unrelated colours read as unrelated objects.

`vision/block_outline.py` `detect_aligned_blocks()` is a drop-in replacement
(same `BlockDetection` type, so the overlay, hover test and snapshot code are
untouched). It drops IoU duplicates, anything running off the frame, and —
given a `MachineGrid` — anything not on the lattice the other blocks describe,
which is what removes the holder's two offcuts beside `[0,0]`. Survivors are
redrawn as true rectangles carrying the population's median size and the
lattice's bearing. Measured on both reference boards: **33 detections → 29**,
every corner exactly square, ~50 ms.

`camera_feed.BLOCK_COLOR` is now a single stroke, with the hovered block
differing by brightness rather than hue.

Two things a future reader will be tempted to change and should not. The
centres are **never** snapped to the lattice — sharing size and bearing is what
makes a board read as a grid, but snapping positions would hide a misplaced
block, which is the one thing this overlay exists to show. And the calibrator's
full-resolution flattened detection settings were tried and reverted: measured,
they find not one extra block at any width and cost up to four seconds a frame.
A timing guard in `test_block_outline.py` (25 checks) keeps that from returning.

Full treatment in the new `docs/BLOCK-VISION.md`; `AGENTS.md` §3d-ter carries
the rules.

### Fix: a saved calibration never reached a running console

Two independent reasons a `blockcalsave` on the Pi appeared to do nothing, both
now fixed and both regression-tested.

**The console never re-read the file.** `config/workspace_map.json` is loaded
once at `ConsolePipeline.start()` and again only inside `set_grid_mode()`. The
rig workflow is to calibrate from a *separate* process — Camera Studio, or
`camera/block_grid_calibrate.py` — while the console runs, so the new map sat
on disk unread until a restart, with nothing on screen saying so. Added
`ConsolePipeline.reload_workspace()`, `POST /api/calibration/reload`, a
**Reload saved calibration** button in the Calibration panel, and `L` in
`rig_build_v1`. A map that is present but refused now surfaces its reason
(400 + the sentence) rather than silence — "no calibration saved" and "camera
lens/orientation/framing changed" need opposite responses.
`tests/test_workspace_reload.py` asserts the full sequence, including that a
running console does *not* adopt a map on its own.

**And a third, found by checking rather than assuming.** Camera Studio stamps
the map with its LIVE geometry, but the app renders from `camera_settings.json`
— so any unsaved crop, zoom, lens tweak or correction toggle made the saved map
refusable by everything. `blockcalsave` now compares the two and refuses up
front, naming which of view/lens/orientation/roi drifted, rather than letting
the app reject it later. `test_calibration_parity.py` additionally asserts that
the block and paper routes write a *byte-identical* `workspace_map.json` — if
those ever diverge the app adopts one and silently refuses the other, and the
only symptom is the one reported here.

**The Studio's confirmation was ambiguous.** That window's SAVE JSON button and
its autosave both write `camera_settings.json`; `blockcalsave` writes
`workspace_map.json`. An unqualified "saved" could reasonably be read as the
wrong one. It now names the file, the grid mode and its dimensions, and says
how to make a running app pick it up.

### Fix: a block calibration saved from Camera Studio was never adopted

`blockcalsave` built its `WorkspaceMap` without a **projection** — the lens /
flip-rotate / correction / framing identity that `load_workspace()` compares
against its own before trusting a map. So the file was written, reported as
written, and then refused by every consumer with "camera lens/orientation/
framing changed". The worst shape of bug: it looked like it worked.

The Studio has everything needed (`profile`, `flip`, `rotate`, `correct`,
`roi()`); it simply was not passing it. `Studio.projection()` now builds it and
`blockcalsave` stamps the map with it. The web route and
`camera/block_grid_calibrate.py` were always correct — both pass
`pipeline.projection` — so only the Studio button was affected.

While there: `blockcalsave` now reports how far the saved map's cells land from
the measured ones. `workspace_map.json` carries four envelope corners and the
grid geometry, not a per-cell table, so a consumer spaces cells evenly between
them and any curvature the fit found is flattened on the way out. The corners
come back exact and the error peaks mid-grid. On the reference board that is
1.25 px mean / 2.07 px max — 0.27 cm on a 2.2 cm block. Removing it would mean
widening the `WorkspaceMap` format, which touches every consumer; reporting it
is the honest interim. `test_block_grid.py` §11 asserts both halves.

### Placed-block calibration is now the console's first calibration route

`Calibrate.tsx` used to offer two ways to make a workspace map: click four
corners, or detect the printed sheet. Both measure the camera against something
a human positioned, and the sheet route then has to *assume* the paper sits
where the firmware's cells are — which is what `HOME_CONVENTIONS` in
`python/vision/color_grid.py` exists to paper over.

The new first choice, **Calibrate with blocks**, has the rig place a block on a
cell it was told and measures where it landed. The correspondence is labelled
at the source, so there is no lattice to infer and no paper to disagree with,
and it measures the real pick-and-place chain rather than a printed
approximation of it. The other two routes are unchanged and still offered.

UI-side notes for a future reader:

- Each step is **one full pick-and-place**, minutes of machine motion, so the
  panel names the cell the rig is about to place on (an operator watching the
  machine needs to know where to look), keeps its button busy for the duration,
  and the backend refuses a second step while one is in flight.
- **SAVE stays disabled until the backend says `ready`,** never on a count. Four
  placements fit a homography exactly and prove nothing, so the floor is five —
  but that rule lives in `vision/block_grid.py`, and duplicating it here would
  be a second place to get it wrong.
- A **refused step is not a lost run**: the error shows, the placements already
  made are kept, and the same cell can be retried. An **abort** is different —
  the claw may still be holding a block, so `finished_reason` is set and every
  step button is disabled with no retry offered.
- `api.calibration.block.*` mirrors the `/api/calibration/block/*` routes; the
  server is authoritative for all of it, including the residual readout.

`AGENTS.md` §3d-bis documents the mechanism, its gates and its one structural
limitation. Python side: `vision/block_grid.py`, `rig/block_calibration.py`,
`camera/block_grid_calibrate.py`, and BLOCK CALIBRATION buttons in Camera
Studio. `blockCalibration.test.tsx` +4; no change to any existing test.

### Building mode pass 2 — the twin mirrors the rig, not just the model

Two changes, both aimed at "the twin is a picture of the machine first".

**The twin always draws its workspace.** `TwinPanel` used to replace the whole
canvas with a `NO MODEL LOADED` plate. It now always mounts `<Twin>`; the
envelope, the lattice and the feeder are the Studio's own, model or not.

**The twin now shows blocks the rig placed that no model describes.**
`twin.ts` gained `TwinProgress.pendingCell` (the in-flight `B c r l`, parsed
from `state.command` and kept across the state where the server clears the
selection — exactly how `pendingId` already works) and `TwinProgress.placements`
(every confirmed placement no model block covers). `twinScene` appends a solid
`--block-white` block for each `placements` cell, and — while such a build is in
flight — a synthetic `building` block so the descent animation (`scene.descent`,
the firmware's `ms=`) runs through the **same** `Building` component and the
same path as a model target. Model placements are unchanged: they still light up
by id via `confirmed`, and a placement a model block already owns is not
double-drawn. New helpers: `parseBuildCommand`, `samePlacedCell`, `PlacedCell`.

### Building mode pass 2 — the `#/build` layout

The route is now camera + twin (an **equal** 1 / 1 split), a collapsible
library, toasts, and a floating control cluster bottom-right over the twin's
dead space. The bottom dock is gone. `RunnerPanel` gained an optional
`compact` prop: it drops the phase readout, the feeder card, the elapsed/ETA
line, the run-report table and the read-only program dump (all now toasts) and
keeps only the buttons an operator presses. The state machine and every guarded
route are untouched; the console renders the panel without the flag and looks
exactly as before.

### Building mode — the `#/build` fullscreen route

A third route beside `#/` and `#/studio`, for the moment the rig is actually
running a program: the live camera and the twin side by side and nothing else,
with status as toasts and the guarded runner in a thin bottom dock. New files
under `web/src/components/buildmode/`:

- `BuildMode.tsx` — the route. Owns no machine authority: it reuses
  `CameraView`, `TwinPanel` and `RunnerPanel` unchanged, and every action still
  travels the same guarded `/api/*` path the console uses. It shares the twin's
  `TWIN_MODEL_KEY`, so a build chosen here is the build the console shows.
- `useBuildToasts.ts` / `ToastStack.tsx` — a keyed toast queue. A byte-identical
  repeat of the newest-content-for-a-key is dropped (the phase stream re-sends
  ~20×/s); changed content refreshes that toast in place with a fresh expiry;
  sticky toasts (lock, lost socket) stay until dismissed and `SOCKET LOST`
  clears itself on reconnect. Cap 4 visible, 6 s TTL.
- `BuildLibrary.tsx` — a slide-over picker over `twinModelChoices()` with the
  runner's own compiler estimate per model. It only *selects*; rename/delete/
  import stay in the Studio's `LibraryDrawer`.

Store change: `createConsoleStore()` moved from a module local in `App.tsx` to
the `web/src/consoleStore.ts` singleton, and the single `connectEvents`
subscription moved to `routes/Root.tsx`, so switching between `#/` and `#/build`
never tears the socket down mid-build.

`RunnerPanel` gained one optional prop, `onToast`. It is a pure mirror of state
the panel already derives (the feeder prompt, the run phase, the confirm
prompt); the console mounts the panel without it and nothing about the runner's
behaviour changes. `TWIN_MODEL_KEY` and its `storedModelId` / `rememberModelId`
helpers are now exported from `TwinPanel.tsx`.

### Server-side run logs for builds dispatched from the console

A real backend run (`python -m web`) now appends two plain-text files under
`logs/` at the repo root — git-ignored, opened in append mode, no rotation:

- `logs/build.log` — one stopwatch section per `/api/build`: the request, the
  job handoff, the board `RECV`, every firmware phase with the firmware's own
  ETA beside the measured duration, and the settled result with total elapsed.
- `logs/serial.log` — every line to/from the Arduino, each with the wall clock
  and the gap since the previous line, so a stall reads as a large delta; the
  terminal ack and a `-- final: …` line close each build.

Off by default (every call a no-op); `web.app.main()` calls
`rig.build_log.configure()`, so `pytest` never writes to `logs/`. The Studio's
runner is unchanged — it still dispatches one guarded `/api/build` at a time;
this is purely observability on the server side of that call. Code:
`python/rig/build_log.py`, wired from `web/app.py`, `web/routes_command.py`,
`rig/link.py`. Operator notes in `docs/server-guide.md` §7. Sizing: ~6–7 KB per
block placed; a 200-block model run is ~1.3 MB.

### Fix: the Studio library drawer could never read a saved model

Saved builds showed on the index page but **not in the Studio's own library
drawer** — only the three examples, so no card, so no `DELETE` button. Cause:
the drawer built `const options = { storage, settings }` from a `storage` prop
the real app never passes, so `storage` was `undefined` *but the key was
present*. `library.ts` reads `"storage" in options ? options.storage :
browserStorage()`, so a present-but-undefined key **pinned storage to
"unavailable"** — every read returned nothing. `TwinPanel` was unaffected
because it calls `listModels()` with no argument at all, so the key is absent
and the `localStorage` fallback runs.

Fix is in the drawer only: spread the `storage` key **only when it is set**
(`storage ? { storage, settings } : { settings }`), in both the memo and
`refresh()`. `LibraryDrawer.test.tsx`: the "unavailable" test now passes a
stub that throws on access (a real private-mode store) instead of relying on
`storage={undefined}`; +1 regression test that a drawer with no `storage` prop
lists a model really in `localStorage`, `DELETE` button and all. No change to
`library.ts` or the storage format.

### Follow-up: the library drawer re-reads storage after a toolbar/Ctrl-S save

The save flow below moved the write into `Studio.tsx`, which left the drawer's
own `listModels()` running only on mount — so a design saved without opening the
drawer did not appear in it until a remount (it did show on the index page,
which builds its picker fresh each mount). Fixed by a `savedTick` counter the
route bumps on every successful write and the drawer re-reads on, alongside
`open` and mount. `LibraryDrawer.test.tsx` +2 (delegated SAVE writes nothing
itself; a `savedTick` bump and a reopen both re-list). No storage-format or
`library.ts` change; per-card `DELETE` + undo was already the delete path.

### Saving a build is a first-class action, with a name and a confirmation

The library and its `localStorage` CRUD were already delivered in M5; what was
missing was a save flow anyone would find. Saving lived behind the `LIBRARY`
drawer, wrote `Untitled` with no prompt, and succeeded silently.

- **`interaction.ts`**: new `"save"` keyboard action for **Ctrl/Cmd-S**;
  `interaction.test.ts` +1 (browser-default suppression asserted). It is
  `preventDefault()`d in `Studio.tsx` like every other action.
- **`Studio.tsx`** now owns saving: a toolbar `SAVE` button beside `LIBRARY`;
  `savedId: string | null` as the tracked identity (`null` for a blank build or
  one opened from an example — `isExampleId` — so the next save forks a fresh
  id and prompts for a name in a centred sheet); a `dirty` fingerprint
  (`blocks + order + name` vs the signature at the last save/open) driving a
  `--signal` dot on `SAVE`, an `— unsaved` name tag, and a `beforeunload`
  confirm; a `--ready` success toast (`Saved "name"`, auto-dismiss 2.4 s) and an
  amber refusal toast that also opens the library so its delete controls are to
  hand. `openDocument` resets `savedId`/`savedSignature` with history.
- **`LibraryDrawer.tsx`**: new optional `onSave` / `dirty` props. Its `SAVE`
  button delegates to `onSave` when given (the route path) and keeps its
  self-contained `save()` only as the fallback — which is the path
  `LibraryDrawer.test.tsx` still drives, so all 20 of its tests are untouched.
  Dirty dot via `[data-dirty]`; a `CURRENT` tag on the tracked card; a clearer
  card hover; empty-state copy now names Ctrl/⌘S.
- No change to `library.ts`, `rigmodel.ts` or the storage format. The console
  entry still ships no `WebGLRenderer`; `Studio-*.js` +2.5 kB.

### Serial-driven build progress — the firmware says what it is doing

The console could not tell an operator anything about the forty seconds between
"RUNNING" and "READY", so the twin illustrated a descent that had not happened
and the runner had only coarse state to go on. The firmware now reports every
phase and the whole stack carries it.

- **Firmware** (`build_test_v1.ino`): `buildStep()` emits
  `@n STEP step= total= phase= action= text= status=begin` before each of the
  fourteen phases, plus one `status=done` at phase 11 (the confirmed release,
  which nothing else can carry because `BUILD_PARK_AFTER_PLACE` may be false).
  `handleBuildCommand()` emits `@n RECV` when the arguments parse. New
  `ackWord()` — deliberately NOT an `ackField()` overload, because `0` is also
  a null pointer constant and the overload would make every numeric call site
  ambiguous. Baud is untouched: fourteen lines is ~0.3 s of 9600-baud airtime,
  and per-step telemetry would be minutes of it. Verified byte-for-byte on a
  host g++ stub build; **not flashed.**
- **Pi** (`rig/link.py`): `SerialProgress`, `parse_progress()`, and
  `on_progress` / `on_ack` constructor callbacks called on the reader thread in
  wire order. `MockBoard` speaks the same stream so the console is testable
  off-rig, with `fail_next_build(..., at_step=)` for a mid-carry abort.
- **New `python/web/events.py`**: the durable/coalesced split. `serial`,
  `build_step` and `build_result` are delivered once each in order and kept in a
  replay buffer; `state` is coalesced to one pending snapshot per client.
  Durable first, always — camera geometry can no longer delay a build phase.
  Every event has a monotonic id and a timestamp.
- **New `python/web/progress.py`**: the status machine, `idle → accepted →
  validating → running → parking → placed | rejected | aborted | locked`. It is
  the only route to a terminal status, and `placed` comes from the terminal OK
  and from nothing before it.
- **`web/app.py`**: `process_once` and `cv2.imencode` moved to ONE dedicated
  worker thread (not the default pool — `AGENTS.md` §7's single-owner rule), so
  the loop stays free for serial callbacks. State snapshots publish immediately
  on a semantic change and at `geometry_hz` (5) otherwise, instead of 20 Hz
  unconditionally. `/api/events` accepts `?after=<id>` and replays.
- **Browser**: `store.ts` folds events into a `BuildProgress` and deduplicates
  by ID — never by text overlap, which used to swallow a genuinely repeated
  serial line. `ws.ts` lost its `setTimeout` batch entirely; a phase reaches
  React on the turn it arrives. The runner shows the rig's own phase and
  still advances only on a terminal `placed`; `runTiming` survives as an
  estimate and is now labelled `(est.)`.
- **The twin**: the looping invented `descentOffsetScene()` deleted, phase
  mapping added, and a real placement descent put in its place — the firmware
  sends `ms=` (its own step-count arithmetic) on the Z phases, and
  `descentProgress()` animates it from the event's arrival, clamped at 0.92 so
  only the release event can land the block. See §6 above. `twin.fixtures.json` regenerated and now carries the recorded EVENT
  stream as well as the states, so the phase mapping is tested against what the
  server actually sends. The recorded abort now dies at phase 8, mid-carry,
  which is the case the twin has to get right.
- **Still true and worth restating:** there is no continuous position telemetry.
  The firmware reports phases. Nothing in this stack knows where the arm is
  between them, and nothing in it is allowed to pretend otherwise.

### Horizontal grid error offset → +0.5 cm X / +0.3 cm Y

- `config/rig.json` `grid.modes.horizontal`: `error_offset_x_cm` 0.0 → **0.5**,
  `error_offset_y_cm` 0.0 → **0.3**, with the firmware's
  `GRID_ERROR_OFFSET_{X,Y}_CM` horizontal slots moved to match (they are a
  paired value, `test_grid.py` asserts it). Measured on the rig: placed blocks
  were landing 0.5 cm (X) / 0.3 cm (Y) toward the home switches, so every
  horizontal centre is nudged that far away from home. This is rotation slop
  from the 90° CCW pickup-rotate not pivoting on the exact block centre — a
  constant per-mode error, **not** part of the +1.9 cm registration trim.
- Studio consequence: every horizontal cell centre moves `+5 mm` X / `+3 mm` Y.
  `coords.ts` already folds `error_offset` into the origin, so `cellToMachine`,
  the twin and the lattice picked it up for free. `coords.fixtures.json`
  regenerated from Python; the `horizontal shift y -2.0 refused` fixture is now
  **accepted** (the +0.3 cm Y headroom keeps cell 0 on the machine), so the
  dumped cell total rose 980 → 1040.
- `axisFits` / `reachableCells` (the shift-clip count) include `error_offset`,
  matching Python's `MachineGrid._axis_fits`; only the *requested-grid*
  geometry check strips it (Python `_assert_fits(ignore_shift=True)`, firmware
  `gridGeometryFits`). So horizontal's last-column clip boundary tightened by
  0.5 cm — `geometry.test.ts` block-edge test moved 5.7/5.8 → 5.2/5.3 — and the
  cross-mode overlap test now reads vertical column 3 rather than 2.
- `coords.test.ts` cell-0 assertion updated to 24 mm / 22 mm (`trim + error
  offset`). `test_grid.py` `SECTION_3` horizontal table recomputed. No plan
  §1 decision changed; `dual-orientation-grid.md` §3's calibration note carries
  the number.

### Support is a centre-of-mass toppling test, not a contact-ratio bypass

- `supportMetrics` now reports `centreStable` (was `centroidSupported`): the
  block's centre of mass projects into the **convex hull of its contact
  patches**, via new `geometry.convexHull` / `geometry.supportPolygonContains`.
  `unsupported` fires unless contact clears the operator's `supportRatio`
  **and** `centreStable` holds. `CENTROID_BYPASS_RATIO` is deleted.
- This replaces both failure modes of the fixed 70% bypass. A symmetric bridge
  **below** 70% contact whose centre of mass sits between its supports is now
  legal; a **high**-contact block cantilevered past its supports is now
  rejected. The old code did the opposite on both. The built-in two-tower
  bridge stays legal at `BRIDGE_SHIFT_CM = 0` — now because its centre of mass
  lies inside the two-tower hull, not because 73.3% ≥ 70%. This supersedes the
  "Support centroid bypass at 70% contact" entry below.
- `geometry.EPS_MM` (1e-3 mm) is now the one shared millimetre-slack constant:
  it replaces the 1e-6 mm "resting on" Z tolerance in `supportMetrics` (a
  nanometre test that could silently drop a real support) and the inline
  `edgeOverhang` epsilon. Footprint overlaps under 0.01 mm² no longer count as
  support (`supportIds`).
- `supportMetrics` still counts **every** block beneath, in any author order:
  `validateModel` answers "is this structure buildable", and `compile.ts`'s
  support graph + Kahn walk own the build sequence. Restricting support to
  earlier-in-order blocks was tried and reverted — it broke the compiler's
  documented ability to repair an illegal author order.
- Settings copy, `validate.test.ts`, `geometry.test.ts` and `examples.test.ts`
  updated to match.

### Support centroid bypass at 70% contact

- `validate.ts` now accepts a placement when it meets the operator's configured
  `supportRatio` and either its centre is supported **or union contact is at
  least 70%** (`CENTROID_BYPASS_RATIO`). The configured minimum still wins if
  somebody raises it above 70%; the bypass removes only the extra centroid veto.
- Added the exact regression fixture reported by the Studio: a horizontal span
  centred over the 1.6 cm gap has 73.33% contact and an unsupported centroid.
  It is now legal. Lower-contact bridges still need their centre supported.
- The built-in two-tower bridge no longer carries a synthetic `shiftX +1.00`
  workaround. `BRIDGE_SHIFT_CM = 0`; it opens at the shipped +1.9 cm
  registration with no support or geometry-drift diagnostic. This supersedes
  the bridge-retuning note immediately below and Plan 4 §6.5's unconditional
  centroid clause.
- The Studio settings copy names the 70% behaviour so the visible control and
  validator no longer tell different stories.

### Horizontal grid registration → +1.9 cm on both axes

- `config/rig.json` `grid.modes.horizontal`: `trim_x_cm` 0.0 → **1.9**,
  `trim_y_cm` 1.6 → **1.9**. The registration is now symmetric: the block is
  picked up standing at the vertical `[0,0]` feeder and rotated about the grip,
  and the rotated 6.0 cm face overhangs the 2.2 cm vertical footprint by
  `6.0/2 − 2.2/2 = 1.9 cm` per side, so a +1.9 cm trim on each axis seats
  horizontal `[0,0]` flush against the vertical `[0,0]` block edge. Supersedes
  the earlier single-axis `trim_y = +1.6` ("one gap width"), which the docs
  (AGENTS.md §6C diagram vs prose, `dual-orientation-grid.md` D14) had never
  agreed on. Firmware `GRID_TRIM_{X,Y}_CM` horizontal slots moved to match;
  `test_grid.py`'s `.ino`↔config parity check holds.
- **This value is a geometric derivation, not a rig measurement.** Committed as
  authoritative per the owner's call; the printed sheet and rig must be
  physically re-registered to match, and a real pickup-place measurement is
  still what would confirm it.
- The 3 × 10 reachable grid is unchanged (X last centre 17.1 ≤ 22.8, Y 36.1 ≤
  38.0; near-edge −1.1 inside the `max_edge_overhang_x_cm = 3.0` budget). No
  clip, no count change.
- **BRIDGE re-tuned, no rule touched.** `+1.9` trim alone centres the span dead
  over the 1.6 cm gap — 73.3% contact but centroid over air, which §6.5
  refuses (mirror of the old "reverse reaches 68.3% in the gap" finding). The
  legal `shiftX` windows for `v[2,2] v[3,2]` / `h[1,4]` are now **−1.0…−0.8 cm
  and +0.8…+1.1 cm**; `BRIDGE_SHIFT_CM` stays `1` (56.7% contact, centroid over
  the far tower) and the example still opens with exactly one `GEOMETRY_DRIFT`
  warning. `coords.fixtures.json` regenerated (17 cases / 980 cells unchanged;
  horizontal cases moved +19 mm X / +3 mm Y). `validate.test.ts`'s bridge-search
  pin moved from candidate `[0,2]` to `[0,1]` (descriptive, not a rule).

### M7 — The runner

- Added `studio/runner.ts`, the pure `step(state,event)` reducer with the named
  §10 phases and effect descriptions only. Its exhaustive reachable-state test
  covers every candidate event across STEP/RUN/DRY RUN and proves no second
  build is emitted while one is in flight and no real select/build/mode effect
  exists while the reducer still observes `build_state === RUNNING`.
- Added `studio/runner-driver.ts`. Per block it changes level only when needed,
  posts `/api/select` (or `/api/select/axis` on a genuine zero-axis target),
  returns the server's `state.command` to the reducer for a byte comparison,
  and only then posts the existing confirmed `/api/build`. It adds no endpoint,
  batch or authority. A second defensive RUNNING check precedes every real API
  effect; server guards remain unchanged.
- STEP reuses `BuildButton`'s existing expiring two-tap confirmation. RUN is
  continuous and has only honest stop-after-current-block semantics. DRY RUN
  sends zero API traffic and uses the same reducer with 600 ms fake builds.
  Every mode op pauses on the X/Y-homing warning before `/api/mode` is possible.
- The manual-feeder prompt appears before START, then uses an in-flight block's
  motion time to name the next required colour. Consecutive identical colours
  reduce to `SAME COLOUR`; the command and `block n of total` remain visible.
- REJECTED preserves the cursor and exposes only CONTINUE / END RUN. ABORTED
  preserves the complete program and log read-only at `stopped at step n of
  total`; there is no cancel or retry control. Socket loss pauses immediately
  and never auto-resumes. Mismatch shows program/rig strings verbatim, makes the
  run read-only and emits nothing further.
- Added the event-derived Markdown report: exact sent commands, terminal
  results, measured per-command and total durations, optional vision result,
  best-effort 320 px camera WebP evidence, and verbatim mismatch/abort detail.
- Measured a complete five-block tower through a real `python -m web --mock`
  process and the production HTTP routes: **2.113, 2.108, 2.112, 2.104,
  2.140 s; mean 2.115 s**. `BLOCK_CYCLE_SECONDS` is now 2.115 and feeds both
  compiler estimates and the runner's elapsed/count/ETA readout. The UI and
  docs explicitly say this is mock transport timing, not physical-arm timing;
  the latch's 16 s remains an editable guess.
- `TwinPanel` can now be controlled by `App`; its picker is frozen while a run,
  mismatch or lock is preserved, so the twin cannot silently switch to a model
  different from the executing program.
- Production build after M7: console 273.50 kB (86.75 kB gzip), CSS 39.36 kB
  (8.06 kB gzip); Three.js remains absent from first paint.

### M6 — The twin

- Added `studio/twin.ts`: the whole of Plan 4 §9 as one pure mapping —
  `twinScene()`, the `foldTwinProgress()` confirmation fold, `twinSignature()`
  and `descentOffsetScene()` (the last of these was deleted later — see the
  serial-driven build progress entry at the top). No React and no three.js in
  it; `scene/Twin.tsx`
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
  make the example pass.** (The specific ratios and shift windows here are
  superseded by the horizontal-registration entry above; the finding stands.)
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

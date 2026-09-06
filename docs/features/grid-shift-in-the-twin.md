# Grid shift in the twin — the lattice the rig is actually on

**Status: partially implemented. The maths is done; the plumbing is not.**

In one sentence: **every coordinate function on the web side already takes an
optional `shift`, and the twin is the one caller that never passes one — because
the server never publishes the value it would pass.**

The Studio got this right and the twin did not, which is the worst possible
split: the read-only panel that claims to mirror the machine is the one drawing
the wrong lattice, while the editor beside it draws the right one.

---

## 1. What exists today

| Piece | State | Where |
| --- | --- | --- |
| Firmware `shiftX` / `shiftY` runtime commands | **exists** | `arduino/build_test_v1/build_test_v1.ino`, `handleShiftCommand` → `applyGridShift` |
| Per-mode `GRID_SHIFT_X_CM[]` / `_Y_CM[]` and live clipping | **exists** | same sketch, `gridColsNow()` / `gridRowsNow()` return `min(requested, fits)` |
| `shift_x_cm` / `shift_y_cm` per mode in the config | **exists** | [config/rig.json](../../config/rig.json), both modes, currently `0.0` |
| `MachineGrid.shift_x_cm/.shift_y_cm`, folded into the origin | **exists** | [python/rig/grid.py:353](../../python/rig/grid.py#L353) |
| `Rig.set_shift()` pushing it to the board | **exists, connect-time only** | [python/rig/link.py:857](../../python/rig/link.py#L857) — called from `connect()` and `recover_after_reset()`, never from a route |
| `latticeOf(mode, shift)`, `cellToMachine(…, shift)`, `cellToScene(…, shift)` | **exists** | [web/src/studio/coords.ts:89](../../web/src/studio/coords.ts#L89), `:106`, `:177` |
| `clippedCells(mode, shift)`, `latticeCells(mode, shift)` | **exists** | [web/src/studio/geometry.ts:173](../../web/src/studio/geometry.ts#L173), [lattice.ts:34](../../web/src/studio/lattice.ts#L34) |
| `CLIPPED_BY_SHIFT` validation and `GEOMETRY_DRIFT` | **exists** | [web/src/studio/validate.ts:129](../../web/src/studio/validate.ts#L129) |
| The **Studio** drawing its model's shift | **exists** | [web/src/routes/Studio.tsx:110](../../web/src/routes/Studio.tsx#L110) — `shiftsOf(document.rig)` into viewport, validator and compiler |
| Fixture coverage of shifted lattices | **exists** | [python/tools/dump_grid_fixtures.py:117](../../python/tools/dump_grid_fixtures.py#L117) — seven shifted cases, checked in `coords.test.ts` |
| **The live shift in `StateModel`** | **does not exist** | [python/web/state.py](../../python/web/state.py) publishes `mode`, `cols`, `rows` and no shift |
| **The twin drawing a shift** | **does not exist** | [web/src/studio/scene/Twin.tsx:218](../../web/src/studio/scene/Twin.tsx#L218) is `<Lattice mode={mode} />`; `:92` is `cellToScene(block.mode, col, row, level)` — no fourth argument |
| **A route that changes the shift at runtime** | **does not exist** | [python/web/routes_command.py](../../python/web/routes_command.py) has select / level / mode / view / build / stop and nothing else |

So there are really **two features hiding under one name**, and they have very
different costs:

1. **Show the shift the rig is on.** Cheap, safe, and strictly a truthfulness
   fix. This is what §2–§4 below are about.
2. **Change the shift from the browser.** A new write route with roughly the
   gravity of `POST /api/mode`. Genuinely riskier — see §6.

Build 1. Consider 2 separately, on purpose, later.

---

## 2. Why today's picture is wrong rather than merely incomplete

`coords.ts` imports `config/rig.json` **at build time**:

```ts
import rigJson from "../../../config/rig.json";
```

So with no shift passed, the twin draws the lattice as the config file was on
the day the bundle was built. Every one of these makes that a lie:

- an operator edits `shift_*_cm` and restarts the server without rebuilding the
  browser bundle;
- `Rig.set_shift(x_cm=…)` is called with an explicit value from anywhere;
- the two modes carry different shifts — and they do, independently — while the
  twin's `mode` is a live mirror of the rig's latch;
- the firmware **clips** a shifted grid (`gridColsNow()`), so the rig refuses
  cells the twin is cheerfully drawing as available.

The twin's whole contract, stated at the top of [twin.ts](../../web/src/studio/twin.ts),
is that it never invents state. A lattice drawn from a stale build-time constant
is invented state — it just happens to be invented by the bundler.

---

## 3. Three ways to give the twin a shift

### Approach A — the server publishes the live shift *(recommended core)*

Add to `StateModel`, from the `MachineGrid` that is already in hand:

```python
shift_cm: tuple[float, float]           # the ACTIVE mode's live shift
reachable: tuple[int, int]              # cols, rows after firmware clipping
```

`build_state()` already holds `rig.grid`; both values are one attribute read and
one call away. The store carries them, `TwinPanel` threads them into `twinScene`
and into `<Twin shift={…}>`, and `Twin.tsx` passes them to `<Lattice>` and to
`cellToScene`.

**Cost:** one Python field, one TS type field, three prop hops.
**Buys:** the twin is true; clipping becomes drawable; the camera overlay and the
twin stop being able to disagree.
**Risk:** the `reachable` count must come from the same clipping rule the
firmware uses. Do not reimplement it in Python — `clippedCells()` in TS already
ports it and `coords.test.ts` holds it to the Python fixtures. Publish the shift
and let the client clip, or publish both and assert they agree in a test.

### Approach B — read it from the model's own `rig` snapshot

Exactly what the Studio does: `shiftsOf(document.rig)`. Zero new server work.

**Wrong as the twin's primary source**, and the reason is the twin's own rule:
the model says what the *author assumed*, not what the *machine is on*. If the
two differ, using the model's number draws a confident picture of the wrong
lattice. But it is exactly right for a **second** job — see the hybrid.

### Approach C — leave it on the build-time config *(the status quo)*

Correct only while nobody ever sets a shift. It is the current behaviour and it
is not labelled anywhere, which is what makes it worse than an honest gap.

Keep it strictly as the **fallback** for a socket that has never delivered a
state, and when it is in force say so in the panel rather than drawing a
confident lattice from a constant.

### The hybrid — and it is the right answer

> **A for the geometry, B for the warning, C only as a labelled fallback.**

- The lattice the twin **draws** and the positions it **places blocks at** come
  from the server's live shift (A).
- The model's stored `rig.shift_cm` is compared against it, and a mismatch
  raises the same kind of banner `GEOMETRY_DRIFT` already raises in the Studio
  (B): *"this model was designed for shiftX +1.60; the rig is on +0.00"*. That
  is a real failure mode — a model authored under a shift and run without one
  builds a structure translated by centimetres — and the twin is the one place
  an operator would see it before pressing go.
- With no state yet, draw from the config and mark the panel as such (C).

Future AIs: **do not pick one of these three.** The three answer three different
questions ("where is the rig's lattice", "where did the author think it was",
"what do we draw before we know") and a good implementation answers all three.

---

## 4. The traps, in the order you will hit them

1. **The shift is per mode.** `GRID_SHIFT_X_CM[GRID_MODE_COUNT]`, and
   `config/rig.json` carries a separate pair under each mode. Key everything by
   mode. Publishing one unlabelled pair and keying it to whatever mode the twin
   happens to be showing silently draws the other grid's shift.
2. **`twinSignature` must include it.** [TwinPanel.tsx](../../web/src/components/TwinPanel.tsx)
   re-renders the canvas only when `twinSignature` changes, precisely so ~20
   states a second do not cost the video stream frames. A shift that is not in
   the signature will be read once and then pinned forever.
3. **A shift moves the lattice, never the cell indices.** `B 3 5 0` is `B 3 5 0`
   under any shift. Do not "helpfully" renumber anything, and do not put the
   shift into a model block's stored coordinates.
4. **Sign convention.** [AGENTS.md](../../AGENTS.md) Rule 0: `+` = away from that
   axis' home switch, on every axis, in magnitude space. `axisPos[]` on X runs
   the other way. The twin never touches machine positions — it goes cell →
   machine mm → scene through `coords.ts` — so **do not introduce a sign flip in
   the scene layer to make a shifted picture "look right"**. If it looks wrong,
   the fixtures in `coords.fixtures.json` are the arbiter.
5. **Clipped cells are struck through, not deleted.** `latticeCells` already
   returns `kind: "clipped"` and the Studio draws it. The twin should match:
   a clipped cell is still addressable, the machine just cannot reach it.
6. **The saved workspace map carries the shift.**
   [python/rig/workspace.py:330](../../python/rig/workspace.py#L330) invalidates a
   saved map when `shift_*_cm` no longer matches. So a shift change is already a
   camera-calibration event; the twin and the camera overlay must not end up
   showing two different lattices for the same rig.

---

## 5. Tests — this is the "+ test" half of the request

The repo's own rule holds: **Python is right, TypeScript is held to it by dumped
fixtures.**

| Suite | What it must check |
| --- | --- |
| `python/tests/web_state_test.py` | `shift_cm` appears in the snapshot, is the **active** mode's pair, and changes when the mode latches to a mode with a different shift |
| `python/tests/test_grid.py` | already covers shift → lattice origin and clipping (§"GRID SHIFT", line 658). Extend it only if a new constant appears; it parses the sketch and is the check that catches a knob edited in one place |
| `web/src/studio/twin.test.ts` | a state carrying a shift produces block positions and a lattice offset by exactly that shift; a **clipped** cell reads as clipped; a model whose `rig.shift_cm` differs from the state's raises the drift banner; `twinSignature` changes when only the shift changes |
| `web/src/studio/coords.test.ts` | already fixture-driven for shifted lattices; regenerate with `python3 python/tools/dump_grid_fixtures.py` if a new case is added |
| `web/src/components/TwinPanel.test.tsx` | the prop actually reaches `<Twin>`; the no-state fallback is labelled |
| fixtures | `python3 python/tools/dump_twin_states.py` must be re-run — `twin.fixtures.json` is recorded from a real `--mock` server and will not contain the new field until it is |

Then the standard gate:

```bash
python3 python/tests/test_grid.py     # firmware <-> config pairing
cd web && npx vitest run
cd python && python3 -m pytest tests/
```

---

## 6. The second feature: changing the shift from the browser

Not required by "grid shift on the twin", and worth its own decision.

`POST /api/shift {mode, x_cm, y_cm}` calling `Rig.set_shift(x, y)` is about
fifteen lines. What makes it non-trivial:

- **It invalidates the saved workspace map** (`workspace.py` §330). Either
  re-calibrate or accept that the camera overlay is now off — and say which.
- **It can clip the grid under a selection.** `S` is validated against the
  *shifted* lattice, which is why `connect()` sends mode → shift → `S` in that
  order ([link.py:493](../../python/rig/link.py#L493)). A route must preserve that
  ordering and re-send `S`.
- **It must be refused while a build is running.** Same guard as every other
  mutation in `routes_command.py`.
- **It is not calibration.** A shift is an operator's deliberate relocation of
  the whole structure. If you find yourself reaching for it to fix a placement
  error, you want the other feature —
  [between-build-error-calibration.md](between-build-error-calibration.md) — and
  you should read its §4 before touching this route.

---

## 7. Difficulty

| Piece | Difficulty | Why |
| --- | --- | --- |
| Publish the shift, thread it to the twin | **2 / 5** | plumbing through code that already accepts the parameter |
| Clipped-cell drawing in the twin | **2 / 5** | `latticeCells` already returns the kind |
| Drift banner vs. the model's snapshot | **2 / 5** | mirrors existing `GEOMETRY_DRIFT` |
| Tests + fixture regeneration | **3 / 5** | the fixtures are recorded from a live mock server, not hand-written |
| `POST /api/shift` (§6, optional) | **4 / 5** | map invalidation, `S` re-send, ordering, safety guards |

**Overall for the requested feature: 2–3 / 5.** It is one of the highest
truth-per-line changes available in this repo — small, testable, and it removes
a case where the console confidently shows the operator the wrong machine.

---

## 8. Not doing

- **Animating the lattice as the shift changes.** The rig does not move when a
  shift is applied; a sliding lattice would imply it did.
- **Letting the twin latch a shift.** Same rule as the mode indicator in
  [TwinPanel.tsx](../../web/src/components/TwinPanel.tsx): the twin is read-only,
  and a habit built in the twin must never move the machine.
- **Inferring the shift from the camera.** That is placement calibration, and it
  is a different document.

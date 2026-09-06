# Stage 15 — between-job placement correction

**Status: design agreed, not implemented.**

This supersedes [between-build-error-calibration.md](between-build-error-calibration.md)
as the design we are actually building. That document designed its *reading (a)*
— measure the machine's systematic drift and write a calibration number back.
**This is its reading (b), and it is deliberately a different, smaller feature.**

---

## 0. The whole feature, in one paragraph

After a build job finishes and the gantry has parked, look at the board. For
each block the machine believes it placed, compare where it should be against
where it is. If exactly one thing is meaningfully out of place, pick that block
up and put it back properly, then look again to confirm. Then the next job may
start. Off by default; a toggle in the build UI.

That is all. It is an **outlier repair**, not a calibration.

---

## 1. Why this is simpler than the document it replaces

The predecessor asked *"is the machine systematically off, and by how much?"*
That question forces a windowed estimate, a deadband against the map's own
noise floor, a bounded correction, a persistent bias with provenance, a decision
about which of three interchangeable-looking knobs to write, and a new firmware
verb to write it with.

This asks *"is that one block in the wrong spot?"* — and the answer is a
physical action, not a number. Everything the other design needed in order to
**store** a correction disappears:

| Deleted | Why |
| --- | --- |
| `error_offset_*`, `shift_*`, `calibration_bias` | nothing is written back; the fix is physical |
| Approaches A / B / C / D and the staged hybrid | all four were about *where to write a number* |
| Provenance, rate caps, "one adjustment per session" | there is no persistent state to be honest about |
| An `errX` / `errY` firmware verb | not needed |
| Windowed mean, drift deadband | one block is judged, not a population |
| `WorkspaceMap.matches_grid` invalidation | the map never changes |

### 1a. Rule 1 is structural here, not a discipline

> **This feature never touches the grid.**

Not the lattice origin, not `error_offset_*`, not `shift_*`, not
[grid.py](../../python/rig/grid.py)'s `cell_center_*_cm`, not
[coords.ts](../../web/src/studio/coords.ts), not the Studio's drawing or model,
and not one line of the 14 build phases' math or ideology. The grid is a
**read-only input**: it supplies "where should this block be", and nothing more.

The predecessor could not offer this, because writing `error_offset` *is* moving
the lattice origin. Here there is no number to write, so there is no way for the
feature to move the grid even by mistake. That is worth more than a rule.

### 1b. The workspace map does not need re-anchoring

An earlier reading of the predecessor's design worried that a map fitted from
placed blocks (`workspace_map_from_calibration`,
[block_grid.py:1040](../../python/vision/block_grid.py#L1040)) absorbs the
machine's own offset into its corners, so `commanded − observed` reads ≈ 0 by
construction.

**That is true, and it does not matter here.** It defeats a *drift* measurement.
It is exactly right for an *outlier* measurement: a map fitted from placed
blocks encodes "where this machine normally lands a block", which is precisely
the yardstick for spotting one that did not. The existing block-calibration map
is the correct reference. Nothing needs re-anchoring.

---

## 2. The decisions

### D1 — Between jobs, never mid-job, never mid-command

Stage 15 runs after a whole build job completes and the firmware's terminal `OK`
has arrived — which is *after* phase 14 has parked the gantry at the origin with
the claw neutral. That is already the quiet, parked, out-of-frame state the
measurement needs; no new interlock has to be invented.

It does **not** run after every block. A per-block check adds a settle and a
frame grab (~2 s) to every placement, and judges each block on a single
observation.

### D2 — It is stage 15 in the UI, and Pi-side in fact

The Mega has no camera and no filesystem. It cannot look at the board, so this
**cannot be a firmware phase**, and phases 1–14 are not modified.

The Pi synthesises a stage-15 `STEP` line into the same progress stream
[`BuildProgressTracker`](../../python/web/progress.py#L158) already consumes, so
the operator sees a genuine 15th stage. Documentation and `total_steps` must say
plainly that 15 is a Pi-side stage, not a firmware one.

### D3 — Level and rotation come from memory, never from vision

The machine knows what it built. `block_levels.py`'s level *inference* is
explicitly not validated on real frames and is not used, and
`estimate_camera_height` is not used either.

The as-built memory answers "the top block at [2,2] is level 2, placed `ROT_CW`",
and that is authoritative. Vision is asked one question only: *where is the
block in the image?*

### D4 — Camera height is needed for **position**, not for levels

This distinction caused real confusion and is worth stating flatly:

> Memory tells us **which level** a block is on. Camera height tells us **how
> much that level displaces the block in the image.** They are different
> problems and the second one does not go away.

The camera is 57 cm above the board. A block's top face at level `L` sits
`(L+1) × 1.5 cm` up, so it projects **outward from the camera's nadir** by
`r · h / (H − h)`, where `r` is its distance from the nadir. Level 0's share of
this is already baked into the workspace map (the map was fitted from level-0
blocks), so what matters is the excess over level 0. At a corner cell
(`r ≈ 22 cm` on a 22.8 × 38.0 workspace, `H = 57`):

| Level | Apparent outward shift | Excess over level 0 |
| --- | --- | --- |
| 0 | 0.60 cm | — (absorbed by the map) |
| 1 | 1.23 cm | **0.63 cm** |
| 2 | 1.90 cm | **1.30 cm** |
| 3 | 2.61 cm | **2.01 cm** |

**A perfectly placed level-2 corner block appears ~1.3 cm out of position** —
over twice the error this feature exists to correct. Uncorrected, stage 15
would confidently shove a good block 1.3 cm in the wrong direction, worst at the
edges, near-zero in the middle, and looking nothing like a bug.

So: `camera.height_cm: 57.0` goes in `config/rig.json` (there is no `camera`
section today), and every observed centre is parallax-corrected using the level
from memory before it is compared to anything.

`r` is measured from the **nadir** — the point directly beneath the lens — not
from the board centre. If the camera is not centred over the workspace, the
nadir must be found; assuming board centre is an error of the same size as the
thing being measured.

### D5 — Only the top block of a column may be corrected

If [2,2] carries levels 0–2 and the *level-0* block is the one out of place, it
is load-bearing and buried, and there is no correction. The as-built memory
knows the column height, and stage 15 **refuses** — halts and asks for a human.
This is a refusal, not a warning.

### D6 — A correction band, not a threshold

The re-place uses the same claw and the same axes as the original place, so it
carries the same placement error. "Correcting" an error comparable to the
machine's own repeatability is a coin flip that can make things worse.

| Measured error | Action |
| --- | --- |
| `< 0.5 cm` | ignore — not worth physically disturbing a block for |
| `0.5 – 1.0 cm` | correct |
| `> 1.0 cm` | **refuse**, halt, flag for a human |

The upper bound is geometric, not arbitrary: in vertical mode the gap is 1.6 cm,
so a block 1.0 cm off has only 0.6 cm of clearance on its near side and the jaws
descend into that gap. Beyond that the block is probably touching its neighbour
and gripping it disturbs two blocks instead of one. **Both bounds are provisional
and must be measured on the bench** — 0.5 cm needs to be confirmed as comfortably
above placement repeatability, and 1.0 cm against actual jaw clearance.

### D7 — Re-verify, and never trust a silent grip

The one genuinely new failure mode: **a claw that closes on nothing reports
success.** The firmware cannot detect it — there is no grip sensor. So after a
correction, stage 15 looks again and confirms the block actually moved to where
it was sent. If it did not, that is a halt-and-inspect, not a retry.

A correction that is not re-verified is a guess with extra steps.

### D8 — One correction per stage-15 pass

Find the worst offender, fix it, re-verify, stop. If several blocks are out of
place, that is not a placement error — it is a knocked rail, a wrong mode latch
or a stale map, and the answer is a human, not fifteen pick-and-places.

### D9 — Off by default

A toggle in the build UI, defaulting **off**. It moves the machine without an
explicit per-action operator command, which is reason enough for opt-in.

---

## 3. The as-built memory

**It does not exist today.** Verified:

- `countPlacedBlock()` ([:4038](../../arduino/build_vertical_grid/build_vertical_grid.ino#L4038))
  is a histogram — `statBlocksAtLevel[level]++`. It does not record the cell.
- `BuildJob` ([build_job.py:45](../../python/rig/build_job.py#L45)) is a
  one-block worker with no history.
- No occupancy model in `orchestrator.py`, `build_controller.py` or `web/state.py`.
- `compile.ts` emits ops carrying `col`/`row`/`level`/mode — but that is the
  **plan**, not the as-built.

So it is a prerequisite, not a detail. It holds, per cell: the top level, the
rotation that placed it, and when.

**In-process only, not persisted.** A server restart loses the board state, and
stage 15 must then **refuse** — "no as-built memory; run a job first" — rather
than guess from a camera frame.

**The standing assumption: no human intervention.** The board contains exactly
what the machine put there. A block moved or removed by hand invalidates the
memory, and nothing detects that. This assumption is what makes the feature
tractable and it should be stated in the UI, not buried here.

---

## 4. What the correction actually does

The pick target and the place target are two different points, which is simpler
than "go back 0.5 cm":

- **pick** at the block's *observed* position — off-lattice, an arbitrary cm offset
- **place** at the block's *commanded* position — the cell centre, unchanged

The existing `B` verb is pick-**from-feeder**-then-place and cannot express this.
`G <col> <row>` addresses cell indices only. A block sitting 0.5 cm off-cell is
not addressable by any command the firmware has today, so this needs a new verb.

### The new firmware verb

Shaped as an offset-aware re-place, mirroring phases 8–14 of `buildBlock()` and
reusing `gotoBuildTarget`, `levelToZSteps`, `rotateClawTo`, `openServoAndWait`:

```
P <col> <row> <level> <dx_cm> <dy_cm>
```

1. rotate claw to the stored rotation (`ROT_NONE` / `ROT_CW` / `ROT_CCW`)
2. open jaws, still high
3. move to cell `(col,row)` **plus** `(dx,dy)` — where the block actually is
4. descend to `levelToZSteps(level)` — the same Z that placed it
5. close jaws (grip)
6. lift to carry height
7. move to cell `(col,row)` with **no** offset — where it belongs
8. descend to `levelToZSteps(level)`, open jaws, lift, park

The `(dx,dy)` injection point is the one already used by the X-rail skew
compensation — `gotoBuildTarget()` at
[:3521](../../arduino/build_vertical_grid/build_vertical_grid.ino#L3521) adds
`buildPlacementOffsetSteps() + buildSkewSteps()` after `cellTargetPosition()`
and before the move. A per-command offset is a third term in the same slot: a
machine-space nudge that the grid model never sees. This is the established
pattern for "move the machine without moving the grid" and it is why Rule 1
survives contact with the firmware.

`parseSignedCm` already exists (`handleShiftCommand`,
[:3300](../../arduino/build_vertical_grid/build_vertical_grid.ino#L3300)); a
five-argument parser does not.

**No local Arduino toolchain.** Per [AGENTS.md](../../AGENTS.md), syntax-check
with the stub-Arduino `g++` harness, state plainly that the result is unflashed
and unverified on hardware, and pair both sketches —
`build_vertical_grid.ino` **and** `build_horizontal_grid.ino` — in the same
commit, with `python/tests/test_grid.py` extended to cover the new verb.

---

## 5. What could still go wrong

1. **The nadir is not the board centre.** Getting `r` wrong scales every
   parallax correction. Worth measuring rather than assuming.
2. **The grip descends into a narrowed gap.** A block 1.0 cm off leaves 0.6 cm
   of clearance. Jaw width against that clearance is a bench measurement nobody
   has taken.
3. **The silent grip failure (D7)** — the only genuinely new failure mode.
4. **The re-place is not more accurate than the place** (D6). If bench
   measurement shows repeatability near 0.5 cm, the correction band is empty and
   the honest answer is that this feature cannot help.
5. **A knocked block that memory still believes in.** The no-intervention
   assumption is load-bearing and undetectable when violated.

---

## 6. Not doing

- **Correcting more than one block per pass** (D8).
- **Correcting a buried block** (D5).
- **Writing anything to the grid, the lattice origin, `error_offset_*`,
  `shift_*`, or `config/rig.json`'s geometry.** Ever. (§1a)
- **Inferring levels from vision.** Memory is authoritative (D3).
- **Persisting the as-built memory.** In-process only; refuse after a restart (§3).
- **Systematic drift calibration.** That is the predecessor document's feature and
  it remains unbuilt.

---

## 7. Difficulty

| Piece | Difficulty |
| --- | --- |
| As-built memory (in-process) | **2 / 5** |
| Observed-vs-commanded in cm, parallax-corrected | **2 / 5** |
| Stage-15 orchestration + UI toggle | **2 / 5** |
| The `P` verb in both sketches | **3 / 5** + unflashable locally |
| The safety rules (D5–D8) and proving them | **4 / 5** |
| Confirming the correction band is not empty (D6) | **bench work, unavoidable** |

**Overall: 3 / 5** — down from the predecessor's 4 / 5, because the knob-choice
problem, the provenance surface and the sign-convention trap all disappear along
with the stored correction. What replaces them is physical risk: this design
moves the claw into a built structure, which the other one never did.

# Stage 15 — between-job placement correction

**Status: design agreed, not implemented — but §3's prerequisite is now BUILT.**

The as-built memory this feature called a prerequisite shipped with
[placement supervision](placement-supervision.md) M1, and it was built to serve
both: `rig/placement_ledger.py` carries **this feature's own D5/D6 safety
predicates**, `is_top_of_column()` and `has_taller_neighbour()`, so Stage 15
inherits them rather than writing a second occupancy model that could disagree.
See §3 for what changed and what did not.

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

There is **no hard level ceiling**, but stage 15 must run its own detection pass
to avoid one — see D7.

---

## 1. Why this is simpler than the document it replaces

The predecessor asked *"is the machine systematically off, and by how much?"*
That question forces a windowed estimate, a deadband against the map's own noise
floor, a bounded correction, a persistent bias with provenance, a decision about
which of three interchangeable-looking knobs to write, and a new firmware verb to
write it with.

This asks *"is that one block in the wrong spot?"* — and the answer is a physical
action, not a number. Everything the other design needed in order to **store** a
correction disappears:

| Deleted | Why |
| --- | --- |
| `error_offset_*`, `shift_*`, `calibration_bias` | nothing is written back; the fix is physical |
| Approaches A / B / C / D and the staged hybrid | all four were about *where to write a number* |
| Provenance, rate caps, "one adjustment per session" | there is no persistent state to be honest about |
| An `errX` / `errY` firmware verb | not needed |
| Windowed mean, drift deadband | one block is judged, not a population |
| `WorkspaceMap.matches_grid` invalidation | the map never changes |

What replaces them is **physical** risk. The predecessor only ever wrote a
number; this design drives the claw down into a finished structure. Every hard
part of this document is downstream of that one difference.

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
It is exactly right for an *outlier* measurement: a map fitted from placed blocks
encodes "where this machine normally lands a block", which is precisely the
yardstick for spotting one that did not. The existing block-calibration map is
the correct reference. Nothing needs re-anchoring.

---

## 2. The decisions

### D1 — Between jobs, never mid-job, never mid-command

Stage 15 runs after a whole build job completes and the firmware's terminal `OK`
has arrived — which is *after* phase 14 has parked the gantry at the origin with
the claw neutral. That is already the quiet, parked, out-of-frame state the
measurement needs; no new interlock has to be invented.

It does **not** run after every block. A per-block check adds a settle and a
frame grab (~2 s) to every placement, and judges each block on one observation.

### D2 — "Stage 15" is a name for the operator, not a 15th build phase

The Mega has no camera and no filesystem. It cannot look at the board, so this
**cannot be a firmware phase**, and phases 1–14 are not modified.

It is tempting to have the Pi synthesise a 15th `@n STEP … phase=` line into the
existing build-progress stream. **Do not.** Two reasons, both checked:

1. Per [AGENTS.md §5a](../../AGENTS.md), the fourteen `phase=` ids are a
   **protocol**, mirrored in four places — the sketch's `buildStep()` call sites,
   `MockBoard.BUILD_PHASES`, `twin.ts`'s `PHASE_BY_ID`, and `docs/ack-protocol.md`
   — and `twin.test.ts` asserts the browser's table matches the documented
   fourteen. Adding a fifteenth is a protocol change to the thing Rule 1 says not
   to touch.
2. The fallback is not graceful. `twin.ts:440` reads
   `PHASE_BY_ID[progress.phase] ?? "moving-to-target"`, so an unrecognised id
   makes the 3D twin **draw the gantry flying to a target** — an active
   misstatement of what the machine is doing, not a shrug.

So stage 15 gets **its own state fields and its own UI strip**, parallel to the
build-phase channel and never inside it. The operator sees "Stage 15 — placement
check" because that is what it is *to them*; the fourteen-phase contract is
untouched, `twin.ts` needs no new id, and `twin.test.ts` keeps passing unchanged.

### D3 — Level and rotation come from memory, never from vision

The machine knows what it built. `block_levels.py`'s level *inference* is
explicitly not validated on real frames and is not used, and
`estimate_camera_height` is not used either.

The as-built memory answers "the top block at [2,2] is level 2, placed `ROT_CW`",
and that is authoritative. Vision is asked one question only: *where is the block
in the image?*

### D4 — Camera geometry: needed for **position**, not for levels

This distinction caused real confusion and is worth stating flatly:

> Memory tells us **which level** a block is on. The camera geometry tells us
> **how much that level displaces the block in the image.** They are different
> problems and the second one does not go away.

**Measured on the bench:**

| Quantity | Value |
| --- | --- |
| Camera height `H` above the board | **57 cm** |
| Nadir, Y (from the Y home switch) | **32.5 cm** |
| Nadir, X | **≈ 11.4 cm — centred** on the 22.8 cm width |

The workspace map is a homography, so it exactly models one plane: the level-0
top faces at `h₀ = 1.5 cm`. A block whose top sits at `h = (L+1)·1.5` is on a
*different* plane, and the map therefore reports it displaced **away from the
nadir** by

```
excess = k(L) · d          k(L) = (h − h₀) / (H − h)
```

where `d` is the block's distance from the nadir. Because `k` is a scalar, the
components separate cleanly — the X error depends only on `|x − 11.4|` and the Y
error only on `|y − 32.5|`:

| Level | `k` | X excess at col 0/6 | Y excess at row 0 |
| --- | --- | --- | --- |
| 0 | 0.000 | — (the map's own plane) | — |
| 1 | 0.028 | 0.32 cm | 0.90 cm |
| 2 | 0.057 | 0.65 cm | 1.86 cm |
| 3 | 0.088 | 1.01 cm | 2.87 cm |

Two things follow, and the second is the dangerous one:

1. **It is large.** A perfectly placed level-2 block on row 0 appears ~1.9 cm out
   of position — larger than the whole correction band in D8.
2. **It is directional and consistent.** The shift always points *away* from the
   nadir, so every upper-level block on row 0 appears displaced toward −Y by a
   similar amount. That does not look like noise; it looks like a real,
   repeatable machine fault — and worst on row 0, which is exactly where a
   genuine homing or backlash error would show up. Uncorrected, stage 15 would
   systematically shove good row-0 blocks in +Y and the results would be
   self-consistent enough to be believed.

**The good news: with both numbers measured, the model is robust.** Being wrong
by 2 cm in the nadir *or* in `H` moves the level-2 worst-case correction by at
most 0.11 cm — comfortably inside the map's own 0.27 cm error. This stops being
a risk and becomes arithmetic.

`camera: { height_cm: 57.0, nadir_x_cm: 11.4, nadir_y_cm: 32.5 }` goes in
`config/rig.json` (there is no `camera` section today), and every observed centre
is parallax-corrected using the level from memory before it is compared to
anything.

### D5 — Only the top block of a column may be corrected

If [2,2] carries levels 0–2 and the *level-0* block is the one out of place, it
is load-bearing and buried, and there is no correction. The as-built memory knows
the column height, and stage 15 **refuses** — halts and asks for a human. This is
a refusal, not a warning.

### D6 — The descent corridor must be clear of taller neighbours

**The 14 build phases never face this problem, and stage 15 does.**

`ORDER_TERMS` puts `level` first ([compile.ts:147](../../web/src/studio/compile.ts#L147)),
so a job is built level-major, bottom-up. During a normal build the claw
therefore never descends into a valley between taller neighbours — the taller
neighbours do not exist yet.

Stage 15 runs *after* the job, on a finished structure with arbitrary height
variation. If [2,2]'s top block is at level 2 while [2,3] is stacked to level 5,
gripping at level 2 drives the claw down a 1.6 cm slot flanked by a stack three
blocks taller.

So D5 is not sufficient. The target must be the top of its own column **and** no
adjacent column may be taller than it. The as-built memory has everything needed
to check this; it is a refusal like D5.

This compounds with D7 — both bite hardest on tall, uneven structures, which is
where placement errors are also most likely. The correctable set is smaller than
it first appears, and that should be surfaced honestly in the UI.

### D7 — No level ceiling, provided the detector is called correctly

There *is* a ceiling on the obvious implementation, and it is worth understanding
before designing around it.

`detect_aligned_blocks` discards any detection sitting more than
`MAX_INDEX_SNAP = 0.34` **cells** off the fitted lattice
([block_grid.py:1747](../../python/vision/block_grid.py#L1747)) — the filter that
stops the holder's wooden offcuts being taken for blocks. Parallax (D4) eats that
budget as levels rise, and Y is the binding axis:

| Row | L1 | L2 | L3 | L4 |
| --- | --- | --- | --- | --- |
| 0 | 0.12 | 0.24 | **0.38 dropped** | **0.52 dropped** |
| 1 | 0.09 | 0.19 | 0.29 | **0.40 dropped** |
| 2–5 | 0.08 | 0.17 | 0.26 | **0.36 dropped** |

So if stage 15 simply consumed `ProcessedFrame.detections`, every block above
level 2 would be **invisible — not misjudged, silently discarded** before stage
15 ever saw it, and the feature would cover three of the rig's seventeen levels.

**That ceiling is an artifact of passing a `grid`, not a property of the camera.**
`_lattice_filter` opens with `if grid is None … return list(detections), [], None`
— **with no grid there is no rejection at all.** And in both paths the centre is
untouched: *"The centre stays exactly where it was measured"*
([block_outline.py:181](../../python/vision/block_outline.py#L181)). `_rectify`
only shares size and bearing.

**So stage 15 runs its own detection pass with `grid=None`**, on the parked frame,
between jobs. It costs one detector call (~84 ms per the module's own benchmark)
once per job — nothing, at this cadence.

It then does its own matching, which build memory makes *stronger* than the
lattice filter it replaced:

1. for each cell the as-built memory says holds a block, predict where it should
   appear = commanded centre + `k(L)·d` parallax (D4);
2. match each prediction to the nearest detection within a fixed radius;
3. **ignore every unmatched detection.** Offcuts, the feeder, a dropped block —
   none of them are at a predicted position.

"Is it near where memory says a block should be" is a sharper test than "is it
roughly on some lattice", and it is available here precisely because this feature
has build memory and the live pipeline does not.

The match radius is bounded on both sides: it must exceed the worst honest error
(map 0.27 cm + parallax model 0.11 cm + the placement error being measured, up to
D8's 1.2 cm refusal) and stay under half the tightest pitch (1.9 cm on X). **1.5 cm
satisfies both**, though not by a wide margin — it is the number most likely to
need adjusting on the bench.

**What still limits height, and it is not much.** Occlusion is real but mild: at
row 0 the view is 29.7° off vertical, so a neighbour must be **8 levels taller**
to hide a block's centre in Y, and occlusion in X never hides a centre at all.
D6 already refuses any block with a taller neighbour, so occlusion is excluded
before it can matter.

What genuinely remains is **untested**: the detector has not been exercised on
tall stacks, where a block is up to 13% larger in frame and `_rectify`'s
population median size is a poor fit for it. Centres — the only thing stage 15
uses — should be unaffected, but that is reasoning, not measurement. Treat levels
above 2 as working-but-unverified, and have the advisory pass report which levels
it actually matched so the first session settles it.

### D8 — A correction band, not a threshold

The re-place uses the same claw and the same axes as the original place, so it
carries the same placement error. "Correcting" an error comparable to the
machine's own repeatability is a coin flip that can make things worse.

| Measured error | Action |
| --- | --- |
| `< 0.5 cm` | ignore — not worth physically disturbing a block for |
| `0.5 – 1.2 cm` | correct |
| `> 1.2 cm` | **refuse**, halt, flag for a human |

**Jaw clearance is not the binding constraint.** Measured on the bench: the jaws
straddle the 2.2 cm block and pit into the gap on either side, and the clearance
is proper. So the upper bound is set by **neighbour contact**: every gap on both
axes of both modes is 1.6 cm, so a block offset by 1.6 cm has its edge against
the neighbouring block, and gripping it disturbs two blocks instead of one.
1.2 cm keeps a margin under that.

The lower bound is still provisional and **must be measured**: 0.5 cm needs
confirming as comfortably above the machine's placement repeatability. If
repeatability turns out to be near 0.5 cm the band is effectively empty, and the
honest conclusion is that this feature cannot help.

### D9 — Re-verify, and never trust a silent grip

The one genuinely new failure mode: **a claw that closes on nothing reports
success.** The firmware cannot detect it — there is no grip sensor. So after a
correction, stage 15 looks again and confirms the block actually moved to where
it was sent. If it did not, that is a halt-and-inspect, not a retry.

A correction that is not re-verified is a guess with extra steps.

### D10 — One correction per stage-15 pass

Find the worst offender, fix it, re-verify, stop. If several blocks are out of
place, that is not a placement error — it is a knocked rail, a wrong mode latch
or a stale map, and the answer is a human, not fifteen pick-and-places.

### D11 — Off by default

A toggle in the build UI, defaulting **off**. It moves the machine without an
explicit per-action operator command, which is reason enough for opt-in.

---

## 3. The as-built memory — **BUILT**

`python/rig/placement_ledger.py`, built as
[placement supervision](placement-supervision.md) M1 and covered by
`tests/test_placement_ledger.py` (42 checks). It is written at one hook —
`BuildController.build()`'s `PLACED` branch — reaches the controller through an
optional `ledger=` field so that `BuildController` still knows nothing about
OpenCV, and it admits `PLACED` only.

**Three things this section asked for that it delivers**, and one it does not:

- per cell the top level, and when — `expected_top_level()`, `placements()`
- D5 and D6's predicates — `is_top_of_column()`, `has_taller_neighbour()`, with
  an empty cell sorting **below** level 0 so any neighbour with a block on it is
  taller, which is the answer that keeps the claw safe
- in-process only; refuse after a restart — `has_memory` is False on a fresh
  process and supervision reports `NO MEMORY`. It *is* appended to
  `logs/placements.log` for the thesis record, and that file is **never read
  back**
- **it does not store the rotation.** That was dropped deliberately: rotation is
  a property of the active grid, so it is identical to the mode the ledger is
  already keyed by, and a second copy is a copy that drifts. Anywhere below that
  says "the rotation that placed it", read "the mode it was placed in".

The audit that established it was missing is kept below, because it is the
evidence that no *other* part of the system already knew this and it is still
true of every one of those places:

- `countPlacedBlock()` ([:4038](../../arduino/build_vertical_grid/build_vertical_grid.ino#L4038))
  is a histogram — `statBlocksAtLevel[level]++`. It does not record the cell.
- `BuildJob` ([build_job.py:45](../../python/rig/build_job.py#L45)) is a
  one-block worker with no history.
- No occupancy model in `orchestrator.py`, `build_controller.py` or `web/state.py`.
- `compile.ts` emits ops carrying `col`/`row`/`level`/mode — but that is the
  **plan**, not the as-built.

So it was a prerequisite, not a detail — and it is now met. D5, D6 and D7 are
all enforced from it, which makes it the safety backbone of the feature and not
merely bookkeeping.

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
`buildPlacementOffsetSteps() + buildSkewSteps()` after `cellTargetPosition()` and
before the move. A per-command offset is a third term in the same slot: a
machine-space nudge that the grid model never sees. This is the established
pattern for "move the machine without moving the grid" and it is why Rule 1
survives contact with the firmware.

`parseSignedCm` already exists (`handleShiftCommand`,
[:3300](../../arduino/build_vertical_grid/build_vertical_grid.ino#L3300)); a
five-argument parser does not.

**No local Arduino toolchain.** Per [AGENTS.md](../../AGENTS.md), syntax-check
with the stub-Arduino `g++` harness, state plainly that the result is unflashed
and unverified on hardware, and pair both sketches — `build_vertical_grid.ino`
**and** `build_horizontal_grid.ino` (6,132 and 6,135 lines) — in the same commit,
with `python/tests/test_grid.py` extended to cover the new verb.

---

## 5. What could still go wrong

1. **The silent grip failure (D9)** — the only genuinely new failure mode, and
   the largest single risk in the design. There is no sensor that can catch it;
   only the re-look can.
2. **Pick accuracy vs jaw capture range — unmeasured.** To grip a displaced block
   the claw must arrive at its *observed* position, and our knowledge of that is
   the map's error (0.27 cm mean, 2.07 px max) plus centroid noise plus parallax
   model error: call it ±0.3–0.5 cm. Clearance being proper settles whether the
   jaws *fit*; it does not settle how far off-centre they can close and still
   grip rather than shove. `SERVO_CLOSE_ANGLE = 144` is calibrated for a block
   presented squarely by the feeder, not one approached with 0.4 cm of slop.
   **This is the cheapest high-value experiment available** — place a block
   deliberately 0.5 cm off and see whether the claw grips it or knocks it.
3. **The re-place is not more accurate than the place** (D8). If bench
   measurement shows repeatability near 0.5 cm, the correction band is empty and
   the honest answer is that this feature cannot help.
4. **Detection on tall stacks is untested** (D7). Reasoning says centres survive;
   nothing has measured it. Also the 1.5 cm match radius has under 0.4 cm of
   headroom against half the X pitch — the likeliest number to need bench
   adjustment.
5. **A knocked block that memory still believes in.** The no-intervention
   assumption is load-bearing and undetectable when violated.
6. **~~The nadir is unknown.~~** Resolved: measured at `(11.4, 32.5)`, and the
   model is insensitive to ±2 cm (D4).
7. **~~The grip descends into a narrowed gap.~~** Resolved: jaw clearance is
   proper; neighbour contact at 1.6 cm is the real bound (D8).

---

## 6. Not doing

- **Correcting more than one block per pass** (D10).
- **Correcting a buried block** (D5) **or one in a valley** (D6).
- **Writing anything to the grid, the lattice origin, `error_offset_*`,
  `shift_*`, or `config/rig.json`'s geometry.** Ever. (§1a)
- **Inferring levels from vision.** Memory is authoritative (D3).
- **Persisting the as-built memory *as authority*.** In-process only; refuse
  after a restart (§3). It *is* written to `logs/placements.log` as evidence,
  and nothing ever reads that file back.
- **Systematic drift calibration.** That is the predecessor document's feature and
  it remains unbuilt.

---

## 7. Feasibility

Split the feature in two, because the halves have very different risk.

**The measurement half — high confidence.** As-built memory, observed-vs-commanded
in cm, parallax correction, stage-15 orchestration, the UI toggle, advisory
output. Every piece exists or is arithmetic; the parallax inputs are now measured
and the model is robust to their error. Nothing here moves the machine.

**The correction half — genuinely uncertain.** It drives the claw into a finished
structure, it needs a new verb in two 6,100-line sketches that **cannot be
compiled or tested locally**, and its viability rests on two numbers nobody has
measured: jaw capture tolerance and placement repeatability. Each debug iteration
is flash → run into a real structure → watch what breaks.

| Piece | Difficulty |
| --- | --- |
| As-built memory (in-process) | **2 / 5** |
| Observed-vs-commanded, parallax-corrected | **2 / 5** |
| Own detection pass (`grid=None`) + memory-driven matching (D7) | **3 / 5** |
| Stage-15 orchestration + UI toggle + advisory output | **2 / 5** |
| Safety rules D5 / D6 / D7 and proving them | **3 / 5** |
| The `P` verb in both sketches | **4 / 5** — unflashable and untestable locally |
| Confirming the band is not empty (D8) and the grip lands (§5.2) | **bench work, unavoidable** |

**Overall: 3 / 5**, but unevenly distributed — most of the difficulty and nearly
all of the risk sits in the last two rows.

---

## 8. The implementation plan

Three stages with **gates between them**. Stage B can kill stage C, and that is
the point of ordering it this way.

### Stage A — measurement only, no motion (build this first, unconditionally)

Nothing in stage A can move the machine. It is safe to run on a live rig from
day one, and it is independently useful even if stage C is never built.

**New files**

| File | Holds |
| --- | --- |
| `python/rig/placement_ledger.py` | **BUILT.** The as-built memory (§3): per cell the top level and when, keyed by mode (rotation ≡ mode, so it is not stored separately). Plus the D5/D6 predicates — `is_top_of_column`, `has_taller_neighbour`. Pure, no OpenCV. |
| `python/rig/placement_check.py` | D4 parallax, D7 matching, D8 banding. `parallax_excess(level, x_cm, y_cm) -> (dx, dy)`, `match(predictions, detections) -> matches`, `judge(error_cm) -> IGNORE / CORRECT / REFUSE`. Pure functions, no camera, no rig, no OpenCV. |
| `python/rig/stage15.py` | the orchestration: take the parked frame, run its own `detect_aligned_blocks(frame, grid=None)`, project through the `WorkspaceMap`, parallax-correct, match, judge, return a report. Advisory only in stage A — it returns findings and does nothing with them. |
| `python/tests/test_placement_ledger.py` | |
| `python/tests/test_placement_check.py` | |
| `python/tests/test_stage15.py` | |

**Edits**

| File | Change |
| --- | --- |
| `config/rig.json` | add the `camera` section: `height_cm: 57.0`, `nadir_x_cm: 11.4`, `nadir_y_cm: 32.5` |
| `python/rig/config.py` | load it |
| `python/rig/build_controller.py` | record every `PLACED` result into the ledger — cell, level, rotation. One call at the existing `elif str(result) == PLACED:` branch. |
| `python/web/state.py` | surface `stage15_*` fields (D2) — never `build_*` |
| `python/web/routes_command.py` | the toggle, and a manual "check now" |
| `web/src/…` | the toggle (default off, D11) and the findings strip |
| `docs/STUDIO.md` | if the toggle lands in the Studio UI, same commit, with changelog |

**`vision/` is not touched.** Stage 15 calls the existing detector with different
arguments; it adds no detector and modifies no module there. The layering rule of
[BLOCK-VISION §7](../BLOCK-VISION.md) holds.

**Gate out of stage A:** run it advisory for a session and answer — are the
errors real, are any above 0.5 cm, and **does the parallax prediction agree with
a ruler at level 2?** If the parallax model does not validate, stop; everything
downstream inherits it.

### Stage B — two bench measurements (gates stage C)

Neither needs code. Both are ~20 minutes.

1. **Jaw capture tolerance** (§5.2). Place a block deliberately 0.5 cm off; drive
   the claw to it; does it grip, or shove? Repeat at 0.8 and 1.2 cm. This decides
   whether stage C can work at all.
2. **Placement repeatability** (§5.3). Place the same cell repeatedly and measure
   the spread. If it is near 0.5 cm, D8's band is empty and **stage C should not
   be built.**

### Stage C — the correction (only if A and B come back favourable)

| File | Change |
| --- | --- |
| `arduino/build_vertical_grid/build_vertical_grid.ino` | the `P` verb (§4) |
| `arduino/build_horizontal_grid/build_horizontal_grid.ino` | the same, same commit |
| `AGENTS.md` §6 | add `P` to the command vocabulary; give it an `@` ack so it is safe from rewording, as `B` is and `S`/`G`/`0` are not |
| `python/rig/link.py` | `replace_block()` beside `build()`, with the same abort discipline |
| `python/rig/mock_board.py` | mock `P` so the whole path is testable off-rig |
| `python/rig/stage15.py` | act on the finding: correct, re-verify (D9), stop (D10) |
| `python/tests/test_grid.py` | extend — it parses the sketch and is the drift check |
| `python/tests/test_link.py` | `P` ack shape and abort handling |
| `docs/ack-protocol.md` | the `P` ack |

**No local Arduino toolchain** (§4): stub-`g++` syntax check, say plainly the
result is unflashed and unverified, and never claim otherwise.

### Checks after any stage

```bash
python3 python/tests/test_grid.py     # firmware <-> config pairing
cd web && npx vitest run              # Studio / coords / Twin
cd python && python3 -m pytest tests/ # the rest
```

Known pre-existing failures, not regressions: `mock_camera_test.py`,
`test_combined_grid`, `test_color_tuning`, `test_camera_performance`,
`test_block_outline`.

---

## 9. Implementation style

Match the repo; it has a strong and consistent house style.

**Layering.** `rig/` orchestrates and knows nothing about OpenCV beyond passing
arrays through — `block_calibration.py` says so in its own docstring and is the
model to copy. `vision/` stays unmodified. Pure geometry (`placement_check.py`)
must be importable and testable with no camera, no serial port and no frame.

**Docstrings explain *why*, not *what*.** The house style is a module docstring
with named sections — "Why it is step-wise rather than one call", "The two safety
rules that are not negotiable". `block_calibration.py` and `progress.py` are the
templates. The D5/D6/D8 refusals each need a sentence saying what they are
protecting against, because none of them is obvious from the code.

**Dataclasses, frozen, for results.** `BuildOutcome`, `BlockGridReport`,
`BuildProgress` are all frozen dataclasses with a docstring naming what exactly
one of them means. Stage 15's finding should be one too.

**`from __future__ import annotations`** at the top of every new module.

**Tests are hand-rolled, not pytest, where the neighbours are.**
`test_build_controller.py` uses a `check(name, condition, detail)` helper with
`PASSED`/`FAILED` lists and prints one aligned line per assertion; `test_grid.py`
is the same shape at 221 checks. Match the file you sit beside rather than
importing a new idiom. Fakes over mocks: `FakeRig` in `test_build_controller.py`
is the pattern.

**Assert named physical scenarios, not bare numbers.** Inherited from the
predecessor doc and it still applies: *"a block at [0,0] level 2 is seen 1.9 cm
toward −Y; the parallax model must explain all of it and the residual error must
be under the ignore threshold"* beats `assert 1.9 == 1.9`, which passes just as
happily with the sign inverted.

**Sign discipline.** [AGENTS.md](../../AGENTS.md) Rule 0 and 0a: every
calibration number is a magnitude from that axis' home switch, `+` away from
home; X's `axisPos[]` runs the opposite way, and the two spaces are crossed only
via `axisPosFromHomeSteps()` / `axisStepsFromHome()`. Stage 15's `(dx,dy)` goes
on the wire in **cm magnitudes** and is converted inside the firmware at the
`gotoBuildTarget()` injection point, exactly as `buildSkewSteps()` already is —
so the conversion happens once, in the place that already gets it right.

**Refusals are refusals.** D5, D6 and D8's upper bound halt and say why. They do
not warn and continue, and they do not clamp — a clamped 3 cm error is a 1.2 cm
correction applied to a machine that has something else wrong with it.

**Docs in the same commit as the code.** `docs/STUDIO.md` and its changelog for
any Studio change; `AGENTS.md` §6 and `docs/ack-protocol.md` for the `P` verb;
this document's status line when a stage lands.

---

## 10. Where to start

Stage A of §8, and nothing else, until its gate is answered.

Stopping after stage A still leaves a feature worth having: the machine tells you
which block is out of place, by how much, and on which level — with the parallax
accounted for, which is the part a person cannot do by eye. The claw never has to
touch it for that to be useful, and everything risky in this document lives on
the other side of a gate that stage A exists to open.

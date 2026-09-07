# Feature designs — one file per idea, audited against the repo

[feature-ideas.md](../feature-ideas.md) is the **catalogue**: everything worth
building, sorted by what it costs and what it buys. This directory is the level
below it — a full design for one specific feature, written after auditing what
the repo actually contains today, and kept only while the feature is unbuilt.

**When one of these lands, fold it into the living doc for the subsystem it
touches and delete the file**, exactly as [plans/README.md](../../plans/README.md)
requires. A second, drifting description of built code is worse than none.

**One deliberate exception: [placement supervision](placement-supervision.md)
and its [build record](placement-supervision-progress.md) are kept after
landing.** Six of that design's own decisions were found to be wrong on contact
with the rig or the code, and the corrections — with the measurements behind
them — are the part a future reader needs. The living docs
([CAMERA.md](../CAMERA.md), [DESIGN.md](../DESIGN.md),
[CONSOLE.md](../CONSOLE.md), [STUDIO.md](../STUDIO.md)) carry what the system
*does*; those two carry **why it does it that way and what was tried first**.
Neither describes code that the living docs also describe.

| Feature | Status | Difficulty | The one-sentence version |
| --- | --- | --- | --- |
| [Running-bond grid shift](running-bond-grid-shift.md) | **built** (unflashed firmware unchanged) | 3 / 5 | A level can carry a half-pitch course offset on the run axis so a block bridges the joint of the two beneath it — Studio, Twin, compiled program and `POST /api/shift` all agree; supersedes the row below. |
| [Grid shift in the twin](grid-shift-in-the-twin.md) | **folded into** running-bond grid shift | 2–3 / 5 | Every web coordinate function already takes a `shift`; the twin is the one caller that never passes one, because the server never publishes it. |
| [Placement supervision](placement-supervision.md) | **BUILT** — Gate 0 measured on the rig, M1/M2/M3a/M3b landed; M4 (repair) and M5 (lift the ceiling) remain future work. **Not yet watched on hardware.** Kept, with [its build record](placement-supervision-progress.md), because six of its own decisions were found wrong in the building and the corrections are the useful part | 4 / 5 | Give the rig a memory of what it placed, a quiet-window look at the board, and the discipline to say when they disagree — per-build *and* continuously, so it also catches a human moving a block. |
| [Camera parallax and levels](camera-parallax-and-levels.md) | **future work** — deliberately ignored by supervision v1, whose level-3 ceiling is now **enforced in code**: `rig.supervisor.LEVEL_CEILING`, and refused cells are listed as `unjudged` rather than silently skipped | 2 / 5 | The workspace map is fitted to one plane, so a stacked block is reported displaced away from the camera — predictably. Ignoring it costs a hard detection ceiling at level 3. |
| [Stage 15 — between-job placement correction](stage-15-placement-correction.md) | **not started** — design agreed; supersedes between-build error calibration. **Its as-built memory is now built**: `PlacementLedger`, including Stage 15's own D5/D6 safety predicates `is_top_of_column()` and `has_taller_neighbour()` | 3 / 5 | After a job parks, find the one block meaningfully out of place, pick it up and set it down properly, re-verify — an outlier repair, never a calibration, never touches the grid. |
| [Between-build error calibration](between-build-error-calibration.md) | **DEFERRED (2026-09-06)** — superseded by Stage 15; measurement half exists in the code, no feedback path | 4 / 5 | Turn a *population* of placement residuals into a bounded correction to the grid origin. Deferred in favour of per-stage outlier repair; un-defer only if [§3.1](../feature-ideas.md#31-placement-repeatability-and-backlash---highest-value-per-line) shows a systematic bias, which per-block repair cannot fix. |
| [Removed-block compensation](removed-block-compensation.md) | **its detection half is BUILT** — placement supervision's continuous verdict already catches a removed block mid-program and pauses the runner. What remains unbuilt is the *compensation*: re-planning or re-placing, which is supervision's M4 | 5 / 5 | Mid-*command* verification is impossible; mid-*program* verification is not, because the runner already stops between every block. |
| [Block identity](block-identity.md) | **DEFERRED** — no tracker built (D1). Analysis only: three tiers, what each unblocks, why full re-ID is not feasible on this camera, and the cheap window-association tier that most questions are actually reaching for | 3 / 5 (tier A) | Every block is interchangeable and every verdict names a *cell*; identity would only let a verdict say "block #17" instead of "the block at [3,2]", which changes no operator action. |

## Read these first

- [AGENTS.md](../../AGENTS.md) — the calibration-knob reference and the sign
  convention. Every one of these features touches a knob.
- [placement-supervision.md](placement-supervision.md) — **start here for
  anything that needs to know what is on the board.** Its M1 memory is the
  shared substrate for Stage 15, removed-block compensation and (if ever
  un-deferred) between-build calibration. Build it once. Its §2a lists three
  things the older designs got wrong about the code.
- [feature-ideas.md Appendix A](../feature-ideas.md#appendix-a--placement-supervision-full-design)
  — the original supervision design. Superseded by the file above; kept for its
  reasoning, not as a work item.
- [BLOCK-VISION.md](../BLOCK-VISION.md) — the layering rule, and the measured
  numbers (0.27 cm map flattening error, 29/29 detection) these designs quote.

## Build order

1. **Grid shift in the twin** — done (folded into running-bond grid shift).
2. **[Placement supervision](placement-supervision.md) M1** — the memory. Pure
   data, no vision, one hook in `BuildController`. Shared by everything below.
3. **Supervision M2** — the observer, report-only. Gate: watch the interlocks on
   the real bench for a session before anything depends on them.
4. **Supervision M3a** — the per-build verdict. Cheapest high-value step in the
   set: the client path already exists, so one published string field lights up
   the runner log and the run report.
5. **Supervision M3b** — continuous idle verdicts. The demonstrable milestone.
6. **[feature-ideas.md §3.1](../feature-ideas.md#31-placement-repeatability-and-backlash---highest-value-per-line)**
   — placement repeatability and backlash. Decides whether Stage 15's correction
   band is empty, and whether **between-build error calibration** comes back off
   the shelf.
7. **Stage 15 Stage A**, then [parallax](camera-parallax-and-levels.md), then
   Stage 15 Stage C, then removed-block compensation R1.

Nothing later in that list should start before the thing above it has run on
real hardware for a session.

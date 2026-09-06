# Feature designs — one file per idea, audited against the repo

[feature-ideas.md](../feature-ideas.md) is the **catalogue**: everything worth
building, sorted by what it costs and what it buys. This directory is the level
below it — a full design for one specific feature, written after auditing what
the repo actually contains today, and kept only while the feature is unbuilt.

**When one of these lands, fold it into the living doc for the subsystem it
touches and delete the file**, exactly as [plans/README.md](../../plans/README.md)
requires. A second, drifting description of built code is worse than none.

| Feature | Status | Difficulty | The one-sentence version |
| --- | --- | --- | --- |
| [Running-bond grid shift](running-bond-grid-shift.md) | **built** (unflashed firmware unchanged) | 3 / 5 | A level can carry a half-pitch course offset on the run axis so a block bridges the joint of the two beneath it — Studio, Twin, compiled program and `POST /api/shift` all agree; supersedes the row below. |
| [Grid shift in the twin](grid-shift-in-the-twin.md) | **folded into** running-bond grid shift | 2–3 / 5 | Every web coordinate function already takes a `shift`; the twin is the one caller that never passes one, because the server never publishes it. |
| [Placement supervision](placement-supervision.md) | **not started** — designed, this is the build plan; **merges and supersedes** Appendix A's `PlacementLedger` and Stage 15 §3's as-built memory | 4 / 5 | Give the rig a memory of what it placed, a quiet-window look at the board, and the discipline to say when they disagree — per-build *and* continuously, so it also catches a human moving a block. |
| [Camera parallax and levels](camera-parallax-and-levels.md) | **future work** — deliberately ignored by supervision v1 | 2 / 5 | The workspace map is fitted to one plane, so a stacked block is reported displaced away from the camera — predictably. Ignoring it costs a hard detection ceiling at level 3. |
| [Stage 15 — between-job placement correction](stage-15-placement-correction.md) | **not started** — design agreed; supersedes between-build error calibration; its as-built memory is now [placement supervision](placement-supervision.md) M1 | 3 / 5 | After a job parks, find the one block meaningfully out of place, pick it up and set it down properly, re-verify — an outlier repair, never a calibration, never touches the grid. |
| [Between-build error calibration](between-build-error-calibration.md) | **DEFERRED (2026-09-06)** — superseded by Stage 15; measurement half exists in the code, no feedback path | 4 / 5 | Turn a *population* of placement residuals into a bounded correction to the grid origin. Deferred in favour of per-stage outlier repair; un-defer only if [§3.1](../feature-ideas.md#31-placement-repeatability-and-backlash---highest-value-per-line) shows a systematic bias, which per-block repair cannot fix. |
| [Removed-block compensation](removed-block-compensation.md) | **not started** — idle half already designed in [Appendix A](../feature-ideas.md#appendix-a--placement-supervision-full-design) | 5 / 5 | Mid-*command* verification is impossible; mid-*program* verification is not, because the runner already stops between every block. |

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

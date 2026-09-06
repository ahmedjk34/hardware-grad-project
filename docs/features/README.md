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
| [Stage 15 — between-job placement correction](stage-15-placement-correction.md) | **not started** — design agreed; supersedes between-build error calibration | 3 / 5 | After a job parks, find the one block meaningfully out of place, pick it up and set it down properly, re-verify — an outlier repair, never a calibration, never touches the grid. |
| [Between-build error calibration](between-build-error-calibration.md) | **DEFERRED (2026-09-06)** — superseded by Stage 15; measurement half exists in the code, no feedback path | 4 / 5 | Turn a *population* of placement residuals into a bounded correction to the grid origin. Deferred in favour of per-stage outlier repair; un-defer only if [§3.1](../feature-ideas.md#31-placement-repeatability-and-backlash--highest-value-per-line) shows a systematic bias, which per-block repair cannot fix. |
| [Removed-block compensation](removed-block-compensation.md) | **not started** — idle half already designed in [Appendix A](../feature-ideas.md#appendix-a--placement-supervision-full-design) | 5 / 5 | Mid-*command* verification is impossible; mid-*program* verification is not, because the runner already stops between every block. |

## Read these first

- [AGENTS.md](../../AGENTS.md) — the calibration-knob reference and the sign
  convention. Every one of these features touches a knob.
- [feature-ideas.md Appendix A](../feature-ideas.md#appendix-a--placement-supervision-full-design)
  — the placement-supervision design. Stage 15's as-built memory, removed-block
  compensation and (if ever un-deferred) between-build calibration all need a
  server-side placement record; build it once.
- [BLOCK-VISION.md](../BLOCK-VISION.md) — the layering rule, and the measured
  numbers (0.27 cm map flattening error, 29/29 detection) these designs quote.

## Build order

1. **Grid shift in the twin** — done (folded into running-bond grid shift).
2. **The `PlacementLedger` / as-built memory** (Appendix A M1, Stage 15 §3) —
   shared by Stage 15, supervision and removed-block compensation.
3. **Stage 15 — Stage A only** (measurement, no motion): as-built memory,
   observed-vs-commanded in cm, parallax correction, advisory output. Gate on
   whether the parallax model validates against a ruler at level 2.
4. **[feature-ideas.md §3.1](../feature-ideas.md#31-placement-repeatability-and-backlash--highest-value-per-line)**
   — placement repeatability and backlash. This is also the check that decides
   whether **between-build error calibration** has to come back off the shelf.
5. **Supervision M2–M3**, then Stage 15 Stage C, then removed-block
   compensation R1.

Nothing later in that list should start before the thing above it has run on
real hardware for a session.

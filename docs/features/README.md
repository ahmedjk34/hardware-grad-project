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
| [Between-build error calibration](between-build-error-calibration.md) | **partial** — measurement exists, feedback path does not | 4 / 5 | Turn a measured placement residual into a bounded, provenance-carrying correction to the grid origin — and pick the honest knob to apply it with. |
| [Removed-block compensation](removed-block-compensation.md) | **not started** — idle half already designed in [Appendix A](../feature-ideas.md#appendix-a--placement-supervision-full-design) | 5 / 5 | Mid-*command* verification is impossible; mid-*program* verification is not, because the runner already stops between every block. |

## Read these first

- [AGENTS.md](../../AGENTS.md) — the calibration-knob reference and the sign
  convention. Every one of these features touches a knob.
- [feature-ideas.md Appendix A](../feature-ideas.md#appendix-a--placement-supervision-full-design)
  — the placement-supervision design. Two of the three features above depend on
  its `PlacementLedger`; build it once.
- [BLOCK-VISION.md](../BLOCK-VISION.md) — the layering rule, and the measured
  numbers (0.27 cm map flattening error, 29/29 detection) these designs quote.

## Build order, if you build all three

1. **Grid shift in the twin** — small, self-contained, and it removes a case
   where the console shows the operator the wrong machine.
2. **The `PlacementLedger`** (Appendix A M1) — shared by both remaining features.
3. **Between-build error calibration, advisory only** — measure for a session
   before anything applies anything.
4. **Supervision M2–M3**, then removed-block compensation R1.

Nothing later in that list should start before the thing above it has run on
real hardware for a session.

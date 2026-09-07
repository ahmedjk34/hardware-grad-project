# Handoff prompt — complete placement supervision

Copy everything below the line into a fresh agent session.

---

Complete the PLACEMENT SUPERVISION feature in this repo
(hardware-grad-project). Gate 0 and M1 are done, M2's logic is done and
unwired. You are finishing M2's integration, M3a, and M3b.

## READ FIRST, IN THIS ORDER — do not write code until you have

1. **`AGENTS.md`** — the authority for this repo. Especially Rule 0 (sign
   convention) and §7 (one owner thread for OpenCV work).
2. **`docs/features/placement-supervision-progress.md`** — **THE BUILD RECORD.
   Read this before the design doc.** It carries the Gate 0 measurements, ten
   findings from the rig, two places where the design was found wrong, and the
   open decisions P1–P7. Several of its findings override the design.
3. **`docs/features/placement-supervision.md`** — the design: D1–D14, M1–M5,
   §6's full UI spec, §8's tests, §9's known limits.
4. **`docs/CAMERA.md`** — §5 (why the error detector is not in `vision/`),
   §7 (what the camera cannot do), §8 (the status board — tick boxes as you
   land things).
5. **`docs/DESIGN.md`** — §2 colour is reserved, §4 the state model,
   §7 accessibility, §8 what must not be done.
6. **`docs/BLOCK-VISION.md` §7** — the layering rule.

Then read `python/rig/supervisor.py` and `python/rig/placement_ledger.py` in
full. They are built, tested and commented with their own reasoning.

## STATE OF PLAY

**Done:** Gate 0 (measured on the rig, constants set), M1 (ledger + hook + log
+ 42 tests), M2 logic (`locate`/`observe`/`classify`/hysteresis/interlocks +
63 tests).

**Not done:** wiring the supervisor into `web/app.py`, M3a, M3b.

**Measured constants, already in `supervisor.py` — do not change them:**
`QUIET_DIFF_FRACTION = 0.01`, `SETTLE_N = 3`, `SETTLE_M = 5`. The pipeline runs
at **8.6–8.7 Hz, not 10**, so a 5-frame settle is 0.58 s.

## SCOPE — build ONLY these, in this order, gated

- **P-decisions first** (see below) — they change `classify()` and are cheapest
  now, before four UI surfaces render its output.
- **M2 wiring** — supervisor into `_drive_pipeline`, frame difference on the
  single-threaded executor. Then STOP and report: this one wants a bench session.
- **M3a** — per-build verdict at `_publish_build_result`, `vision_verification`
  on `StateModel`.
- **M3b** — `SupervisionModel`, `POST /api/supervision/ack`, then the four UI
  surfaces, **camera overlay first**.

**DO NOT BUILD:** M4 automatic repair, Stage 15, the `P` firmware verb, parallax
correction, `block_levels` validation. **NO FIRMWARE CHANGES. Do not touch
`arduino/`.** `vision/` is not touched — consume `ProcessedFrame.detections` and
`WorkspaceMap`, add no detector, take no extra frames.

## DECISIONS TO CONFIRM WITH THE USER BEFORE CODING

`progress.md` §4 carries P1–P7. Three need a human answer; ask them together, in
one question, before writing anything:

- **P1 (recommended)** — refine D9 so N missing / 0 unexpected → `REMOVED`
  naming all N, and 0 missing / N unexpected → `FOREIGN` naming all N.
  `DISAGREES` is reserved for the genuinely ambiguous both-sides case. This
  **deviates from the approved design** and the reasoning is in §3 Q8.
- **P2** — reset hysteresis when the detection count crosses
  `MIN_LATTICE_BLOCKS`, same argument as D13's mode reset.
- **P5** — `test_grid.py` currently fails on an unrelated firmware change
  (F10). Not your scope to fix, but confirm the user knows it is failing and
  whether they want it left alone.

P3, P4, P6, P7 are yours to just do as you pass through.

## THE TRAPS — all found by reading the code or measured on the rig

1. **`_lattice_filter` is not a board-membership test.** It fits an *infinite*
   lattice from the detections themselves; an object well off the board can land
   near an integer index and survive. Measured: one off-board object persisted
   in 523/524 frames with the filter engaged. Only the calibrated `WorkspaceMap`
   answers "is this on the board".
2. **`cell_at → None` means three different things** and `rig.supervisor.locate()`
   already splits them: `gap` (on the board, off every site — real `FOREIGN`),
   `margin` and `outside` (rails and offcuts — **ignored**). **Never collapse
   these back into one number.** The merged version emitted `FOREIGN` in 99.8%
   of windows on a correct board. There is a regression test.
3. **Detections are not labelled with cells.** `_lattice_filter` solves indices
   relative to `detections[0]` only to decide keep/reject, then discards them.
   Pixel→cell is your work, and it is already done in `observe()`.
4. **Rotation ≡ grid mode.** Never store it separately.
5. **The frame difference is a full-frame numpy op** (~5–15 ms on a Pi 5). It
   goes on the **same single-threaded executor** as `pipeline.process_once` and
   `encode_jpeg` in `_drive_pipeline` — AGENTS.md §7's one-owner-thread rule.
   The set maths stays on the event loop.
6. **`BuildController` knows nothing about OpenCV.** Keep it that way; the
   ledger is pure data and reaches it through an optional `ledger=` field.
7. **The pipeline is 8.6–8.7 Hz.** Any UI settle countdown must not assume 10.

## NON-NEGOTIABLE RULES

- A verdict **NEVER** sets `LOCKED`. It pauses (amber) or stops (red). `LOCKED`
  means the claw's position is unknown and needs a human plus a service restart.
- The ledger admits `PLACED` only — never rejected, never aborted.
- The ledger is persisted to `logs/placements.log` and **never reloaded as
  authority**. After a restart, report `NO MEMORY` and refuse every verdict.
- Refuse every verdict when `frame.calibrated` is false — report `NO MAP`.
- Refuse to judge any cell whose expected top level is ≥ 3. List them as
  `unjudged`, never silently skip.
- Never emit `FOREIGN` below `MIN_LATTICE_BLOCKS` (6) detections.
- Hysteresis counters **RESET**, not decay, when an interlock trips; reset on a
  `frame.grid_mode` change; suspend across a mode latch.
- **ONE server field, four readers.** No surface re-derives a verdict
  client-side.

## UI — follow the design's §6 exactly; the easy-to-get-wrong parts

- **`VERIFIED` gets NO banner.** 40 green bars per build trains people to ignore
  them. Log row plus one 200 ms cell pulse.
- **`BUSY` / `QUIET` / `NO_MEMORY` get NO state colour** — they are
  `--text-dim`. `BUSY` is the normal state for a whole build; colouring it amber
  kills the reserved palette. Not looking is not the same as finding something
  wrong.
- `MOVED` / `REMOVED` / `NOT_DETECTED` = amber, `role="status"`, **pause**.
  `FOREIGN` / `DISAGREES` = red, `role="alert"`, **stop**.
- `unjudged` cells use a **45° SVG hatch, not a colour** — an absence of state
  must not take a state colour — plus a count and reason in the banner and a
  `<title>` per cell.
- Add `--danger-text: #FF8A8A` (7.86:1). `--danger` `#FF5C5C` measures 5.89:1 on
  `--surface` and **fails DESIGN.md's own 7:1 state-text bar**. Do not lighten
  `--danger` itself — `LOCKED` depends on it. State colour carries icon + edge +
  bold chip only; body copy is `--text`.
- **Never colour alone**: every state carries a word AND an icon (● ▲ ■ ○ ◐).
- One 200 ms pulse on a new verdict, **never a loop**. Honour
  `prefers-reduced-motion`.
- **Build the CAMERA OVERLAY first** — a per-cell class in `GridOverlay.tsx`,
  exactly how `blocked` cells already work today. Cheapest surface and the one
  the operator is looking at.
- **No sixth `TwinAppearance`.** The twin has exactly five and `twin.test.ts`
  asserts them. Supervision is a separate overlay layer.
- Copy per §6.9: name the cell in the first four words, say what to do, never
  say "error" for something the machine may have got right.

## THE FREE WIN IN M3A

The client path for the per-build verdict is **already wired end to end and
nothing populates it**: `RunnerPanel.tsx:182` reads `vision_verification` →
`runner.ts`'s `RunLogEntry.verification` → `run-report.ts` already emits it as a
Markdown column. **One string field from Python lights up the runner log and the
thesis run report with zero client work.** Add it to `_SEMANTIC_FIELDS` in
`app.py` so it publishes immediately rather than on the 5 Hz geometry throttle.

## TESTS

Match the neighbouring style — `test_build_controller.py`, `test_grid.py`,
`test_placement_ledger.py` and `test_supervisor.py` are hand-rolled with a
`check(name, condition, detail)` helper and PASSED/FAILED lists. Fakes over
mocks. `from __future__ import annotations` at the top of every new module.
Frozen dataclasses for results.

**ASSERT EXACT CELL SETS, NEVER COUNTS** — a count assertion passes on a board
renumbered by one cell, which is the failure that matters.

Gate after every milestone, and report before continuing:

```bash
python3 python/tests/test_grid.py
cd web && npx vitest run
cd python && python3 -m pytest tests/
```

**Known failures that are NOT yours:**
- `mock_camera_test.py` (2 tests) — documented pre-existing
- `web_state_test.py::test_events_send_initial_update_and_heartbeat` — flaky,
  verified failing on a clean tree
- `test_grid.py`'s `zGoPickup()` check — an unrelated firmware change, F10
- `test_combined_grid`, `test_color_tuning`, `test_camera_performance`,
  `test_block_outline` — missing fixtures on a clean checkout

## WHEN YOU LAND SOMETHING

Tick the box in `docs/CAMERA.md` §8, and **in the same commit** fix any prose the
change makes false. In particular: §0 and §6a currently say the camera "never
makes an assertion the system acts on". That is still true today and **M3a makes
it wrong** — correct it in the M3a commit, not later.

Add anything you measure or discover to
`docs/features/placement-supervision-progress.md`, in its own numbered finding.

## HOW TO WORK

Stop at each gate and report before continuing. If a measurement contradicts the
design, say so and stop rather than working around it — that has already
happened twice on this feature and both times the design was the thing that was
wrong. There is no camera on the dev desktop, so say plainly which paths are
unverified on hardware rather than implying otherwise.

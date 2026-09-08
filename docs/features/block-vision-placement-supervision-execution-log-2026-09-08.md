# Block-vision placement-supervision execution log

Date: 2026-09-08

## CURRENT RESUME STATE

- Completed and verified: Section 8 item 1 (pre-existing); Section 8 item 2 (`NO_VISION` propagation for detector failure and stale frames — implemented, tested, committed on `main`).
- Implemented but unmerged: none.
- Active or blocked work: Phase 1 continues with item 7 (`python/rig/supervisor.py` gap-history reset/decay semantics). Items 7, 8, 4 remain serialized in that order per the Phase 0 overlap finding.
- Unmerged branches/worktrees: none.
- Next required action: start item 7 — clear `_gap_history` through the same reset primitive as `_CellHistory` on every mode/interlock/no-memory transition, and hysterese gap-verdict clearing with a persistent per-gap identity. Add the leaked-gap-vote regression the audit calls for (existing interlock-reset test only checks the first warming frame).

## Phase 0 — status audit

### Agent `phase0_audit`

- Assigned item(s): read-only Phase 0 audit; confirmation of item 1; file, test, and overlap mapping for items 2–9.
- Branch/worktree: `main`; `/home/ahmedjk34/Desktop/Work_Dev/Miscellaneous/hardware-grad-project`.
- Files changed: none.
- Implementation summary: confirmed that item 1 is implemented by the coherent analysis handoff in `analysis_worker.py`, `console_pipeline.py`, and `web/app.py`; identified unresolved implementation paths for items 2–9; found direct overlap among the requested Phase 1 tasks.
- Tests added: none.
- Exact test commands and results:
  - `.venv/bin/python -m pytest -q python/tests/console_pipeline_test.py` — 8 passed.
  - `.venv/bin/python -m pytest -q python/tests/web_supervision_test.py -k 'old_map_generation or completed_result_id or stale_analysis_result'` — 3 passed, 43 deselected.
  - `.venv/bin/python python/tests/test_latest_workers.py` — 25 passed, 0 failed.
- Commit hash: none (read-only audit).
- Unresolved issues: item 2 still collapses detector exceptions to empty detections; item 7 has global/leaky gap history and asymmetric clearing; item 8 has global `has_memory` and no board epoch; item 4 lacks a Pi-side exact compensated-motion preflight. Hardware motion remains unverified locally.
- Whether merged: not applicable; no changes.
- Parallelization decision: the requested four-way Phase 1 implementation is unsafe. Items 2, 7, and 8 share `python/rig/supervisor.py` and overlapping tests; item 8's epoch transition depends on item 7 reset semantics; item 4 likely shares the link/epoch capability boundary with item 8. Per the request's conflict rule, use the audited safe sequence: 2 → 7 → 8 → 4, then items 6+9 → 3 → 5.

## Phase 1 — item 2: NO_VISION propagation

### Agent `item2_no_vision`

- Assigned item(s): Section 8 item 2 only — detector failure and stale-frame propagation as `NO_VISION`; never as empty detections; never as `REMOVED`.
- Branch/worktree: `main`; `/home/ahmedjk34/Desktop/Work_Dev/Miscellaneous/hardware-grad-project` (no separate worktree; working tree was clean and no other Phase 1 work is in flight).
- Files changed:
  - `python/rig/console_pipeline.py` — `ProcessedFrame` gains `analysis_ok: bool` / `analysis_error: str | None`; `_coherent_frame` sets them from `completed.error` and forces `detections=()` on failure, so a caller that ignores the flag still cannot read a spurious REMOVED. The frame is still published (supervision must see the failure).
  - `python/web/app.py` — `_supervise` replaces the stale-only branch with a combined `not analysis_ok or frame.stale` branch: `supervisor.reset()`, drop the quiet baseline, publish state `NO_VISION` (detector reason when present, else the stale sentence), and return before `observe()` / `supervisor.step()` ever sees the empty tuple. The one-result-consumed-once dedup still runs first, so a failed result also uses up its single N-of-M opportunity.
  - `python/rig/supervisor.py` — `STATES` gains `"NO_VISION"` (raised by the app layer, not `Supervisor.step`), with a comment explaining why the distinction exists.
  - `python/web/state.py` — `SupervisionModel.state` Literal gains `"NO_VISION"`; docstring explains it is verdict-less and takes no state colour.
  - `web/src/types.ts`, `web/src/components/SupervisionBanner.tsx` — `SupervisionPhase` union, `SHAPE` map (`○`), `statusLine()` sentence, and the `dim` (no-colour) set all gain `NO_VISION`.
  - `docs/features/placement-supervision.md` — §6.3 state table, the §6 `SupervisionModel` sketch, §6.9 copy table, and §6.10 "no colour on" list all updated.
  - Tests: `python/tests/console_pipeline_test.py` (+2), `python/tests/web_supervision_test.py` (+2, plus `frame_at` helper and the existing stale test updated from `BUSY` to `NO_VISION`).
- Implementation summary: the detector exception was already caught in `AnalysisWorker._run` (`error` set, detections emptied), but `ProcessedFrame` dropped `error` and downstream `_supervise` fed the empty tuple straight into `observe()` → `supervisor.step()` → `REMOVED` on a non-empty ledger. Provenance for the failure is now first-class on `ProcessedFrame`, and `_supervise` fails closed to a distinct `NO_VISION` state for both the detector-failure and the already-handled stale-frame path. The distinction between "a successful detection that saw zero blocks" and "vision could not observe" now survives all the way to the published `SupervisionModel` and the banner, not just the verdict.
- Tests added:
  - `test_a_detector_exception_publishes_NO_VISION_not_zero_detections` — `_coherent_frame` carries `analysis_ok=False` / `analysis_error` and forces `detections=()`.
  - `test_a_successful_empty_frame_stays_analysis_ok` — a genuine zero-block frame is still `analysis_ok=True`, preserving the distinction.
  - `test_a_detector_failure_frame_is_NO_VISION_not_an_empty_board` — a failed frame after a settled VERIFIED yields state `NO_VISION`, no verdict, no correction, baseline cleared.
  - `test_detector_failures_do_not_advance_hysteresis_toward_REMOVED` — six consecutive failed frames on a non-empty ledger never settle any verdict; a clean board afterwards must re-warm from nothing.
  - `test_a_stale_analysis_result_never_becomes_quiet_evidence` — updated: stale result now reads `NO_VISION` (was `BUSY`), still no verdict, still no baseline.
- Exact test commands and results:
  - `.venv/bin/python -m pytest -q python/tests/web_supervision_test.py python/tests/console_pipeline_test.py python/tests/web_state_test.py python/tests/web_command_test.py python/tests/web_events_test.py` — 81 passed (rerun of the item-2 files alone: 58 passed).
  - `.venv/bin/python python/tests/test_supervisor.py` — 111 passed, 0 failed.
  - `.venv/bin/python python/tests/test_supervisor_frames.py` — 21 passed, 0 failed.
  - `.venv/bin/python python/tests/test_latest_workers.py` — 25 passed, 0 failed.
  - `.venv/bin/python python/tests/test_grid.py` — 239 passed, 0 failed.
  - `.venv/bin/python -m pytest -q python/tests/` — 127 passed.
  - `cd web && npx vitest run` — 42 files, 563 passed.
  - `cd web && npx tsc --noEmit` — no new errors (pre-existing `node:fs` / `node:path` / `process` type errors in `src/tokens.test.ts` only).
- Commit hash: `81282ee` (this doc line was set by a follow-up `--amend`; the tree hash it names is stable).
- Unresolved issues: none for item 2. Hardware motion remains unverified locally (no Arduino toolchain, no camera). `NO_VISION` is deliberately not a state-coloured fault — an operator sees it as a dim strip like BUSY, distinguished only by wording; if the team wants the camera-pipeline failure to be louder, that is a follow-up UI decision, not a safety gap. Items 7, 8, 4 remain open in that order.
- Whether merged: committed directly to `main` (no divergent Phase 1 branch to merge against).
- Next action: begin item 7 — unify `_gap_history` clearing with `_CellHistory` reset and add persistent per-gap identity / symmetric N-of-M clearing, with the leaked-gap-vote regression test.

# Block-vision placement-supervision execution log

Date: 2026-09-08

## CURRENT RESUME STATE

- Completed and verified: Section 8 item 1 (pre-existing); Section 8 item 2 (`NO_VISION` propagation for detector failure and stale frames — implemented, tested, committed on `main`); Section 8 item 7 (per-identity gap history, symmetric reset/decay — implemented, tested, committed `074aaf9` on `main`); Section 8 item 8 (mode- and board-epoch-specific ledger memory — implemented, tested, committed `70f2e17` on `main`).
- Implemented but unmerged: none.
- Active or blocked work: Phase 1 continues with item 4 (Pi-side exact compensated-motion reachability/clamp preflight). Item 4 was the last of the serialized 2 → 7 → 8 → 4 chain; after it, items 6+9 → 3 → 5.
- Unmerged branches/worktrees: none.
- Next required action: start item 4 — add an exact Python full-motion reachability/clamp preflight for every compensated correction target (skew + fixed build offset + tool offset + requested nudge), per active mode and the paired calibration values, with any predicted firmware clamp a hard refusal. Item 4 likely shares the link/epoch capability boundary with item 8's `board_epoch` work — build on it rather than duplicating. Item 10 is out of scope.

## Phase 1 — item 8: mode- and board-epoch-specific ledger memory

### Agent `item8_board_epoch`

- Assigned item(s): Section 8 item 8 only — make placement-ledger memory mode- and board-epoch-specific; stop `VERIFIED` / `FOREIGN` / historical placement state leaking across mode changes, resets, reconnects and board epochs; redesign the global `has_memory`. Reuse item 7's `_reset_hysteresis()` reset semantics. No other Section 8 item touched; item 10 not touched.
- Branch/worktree: `main`; working tree clean at start (items 2 and 7 already on `main`).
- Files changed:
  - `python/rig/placement_ledger.py`:
    - New module sentinel `_CURRENT_EPOCH`.
    - `Placement` gains `board_epoch: int = 0` (defaulted so existing constructions still type-check; `append` always stamps the live epoch).
    - `PlacementLedger.__init__` gains `self._board_epoch = 0`; new `board_epoch` property and `new_board_epoch()` (advances the counter, returns it, KEEPS the rows).
    - New private `_resolve_epoch()` (sentinel → live epoch, `None` → every epoch, int → that epoch).
    - `append` now builds the `Placement` inside the lock so it can read `self._board_epoch`.
    - `has_memory` is no longer a `@property` — it is `has_memory(mode=None, board_epoch=_CURRENT_EPOCH) -> bool`, scoped by mode and epoch.
    - `placements`, `expected_occupancy`, `expected_top_level`, `is_top_of_column`, `has_taller_neighbour` all gain an optional `board_epoch` (default = live epoch) and thread it through.
    - Module + class docstrings updated for the mode/epoch scoping.
  - `python/rig/supervisor.py`:
    - `Supervisor.__init__`: new `self._identity: tuple[str|None,int]|None`, `self._board_epoch: int = 0` (kept `self._mode` for compatibility).
    - `note_mode(mode)` → `note_mode(mode, board_epoch=0)`: resets **both** histories via `_reset_hysteresis()` when the `(mode, board_epoch)` identity changes — a mode latch OR an epoch change, one primitive (item 7), no second mechanism.
    - `step()`: reads `epoch = int(getattr(ledger, "board_epoch", 0))`, passes it to `note_mode`, gates on `ledger.has_memory(mode, epoch)`, and scopes `expected_occupancy` / `expected_top_level` to `(mode, epoch)`. NO_MEMORY sentence unchanged (kept in sync with the hardcoded copy in `web/state.py`).
  - `python/web/app.py`: `_serial_ack` — a genuine `@0 BOOT` calls `supervisor.reset()` and, when `ledger.has_memory()` (something to supersede), `ledger.new_board_epoch()`. Guarded so the expected port-open BOOT during `connect()` (empty ledger) does not bump.
  - `docs/features/placement-supervision.md`: D3 section + ledger API/gate block updated for mode/epoch scoping.
  - `docs/features/block-vision-placement-supervision-audit-2026-09-08.md`: shortlist item 8 marked `[x]`.
- Implementation summary: the leak was a single global `has_memory` boolean read before `Supervisor.step` judged the *active* grid against a per-mode expected set. Horizontal-only placements → vertical mode "has memory" → `classify(expected=∅, …)` → VERIFIED on an empty view, FOREIGN on a real vertical board. A settled verdict also outlived a gantry reboot because nothing scoped the ledger to the physical board it described. Fix: stamp every placement with a `board_epoch`, answer every reader for `(mode, current_epoch)` by default, retain superseded rows only for the append-only record, and make the supervisor treat an epoch change identically to an R/RR latch — both drop the cell AND gap histories through item 7's `_reset_hysteresis()`. `new_board_epoch()` is wired to `@0 BOOT` in the app layer; the deeper reconnect/recovery wiring belongs to item 4's link/epoch boundary and is left for it.
- Tests added:
  - `python/tests/test_placement_ledger.py` (+15 checks): epoch 0 default; placements stamped with their epoch; `new_board_epoch()` return/advance; current epoch empty after a bump; old epoch's rows retained and explicitly addressable; every-epoch history view; post-bump placement stamped epoch 1; mode+epoch `has_memory` combinations; `is_top_of_column` / `has_taller_neighbour` scoped to the current epoch.
  - `python/tests/test_supervisor.py` (+13 checks, new `item 8` block): mode change with horizontal-only memory → NO_MEMORY on an empty view AND on a real vertical board (not FOREIGN); the placed mode still reaches VERIFIED; historical VERIFIED dropped across a new board epoch; historical FOREIGN not produced across a new epoch; reconnect — first new-epoch frame WARMS then the new epoch's own placement settles VERIFIED on its cell; `reset()` re-warms while same-epoch memory is preserved; a settled verdict is stable frame to frame within an unchanged mode/epoch; `board_epoch` stays 0 when nothing bumps it.
  - `python/tests/web_supervision_test.py` (+1 test): `test_a_gantry_reboot_starts_a_new_board_epoch` — an empty-ledger BOOT does not bump; a BOOT with memory advances the epoch, retains the pre-reboot row, and leaves the current epoch with no memory.
- Exact test commands and results:
  - `.venv/bin/python python/tests/test_supervisor.py` — 139 passed, 0 failed (was 126; +13).
  - `.venv/bin/python python/tests/test_placement_ledger.py` — 57 passed, 0 failed (was 42; +15).
  - `.venv/bin/python python/tests/test_supervisor_frames.py` — 21 passed, 0 failed.
  - `.venv/bin/python python/tests/test_grid.py` — 239 passed, 0 failed.
  - `.venv/bin/python -m pytest -q python/tests/` — 128 passed (item 2's `web_supervision_test.py` +1, `console_pipeline_test.py`, item 7's `test_supervisor.py` all green).
  - `.venv/bin/python -m pytest -q python/tests/web_supervision_test.py python/tests/console_pipeline_test.py python/tests/orchestrator_test.py` — 63 → 63 (+1 new test) passed.
  - `.venv/bin/python python/tests/test_placement_check.py` — 41; `test_placement_geometry.py` — 32; `test_build_controller.py` — 30; `test_latest_workers.py` — 25.
  - `cd web && npx vitest run src/` — 42 files, 563 passed (no frontend change; NO_MEMORY copy unchanged).
- Commit hash: `70f2e17` (`feat(supervision): scope placement memory by mode and board epoch`) — code + tests + docs + audit checkbox.
- Unresolved issues: none for item 8. The `@0 BOOT` hook is the only in-process epoch trigger wired today; a web reconnect/recovery route (`recover_after_reset`) does not exist yet and, per Phase 0, its link/epoch boundary is item 4's. `note_mode`'s `board_epoch` default of `0` is only for the single-arg legacy signature; `step` always passes the real epoch. Hardware/camera unverified locally as always.
- Whether merged: committed directly to `main`.
- Next action: begin item 4 — Pi-side exact compensated-motion reachability/clamp preflight.

## Phase 1 — item 7: gap-history reset and decay semantics

### Agent `item7_gap_history`

- Assigned item(s): Section 8 item 7 only — clear gap history through the same reset primitive as `_CellHistory`; hysterese gap-verdict clearing with a persistent per-gap identity; add the regression tests the audit calls for. No other Section 8 item touched; item 10 not touched.
- Branch/worktree: `main`; `/home/ahmedjk34/Desktop/Work_Dev/Miscellaneous/hardware-grad-project` (working tree clean at start; item 2 already on `main`, no other Phase 1 work in flight).
- Files changed:
  - `python/rig/supervisor.py`:
    - New `GAP_IDENTITY_MATCH_CM = 2.0` module constant (PROVISIONAL — flagged as wanting the same rig measurement as `PAIRING_BEYOND_CM`, per audit §5.2).
    - New `_GapTrack` dataclass (`anchor: tuple[float,float] | None`, `readings: deque`) and `_GapHistory` class: per-identity last-M readings, greedy nearest-anchor association within the match radius, EMA anchor drift (`0.6·old + 0.4·new`), anonymous positional slots for frames that carry a bare `in_gap` count with no `gap_points_cm`, `_state()` N-of-M (mirrors `_CellHistory.settled`), decay that forgets a track once N of its last M readings are absent, and `settled_gap_count()`.
    - `Supervisor.__init__`: `self._gap_history` is now a `_GapHistory(settle_n, settle_m)` instead of `deque[bool]`; comment rewritten.
    - New `Supervisor._reset_hysteresis()` clears `_history` **and** `_gap_history`. Public `reset()` now delegates to it. `note_mode()` (mode latch), the interlock-refusal branch and the no-memory branch of `step()` all call `_reset_hysteresis()` where they previously called `self._history.reset()` alone.
    - `step()`: `self._gap_history.update(observation)` replaces `.append(observation.in_gap > 0)`; `classify(..., in_gap=self._gap_history.settled_gap_count())` replaces the `gap_settled`/`observation.in_gap` expression, so the classifier now sees the count of distinct settled gap identities, never the raw per-frame count.
  - `python/tests/test_supervisor.py`: +15 checks in a new `item 7` block (helpers `gap_frame`, `run`; constants `GAP_A`, `GAP_B`, `clean2`) — see "Tests added".
  - `docs/features/block-vision-placement-supervision-audit-2026-09-08.md`: Section 8 item 7 marked `[x]`.
- Implementation summary: `_gap_history` was one global `deque[bool]` with two defects. (1) Asymmetric/leaky clearing: the settled verdict was rendered from the current frame's `in_gap` count gated by a global N-of-M, so one gap-free frame cleared a settled DISPLACED/FOREIGN, and three "a gap exists" votes from three different objects settled as one gap. `_GapHistory` gives every distinct gap a spatial identity and requires N-of-M for both assertion and clearing; a gap whose position jumps past `GAP_IDENTITY_MATCH_CM` is a new identity that warms from nothing while the old one decays over N frames and is forgotten. (2) Asymmetric reset: `note_mode` and the interlock/no-memory branches reset `_CellHistory` only. `_reset_hysteresis()` is now the single primitive every reset cause goes through, so a stale gap verdict cannot outlive the cell evidence beside it. Item 2's `NO_VISION` path in `web/app.py` calls `supervisor.reset()`, which now also clears the gap history — no change there, re-verified.
- Tests added (all in `python/tests/test_supervisor.py`):
  - repeated same gap settles FOREIGN once and stays FOREIGN with no flicker;
  - one gap-free frame does NOT clear a settled gap; N gap-free frames decay it back to VERIFIED (timeout/decay);
  - a fresh gap identity warms from nothing, not from the decayed gap's votes, then settles on its own N-of-M;
  - a gap that jumps a whole pitch starts a new identity (`len(_tracks) == 2`, old one decaying);
  - two distinct persistent gaps settle as a count of 2 (`settled_gap_count() == 2`);
  - interlock trip: post-trip the board reads VERIFIED with no gap, one gap frame after the trip is not FOREIGN, and a full fresh N-of-M is required to re-reach FOREIGN — the leaked-gap-vote regression (the older interlock-reset check only looked at the first warming frame, kept unchanged);
  - `reset()` drops the settled gap verdict — the next frame re-warms;
  - a mode latch clears the gap history — horizontal is not FOREIGN off vertical's gap.
- Exact test commands and results:
  - `.venv/bin/python python/tests/test_supervisor.py` — 126 passed, 0 failed (was 111; +15).
  - `.venv/bin/python python/tests/test_supervisor_frames.py` — 21 passed, 0 failed.
  - `.venv/bin/python python/tests/test_grid.py` — 239 passed, 0 failed.
  - `.venv/bin/python -m pytest -q python/tests/` — 127 passed.
  - `.venv/bin/python -m pytest -q python/tests/web_supervision_test.py python/tests/console_pipeline_test.py python/tests/orchestrator_test.py` — 63 passed (item 2's `web_supervision_test.py` + `console_pipeline_test.py` intact).
  - `.venv/bin/python python/tests/test_placement_check.py` — 41 passed; `test_placement_geometry.py` — 32; `test_placement_ledger.py` — 42; `test_latest_workers.py` — 25; `test_build_controller.py` — 30.
  - `cd web && npx vitest run src/` — 42 files, 563 passed.
- Commit hash: `074aaf9` (`feat(supervision): per-identity gap history, symmetric reset and decay`) — code + tests + audit checkbox.
- Unresolved issues: none for item 7. `GAP_IDENTITY_MATCH_CM = 2.0` is PROVISIONAL and wants a rig measurement (audit §5.2) — same status as `PAIRING_BEYOND_CM`. The `_CellHistory` interest-set asymmetry noted in audit line 74 first clause (an unexpected cell leaving the interest set on a single-frame dropout) is a separate `_CellHistory` concern and was left untouched — the resume note and shortlist item 7 both scope this task to the gap history; flag for the team if they want it folded in. Hardware/camera unverified locally as always.
- Whether merged: committed directly to `main`.
- Next action: begin item 8 — mode- and board-epoch-specific `has_memory`.

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
- Commit hash: `908a5dc` (code + tests + docs for item 2). This one-line hash correction is the immediately following commit.
- Unresolved issues: none for item 2. Hardware motion remains unverified locally (no Arduino toolchain, no camera). `NO_VISION` is deliberately not a state-coloured fault — an operator sees it as a dim strip like BUSY, distinguished only by wording; if the team wants the camera-pipeline failure to be louder, that is a follow-up UI decision, not a safety gap. Items 7, 8, 4 remain open in that order.
- Whether merged: committed directly to `main` (no divergent Phase 1 branch to merge against).
- Next action: begin item 7 — unify `_gap_history` clearing with `_CellHistory` reset and add persistent per-gap identity / symmetric N-of-M clearing, with the leaked-gap-vote regression test.

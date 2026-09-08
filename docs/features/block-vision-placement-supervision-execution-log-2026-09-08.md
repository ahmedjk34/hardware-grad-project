# Block-vision placement-supervision execution log

Date: 2026-09-08

## CURRENT RESUME STATE

- Completed and verified: Section 8 item 1 (pre-existing); Section 8 item 2 (`NO_VISION` propagation for detector failure and stale frames — implemented, tested, committed on `main`); Section 8 item 7 (per-identity gap history, symmetric reset/decay — implemented, tested, committed `074aaf9` on `main`); Section 8 item 8 (mode- and board-epoch-specific ledger memory — implemented, tested, committed `70f2e17` on `main`); Section 8 item 4 (Pi-side exact compensated-motion reachability/clamp preflight — implemented, tested, committed `a22e92d` on `main`); Section 8 items 6 + 9 (preserve detection multiplicity + require one stable block-consistent track for MOVED/DISPLACED; fuse centroid/angle/size over the existing coherent quiet window with exposed uncertainty/residuals — implemented, tested, committed on `main`).
- Implemented but unmerged: none.
- Active or blocked work: Phase 1's serialized 2 → 7 → 8 → 4 → (6 + 9) chain is complete. Next in the audited safe sequence is item 3, then item 5.
- Unmerged branches/worktrees: none.
- Next required action: start **item 3** — make correction a one-shot coherent ticket with atomic quiet/mode/map/track revalidation (audit §1 P0 `routes_command.py` `/correct`, §6.4). It builds directly on items 6 + 9: `Supervisor.track_evidence_at` now yields a track signature/uncertainty the ticket can bind and re-check, and `assess_frame_correction` already re-derives everything server-side with `require_track=True`. Items 5 (diagonal/both-neighbour clearance) and 10 (the rig measurement campaign) remain after it / out of scope.

## Phase 1 — items 6 + 9: multiplicity-preserving coherent track; quiet-window centroid/angle/size fusion

### Agent `items6_9_coherent_track`

- Assigned item(s): Section 8 items 6 and 9 ONLY, implemented together because they share one vision/tracking pipeline. Item 6: preserve detection multiplicity and require ONE stable, block-consistent track for `MOVED` / `DISPLACED` — no merged blobs, no candidate switching, no arbitrary first-candidate selection, no unstable/ambiguous track producing a movement verdict's correction. Item 9: fuse centroid, angle and size across the EXISTING coherent quiet window; expose meaningful uncertainty and residuals; no separate second frame pipeline or unrelated temporal mechanism. No other Section 8 item touched (item 3's coherent ticket, item 5's diagonal gate, item 10's rig campaign all left alone).
- Branch/worktree: `main`; working tree clean at start (items 2, 7, 8, 4 already on `main`).
- Files changed:
  - `python/rig/supervisor.py`:
    - New frozen `DetectionRecord` (`placement`, `cell`, `centre_cm`, `angle_deg`, `size_cm`) — one entry per detection, in detector order, kept WHOLE. `Observation` gains `detections_detail: tuple[DetectionRecord, ...] = ()`; `observe()` now records EVERY detection there (projecting `point_cm` once per detection) before the existing per-cell collapse, so two detections on one cell (merged blob / duplicate hypothesis / decomposed compound) are visible instead of silently first-wins.
    - New module constants (all PROVISIONAL, flagged for the same rig localisation-repeatability run as `PAIRING_BEYOND_CM` / `SIZE_TOLERANCE_CM`, audit §7.5): `TRACK_IDENTITY_MATCH_CM = 1.2` (tighter than `GAP_IDENTITY_MATCH_CM = 2.0` on purpose — a track must separate a displaced block from its adjacent neighbour cell, only half a pitch away), `SWITCH_NEIGHBOUR_CM = 3.0`, `TRACK_CENTRE_SIGMA_MAX_CM = 0.6`, `TRACK_ANGLE_SIGMA_MAX_DEG = 4.0`, `TRACK_SIZE_SIGMA_MAX_CM = 0.8`.
    - New helpers: `_median`, `_dispersion` (population std, 0 for <2 samples), `_circular_mean_deg` / `_circular_std_deg` (period-180 circular statistics — `179`/`1`/`-179` average near `0`, `88`/`-88` near `±90`; wraparound never inflates the scatter).
    - New `_TrackFrame` / `_Track` / frozen `TrackEvidence` and the `_TrackHistory` class — `_CellHistory` / `_GapHistory` for the CORRECTION pick target. Same N-of-M window, cleared through the same `_reset_hysteresis()` primitive. `update(observation)` associates every block-shaped detection (cell or gap) frame to frame by cm anchor (greedy nearest 1:1, EMA anchor drift `0.6·old + 0.4·new`), records per-frame multiplicity (records within the match radius of a track), opens a merged/duplicate pair as ONE track already flagged multiplicity 2, and decays a track once N of its last M frames say it is gone. `evidence_at(point_cm)` finds the nearest track, fuses the present frames (median centre, circular-mean angle, median size), and gates: `settled` (≥ N present), `consistent` (multiplicity ≤ 1 AND not an anti-phase candidate switch — `_looks_like_switch` tells a switch from an occupied neighbour by anti-correlated presence, not distance), `stable` (radial centre / angle / size dispersion each under its ceiling). `ok = settled and consistent and stable`; the `reason` is the affirmative sentence or every failing gate joined with `; `.
    - `Supervisor`: new `self._track_history`; `_reset_hysteresis()` clears it alongside the other two; `step()` calls `self._track_history.update(observation)` next to `_gap_history.update()` (same observation, same window, before the warming check); new read-only public `track_evidence_at(point_cm)`.
  - `python/rig/placement_check.py`:
    - `Correction` gains advisory `localization_sigma_cm` / `localization_residual_cm` / `track_samples` / `angle_sigma_deg` (defaulted None; `command_args` unchanged — the `P` verb does not read them).
    - `assess()` gains matching keyword args, threaded onto BOTH the MOVED and the DISPLACED `Correction`. The MOVED branch now also runs the same `consistency()` size/shape gate DISPLACED already had (audit item 6: "apply measured size/shape gates to MOVED as well as DISPLACED") — a merged blob squarely on the wrong cell is refused.
  - `python/web/state.py`:
    - New `correction_query_point(observation, verdict)` — the single-frame cm point the block sits at (gap detection for DISPLACED, wrong-cell detection for MOVED), the exact anchor both `web/app.py` and `/api/supervision/correct` use to look the fused track up so the two never drift.
    - `assess_frame_correction()` gains `track=None, require_track=False`. With `require_track` and a missing/`not ok` track it returns `(None, reason)` — item 6's hard gate. With an `ok` track it REPLACES the single-frame `observed_cm` / `angle_deg` / `measured_size_cm` with the fused robust values (item 9) before `_drift_neighbour` and `_assess`, and threads the uncertainty onto the `Correction`.
    - `SupervisionState` + `SupervisionModel` + `supervision_model()` gain `localization_sigma_cm` / `localization_residual_cm` / `track_samples` (advisory; no state colour; None for every non-MOVED/DISPLACED case).
  - `python/web/app.py`: `_supervise` derives `query_point` + `track = supervisor.track_evidence_at(...)` right after `supervisor.step()`, passes it to `_assess_correction(..., track)` (which now calls `assess_frame_correction(..., track=track, require_track=True)`) and to `_note_supervision(..., track)`, which publishes the fused uncertainty onto `SupervisionState`.
  - `python/web/routes_command.py`: `/api/supervision/correct` re-queries the SAME `app.state.supervisor` track (`correction_query_point` + `track_evidence_at`) and calls `assess_frame_correction(..., track=track, require_track=True)` — a byte is sent only if the block is still one stable, unambiguous, block-consistent track. Deduplicated the later `supervisor = getattr(...)` now that it is resolved earlier.
  - `docs/features/block-vision-placement-supervision-audit-2026-09-08.md`: shortlist items 6 and 9 marked `[x]`.
- Implementation summary: `observe()` collapsed detections to a set and stored only the first per cell, and `assess_frame_correction` / `web/state.py` then picked that first candidate for the pick coordinate from ONE frame — so a merged blob, a duplicate hypothesis, a candidate switch or an unstable track all read as a clean single-block pick. Fix: `detections_detail` preserves multiplicity out of `observe()`; `_TrackHistory` — a sibling of item 7's `_GapHistory`, fed from the same `observation` on the same N-of-M window in the same `step()`, cleared by the same primitive, NOT a second analysis path — associates every block-shaped detection frame to frame and fuses the matched run into a robust centre / circular-mean angle / median size with a per-axis and radial dispersion and a worst per-frame residual. `assess_frame_correction` with `require_track=True` (both the live `_supervise` path and the `/correct` re-check) refuses a MOVED/DISPLACED correction unless exactly one such track is settled, unambiguous (multiplicity ≤ 1 and not an anti-phase candidate switch) and low-dispersion, and uses the fused centre/angle/size in place of the single-frame values. The uncertainty and residual reach `SupervisionModel` for the operator and the log. Firmware untouched; no `config/rig.json` change; no new paired constant (`motion_preflight.py`'s mirror is the only one and is not touched).
- Tests added:
  - `python/tests/test_supervisor.py` (+28 checks, new `item 6 + 9` block): `observe()` keeps every detection in `detections_detail` while `cells` still collapses; a stable single-block track over the window is `ok` with fused centre = tracked centre, sigma ~0, residual ~0, multiplicity 1; a lightly-noisy centroid still fuses and reports a non-zero worst-frame residual; a centroid scattering past `TRACK_CENTRE_SIGMA_MAX_CM` is refused ("scattered"); two detections on one spot every frame → merged blob, refused (multiplicity ≥ 2); a detection alternating between two spots → candidate switch, refused; a second block present at the SAME time (a neighbour) is NOT flagged as a switch; circular mean folds `179`/`1`/`-179` to ~0 and `88`/`-88` to ~±90, circular std small for tight angles and large for a 40° spread; angle wraparound near ±180 is not read as huge scatter; an angle scattering past the ceiling is refused; small footprint variation still fuses, a >0.8 cm footprint jump is refused; 3 of 5 frames present (2 missing) still settles; a track seen in only 2 frames is not settled ("are needed"); `evidence_at` a point with no track nearby is refused ("not consistent frame to frame"); decay after 3 empty frames and a reappearance warms from nothing (1 sample); `step()` feeds the track history from the same observation; `Supervisor.reset()`, a mode latch and a tripped interlock each clear the track history; `TRACK_IDENTITY_MATCH_CM == 1.2`.
  - `python/tests/web_supervision_test.py` (+3 tests, and `_correct_app` now seeds the track history so the route tests exercise the real re-query): a clean DISPLACED track publishes its fused uncertainty (`track_samples == (1,1)`, sigma/residual `0.0`) on `SupervisionState` and `SupervisionModel`; a merged blob (duplicate detection) on the MOVED 'to' cell keeps the set-level `MOVED` verdict but makes `correction` `None` / `correctable` `False` with "merged blob"; the `/correct` route refuses (409, no `P` sent) when the supervisor's track history has nothing established for the block.
- Exact test commands and results:
  - `.venv/bin/python python/tests/test_supervisor.py` — 167 passed, 0 failed (was 139; +28).
  - `.venv/bin/python -m pytest -q python/tests/web_supervision_test.py` — 52 passed (was 49; +3).
  - `.venv/bin/python -m pytest -q python/tests/` — 131 passed (was 128; +3).
  - `.venv/bin/python python/tests/test_supervisor_frames.py` — 21; `test_placement_check.py` — 41; `test_placement_geometry.py` — 32; `test_placement_ledger.py` — 57; `test_motion_preflight.py` — 62; `test_grid.py` — 239; `test_link.py` — 113; `test_build_controller.py` — 30; `test_latest_workers.py` — 25. All 0 failed.
  - `cd web && npx vitest run` — 42 files, 563 passed (no `web/src` change; the new `SupervisionModel` fields are optional JSON the client ignores).
- Commit hash: `f0c8c37` (`feat(supervision): coherent quiet-window track for MOVED/DISPLACED corrections`) — code + tests + `types.ts` + `placement-supervision.md` + audit checkboxes. This log entry is the immediately following docs commit.
- Unresolved issues: none for items 6 + 9. All five `TRACK_*` constants are PROVISIONAL and want the rig localisation-repeatability run (audit §7.5). `_looks_like_switch` distinguishes a candidate switch from an occupied neighbour by anti-phase presence over the window, not by distance — correct on the traces reasoned through here but unverified on a real alternating detector output. Hardware/camera unverified locally as always. Item 3 (coherent one-shot ticket) is the next action and now has `track_evidence_at` to bind a track signature against.
- Whether merged: committed directly to `main`.
- Next action: begin item 3 — one-shot coherent correction ticket with atomic quiet/mode/map/track revalidation.

## Phase 1 — item 4: Pi-side exact compensated-motion reachability/clamp preflight

### Agent `item4_motion_preflight`

- Assigned item(s): Section 8 item 4 only — an exact Python full-motion reachability and clamp preflight for every compensated CORRECTION (`P`) target: cell centre − tool offset, then `BUILD_PLACEMENT_OFFSET_*` + `SKEW_*` + the requested `(dx,dy)` nudge, on both the pick and the place leg, per active mode and the paired calibration values, with any predicted firmware clamp a hard refusal. Match the real motion semantics, not an approximate model. No other Section 8 item touched; item 10 not touched.
- Branch/worktree: `main`; working tree clean at start (items 2, 7, 8 already on `main`).
- Files changed:
  - `python/rig/motion_preflight.py` (**new**): a line-for-line mirror of `gotoBuildTargetOffset()` in `build_test_v1.ino`.
    - Firmware-only constants copied in as read-only module state, because the arithmetic needs them and they must not enter `rig.json` (AGENTS.md "What must NOT be copied"): `X_TRAVEL_STEPS = 4550`, `Y_TRAVEL_STEPS = 7600` (`SOFT_LIMIT_*_TRAVEL`); the per-mode `SKEW_{X,Y}_PER_{COL,ROW,COLROW}_CM` and `BUILD_PLACEMENT_OFFSET_{X,Y}_CM` tables, keyed by mode name so a `{vertical, horizontal}` swap cannot pass.
    - `_lround()` — C `lround` (round half AWAY from zero), not Python's round-half-to-even, so the preflight agrees with the firmware at exact half-steps.
    - `steps_per_cm(axis, grid)` — DERIVED as `cap / grid.workspace_{width,height}_cm` (the paired `X_TRAVEL_CM` partner), never hard-coded, exactly like `xyStepsPerCmOf()`.
    - `_axis_leg()` runs both firmware stages per axis per leg: (1) `cellTargetPosition()` — the UNCOMPENSATED holder target, float bounds with `slack = 1e-4` then the `[0, cap]` step check; (2) the magnitude-space correction (three separately-`lround`'d terms — placement offset, skew polynomial in `col` AND `row`, `lround(extra*spc)`) added to the magnitude, then `clamp(0, cap)`. `clamped` is `True` exactly when the firmware's clamp would bite. All in magnitude space — no signed `axisPos[]`, no travel-direction multiply — so `+dx` is away from home on both axes.
    - `preflight_correction(*, grid, mode, pick_cell, place_cell, dx_cm, dy_cm, tool_offset_cm=(0.0, 0.0)) -> MotionPreflight` — pick leg carries the nudge, place leg carries `0, 0`, mirroring `replaceBlock()`'s `gotoBuildTargetOffset(pcol,prow,rot,dx,dy)` then `gotoBuildTarget(qcol,qrow,rot)`. `MotionPreflight.ok` / `.reason` / `.legs` / `.clamped_legs`.
    - `tool_offset_for_mode(cfg, mode)` — resolves `tool_offsets.{neutral,cw}` for the mode's build rotation from a loaded config dict (reads, does not load).
  - `python/rig/placement_check.py`: `assess()` gains `tool_offset_cm=(0.0, 0.0)`; new private `_preflight_reject()` runs `preflight_correction` over the just-built `Correction` and returns `(None, reason)` on a predicted clamp, called in BOTH the MOVED and the DISPLACED branch immediately before the affirmative return. Skipped when `grid is None` (the map-less path is already rejected upstream for lacking a cm position). Vertical's `neutral` tool offset is a genuine `(0.0, 0.0)`, so the default is exact for the only `SUPPORTED_MODES` entry; docstring notes a future horizontal path must pass `tool_offsets.cw`.
  - `python/rig/link.py`: `Rig.replace_block()` gains a defence-in-depth guard after the 3 cm nudge check — runs `preflight_correction` with `self.grid`, `self.grid.mode`, and the real `tool_offset_for_mode(self._cfg, mode)` (mode-agnostic, so it is exact for horizontal too), and raises `ValueError("correction refused before motion: …")` sending nothing, the same fail-closed contract as the feeder/belt/level guards beside it.
  - `AGENTS.md`: new paragraph in "What must NOT be copied into `config/rig.json`" documenting `motion_preflight.py` as the one deliberate firmware-constant mirror, pinned against the sketch by `test_motion_preflight.py`, to be changed in the same commit as the sketch.
  - `docs/features/block-vision-placement-supervision-audit-2026-09-08.md`: shortlist item 4 marked `[x]`.
- Implementation summary: the firmware's `cellTargetPosition()` validates only the uncompensated holder target; `BUILD_PLACEMENT_OFFSET_*`, `SKEW_*` and the `P` nudge are added afterwards inside `gotoBuildTargetOffset()`, where an off-travel target is clamped onto the cap, a console warning is printed, and the claw is driven anyway — so a far-edge correction descends somewhere other than the block's centre and nothing on the Pi predicts it. `motion_preflight.py` reproduces that exact magnitude-space arithmetic (same `lround`, same three-term correction, same clamp condition) for both legs; a predicted clamp — or an uncompensated target already off travel via the tool offset — is a hard refusal. Wired at the policy layer (`assess()`, the single source of truth `/api/supervision/correct` re-runs before dispatch) and independently at the motion layer (`replace_block()`, the "before a byte is sent" point that calibration/commissioning paths also call). Firmware untouched — the mirror carries the constants and `test_motion_preflight.py` fails on any drift from `build_test_v1.ino`.
- Tests added:
  - `python/tests/test_motion_preflight.py` (**new**, 62 checks, hand-rolled like `test_placement_check.py`; not pytest-collected — `pytest.ini` restricts collection to `*_test.py`):
    - `_lround` matches C round-half-away-from-zero (incl. the `82.5 -> 83` case where Python's `round` gives 82).
    - Firmware-mirror drift guard: parses `build_test_v1.ino` and asserts `X_TRAVEL_STEPS` / `Y_TRAVEL_STEPS` == `SOFT_LIMIT_*_TRAVEL`, every `SKEW_*` and `BUILD_PLACEMENT_OFFSET_*` table == the sketch (both modes), the mode keys are exactly `{vertical, horizontal}`, and `steps_per_cm` is derived not hard-coded.
    - A mid-grid correction is reachable, reports no clamped legs, preflights all four axis-legs; the per-leg magnitude / correction / `wanted_from_home` arithmetic is re-derived by hand (pick X one nudge term, pick Y skew(col)+nudge, place legs skew-only, place X correction exactly zero → firmware `continue`).
    - Just-inside vs just-outside the far X cap at ±1 step of compensation; a compensated target landing EXACTLY on the cap is not clamped (`> maximum`, not `>=`).
    - Compensation-induced failure with `dx=dy=0`: vertical `[6,5]` skew alone (`0.115*6 = 0.69 cm`) clamps the pick Y leg; reason carries the ~0.69 cm miss distance.
    - Both legs checked: a clamp on the PLACE leg (`place_cell=[6,5]`) fails the preflight with the pick legs clean.
    - `cellTargetPosition` stage: a negative X tool offset puts the holder past 22.8 cm → refused before any nudge (`target_mag is None`); a positive X tool offset at col 0 puts it before the home switch → refused.
    - X-axis sign convention: around a mid cell `+dx` / `−dx` move `wanted_from_home` symmetrically (no travel-direction factor); `+dx` past the far cap clamps to the cap, `−dx` below home clamps to 0 (a sign-inverted model would clamp the wrong end), and the raw wanted magnitude is genuinely negative at the home end.
    - Both modes through the full stack: horizontal folds in the `cw` tool offset and the `−0.4 cm` `BUILD_PLACEMENT_OFFSET_X`; horizontal's reachable clamp is at the home end (its grid only reaches X = 17.1 cm), exercised at col 0.
    - Integration through `assess()`: an in-band reachable DISPLACED still returns a `Correction`; a DISPLACED whose compensated pick would clamp (`[6,2]` on the X cap, +0.7 cm) is refused with "clamp" / "pick X" in the reason; the MOVED path is guarded the same way; `grid=None` still returns a `Correction` (preflight skipped).
- Exact test commands and results:
  - `.venv/bin/python python/tests/test_motion_preflight.py` — 62 passed, 0 failed (new).
  - `.venv/bin/python python/tests/test_placement_check.py` — 41 passed, 0 failed.
  - `.venv/bin/python python/tests/test_placement_geometry.py` — 32 passed, 0 failed.
  - `.venv/bin/python python/tests/test_link.py` — 113 passed, 0 failed (the `replace_block` guard added; nominal `P 3 1 0 -0.420 0.110 2 1 0` still preflights clean).
  - `.venv/bin/python python/tests/test_supervisor.py` — 139 passed, 0 failed (item 7/8 intact).
  - `.venv/bin/python python/tests/test_supervisor_frames.py` — 21 passed, 0 failed.
  - `.venv/bin/python python/tests/test_placement_ledger.py` — 57 passed, 0 failed (item 8 intact).
  - `.venv/bin/python python/tests/test_grid.py` — 239 passed, 0 failed (firmware pairing unchanged).
  - `.venv/bin/python python/tests/test_build_controller.py` — 30; `test_latest_workers.py` — 25.
  - `.venv/bin/python -m pytest -q python/tests/` — 128 passed (item 2's `web_supervision_test.py`, `console_pipeline_test.py`, `orchestrator_test.py` all green).
  - No `web/src` change, so `npx vitest` not re-run.
- Commit hash: `a22e92d` (`feat(supervision): Pi-side exact compensated-motion clamp preflight`) — code + tests + `AGENTS.md` + audit checkbox. This log entry is the immediately following docs commit.
- Unresolved issues: none for item 4. The firmware `P` verb itself remains **unflashed and unverified on hardware** (no local Arduino toolchain) — the preflight mirrors the sketch's arithmetic, which `arduino/tools/pcheck` only syntax-checks. The 3 cm `P` envelope escaping as an HTTP 500 (audit §1, `placement_check.py:256-291`) is a **separate** shortlist row, not folded in here. `test_motion_preflight.py` is the drift guard between the mirror and `build_test_v1.ino`; if the sketch's caps or compensation tables ever change, that test fails until the mirror is updated in the same commit.
- Whether merged: committed directly to `main`.
- Next action: begin items 6+9 — coherent quiet-window pick-point fusion with exposed uncertainty (§6.2) and unique-result throughput/backpressure telemetry (§7.3).

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

# Block-vision and placement-supervision audit

Date: 2026-09-08  
Scope: Raspberry Pi vision, supervision, placement memory, and correction authorization  
Status: audit and design report only; no production code or calibration value was changed

## 0. Scope, evidence, and capture review

### Executive summary

The stack has a sound high-level separation: shape hypotheses, lattice alignment, workspace calibration, and placement supervision are distinct; the controller prevents most correction actions unless the verdict is explicitly correctable; horizontal correction is refused; and the correction sign is presently consistent with the repository's magnitude-from-home convention. The current detector also handles the two reference boards well: in this environment it found 29 on-lattice blocks on each reference board and rejected the home-corner holder offcut.

The most important weakness is not detector recall. It is evidence coherence. `ConsolePipeline` can publish detections computed from an older image as if they belong to the newest `ProcessedFrame`, while the supervisor takes motion/quietness from that newest image. The correction endpoint then authorizes motion from an older settled verdict without atomically rechecking a coherent, quiet, mode-current observation. Together, these can turn individually reasonable components into an unsafe correction decision.

Four other issues should block correction commissioning until resolved:

1. A diagonal displacement is reduced to one dominant axis and only one neighbour corridor is checked.
2. An outward correction at a grid edge can be clamped by the firmware and then continue to descend at the wrong point; the Pi does not preflight the complete compensated target.
3. MOVED correction does not enforce one valid block hypothesis at each relevant site and omits the same size/shape consistency used for DISPLACED.
4. A correction judged geometrically possible can exceed the serial `P` command's 3 cm envelope and currently escape as an HTTP 500 rather than being refused by the assessor.

The correction mathematics itself has no discovered X-sign inversion or skew double-count. `correction_offset()` returns an observed-minus-nominal displacement in the workspace magnitude frame; a positive component means farther from the corresponding home switch. Standard build skew and the mode's fixed build offset are applied on the placement leg, not added twice to the pickup residual. Accuracy is nevertheless limited by a single-frame centroid, residual four-corner-map error, lack of a localization uncertainty, and unmodelled parallax above level 0.

### Material reviewed

I read the repository authority and calibration rules in `AGENTS.md`, `CLAUDE.md`, all of `docs/BLOCK-VISION.md`, CAMERA §5a, and all requested feature/design documents. I read the requested detector, outline, levels, evidence, worker, supervisor, geometry, correction-policy, ledger, controller, orchestrator, and web state/event/route sources; for `block_grid.py` I followed the requested fit, curvature, and frame-difference paths plus their callers. I also read the named tests and traced the live `ConsolePipeline` path that joins capture, asynchronous analysis, `ProcessedFrame`, and supervision.

The current implementation and historical design documents do not always describe the same revision. In particular, some supervision prose still says `idle` only and a 0.02 quiet threshold, whereas the current pipeline admits `idle` and `complete` and uses 0.01. The correction documents also retain older provisional bands lower in the files. Code and the latest progress record were treated as implementation evidence; stale documentation is called out below rather than silently reconciled.

### Capture observations

| Capture | What it shows |
|---|---|
| `WITHOUT_BLOCK_DETECTOR_ON_EXAMPLE.png` | Ten loose wooden blocks on a strongly pink/magenta, partly overexposed surface. Rails, wiring, a phone, and hard shadows make this a useful non-lattice clutter scene. |
| `WITH_BLOCK_DETECTOR_ON_EXAMPLE.png` | Green outlines and centres visually cover all ten loose blocks. The result demonstrates useful layer-1 recall despite colour cast and uneven exposure. |
| `with_block_detector_on_FAULTY.png` | The black boxes correspond to the ten scattered blocks, but the green output is a full regular 7×6 virtual lattice extending over empty table. The failure was not merely a shifted box: a calibration/lattice path extrapolated a complete grid from loose, non-grid detections and destroyed the correspondence between observed blocks and reported cells. The current `detect_block_lattice` fails closed on this image with “no consistent x spacing”; this is therefore an important historical regression case that is now guarded, not evidence that the current path still produces the pictured lattice. |
| `BLOCK_CALIBRATION_DETECTED.png` | Twenty-nine physical blocks are outlined; thirteen farther cells are extrapolated in red. The cyan workspace boundary and magenta feeder cell make the physical-versus-virtual distinction visible. |
| `IMAGE_TO_TEST_BLOCK_CALIBRATION.png` | Reference board with 29 blocks. Two wood-coloured holder offcuts meet near the home corner and are plausible shape/colour distractors. Dense inter-block shadows reduce colour separability. |
| `20260903-122957_corrected_...lens168...png` | Second reference rendering of the same board. Perspective and residual non-linear lens error remain small but visible; the holder offcuts remain the key false-positive challenge. |
| `20260903-122957_raw.png` | Severe wide-angle barrel distortion, curved rails, a large peripheral bench region, clutter, and a person. The corrected crop materially straightens and isolates the board, but a four-corner map cannot remove all local curvature or perspective variation. |
| `20260905-123235_corrected_...png` | Multi-level scene with visible side faces, directional parallax, shadows that bridge neighbouring top faces, and partial top-face occlusion. It is suitable for testing hypotheses about height, not yet for asserting absolute level accuracy. |
| `camera_live.png` | A coloured printed calibration sheet under purple cast and surface overexposure, plus an off-axis wooden object. Colour alone is plainly not a stable semantic discriminator. |
| `physical_grid_digital_image.jpeg` | Clean digital source art, unlike the photographed print. Its regularity should not be mistaken for the geometry or photometry of the live corrected camera view. |

Current-environment spot measurements, using the unchanged production functions, were:

| Image | Layer-1 raw | Aligned result | Levels path |
|---|---:|---:|---:|
| Loose-block example | 10 in 43 ms | 10 on-lattice / 0 rejected in 34 ms | 10 reports, 4 measured, 617 ms |
| Reference board 1 | 30 in 35 ms | 29 on-lattice / 1 rejected in 47 ms | 28 reports, 20 measured, 447 ms |
| Reference board 2 | 33 in 27 ms | 29 on-lattice / 1 rejected from the 30 aligned candidates in 40 ms | 28 reports, 333 ms |
| Multi-level capture | 10 in 48 ms | 10 on-lattice in 54 ms | 13 top hypotheses, 6 covered, 12 measured, 378 ms |

These are one-run development-machine measurements, not Raspberry Pi 5 acceptance numbers. They are useful for finding redundant work, not for changing thresholds or resolution. The repository's measured Gate 0 evidence remains the authority: 0.01 quiet fraction, N=3 of M=5, approximately 8.6–8.7 Hz, five physical blocks, and 1,398 trace frames. Any retune still requires a new rig run.

The relevant non-web unit scripts passed locally: supervisor (111 checks), placement geometry (32), placement check (41), ledger (42), detector, outline, block-grid, block-levels, supervisor-frame traces (21), build controller, and orchestrator. The trace set still exposes a limitation: the hand trace reports BUSY on 91.4% of frames but reaches VERIFIED on 9 frames, consistent with a stopped hand eventually appearing quiet. `test_camera_performance.py` has one stale fixture expectation at lines 79–82: it expects six detections in the first corrected capture, which now contains three. Twenty-four other checks passed. The web integration suite did not complete in this environment: it consistently stopped making progress at an executor-backed supervision case after four tests, so this report does not claim a full web-suite pass; the cause should be reproduced on the target Pi before commissioning.

Severity meanings used below: **P0** can authorize or execute unsafe/wrong motion or falsify the evidence used for it; **P1** can produce an operationally misleading verdict or defeat intended supervision; **P2** is a robustness, performance, latent, test, or documentation problem that is not presently an immediate motion hazard.

## 1. Correctness bugs

| Severity | File:line | What is wrong | Failure scenario | Required fix | Test to add |
|---|---|---|---|---|---|
| P0 | `python/rig/console_pipeline.py:277-299`; `python/vision/analysis_worker.py:10-33` | Analysis currency checks only `map_generation`; `source_sequence` is not required to match the published frame. Older detections are attached to the newest sequence and view. | A slow detector repeats an old occupied result over several new frames, or pairs an old empty result with a new quiet image. Occupancy hysteresis advances on fabricated “new” evidence and quietness is measured on a different scene. | Make frame provenance first-class: source sequence, map generation, analysis error, and age. Step supervision only once per unique completed analysis result and bind it to the exact immutable source view, using a small bounded frame/result handoff rather than another capture. | Delay the analysis worker across several capture frames; prove no repeated source sequence advances N-of-M and that the quiet baseline and detections have identical source IDs. |
| P0 | `python/vision/analysis_worker.py:151-170`; `python/rig/console_pipeline.py:282-299` | Detector exceptions become an empty tuple; error state is not propagated into `ProcessedFrame` or verdict policy. | A temporary detector failure is interpreted as an empty board for enough frames and becomes REMOVED. | Publish `analysis_ok/error` and treat missing/failed/stale analysis as NO_VISION/INSUFFICIENT, never as zero detections. | Inject detector exceptions for M frames with a non-empty ledger; assert no REMOVED or correctable verdict. |
| P0 | `python/web/routes_command.py:337-384`; `python/web/app.py:211-255` | `/correct` rechecks camera freshness and recomputes geometry, but does not atomically require a current quiet, settled, mode/map-coherent observation. It can act on an older verdict. | After a correctable verdict, a hand enters, the grid mode/map generation changes, or the block moves again; confirmation still starts motion. | Issue a one-shot correction ticket bound to verdict ID, detection source sequence, view sequence, map generation, mode, track signature, and expiry. Immediately before dispatch, require coherent current quiet evidence and invalidate tickets on any frame/mode/map/interlock change. | Race hand entry, new frame, `R/RR`, shift/map reload, and double-submit between confirmation and dispatch; all must return a controlled refusal and send no `P`. |
| P0 | `python/rig/placement_geometry.py:164-171`; `python/web/state.py:168-179`; `python/rig/placement_check.py:279-286` | Diagonal drift is collapsed to the largest axis; only one orthogonal neighbour corridor is examined. There is no “essentially one-dimensional” gate. | A block displaced diagonally narrows or overlaps two corridors, but the selected axis's neighbour is clear, so correction is approved. | Until measured diagonal jaw geometry exists, refuse ambiguous two-axis drift. A future policy must check both signed-axis neighbours, the corner sweep, and all occupied footprints. | Sweep diagonal offsets and all occupancy combinations, including boundaries and ties where `abs(dx)==abs(dy)`; no unmeasured diagonal case may be CORRECT. |
| P0 | `python/rig/placement_check.py:256-291`; `python/rig/link.py:1160-1168`; `python/web/routes_command.py:377-384` | The assessor has no command-envelope ceiling. `P` rejects either component above 3 cm with `ValueError`, while the route catches only `RigError`. | UI advertises CORRECT, confirmation produces HTTP 500, or a future catch turns it into a late operational failure after state has changed. | Put the actual command envelope in the preflight policy and catch input-validation errors as a 409 refusal. Treat the 3 cm value as a provisional machine capability until physically validated. | Boundary cases just below/at/above each axis envelope, with assertions for no command, stable lock state, and deterministic HTTP response. |
| P0 | Pi preflight absent; firmware behavior at `arduino/build_test_v1/build_test_v1.ino:4183-4219` and raw validation at `:5294-5301` | The complete target including skew, fixed build offset, tool offset, and correction is not proven reachable on the Pi. Firmware clamps a corrected edge target, warns, and proceeds. | An outward nudge from a far-edge cell is clamped to the travel cap; the claw then descends somewhere other than the displaced block's centre. | Without editing Arduino code, add a Python-side exact full-motion preflight using the active mode and the paired calibration values. Any clamp prediction is a hard refusal and a commissioning blocker. | For every edge/corner cell, test inward/outward offsets and both modes against a shared motion fixture; assert every sent correction is unclamped. Bench-check with an open claw/pointer. |
| P0 | `python/rig/placement_check.py:235-254`; `python/web/state.py:205-208`; `python/rig/supervisor.py:350-375` | MOVED checks angle but not block size/shape consistency. Observation collapses detections to a set and stores only the first detection per cell. | A merged blob, duplicate hypotheses, or unrelated wood-shaped object becomes the selected pickup target. | Preserve per-cell multiplicity and candidate quality. Require exactly one stable, block-consistent track at source and destination/gap before correction. Apply measured size/shape gates to MOVED as well as DISPLACED. | Duplicate-in-cell, merged-pair, offcut-plus-block, and ordering-permutation tests; changing detector output order must not change the action. |
| P1 | `python/rig/placement_geometry.py:239-257` | `size_tolerance_cm` serves both footprint tolerance and allowed geometric extension beyond a neighbour. These are physically different uncertainties. | A block can extend materially past the paired cell yet pass because the broad size tolerance also acts as pairing slack. | Split footprint measurement tolerance from pairing/beyond tolerance. The latter must come from map/localization error and physical pairing measurements, not the current size constant. | Independently vary measured size and beyond-neighbour distance; prove one threshold cannot mask failure of the other. |
| P1 | `python/rig/supervisor.py:230-265` | `locate()` rejects normalized points outside `[0,1]` with near-zero epsilon before applying cell geometry. Far-edge centres sit exactly on the workspace cap. | Small residual map error pushes a legitimate last-row/column centroid outside the quadrilateral; it disappears and can produce REMOVED. A displaced edge block in the inside-quad margin is counted off-board and ignored rather than treated as a hazard. | Classify by uncertainty-aware footprint overlap and nearest expected edge zone. Distinguish outside-camera clutter, board margin, and an edge-cell displacement. | Perturb every boundary centre by measured map/localization error in all directions; ensure correct edge identity or conservative DISAGREES, never silent disappearance. |
| P1 | `python/rig/supervisor.py:699-708,733-759` | Mode changes and interlock trips reset `_CellHistory` but not `_gap_history`; only `reset()` clears both. Old gap votes survive the safety reset. | With N=2/M=3, two pre-trip gap votes plus one post-trip gap can settle FOREIGN after insufficient post-trip evidence. | Clear both histories through one reset primitive on mode/interlock/no-memory transitions. | Seed gap history, trip each reset cause, then prove N fresh post-reset positives are required. Existing lines 549–558 test only the first warming frame and miss this. |
| P1 | `python/rig/supervisor.py:746-763` | Hysteresis is asymmetric. Unexpected cell histories leave the `interest` set immediately when absent, and a settled gap verdict is rendered from the current frame's gap count. | One detector dropout clears a stable FOREIGN verdict without N-of-M evidence; one gap-free frame clears a previously settled gap despite the history. | Maintain a bounded stable universe of recent cell/gap tracks and apply N-of-M to both assertion and clearing. Gap history must be per persistent gap identity, not one global boolean. | Stable foreign/gap followed by one-frame dropout, alternating gap locations, and two simultaneous gaps. |
| P1 | `python/rig/placement_ledger.py:109-117`; `python/rig/supervisor.py:740-747` | `has_memory` is global, while expected occupancy is mode-specific. | Placements exist only for horizontal mode; vertical mode therefore has “memory” but an empty expected set and can yield VERIFIED on an empty view or FOREIGN on a real vertical board instead of NO_MEMORY. | Add `has_memory(mode, board_epoch)` and explicit board/session identity. Persist per-mode ledgers, but do not treat memory from another physical board state as authority. | All combinations of active mode, per-mode placement entries, restart, and board-epoch transition. |
| P1 | `python/rig/supervisor.py:203-227`; `python/web/app.py:228-255` | Quietness is previous-frame full-image difference. A stationary occluder becomes quiet; the real hand trace already reaches VERIFIED for nine frames. | An operator pauses a hand over a cell; after one changing frame the hand becomes baseline and missing/foreign evidence is accepted. | Combine motion with visibility/appearance change against a rolling clean reference. Permit per-region advisory judging, but require globally clear workspace for correction motion. Gate 0b must be measured before deployment. | Hold a hand/tool still for longer than M frames over expected and empty cells; no safety verdict or correction ticket may result. |
| P1 | `python/rig/console_pipeline.py:150-158`; `python/vision/block_outline.py:164-176`; `python/rig/supervisor.py:350-396,512-519` | Live analysis deliberately keeps off-lattice candidates, but observation ignores `on_lattice`. The level ceiling suppresses only a detection mapped back to the same unjudged cell. | Parallax from a level-3+ block shifts its top into a gap or neighbour; it survives as FOREIGN/DISAGREES although the source stack is meant to be unjudged. | Carry lattice membership and height/visibility attribution into layer 4. Conservatively suppress unexpected evidence plausibly caused by an unjudged stack until the parallax model is validated. | Known stacks at all cells/radii and heights around the ceiling, including projected tops crossing gaps and neighbouring cells. |
| P2 | `python/vision/block_levels.py:1008-1017` | A failed level snap can still leave a computed face height that is used for ground projection while `level` is `None`. This path is not currently integrated into live supervision. | Future integration silently moves a centroid using an invalid height estimate. | Ground-project only a validated level/height, otherwise preserve the observed image geometry and mark uncertainty. | Ratios between level bands, impossible heights, and low-confidence fits must not alter ground centre. |
| P2 | `python/tests/test_camera_performance.py:79-82` | The fixture expectation says the first corrected image has six blocks; the current capture has three. | The relevant test suite reports a false regression and can hide a real one among known noise. | Name fixtures explicitly and store per-fixture expected counts/masks. | Test each capture by basename and fail if a fixture changes without its manifest changing. |
| P2 | `docs/features/placement-supervision.md:323-335` and older correction bands; current code in `python/rig/console_pipeline.py` and `python/rig/supervisor.py` | Status prose contains stale phase and quiet-threshold claims, and layer-2 rejection prose predates `include_rejected=True`. | An operator or future change uses an obsolete safety assumption. | Add a single current-status table with implementation version/evidence date and mark historical values explicitly. | Documentation consistency check for named constants and admitted phases. |

No off-by-one error was found in the current `[col,row]` convention: zero is a real coordinate, `[0,0]` is the feeder sentinel, and counts versus highest indices are handled deliberately. `direction==0` in the correction geometry is also handled as no useful drift rather than manufacturing an axis. Those contracts should remain explicitly tested while the surrounding pairing logic is strengthened.

## 2. Detector reliability and information gain (B)

### 2.1 Map-derived expected size as an optional prior

- **What:** Use the calibrated workspace map to supply a local expected level-0 footprint when a valid, generation-matched map exists. Do not make it mandatory and do not replace the frame-width fallback for loose-block, calibration, or pre-map use.
- **Why:** `block_detector.py:571-572` derives `0.144` and `0.052` from image width, so a crop/resolution change alters the geometric prior even when the physical scene does not. A local map prior is physically meaningful and can reduce compound/small-contour ambiguity.
- **Evidence:** The two reference boards have the same physical blocks at different corrected dimensions, while the fallback changes with width. The current aligned detector already returns the correct 29 on-lattice blocks on both, so this is a robustness improvement, not evidence for changing detection settings today.
- **Approach:** Keep layer 1 a pure shape-hypothesis generator. A layer-2 caller may pass a map-derived expected-size hint computed from robust predicted level-0 footprints, possibly binned by location if perspective makes it vary. Map generation and image geometry must match the analysed frame. Layer 1 must not query or reject against the lattice itself.
- **Risk/constraint:** “Always pass it” is invalid because calibration and loose-scene detection may have no trustworthy workspace map. Any altered thresholds, resolution, or flattening require count and wall-time measurements on both reference boards.
- **Validation:** Compare default and map-prior paths on both reference boards, the loose scene, stacked scene, holder offcuts, edge cells, and resized/cropped copies. Record physical/on-lattice/off-lattice counts and wall time for every case.
- **Effort:** Small–medium.

### 2.2 Compound hypotheses with provenance, resolved in layer 2/3

- **What:** Keep `_decompose_compound` hypotheses but attach component/provenance metadata and resolve mutually exclusive hypotheses through lattice/global assignment in layer 2 or calibration in layer 3.
- **Why:** A synthetic child rectangle is deliberately block-shaped; another local shape score cannot reliably reject it. Position and global exclusivity are the missing evidence.
- **Evidence:** `block_detector.py:461-467` can replace a child's ordinary confidence with a candidate score, and the FAULTY capture demonstrates how damaging unchecked lattice extrapolation can be. The holder offcuts show why shape plus wood colour is not semantic identity.
- **Approach:** Add `component_id`, original-versus-synthetic, decomposition score, covered-area fraction, and sibling exclusivity to the detection contract. Layer 2 solves a one-hypothesis-per-component assignment against expected physical cells; layer 3 may use the same evidence during calibration. Rejected alternatives remain inspectable for diagnostics.
- **Risk/constraint:** Consulting the lattice *inside layer 1* would violate the required pure-shape boundary. The clean seam is richer hypotheses out of layer 1, lattice decisions in layer 2/3.
- **Validation:** Touching blocks, cast shadows, offcuts, single large rectangles, and deliberate false seams, with shuffled candidate order. Measure both reference counts and times if candidate generation settings change.
- **Effort:** Medium.

### 2.3 Photometric health and Gate 0b, not a second detector

- **What:** Add exposure/white-balance health and a measured per-cell pre/post change signal to the existing supervision observation.
- **Why:** Red-minus-blue segmentation is vulnerable to the strong magenta cast and clipped tabletop seen in the captures. A same-camera temporal difference can confirm that a planned cell actually changed even when colour confidence degrades.
- **Evidence:** `camera_live.png` and the loose capture have visibly different casts; shadows bridge block edges on both reference boards. Frame differencing exists in the labelled calibration path but not as live placement evidence.
- **Approach:** Maintain a rolling *clean, coherent* reference derived from the already-captured stream and calculate per-cell/footprint change after a placement. Fuse it as Gate 0b evidence with the existing detection result; do not create a detector, second analysis path, or extra capture. Preserve a global visibility gate for motion authorization.
- **Risk/constraint:** No threshold is presently measured. Illumination changes and arm shadows can mimic placement. This cannot be enabled on the rig until the measurement in §7.5 is complete.
- **Validation:** Label unchanged, placed, removed, hand, arm-shadow, exposure-step, and neighbour-only changes per cell across the board and levels. Select a threshold on held-out runs with a safety-weighted false-accept target.
- **Effort:** Medium.

### 2.4 Sub-pixel localization and temporal centroid fusion

- **What:** Preserve genuinely floating-point geometry through resize/rectification, refine stable edges if useful, and fuse centres/angles/sizes over the quiet evidence window.
- **Why:** Correction currently targets a single observation. Random centroid jitter can be reduced without new frames because the N-of-M window already contains frames.
- **Evidence:** `minAreaRect` starts with floating geometry, but the resize path reconstructs from rounded contours at `block_detector.py:623-644`. Rectified boxes are excellent for angle/size consistency but can shift toward a shadow or merged edge. Occupancy alone is hysteresed today.
- **Approach:** Retain transformed float centre/corners, then associate detections across coherent quiet frames. Use a robust median or Huber-weighted centre and circular angle statistic; report covariance/dispersion. Test contour moments and line-refined corners empirically—moments may be *more* biased by shadows, so they should not be adopted by intuition.
- **Risk/constraint:** Temporal fusion must use the exact source frames and must not add captures. It depends on fixing the P0 frame-provenance bug first.
- **Validation:** Stationary blocks repeated across all cells and lighting conditions; compare bias, repeatability, and correction miss distance for box centre, moments, refined corners, and temporal fusion.
- **Effort:** Medium.

### 2.5 Detection trust as calibrated evidence

- **What:** Propagate a quality vector and eventually a calibrated likelihood/uncertainty, rather than treating every hypothesis equally or presenting the current score as a probability.
- **Why:** Merged blobs, partial blocks, offcuts, and weak colour separation should reduce confidence or force an insufficient-evidence verdict.
- **Evidence:** `BlockDetection` carries contour, box, centre, width, height, angle, area, rectangularity, solidity, confidence, hue, measured width/height/angle, and `on_lattice` (`block_detector.py:36-64`). Current `confidence` is only `0.55*rectangularity + 0.45*solidity` (`:489-491`) and can be replaced by a compound candidate score.
- **Approach:** Preserve raw features plus provenance. Fit/calibrate a trust model from labelled rig captures, or initially use explicit quality gates with measured bands. Convert localization repeatability into axis covariance separately from “is one block” confidence.
- **Risk/constraint:** A guessed fusion weight is another unmeasured threshold. Low confidence must fail closed; it must never turn red evidence green.
- **Validation:** Reliability plots and held-out confusion matrices for single block, merged blocks, partial occlusion, offcuts, shadows, and non-wood objects, plus localization error versus predicted covariance.
- **Effort:** Medium–large, mostly data.

### 2.6 Absolute level and parallax trust

- **What:** Calibrate camera height/nadir with tape measurements at multiple radii; combine the side-band ratio with ledger-known stack level and other cues only after they are validated. Feed a validated ground-footprint prediction to layer 4.
- **Why:** Levels 1–2 currently carry approximately 0.9–1.9 cm directional parallax in the documented tape estimate, which is too large for correction. A correct model can raise the judgement ceiling and improve identity.
- **Evidence:** The stacked capture clearly shows side faces and radial top-face displacement. The real-board side/top ratio CV is worse than the multi-level capture; absolute level numbers have not been validated. `block_levels.py` already implements the projective correction, but live `ConsolePipeline` does not use it.
- **Approach:** Near term, use the ledger's known top level as the height prior and analytically predict where that top should appear; compare detections in image space and retain ground cell identity. Longer term, refactor one shared segmentation/geometry front end whose outputs serve outline and level inference. Side-band ratio, top-face scale, and perhaps shadow/defocus may corroborate height, but shadow and defocus are lighting/focus dependent and must not be primary cues without data.
- **Risk/constraint:** Calling `block_levels` alongside the live outline detector would be a second detector/path and violates the layer-4 constraint. Integration must share one layer-1 result or remain offline. The current double-flatten cost also makes direct live insertion unattractive.
- **Validation:** Known stacks from level 0 through the physical maximum at centre, corners, and intermediate radii; tape-measured camera height/nadir; compare predicted versus observed top displacement, level confusion, cell identity, and correction pick error on held-out positions.
- **Effort:** Large.

## 3. Supervisor intelligence and discarded evidence (C)

### 3.1 Detector-field inventory

| Produced field | Current layer-4 use | Recommended role |
|---|---|---|
| `center` | Used for `locate`, residual, gap point, and correction | Keep; bind to source frame and fuse temporally with uncertainty. |
| `box` | Indirectly used for footprint/own size | Use footprint overlap, edge/margin hazards, occlusion, and corridor geometry. |
| `width`, `height`, `angle` and `own_size`/`own_angle` | Own size/angle are stored for the first detection per cell | Preserve per candidate/track; use measured one-block consistency for MOVED and DISPLACED. |
| `contour` | Ignored | Diagnostics and optional offline localization comparison; not necessarily safe online due to shadows. |
| `area` | Ignored | Detect partial/compound inconsistency when calibrated against local expected footprint. |
| `rectangularity`, `solidity` | Ignored | Evidence that the hypothesis is one clean block; low values should cause ambiguity/insufficient evidence. |
| `confidence` | Ignored | Use only after calibration and provenance-aware interpretation; current value is not a probability. |
| `hue` | Ignored | Weak material/identity cue and assignment tie-breaker. It cannot by itself distinguish wood under the observed lighting. |
| `on_lattice` | Ignored after `include_rejected=True` | Preserve as layer-2 evidence. Off-lattice near a planned corridor is a hazard, not merely display clutter. |
| `measured_width/height/angle` | Reached through own-size/angle helpers | Keep the separation from rectified display geometry and expose uncertainty. |
| total detections and `off_board` count | Counted in `Observation`, not used in classification/action | Surface as scene health/hazard. Nearby off-board footprints should block the next motion; remote clutter may remain advisory. |
| `cell_residuals_cm` | Computed but not rendered | Render as advisory vector/history with uncertainty. Never expose a raw single-frame residual as a motion promise. |

### 3.2 Rich observation model with explicit ambiguity

- **What:** Replace set-only evidence with per-cell/per-gap candidate lists and persistent tracks, including multiplicity, provenance, quality, footprint, covariance, and source-frame identity.
- **Why:** Sets are excellent for fail-safe occupancy comparison but erase exactly the information needed to decide whether a MOVED hypothesis is one real block.
- **Evidence:** `supervisor.py:350-375` stores only the first point/angle/size per cell, and `web/state.py:205-208` selects the first detection when building a correction candidate.
- **Approach:** Retain the set verdict as the conservative first layer. A second association stage may refine one unambiguous one-to-one case. Any multiplicity, poor quality, or near-tie remains DISAGREES/INSUFFICIENT.
- **Risk/constraint:** More information must not make the safety policy eager. Layer 4 consumes existing detector output only.
- **Validation:** Candidate order permutations, duplicate hypotheses, merged blocks, two simultaneous moves, and confidence ties.
- **Effort:** Medium.

### 3.3 Verdict evidence quality

- **What:** Add a structured evidence-quality object rather than one unexplained scalar probability.
- **Why:** Operators need to know whether a verdict is supported by 3/5 coherent frames, precise localization, complete visibility, and a unique association.
- **Evidence:** `Verdict` carries severity but no quality; the current UI cannot distinguish a barely settled weak detection from a clean five-frame result.
- **Approach:** Report temporal support `(positive,total)`, coherent-frame age, visibility/quiet status, candidate quality, localization sigma, map uncertainty, association margin, and whether geometry constants are measured. A derived UI band may be high/medium/insufficient, with insufficient always failing closed.
- **Risk/constraint:** Do not present an uncalibrated number as “92% safe.” Quality is explanatory evidence, not permission to override a red condition.
- **Validation:** Calibration plots versus labelled outcomes and tests showing every missing required dimension blocks correction.
- **Effort:** Medium.

### 3.4 Conservative identity assignment

- **What:** Use gated bipartite/Hungarian assignment between missing expected tracks and new detections, with centre distance, footprint, angle, hue, and temporal continuity.
- **Why:** Some multi-cell set differences are one or two resolvable moved blocks rather than an unknowable board.
- **Evidence:** Current `classify()` stops at DISAGREES for many two-cell changes even though residual and appearance evidence exists but is discarded.
- **Approach:** Assignment may produce an *advisory* identity only when there is a unique, well-separated optimum within measured physical limits. Correction remains restricted to one stable level-0 vertical block with clear full corridor. Near-equal assignments, occlusion, merges, foreign material, or multiple interacting movements remain must-stop.
- **Risk/constraint:** Hungarian assignment always returns an answer unless gated; an ungated answer would be worse than set logic. All cost weights and acceptance margins need labelled measurement.
- **Validation:** Controlled one/two-block moves, swaps, crossings, same-size ties, hue changes, missing detections, and occlusion; report assignment precision, especially false unique assignments.
- **Effort:** Large, data-heavy.

### 3.5 Regional quiet and persistent visibility

- **What:** Track quietness/visibility per cell or region against a rolling clean reference while retaining a global-clear requirement for correction motion.
- **Why:** A remote arm shadow need not prevent advisory judgement of a settled region, but a stationary hand over the target must not become “quiet.”
- **Evidence:** The current whole-frame previous-frame metric blocks on any motion yet eventually accepts static occluders. Captures show large irrelevant peripheral regions in raw view and concentrated shadows on the board.
- **Approach:** Work only on the already-corrected captured view. Maintain clean-reference age and ROI masks for expected footprints/corridors; compute local change and visibility. Supervisor may update unaffected cells, but correction ticket creation and dispatch require target, corridor, and whole workspace clear according to measured gates.
- **Risk/constraint:** ROI/downsample changes alter Gate 0's statistical footing. They require new measurements and cannot be silently substituted for 0.01.
- **Validation:** The Gate 0b protocol in §7.5 plus full build-cycle traces, not static five-block clips alone.
- **Effort:** Medium–large.

### 3.6 Window availability and level ceiling

- **What:** Instrument how often a coherent N-of-M quiet window exists after real placements, and make level eligibility a capability result rather than a magic ceiling.
- **Why:** Frequent arm motion resets history, so nominal N/M says little about actual latency/availability. Level 3 is currently permanently unjudged regardless of camera radius or evidence quality.
- **Evidence:** `_CellHistory` and `_gap_history` reset around interlocks; current traces are useful but are not full build cycles. `LEVEL_CEILING = 3` at `supervisor.py:75` predates validated parallax integration.
- **Approach:** Log terminal PLACED time, coherent analysed source frames, motion/visibility rejection reason, time-to-first-settled verdict, and resets by cause. Level policy should ask whether projected displacement uncertainty keeps the top footprint uniquely attributable to the cell; if not, return UNJUDGED.
- **Risk/constraint:** Raising the ceiling before tape and stack validation is invalid.
- **Validation:** Entire vertical builds under representative day/night lighting and every cell, plus the level protocol in §2.6.
- **Effort:** Instrumentation small; validated level expansion large.

## 4. Memory and build state (D)

### 4.1 Separate command truth from as-built evidence

- **What:** Keep `Placement` immutable as command/terminal truth and add an append-only `AsBuiltObservation` linked by placement ID.
- **Why:** Overwriting the ledger with noisy vision would corrupt the authoritative record. A separate evidence stream enables actual-position comparison, drift trends, and auditability.
- **Evidence:** `placement_ledger.py` stores only mode/col/row/level/placed_at. The proposed observed centre/residual fields are not currently written.
- **Approach:** Store source sequence, map generation/version, mode, measured centre/angle/size, residual and covariance, detector/visibility quality, verdict, and observation time. Never reload these measurements as motion calibration automatically; aggregate trends are recommendations until a human-approved calibration process validates them.
- **Risk/constraint:** Mixing grid model knobs, build offsets, tool offsets, and observed residual would violate the calibration taxonomy. Any paired firmware/config change must remain paired, and this report proposes none.
- **Validation:** Persistence/restart, map-version change, failed/corrected placement, and immutable-command-history tests.
- **Effort:** Medium.

### 4.2 Recency and spatial priors as tie-breakers only

- **What:** Associate `placed_at` and the just-worked cell with the observation window and candidate assignment.
- **Why:** The newest placement is the most likely changed location and has the freshest known pre/post evidence.
- **Evidence:** `placed_at` is currently unused by supervision; BuildController/Orchestrator already define a serial operation boundary.
- **Approach:** Use recency to choose the expected change ROI/reference and to break otherwise safe assignment ties. Never let it override contradictory visual evidence or permit motion.
- **Risk/constraint:** “The arm was there, therefore that block moved” is not evidence. Prior strength needs labelled sequences.
- **Validation:** Disturb the just-placed cell, a neighbour, and a remote cell in separate and combined trials; measure association error.
- **Effort:** Small–medium.

### 4.3 Bootstrap and board/session identity

- **What:** Add an explicit operator-confirmed baseline-inventory mode with a board/session epoch and evidence provenance.
- **Why:** A restart currently has no authority to infer that a visually full board matches prior commands, but permanent NO_MEMORY is operationally limiting.
- **Evidence:** The ledger intentionally does not reconstruct from camera observations. This is safer than silent inference and should remain the default.
- **Approach:** Capture a labelled baseline, show all inferred cells/levels to the operator, and store it as a lower-authority bootstrap record. Monitoring may use it; correction should remain disabled unless mode, grid map, anchor, levels, and board identity are explicitly confirmed to the same standard as commanded placements.
- **Risk/constraint:** A merely “full-looking” board cannot reveal hidden stack levels or identity. Automatic bootstrap-to-correction is unsafe.
- **Validation:** Known boards with missing, extra, stacked, moved, and occluded blocks; require perfect safety-critical acceptance on the commissioning set.
- **Effort:** Large.

### 4.4 Per-mode persistence and event history

- **What:** Preserve per-mode ledger records across `R/RR`, but bind them to physical board epoch; represent corrected/disturbed/removed as append-only events rather than a mutable flag.
- **Why:** A mode latch need not erase historical data, while the same coordinates in different modes do not describe the same physical allocation. Event history preserves causality and prevents “corrected=true” from outliving a later disturbance.
- **Evidence:** The ledger is already keyed by mode, but the supervisor's global `has_memory` test is wrong for this purpose. `note_mode` resets hysteresis, not the underlying ledger.
- **Approach:** Query memory by `(board_epoch, mode)`. On mode change invalidate all live verdicts/tickets/tracks, then load only that mode's expected history if the operator confirms the physical board state is the corresponding one.
- **Risk/constraint:** Vertical and horizontal grids overlap physically but have different registration, footprints, tool rotation, and counts. They must not be merged into one occupancy map.
- **Validation:** Repeated mode latches with untouched, cleared, and replaced boards; no cross-mode verdict leakage.
- **Effort:** Medium.

## 5. MOVED versus DISPLACED (E)

### 5.1 Continuous evidence, conservative final classes

- **What:** Compute a continuous displacement evidence record—residual vector/covariance, planned-footprint overlap, neighbour-footprint overlap, gap penetration, own-size/angle quality, and axis dominance—then map it to the existing fail-safe verdict classes.
- **Why:** Pure set difference is brittle around boundaries, while a free-running probabilistic classifier could become overconfident. Continuous geometry can improve explanation and association without weakening stop behaviour.
- **Evidence:** `implausible_displacement()` uses only whether a gap point lies more than provisional `PAIRING_BEYOND_CM=1.0` past the neighbour. `axis_coverage()` and `residual_cm()` already provide pieces of a richer model.
- **Approach:** For each stable track, calculate likelihood-compatible features with explicit uncertainty bands. `MOVED` means a unique source/destination cell association; `DISPLACED` means a unique source block whose footprint remains off-site or in a defined adjacent gap; `DISAGREES` remains the answer for overlap, diagonal ambiguity, multiple identities, poor quality, or band overlap. Do not guess the bands.
- **Risk/constraint:** A continuous score must not bypass the discrete safety gates. Every threshold listed in §7.5 needs physical measurement.
- **Validation:** Controlled offset sweeps along both axes and diagonals, at centre/edge/corner cells, with occupied and empty neighbours. Plot features against labelled physical state and grip/collision outcome.
- **Effort:** Medium–large.

### 5.2 Persistent per-gap identity

- **What:** Replace the global `_gap_history: deque[bool]` with tracks keyed by nearest source cell, signed axis/side, and spatial position.
- **Why:** Three “gap present” votes can currently come from different objects or locations, and one gap-free frame clears settled evidence asymmetrically.
- **Evidence:** The source comment explicitly notes per-gap identity is not built (`supervisor.py:750-759`).
- **Approach:** Associate gap candidates frame-to-frame under measured distance/quality gates, preserve both positive and negative evidence, and require N-of-M for the same track. Drop or mark ambiguous when tracks cross, split, merge, or change candidate provenance.
- **Risk/constraint:** Track association must be provenance-correct and cannot add frames. A global boolean is safer than a falsely confident identity, so ambiguous tracks must degrade to DISAGREES.
- **Validation:** Alternating gaps, two simultaneous gaps, jitter across a cell boundary, occlusion/dropout, and block replacement by a different object.
- **Effort:** Medium.

## 6. Correction targeting and mode scope (F)

### 6.1 Audit of the current offset

`correction_offset(observed_centre_cm, pick_cell_centre_cm)` is conceptually correct: it produces the displacement required to move the neutral pickup target from the source cell centre to the observed block centre. Both points live in the map's `(u,v) * workspace_cm` magnitude-from-home frame, so positive X/Y means away from the respective home switch. Python does not manipulate firmware `axisPos[]`; the firmware's named conversion helpers remain the only signed-position crossing. A reported placement error would indeed take the opposite correction sign, whereas this function is not processing a verbal error—it is directly computing the requested pickup location.

`SKEW_Y_PER_COL_CM` is not double-counted. It affects where the original build physically placed the block, and that physical result is measured by the camera. The correction residual takes the pickup to that measured result; the standard build leg then applies the normal skew once for the destination. The fixed horizontal build placement offset and CW tool offset are likewise placement mechanics, not terms to fold into the lattice or workspace map.

The accuracy limits are:

- a single `Observation` centre rather than an N-frame fused track;
- rectified/rounded box geometry and shadows rather than a measured localization covariance;
- four-corner workspace flattening residual documented at mean 1.25 px, maximum 2.07 px, approximately 0.27 cm;
- lack of local curvature compensation;
- no valid height/parallax correction above level 0;
- no exact Pi-side full-motion reachability calculation;
- possible source-frame mismatch described in §1.

### 6.2 Most accurate achievable pick point

- **What:** Use a provenance-coherent robust track centre, map it through a locally validated workspace model, correct expected parallax from a validated/ledger-known height, and carry a covariance through the full motion preflight.
- **Why:** Temporal fusion removes random jitter; local map residual correction removes systematic bias that averaging cannot; height correction restores ground identity; full compensation preflight prevents clamps.
- **Evidence:** The map's 0.27 cm worst residual is comparable to a meaningful correction band. The stacked capture shows parallax substantially larger than that. Current correction uses one centre.
- **Approach:** First fix source binding. Fuse only coherent quiet detections belonging to one stable candidate. Use a held-out calibration target to build a layer-3 residual field or piecewise map—without moving the grid model's trim/error/shift knobs. Apply analytic height projection only when height/level is valid. Convert the requested magnitude displacement into the exact compensated holder target in a Python mirror and reject uncertainty bands that intersect limits or occupied swept volumes.
- **Risk/constraint:** Local mapping belongs to calibration layer 3, not layer 1. Do not change `GRID_ERROR_OFFSET_*` or `GRID_SHIFT_*` without explicit user permission. Any firmware/config pair remains paired. No threshold or model is accepted without rig validation.
- **Validation:** Use a calibration puck or block at commanded cells including every edge/corner. With an open claw or non-contact pointer, compare camera target to physical centre over repeated approaches from both directions. Then run sacrificial pickup/place trials, reporting per-axis bias, 95th percentile, worst error, and success/collision—not merely mean error.
- **Effort:** Medium for coherent fusion/preflight; large for calibrated local mapping/height.

### 6.3 Horizontal correction scope

- **What:** Keep horizontal correction disabled until it has its own end-to-end map, motion, rotation, and capture validation.
- **Why:** Horizontal placement uses the +1.9/+1.9 cm grid registration, CW tool offset `(+0.9,-0.3)` cm, fixed build X placement offset `-0.4` cm, a rotated 6.0×2.2 footprint, and a pickup-rotate swing. A vertical-only proof does not exercise X's inverted signed machine position or the rotation geometry.
- **Evidence:** `placement_check.py:215-223` correctly refuses non-vertical correction today. The repo authority explicitly says anything tested only on Y/Z proves nothing about X.
- **Approach:** Acquire a fresh block-calibrated horizontal workspace map and validate every term separately: lattice centres, CW swing/tool offset, fixed build placement offset, local residual, correction direction, jaw orientation, corridor, and edge reachability. Exercise positive and negative requested offsets on both axes and verify conversion through the firmware helpers rather than duplicating signed-axis arithmetic in Python.
- **Risk/constraint:** Do not absorb physical placement error into horizontal `error_offset` or `shift`; those move every drawing. Do not propose Arduino edits in this pass. Calibration values with config partners must stay paired in any later authorized change.
- **Validation:** Full horizontal cell matrix including row/column zero, far edges, neighbours occupied on each side, repeated CW cycles, and independent physical measurement of holder-versus-block centre before/after rotation.
- **Effort:** Large; hardware-heavy.

### 6.4 Automation recommendation

- **What:** Retain explicit operator-confirmed correction. Do not enable automatic correction yet.
- **Why:** Current P0 evidence and reachability gaps can authorize the wrong motion even when the geometric policy says CORRECT.
- **Evidence:** Correction hardware phase P is documented as built but not bench-flashed/commissioned; the endpoint lacks a coherent ticket; no exact clamp preflight exists.
- **Approach:** Automatic correction may be reconsidered only after coherent provenance, detector-error fail-closed, stable unique track, measured gates, global visibility/quiet, level-0 vertical scope, complete corridor/reachability proof, one-shot ticket, one-attempt limit, and successful phase-P commissioning. Any uncertainty returns control to the operator.
- **Risk/constraint:** Automation magnifies rare false accepts; operator confirmation does not repair bad evidence, so it is necessary but not sufficient.
- **Validation:** Fault-injection campaign plus a staged hardware acceptance checklist before any flag can enable automation.
- **Effort:** Small to keep disabled; large to qualify.

## 7. Efficiency, performance, and validation gaps (G/H)

### 7.1 Redundant segmentation and flattening

- **What:** Share one preprocessed frame/hypothesis front end if levels are integrated, and eliminate the levels path's duplicate illumination flattening only after the required benchmark.
- **Why:** `block_levels.py:413-417` flattens before later calling block detection, whose default path flattens again (`block_detector.py:542`; levels call around `:943-951`). This helps explain the 333–617 ms local times.
- **Evidence:** The aligned live pipeline currently runs one detector per analysed frame; supervision does not re-segment. Redundancy arises in the standalone levels path, not between current live layers. On the two reference boards, the levels path measured about 447 and 333 ms locally.
- **Approach:** Refactor preprocessing ownership so a single corrected/flattened representation and shape hypothesis set can feed outline and level cues. A tempting `flatten=False` change is not accepted merely because it is faster.
- **Risk/constraint:** Any flatten/detection-setting change must report count and wall-time on *both* reference boards, plus stacked/loose regressions. Layer 4 may not create a second analysis path.
- **Validation:** Before/after table with physical, aligned, rejected, level-measured, and covered counts and wall time on both named boards, then stacked/loose scenes.
- **Effort:** Medium.

### 7.2 Quiet-fraction cost

- **What:** Replace large temporary NumPy conversions with an OpenCV-backed absolute difference/threshold/reduction and consider ROI/downsample only as separately measured variants.
- **Why:** Current `quiet_fraction()` converts two frames to signed arrays and creates full-size difference/channel-max temporaries on every supervised frame.
- **Evidence:** On this development machine, current NumPy cost was about 11–12 ms at 433×520 and 62 ms at 1296×972; an equivalent OpenCV split/threshold/OR prototype was about 0.46 ms and 4.33 ms respectively. The actual current corrected view is approximately 433×520. These are not Pi 5 numbers. The source's 5–15 ms comment for 1296-width work is not backed by an isolated current Pi trace in the reviewed evidence.
- **Approach:** Benchmark the exact semantic equivalent on Pi 5, including memory and event-loop latency. Keep one OpenCV owner/executor. If ROI or downsampling is considered, treat it as a new Gate 0 statistic and remeasure its threshold.
- **Risk/constraint:** A numerically similar fraction is not automatically equivalent near threshold; colour-channel reduction, interpolation, and masks can change decisions.
- **Validation:** Bit/decision comparison on all 1,398 Gate 0 trace frames, both reference boards, arm/hand traces, and full-build recordings; report timing distributions, not one mean.
- **Effort:** Small for exact OpenCV form; medium for revalidated ROI.

### 7.3 Pipeline throughput and backpressure telemetry

- **What:** Measure capture rate, analysis completion rate, source-frame age, replacement count, errors, and supervisor-consumed unique results.
- **Why:** Latest-only workers are appropriate for latency, but without provenance telemetry their dropped/replaced work is invisible and currently creates false frame identity.
- **Evidence:** `AnalysisWorker` already records source sequence, generation, submit/finish times, replacements, and errors, but `ConsolePipeline` discards most of that semantic information when forming `ProcessedFrame`.
- **Approach:** After the P0 binding fix, expose age/replacement/error counters and drive supervision only from unique coherent results. Keep capture responsive; do not queue an unbounded backlog.
- **Risk/constraint:** No extra frames or detector pass is required. Instrumentation must avoid leaking large frame buffers.
- **Validation:** Artificial detector delays, failures, map changes, and phase changes at several capture rates; prove bounded memory and correct verdict latency.
- **Effort:** Small.

### 7.4 Existing coverage holes

The strongest current tests validate static set logic, individual geometry functions, saved-frame detector counts, and several real motion/hand traces. The important missing contracts are cross-component and temporal:

- exact analysis source frame equals the view used for quietness and the sequence used for hysteresis;
- analysis exception/staleness cannot mean empty board;
- no source result advances hysteresis more than once;
- correction ticket invalidation under new frames, map/mode/shift changes, interlock, hand entry, and double click;
- complete compensated target remains inside travel with no clamp for every edge/corner;
- diagonal/two-neighbour and corner swept-volume clearance;
- multiplicity and detector-order invariance;
- symmetric assertion/clearing hysteresis and per-gap identity;
- per-mode `has_memory` and board epoch;
- stationary occlusion longer than M;
- level-ceiling parallax into an adjacent/gap cell;
- end-to-end full build-cycle window availability;
- horizontal correction qualification;
- exact expected fixture identities in `test_camera_performance.py`.

The web supervision helpers fabricate a `ProcessedFrame` whose view and detections are constructed together, so they cannot expose the current production source-sequence mismatch. The existing interlock reset case observes only the first post-reset warming frame; it needs enough subsequent frames to expose leaked gap votes.

### 7.5 Measurements required before provisional values reach the rig

No replacement numbers are proposed here.

| Constant/capability | Measurement to run | Acceptance output |
|---|---|---|
| `PAIRING_BEYOND_CM` | At several centre/edge cells, place one block at controlled X and Y offsets through the source-to-neighbour corridor and beyond it; include a genuinely different block in the gap and occupied neighbours. Tape/fixture the ground-truth centre. | Labelled distributions for true paired displacement versus false pairing, map/localization error included; select a bound with no false-correctable cases in the commissioning set. |
| `CORRECT_BAND_MIN_CM` | Repeat normal placements and correction attempts over a controlled small-offset sweep. Compare final centre error and disturbance/failure probability with versus without correction. | Smallest band where correction improves the held-out 95th-percentile result and does not worsen settled blocks. |
| `SIZE_TOLERANCE_CM` | Capture single blocks, partial blocks, touching/merged blocks, offcuts, shadows, and rotated blocks across cells/light. Measure projected own-size error against taped dimensions. | Separate single-block measurement tolerance from compound rejection; demonstrate merged/partial cases cannot pass the correction gate. |
| `JAW_CLEARANCE_CM` | With sacrificial blocks and emergency stop, increment displacement toward occupied neighbours and perform slow open-jaw approaches without gripping, for both axes and worst orientations/cells. | Conservative clearance bound from actual swept jaw envelope and a lower confidence limit, not nominal CAD alone. |
| `ANGLE_TOLERANCE_DEG` | Rotate blocks by known increments across cells, then measure pickup success, slip, and neighbour contact for repeated approaches. | Angle band supported by worst-cell/worst-light success and clearance data. |
| `LEVEL_CEILING` | Tape-measure camera height and nadir; build known stacks at multiple radii/corners through physical maximum; record top displacement, side ratio, scale, detection recall, cell identity, and false FOREIGN. | Eligibility by validated uncertainty/cell separability. Raise no level merely because the estimator emits a number. |
| Gate 0b per-cell change | Record coherent pre/post views for unchanged, place, remove, neighbour-only, hand/tool, arm shadow, and exposure/lighting changes at all regions and representative levels. Split by run/day for validation. | ROI change distributions, false-accept/false-reject curve, selected operating rule, and full-cycle availability/latency. |
| Gate 0 existing 0.01 and 3/5 | Instrument complete builds from terminal PLACED through arm exit and next motion under representative lighting, cells, and stack states. | p50/p95 time to coherent settled window, unavailable fraction, reason counts, and false verdict count. |
| 3 cm `P` envelope and full target reachability | Use a pointer/open claw at controlled ±X/±Y offsets including all edges; compare predicted full compensated holder target to physical travel and stop before any predicted clamp. | Measured safe command domain by mode/cell/rotation; Python preflight agreement with observed holder position. |
| Local map residual/parallax | Place a taped calibration target at a denser grid than four corners and at known heights/radii. | Held-out vector residual field and uncertainty, with separate systematic map and height components. |

Any proposed detection resolution, flattening, area, colour, or morphology change additionally requires the mandated report for **both** reference boards: physical block count, on-lattice count, rejected/offcut count, and wall-time distribution under identical hardware and warm-up. The previous “zero extra blocks for roughly four seconds per frame” experiment is the cautionary baseline.

## 8. Ranked shortlist: highest value per effort

1. [x] **Bind detections, quiet image, sequence, and map generation; consume each analysis result once.** Highest safety gain and prerequisite for every temporal improvement. Medium effort.
2. [x] **Propagate detector failures/staleness as NO_VISION, never empty detections.** Small effort, closes a direct false-REMOVED path.
3. **Make correction a one-shot coherent ticket with atomic quiet/mode/map/track revalidation.** Medium effort, closes the decision-to-motion race.
4. **Add exact Python full-motion reachability/clamp preflight for all compensated targets.** Medium effort and a commissioning blocker at edges.
5. **Refuse diagonal correction and enforce both-neighbour/corner clearance until measured.** Small initial effort with large collision-risk reduction.
6. **Preserve multiplicity and require one stable block-consistent track for MOVED/DISPLACED.** Medium effort; prevents first-candidate/merged-blob pickup.
7. [x] **Fix reset/decay semantics: clear gap history everywhere and hysterese clearing with persistent gap identity.** Small–medium effort; removes repeatable false/stale verdicts.
8. **Make ledger memory mode- and board-epoch-specific.** Small–medium effort; fixes misleading cross-mode VERIFIED/FOREIGN outcomes.
9. **Fuse centroid/angle/size over the existing coherent quiet window and expose uncertainty/residuals.** Medium effort; directly improves the requested pickup centre without extra frames.
10. **Run the complete-build Gate 0/Gate 0b and provisional-geometry measurement campaign.** Hardware effort is substantial, but it is the only valid route to safely tune thresholds, raise the level ceiling, or automate correction.

Performance cleanup—especially the exact OpenCV quiet-fraction equivalent and removal of double flattening—should follow the correctness items. It is attractive and likely inexpensive, but throughput cannot compensate for incoherent evidence.

## 9. Open questions for the human team

1. Has phase `P` actually been flashed and bench-tested since the latest correction documents, or is “implemented but uncommissioned” still current?
2. Can the Pi log or retain the exact analysed source frame for a short bounded window, or is there a memory constraint that requires the worker to return its source view with the result?
3. What is the required safety target for correction qualification: zero false-correctable outcomes in a defined trial count, a maximum miss distance, and/or a jaw-contact criterion?
4. Is there an approved non-contact pointer, calibration puck, sacrificial block setup, and emergency-stop operator for the reachability/jaw-clearance trials?
5. What are the taped camera height and nadir coordinates? The documented `H≈57 cm`, `X≈11.4 cm`, `Y≈32.5 cm` are estimates and should not become calibration constants without confirmation.
6. Does a physical board ever remain in place across an `R/RR` latch or process restart, and how should the operator attest that the board epoch is unchanged?
7. Should off-board objects anywhere inside the holder/work envelope block the next placement, or only objects whose footprint intersects the planned approach/corridor?
8. Is horizontal correction a real near-term requirement, or should the product explicitly label it unsupported until a dedicated commissioning campaign is funded?
9. Can representative full-build recordings be collected across lighting periods, including stopped-hand, arm-shadow, exposure-step, and stacked-block cases, while preserving frame sequence/timestamps?
10. Is the web-test executor stall reproducible on the target Pi or a development-container artifact? It should be resolved before relying on the suite as proof of event-loop/build-thread safety.
11. Which document is intended to be the live operational authority for supervision constants? A generated current-status table would prevent the present 0.01/0.02 and phase-admission contradictions.
12. Who is authorized to approve later changes to shared grid-model values? This audit intentionally proposes no change to `GRID_ERROR_OFFSET_*`, `GRID_SHIFT_*`, trims, tool offsets, firmware, or `config/rig.json`.

The recommended immediate scope is therefore narrow: repair evidence provenance and fail-closed behavior, harden correction authorization/reachability, and collect the missing rig measurements. Detector retuning, higher-level correction, horizontal correction, and automatic correction should remain gated behind those results.

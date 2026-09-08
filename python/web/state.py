"""Small, frame-free state snapshots for the web operator console."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Literal

from pydantic import BaseModel

from rig.placement_check import Correction, assess as _assess
from rig.placement_geometry import residual_cm as _residual_cm
from rig.supervisor import STATES, Verdict
from web.geometry import build_geometry


@dataclass(frozen=True)
class SupervisionState:
    """The latest thing the observer said, held on ``app.state``.

    Server-side only for now: M3b turns this into a published
    ``SupervisionModel`` and the four surfaces that render it. It exists at M2
    so a bench session has something to watch and so the wiring can be tested
    without any of the UI.

    ``state`` is one of ``rig.supervisor.STATES``. ``verdict`` is None for every
    state but ``VERDICT`` — including the good ones: BUSY, QUIET and NO_MEMORY
    are not faults and must never take a state colour.
    """

    state: str
    reason: str | None
    verdict: Verdict | None
    judged_at_ms: int
    #: The operator CORRECTION action's assessment of the current verdict — a
    #: `Correction` when the claw MAY return a DISPLACED block, else None. The
    #: `correction_reason` sentence beside it in `SupervisionModel` always says
    #: why. Server-authoritative: `/api/supervision/correct` re-derives this and
    #: never trusts the published flag (DESIGN.md §8).
    correction: Correction | None = None
    correction_reason: str | None = None
    #: ADVISORY — straight-line cm from the offending block to its planned cell
    #: centre, for a MOVED / DISPLACED verdict. Published for the operator to
    #: read "how far off"; it never gates anything and takes no state colour.
    residual_cm: float | None = None
    #: ADVISORY — the largest on-cell drift anywhere on the board, cm. Non-None
    #: for VERIFIED too: a board can be "correct" and still have a block 0.8 cm
    #: off its centre. Gates nothing, no state colour.
    max_cell_residual_cm: float | None = None
    #: ITEM 9 — the fused CORRECTION track's uncertainty across the coherent
    #: quiet window, for a MOVED / DISPLACED verdict: radial centroid
    #: dispersion, worst single-frame residual from the fused centre, and
    #: ``(frames_seen, window)``. Advisory; None when there is no track.
    localization_sigma_cm: float | None = None
    localization_residual_cm: float | None = None
    track_samples: tuple[int, int] | None = None

    @property
    def severity(self) -> str:
        """``amber`` / ``red`` / ``none``. A verdict NEVER produces LOCKED."""
        return self.verdict.severity if self.verdict is not None else "none"


class SupervisionModel(BaseModel):
    """What the observer says about the board — ONE field, four readers.

    The requirement that supervision "appears everywhere and stays in sync" is
    met **structurally, not by discipline**: the server publishes this object
    and every surface renders it. **No surface re-derives a verdict.** Four
    renderers of one field cannot disagree, so "sync" is not a thing anyone has
    to maintain — and DESIGN.md §8's "no client-side safety logic" holds by
    construction rather than by review.

    Read the `state`/`verdict` split carefully, because the UI depends on it:
    `BUSY`, `QUIET` and `NO_MEMORY` are **not faults** and take no state
    colour. BUSY is the normal condition for the whole of a build; colouring it
    amber would leave the console amber most of the time and kill the reserved
    palette. Not looking is not the same as finding something wrong.

    `NO_VISION` is also verdict-less and takes no state colour: the detector
    failed on this frame, or the analysed image aged out before its result
    landed. It is deliberately distinct from a clean board with nothing on it —
    the server must never turn "vision could not observe" into REMOVED — and
    from BUSY, so an operator can see the camera pipeline is the thing at fault.
    """

    state: Literal["NO_MEMORY", "NO_MAP", "NO_VISION", "WARMING", "BUSY",
                   "QUIET", "VERDICT"]
    verdict: Literal["VERIFIED", "NOT_DETECTED", "REMOVED",
                     "MOVED", "DISPLACED", "FOREIGN", "DISAGREES"] | None
    #: `amber` pauses the runner, `red` stops it. NEVER `LOCKED` — that means
    #: the claw's position is unknown and needs a human plus a service restart,
    #: and a verdict is a statement about the BOARD, not about the machine.
    severity: Literal["none", "amber", "red"]
    #: The cells the verdict names. For MOVED they are ordered [from, to]; for
    #: DISPLACED there is only the origin cell (the block landed on no site).
    cells: list[tuple[int, int]]
    mode: str
    #: Both sides, so a DISAGREES banner can show expected against observed.
    expected: list[tuple[int, int]]
    observed: list[tuple[int, int]]
    #: D6's refusals — expected top level at or above the ceiling. Drawn as a
    #: HATCH, never a colour: an absence of state must not take a state colour.
    unjudged: list[tuple[int, int]]
    #: Why it is not judging, when `state` is not VERDICT.
    reason: str | None
    judged_at_ms: int | None
    #: D12. The operator has dealt with this one, whether by putting the block
    #: back or by choosing not to. Cleared the moment the verdict changes.
    acknowledged: bool
    #: The operator CORRECTION action (`docs/features/correction-action.md`).
    #: `correctable` is True ONLY for a MOVED or DISPLACED verdict the claw may
    #: safely return: vertical mode, level 0, the block axis-aligned, no taller
    #: neighbour, the cell clear, the pick offset above the 0.5 cm floor, and —
    #: for DISPLACED — the detection consistent with one block and the cell it
    #: drifted toward not fouling the descent corridor (`rig.placement_geometry`).
    #: `False` the rest of the time, and `correction_reason` always says why in a
    #: sentence the UI shows verbatim. The browser NEVER acts on `pick_offset_cm`
    #: — the route re-derives everything server-side. Motion, server-authoritative.
    correctable: bool = False
    correction_reason: str | None = None
    correction_cell: tuple[int, int] | None = None
    correction_level: int | None = None
    pick_offset_cm: tuple[float, float] | None = None
    #: ADVISORY — cm the offending block is from its planned cell centre, for a
    #: MOVED / DISPLACED verdict. Display-only; it gates nothing and has no
    #: state colour. None for every other verdict and state.
    residual_cm: float | None = None
    #: ADVISORY — the worst on-cell drift anywhere on the board, cm. Present for
    #: VERIFIED too. Display-only; gates nothing, no state colour.
    max_cell_residual_cm: float | None = None
    #: ITEM 9 — the fused CORRECTION track's uncertainty over the coherent quiet
    #: window (audit §2.4 / §6.2): ``localization_sigma_cm`` is the radial
    #: centroid dispersion, ``localization_residual_cm`` the worst single-frame
    #: deviation from the fused centre, ``track_samples`` is ``[frames_seen,
    #: window]``. Advisory — the operator sees why a track is or is not trusted;
    #: gates nothing, no state colour. None for every non MOVED/DISPLACED case.
    localization_sigma_cm: float | None = None
    localization_residual_cm: float | None = None
    track_samples: tuple[int, int] | None = None


def supervision_model(reading, *, acknowledged: bool = False) -> SupervisionModel:
    """Fold one `SupervisionState` into the published object."""
    if reading is None:
        return SupervisionModel(
            state="NO_MEMORY", verdict=None, severity="none", cells=[],
            mode="", expected=[], observed=[], unjudged=[],
            reason="NO MEMORY — the board is only tracked from the first "
                   "build after a restart",
            judged_at_ms=None, acknowledged=False)
    verdict = reading.verdict
    assert reading.state in STATES, reading.state
    correction = getattr(reading, "correction", None)
    return SupervisionModel(
        state=reading.state,
        verdict=None if verdict is None else verdict.verdict,
        severity=reading.severity,
        cells=[] if verdict is None else [list(cell) for cell in verdict.cells],
        mode="" if verdict is None else verdict.mode,
        expected=[] if verdict is None else [list(c) for c in verdict.expected],
        observed=[] if verdict is None else [list(c) for c in verdict.observed],
        unjudged=[] if verdict is None else [list(c) for c in verdict.unjudged],
        reason=reading.reason,
        judged_at_ms=reading.judged_at_ms,
        acknowledged=acknowledged,
        correctable=correction is not None,
        correction_reason=getattr(reading, "correction_reason", None),
        # The cell the block BELONGS on — where the operator will see it land.
        correction_cell=None if correction is None else tuple(correction.place_cell),
        correction_level=None if correction is None else correction.place_level,
        pick_offset_cm=None if correction is None
        else (round(correction.dx_cm, 3), round(correction.dy_cm, 3)),
        residual_cm=getattr(reading, "residual_cm", None),
        max_cell_residual_cm=getattr(reading, "max_cell_residual_cm", None),
        localization_sigma_cm=getattr(reading, "localization_sigma_cm", None),
        localization_residual_cm=getattr(reading, "localization_residual_cm", None),
        track_samples=(tuple(reading.track_samples)
                       if getattr(reading, "track_samples", None) else None),
    )


def _neighbour_stack_above_0(top_levels: dict, cell) -> bool:
    """Does an orthogonally adjacent cell carry a block above level 0?

    A same-height (level 0) neighbour is NOT a descent hazard — the claw goes to
    level 0 beside it exactly as a normal `B` does. Only a neighbour STACK above
    level 0 fouls the 1.6 cm slot the claw descends (Stage 15 D6).
    """
    col, row = cell
    return any(top_levels.get((col + dx, row + dy), -1) >= 1
               for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))


def _drift_neighbour(cell, centre_cm, observed_cm):
    """The orthogonal neighbour a displaced block has slid toward.

    Chosen by the larger component of ``observed − centre`` — a single-cell
    displacement is essentially 1-D. Returns ``(col, row)``.
    """
    col, row = cell
    dx = observed_cm[0] - centre_cm[0]
    dy = observed_cm[1] - centre_cm[1]
    if abs(dx) >= abs(dy):
        return (col + (1 if dx >= 0 else -1), row)
    return (col, row + (1 if dy >= 0 else -1))


def correction_query_point(observation, verdict):
    """The single-frame cm point a MOVED / DISPLACED block sits at — the gap
    detection for DISPLACED, the wrong-cell detection for MOVED — or None when
    the verdict is not a correctable shape or the frame did not pin it down.

    `web/app.py` and `/api/supervision/correct` both use it to look the fused
    track up in the supervisor (`Supervisor.track_evidence_at`) at the same
    point `assess_frame_correction` derives internally, so the two never drift.
    """
    name = getattr(verdict, "verdict", None)
    if verdict is None or name not in ("MOVED", "DISPLACED"):
        return None
    if name == "DISPLACED":
        if len(verdict.cells) != 1 or len(observation.gap_points_cm) != 1:
            return None
        return observation.gap_points_cm[0]
    if len(verdict.cells) != 2:
        return None
    where = (int(verdict.cells[1][0]), int(verdict.cells[1][1]))
    return dict(observation.cell_points_cm).get(where)


def assess_frame_correction(*, ledger, workspace, observation, state: str,
                            verdict, mode: str, track=None,
                            require_track: bool = False):
    """Can the claw safely return this MOVED / DISPLACED block? Read-only.

    The single source of truth for the operator CORRECTION action: `web/app.py`
    calls it once per quiet frame to publish `correctable`, and
    `/api/supervision/correct` calls it AGAIN on the current frame before it
    moves anything — the published flag is never trusted, because a correction
    is motion (DESIGN.md §8). Nothing here touches the rig.

    `track` is the fused `rig.supervisor.TrackEvidence` for this block over the
    coherent quiet window (audit items 6 + 9), from `Supervisor.track_evidence_at`.
    With `require_track` the correction is REFUSED unless that track is settled,
    unambiguous and low-dispersion — no merged blob, no candidate switch, no
    arbitrary first-of-many pick — and its robust centre / angle / size then
    replace the single-frame values the pick offset is computed from. Without
    `track` (a bare unit test) the single-frame path is kept.

    Returns `(Correction | None, reason | None)`. `reason` is None only when the
    verdict is not one that could ever be corrected; otherwise it is a sentence
    saying either "the claw can move it back" or exactly why not.
    """
    if state != "VERDICT" or verdict is None:
        return None, None
    name = verdict.verdict
    if name not in ("MOVED", "DISPLACED"):
        return None, None

    grid = getattr(workspace, "mapped_grid", None)
    top_levels = ledger.expected_top_level(mode)
    occupied = set(observation.cells)
    cell_points = dict(observation.cell_points_cm)
    cell_order = [c for c, _ in observation.cell_points_cm]
    cell_angles = dict(zip(cell_order, observation.cell_angles_deg))
    cell_sizes = dict(zip(cell_order, observation.cell_sizes_cm))

    if name == "DISPLACED":
        if len(verdict.cells) != 1 or len(observation.gap_points_cm) != 1:
            return None, "the block's position in the frame could not be pinned down"
        plan_cell = (int(verdict.cells[0][0]), int(verdict.cells[0][1]))
        where_cell = plan_cell
        observed_cm = observation.gap_points_cm[0]
        angle_deg = (observation.gap_angles_deg[0]
                     if observation.gap_angles_deg else 0.0)
        measured_size_cm = (observation.gap_sizes_cm[0]
                            if observation.gap_sizes_cm else None)
    else:  # MOVED — cells are (from, to)
        if len(verdict.cells) != 2:
            return None, "the block's position in the frame could not be pinned down"
        plan_cell = (int(verdict.cells[0][0]), int(verdict.cells[0][1]))
        where_cell = (int(verdict.cells[1][0]), int(verdict.cells[1][1]))
        observed_cm = cell_points.get(where_cell)
        angle_deg = cell_angles.get(where_cell, 0.0)
        measured_size_cm = cell_sizes.get(where_cell)
        if observed_cm is None:
            return None, "the block's position in the frame could not be pinned down"

    if measured_size_cm in (None, (0.0, 0.0)):
        measured_size_cm = None

    # ITEM 6 + 9: gate on ONE stable, block-consistent track over the coherent
    # quiet window, and fuse the pick centroid / angle / size from it. `track`
    # is anchored at exactly the point derived above (see `correction_query_point`).
    loc_sigma_cm = loc_residual_cm = track_samples = angle_sigma_deg = None
    if require_track and (track is None or not track.ok):
        return None, (track.reason if track is not None else
                      "the block is not being tracked as one stable object "
                      "across the quiet window")
    if track is not None and track.ok:
        if track.centre_cm is not None:
            observed_cm = track.centre_cm
        angle_deg = track.angle_deg
        if track.size_cm and track.size_cm != (0.0, 0.0):
            measured_size_cm = track.size_cm
        loc_sigma_cm = round(track.centre_sigma_cm, 3)
        loc_residual_cm = round(track.max_residual_cm, 3)
        track_samples = (int(track.samples), int(track.window))
        angle_sigma_deg = round(track.angle_sigma_deg, 2)

    plan_level = top_levels.get(plan_cell)
    map_pick_centre_cm = None if grid is None else grid.cell_center_cm(*where_cell)

    if where_cell == plan_cell:
        pick_is_top = (plan_level is not None
                       and ledger.is_top_of_column(mode, *plan_cell, plan_level))
    else:
        pick_is_top = top_levels.get(where_cell, -1) <= 0

    drift_neighbour_occupied = False
    if map_pick_centre_cm is not None:
        drift_cell = _drift_neighbour(where_cell, map_pick_centre_cm, observed_cm)
        drift_neighbour_occupied = (drift_cell in occupied
                                    or top_levels.get(drift_cell, -1) >= 0)

    return _assess(
        verdict=name, mode=mode, plan_cell=plan_cell, plan_level=plan_level,
        where_cell=where_cell, observed_cm=observed_cm,
        map_pick_centre_cm=map_pick_centre_cm, angle_deg=float(angle_deg),
        plan_cell_clear=plan_cell not in occupied,
        taller_neighbour_pick=_neighbour_stack_above_0(top_levels, where_cell),
        taller_neighbour_place=_neighbour_stack_above_0(top_levels, plan_cell),
        pick_is_top_of_column=pick_is_top, grid=grid,
        measured_size_cm=measured_size_cm,
        drift_neighbour_occupied=drift_neighbour_occupied,
        localization_sigma_cm=loc_sigma_cm,
        localization_residual_cm=loc_residual_cm,
        track_samples=track_samples, angle_sigma_deg=angle_sigma_deg,
    )


def frame_residual_cm(*, observation, workspace, verdict, mode) -> float | None:
    """How far the offending block is from its planned cell centre, in cm.

    ADVISORY. Published on `SupervisionModel.residual_cm` so the operator sees
    "how far off"; it gates nothing. Set for a MOVED or DISPLACED verdict when
    the map can place both points in cm — for DISPLACED the block's gap
    detection, for MOVED the detection on the cell it landed on — else None.
    """
    if verdict is None or verdict.verdict not in ("MOVED", "DISPLACED"):
        return None
    grid = getattr(workspace, "mapped_grid", None)
    if grid is None or not verdict.cells:
        return None
    plan_cell = (int(verdict.cells[0][0]), int(verdict.cells[0][1]))

    if verdict.verdict == "DISPLACED":
        if len(observation.gap_points_cm) != 1:
            return None
        observed_cm = observation.gap_points_cm[0]
    else:  # MOVED — cells are (from, to); the block sits on the 'to' cell
        if len(verdict.cells) != 2:
            return None
        where = (int(verdict.cells[1][0]), int(verdict.cells[1][1]))
        observed_cm = dict(observation.cell_points_cm).get(where)
        if observed_cm is None:
            return None

    try:
        planned_centre = grid.cell_center_cm(*plan_cell)
    except ValueError:
        return None
    return round(_residual_cm(observed_cm, planned_centre), 2)


def worst_cell_residual_cm(observation) -> float | None:
    """The largest on-cell drift on the board, in cm — ADVISORY.

    Every occupied cell's block carries a `residual_cm` from `observe()`; this
    is the worst of them. Published so a VERIFIED board can still say "the worst
    block is 0.8 cm off". It gates nothing and takes no state colour. None when
    the map is off or no cell is occupied.
    """
    residuals = getattr(observation, "cell_residuals_cm", ())
    if not residuals:
        return None
    return round(max(value for _cell, value in residuals), 2)


class StateModel(BaseModel):
    """The complete client state for the operator console.

    Raw video never belongs here; Step 6 adds only lightweight drawing geometry
    for the browser-owned SVG overlay.

    The `build_*` block is the serial-driven build progress. It is the SAME
    facts the `build_step` events carry, folded into the snapshot so that a
    client which has just connected, or which missed events while its socket
    was down, starts from the truth rather than from blank. `serial_event_id`
    says which event the block was folded from: a client compares it with the
    progress it already has and keeps the newer of the two, so a state
    snapshot that overtook a phase event on the wire cannot roll the UI back.
    """

    mode: str
    cols: int
    rows: int
    #: The ACTIVE mode's live grid shift (`shiftX` / `shiftY`), in cm, as it
    #: stands on the board right now. `(0.0, 0.0)` is the shipped default; the
    #: Studio's running-bond courses and a manual re-registration both land
    #: here. The Twin draws its lattice from this, not from the build-time
    #: `config/rig.json`, so a shift set at runtime is not a lie on screen.
    shift_cm: tuple[float, float]
    #: `(cols, rows)` after the firmware's `gridColsNow()` / `gridRowsNow()`
    #: clipping — i.e. what a `B` can actually reach under `shift_cm`. Equal to
    #: `cols` / `rows` above (those are already clipped); published separately
    #: so the client can assert the two agree rather than assume it.
    reachable: tuple[int, int]
    #: `(cols, rows)` as asked for before any shift clipped them. Equal to
    #: `reachable` whenever no shift trims the grid; the Twin draws the
    #: difference as the amber out-of-reach cells.
    requested: tuple[int, int]
    calibrated: bool
    selected: tuple[int, int] | None
    command: str | None
    level: int
    build_state: Literal["READY", "RUNNING", "LOCKED"]
    locked_reason: str | None
    camera: Literal["LIVE", "STALE", "WAITING"]
    camera_age_ms: int | None
    last_result: Literal["placed", "rejected", "aborted"] | None
    last_result_reason: str | None
    gantry_connected: bool
    feeder_connected: bool
    hardware_ready: bool
    cell_phase: Literal["idle", "feeding", "staging", "ready_for_pick",
                        "awaiting_manual_close", "placing", "complete", "error"]
    feeder_transaction_id: int | None
    feeder_state: str | None
    feeder_error: str | None
    build_command_seq: int | None
    build_step: int | None
    build_total_steps: int | None
    build_phase: str | None
    build_phase_label: str | None
    build_phase_action: str | None
    build_phase_started_at: int | None
    #: The firmware's predicted duration for the phase in flight, in ms, or
    #: None when it did not say. A floor, not a schedule: a client may animate
    #: from it but must never let it assert that the phase finished.
    build_phase_eta_ms: int | None
    build_phase_status: str
    #: Phase 11's `status=done`: the jaws opened and the block is on the
    #: stack. NOT the same as placed — the command is still running and the
    #: rig still has to park. See `web/progress.py`.
    build_release_confirmed: bool
    serial_event_id: int
    #: M3a. One sentence about the placement that just settled — "verified in
    #: frame at [3,1]", "not detected at [2,2]", "unchecked — level 3 ...".
    #: The runner log row and the thesis run report's Markdown column both
    #: read it. None when no build has settled in this session.
    vision_verification: str | None
    #: M3b. The board's verdict, published whole. See `SupervisionModel`.
    supervision: SupervisionModel
    #: The outcome of the last operator CORRECTION action this session, or None.
    #: `{result: placed|rejected|aborted, reason, cell: [c,r], verdict}`. The
    #: runner shows it and resumes only after the board re-verifies (D12).
    last_correction: dict[str, Any] | None
    views: dict[str, bool]
    geometry: dict[str, Any] | None


def build_state(app) -> StateModel:
    """Read the owned services without opening any new hardware connection."""
    controller = app.state.controller
    job = app.state.job
    rig = app.state.rig
    frame = app.state.latest_frame
    # A mode latch invalidates the old frame's workspace immediately.  Wait for
    # the pipeline's next per-mode frame rather than pairing old geometry with
    # new coordinates for even one state message.
    if frame is not None and frame.grid_mode != rig.grid.mode:
        frame = None
    if (frame is not None
            and getattr(frame, "map_generation", None)
            != getattr(app.state.pipeline, "map_generation", None)):
        frame = None

    if job.running:
        build_state = "RUNNING"
    elif controller.locked:
        build_state = "LOCKED"
    else:
        build_state = "READY"

    if frame is None:
        camera = "WAITING"
        camera_age_ms = None
        calibrated = bool(app.state.pipeline.saved_workspace is not None)
    else:
        camera = "STALE" if frame.stale else "LIVE"
        camera_age_ms = max(0, round((time.monotonic() - frame.captured_at) * 1000))
        calibrated = frame.calibrated

    result = controller.last_result
    progress = app.state.progress.progress
    grid = rig.grid
    return StateModel(
        mode=grid.mode,
        cols=grid.cols,
        rows=grid.rows,
        shift_cm=(grid.shift_x_cm, grid.shift_y_cm),
        reachable=(grid.cols, grid.rows),
        requested=(grid.requested_cols or grid.cols, grid.requested_rows or grid.rows),
        calibrated=calibrated,
        selected=controller.selected,
        command=controller.command,
        level=controller.level,
        build_state=build_state,
        locked_reason=controller.locked_reason,
        camera=camera,
        camera_age_ms=camera_age_ms,
        last_result=str(result) if result is not None else None,
        last_result_reason=result.reason if result is not None else None,
        gantry_connected=rig.connected,
        feeder_connected=app.state.feeder.connected,
        hardware_ready=rig.connected and app.state.feeder.connected,
        cell_phase=app.state.cell_phase,
        feeder_transaction_id=app.state.feeder_transaction_id,
        feeder_state=app.state.feeder_state,
        feeder_error=app.state.feeder_error,
        **progress.as_state_fields(),
        vision_verification=getattr(app.state, "vision_verification", None),
        supervision=supervision_model(
            getattr(app.state, "supervision", None),
            acknowledged=bool(getattr(app.state, "supervision_acknowledged", False))),
        last_correction=getattr(app.state, "last_correction_result", None),
        views=dict(app.state.views),
        geometry=build_geometry(frame, controller.selected) if frame is not None else None,
    )

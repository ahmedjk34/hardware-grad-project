"""Server-authoritative Step 5 command routes for the operator console."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, root_validator

from rig import build_log
from rig.build_controller import BuildStateError
from rig.build_job import BUSY_MESSAGE
from rig.link import ABORTED, RigError
from rig.supervisor import TRACK_IDENTITY_MATCH_CM, observe, quiet_fraction
from web.state import (
    StateModel, assess_frame_correction, build_state, correction_query_point,
    correction_track_moved_cm, validate_correction_ticket,
)


router = APIRouter(prefix="/api", tags=["commands"])


class SelectRequest(BaseModel):
    x: float
    y: float
    img_w: float = Field(..., gt=0)
    img_h: float = Field(..., gt=0)


class AxisSelectRequest(BaseModel):
    axis: Literal["col", "row"]
    value: int


class LevelRequest(BaseModel):
    delta: int | None = None
    value: int | None = None

    @root_validator(skip_on_failure=True)
    def exactly_one_adjustment(cls, values):
        if (values.get("delta") is None) == (values.get("value") is None):
            raise ValueError("provide exactly one of delta or value")
        return values


class ModeRequest(BaseModel):
    mode: Literal["vertical", "horizontal"]


class ShiftRequest(BaseModel):
    """A runtime grid shift — an operator re-registration or a running-bond
    course change from the Studio. `x_cm` / `y_cm` are absolute, `+` away from
    each home switch (AGENTS.md Rule 0)."""

    mode: Literal["vertical", "horizontal"]
    x_cm: float
    y_cm: float


class ViewRequest(BaseModel):
    grid: bool | None = None
    detect: bool | None = None
    paper: bool | None = None
    overlay: bool | None = None


class BuildRequest(BaseModel):
    confirm: bool
    command: str


class ManualCloseRequest(BaseModel):
    confirm: bool = True


class AutoPickupRequest(BaseModel):
    """Arm or disarm camera-gated automatic pickup for an autonomous RUN."""

    enabled: bool


class CorrectRequest(BaseModel):
    """The operator CORRECTION action. `confirm` is the explicit consent the
    confirm dialog collects — a correction drives the claw into a finished
    structure, so it must never fire without it (DESIGN.md §8's superseded
    'no re-place button' rule now carries an operator-initiated carve-out)."""

    confirm: bool


#: Held while a mode latch is homing X/Y. Read as "the rig is moving" by
#: everything that must not send down the same cable meanwhile.
MODE_BUSY_MESSAGE = "a grid-mode latch is homing X/Y; wait for it to finish"


def _latching(app) -> bool:
    lock = getattr(app.state, "mode_latch_lock", None)
    return bool(lock is not None and lock.locked())


def require_mutable(app) -> None:
    """Reject actions that could queue behind motion or a locked machine."""
    if app.state.job.running:
        raise HTTPException(status_code=409, detail=BUSY_MESSAGE)
    if _latching(app):
        raise HTTPException(status_code=409, detail=MODE_BUSY_MESSAGE)
    if app.state.controller.locked:
        raise HTTPException(status_code=409,
                            detail=app.state.controller.locked_reason)


def require_fresh_camera(app):
    """Return the current frame only when it is safe to use for a target."""
    frame = app.state.latest_frame
    if frame is None:
        raise HTTPException(status_code=409, detail="camera frame is not ready")
    current_generation = getattr(app.state.pipeline, "map_generation", None)
    frame_generation = getattr(frame, "map_generation", current_generation)
    if frame_generation != current_generation:
        raise HTTPException(
            status_code=409,
            detail="camera evidence belongs to an older map; wait for analysis",
        )
    if frame.stale:
        raise HTTPException(status_code=409,
                            detail="camera frame is stale; selection is unsafe")
    return frame


def _state(app) -> StateModel:
    return build_state(app)


def _signal(app) -> None:
    app.state.signal_change()


@router.post("/select", response_model=StateModel)
async def select(request: SelectRequest, http: Request) -> StateModel:
    app = http.app
    require_mutable(app)
    frame = require_fresh_camera(app)
    width, height = frame.image_size
    point = request.x * width / request.img_w, request.y * height / request.img_h
    cell = frame.workspace.cell_at(point, frame.image_size)
    if cell is None:
        raise HTTPException(status_code=400, detail="outside the grid or in a gap")
    try:
        app.state.controller.select(cell)
    except BuildStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _signal(app)
    return _state(app)


@router.post("/select/axis", response_model=StateModel)
async def select_axis(request: AxisSelectRequest, http: Request) -> StateModel:
    app = http.app
    require_mutable(app)
    require_fresh_camera(app)
    cell = (request.value, 0) if request.axis == "col" else (0, request.value)
    try:
        app.state.controller.select(cell)
    except BuildStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _signal(app)
    return _state(app)


@router.post("/deselect", response_model=StateModel)
async def deselect(http: Request) -> StateModel:
    app = http.app
    require_mutable(app)
    app.state.controller.clear_selection()
    _signal(app)
    return _state(app)


@router.post("/level", response_model=StateModel)
async def level(request: LevelRequest, http: Request) -> StateModel:
    app = http.app
    require_mutable(app)
    try:
        if request.delta is not None:
            app.state.controller.adjust_level(request.delta)
        else:
            app.state.controller.set_level(request.value)
    except BuildStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _signal(app)
    return _state(app)


# A plain `def`, not `async def`, for the same reason every route in
# routes_calibration.py is one: selecting the horizontal grid homes X and Y,
# which is many seconds of BLOCKING serial motion. On the event loop that
# stalls everything the loop owns for the whole move — the WebSocket fan-out
# and its heartbeats, the MJPEG stream, and `_drive_pipeline`, which is the
# only thing that polls the build job and publishes `build_result`. The
# console then looks frozen mid-latch and catches up in a burst afterwards.
# FastAPI runs a sync handler on a worker thread instead.
@router.post("/mode", response_model=StateModel)
def mode(request: ModeRequest, http: Request) -> StateModel:
    app = http.app
    require_mutable(app)
    # The event loop used to serialise these by accident. Now that the latch
    # runs on a worker thread, take the lock explicitly: two overlapping
    # latches would interleave commands on one serial cable.
    lock = app.state.mode_latch_lock
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=MODE_BUSY_MESSAGE)
    try:
        app.state.controller.set_mode(request.mode, home_before_horizontal=True)
        # The controller latches the serial rig first; only then may the
        # camera switch its per-mode workspace/specification state.
        app.state.pipeline.set_grid_mode(request.mode, app.state.rig.grid)
    except (BuildStateError, RigError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        lock.release()
    _signal(app)
    return _state(app)


# Sync, on a worker thread, for the same reason as `/mode`: `set_shift` blocks
# on serial round-trips and `set_grid_mode` re-reads the workspace map from
# disk. A grid shift moves NOTHING on the rig (`applyGridShift` re-clips its
# reachable range in place, no homing, no `S` re-sent) — but it does change
# what a camera pixel maps to, so the saved workspace map is re-validated and,
# if it no longer matches this lattice, dropped with a rejection sentence.
@router.post("/shift", response_model=StateModel)
def shift(request: ShiftRequest, http: Request) -> StateModel:
    app = http.app
    require_mutable(app)
    rig = app.state.rig
    if request.mode != rig.grid.mode:
        raise HTTPException(
            status_code=409,
            detail=f"latch the {request.mode} grid before shifting it "
                   f"(the board is in the {rig.grid.mode} grid)",
        )
    lock = app.state.mode_latch_lock
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=MODE_BUSY_MESSAGE)
    try:
        rig.set_shift(x_cm=request.x_cm, y_cm=request.y_cm)
        # Re-sync the camera's per-mode state to the now-shifted grid and
        # re-validate the saved map against it. A mismatch leaves
        # `workspace_rejection` set and `calibrated` false rather than pairing
        # old pixels with new cells.
        app.state.pipeline.set_grid_mode(rig.grid.mode, rig.grid)
    except (RigError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        lock.release()
    _signal(app)
    return _state(app)


@router.post("/view", response_model=StateModel)
async def view(request: ViewRequest, http: Request) -> StateModel:
    """Display-only choices remain available while a build is moving."""
    app = http.app
    changes = request.dict(exclude_none=True)
    if "paper" in changes and changes["paper"] != app.state.views["paper"]:
        app.state.pipeline.paper.toggle()
    app.state.views.update(changes)
    _signal(app)
    return _state(app)


@router.post("/supervision/ack", response_model=StateModel)
async def acknowledge_supervision(http: Request) -> StateModel:
    """D12. The operator says "I have dealt with this", and the board is re-checked.

    Acknowledging means the operator has handled it — whether they put the
    block back or chose not to. It is deliberately **not** "ignore this cell
    from now on": a repair that is not re-verified is a guess with extra steps,
    and that applies just as much to a human's repair as to a machine's. So the
    acknowledgement clears the flag on THIS event only, and the supervisor's
    hysteresis is reset so the next verdict is built from fresh evidence rather
    than from frames gathered while the operator's hands were over the board.

    Available while a build is running, unlike every mutating route here: it
    moves nothing, and a verdict that paused the runner has to be dismissible
    before the runner can be allowed on. There is no "re-place it" button —
    automatic repair is M4, and a button implying the machine will fix it would
    be a lie about what is built.
    """
    app = http.app
    app.state.supervision_acknowledged = True
    supervisor = getattr(app.state, "supervisor", None)
    if supervisor is not None:
        supervisor.reset()
    build_log.placements.note("operator acknowledged the verdict")
    _signal(app)
    return _state(app)


def _verdict_signature(sv) -> tuple | None:
    if sv is None or getattr(sv, "verdict", None) is None:
        return None
    v = sv.verdict
    return (sv.state, v.verdict, tuple(v.cells))


# Sync, on a worker thread, for the same reason as `/mode` and `/shift`:
# `rig.replace_block()` blocks on ~30-60 s of serial motion. On the event loop
# that would stall the WebSocket fan-out, the MJPEG stream and `_drive_pipeline`.
# It holds `rig._inflight` for the whole move, so a `/api/build` arriving
# meanwhile gets RigBusy rather than interleaving on one cable.
@router.post("/supervision/correct", response_model=StateModel)
def correct_supervision(request: CorrectRequest, http: Request) -> StateModel:
    """The operator CORRECTION action — pick a MOVED / DISPLACED block up and
    set it on the cell it belongs on (`docs/features/correction-action.md`).

    This SUPERSEDES DESIGN.md §8's "no re-place button" and D11's "a verdict
    never moves the rig", with an operator-initiated carve-out: it is opt-in per
    press, confirm-gated, one attempt per verdict event, and it never fires
    automatically. AGENTS.md §2a permits a guarded direct-Mega call on an
    "explicit calibration/commissioning path where a person has staged the
    block" — a CORRECTION is exactly that, the block already being on the board.

    Server-authoritative: the published `correctable` flag is NOT trusted. This
    re-runs `assess_frame_correction` on the CURRENT frame and refuses, with the
    reason, if anything has changed. A `HELD`/`aborted` result LOCKS the
    controller (the claw may still hold a block) — the one case where a
    correction is allowed to lock, because it is a statement about the MACHINE,
    not the board.
    """
    app = http.app
    if not request.confirm:
        raise HTTPException(status_code=400, detail="correction requires confirm=true")
    require_mutable(app)
    frame = require_fresh_camera(app)
    rig = app.state.rig
    if not rig.connected:
        raise HTTPException(status_code=409,
                            detail="Mega gantry must be connected for a correction")
    if not bool(getattr(frame, "calibrated", False)):
        raise HTTPException(status_code=409,
                            detail="no calibrated workspace map; a correction needs one")

    if not bool(getattr(frame, "analysis_ok", True)):
        raise HTTPException(
            status_code=409,
            detail="vision is not returning a usable reading right now; "
                   "wait for it to recover")

    supervisor = getattr(app.state, "supervisor", None)
    if supervisor is None:
        raise HTTPException(status_code=409, detail="the observer is not ready")

    # ITEM 3: the decision and the `consumed` write are one critical section, so
    # a second press or a concurrent dispatch cannot both validate the same
    # ticket. A mode/map/epoch change that lands mid-validation is caught by
    # `validate_correction_ticket` re-reading live state inside the lock.
    lock = getattr(app.state, "correction_lock", None)
    if lock is None or not lock.acquire(blocking=False):
        raise HTTPException(status_code=409,
                            detail="a correction is already being dispatched")
    try:
        # A grid-mode / shift latch that started between `require_mutable` and
        # here would be homing X/Y on the same cable. Re-check inside the lock.
        if _latching(app):
            raise HTTPException(status_code=409, detail=MODE_BUSY_MESSAGE)
        sv = getattr(app.state, "supervision", None)
        signature = _verdict_signature(sv)
        if signature is None:
            raise HTTPException(status_code=409, detail="no verdict to correct")
        if getattr(app.state, "correction_attempted_signature", None) == signature:
            raise HTTPException(
                status_code=409,
                detail="a correction has already been attempted for this verdict; "
                       "dismiss it and let the board re-check")

        # ITEM 3: the one-shot coherent ticket, checked BEFORE the re-assessment
        # so a consumed / stale / raced ticket refuses regardless of what the
        # current frame shows. `_supervise` mints it while the correctable
        # verdict is published; its whole bundle — verdict signature, map
        # generation, grid mode, board epoch, source sequence — must still equal
        # live state, or a race (mode/map/epoch change, stale analysis, verdict
        # change, replay) is refused with no `P` sent.
        ticket = getattr(app.state, "correction_ticket", None)
        ok, why = validate_correction_ticket(app, ticket, frame, sv, signature)
        if not ok:
            raise HTTPException(status_code=409, detail=why)

        observation = observe(frame.detections, frame.workspace, frame.image_size)
        # ITEM 6 + 9: re-check on the SAME coherent quiet-window track the driver
        # has been accumulating — the block must still be one stable, unambiguous,
        # block-consistent track before a byte is sent, and the pick centroid is
        # the fused one, not this frame's first candidate.
        query_point = correction_query_point(observation, sv.verdict)
        track = (supervisor.track_evidence_at(query_point)
                 if query_point is not None else None)
        correction, reason = assess_frame_correction(
            ledger=app.state.ledger, workspace=frame.workspace,
            observation=observation, state=sv.state, verdict=sv.verdict,
            mode=frame.grid_mode, track=track, require_track=True)
        if correction is None:
            raise HTTPException(status_code=409,
                                detail=reason or "this block cannot be corrected")

        # The authorisation must correspond to the evidence that still exists:
        # the freshly re-derived motion and the fused track centre both have to
        # match what the ticket was affirmed against, or the block has moved
        # between the reading and this confirmation.
        if tuple(correction.command_args) != tuple(ticket.command_args):
            raise HTTPException(
                status_code=409,
                detail="the block moved since the correction was offered; "
                       "dismiss the verdict and let the board re-check")
        moved = correction_track_moved_cm(ticket, track)
        if moved is not None and moved > TRACK_IDENTITY_MATCH_CM:
            raise HTTPException(
                status_code=409,
                detail=f"the tracked block shifted {moved:.2f} cm since the "
                       f"correction was offered; let the board re-check")

        # Quiet, right now, on this exact frame — not a settled verdict from an
        # older one. `supervision_baseline` is the frame `_supervise` last
        # accepted; a hand entering between them makes this fraction non-quiet.
        baseline = getattr(app.state, "supervision_baseline", None)
        if not supervisor.is_quiet(quiet_fraction(frame.view, baseline)):
            raise HTTPException(
                status_code=409,
                detail="the scene is not still enough to correct; "
                       "wait for it to settle")

        # Consume BEFORE the move: a retry during it, a replay, or a
        # decision-to-motion race now all send nothing. `_note_supervision`
        # drops the ticket and this signature when the reading changes.
        ticket.consumed = True
        app.state.correction_attempted_signature = signature
    finally:
        lock.release()

    pc, pr, pl, dx, dy, qc, qr, ql = correction.command_args
    build_log.placements.note(
        f"operator CORRECTION: pick [{pc},{pr}] L{pl} nudge ({dx:.2f},{dy:.2f}) "
        f"-> place [{qc},{qr}] L{ql}")

    try:
        result = rig.replace_block(pc, pr, pl, dx, dy, qc, qr, ql)
    except RigError as exc:
        app.state.controller.locked_reason = (
            f"serial/build state unknown after a correction: {exc}; "
            "inspect the rig and restart")
        _signal(app)
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    app.state.last_correction_result = {
        "result": str(result), "reason": result.reason,
        "cell": list(correction.place_cell), "verdict": correction.verdict,
    }
    if str(result) == ABORTED or result.needs_a_human:
        # The one case a correction locks: the claw may be holding a block at an
        # unknown position. That is a MACHINE fact, not a board verdict.
        app.state.controller.locked_reason = (
            result.reason or "correction aborted; the claw may be holding a block")
    else:
        # D12: re-verify. Drop the hysteresis so the next quiet window judges
        # the board fresh, not on frames taken while the arm was over it.
        if supervisor is not None:
            supervisor.reset()
        app.state.supervision_acknowledged = False
    build_log.placements.note(f"correction result: {result} ({result.reason})")
    _signal(app)
    return _state(app)


@router.post("/build", response_model=StateModel)
async def build(request: BuildRequest, http: Request) -> StateModel:
    app = http.app
    require_mutable(app)
    require_fresh_camera(app)
    if not app.state.rig.connected:
        raise HTTPException(
            status_code=409,
            detail="Mega gantry must be connected before build",
        )
    if not request.confirm:
        raise HTTPException(status_code=400, detail="build requires confirm=true")
    if request.command != app.state.controller.command:
        raise HTTPException(status_code=400,
                            detail="command does not match the current selection")
    controller = app.state.controller
    try:
        app.state.job.start()
    except BuildStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Open this build's section in logs/build.log now that the job is running:
    # this timestamp is the stopwatch zero for every phase that follows off the
    # wire (RECV, the fourteen STEPs, the terminal ack).
    build_log.build.build_requested(
        request.command, selection=controller.selected,
        level=controller.level, mode=controller.mode,
    )
    build_log.build.job_started()
    # AGENTS.md §2a: an autonomous RUN closes the pickup claw itself. The
    # decision is latched HERE, while the claw is still parked and the overhead
    # camera has a clean view of the feeder — not at `await_manual_close`, where
    # the open claw sits over the block and hides it. `_auto_pickup` acts on
    # this latch. Feeder empty now, or `auto_pickup` not armed -> no latch ->
    # the firmware waits for the manual `C`.
    app.state.auto_close_pending = bool(
        getattr(app.state, "auto_pickup", False)
        and getattr(app.state, "feeder_block_present", False))
    if app.state.auto_close_pending:
        build_log.build.note("auto-pickup: block confirmed at the feeder; "
                             "will close the claw automatically")
    # The console's own half of the progress story: the command is ACCEPTED.
    # Nothing has moved and nothing may be claimed yet - the board has not even
    # said RECV. Everything after this comes off the wire.
    app.state.progress.command_accepted(app.state.hub.last_event_id)
    _signal(app)
    return _state(app)


@router.post("/manual-close", response_model=StateModel)
async def manual_close(request: ManualCloseRequest, http: Request) -> StateModel:
    """Close a manual pickup only after the firmware reports it is down/open."""
    app = http.app
    if not request.confirm:
        raise HTTPException(status_code=400, detail="manual close requires confirm=true")
    if not app.state.job.running or app.state.cell_phase != "awaiting_manual_close":
        raise HTTPException(status_code=409, detail="the claw is not waiting for manual alignment")
    try:
        app.state.pickup.close_manual_pick()
    except (BuildStateError, RigError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _signal(app)
    return _state(app)


@router.post("/auto-pickup", response_model=StateModel)
async def set_auto_pickup(request: AutoPickupRequest, http: Request) -> StateModel:
    """Arm / disarm camera-gated automatic pickup (AGENTS.md §2a).

    When armed, the driver loop closes the claw on its own once the feeder
    detector confirms a block is staged at ``[0,0]`` and the firmware has
    reached ``await_manual_close``. It sends the same single ``C`` byte the
    manual button does and nothing else; ``feeder_has_block`` fails closed, so
    when it cannot see a block the firmware just keeps waiting exactly as a
    manual pickup would. Only the RUN run-style arms this; STEP, DRY and the
    single-build console never do, and the manual CLOSE CLAW button stays live
    as the override in every style.

    Moves nothing itself, so it is not behind :func:`require_mutable` — it has
    to be armable at the start of a RUN before the first block and re-settable
    while one is in flight.
    """
    app = http.app
    app.state.auto_pickup = bool(request.enabled)
    build_log.build.note(
        f"auto-pickup {'armed' if request.enabled else 'disarmed'}")
    _signal(app)
    return _state(app)


@router.post("/session/reset", response_model=StateModel)
async def reset_session(http: Request) -> StateModel:
    """CLEAR BUILD STATE — start over on a board nobody has looked at yet.

    The operator has taken the blocks off the table (or is about to) and wants
    the next build judged on its own evidence. Clearing the runner panel alone
    was never enough: the as-built ledger, the observer's hysteresis and the
    published verdict all live here, so the console would sit on a cleared
    panel while supervision went on naming cells from the build before it.

    What this does is exactly what a gantry reboot does to the memory, minus
    the reboot: :meth:`PlacementLedger.new_board_epoch` retires every existing
    placement, and the supervisor's histories go through its one reset
    primitive. The rows are KEPT — the ledger is the append-only thesis record
    — but no reader answers for them any more, so the next verdict is built
    from frames gathered after this moment and from nothing else.

    **It moves nothing and it sends no serial line.** It is refused, like every
    other mutating route, while a job is running or a mode latch is homing —
    and while the session is LOCKED, because a lock means the claw's position
    is unknown and forgetting the board would not make that any less true.
    That is a human and a service restart, exactly as before.
    """
    app = http.app
    require_mutable(app)

    ledger = getattr(app.state, "ledger", None)
    if ledger is not None and ledger.has_memory():
        ledger.new_board_epoch()
    supervisor = getattr(app.state, "supervisor", None)
    if supervisor is not None:
        supervisor.reset()

    # The published verdict and every input it was derived from. Dropping the
    # baseline as well as the reading matters: D5's frame difference against a
    # frame of the OLD board would read as motion and hold the next window BUSY.
    app.state.supervision = None
    app.state.supervision_signature = None
    app.state.supervision_baseline = None
    app.state.supervision_sequence = None
    app.state.supervision_result_id = None
    app.state.supervision_acknowledged = False
    #: The armed per-build check and its one sentence.
    app.state.pending_check = None
    app.state.vision_verification = None
    # The correction authorisation is scoped to a verdict that no longer
    # exists. Leaving the ticket would leave a one-shot pick-and-place armed
    # against a board this route has just declared unknown.
    app.state.correction_ticket = None
    app.state.correction_attempted_signature = None
    app.state.last_correction_result = None

    # The console's own read-outs: the phase bar, the last result banner and
    # the selection. None of these is authority — they are what the operator
    # sees — but a cleared session showing the previous build's `placed` is
    # the same half-truth the tracker exists to prevent.
    app.state.progress.reset()
    controller = app.state.controller
    controller.clear_selection()
    controller.last_result = None
    app.state.cell_phase = "idle"
    # A cleared session is starting over; nothing autonomous should carry over.
    app.state.auto_pickup = False
    app.state.auto_close_pending = False
    app.state.awaiting_close_since = None

    build_log.placements.note("operator cleared the build state — new board epoch")
    build_log.build.note("session reset: ledger epoch advanced, supervision dropped")
    _signal(app)
    return _state(app)

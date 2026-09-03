"""Server-authoritative Step 10 workspace calibration routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from dataclasses import replace

from camera.gridded_camera_feed import paper_workspace_map
from rig.block_calibration import (BlockCalibrationAborted,
                                   BlockCalibrationError,
                                   BlockCalibrationRun)
from rig.workspace import CORNER_NAMES, WorkspaceMap
from vision.block_grid import (DEFAULT_OBSERVATIONS, MIN_OBSERVATIONS,
                               BlockGridError)
from vision.color_grid import ColorGridError
from web.routes_command import require_fresh_camera, require_mutable
from web.state import build_state

router = APIRouter(prefix="/api/calibration", tags=["calibration"])

class CornerRequest(BaseModel):
    x: float
    y: float
    img_w: float = Field(..., gt=0)
    img_h: float = Field(..., gt=0)

class PaperRequest(BaseModel):
    selection: int | None = Field(None, ge=0)

def _reply(app):
    points = app.state.calibration_points
    return {"count": len(points), "next": CORNER_NAMES[len(points)] if len(points) < 4 else None,
            "corners": [list(point) for point in points], "state": build_state(app).dict()}

@router.post("/start")
async def start(http: Request):
    app = http.app; require_mutable(app); require_fresh_camera(app)
    app.state.calibration_points = []
    app.state.controller.clear_selection(); app.state.signal_change()
    return _reply(app)

@router.post("/corner")
async def corner(request: CornerRequest, http: Request):
    app = http.app; require_mutable(app); frame = require_fresh_camera(app)
    if len(app.state.calibration_points) >= 4: raise HTTPException(400, "four corners are already collected")
    width, height = frame.image_size
    app.state.calibration_points.append((request.x * width / request.img_w, request.y * height / request.img_h))
    app.state.signal_change(); return _reply(app)

@router.post("/undo")
async def undo(http: Request):
    app = http.app; require_mutable(app); require_fresh_camera(app)
    if app.state.calibration_points: app.state.calibration_points.pop()
    app.state.signal_change(); return _reply(app)

@router.post("/cancel")
async def cancel(http: Request):
    app = http.app; require_mutable(app); require_fresh_camera(app)
    app.state.calibration_points = []; app.state.signal_change(); return _reply(app)

@router.post("/save")
async def save(http: Request):
    app = http.app; require_mutable(app); frame = require_fresh_camera(app)
    if len(app.state.calibration_points) != 4: raise HTTPException(400, "collect exactly four corners before saving")
    try:
        workspace = WorkspaceMap.from_grid(app.state.pipeline.grid, app.state.calibration_points, frame.image_size, app.state.pipeline.projection)
        workspace.save(app.state.pipeline.workspace_map_path)
        app.state.pipeline.set_workspace(workspace)
    except (OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    app.state.latest_frame = replace(frame, workspace=workspace, calibrated=True)
    app.state.calibration_points = []; app.state.controller.clear_selection(); app.state.signal_change()
    return build_state(app)

@router.post("/paper")
async def paper(request: PaperRequest, http: Request):
    app = http.app; require_mutable(app); frame = require_fresh_camera(app)
    selection = app.state.pipeline.paper.selection if request.selection is None else request.selection
    try:
        workspace, _found = paper_workspace_map(frame.view, app.state.pipeline.paper.spec, app.state.pipeline.grid, app.state.pipeline.projection, "firmware", selection)
        workspace.save(app.state.pipeline.workspace_map_path)
        app.state.pipeline.set_workspace(workspace)
    except (ColorGridError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    app.state.latest_frame = replace(frame, workspace=workspace, calibrated=True)
    app.state.controller.clear_selection(); app.state.signal_change(); return build_state(app)


# --------------------------------------------------------------------------- #
# Placed-block calibration - the primary path.
#
# The corner and sheet routes above measure the camera against something an
# operator positioned: four clicks, or a printed sheet that is then *assumed*
# to sit where the machine's cells are. These routes have the rig place a block
# on a cell it was told, so the correspondence is labelled at the source and
# the whole class of "does the paper agree with the firmware" question does not
# arise. See vision/block_grid.py for why that matters.
#
# Every route here is a plain `def`, not `async def`: one step is a full
# pick-and-place, minutes of blocking serial motion, and FastAPI runs sync
# handlers on a worker thread instead of stalling the event loop the camera
# stream shares.
# --------------------------------------------------------------------------- #

class BlockStartRequest(BaseModel):
    count: int = Field(DEFAULT_OBSERVATIONS, ge=MIN_OBSERVATIONS, le=24)
    #: Drop this many outermost rings of cells. Raise it to 1 when the camera
    #: is framed tightly enough that a block on the outer row is cut off by the
    #: frame edge - locate_block refuses those, correctly, because a clipped
    #: block's centroid is not its centre.
    inset: int = Field(0, ge=0, le=3)
    cells: list[tuple[int, int]] | None = None


class BlockCellRequest(BaseModel):
    cell: tuple[int, int]


def _block_run(app):
    run = getattr(app.state, "block_calibration", None)
    if run is None:
        raise HTTPException(409, "no placed-block calibration is in progress; "
                                 "POST /api/calibration/block/start first")
    return run


def _block_reply(app, run):
    status = run.status()
    report = status.report
    return {
        "mode": status.mode,
        "planned": [list(cell) for cell in status.planned],
        "observed": [list(cell) for cell in status.observed],
        "remaining": [list(cell) for cell in status.remaining],
        "ready": status.ready,
        "reasons": list(status.reasons),
        "started": run.started,
        "finished_reason": run.finished_reason,
        "summary": status.describe(),
        "report": None if report is None else {
            "observations": report.observations,
            "mean_residual_px": round(report.mean_residual_px, 3),
            "max_residual_px": round(report.max_residual_px, 3),
            "worst_cell": None if report.worst_cell is None else list(report.worst_cell),
            "short_pitch_px": round(report.short_pitch_px, 2),
            "size_agreement": round(report.size_agreement, 3),
            "max_bearing_error_deg": round(report.max_bearing_error_deg, 2),
            "residuals": {f"{col},{row}": round(value, 3)
                          for (col, row), value in report.residuals.items()},
        },
        "state": build_state(app).dict(),
    }


@router.post("/block/start")
def block_start(request: BlockStartRequest, http: Request):
    """Plan the cells and record the empty workspace as the baseline.

    The build area must be **clear** when this is called: a block already on
    the table is in the baseline, so it is invisible to the frame differencing
    and can only be found by shape, which is the weaker path.
    """
    app = http.app
    require_mutable(app)
    require_fresh_camera(app)
    lock = app.state.block_calibration_lock
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "a calibration step is already running")
    try:
        run = BlockCalibrationRun(
            app.state.rig,
            lambda: require_fresh_camera(app).view,
            grid=app.state.pipeline.grid,
            cells=[tuple(cell) for cell in request.cells] if request.cells else None,
            count=request.count,
            inset=request.inset,
        )
        run.start()
    except (BlockGridError, BlockCalibrationError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        lock.release()
    app.state.block_calibration = run
    app.state.signal_change()
    return _block_reply(app, run)


@router.post("/block/step")
def block_step(http: Request):
    """Place the next planned block and observe where it landed.

    Blocks for the length of one pick-and-place. The lock is what stops two
    impatient clicks from issuing two builds at a rig that is deaf to the
    second one.
    """
    app = http.app
    run = _block_run(app)
    require_mutable(app)
    lock = app.state.block_calibration_lock
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "a calibration step is already running")
    try:
        outcome = run.step()
    except BlockCalibrationAborted as exc:
        # The claw may still be holding a block. Lock the whole console, not
        # just this run: nothing else should move until a human has looked.
        app.state.controller.locked_reason = str(exc)
        app.state.signal_change()
        raise HTTPException(409, str(exc)) from exc
    except BlockCalibrationError as exc:
        app.state.signal_change()
        raise HTTPException(400, str(exc)) from exc
    finally:
        lock.release()
    app.state.signal_change()
    reply = _block_reply(app, run)
    reply["last_step"] = {
        "cell": list(outcome.cell),
        "residual_px": None if outcome.residual_px is None
        else round(outcome.residual_px, 3),
        "summary": outcome.describe(),
    }
    return reply


@router.post("/block/undo")
def block_undo(request: BlockCellRequest, http: Request):
    """Forget one placement without touching the rig.

    The block stays on the table; only the observation is dropped. Use it when
    a placement was seen but landed visibly wrong, then re-run that cell.
    """
    app = http.app
    run = _block_run(app)
    run.session.drop(tuple(request.cell))
    app.state.signal_change()
    return _block_reply(app, run)


@router.post("/block/cancel")
def block_cancel(http: Request):
    """Abandon the run. Blocks already placed stay where they are."""
    app = http.app
    app.state.block_calibration = None
    app.state.signal_change()
    return {"cancelled": True, "state": build_state(app).dict()}


@router.post("/block/save")
def block_save(http: Request):
    """Fit, gate and write the workspace map.

    The gates live in :func:`vision.block_grid.fit_block_grid` and are not
    negotiable from here: a refused fit is a 400 carrying the sentence that
    says which check failed.
    """
    app = http.app
    run = _block_run(app)
    frame = require_fresh_camera(app)
    try:
        workspace = run.workspace_map(frame.image_size,
                                      app.state.pipeline.projection)
        workspace.save(app.state.pipeline.workspace_map_path)
        app.state.pipeline.set_workspace(workspace)
    except (ColorGridError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    app.state.latest_frame = replace(frame, workspace=workspace, calibrated=True)
    app.state.block_calibration = None
    app.state.controller.clear_selection()
    app.state.signal_change()
    return build_state(app)


@router.get("/block/status")
def block_status(http: Request):
    app = http.app
    run = getattr(app.state, "block_calibration", None)
    if run is None:
        return {"active": False, "state": build_state(app).dict()}
    return {"active": True, **_block_reply(app, run)}

"""Server-authoritative Step 5 command routes for the operator console."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, root_validator

from rig import build_log
from rig.build_controller import BuildStateError
from rig.build_job import BUSY_MESSAGE
from rig.link import RigError
from web.state import StateModel, build_state


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


class ViewRequest(BaseModel):
    grid: bool | None = None
    detect: bool | None = None
    paper: bool | None = None
    overlay: bool | None = None


class BuildRequest(BaseModel):
    confirm: bool
    command: str


def require_mutable(app) -> None:
    """Reject actions that could queue behind motion or a locked machine."""
    if app.state.job.running:
        raise HTTPException(status_code=409, detail=BUSY_MESSAGE)
    if app.state.controller.locked:
        raise HTTPException(status_code=409,
                            detail=app.state.controller.locked_reason)


def require_fresh_camera(app):
    """Return the current frame only when it is safe to use for a target."""
    frame = app.state.latest_frame
    if frame is None:
        raise HTTPException(status_code=409, detail="camera frame is not ready")
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


@router.post("/mode", response_model=StateModel)
async def mode(request: ModeRequest, http: Request) -> StateModel:
    app = http.app
    require_mutable(app)
    try:
        app.state.controller.set_mode(request.mode, home_before_horizontal=True)
        # The controller latches the serial rig first; only then may the
        # camera switch its per-mode workspace/specification state.
        app.state.pipeline.set_grid_mode(request.mode, app.state.rig.grid)
    except (BuildStateError, RigError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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


@router.post("/build", response_model=StateModel)
async def build(request: BuildRequest, http: Request) -> StateModel:
    app = http.app
    require_mutable(app)
    require_fresh_camera(app)
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
    # The console's own half of the progress story: the command is ACCEPTED.
    # Nothing has moved and nothing may be claimed yet - the board has not even
    # said RECV. Everything after this comes off the wire.
    app.state.progress.command_accepted(app.state.hub.last_event_id)
    _signal(app)
    return _state(app)

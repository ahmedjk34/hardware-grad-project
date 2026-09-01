"""Server-authoritative Step 10 workspace calibration routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from dataclasses import replace

from camera.gridded_camera_feed import paper_workspace_map
from rig.workspace import CORNER_NAMES, WorkspaceMap
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

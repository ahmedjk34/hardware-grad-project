"""Small, frame-free state snapshots for the web operator console."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel

from web.geometry import build_geometry


class StateModel(BaseModel):
    """The complete client state for the operator console.

    Raw video never belongs here; Step 6 adds only lightweight drawing geometry
    for the browser-owned SVG overlay.
    """

    mode: str
    cols: int
    rows: int
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
    return StateModel(
        mode=rig.grid.mode,
        cols=rig.grid.cols,
        rows=rig.grid.rows,
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
        views=dict(app.state.views),
        geometry=build_geometry(frame, controller.selected) if frame is not None else None,
    )

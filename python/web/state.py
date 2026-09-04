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
                        "placing", "complete", "error"]
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
    progress = app.state.progress.progress
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
        gantry_connected=rig.connected,
        feeder_connected=app.state.feeder.connected,
        hardware_ready=rig.connected and app.state.feeder.connected,
        cell_phase=app.state.cell_phase,
        feeder_transaction_id=app.state.feeder_transaction_id,
        feeder_state=app.state.feeder_state,
        feeder_error=app.state.feeder_error,
        **progress.as_state_fields(),
        views=dict(app.state.views),
        geometry=build_geometry(frame, controller.selected) if frame is not None else None,
    )

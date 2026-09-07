"""Small, frame-free state snapshots for the web operator console."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Literal

from pydantic import BaseModel

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
    """

    state: Literal["NO_MEMORY", "NO_MAP", "WARMING", "BUSY", "QUIET", "VERDICT"]
    verdict: Literal["VERIFIED", "NOT_DETECTED", "REMOVED",
                     "MOVED", "FOREIGN", "DISAGREES"] | None
    #: `amber` pauses the runner, `red` stops it. NEVER `LOCKED` — that means
    #: the claw's position is unknown and needs a human plus a service restart,
    #: and a verdict is a statement about the BOARD, not about the machine.
    severity: Literal["none", "amber", "red"]
    #: The cells the verdict names. For MOVED they are ordered [from, to].
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
    )


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
    #: M3a. One sentence about the placement that just settled — "verified in
    #: frame at [3,1]", "not detected at [2,2]", "unchecked — level 3 ...".
    #: The runner log row and the thesis run report's Markdown column both
    #: read it. None when no build has settled in this session.
    vision_verification: str | None
    #: M3b. The board's verdict, published whole. See `SupervisionModel`.
    supervision: SupervisionModel
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
        views=dict(app.state.views),
        geometry=build_geometry(frame, controller.selected) if frame is not None else None,
    )

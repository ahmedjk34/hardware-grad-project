"""M2's wiring: the observer inside `_drive_pipeline`, and the three refusals.

`test_supervisor.py` covers the classifier and `test_supervisor_frames.py`
replays the rig traces through it. Neither of them knows the server exists.
This file covers the seam — what `web/app.py` hands the supervisor, and the
refusals it makes on the supervisor's behalf because they are facts about the
server's plumbing rather than about the board.

`_supervise` is exercised directly against a fake app rather than through a
live camera: the frames it needs are three numpy arrays and the decisions it
makes are all visible in `app.state.supervision`. The lifespan test at the
bottom is the one that proves the real wiring exists.

**There is no camera on the dev desktop.** Everything here runs on synthetic
arrays through the mock pipeline; the numbers that matter — whether the quiet
window actually opens on the rig's own frames — are Gate 0's, in
`docs/features/placement-supervision-progress.md` §1.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import numpy as np
from asgi_lifespan import LifespanManager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import SETTINGS_PATH  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from rig.link import PLACED, BuildResult  # noqa: E402
from rig.placement_ledger import PlacementLedger  # noqa: E402
from rig.supervisor import (  # noqa: E402
    PARKED_CELL_PHASES, QUIET_DIFF_FRACTION, Supervisor, quiet_fraction,
)
from rig.workspace import WorkspaceMap  # noqa: E402
from web.app import ConsoleAppOptions, _supervise, create_app  # noqa: E402


def mock_settings(tmp_path: Path) -> Path:
    data = json.loads(SETTINGS_PATH.read_text())
    data["capture"].update({"width": 640, "height": 480})
    data["correction"]["enabled"] = False
    data["framing"] = {"crops": [], "zoom": 1.0, "pan": [0.5, 0.5]}
    path = tmp_path / "camera_settings.json"
    path.write_text(json.dumps(data))
    return path


SIZE = (320, 240)
GRID = MachineGrid.from_config(mode="vertical")
MAP = WorkspaceMap.from_grid(GRID, ((0, 0), (320, 0), (320, 240), (0, 240)), SIZE)


class FakeDetection:
    def __init__(self, center):
        self.center = center


def at_cell(col, row):
    x_cm, y_cm = GRID.cell_center_cm(col, row)
    return FakeDetection(MAP.pixel_at(x_cm / GRID.workspace_width_cm,
                                      y_cm / GRID.workspace_height_cm, SIZE))


def view(fill: int = 40) -> np.ndarray:
    """One synthetic capture. Flat, so two of them differ by exactly `fill`."""
    frame = np.full((SIZE[1], SIZE[0], 3), fill, dtype=np.uint8)
    frame.flags.writeable = False
    return frame


def frame_at(sequence, *, cells=((1, 1), (2, 1)), fill=40, calibrated=True,
             mode="vertical"):
    return SimpleNamespace(
        view=view(fill), sequence=sequence, image_size=SIZE,
        detections=tuple(at_cell(col, row) for col, row in cells),
        workspace=MAP, calibrated=calibrated, grid_mode=mode, stale=False)


def fake_app(*, cells=((1, 1), (2, 1)), cell_phase="idle", locked=False,
             mode="vertical"):
    """Everything `_supervise` touches on `app.state`, and nothing else."""
    ledger = PlacementLedger()
    for col, row in cells:
        ledger.append("vertical", col, row, 0, BuildResult(PLACED))
    state = SimpleNamespace(
        ledger=ledger,
        # settle_n=1 keeps these tests about the WIRING; the N-of-M behaviour
        # itself is measured and asserted in the two supervisor suites.
        supervisor=Supervisor(quiet_diff_fraction=QUIET_DIFF_FRACTION,
                              settle_n=1, settle_m=1),
        supervision=None, supervision_signature=None,
        supervision_baseline=None, supervision_sequence=None,
        cell_phase=cell_phase,
        controller=SimpleNamespace(locked=locked),
        rig=SimpleNamespace(grid=SimpleNamespace(mode=mode)),
    )
    return SimpleNamespace(state=state)


def drive(app, frames, *, running=False):
    """Push frames through `_supervise` on a real loop and real executor."""
    job = SimpleNamespace(running=running)

    async def scenario():
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            seen = []
            for frame in frames:
                await _supervise(app, frame, job, loop, executor)
                seen.append(app.state.supervision)
            return seen

    return asyncio.run(scenario())


# --- the quiet gate, which is the only numpy in the supervisor ------------- #

def test_quiet_fraction_has_no_baseline_on_the_first_frame():
    assert quiet_fraction(view(), None) is None
    # And None is NOT quiet — the fail-closed direction.
    assert Supervisor().is_quiet(None) is False


def test_quiet_fraction_is_zero_between_two_identical_captures():
    assert quiet_fraction(view(40), view(40)) == 0.0


def test_quiet_fraction_is_one_when_every_pixel_clears_the_threshold():
    # 40 -> 100 is 60, well over PIXEL_THRESHOLD's 18.
    assert quiet_fraction(view(100), view(40)) == 1.0


def test_a_changed_scene_is_not_quiet_at_the_measured_threshold():
    assert not Supervisor().is_quiet(quiet_fraction(view(100), view(40)))


# --- the happy path -------------------------------------------------------- #

def test_a_still_correct_board_reaches_a_VERIFIED_verdict():
    app = fake_app()
    seen = drive(app, [frame_at(1), frame_at(2)])
    # Frame 1 has no baseline, so it cannot be quiet: BUSY, not a verdict.
    assert seen[0].state == "BUSY" and seen[0].verdict is None
    assert seen[1].state == "VERDICT"
    assert seen[1].verdict.verdict == "VERIFIED"
    assert seen[1].verdict.expected == ((1, 1), (2, 1))
    assert seen[1].severity == "none"


def test_a_missing_block_names_the_exact_cell():
    app = fake_app()
    seen = drive(app, [frame_at(1), frame_at(2, cells=((1, 1),))])
    assert seen[-1].verdict.verdict == "REMOVED"
    assert seen[-1].verdict.cells == ((2, 1),)
    # Amber pauses. A verdict NEVER locks the session.
    assert seen[-1].severity == "amber"


# --- refusal 1: the mode latch (D13) --------------------------------------- #

def test_a_frame_from_the_other_lattice_suspends_and_clears_the_baseline():
    app = fake_app()
    drive(app, [frame_at(1), frame_at(2)])
    assert app.state.supervision_baseline is not None

    latched = drive(app, [frame_at(3, mode="horizontal")])
    assert latched[0].state == "BUSY"
    assert "MODE LATCH" in latched[0].reason
    assert latched[0].verdict is None
    # `set_mode` homes X/Y, so the scene moved: the difference baseline is as
    # invalid as the hysteresis is.
    assert app.state.supervision_baseline is None
    assert app.state.supervision_sequence is None


def test_the_frame_after_a_latch_cannot_be_quiet_so_it_cannot_judge():
    app = fake_app()
    drive(app, [frame_at(1), frame_at(2)])
    drive(app, [frame_at(3, mode="horizontal")])
    resumed = drive(app, [frame_at(4)])
    assert resumed[0].state == "BUSY" and resumed[0].verdict is None


# --- refusal 2: the same capture, handed back ------------------------------ #

def test_a_repeated_sequence_is_not_a_second_observation():
    """`process_once` returns the last frame again when only staleness changed.

    Stepping on it would difference an array against itself — calling a scene
    quiet on no evidence — and let one capture supply two of the N-of-M
    readings. One step per new capture, exactly as Gate 0's instrument did.
    """
    app = fake_app()
    second = frame_at(2)
    drive(app, [frame_at(1), second])
    before = app.state.supervision
    assert before.state == "VERDICT"

    # The same capture, re-delivered as `replace(frame, stale=True)` does: same
    # sequence, same `view` object, a different ProcessedFrame.
    restaled = frame_at(2)
    restaled.view = second.view
    drive(app, [restaled])
    assert app.state.supervision is before
    assert app.state.supervision_baseline is second.view


# --- refusal 3: D5's gantry-parked gate ------------------------------------ #

def test_a_running_build_refuses_every_verdict():
    app = fake_app()
    seen = drive(app, [frame_at(1), frame_at(2)], running=True)
    assert [s.state for s in seen] == ["BUSY", "BUSY"]
    assert all(s.verdict is None for s in seen)


def test_a_locked_controller_refuses_every_verdict():
    app = fake_app(locked=True)
    seen = drive(app, [frame_at(1), frame_at(2)])
    assert all(s.verdict is None for s in seen)


def test_an_in_flight_cell_phase_refuses_every_verdict():
    for phase in ("feeding", "staging", "ready_for_pick", "placing", "error"):
        app = fake_app(cell_phase=phase)
        seen = drive(app, [frame_at(1), frame_at(2)])
        assert all(s.verdict is None for s in seen), phase
        assert seen[-1].state == "BUSY", phase


def test_complete_is_parked_or_supervision_dies_after_the_first_block():
    """The one that would have wedged the feature silently.

    `CellOrchestrator._phase("complete")` is terminal and sticky — nothing
    resets it — so `cell_phase` reads `complete` from the first placed block
    until the next build starts. The design's `cell_phase == "idle"` would hold
    supervision at BUSY for every session after block one, in exactly the
    situation the feature exists for.
    """
    assert "complete" in PARKED_CELL_PHASES and "idle" in PARKED_CELL_PHASES
    app = fake_app(cell_phase="complete")
    seen = drive(app, [frame_at(1), frame_at(2)])
    assert seen[-1].state == "VERDICT"
    assert seen[-1].verdict.verdict == "VERIFIED"


# --- refusal 4: the map, and the memory ------------------------------------ #

def test_an_uncalibrated_frame_reports_NO_MAP_and_judges_nothing():
    app = fake_app()
    seen = drive(app, [frame_at(1, calibrated=False),
                       frame_at(2, calibrated=False)])
    assert seen[-1].state == "NO_MAP" and seen[-1].verdict is None


def test_an_empty_ledger_reports_NO_MEMORY_after_a_restart():
    app = fake_app(cells=())
    seen = drive(app, [frame_at(1), frame_at(2)])
    assert seen[-1].state == "NO_MEMORY" and seen[-1].verdict is None


# --- the real wiring exists ------------------------------------------------ #

def test_the_lifespan_owns_a_ledger_the_controller_writes_to(tmp_path):
    """The seam M1 built and M2 turns on: `ledger=` on the controller."""
    app = create_app(ConsoleAppOptions(
        mock=True,
        settings_path=mock_settings(tmp_path),
        workspace_map_path=tmp_path / "workspace_map.json",
    ))

    async def scenario():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test"):
                return app.state

    state = asyncio.run(scenario())
    assert isinstance(state.ledger, PlacementLedger)
    assert state.controller.ledger is state.ledger
    assert isinstance(state.supervisor, Supervisor)
    # D3: empty on every process, never reloaded from `placements.log`.
    assert state.ledger.has_memory is False
    # Gate 0's measured constants reached the running server unaltered.
    assert state.supervisor.quiet_diff_fraction == QUIET_DIFF_FRACTION
    assert (state.supervisor.settle_n, state.supervisor.settle_m) == (3, 5)

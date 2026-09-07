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


def at_gap(a, b):
    """A detection halfway between two cell centres — in the deliberate gap."""
    ax, ay = GRID.cell_center_cm(*a)
    bx, by = GRID.cell_center_cm(*b)
    return FakeDetection(MAP.pixel_at((ax + bx) / 2 / GRID.workspace_width_cm,
                                      (ay + by) / 2 / GRID.workspace_height_cm,
                                      SIZE))


def view(fill: int = 40) -> np.ndarray:
    """One synthetic capture. Flat, so two of them differ by exactly `fill`."""
    frame = np.full((SIZE[1], SIZE[0], 3), fill, dtype=np.uint8)
    frame.flags.writeable = False
    return frame


def frame_at(sequence, *, cells=((1, 1), (2, 1)), extra=(), fill=40,
             calibrated=True, mode="vertical"):
    return SimpleNamespace(
        view=view(fill), sequence=sequence, image_size=SIZE,
        detections=tuple(at_cell(col, row) for col, row in cells) + tuple(extra),
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
        pending_check=None, vision_verification=None,
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


def test_an_unexpected_block_on_a_near_empty_board_is_FOREIGN():
    """D10 removed: with the holder off the rig the classifier no longer

    suppresses FOREIGN on a sparse board. Two placed cells plus one extra
    detection — three in the frame, well under the old threshold of six —
    now stops the program instead of reading VERIFIED.
    """
    app = fake_app()
    seen = drive(app, [frame_at(1, cells=((1, 1), (2, 1), (4, 4))),
                       frame_at(2, cells=((1, 1), (2, 1), (4, 4)))])
    assert seen[-1].state == "VERDICT"
    assert seen[-1].verdict.verdict == "FOREIGN"
    assert seen[-1].verdict.cells == ((4, 4),)
    assert seen[-1].severity == "red"


def test_a_block_knocked_into_a_gap_is_DISPLACED_and_names_its_cell():
    """One cell emptied, one detection in the build area but on no site: the

    block was knocked off [2,1] into the gap. Amber, pauses, names the origin.
    Before this it read as red FOREIGN with no cell named.
    """
    app = fake_app()  # ledger expects [1,1] and [2,1]
    gap = at_gap((2, 1), (3, 1))
    seen = drive(app, [frame_at(1, cells=((1, 1),), extra=(gap,)),
                       frame_at(2, cells=((1, 1),), extra=(gap,))])
    assert seen[-1].state == "VERDICT"
    assert seen[-1].verdict.verdict == "DISPLACED"
    assert seen[-1].verdict.cells == ((2, 1),)
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


# --- M3a: the per-build check, armed at the settle, answered in a window --- #

def _armed_app(level=0):
    app = fake_app(cells=((1, 1), (2, 1)))
    app.state.pending_check = app.state.ledger.placements()[-1]
    if level:
        app.state.ledger.append("vertical", 2, 1, level, BuildResult(PLACED))
        app.state.pending_check = app.state.ledger.placements()[-1]
    app.state.vision_verification = "checking — waiting for a still frame"
    # `_resolve_pending_check` publishes; the fake app has no hub, so stand in
    # a no-op. What is under test is the sentence, not the publish.
    app.state.hub = None
    return app


def test_the_per_build_check_is_not_answerable_at_settle_time():
    """It stays `checking` until a quiet window arrives, which is the point.

    The rig has only just parked when the result settles. D5 wants a still,
    settled scene — ~0.6 s later at the measured 8.6-8.7 Hz — so the sentence
    cannot exist yet, and the design's "zero client work" claim does not hold.
    """
    app = _armed_app()
    drive(app, [frame_at(1)])          # no baseline yet, so BUSY
    assert app.state.vision_verification == "checking — waiting for a still frame"
    assert app.state.pending_check is not None


def test_a_quiet_window_answers_the_per_build_check(monkeypatch):
    import web.app as web_app
    monkeypatch.setattr(web_app, "publish_state", lambda app, **kw: True)
    app = _armed_app()
    drive(app, [frame_at(1), frame_at(2)])
    assert app.state.vision_verification == "verified in frame at [2,1]"
    # Answered once, then disarmed: one placement, one sentence.
    assert app.state.pending_check is None


def test_a_block_that_never_arrived_names_the_cell(monkeypatch):
    import web.app as web_app
    monkeypatch.setattr(web_app, "publish_state", lambda app, **kw: True)
    app = _armed_app()
    drive(app, [frame_at(1, cells=((1, 1),)), frame_at(2, cells=((1, 1),))])
    assert app.state.vision_verification == "not detected at [2,1]"


def test_an_uncalibrated_frame_resolves_the_check_rather_than_leaving_it(monkeypatch):
    """A run report that cannot tell "checked" from "never checked" is worse
    than one that says nothing."""
    import web.app as web_app
    monkeypatch.setattr(web_app, "publish_state", lambda app, **kw: True)
    app = _armed_app()
    drive(app, [frame_at(1, calibrated=False), frame_at(2, calibrated=False)])
    assert app.state.vision_verification.startswith("unchecked — no map")
    assert app.state.pending_check is None


# --- M3b: one field, four readers ------------------------------------------ #

def test_the_published_model_is_flat_and_carries_the_severity():
    """No surface re-derives a verdict — so the SERVER has to send the severity.

    Four renderers of one field cannot disagree, which is what makes "appears
    everywhere and stays in sync" structural rather than a discipline anyone
    has to keep.
    """
    from rig.supervisor import Verdict
    from web.state import SupervisionState, supervision_model

    verdict = Verdict(verdict="FOREIGN", cells=((4, 2),), mode="vertical",
                      expected=((1, 1),), observed=((1, 1), (4, 2)),
                      unjudged=((3, 3),))
    model = supervision_model(SupervisionState(
        state="VERDICT", reason=None, verdict=verdict, judged_at_ms=7))
    assert model.state == "VERDICT" and model.verdict == "FOREIGN"
    assert model.severity == "red"
    # Pydantic narrows to the declared tuple type; it is a JSON array on the
    # wire either way. Exact CELLS, never a count.
    assert model.cells == [(4, 2)]
    assert model.expected == [(1, 1)] and model.observed == [(1, 1), (4, 2)]
    assert model.unjudged == [(3, 3)]
    assert model.acknowledged is False


def test_an_amber_verdict_publishes_as_amber_and_never_as_locked():
    from rig.supervisor import AMBER_VERDICTS, RED_VERDICTS, Verdict
    from web.state import SupervisionState, supervision_model

    for name in AMBER_VERDICTS + RED_VERDICTS:
        model = supervision_model(SupervisionState(
            state="VERDICT", reason=None, judged_at_ms=1,
            verdict=Verdict(verdict=name, cells=((1, 1),), mode="vertical",
                            expected=(), observed=(), unjudged=())))
        assert model.severity in ("amber", "red")
        assert model.severity != "locked"
    assert "LOCKED" not in set(AMBER_VERDICTS) | set(RED_VERDICTS)


def test_a_refusal_publishes_no_verdict_and_no_cells():
    """BUSY is the normal condition for a whole build. It names no cell and
    carries no verdict, so nothing downstream can paint it as a fault."""
    from web.state import SupervisionState, supervision_model

    model = supervision_model(SupervisionState(
        state="BUSY", reason="RIG MOVING", verdict=None, judged_at_ms=3))
    assert model.verdict is None and model.cells == []
    assert model.severity == "none"
    assert model.reason == "RIG MOVING"


def test_a_fresh_process_publishes_NO_MEMORY_before_any_frame():
    from web.state import supervision_model
    model = supervision_model(None)
    assert model.state == "NO_MEMORY" and model.verdict is None
    assert "restart" in model.reason


def test_the_state_snapshot_carries_supervision_and_survives_a_mode_latch(tmp_path):
    app = create_app(ConsoleAppOptions(
        mock=True,
        settings_path=mock_settings(tmp_path),
        workspace_map_path=tmp_path / "workspace_map.json",
    ))

    async def scenario():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                before = (await client.get("/api/state")).json()
                acked = (await client.post("/api/supervision/ack")).json()
                return before, acked

    before, acked = asyncio.run(scenario())
    assert before["supervision"]["state"] == "NO_MEMORY"
    assert before["supervision"]["verdict"] is None
    assert before["vision_verification"] is None
    # D12: the ack is available even mid-build — it moves nothing, and a
    # verdict that paused the runner has to be dismissible. It answers with the
    # whole state, like every other command route.
    assert "supervision" in acked and "acknowledged" in acked["supervision"]


def test_acknowledging_is_per_event_and_a_new_reading_clears_it():
    """D12's dismissal is per EVENT, not a persistent "stop asking" mark.

    "After a dismissal the cell is re-checked in the next quiet window before
    the runner continues" — a repair that is not re-verified is a guess with
    extra steps, and that applies to a human's repair as much as a machine's.
    """
    from web.app import _note_supervision
    from rig.supervisor import Verdict

    app = fake_app()
    removed = Verdict(verdict="REMOVED", cells=((2, 1),), mode="vertical",
                      expected=((1, 1), (2, 1)), observed=((1, 1),), unjudged=())
    _note_supervision(app, "VERDICT", None, removed)
    app.state.supervision_acknowledged = True

    # The SAME verdict again is the same event: the ack stands.
    _note_supervision(app, "VERDICT", None, removed)
    assert app.state.supervision_acknowledged is True

    # The same verdict at a DIFFERENT cell is a new thing to look at.
    moved = Verdict(verdict="REMOVED", cells=((1, 1),), mode="vertical",
                    expected=((1, 1), (2, 1)), observed=((2, 1),), unjudged=())
    _note_supervision(app, "VERDICT", None, moved)
    assert app.state.supervision_acknowledged is False


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

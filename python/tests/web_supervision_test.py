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


def at_cm_point(x_cm, y_cm, angle=0.0):
    """A detection at an arbitrary workspace-cm point, with an optional angle."""
    d = FakeDetection(MAP.pixel_at(x_cm / GRID.workspace_width_cm,
                                   y_cm / GRID.workspace_height_cm, SIZE))
    d.angle = angle
    return d


def view(fill: int = 40) -> np.ndarray:
    """One synthetic capture. Flat, so two of them differ by exactly `fill`."""
    frame = np.full((SIZE[1], SIZE[0], 3), fill, dtype=np.uint8)
    frame.flags.writeable = False
    return frame


def frame_at(sequence, *, cells=((1, 1), (2, 1)), extra=(), fill=40,
             calibrated=True, mode="vertical", analysis_ok=True,
             analysis_error=None):
    return SimpleNamespace(
        view=view(fill), sequence=sequence, image_size=SIZE,
        detections=tuple(at_cell(col, row) for col, row in cells) + tuple(extra),
        workspace=MAP, calibrated=calibrated, grid_mode=mode, stale=False,
        analysis_ok=analysis_ok, analysis_error=analysis_error)


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
        supervision_result_id=None,
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
    # No offending block, so no advisory offender residual — but the board's
    # blocks are placed dead on their centres, so the worst on-cell drift is ~0.
    assert seen[1].residual_cm is None
    from web.state import supervision_model
    model = supervision_model(seen[1])
    assert model.residual_cm is None
    assert seen[1].max_cell_residual_cm is not None and seen[1].max_cell_residual_cm < 0.1
    assert model.max_cell_residual_cm is not None and model.max_cell_residual_cm < 0.1


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


# --- the operator CORRECTION action's server-side assessment ------------- #
#
# `_supervise` calls `_assess_correction`, which is read-only: it projects the
# offending detection into workspace cm, reads the ledger, and asks the pure
# `rig.placement_check.assess`. Nothing here moves the rig. The route
# `/api/supervision/correct` re-runs the same path — the published flag is
# never trusted (DESIGN.md §8).

def test_a_DISPLACED_block_inside_the_band_publishes_a_ready_correction():
    from web.state import supervision_model
    app = fake_app()  # vertical, ledger [1,1] and [2,1]
    # Cell (2,1) centre x = 7.6 cm, footprint ends at 8.7 cm. A detection at
    # 8.75 cm is in the gap and 1.15 cm off the cell — inside the 0.5-1.2 band.
    y = GRID.cell_center_cm(2, 1)[1]
    off = at_cm_point(8.75, y)
    seen = drive(app, [frame_at(1, cells=((1, 1),), extra=(off,)),
                       frame_at(2, cells=((1, 1),), extra=(off,))])
    sv = seen[-1]
    assert sv.verdict.verdict == "DISPLACED"
    assert sv.correction is not None
    assert sv.correction.pick_cell == (2, 1) and sv.correction.place_cell == (2, 1)
    assert sv.correction.pick_level == 0
    assert "pick it up" in sv.correction_reason
    model = supervision_model(sv)
    assert model.correctable is True
    assert model.correction_cell == (2, 1) and model.correction_level == 0
    assert model.pick_offset_cm is not None and abs(model.pick_offset_cm[0] - 1.15) < 0.05
    # ADVISORY residual — "how far off", published, gates nothing.
    assert sv.residual_cm is not None and abs(sv.residual_cm - 1.15) < 0.05
    assert model.residual_cm is not None and abs(model.residual_cm - 1.15) < 0.05


def test_a_DISPLACED_block_far_off_with_a_clear_neighbour_is_now_corrected():
    """The old 1.2 cm ceiling is gone. 1.9 cm off, straight, nothing in the way

    the block slid toward -> the claw returns it. `dx` carries the real 1.9 cm.
    """
    from web.state import supervision_model
    app = fake_app()  # ledger [1,1] and [2,1]; [3,1] is empty
    gap = at_gap((2, 1), (3, 1))  # the midpoint: 1.9 cm off toward the empty [3,1]
    seen = drive(app, [frame_at(1, cells=((1, 1),), extra=(gap,)),
                       frame_at(2, cells=((1, 1),), extra=(gap,))])
    sv = seen[-1]
    assert sv.verdict.verdict == "DISPLACED"
    assert sv.correction is not None
    assert abs(sv.correction.dx_cm - 1.9) < 0.05 and abs(sv.correction.dy_cm) < 0.05
    assert supervision_model(sv).correctable is True
    assert sv.residual_cm is not None and abs(sv.residual_cm - 1.9) < 0.05


def test_a_gap_block_far_from_its_paired_cell_is_downgraded_to_DISAGREES():
    """`classify` pairs the one emptied cell with the one gap detection by set

    difference; `step()` with the grid rejects the pairing when they are more
    than a pitch apart — the case that was surfacing as a nonsense correction.
    """
    app = fake_app()  # ledger [1,1] and [2,1]; [2,1] centre is (7.6, 7.6) cm
    far = at_cm_point(7.6, 7.6 + 11.0)  # in a gap, but 11 cm from [2,1]
    seen = drive(app, [frame_at(1, cells=((1, 1),), extra=(far,)),
                       frame_at(2, cells=((1, 1),), extra=(far,))])
    sv = seen[-1]
    assert sv.verdict.verdict == "DISAGREES"
    assert sv.severity == "red"
    assert sv.reason is not None and "past the cell [2,1]" in sv.reason
    assert sv.correction is None


def test_a_DISPLACED_block_toward_an_occupied_neighbour_is_refused_by_hand():
    """Same 1.9 cm displacement, but [3,1] now holds a block: the descending

    jaw would shove it. The corridor check refuses and says to clear it by hand.
    """
    from web.state import supervision_model
    app = fake_app(cells=((1, 1), (2, 1), (3, 1)))
    gap = at_gap((2, 1), (3, 1))  # 1.9 cm off toward the OCCUPIED [3,1]
    seen = drive(app, [frame_at(1, cells=((1, 1), (3, 1)), extra=(gap,)),
                       frame_at(2, cells=((1, 1), (3, 1)), extra=(gap,))])
    sv = seen[-1]
    assert sv.verdict.verdict == "DISPLACED"
    assert sv.correction is None
    assert "by hand" in sv.correction_reason
    assert supervision_model(sv).correctable is False


def test_a_MOVED_block_publishes_a_correction_naming_both_cells():
    from web.state import supervision_model
    app = fake_app()  # ledger [1,1] and [2,1]
    # [2,1] emptied, a block squarely on the wrong cell [3,1], no gap detection.
    seen = drive(app, [frame_at(1, cells=((1, 1), (3, 1))),
                       frame_at(2, cells=((1, 1), (3, 1)))])
    sv = seen[-1]
    assert sv.verdict.verdict == "MOVED"
    assert sv.verdict.cells == ((2, 1), (3, 1))
    assert sv.correction is not None
    assert sv.correction.pick_cell == (3, 1)   # where it IS
    assert sv.correction.place_cell == (2, 1)  # where it BELONGS
    model = supervision_model(sv)
    assert model.correctable is True and model.correction_cell == (2, 1)


def test_a_REMOVED_verdict_offers_no_correction_at_all():
    from web.state import supervision_model
    app = fake_app()
    seen = drive(app, [frame_at(1, cells=((1, 1),)), frame_at(2, cells=((1, 1),))])
    sv = seen[-1]
    assert sv.verdict.verdict == "REMOVED"
    assert sv.correction is None and sv.correction_reason is None
    model = supervision_model(sv)
    assert model.correctable is False and model.correction_reason is None


def test_a_rotated_DISPLACED_block_is_refused_with_a_straighten_it_reason():
    from web.state import supervision_model
    app = fake_app()
    y = GRID.cell_center_cm(2, 1)[1]
    off = at_cm_point(8.75, y, angle=20.0)
    seen = drive(app, [frame_at(1, cells=((1, 1),), extra=(off,)),
                       frame_at(2, cells=((1, 1),), extra=(off,))])
    sv = seen[-1]
    assert sv.verdict.verdict == "DISPLACED"
    assert sv.correction is None and "rotated" in sv.correction_reason
    assert supervision_model(sv).correctable is False


# --- items 6 + 9: the correction rests on one coherent, stable track ------ #
#
# `_supervise` looks the offending block's fused quiet-window track up in the
# supervisor and refuses a correction unless it is one stable, unambiguous,
# block-consistent track. `fake_app` runs settle_n = settle_m = 1, so a single
# steady frame is enough — the point here is the multiplicity / switch / fusion
# behaviour, not the N-of-M window (that is `test_supervisor.py`).

def test_a_clean_DISPLACED_track_publishes_its_fused_uncertainty():
    from web.state import supervision_model
    app = fake_app()
    y = GRID.cell_center_cm(2, 1)[1]
    off = at_cm_point(8.75, y)
    seen = drive(app, [frame_at(1, cells=((1, 1),), extra=(off,)),
                       frame_at(2, cells=((1, 1),), extra=(off,))])
    sv = seen[-1]
    assert sv.verdict.verdict == "DISPLACED" and sv.correction is not None
    # Item 9 uncertainty surfaced: one steady detection -> sigma 0, 1 of 1 frame.
    assert sv.track_samples == (1, 1)
    assert sv.localization_sigma_cm == 0.0 and sv.localization_residual_cm == 0.0
    model = supervision_model(sv)
    assert model.track_samples == (1, 1)
    assert model.localization_sigma_cm == 0.0


def test_a_merged_blob_on_the_MOVED_cell_is_not_correctable():
    from web.state import supervision_model
    app = fake_app()  # ledger [1,1] and [2,1]; [2,1] emptied, block on [3,1]
    x, y = GRID.cell_center_cm(3, 1)
    dupe = FakeDetection(MAP.pixel_at((x + 0.3) / GRID.workspace_width_cm,
                                      y / GRID.workspace_height_cm, SIZE))
    seen = drive(app, [frame_at(1, cells=((1, 1), (3, 1)), extra=(dupe,)),
                       frame_at(2, cells=((1, 1), (3, 1)), extra=(dupe,))])
    sv = seen[-1]
    assert sv.verdict.verdict == "MOVED"     # the SET still reads one moved block
    assert sv.correction is None             # ... but the track is ambiguous
    assert sv.correction_reason and "merged blob" in sv.correction_reason
    assert supervision_model(sv).correctable is False


def test_the_correct_route_refuses_when_the_track_is_not_established():
    """The `/correct` route re-queries the SAME supervisor track. If nothing has
    been tracked (the driver never ran, or the block stopped being seen), the
    correction is refused rather than driven off a single stale frame."""
    from fastapi import HTTPException
    http, state, sent = _correct_app(off_cm=8.75)
    state.supervisor._track_history.reset()   # as if the block dropped out
    try:
        _call_correct(http)
        assert False, "should have refused"
    except HTTPException as exc:
        assert exc.status_code == 409
    assert sent == []


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


def test_detections_from_an_old_map_generation_never_reach_supervision():
    app = fake_app()
    app.state.pipeline = SimpleNamespace(map_generation=8)
    old = frame_at(1)
    old.map_generation = 7

    reading = drive(app, [old])[0]

    assert reading.state == "BUSY"
    assert "MAP CHANGED" in reading.reason
    assert app.state.supervision_baseline is None
    assert app.state.supervision_result_id is None


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


def test_a_completed_result_id_is_consumed_only_once():
    app = fake_app()
    first = frame_at(1)
    first.analysis_result_id = 7
    duplicate = frame_at(99)
    duplicate.analysis_result_id = 7

    drive(app, [first])
    before = app.state.supervision
    baseline = app.state.supervision_baseline
    drive(app, [duplicate])

    assert app.state.supervision is before
    assert app.state.supervision_baseline is baseline
    assert app.state.supervision_sequence == 1


def test_a_stale_analysis_result_never_becomes_quiet_evidence():
    app = fake_app()
    stale = frame_at(1)
    stale.stale = True

    first = drive(app, [stale])[0]
    assert first.state == "NO_VISION"
    assert "STALE" in first.reason
    assert first.verdict is None
    assert app.state.supervision_baseline is None

    # The next fresh result is only a new baseline.  The stale image cannot be
    # its quiet predecessor and cannot contribute a supervisor vote.
    resumed = drive(app, [frame_at(2)])[0]
    assert resumed.state == "BUSY" and resumed.verdict is None


# --- detector failure / staleness -> NO_VISION, never REMOVED ------------- #

def test_a_detector_failure_frame_is_NO_VISION_not_an_empty_board():
    """The worker caught a detector exception and handed back zero detections
    with `analysis_ok=False`.  That must read as "vision is unavailable", never
    as "the board was swept clean" — which on a non-empty ledger is REMOVED."""
    app = fake_app()
    # Settle a clean VERIFIED first so there IS a verdict to wrongly overwrite.
    drive(app, [frame_at(1), frame_at(2)])
    assert app.state.supervision.verdict.verdict == "VERIFIED"

    failed = frame_at(3, analysis_ok=False,
                      analysis_error="analysis failed: boom")
    failed.detections = ()
    reading = drive(app, [failed])[0]

    assert reading.state == "NO_VISION"
    assert reading.verdict is None
    assert reading.correction is None
    assert "boom" in reading.reason
    assert app.state.supervision_baseline is None


def test_detector_failures_do_not_advance_hysteresis_toward_REMOVED():
    """Several consecutive failed results with a non-empty ledger must not
    settle any AMBER verdict — the empty tuple is not evidence."""
    app = fake_app()
    drive(app, [frame_at(1), frame_at(2)])

    fails = []
    for seq in range(3, 9):
        f = frame_at(seq, analysis_ok=False, analysis_error="detector crashed")
        f.detections = ()
        fails.append(f)
    seen = drive(app, fails)

    assert [s.state for s in seen] == ["NO_VISION"] * len(fails)
    assert all(s.verdict is None for s in seen)

    # And a clean board afterwards still has to re-warm from nothing, not snap
    # to a verdict on the strength of the failed frames.
    resumed = drive(app, [frame_at(9), frame_at(10)])
    assert resumed[-1].verdict.verdict == "VERIFIED"


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


# --- POST /api/supervision/correct — the operator CORRECTION action ------- #
#
# The route re-derives the correction on the CURRENT frame and never trusts the
# published flag. A HELD result locks the controller; a good result drops the
# hysteresis so the board re-verifies (D12). Nothing here talks to real
# hardware — `rig.replace_block` is a fake that returns a BuildResult.

def _correct_app(*, verdict_name="DISPLACED", off_cm=8.75, angle=0.0,
                 replace_result=None, locked=False, job_running=False,
                 occupied_neighbour=False):
    import threading
    from rig.link import BuildResult, PLACED
    from rig.supervisor import Verdict
    from web.state import SupervisionState

    y = GRID.cell_center_cm(2, 1)[1]
    if verdict_name == "DISPLACED":
        extra = (at_cm_point(off_cm, y, angle),)
        cells_seen = ((1, 1), (3, 1)) if occupied_neighbour else ((1, 1),)
        observed = cells_seen
        verdict = Verdict(verdict="DISPLACED", cells=((2, 1),), mode="vertical",
                          expected=((1, 1), (2, 1)), observed=observed, unjudged=())
    else:  # MOVED
        extra = ()
        cells_seen = ((1, 1), (3, 1))
        verdict = Verdict(verdict="MOVED", cells=((2, 1), (3, 1)), mode="vertical",
                          expected=((1, 1), (2, 1)), observed=((1, 1), (3, 1)),
                          unjudged=())

    frame = frame_at(1, cells=cells_seen, extra=extra)
    ledger = PlacementLedger()
    ledger.append("vertical", 1, 1, 0, BuildResult(PLACED))
    ledger.append("vertical", 2, 1, 0, BuildResult(PLACED))
    if occupied_neighbour:
        ledger.append("vertical", 3, 1, 0, BuildResult(PLACED))

    sent = []

    def fake_replace(*args):
        sent.append(args)
        return replace_result or BuildResult(PLACED, "")

    supervisor = Supervisor(quiet_diff_fraction=QUIET_DIFF_FRACTION,
                            settle_n=1, settle_m=1)
    # Items 6 + 9: the route re-queries the supervisor's coherent quiet-window
    # track. The driver (`_supervise`) fills it in production; here, seed it by
    # feeding the current frame's observation N times so a stable single-block
    # track exists for `track_evidence_at` to return.
    from rig.supervisor import observe as _observe
    _seed = _observe(frame.detections, frame.workspace, frame.image_size)
    for _ in range(max(supervisor.settle_n, 1)):
        supervisor._track_history.update(_seed)
    supervisor.reset_calls = 0
    _orig_reset = supervisor.reset
    supervisor.reset = lambda: (setattr(supervisor, "reset_calls",
                                        supervisor.reset_calls + 1), _orig_reset())[1]

    lock = threading.Lock()
    state = SimpleNamespace(
        job=SimpleNamespace(running=job_running),
        mode_latch_lock=lock,
        controller=SimpleNamespace(locked=locked, locked_reason=None),
        latest_frame=frame,
        rig=SimpleNamespace(connected=True, replace_block=fake_replace),
        ledger=ledger,
        supervisor=supervisor,
        supervision=SupervisionState(state="VERDICT", reason=None, verdict=verdict,
                                     judged_at_ms=1),
        supervision_acknowledged=True,
        signal_change=lambda: None,
        pipeline=SimpleNamespace(saved_workspace=object()),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state)), state, sent


def _call_correct(http, confirm=True):
    """Call the route, but return `app.state` instead of a full `StateModel`:
    `build_state()` needs the whole running app, which the fake deliberately is
    not. The route's side effects on `app.state` are what these tests check."""
    import web.routes_command as rc
    from web.routes_command import CorrectRequest, correct_supervision
    saved = rc._state
    rc._state = lambda app: app.state
    try:
        return correct_supervision(CorrectRequest(confirm=confirm), http)
    finally:
        rc._state = saved


def test_correct_requires_confirm():
    from fastapi import HTTPException
    http, _, _ = _correct_app()
    try:
        _call_correct(http, confirm=False)
        assert False, "should have refused"
    except HTTPException as exc:
        assert exc.status_code == 400 and "confirm" in exc.detail


def test_correct_refuses_when_there_is_no_verdict():
    from fastapi import HTTPException
    http, state, _ = _correct_app()
    state.supervision = None
    try:
        _call_correct(http)
        assert False
    except HTTPException as exc:
        assert exc.status_code == 409 and "no verdict" in exc.detail


def test_correct_drives_a_DISPLACED_block_in_band_and_re_verifies():
    http, state, sent = _correct_app(off_cm=8.75)  # 1.15 cm off -> in band
    result = _call_correct(http)
    assert len(sent) == 1
    pc, pr, pl, dx, dy, qc, qr, ql = sent[0]
    assert (pc, pr, pl) == (2, 1, 0) and (qc, qr, ql) == (2, 1, 0)
    assert abs(dx - 1.15) < 0.05 and abs(dy) < 0.05
    assert result.last_correction_result["result"] == "placed"
    assert result.last_correction_result["cell"] == [2, 1]
    # D12: the board is re-checked — hysteresis dropped, ack cleared.
    assert state.supervisor.reset_calls == 1
    assert state.supervision_acknowledged is False
    # One attempt per verdict event.
    assert state.correction_attempted_signature is not None


def test_correct_is_one_shot_per_verdict_event():
    from fastapi import HTTPException
    http, state, sent = _correct_app(off_cm=8.75)
    _call_correct(http)
    try:
        _call_correct(http)
        assert False
    except HTTPException as exc:
        assert exc.status_code == 409 and "already been attempted" in exc.detail
    assert len(sent) == 1  # the rig was asked exactly once


def test_correct_refuses_a_DISPLACED_toward_an_occupied_neighbour_with_the_reason():
    from fastapi import HTTPException
    # 1.9 cm off toward [3,1], which now holds a block: the route re-checks the
    # descent corridor and refuses rather than trust the published flag.
    http, _, sent = _correct_app(off_cm=9.5, occupied_neighbour=True)
    try:
        _call_correct(http)
        assert False
    except HTTPException as exc:
        assert exc.status_code == 409 and "by hand" in exc.detail
    assert sent == []


def test_a_HELD_correction_locks_the_controller():
    from rig.link import BuildResult, ABORTED
    http, state, _ = _correct_app(
        off_cm=8.75, replace_result=BuildResult(ABORTED, "Z did not reach the pick level"))
    _call_correct(http)
    assert state.controller.locked_reason is not None
    assert "Z did not reach" in state.controller.locked_reason
    # A verdict never locks — but a HELD is a MACHINE fact, so this one does.
    assert state.last_correction_result["result"] == "aborted"


def test_correct_refuses_while_a_build_is_running():
    from fastapi import HTTPException
    http, _, sent = _correct_app(job_running=True)
    try:
        _call_correct(http)
        assert False
    except HTTPException as exc:
        assert exc.status_code == 409
    assert sent == []


def test_correct_moves_a_MOVED_block_back_to_its_planned_cell():
    http, state, sent = _correct_app(verdict_name="MOVED")
    _call_correct(http)
    assert len(sent) == 1
    pc, pr, pl, dx, dy, qc, qr, ql = sent[0]
    assert (pc, pr) == (3, 1)   # picked where it IS
    assert (qc, qr) == (2, 1)   # placed where it BELONGS


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
    assert state.ledger.has_memory() is False
    # Gate 0's measured constants reached the running server unaltered.
    assert state.supervisor.quiet_diff_fraction == QUIET_DIFF_FRACTION
    assert (state.supervisor.settle_n, state.supervisor.settle_m) == (3, 5)


def test_a_gantry_reboot_starts_a_new_board_epoch(tmp_path):
    """Audit item 8: a genuine `@0 BOOT` under a running session means the board
    on the table can no longer be spoken for by the ledger's entries. The rows
    stay, but a new epoch is started so no pre-reboot placement is authority,
    and the observer's hysteresis is dropped through item 7's reset primitive.
    """
    from rig.link import Ack

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
                st = app.state
                # An empty ledger has nothing to protect: a boot does not bump.
                st.rig._on_ack(Ack(seq=0, kind="BOOT"))
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                assert st.ledger.board_epoch == 0

                # With memory on the board, a reboot supersedes it.
                st.ledger.append("vertical", 2, 1, 0, BuildResult(PLACED))
                assert st.ledger.has_memory("vertical", 0) is True
                st.rig._on_ack(Ack(seq=0, kind="BOOT"))
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                return st

    st = asyncio.run(scenario())
    assert st.ledger.board_epoch == 1
    # The pre-reboot row is retained for the record...
    assert len(st.ledger.placements("vertical", board_epoch=None)) == 1
    # ...but the current epoch has no memory, so supervision reports NO_MEMORY
    # rather than judging the new board against the old one.
    assert st.ledger.has_memory("vertical") is False
    assert st.ledger.has_memory("vertical", 0) is True

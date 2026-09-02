"""What `/api/events` promises: ids, priority, replay, and honest terminals.

The console's whole claim about a running build is "what you are looking at is
what the rig said". These tests are that claim, split into the pieces that can
each be got wrong separately:

* a build phase reaches the browser as a `build_step` event with an id;
* a camera backlog can never delay one;
* nothing says `placed` before the terminal OK;
* a reconnect replays what was missed, by id, and never by matching text;
* HELD locks the session and SAFE does not.

The rig here is `MockBoard`, which speaks the same `@n STEP` protocol as
`build_test_v1.ino` — see `MockBoard.BUILD_PHASES`, which is copied from the
sketch. It proves the wiring, not the rig.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import time

import httpx
import pytest
from asgi_lifespan import LifespanManager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import SETTINGS_PATH  # noqa: E402
from web.app import ConsoleAppOptions, create_app, publish_state  # noqa: E402
from web.events import EventHub  # noqa: E402
from web.progress import BuildProgressTracker  # noqa: E402
from rig.link import parse_ack, parse_progress  # noqa: E402


def mock_settings(tmp_path: Path) -> Path:
    data = json.loads(SETTINGS_PATH.read_text())
    data["capture"].update({"width": 640, "height": 480})
    data["correction"]["enabled"] = False
    data["framing"] = {"crops": [], "zoom": 1.0, "pan": [0.5, 0.5]}
    path = tmp_path / "camera_settings.json"
    path.write_text(json.dumps(data))
    return path


def console(tmp_path: Path, **options):
    return create_app(ConsoleAppOptions(
        mock=True,
        settings_path=mock_settings(tmp_path),
        workspace_map_path=tmp_path / "workspace_map.json",
        heartbeat_s=5.0,
        build_seconds=options.pop("build_seconds", 0.6),
        **options,
    ))


async def wait_for(client, predicate, timeout: float = 6.0):
    """Poll `/api/state` until it matches. Returns the matching state."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = (await client.get("/api/state")).json()
        if predicate(last):
            return last
        await asyncio.sleep(0.01)
    raise AssertionError(f"state never matched: {last!r}")


async def select_and_build(client, app, *, cell=(3, 2), level=0):
    """Do exactly what the browser does: select a real pixel, then confirm."""
    state = await wait_for(client, lambda body: body["camera"] == "LIVE")
    grid = state["geometry"]["grid"]
    target = next(item for item in grid
                  if (item["col"], item["row"]) == tuple(cell))
    x = sum(point[0] for point in target["polygon"]) / 4
    y = sum(point[1] for point in target["polygon"]) / 4
    size = state["geometry"]["image_size"]
    await client.post("/api/select",
                      json={"x": x, "y": y, "img_w": size[0], "img_h": size[1]})
    if level:
        await client.post("/api/level", json={"value": level})
    command = f"B {cell[0]} {cell[1]} {level}"
    response = await client.post("/api/build",
                                 json={"confirm": True, "command": command})
    assert response.status_code == 200, response.text
    return command


# ======================================================================
# The hub on its own: ids, priority, coalescing, replay
# ======================================================================


def test_event_ids_are_monotonic_across_every_type():
    hub = EventHub()
    ids = [
        hub.publish("serial", {"line": "a"}).event_id,
        hub.publish_state({"mode": "vertical"}).event_id,
        hub.publish("build_step", {"step": 1}).event_id,
        hub.mint("heartbeat").event_id,
        hub.publish("build_result", {"result": "placed"}).event_id,
    ]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    assert hub.last_event_id == ids[-1]


def test_serial_events_are_never_delayed_behind_a_camera_backlog():
    """The whole reason this module exists.

    Twenty camera snapshots arrive, then one build phase. The client must be
    offered the phase FIRST, and must never be handed nineteen stale pictures
    to get to it.
    """
    hub = EventHub()
    client = hub.subscribe()
    for index in range(20):
        hub.publish_state({"camera_age_ms": index})
    phase = hub.publish("build_step", {"step": 8, "phase": "move_to_target"})

    first = client.take()
    assert first.type == "build_step"
    assert first.event_id == phase.event_id

    # And the camera cost exactly one message, not twenty: only the newest
    # snapshot had any value left by the time this client was read.
    second = client.take()
    assert second.type == "state"
    assert second.payload["state"]["camera_age_ms"] == 19
    assert client.take() is None


def test_state_snapshots_coalesce_but_serial_events_all_survive():
    hub = EventHub()
    client = hub.subscribe()
    for index in range(50):
        hub.publish_state({"camera_age_ms": index})
        hub.publish("serial", {"line": f"line {index}"})

    delivered = []
    while True:
        event = client.take()
        if event is None:
            break
        delivered.append(event)

    lines = [event for event in delivered if event.type == "serial"]
    states = [event for event in delivered if event.type == "state"]
    assert len(lines) == 50, "a dropped serial line is a lost fact"
    assert [event.payload["line"] for event in lines] == [
        f"line {index}" for index in range(50)]
    assert len(states) == 1, "an old snapshot has no value once a newer exists"
    assert states[0].payload["state"]["camera_age_ms"] == 49


def test_replay_returns_only_what_is_newer_and_reports_a_gap():
    hub = EventHub(replay_cap=4)
    first = hub.publish("serial", {"line": "one"})
    hub.publish_state({"n": 1})  # coalescing: never replayed
    second = hub.publish("build_step", {"step": 1})
    hub.publish("build_result", {"result": "placed"})

    missed = hub.replay_since(first.event_id)
    assert [event.event_id for event in missed] == [
        second.event_id, second.event_id + 1]
    assert all(event.type != "state" for event in hub.replay_since(None))

    # Nothing newer than the newest is not an error; it is an empty answer.
    assert hub.replay_since(hub.last_event_id) == []

    # Overflow the buffer, and the oldest id moves past what a stale client
    # last saw. That client has a hole, and the socket says so.
    for index in range(6):
        hub.publish("serial", {"line": f"more {index}"})
    assert hub.oldest_replay_id > first.event_id


def test_a_slow_client_records_dropped_events_rather_than_hiding_them():
    hub = EventHub(client_cap=3)
    client = hub.subscribe()
    for index in range(5):
        hub.publish("serial", {"line": str(index)})
    assert client.dropped == 2
    assert [client.take().payload["line"] for _ in range(3)] == ["2", "3", "4"]


# ======================================================================
# The progress tracker: the status machine, and what 'placed' means
# ======================================================================


def step_ack(seq, step, phase, action, label, status="begin", total=14, ms=None):
    tail = f" ms={ms}" if ms is not None else ""
    return parse_progress(parse_ack(
        f"@{seq} STEP step={step} total={total} phase={phase} action={action}"
        f" text={label} status={status}{tail}"))


def test_the_firmwares_predicted_duration_is_carried_but_never_authoritative():
    """`ms=` reaches the browser; nothing on the Pi acts on it.

    It is the firmware's own arithmetic (exact step count x its Z step period),
    on the wire because `Z_TRAVEL_STEPS` and `BLOCK_HEIGHT_CM` are firmware-
    owned and the Pi is forbidden a copy — see AGENTS.md. It is a FLOOR: the
    real move can only take longer, so nothing here may treat its expiry as
    the phase finishing.
    """
    tracker = BuildProgressTracker()
    tracker.command_accepted(1)
    tracker.on_progress(step_ack(1, 10, "lower_to_level", "move", "Lower", ms=2570), 2)
    assert tracker.progress.phase_eta_ms == 2570
    assert tracker.progress.as_state_fields()["build_phase_eta_ms"] == 2570

    # A phase the firmware cannot predict carries no duration, and the previous
    # phase's must not linger under it.
    tracker.on_progress(step_ack(1, 11, "release", "release", "Open"), 3)
    assert tracker.progress.phase_eta_ms is None

    # A settled build is not a phase and claims no duration either.
    tracker.on_result("placed", 4)
    assert tracker.progress.status == "placed"


def test_progress_walks_accepted_validating_running_parking_and_only_then_placed():
    tracker = BuildProgressTracker()
    assert tracker.progress.status == "idle"

    tracker.command_accepted(1)
    assert tracker.progress.status == "accepted"
    assert tracker.progress.step is None, "accepted claims no phase"

    tracker.on_ack(parse_ack("@12 RECV cmd=B col=3 row=2 level=0"), 2)
    assert tracker.progress.status == "validating"
    assert tracker.progress.command_seq == 12

    tracker.on_progress(step_ack(12, 8, "move_to_target", "move", "Move_XY"), 3)
    assert tracker.progress.status == "running"
    assert (tracker.progress.step, tracker.progress.total_steps) == (8, 14)
    assert tracker.progress.phase_label == "Move XY"
    assert tracker.progress.release_confirmed is False

    tracker.on_progress(step_ack(12, 11, "release", "release", "Open", "done"), 4)
    assert tracker.progress.release_confirmed is True
    assert tracker.progress.status == "running", (
        "the block is down but the command has not finished")

    tracker.on_progress(step_ack(12, 13, "park_home", "park", "Return_XY"), 5)
    assert tracker.progress.status == "parking"
    assert tracker.progress.release_confirmed is True

    # Every one of the above happened, and none of them said placed.
    tracker.on_result("placed", 6)
    assert tracker.progress.status == "placed"
    assert tracker.progress.serial_event_id == 6


def test_a_rejection_and_an_abort_do_not_share_a_status():
    rejected = BuildProgressTracker()
    rejected.command_accepted(1)
    rejected.on_result("rejected", 2)
    assert rejected.progress.status == "rejected"
    assert rejected.progress.release_confirmed is False

    aborted = BuildProgressTracker()
    aborted.command_accepted(1)
    aborted.on_progress(step_ack(4, 8, "move_to_target", "move", "Move_XY"), 2)
    aborted.on_result("aborted", 3, locked=True)
    assert aborted.progress.status == "locked", (
        "a locked session is a bigger fact than the word 'aborted'")
    assert aborted.progress.step == 8, "the last known phase is still the truth"


def test_a_new_command_clears_the_previous_phase():
    tracker = BuildProgressTracker()
    tracker.command_accepted(1)
    tracker.on_progress(step_ack(1, 11, "release", "release", "Open", "done"), 2)
    tracker.on_result("placed", 3)

    tracker.command_accepted(4)
    assert tracker.progress.step is None
    assert tracker.progress.phase is None
    assert tracker.progress.release_confirmed is False, (
        "the last build's release must not colour the next one")


# ======================================================================
# End to end, over the socket
# ======================================================================


# The abort dies at phase 8, MID-CARRY: the block is in the claw and neither
# the machine nor the console knows where. That is the case the twin and the
# runner both have to get right, and it is not the same as a parking failure.
@pytest.mark.parametrize("failure,expected_result,expect_locked", [
    (None, "placed", False),
    (("REJECTED", "no block at the feeder", 0), "rejected", False),
    (("ABORTED", "could not reach the target cell", 8), "aborted", True),
])
def test_a_build_streams_its_phases_then_exactly_one_result(
        tmp_path, failure, expected_result, expect_locked):
    app = console(tmp_path)

    async def scenario():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                subscriber = app.state.hub.subscribe()
                if failure is not None:
                    app.state.mock_board.fail_next_build(*failure)
                await select_and_build(client, app)
                await wait_for(client, lambda body: body["build_state"] != "RUNNING")
                # The result event is published by the driver loop when it
                # polls the finished job; give it a turn to notice.
                await wait_for(client,
                               lambda body: body["build_phase_status"] in
                               {"placed", "rejected", "aborted", "locked"})

                delivered = []
                while True:
                    event = subscriber.take()
                    if event is None:
                        break
                    delivered.append(event)
                return delivered, (await client.get("/api/state")).json()

    delivered, final = asyncio.run(scenario())

    steps = [event for event in delivered if event.type == "build_step"]
    results = [event for event in delivered if event.type == "build_result"]
    serial = [event for event in delivered if event.type == "serial"]

    assert len(results) == 1, "one command settles exactly once"
    assert results[0].payload["result"] == expected_result
    assert results[0].payload["locked"] is expect_locked

    # Ordering: every phase precedes the answer, on the wire as on the cable.
    assert all(event.event_id < results[0].event_id for event in steps)
    assert [event.event_id for event in delivered] == sorted(
        event.event_id for event in delivered)

    # The raw line is still there for the log, beside the structured event.
    assert any("STEP" in event.payload["line"] for event in serial) or not steps

    if expected_result == "rejected":
        assert steps == [], "a rejection refuses before anything moves"
        assert final["build_phase_status"] == "rejected"
        assert final["build_state"] == "READY", "SAFE does not lock the session"
        assert final["locked_reason"] is None
    else:
        assert [event.payload["step"] for event in steps] == sorted(
            event.payload["step"] for event in steps)
        assert steps[0].payload["phase"] == "raise_clear"
        assert steps[0].payload["label"] == "Raise Z into the top switch"
        assert steps[0].payload["command_seq"] == results[0].payload["command_seq"]
        assert steps[0].payload["total"] == 14
        # The Z moves carry the firmware's predicted duration; the phases whose
        # length nothing can predict carry None rather than a made-up number.
        by_phase = {event.payload["phase"]: event.payload["eta_ms"]
                    for event in steps if event.payload["status"] == "begin"}
        assert by_phase["lower_to_ground"] == 2570
        assert by_phase.get("grip") is None
        assert by_phase.get("move_to_target") is None

    if expected_result == "placed":
        assert steps[-1].payload["phase"] == "park_rotation"
        assert steps[-1].payload["action"] == "park"
        assert any(event.payload["status"] == "done" for event in steps)
        assert final["build_release_confirmed"] is True
        assert final["build_phase_status"] == "placed"
    if expected_result == "aborted":
        assert final["build_state"] == "LOCKED", "HELD locks the session"
        assert final["locked_reason"]
        assert final["build_phase_status"] == "locked"
        assert final["build_release_confirmed"] is False, (
            "it died carrying the block; nothing released it")
        assert final["build_step"] == 8, "the last phase seen is the last known"


def test_nothing_says_placed_before_the_terminal_acknowledgement(tmp_path):
    """Watch the whole stream and check no frame claims a placement early."""
    app = console(tmp_path, build_seconds=1.0)

    async def scenario():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                subscriber = app.state.hub.subscribe()
                await select_and_build(client, app)
                seen = []
                deadline = time.monotonic() + 8.0
                while time.monotonic() < deadline:
                    event = subscriber.take()
                    if event is None:
                        await asyncio.sleep(0.02)
                        continue
                    seen.append(event)
                    if event.type == "build_result":
                        break
                return seen

    seen = asyncio.run(scenario())
    result = seen[-1]
    assert result.type == "build_result" and result.payload["result"] == "placed"

    for event in seen[:-1]:
        if event.type == "state":
            assert event.payload["state"]["build_phase_status"] != "placed"
            assert event.payload["state"]["last_result"] != "placed"
        if event.type == "build_step":
            assert event.payload["status"] in {"begin", "done"}

    # The release IS reported before the result — that is the point of the
    # phase-11 'done' — but it is a different fact from being placed.
    released = [event for event in seen
                if event.type == "build_step" and event.payload["status"] == "done"]
    assert len(released) == 1
    assert released[0].event_id < result.event_id

    # The descent estimate reached the browser, and the release still arrived
    # as its own separate event: the estimate illustrates, it never concludes.
    lowering = [event for event in seen if event.type == "build_step"
                and event.payload["phase"] == "lower_to_level"]
    assert lowering and lowering[0].payload["eta_ms"] == 2570
    assert lowering[0].event_id < released[0].event_id
    parking = [event for event in seen if event.type == "build_step"
               and event.payload["action"] == "park"]
    assert parking and all(event.event_id > released[0].event_id
                           for event in parking)


def test_reconnecting_replays_by_id_and_delivers_nothing_twice(tmp_path):
    """A dropped socket must cost nothing but the time it was down."""
    app = console(tmp_path)

    async def scenario():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                await wait_for(client, lambda body: body["camera"] == "LIVE")
                first = app.state.hub.subscribe()

                await select_and_build(client, app)
                await asyncio.sleep(0.2)

                # The client drains what it has, remembers the last id, and
                # then "loses its connection" — its subscription goes away.
                seen = []
                while True:
                    event = first.take()
                    if event is None:
                        break
                    seen.append(event)
                app.state.hub.unsubscribe(first)
                last_id = max(event.event_id for event in seen)

                await wait_for(client, lambda body: body["build_state"] != "RUNNING")
                await wait_for(client,
                               lambda body: body["build_phase_status"] == "placed")

                missed = app.state.hub.replay_since(last_id)
                return seen, missed, (await client.get("/api/state")).json()

    seen, missed, final = asyncio.run(scenario())

    already = {event.event_id for event in seen}
    assert already, "the first connection saw something"
    assert not (already & {event.event_id for event in missed}), (
        "replay must be by id, never a re-send of what was already delivered")
    assert [event.event_id for event in missed] == sorted(
        event.event_id for event in missed)

    # Identical text is NOT how duplicates are detected. Prove the buffer can
    # legitimately hold two events with the same line and different ids.
    assert final["build_phase_status"] == "placed"
    replayed = app.state.hub.replay_since(None)
    assert len({event.event_id for event in replayed}) == len(replayed)

    # And a reconnecting client picks the build up where it left off, because
    # the state snapshot carries the progress as well as the events do.
    assert final["serial_event_id"] > 0


def test_a_fresh_socket_is_told_the_state_then_the_replay(tmp_path):
    app = console(tmp_path)

    async def scenario():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                await wait_for(client, lambda body: body["camera"] == "LIVE")
            # ASGITransport cannot open a WebSocket, so exercise the same two
            # frames the endpoint builds, from the same hub.
            hub = app.state.hub
            opening = hub.mint("state", {"state": {"build_phase_status": "idle"}})
            replay = hub.replay_since(None)
            return opening, replay, hub.last_event_id

    opening, replay, last_id = asyncio.run(scenario())
    assert opening.type == "state"
    assert opening.to_json()["event_id"] == opening.event_id
    assert opening.to_json()["at"] > 0
    # Minted, not published: nobody else was handed this client's own frame.
    assert opening.event_id <= last_id
    assert all(event.type in {"serial", "build_step", "build_result"}
               for event in replay)


def test_camera_frames_alone_do_not_flood_the_stream(tmp_path):
    """Geometry is throttled; a phase or a selection is not."""
    app = console(tmp_path, geometry_hz=2.0, driver_hz=20.0)

    async def scenario():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                await wait_for(client, lambda body: body["camera"] == "LIVE")
                subscriber = app.state.hub.subscribe()
                published = []
                # Sample for a second, taking one event per turn the way a
                # socket does, so coalescing cannot hide the publish rate.
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline:
                    event = subscriber.take()
                    if event is not None:
                        published.append(event)
                    await asyncio.sleep(0.005)
                return published

    published = asyncio.run(scenario())
    states = [event for event in published if event.type == "state"]
    # 20 Hz of frames, ~2 Hz of snapshots. Generous bounds: this is a promise
    # about ORDERS of magnitude, not a benchmark.
    assert len(states) <= 8, f"camera state was published {len(states)} times"


def test_a_semantic_change_is_published_immediately_whatever_the_throttle(tmp_path):
    app = console(tmp_path, geometry_hz=0.2)

    async def scenario():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                await wait_for(client, lambda body: body["camera"] == "LIVE")
                subscriber = app.state.hub.subscribe()
                while subscriber.take() is not None:
                    pass
                # A five-second geometry throttle is in force, and a selection
                # must not wait for it.
                assert publish_state(app) is False, "geometry alone is throttled"
                app.state.controller.select((3, 2))
                assert publish_state(app) is True
                event = subscriber.take()
                return event

    event = asyncio.run(scenario())
    assert event.type == "state"
    assert list(event.payload["state"]["selected"]) == [3, 2]

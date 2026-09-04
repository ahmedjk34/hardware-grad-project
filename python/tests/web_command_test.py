"""Step 5 server-side command guards against the supported mock rig."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import time

import httpx
from asgi_lifespan import LifespanManager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import SETTINGS_PATH, STALE_FRAME_AFTER_S  # noqa: E402
from web.app import ConsoleAppOptions, create_app  # noqa: E402


def mock_settings(tmp_path: Path) -> Path:
    data = json.loads(SETTINGS_PATH.read_text())
    data["capture"].update({"width": 640, "height": 480})
    data["correction"]["enabled"] = False
    data["framing"] = {"crops": [], "zoom": 1.0, "pan": [0.5, 0.5]}
    path = tmp_path / "camera_settings.json"
    path.write_text(json.dumps(data))
    return path


async def wait_for_state(client, predicate, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = await client.get("/api/state")
        assert response.status_code == 200
        last = response.json()
        if predicate(last):
            return last
        await asyncio.sleep(0.01)
    raise AssertionError(f"state never matched predicate: {last!r}")


def point_in_cell(app, col: int, row: int) -> tuple[float, float, tuple[int, int]]:
    frame = app.state.latest_frame
    assert frame is not None
    polygon = frame.workspace.target_polygon(col, row, frame.image_size)
    x = sum(point[0] for point in polygon) / len(polygon)
    y = sum(point[1] for point in polygon) / len(polygon)
    return x, y, frame.image_size


async def select_cell(client, app, col=3, row=5):
    x, y, (width, height) = point_in_cell(app, col, row)
    return await client.post("/api/select", json={
        # Exercise browser-to-feed coordinate scaling as well as cell lookup.
        "x": x * 2,
        "y": y * 2,
        "img_w": width * 2,
        "img_h": height * 2,
    })


def test_select_level_mode_and_stale_camera_guards(tmp_path):
    app = create_app(ConsoleAppOptions(
        mock=True, settings_path=mock_settings(tmp_path),
        workspace_map_path=tmp_path / "workspace_map.json", build_seconds=0.1,
    ))

    async def scenario():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                await wait_for_state(client, lambda state: state["camera"] == "LIVE")
                selected = await select_cell(client, app)
                assert selected.status_code == 200
                assert selected.json()["selected"] == [3, 5]
                assert selected.json()["command"] == "B 3 5 0"

                axis = await client.post("/api/select/axis", json={"axis": "col", "value": 2})
                assert axis.status_code == 200
                assert axis.json()["selected"] == [2, 0]
                deselected = await client.post("/api/deselect")
                assert deselected.status_code == 200
                assert deselected.json()["selected"] is None
                assert (await select_cell(client, app)).status_code == 200

                feeder_x, feeder_y, (width, height) = point_in_cell(app, 0, 0)
                feeder = await client.post("/api/select", json={
                    "x": feeder_x, "y": feeder_y, "img_w": width, "img_h": height,
                })
                assert feeder.status_code == 400
                assert feeder.json()["detail"].startswith("[0,0] is the feeder")

                outside = await client.post("/api/select", json={
                    "x": -1, "y": -1, "img_w": width, "img_h": height,
                })
                assert outside.status_code == 400

                level = await client.post("/api/level", json={"delta": -1})
                assert level.status_code == 200
                assert level.json()["level"] == 0

                view = await client.post("/api/view", json={"grid": False, "paper": True})
                assert view.status_code == 200
                assert view.json()["views"] == {
                    "grid": False, "detect": True, "paper": True, "overlay": True,
                }

                mode = await client.post("/api/mode", json={"mode": "horizontal"})
                assert mode.status_code == 200
                assert mode.json()["mode"] == "horizontal"
                assert mode.json()["selected"] is None
                assert (mode.json()["cols"], mode.json()["rows"]) != (7, 6)

                app.state.pipeline.camera.freeze()
                await asyncio.sleep(STALE_FRAME_AFTER_S + 0.15)
                await wait_for_state(client, lambda state: state["camera"] == "STALE")
                stale = await select_cell(client, app, 1, 1)
                assert stale.status_code == 409

    asyncio.run(scenario())


def test_build_placed_rejected_and_aborted_paths_are_server_guarded(tmp_path):
    app = create_app(ConsoleAppOptions(
        mock=True, settings_path=mock_settings(tmp_path),
        workspace_map_path=tmp_path / "workspace_map.json", build_seconds=0.12,
    ))

    async def scenario():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                await wait_for_state(client, lambda state: state["camera"] == "LIVE")
                assert (await select_cell(client, app)).status_code == 200

                bad_command = await client.post("/api/build", json={
                    "confirm": True, "command": "B 9 9 9",
                })
                assert bad_command.status_code == 400

                placed = await client.post("/api/build", json={
                    "confirm": True, "command": "B 3 5 0",
                })
                assert placed.status_code == 200
                assert placed.json()["build_state"] == "RUNNING"
                busy = await client.post("/api/deselect")
                assert busy.status_code == 409
                display_only = await client.post("/api/view", json={"overlay": False})
                assert display_only.status_code == 200
                assert display_only.json()["views"]["overlay"] is False
                done = await wait_for_state(client, lambda state: state["last_result"] == "placed")
                assert done["build_state"] == "READY"
                assert done["selected"] is None
                assert done["hardware_ready"] is True
                assert done["gantry_connected"] is True
                assert done["feeder_connected"] is True
                assert any(line.endswith("OK state=block_ready result=staged")
                           for line in app.state.mock_feeder.timeline)
                assert sum(line.startswith("B ")
                           for line in app.state.mock_board.written) == 1

                assert (await select_cell(client, app)).status_code == 200
                app.state.mock_board.fail_next_build("REJECTED", "simulated safe refusal")
                rejected = await client.post("/api/build", json={
                    "confirm": True, "command": "B 3 5 0",
                })
                assert rejected.status_code == 200
                locked = await wait_for_state(client, lambda state: state["build_state"] == "LOCKED")
                assert locked["last_result"] == "aborted"
                assert "simulated safe refusal" in locked["locked_reason"]
                assert "pickup state requires inspection" in locked["locked_reason"]
                assert (await client.post("/api/level", json={"delta": 1})).status_code == 409

    asyncio.run(scenario())


def test_feeder_failure_and_operator_cancel_never_send_mega_build(tmp_path):
    app = create_app(ConsoleAppOptions(
        mock=True, settings_path=mock_settings(tmp_path),
        workspace_map_path=tmp_path / "workspace_map.json", build_seconds=0.1,
    ))

    async def scenario():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                await wait_for_state(client, lambda state: state["camera"] == "LIVE")
                assert (await select_cell(client, app)).status_code == 200
                app.state.mock_feeder.fail_next("stage_timeout")
                assert (await client.post("/api/build", json={
                    "confirm": True, "command": "B 3 5 0",
                })).status_code == 200
                failed = await wait_for_state(
                    client, lambda state: state["build_state"] == "LOCKED")
                assert failed["last_result"] == "aborted"
                assert "stage_timeout" in failed["locked_reason"]
                assert not any(line.startswith("B ")
                               for line in app.state.mock_board.written)

        # A new service process is the required recovery from LOCKED.
        second = create_app(ConsoleAppOptions(
            mock=True, settings_path=mock_settings(tmp_path),
            workspace_map_path=tmp_path / "workspace_map_2.json",
            build_seconds=0.1,
        ))
        async with LifespanManager(second):
            second.state.mock_feeder.feed_seconds = 1.0
            transport = httpx.ASGITransport(app=second)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                await wait_for_state(client, lambda state: state["camera"] == "LIVE")
                assert (await select_cell(client, second)).status_code == 200
                assert (await client.post("/api/build", json={
                    "confirm": True, "command": "B 3 5 0",
                })).status_code == 200
                await wait_for_state(client, lambda state: state["cell_phase"] == "feeding")
                stopped = await client.post("/api/stop")
                assert stopped.status_code == 200
                cancelled = await wait_for_state(
                    client, lambda state: state["build_state"] == "LOCKED")
                assert "cancelled" in cancelled["locked_reason"]
                assert "STOP" in second.state.mock_feeder.writes
                assert not any(line.startswith("B ")
                               for line in second.state.mock_board.written)

    asyncio.run(scenario())

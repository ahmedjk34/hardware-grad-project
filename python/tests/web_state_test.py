"""Step 4 HTTP and WebSocket state coverage against the supported mock rig."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import threading
import time

import asyncio
import httpx
import uvicorn
from asgi_lifespan import LifespanManager
from websockets.sync.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import SETTINGS_PATH  # noqa: E402
from rig.config import load as load_rig_config  # noqa: E402
from web.app import ConsoleAppOptions, create_app  # noqa: E402


def mock_settings(tmp_path: Path) -> Path:
    data = json.loads(SETTINGS_PATH.read_text())
    data["capture"].update({"width": 640, "height": 480})
    data["correction"]["enabled"] = False
    data["framing"] = {"crops": [], "zoom": 1.0, "pan": [0.5, 0.5]}
    path = tmp_path / "camera_settings.json"
    path.write_text(json.dumps(data))
    return path


async def wait_for_state(client: httpx.AsyncClient, predicate, timeout: float = 2.0):
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


def test_mock_lifespan_serves_state_and_closes_rig(tmp_path):
    grid = load_rig_config(reload=True)["grid"]["modes"]["vertical"]
    app = create_app(ConsoleAppOptions(
        mock=True,
        settings_path=mock_settings(tmp_path),
        workspace_map_path=tmp_path / "workspace_map.json",
        heartbeat_s=0.02,
    ))
    async def scenario():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                initial = await client.get("/api/state")
                assert initial.status_code == 200
                data = initial.json()
                assert data["build_state"] == "READY"
                assert data["calibrated"] is False
                assert data["selected"] is None
                assert data["mode"] == "vertical"
                assert data["cols"] == grid["cols"]
                assert data["rows"] == grid["rows"]
                assert data["camera"] in {"WAITING", "LIVE"}

                live = await wait_for_state(client, lambda state: state["camera"] == "LIVE")
                assert live["camera_age_ms"] is not None
                assert app.state.pipeline is not None
                assert app.state.rig is not None

    asyncio.run(scenario())
    assert app.state.mock_board.is_open is False


def test_events_send_initial_update_and_heartbeat(tmp_path):
    app = create_app(ConsoleAppOptions(
        mock=True,
        settings_path=mock_settings(tmp_path),
        workspace_map_path=tmp_path / "workspace_map.json",
        heartbeat_s=0.02,
    ))
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    host, port = listener.getsockname()
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port,
                                            log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 3.0
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        with connect(f"ws://{host}:{port}/api/events", open_timeout=2.0) as events:
            # A new socket is told the truth first, then what it missed.
            initial = json.loads(events.recv())
            assert initial["type"] == "state"
            assert initial["state"]["selected"] is None
            # Every event carries an id and a timestamp, from one counter.
            assert initial["event_id"] >= 1
            assert initial["at"] > 0
            # An idle console has no build to describe, and says so rather
            # than leaving the fields absent.
            assert initial["state"]["build_phase_status"] == "idle"
            assert initial["state"]["build_step"] is None
            assert initial["state"]["build_release_confirmed"] is False

            replay = json.loads(events.recv())
            assert replay["type"] == "replay"
            # A first connection has no history to be missing, so no gap.
            assert replay["gap"] is False
            assert all(event["type"] in {"serial", "feeder", "build_step", "build_result"}
                       for event in replay["events"])

            app.state.controller.select((3, 5))
            app.state.signal_change()
            updated = json.loads(events.recv())
            assert updated["type"] == "state"
            assert updated["state"]["selected"] == [3, 5]
            assert updated["state"]["command"] == "B 3 5 0"
            assert updated["event_id"] > initial["event_id"]

            heartbeat = json.loads(events.recv())
            assert heartbeat["type"] == "heartbeat"
            assert heartbeat["event_id"] > updated["event_id"]
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)
        listener.close()
    assert not thread.is_alive()

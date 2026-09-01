"""Step 6 raw-MJPEG and browser-geometry coverage using the mock console."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import socket
import sys
import threading
import time

import httpx
import uvicorn
from asgi_lifespan import LifespanManager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import SETTINGS_PATH  # noqa: E402
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


def test_geometry_matches_workspace_and_skips_encode_without_viewers(tmp_path):
    app = create_app(ConsoleAppOptions(
        mock=True, settings_path=mock_settings(tmp_path),
        workspace_map_path=tmp_path / "workspace_map.json",
    ))

    async def scenario():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                state = await wait_for_state(client, lambda body: body["camera"] == "LIVE")
                assert app.state.jpeg_encode_count == 0
                await asyncio.sleep(0.15)
                assert app.state.jpeg_encode_count == 0
                state = await wait_for_state(
                    client, lambda body: bool(body["geometry"]["detections"]))

                geometry = state["geometry"]
                frame = app.state.latest_frame
                assert geometry["image_size"] == list(frame.image_size)
                assert geometry["calibrated"] is False
                assert len(geometry["grid"]) == frame.workspace.mapped_grid.cols * frame.workspace.mapped_grid.rows
                target = next(cell for cell in geometry["grid"]
                              if (cell["col"], cell["row"]) == (3, 5))
                expected = frame.workspace.target_polygon(3, 5, frame.image_size)
                assert target["polygon"] == [[float(x), float(y)] for x, y in expected]
                assert geometry["selected"] is None
                assert geometry["detections"]

                x, y = target["polygon"][0]
                # The first vertex can lie on an edge; use its polygon centre.
                x = sum(point[0] for point in target["polygon"]) / 4
                y = sum(point[1] for point in target["polygon"]) / 4
                selected = await client.post("/api/select", json={
                    "x": x, "y": y, "img_w": frame.image_size[0], "img_h": frame.image_size[1],
                })
                assert selected.status_code == 200
                assert selected.json()["geometry"]["selected"] == target

    asyncio.run(scenario())


def test_mjpeg_encodes_only_for_a_connected_viewer(tmp_path):
    app = create_app(ConsoleAppOptions(
        mock=True, settings_path=mock_settings(tmp_path),
        workspace_map_path=tmp_path / "workspace_map.json",
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
        assert app.state.jpeg_encode_count == 0
        payload = bytearray()
        with httpx.Client(timeout=3.0) as client:
            with client.stream("GET", f"http://{host}:{port}/api/stream.mjpg") as response:
                assert response.status_code == 200
                assert "multipart/x-mixed-replace" in response.headers["content-type"]
                for chunk in response.iter_raw():
                    payload.extend(chunk)
                    if payload.count(b"\xff\xd8") >= 3:
                        break
        assert payload.count(b"--frame\r\n") >= 3
        assert payload.count(b"Content-Length: ") >= 3
        assert payload.count(b"\xff\xd8") >= 3
        assert app.state.jpeg_encode_count >= 3
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)
        listener.close()
    assert not thread.is_alive()

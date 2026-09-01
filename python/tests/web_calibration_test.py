"""Step 10 browser-calibration routes use the same generated map artefact."""
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

def mock_settings(tmp_path):
    data = json.loads(SETTINGS_PATH.read_text()); data["capture"].update({"width": 640, "height": 480}); data["correction"]["enabled"] = False; data["framing"] = {"crops": [], "zoom": 1.0, "pan": [0.5, 0.5]}
    path = tmp_path / "camera_settings.json"; path.write_text(json.dumps(data)); return path

async def wait_live(client):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        state = (await client.get("/api/state")).json()
        if state["camera"] == "LIVE": return state
        await asyncio.sleep(.01)
    raise AssertionError("mock camera did not become live")

def test_four_corner_calibration_saves_and_changes_geometry(tmp_path):
    path = tmp_path / "workspace_map.json"; app = create_app(ConsoleAppOptions(mock=True, settings_path=mock_settings(tmp_path), workspace_map_path=path))
    async def scenario():
        async with LifespanManager(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                before = await wait_live(client); assert before["calibrated"] is False
                started = await client.post("/api/calibration/start"); assert started.status_code == 200; assert started.json()["next"] == "holder home [0,0]"
                for point in ((80, 60), (560, 90), (540, 420), (70, 400)):
                    response = await client.post("/api/calibration/corner", json={"x": point[0], "y": point[1], "img_w": 640, "img_h": 480}); assert response.status_code == 200
                saved = await client.post("/api/calibration/save"); assert saved.status_code == 200; assert saved.json()["calibrated"] is True; assert path.exists(); assert saved.json()["geometry"]["grid"] != before["geometry"]["grid"]
    asyncio.run(scenario())

def test_calibration_rejects_degenerate_running_and_stale_camera(tmp_path):
    app = create_app(ConsoleAppOptions(mock=True, settings_path=mock_settings(tmp_path), workspace_map_path=tmp_path / "workspace_map.json"))
    async def scenario():
        async with LifespanManager(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                await wait_live(client); assert (await client.post("/api/calibration/start")).status_code == 200
                for _ in range(4): assert (await client.post("/api/calibration/corner", json={"x": 100, "y": 100, "img_w": 640, "img_h": 480})).status_code == 200
                assert (await client.post("/api/calibration/save")).status_code == 400
                app.state.job._thread = type("Running", (), {"is_alive": lambda self: True})()
                assert (await client.post("/api/calibration/start")).status_code == 409
                app.state.job._thread = None; app.state.pipeline.camera.freeze(); await asyncio.sleep(STALE_FRAME_AFTER_S + .15)
                assert (await client.post("/api/calibration/start")).status_code == 409
    asyncio.run(scenario())

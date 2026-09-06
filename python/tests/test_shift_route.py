"""`POST /api/shift` — the runtime grid shift / running-bond course change.

Mirrors `web_state_test.py`'s mock-rig harness. The shift moves nothing on the
board; it re-clips the reachable grid and re-validates the saved workspace map.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import httpx
from asgi_lifespan import LifespanManager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import SETTINGS_PATH  # noqa: E402
from web.app import ConsoleAppOptions, create_app  # noqa: E402


def _mock_settings(tmp_path: Path) -> Path:
    data = json.loads(SETTINGS_PATH.read_text())
    data["capture"].update({"width": 640, "height": 480})
    data["correction"]["enabled"] = False
    data["framing"] = {"crops": [], "zoom": 1.0, "pan": [0.5, 0.5]}
    path = tmp_path / "camera_settings.json"
    path.write_text(json.dumps(data))
    return path


def _app(tmp_path: Path):
    return create_app(ConsoleAppOptions(
        mock=True,
        settings_path=_mock_settings(tmp_path),
        workspace_map_path=tmp_path / "workspace_map.json",
        heartbeat_s=0.02,
    ))


def _run(app, scenario):
    async def main():
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                await scenario(client)
    asyncio.run(main())


def test_shift_applies_and_clips_the_far_row(tmp_path):
    app = _app(tmp_path)

    async def scenario(client: httpx.AsyncClient):
        before = (await client.get("/api/state")).json()
        assert before["shift_cm"] == [0.0, 0.0]
        assert before["mode"] == "vertical"

        # Half a Y pitch (7.6 / 2) on the run axis: the running-bond course.
        response = await client.post("/api/shift",
                                     json={"mode": "vertical", "x_cm": 0.0, "y_cm": 3.8})
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["shift_cm"] == [0.0, 3.8]
        # Vertical sits exactly on its Y cap, so a +3.8 cm course loses row 5.
        assert state["requested"] == [7, 6]
        assert state["reachable"] == [7, 5]
        assert state["reachable"] == [state["cols"], state["rows"]]

        # Clearing it restores the full grid with no re-`S`.
        cleared = await client.post("/api/shift",
                                    json={"mode": "vertical", "x_cm": 0.0, "y_cm": 0.0})
        assert cleared.status_code == 200
        assert cleared.json()["reachable"] == [7, 6]

    _run(app, scenario)


def test_shift_refuses_a_mode_that_is_not_latched(tmp_path):
    app = _app(tmp_path)

    async def scenario(client: httpx.AsyncClient):
        response = await client.post("/api/shift",
                                     json={"mode": "horizontal", "x_cm": 3.8, "y_cm": 0.0})
        assert response.status_code == 409
        assert "latch the horizontal grid" in response.text

    _run(app, scenario)


def test_shift_refuses_a_value_that_unseats_the_grid(tmp_path):
    app = _app(tmp_path)

    async def scenario(client: httpx.AsyncClient):
        response = await client.post("/api/shift",
                                     json={"mode": "vertical", "x_cm": 0.0, "y_cm": -50.0})
        assert response.status_code == 409
        assert "grid shift" in response.text.lower() or "no vertical cell" in response.text
        # The rejected shift left the published state untouched.
        assert (await client.get("/api/state")).json()["shift_cm"] == [0.0, 0.0]

    _run(app, scenario)

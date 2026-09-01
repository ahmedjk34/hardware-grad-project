"""Step 4 FastAPI service with one lifespan-owned camera and serial rig."""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from camera.camera_feed import SETTINGS_PATH
from rig.build_controller import BuildController
from rig.build_job import BuildJob
from rig.console_pipeline import ConsolePipeline
from rig.mock_board import MockBoard
from rig.workspace import WORKSPACE_MAP_PATH
from web.routes_command import router as command_router
from web.state import StateModel, build_state


@dataclass(frozen=True)
class ConsoleAppOptions:
    """Construction options, kept explicit so tests never patch real serial."""

    mock: bool = False
    mode: str | None = None
    settings_path: Path = SETTINGS_PATH
    workspace_map_path: Path = WORKSPACE_MAP_PATH
    heartbeat_s: float = 10.0
    driver_hz: float = 20.0
    build_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.heartbeat_s <= 0 or self.driver_hz <= 0:
            raise ValueError("heartbeat_s and driver_hz must be positive")


def _is_mock(options: ConsoleAppOptions) -> bool:
    return options.mock or os.environ.get("RIG_MOCK") == "1"


def _state_payload(app: FastAPI) -> dict:
    # This output is already JSON-compatible for the frame-free model and
    # works with the Pydantic versions supplied by the development/Pi setup.
    return {"type": "state", "state": build_state(app).dict()}


async def _notify_state(app: FastAPI) -> None:
    """Wake WebSocket waiters after state changes on the application loop."""
    app.state.revision += 1
    app.state.changed.set()


async def _drive_pipeline(app: FastAPI, pipeline: ConsolePipeline,
                          job: BuildJob, interval_s: float) -> None:
    """Own the synchronous frame work without blocking HTTP/WebSocket traffic."""
    try:
        while True:
            # ``process_once`` reads the latest frame from a non-blocking pump;
            # detector work is already on its own workers.  Keep this small
            # coordinator on the owner loop until profiling a real Pi says
            # otherwise, rather than constructing camera/OpenCV state on an
            # arbitrary executor thread.
            frame = pipeline.process_once()
            outcome = job.poll()
            if frame is not None:
                app.state.latest_frame = frame
            if frame is not None or outcome is not None:
                await _notify_state(app)
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        raise


def create_app(options: ConsoleAppOptions | None = None) -> FastAPI:
    """Create a service whose lifespan owns exactly one pipeline and one Rig."""
    options = options or ConsoleAppOptions()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()
        app.state.changed = asyncio.Event()
        app.state.revision = 0
        app.state.latest_frame = None
        app.state.log = deque(maxlen=200)
        app.state.log_revision = 0
        app.state.views = {"grid": True, "detect": True, "paper": False,
                           "overlay": True}
        app.state.driver = None
        app.state.mock_board = None

        def signal_change() -> None:
            """Thread-safe signal used by serial callbacks and test hooks."""
            loop.call_soon_threadsafe(_schedule_notification, app)

        def _schedule_notification(target: FastAPI) -> None:
            target.state.revision += 1
            target.state.changed.set()

        def on_line(line: str) -> None:
            app.state.log.append(str(line))
            app.state.log_revision += 1
            signal_change()

        def on_error(message: str) -> None:
            app.state.log.append(str(message))
            app.state.log_revision += 1
            signal_change()

        app.state.signal_change = signal_change
        mock = _is_mock(options)
        pipeline = ConsolePipeline(
            camera_backend="mock" if mock else "auto",
            settings_path=options.settings_path,
            workspace_map_path=options.workspace_map_path,
            mode=options.mode,
        )
        board = MockBoard(build_seconds=options.build_seconds) if mock else None
        from rig.link import Rig  # Import after configuration, never monkeypatch it.
        rig = Rig(
            on_line=on_line,
            on_error=on_error,
            mode=options.mode,
            serial_factory=(lambda *_args, **_kwargs: board) if board else None,
        )
        controller = BuildController(rig, level=0)
        job = BuildJob(controller, timeout=300.0)
        app.state.pipeline = pipeline
        app.state.rig = rig
        app.state.controller = controller
        app.state.job = job
        app.state.mock_board = board

        try:
            # Startup runs before the ASGI server accepts requests.  Keep this
            # on the owner thread: OpenCV/camera setup is not generally safe
            # to construct in an executor thread, while frame processing below
            # is explicitly offloaded.
            pipeline.start()
            # This occurs before the ASGI server accepts traffic.  It can wait
            # for the Mega's boot banner without exposing a half-owned rig.
            rig.connect(home_before_configure=(rig.grid.mode == "horizontal"))
            app.state.driver = asyncio.create_task(
                _drive_pipeline(app, pipeline, job, 1.0 / options.driver_hz),
                name="console-pipeline-driver",
            )
            await _notify_state(app)
            yield
        finally:
            driver = app.state.driver
            if driver is not None:
                driver.cancel()
                with suppress(asyncio.CancelledError):
                    await driver
            # Do not close serial under an in-flight build.  The worker may
            # be slow, but its outcome is needed before it is safe to close.
            job.join()
            pipeline.stop()
            rig.close()

    app = FastAPI(title="Rig operator console", lifespan=lifespan)
    app.state.options = options

    @app.get("/api/state", response_model=StateModel)
    async def get_state() -> StateModel:
        return build_state(app)

    app.include_router(command_router)

    @app.websocket("/api/events")
    async def events(socket: WebSocket) -> None:
        await socket.accept()
        sent_revision = app.state.revision
        sent_log_revision = app.state.log_revision
        try:
            await socket.send_json(_state_payload(app))
            while True:
                try:
                    await asyncio.wait_for(app.state.changed.wait(), options.heartbeat_s)
                except TimeoutError:
                    await socket.send_json({"type": "heartbeat"})
                    continue
                app.state.changed.clear()
                revision = app.state.revision
                log_revision = app.state.log_revision
                if revision != sent_revision:
                    await socket.send_json(_state_payload(app))
                    sent_revision = revision
                if log_revision != sent_log_revision:
                    for line in tuple(app.state.log):
                        await socket.send_json({"type": "log", "line": line})
                    sent_log_revision = log_revision
        except WebSocketDisconnect:
            return

    return app


app = create_app()


def main(argv: list[str] | None = None) -> None:
    """Run one process only; production deliberately never enables reload."""
    parser = argparse.ArgumentParser(description="Rig operator console backend")
    parser.add_argument("--mock", action="store_true", help="use MockCamera and MockBoard")
    parser.add_argument("--mode", choices=("vertical", "horizontal"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    import uvicorn

    uvicorn.run(create_app(ConsoleAppOptions(mock=args.mock, mode=args.mode)),
                host=args.host, port=args.port)


if __name__ == "__main__":
    main()

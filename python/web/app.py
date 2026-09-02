"""Step 4 FastAPI service with one lifespan-owned camera and serial rig.

Two things this file is shaped around, both about not making the operator wait
for the wrong thing:

**The serial stream is the important one.** The firmware reports every build
phase (`@n STEP ...`), and those events, the raw serial lines and the terminal
result go out immediately, ahead of any pending camera state. `web/events.py`
owns that priority; this file only decides what to publish and when.

**The camera must not own the event loop.** `ConsolePipeline.process_once()` is
synchronous OpenCV work and `cv2.imencode` is more of it, so both run on ONE
dedicated worker thread — not the default executor, and not the loop. One
thread, because `AGENTS.md` §7 says the pipeline has exactly one owner and a
pool would hand its camera state to whichever thread was free. The loop is then
free for serial callbacks, WebSocket sends, HTTP responses and heartbeats.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
import os
from pathlib import Path
import time
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from camera.camera_feed import SETTINGS_PATH
from rig.build_controller import BuildController
from rig.build_job import BuildJob
from rig.console_pipeline import ConsolePipeline
from rig.mock_board import MockBoard
from rig.workspace import WORKSPACE_MAP_PATH
from web.events import EventHub, now_ms
from web.mjpeg import encode_jpeg, publish_encoded, router as mjpeg_router
from web.progress import BuildProgressTracker
from web.routes_command import router as command_router
from web.routes_calibration import router as calibration_router
from web.state import StateModel, build_state


#: The state fields that make a snapshot MEAN something different. Camera
#: geometry and frame age are deliberately absent: they change on every frame
#: and would make "did anything happen?" always true. They still reach the
#: browser, but on the throttle below rather than at the driver's full rate.
_SEMANTIC_FIELDS = (
    "mode", "cols", "rows", "calibrated", "selected", "command", "level",
    "build_state", "locked_reason", "camera", "last_result",
    "last_result_reason", "build_command_seq", "build_step",
    "build_total_steps", "build_phase", "build_phase_status",
    "build_release_confirmed", "views",
)


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
    #: How often a snapshot whose only change is camera geometry may go out.
    #: The driver still runs at `driver_hz` for the MJPEG stream; this is the
    #: rate at which the browser is told about new polygons. A semantic change
    #: — a selection, a build phase, a result — ignores it entirely.
    geometry_hz: float = 5.0

    def __post_init__(self) -> None:
        if self.heartbeat_s <= 0 or self.driver_hz <= 0:
            raise ValueError("heartbeat_s and driver_hz must be positive")
        if self.geometry_hz <= 0:
            raise ValueError("geometry_hz must be positive")


def _is_mock(options: ConsoleAppOptions) -> bool:
    return options.mock or os.environ.get("RIG_MOCK") == "1"


def _semantic_signature(payload: dict) -> tuple:
    return tuple(repr(payload.get(field)) for field in _SEMANTIC_FIELDS)


def publish_state(app, *, force: bool = False) -> bool:
    """Publish a state snapshot if it is worth one. True when it went out.

    Three cases:

    * something semantic changed — always published, immediately;
    * only the camera moved — published at most `geometry_hz` times a second,
      and coalesced per client on top of that, so a slow phone only ever holds
      the newest one;
    * nothing changed at all and the throttle has not elapsed — nothing sent.

    `force` is for the moments a caller KNOWS matter and does not want to
    reason about the signature: a serial phase, a settled build, the reply to
    a command route.
    """
    payload = build_state(app).dict()
    signature = _semantic_signature(payload)
    changed = signature != app.state.state_signature
    now = time.monotonic()
    if not (force or changed):
        if now - app.state.state_published_at < app.state.geometry_min_interval:
            return False
    app.state.state_signature = signature
    app.state.state_published_at = now
    app.state.hub.publish_state(payload)
    return True


async def _notify_state(app: FastAPI) -> None:
    """Publish the current state after a change made on the application loop."""
    app.state.revision += 1
    publish_state(app, force=True)


async def _drive_pipeline(app: FastAPI, pipeline: ConsolePipeline,
                          job: BuildJob, interval_s: float,
                          executor: ThreadPoolExecutor) -> None:
    """Own the synchronous frame work without blocking HTTP/WebSocket traffic."""
    loop = asyncio.get_running_loop()
    try:
        while True:
            # Both of these are blocking OpenCV work and both go to the SAME
            # single-threaded executor, so the pipeline still has exactly one
            # owner thread (AGENTS.md §7) and the loop stays free for serial
            # callbacks while a frame is being remapped or encoded.
            frame = await loop.run_in_executor(executor, pipeline.process_once)
            outcome = job.poll()
            if frame is not None:
                app.state.latest_frame = frame
                if app.state.stream_subscribers > 0:
                    jpeg = await loop.run_in_executor(executor, encode_jpeg, frame)
                    await publish_encoded(app, frame, jpeg)
            if outcome is not None:
                # A settled build is semantic; a new frame is only geometry.
                _publish_build_result(app, outcome)
                await _notify_state(app)
            elif frame is not None:
                publish_state(app)
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        raise


def _publish_build_result(app: FastAPI, outcome) -> None:
    """One settled build, as the one event that may say 'placed'.

    The terminal `@n OK` has already gone past as a `serial` event, so this is
    ordered after it and after every phase — which is what makes "the STEPs
    came before the result" true on the wire as well as on the cable.

    The outcome comes from `BuildJob`, not from the ack, because the ack alone
    cannot say whether the CONTROLLER locked: a rejection is retryable, an
    abort is not, and only `BuildController` decides which happened.
    """
    controller = app.state.controller
    result = outcome.result
    locked = bool(outcome.locked or controller.locked)
    reason = None
    if result is not None:
        reason = result.reason or None
    elif outcome.error is not None:
        reason = str(outcome.error)
    event = app.state.hub.publish("build_result", {
        "command_seq": app.state.progress.progress.command_seq,
        "result": str(result) if result is not None else None,
        "reason": reason,
        "locked": locked,
        "locked_reason": controller.locked_reason,
        # True when `Rig` had to read the prose because no ack arrived. Worth
        # surfacing: it is the evidence `plans/ack-protocol.md` wants before
        # the fallback can be deleted.
        "from_prose": bool(getattr(result, "from_prose", False)),
    })
    app.state.progress.on_result(result, event.event_id, locked=locked)


def create_app(options: ConsoleAppOptions | None = None) -> FastAPI:
    """Create a service whose lifespan owns exactly one pipeline and one Rig."""
    options = options or ConsoleAppOptions()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()
        app.state.revision = 0
        app.state.latest_frame = None
        app.state.log = deque(maxlen=200)
        app.state.stream_subscribers = 0
        app.state.latest_jpeg = None
        app.state.jpeg_revision = 0
        app.state.jpeg_encode_count = 0
        app.state.jpeg_condition = asyncio.Condition()
        app.state.views = {"grid": True, "detect": True, "paper": False,
                           "overlay": True}
        app.state.driver = None
        app.state.mock_board = None
        app.state.calibration_points = []
        app.state.hub = EventHub()
        app.state.progress = BuildProgressTracker()
        app.state.state_signature = None
        app.state.state_published_at = 0.0
        app.state.geometry_min_interval = 1.0 / options.geometry_hz

        def _serial_line(line: str) -> None:
            """On the loop. One raw line: the log AND one durable event.

            The log deque stays because `RigLog` still shows every raw line,
            acks included, and because a client that connects after the buffer
            has rolled needs SOMETHING. What has gone is re-sending the whole
            deque on every new line: each line is now one event with one id,
            delivered once.
            """
            app.state.log.append(line)
            app.state.hub.publish("serial", {"line": line, "stream": "rig"})

        def _serial_error(message: str) -> None:
            app.state.log.append(message)
            app.state.hub.publish("serial", {"line": message, "stream": "error"})
            publish_state(app, force=True)

        def _serial_progress(progress) -> None:
            """On the loop. One build phase, straight out to every client."""
            event = app.state.hub.publish("build_step", {
                "command_seq": progress.seq,
                "step": progress.step,
                "total": progress.total,
                "phase": progress.phase,
                "label": progress.label,
                "action": progress.action,
                "status": progress.status,
                "eta_ms": progress.eta_ms,
            })
            app.state.progress.on_progress(progress, event.event_id)
            publish_state(app, force=True)

        def _serial_ack(ack) -> None:
            """On the loop. RECV moves the tracker; everything else is logged."""
            if app.state.progress.on_ack(ack, app.state.hub.last_event_id) is not None:
                publish_state(app, force=True)

        # The reader thread must never touch the hub, the tracker or the log:
        # they are the loop's. Hopping each callback across with
        # `call_soon_threadsafe` preserves the order the lines arrived in,
        # which is the only reason "the phases came before the result" holds.
        def on_line(line: str) -> None:
            loop.call_soon_threadsafe(_serial_line, str(line))

        def on_error(message: str) -> None:
            loop.call_soon_threadsafe(_serial_error, str(message))

        def on_progress(progress) -> None:
            loop.call_soon_threadsafe(_serial_progress, progress)

        def on_ack(ack) -> None:
            loop.call_soon_threadsafe(_serial_ack, ack)

        def signal_change() -> None:
            """Thread-safe 'publish the current state now', for routes and tests."""
            loop.call_soon_threadsafe(_schedule_notification, app)

        def _schedule_notification(target: FastAPI) -> None:
            target.state.revision += 1
            publish_state(target, force=True)

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
            on_progress=on_progress,
            on_ack=on_ack,
            mode=options.mode,
            serial_factory=(lambda *_args, **_kwargs: board) if board else None,
        )
        controller = BuildController(rig, level=0)
        job = BuildJob(controller, timeout=300.0)
        executor = ThreadPoolExecutor(max_workers=1,
                                      thread_name_prefix="console-pipeline")
        app.state.pipeline = pipeline
        app.state.rig = rig
        app.state.controller = controller
        app.state.job = job
        app.state.mock_board = board
        app.state.pipeline_executor = executor

        try:
            # Startup runs before the ASGI server accepts requests.  Keep this
            # on the owner thread: OpenCV/camera setup is not generally safe
            # to construct in an executor thread, while frame processing below
            # is explicitly offloaded to one dedicated worker.
            pipeline.start()
            # This occurs before the ASGI server accepts traffic.  It can wait
            # for the Mega's boot banner without exposing a half-owned rig.
            rig.connect(home_before_configure=(rig.grid.mode == "horizontal"))
            app.state.driver = asyncio.create_task(
                _drive_pipeline(app, pipeline, job, 1.0 / options.driver_hz,
                                executor),
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
            # After the pipeline: the worker may still be inside process_once.
            executor.shutdown(wait=True)

    app = FastAPI(title="Rig operator console", lifespan=lifespan)
    app.state.options = options

    @app.get("/api/state", response_model=StateModel)
    async def get_state() -> StateModel:
        return build_state(app)

    app.include_router(command_router)
    app.include_router(calibration_router)
    app.include_router(mjpeg_router)

    @app.websocket("/api/events")
    async def events(socket: WebSocket) -> None:
        """One client's stream: current truth, then replay, then live events.

        Connect with `?after=<last event_id you saw>` to resume. The client
        deduplicates by id, so a replay that overlaps what it already has is
        free — which is why this replays generously instead of trying to be
        clever about text overlap, the way the old log-deque replay had to.
        """
        await socket.accept()
        hub = app.state.hub
        raw_after = socket.query_params.get("after")
        try:
            after_id = int(raw_after) if raw_after is not None else None
        except ValueError:
            after_id = None

        subscriber = hub.subscribe()
        try:
            # 1. The current semantic state, including the build progress. A
            #    page opened mid-build starts knowing there IS a build and
            #    which phase it is in, rather than starting blank.
            await socket.send_json(hub.mint("state", {
                "state": build_state(app).dict()}).to_json())

            # 2. What happened while this client was away — or, on a first
            #    connect, whatever is still in the buffer, so the log and the
            #    phases so far are there. One envelope rather than N frames:
            #    a reconnect mid-build can be hundreds of lines.
            missed = hub.replay_since(after_id)
            oldest = hub.oldest_replay_id
            await socket.send_json({
                "type": "replay",
                "event_id": hub.last_event_id,
                "at": missed[-1].at if missed else now_ms(),
                "events": [event.to_json() for event in missed],
                # True when `after` predates the buffer: this client has a hole
                # it can never fill, and should say so rather than pretend the
                # log is continuous.
                "gap": bool(after_id is not None and oldest is not None
                            and after_id + 1 < oldest),
            })

            # 3. Live. Durable events first, the newest state second, a
            #    heartbeat when neither has anything to say.
            while True:
                if not await subscriber.wait(options.heartbeat_s):
                    await socket.send_json(hub.mint("heartbeat").to_json())
                    continue
                while True:
                    event = subscriber.take()
                    if event is None:
                        break
                    await socket.send_json(event.to_json())
        except WebSocketDisconnect:
            return
        finally:
            hub.unsubscribe(subscriber)

    # Register the catch-all only after REST and WebSocket routes, otherwise a
    # StaticFiles mount would try to handle the WebSocket handshake as HTTP.
    static_dir = Path(__file__).resolve().parents[2] / "web" / "dist"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

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

    # Browsers accumulate cookies across every dev server on localhost, and a
    # fat Cookie header makes h11's 16 KiB default answer 431 before the app
    # ever sees the request.  The console is LAN-local; give it room.
    uvicorn.run(create_app(ConsoleAppOptions(mock=args.mock, mode=args.mode)),
                host=args.host, port=args.port,
                h11_max_incomplete_event_size=256 * 1024)


if __name__ == "__main__":
    main()

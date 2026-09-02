"""Shared-latest raw MJPEG stream; browser overlays remain client-side."""

from __future__ import annotations

import cv2
from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse


router = APIRouter(prefix="/api", tags=["stream"])


def encode_jpeg(frame) -> bytes | None:
    """The blocking half: one JPEG for all viewers, or None if it failed.

    Split from the publish so the caller can run it on the pipeline worker
    thread. Encoding a 1296x972 frame twenty times a second on the event
    loop is enough to make a serial callback wait behind a picture, which is
    the one thing `web/events.py` exists to prevent.
    """
    ok, encoded = cv2.imencode(".jpg", frame.view, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return encoded.tobytes() if ok else None


async def publish_encoded(app, frame, jpeg: bytes | None) -> None:
    """Hand an already-encoded frame to the waiting stream readers."""
    if jpeg is None:
        return
    async with app.state.jpeg_condition:
        app.state.latest_jpeg = (frame.sequence, jpeg)
        app.state.jpeg_revision += 1
        app.state.jpeg_encode_count += 1
        app.state.jpeg_condition.notify_all()


def _part(jpeg: bytes) -> bytes:
    return (b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            + f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii")
            + jpeg + b"\r\n")


@router.get("/stream.mjpg")
async def stream(request: Request):
    """Fan out the newest raw corrected frame without per-client buffering."""
    app = request.app

    async def parts():
        app.state.stream_subscribers += 1
        revision = -1
        try:
            while True:
                async with app.state.jpeg_condition:
                    await app.state.jpeg_condition.wait_for(
                        lambda: (app.state.latest_jpeg is not None
                                 and app.state.jpeg_revision != revision))
                    sequence, jpeg = app.state.latest_jpeg
                    revision = app.state.jpeg_revision
                # ``sequence`` is intentionally not exposed as a protocol
                # header: this is standard raw MJPEG, not a video/control API.
                del sequence
                yield _part(jpeg)
        finally:
            app.state.stream_subscribers = max(0, app.state.stream_subscribers - 1)

    return StreamingResponse(parts(), media_type="multipart/x-mixed-replace; boundary=frame")

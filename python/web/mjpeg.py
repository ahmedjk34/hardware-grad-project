"""Shared-latest raw MJPEG stream; browser overlays remain client-side."""

from __future__ import annotations

import cv2
from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse


router = APIRouter(prefix="/api", tags=["stream"])


async def publish_jpeg(app, frame) -> None:
    """Encode once for all active viewers, never when nobody is watching."""
    if app.state.stream_subscribers <= 0:
        return
    ok, encoded = cv2.imencode(
        ".jpg", frame.view, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        return
    async with app.state.jpeg_condition:
        app.state.latest_jpeg = (frame.sequence, encoded.tobytes())
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

#!/usr/bin/env python3
"""Prove a blocked camera read cannot block the UI-side frame snapshot.

No camera is needed.  The fake source waits exactly like a stuck CSI capture
would; the test keeps polling the pump while that read is still blocked.
"""

from pathlib import Path
import sys
import threading
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.rig_build_v1 import camera_is_live  # noqa: E402
from vision.camera_source import FrameSnapshot, LatestFramePump  # noqa: E402


PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:54} {detail}")


class BlockingCamera:
    """Returns one frame only after the test explicitly releases its read()."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def read(self):
        self.calls += 1
        self.entered.set()
        self.release.wait(5.0)
        self.release.clear()
        return True, np.full((3, 4, 3), self.calls, dtype=np.uint8)


camera = BlockingCamera()
pump = LatestFramePump(camera)
pump.start()
check("capture worker entered its blocking read", camera.entered.wait(1.0))

# This is what the OpenCV loop needs during a motor/camera fault: snapshot()
# stays prompt even though the only call to source.read() is still waiting.
start = time.monotonic()
snapshots = [pump.snapshot() for _ in range(1000)]
elapsed = time.monotonic() - start
check("UI snapshots stay non-blocking during stalled capture", elapsed < 0.1,
      f"{elapsed * 1000:.1f} ms")
check("no frame is invented while camera is blocked",
      all(snapshot.frame is None for snapshot in snapshots))

camera.release.set()
deadline = time.monotonic() + 1.0
snapshot = pump.snapshot()
while snapshot.frame is None and time.monotonic() < deadline:
    time.sleep(0.005)
    snapshot = pump.snapshot()
check("completed capture becomes visible to UI", snapshot.frame is not None)
check("completed capture increments sequence", snapshot.sequence == 1,
      str(snapshot.sequence))
check("frame timestamp supports a stale-age warning", snapshot.age_s() is not None)

now = time.monotonic()
check("fresh camera snapshot permits camera-based controls",
      camera_is_live(FrameSnapshot(None, now, 1, None), now))
check("stale camera snapshot blocks camera-based controls",
      not camera_is_live(FrameSnapshot(None, now - 1.0, 1, None), now))

# The worker is now blocked in its next read.  Releasing it lets stop() join
# cleanly rather than relying on daemon-process shutdown.
camera.release.set()
check("pump stops after its read returns", pump.stop(1.0))

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

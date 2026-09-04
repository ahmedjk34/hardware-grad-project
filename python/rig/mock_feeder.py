"""Pyserial-shaped protocol-2 Uno simulator used by feeder/web tests."""

from __future__ import annotations

import queue
import threading
import time


class MockFeeder:
    def __init__(self, feed_seconds: float = 0.05):
        self.is_open = True
        self.feed_seconds = feed_seconds
        self.writes: list[str] = []
        self.timeline: list[str] = []
        self._rx: queue.Queue[bytes] = queue.Queue()
        self._failure: str | None = None
        self._disconnect = False
        self._reset = False
        self._cancel = threading.Event()
        self._active_id: int | None = None
        self._rx.put(b"@0 READY firmware=belt_v1 protocol=2 board=uno\n")

    @property
    def in_waiting(self):
        return self._rx.qsize()

    def fail_next(self, reason: str):
        self._failure = reason

    def disconnect_next(self):
        self._disconnect = True

    def reset_next(self):
        self._reset = True

    def write(self, data: bytes):
        line = data.decode("ascii").strip()
        self.writes.append(line)
        self.timeline.append(line)
        if line.startswith("FEED "):
            request_id = int(line.split()[1])
            self._active_id = request_id
            self._cancel.clear()
            threading.Thread(target=self._finish_feed, args=(request_id,),
                             name="mock-feeder", daemon=True).start()
        elif line == "STOP":
            self._cancel.set()
        elif line == "STATUS":
            self._emit("@0 STATUS state=idle active=0 belt=stopped container=closed")
        return len(data)

    def flush(self):
        return None

    def _emit(self, line: str):
        self.timeline.append(line)
        self._rx.put((line + "\n").encode("ascii"))

    def _finish_feed(self, request_id: int):
        self._emit(f"@{request_id} RECV cmd=FEED")
        self._emit(f"@{request_id} ACK cmd=FEED accepted=1")
        for state in ("closing", "waiting_for_exit", "moving_to_stage",
                      "aligning", "verifying_stage"):
            if self._cancel.wait(self.feed_seconds / 6):
                self._emit(f"@{request_id} STATE state=idle")
                self._emit(f"@{request_id} ERROR state=idle reason=cancelled")
                return
            self._emit(f"@{request_id} STATE state={state}")
        if self._disconnect:
            self._disconnect = False
            self.close()
            return
        if self._reset:
            self._reset = False
            self._emit("@0 READY firmware=belt_v1 protocol=2 board=uno")
            return
        if self._failure:
            reason, self._failure = self._failure, None
            self._emit(f"@{request_id} ERROR state=fault reason={reason}")
            return
        self._emit(f"@{request_id} STATE state=block_ready")
        self._emit(f"@{request_id} OK state=block_ready result=staged")

    def readline(self):
        if not self.is_open:
            raise OSError("mock feeder disconnected")
        try:
            return self._rx.get(timeout=0.02)
        except queue.Empty:
            return b""

    def close(self):
        self.is_open = False


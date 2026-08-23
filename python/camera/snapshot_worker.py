"""One bounded background writer for camera snapshots."""

from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class SnapshotResult:
    busy: bool
    result: object | None
    error: str | None
    completed_count: int


class SnapshotWorker:
    """Execute at most one queued snapshot after the active write.

    ``submit`` returns ``False`` while a write or queued request already
    exists, preventing repeated key presses from creating unbounded image
    copies or disk writers.
    """

    def __init__(self, writer, *, name="snapshot-writer"):
        self._writer = writer
        self._name = name
        self._condition = threading.Condition()
        self._pending = None
        self._busy = False
        self._stop = False
        self._completed_count = 0
        self._result = None
        self._error = None
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, *args, **kwargs):
        with self._condition:
            if self._stop or self._busy or self._pending is not None:
                return False
            self._pending = (args, kwargs)
            self._condition.notify()
            return True

    def snapshot(self):
        with self._condition:
            return SnapshotResult(self._busy or self._pending is not None,
                                  self._result, self._error,
                                  self._completed_count)

    def stop(self, timeout=5.0, *, finish=True):
        with self._condition:
            self._stop = True
            if not finish:
                self._pending = None
            self._condition.notify_all()
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run(self):
        while True:
            with self._condition:
                while self._pending is None and not self._stop:
                    self._condition.wait()
                if self._pending is None and self._stop:
                    return
                args, kwargs = self._pending
                self._pending = None
                self._busy = True

            result = None
            error = None
            try:
                result = self._writer(*args, **kwargs)
            except Exception as exc:
                error = f"snapshot failed: {exc}"

            with self._condition:
                self._busy = False
                self._completed_count += 1
                self._result = result
                self._error = error
                if self._stop and self._pending is None:
                    return

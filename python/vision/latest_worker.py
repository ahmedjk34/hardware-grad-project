"""Generic latest-request-only worker for expensive replaceable values."""

from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class ValueSnapshot:
    generation: int
    value: object | None
    error: str | None
    completed_count: int
    replaced_count: int


class LatestValueWorker:
    def __init__(self, function, *, name="latest-value-worker"):
        self._function = function
        self._condition = threading.Condition()
        self._pending = None
        self._stop = False
        self._completed = 0
        self._replaced = 0
        self._result = ValueSnapshot(0, None, None, 0, 0)
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, generation, *args, **kwargs):
        with self._condition:
            if self._stop:
                return False
            if self._pending is not None:
                self._replaced += 1
            self._pending = (int(generation), args, kwargs)
            self._condition.notify()
            return True

    def snapshot(self):
        with self._condition:
            result = self._result
            return ValueSnapshot(result.generation, result.value, result.error,
                                 self._completed, self._replaced)

    def stop(self, timeout=5.0):
        with self._condition:
            self._stop = True
            self._pending = None
            self._condition.notify_all()
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run(self):
        while True:
            with self._condition:
                while self._pending is None and not self._stop:
                    self._condition.wait()
                if self._stop:
                    return
                generation, args, kwargs = self._pending
                self._pending = None
            value = None
            error = None
            try:
                value = self._function(*args, **kwargs)
            except Exception as exc:
                error = f"background rebuild failed: {exc}"
            with self._condition:
                self._completed += 1
                self._result = ValueSnapshot(
                    generation, value, error, self._completed, self._replaced)

"""Latest-only background analysis for responsive live camera previews."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class AnalysisSnapshot:
    detections: tuple
    source_sequence: int
    map_generation: int
    submitted_at: float | None
    completed_at: float | None
    duration_s: float
    rate_hz: float
    error: str | None
    completed_count: int
    replaced_count: int
    duplicate_count: int

    def age_s(self, now: float | None = None) -> float | None:
        if self.completed_at is None:
            return None
        return max(0.0, (time.monotonic() if now is None else now)
                   - self.completed_at)

    def is_current(self, generation: int) -> bool:
        """Whether this completed result belongs to the active map geometry."""
        return (self.completed_at is not None
                and self.map_generation == int(generation))


@dataclass(frozen=True)
class _Request:
    frame: object
    sequence: int
    generation: int
    submitted_at: float
    kwargs: dict


class AnalysisWorker:
    """Run an analyzer at a capped rate and keep only the newest request.

    Ownership of the submitted frame transfers to the worker. Callers should
    submit the unmodified corrected image and draw overlays on a separate copy.
    Replacing queued work is deliberate: old camera frames have no value to a
    live preview.
    """

    def __init__(self, analyzer, *, max_hz=10.0, name="camera-analysis"):
        if max_hz <= 0:
            raise ValueError("max_hz must be positive")
        self._analyzer = analyzer
        self._interval = 1.0 / float(max_hz)
        self._name = name
        self._condition = threading.Condition()
        self._stop = False
        self._pending: _Request | None = None
        self._thread: threading.Thread | None = None
        self._completed_count = 0
        self._replaced_count = 0
        self._duplicate_count = 0
        self._newest_key = None
        self._last_completed_at = None
        self._rate_hz = 0.0
        self._result = AnalysisSnapshot(
            (), 0, 0, None, None, 0.0, 0.0, None, 0, 0, 0)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        with self._condition:
            self._stop = False
            self._newest_key = None
        self._thread = threading.Thread(target=self._run, name=self._name,
                                        daemon=True)
        self._thread.start()

    def submit(self, frame, sequence, generation=0, **kwargs):
        request = _Request(frame, int(sequence), int(generation),
                           time.monotonic(), dict(kwargs))
        with self._condition:
            if self._stop:
                return False
            key = (request.sequence, request.generation)
            if key == self._newest_key:
                self._duplicate_count += 1
                return False
            if self._pending is not None:
                self._replaced_count += 1
            self._pending = request
            self._newest_key = key
            self._condition.notify()
        return True

    def snapshot(self):
        with self._condition:
            result = self._result
            # Counts may advance after the most recent completed result.
            return AnalysisSnapshot(
                result.detections, result.source_sequence,
                result.map_generation, result.submitted_at,
                result.completed_at, result.duration_s, self._rate_hz, result.error,
                self._completed_count, self._replaced_count,
                self._duplicate_count)

    def stop(self, timeout=2.0):
        with self._condition:
            self._stop = True
            self._pending = None
            self._condition.notify_all()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return not self.running

    def _run(self):
        last_started = 0.0
        while True:
            with self._condition:
                while not self._stop and self._pending is None:
                    self._condition.wait()
                if self._stop:
                    return

                deadline = last_started + self._interval
                delay = deadline - time.monotonic()
                while delay > 0 and not self._stop:
                    self._condition.wait(delay)
                    delay = deadline - time.monotonic()
                    if self._stop:
                        return
                    # A newer submit may have replaced the request while the
                    # rate limiter waited. Read it only after that wait.
                request = self._pending
                self._pending = None

            if request is None:
                continue
            started = time.monotonic()
            last_started = started
            error = None
            try:
                detections = tuple(self._analyzer(request.frame,
                                                  **request.kwargs))
            except Exception as exc:  # analysis must never kill the preview
                detections = ()
                error = f"analysis failed: {exc}"
            completed = time.monotonic()
            with self._condition:
                if self._last_completed_at is not None:
                    dt = completed - self._last_completed_at
                    if dt > 0:
                        instant = 1.0 / dt
                        self._rate_hz = (0.85 * self._rate_hz + 0.15 * instant
                                         if self._rate_hz else instant)
                self._last_completed_at = completed
                self._completed_count += 1
                self._result = AnalysisSnapshot(
                    detections, request.sequence, request.generation,
                    request.submitted_at, completed, completed - started,
                    self._rate_hz, error, self._completed_count,
                    self._replaced_count, self._duplicate_count)

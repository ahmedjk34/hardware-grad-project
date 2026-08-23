"""Cheap rolling rates and stage timings for live camera dashboards."""

from __future__ import annotations

import time


class RateMeter:
    def __init__(self, smoothing=0.15):
        self.smoothing = float(smoothing)
        self.rate = 0.0
        self._last_at = None
        self.count = 0

    def tick(self, now=None):
        now = time.perf_counter() if now is None else now
        if self._last_at is not None:
            dt = now - self._last_at
            if dt > 0:
                instant = 1.0 / dt
                self.rate = ((1.0 - self.smoothing) * self.rate
                             + self.smoothing * instant) if self.rate else instant
        self._last_at = now
        self.count += 1
        return self.rate


class StageTimings:
    def __init__(self, smoothing=0.15):
        self.smoothing = float(smoothing)
        self.ms = {}

    def observe(self, name, elapsed_s):
        value = max(0.0, float(elapsed_s) * 1000.0)
        old = self.ms.get(name)
        self.ms[name] = (value if old is None else
                         (1.0 - self.smoothing) * old + self.smoothing * value)
        return self.ms[name]

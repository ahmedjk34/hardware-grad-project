"""The Raspberry Pi-owned physical handoff: Uno FEED, then Mega BUILD."""

from __future__ import annotations

import threading

from rig.feeder import FeedResult, FeederError
from rig.link import ABORTED, PLACED, BuildResult, RigError


class CellError(RigError):
    """A complete cell placement is unsafe/unknown and must not be retried."""


class CellOrchestrator:
    """Serialize the shared pickup resource across the two independent boards."""

    def __init__(self, feeder, gantry, *, feed_timeout: float = 45.0,
                 on_phase=None):
        self.feeder = feeder
        self.gantry = gantry
        self.feed_timeout = float(feed_timeout)
        self._operation = threading.Lock()
        self._on_phase = on_phase
        self.phase = "idle"
        self.last_feed: FeedResult | None = None
        self.locked_reason: str | None = None

    def _phase(self, value: str) -> None:
        self.phase = value
        if self._on_phase is not None:
            self._on_phase(value)

    def _abort(self, reason: str) -> BuildResult:
        self.locked_reason = reason
        self._phase("error")
        return BuildResult(ABORTED, reason)

    def place_block(self, col: int, row: int, level: int,
                    timeout: float = 300.0) -> BuildResult:
        if self.locked_reason is not None:
            raise CellError(
                f"cell orchestrator is locked: {self.locked_reason}; restart after inspection")
        if not self._operation.acquire(blocking=False):
            raise CellError("another physical cell operation already owns the pickup area")
        staged = False
        try:
            self._phase("feeding")
            try:
                self.last_feed = self.feeder.feed(timeout=self.feed_timeout)
            except FeederError as exc:
                return self._abort(
                    f"feeder did not safely stage a block: {exc}; "
                    "pickup state requires inspection",
                )
            staged = True
            self._phase("ready_for_pick")
            try:
                self._phase("placing")
                result = self.gantry.build(col, row, level, timeout=timeout)
            except RigError as exc:
                return self._abort(
                    f"gantry failed after feeder staged transaction "
                    f"{self.last_feed.request_id}; pickup/claw state is unknown: {exc}",
                )
            if str(result) != PLACED:
                # SAFE on the Mega means no gantry movement, but a block was
                # already staged; another FEED would intentionally double-load.
                return self._abort(
                    f"gantry returned {result} after feeder staged transaction "
                    f"{self.last_feed.request_id}: {result.reason or 'no reason'}; "
                    "pickup state requires inspection",
                )
            self._phase("complete")
            return result
        finally:
            # `staged` intentionally has no automatic cleanup. Failure after it
            # locks the controller; only a person can establish pickup state.
            _ = staged
            self._operation.release()

    def cancel(self) -> bool:
        """Actively STOP only while Uno owns the physical operation."""
        if self.phase not in {"feeding", "staging"}:
            return False
        self.feeder.stop()
        return True

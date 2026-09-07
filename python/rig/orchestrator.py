"""The Raspberry Pi-owned physical handoff into one Mega BUILD.

Production normally stages with ``Uno FEED``.  The operator console may also
explicitly attest that a block has already been placed in the pickup area; that
manual path skips only the Uno command and keeps the same operation lock and
post-staging safety rules.
"""

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
        """Stage with the Uno, then run the selected Mega placement."""
        if self.locked_reason is not None:
            raise CellError(
                f"cell orchestrator is locked: {self.locked_reason}; restart after inspection")
        if not self._operation.acquire(blocking=False):
            raise CellError("another physical cell operation already owns the pickup area")
        try:
            self._phase("feeding")
            try:
                self.last_feed = self.feeder.feed(timeout=self.feed_timeout)
            except FeederError as exc:
                return self._abort(
                    f"feeder did not safely stage a block: {exc}; "
                    "pickup state requires inspection",
                )
            self._phase("ready_for_pick")
            return self._place_staged_block(
                col, row, level, timeout=timeout,
                staged_description=f"feeder staged transaction {self.last_feed.request_id}",
            )
        finally:
            # No automatic cleanup on a failure after staging: that locks the
            # controller instead, because only a person can establish pickup
            # state at that point.
            self._operation.release()

    def place_manually_staged_block(self, col: int, row: int, level: int,
                                    timeout: float = 300.0) -> BuildResult:
        """Place a block the operator attests is already in the pickup area.

        This is deliberately a separate entry point rather than a fake feeder
        success: no Uno transaction occurred.  Once accepted, however, the
        pickup area is occupied and every Mega failure has the same lockout
        consequence as the automatic path.
        """
        if self.locked_reason is not None:
            raise CellError(
                f"cell orchestrator is locked: {self.locked_reason}; restart after inspection")
        if not self._operation.acquire(blocking=False):
            raise CellError("another physical cell operation already owns the pickup area")
        try:
            self.last_feed = None
            self._phase("ready_for_pick")
            return self._place_staged_block(
                col, row, level, timeout=timeout,
                staged_description="operator-confirmed manual block",
                manual_pick=True,
            )
        finally:
            self._operation.release()

    def _place_staged_block(self, col: int, row: int, level: int, *,
                            timeout: float, staged_description: str,
                            manual_pick: bool = False) -> BuildResult:
        """Run the common Mega half after either staging method succeeded."""
        try:
            self._phase("placing")
            result = self.gantry.build(
                col, row, level, timeout=timeout, manual_pick=manual_pick)
        except RigError as exc:
            return self._abort(
                f"gantry failed after {staged_description}; "
                f"pickup/claw state is unknown: {exc}",
            )
        if str(result) != PLACED:
            # SAFE on the Mega means no gantry movement, but a block was
            # already staged; another feed would intentionally double-load.
            return self._abort(
                f"gantry returned {result} after {staged_description}: "
                f"{result.reason or 'no reason'}; pickup state requires inspection",
            )
        self._phase("complete")
        return result

    def close_manual_pick(self) -> None:
        """Let the explicitly paused manual build close its already-open claw."""
        if self.phase != "awaiting_manual_close":
            raise CellError("the claw is not waiting for a manual close")
        self.gantry.close_manual_pick()
        self._phase("placing")

    def manual_close_ready(self) -> None:
        """Mirror firmware's post-descent pause into the owned cell state."""
        if self.phase == "placing":
            self._phase("awaiting_manual_close")

    def cancel(self) -> bool:
        """Actively STOP only while Uno owns the physical operation."""
        if self.phase not in {"feeding", "staging"}:
            return False
        self.feeder.stop()
        return True

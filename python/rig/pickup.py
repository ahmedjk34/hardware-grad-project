"""Coordinate one manually staged block through the Mega's safe pickup flow."""

from __future__ import annotations

import threading

from rig.link import ABORTED, PLACED, BuildResult, RigError


class PickupError(RigError):
    """A pickup/placement operation is unsafe or physically unknown."""


class PickupCoordinator:
    """Own the pickup area and preserve the explicit ``M`` then ``C`` handshake."""

    def __init__(self, gantry, *, on_phase=None):
        self.gantry = gantry
        self._operation = threading.Lock()
        self._on_phase = on_phase
        self.phase = "idle"
        self.locked_reason: str | None = None

    def _phase(self, value: str) -> None:
        self.phase = value
        if self._on_phase is not None:
            self._on_phase(value)

    def _abort(self, reason: str) -> BuildResult:
        self.locked_reason = reason
        self._phase("error")
        return BuildResult(ABORTED, reason)

    def place_staged_block(self, col: int, row: int, level: int,
                           timeout: float = 300.0) -> BuildResult:
        """Place the block the operator confirmed is at the pickup cell."""
        if self.locked_reason is not None:
            raise PickupError(
                f"pickup coordinator is locked: {self.locked_reason}; restart after inspection")
        if not self._operation.acquire(blocking=False):
            raise PickupError("another physical operation already owns the pickup area")
        try:
            self._phase("manual_staging_confirmed")
            try:
                self._phase("placing")
                result = self.gantry.build(
                    col, row, level, timeout=timeout, manual_pick=True)
            except RigError as exc:
                return self._abort(
                    "gantry failed after operator-confirmed manual staging; "
                    f"pickup/claw state is unknown: {exc}")
            if str(result) != PLACED:
                return self._abort(
                    f"gantry returned {result} after operator-confirmed manual staging: "
                    f"{result.reason or 'no reason'}; pickup state requires inspection")
            self._phase("complete")
            return result
        finally:
            self._operation.release()

    def close_manual_pick(self) -> None:
        """Close only after firmware announced its open-claw alignment pause."""
        if self.phase != "awaiting_manual_close":
            raise PickupError("the claw is not waiting for a manual close")
        self.gantry.close_manual_pick()
        self._phase("placing")

    def manual_close_ready(self) -> None:
        if self.phase == "placing":
            self._phase("awaiting_manual_close")

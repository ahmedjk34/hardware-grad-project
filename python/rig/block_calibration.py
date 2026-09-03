#!/usr/bin/env python3
"""Drive the machine through a placed-block calibration, one cell at a time.

:mod:`vision.block_grid` does the geometry and knows nothing about a rig. This
is the other half: it issues the ``B`` commands, waits for each one to finish,
grabs a frame and hands it to the session. It knows nothing about OpenCV beyond
passing arrays through, and nothing about a UI - the same object backs the web
routes, the CLI tool and the tests.

Why it is step-wise rather than one ``calibrate()`` call
--------------------------------------------------------
A six-cell run is six full pick-and-places, several minutes of motion. A single
blocking call would give an operator no progress, no way to stop after four,
and no way to retry the one placement that landed badly. Each :meth:`step` is
therefore one placement, and everything before and after it is recoverable
state on this object.

The two safety rules that are not negotiable
--------------------------------------------
1. An ``aborted`` build means the claw may still be holding a block somewhere
   unknown. :meth:`step` re-raises that as :class:`BlockCalibrationAborted` and
   the run is over - no retry, no homing, go and look. This mirrors
   :attr:`rig.link.BuildResult.needs_a_human` and exists for the same reason.
2. The frame is only taken once the rig says it has parked. A capture with the
   gantry still over the workspace either hides the block or gets detected as
   one, and both write a wrong map. :data:`SETTLE_SECONDS` is the belt-and-
   braces wait on top of the firmware's own confirmation.

Feeding the blocks
------------------
The rig picks every block up from the feeder at ``[0,0]``, so an operator has
to keep it stocked; there is no sensor that can tell an empty feeder from a
failed grip. A ``rejected`` result is surfaced as a normal, retryable error
saying so, because "reload the feeder and press step again" is the usual fix.
"""

from __future__ import annotations

from dataclasses import dataclass
import time

from rig.link import ABORTED, PLACED, RigError
from vision.block_grid import (
    DEFAULT_OBSERVATIONS,
    BlockGridError,
    BlockGridSession,
)


# How long to wait after the firmware says it has parked, before grabbing the
# frame. The rig reports the park as done when the motion command completes;
# the structure keeps ringing for a moment after that, and a smeared block
# costs more than a second does.
SETTLE_SECONDS = 1.5

# Level 0 throughout: a calibration wants one block flat on the surface at each
# cell, not a stack. Nothing here ever builds upward.
CALIBRATION_LEVEL = 0


class BlockCalibrationError(RuntimeError):
    """A calibration step failed in a way the operator can act on and retry."""


class BlockCalibrationAborted(BlockCalibrationError):
    """The rig aborted mid-motion. The claw state is unknown; stop and inspect.

    Deliberately a distinct type rather than a flag: every caller has to decide
    what to do about it, and a caller that forgets gets a crash instead of a
    quietly continued run.
    """


@dataclass(frozen=True)
class StepOutcome:
    """What one placement produced."""

    cell: tuple
    placed: bool
    residual_px: float | None
    status: object            # BlockGridStatus after this step

    def describe(self) -> str:
        where = f"[{self.cell[0]},{self.cell[1]}]"
        residual = ("" if self.residual_px is None
                    else f", {self.residual_px:.2f} px from the fit so far")
        return f"placed {where}{residual} - {self.status.describe()}"


class BlockCalibrationRun:
    """One machine-driven calibration run.

    ``capture`` is any zero-argument callable returning the current corrected
    BGR frame - the console pipeline's latest view, a camera grab, or a canned
    frame in a test. It is called only when the rig is parked.
    """

    def __init__(self, rig, capture, *, grid=None, cells=None,
                 count: int = DEFAULT_OBSERVATIONS, inset: int = 0,
                 settle: float = SETTLE_SECONDS,
                 build_timeout: float = 300.0,
                 sleep=time.sleep):
        self.rig = rig
        self.capture = capture
        self.grid = grid if grid is not None else rig.grid
        # The rig lays a block along whichever axis its ACTIVE mode says, and
        # nothing downstream can tell a correctly placed vertical block from a
        # horizontal one that happens to be in the right spot. Calibrating one
        # mode while the machine is in the other would therefore write a map
        # that is wrong in a way the bearing check cannot catch, because the
        # blocks would agree with each other. Refuse it here instead.
        rig_mode = getattr(getattr(rig, "grid", None), "mode", None)
        if rig_mode is not None and self.grid.mode is not None \
                and rig_mode != self.grid.mode:
            raise BlockCalibrationError(
                f"the rig is in {rig_mode} mode but the calibration is for the "
                f"{self.grid.mode} grid; switch the rig's mode first, or the "
                f"blocks will be laid along the wrong axis")
        self.session = BlockGridSession(self.grid, cells=cells, count=count,
                                        inset=inset)
        self.settle = float(settle)
        self.build_timeout = float(build_timeout)
        self._sleep = sleep
        self.started = False
        self.finished_reason: str | None = None

    # --- lifecycle -----------------------------------------------------

    def start(self) -> None:
        """Record the empty workspace. Everything after is differenced to it.

        Call this with the build area **clear**. A block left over from a
        previous run is in the baseline, so it is invisible to the difference
        and can only be found by shape - which is the weaker path, and the one
        that mistakes a cable for a block.
        """
        frame = self._grab()
        self.session.set_baseline(frame)
        self.started = True
        self.finished_reason = None

    def step(self) -> StepOutcome:
        """Place the next planned block and observe it. One cell per call."""
        if not self.started:
            raise BlockCalibrationError(
                "call start() first, with the build area clear, so the run has "
                "a baseline to difference against")
        if self.finished_reason:
            raise BlockCalibrationError(self.finished_reason)
        remaining = self.session.remaining
        if not remaining:
            raise BlockCalibrationError("every planned cell has been placed")
        cell = remaining[0]

        try:
            result = self.rig.build(int(cell[0]), int(cell[1]),
                                    CALIBRATION_LEVEL,
                                    timeout=self.build_timeout)
        except RigError as exc:
            raise BlockCalibrationError(
                f"the rig refused to place [{cell[0]},{cell[1]}]: {exc}") from exc

        if str(result) == ABORTED:
            self.finished_reason = (
                f"the rig aborted while placing [{cell[0]},{cell[1]}]: "
                f"{result.reason or 'no reason given'}. The claw may still be "
                f"holding a block - do not retry, go and look at the rig")
            raise BlockCalibrationAborted(self.finished_reason)
        if str(result) != PLACED:
            raise BlockCalibrationError(
                f"[{cell[0]},{cell[1]}] was not placed ({result}"
                f"{': ' + result.reason if result.reason else ''}). Is the "
                f"feeder at [0,0] loaded? Nothing moved, so this is safe to "
                f"retry")

        # Only now is the gantry out of the way.
        if self.settle > 0:
            self._sleep(self.settle)
        frame = self._grab()
        try:
            self.session.observe(cell, frame)
        except BlockGridError as exc:
            # The block IS on the table whatever the camera thinks, so it now
            # belongs to the baseline. Leaving it out would make every later
            # difference light up on it as well as on the new block.
            self.session.baseline = frame.copy()
            raise BlockCalibrationError(
                f"[{cell[0]},{cell[1]}] was placed but not seen: {exc}") from exc

        status = self.session.status()
        residual = None
        if status.report is not None:
            residual = status.report.residuals.get(cell)
        return StepOutcome(cell=cell, placed=True, residual_px=residual,
                           status=status)

    def run(self):
        """Place every remaining cell, yielding one :class:`StepOutcome` each.

        A generator so a caller can render progress, and so a
        :class:`BlockCalibrationAborted` stops the loop at the failing cell with
        everything before it kept.
        """
        if not self.started:
            self.start()
        while self.session.remaining:
            yield self.step()

    # --- results -------------------------------------------------------

    def status(self):
        return self.session.status()

    def workspace_map(self, image_size=None, projection=None):
        """The saveable map, or :class:`BlockGridError` saying why not yet."""
        return self.session.workspace_map(image_size, projection)

    # --- internals -----------------------------------------------------

    def _grab(self):
        frame = self.capture()
        if frame is None:
            raise BlockCalibrationError(
                "no camera frame is available; the calibration cannot see "
                "where the blocks went")
        return frame

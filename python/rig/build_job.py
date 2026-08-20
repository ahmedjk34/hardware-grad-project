#!/usr/bin/env python3
"""Run one confirmed build off the UI thread, without blocking the camera.

``BuildController.build`` waits for the Mega to finish moving, which is minutes
of dead time. A camera UI that calls it directly stops reading frames and its
window goes grey — the operator loses sight of the rig exactly while it moves.

``BuildJob`` moves that wait onto a worker thread so the UI keeps grabbing and
drawing frames. It does not relax any safety rule:

* Only one build can be in flight; :meth:`start` refuses a second.
* The UI must refuse every controller mutation while :attr:`running` is true,
  so nothing queues behind the command the Mega is deaf to.
* An unexpected worker failure means unknown machine state, so it locks the
  controller exactly like a :class:`RigError` does.

Like :mod:`rig.build_controller` this deliberately knows nothing about OpenCV.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from rig.build_controller import BuildStateError
from rig.link import BuildResult, RigError


BUSY_MESSAGE = "build in progress; wait for its result"


@dataclass(frozen=True)
class BuildOutcome:
    """What one finished worker has to report back to the UI thread.

    Exactly one of ``result``/``error`` is set. ``locked`` means the controller
    locked itself: the machine state is unknown and a human must inspect it.
    """

    result: BuildResult | None = None
    error: Exception | None = None
    locked: bool = False


class BuildJob:
    """One-at-a-time worker around :meth:`BuildController.build`."""

    def __init__(self, controller, timeout: float = 300.0):
        self._controller = controller
        self._timeout = float(timeout)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._outcome: BuildOutcome | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        """Send the controller's selected command on a worker thread."""
        if self.running:
            raise BuildStateError(BUSY_MESSAGE)
        if self._controller.locked:
            raise BuildStateError(self._controller.locked_reason)
        if self._controller.command is None:
            raise BuildStateError("select a camera grid cell first")
        with self._lock:
            self._outcome = None
        self._thread = threading.Thread(target=self._run, name="rig-build",
                                        daemon=True)
        self._thread.start()

    def poll(self) -> BuildOutcome | None:
        """Return the finished outcome once, or ``None`` while still running."""
        if self.running:
            return None
        with self._lock:
            outcome, self._outcome = self._outcome, None
        return outcome

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(self) -> None:
        try:
            outcome = BuildOutcome(result=self._controller.build(timeout=self._timeout))
        except BuildStateError as exc:
            outcome = BuildOutcome(error=exc)
        except RigError as exc:
            outcome = BuildOutcome(error=exc, locked=True)
        except Exception as exc:  # noqa: BLE001 - unknown failure, unknown machine
            self._controller.locked_reason = (
                f"build worker failed: {exc!r}; inspect the rig and restart"
            )
            outcome = BuildOutcome(error=exc, locked=True)
        else:
            if self._controller.locked:
                outcome = BuildOutcome(result=outcome.result, locked=True)
        with self._lock:
            self._outcome = outcome

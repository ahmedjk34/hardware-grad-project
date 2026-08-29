#!/usr/bin/env python3
"""Test that one build runs off the UI thread without unlocking any safety rule.

No camera and no serial device: a fake rig blocks inside `build()` for as long
as the test needs, which is what a real Mega does for minutes at a time.
"""

from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.build_controller import BuildController, BuildStateError  # noqa: E402
from rig.build_job import BuildJob  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from rig.link import ABORTED, PLACED, BuildResult, RigError  # noqa: E402


PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:46} {detail}")


class SlowRig:
    """A rig whose build blocks until the test releases it."""

    def __init__(self, outcome):
        self.grid = MachineGrid.from_config()
        self.outcome = outcome
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def build(self, col, row, level, timeout=300):
        self.calls.append((col, row, level, timeout))
        self.entered.set()
        self.release.wait(5.0)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def wait_for(predicate, limit=5.0):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def started(rig, controller, cell=(3, 4)):
    controller.select(cell)
    job = BuildJob(controller, timeout=30.0)
    job.start()
    rig.entered.wait(5.0)
    return job


# --- the UI thread keeps running while the firmware works -------------------
rig = SlowRig(BuildResult(PLACED))
controller = BuildController(rig)
job = started(rig, controller)

frames = 0
while rig.entered.is_set() and frames < 25 and job.running:
    frames += 1  # stands in for one camera read + imshow
    time.sleep(0.002)
check("UI loop keeps iterating during a build", frames >= 25, f"{frames} frames")
check("build is still in flight", job.running)
check("no outcome until the firmware answers", job.poll() is None)

rig.release.set()
check("worker finishes", wait_for(lambda: not job.running))
outcome = job.poll()
check("finished outcome is delivered once", outcome is not None and not outcome.locked)
check("outcome carries the firmware result",
      outcome is not None and str(outcome.result) == PLACED)
check("outcome is consumed, not repeated", job.poll() is None)
check("placed clears the selection", controller.selected is None)

# --- nothing may queue behind an in-flight build ----------------------------
rig = SlowRig(BuildResult(PLACED))
controller = BuildController(rig)
job = started(rig, controller)
try:
    job.start()
    check("a second build is refused", False)
except BuildStateError:
    check("a second build is refused", True)
rig.release.set()
job.join(5.0)
check("only one command reached the rig", len(rig.calls) == 1, f"{rig.calls}")

# --- a lost cable locks the session from the worker thread ------------------
rig = SlowRig(RigError("cable lost"))
controller = BuildController(rig)
job = started(rig, controller)
rig.release.set()
job.join(5.0)
outcome = job.poll()
check("serial failure reports locked", outcome is not None and outcome.locked)
check("serial failure locks the controller", controller.locked)
try:
    job.start()
    check("locked controller refuses a new job", False)
except BuildStateError:
    check("locked controller refuses a new job", True)

# --- an aborted build locks too, even though build() returned normally ------
rig = SlowRig(BuildResult(ABORTED, "claw may hold a block"))
controller = BuildController(rig)
job = started(rig, controller)
rig.release.set()
job.join(5.0)
outcome = job.poll()
check("aborted result reports locked", outcome is not None and outcome.locked)
check("aborted keeps the controller locked", controller.locked)

# --- an unexpected worker crash is treated as unknown machine state ---------
class BrokenRig(SlowRig):
    def build(self, col, row, level, timeout=300):
        raise ValueError("bug in the worker")


rig = BrokenRig(None)
controller = BuildController(rig)
controller.select((1, 1))
job = BuildJob(controller, timeout=30.0)
job.start()
job.join(5.0)
outcome = job.poll()
check("worker crash reports locked", outcome is not None and outcome.locked)
check("worker crash locks the controller", controller.locked)

# --- a job that never started has nothing to report -------------------------
rig = SlowRig(BuildResult(PLACED))
controller = BuildController(rig)
job = BuildJob(controller, timeout=30.0)
check("idle job is not running", not job.running)
check("idle job polls empty", job.poll() is None)
job.join(0.1)
try:
    job.start()
    check("job refuses to start without a selection", False)
except BuildStateError:
    check("job refuses to start without a selection", True)
check("refused start sent nothing", not rig.calls)

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

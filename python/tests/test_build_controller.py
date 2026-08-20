#!/usr/bin/env python3
"""Test camera-build safety state without a camera or serial device."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.build_controller import BuildController, BuildStateError  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from rig.link import ABORTED, PLACED, REJECTED, BuildResult, RigError  # noqa: E402


PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:42} {detail}")


class FakeRig:
    def __init__(self, outcomes):
        self.grid = MachineGrid.from_config()
        self.outcomes = list(outcomes)
        self.calls = []

    def build(self, col, row, level, rotation=None, timeout=300):
        self.calls.append((col, row, level, rotation, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


rig = FakeRig([BuildResult(PLACED)])
controller = BuildController(rig)
try:
    controller.select((1, 1), calibrated=False)
    check("approximate grid cannot select", False)
except BuildStateError:
    check("approximate grid cannot select", True)

controller.select((3, 4), calibrated=True)
check("default command is exact B col row level", controller.command == "B 3 4 0")
result = controller.build(timeout=12)
check("placed result returned", result == PLACED)
check("placed build sent correct arguments", rig.calls == [(3, 4, 0, None, 12)])
check("placed build requires fresh selection", controller.selected is None)

rig = FakeRig([BuildResult(REJECTED, "bad level"),
               BuildResult(ABORTED, "Z switch not reached")])
controller = BuildController(rig, level=2, rotation="R")
controller.select((22, 5), calibrated=True)
check("rotation appears only when requested", controller.command == "B 22 5 2 R")
result = controller.build()
check("safe rejection keeps selection", result == REJECTED and controller.selected == (22, 5))
result = controller.build()
check("aborted result locks controller", result == ABORTED and controller.locked)
try:
    controller.build()
    check("locked controller refuses retry", False)
except BuildStateError:
    check("locked controller refuses retry", True)

rig = FakeRig([RigError("cable lost")])
controller = BuildController(rig)
controller.select((1, 1), calibrated=True)
try:
    controller.build()
    check("serial error propagates", False)
except RigError:
    check("serial error propagates", True)
check("serial error locks unknown state", controller.locked)

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

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
    def __init__(self, outcomes, mode="vertical"):
        self.grid = MachineGrid.from_config(mode=mode)
        self.outcomes = list(outcomes)
        self.calls = []
        self.mode_calls = []
        self.home_calls = []
        self.home_result = True

    def build(self, col, row, level, timeout=300):
        self.calls.append((col, row, level, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def set_mode(self, mode):
        # The real Rig re-reads its grid here, because every coordinate now
        # means a different place. A fake that skipped that would let the
        # controller keep selecting cells the new grid does not have.
        self.mode_calls.append(mode)
        self.grid = MachineGrid.from_config(mode=mode)

    def home(self, full=True):
        self.home_calls.append(full)
        return self.home_result


rig = FakeRig([BuildResult(PLACED)])
controller = BuildController(rig)
controller.select((3, 4))
check("approximate grid can select", controller.selected == (3, 4))
check("default command is exact B col row level", controller.command == "B 3 4 0")
result = controller.build(timeout=12)
check("placed result returned", result == PLACED)
check("placed build sent correct arguments", rig.calls == [(3, 4, 0, 12)])
check("placed build requires fresh selection", controller.selected is None)

rig = FakeRig([BuildResult(REJECTED, "bad level"),
               BuildResult(ABORTED, "Z switch not reached")])
controller = BuildController(rig, level=2)
controller.select((9, 5))
check("the command never carries a rotation word", controller.command == "B 9 5 2",
      controller.command)
result = controller.build()
check("safe rejection keeps selection", result == REJECTED and controller.selected == (9, 5))
result = controller.build()
check("aborted result locks controller", result == ABORTED and controller.locked)
try:
    controller.build()
    check("locked controller refuses retry", False)
except BuildStateError:
    check("locked controller refuses retry", True)

calibration_controller = BuildController(FakeRig([]), level=2)
calibration_controller.select((0, 5))
check("zero X calibration target is valid",
      calibration_controller.command == "B 0 5 2")
calibration_controller.select((9, 0))
check("zero Y calibration target is valid",
      calibration_controller.command == "B 9 0 2")
calibration_controller.select((0, 0))
check("zero-zero no-op target is valid",
      calibration_controller.command == "B 0 0 2")

# ------------------------------------------------------------------
# Grid mode is selected here, and it is not a per-block rotation
# ------------------------------------------------------------------

rig = FakeRig([])
controller = BuildController(rig)
check("the controller reports the rig's grid", controller.mode == "vertical")
check("no mode is cached on the controller",
      not hasattr(controller, "rotation") and "mode" not in vars(controller))

controller.select((9, 5))
controller.set_mode("horizontal")
check("set_mode latched the rig", rig.mode_calls == ["horizontal"])
check("set_mode re-read the grid", controller.mode == "horizontal"
      and (rig.grid.cols, rig.grid.rows) == (3, 15))
check("a mode switch drops the pending selection", controller.selected is None)
check("cells the new grid lacks are now refused",
      not rig.grid.contains_build_target(9, 5))

controller.set_mode("horizontal")
check("selecting the mode already latched sends nothing",
      rig.mode_calls == ["horizontal"])

controller.cycle_mode()
check("cycle_mode toggles back", rig.mode_calls == ["horizontal", "vertical"]
      and controller.mode == "vertical")

controller.cycle_mode(home_before_horizontal=True)
check("entering horizontal can explicitly home X/Y first",
      rig.home_calls == [False] and rig.mode_calls == ["horizontal", "vertical", "horizontal"])
controller.cycle_mode(home_before_horizontal=True)
check("returning vertical does not home", rig.home_calls == [False]
      and rig.mode_calls[-1] == "vertical")

rig = FakeRig([])
rig.home_result = False
controller = BuildController(rig)
try:
    controller.set_mode("horizontal", home_before_horizontal=True)
    check("failed X/Y home refuses horizontal", False)
except RigError:
    check("failed X/Y home refuses horizontal",
          rig.home_calls == [False] and rig.mode_calls == [] and controller.mode == "vertical")

try:
    controller.set_mode("diagonal")
    check("an unknown mode is refused", False)
except BuildStateError as exc:
    check("an unknown mode is refused", "vertical" in str(exc), str(exc))
check("the refused mode sent nothing",
      rig.mode_calls == [])

# A horizontal controller builds with a plain three-number command too: the
# turn is the grid's, and the firmware derives it from the mode.
horizontal = BuildController(FakeRig([BuildResult(PLACED)], mode="horizontal"),
                             level=1)
horizontal.select((3, 15))
check("horizontal builds carry no rotation word either",
      horizontal.command == "B 3 15 1", horizontal.command)
check("horizontal knows which grid it is in", horizontal.mode == "horizontal")

locked = BuildController(FakeRig([]))
locked.locked_reason = "aborted earlier"
try:
    locked.set_mode("horizontal")
    check("a locked controller refuses a mode switch", False)
except BuildStateError:
    check("a locked controller refuses a mode switch", True)

rig = FakeRig([RigError("cable lost")])
controller = BuildController(rig)
controller.select((1, 1))
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

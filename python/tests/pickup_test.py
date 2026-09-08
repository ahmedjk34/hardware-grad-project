"""Manual pickup coordination keeps the physical handoff safe without an Uno."""

from __future__ import annotations

import pytest

from rig.link import BuildResult, RigError
from rig.pickup import PickupCoordinator, PickupError


class Gantry:
    def __init__(self, result=BuildResult("placed")):
        self.result = result
        self.build_calls = []
        self.close_calls = 0

    def build(self, col, row, level, *, timeout, manual_pick):
        self.build_calls.append((col, row, level, timeout, manual_pick))
        return self.result

    def close_manual_pick(self):
        self.close_calls += 1


def test_one_staged_block_uses_the_manual_mega_route():
    gantry = Gantry()
    phases = []
    pickup = PickupCoordinator(gantry, on_phase=phases.append)

    result = pickup.place_staged_block(2, 3, 1, timeout=12.0)

    assert str(result) == "placed"
    assert gantry.build_calls == [(2, 3, 1, 12.0, True)]
    assert phases == ["manual_staging_confirmed", "placing", "complete"]
    assert pickup.locked_reason is None


def test_close_is_impossible_before_the_firmware_gate():
    gantry = Gantry()
    pickup = PickupCoordinator(gantry)

    with pytest.raises(PickupError, match="not waiting"):
        pickup.close_manual_pick()
    pickup._phase("placing")
    pickup.manual_close_ready()
    pickup.close_manual_pick()

    assert gantry.close_calls == 1
    assert pickup.phase == "placing"


@pytest.mark.parametrize("result", [
    BuildResult("rejected", "safe refusal"),
    BuildResult("aborted", "position unknown"),
])
def test_any_failure_after_manual_staging_locks_for_inspection(result):
    pickup = PickupCoordinator(Gantry(result))

    outcome = pickup.place_staged_block(1, 1, 0)

    assert str(outcome) == "aborted"
    assert pickup.phase == "error"
    assert "inspection" in pickup.locked_reason
    with pytest.raises(PickupError, match="locked"):
        pickup.place_staged_block(1, 2, 0)


def test_transport_failure_after_staging_also_locks():
    class FailedGantry(Gantry):
        def build(self, *args, **kwargs):
            raise RigError("cable lost")

    pickup = PickupCoordinator(FailedGantry())
    outcome = pickup.place_staged_block(1, 1, 0)

    assert str(outcome) == "aborted"
    assert "pickup/claw state is unknown" in pickup.locked_reason

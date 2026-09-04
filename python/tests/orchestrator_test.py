"""The pickup-area invariant: every block is FEED terminal OK then Mega B."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.feeder import FeedResult, FeederError, FeederMessage  # noqa: E402
from rig.link import ABORTED, PLACED, REJECTED, BuildResult  # noqa: E402
from rig.orchestrator import CellError, CellOrchestrator  # noqa: E402


class StubFeeder:
    def __init__(self, timeline, outcomes=None):
        self.timeline = timeline
        self.outcomes = list(outcomes or [])
        self.next_id = 1
        self.stopped = False

    def feed(self, timeout=45):
        request_id = self.next_id
        self.next_id += 1
        self.timeline.append(f"FEED{request_id}")
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        self.timeline.append(f"UNO_OK{request_id}")
        terminal = FeederMessage(request_id, "OK",
                                 {"state": "block_ready", "result": "staged"})
        return FeedResult(request_id, "block_ready", "staged", (terminal,))

    def stop(self):
        self.stopped = True


class StubGantry:
    def __init__(self, timeline, outcomes=None):
        self.timeline = timeline
        self.outcomes = list(outcomes or [])

    def build(self, col, row, level, timeout=300):
        self.timeline.append(f"B{col}{row}{level}")
        outcome = self.outcomes.pop(0) if self.outcomes else BuildResult(PLACED)
        if isinstance(outcome, Exception):
            raise outcome
        self.timeline.append(f"MEGA_{str(outcome).upper()}")
        return outcome


def test_happy_path_order_and_three_blocks_are_strictly_sequential():
    timeline = []
    cell = CellOrchestrator(StubFeeder(timeline), StubGantry(timeline))
    for col in (1, 2, 3):
        assert cell.place_block(col, 1, 0) == PLACED
    assert timeline == [
        "FEED1", "UNO_OK1", "B110", "MEGA_PLACED",
        "FEED2", "UNO_OK2", "B210", "MEGA_PLACED",
        "FEED3", "UNO_OK3", "B310", "MEGA_PLACED",
    ]


def test_feeder_error_never_calls_mega():
    timeline = []
    feeder = StubFeeder(timeline, [FeederError("stage_timeout")])
    cell = CellOrchestrator(feeder, StubGantry(timeline))
    result = cell.place_block(2, 1, 0)
    assert result == ABORTED
    assert "stage_timeout" in result.reason
    assert timeline == ["FEED1"]
    with pytest.raises(CellError, match="orchestrator is locked"):
        cell.place_block(2, 1, 0)
    assert timeline == ["FEED1"]


def test_mega_safe_after_staging_becomes_locked_high_level_abort():
    timeline = []
    cell = CellOrchestrator(StubFeeder(timeline), StubGantry(
        timeline, [BuildResult(REJECTED, "cell out of range")]))
    result = cell.place_block(2, 1, 0)
    assert result == ABORTED
    assert "pickup state requires inspection" in result.reason
    assert timeline == ["FEED1", "UNO_OK1", "B210", "MEGA_REJECTED"]
    with pytest.raises(CellError, match="orchestrator is locked"):
        cell.place_block(3, 1, 0)
    assert timeline == ["FEED1", "UNO_OK1", "B210", "MEGA_REJECTED"]

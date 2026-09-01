"""Protocol-level tests for the supported no-hardware serial board."""

from __future__ import annotations

from pathlib import Path
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.link import Rig, RigBusy, RigReset  # noqa: E402
from rig.mock_board import MockBoard  # noqa: E402


def make_rig(*, build_seconds: float = 0.01):
    board = MockBoard(build_seconds=build_seconds)
    rig = Rig(serial_factory=lambda *args: board)
    rig.connect(timeout=1.0)
    return rig, board


def test_connect_replays_configured_grid_and_ready_banner():
    rig, board = make_rig()
    try:
        assert "@0 READY" in "\n".join(board.emitted)
        assert (rig.grid.cols, rig.grid.rows) == (7, 6)
        assert "S 6 5" in board.written
    finally:
        rig.close()


def test_build_returns_placed():
    rig, _board = make_rig()
    try:
        assert str(rig.build(3, 5, 0, timeout=1.0)) == "placed"
    finally:
        rig.close()


def test_aborted_build_requires_a_human():
    rig, board = make_rig()
    try:
        board.fail_next_build("ABORTED", "simulated abort")
        result = rig.build(3, 5, 0, timeout=1.0)
        assert str(result) == "aborted"
        assert result.needs_a_human is True
    finally:
        rig.close()


def test_prose_fallback_works_when_next_ack_is_dropped():
    rig, board = make_rig()
    try:
        board.drop_next_ack()
        result = rig.build(3, 5, 0, timeout=3.0)
        assert str(result) == "placed"
        assert result.from_prose is True
        assert rig.prose_fallbacks == 1
    finally:
        rig.close()


def test_idle_reboot_blocks_the_next_command():
    rig, board = make_rig()
    try:
        board.reboot()
        deadline = time.monotonic() + 1.0
        while not rig._reset_detected and time.monotonic() < deadline:
            time.sleep(0.005)
        with pytest.raises(RigReset):
            rig.build(3, 5, 0)
    finally:
        rig.close()


def test_feeder_and_overlapping_build_are_refused():
    rig, _board = make_rig(build_seconds=0.2)
    try:
        with pytest.raises(ValueError, match="feeder"):
            rig.build(0, 0, 0)

        started = threading.Event()

        def build():
            started.set()
            rig.build(3, 5, 0, timeout=1.0)

        worker = threading.Thread(target=build)
        worker.start()
        started.wait(1.0)
        deadline = time.monotonic() + 1.0
        while "B 3 5 0" not in _board.written and time.monotonic() < deadline:
            time.sleep(0.005)
        with pytest.raises(RigBusy):
            rig.build(2, 4, 0)
        worker.join(1.0)
        assert not worker.is_alive()
    finally:
        rig.close()

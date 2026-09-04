"""Uno protocol parsing, identity, correlation, reset and cancellation."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.feeder import (FeedResult, Feeder, FeederBusy, FeederDisconnected,
                        FeederError, FeederRejected, FeederReset,
                        FeederTimeout, parse_feeder_message)  # noqa: E402
from rig.mock_feeder import MockFeeder  # noqa: E402
from rig.link import Rig, RigError  # noqa: E402


CFG = {"feeder": {"port": "mock", "baud": 9600, "firmware": "belt_v1",
                   "protocol": 2}}


def test_committed_config_and_uno_firmware_identity_stay_paired():
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "config/rig.json").read_text())
    feeder = config["feeder"]
    sketch = (root / feeder["sketch"] / "belt_v1.ino").read_text()
    assert feeder["port"] == "" or feeder["port"].startswith("/dev/serial/by-id/")
    assert f"Serial.begin({feeder['baud']})" in sketch
    ready = (f"@0 READY firmware={feeder['firmware']} "
             f"protocol={feeder['protocol']} board=uno")
    assert ready in sketch
    assert feeder["fqbn"] == "arduino:avr:uno"


@pytest.mark.parametrize(("line", "request_id", "kind", "field"), [
    ("@0 READY firmware=belt_v1 protocol=2 board=uno", 0, "READY", ("board", "uno")),
    ("@42 RECV cmd=FEED", 42, "RECV", ("cmd", "FEED")),
    ("@42 ACK cmd=FEED accepted=1", 42, "ACK", ("accepted", "1")),
    ("@42 STATE state=moving_to_stage", 42, "STATE", ("state", "moving_to_stage")),
    ("@42 SENSOR sensor=stage distance_cm=8.2 detected=1", 42, "SENSOR", ("detected", "1")),
    ("@42 EVENT phase=stage_detected_aligning distance_cm=8.2", 42, "EVENT", ("phase", "stage_detected_aligning")),
    ("@42 OK state=block_ready result=staged", 42, "OK", ("result", "staged")),
    ("@42 ERROR state=fault reason=stage_timeout", 42, "ERROR", ("reason", "stage_timeout")),
])
def test_parse_protocol(line, request_id, kind, field):
    message = parse_feeder_message(line)
    assert message is not None
    assert (message.request_id, message.type) == (request_id, kind)
    assert message.fields[field[0]] == field[1]


@pytest.mark.parametrize("line", ["", "human prose", "@", "@x OK", "@1"])
def test_malformed_lines_are_ignored(line):
    assert parse_feeder_message(line) is None


def connected(board=None, **callbacks):
    board = board or MockFeeder(0.02)
    feeder = Feeder(CFG, serial_factory=lambda *_args: board, **callbacks)
    feeder.connect(timeout=1)
    return feeder, board


def test_success_uses_pi_id_and_exact_terminal_contract():
    feeder, board = connected()
    try:
        result = feeder.feed(timeout=1)
        assert isinstance(result, FeedResult)
        assert result.request_id == 1
        assert board.writes[0] == "FEED 1"
        assert result.messages[-1].raw == "@1 OK state=block_ready result=staged"
        second = feeder.feed(timeout=1)
        assert second.request_id == 2
        assert board.writes[1] == "FEED 2"
    finally:
        feeder.close()


@pytest.mark.parametrize("reason", ["stage_occupied", "exit_timeout", "stage_timeout"])
def test_terminal_error_never_becomes_success(reason):
    board = MockFeeder(0.01)
    board.fail_next(reason)
    feeder, _ = connected(board)
    try:
        with pytest.raises(FeederRejected, match=reason):
            feeder.feed(timeout=1)
    finally:
        feeder.close()


def test_wrong_transaction_terminal_is_ignored():
    board = MockFeeder(0.08)
    feeder, _ = connected(board)
    board._emit("@99 OK state=block_ready result=staged")
    try:
        result = feeder.feed(timeout=1)
        assert result.request_id == 1
        assert all(message.request_id == 1 for message in result.messages)
    finally:
        feeder.close()


def test_malformed_success_is_not_permission_to_call_mega():
    board = MockFeeder()
    board._finish_feed = lambda request_id: board._emit(  # type: ignore[method-assign]
        f"@{request_id} OK state=block_ready result=almost")
    feeder, _ = connected(board)
    try:
        with pytest.raises(FeederError, match="malformed success"):
            feeder.feed(timeout=1)
    finally:
        feeder.close()


def test_disconnect_during_feed_is_typed_and_connection_drops():
    board = MockFeeder(0.01)
    board.disconnect_next()
    feeder, _ = connected(board)
    try:
        with pytest.raises(FeederDisconnected, match="physical outcome is unknown"):
            feeder.feed(timeout=1)
        assert not feeder.connected
    finally:
        feeder.close()


def test_host_timeout_attempts_stop_without_claiming_recovery():
    feeder, board = connected(MockFeeder(2.0))
    try:
        with pytest.raises(FeederTimeout, match="STOP requested"):
            feeder.feed(timeout=0.03)
        assert "STOP" in board.writes
    finally:
        feeder.close()


def test_ready_during_feed_is_unknown_reset():
    board = MockFeeder(0.01)
    board.reset_next()
    feeder, _ = connected(board)
    try:
        with pytest.raises(FeederReset):
            feeder.feed(timeout=1)
    finally:
        feeder.close()


def test_unexpected_ready_while_idle_is_reported_and_poisoned():
    errors = []
    feeder, board = connected(on_error=errors.append)
    board._emit("@0 READY firmware=belt_v1 protocol=2 board=uno")
    deadline = time.monotonic() + 1
    while not errors and time.monotonic() < deadline:
        time.sleep(0.005)
    try:
        assert errors and "reset unexpectedly" in errors[-1]
        with pytest.raises(FeederReset):
            feeder.feed(timeout=1)
    finally:
        feeder.close()


def test_wrong_board_identity_fails_before_commands():
    board = MockFeeder()
    board._rx = __import__("queue").Queue()
    board._rx.put(b"@0 READY fw=build_test_v1 board=mega protocol=2\n")
    feeder = Feeder(CFG, serial_factory=lambda *_args: board)
    with pytest.raises(FeederError, match="not the expected Uno"):
        feeder.connect(timeout=1)
    assert board.writes == []


def test_uno_on_configured_gantry_port_is_rejected_before_commands():
    board = MockFeeder()
    rig = Rig(serial_factory=lambda *_args: board)
    with pytest.raises(RigError, match="not the Mega"):
        rig.connect(timeout=1)
    assert board.writes == []


def test_stop_cancels_active_feed_and_second_feed_is_busy():
    feeder, board = connected(MockFeeder(0.3))
    errors = []
    thread = threading.Thread(target=lambda: _capture_feed(feeder, errors))
    thread.start()
    deadline = time.monotonic() + 1
    while feeder.active_request_id is None and time.monotonic() < deadline:
        time.sleep(0.005)
    with pytest.raises(FeederBusy):
        feeder.feed(timeout=1)
    feeder.stop()
    thread.join(timeout=2)
    try:
        assert not thread.is_alive()
        assert any(isinstance(error, FeederRejected) for error in errors)
        assert "STOP" in board.writes
    finally:
        feeder.close()


def _capture_feed(feeder, errors):
    try:
        feeder.feed(timeout=2)
    except Exception as exc:  # expected cancellation result
        errors.append(exc)

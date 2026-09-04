#!/usr/bin/env python3
"""Typed, transaction-safe serial client for the Arduino Uno feeder."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field

import serial

from rig import build_log
from rig.config import load


TERMINAL_TYPES = frozenset({"OK", "ERROR"})


@dataclass(frozen=True)
class FeederMessage:
    request_id: int
    type: str
    fields: dict[str, str] = field(default_factory=dict)
    args: tuple[str, ...] = ()
    raw: str = ""

    @property
    def terminal(self) -> bool:
        return self.type in TERMINAL_TYPES

    @property
    def reason(self) -> str:
        return self.fields.get("reason", " ".join(self.args))


def parse_feeder_message(line: str) -> FeederMessage | None:
    """Parse ``@<id> TYPE key=value...`` without throwing on bad input."""
    raw = line.strip()
    if not raw.startswith("@"):
        return None
    parts = raw[1:].split()
    if len(parts) < 2:
        return None
    try:
        request_id = int(parts[0])
    except ValueError:
        return None
    if request_id < 0:
        return None
    fields: dict[str, str] = {}
    args: list[str] = []
    for token in parts[2:]:
        if "=" in token:
            key, value = token.split("=", 1)
            if key:
                fields[key] = value
            else:
                args.append(token)
        else:
            args.append(token)
    return FeederMessage(request_id, parts[1].upper(), fields,
                         tuple(args), raw)


@dataclass(frozen=True)
class FeedResult:
    request_id: int
    state: str
    result: str
    messages: tuple[FeederMessage, ...]


class FeederError(RuntimeError):
    """Base error for the independent Uno connection."""


class FeederNotConnected(FeederError):
    pass


class FeederBusy(FeederError):
    pass


class FeederTimeout(FeederError):
    pass


class FeederDisconnected(FeederError):
    pass


class FeederReset(FeederError):
    pass


class FeederRejected(FeederError):
    def __init__(self, message: FeederMessage):
        self.message = message
        detail = message.reason or "unspecified feeder error"
        super().__init__(
            f"feeder transaction {message.request_id} failed: {detail} "
            f"(state={message.fields.get('state', 'unknown')})"
        )


_MESSAGE = "message"
_MALFORMED = "malformed"
_DEAD = "dead"


class Feeder:
    """One independently-read Uno link with one correlated FEED at a time."""

    def __init__(self, cfg: dict | None = None, *, serial_factory=None,
                 on_line=None, on_message=None, on_error=None):
        cfg = cfg if cfg is not None else load()
        feeder_cfg = cfg.get("feeder", {})
        self.port_name = str(feeder_cfg.get("port") or "")
        self.baud = int(feeder_cfg.get("baud", 9600))
        self.expected_firmware = str(feeder_cfg.get("firmware", "belt_v1"))
        self.expected_protocol = int(feeder_cfg.get("protocol", 2))
        self._serial_factory = serial_factory
        self._on_line = on_line
        self._on_message = on_message
        self._on_error = on_error
        self._port = None
        self._reader = None
        self._stopping = threading.Event()
        self._events: queue.Queue = queue.Queue(maxsize=1024)
        self._transaction = threading.Lock()
        self._write_lock = threading.Lock()
        self._next_request_id = 1
        self._active_request_id: int | None = None
        self._reset_detected = False
        self.ready: FeederMessage | None = None

    @property
    def connected(self) -> bool:
        return self._port is not None and bool(self._port.is_open)

    @property
    def active_request_id(self) -> int | None:
        return self._active_request_id

    def connect(self, timeout: float = 15.0) -> None:
        if self.connected:
            raise FeederError("feeder already connected")
        if not self.port_name and self._serial_factory is None:
            raise FeederError(
                "feeder.port is not configured; run 'ls -l /dev/serial/by-id/' "
                "and put the Uno's full stable path in config/rig.json"
            )
        try:
            if self._serial_factory is None:
                self._port = serial.Serial(
                    self.port_name, self.baud, timeout=0.2, write_timeout=2.0,
                    exclusive=True,
                )
            else:
                self._port = self._serial_factory(self.port_name, self.baud, 0.2)
        except (serial.SerialException, OSError, ValueError) as exc:
            self._port = None
            raise FeederError(
                f"cannot open feeder port {self.port_name!r} at {self.baud}: {exc}"
            ) from exc
        self._stopping.clear()
        self._reset_detected = False
        self.ready = None
        self._reader = threading.Thread(target=self._read_loop,
                                        name="feeder-serial", daemon=True)
        self._reader.start()
        try:
            self._wait_ready(timeout)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        self._stopping.set()
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
        if self._reader is not None:
            self._reader.join(timeout=1.0)
        self._port = None
        self._reader = None
        self._active_request_id = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    def _put(self, event) -> None:
        while True:
            try:
                self._events.put_nowait(event)
                return
            except queue.Full:
                try:
                    self._events.get_nowait()
                except queue.Empty:
                    pass

    def _drain(self) -> None:
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                return

    def _read_loop(self) -> None:
        port = self._port
        while not self._stopping.is_set():
            try:
                raw = port.readline()
            except (serial.SerialException, OSError, TypeError) as exc:
                if not self._stopping.is_set():
                    text = f"feeder serial port went away: {exc}"
                    self._put((_DEAD, text))
                    if self._on_error is not None:
                        self._on_error(text)
                    try:
                        port.close()
                    except Exception:
                        pass
                return
            if not raw:
                continue
            text = raw.decode("utf-8", errors="replace").rstrip()
            build_log.serial.line_in(f"[UNO/FEEDER] {text}")
            if self._on_line is not None:
                self._on_line(text)
            message = parse_feeder_message(text)
            if message is None:
                self._put((_MALFORMED, text))
                continue
            if message.request_id == 0 and message.type == "READY":
                unexpected = self.ready is not None or self._active_request_id is not None
                if unexpected:
                    self._reset_detected = True
                self.ready = message
                if unexpected and self._on_error is not None:
                    self._on_error(
                        "feeder reset unexpectedly; pickup state requires inspection")
            if self._on_message is not None:
                self._on_message(message)
            self._put((_MESSAGE, message))

    def _next_event(self, deadline: float):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, None
        try:
            return self._events.get(timeout=min(remaining, 0.2))
        except queue.Empty:
            return None, None

    def _wait_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            kind, payload = self._next_event(deadline)
            if kind == _DEAD:
                raise FeederError(payload)
            if kind != _MESSAGE:
                continue
            message = payload
            if message.request_id != 0 or message.type != "READY":
                continue
            expected = {
                "board": "uno",
                "firmware": self.expected_firmware,
                "protocol": str(self.expected_protocol),
            }
            wrong = {key: (expected_value, message.fields.get(key))
                     for key, expected_value in expected.items()
                     if message.fields.get(key) != expected_value}
            if wrong:
                self.close()
                detail = ", ".join(
                    f"{key} expected {want!r}, got {got!r}"
                    for key, (want, got) in wrong.items())
                raise FeederError(
                    f"configured feeder port is not the expected Uno: {detail}"
                )
            self._reset_detected = False
            return
        raise FeederTimeout(
            f"feeder did not announce @0 READY within {timeout:g}s; check port, "
            "baud, cable, and belt_v1 firmware"
        )

    def _write(self, line: str) -> None:
        if not self.connected:
            raise FeederNotConnected("feeder is not connected")
        data = (line.strip() + "\n").encode("ascii")
        build_log.serial.line_out(f"[UNO/FEEDER] {line.strip()}")
        with self._write_lock:
            try:
                written = self._port.write(data)
                self._port.flush()
            except (serial.SerialException, OSError, TypeError) as exc:
                raise FeederError(f"could not write to feeder: {exc}") from exc
        if written is not None and written != len(data):
            raise FeederError(
                f"partial feeder write: {written} of {len(data)} bytes")

    def feed(self, timeout: float = 45.0) -> FeedResult:
        """Stage exactly one block; only matching terminal staged OK succeeds."""
        if not self._transaction.acquire(blocking=False):
            raise FeederBusy("a FEED transaction is already active")
        if self._next_request_id > 0xFFFFFFFF:
            self._transaction.release()
            raise FeederError(
                "feeder request-ID space exhausted; restart before another physical cycle")
        request_id = self._next_request_id
        self._next_request_id = request_id + 1
        self._active_request_id = request_id
        messages: list[FeederMessage] = []
        try:
            if self._reset_detected:
                raise FeederReset("feeder reset; inspect the pickup area before feeding")
            self._drain()
            self._write(f"FEED {request_id}")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                kind, payload = self._next_event(deadline)
                if kind == _DEAD:
                    raise FeederDisconnected(
                        f"feeder disconnected during transaction {request_id}; "
                        "physical outcome is unknown"
                    )
                if kind != _MESSAGE:
                    continue
                message: FeederMessage = payload
                if message.request_id == 0 and message.type == "READY":
                    raise FeederReset(
                        f"feeder reset during transaction {request_id}; physical "
                        "outcome is unknown"
                    )
                if message.request_id != request_id:
                    continue
                messages.append(message)
                if not message.terminal:
                    continue
                if message.type == "ERROR":
                    raise FeederRejected(message)
                if (message.fields.get("state") != "block_ready" or
                        message.fields.get("result") != "staged"):
                    raise FeederError(
                        f"feeder transaction {request_id} returned malformed success: "
                        f"{message.raw}"
                    )
                return FeedResult(request_id, "block_ready", "staged",
                                  tuple(messages))
            try:
                self.stop()
                stop_detail = "; STOP requested, but delivery is not proof"
            except FeederError:
                stop_detail = "; STOP could not be delivered"
            raise FeederTimeout(
                f"feeder transaction {request_id} timed out after {timeout:g}s; "
                f"physical outcome is unknown{stop_detail}"
            )
        finally:
            self._active_request_id = None
            self._transaction.release()

    def stop(self) -> None:
        """Request Uno cancellation; the active feed waiter observes its ERROR."""
        self._write("STOP")

    def status(self) -> None:
        """Request structured @0 STATUS/SENSOR telemetry asynchronously."""
        if self._active_request_id is not None:
            raise FeederBusy("STATUS is disabled during an automatic FEED")
        self._write("STATUS")

    def manual(self, command: str) -> None:
        """Commissioning command, refused while production owns the feeder."""
        if self._active_request_id is not None:
            raise FeederBusy("manual feeder commands are disabled during FEED")
        head = command.strip().split(maxsplit=1)[0].upper() if command.strip() else ""
        if head in {"FEED", "RUN", "STOP"}:
            raise ValueError("use feed() or stop() for transactional commands")
        if head not in {"STATUS", "P", "US", "OPEN", "O", "CLOSE", "C",
                        "ON", "OFF", "X", "F", "B", "R", "REVERSE", "S",
                        "HELP", "H", "?"}:
            raise ValueError(f"unsupported feeder commissioning command: {head!r}")
        self._write(command)

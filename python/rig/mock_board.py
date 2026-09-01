"""A small, protocol-faithful Arduino stand-in for off-rig development.

``MockBoard`` deliberately implements the pyserial surface used by
:class:`rig.link.Rig`, rather than a higher-level fake Rig.  That keeps the
handshake, reader thread, acknowledgement parsing, prose fallback, reset, and
one-command-at-a-time behaviour exercised without a Mega attached.
"""

from __future__ import annotations

import queue
import threading
import time


class FakeSerial:
    """Scripted pyserial-shaped transport retained for transcript tests.

    ``MockBoard`` below is the supported dynamic fake for applications.  This
    smaller class keeps the existing link transcript tests precise: each reply
    is supplied by the test, including intentional silent intervals.
    """

    def __init__(self, script, acks=True):
        self.is_open = True
        self.written = []
        self._script = script
        self._acks = acks
        self._out = queue.Queue()
        self._emit(script["banner"])

    def _emit(self, lines):
        def run():
            for line in lines:
                if isinstance(line, float):
                    time.sleep(line)
                    continue
                if not self._acks and line.startswith("@"):
                    continue
                self._out.put((line + "\r\n").encode())

        threading.Thread(target=run, daemon=True).start()

    def readline(self):
        if not self.is_open:
            raise OSError("port closed")
        try:
            return self._out.get(timeout=0.2)
        except queue.Empty:
            return b""

    def write(self, data):
        text = data.decode().strip()
        self.written.append(text)
        for prefix, lines in self._script.get("replies", {}).items():
            if text.upper().startswith(prefix):
                self._emit(lines)
                break
        return len(data)

    def close(self):
        self.is_open = False


class MockBoard:
    """An in-memory serial transport that speaks the rig's current protocol."""

    def __init__(self, *, grid: str = "6x5", mode: str = "vertical",
                 build_seconds: float = 0.5):
        if mode not in {"vertical", "horizontal"}:
            raise ValueError("mode must be 'vertical' or 'horizontal'")
        if build_seconds < 0:
            raise ValueError("build_seconds must be non-negative")
        self.is_open = True
        self.written: list[str] = []
        self.emitted: list[str] = []
        self._grid = str(grid)
        self._mode = mode
        self._build_seconds = float(build_seconds)
        self._out: queue.Queue[bytes] = queue.Queue()
        self._read_buffer = bytearray()
        self._lock = threading.Lock()
        self._next_build_failure: tuple[str, str] | None = None
        self._drop_next_build_ack = False
        self._emit((
            "@0 BOOT fw=mock-board",
            "=== GRID ===",
            "Mock board: position is UNKNOWN until you home.",
            f"@0 READY grid={self._grid} mode={self._mode}",
        ))

    def fail_next_build(self, kind: str = "ABORTED",
                        reason: str = "simulated abort") -> None:
        """Make the next build finish as a safe rejection or unknown abort."""
        kind = str(kind).upper()
        if kind not in {"ABORTED", "HELD", "REJECTED", "SAFE", "ERR"}:
            raise ValueError("kind must be ABORTED/HELD or REJECTED/SAFE/ERR")
        with self._lock:
            self._next_build_failure = kind, str(reason)

    def drop_next_ack(self) -> None:
        """Suppress only the next build's terminal ``@`` line."""
        with self._lock:
            self._drop_next_build_ack = True

    def reboot(self) -> None:
        """Emit an unexpected boot marker, as a USB-reset Mega would."""
        with self._lock:
            self._mode = "vertical"
        self._emit(("@0 BOOT fw=mock-board",))

    def read(self, n: int = 1) -> bytes:
        """pyserial-compatible byte read; Rig currently uses ``readline``."""
        if not self.is_open:
            raise OSError("port closed")
        n = max(1, int(n))
        if not self._read_buffer:
            try:
                self._read_buffer.extend(self._out.get(timeout=0.2))
            except queue.Empty:
                return b""
        data = bytes(self._read_buffer[:n])
        del self._read_buffer[:n]
        return data

    def readline(self) -> bytes:
        if not self.is_open:
            raise OSError("port closed")
        if self._read_buffer:
            newline = self._read_buffer.find(b"\n")
            if newline >= 0:
                data = bytes(self._read_buffer[:newline + 1])
                del self._read_buffer[:newline + 1]
                return data
            data = bytes(self._read_buffer)
            self._read_buffer.clear()
            return data
        try:
            return self._out.get(timeout=0.2)
        except queue.Empty:
            return b""

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise OSError("port closed")
        command = data.decode("utf-8", errors="replace").strip()
        self.written.append(command)
        upper = command.upper()
        if upper.startswith("S "):
            self._handle_grid(command)
        elif upper == "0":
            self._emit(("  Homing X/Y...", "  AT ORIGIN. Position = X 0 / Y 0"))
        elif upper == "0+":
            self._emit(("=== FULL RESET - Z, then X/Y ===",
                        "FULL RESET COMPLETE - X/Y at origin, Z on its top switch."))
        elif upper in {"R", "RR"}:
            self._handle_mode(upper)
        elif upper.startswith("B "):
            self._handle_build(command)
        elif upper.startswith("G "):
            self._emit((f"  ARRIVED at cell [{command[2:]}]",))
        else:
            self._emit((f"ERROR - mock board does not understand {command!r}",))
        return len(data)

    def close(self) -> None:
        self.is_open = False

    def _handle_grid(self, command: str) -> None:
        parts = command.split()
        if len(parts) == 3:
            try:
                self._grid = f"{int(parts[1])}x{int(parts[2])}"
            except ValueError:
                pass
        self._emit(("GRID RESIZED", f"Division : {self._grid} highest indices"))

    def _handle_mode(self, command: str) -> None:
        wanted = "horizontal" if command == "RR" else "vertical"
        with self._lock:
            previous = self._mode
            self._mode = wanted
        if previous == wanted:
            self._emit((f"  ERROR - already in {wanted} mode.",))
            return
        self._emit((f"GRID MODE: {previous}  ->  {wanted}",))

    def _handle_build(self, command: str) -> None:
        parts = command.split()
        try:
            _, col, row, level = parts
            int(col), int(row), int(level)
        except ValueError:
            self._emit(("BUILD REJECTED - bad arguments", "@3 ERR bad arguments"))
            return

        with self._lock:
            failure = self._next_build_failure
            self._next_build_failure = None
            drop_ack = self._drop_next_build_ack
            self._drop_next_build_ack = False

        def finish():
            if self._build_seconds:
                time.sleep(self._build_seconds)
            if failure is None:
                lines = [f"BUILD COMPLETE - block placed at [{col},{row}] level {level}",
                         "PARKED - Z at the top, X/Y at the origin."]
                if not drop_ack:
                    lines.append(f"@3 OK col={col} row={row} level={level}")
            elif failure[0] in {"ABORTED", "HELD"}:
                lines = [f"BUILD ABORTED - {failure[1]}"]
                if not drop_ack:
                    lines.append(f"@3 HELD {failure[1]}")
            else:
                ack = "ERR" if failure[0] == "ERR" else "SAFE"
                lines = [f"BUILD REJECTED - {failure[1]}", "Nothing moved."]
                if not drop_ack:
                    lines.append(f"@3 {ack} {failure[1]}")
            self._emit(tuple(lines))

        threading.Thread(target=finish, name="mock-board-build", daemon=True).start()

    def _emit(self, lines: tuple[str, ...]) -> None:
        for line in lines:
            self.emitted.append(line)
            self._out.put((line + "\r\n").encode())

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

    #: The build phases the firmware announces, in order:
    #: ``(step, phase, action, wire label)``.  Copied from
    #: ``buildStep()``/``buildPark()`` in ``build_test_v1.ino`` — when the two
    #: disagree the sketch is right, and ``test_link.py`` says so.
    BUILD_PHASES = (
        (1, "raise_clear", "move", "Raise_Z_into_the_top_switch"),
        (2, "home_feeder", "move", "Home_XY_to_the_feeder"),
        (3, "neutralise_claw", "rotate", "Return_the_claw_to_neutral"),
        (4, "open_claw", "release", "Open_the_claw"),
        (5, "lower_to_ground", "move", "Lower_Z_to_the_ground_switch"),
        (6, "grip", "grip", "Close_the_claw_and_grip"),
        (7, "lift_block", "move", "Raise_Z_to_carry_height"),
        (8, "move_to_target", "move", "Move_XY_to_the_target_cell"),
        (9, "rotate_to_grid", "rotate", "Apply_the_grid_rotation"),
        (10, "lower_to_level", "move", "Lower_Z_to_the_target_level"),
        (11, "release", "release", "Open_the_claw_and_release"),
        (12, "park_clear", "park", "Raise_Z_clear_of_the_stack"),
        (13, "park_home", "park", "Return_XY_to_the_origin"),
        (14, "park_rotation", "park", "Return_the_claw_to_neutral"),
    )
    BUILD_STEP_COUNT = len(BUILD_PHASES)

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
        # The board assigns the sequence number, so the mock does too.  Seq 0
        # is reserved for BOOT/READY, exactly as in the firmware.
        self._seq = 0
        #: Which phase a scripted failure should die at, so a test can watch
        #: an abort land mid-carry rather than only at the end.
        self._fail_at_step = 0
        self._emit((
            "@0 BOOT fw=mock-board",
            "=== GRID ===",
            "Mock board: position is UNKNOWN until you home.",
            f"@0 READY grid={self._grid} mode={self._mode}",
        ))

    def fail_next_build(self, kind: str = "ABORTED",
                        reason: str = "simulated abort",
                        at_step: int = 0) -> None:
        """Make the next build finish as a safe rejection or unknown abort.

        ``at_step`` is which phase an ABORTED/HELD build dies at, 1-based.  The
        default 0 means "after the last phase", which is where a parking
        failure lands.  A rejection never reaches a phase at all: the firmware
        refuses it during validation, before anything moves, so a REJECTED
        build emits no STEP lines whatever ``at_step`` says.
        """
        kind = str(kind).upper()
        if kind not in {"ABORTED", "HELD", "REJECTED", "SAFE", "ERR"}:
            raise ValueError("kind must be ABORTED/HELD or REJECTED/SAFE/ERR")
        at_step = int(at_step)
        if not 0 <= at_step <= self.BUILD_STEP_COUNT:
            raise ValueError(f"at_step must be 0..{self.BUILD_STEP_COUNT}")
        with self._lock:
            self._next_build_failure = kind, str(reason)
            self._fail_at_step = at_step

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

    #: Predicted durations the firmware sends as `ms=` on its Z moves, keyed by
    #: phase.  The real numbers come from `zEtaMs()` in the sketch — step count
    #: times `stepPeriodMs(AXIS_Z)` — and are level-dependent for
    #: `lower_to_level`.  These are the full-travel figures for a stock rig
    #: (1350 steps x 1.9 ms + DIR_SETTLE_MS); the mock does not model Z
    #: position, so it sends the same number every time.  Phases the firmware
    #: cannot predict send nothing at all, and that absence is deliberate.
    PHASE_ETA_MS = {"raise_clear": 2570, "lower_to_ground": 2570,
                    "lift_block": 2570, "lower_to_level": 2570,
                    "park_clear": 2570}

    def _step_line(self, seq: int, step: int, phase: str, action: str,
                   label: str, status: str) -> str:
        line = (f"@{seq} STEP step={step} total={self.BUILD_STEP_COUNT} "
                f"phase={phase} action={action} text={label} status={status}")
        eta = self.PHASE_ETA_MS.get(phase) if status == "begin" else None
        return f"{line} ms={eta}" if eta else line

    def _handle_build(self, command: str) -> None:
        parts = command.split()
        with self._lock:
            self._seq += 1
            seq = self._seq
        try:
            _, col, row, level = parts
            int(col), int(row), int(level)
        except ValueError:
            self._emit(("BUILD REJECTED - bad arguments", f"@{seq} ERR bad arguments"))
            return

        with self._lock:
            failure = self._next_build_failure
            self._next_build_failure = None
            fail_at = self._fail_at_step
            self._fail_at_step = 0
            drop_ack = self._drop_next_build_ack
            self._drop_next_build_ack = False

        rejected = failure is not None and failure[0] not in {"ABORTED", "HELD"}
        self._emit((f"@{seq} RECV cmd=B col={col} row={row} level={level}",))

        def finish():
            if rejected:
                # Refused during validation.  Nothing moved, so there is no
                # phase to announce — that absence is itself information.
                if self._build_seconds:
                    time.sleep(self._build_seconds)
                ack = "ERR" if failure[0] == "ERR" else "SAFE"
                lines = [f"BUILD REJECTED - {failure[1]}", "Nothing moved."]
                if not drop_ack:
                    lines.append(f"@{seq} {ack} {failure[1]}")
                self._emit(tuple(lines))
                return

            aborting = failure is not None
            last = fail_at if (aborting and fail_at) else self.BUILD_STEP_COUNT
            # Spread the phases across the whole build so a consumer sees them
            # arrive one at a time, the way a 40-second build delivers them.
            pause = (self._build_seconds / max(1, last)) if self._build_seconds else 0.0

            for step, phase, action, label in self.BUILD_PHASES[:last]:
                self._emit((self._step_line(seq, step, phase, action, label, "begin"),
                            f"[BUILD {step}/{self.BUILD_STEP_COUNT}] {label}"))
                if pause:
                    time.sleep(pause)
                # The one 'done': the block has left the claw.  Not emitted when
                # the run dies before finishing the release.
                if step == 11 and not (aborting and fail_at == 11):
                    self._emit((self._step_line(seq, step, phase, action, label,
                                                "done"),))

            if aborting:
                lines = [f"BUILD ABORTED - {failure[1]}",
                         "*** The claw may still be holding a block. Check the rig."]
                if not drop_ack:
                    lines.append(f"@{seq} HELD {failure[1]}")
            else:
                lines = [f"BUILD COMPLETE - block placed at [{col},{row}] level {level}",
                         "PARKED - Z at the top, X/Y at the origin."]
                if not drop_ack:
                    lines.append(f"@{seq} OK col={col} row={row} level={level}")
            self._emit(tuple(lines))

        threading.Thread(target=finish, name="mock-board-build", daemon=True).start()

    def _emit(self, lines: tuple[str, ...]) -> None:
        for line in lines:
            self.emitted.append(line)
            self._out.put((line + "\r\n").encode())

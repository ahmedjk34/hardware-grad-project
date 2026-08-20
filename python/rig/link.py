#!/usr/bin/env python3
"""The serial link to the rig: open the port, send a line, know when it finished.

    from rig.link import Rig

    rig = Rig()                 # reads config/rig.json
    rig.connect()               # opens the port, waits out the reboot banner
    rig.send("5")               # fire and forget, like the console does
    rig.build(3, 5, 0)          # blocks, returns 'placed'/'rejected'/'aborted'

`rig_console.py` is a thin wrapper around the first three lines. Anything that
needs to KNOW whether a command worked — the camera viewer, next — uses the
fourth.

How completion is detected
--------------------------
The firmware talks to a human: it prints prose, not status codes. Two ways out
of that, and this module uses both:

1. `@` acknowledgement lines. `build_test_v1` prints one beside the prose for
   every build outcome — `@3 OK col=3 row=5 level=0`, `@3 SAFE ...`,
   `@3 HELD ...`. A fixed token in a fixed position. This is the real answer.
   See plans/ack-protocol.md.
2. Prose matching, as a FALLBACK, because the ack lines are compile-verified
   but were written before anyone flashed them. Every time the fallback fires
   it says so on stderr. Once it has gone quiet for a while, delete it.

Only `B` is acked. `S`, `0`, `0+` and `G` predate the protocol and still print
prose only, so those wait on prose plus a settle period instead — see
`_send_and_settle`.

SAFE and HELD are NOT the same failure
--------------------------------------
`rejected` means nothing moved: a typo, retry freely. `aborted` means the run
died half way and **the claw may still be gripping a block at an unknown
position**. That needs a human at the rig, not a retry. They are separate words
here for the same reason they are separate kinds in the firmware: so that
calling code cannot handle both with one `if not ok: retry`.

Two hardware facts this module is shaped around
-----------------------------------------------
- **The rig goes deaf during a build.** `buildBlock()` runs homing, Z travel and
  the servo inside one synchronous call and never reads serial while it does.
  A second command sent into that silence sits in a 64-byte buffer and arrives
  late. So the waiting sends refuse to overlap — see `RigBusy`.
- **Opening the port reboots the board.** Normal USB serial behaviour on a Mega:
  DTR toggles, the sketch restarts, and it forgets its grid size. That is why
  `connect()` pushes `S <cols> <rows>` from config/rig.json every time. An
  unexpected `@0 BOOT` at any other moment means it happened again underneath
  us, and is raised as `RigReset`.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from dataclasses import dataclass, field

import serial

from rig.config import load

# ------------------------------------------------------------------
# Ack lines
# ------------------------------------------------------------------

ACK_PREFIX = "@"

# Kinds that END a command. Everything else (RECV, RUN, and the seq-0 events)
# is progress or chatter. Only OK/ERR/SAFE/HELD are emitted by the firmware
# today; BUSY is listed because the protocol reserves it and a Pi that ignored
# it would hang instead of failing.
TERMINAL_KINDS = frozenset({"OK", "ERR", "SAFE", "HELD", "BUSY"})

# The three words a caller has to handle.
PLACED = "placed"
REJECTED = "rejected"
ABORTED = "aborted"

_KIND_TO_OUTCOME = {
    "OK": PLACED,
    "ERR": REJECTED,  # refused at parse time, nothing moved
    "SAFE": REJECTED,  # refused at validation time, nothing moved
    "BUSY": REJECTED,  # refused because something was already running
    "HELD": ABORTED,  # died mid-motion, claw state unknown
}


@dataclass(frozen=True)
class Ack:
    """One `@<seq> <KIND> [reason words] [key=value ...]` line, parsed.

    `args` and `fields` are split rather than merged because the firmware uses
    both shapes: `OK` and `READY` carry key=value pairs, while ERR/SAFE/HELD
    carry the same free-text reason the prose above them already printed.
    """

    seq: int
    kind: str
    args: tuple[str, ...] = ()
    fields: dict = field(default_factory=dict)
    raw: str = ""

    @property
    def reason(self) -> str:
        return " ".join(self.args)

    @property
    def terminal(self) -> bool:
        return self.kind in TERMINAL_KINDS


def parse_ack(line: str) -> Ack | None:
    """Turn a machine line into an Ack, or None if it is prose.

    One `startswith` is the whole filter: no other line the sketch prints
    begins with '@' (checked — zero occurrences), which is why that character
    was chosen.
    """
    line = line.strip()
    if not line.startswith(ACK_PREFIX):
        return None

    parts = line[1:].split()
    if len(parts) < 2:
        return None

    try:
        seq = int(parts[0])
    except ValueError:
        # '@' followed by something that is not a sequence number. Not ours.
        return None

    args: list[str] = []
    fields: dict[str, str] = {}
    for token in parts[2:]:
        if "=" in token:
            key, _, value = token.partition("=")
            fields[key] = value
        else:
            args.append(token)

    return Ack(seq=seq, kind=parts[1].upper(), args=tuple(args), fields=fields, raw=line)


# ------------------------------------------------------------------
# Build results
# ------------------------------------------------------------------


class BuildResult(str):
    """The outcome word, with the detail carried along.

    It IS the string 'placed' / 'rejected' / 'aborted', so
    `rig.build(3, 5, 0) == PLACED` reads the way you would write it and a REPL
    prints the answer without unpacking anything. The extras hang off it:

        r = rig.build(3, 5, 0)
        r == ABORTED        -> go and look at the rig
        r.reason            -> 'Z never reached the ground switch'
        r.ack               -> the Ack it came from, or None if prose

    Deliberately no __bool__: a non-empty string is always truthy, so
    `if rig.build(...)` would silently mean 'yes' even for an abort. Compare
    against the word, or use .ok.
    """

    reason: str
    ack: Ack | None
    lines: tuple
    from_prose: bool

    def __new__(cls, outcome, reason="", ack=None, lines=(), from_prose=False):
        self = super().__new__(cls, outcome)
        self.reason = reason
        self.ack = ack
        self.lines = tuple(lines)
        self.from_prose = from_prose
        return self

    @property
    def ok(self) -> bool:
        return str(self) == PLACED

    @property
    def needs_a_human(self) -> bool:
        """True when the claw may still be holding a block. Do not retry."""
        return str(self) == ABORTED

    def __repr__(self) -> str:
        detail = f" ({self.reason})" if self.reason else ""
        return f"<BuildResult {str(self)}{detail}>"


# ------------------------------------------------------------------
# Errors
# ------------------------------------------------------------------


class RigError(Exception):
    """Anything wrong with the link itself, as opposed to the build."""


class RigNotConnected(RigError):
    pass


class RigBusy(RigError):
    """A command is already in flight. The rig is not listening — do not queue."""


class RigTimeout(RigError):
    """The rig said nothing conclusive in time. State is UNKNOWN — go and look."""


class RigReset(RigError):
    """An unexpected `@0 BOOT`. The board rebooted: it has forgotten its grid
    and its homing, and anything in flight died with it."""


# ------------------------------------------------------------------
# The link
# ------------------------------------------------------------------

# Events the reader thread hands to whoever is waiting.
_ACK = "ack"
_LINE = "line"
_DEAD = "dead"

_EVENT_QUEUE_MAX = 4096


class Rig:
    """One serial connection to the rig. Not thread-safe by design: the rig
    runs strictly one command at a time, so the waiting sends take a lock and
    raise `RigBusy` rather than queueing behind each other."""

    def __init__(self, cfg: dict | None = None, on_line=None, on_error=None):
        """`on_line` is called from the reader thread with every raw line the
        rig prints, acks included. That is how `rig_console.py` still shows
        everything while this class quietly parses the same stream.

        `on_error` is called from the same thread when the port dies under it.
        A waiting command finds out by getting `RigError` raised at it, but an
        idle console has nobody waiting, so it needs telling."""
        cfg = cfg if cfg is not None else load()
        self.port_name: str = cfg["serial"]["port"]
        self.baud: int = cfg["serial"]["baud"]
        self.cols: int = cfg["grid"]["cols"]
        self.rows: int = cfg["grid"]["rows"]

        self._on_line = on_line
        self._on_error = on_error
        self._port: serial.Serial | None = None
        self._reader: threading.Thread | None = None
        self._stopping = threading.Event()
        # Bounded, oldest-dropped. While a command is in flight the waiter
        # drains this as fast as the rig fills it; the cap is for the other
        # case — an idle console sitting open for hours, where nobody is
        # reading and every banner line would otherwise be kept forever.
        self._events: queue.Queue = queue.Queue(maxsize=_EVENT_QUEUE_MAX)
        self._inflight = threading.Lock()

        # Set by the reader thread the moment a BOOT arrives. Checked rather
        # than raised there, because the reader has nobody to raise at.
        self._booted = threading.Event()

        self.ready_grid: str | None = None  # what the board booted with
        self.prose_fallbacks = 0  # how often the ack lines were missing

    # -- lifecycle -------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._port is not None and self._port.is_open

    def connect(self, timeout: float = 25.0, configure: bool = True,
                home: bool = False) -> None:
        """Open the port, wait out the reboot, and put the board in a known state.

        Three steps, in order:

        1. read until `@0 READY` — that line is the last thing `setup()` prints,
           so it ends the banner exactly. Before the acks existed this meant
           matching the final banner line by its wording, which broke whenever
           someone reworded it.
        2. send `S <cols> <rows>` from config/rig.json. The sketch has no EEPROM
           and the port-open reset just wiped its grid back to the compiled
           default, so this is not optional.
        3. optionally `0+` — home Z, park it at the top, home X/Y.

        `home` defaults to FALSE because opening a connection should not make
        the machine move on its own. `B` homes everything itself anyway, so
        this is about starting a session in a state you can reason about, not
        about safety. Pass `home=True` when nobody is going to be surprised.
        """
        if self.connected:
            raise RigError("already connected")

        try:
            # timeout= is the per-readline timeout, not a connect timeout: the
            # reader thread needs to wake up regularly to notice _stopping.
            self._port = serial.Serial(self.port_name, self.baud, timeout=0.2)
        except serial.SerialException as exc:
            raise RigError(
                f"Cannot open {self.port_name} at {self.baud}: {exc}\n"
                "  - board plugged in?    ./scripts/flash.sh boards\n"
                "  - permission denied?   sudo usermod -aG dialout $USER, then log out\n"
                "  - wrong port?          a CH340 clone is /dev/ttyUSB0, set it in "
                "config/rig.json"
            ) from exc

        self._stopping.clear()
        self._booted.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        self._wait_ready(timeout)
        if configure:
            self.set_grid()
        if home:
            self.home()

    def close(self) -> None:
        """Order matters: flag first, then close, then let the reader notice.
        Closing the port under a thread that is mid-print can take the
        interpreter down with it."""
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

    def __enter__(self):
        if not self.connected:
            self.connect()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # -- the reader thread -----------------------------------------

    def _read_loop(self) -> None:
        """Print-and-parse every line, until told to stop or the cable goes.

        Decoding is lenient: a reset mid-line hands us a partial UTF-8 sequence,
        and a garbled character is not worth a traceback.
        """
        port = self._port
        while not self._stopping.is_set():
            try:
                raw = port.readline()
            # TypeError is in the list because pyserial sets its file descriptor
            # to None on close, and a readline() already blocked on that fd then
            # fails inside os.read rather than raising anything serial-shaped.
            except (serial.SerialException, OSError, TypeError):
                if not self._stopping.is_set():
                    message = "serial port went away — cable unplugged?"
                    self._put((_DEAD, message, time.monotonic()))
                    if self._on_error is not None:
                        self._on_error(message)
                return
            if not raw:
                continue

            text = raw.decode("utf-8", errors="replace").rstrip()
            if self._on_line is not None:
                self._on_line(text)

            ack = parse_ack(text)
            if ack is None:
                self._put((_LINE, text, time.monotonic()))
                continue

            if ack.kind == "BOOT":
                self._booted.set()
            elif ack.kind == "READY":
                self.ready_grid = ack.fields.get("grid")
            self._put((_ACK, ack, time.monotonic()))

    def _put(self, event) -> None:
        """Queue an event, dropping the oldest if nobody is keeping up."""
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
        """Throw away everything that arrived before this command.

        Without it, a `B` would happily match the `@0 READY` still sitting in
        the queue from connect time.
        """
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                return

    # -- sending ---------------------------------------------------

    def send(self, line: str) -> None:
        """Write one line and return immediately. No waiting, no parsing.

        This is what the console uses. Every multi-character command in the
        sketch needs the newline, and the single-character ones tolerate it.
        """
        if not self.connected:
            raise RigNotConnected("not connected — call connect() first")
        self._port.write((line.strip() + "\n").encode())

    # -- waiting ---------------------------------------------------

    def _wait_ready(self, timeout: float) -> None:
        """Read until `@0 READY`, or until the banner stops arriving.

        The fallback exists because the ack lines have never been flashed: a
        board still running the pre-ack firmware would otherwise hang here for
        the whole timeout on every connect.
        """
        deadline = time.monotonic() + timeout
        last_line_at = None

        while time.monotonic() < deadline:
            kind, payload, at = self._next_event(deadline)
            if kind is None:
                # Silence. Either the board is still inside setup()'s
                # delay(1000), or the banner has finished and there is no
                # READY coming.
                if last_line_at is not None and time.monotonic() - last_line_at > 2.0:
                    break
                continue
            if kind == _DEAD:
                raise RigError(payload)
            if kind == _ACK and payload.kind == "READY":
                return
            last_line_at = at

        if last_line_at is None:
            raise RigTimeout(
                f"{self.port_name} said nothing in {timeout:.0f}s. Wrong baud, "
                "wrong port, or a board with no sketch on it."
            )
        self._note_fallback("no '@0 READY' in the banner — is the firmware flashed?")

    def _next_event(self, deadline: float):
        """One event, or (None, None, None) if nothing arrived before `deadline`."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return (None, None, None)
        try:
            return self._events.get(timeout=min(remaining, 0.2))
        except queue.Empty:
            return (None, None, None)

    def _note_fallback(self, why: str) -> None:
        """Say out loud that the ack lines were not there.

        Counted as well as printed: the plan is to delete the prose matching
        once this has stopped firing, and 'stopped firing' needs evidence.
        """
        self.prose_fallbacks += 1
        print(f"!! prose fallback: {why}", file=sys.stderr)

    def _send_and_settle(self, line: str, timeout: float, done: tuple[str, ...],
                         settle: float = 1.0, quiet: float | None = None) -> list[str]:
        """For the commands that predate the ack protocol: `S`, `0`, `0+`, `G`.

        There is no terminal token to wait for, so this waits for one of the
        `done` strings, then for `settle` seconds of silence to pick up the
        lines printed after it.

        `quiet` is the escape hatch for a board whose wording has drifted: if
        it printed something, then said nothing for `quiet` seconds, give up
        waiting and return what there is. **It is None for anything that
        moves.** `seekLimit()` prints "Seeking X- (pin 3) ..." and then goes
        completely silent for the entire travel, so on `0+` or `G` a quiet
        period means the motor is running, not that the command finished.
        Guessing wrong there would hand back a made-up answer and let the next
        command go out while the rig is still moving. A timeout is the safe
        failure.
        """
        if not self._inflight.acquire(blocking=False):
            raise RigBusy("a command is already running — the rig is not listening")
        try:
            self._drain()
            self.send(line)

            deadline = time.monotonic() + timeout
            collected: list[str] = []
            saw_done = False
            last_at = time.monotonic()

            while time.monotonic() < deadline:
                kind, payload, at = self._next_event(deadline)
                if kind is None:
                    quiet_for = time.monotonic() - last_at
                    if saw_done and quiet_for > settle:
                        return collected
                    if quiet is not None and collected and quiet_for > quiet:
                        self._note_fallback(
                            f"{line!r} printed, then went quiet without saying "
                            f"any of {done}"
                        )
                        return collected
                    continue
                last_at = at
                if kind == _DEAD:
                    raise RigError(payload)
                if kind == _ACK:
                    if payload.kind == "BOOT":
                        raise RigReset(f"board reset while running {line!r}")
                    continue
                collected.append(payload)
                if any(marker in payload for marker in done):
                    saw_done = True

            raise RigTimeout(f"{line!r} did not finish in {timeout:.0f}s")
        finally:
            self._inflight.release()

    # -- commands --------------------------------------------------

    def set_grid(self, cols: int | None = None, rows: int | None = None) -> None:
        """Push the grid from config/rig.json. The board forgot it on reset."""
        cols = self.cols if cols is None else cols
        rows = self.rows if rows is None else rows
        # quiet= is safe here and only here: S moves nothing and answers
        # immediately, so silence after its output really is the end of it.
        out = self._send_and_settle(
            f"S {cols} {rows}",
            timeout=10.0,
            done=("GRID RESIZED", "ERROR - grid must be"),
            quiet=3.0,
        )
        if any("ERROR - grid must be" in line for line in out):
            raise RigError(
                f"the rig refused the grid {cols}x{rows} from config/rig.json:\n  "
                + "\n  ".join(line for line in out if "ERROR" in line or "cols" in line)
            )

    def home(self, full: bool = True, timeout: float = 180.0) -> bool:
        """`0+` (Z down, Z up, then X/Y) or `0` (X/Y only). True if it completed.

        False is not an exception: the firmware prints its own warnings and
        stops safely, and the caller has to decide whether it cares.
        """
        line = "0+" if full else "0"
        done = ("FULL RESET COMPLETE", "FULL RESET INCOMPLETE") if full else (
            "AT ORIGIN", "ORIGIN NOT REACHED")
        out = self._send_and_settle(line, timeout=timeout, done=done)
        bad = ("FULL RESET INCOMPLETE", "ORIGIN NOT REACHED", "ABORTED")
        return not any(marker in text for text in out for marker in bad)

    def goto(self, col: int, row: int, timeout: float = 180.0) -> bool:
        """`G <col> <row>` — drive to a cell without picking anything up.

        The safe way to check a pixel-to-cell mapping: a wrong answer costs a
        wasted trip, not a dropped block.
        """
        out = self._send_and_settle(
            f"G {col} {row}",
            timeout=timeout,
            done=("ARRIVED at cell", "MOVE INCOMPLETE", "ABORTED", "ERROR"),
        )
        if any("ARRIVED at cell" in text for text in out):
            return True
        # gotoCell() can also fail before it prints anything at all, when
        # gridReady() or cellInRange() rejects it — hence "did it say ARRIVED"
        # rather than "did it say a bad word".
        return False

    def build(self, col: int, row: int, level: int, rotation: str | None = None,
              timeout: float = 300.0) -> BuildResult:
        """`B <col> <row> <level>` — one full pick-and-place. Blocks until done.

        Returns 'placed', 'rejected' or 'aborted'. **'aborted' means stop.**
        The claw may still be gripping a block somewhere unknown; the firmware
        says so itself. Do not retry it, do not home it, go and look.

        The timeout is generous on purpose. A build is ~40 s of motion, and the
        firmware bounds every one of its own seeks and reports its own failures
        (see plans/ack-protocol.md on why there is no watchdog). Hitting this
        timeout therefore means something outside the firmware's model went
        wrong, which is also a go-and-look, not a retry.
        """
        command = f"B {col} {row} {level}"
        if rotation:
            command += f" {rotation.upper()}"

        if not self._inflight.acquire(blocking=False):
            raise RigBusy("a build is already running — the rig is not listening")
        try:
            self._drain()
            self.send(command)
            return self._wait_build(command, timeout)
        finally:
            self._inflight.release()

    def _wait_build(self, command: str, timeout: float) -> BuildResult:
        """One terminal ack, or the prose that says the same thing."""
        deadline = time.monotonic() + timeout
        collected: list[str] = []

        # Prose fallback state. It cannot stop at the first match the way the
        # ack can: 'BUILD COMPLETE' prints BEFORE the parking warnings, and a
        # build that placed the block but failed to park is HELD, not OK. So a
        # prose match starts a short settle window instead of returning.
        prose_outcome: str | None = None
        prose_reason = ""
        prose_at = 0.0

        while time.monotonic() < deadline:
            kind, payload, at = self._next_event(deadline)

            if kind is None:
                if prose_outcome is not None and time.monotonic() - prose_at > 1.5:
                    self._note_fallback(f"no ack for {command!r}, read the prose instead")
                    return BuildResult(prose_outcome, prose_reason, None, collected, True)
                continue

            if kind == _DEAD:
                raise RigError(payload)

            if kind == _ACK:
                ack = payload
                if ack.kind == "BOOT":
                    raise RigReset(
                        f"the board reset during {command!r}. It has forgotten its "
                        "grid and its homing, and the claw may still be holding a "
                        "block. Reconnect, then go and look at the rig."
                    )
                if ack.terminal:
                    return BuildResult(
                        _KIND_TO_OUTCOME[ack.kind], ack.reason, ack, collected, False
                    )
                continue

            collected.append(payload)
            outcome, reason = _prose_outcome(payload)
            if outcome is None:
                continue
            # A later line can only make the news worse, never better: PARKING
            # FAILED downgrades a COMPLETE to an abort.
            if prose_outcome is None or outcome == ABORTED:
                prose_outcome, prose_reason, prose_at = outcome, reason, at

        raise RigTimeout(
            f"{command!r} did not finish in {timeout:.0f}s and said nothing "
            "conclusive. The rig's state is UNKNOWN — go and look at it before "
            "sending anything else."
        )


def _prose_outcome(line: str) -> tuple[str | None, str]:
    """Read a build outcome out of the human text. The fallback path only.

    Every string here is a literal in build_test_v1.ino. If you reword one
    there, this is the grep hit AGENTS.md section 6 is telling you about.
    """
    if "BLOCK IS PLACED, BUT PARKING FAILED" in line:
        return ABORTED, "block placed but parking failed"
    if "BUILD COMPLETE" in line:
        return PLACED, ""
    if "BUILD REJECTED" in line:
        return REJECTED, line.split(" - ", 1)[-1].strip()
    if "BUILD ABORTED" in line:
        return ABORTED, line.split(" - ", 1)[-1].strip()
    if "ERROR - use:  B " in line or "rotation must be R, RR or NR" in line:
        return REJECTED, "bad arguments"
    return None, ""

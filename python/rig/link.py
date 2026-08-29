#!/usr/bin/env python3
"""The serial link to the rig: open the port, send a line, know when it finished.

    from rig.link import Rig

    rig = Rig()                 # reads config/rig.json
    rig.connect()               # opens the port, waits out the reboot banner
    rig.send("5")               # fire and forget, like the console does
    rig.build(3, 5, 0)          # blocks, returns 'placed'/'rejected'/'aborted'
    rig.build(0, 5, 0)          # calibration: target Y only

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
  DTR toggles, the sketch restarts, and it forgets its grid size AND its grid
  mode — it comes back vertical, whatever it was doing. That is why `connect()`
  pushes the mode and then `S <cols> <rows>` from config/rig.json every time,
  in that order: `S` is validated against the active mode's geometry, so
  pushing it first checks the counts against the wrong grid. An unexpected
  `@0 BOOT` at any other moment means it happened again underneath us, and is
  raised as `RigReset`.

Build rotation is not per-block
-------------------------------
`build()` takes no rotation. Which way a block is laid is a property of the
active GRID, not of the block: the vertical grid places blocks as the feeder
presents them, the horizontal grid turns every one of them 90° CCW. Choose
with `set_mode()`, which sends the firmware's `R` / `RR` latch. See
plans/dual-orientation-grid.md D7 and D8.

For a deliberate bench test there is also `rotate_aux(degrees)`, which sends
the firmware's signed relative `A <degrees>` command. It is not an absolute
angle — the aux stepper has no home switch — and a non-grid-aligned manual
angle disables manual `G`/mode-latch moves until the next `B` returns neutral.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from dataclasses import dataclass, field

import serial

from rig.config import (DEFAULT_GRID_MODE, GRID_MODES, load,
                        serial_port_candidates)
from rig.grid import MachineGrid

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

    def __init__(self, cfg: dict | None = None, on_line=None, on_error=None,
                 mode: str | None = None):
        """`on_line` is called from the reader thread with every raw line the
        rig prints, acks included. That is how `rig_console.py` still shows
        everything while this class quietly parses the same stream.

        `on_error` is called from the same thread when the port dies under it.
        A waiting command finds out by getting `RigError` raised at it, but an
        idle console has nobody waiting, so it needs telling."""
        cfg = cfg if cfg is not None else load()
        self.port_name: str = cfg["serial"]["port"]
        self.baud: int = cfg["serial"]["baud"]
        # One object validates the logical counts, block footprints, gaps,
        # trims and 24.3x40 cm displacement of the SELECTED MODE before S is
        # sent. Which mode that is comes from grid.active_mode in the config.
        self._cfg = cfg
        # A UI may make an explicit one-session mode choice before it opens
        # the port.  Store that desired grid now, so connect() can home before
        # it attempts the mode latch after the board's reset-to-vertical boot.
        self.grid = MachineGrid.from_config(cfg, mode=mode)
        self.cols: int = self.grid.cols
        self.rows: int = self.grid.rows

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
        # The board's own word for which grid it is in. A reset returns it to
        # 'vertical' without asking, so this is read from the machine rather
        # than assumed from the config.
        self.ready_mode: str | None = None
        # Unlike the transient BOOT event, this remains set until an explicit,
        # human-authorized recovery homes the reset board and replays its mode
        # and size.  Otherwise an idle reset could be drained by the next
        # command and leave Python addressing the wrong layout.
        self._reset_detected = False
        self.prose_fallbacks = 0  # how often the ack lines were missing

    # -- lifecycle -------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._port is not None and self._port.is_open

    def connect(self, timeout: float = 25.0, configure: bool = True,
                home: bool = False, home_before_configure: bool = False) -> None:
        """Open the port, wait out the reboot, and put the board in a known state.

        Four steps, in order:

        1. read until `@0 READY` — that line is the last thing `setup()` prints,
           so it ends the banner exactly. Before the acks existed this meant
           matching the final banner line by its wording, which broke whenever
           someone reworded it.
        2. optionally home X/Y with ``0`` before configuring. This is for an
           explicit horizontal-mode request: its ``RR`` latch is only legal
           after X/Y are homed.
        3. push the grid MODE from config/rig.json (or an explicit one-session
           override), then send
           `S <cols> <rows>` — in that order. The sketch has no EEPROM and the
           port-open reset just wiped both back to the compiled vertical
           default, so neither is optional. The order is not arbitrary: the
           firmware validates `S` against the active mode's geometry, so
           sending it first would check the counts against the wrong grid.
        4. optionally `0+` — home Z, park it at the top, home X/Y.

        `home` defaults to FALSE because opening a connection should not make
        the machine move on its own. `B` homes everything itself anyway, so
        this is about starting a session in a state you can reason about, not
        about safety. Pass `home=True` when nobody is going to be surprised.
        """
        if self.connected:
            raise RigError("already connected")

        last_error = None
        for candidate in serial_port_candidates(self.port_name):
            try:
                # timeout= is the per-readline timeout, not a connect timeout:
                # the reader thread needs to wake up regularly to notice stop.
                self._port = serial.Serial(candidate, self.baud, timeout=0.2)
                self.port_name = candidate
                break
            except serial.SerialException as exc:
                last_error = exc
        if self._port is None:
            raise RigError(
                f"Cannot open /dev/ttyACM0 or /dev/ttyACM1 at {self.baud}: {last_error}\n"
                "  - board plugged in?    ./scripts/flash.sh boards\n"
                "  - permission denied?   sudo usermod -aG dialout $USER, then log out\n"
                "  - wrong port?          a CH340 clone is /dev/ttyUSB0, set it in "
                "config/rig.json"
            ) from last_error

        self._stopping.clear()
        self._booted.clear()
        self._reset_detected = False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        self._wait_ready(timeout)
        # This BOOT is the expected port-open reset; it is exactly what the
        # following configure handshake is here to repair. Later BOOT events
        # remain latched until recover_after_reset() is explicitly authorized.
        self._reset_detected = False
        if home_before_configure:
            if not self.home(full=False):
                raise RigError("X/Y home did not reach the origin before configuration")
        if configure:
            self.sync_mode()
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
                self.ready_grid = None
                self.ready_mode = None
                self._reset_detected = True
            elif ack.kind == "READY":
                self.ready_grid = ack.fields.get("grid")
                # Absent on firmware predating the mode latch. None means
                # "the board did not say", not "vertical".
                self.ready_mode = ack.fields.get("mode")
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

    def _require_not_reset(self) -> None:
        if self._reset_detected:
            raise RigReset(
                "the board reset and is back in its unhomed vertical default. "
                "Inspect the rig, then call recover_after_reset(home=True) "
                "before sending another command."
            )

    def recover_after_reset(self, *, home: bool = False) -> None:
        """Explicitly restore mode and size after an unexpected board reset.

        A reset loses homing as well as returning the firmware to vertical.
        D9 therefore makes an automatic horizontal latch impossible and the
        build UI deliberately never calls this method: a person must inspect
        the claw and consciously authorize the recovery homing move. Once
        homed, replay the same safe order as connect: mode first, then ``S``.
        """
        if not self._reset_detected:
            return
        if not home:
            raise RigReset(
                "the board reset; inspect it and call "
                "recover_after_reset(home=True) to home and re-sync the grid"
            )
        # The explicit `home=True` is the authorization for this motion. Let
        # the normal helpers run, but restore the lock if anything goes wrong.
        self._reset_detected = False
        try:
            if not self.home():
                raise RigError("reset recovery homing did not reach the origin")
            self.ready_mode = DEFAULT_GRID_MODE
            self.sync_mode()
            self.set_grid()
        except Exception:
            self._reset_detected = True
            raise

    def set_grid(self, cols: int | None = None, rows: int | None = None) -> None:
        """Push the grid from config/rig.json. The board forgot it on reset.

        `S` is scoped to the board's ACTIVE mode and revalidated against that
        mode's geometry, so the mode has to be right before this is sent.
        `connect()` does them in that order.
        """
        self._require_not_reset()
        cols = self.cols if cols is None else cols
        rows = self.rows if rows is None else rows
        # quiet= is safe here and only here: S moves nothing and answers
        # immediately, so silence after its output really is the end of it.
        out = self._send_and_settle(
            f"S {cols} {rows}",
            timeout=10.0,
            done=("GRID RESIZED", "ERROR - grid must be", "ERROR - claw"),
            quiet=3.0,
        )
        if any("ERROR - grid must be" in line or "ERROR - claw" in line
               for line in out):
            raise RigError(
                f"the rig refused the grid {cols}x{rows} from config/rig.json:\n  "
                + "\n  ".join(line for line in out if "ERROR" in line or "cols" in line)
            )

    def set_mode(self, mode: str, timeout: float = 20.0,
                 push_grid: bool = True) -> None:
        """Latch the board's grid mode with `R` (vertical) or `RR` (horizontal).

        This moves nothing. It changes which grid every coordinate refers to —
        `[3,5]` means a different physical place afterwards, so anything
        holding a cell from before the switch is holding a stale one.

        The firmware refuses the latch unless X and Y are homed (a mode switch
        redefines what the current cell means). It does NOT home for you: an
        un-homed rig raises rather than starting an unasked-for motion.

        `push_grid` re-sends `S` afterwards, because the board's counts for the
        newly selected mode are ITS compiled defaults, not this config's.
        `connect()` passes False only because it sends `S` itself immediately
        after.
        """
        self._require_not_reset()
        mode = str(mode)
        if mode not in GRID_MODES:
            raise ValueError(
                f"grid mode must be one of {', '.join(GRID_MODES)}, not {mode!r}")

        # Build the new grid BEFORE touching the machine: an unknown mode or a
        # geometry that does not fit should fail with the rig untouched.
        grid = MachineGrid.from_config(self._cfg, mode=mode)

        command = "RR" if mode == "horizontal" else "R"
        out = self._send_and_settle(
            command,
            timeout=timeout,
            done=("GRID MODE:", "ERROR - already in", "ERROR - home X/Y first",
                  "ERROR - claw", "ERROR - the", "ERROR - use:"),
            quiet=3.0,
        )
        latched = any("GRID MODE:" in line for line in out)
        # "already in" is the firmware refusing to confirm a state nobody asked
        # it to reach. From the Pi's side, wanting what you already have is
        # simply done, so it counts as success here and nowhere else.
        already = any("ERROR - already in" in line for line in out)
        if not (latched or already):
            raise RigError(
                f"the rig refused to switch to the {mode} grid:\n  "
                + "\n  ".join(line.strip() for line in out if line.strip())
            )

        self.grid = grid
        self.cols, self.rows = grid.cols, grid.rows
        if push_grid:
            self.set_grid()

    def sync_mode(self, timeout: float = 20.0) -> None:
        """Make the board's mode agree with this Rig's grid. Called on connect.

        The board comes up vertical after every reset, so a session that wants
        horizontal has to say so before anything else — see R4 in
        plans/dual-orientation-grid.md. Sending the latch is skipped when the
        board has already told us, on its READY line, that it is where we want
        it; that keeps the common vertical case free of an error line in the
        log and free of an unasked-for homing move.
        """
        wanted = self.grid.mode or DEFAULT_GRID_MODE
        if self.ready_mode is not None and self.ready_mode == wanted:
            return
        if self.ready_mode is None and wanted == DEFAULT_GRID_MODE:
            # Firmware too old to report its mode. It has just reset, so it is
            # vertical, and vertical is what we want: nothing to do.
            return
        # connect() sends S itself on the next line, so do not send it twice.
        self.set_mode(wanted, timeout=timeout, push_grid=False)

    def home(self, full: bool = True, timeout: float = 180.0) -> bool:
        """`0+` (Z down, Z up, then X/Y) or `0` (X/Y only). True if it completed.

        False is not an exception: the firmware prints its own warnings and
        stops safely, and the caller has to decide whether it cares.
        """
        self._require_not_reset()
        line = "0+" if full else "0"
        done = ("FULL RESET COMPLETE", "FULL RESET INCOMPLETE") if full else (
            "AT ORIGIN", "ORIGIN NOT REACHED")
        out = self._send_and_settle(line, timeout=timeout, done=done)
        bad = ("FULL RESET INCOMPLETE", "ORIGIN NOT REACHED", "ABORTED")
        return not any(marker in text for text in out for marker in bad)

    def rotate_aux(self, degrees: int, timeout: float = 30.0) -> None:
        """Relative auxiliary-stepper jog: ``A <degrees>``.

        Positive is clockwise and negative is counter-clockwise. The firmware
        intentionally limits one request to one turn (``-360..360``): this
        motor has no limit switch or absolute-angle sensor. A manual angle not
        equal to 0/+90/-90 has no calibrated tool offset; a later build safely
        returns it to neutral before picking up a block.
        """
        self._require_not_reset()
        if isinstance(degrees, bool) or int(degrees) != degrees:
            raise ValueError("aux rotation degrees must be an integer")
        degrees = int(degrees)
        if not -360 <= degrees <= 360:
            raise ValueError("aux rotation degrees must be in -360..360")
        out = self._send_and_settle(
            f"A {degrees}",
            timeout=timeout,
            done=("AUX STEPPER: done.", "ERROR - use:"),
        )
        if any("ERROR - use:" in line for line in out):
            raise RigError(
                "the rig refused the auxiliary-stepper angle:\n  "
                + "\n  ".join(line.strip() for line in out if line.strip())
            )

    def goto(self, col: int, row: int, timeout: float = 180.0) -> bool:
        """`G <col> <row>` — drive to a cell without picking anything up.

        The safe way to check a pixel-to-cell mapping: a wrong answer costs a
        wasted trip, not a dropped block.

        0 on either axis is a real target, not just a camera-cell reject:
        it means "leave that axis at the origin", so ``G 0 0`` goes home
        (or does nothing if already there) and e.g. ``G 5 0`` moves X only.
        """
        self._require_not_reset()
        out = self._send_and_settle(
            f"G {col} {row}",
            timeout=timeout,
            done=("ARRIVED at cell", "ALREADY AT ORIGIN", "MOVE INCOMPLETE",
                  "ABORTED", "ERROR"),
        )
        if any("ARRIVED at cell" in text or "ALREADY AT ORIGIN" in text
               for text in out):
            return True
        # gotoCell() can also fail before it prints anything at all, when
        # gridReady() or cellInRange() rejects it — hence "did it say ARRIVED"
        # rather than "did it say a bad word".
        return False

    def build(self, col: int, row: int, level: int,
              timeout: float = 300.0) -> BuildResult:
        """`B <col> <row> <level>` — one full pick-and-place. Blocks until done.

        There is no rotation argument. The active grid decides how the block is
        laid; use `set_mode()` to change that. See D7/D8 in
        plans/dual-orientation-grid.md.

        For calibration, firmware also accepts zero for either coordinate:
        ``B 0 5`` skips X and ``B 9 0`` skips Y; ``B 0 0`` is an inert no-op.

        Returns 'placed', 'rejected' or 'aborted'. **'aborted' means stop.**
        The claw may still be gripping a block somewhere unknown; the firmware
        says so itself. Do not retry it, do not home it, go and look.

        The timeout is generous on purpose. A build is ~40 s of motion, and the
        firmware bounds every one of its own seeks and reports its own failures
        (see plans/ack-protocol.md on why there is no watchdog). Hitting this
        timeout therefore means something outside the firmware's model went
        wrong, which is also a go-and-look, not a retry.
        """
        self._require_not_reset()
        try:
            col, row, level = int(col), int(row), int(level)
        except (TypeError, ValueError) as exc:
            raise ValueError("build coordinates and level must be integers") from exc
        if not self.grid.contains_build_target(col, row):
            raise ValueError(
                f"build target [{col},{row}] is outside 0..{self.cols} x "
                f"0..{self.rows}"
            )
        if level < 0:
            raise ValueError("build level cannot be negative")

        command = f"B {col} {row} {level}"

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
    if "ERROR - use:  B " in line or "B takes exactly three numbers" in line:
        return REJECTED, "bad arguments"
    return None, ""

#!/usr/bin/env python3
"""Append-only run logs for the rig build pipeline.

Two files under ``logs/`` at the repository root, both git-ignored, both opened
in append mode so every server run adds to them rather than replacing them:

``logs/build.log``
    One clearly separated section per build: the ``/api/build`` request, the
    controller/job handoff, every firmware phase with the ETA the firmware
    predicted and the time the phase ACTUALLY took, and the settled result.
    Every timestamp in a section is relative to the moment that build was
    accepted, so the section reads as a stopwatch.

``logs/serial.log``
    Every line to and from the Arduino, each stamped with the wall clock AND
    the gap since the previous serial line. A stall on the cable or a slow
    firmware phase shows up directly as a large delta in the second column.

Disabled by default. Importing this module costs nothing and every logging
call is a cheap no-op until :func:`configure` is called, which
``web.app.main()`` does for a real server run. The test-suite never calls
:func:`configure`, so ``pytest`` never writes to ``logs/``.

Nothing here raises: a logging helper that could take the build down with it
would be worse than a missing log line. I/O errors are swallowed.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

#: ``python/rig/build_log.py`` -> ``rig`` -> ``python`` -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_DIR = _REPO_ROOT / "logs"


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clock() -> str:
    # Millisecond resolution is plenty for a 9600-baud cable and keeps the
    # column narrow.
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class _Sink:
    """One append-only text file, or nothing at all until :meth:`open`.

    Re-opened per write. The traffic is tiny (a build is a few dozen lines)
    and this way a crash mid-build still leaves a complete, flushed file.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: Path | None = None

    def open(self, path: Path) -> None:
        with self._lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                return
            self._path = path

    @property
    def enabled(self) -> bool:
        return self._path is not None

    def write(self, text: str) -> None:
        path = self._path
        if path is None:
            return
        line = text if text.endswith("\n") else text + "\n"
        with self._lock:
            try:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
            except OSError:
                pass


_build_sink = _Sink()
_serial_sink = _Sink()


class SerialLog:
    """``logs/serial.log`` — raw Arduino traffic with inter-line timing.

    ``line_out``/``line_in`` are called from :mod:`rig.link`: ``line_out`` from
    the sending thread, ``line_in`` from the reader thread. The lock keeps the
    two from interleaving a half-written line, and the delta column is computed
    under it so it always reflects the true previous line.
    """

    def __init__(self, sink: _Sink) -> None:
        self._sink = sink
        self._lock = threading.Lock()
        self._last: float | None = None

    def _delta(self, now: float) -> str:
        if self._last is None:
            gap = " " * 9
        else:
            gap = f"+{now - self._last:7.3f}s"
        self._last = now
        return gap

    def session(self, message: str) -> None:
        """A blank line and a header — a new connection, a reconnect, a run."""
        if not self._sink.enabled:
            return
        with self._lock:
            self._sink.write("")
            self._sink.write(f"### {_stamp()}  {message}")
            self._last = time.monotonic()

    def line_out(self, text: str) -> None:
        if not self._sink.enabled:
            return
        now = time.monotonic()
        with self._lock:
            self._sink.write(f"{_clock()}  {self._delta(now)}  >>  {text}")

    def line_in(self, text: str) -> None:
        if not self._sink.enabled:
            return
        now = time.monotonic()
        with self._lock:
            self._sink.write(f"{_clock()}  {self._delta(now)}  <<  {text}")

    def note(self, text: str) -> None:
        """A commentary line — the settled result, a dead port — not wire data."""
        if not self._sink.enabled:
            return
        with self._lock:
            self._sink.write(f"{_clock()}  {' ' * 9}  --  {text}")


class BuildLog:
    """``logs/build.log`` — one stopwatch section per build.

    All methods are called on the FastAPI event loop thread (``web/app.py``
    hops every serial callback across with ``call_soon_threadsafe`` before it
    reaches here), so this class keeps no lock: the ordering that makes "the
    phases came before the result" true is the same ordering that serialises
    these calls.
    """

    def __init__(self, sink: _Sink) -> None:
        self._sink = sink
        self._t0: float | None = None
        #: The phase whose ``begin`` we have logged but whose duration we have
        #: not: ``(SerialProgress, started_monotonic)``.
        self._pending: tuple[object, float] | None = None

    def _rel(self, now: float | None = None) -> str:
        if self._t0 is None:
            return "+0.00s"
        now = time.monotonic() if now is None else now
        return f"+{now - self._t0:.2f}s"

    def run_started(self, *, mode: str | None, cols: int, rows: int,
                    port: str, baud: int, mock: bool,
                    feeder_port: str | None = None,
                    feeder_baud: int | None = None) -> None:
        """A run banner, written to BOTH logs so they line up by eye."""
        line = (f"SERVER RUN  {_stamp()}  mode={mode} grid={cols}x{rows} "
                f"mega_port={port} mega_baud={baud} "
                f"feeder_port={feeder_port} feeder_baud={feeder_baud} mock={mock}")
        rule = "=" * 78
        for sink in (_build_sink, _serial_sink):
            if sink.enabled:
                sink.write("")
                sink.write(rule)
                sink.write(line)
                sink.write(rule)

    def build_requested(self, command: str, *, selection, level: int,
                        mode: str | None) -> None:
        self._t0 = time.monotonic()
        self._pending = None
        if not self._sink.enabled:
            return
        self._sink.write("")
        self._sink.write("-" * 78)
        self._sink.write(f"BUILD  {_stamp()}  {command}")
        self._sink.write(f"  selection={selection}  level={level}  mode={mode}")
        self._sink.write(f"  {self._rel():>8}  request accepted by /api/build")

    def job_started(self) -> None:
        if self._sink.enabled:
            self._sink.write(f"  {self._rel():>8}  build job thread started")

    def accepted(self, ack) -> None:
        """The board's ``@n RECV`` — the command parsed and was accepted."""
        if self._sink.enabled:
            self._sink.write(f"  {self._rel():>8}  board RECV seq={ack.seq}")

    def phase(self, progress) -> None:
        """One ``@n STEP`` line. Closes the previous phase, opens this one."""
        now = time.monotonic()
        if self._pending is not None:
            self._close_phase(now)
        if not self._sink.enabled:
            return
        if progress.status == "done":
            self._sink.write(
                f"  {self._rel(now):>8}  phase {progress.step}/{progress.total} "
                f"{progress.phase} confirmed  ({progress.label})")
            self._pending = None
            return
        eta = ""
        if progress.eta_ms:
            eta = f"  firmware-ETA {progress.eta_ms / 1000:.2f}s"
        self._sink.write(
            f"  {self._rel(now):>8}  phase {progress.step}/{progress.total} "
            f"begin {progress.phase} [{progress.action}]{eta}  {progress.label}")
        self._pending = (progress, now)

    def _close_phase(self, now: float) -> None:
        progress, started = self._pending  # type: ignore[misc]
        self._pending = None
        if not self._sink.enabled:
            return
        took = now - started
        detail = ""
        if progress.eta_ms:
            drift = took - progress.eta_ms / 1000
            detail = f"  (firmware ETA {progress.eta_ms / 1000:.2f}s, {drift:+.2f}s)"
        self._sink.write(
            f"  {' ':>8}  phase {progress.step} {progress.phase} "
            f"took {took:.2f}s{detail}")

    def result(self, word: str, *, reason: str | None, locked: bool,
               from_prose: bool) -> None:
        now = time.monotonic()
        if self._pending is not None:
            self._close_phase(now)
        if self._sink.enabled:
            tail = f"  ({reason})" if reason else ""
            self._sink.write(f"  {self._rel(now):>8}  RESULT {word.upper()}{tail}")
            if from_prose:
                self._sink.write(f"  {' ':>8}  (no ack — outcome read from prose)")
            if locked:
                self._sink.write(
                    f"  {' ':>8}  controller LOCKED — human inspection required")
            total = 0.0 if self._t0 is None else now - self._t0
            self._sink.write(
                f"  {self._rel(now):>8}  build finished, total {total:.2f}s")
        self._t0 = None

    def note(self, text: str) -> None:
        """Anything else worth a line in the current section — e.g. a port death."""
        if self._sink.enabled:
            self._sink.write(f"  {self._rel():>8}  {text}")


#: Module singletons. One server process, one of each — see AGENTS.md on the
#: console owning exactly one camera and one serial link.
serial = SerialLog(_serial_sink)
build = BuildLog(_build_sink)


def configure(*, log_dir: Path | str = DEFAULT_LOG_DIR, enabled: bool = True) -> None:
    """Point the two logs at ``<log_dir>/{build,serial}.log`` and start writing.

    Idempotent and safe to call before anything else. ``enabled=False`` leaves
    every logging call a no-op, which is the state the test-suite relies on.
    """
    if not enabled:
        return
    directory = Path(log_dir)
    _build_sink.open(directory / "build.log")
    _serial_sink.open(directory / "serial.log")

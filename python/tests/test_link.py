#!/usr/bin/env python3
"""Drive rig/link.py against a fake board, because the real one is not here.

    cd python
    ../.venv/bin/python tests/test_link.py

No pytest, no fixtures — one file, plain asserts, prints a line per check.

What this can and cannot prove
------------------------------
It proves the parsing: that `@3 HELD ...` becomes 'aborted', that a build with
the ack lines stripped out still reaches the same answer through the prose, that
a second command is refused rather than queued, and that a long silence in the
middle of a homing run is not mistaken for the end of it.

It proves nothing about the rig. The transcripts below are copied out of
`build_test_v1.ino` by hand, so they are only as right as that copy — and the
ack lines have never been printed by an actual board. This is the desktop half
of the testing; the other half is flashing it and watching.
"""

import os
import queue
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rig.link as link


# ------------------------------------------------------------------
# A fake build_test_v1 on a fake serial port
# ------------------------------------------------------------------


class FakeSerial:
    """Enough of pyserial's Serial for the reader thread: readline, write, close.

    `replies` maps a command prefix to the lines the sketch prints for it. Each
    line can be a float instead, meaning "stay silent for this long" — that is
    how the homing tests reproduce `seekLimit()` driving a motor for ten seconds
    without a word.
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


# ------------------------------------------------------------------
# Transcripts, copied out of build_test_v1.ino
# ------------------------------------------------------------------

BANNER = [
    "@0 BOOT fw=build_test_v1",
    "=== GRID ===",
    "Division : 22 cols x 5 rows  = 110 cells",
    ">> Position is UNKNOWN until you home. Send 0 to home.",
    "@0 READY grid=22x5",
]

GRID_RESIZED = [
    "",
    "GRID RESIZED",
    "--- GRID ---",
    "Division : 22 cols x 5 rows  = 110 cells",
    "col 1 = X switch side, row 1 = Y switch side",
]

BUILD_OK = [
    "======================================",
    "BUILD  cell [3,5]  level 0  rot NONE",
    "======================================",
    "[BUILD 1/14] Home everything",
    "[BUILD 14/14] Return the claw to its original rotation",
    "======================================",
    "BUILD COMPLETE - block placed at [3,5] level 0 (0.00 cm)",
    "Place time: 41.2s",
    "PARKED - Z at the top, X/Y at the origin.",
    "======================================",
    "@3 OK col=3 row=5 level=0",
]

BUILD_REJECTED = [
    "  BUILD REJECTED - cell out of range",
    "  Nothing moved.",
    "@3 SAFE cell out of range",
]

BUILD_ABORTED = [
    "",
    "*** BUILD ABORTED - Z never reached the ground switch",
    "*** The claw may still be holding a block. Check the rig.",
    "@3 HELD Z never reached the ground switch",
]

# The nasty one: the block IS down, so the prose says COMPLETE — and then two
# lines later says parking failed, which makes it a HELD.
BUILD_PARK_FAILED = [
    "======================================",
    "BUILD COMPLETE - block placed at [3,5] level 0 (0.00 cm)",
    "Place time: 41.2s",
    "!! BLOCK IS PLACED, BUT PARKING FAILED - see above.",
    "!! Check the rig before the next command.",
    "======================================",
    "@3 HELD block placed but parking failed",
]

# 4 seconds of silence in the middle, as seekLimit() does while the motor runs.
HOME_OK = [
    "",
    "=== FULL RESET - Z, then X/Y ===",
    "  [1/3] Z down into its BOTTOM switch (true zero)...",
    "  Homing Z- (pin 28) ...",
    4.0,
    "Z- switch found after 4210 steps. Axis zeroed.",
    "  [3/3] Homing X/Y...",
    "  AT ORIGIN. Position = X 0 / Y 0",
    "",
    "FULL RESET COMPLETE - X/Y at origin, Z on its top switch.",
]

GOTO_OK = [
    "",
    "=== GOTO CELL [3,5] ===",
    "  Target position: X -631 / Y 6563",
    2.0,
    "  ARRIVED at cell [3,5]  pos X -631 / Y 6563",
]

CFG = {
    "serial": {"port": "/dev/fake", "baud": 9600},
    "grid": {
        "cols": 22, "rows": 5,
        "cell_width_cm": 1.5, "cell_height_cm": 7.5,
        "trim_x_cm": 0.0, "trim_y_cm": 0.0,
    },
    "workspace": {"width_cm": 34.0, "height_cm": 40.0},
    "frame": {"width_cm": 20.0, "height_cm": 35.0},
}

DEFAULT_REPLIES = {"S": GRID_RESIZED, "B": BUILD_OK, "0+": HOME_OK, "G": GOTO_OK}


def fake_rig(replies=None, acks=True, timeout=10, **kwargs):
    """A connected Rig talking to a FakeSerial. Returns (rig, fake)."""
    script = {"banner": BANNER, "replies": replies or DEFAULT_REPLIES}
    fake = FakeSerial(script, acks=acks)
    link.serial.Serial = lambda *a, **k: fake  # the whole point of the fake
    rig = link.Rig(cfg=CFG)
    rig.connect(timeout=timeout, **kwargs)
    return rig, fake


PASSED = []
FAILED = []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:34} {detail}")


# ------------------------------------------------------------------
# The ack parser
# ------------------------------------------------------------------

for raw, kind, seq in [
    ("@0 BOOT fw=build_test_v1", "BOOT", 0),
    ("@0 READY grid=22x5", "READY", 0),
    ("@1 ERR expected: B <col> <row> <level> [R|RR|NR]", "ERR", 1),
    ("@2 SAFE cell out of range", "SAFE", 2),
    ("@3 OK col=3 row=5 level=0", "OK", 3),
    ("@4 HELD Z never reached the ground switch", "HELD", 4),
]:
    ack = link.parse_ack(raw)
    check(f"parse {kind}", ack is not None and ack.kind == kind and ack.seq == seq, raw)

ack = link.parse_ack("@3 OK col=3 row=5 level=0")
check("key=value fields", ack.fields == {"col": "3", "row": "5", "level": "0"})
ack = link.parse_ack("@2 SAFE cell out of range")
check("free-text reason", ack.reason == "cell out of range" and ack.terminal)
check("prose is not an ack", link.parse_ack("BUILD COMPLETE - block placed") is None)
check("'@' alone is not an ack", link.parse_ack("@nope thing") is None)


# ------------------------------------------------------------------
# Build outcomes, with the acks and then without them
# ------------------------------------------------------------------


def build_outcome(name, transcript, expected, acks=True):
    rig, fake = fake_rig(replies={"S": GRID_RESIZED, "B": transcript}, acks=acks)
    result = rig.build(3, 5, 0, timeout=20)
    rig.close()
    check(
        name,
        str(result) == expected and result.from_prose == (not acks),
        f"-> {str(result)!r} {result.reason!r}",
    )
    return result


for acks in (True, False):
    tag = "ack" if acks else "prose"
    build_outcome(f"{tag}: complete", BUILD_OK, link.PLACED, acks)
    build_outcome(f"{tag}: rejected", BUILD_REJECTED, link.REJECTED, acks)
    build_outcome(f"{tag}: aborted", BUILD_ABORTED, link.ABORTED, acks)
    # Never 'placed': the block is down but the rig is somewhere unknown.
    build_outcome(f"{tag}: placed, not parked", BUILD_PARK_FAILED, link.ABORTED, acks)


# ------------------------------------------------------------------
# The connect sequence
# ------------------------------------------------------------------

rig, fake = fake_rig()
check("connect pushes the grid", "S 22 5" in fake.written, str(fake.written))
check("connect does not home", "0+" not in fake.written, str(fake.written))
check("READY grid captured", rig.ready_grid == "22x5", str(rig.ready_grid))
check("no fallback with acks", rig.prose_fallbacks == 0)
rig.close()

rig, fake = fake_rig(home=True)
check("connect(home=True) homes", "0+" in fake.written, str(fake.written))
rig.close()

# A board still running the pre-ack firmware: no READY ever arrives. Must give
# up on the banner quickly rather than burning the whole timeout.
started = time.monotonic()
rig, fake = fake_rig(acks=False, timeout=30)
elapsed = time.monotonic() - started
check("no READY -> falls back fast", elapsed < 10 and rig.prose_fallbacks >= 1, f"{elapsed:.1f}s")
rig.close()


# ------------------------------------------------------------------
# The things that must not go wrong
# ------------------------------------------------------------------

# Homing is silent for seconds at a time. Returning early here would let the
# next command out while the motor is still running.
rig, fake = fake_rig()
started = time.monotonic()
homed = rig.home(timeout=30)
elapsed = time.monotonic() - started
check("silence mid-home is not the end", homed and elapsed > 4.0, f"{elapsed:.1f}s")
check("goto waits for ARRIVED", rig.goto(3, 5, timeout=30) is True)
check("no fallback on S/0+/G", rig.prose_fallbacks == 0)
rig.close()

# A reset under a running command loses the grid and the homing.
rig, fake = fake_rig(replies={"S": GRID_RESIZED,
                              "B": ["[BUILD 5/14] descend", "@0 BOOT fw=build_test_v1"]})
try:
    rig.build(3, 5, 0, timeout=20)
    check("mid-build reset raises", False)
except link.RigReset:
    check("mid-build reset raises", True, "RigReset")
rig.close()

# The rig is not listening during a build. A second command must be refused,
# not queued: it would sit in the 64-byte buffer and arrive late.
# The 2.0 makes the fake board take as long as a real build does, so the
# second command genuinely lands while the first is still running.
rig, fake = fake_rig(replies={"S": GRID_RESIZED, "B": [2.0] + BUILD_OK})
refused = []


def second_command():
    time.sleep(0.05)
    try:
        rig.build(1, 1, 0)
        refused.append("accepted")
    except link.RigBusy:
        refused.append("RigBusy")


thread = threading.Thread(target=second_command)
thread.start()
rig.build(3, 5, 0, timeout=20)
thread.join()
check("second command refused", refused == ["RigBusy"], str(refused))
rig.close()

# Nothing conclusive, ever. The rig's state is unknown and that has to be loud.
rig, fake = fake_rig(replies={"S": GRID_RESIZED, "B": ["[BUILD 5/14] descend"]})
try:
    rig.build(3, 5, 0, timeout=2)
    check("silent firmware times out", False)
except link.RigTimeout:
    check("silent firmware times out", True, "RigTimeout")
rig.close()

# BuildResult is the word, with the detail attached.
result = link.BuildResult(link.ABORTED, "block placed but parking failed")
check(
    "BuildResult reads as its word",
    result == link.ABORTED and result.needs_a_human and not result.ok,
    repr(result),
)

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
sys.exit(1 if FAILED else 0)

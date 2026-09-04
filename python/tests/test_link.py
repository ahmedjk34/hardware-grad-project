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

import copy
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rig.link as link
from rig.mock_board import FakeSerial


# ------------------------------------------------------------------
# A fake build_test_v1 on a fake serial port
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# Transcripts, copied out of build_test_v1.ino
# ------------------------------------------------------------------

BANNER = [
    "@0 BOOT fw=build_test_v1",
    "=== GRID ===",
    "Division : 9 cols x 5 rows  = 45 positive cells",
    ">> Position is UNKNOWN until you home. Send 0 to home.",
    "@0 READY grid=9x5 mode=vertical",
]

# A board that boots vertical, as every board does, being latched to the
# horizontal grid. Copied out of setGridMode().
MODE_LATCHED = [
    "",
    "GRID MODE: vertical  ->  horizontal",
    "  The claw did NOT move. The next B turns it at the feeder.",
    "--- GRID ---",
    "Mode      : horizontal  (block 7.50 X x 2.20 Y cm)  RR = horizontal, R = vertical",
    "Division : 3 cols x 15 rows  = 45 positive cells",
]

MODE_ALREADY = [
    "",
    "  ERROR - already in vertical mode.",
    "  RR selects horizontal, R selects vertical.",
]

MODE_UNHOMED = [
    "",
    "  ERROR - home X/Y first (send 0).",
    "  A mode switch redefines every coordinate, so the",
    "  current cell has to mean something before it is re-read.",
]

MODE_MANUAL_ANGLE = [
    "",
    "  ERROR - claw is at an arbitrary manual A angle.",
    "  Latching a grid needs a calibrated 0/+90/-90 angle; run B first.",
]

GRID_RESIZED = [
    "",
    "GRID RESIZED",
    "--- GRID ---",
    "Division : 9 cols x 5 rows  = 45 positive cells",
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

# The same build with the machine channel the firmware now prints: RECV, one
# STEP per phase, the phase-11 'done' that confirms the release, then the OK.
# Copied from the host-stub transcript in docs/ack-protocol.md.
BUILD_WITH_STEPS = [
    "@12 RECV cmd=B col=3 row=4 level=0",
    "@12 STEP step=1 total=14 phase=raise_clear action=move"
    " text=Raise_Z_into_the_top_switch status=begin",
    "[BUILD 1/14] Raise Z into the top switch (clearance)",
    "@12 STEP step=6 total=14 phase=grip action=grip"
    " text=Close_the_claw_and_grip status=begin",
    "@12 STEP step=8 total=14 phase=move_to_target action=move"
    " text=Move_XY_to_the_target_cell status=begin",
    "@12 STEP step=11 total=14 phase=release action=release"
    " text=Open_the_claw_and_release status=begin",
    "@12 STEP step=11 total=14 phase=release action=release"
    " text=Open_the_claw_and_release status=done",
    "@12 STEP step=14 total=14 phase=park_rotation action=park"
    " text=Return_the_claw_to_neutral status=begin",
    "BUILD COMPLETE - block placed at [3,4] level 0 (0.00 cm)",
    "@12 OK col=3 row=4 level=0",
]

# The abort that matters: it dies while CARRYING, so the last thing anyone
# knows is phase 8 and the claw still has the block.
BUILD_ABORTED_MID_CARRY = [
    "@13 RECV cmd=B col=3 row=4 level=0",
    "@13 STEP step=7 total=14 phase=lift_block action=move"
    " text=Raise_Z_to_carry_height status=begin",
    "@13 STEP step=8 total=14 phase=move_to_target action=move"
    " text=Move_XY_to_the_target_cell status=begin",
    "*** BUILD ABORTED - could not reach the target cell",
    "@13 HELD could not reach the target cell",
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

# ``0`` homes only the X/Y axes. That is the deliberately small motion a
# horizontal-mode request needs before its RR latch.
HOME_XY_OK = [
    "",
    "  Homing X/Y...",
    "  AT ORIGIN. Position = X 0 / Y 0",
]

AUX_TURN_OK = [
    "",
    "AUX STEPPER: rotating -45 deg relative (-256 steps) CCW...",
    "AUX STEPPER: done. Tracked angle from power-on neutral: -45.0 deg.",
    "  Grid moves/latches are refused until a B returns the claw to neutral.",
]

GOTO_OK = [
    "",
    "=== GOTO CELL [3,5] ===",
    "  Target position: X -743 / Y 6563",
    2.0,
    "  ARRIVED at cell [3,5]  pos X -743 / Y 6563",
]

# 0,0 is the origin, not a rejected cell: already there is a real success that
# never says "ARRIVED at cell", so link.Rig.goto() must recognize it too.
GOTO_ALREADY_HOME = [
    "",
    "=== GOTO CELL [0,0] ===",
    "  ALREADY AT ORIGIN - no move needed.",
]

# Axis-only: row 0 means "leave Y at the origin", so only X moves.
GOTO_AXIS_ONLY = [
    "",
    "=== GOTO CELL [5,0] ===",
    2.0,
    "  Moving X to -2185 ...",
    "  ARRIVED at cell [5,0]  pos X -2185 / Y 0",
]

CFG = {
    "serial": {"port": "/dev/fake", "baud": 9600},
    "grid": {
        "active_mode": "vertical",
        "modes": {
            "vertical": {
                "cols": 9, "rows": 5,
                "block_x_cm": 2.2, "block_y_cm": 7.5,
                "gap_x_cm": 0.5, "gap_y_cm": 0.5,
                "trim_x_cm": 0.0, "trim_y_cm": 0.0,
            },
            "horizontal": {
                "cols": 3, "rows": 9,
                "block_x_cm": 7.5, "block_y_cm": 2.2,
                "gap_x_cm": 0.5, "gap_y_cm": 0.5,
                "trim_x_cm": 0.0, "trim_y_cm": 0.25,
                # half a block on each axis: a centre-anchored cell 0 always overhangs
                "max_edge_overhang_x_cm": 3.75, "max_edge_overhang_y_cm": 1.1,
            },
        },
    },
    "workspace": {"width_cm": 24.3, "height_cm": 40.0},
    "frame": {"width_cm": 20.0, "height_cm": 35.0},
}

DEFAULT_REPLIES = {"S": GRID_RESIZED, "B": BUILD_OK, "0+": HOME_OK, "G": GOTO_OK,
                   "RR": MODE_LATCHED, "R": MODE_ALREADY}


def fake_rig(replies=None, acks=True, timeout=10, cfg=None, banner=None,
             mode=None, on_progress=None, on_ack=None, **kwargs):
    """A connected Rig talking to a FakeSerial. Returns (rig, fake).

    `on_progress` / `on_ack` are the Rig's own constructor callbacks, not
    connect() arguments; every other keyword still goes to connect().
    """
    script = {"banner": banner or BANNER, "replies": replies or DEFAULT_REPLIES}
    fake = FakeSerial(script, acks=acks)
    link.serial.Serial = lambda *a, **k: fake  # the whole point of the fake
    rig = link.Rig(cfg=cfg or CFG, mode=mode, on_progress=on_progress,
                   on_ack=on_ack)
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
    ("@0 READY grid=9x5 mode=vertical", "READY", 0),
    ("@1 ERR expected: B <col> <row> <level>", "ERR", 1),
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
    result = rig.build(3, 4, 0, timeout=20)
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
check("connect pushes the grid", "S 8 4" in fake.written, str(fake.written))
check("connect reads the board's mode", rig.ready_mode == "vertical", str(rig.ready_mode))
check("a vertical session sends no latch",
      "R" not in fake.written and "RR" not in fake.written, str(fake.written))
check("connect does not home", "0+" not in fake.written, str(fake.written))
check("READY grid captured", rig.ready_grid == "9x5", str(rig.ready_grid))
check("no fallback with acks", rig.prose_fallbacks == 0)
rig.close()

rig, fake = fake_rig(home=True)
check("connect(home=True) homes", "0+" in fake.written, str(fake.written))
rig.close()

# A vertical session with no shift in the config sends no shiftX / shiftY:
# 0 is the board's compiled default, so a freshly-reset board already agrees.
rig, fake = fake_rig()
check("no shift command when the config shift is zero",
      not any(w.lower().startswith("shift") for w in fake.written), str(fake.written))
rig.close()

# A config that carries a grid shift pushes it on connect, AFTER the mode latch
# and BEFORE S - the firmware validates S against the shifted lattice.
SHIFTED_CFG = copy.deepcopy(CFG)
SHIFTED_CFG["grid"]["modes"]["vertical"]["shift_y_cm"] = 4.0
SHIFT_OK = [
    "",
    "GRID SHIFT [vertical] Y  0.000 -> 4.000 cm   (pick-up NOT shifted; applied from [0,0])",
    "--- GRID ---",
]
rig, fake = fake_rig(
    replies={"S ": GRID_RESIZED, "SHIFTY": SHIFT_OK, "R": MODE_ALREADY},
    cfg=SHIFTED_CFG,
)
check("connect pushes the Y shift", "shiftY 4" in fake.written, str(fake.written))
check("connect sends no shiftX when the X shift is zero",
      not any(w.startswith("shiftX") for w in fake.written), str(fake.written))
check("the shift is pushed before S",
      "shiftY 4" in fake.written and "S 8 4" in fake.written
      and fake.written.index("shiftY 4") < fake.written.index("S 8 4"),
      str(fake.written))
rig.close()

# A board that refuses the shift stops connect rather than pressing on to S.
SHIFT_REFUSED = [
    "",
    "  ERROR - a 4.000 cm Y shift leaves no cell on the X/Y travel. Reverted.",
]
try:
    fake_rig(replies={"S ": GRID_RESIZED, "SHIFTY": SHIFT_REFUSED, "R": MODE_ALREADY},
             cfg=SHIFTED_CFG)
    check("a refused shift aborts connect", False)
except link.RigError:
    check("a refused shift aborts connect", True)

# An explicit horizontal session has to home X/Y before it can send RR. The
# order is physical safety, not cosmetic: the firmware rejects RR otherwise.
rig, fake = fake_rig(
    replies={"0": HOME_XY_OK, "RR": MODE_LATCHED, "S": GRID_RESIZED},
    mode="horizontal",
    home_before_configure=True,
)
check("horizontal connect homes X/Y before RR and S",
      fake.written == ["0", "RR", "S 2 8"], str(fake.written))
check("horizontal connect selects its requested grid",
      rig.grid.mode == "horizontal" and (rig.cols, rig.rows) == (3, 9))
rig.close()

# The manual auxiliary-stepper helper is deliberately relative and bounded.
rig, fake = fake_rig(replies={"S": GRID_RESIZED, "A": AUX_TURN_OK})
fake.written.clear()
rig.rotate_aux(-45)
check("manual aux turn sends signed degree command", fake.written == ["A -45"],
      str(fake.written))
try:
    rig.rotate_aux(361)
    check("manual aux turn rejects more than one turn", False)
except ValueError:
    check("manual aux turn rejects more than one turn", True)
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

# 0 on either axis is a real target (origin / axis-only), not a rejected cell.
rig, fake = fake_rig(replies={"S": GRID_RESIZED, "G 0 0": GOTO_ALREADY_HOME, "G": GOTO_OK})
check("goto(0,0) already-home counts as success", rig.goto(0, 0, timeout=10) is True)
rig.close()

rig, fake = fake_rig(replies={"S": GRID_RESIZED, "G 5 0": GOTO_AXIS_ONLY, "G": GOTO_OK})
check("goto(5,0) axis-only move counts as success", rig.goto(5, 0, timeout=10) is True)
rig.close()

# A reset under a running command loses the grid and the homing.
rig, fake = fake_rig(replies={"S": GRID_RESIZED,
                              "B": ["[BUILD 5/14] descend", "@0 BOOT fw=build_test_v1"]})
try:
    rig.build(3, 4, 0, timeout=20)
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
rig.build(3, 4, 0, timeout=20)
thread.join()
check("second command refused", refused == ["RigBusy"], str(refused))
rig.close()

# Nothing conclusive, ever. The rig's state is unknown and that has to be loud.
rig, fake = fake_rig(replies={"S": GRID_RESIZED, "B": ["[BUILD 5/14] descend"]})
try:
    rig.build(3, 4, 0, timeout=2)
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

# ------------------------------------------------------------------
# The grid mode latch and the reset boundary (R4)
# ------------------------------------------------------------------

import copy  # noqa: E402

HORIZONTAL_CFG = copy.deepcopy(CFG)
HORIZONTAL_CFG["grid"]["active_mode"] = "horizontal"

rig, fake = fake_rig(cfg=HORIZONTAL_CFG)
check("a horizontal session latches on connect", "RR" in fake.written,
      str(fake.written))
check("the latch is pushed BEFORE S (R4)",
      fake.written.index("RR") < fake.written.index("S 2 8"), str(fake.written))
check("connect pushes the horizontal counts", "S 2 8" in fake.written,
      str(fake.written))
check("the rig's grid followed the latch",
      rig.grid.mode == "horizontal" and (rig.cols, rig.rows) == (3, 9))

# An idle reset must not disappear when the next command drains old events.
# Recovery is deliberately explicit because a reset loses X/Y homing: only the
# caller's `home=True` authorizes that motion, after a human has inspected it.
fake.written.clear()
fake._emit(["@0 BOOT fw=build_test_v1"])
time.sleep(0.05)
try:
    rig.goto(1, 1)
    check("an idle reset blocks later commands until recovery", False)
except link.RigReset:
    check("an idle reset blocks later commands until recovery", True)
try:
    rig.recover_after_reset()
    check("reset recovery requires explicit homing authority", False)
except link.RigReset:
    check("reset recovery requires explicit homing authority", True)
rig.recover_after_reset(home=True)
check("reset recovery homes then re-pushes horizontal mode before S",
      fake.written == ["0+", "RR", "S 2 8"], str(fake.written))
rig.close()

# set_mode outside connect re-sends S, because the board's count for the mode
# it has just switched into is ITS compiled default, not this config's.
rig, fake = fake_rig()
fake.written.clear()
rig.set_mode("horizontal")
check("set_mode latches and then re-pushes S",
      fake.written == ["RR", "S 2 8"], str(fake.written))
check("set_mode re-read the grid",
      rig.grid.mode == "horizontal" and (rig.cols, rig.rows) == (3, 9))

# Wanting the mode the board is already in is not an error on this side.
fake.written.clear()
rig.set_mode("vertical")
check("an 'already in' refusal still counts as success",
      rig.grid.mode == "vertical" and (rig.cols, rig.rows) == (9, 5))

try:
    rig.set_mode("diagonal")
    check("an unknown mode never reaches the wire", False)
except ValueError as exc:
    check("an unknown mode never reaches the wire",
          "R" not in fake.written[-1:] or "diagonal" in str(exc), str(exc))
rig.close()

# An un-homed board refuses the latch, and that must surface as an error
# rather than as a silent no-op that leaves Python believing the wrong grid.
rig, fake = fake_rig(replies={**DEFAULT_REPLIES, "RR": MODE_UNHOMED})
try:
    rig.set_mode("horizontal")
    check("an un-homed latch refusal raises", False)
except link.RigError as exc:
    check("an un-homed latch refusal raises", "home X/Y first" in str(exc))
check("the refused latch left the grid alone",
      rig.grid.mode == "vertical" and (rig.cols, rig.rows) == (9, 5))
rig.close()

rig, fake = fake_rig(replies={**DEFAULT_REPLIES, "RR": MODE_MANUAL_ANGLE})
try:
    rig.set_mode("horizontal")
    check("a manual aux angle refuses the latch", False)
except link.RigError as exc:
    check("a manual aux angle refuses the latch", "arbitrary manual A angle" in str(exc))
check("manual-angle latch refusal leaves Python vertical", rig.grid.mode == "vertical")
rig.close()

# ------------------------------------------------------------------
# The rotation word is gone (D8)
# ------------------------------------------------------------------

rig, fake = fake_rig()
rig.build(3, 4, 0, timeout=20)
check("B carries three numbers and nothing else",
      fake.written[-1] == "B 3 4 0", str(fake.written[-1]))
try:
    rig.build(3, 4, 0, rotation="RR", timeout=20)
    check("build() no longer accepts a rotation", False)
except TypeError:
    check("build() no longer accepts a rotation", True)
rig.close()

outcome, reason = link._prose_outcome("  ERROR - B takes exactly three numbers.")
check("the firmware's new B error reads as a rejection",
      outcome == link.REJECTED and reason == "bad arguments", f"{outcome} {reason}")


# ------------------------------------------------------------------
# Structured build progress - @n STEP
# ------------------------------------------------------------------

progress = link.parse_progress(link.parse_ack(
    "@12 STEP step=8 total=14 phase=move_to_target action=move"
    " text=Move_XY_to_the_target_cell status=begin"))
check("STEP parses to a SerialProgress", progress is not None)
check("STEP carries the command sequence", progress.seq == 12, str(progress.seq))
check("STEP carries step and total",
      (progress.step, progress.total) == (8, 14), f"{progress.step}/{progress.total}")
check("STEP carries the stable phase id", progress.phase == "move_to_target",
      progress.phase)
check("STEP un-underscores the human label",
      progress.label == "Move XY to the target cell", progress.label)
check("STEP carries the coarse action", progress.action == "move", progress.action)
check("a begin STEP is not a release", not progress.done)
check("a moving phase is not parking", not progress.parking)
check("STEP keeps the raw line", progress.raw.startswith("@12 STEP"), progress.raw)
check("a phase with no predictable duration says nothing",
      progress.eta_ms is None, str(progress.eta_ms))

# `ms=` is the firmware's own arithmetic: the exact step count for this level
# times its own Z step period. It is on the wire because Z_TRAVEL_STEPS and
# BLOCK_HEIGHT_CM are firmware-owned and the Pi is forbidden a copy of them.
timed = link.parse_progress(link.parse_ack(
    "@12 STEP step=10 total=14 phase=lower_to_level action=move"
    " text=Lower_Z_to_the_target_level status=begin ms=2570"))
check("a Z move carries the predicted duration", timed.eta_ms == 2570,
      str(timed.eta_ms))
# Absent is not zero. A UI would draw ms=0 as "instant" and land the block
# immediately, which is the exact failure the estimate is fenced against.
for bad in ("ms=0", "ms=-5", "ms=soon"):
    line = ("@12 STEP step=10 total=14 phase=lower_to_level action=move"
            f" text=L status=begin {bad}")
    check(f"a non-positive duration reads as absent: {bad}",
          link.parse_progress(link.parse_ack(line)).eta_ms is None)

done = link.parse_progress(link.parse_ack(
    "@12 STEP step=11 total=14 phase=release action=release"
    " text=Open_the_claw_and_release status=done"))
check("the phase-11 done is the confirmed release", done.done and done.step == 11)

parking = link.parse_progress(link.parse_ack(
    "@12 STEP step=13 total=14 phase=park_home action=park"
    " text=Return_XY_to_the_origin status=begin"))
check("a park action reads as parking", parking.parking)

# STEP is progress, never an answer. A waiter that returned on one would let
# the next command out while the rig was still moving.
step_ack = link.parse_ack("@12 STEP step=8 total=14 phase=move_to_target")
check("STEP is not terminal", not step_ack.terminal)
check("RECV is not terminal", not link.parse_ack("@12 RECV cmd=B col=3").terminal)

# Malformed STEPs are dropped rather than raised: the reader thread has nobody
# to raise at, and the raw line is still in the log either way.
for bad in ("@12 STEP total=14 phase=x",          # no step
            "@12 STEP step=0 total=14 phase=x",   # steps are 1-based
            "@12 STEP step=20 total=14 phase=x",  # past the end
            "@12 STEP step=1 total=14",           # no phase id
            "@12 STEP step=a total=14 phase=x"):  # not a number
    check(f"malformed STEP is dropped: {bad[10:24]}",
          link.parse_progress(link.parse_ack(bad)) is None)
check("a terminal ack is not progress",
      link.parse_progress(link.parse_ack("@12 OK col=3 row=5 level=0")) is None)


# ------------------------------------------------------------------
# The progress callback: order, attribution, and the terminal answer
# ------------------------------------------------------------------

seen = []
rig, fake = fake_rig(
    replies={"S": GRID_RESIZED, "B": BUILD_WITH_STEPS},
    on_progress=lambda item: seen.append(("step", item)),
    on_ack=lambda ack: seen.append(("ack", ack)),
)
result = rig.build(3, 4, 0, timeout=20)
rig.close()

steps = [item for kind, item in seen if kind == "step"]
acks = [item for kind, item in seen if kind == "ack"]
check("every STEP reached the progress callback", len(steps) == 6, str(len(steps)))
check("the callback sees them in wire order",
      [item.step for item in steps] == [1, 6, 8, 11, 11, 14],
      str([item.step for item in steps]))
check("every phase is attributed to the same command",
      {item.seq for item in steps} == {12}, str({item.seq for item in steps}))
check("the release is confirmed exactly once",
      sum(1 for item in steps if item.done) == 1)
# on_ack is the WHOLE machine channel, boot banner included - a console that
# wants to show every ack should not have to subscribe to four callbacks.
check("the on_ack callback sees every machine line, in order",
      [ack.kind for ack in acks] == ["BOOT", "READY", "RECV", "STEP", "STEP",
                                     "STEP", "STEP", "STEP", "STEP", "OK"],
      str([ack.kind for ack in acks]))
# The whole point of ordering: the phases are facts about a build that had not
# finished, so every one of them must precede the answer.
last_step = max(i for i, (kind, _) in enumerate(seen) if kind == "step")
terminal = max(i for i, (kind, item) in enumerate(seen)
               if kind == "ack" and item.terminal)
check("progress precedes the terminal acknowledgement", last_step < terminal,
      f"{last_step} < {terminal}")
check("STEPs did not change the outcome", str(result) == link.PLACED, str(result))
check("STEPs did not trigger the prose fallback", rig.prose_fallbacks == 0)

# An abort mid-carry: the last phase anyone saw is the last thing known.
seen = []
rig, fake = fake_rig(
    replies={"S": GRID_RESIZED, "B": BUILD_ABORTED_MID_CARRY},
    on_progress=lambda item: seen.append(item),
)
result = rig.build(3, 4, 0, timeout=20)
rig.close()
check("an abort mid-carry still reports its phases",
      [item.step for item in seen] == [7, 8], str([item.step for item in seen]))
check("nothing confirmed a release", not any(item.done for item in seen))
check("HELD is still aborted", str(result) == link.ABORTED, str(result))

# A rejection never reaches a phase: the firmware refuses it before anything
# moves, and that absence is how the Pi can tell SAFE from HELD by shape.
seen = []
rig, fake = fake_rig(replies={"S": GRID_RESIZED, "B": BUILD_REJECTED},
                     on_progress=lambda item: seen.append(item))
result = rig.build(3, 4, 0, timeout=20)
rig.close()
check("a SAFE rejection announces no phase at all", seen == [], str(seen))
check("SAFE is still rejected", str(result) == link.REJECTED, str(result))

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
sys.exit(1 if FAILED else 0)

#!/usr/bin/env python3
"""End-to-end checks for rig/block_calibration.py against a mock rig + camera.

Run from python/:  ../.venv/bin/python tests/test_block_calibration.py

The mock camera draws its blocks through a :class:`WorkspaceMap` it built
itself, so it *is* the ground truth: a calibration that works must recover the
map the camera was rendering from. That is a stronger claim than "the fit had a
small residual", which a self-consistent but wrong lattice would also satisfy.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.block_calibration import (                                 # noqa: E402
    BlockCalibrationAborted,
    BlockCalibrationError,
    BlockCalibrationRun,
)
from rig.config import load as load_rig_config                      # noqa: E402
from rig.grid import MachineGrid                                    # noqa: E402
from rig.link import BuildResult                                    # noqa: E402
from vision.mock_camera import MockCamera                           # noqa: E402

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"ok    {name}")
    else:
        print(f"FAIL  {name}{': ' + detail if detail else ''}")
        failures.append(name)


def expect(name, exc_type, fn, needle=""):
    try:
        fn()
    except exc_type as exc:
        if needle and needle.lower() not in str(exc).lower():
            print(f"FAIL  {name}: wrong message {str(exc)[:80]!r}")
            failures.append(name)
        else:
            print(f"ok    {name}")
        return
    except Exception as exc:                                # noqa: BLE001
        print(f"FAIL  {name}: {type(exc).__name__} {str(exc)[:70]}")
        failures.append(name)
        return
    print(f"FAIL  {name}: no {exc_type.__name__} raised")
    failures.append(name)


class FakeRig:
    """A rig that 'places' a block by adding it to the mock camera's scene.

    ``outcomes`` lets a test make one specific cell fail, which is how the
    rejected/aborted branches get exercised without a real machine.
    """

    def __init__(self, camera, grid, outcomes=None):
        self.camera = camera
        self.grid = grid
        self.outcomes = dict(outcomes or {})
        self.placed = []
        self.commands = []

    def build(self, col, row, level, timeout=None):
        self.commands.append((col, row, level))
        outcome = self.outcomes.get((col, row))
        if outcome is not None:
            return outcome
        self.placed.append((col, row, "orange"))
        self.camera.set_blocks(self.placed)
        return BuildResult("placed")


def make(mode="vertical", *, outcomes=None, count=6, perspective=0.0, inset=1):
    """A run wired to a mock camera and a rig that draws into it.

    ``inset=1`` by default because MockCamera renders its envelope at 96% of
    the frame, so a block on the outermost row - which legitimately overhangs
    the travel limit by up to max_edge_overhang_y_cm - is cut off by the frame.
    locate_block refuses a clipped block, correctly: its centroid is dragged
    inwards by whatever was lost (21 px on a 40 px block here). Insetting the
    plan is the same answer a real tightly-framed camera needs.
    """
    grid = MachineGrid.from_config(load_rig_config(), mode=mode)
    camera = MockCamera(size=(960, 720), blocks=(), draw_printed_grid=False,
                        perspective=perspective, mode=mode)
    rig = FakeRig(camera, grid, outcomes)

    def capture():
        for _ in range(5):
            ok, frame = camera.read()
            if ok:
                return frame
        raise AssertionError("the mock camera produced no frame")

    # sleep=lambda _: None: the settle wait is real time on a real rig and
    # dead time here. The mock camera renders instantly and has no ringing.
    run = BlockCalibrationRun(rig, capture, grid=grid, count=count,
                              inset=inset, sleep=lambda _seconds: None)
    return run, rig, camera, grid


# --------------------------------------------------------------------------- #
# 1. a clean run recovers the map the mock camera was drawing from
# --------------------------------------------------------------------------- #

for mode in ("vertical", "horizontal"):
    run, rig, camera, grid = make(mode)
    outcomes = list(run.run())
    check(f"{mode}: every planned cell was built",
          len(outcomes) == len(run.session.planned), str(len(outcomes)))
    check(f"{mode}: the rig was asked for level 0 only",
          all(level == 0 for _c, _r, level in rig.commands))
    check(f"{mode}: the feeder was never a build target",
          all((col, row) != (0, 0) for col, row, _level in rig.commands))

    status = run.status()
    check(f"{mode}: the run reports ready", status.ready, status.describe())

    recovered = run.workspace_map(camera.size)
    truth = camera.workspace
    # Corners are normalised, so this is a fraction-of-frame comparison; scale
    # it back to pixels to say something an operator would recognise.
    drift = max(
        math.dist(np.asarray(a) * np.asarray(camera.size),
                  np.asarray(b) * np.asarray(camera.size))
        for a, b in zip(recovered.corners, truth.corners))
    check(f"{mode}: the recovered envelope matches the camera's own",
          drift < 12.0, f"worst corner off by {drift:.1f} px")
    check(f"{mode}: the recovered map carries the mode and counts",
          (recovered.mode, recovered.cols, recovered.rows)
          == (mode, grid.cols, grid.rows))

    # The point of a calibration: a pixel maps back to the cell it came from.
    wrong = []
    for col, row, _colour in rig.placed:
        centre = truth.target_polygon(col, row, camera.size)
        middle = np.asarray(centre, dtype=np.float64).mean(axis=0)
        got = recovered.cell_at(middle, camera.size)
        if got != (col, row):
            wrong.append((col, row, got))
    check(f"{mode}: every placed block maps back to its own cell",
          not wrong, str(wrong))

# --------------------------------------------------------------------------- #
# 1b. the outermost ring is refused, not silently mis-measured
# --------------------------------------------------------------------------- #

run, rig, camera, grid = make("vertical", inset=0)
run.start()
expect("a block clipped by this camera's framing is refused",
       BlockCalibrationError, run.step, "cut off")
check("the refused placement recorded no observation",
      not run.session.observations)
check("the refused placement is retryable, not fatal",
      run.finished_reason is None)


# --------------------------------------------------------------------------- #
# 2. perspective, which is the case a four-click calibration handles worst
# --------------------------------------------------------------------------- #

run, rig, camera, grid = make("vertical", perspective=0.18)
list(run.run())
recovered = run.workspace_map(camera.size)
drift = max(
    math.dist(np.asarray(a) * np.asarray(camera.size),
              np.asarray(b) * np.asarray(camera.size))
    for a, b in zip(recovered.corners, camera.workspace.corners))
check("a perspective view still recovers the envelope", drift < 16.0,
      f"worst corner off by {drift:.1f} px")

# --------------------------------------------------------------------------- #
# 3. the refusals
# --------------------------------------------------------------------------- #

run, rig, camera, grid = make()
expect("stepping before start() is refused", BlockCalibrationError,
       run.step, "start()")

run, rig, camera, grid = make()
run.start()
list(run.run())
expect("stepping past the plan is refused", BlockCalibrationError,
       run.step, "every planned cell")

# A rejected build moved nothing, so it must stay retryable and must NOT be
# confused with an abort.
first = make()[0].session.planned[0]
run, rig, camera, grid = make(
    outcomes={first: BuildResult("rejected", "no block at the feeder")})
run.start()
expect("a rejected placement is retryable", BlockCalibrationError,
       run.step, "feeder")
check("a rejected placement does not end the run",
      run.finished_reason is None)
check("a rejected placement recorded nothing",
      not run.session.observations)

# An abort means the claw may still be holding a block: the run is over.
run, rig, camera, grid = make(
    outcomes={first: BuildResult("aborted", "Z never reached the ground switch")})
run.start()
expect("an abort raises its own type", BlockCalibrationAborted,
       run.step, "go and look")
check("an abort ends the run", run.finished_reason is not None)
expect("an ended run refuses further steps", BlockCalibrationError,
       run.step, "go and look")

# A placement the camera cannot see is reported as such, and the frame still
# becomes the baseline so the next difference is not confused by it.
run, rig, camera, grid = make()
run.start()
camera.set_blocks(())          # the block "vanishes" before the capture


class BlindRig(FakeRig):
    def build(self, col, row, level, timeout=None):
        self.commands.append((col, row, level))
        return BuildResult("placed")


run.rig = BlindRig(camera, grid)
expect("a placed but unseen block says so", BlockCalibrationError,
       run.step, "not seen")

# --------------------------------------------------------------------------- #
# 4. saving is gated on the fit, not on having finished the plan
# --------------------------------------------------------------------------- #

run, rig, camera, grid = make(count=6)
run.start()
for _ in range(4):
    run.step()
expect("four placements cannot be saved", Exception,
       lambda: run.workspace_map(camera.size), "at least")
run.step()
saved = run.workspace_map(camera.size)
check("five placements can be saved", saved is not None)
check("the status agrees that five is enough", run.status().ready)

print()
if failures:
    print(f"{len(failures)} failing check(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")

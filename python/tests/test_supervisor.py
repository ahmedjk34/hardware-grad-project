#!/usr/bin/env python3
"""The classifier, the interlocks, the hysteresis and the two suppressions.

Hand-rolled like ``test_build_controller.py``: a ``check`` helper, PASSED/FAILED
lists, fakes over mocks. No camera, no frames — every case here is built from
synthetic cell sets, which is the point: the subtraction is testable without a
rig precisely because it does not live in ``vision/``.

**Exact cell sets, never counts.** A count-only assertion passes on a board
renumbered by one cell, and that is the failure that matters.

Gate 0's three interlock constants are UNMEASURED and every construction below
passes explicit values. They are test fixtures, not recommendations.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.link import PLACED, BuildResult  # noqa: E402
from rig.placement_ledger import PlacementLedger  # noqa: E402
from rig.supervisor import (  # noqa: E402
    LEVEL_CEILING, MIN_LATTICE_BLOCKS, AMBER_VERDICTS, RED_VERDICTS,
    Interlocks, Observation, Supervisor, classify, observe, unjudged_cells,
)


PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:56} {detail}")


class FakeDetection:
    """A BlockDetection is a pixel centre and no cell. That is the whole point."""

    def __init__(self, center):
        self.center = center


class FakeWorkspace:
    """`cell_at` with a table, so a test can say 'this one lands in a gap'."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def cell_at(self, point, image_size):
        self.calls.append((point, image_size))
        return self.table.get(tuple(point))


def ledger_with(mode, cells):
    ledger = PlacementLedger()
    for col, row, level in cells:
        ledger.append(mode, col, row, level, BuildResult(PLACED))
    return ledger


def supervisor(settle_n=3, settle_m=5, quiet=0.02):
    return Supervisor(quiet_diff_fraction=quiet, settle_n=settle_n,
                      settle_m=settle_m)


def busy_board(n=MIN_LATTICE_BLOCKS):
    """A detection count that clears D10, so FOREIGN/DISAGREES are allowed."""
    return n


# --- pixel -> cell is our own work (§2a.1) --------------------------------- #

workspace = FakeWorkspace({(10.0, 10.0): (1, 1), (20.0, 20.0): (2, 1),
                           (30.0, 30.0): None})
result = observe([FakeDetection((10.0, 10.0)), FakeDetection((20.0, 20.0)),
                  FakeDetection((30.0, 30.0))], workspace, (640, 480))
check("cell_at is called once per detection", len(workspace.calls) == 3)
check("cell_at is given the frame's image size",
      all(call[1] == (640, 480) for call in workspace.calls))
check("observed cells are the exact set", result.cells == ((1, 1), (2, 1)),
      str(result.cells))
check("a None cell becomes off_lattice, not a dropout", result.off_lattice == 1)
check("detections counts everything, for D10", result.detections == 3)
duplicate = observe([FakeDetection((10.0, 10.0)), FakeDetection((10.0, 10.0))],
                    workspace, (640, 480))
check("two detections in one cell are one occupied cell",
      duplicate.cells == ((1, 1),))


# --- D9, every row --------------------------------------------------------- #

full = {(1, 1), (2, 1), (3, 1), (1, 2), (2, 2), (3, 2)}

verdict = classify("vertical", full, full, detections=busy_board())
check("D9 sets equal -> VERIFIED", verdict.verdict == "VERIFIED")
check("VERIFIED names no cells", verdict.cells == ())

verdict = classify("vertical", full, full - {(2, 2)}, detections=busy_board())
check("D9 one missing -> REMOVED", verdict.verdict == "REMOVED")
check("REMOVED names the EXACT cell", verdict.cells == ((2, 2),), str(verdict.cells))

verdict = classify("vertical", full, (full - {(2, 2)}) | {(4, 2)},
                   detections=busy_board())
check("D9 one missing + one unexpected -> MOVED", verdict.verdict == "MOVED")
check("MOVED names both cells, from then to",
      verdict.cells == ((2, 2), (4, 2)), str(verdict.cells))

verdict = classify("vertical", full, full | {(4, 2)}, detections=busy_board())
check("D9 one unexpected -> FOREIGN", verdict.verdict == "FOREIGN")
check("FOREIGN names the EXACT cell", verdict.cells == ((4, 2),))

verdict = classify("vertical", full, full, off_lattice=1, detections=busy_board())
check("D9 a detection in a GAP -> FOREIGN", verdict.verdict == "FOREIGN",
      "a block on the board and not on a site")

verdict = classify("vertical", full, full - {(2, 2), (3, 2)},
                   detections=busy_board())
check("D9 two missing -> DISAGREES", verdict.verdict == "DISAGREES")
check("DISAGREES names every differing cell",
      verdict.cells == ((2, 2), (3, 2)), str(verdict.cells))

verdict = classify("vertical", full, full | {(4, 1), (4, 2)},
                   detections=busy_board())
check("D9 two unexpected -> DISAGREES", verdict.verdict == "DISAGREES")

verdict = classify("vertical", full, (full - {(1, 1), (2, 1)}) | {(4, 1), (4, 2)},
                   detections=busy_board())
check("D9 both sides differ by two -> DISAGREES", verdict.verdict == "DISAGREES")
check("DISAGREES carries BOTH sets for the banner",
      verdict.expected == tuple(sorted(full))
      and (4, 2) in verdict.observed)

check("amber and red are disjoint and complete",
      set(AMBER_VERDICTS) & set(RED_VERDICTS) == set()
      and "DISAGREES" in RED_VERDICTS and "REMOVED" in AMBER_VERDICTS)
check("MOVED is amber, FOREIGN is red",
      classify("vertical", full, (full - {(2, 2)}) | {(4, 2)},
               detections=busy_board()).severity == "amber"
      and classify("vertical", full, full | {(4, 2)},
                   detections=busy_board()).severity == "red")


# --- D6: the level ceiling ------------------------------------------------- #

top_levels = {(1, 1): 0, (2, 1): 2, (3, 1): LEVEL_CEILING, (1, 2): 4}
check("D6 refuses exactly the cells at or above the ceiling",
      unjudged_cells(top_levels) == ((1, 2), (3, 1)), str(unjudged_cells(top_levels)))
check("level 2 is still judged — the ceiling is 3", LEVEL_CEILING == 3)

expected = {(1, 1), (2, 1), (3, 1)}
verdict = classify("vertical", expected, {(1, 1), (2, 1)},
                   top_levels={(1, 1): 0, (2, 1): 0, (3, 1): 3},
                   detections=busy_board())
check("a cell above the ceiling is NEVER reported REMOVED",
      verdict.verdict == "VERIFIED", verdict.verdict)
check("it is listed as unjudged instead of silently skipped",
      verdict.unjudged == ((3, 1),), str(verdict.unjudged))
check("an unjudged cell is absent from expected and observed alike",
      (3, 1) not in verdict.expected and (3, 1) not in verdict.observed)

verdict = classify("vertical", expected, {(1, 1), (2, 1), (3, 1)},
                   top_levels={(3, 1): 4}, detections=busy_board())
check("a cell above the ceiling is never FOREIGN either",
      verdict.verdict == "VERIFIED", verdict.verdict)


# --- D10: sparse boards get no FOREIGN ------------------------------------- #

sparse = {(1, 1), (2, 1)}
verdict = classify("vertical", sparse, sparse | {(4, 4)},
                   detections=MIN_LATTICE_BLOCKS - 1)
check("D10 no FOREIGN below MIN_LATTICE_BLOCKS",
      verdict.verdict == "VERIFIED", verdict.verdict)
verdict = classify("vertical", sparse, sparse, off_lattice=3,
                   detections=MIN_LATTICE_BLOCKS - 1)
check("D10 an off-lattice detection is junk on a sparse board",
      verdict.verdict == "VERIFIED", verdict.verdict)
verdict = classify("vertical", sparse, set(), detections=MIN_LATTICE_BLOCKS - 1)
check("D10 REMOVED still fires on a sparse board",
      verdict.verdict == "REMOVED", verdict.verdict)
check("D10 REMOVED names every missing cell, not DISAGREES",
      verdict.cells == ((1, 1), (2, 1)), str(verdict.cells))
verdict = classify("vertical", sparse, sparse | {(4, 4)},
                   detections=MIN_LATTICE_BLOCKS)
check("at exactly MIN_LATTICE_BLOCKS the filter is trusted again",
      verdict.verdict == "FOREIGN", verdict.verdict)
check("MIN_LATTICE_BLOCKS is block_outline's own 6", MIN_LATTICE_BLOCKS == 6)


# --- D5: each interlock independently suppresses a verdict ----------------- #

ledger = ledger_with("vertical", [(1, 1, 0), (2, 1, 0)])
observation = Observation(cells=((1, 1), (2, 1)), off_lattice=0, detections=8)

for name, locks, want_state in (
        ("uncalibrated", Interlocks(parked=True, calibrated=False, quiet=True), "NO_MAP"),
        ("gantry moving", Interlocks(parked=False, calibrated=True, quiet=True), "BUSY"),
        ("scene not still", Interlocks(parked=True, calibrated=True, quiet=False), "BUSY"),
):
    state, reason, verdict = supervisor().step(
        mode="vertical", ledger=ledger, observation=observation, interlocks=locks)
    check(f"D5 {name} suppresses every verdict",
          verdict is None and state == want_state, f"{state}: {reason}")

check("NO_MAP wins over a moving gantry — say the worse thing",
      Interlocks(parked=False, calibrated=False, quiet=False).refusal()[0] == "NO_MAP")
check("all four gates open means no refusal",
      Interlocks(parked=True, calibrated=True, quiet=True).refusal() is None)

sup = supervisor()
check("the quiet gate is a threshold on the diff fraction",
      sup.is_quiet(0.001) and not sup.is_quiet(0.5))
check("no baseline yet is NOT quiet", sup.is_quiet(None) is False)


# --- D3: no memory refuses every verdict ----------------------------------- #

state, reason, verdict = supervisor().step(
    mode="vertical", ledger=PlacementLedger(), observation=observation,
    interlocks=Interlocks(parked=True, calibrated=True, quiet=True))
check("D3 an empty ledger refuses every verdict",
      verdict is None and state == "NO_MEMORY", f"{state}: {reason}")


# --- D7: hysteresis needs N of M, and RESETS on a tripped interlock -------- #

open_gates = Interlocks(parked=True, calibrated=True, quiet=True)
shut_gates = Interlocks(parked=False, calibrated=True, quiet=True)

sup = supervisor(settle_n=3, settle_m=5)
states = []
for _ in range(2):
    states.append(sup.step(mode="vertical", ledger=ledger,
                           observation=observation, interlocks=open_gates)[0])
check("D7 one clean frame is not evidence", states == ["WARMING", "WARMING"],
      str(states))
state, _, verdict = sup.step(mode="vertical", ledger=ledger,
                             observation=observation, interlocks=open_gates)
check("D7 a verdict arrives on the third of three settle frames",
      state == "VERDICT" and verdict.verdict == "VERIFIED")

sup = supervisor(settle_n=3, settle_m=5)
for _ in range(2):
    sup.step(mode="vertical", ledger=ledger, observation=observation,
             interlocks=open_gates)
sup.step(mode="vertical", ledger=ledger, observation=observation,
         interlocks=shut_gates)
state, _, verdict = sup.step(mode="vertical", ledger=ledger,
                             observation=observation, interlocks=open_gates)
check("D7 a tripped interlock RESETS the counters rather than decaying them",
      state == "WARMING" and verdict is None,
      "two frames of evidence + a trip must not leave one frame short")

sup = supervisor(settle_n=2, settle_m=3)
dropout = Observation(cells=((1, 1),), off_lattice=0, detections=8)
sup.step(mode="vertical", ledger=ledger, observation=observation,
         interlocks=open_gates)
sup.step(mode="vertical", ledger=ledger, observation=dropout,
         interlocks=open_gates)
state, _, verdict = sup.step(mode="vertical", ledger=ledger,
                             observation=observation, interlocks=open_gates)
check("D7 a single-frame dropout is jitter, not a REMOVED",
      state == "VERDICT" and verdict.verdict == "VERIFIED", str(verdict))

sup = supervisor(settle_n=2, settle_m=3)
for _ in range(3):
    state, _, verdict = sup.step(mode="vertical", ledger=ledger,
                                 observation=dropout, interlocks=open_gates)
check("D7 a sustained dropout does become a REMOVED",
      verdict is not None and verdict.verdict == "REMOVED"
      and verdict.cells == ((2, 1),), str(verdict))


# --- D13: a mode change resets, and the lattices never mix ----------------- #

both = ledger_with("vertical", [(1, 1, 0), (2, 1, 0)])
for col, row, level in [(1, 1, 0), (2, 7, 0)]:
    both.append("horizontal", col, row, level, BuildResult(PLACED))

sup = supervisor(settle_n=2, settle_m=3)
sup.step(mode="vertical", ledger=both, observation=observation,
         interlocks=open_gates)
state, _, verdict = sup.step(mode="horizontal", ledger=both,
                             observation=observation, interlocks=open_gates)
check("D13 a mode change resets the hysteresis",
      state == "WARMING" and verdict is None, f"{state}")

sup = supervisor(settle_n=1, settle_m=1)
horizontal = Observation(cells=((1, 1), (2, 7)), off_lattice=0, detections=8)
state, _, verdict = sup.step(mode="horizontal", ledger=both,
                             observation=horizontal, interlocks=open_gates)
check("D13 horizontal is judged against horizontal's lattice alone",
      verdict.verdict == "VERIFIED" and verdict.expected == ((1, 1), (2, 7)),
      str(verdict.expected))


# --- a verdict never locks ------------------------------------------------- #

check("no verdict name is LOCKED",
      "LOCKED" not in set(AMBER_VERDICTS) | set(RED_VERDICTS) | {"VERIFIED"})


# --- Gate 0's constants cannot be guessed ---------------------------------- #

for bad in ({"quiet_diff_fraction": None, "settle_n": 3, "settle_m": 5},
            {"quiet_diff_fraction": 0.02, "settle_n": None, "settle_m": 5},
            {"quiet_diff_fraction": 0.02, "settle_n": 3, "settle_m": None}):
    try:
        Supervisor(**bad)
        check(f"an unmeasured {[k for k, v in bad.items() if v is None][0]} is refused", False)
    except ValueError:
        check(f"an unmeasured {[k for k, v in bad.items() if v is None][0]} is refused", True)
try:
    Supervisor(quiet_diff_fraction=0.02, settle_n=5, settle_m=3)
    check("settle_n > settle_m is refused", False)
except ValueError:
    check("settle_n > settle_m is refused", True)

import rig.supervisor as supervisor_module  # noqa: E402
check("the module constants are still UNMEASURED",
      supervisor_module.QUIET_DIFF_FRACTION is None
      and supervisor_module.SETTLE_N is None
      and supervisor_module.SETTLE_M is None,
      "Gate 0 fills these in; nothing may ship a guess")


print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

#!/usr/bin/env python3
"""The classifier, the interlocks, the hysteresis and the two suppressions.

Hand-rolled like ``test_build_controller.py``: a ``check`` helper, PASSED/FAILED
lists, fakes over mocks. No camera, no frames — every case here is built from
synthetic cell sets, which is the point: the subtraction is testable without a
rig precisely because it does not live in ``vision/``.

**Exact cell sets, never counts.** A count-only assertion passes on a board
renumbered by one cell, and that is the failure that matters.

Gate 0's three interlock constants were measured on the rig on 2026-09-07, but
every construction below still passes explicit values. Those are test fixtures,
not recommendations; the measured defaults are asserted separately at the end.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.link import PLACED, BuildResult  # noqa: E402
from rig.placement_ledger import PlacementLedger  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from rig.supervisor import (  # noqa: E402
    LEVEL_CEILING, MIN_LATTICE_BLOCKS, AMBER_VERDICTS, RED_VERDICTS,
    Interlocks, Observation, Supervisor, classify, locate, observe,
    unjudged_cells,
)
from rig.workspace import WorkspaceMap  # noqa: E402


PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:56} {detail}")


class FakeDetection:
    """A BlockDetection is a pixel centre and no cell. That is the whole point."""

    def __init__(self, center):
        self.center = center


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

#: A real WorkspaceMap, so `locate` is tested against the geometry it will
#: actually see rather than against a stub that agrees with it by construction.
GRID = MachineGrid.from_config(mode="vertical")
SIZE = (1000, 800)
MAP = WorkspaceMap.from_grid(GRID, ((0, 0), (1000, 0), (1000, 800), (0, 800)), SIZE)


def at_cm(x_cm, y_cm):
    return MAP.pixel_at(x_cm / GRID.workspace_width_cm,
                        y_cm / GRID.workspace_height_cm, SIZE)


centre = GRID.cell_center_cm(3, 2)
gap_x = (GRID.cell_center_cm(3, 2)[0] + GRID.cell_center_cm(4, 2)[0]) / 2
check("locate names a cell at a cell centre",
      locate(MAP, at_cm(*centre), SIZE) == ((3, 2), "cell"))
check("locate calls a between-cells point a GAP — on the board, off every site",
      locate(MAP, at_cm(gap_x, centre[1]), SIZE) == (None, "gap"))
check("locate calls a point beyond the envelope OUTSIDE",
      locate(MAP, (-500.0, -500.0), SIZE) == (None, "outside"))
check("locate calls a point past the far edge OUTSIDE",
      locate(MAP, (1200.0, 400.0), SIZE) == (None, "outside"))

result = observe([FakeDetection(at_cm(*centre)),
                  FakeDetection(at_cm(gap_x, centre[1])),
                  FakeDetection((-500.0, -500.0))], MAP, SIZE)
check("observed cells are the exact set", result.cells == ((3, 2),), str(result.cells))
check("a GAP detection is counted as evidence about the board",
      result.in_gap == 1)
check("an OFF-BOARD detection is counted separately, never as gap",
      result.off_board == 1 and result.in_gap == 1)
check("detections counts everything, for D10", result.detections == 3)

duplicate = observe([FakeDetection(at_cm(*centre)), FakeDetection(at_cm(*centre))],
                    MAP, SIZE)
check("two detections in one cell are one occupied cell",
      duplicate.cells == ((3, 2),))

# The measured regression: on 2026-09-07 one persistent object sat off the
# board in 523 of 524 parked frames. Reading it as FOREIGN would have held the
# machine stopped on a board that was entirely correct.
rails = observe([FakeDetection(at_cm(*centre)), FakeDetection((-500.0, -500.0))],
                MAP, SIZE)
verdict = classify("vertical", {(3, 2)}, rails.cells, in_gap=rails.in_gap,
                   detections=busy_board())
check("REGRESSION: an off-board detection NEVER produces FOREIGN",
      verdict.verdict == "VERIFIED", verdict.verdict)


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

verdict = classify("vertical", full, full, in_gap=1, detections=busy_board())
check("D9 a detection in a GAP -> FOREIGN", verdict.verdict == "FOREIGN",
      "a block on the board and not on a site")

# P1, decided with the user: a ONE-SIDED change of any size is named, not
# dismissed. Identity is only needed when there is something to pair with, and
# a clean disappearance with nothing gained offers nothing to pair with.
verdict = classify("vertical", full, full - {(2, 2), (3, 2)},
                   detections=busy_board())
check("P1 two missing, nothing gained -> REMOVED, not DISAGREES",
      verdict.verdict == "REMOVED", verdict.verdict)
check("REMOVED names ALL the missing cells",
      verdict.cells == ((2, 2), (3, 2)), str(verdict.cells))

verdict = classify("vertical", full, full - {(1, 1), (2, 2), (3, 2)},
                   detections=busy_board())
check("P1 three missing is still REMOVED — there is no ambiguity to protect",
      verdict.verdict == "REMOVED" and verdict.cells == ((1, 1), (2, 2), (3, 2)),
      str(verdict.cells))
check("P1 many missing is amber and PAUSES, it does not stop the program",
      verdict.severity == "amber", verdict.severity)

verdict = classify("vertical", full, full | {(4, 1), (4, 2)},
                   detections=busy_board())
check("P1 two unexpected, nothing missing -> FOREIGN, not DISAGREES",
      verdict.verdict == "FOREIGN", verdict.verdict)
check("FOREIGN names ALL the unexpected cells",
      verdict.cells == ((4, 1), (4, 2)), str(verdict.cells))
check("P1 many unexpected is still red — the plan cannot account for them",
      verdict.severity == "red", verdict.severity)

verdict = classify("vertical", full, (full - {(1, 1), (2, 1)}) | {(4, 1), (4, 2)},
                   detections=busy_board())
check("P1 DISAGREES is reserved for BOTH sides changing",
      verdict.verdict == "DISAGREES", verdict.verdict)
check("DISAGREES names every differing cell, from both sides",
      verdict.cells == ((1, 1), (2, 1), (4, 1), (4, 2)), str(verdict.cells))
check("DISAGREES carries BOTH sets for the banner",
      verdict.expected == tuple(sorted(full))
      and (4, 2) in verdict.observed)

# The systemic case P1 was tested against: a camera bump shifts EVERYTHING, so
# it presents as missing AND unexpected and still lands on DISAGREES.
verdict = classify("vertical", full, {(2, 1), (3, 1), (4, 1), (2, 2), (3, 2), (4, 2)},
                   detections=busy_board())
check("P1 a shifted board still reaches DISAGREES, not REMOVED",
      verdict.verdict == "DISAGREES", verdict.verdict)

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
verdict = classify("vertical", sparse, sparse, in_gap=3,
                   detections=MIN_LATTICE_BLOCKS - 1)
check("D10 a gap detection is junk on a sparse board",
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
observation = Observation(cells=((1, 1), (2, 1)), detections=8)

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
dropout = Observation(cells=((1, 1),), detections=8)
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
horizontal = Observation(cells=((1, 1), (2, 7)), detections=8)
state, _, verdict = sup.step(mode="horizontal", ledger=both,
                             observation=horizontal, interlocks=open_gates)
check("D13 horizontal is judged against horizontal's lattice alone",
      verdict.verdict == "VERIFIED" and verdict.expected == ((1, 1), (2, 7)),
      str(verdict.expected))


# --- P2: the MIN_LATTICE_BLOCKS crossing resets too (F8) ------------------- #
#
# The threshold is a cliff, not a slope, and it counts DETECTIONS, not blocks.
# Above it the lattice filter runs and rectifies; below it nothing is rejected.
# Evidence gathered under one filtering regime must not judge under the other —
# D13's argument, applied to the other boundary the observed set has.

busy = Observation(cells=((1, 1), (2, 1)), detections=MIN_LATTICE_BLOCKS)
thin = Observation(cells=((1, 1), (2, 1)), detections=MIN_LATTICE_BLOCKS - 1)

sup = supervisor(settle_n=2, settle_m=3)
sup.step(mode="vertical", ledger=ledger, observation=busy, interlocks=open_gates)
state, _, verdict = sup.step(mode="vertical", ledger=ledger, observation=thin,
                             interlocks=open_gates)
check("P2 dropping below MIN_LATTICE_BLOCKS resets the hysteresis",
      state == "WARMING" and verdict is None, f"{state}")

sup = supervisor(settle_n=2, settle_m=3)
sup.step(mode="vertical", ledger=ledger, observation=thin, interlocks=open_gates)
state, _, verdict = sup.step(mode="vertical", ledger=ledger, observation=busy,
                             interlocks=open_gates)
check("P2 crossing back UP resets it as well — both directions",
      state == "WARMING" and verdict is None, f"{state}")

sup = supervisor(settle_n=2, settle_m=3)
for _ in range(2):
    state, _, verdict = sup.step(mode="vertical", ledger=ledger, observation=busy,
                                 interlocks=open_gates)
check("P2 a STEADY detection count still settles — it is a crossing, not a gate",
      state == "VERDICT" and verdict.verdict == "VERIFIED", f"{state}")

sup = supervisor(settle_n=2, settle_m=3)
for detections in (MIN_LATTICE_BLOCKS + 4, MIN_LATTICE_BLOCKS + 1):
    state, _, verdict = sup.step(
        mode="vertical", ledger=ledger,
        observation=Observation(cells=((1, 1), (2, 1)), detections=detections),
        interlocks=open_gates)
check("P2 a count that moves WITHOUT crossing does not reset",
      state == "VERDICT" and verdict.verdict == "VERIFIED", f"{state}")


# --- a verdict never locks ------------------------------------------------- #

check("no verdict name is LOCKED",
      "LOCKED" not in set(AMBER_VERDICTS) | set(RED_VERDICTS) | {"VERIFIED"})


# --- Gate 0's constants cannot be guessed ---------------------------------- #

for bad in ({"quiet_diff_fraction": None, "settle_n": 3, "settle_m": 5},
            {"quiet_diff_fraction": 0.02, "settle_n": None, "settle_m": 5},
            {"quiet_diff_fraction": 0.02, "settle_n": 3, "settle_m": None},
            {"quiet_diff_fraction": 0.0, "settle_n": 3, "settle_m": 5}):
    try:
        Supervisor(**bad)
        check(f"a bad {[k for k, v in bad.items() if not v][0]} is refused", False)
    except ValueError:
        check(f"a bad {[k for k, v in bad.items() if not v][0]} is refused", True)
try:
    Supervisor(quiet_diff_fraction=0.02, settle_n=5, settle_m=3)
    check("settle_n > settle_m is refused", False)
except ValueError:
    check("settle_n > settle_m is refused", True)

# Gate 0 ran on the rig on 2026-09-07. These are its numbers; the reasoning and
# the measured percentages are in the module's own comment.
import rig.supervisor as supervisor_module  # noqa: E402
check("Gate 0's measured constants are in place",
      supervisor_module.QUIET_DIFF_FRACTION == 0.01
      and supervisor_module.SETTLE_N == 3
      and supervisor_module.SETTLE_M == 5,
      "parked p99 0.000573 / hand p50 0.070745")
check("the defaults are the measured constants",
      Supervisor().quiet_diff_fraction == 0.01)
check("the quiet threshold clears the worst parked maximum seen (0.003855)",
      supervisor_module.QUIET_DIFF_FRACTION > 0.003855)
check("and stays well under the median hand disturbance (0.070745)",
      supervisor_module.QUIET_DIFF_FRACTION < 0.070745 / 5)


print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

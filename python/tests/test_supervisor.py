#!/usr/bin/env python3
"""The classifier, the interlocks, the hysteresis and the level ceiling.

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
    LEVEL_CEILING, PAIRING_BEYOND_CM, AMBER_VERDICTS, RED_VERDICTS,
    Interlocks, Observation, Supervisor, classify, implausible_displacement,
    locate, observe, unjudged_cells, verify_placement,
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
check("observe counts every detection, junk included", result.detections == 3)

duplicate = observe([FakeDetection(at_cm(*centre)), FakeDetection(at_cm(*centre))],
                    MAP, SIZE)
check("two detections in one cell are one occupied cell",
      duplicate.cells == ((3, 2),))

# The measured regression: on 2026-09-07 one persistent object sat off the
# board in 523 of 524 parked frames. Reading it as FOREIGN would have held the
# machine stopped on a board that was entirely correct.
rails = observe([FakeDetection(at_cm(*centre)), FakeDetection((-500.0, -500.0))],
                MAP, SIZE)
verdict = classify("vertical", {(3, 2)}, rails.cells, in_gap=rails.in_gap)
check("REGRESSION: an off-board detection NEVER produces FOREIGN",
      verdict.verdict == "VERIFIED", verdict.verdict)


# --- observe() retains a pick coordinate for the CORRECTION action -------- #
#
# The classifier never looks at these; the operator CORRECTION button does.
# They must round-trip pixel -> cm within the map's own tolerance and stay
# aligned with the gap / cell counts.

class AngledDetection:
    def __init__(self, center, angle):
        self.center, self.angle = center, angle


pts = observe([AngledDetection(at_cm(*centre), 1.5),
               AngledDetection(at_cm(gap_x, centre[1]), 4.0),
               FakeDetection((-500.0, -500.0))], MAP, SIZE)
check("the GAP detection's centre is kept in workspace cm, one per in_gap",
      len(pts.gap_points_cm) == pts.in_gap == 1
      and abs(pts.gap_points_cm[0][0] - gap_x) < 0.05
      and abs(pts.gap_points_cm[0][1] - centre[1]) < 0.05,
      str(pts.gap_points_cm))
check("the GAP detection's angle rides alongside it",
      pts.gap_angles_deg == (4.0,))
check("the ON-CELL detection's centre and angle are kept, keyed by cell",
      pts.cell_points_cm[0][0] == (3, 2)
      and abs(pts.cell_points_cm[0][1][0] - centre[0]) < 0.05
      and pts.cell_angles_deg == (1.5,))
check("an OFF-BOARD detection contributes no pick coordinate",
      len(pts.gap_points_cm) + len(pts.cell_points_cm) == 2)

bare = observe([FakeDetection(at_cm(*centre))], MAP, SIZE)
check("a detection with no .angle attribute defaults to 0.0, never raises",
      bare.cell_angles_deg == (0.0,))


# --- observe() carries the block's OWN measured footprint (Phase 0) -------- #
#
# `block_outline._rectify` hands back the lattice bearing and the population
# median size for every block. Supervision reads `own_angle` and projects the
# detection's own `box` to cm instead — a misplaced block IS the wrong size or
# angle, and the CORRECTION action's consistency check has to see that.

class SizedDetection:
    def __init__(self, center, own_angle, box, own_size=None):
        self.center, self.own_angle, self.box = center, own_angle, box
        if own_size is not None:
            self.own_size = own_size


def box_at_cm(cx, cy, long_cm, short_cm):
    """The four px corners of an axis-aligned block centred at ``(cx, cy)`` cm."""
    hw, hh = long_cm / 2.0, short_cm / 2.0
    return [at_cm(cx - hw, cy - hh), at_cm(cx + hw, cy - hh),
            at_cm(cx + hw, cy + hh), at_cm(cx - hw, cy + hh)]


def own_px(long_cm, short_cm):
    """`own_size` in px for a block that round-trips to `(long_cm, short_cm)`."""
    return (long_cm * SIZE[0] / GRID.workspace_width_cm,
            short_cm * SIZE[1] / GRID.workspace_height_cm)


sized = observe([SizedDetection(at_cm(*centre), 1.0,
                                box_at_cm(centre[0], centre[1], 6.0, 2.2)),
                 SizedDetection(at_cm(gap_x, centre[1]), 2.0,
                                box_at_cm(gap_x, centre[1], 6.0, 2.2))],
                MAP, SIZE)
check("the ON-CELL block's footprint is projected to ~ (6.0, 2.2) cm",
      len(sized.cell_sizes_cm) == 1
      and abs(sized.cell_sizes_cm[0][0] - 6.0) < 0.3
      and abs(sized.cell_sizes_cm[0][1] - 2.2) < 0.3,
      str(sized.cell_sizes_cm))
own_wins = observe([SizedDetection(at_cm(*centre), 0.0,
                                   box_at_cm(centre[0], centre[1], 3.0, 3.0),
                                   own_size=own_px(6.0, 2.2))], MAP, SIZE)
check("_detection_size_cm uses own_size, not the (rectified) box beside it",
      abs(own_wins.cell_sizes_cm[0][0] - 6.0) < 0.3
      and abs(own_wins.cell_sizes_cm[0][1] - 2.2) < 0.3,
      str(own_wins.cell_sizes_cm))

check("the GAP block's footprint rides alongside gap_points_cm, one per in_gap",
      len(sized.gap_sizes_cm) == sized.in_gap == 1
      and abs(sized.gap_sizes_cm[0][0] - 6.0) < 0.3,
      str(sized.gap_sizes_cm))

merged = observe([SizedDetection(at_cm(gap_x, centre[1]), 0.0,
                                 box_at_cm(gap_x, centre[1], 9.4, 2.2))],
                 MAP, SIZE)
check("a merged two-block blob projects at its true oversized length",
      bool(merged.gap_sizes_cm) and merged.gap_sizes_cm[0][0] > 8.5,
      str(merged.gap_sizes_cm))


class RectifiedDetection:
    """What `_rectify` leaves: `angle` is the lattice bearing, `own_angle` is not."""

    angle = 42.0

    def __init__(self, center):
        self.center, self.own_angle, self.box = center, 3.0, None


ra = observe([RectifiedDetection(at_cm(*centre))], MAP, SIZE)
check("observe() reads own_angle, never the rectified lattice bearing",
      ra.cell_angles_deg == (3.0,), str(ra.cell_angles_deg))
check("a detection whose box will not project keeps a (0, 0) size, never raises",
      ra.cell_sizes_cm == ((0.0, 0.0),), str(ra.cell_sizes_cm))


# --- observe() reports per-cell drift (advisory; the classifier ignores it) - #

drifted = observe([FakeDetection(at_cm(centre[0] + 0.8, centre[1]))], MAP, SIZE)
check("observe() reports how far an on-cell block is from its lattice centre",
      len(drifted.cell_residuals_cm) == 1
      and drifted.cell_residuals_cm[0][0] == (3, 2)
      and abs(drifted.cell_residuals_cm[0][1] - 0.8) < 0.05,
      str(drifted.cell_residuals_cm))
check("a drift inside the footprint does NOT change the verdict (still occupied)",
      drifted.cells == ((3, 2),))

square_cell = observe([FakeDetection(at_cm(*centre))], MAP, SIZE)
check("a squarely placed block reports a near-zero residual",
      square_cell.cell_residuals_cm[0][1] < 0.05,
      str(square_cell.cell_residuals_cm))


# --- D9, every row --------------------------------------------------------- #

full = {(1, 1), (2, 1), (3, 1), (1, 2), (2, 2), (3, 2)}

verdict = classify("vertical", full, full)
check("D9 sets equal -> VERIFIED", verdict.verdict == "VERIFIED")
check("VERIFIED names no cells", verdict.cells == ())

verdict = classify("vertical", full, full - {(2, 2)})
check("D9 one missing -> REMOVED", verdict.verdict == "REMOVED")
check("REMOVED names the EXACT cell", verdict.cells == ((2, 2),), str(verdict.cells))

verdict = classify("vertical", full, (full - {(2, 2)}) | {(4, 2)})
check("D9 one missing + one unexpected -> MOVED", verdict.verdict == "MOVED")
check("MOVED names both cells, from then to",
      verdict.cells == ((2, 2), (4, 2)), str(verdict.cells))

verdict = classify("vertical", full, full | {(4, 2)})
check("D9 one unexpected -> FOREIGN", verdict.verdict == "FOREIGN")
check("FOREIGN names the EXACT cell", verdict.cells == ((4, 2),))

verdict = classify("vertical", full, full, in_gap=1)
check("D9 a detection in a GAP with nothing missing -> FOREIGN",
      verdict.verdict == "FOREIGN", "a block the plan cannot account for")

# --- MOVED vs DISPLACED: same event, split by where the block landed ------ #
# `MOVED` (one out, one onto a valid cell) is covered above. DISPLACED is the
# same event with the block landing in the build area but on no site.

verdict = classify("vertical", full, full - {(2, 2)}, in_gap=1)
check("one out, one into the build area off every site -> DISPLACED",
      verdict.verdict == "DISPLACED", verdict.verdict)
check("DISPLACED names the origin cell only, no 'to'",
      verdict.cells == ((2, 2),), str(verdict.cells))
check("DISPLACED is amber — recoverable, the runner pauses",
      verdict.severity == "amber" and "DISPLACED" in AMBER_VERDICTS)

verdict = classify("vertical", full, (full - {(2, 2)}) | {(4, 2)}, in_gap=1)
check("one out, one onto a cell AND something in a gap -> DISAGREES",
      verdict.verdict == "DISAGREES", verdict.verdict)

verdict = classify("vertical", full, full - {(2, 2)}, in_gap=2)
check("one out, TWO in gaps is ambiguous -> DISAGREES",
      verdict.verdict == "DISAGREES", verdict.verdict)

verdict = classify("vertical", full, full - {(2, 2), (3, 2)}, in_gap=1)
check("two out, one in a gap will not pair -> DISAGREES",
      verdict.verdict == "DISAGREES", verdict.verdict)

verdict = classify("vertical", full, full - {(2, 2)})
check("one out, nothing anywhere in the build area -> REMOVED",
      verdict.verdict == "REMOVED", verdict.verdict)

# P1, decided with the user: a ONE-SIDED change of any size is named, not
# dismissed. Identity is only needed when there is something to pair with, and
# a clean disappearance with nothing gained offers nothing to pair with.
verdict = classify("vertical", full, full - {(2, 2), (3, 2)})
check("P1 two missing, nothing gained -> REMOVED, not DISAGREES",
      verdict.verdict == "REMOVED", verdict.verdict)
check("REMOVED names ALL the missing cells",
      verdict.cells == ((2, 2), (3, 2)), str(verdict.cells))

verdict = classify("vertical", full, full - {(1, 1), (2, 2), (3, 2)})
check("P1 three missing is still REMOVED — there is no ambiguity to protect",
      verdict.verdict == "REMOVED" and verdict.cells == ((1, 1), (2, 2), (3, 2)),
      str(verdict.cells))
check("P1 many missing is amber and PAUSES, it does not stop the program",
      verdict.severity == "amber", verdict.severity)

verdict = classify("vertical", full, full | {(4, 1), (4, 2)})
check("P1 two unexpected, nothing missing -> FOREIGN, not DISAGREES",
      verdict.verdict == "FOREIGN", verdict.verdict)
check("FOREIGN names ALL the unexpected cells",
      verdict.cells == ((4, 1), (4, 2)), str(verdict.cells))
check("P1 many unexpected is still red — the plan cannot account for them",
      verdict.severity == "red", verdict.severity)

verdict = classify("vertical", full, (full - {(1, 1), (2, 1)}) | {(4, 1), (4, 2)})
check("P1 DISAGREES is reserved for BOTH sides changing",
      verdict.verdict == "DISAGREES", verdict.verdict)
check("DISAGREES names every differing cell, from both sides",
      verdict.cells == ((1, 1), (2, 1), (4, 1), (4, 2)), str(verdict.cells))
check("DISAGREES carries BOTH sets for the banner",
      verdict.expected == tuple(sorted(full))
      and (4, 2) in verdict.observed)

# The systemic case P1 was tested against: a camera bump shifts EVERYTHING, so
# it presents as missing AND unexpected and still lands on DISAGREES.
verdict = classify("vertical", full, {(2, 1), (3, 1), (4, 1), (2, 2), (3, 2), (4, 2)})
check("P1 a shifted board still reaches DISAGREES, not REMOVED",
      verdict.verdict == "DISAGREES", verdict.verdict)

check("amber and red are disjoint and complete",
      set(AMBER_VERDICTS) & set(RED_VERDICTS) == set()
      and "DISAGREES" in RED_VERDICTS and "REMOVED" in AMBER_VERDICTS)
check("MOVED is amber, FOREIGN is red",
      classify("vertical", full, (full - {(2, 2)}) | {(4, 2)}).severity == "amber"
      and classify("vertical", full, full | {(4, 2)}).severity == "red")


# --- D6: the level ceiling ------------------------------------------------- #

top_levels = {(1, 1): 0, (2, 1): 2, (3, 1): LEVEL_CEILING, (1, 2): 4}
check("D6 refuses exactly the cells at or above the ceiling",
      unjudged_cells(top_levels) == ((1, 2), (3, 1)), str(unjudged_cells(top_levels)))
check("level 2 is still judged — the ceiling is 3", LEVEL_CEILING == 3)

expected = {(1, 1), (2, 1), (3, 1)}
verdict = classify("vertical", expected, {(1, 1), (2, 1)},
                   top_levels={(1, 1): 0, (2, 1): 0, (3, 1): 3})
check("a cell above the ceiling is NEVER reported REMOVED",
      verdict.verdict == "VERIFIED", verdict.verdict)
check("it is listed as unjudged instead of silently skipped",
      verdict.unjudged == ((3, 1),), str(verdict.unjudged))
check("an unjudged cell is absent from expected and observed alike",
      (3, 1) not in verdict.expected and (3, 1) not in verdict.observed)

verdict = classify("vertical", expected, {(1, 1), (2, 1), (3, 1)},
                   top_levels={(3, 1): 4})
check("a cell above the ceiling is never FOREIGN either",
      verdict.verdict == "VERIFIED", verdict.verdict)


# --- D10 removed: the classifier no longer branches on detection count ----- #
#
# The holder is off the rig, so the only surviving rationale for suppressing
# FOREIGN on a sparse board is gone. `locate()` classifies junk by geometry at
# any count, and `classify` takes no `detections` argument any more. FOREIGN
# and DISAGREES are now reachable however few blocks are on the board.

few = {(1, 1), (2, 1)}
check("a near-empty board still names an unexpected cell FOREIGN",
      classify("vertical", few, few | {(4, 4)}).verdict == "FOREIGN")
check("a gap detection is FOREIGN on a near-empty board too",
      classify("vertical", few, few, in_gap=3).verdict == "FOREIGN")
verdict = classify("vertical", few, (few - {(1, 1)}) | {(4, 1), (4, 4)})
check("both sides changing still reaches DISAGREES on a near-empty board",
      verdict.verdict == "DISAGREES", verdict.verdict)
verdict = classify("vertical", few, set())
check("REMOVED names every missing cell, sparse or not",
      verdict.verdict == "REMOVED" and verdict.cells == ((1, 1), (2, 1)),
      str(verdict.cells))
check("classify() no longer accepts a detections argument",
      "detections" not in classify.__code__.co_varnames)


# --- D8a: the per-build sentence, and what it refuses to claim ------------- #

check("D8a level 0 empty -> occupied is decisive",
      verify_placement((3, 1), 0, True) == "verified in frame at [3,1]",
      verify_placement((3, 1), 0, True))
check("D8a level 0 still empty NAMES the cell in the first four words",
      verify_placement((2, 2), 0, False) == "not detected at [2,2]",
      verify_placement((2, 2), 0, False))
check("D8a an empty cell is decisive at EVERY judged level — a tower fell",
      verify_placement((2, 2), 2, False) == "not detected at [2,2]")
check("D8a level 1 occupied is UNCONFIRMED, never verified",
      verify_placement((2, 2), 1, True).startswith("unconfirmed"),
      verify_placement((2, 2), 1, True))
check("D8a and it says why, rather than implying a failure",
      "cannot be told from the one under it" in verify_placement((2, 2), 1, True))
check("D8a level >= the ceiling is refused and SAID",
      verify_placement((1, 1), LEVEL_CEILING, True)
      == "unchecked — level 3 at [1,1] is above the detection ceiling",
      verify_placement((1, 1), LEVEL_CEILING, True))
check("D8a the ceiling wins even over an empty cell — the absence is an artifact",
      verify_placement((1, 1), 4, False).startswith("unchecked — level 4"))
check("D8a no map is unchecked, not unverified",
      verify_placement((1, 1), 0, None, calibrated=False).startswith("unchecked — no map"))
check("D8a a cell that never settled is unchecked, not not-detected",
      verify_placement((1, 1), 0, None).startswith("unchecked"),
      verify_placement((1, 1), 0, None))
check("D8a never says the word 'error' — the machine may have got it right",
      not any("error" in verify_placement(c, l, o, calibrated=cal)
              for c, l, o, cal in (((1, 1), 0, True, True), ((1, 1), 0, False, True),
                                   ((1, 1), 1, True, True), ((1, 1), 3, True, True),
                                   ((1, 1), 0, None, False))))


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


# --- in_gap gets D7's hysteresis too ------------------------------------- #
#
# `in_gap` is the one signal that used to reach `classify` straight from the
# current frame. A single frame where a correctly placed block's centroid
# crosses a footprint boundary must not stop the program, so a non-zero
# `in_gap` now has to survive N of the last M judged frames. Denoising only —
# it does not name the gap cell, and it is not the fix for a MOVED block that
# lands off-site.

clean = Observation(cells=((1, 1), (2, 1)), detections=8)
one_gap = Observation(cells=((1, 1), (2, 1)), in_gap=1, detections=8)

sup = supervisor(settle_n=2, settle_m=3)
for _ in range(2):
    state, _, verdict = sup.step(mode="vertical", ledger=ledger,
                                 observation=clean, interlocks=open_gates)
check("baseline: a matching board with no gap is VERIFIED",
      state == "VERDICT" and verdict.verdict == "VERIFIED", f"{state}")

state, _, verdict = sup.step(mode="vertical", ledger=ledger,
                             observation=one_gap, interlocks=open_gates)
check("a SINGLE gap frame does not stop the program",
      verdict.verdict == "VERIFIED", verdict.verdict)

state, _, verdict = sup.step(mode="vertical", ledger=ledger,
                             observation=one_gap, interlocks=open_gates)
check("a gap sustained N of M frames DOES become FOREIGN",
      verdict.verdict == "FOREIGN", verdict.verdict)

# A tripped interlock resets the gap history along with the cell history (D7:
# reset, never decay) — evidence from a frame that was not allowed to be
# judged must not leak into the next verdict.
shut = Interlocks(parked=True, calibrated=True, quiet=False)
sup.step(mode="vertical", ledger=ledger, observation=one_gap, interlocks=shut)
state, _, verdict = sup.step(mode="vertical", ledger=ledger,
                             observation=one_gap, interlocks=open_gates)
check("one gap frame after an interlock trip is not yet FOREIGN",
      verdict is None or verdict.verdict != "FOREIGN",
      f"{state} {verdict.verdict if verdict else None}")


# --- item 7: gap history is per-identity, and clears everywhere ----------- #
#
# `_gap_history` used to be one global `deque[bool]`: every "a gap exists" frame
# appended True regardless of WHERE, the settled verdict was rendered from the
# CURRENT frame's count (so one gap-free frame cleared it), and `note_mode` /
# the interlock and no-memory branches reset `_CellHistory` but not the gap
# deque. Each fix below is asserted against the model that replaced it.

def gap_frame(x_cm, y_cm, cells=((1, 1), (2, 1))):
    """A settled-board observation with one gap detection at a cm point."""
    return Observation(cells=cells, in_gap=1, detections=6,
                       gap_points_cm=((x_cm, y_cm),))


GAP_A = ((GRID.cell_center_cm(2, 1)[0] + GRID.cell_center_cm(3, 1)[0]) / 2,
         GRID.cell_center_cm(2, 1)[1])
GAP_B = ((GRID.cell_center_cm(1, 1)[0] + GRID.cell_center_cm(1, 2)[0]) / 2,
         (GRID.cell_center_cm(1, 1)[1] + GRID.cell_center_cm(1, 2)[1]) / 2)
clean2 = Observation(cells=((1, 1), (2, 1)), detections=6)


def run(sup, obs, gates=open_gates, mode="vertical", led=None):
    return sup.step(mode=mode, ledger=led if led is not None else ledger,
                    observation=obs, interlocks=gates)


# repeated observation of the SAME gap: settles once, stays coherent.
sup = supervisor(settle_n=2, settle_m=3)
run(sup, gap_frame(*GAP_A))
_, _, v2 = run(sup, gap_frame(*GAP_A))
_, _, v3 = run(sup, gap_frame(*GAP_A))
check("the same gap seen N frames running settles FOREIGN",
      v2.verdict == "FOREIGN", v2.verdict)
check("and stays FOREIGN while that same gap persists — no flicker",
      v3.verdict == "FOREIGN", v3.verdict)

# symmetric clearing: ONE gap-free frame does not clear a settled gap; a full
# N of the last M do (timeout / decay).
_, _, d1 = run(sup, clean2)
_, _, d2 = run(sup, clean2)
check("one gap-free frame does NOT clear a settled gap (clearing is hysteresed)",
      d1.verdict == "FOREIGN", d1.verdict)
check("N gap-free frames decay the gap back to VERIFIED",
      d2.verdict == "VERIFIED", d2.verdict)

# a CHANGED gap identity does not inherit the decayed one's evidence: after the
# gap at A has decayed, a fresh gap at B must warm from nothing.
_, _, b1 = run(sup, gap_frame(*GAP_B))
_, _, b2 = run(sup, gap_frame(*GAP_B))
check("a fresh gap identity warms from nothing, not from the old gap's votes",
      b1.verdict == "VERIFIED", b1.verdict)
check("and settles FOREIGN on its own N-of-M",
      b2.verdict == "FOREIGN", b2.verdict)

# a gap whose position JUMPS more than the match radius in one frame is a new
# identity, not the same one moved.
sup = supervisor(settle_n=2, settle_m=3)
for _ in range(3):
    run(sup, gap_frame(*GAP_A))
_, _, j1 = run(sup, gap_frame(GAP_A[0], GAP_A[1] + 7.6))  # a full pitch away
check("a gap that jumps a whole pitch starts a new identity (old one decays)",
      j1.verdict in ("FOREIGN", "VERIFIED"), j1.verdict)
check("the jumped gap is tracked separately, not as the same gap moved",
      sup._gap_history.settled_gap_count() <= 1
      and len(sup._gap_history._tracks) == 2, str(sup._gap_history._tracks))

# two DISTINCT persistent gaps are two identities, not one repeated vote.
sup = supervisor(settle_n=2, settle_m=3)
two = Observation(cells=((1, 1), (2, 1)), in_gap=2, detections=7,
                  gap_points_cm=(GAP_A, GAP_B))
for _ in range(3):
    _, _, tv = run(sup, two)
check("two persistent distinct gaps settle as a count of 2",
      sup._gap_history.settled_gap_count() == 2, str(sup._gap_history._tracks))
check("  ... and with nothing missing that reads FOREIGN",
      tv.verdict == "FOREIGN", tv.verdict)

# RESET on a tripped interlock: the pre-trip gap votes are GONE, and a full
# fresh N-of-M is required afterwards — the leaked-gap-vote regression the
# audit calls for (the older test only checked the first warming frame).
sup = supervisor(settle_n=2, settle_m=3)
for _ in range(4):
    run(sup, gap_frame(*GAP_A))
run(sup, gap_frame(*GAP_A), gates=shut_gates)     # trip: _reset_hysteresis()
run(sup, clean2)                                  # re-warm the cell history
_, _, r0 = run(sup, clean2)
check("post-trip with no gap the board is VERIFIED — pre-trip votes did not leak",
      r0.verdict == "VERIFIED", r0.verdict)
_, _, r1 = run(sup, gap_frame(*GAP_A))
_, _, r2 = run(sup, gap_frame(*GAP_A))
check("one gap frame after the trip is NOT FOREIGN (no inherited votes)",
      r1.verdict == "VERIFIED", r1.verdict)
check("it takes a full fresh N-of-M after the trip to reach FOREIGN",
      r2.verdict == "FOREIGN", r2.verdict)

# reset() drops the settled gap verdict: it must not survive into the next frame.
sup = supervisor(settle_n=2, settle_m=3)
for _ in range(3):
    run(sup, gap_frame(*GAP_A))
sup.reset()
state, _, v = run(sup, gap_frame(*GAP_A))
check("reset() drops the stale gap verdict — the next frame re-warms",
      state == "WARMING" and v is None, f"{state} {v}")

# a MODE LATCH clears the gap history too, not just the cell history (D13).
mixed = ledger_with("vertical", [(1, 1, 0), (2, 1, 0)])
mixed.append("horizontal", 1, 1, 0, BuildResult(PLACED))
sup = supervisor(settle_n=1, settle_m=2)
run(sup, gap_frame(*GAP_A), led=mixed)            # vertical: gap settles FOREIGN
_, _, hv = sup.step(mode="horizontal", ledger=mixed,
                    observation=Observation(cells=((1, 1),), detections=4),
                    interlocks=open_gates)
check("a mode latch clears the gap history — horizontal is not FOREIGN off "
      "vertical's gap", hv is not None and hv.verdict == "VERIFIED", str(hv))


# --- step() rejects a DISPLACED pairing the geometry cannot support -------- #
#
# `classify` names the emptied cell as the origin of the gap detection by set
# difference alone. When `step()` is given the grid, a gap block more than
# PAIRING_BEYOND_CM past that cell's neighbour is downgraded to DISAGREES —
# different blocks, or a misregistered map.

pair_ledger = ledger_with("vertical", [(1, 1, 0), (2, 1, 0)])
plan_centre = GRID.cell_center_cm(2, 1)  # (7.6, 7.6)

near_gap = Observation(cells=((1, 1),), in_gap=1, detections=4,
                       gap_points_cm=((plan_centre[0] + 1.9, plan_centre[1]),))
sup = supervisor(settle_n=1, settle_m=1)
state, reason, verdict = sup.step(mode="vertical", ledger=pair_ledger,
                                  observation=near_gap, interlocks=open_gates,
                                  grid=GRID)
check("a gap block one cell away stays DISPLACED", verdict.verdict == "DISPLACED",
      f"{verdict.verdict} / {reason}")

far_gap = Observation(cells=((1, 1),), in_gap=1, detections=4,
                      gap_points_cm=((plan_centre[0], plan_centre[1] + 11.0),))
sup = supervisor(settle_n=1, settle_m=1)
state, reason, verdict = sup.step(mode="vertical", ledger=pair_ledger,
                                  observation=far_gap, interlocks=open_gates,
                                  grid=GRID)
check("a gap block 11 cm from the paired cell is downgraded to DISAGREES",
      verdict.verdict == "DISAGREES", f"{verdict.verdict}")
check("  ... and the reason names the distance and the cell",
      reason is not None and "past the cell [2,1]" in reason, str(reason))
check("  ... DISAGREES stops the runner (red)", verdict.severity == "red")

check("without a grid, step() publishes the DISPLACED verdict unchanged",
      supervisor(settle_n=1, settle_m=1).step(
          mode="vertical", ledger=pair_ledger, observation=far_gap,
          interlocks=open_gates)[2].verdict == "DISPLACED")

check("implausible_displacement returns None for a credible pairing",
      implausible_displacement(GRID, (2, 1), near_gap) is None)
check("implausible_displacement explains an incredible one",
      "past the cell" in (implausible_displacement(GRID, (2, 1), far_gap) or ""))
check("PAIRING_BEYOND_CM is the provisional 1.0 cm slack", PAIRING_BEYOND_CM == 1.0)


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

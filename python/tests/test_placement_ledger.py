#!/usr/bin/env python3
"""The as-built memory: what it admits, what it separates, what it refuses.

Hand-rolled in the same style as ``test_build_controller.py`` and
``test_grid.py`` — a ``check`` helper, PASSED/FAILED lists, fakes over mocks.

**Every occupancy assertion compares an EXACT cell set, never a count.** A
count-only assertion passes on a board renumbered by one cell, and a board
renumbered by one cell is the failure that matters (BLOCK-VISION §0).
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.build_controller import BuildController  # noqa: E402
from rig.grid import MachineGrid  # noqa: E402
from rig.link import ABORTED, PLACED, REJECTED, BuildResult  # noqa: E402
from rig.placement_ledger import GROUND, PlacementLedger  # noqa: E402


PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:52} {detail}")


class FakeRig:
    """The pattern from test_build_controller.py, unchanged."""

    def __init__(self, outcomes, mode="vertical"):
        self.grid = MachineGrid.from_config(mode=mode)
        self.outcomes = list(outcomes)
        self.calls = []

    def build(self, col, row, level, timeout=300):
        self.calls.append((col, row, level, timeout))
        return self.outcomes.pop(0)

    def set_mode(self, mode):
        self.grid = MachineGrid.from_config(mode=mode)

    def home(self, full=True):
        return True


def fill(ledger, mode, cells):
    for col, row, level in cells:
        ledger.append(mode, col, row, level, BuildResult(PLACED))
    return ledger


# --- D3: no memory after a restart ---------------------------------------- #

ledger = PlacementLedger()
check("a fresh ledger has NO MEMORY", ledger.has_memory() is False)
check("no memory means an empty occupancy set, not an error",
      ledger.expected_occupancy("vertical") == frozenset())
ledger.append("vertical", 3, 2, 0, BuildResult(PLACED))
check("one placement gives it a memory", ledger.has_memory() is True)
check("a fresh ledger of its own is still empty (nothing is reloaded)",
      PlacementLedger().has_memory() is False)


# --- D2: PLACED only ------------------------------------------------------- #

ledger = PlacementLedger()
check("rejected is refused",
      ledger.append("vertical", 1, 1, 0, BuildResult(REJECTED, "empty feeder")) is None)
check("aborted is refused",
      ledger.append("vertical", 2, 2, 0, BuildResult(ABORTED, "claw unknown")) is None)
check("a refused build leaves NO memory at all", ledger.has_memory() is False)
check("refusals leave the occupancy set exactly empty",
      ledger.expected_occupancy("vertical") == frozenset())
entry = ledger.append("vertical", 2, 2, 0, BuildResult(PLACED))
check("placed is admitted and returns its entry",
      entry is not None and entry.cell == (2, 2) and entry.level == 0)
check("admitted placement is the exact cell set",
      ledger.expected_occupancy("vertical") == frozenset({(2, 2)}))


# --- D13: the two lattices are separate ------------------------------------ #

ledger = PlacementLedger()
fill(ledger, "vertical", [(1, 1, 0), (2, 1, 0), (3, 4, 0)])
fill(ledger, "horizontal", [(1, 1, 0), (2, 7, 0)])
check("vertical returns exactly its own cells",
      ledger.expected_occupancy("vertical") == frozenset({(1, 1), (2, 1), (3, 4)}),
      str(sorted(ledger.expected_occupancy("vertical"))))
check("horizontal returns exactly its own cells",
      ledger.expected_occupancy("horizontal") == frozenset({(1, 1), (2, 7)}),
      str(sorted(ledger.expected_occupancy("horizontal"))))
check("a cell in both modes is not one fact",
      ledger.expected_top_level("vertical")[(1, 1)] == 0
      and (1, 1) in ledger.expected_top_level("horizontal"))
check("an unknown mode is empty, not a mix",
      ledger.expected_occupancy("diagonal") == frozenset())
check("placements() filters by mode exactly",
      tuple(p.cell for p in ledger.placements("horizontal")) == ((1, 1), (2, 7)))


# --- D4: levels collapse to a column --------------------------------------- #

ledger = PlacementLedger()
fill(ledger, "vertical", [(2, 2, 0), (2, 2, 1), (2, 2, 2), (5, 3, 0)])
check("a three-high stack is ONE occupied cell",
      ledger.expected_occupancy("vertical") == frozenset({(2, 2), (5, 3)}),
      str(sorted(ledger.expected_occupancy("vertical"))))
check("top level is the highest placed, not the last",
      ledger.expected_top_level("vertical") == {(2, 2): 2, (5, 3): 0})
ledger.append("vertical", 2, 2, 1, BuildResult(PLACED))
check("a re-place at a lower level does not lower the top",
      ledger.expected_top_level("vertical")[(2, 2)] == 2)
check("every placement is kept in order, including the re-place",
      tuple(p.level for p in ledger.placements("vertical")) == (0, 1, 2, 0, 1))


# --- rotation is not stored (D2 / §2a.3) ----------------------------------- #

check("a Placement has no rotation field — rotation IS the mode",
      not hasattr(ledger.placements("vertical")[0], "rotation"))


# --- Stage 15's D5: is_top_of_column --------------------------------------- #

ledger = PlacementLedger()
fill(ledger, "vertical", [(2, 2, 0), (2, 2, 1), (4, 1, 0)])
check("the top of a stack is the top of its column",
      ledger.is_top_of_column("vertical", 2, 2, 1) is True)
check("a buried block is not", ledger.is_top_of_column("vertical", 2, 2, 0) is False)
check("a lone level-0 block is the top of its column",
      ledger.is_top_of_column("vertical", 4, 1, 0) is True)
check("a cell nothing was placed on has no top",
      ledger.is_top_of_column("vertical", 6, 5, 0) is False)
check("a level above the stack is not the top either",
      ledger.is_top_of_column("vertical", 2, 2, 2) is False)
check("the predicate is per mode",
      ledger.is_top_of_column("horizontal", 2, 2, 1) is False)


# --- Stage 15's D6: has_taller_neighbour ----------------------------------- #

ledger = PlacementLedger()
#   [3,2] is a two-high stack; [2,2] and [4,2] sit beside it at level 0;
#   [3,4] is two cells away and [4,3] is diagonal.
fill(ledger, "vertical", [(3, 2, 0), (3, 2, 1), (2, 2, 0), (4, 2, 0),
                          (3, 4, 0), (4, 3, 0)])
check("a level-0 block beside a two-high stack has a taller neighbour",
      ledger.has_taller_neighbour("vertical", 2, 2) is True)
check("the tall stack itself does not",
      ledger.has_taller_neighbour("vertical", 3, 2) is False)
check("a block two cells away is unaffected",
      ledger.has_taller_neighbour("vertical", 3, 4) is False)
check("a DIAGONAL neighbour does not count — the claw descends on the axes",
      ledger.has_taller_neighbour("vertical", 4, 3) is False)
check("an empty cell beside a block has a taller neighbour (empty is GROUND)",
      ledger.has_taller_neighbour("vertical", 1, 2) is True)
check("an empty cell in open space does not",
      ledger.has_taller_neighbour("vertical", 6, 5) is False)
check("GROUND sorts below level 0 — an empty cell is not a level-0 block",
      GROUND < 0)


# --- the BuildController hook ---------------------------------------------- #

ledger = PlacementLedger()
rig = FakeRig([BuildResult(PLACED)])
controller = BuildController(rig, level=1, ledger=ledger)
controller.select((3, 4))
controller.build()
check("a placed build reaches the ledger",
      ledger.expected_occupancy("vertical") == frozenset({(3, 4)}))
check("the hook records the controller's level, not zero",
      ledger.expected_top_level("vertical") == {(3, 4): 1})

ledger = PlacementLedger()
rig = FakeRig([BuildResult(REJECTED, "empty feeder"), BuildResult(ABORTED, "held")])
controller = BuildController(rig, ledger=ledger)
controller.select((3, 4))
controller.build()
check("a rejected build reaches nothing", ledger.has_memory() is False)
check("a rejected build keeps its selection", controller.selected == (3, 4))
controller.build()
check("an aborted build reaches nothing", ledger.has_memory() is False)
check("an aborted build locks the controller", controller.locked)
check("nothing was recorded across either failure",
      ledger.expected_occupancy("vertical") == frozenset())

ledger = PlacementLedger()
rig = FakeRig([BuildResult(PLACED)], mode="horizontal")
controller = BuildController(rig, ledger=ledger)
controller.select((2, 7))
controller.build()
check("the hook records the mode the rig is actually in",
      ledger.expected_occupancy("horizontal") == frozenset({(2, 7)})
      and ledger.expected_occupancy("vertical") == frozenset())

rig = FakeRig([BuildResult(PLACED)])
plain = BuildController(rig)
plain.select((3, 4))
plain.build()
check("a controller with no ledger still builds", plain.selected is None)


# --- audit item 8: memory is scoped by board epoch ----------------------- #
#
# A gantry reboot / reconnect / operator board swap calls `new_board_epoch()`.
# The rows are KEPT for the record, but `has_memory` / `expected_occupancy` and
# every derived predicate answer for the CURRENT epoch only — so a superseded
# board can never lend authority to a verdict about the one on the table now.

ledger = PlacementLedger()
check("a fresh ledger is board epoch 0", ledger.board_epoch == 0)
fill(ledger, "vertical", [(1, 1, 0), (2, 1, 0)])
check("epoch 0 has memory for vertical",
      ledger.has_memory("vertical", 0) is True)
check("placements are stamped with the epoch they were made in",
      all(p.board_epoch == 0 for p in ledger.placements("vertical")))

epoch = ledger.new_board_epoch()
check("new_board_epoch() returns and advances to epoch 1", epoch == 1
      and ledger.board_epoch == 1)
check("the current epoch has NO memory — nothing placed in it yet",
      ledger.has_memory("vertical") is False)
check("current-epoch occupancy is empty after the bump",
      ledger.expected_occupancy("vertical") == frozenset())
check("the old epoch's rows are retained and still addressable explicitly",
      ledger.expected_occupancy("vertical", 0) == frozenset({(1, 1), (2, 1)}))
check("the every-epoch (history) view still sees them",
      ledger.has_memory("vertical", None) is True
      and len(ledger.placements("vertical", None)) == 2)

fill(ledger, "vertical", [(4, 4, 0)])
check("a placement after the bump is stamped epoch 1",
      ledger.placements("vertical")[-1].board_epoch == 1)
check("current-epoch memory is exactly the post-bump placement",
      ledger.expected_occupancy("vertical") == frozenset({(4, 4)}))
check("the old epoch is unchanged by the new placement",
      ledger.expected_occupancy("vertical", 0) == frozenset({(1, 1), (2, 1)}))

# mode AND epoch together: horizontal placed in epoch 1 is not vertical's, and
# not epoch 0's either.
fill(ledger, "horizontal", [(1, 1, 0)])
check("has_memory is false for a mode with nothing in this epoch",
      ledger.has_memory("horizontal", 0) is False)
check("has_memory is true for the mode+epoch that was actually placed",
      ledger.has_memory("horizontal", 1) is True)
check("is_top_of_column is scoped to the current epoch",
      ledger.is_top_of_column("vertical", 4, 4, 0) is True
      and ledger.is_top_of_column("vertical", 1, 1, 0) is False)
check("has_taller_neighbour is scoped to the current epoch",
      ledger.has_taller_neighbour("vertical", 1, 1) is False)


print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

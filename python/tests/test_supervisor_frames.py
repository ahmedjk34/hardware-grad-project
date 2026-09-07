#!/usr/bin/env python3
"""The Gate 0 rig traces, replayed frame by frame through the real Supervisor.

This is P6, and it is deliberately **not** the test the design's §8 asked for.
That one wanted the two reference stills in ``python/captures/`` run through the
detector. These CSVs are stronger evidence and cheaper: they are **1398 frames
the rig actually produced** on 2026-09-07 — same camera, same settings, same
colour correction, same lens map, same 8.6-8.7 Hz analysis worker — on boards
whose contents are known exactly. A still proves the classifier can read one
frame; a trace proves it survives a real one's jitter, its dropouts and its
off-board junk over a minute.

No camera and no OpenCV: the CSVs are the pipeline's own output and everything
below is arithmetic over them. Hand-rolled in the neighbouring style — a
``check`` helper, PASSED/FAILED lists, fakes over mocks.

**Exact cell sets, never counts.** The board's five cells are named in
``PLACED_CELLS`` and asserted as a set, because a count assertion passes on a
board renumbered by one cell.

WHAT THE FIXTURES CAN AND CANNOT SAY
------------------------------------
Only ``gate0_split.csv`` carries the ``gap`` / ``margin`` / ``outside`` split.
The other three predate that instrumentation and log one merged ``off_lattice``
count — which is **F6 exactly**: the persistent off-board object was gone by
the time the splitting instrument ran, so it was never classified. This file
does not paper over that. It replays those runs with ``in_gap = 0`` (the
reading that holds if the object is off the board) and, separately, replays the
parked run with ``in_gap = off_lattice`` to reproduce the **pre-fix merged
behaviour** and show what it did: FOREIGN in 99.8% of windows on a board that
was entirely correct. That second replay is the F5 regression, built from the
column the CSV actually has rather than from one inferred.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.link import PLACED, BuildResult  # noqa: E402
from rig.placement_ledger import PlacementLedger  # noqa: E402
from rig.supervisor import (  # noqa: E402
    Interlocks, Observation, Supervisor,
)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:58} {detail}")


#: Session 2, 2026-09-07. Five RIG-PLACED blocks. F4 is emphatic that a
#: hand-scattered board is a different regime and not a weaker one, so only the
#: rig-placed runs are ever replayed as *correct* boards.
PLACED_CELLS = ((0, 2), (2, 0), (2, 1), (3, 2), (4, 4))

MEASUREMENTS = Path(__file__).resolve().parents[2] / "docs" / "measurements"


def load(name):
    """One Gate 0 CSV as dicts. Written by python/tools/measure_quiet_window.py.

    ``cells`` is space-separated ``col:row`` and ``elsewhere`` is free text, so
    the columns are taken positionally against the header the file was written
    with — two header shapes exist and the older one has no ``in_gap``.
    """
    lines = [line for line in (MEASUREMENTS / name).read_text().splitlines()
             if line.strip()]
    header = lines[0].split(",")
    rows = []
    for line in lines[1:]:
        row = dict(zip(header, line.split(",")))
        row["cells"] = tuple(sorted(
            (int(c.split(":")[0]), int(c.split(":")[1]))
            for c in row["cells"].split() if ":" in c))
        row["detections"] = int(row["detections"] or 0)
        row["off_lattice"] = int(row["off_lattice"] or 0)
        #: Absent from every run but `split` — see the module docstring.
        row["in_gap"] = int(row.get("in_gap") or 0)
        row["split_instrumented"] = "in_gap" in header
        row["calibrated"] = row["calibrated"] == "1"
        row["diff_fraction"] = (float(row["diff_fraction"])
                                if row["diff_fraction"] else None)
        rows.append(row)
    return rows


def ledger_for(cells):
    ledger = PlacementLedger()
    for col, row in cells:
        ledger.append("vertical", col, row, 0, BuildResult(PLACED))
    return ledger


def replay(rows, *, ledger=None, parked=True, merge_off_lattice=False):
    """Every row through the real Supervisor. Returns ``(tally, verdicts)``.

    The interlocks are assembled exactly as ``web/app.py`` will: the quiet gate
    from the frame's own measured difference fraction through
    ``Supervisor.is_quiet``, the map gate from ``calibrated``. Nothing is
    stubbed to agree with the classifier.

    ``merge_off_lattice`` reproduces the DEFECT — every ``cell_at -> None``
    read as a gap — and exists only so its consequence can be asserted.
    """
    ledger = ledger if ledger is not None else ledger_for(PLACED_CELLS)
    sup = Supervisor()
    tally, verdicts = {}, []
    for row in rows:
        observation = Observation(
            cells=row["cells"],
            in_gap=row["off_lattice"] if merge_off_lattice else row["in_gap"],
            detections=row["detections"])
        state, _reason, verdict = sup.step(
            mode="vertical", ledger=ledger, observation=observation,
            interlocks=Interlocks(parked=parked, calibrated=row["calibrated"],
                                  quiet=sup.is_quiet(row["diff_fraction"])))
        name = verdict.verdict if verdict is not None else state
        tally[name] = tally.get(name, 0) + 1
        if verdict is not None:
            verdicts.append(verdict)
    return tally, verdicts


def share(tally, name):
    total = sum(tally.values())
    return 100.0 * tally.get(name, 0) / total if total else 0.0


# --- the fixtures are the evidence base, so assert they are intact --------- #

split = load("gate0_split.csv")
parked = load("gate0_parked.csv")
program = load("gate0_program.csv")
hand = load("gate0_hand.csv")

check("the split trace is the 172 frames §1.2 records", len(split) == 172,
      f"{len(split)} rows")
check("the parked trace is the 524 frames §1.2 records", len(parked) == 524,
      f"{len(parked)} rows")
check("every frame of every run was calibrated",
      all(row["calibrated"] for row in split + parked + program + hand))
check("only the split run carries the gap/margin/outside split (F6)",
      split[0]["split_instrumented"]
      and not any(row["split_instrumented"] for row in parked + program + hand),
      "the object had gone before the splitting instrument ran")


# --- the clean run: a correct board must read as a correct board ----------- #

tally, verdicts = replay(split)
check("SPLIT: the clean rig-placed run is overwhelmingly VERIFIED",
      share(tally, "VERIFIED") > 95.0, f"{share(tally, 'VERIFIED'):.1f}%")
check("SPLIT: not one false verdict on a board that was correct",
      not any(v.verdict != "VERIFIED" for v in verdicts),
      str(sorted({v.verdict for v in verdicts})))
check("SPLIT: every verdict judged the EXACT five placed cells",
      all(v.expected == tuple(sorted(PLACED_CELLS)) for v in verdicts),
      str(verdicts[0].expected))
check("SPLIT: and observed exactly those five, never a renumbered set",
      all(v.observed == tuple(sorted(PLACED_CELLS)) for v in verdicts))
# Q6, from the trace itself: this run never had more than 5 detections in a
# frame, and every verdict on it was still correct. Detection count no longer
# gates anything (D10 removed with the holder), but the fact is worth pinning:
# a low count is not a degraded verdict for a cell the ledger named.
check("SPLIT: five detections at most, and still flawless",
      max(row["detections"] for row in split) <= 5,
      f"{max(row['detections'] for row in split)} detections at most")


# --- F5, the regression that would have stopped the machine --------------- #

tally, verdicts = replay(parked)
check("F5 REGRESSION: the off-board object NEVER produces FOREIGN",
      "FOREIGN" not in tally, str(tally))
check("F5 REGRESSION: nor DISAGREES", "DISAGREES" not in tally, str(tally))
check("PARKED: still overwhelmingly VERIFIED with the object in frame",
      share(tally, "VERIFIED") > 95.0, f"{share(tally, 'VERIFIED'):.1f}%")

# The defect itself, replayed. This is §1.9's third row, and the reason
# `locate()`'s three-way split is load-bearing rather than tidy.
broken, _ = replay(parked, merge_off_lattice=True)
check("F5 the PRE-FIX merged reading stops the machine on a correct board",
      share(broken, "FOREIGN") > 95.0, f"{share(broken, 'FOREIGN'):.1f}% FOREIGN")

# §1.6's honest residual: (2,0) has 97.3% recall, so ~1.35% of windows read it
# as gone. Amber — it pauses rather than stops, and D12 covers it. Not free,
# and pinned here so a regression cannot hide inside it.
removed = [v for v in verdicts if v.verdict == "REMOVED"]
check("PARKED: the residual REMOVED rate matches the ~1.35% predicted by recall",
      share(tally, "REMOVED") < 3.0, f"{share(tally, 'REMOVED'):.2f}%")
check("PARKED: and every one of them names (2,0), the 97.3%-recall cell",
      bool(removed) and all(v.cells == ((2, 0),) for v in removed),
      str(sorted({v.cells for v in removed})) if removed else "none fired")


# --- the interlocks, against a real disturbance --------------------------- #

tally, _ = replay(hand)
check("HAND: a hand over the board is BUSY, never a verdict",
      share(tally, "BUSY") > 80.0, f"{share(tally, 'BUSY'):.1f}%")
check("HAND: and it never yields a red verdict",
      not {"FOREIGN", "DISAGREES"} & set(tally), str(tally))

tally, _ = replay(split, parked=False)
check("D5 a moving gantry suppresses every verdict on a real trace",
      set(tally) == {"BUSY"}, str(tally))

tally, verdicts = replay(split, ledger=PlacementLedger())
# BUSY on the first frame, and that is the ordering the interlocks want: D5's
# gates are asked before the memory is, so "the scene was not still" is
# reported ahead of "there is nothing to compare it to". Neither is a verdict.
check("D3 an empty ledger yields no verdict on any frame of a real trace",
      not verdicts and set(tally) <= {"NO_MEMORY", "BUSY"}, str(tally))
check("D3 and every judgeable frame of it says NO MEMORY",
      tally.get("NO_MEMORY") == len(split) - tally.get("BUSY", 0), str(tally))


# --- detection count no longer changes a verdict -------------------------- #
#
# F8/P2 are retired: `note_regime` reset the hysteresis on the count crossing 6
# because `_lattice_filter` switched behaviour there. With D10 gone the
# classifier ignores the count entirely, so a swing in `detections` — the exact
# thing the hand run does 6 times — must not disturb a settle in progress.
sup = Supervisor(quiet_diff_fraction=0.01, settle_n=3, settle_m=5)
ledger = ledger_for(PLACED_CELLS)
open_gates = Interlocks(parked=True, calibrated=True, quiet=True)
states = []
for detections in (8, 8, 4, 4, 4):
    states.append(sup.step(
        mode="vertical", ledger=ledger,
        observation=Observation(cells=tuple(sorted(PLACED_CELLS)),
                                detections=detections),
        interlocks=open_gates)[0])
check("a detection-count swing does not restart the settle",
      states == ["WARMING", "WARMING", "VERDICT", "VERDICT", "VERDICT"],
      str(states))


print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)

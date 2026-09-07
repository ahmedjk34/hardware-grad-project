#!/usr/bin/env python3
"""Gate 0 for placement supervision — does the quiet window ever open?

THROWAWAY. Nothing imports this and nothing in the app depends on it. It exists
to answer three questions with measurements instead of guesses, before a line
of ``rig/supervisor.py`` is written:

1. Does the quiet window ever open, and how often?
2. Is detection stable frame to frame?
3. Do cells assign consistently?

Those answers set ``QUIET_DIFF_FRACTION``, ``SETTLE_N`` and ``SETTLE_M``.
``docs/features/placement-supervision.md`` D5 carries placeholder values of
0.02 / 3 / 5 and says outright that they are "to be measured on hardware, not
trusted from here".

> **If the quiet window never opens, supervision would sit at BUSY forever and
> silently do nothing.** That is the single biggest risk in the feature and
> this script is how it is retired. Say so in the summary rather than picking a
> threshold that makes the number look better.

Run it with the rig PARKED and nobody's hands over the board::

    .venv/bin/python python/tools/measure_quiet_window.py --seconds 60 --csv /tmp/gate0.csv

It opens the camera through ``ConsolePipeline`` exactly as the console does —
same settings file, same colour correction, same lens map, same 10 Hz analysis
worker — so the numbers describe the frames supervision will actually see. It
adds no detector, takes no extra frames and never touches ``vision/``.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import SETTINGS_PATH  # noqa: E402
from rig.console_pipeline import ConsolePipeline  # noqa: E402
from rig.workspace import WORKSPACE_MAP_PATH  # noqa: E402

#: Per-pixel level at which a channel-max difference counts as "this pixel
#: changed". ``vision/block_grid.py``'s DIFF_MIN_THRESHOLD, so the energy
#: fraction here is measured on the same footing as the one detector in the
#: repo that already differences frames.
PIXEL_THRESHOLD = 18

#: The fractions we report window counts for. 0.02 is the plan's placeholder;
#: the rest are there so the choice is made from a curve rather than one number.
CANDIDATE_FRACTIONS = (0.002, 0.005, 0.01, 0.02, 0.05, 0.10)

#: Settle lengths we simulate, in frames. At the pipeline's 10 Hz these are
#: 0.3 / 0.5 / 0.6 / 0.8 s of continuous stillness.
CANDIDATE_SETTLES = (3, 5, 6, 8)


def diff_fraction(view: np.ndarray, previous: np.ndarray | None) -> float | None:
    """Fraction of pixels whose channel-max change clears PIXEL_THRESHOLD.

    Channel-max, not a grey difference: ``_difference_sightings`` explains why
    — a pale wooden block on pale paper separates far better in one channel
    than in luminance, and which channel that is depends on the cast of the day.

    This is a full-frame numpy op, ~5-15 ms at 1296 px on a Pi 5, which is
    precisely why the real supervisor must run it on the single-threaded
    executor with the other OpenCV work (AGENTS.md §7) and not on the event
    loop. Here it is on the main thread because nothing else is.
    """
    if previous is None or previous.shape != view.shape:
        return None
    diff = np.abs(view.astype(np.int16) - previous.astype(np.int16)).max(axis=2)
    return float(np.count_nonzero(diff >= PIXEL_THRESHOLD)) / float(diff.size)


def cell_for(frame, detection):
    """Pixel -> cell, which is the supervisor's own work.

    ``_lattice_filter`` solves indices relative to ``detections[0]`` only to
    decide keep/reject and then DISCARDS them, so a ``BlockDetection`` carries
    a pixel centre and no cell. ``WorkspaceMap.cell_at`` is the only route.

    It returns None for two different facts and only one is a dropout: outside
    the quadrilateral means "not on the board"; inside it but in a deliberate
    gap between block footprints means "a block IS on the board and is not on a
    site" — a FOREIGN-shaped fact. This script counts them together and reports
    the total; separating them needs the supervisor's own geometry, and what
    matters at Gate 0 is how often it happens at all.
    """
    return frame.workspace.cell_at(detection.center, frame.image_size)


def quiet_runs(quiet_flags: list[bool]) -> list[int]:
    """Lengths of every maximal run of consecutive quiet frames."""
    runs, current = [], 0
    for flag in quiet_flags:
        if flag:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


def settle_windows(quiet_flags: list[bool], m: int) -> int:
    """How many times M consecutive quiet frames were available.

    D5 is explicit that a frame over the threshold is DISCARDED and RESTARTS
    the settle timer — it does not merely fail to count. So this is runs of
    consecutive quiet frames, never a sliding N-of-M that a flickering scene
    could satisfy by alternating. Modelling it the loose way was the first
    thing this script got wrong, and it flattered the result: an alternating
    quiet/busy stream satisfies "3 of 5" on every other frame and never
    contains three consecutive still frames at all.

    Counted as opportunities, not frames: a run of forty quiet frames is one
    chance to judge, not thirty-eight.
    """
    return sum(1 for run in quiet_runs(quiet_flags) if run >= m)


def percentile(values, q: float) -> float:
    return float(np.percentile(values, q)) if len(values) else float("nan")


def collect(pipeline, seconds: float, interval: float) -> list[dict]:
    rows = []
    previous_view = None
    previous_cells = None
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        frame = pipeline.process_once()
        if frame is None:
            time.sleep(interval)
            continue
        fraction = diff_fraction(frame.view, previous_view)
        previous_view = frame.view

        cells, off_lattice = [], 0
        for detection in frame.detections:
            cell = cell_for(frame, detection)
            if cell is None:
                off_lattice += 1
            else:
                cells.append(tuple(cell))
        cell_set = frozenset(cells)
        churn = None if previous_cells is None else len(cell_set ^ previous_cells)
        previous_cells = cell_set

        rows.append({
            "t": round(time.monotonic() - started, 3),
            "seq": frame.sequence,
            "stale": frame.stale,
            "calibrated": frame.calibrated,
            "mode": frame.grid_mode,
            "diff_fraction": fraction,
            "detections": len(frame.detections),
            "on_lattice": len(cells),
            "off_lattice": off_lattice,
            "cell_churn": churn,
            "cells": sorted(cell_set),
        })
        time.sleep(interval)
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    lines = ["t,seq,stale,calibrated,mode,diff_fraction,detections,"
             "on_lattice,off_lattice,cell_churn,cells"]
    for row in rows:
        cells = " ".join(f"{col}:{r}" for col, r in row["cells"])
        fraction = "" if row["diff_fraction"] is None else f"{row['diff_fraction']:.6f}"
        churn = "" if row["cell_churn"] is None else row["cell_churn"]
        lines.append(
            f"{row['t']},{row['seq']},{int(row['stale'])},{int(row['calibrated'])},"
            f"{row['mode']},{fraction},{row['detections']},{row['on_lattice']},"
            f"{row['off_lattice']},{churn},{cells}")
    path.write_text("\n".join(lines) + "\n")


def report(rows: list[dict]) -> int:
    print()
    print("=" * 72)
    print("GATE 0 - placement supervision de-risk")
    print("=" * 72)
    if not rows:
        print("NO FRAMES. The camera produced nothing; this measures nothing.")
        return 1

    calibrated = all(row["calibrated"] for row in rows)
    span = max(rows[-1]["t"], 1e-9)
    print(f"frames                {len(rows)} over {rows[-1]['t']:.1f}s "
          f"({len(rows) / span:.1f} Hz)")
    print(f"grid mode             {rows[0]['mode']}")
    print(f"calibrated            {calibrated}"
          + ("" if calibrated else "   <-- cell_at is a GUESS; supervision "
                                   "would report NO MAP and judge nothing"))
    print(f"stale frames          {sum(1 for row in rows if row['stale'])}")

    fractions = [row["diff_fraction"] for row in rows
                 if row["diff_fraction"] is not None]
    print()
    print("--- Q1: does the quiet window ever open? ---------------------------")
    print(f"diff fraction (channel-max >= {PIXEL_THRESHOLD}), n={len(fractions)}")
    for q in (5, 25, 50, 75, 90, 95, 99):
        print(f"  p{q:<3}                {percentile(fractions, q):.5f}")
    if fractions:
        print(f"  max                 {max(fractions):.5f}")

    print()
    print("  quiet frames and settle windows, per candidate threshold:")
    print(f"  {'QUIET_DIFF_FRACTION':<22}{'quiet %':>9}{'longest':>9}"
          + "".join(f"{f'>={m}':>9}" for m in CANDIDATE_SETTLES))
    for candidate in CANDIDATE_FRACTIONS:
        flags = [(row["diff_fraction"] is not None
                  and row["diff_fraction"] <= candidate) for row in rows]
        share = 100.0 * sum(flags) / len(flags)
        runs = quiet_runs(flags)
        longest = max(runs) if runs else 0
        opens = "".join(f"{settle_windows(flags, m):>9}" for m in CANDIDATE_SETTLES)
        print(f"  {candidate:<22.4f}{share:>8.1f}%{longest:>9}{opens}")
    print("  (the >=M columns count RUNS of M consecutive quiet frames, which")
    print("   is what D5 actually asks for: a busy frame restarts the timer.")
    print("   One long still period is one chance to judge, not one per frame.)")

    print()
    print("--- Q2: is detection stable frame to frame? ------------------------")
    counts = [row["detections"] for row in rows]
    print(f"detections            min {min(counts)}  median "
          f"{percentile([float(c) for c in counts], 50):.0f}  max {max(counts)}")
    print(f"count histogram       {dict(sorted(Counter(counts).items()))}")
    print(f"off-lattice (cell_at -> None)  total "
          f"{sum(row['off_lattice'] for row in rows)}, frames with any: "
          f"{sum(1 for row in rows if row['off_lattice'])}")
    sparse = sum(1 for row in rows if row["detections"] < 6)
    print(f"frames under MIN_LATTICE_BLOCKS (6): {sparse}"
          + ("   <-- D10: no FOREIGN, no DISAGREES in these" if sparse else ""))

    print()
    print("--- Q3: do cells assign consistently? ------------------------------")
    churn = [row["cell_churn"] for row in rows if row["cell_churn"] is not None]
    if churn:
        floats = [float(c) for c in churn]
        print(f"cell-set churn        median {percentile(floats, 50):.1f}  "
              f"p90 {percentile(floats, 90):.1f}  max {max(churn)}")
        print(f"frames with churn 0   {sum(1 for c in churn if c == 0)} / {len(churn)}")
    seen = Counter()
    for row in rows:
        seen.update(row["cells"])
    always = {cell for cell, n in seen.items() if n == len(rows)}
    flapping = {cell: n for cell, n in seen.items() if 0 < n < len(rows)}
    print(f"cells seen in EVERY frame ({len(always)}): {sorted(always)}")
    print(f"cells that flap ({len(flapping)}): "
          f"{sorted((cell, n) for cell, n in flapping.items())}")
    print("  (exact cell sets, never counts - a count matches on a board")
    print("   renumbered by one cell, which is the failure that matters)")

    print()
    print("--- the decision ---------------------------------------------------")
    best = None
    for candidate in CANDIDATE_FRACTIONS:
        flags = [(row["diff_fraction"] is not None
                  and row["diff_fraction"] <= candidate) for row in rows]
        if settle_windows(flags, 5) > 0:
            best = candidate
            break
    if best is None:
        print("THE QUIET WINDOW NEVER OPENED at any candidate threshold.")
        print("STOP. Supervision would sit at BUSY forever and silently do")
        print("nothing. Do not pick a looser threshold to make this pass -")
        print("re-plan the interlock instead.")
        return 2
    print(f"a 5-frame settle first becomes reachable at "
          f"QUIET_DIFF_FRACTION = {best}")
    print("Read the table above rather than taking that number on its own:")
    print("pick the loosest threshold whose quiet % is still well under 100,")
    print("or the window is not measuring stillness, it is always true.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--hz", type=float, default=10.0,
                        help="poll rate; the pipeline analyses at 10 Hz")
    parser.add_argument("--backend", default=None,
                        help="camera backend override, e.g. v4l2")
    parser.add_argument("--mode", default=None, help="grid mode; default is config")
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH)
    parser.add_argument("--workspace-map", type=Path, default=WORKSPACE_MAP_PATH)
    parser.add_argument("--csv", type=Path, default=None,
                        help="write the per-frame table here as well as summarising")
    args = parser.parse_args()

    pipeline = ConsolePipeline(camera_backend=args.backend, mode=args.mode,
                               settings_path=args.settings,
                               workspace_map_path=args.workspace_map)
    pipeline.start()
    try:
        rows = collect(pipeline, args.seconds, 1.0 / args.hz)
    finally:
        pipeline.stop()

    if args.csv is not None:
        write_csv(rows, args.csv)
    return report(rows)


if __name__ == "__main__":
    raise SystemExit(main())

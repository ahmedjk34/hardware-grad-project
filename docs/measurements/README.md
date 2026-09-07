# Measurements — numbers taken off the rig, kept as evidence

Files here are **raw instrument output**, not documents. They exist so that a
constant in the code can be traced to the run that produced it, and so that a
future reader can disagree with a conclusion by re-reading the data rather than
by re-running the rig.

**Two of them are also test fixtures. Deleting a file here deletes a
regression.**

## `gate0_*.csv` — placement supervision's Gate 0, 2026-09-07

Written by `python/tools/measure_quiet_window.py`, run on the Pi through
`ConsolePipeline` exactly as the console runs it: same `camera_settings.json`,
same colour correction, same lens map, same analysis worker. No extra detector,
no extra frames. One row per delivered frame.

| file | board | frames | what it is for |
| --- | --- | --- | --- |
| `gate0_parked.csv` | 5 rig-placed blocks, hands off | 524 | the still floor, and the persistent off-board object of F6 |
| `gate0_hand.csv` | the same board, a hand over it | 174 | the disturbed ceiling |
| `gate0_split.csv` | the same board, hands off | 172 | the clean run, and the **only** file with the `gap`/`margin`/`outside` split |
| `gate0_program.csv` | near-empty, a program running | 528 | how often the quiet window opens mid-run |

The analysis, the chosen thresholds and the reasoning are
[features/placement-supervision-progress.md](../features/placement-supervision-progress.md) §1.
`python/tests/test_supervisor_frames.py` replays all four through the shipped
`Supervisor` on every test run.

### Two things to know before trusting them

**Only `gate0_split.csv` carries `in_gap` / `margin` / `outside`.** The other
three predate that instrumentation and log one merged `off_lattice` column —
which is finding F6 as a data fact: the off-board object was gone by the time
the splitting instrument existed, so the run that contains it is the run that
cannot classify it. The replay test states this rather than working around it.

**Any new measurement uses RIG-PLACED blocks.** Finding F4: a hand-scattered
board is not a weaker version of the real thing, it is a different regime — most
blocks sit in the gaps between sites, the detection count flaps across
`MIN_LATTICE_BLOCKS`, and the lattice filter switches on and off frame to frame.
Session 1 read 65% recall that way and 97–99% when the same blocks were placed
by the rig.

## Adding a file here

Say, in the same commit, in the owning document: what the board held, whether it
was rig-placed, which script wrote it, and what question it was answering. A
measurement whose conditions are not written down is an anecdote.

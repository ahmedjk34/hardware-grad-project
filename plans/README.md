# Plans

One plan at a time. A plan is written, reviewed, worked through, then archived.

| Plan | State | What it covers |
| --- | --- | --- |
| [plan-2-click-to-build.md](plan-2-click-to-build.md) | **active** | click a spot on the camera image, the rig places a block there |
| [ack-protocol.md](ack-protocol.md) | **partly built** | machine-readable `@` lines beside the human prose. The safety subset is in `build_test_v1` but has never been flashed; `python/rig/link.py` reads it, with prose matching as a fallback |
| [archive/plan-1-cable.md](archive/plan-1-cable.md) | done | archive the old sketches, one config file, flash from the Pi, talk to the rig from Python |
| [archive/plan-2-research-notes.md](archive/plan-2-research-notes.md) | reference | the long first draft of Plan 2. Superseded, but it holds the detail the short version leaves out — exact firmware output strings, GPIO UART pinout and level-shifting, timing constraints |

Keep the active plan short enough to read in one sitting. If it needs a table of
risks to be understood, it is too big — split it.

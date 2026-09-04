# Evidence-Assisted Printed-Grid Calibration

This is the operator guide for calibrating the camera-to-machine workspace
when the gantry, a cable, or another fixed rig part hides some of the printed
colour-grid cells.

It is a calibration feature of `python/camera/gridded_camera_feed.py`. It does
not move hardware and it writes the same generated
`config/workspace_map.json` as the normal four-click and single-frame printed
sheet routes.

## What it does

The printed sheet remains a real measurement target. A cell is accepted only
when it is a complete, colour-detected printed block that passes the detector's
fullness, lattice, parity and per-frame residual checks. The feature then pools
those physical observations from two or more manually accepted camera frames.

The merged fit draws every coordinate in the selected mode: 7 x 6 vertical or
3 x 10 horizontal. A cell seen physically is solid green. A cell that is
present only in the fitted geometry is amber and dashed. Amber means
**virtual**, not measured.

This is safe for an interior gantry occlusion because the observed outer edges
and corner regions constrain the surrounding grid. It never permits a virtual
outer boundary: the evidence must physically cover every outer edge and all
four corner regions before it can save a map.

## Before starting

1. Tune and save lens, orientation, colour and framing settings first with
   `camera_studio.py` / the lens tools. The printed grid maps the final camera
   view; changing any of those settings afterwards invalidates the map.
2. Put the printed sheet flat in the work area. Its block footprint and gaps
   must match `config/rig.json` — 2.2 x 6.0 cm (vertical) / 6.0 x 2.2 cm
   (horizontal), a uniform 1.6 cm gap on both axes. (The legacy green/magenta
   per-mode sheets carry a 0.8 cm Y gap and are now refused until reprinted;
   the combined A2 target is the primary artefact.)
3. Keep the **camera and paper fixed** throughout the evidence session. The
   gantry may remain in view.
4. Use only normal, safe manual rig positioning if you choose to reveal a
   different part of the sheet. This tool never commands a motor.

## Run it

From the `python/` directory:

```bash
../.venv/bin/python camera/gridded_camera_feed.py --mode horizontal
```

The program opens a Tk Controls dashboard and an OpenCV Preview. Work in the
preview; read the evidence report in the dashboard.

1. Press `p` if the printed-sheet overlay is not already shown.
2. Press `e` to start a fresh **Evidence-Assisted Printed-Grid Calibration**
   session. This clears any old, unsaved evidence; it does not erase an
   existing workspace map.
3. Inspect the preview. Green solid cells are physical evidence already
   accepted. Amber dashed cells are the still-virtual part of the map (7 x 6
   or 3 x 10).
4. When the current gantry position exposes useful cells, press `Space` once.
   The tool either accepts the frame or explains why it was rejected.
5. If needed, move the gantry only through your normal safe controls, wait for
   a fresh live image, and press `Space` again. Two to five distinct positions
   are normally sufficient. Repeated frames with no newly visible sheet area
   only help the consistency check; they do not create physical evidence.
6. Read the `Evidence:` line. Do not press `k` until it ends in
   **READY TO SAVE**.
7. Press `k`. The tool writes `config/workspace_map.json`, reloads it as the
   normal calibrated grid, and exits evidence mode. `x` cancels an evidence
   session without changing the previous saved map.

## Readiness gates

`READY TO SAVE` means all of these were true:

| Gate | Required value | Why |
| --- | --- | --- |
| accepted frames | at least 2 | catches camera/paper motion and avoids saving an accidental single glimpse |
| overlap between later frames | at least 4 previously verified cells | proves a newly revealed region still belongs to the same fixed camera/sheet view |
| physical printed cells | at least 60% (`ceil(0.60·cols·rows)`): 26 of 42 vertical, 18 of 30 horizontal | the fit is supported by most of the selected map |
| corner regions | 4 of 4 | no virtual extrapolation at a workspace corner |
| each outer edge | `ceil(0.50·rows)` on each short edge, `ceil(0.30·cols)` on each long edge | no virtual extrapolation along a workspace boundary |
| merged residual | mean <= 2 px, max <= 6 px | the virtual grid remains tied to the ink |
| repeated-cell spread | <= 3 px | camera and paper did not move between accepted frames |

An interior cell may stay amber/dashed at save time. A missing edge or corner
may not. This is the distinction that lets the workflow handle the gantry
without making an unsafe camera map.

## Common messages

| Dashboard message | Meaning and action |
| --- | --- |
| `evidence frame rejected: ...` | That frame was not added. Clear the cable/scene clutter, improve focus/framing, or accept a different gantry position. |
| `need N more verified cells` | Accept a frame that reveals additional printed blocks. |
| `observe left/right/bottom/top outer edge` | The requested map would extrapolate that edge. Move the sheet/camera or reveal that boundary; do not merely collect duplicate frames. |
| `need N more corner-region anchor` | One of the four map corners is still unseen. Reveal a cell within one grid pitch of that corner. |
| `camera or sheet moved between accepted frames` | Cancel with `x`, restore the same camera/sheet placement, and start again. |
| `evidence is not ready` after `k` | Nothing was saved. Follow the reasons listed on the Evidence line. |

## Which calibration route to use

| Situation | Route |
| --- | --- |
| One clean frame contains a complete unobstructed mode-sized window (7 x 6 vertical; 3 x 10 horizontal) | `p`, then `k`: strict single-frame printed-sheet calibration. |
| Gantry/cable hides interior sheet cells but the outer boundaries can be seen across a few positions | `e`, `Space` for each useful position, wait for READY TO SAVE, then `k`. |
| A workspace boundary cannot be seen at all | Reframe the camera/sheet or use four clicked corners; evidence mode correctly refuses to invent it. |
| Lens/crop/orientation is being changed | Do that first, then calibrate the workspace again. |

## Relation to crop and lens calibration

This feature calibrates the **camera view to the machine workspace**. It is an
excellent way to validate the final crop because the saved map must match the
view the normal feed uses. It is not a replacement for lens calibration:
correct fisheye/lens geometry first, then use this sheet to place the machine
grid and choose a crop that preserves the required workspace.

The saved map includes projection identity. Lens, orientation, framing/crop,
or physical grid changes automatically make it stale; recalibrate rather than
trying to reuse its corners.

## Safety contract

- No partial, clipped or gantry-covered printed block ever becomes a physical
  observation.
- Virtual cells are display/fitting results only; they are not evidence.
- The tool never moves the gantry or sends serial commands.
- `k` writes only after all readiness gates pass. A failed session leaves the
  previous `workspace_map.json` intact.
- The hardware moving `rig_build_v1.py` deliberately retains its existing
  strict single-frame `p`/`k` route. Do calibration in the non-moving gridded
  viewer first, then use the saved map for builds.

## Implementation and tests — built

`vision/color_grid.py` performs sparse whole-cell detection when explicitly
called in evidence mode. `vision/grid_evidence.py`'s `PaperGridEvidence` pools
accepted frames and enforces the readiness gates — its constants
(`MIN_FRAMES=2`, `MIN_CELL_FRACTION=0.60`, `MIN_SHORT_EDGE_FRACTION=0.50`,
`MIN_LONG_EDGE_FRACTION=0.30`, `MIN_FRAME_OVERLAP=4`,
`MAX_MEAN_RESIDUAL_PX=2.0`, `MAX_RESIDUAL_PX=6.0`, `MAX_CELL_SPREAD_PX=3.0`)
match the readiness-gate table above exactly. `camera/gridded_camera_feed.py`
owns the `e`, `Space`, `k`, and `x` operator flow, and reaches this through
`combined_grid.PrintedGridEvidence`, a thin wrapper over
`PaperGridEvidence` — so the combined A2 target (the primary calibration
artefact, see [printed-color-grid.md](printed-color-grid.md)) gets the same
evidence workflow as the legacy sheet this doc was written against.

Run the headless regression suite with:

```bash
cd python
../.venv/bin/python tests/test_color_grid.py
```

It includes a synthetic gantry-shaped occlusion: strict calibration refuses the
frame, while evidence calibration keeps six interior cells virtual and becomes
ready only after two consistent accepted frames, for both grid modes.

**A note on running this script, not on the feature:** the same file has an
unrelated flaky check — an off-thread `PaperGridTracker` poll around line 507
with a 5-second deadline — that can crash the script on a cold/slow run
before it reaches the evidence-gantry checks further down. A warm run, or a
longer poll deadline, shows every check including the evidence ones passing.
Nothing here has been run against a live Pi camera.

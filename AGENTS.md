# AGENTS.md

Rules for anyone — human or agent — editing this repo.

The rig is two machines that have to agree with each other: a Raspberry Pi 5
running Python, and an Arduino MEGA 2560 running compiled C++. **The Arduino
cannot read `config/rig.json`.** It has no filesystem. Its numbers are baked in
at flash time. So a handful of values genuinely exist in two places, and this
file is the list of them.

**If you change one of these, change its partner in the same commit.**

---

## The shared values

### 1. Serial baud — must match exactly or nothing works

| Where | What |
| --- | --- |
| `config/rig.json` → `serial.baud` | what the Pi opens the port at |
| `arduino/build_test_v1/build_test_v1.ino:898` | `Serial.begin(9600)` |
| `arduino/README.md` | states the baud in prose |

A mismatch does not error. You get garbage bytes or silence, which reads like a
dead cable. Change all three together.

### 2. Serial port and board — single source, keep it that way

| Where | What |
| --- | --- |
| `config/rig.json` → `serial.port` | what the Pi opens, **and** what `scripts/flash.sh` uploads to |
| `config/rig.json` → `board.fqbn` / `board.sketch` | what `scripts/flash.sh` compiles |

These are deliberately in one place only. `scripts/flash.sh` reads them, so do
not paste an `arduino-cli` command with a literal `-p /dev/ttyACM0` into a
README or a script — that is how the duplicate comes back.

A genuine Mega enumerates as `/dev/ttyACM0`; a CH340 clone as `/dev/ttyUSB0`.
Switching boards is then a one-line edit to `rig.json`.

### 3. Grid dimensions — the one the firmware forgets

| Where | What |
| --- | --- |
| `config/rig.json` → `grid.cols` / `grid.rows` | **authoritative at runtime** |
| `build_test_v1.ino` SECTION 6C | `GRID_COLS` / `GRID_ROWS` — the compiled default |
| `python/rig/grid.py` | `MachineGrid.from_config()` — what the viewers draw |

The sketch uses no EEPROM, so nothing survives a reset — and opening the USB
port resets the board. Every session therefore starts at the compiled default,
and the Pi pushes `S <cols> <rows>` on connect to overwrite it.

The firmware default should still be kept equal to the config, so that a manual
Arduino Serial Monitor session behaves the same as a Pi-driven one. Editing only
the sketch is the trap: the Pi will silently overwrite it on the next connect.

This applies to AI agents as well as humans: **an agent changing a paired grid
value must edit both the Raspberry Pi JSON/Python side and the live Arduino
sketch in the same change.** Run `python/tests/test_grid.py`; it parses the live
sketch constants and fails if any listed pair differs from `rig.json`.

Current default: **9 positive columns × 5 positive rows = 45 normal cells**.
Including coordinate zero, commands address col `0..9` and row `0..5`: a
**10 × 6 coordinate grid** consisting of 45 normal cells, 9 X-only targets,
5 Y-only targets, and `[0,0]` home.

### 3a. X/Y physical grid geometry — fixed-pitch block cells

| Meaning | Pi / camera side | Firmware side |
| --- | --- | --- |
| physical envelope | `rig.json` → `workspace.width_cm` / `height_cm` | `X_TRAVEL_CM` / `Y_TRAVEL_CM` |
| one block footprint | `rig.json` → `grid.block_width_cm` / `block_length_cm` | `GRID_BLOCK_X_CM` / `GRID_BLOCK_Y_CM` |
| gap before each positive cell | `rig.json` → `grid.gap_x_cm` / `gap_y_cm` | `GRID_GAP_X_CM` / `GRID_GAP_Y_CM` |
| signed complete-grid shift | `rig.json` → `grid.trim_x_cm` / `trim_y_cm` | `GRID_TRIM_X_CM` / `GRID_TRIM_Y_CM` |

`rig.json` → `observed_build_area` is a measurement record only. It has no
firmware partner and never replaces the holder travel cap in `workspace`.

These centimetre measurements are **holder displacements**, not pure object
dimensions: they compare the holder reference at home with that same reference
at the active software cap. The live calibration is:

- X: **24.3 cm holder displacement = 4750 steps**, so `4750 / 24.3 =
  195.4733 steps/cm`;
- Y: **40 cm holder displacement = 8250 steps**, so `8250 / 40 =
  206.25 steps/cm`.

Never hard-code those ratios; firmware derives them from the cap and measured
displacement. A separate physical observation found a **24.3 × 43 cm build
footprint**. It is close to the 43.75 cm Y footprint derived below; it never
changes the 40 cm holder-centre motion cap. Current tool offsets remain zero.

Blocks are **2.2 cm X × 7.5 cm Y × 1.5 cm Z** in the supported unrotated
footprint. `[0,0]` is the feeder-block centre where the claw picks up. Every
positive cell has a **0.5 cm gap** before it. On Y the build grid begins
**3.75 cm** (half a feeder-block length) away from `[0,0]`; this makes the
centre-to-centre distance from the feeder to row 1 exactly `3.75 + 0.5 +
3.75 = 8.0 cm`. There is no additional trailing outer margin inside the grid:

```text
X pitch = 2.2 + 0.5 = 2.7 cm; 9 × 2.7 = 24.3 cm
Y pitch = 7.5 + 0.5 = 8.0 cm; 5 × 8.0 = 40.0 cm

positive-block footprint X = 9 × 2.2 + 8 × 0.5 = 23.8 cm
positive-block footprint Y = 5 × 7.5 + 4 × 0.5 = 39.5 cm
```

The X span starts from home; Y's span starts 3.75 cm from the feeder centre.
First centres are X `0.5 + 2.2/2 = 1.6 cm` and Y `3.75 + 0.5 + 7.5/2 =
8.0 cm`; pitch then repeats to last centres X `23.2` and Y `40.0 cm`.
The last Y block therefore ends at `43.75 cm` from the feeder centre. This is
safe only because the holder needs to reach its **centre** at 40 cm; the held
block itself extends past that holder coordinate.

The firmware owns the step counts and derives both steps/cm ratios at runtime;
never hard-code either ratio and do not copy the `4750 × 8250` safety envelope
into JSON. The Pi does not need motor steps to draw or select a cell: it maps
camera pixel → physical cm → `[col,row]`, and the Arduino alone maps that cell
to safe step targets. The Pi needs the centimetre geometry to interpret camera
scale, while the firmware needs it to turn cell centres into steps, so those
centimetre values genuinely have partners on both machines. Change both
partners in the same commit. Positive trim moves the entire grid away from its
home/feeder reference; negative trim moves it toward that reference. The
shipped Y trim is `+3.75 cm`, the measured feeder-centre-to-build-grid shift;
it is not a holder-to-tool offset.

### 3b. Grid NUMBERING — the convention, not the count

| Where | What |
| --- | --- |
| `build_test_v1.ino` `printGrid()` | draws the map that `9` prints |
| `python/rig/grid.py` | `cell_at()` / `image_cell()` / `ascii_map()` |
| `python/tests/test_grid.py` | holds the two to the same map |

Positive block cells are **1-based**. Col 1 is the X switch side, row 1 is the
Y switch side, and `[1,1]` is drawn above/right of home. The complete map also
draws col 0 and row 0: `[0,0]` is home, `[col,0]` is X-only, and `[0,row]` is
Y-only. Rows increase upward and columns rightward. Cells are written
`[col,row]`, the same order as the arguments to `G` and `B`.

`ascii_map()` reproduces `printGrid()` byte for byte on purpose, so a change to
either can be caught by diffing them rather than by noticing that the claw went
to the wrong place. If you reword that map, run `python/tests/test_grid.py`.

Where the grid sits **on the camera image** is NOT part of this numbering
convention. `gridded_camera_feed.py` derives it from four clicked envelope
corners and saves `workspace_map.json`; `MachineGrid.origin` / `swap_axes`
remain useful only for count-only/legacy drawings without that homography.

### 3c. Tool-centre offsets — holder position is not block position

| Where | What |
| --- | --- |
| `config/rig.json` → `tool_offsets.neutral/cw/ccw` | editable calibration record, in cm |
| `build_test_v1.ino` `TOOL_OFFSET_*_CM` | compiled values used to move the holder |
| `python/tests/test_grid.py` | verifies every JSON/firmware pair |

The X/Y counters describe the gantry holder. Each offset is the signed vector
**from holder reference to actual block-placement centre**, where positive is
away from that axis's home switch. The Arduino subtracts that vector from the
selected grid-cell centre before moving, so the tool — not its holder — reaches
the requested cell. `neutral` is for an unrotated claw; `cw` and `ccw` are for
the eventual `R` and `RR` placement orientations. A `G` command uses the claw's
current orientation; a `B` command uses the requested placement orientation.

All shipped offsets are **zero**, which is an intentional no-op. Enter measured
values in both places in the same commit. Do not compensate this by moving the
camera grid or changing `grid.trim_*`: those define the block grid itself, not
the holder-to-tool geometry. Targets that would put the holder outside its safe
X/Y envelope are refused, never silently clipped.

#### 3d. The printed colour calibration sheet — geometry it must be reprinted for

| Where | What |
| --- | --- |
| `config/rig.json` -> `grid.block_width_cm` / `block_length_cm` / `gap_x_cm` / `gap_y_cm` | what `ColorGridSpec.from_config()` expects to see on the paper |
| the physical printed sheet | 7.5 x 2.2 cm cells with 0.5 cm inner margins |
| `python/vision/color_grid.py` | detects it; refuses a sheet whose measured geometry disagrees |
| `plans/printed-color-grid.md` | the full treatment, including the layout disagreement below |

The sheet is a **physical artefact carrying a copy of the block geometry**, so
it belongs on this list even though nothing can push a number onto paper. If
`grid.block_*_cm` or `grid.gap_*_cm` changes, the sheet is wrong and must be
reprinted; `ColorGridCalibration._check_geometry_matches` refuses rather than
calibrating against stale paper.

`ColorGridSpec.from_config()` reads `grid.cols + 1` and `grid.rows + 1`: the
sheet prints a real block at **every** coordinate, coordinate zero included, so
its layout is the complete 10 x 6 map, not the 9 x 5 positive one.

**The sheet and the firmware do not lay coordinate zero out the same way.** The
sheet puts a whole 2.2 x 7.5 cm block there; the firmware puts a bare point with
only the 0.5 cm gap before cell 1. The printed grid is therefore one block wider
on X and one block taller on Y than the machine's grid, and aligning them is an
explicit decision, not an assumption:

```text
sheet  X = 10 x 2.2 + 9 x 0.5 = 26.5 cm      rig X = 9 x 2.7 = 24.3 cm
sheet  Y =  6 x 7.5 + 5 x 0.5 = 47.5 cm      rig Y = 5 x 8.0 = 40.0 cm
```

`ColorGridCalibration.workspace_corners()` takes a `convention`. The default
`"firmware"` puts the machine origin at the far corner of printed `[0,0]`, which
makes printed `[c,r]` coincide exactly with the firmware's `[c,r]` for all 45
positive cells. `"printed"` takes the paper at face value and lands every
positive cell 1.1 cm (X) and 3.75 cm (Y) further from home. Do not add a third
convention without a row here and a note in the plan.

## 4. Frame span in centimetres

| Where | What |
| --- | --- |
| `config/rig.json` → `frame` | the only copy |
| `grid/undistorted_grid_viewer.py`, `grid/measured_grid_viewer.py` | read it via `rig.config.load()` |

Already centralised. The rule here is: **do not reintroduce a module-level
constant.** Both viewers used to carry their own copy and drifted. This is the
physical span of the complete camera image and is deliberately separate from
the machine envelope in `workspace`.

### 5. The `@` acknowledgement lines

| Where | What |
| --- | --- |
| `build_test_v1.ino` SECTION 7C | emits `@<seq> <KIND> ...` |
| `python/rig/link.py` | parses them — `parse_ack()`, and `_KIND_TO_OUTCOME` |
| `plans/ack-protocol.md` | the kind list, and the reasoning |

`OK`, `ERR`, `SAFE`, `HELD`, `BOOT`, `READY`. **`SAFE` and `HELD` are not
interchangeable**: `SAFE` means nothing moved, `HELD` means the claw may still
be gripping a block at an unknown position. Never collapse them into one
"failed" branch on the Pi.

Adding a kind means updating the firmware, the Pi parser and that document
together. Every ack literal is `F()`, like everything else the sketch prints.

### 6. Firmware command vocabulary

The sketch's commands (`B`, `G`, `S`, `0`, `0+`, `5`, `9`, `Z`, `U`, `D`, `O`,
`C`, `R`, `RR`) are the contract between the two machines.

If you rename a command, change its arguments, or change the text it prints on
success or failure, **grep `python/` for the old form first.** `B` has an `@`
ack and is safe from rewording, but `S`, `G`, `0` and `0+` do not — for those,
`link.py` waits on the prose. The strings it matches are all in one place,
`_prose_outcome()` and the `done=` arguments in `python/rig/link.py`.

### 7. The studio's shipped defaults and the main camera feed

| Where | What |
| --- | --- |
| `python/config/camera_settings.json` | the committed default settings |
| `camera_studio.py` `Studio.__init__` | the built-in defaults `--fresh` and `reset` use |
| `camera/camera_feed.py` | the canonical runtime feed that consumes the saved settings |
| `camera/gridded_camera_feed.py` | the same runtime feed plus machine-grid calibration/overlay |
| `camera/rig_build_v1.py` | camera-grid cell selection plus confirmed serial build |
| `camera/color_grid_check.py` | the printed-sheet detector on its own, live or on a still |
| `rig/build_job.py` | the worker thread that keeps that camera live during a build |
| `camera/undistorted_viewer.py` | the standalone lens-tuning viewer |

`camera_studio.py` is supposed to open showing **exactly what
`camera_feed.py` renders** from the committed settings — same remap table, same
output size, correction on, no zoom or crop. That is three things agreeing, and
nothing enforces it at runtime.

`camera/camera_feed.py` is the main camera script. It must load
`python/config/camera_settings.json` (or an explicitly supplied settings path),
apply its capture and sensor values, then produce the configured camera frame.
Future vision stages build from this feed instead of opening the camera a second
time. The feed owns the first block-detection pass: clean contours, colour-coded
rotated boxes, centres, hover coordinates and saved detection metadata. Later
mapping code should consume those detections. `camera_studio.py` is the editor
that writes the file; it is not the runtime pipeline entry point.

`camera/gridded_camera_feed.py` is an alternate presentation of that canonical
pipeline, not a second interpretation of camera settings. It imports the feed's
settings, correction, enhancement, detection and snapshot helpers. Keep those
shared rather than letting the gridded version drift. Its grid comes only from
`config/rig.json`, and its four clicked envelope corners are saved as the
generated `config/workspace_map.json`. Before calibration it may show only an
explicitly amber **APPROXIMATION ONLY** grid; never display a full-frame guess
as calibrated. A change to lens geometry, orientation, framing, cell geometry
or grid trims must invalidate the saved workspace map.

`camera/rig_build_v1.py` is the first hardware-moving camera UI. Preserve all
of these rules when editing it:

- Both the amber approximate map and a saved calibrated `WorkspaceMap` may
  select a build target. Calibration refines the camera mapping but is optional.
- A click selects and shows the exact `B <col> <row> <level> [R|RR]` command;
  it never moves hardware. `b`/Enter is the separate confirmation.
- Send builds only through `rig.link.Rig.build()`, never a second raw serial
  connection. That call blocks for minutes, so `rig/build_job.py` runs it on one
  worker thread and the camera loop keeps drawing. The UI must refuse every
  controller mutation — select, level, rotation, deselect, calibrate, build,
  quit — while `BuildJob.running`, so clicks still cannot queue while the Mega
  is deaf during motion. Never run two builds at once, and never close the
  serial port with one in flight: join the job first.
- A successful build clears selection so key repeat cannot place twice in one
  cell. A safe rejection may retain it. `ABORTED`, reset, timeout or cable loss
  locks the session: no retry, no automatic home, no further build. A human
  inspects the claw/rig and restarts.
- The UI's `level` is the firmware's block-stack level (the fourth `B` token),
  not raw Z steps or centimetres. Firmware remains authoritative for its range.

The printed-sheet calibration (`p` overlay, `k` calibrate) is a **second route
to the same artefact**, not a second artefact. Both feeds must keep writing the
identical `config/workspace_map.json` through `WorkspaceMap.from_grid`, with the
same projection identity and the same invalidation rules — nothing downstream
of the map is allowed to learn that the sheet exists. `PaperGridTracker`,
`paper_workspace_map` and `draw_paper_grid` live in `gridded_camera_feed.py` and
are imported by `rig_build_v1.py`; keep them shared rather than letting the two
drift, the same way `draw_machine_grid` already is. In `rig_build_v1.py` the
`k` key carries every guard `c` carries: refused during a build (it is in
`forbidden_during_build`), refused on a stale camera, and it clears the current
selection.

`vision/block_detector.py` must not assume one connected colour component is
one block. Touching standard blocks produce L, U, cross, side-by-side and
end-to-end unions. Colour proposes the component; straight edges, internal
seams and the standard four-sided block dimensions decompose it into individual
rectangles. Keep `tests/test_block_detector.py` covering those combinations.

The `lens` block in `camera_settings.json` is consumed by `camera_feed.py` so a
saved studio setup is reproducible. `config/lens_profile.json` remains the
separate generated profile used by the standalone lens/grid viewers, and the
studio's `lens` command keeps those two lens artefacts in sync.

If you change a `LensProfile` default, a `Studio.__init__` default, or the
committed JSON, check the other consumers too. The check is cheap and exact —
build the studio/feed maps for the same input size and compare the tables:

```python
from vision.fisheye import LensProfile, build_maps
import numpy as np
a = build_maps(LensProfile.load(), (1296, 972), "cubic", mip=True)   # the viewer
# ... studio's maps after read_settings + apply_overrides ...
np.array_equal(a.levels[0][0], b.levels[0][0])      # must be True
```

The JSON is not hand-written: regenerate it from `Studio(args, LensProfile())`
and strip `saved_at`, `camera` and `derived`, so it cannot drift from the code
it is meant to mirror.

**The lens trims `k1`, `k2`, `centre_dx`, `centre_dy` default to zero and that
zero is load-bearing.** They are an exact no-op at zero, which is what lets
`fisheye.py` grow them without changing what every existing tool renders. If you
ever give one a non-zero default, the grid viewers' geometry moves with it.

---

## What must NOT be copied into `config/rig.json`

These are physical facts about the machine. Nothing can push them over serial,
so a copy in the JSON would be a lie that nobody notices until the rig crashes
into something.

- firmware-only X/Y software caps (`X = 4750`, `Y = 8250`)
- `Z_TRAVEL_CM`, `Z_TRAVEL_STEPS`, `BLOCK_HEIGHT_CM`, build ceiling
- pin assignments, servo angles, motor direction polarity

The firmware owns all of it. If the Pi needs one of these numbers, it parses the
`5` report — it does not keep its own copy.

**The dividing line:** `rig.json` owns what can change without reflashing. The
firmware owns what cannot.

## `config/lens_profile.json` is not config

It is a *generated artefact*. The viewers write it with their `save` command
(`camera_studio.py` calls the same thing `lens`), and one day a checkerboard
calibration will. Never merge it into `rig.json` — a calibration run would then
be able to silently rewrite your serial port. It is referenced by path, not by
value.

`python/config/camera_settings.json` is the same kind of thing, one layer out:
`camera_studio.py` reads it at startup and its `save` writes it, and it holds
the lens block **plus** the sensor controls, the crop stack and the frame
orientation. Same rules — generated, not hand-authored, referenced by path. It
is not the source of the lens parameters the other tools read;
`lens_profile.json` still is, and the studio's `lens` command copies one into
the other.

`config/workspace_map.json` is also generated. The gridded feed writes it after
four prompted clicks around the complete machine envelope. It contains the
camera projection identity and the physical grid geometry it was made against;
do not hand-edit it or treat normalized corner pixels as portable across lens,
orientation, crop or grid changes.

---

## Environment rules that will bite you

**On the Pi, numpy and OpenCV come from apt. Everything else goes in the venv.**
The venv is built with `--system-site-packages` so it can see the apt
`python3-picamera2` and `python3-opencv`, which are compiled against the system
numpy. Pip-installing `numpy` or `opencv-python` shadows that and breaks
`import picamera2` with an ABI error.

Every other dependency installs into the venv normally, on both machines. The
test for a new package is: **pure Python, no compiled extension, no numpy
dependency?** Then it goes in `requirements.txt`. Otherwise it goes in
`requirements-dev.txt` and the Pi gets it from apt instead.

    pip show <pkg> | grep Requires      # what it drags in
    find .venv/lib/*/site-packages/<pkg> -name "*.so"   # compiled? then no

**The two machines disagree about `python` vs `python3`.** The Pi has `python`;
the x86 desktop has `python3`. This matters in exactly one place — the command
that *creates* the venv. Everywhere else, invoke `.venv/bin/python` or
`.venv/bin/pip`, which exist on both. Never hardcode `python3` in a script that
runs on the Pi: `scripts/flash.sh` detects the interpreter instead, and anything
new should do the same.

**There is no Arduino toolchain on the dev desktop.** `arduino-cli compile` runs
on the Pi and is the only real syntax check. Locally, a `.ino` edit can be
checked with a stub-Arduino g++ harness — that proves it parses, not that it
builds for AVR and definitely not that it behaves.

**A clean compile is not a test.** Anything touching motion, limits or Z has to
be flashed and watched on the physical rig.

**Camera code cannot be verified on the desktop.** The Pi 5's CSI camera is
reachable only through Picamera2. Keep the V4L2 fallback working, and say
plainly which paths are untested when handing work over.

---

## `arduino/archive/` is dead code

Do not flash it, do not fix bugs in it, do not update it to match a change made
in `build_test_v1`. Several archived sketches disagree with the live one about
limit switches and Z travel. `build_test_v1` is the only sketch that matters.

---

## Adding a new shared value

If you add something that has to exist on both sides, **add a row to this file
in the same commit.** A shared value that is not listed here is a shared value
that will drift.

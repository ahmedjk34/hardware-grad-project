# Tool Guide

What every Python file is for, when to reach for it, and how to run it.

Setup instructions are in [README.md](README.md) — do that first. All commands
below assume you are in the `python/` directory with the venv active.

---

## Quick reference

| I want to… | Use |
| --- | --- |
| **Run the configured camera feed for the vision pipeline** | [`camera_feed.py`](#camera_feedpy) |
| **See/calibrate the Arduino block grid on the camera** | [`gridded_camera_feed.py`](#gridded_camera_feedpy) |
| **Select a camera cell and build there** | [`rig_build_v1.py`](#rig_build_v1py) |
| **Check the printed colour calibration sheet is detected** | [`color_grid_check.py`](#color_grid_checkpy) |
| **Fix the camera's colour cast** | [`camera_studio.py` → COLOUR](#colour-correction) |
| **Correct the fisheye with a straightness grid** | [`undistorted_grid_viewer.py`](#undistorted_grid_viewerpy) |
| **Tune every camera setting and save them to JSON** | [`camera_studio.py`](#camera_studiopy) |
| Check the camera is connected and working | [`camera_viewer.py`](#camera_viewerpy) |
| Remove the fisheye distortion / tune the lens model | [`undistorted_viewer.py`](#undistorted_viewerpy) |
| Zoom or crop the preview, or hand-correct residual bowing | [`camera_studio.py`](#camera_studiopy) |

All of them exit on `q` or `Esc`, or when you close the window.

Live tools now open two windows in one process: a small **Tk Controls**
dashboard and a clean **OpenCV Preview**. Tk owns buttons, commands, hover
details, FPS and warnings; OpenCV owns only camera pixels and useful geometry.
This avoids copying every frame through Tk's `PhotoImage` transport. Keys from
either window are merged, and mouse coordinates from a scaled preview are
translated back to corrected-feed pixels.

Use the canonical feed by default. The single-purpose viewers remain useful
when you want to isolate camera capture or lens correction from detection and
machine mapping.

`camera_feed.py` is the main camera script. It reads
`config/camera_settings.json` and is the starting point for future vision
stages. `camera_studio.py` is the settings editor: tune there, `save`, and the
feed consumes the JSON.

`camera_studio.py` is not the runtime pipeline entry point. The standalone
viewers still read `config/lens_profile.json`, which the studio's `lens` command
writes.

---

## `camera_feed.py`

**Use it for:** the normal camera feed and the foundation of the vision
pipeline. It opens the configured source, applies the saved sensor controls and
orientation, renders the saved correction and framing from
`config/camera_settings.json`, and detects the warm rectangular blocks in the
current captures. The default geometry overlay draws clean contours, rotated
boxes and centres. IDs and coordinates live in the Tk dashboard so they cannot
hide the camera feed.

Colour finds candidate material; it does not decide the block count. If several
blocks touch, the detector fits the known standard rectangle to long straight
edges and internal seams, allowing L, U, side-by-side and end-to-end unions to
be separated into their individual four-sided blocks.

```bash
python camera/camera_feed.py
python camera/camera_feed.py --settings ../config/table_cam.json
python camera/camera_feed.py --display-scale 1.5
```

Move the mouse over a block for its corrected-image pixel coordinates, size,
angle and edge confidence. These are image coordinates for now; machine/grid
mapping still waits for camera calibration. Press `s` to save the annotated
frame and a JSON file containing the block geometry. `--color-threshold` and
`--min-area` are the two tuning knobs if a new lighting setup changes the
segmentation. Future workspace mapping and robot-coordinate code should build
from this feed rather than opening the camera independently. Run
`camera_studio.py` first when the camera settings need tuning.

Block analysis runs latest-only at 10 Hz while preview/capture continue at the
camera rate. `o` cycles `off → geometry → detail`; `--overlay` chooses the
startup mode. Software CLAHE/sharpening is off by default; request it explicitly
with `--enhance`. `--analysis-hz` changes the analysis cap and
`--opencv-threads` defaults to two on the Pi.

---

## `gridded_camera_feed.py`

**Use it for:** seeing the real fixed-pitch Arduino grid on the canonical camera
feed and checking which `[col,row]` lies under the cursor. It reads camera
appearance from `python/config/camera_settings.json`, physical geometry from
the repository-level `config/rig.json`, and saves four-corner calibration under
the selected mode in `config/workspace_map.json`.

```bash
python camera/gridded_camera_feed.py
python camera/gridded_camera_feed.py --display-scale 1.5
python camera/gridded_camera_feed.py --mode horizontal
```

It opens with an amber **APPROXIMATION ONLY** grid so you can see the configured
layout immediately (9×5 vertical or 3×15 horizontal). That guess fills the
image and is not evidence that camera and motor cells match. To calibrate:

1. Press `c`.
2. Click the complete 24.3×40 cm holder-centre envelope corners in the prompted order:
   X/Y home, far-X/home-Y, far-X/far-Y, home-X/far-Y.
3. Confirm the Tk dashboard changes to `Grid: CALIBRATED`.
4. Hover cells and verify several displayed `G col row` commands with the rig
   before placing a block.

There is a second, faster route. Print
[`plans/assets/combined-calibration-grid.svg`](../plans/assets/combined-calibration-grid.svg)
at 100% / actual size, never “fit to page”. Lay the combined A2
green/magenta/beige calibration page in the work area with its physical
lower-left page corner at holder home, press `p` to see its 8×10 chromatic
fiducial lattice, and press `k` to derive the same four corners from one
complete frame and save them. The dark colored center thirds encode vertical;
beige/white/beige intervals bracketed by alternating colored rows encode
horizontal. The detector automatically retries
faded or cracked full bars and then their dark centre accents, using separate
per-colour and local-contrast thresholds for uneven lighting, then classifies
all projected thirds with relative channels, HSV and Lab. The woven artwork
contains 80 muted/dark/muted vertical patterns and 80 separate
colour/beige/opposite-colour horizontal bridges. Every physical pattern gets
one class only; a beige bridge is never copied as a second vote onto either
neighboring bar. The active `--mode` selects which family is returned and
drawn: vertical shows only V patterns, horizontal only H patterns. Beige never
detects the sheet by itself; both chromatic end
thirds and the sheet-wide alternating parity must agree. It still refuses a
result unless the lattice geometry, colour parity and requested orientation
layer agree. It
writes the same
`config/workspace_map.json`, separately for the active mode. The older
mode-specific sheets remain supported as a fallback.

The horizontal beige middle is intentionally recoverable. Primary detection
compares it with the nearby white centre lane. If one 1.6 cm middle cannot be
read, other directly measured bridges first establish the five alternating
encoded intervals; only then may its two opposite-colour ends fill the blank.
The overlay marks that result `H~`, never direct `H`.

If the gantry hides interior cells, use **Evidence-Assisted Printed-Grid
Calibration** instead: press `e`, press `Space` once for each useful safe
gantry position, wait for `Evidence: ... READY TO SAVE`, then press `k`. The
collector supports the combined target and both legacy targets, and locks onto
the design used by its first accepted frame. The
preview draws accepted physical cells solid green and inferred-only interior
cells amber/dashed. It refuses to save unless the physical evidence covers all
four corners and outer edges, so it never invents a workspace boundary. `x`
cancels without changing an existing map. The full procedure, quality gates and
camera/crop order are in
[Evidence-Assisted Printed-Grid Calibration](../plans/evidence-assisted-printed-grid-calibration.md).
See [printed-color-grid.md](../plans/printed-color-grid.md), and check strict
single-frame detection first with `color_grid_check.py`.

`x` cancels calibration without destroying the previous saved map, `g` toggles
the grid, `o` cycles block/geometry overlay detail, and `s` saves the annotated
frame and detection JSON. Changing the
lens geometry, orientation, crop, physical workspace, block size, gap or signed trim
invalidates the old map and returns to the amber approximation.

The camera image contains only the camera, grid, and block visualization;
calibration state, cell details, FPS, and controls are in the separate Tk dashboard.

The JSON deliberately does not duplicate the firmware's motor step limits.
The live caps are `4750` X and `8250` Y steps; paired with the measured holder
displacements, firmware derives `4750 / 24.3 = 195.4733` X steps/cm and
`8250 / 40 = 206.25` Y steps/cm. The separately observed build displacement
is 43 cm on Y. The current feeder-centre Y shift makes the calculated physical
block footprint 43.75 cm high while holder centres remain limited to 40 cm.
The Pi maps pixels through centimetres
to a logical cell; Arduino alone converts the selected centre to step pulses.

The numbers below are the **vertical** grid's. The horizontal grid swaps which
block extent lies along which axis and repacks to `3 × 15`; see AGENTS.md §3a
for both tables. A calibration belongs to one mode and never transfers.

Grid pitch is not block size. X pitch is `2.2 + 0.5 = 2.7 cm`; Y pitch is
`7.5 + 0.5 = 8 cm`. `[0,0]` is the feeder-block centre. The X/Y grid shifts
are half a feeder block: `1.1 cm` X and `3.75 cm` Y. Column centres are
`2.7..24.3 cm`; row centres are `8, 16, 24, 32, 40 cm` from the feeder centre.
Positive block footprints occupy `23.8 × 39.5 cm`; their shifted envelope runs
from `1.6..25.4 cm` X and `4.25..43.75 cm` Y. Holder caps limit placement
centres, not the far edge of a held block.

---

## `rig_build_v1.py`

**Use it for:** manually selecting one camera-grid cell and commanding one
complete Arduino build there.

```bash
python camera/rig_build_v1.py
python camera/rig_build_v1.py --level 0
python camera/rig_build_v1.py --level 2 --mode horizontal
```

Startup opens the configured serial port, waits for the Mega reboot banner,
latches the grid mode and then pushes that mode's grid count — in that order,
because the Mega validates the count against whichever grid is active. A reset
returns the board to the vertical grid without saying so, which is why the mode
is pushed on every connect rather than assumed. An unexpected reset locks the
build UI; recovery needs inspection and an explicit `recover_after_reset(home=True)`,
which homes before re-pushing mode then size. It then opens the same corrected/detected camera
pipeline as `camera_feed.py`. The amber approximate grid is selectable and can
issue a build immediately. A matching `workspace_map.json` refines the mapping
when present, but it is not required. The camera image contains only the camera,
grid, detections, and selected-cell outline; build, camera, calibration, and
command feedback live in the separate Tk dashboard.

Workflow:

1. Left-click a cell on the approximate or calibrated grid.
2. The magenta outline and Tk status panel show the selection. Press `c` only if
   you want to refine the mapping with four envelope corners, or `k` to refine
   it from the printed calibration sheet (`p` shows what the sheet detector
   sees). Both are refused during a build and both clear the selection.
3. Set the stack level with `[` / `]`. `o` latches the other grid — vertical
   ⇄ horizontal. That is not a per-block rotation: it changes what every
   coordinate means, so it drops the selection, and the camera map has to be
   recalibrated for the mode you switch into.
4. Read the displayed command, such as `B 3 4 0`.
5. Press `b` or Enter to confirm and send it.

The firmware build runs on a worker thread and camera capture runs on a second
worker thread, so a serial wait or stalled CSI capture cannot freeze the UI.
The panel reads **BUILDING — SERIAL INPUT LOCKED** for the duration: clicks,
`[`/`]`, `o`, `d`, `c`, a second `b` and even `q` are all refused, so nothing
can queue while the Mega is deaf. `i` cycles overlay detail; `g` (toggle grid)
and `s` (snapshot) still
work, since neither touches the rig. If no new camera frame arrives for 0.75 s,
the Tk dashboard reports **STALE** with its age; inspect camera power/CSI
wiring after the build rather than trusting the frozen image. Selection,
calibration and build confirmation are refused until live frames resume.
Closing either window mid-build is refused and a closed preview is recreated;
after the build reports, normal shutdown joins the worker before the serial
port is closed. `placed`
clears the selection and requires a fresh click. A safe `rejected` result keeps
the selection for correction. `aborted`, reset, timeout or cable loss locks the
session—inspect the rig and restart; do not retry or auto-home.

Here “level” is the firmware's Z block-stack level: `0` ground, `1` one block
high, and so on. It is not a raw Z step count.

---

## Camera performance checks

Use the read-only diagnostic before blaming camera code or changing packages:

```bash
python camera/camera_perf_check.py
python camera/camera_perf_check.py --probe-camera
```

It reports configured and corrected sizes, actual backend when probed, Python /
OpenCV / NumPy locations, OpenCV thread count, display session, Pi temperature,
ARM clock and `get_throttled`. On the Pi, OpenCV, NumPy and Picamera2 must remain
the apt builds visible through the system-site-packages venv—do not install
`opencv-python` or NumPy with pip there.

The camera-free regression benchmark uses the committed captures:

```bash
python camera/benchmark_camera_pipeline.py
python camera/benchmark_camera_pipeline.py --iterations 100 --json
```

It records detector/enhancement median and p95 time, normalized processing
size, contour/compound counts, Python allocation/peak-memory counts, and the
rectangle-hypothesis budget. Run the live
acceptance check for five minutes on local HDMI: preview should normally remain
24–30 FPS, analysis at least 8 Hz with results under 300 ms old, and the Pi must
report no undervoltage or thermal throttling. VNC and `ssh -X` add display-copy
latency and are useful for control, not for validating camera FPS.

---

## `color_grid_check.py`

**Use it for:** proving the printed colour calibration sheet is being detected
correctly, before trusting a calibration made from it. It does nothing else —
it never writes `config/workspace_map.json`.

```bash
python camera/color_grid_check.py                       # live camera
python camera/color_grid_check.py --image captures/grid_training/original_image_VERTICAL.jpeg --mode vertical
python camera/color_grid_check.py --mode horizontal
python camera/color_grid_check.py --image IN.jpeg --save OUT.png
```

The current target is one A2 landscape page for both modes. Its detector uses
an 8×10 lattice of 6.0 × 2.2 cm chromatic bars, with 0.8 cm X gaps and 1.6 cm
Y gaps. These are **fiducials**, not block dimensions. Their fitted page plane
is converted to the 24.3 × 40.0 cm holder envelope, then the active
`MachineGrid` supplies either the 9×5 vertical cells or 3×15 horizontal cells.
Labels beginning with `F` are fiducial coordinates, never firmware `B`/`G`
coordinates. The page's physical lower-left corner must be aligned with holder
home, and the combined route requires `--home-convention firmware`.

The legacy vertical sheet is 2.2 × 7.5 cm and the legacy horizontal sheet
7.5 × 2.2 cm, both with 0.5 cm inner margins. For those sheets the tool still
picks a complete 10×6 or 4×16 whole-cell window as before.

Every mapped cell is tinted and stamped with its `col,row`; whole cells outside
the chosen window are outlined dull yellow, and cells clipped by the paper edge
or the frame edge red. The blue quadrilateral is the holder envelope a
calibration would save. Watch the tint against the ink: a residual number tells
you how good the fit is on average, not *where* it went wrong.

`l` toggles labels, `r` the rejected outlines, `t` cycles the tint, `w` the
envelope, `h` switches the home convention, `s` saves the annotated frame.

**A refusal still draws something.** Blobs that joined a lattice are outlined
green, the rest red, with the count and the failing stage in the corner — so
"the sheet is out of shot", "the colours are wrong" and "the code never ran"
never look the same. Many red blobs on the walls under a colour cast is normal;
the lattice discards them.

Frames are white balanced before segmentation, which is load-bearing rather
than cosmetic: an uncorrected magenta cast from the rig's camera moved the
green ink to hue 120 and made every green cell invisible. If the whole preview
looks strongly tinted, fix the camera's white balance in `camera_studio.py`
too — `block_detector.py` keys on red-minus-blue and is degraded by the same
cast.

The status line reports the whole-cell count, the lattice size found, the mean
residual in pixels and the colour-parity agreement. Parity below 100 % means
the lattice indices are inconsistent — distrust the fit even if the residual
looks fine. Refusals are sentences you can act on, such as
`found a 22x5 block of whole cells, which cannot hold the 10x6 grid`.

Full detail, including the one place the sheet's layout disagrees with the
firmware's, is in
[plans/printed-color-grid.md](../plans/printed-color-grid.md).

---

## `undistorted_grid_viewer.py`

**Use it for:** a corrected preview with a clean 8×8 straightness reference.
It is the grid-flavoured companion to `undistorted_viewer.py`; machine-cell
calibration and selection belong to `gridded_camera_feed.py` and
`rig_build_v1.py`.

> Every `python ...` line below assumes the venv is **activated**
> (`source .venv/bin/activate`). Inside a venv `python` always exists, on
> both machines. Without activating, use `.venv/bin/python` instead — the Pi
> and the desktop disagree about whether a bare `python3` exists.

```bash
python grid/undistorted_grid_viewer.py
python grid/undistorted_grid_viewer.py --hq                       # sharpest
python grid/undistorted_grid_viewer.py --display-scale 1.5
```

### Keys

| Key | Effect |
| --- | --- |
| `u` | toggle correction |
| `b` | toggle raw/corrected side-by-side view |
| `g` | toggle the 8×8 straightness grid |
| `[` `]` | lens FOV ∓2° — **the main correction-strength knob** |
| `-` `=` | output FOV ∓5° |
| `,` `.` | output scale ∓0.1 |
| `m` / `i` | cycle projection model / interpolation kernel |
| `s` / `w` / `r` | snapshot / write profile / reset |
| `q`, `Esc` | quit |

Like the other live tools, it uses one latest-frame capture thread, shows only
image/grid geometry in OpenCV, and puts profile, sampling, FPS, warnings, and
controls in Tk. `--opencv-threads` defaults to two.

---

## `camera_studio.py`

**The tuning bench.** Everything that decides what the picture looks like — the
fisheye correction, the sensor's own controls, zoom, crop, flip — adjustable
live, with a separate Tk control dashboard and one `save` that writes the whole
state to JSON.

```bash
python camera/camera_studio.py
python camera/camera_studio.py --hq                  # sharpest: full sensor in
python camera/camera_studio.py --settings ../config/table_cam.json --autosave
python camera/camera_studio.py --fresh               # ignore the settings file
```

Reach for this when you are *deciding* what the camera settings should be.
Reach for `camera_feed.py` when you are using the saved result in the pipeline,
or `gridded_camera_feed.py` when you are working with the machine grid.

### It starts where you left off

The tool **reads `config/camera_settings.json` at startup** and `save` writes it
back, so a session resumes rather than restarting. A normal launch renders that
saved file exactly as `camera_feed.py` does, including its crop stack and natural
corrected output size. `--fresh` and `reset` return to the uncropped built-in
defaults shared with `undistorted_viewer.py`.

Four layers, each overriding the one before:

| | Source |
| --- | --- |
| 1 | the built-in defaults in `Studio.__init__` and `LensProfile` |
| 2 | `config/lens_profile.json` — the lens parameters the *other* tools read |
| 3 | `config/camera_settings.json`, or whatever `--settings` names |
| 4 | the command-line flags |

`--fresh` skips layer 3. This is why the framing and interpolation flags have no
argparse default: a default is indistinguishable from an explicit value, so it
would silently outrank the settings file.

### The windows

Camera Studio uses a resizable Tk control centre plus a separate clean OpenCV
preview. The preview never passes through Tk/Tcl, while the control centre keeps
real entries, dropdowns, buttons, status labels, logs and the command entry.
Field and button groups wrap when the dashboard narrows.

The correction always opens at the canonical Camera Feed size derived from the
saved lens and ROI—currently 384×440—not at the desktop window size.
`--window WxH` and `--display-scale` are display-only. Only explicit processing
commands such as `viewbox` and `refit` change rendered resolution. `fill`
returns to the canonical feed's natural corrected size.

There are deliberately no OpenCV trackbars. The exact value remains visible in
a real text entry, and a fixed-choice parameter is a real dropdown.

### The fields

The panel is generated from the same 32-field table the command layer uses; no
widget is hand-written. That table supplies each label, command name, displayed
value, step size and fixed choices.

**20 entries** hold continuous or multi-number values (`fov`, `k1`, `scale`,
`zoom`, `crop`, exposure, gain…).

| Key | Effect |
| --- | --- |
| **Enter** | run the field's command with the text in the entry |
| **Up / Down** | run the same command with its positive or negative step |
| **Esc**, or leave the entry | discard unfinished text and restore the real value |

Entries accept the same values as typed commands, including relative `+2` /
`-2` forms and `auto`. Stepping a sensor field away from `auto` starts at a
useful value; stepping past a limit clamps with a note instead of failing.

**12 read-only dropdowns** hold fixed choices: `ref`, `model`, `correction`,
`interp`, `mip`, `show`, `grid`, `sizing`, `flip`, `rotate`, `awb` and
`denoise`. A selection runs its command immediately, so you can choose a
projection or interpolation mode by watching the picture.

Every field action is a command string sent through the same command engine as
terminal input, shortcuts and buttons. That is the contract that keeps all
input paths from drifting.

The derived line and `camera:` line are read-only status labels. Beneath them,
four coloured log labels show recent success and error messages.

| Button | Same as typing |
| --- | --- |
| SAVE JSON | `save` |
| SNAP PNG | `snap` |
| ZOOM + / ZOOM − | `zoom +0.25` / `zoom -0.25` |
| CROP | `crop` |
| UNDO CROP | `uncrop` |
| NO CROP | `nocrop` |
| REFIT | `refit` |
| RAW/CORR | cycles `view corrected`, `view raw`, `view both` |
| GRID | `grid` |
| RESET | `reset` |
| HELP | `help` |
| QUIT | `quit` |

### Driving it — four input channels

1. **Terminal.** Type a command in the shell that launched the studio. The
   stdin reader still works without window focus.
2. **Command entry.** Type any command in the entry at the very bottom and
   press Enter. Pressing `:` while no field has focus jumps there.
3. **Fields and buttons.** Entries, dropdowns and buttons all execute command
   strings through the same dispatcher.
4. **Crop drag.** Drag on the OpenCV preview. The area outside the selection
   dims; right-click cancels. Display scaling is undone before the
   crop is converted to the rendered image's coordinates.

Single-key shortcuts are bound to the Tk window. They are deliberately ignored
while an Entry or Combobox has focus, so typing `158` edits only that field.
A terminal command still updates all unfocused widgets on the next frame; a
focused entry is left alone until you commit or leave it.

`?` and the HELP button open a separate help window. The command entry replaces
the former in-image `:` prompt.

### Fixing the fisheye

Point the camera at a long straight edge, put it near the frame **edge** (the
centre is nearly straight whatever you do), and press `g` for a ruler to judge
against. Then, in this order:

| Step | Knob | What it does that the others cannot |
| --- | --- | --- |
| 1 | `fov` (`[` `]`) | Scales every radius at once. By far the biggest effect — nothing else is worth touching until this is close. Bowing **outward** → `]`. Bowing **inward**, over-corrected → `[`. |
| 2 | `model` (`m`) | Four ideal projection curves. Cheap to try, so try all four. |
| 3 | `k1` / `k2` (`1`–`4`) | The residual. Straight in the middle of the frame but still bending in the last fifth is exactly what these fix: they are zero on the optical axis and grow toward the edge, which is the shape `fov` cannot make. |
| 4 | `cx` / `cy` (`5`–`8`) | Only for **asymmetric** bowing — straight along the left edge, curved along the right. That is the sensor sitting off-centre behind the lens, and no amount of `k1` will fix it. |

`straight` prints this list into the window.

`k1`, `k2`, `centre_dx` and `centre_dy` are new fields on `LensProfile`; they
default to zero, which is an exact no-op, so a profile that has never been near
this tool behaves precisely as it did.

### Zoom and crop are not what they usually are

They are folded into the correction's lookup table rather than applied to the
finished image, so a 2× zoom **re-renders that part of the field straight from
the sensor frame** instead of enlarging pixels that were already interpolated
once. The `SAMPLE` line reports the real cost: at zoom 2 you should see `centre`
roughly halve, and if it drops well below 1.00 the answer is `--hq`, not a
sharper interpolation kernel.

Crops **compose** and are kept as a stack, so `uncrop` (or Backspace, or the
UNDO CROP button) restores the previous framing rather than resetting to the
whole frame. `nocrop` drops all of them.

Zoom is deliberately *not* part of that stack. A crop is a decision you are
recording in the JSON; zoom is how you are looking at it right now, and you want
to be able to zoom back out without losing the crop. `c` promotes the current
zoom rectangle into a real crop once you decide you meant it.

Two ways of sizing the result, toggled with `v`:

- **`fit`** (default) — the ROI is scaled to fill the view box, so the window
  keeps its size however far you zoom. `scale` then becomes a pure quality knob:
  it changes how much source detail feeds the correction, not how big the
  window is.
- **`native`** — the ROI renders at its natural size, so zoom and crop never
  interpolate anything, at the cost of the window resizing under you.

`refit` gets the best of both: it resizes the view box to the crop's own size,
so the crop renders exactly 1:1 and *stays* there as you keep working. `fill`
undoes it, putting the view box back to the canonical Camera Feed output.

### Sensor controls

Twelve of them, one command each, all live: `brightness`, `contrast`,
`saturation`, `sharpness`, `ev`, `exposure`, `gain`, `awb`, `redgain`,
`bluegain`, `denoise`, `fps`. Every one also takes `auto` to hand it back to the
camera's own loop, which is different from — and better than — pinning it to
whatever value that loop had settled on. `autoall` does the lot; `sensor` prints
every value and what the camera did with it.

The couplings live in `vision/camera_source.py` and are handled once:
`exposure` or `gain` implies `AeEnable False`, `redgain`/`bluegain` implies
`AwbEnable False`.

**Ranges are the Picamera2 ones.** libcamera normalises these controls to
documented units; a UVC webcam does not — a V4L2 driver reports whatever integer
range it likes (0–255 and −64–64 are both common) and the same number means
something different on each. On the V4L2 backend, treat them as raw driver units
and tune by eye. Controls a driver does not implement are reported as
unavailable rather than silently swallowed, because a UVC driver's usual answer
to a control it lacks is to return success and change nothing.

### Keys

```
:  focus command box   ?  help window     q / Esc  quit
u  view: corrected / raw / both           n  correction on / off
[ ]  lens FOV -/+ 2 deg                   m  cycle projection model
- =  output FOV -/+ 5 deg                 i  cycle interpolation kernel
, .  output scale -/+ 0.1                 g  grid overlay
1 2  k1 -/+ 0.01                          3 4  k2 -/+ 0.01
5 6  optical centre X -/+ 2 px            7 8  optical centre Y -/+ 2 px
z x  zoom out / in                        arrows  pan
0  reset zoom and pan                     c  crop to the current zoom rect
Backspace  undo the last crop             f  refit (render the crop 1:1)
v  fit / native sizing                    r  reset everything
s  save the JSON                          p  snapshot PNGs
```

Unrecognised printable keys are reported in the log. Arrow keys pan when the
video or a button has focus and step an Entry when that Entry has focus;
Comboboxes consume their own navigation keys. `reset` (`r`)
goes back to the built-in defaults plus your command-line flags — it does *not*
re-read the settings file, because `reset` is what you press when the tuning has
gone somewhere strange and you want the known starting point back. `load` is the
one that re-reads.

### The JSON

`save` writes `config/camera_settings.json` (or `--settings <path>`), and
`--autosave` marks changes dirty and writes the newest state after a 500 ms
debounce. It is also read back automatically at startup; `load` re-reads it
mid-session.

```
capture     backend, device, resolution, swap_rb, flip, rotate
lens        the full LensProfile — fov, model, k1, k2, centre offsets, output
correction  enabled, interpolation kernel, mip filtering
framing     the crop stack, zoom, pan, fit mode, view box
sensor      all twelve controls, each a number or "auto"
colour      the software colour correction: matrix, gamma, saturation, source
derived     roi, output size, focal length, output camera matrix, sampling stats
```

`derived` is **output, not input** — it exists so that whatever reads the file
next does not have to redo the geometry to find where the crop landed or how
much detail survived. `load` ignores it.

Loading is deliberately tolerant: every section is optional and unknown keys are
ignored, so a file trimmed down to just the `lens` block still loads. The one
thing it will not do is change the capture resolution, since that means
reconfiguring the sensor — it tells you to relaunch with `--width`/`--height`
instead.

`lens` (the command) writes the lens half to `config/lens_profile.json` as well,
which is what the *other* tools read.

### Colour correction

The rig's camera has a magenta cast strong enough to turn the printed sheet's
green ink cyan — which makes half of it invisible to the grid detector and
degrades block detection, since that keys on red-minus-blue. The **COLOUR**
section of the panel fixes it once. The result is saved in
`python/config/camera_settings.json` and applied by `camera_feed.py`,
`gridded_camera_feed.py`, `rig_build_v1.py` and `color_grid_check.py`, so every
tool sees the same pixels.

Put the printed calibration sheet in shot, then either:

1. **WHITE BAL** (`wb`) — one press. Neutralises the cast against the sheet's
   own white paper. No reference photograph needed. Start here.
2. **COLOUR CAL** (`colourcal <image>`) — match the camera to a photo of the
   *same sheet* taken with something you trust, usually a phone. Both images are
   reduced to three measured colours (green ink, magenta ink, white paper) and
   the transform between them is solved. The two shots do not need to be framed
   alike or show the same part of the sheet: green is green in both.

`colourmode` picks what a calibration fits:

| mode | fits | when |
| --- | --- | --- |
| `gain` *(default)* | one gain per channel, through the origin | almost always |
| `affine` | gain plus offset per channel | when brightness is off too — but the sheet is all mid-to-bright, so the line down to black is extrapolated |
| `matrix` | full linear 3×3 | when the diagonal visibly cannot get there |

**Read the warnings, not the residual.** Measured on a real rig frame:

| mode | residual | warnings | how it actually looked |
| --- | --- | --- | --- |
| `gain` | 19.7 | 0 | correct |
| `affine` | 4.1 | 1 | sheet right, brick wall turned olive |
| `matrix` | **0.00** | 3 | sheet right, wall turned bright pink |

The residual only measures the three colours the fit was given, so the richer
fits drive it to zero by contorting themselves everywhere else. `colourinfo`
prints the matrix and everything implausible about it; `nomix` walks a matrix
fit back to its white balance.

Every fit also reports the **`redgain`/`bluegain` that would do the same job in
the SENSOR section**. Prefer those where the backend has them — they act before
the camera throws away headroom in the channel it under-exposed. The software
correction is the fallback, and what the V4L2 path usually has to use.

The COLOUR fields are full manual control over whatever a fit produced: per
channel gain and offset, `gamma`, and `csat` (a software saturation, separate
from the sensor's own). `colourreset` returns to a disabled identity, and so
does the global `reset`.


---

## `camera_viewer.py`

**Use it for:** confirming the camera is alive. Raw feed, zero processing — the
first thing to run after touching wiring, and the tool to use when adjusting
focus, exposure or physical framing.

```bash
python camera/camera_viewer.py                    # auto-detect the camera
python camera/camera_viewer.py --backend v4l2     # force the /dev/video* picker
python camera/camera_viewer.py --device /dev/video0
python camera/camera_viewer.py --width 640 --height 480
```

With `--backend v4l2` and no `--device`, it lists every capture device it finds
and prompts you to pick one by number.

**What you should see:** a heavily barrel-distorted image. Straight table edges
will bow outward, strongly near the frame edges. That is correct and expected —
it is what `undistorted_viewer.py` fixes.

---

## `undistorted_viewer.py`

**Use it for:** a standalone corrected live preview and for tuning the lens
model by eye. The config-driven `camera_feed.py` is the main runtime camera
tool.

```bash
python camera/undistorted_viewer.py                                   # defaults
python camera/undistorted_viewer.py --hq                              # sharpest
python camera/undistorted_viewer.py --output-fov 140 --output-scale 1.5
python camera/undistorted_viewer.py --backend v4l2 --device /dev/video0
```

The corrected image is kept clear. Profile state, FPS, sampling information,
and tuning commands are shown in the separate Tk controls dashboard.

### Keys

| Key | Effect |
| --- | --- |
| `q` / `Esc` | quit |
| `u` | toggle correction on/off |
| `b` | raw \| corrected side by side |
| `g` | grid overlay — the straightness ruler |
| `[` `]` | lens FOV ∓2° — **the main correction-strength knob** |
| `-` `=` | output FOV ∓5° |
| `m` | cycle projection model |
| `,` `.` | output scale ∓0.1 |
| `i` | cycle interpolation kernel |
| `s` | save raw + corrected snapshot to `captures/` |
| `w` | write current parameters to `config/lens_profile.json` |
| `r` | reset to defaults |

### How to tune it

1. Put something with a long straight edge in view — a table edge, a ruler, a
   sheet of paper. Get it near the edge of the frame, where distortion is
   strongest and errors are easiest to see.
2. Press `g` for the grid overlay and line the real edge up against a grid line.
3. Now judge the residual bow:
   - bows **outward** → still under-corrected → press `]`
   - bows **inward** → over-corrected → press `[`
4. Once the bow is as small as you can get it, try `m` to cycle the projection
   model. This is a second-order refinement — get step 3 right first, because
   the FOV number matters far more than the curve shape.
5. Press `w` to save. Press `s` at any point to keep a before/after image pair.

`b` (side by side) is the fastest way to confirm you have actually improved
something rather than just changed it.

### The status panel

```
PROFILE: ESTIMATED (uncalibrated)          ← shown in the Tk panel
lens FOV 160deg (diagonal)  model equidistant
output FOV 120deg  1296x972  scale 1.00
in 1296x972   28.4 fps  cubic  view CORRECTED
SAMPLE src px/out px: centre 1.24  edge 0.34  (83% magnified)
```

The last line is the sharpness budget — see
[Why the corrected image looks soft](#why-the-corrected-image-looks-soft).

### Options

| Flag | Default | What it does |
| --- | --- | --- |
| `--lens-fov` | 160 | Quoted lens FOV. The dominant parameter. |
| `--fov-reference` | diagonal | Whether that number is the diagonal or horizontal FOV. Vendor specs are ambiguous; try both. |
| `--model` | equidistant | Projection curve: `equidistant`, `equisolid`, `stereographic`, `orthographic`. |
| `--output-fov` | 120 | How much of the 160° cone to render. |
| `--output-scale` | 1.0 | Output size relative to input. |
| `--display-scale` | 1.0 | Scales the window only — processing is unaffected. |
| `--profile` | `config/lens_profile.json` | Which profile to load and save. |
| `--swap-rb` | off | Fix inverted red/blue channels. |
| `--hq` | off | Capture the full 2592×1944 sensor readout, render a half-size output. Same field of view, ~2× the real detail at the edges, ~15 fps. |
| `--interp` | cubic | Resampling kernel: `linear`, `cubic`, `lanczos4`. |
| `--no-mip` | off | Skip pyramid filtering of the shrunk regions. Faster; aliases. |
| `--sharpness` | ISP default | ISP sharpening amount; `0` disables it. |
| `--denoise` | ISP default | `off`, `fast`, `hq`. |
| `--shutter` | auto | Fixed exposure time in µs. |
| `--gain` | auto | Fixed analogue gain. |
| `--awb` | auto | White balance preset. |
| `--list-modes` | — | Print the sensor's modes and exit. |

The last six are Picamera2-only and are ignored (with a note) on V4L2.

### Why the corrected image looks soft

Undistortion never resamples 1:1. `tan(θ)` grows much faster than `θ`, so the
edges of the output are stretched far harder than the centre. At the default
160° lens / 120° output / scale 1.0 the numbers are:

| | source px per output px | meaning |
| --- | --- | --- |
| centre | 1.24 | slightly supersampled — fine |
| edge | 0.34 | each output pixel interpolated from a third of a source pixel |

That 0.34 is ~3× empty magnification. No interpolation kernel recovers detail
that was never captured, so the corners will look soft no matter what. The Tk
status panel's `SAMPLE` line reports both numbers live, so the cost of a parameter change is
visible while making it.

**The one fix that adds real detail is `--hq`.** The default capture mode,
1296×972, is the OV5647's 2×2-binned readout — half the linear resolution the
sensor can produce. `--hq` captures the full 2592×1944 instead and renders the
same 1296×972 output from it, which takes `edge` from 0.34 to 0.69. Same field
of view, twice the detail where it is most needed. The cost is frame rate: the
sensor caps at about 15 fps at full resolution.

Everything else redistributes sharpness rather than adding it:

- `--output-scale` / `--output-fov` set how hard the stretch is. Lowering the
  scale gives a smaller but crisper image.
- `--interp cubic` (now the default, was linear) resolves an upscale visibly
  better; `lanczos4` is a smaller step again.

Once the capture resolution exceeds the output resolution, parts of the frame
are being *shrunk* rather than stretched, and point sampling there aliases —
shimmering on fine texture, moiré on checkerboards, which matters directly for
the calibration step. `build_maps` detects this and builds mip levels for the
affected regions automatically; `--no-mip` turns it off if you need the frame
rate back.

### If the raw frame is already soft

Press `u` and look at the uncorrected image. If that is soft too, none of the
above applies — the detail is missing before the correction runs. In order of
likelihood:

1. **Lens focus.** These M12 fisheye modules are manual focus and frequently
   ship focused nowhere useful. Loosen the lock ring and turn the lens while
   watching the preview.
2. **Light.** In a dim room the auto exposure picks a long shutter *and* high
   gain; the result is motion blur plus sensor noise, which the ISP's denoise
   then smears into mush. Add light, or pin the exposure: `--shutter 8000
   --gain 1.5`.
3. **ISP denoise.** `--denoise hq` keeps far more fine texture than the video
   default (`fast`) does.
4. **Colour cast** rather than softness — try `--awb tungsten` (or another
   preset), and `--swap-rb` if red and blue look exchanged.

### Why the output FOV defaults to 120°, not 160°

Rectilinear projection stretches by 1/cos, so rendering the full 160° would
smear the corners enormously and shrink the centre to about 25% scale. At 120°
the centre sits at 0.81× and the corners stay usable.

This is a *projection extent* choice, not a crop to the workspace — nothing is
being trimmed to make the picture look tidy. To keep more field:

```bash
python camera/undistorted_viewer.py --output-fov 150 --output-scale 1.5
```

`--output-scale` matters here: without it, a wider output FOV is bought by
shrinking the centre. At scale 1.5 the output is 1944×1458 and the centre stays
near 1:1.

**Worth knowing:** at 50 cm height your 60×30 cm workspace spans only ±34°, so
it sits well inside the central cone. The 120° default already covers about
139 cm of ground across the frame width. The stretched, low-quality outer ring
is nowhere near where the blocks are.

### Black corners are expected

Rays outside the lens' real 160° cone have no source pixel, so they are filled
black rather than smeared. This is deliberate.

---

## The `vision/` library

Not runnable — imported by the tools above.

### `vision/camera_source.py`

One frame source for both machines. `open_camera()` returns something with
`.read()`, `.release()`, `.size` and `.name`, so callers never branch on backend.

- **`Picamera2Source`** — the Pi CSI path. Pins the sensor readout to a
  full-sensor mode via `pick_full_fov_mode()`, because the OV5647's 1080p mode
  is a centre crop that would silently narrow the field of view *and* invalidate
  the FOV-derived focal length.
- **`V4L2Source`** — `cv2.VideoCapture` for USB webcams. Requests MJPG, since
  most USB cameras manage only ~5 fps on uncompressed YUYV at this resolution.

### `vision/devices.py`

Enumerates `/dev/video*` and prompts for one. Filters to nodes that can actually
capture — a single physical camera usually registers several nodes and only the
first delivers frames. Falls back gracefully when `v4l2-ctl` isn't installed.

### `vision/fisheye.py`

The correction itself. A fisheye maps a ray at angle θ to radius
`r = f·proj(θ)`; a rectilinear lens maps it to `r = f·tan(θ)`, and `tan` is
precisely the projection under which world-straight lines stay image-straight.
Undistorting means re-projecting between the two, which reduces to a fixed
lookup table — so the per-frame cost is just one `cv2.remap`.

- `LensProfile` — all parameters, load/save to JSON, `clamp()` to keep every
  value in a range that yields a valid map.
- `build_maps()` — builds the lookup table (~50 ms; on startup and on parameter
  changes, never per frame).
- `undistort()` — the only part that runs per frame.

Read the module docstring for the full list of assumptions. It also contains the
calibrated branch that activates once real `camera_matrix` / `dist_coeffs` land
in the profile.

### `vision/overlays.py`

Shared drawing helpers — `draw_grid`, `hovered_cell`, `draw_info_box`,
`draw_cell_info` — so the grid tools and the undistortion tool render overlays
identically and the info-box layout exists in exactly one place.

---

## Output files

| Path | Contents |
| --- | --- |
| `config/lens_profile.json` | Lens parameters. Committed — it is tuning worth keeping. Written by `undistorted*_viewer.py`'s `save`/`w`, and by `camera_studio.py`'s `lens`. |
| `config/camera_settings.json` | Everything `camera_studio.py` can adjust — lens, sensor, framing, orientation. **Read by `camera_studio.py` and the main `camera_feed.py`, written by `save`.** Pass `--settings <path>` to keep several, one per camera position. |
| `captures/` | Snapshots from `s`. Git-ignored. Corrected images are filename-tagged with the parameters that produced them, so several tuning attempts stay comparable. |

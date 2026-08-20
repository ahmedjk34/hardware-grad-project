# Tool Guide

What every Python file is for, when to reach for it, and how to run it.

Setup instructions are in [README.md](README.md) — do that first. All commands
below assume you are in the `python/` directory with the venv active.

---

## Quick reference

| I want to… | Use |
| --- | --- |
| **Correct the fisheye AND measure on the result** | [`undistorted_grid_viewer.py`](#undistorted_grid_viewerpy) |
| Check the camera is connected and working | [`camera_viewer.py`](#camera_viewerpy) |
| Read pixel coordinates off the image | [`grid_viewer.py`](#grid_viewerpy) |
| Estimate real-world sizes in centimetres | [`measured_grid_viewer.py`](#measured_grid_viewerpy) |
| Remove the fisheye distortion / tune the lens model | [`undistorted_viewer.py`](#undistorted_viewerpy) |

All of them exit on `q` or `Esc`, or when you close the window.

The first is the other two grid tools and the undistortion tool merged, and is
the one to reach for by default. The single-purpose viewers are kept because
each is short enough to read end to end when you want to see one stage in
isolation.

---

## `undistorted_grid_viewer.py`

**Use it for:** everything — the corrected preview, tuning the lens model, and
reading positions and sizes off the result. It is the combination that actually
makes sense, because a centimetre grid is only meaningful on a corrected image.

> Every `python ...` line below assumes the venv is **activated**
> (`source .venv/bin/activate`). Inside a venv `python` always exists, on
> both machines. Without activating, use `.venv/bin/python` instead — the Pi
> and the desktop disagree about whether a bare `python3` exists.

```bash
python grid/undistorted_grid_viewer.py
python grid/undistorted_grid_viewer.py --hq                       # sharpest
python grid/undistorted_grid_viewer.py --frame-width-cm 60 --frame-height-cm 45
```

### Driving it — three input channels

OpenCV hands a keystroke to the program **only while the image window has
focus**. Not the terminal. Over VNC or `ssh -X`, often not until the window has
been clicked. This is nearly always the cause of "I press keys and nothing
happens", and there is no way to tell from the outside whether the key arrived.

So this tool takes the same commands three ways, and echoes every one of them
into a log at the bottom of the frame:

| Channel | How | Needs window focus |
| --- | --- | --- |
| **Terminal** | type `fov 158` + Enter in the shell you launched it from | **no** |
| **In-window prompt** | press `:`, type, press Enter (Esc cancels, ↑/↓ for history) | yes |
| **Sliders and keys** | trackbars along the top of the window; single-key shortcuts | mouse: no / keys: yes |

Every keypress is reported, *including ones that are not bound* — so if you
press a key and nothing at all appears in the log, the window does not have
focus and the terminal channel is what you want.

### Commands

Run `help` (in either the terminal or the `:` prompt) for the live list. Numeric
commands take an absolute value **or a signed step**, so `fov 158` and `fov +2`
both work, and choices accept any unambiguous prefix (`model stereo`).

| Command | Does |
| --- | --- |
| `fov <deg\|+N\|-N>` | quoted lens FOV — the main correction knob |
| `out <deg>` | how much of the lens cone to render |
| `scale <f>` | output size relative to the capture |
| `model <name>` | projection curve |
| `ref <diagonal\|horizontal>` | which FOV the lens number refers to |
| `interp <name>` | resampling kernel: `linear`, `cubic`, `lanczos4` |
| `rows <n>` / `cols <n>` | grid divisions — the px/cm ruler only |
| `grid <machine\|off\|px\|cm>` | grid overlay: the rig's cells, or the ruler |
| `origin <corner>` | which image corner holds machine cell `[1,1]` |
| `swapaxes [on\|off]` | machine columns run down the image, not across |
| `map` | print the rig's grid map — hold it next to `9` |
| `view <corrected\|raw\|both>` | which image to show |
| `wcm <cm>` / `hcm <cm>` | the measured span of the whole frame |
| `mip [on\|off]`, `hover [on\|off]` | bare word toggles |
| `show` | dump every current parameter into the log |
| `save` / `snap` / `reset` / `help` / `quit` | as named |

### Keys

| Key | Effect |
| --- | --- |
| `:` | open the command prompt |
| `?` | show / hide the key list on the frame |
| `u` | cycle view: corrected → raw → both |
| `g` | cycle grid: machine → off → px → cm |
| `[` `]` | lens FOV ∓2° — **the main correction-strength knob** |
| `-` `=` | output FOV ∓5° |
| `,` `.` | output scale ∓0.1 |
| `m` / `i` | cycle projection model / interpolation kernel |
| `h` | toggle the hovered-cell readout |
| `c` | clear the measurement points |
| `s` / `w` / `r` | snapshot / write profile / reset |
| `q`, `Esc` | quit |

### Mouse

Hover a grid cell to read its bounds in pixels and, on the corrected view with
`grid cm`, in centimetres. Left-click two points to measure the distance between
them; right-click clears them.

### The machine grid

`grid machine` (the default) draws the **rig's** grid: 10 × 20 cells read from
`config/rig.json`, each labelled with the `col,row` you would type into `G` or
`B`. Hover a cell and it prints the commands for it. `map` prints the same
picture the rig's own `9` prints, so the two can be held side by side.

**Only the numbering is real. The position is not.** The grid is spread over the
whole frame because nothing has yet told the software where the build area is,
and the build area is almost certainly not the whole frame. The amber banner
says so, and Plan 2 step 4 replaces the guess with four clicked corners.

The numbering comes from `printGrid()` in the firmware: 1-based, col 1 on the X
switch side, row 1 on the Y switch side, `[1,1]` drawn bottom-left. If it runs
the wrong way on screen, the camera is mounted turned or mirrored relative to
the rig — `origin <bottom-left|bottom-right|top-left|top-right>` moves `[1,1]`,
and `swapaxes` handles a camera a quarter turn out. Eight combinations, and the
edge labels carry a `c`/`r` prefix so none of them can be read ambiguously.

`rows` / `cols` do not apply here — the rig divides its envelope into exactly
these cells, so a machine grid with a different cell count would be a lie. Those
two still drive the px/cm ruler.

### The centimetre readings

`--frame-width-cm` / `--frame-height-cm` (live: `wcm` / `hcm`) say what physical
rectangle the **whole frame** spans. Everything in centimetres is that span
scaled linearly, which assumes a flat plane viewed square-on — so:

- it is only offered on the **corrected** view. Ask for `grid cm` on the raw
  fisheye and you get pixels plus a warning, because centimetres per pixel there
  grows by a factor of three toward the edges.
- it is still an estimate on the corrected view, because the correction itself
  is built on an estimated FOV rather than a calibration.
- it only describes objects lying in the plane you measured the span against.
  A block 5 cm tall reads wide.

Treat it as a working approximation, not a measurement, until the checkerboard
calibration lands.

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

## `grid_viewer.py`

**Use it for:** reading image coordinates. Overlays an 8×8 grid; hover any cell
to see its row/column index and pixel bounds.

```bash
python grid/grid_viewer.py
python grid/grid_viewer.py --rows 6 --cols 12   # any grid size
```

**Hover readout:**

```
cell (row=3, col=5)
start: (810, 364)
end:   (972, 486)
size:  162 x 122
```

Also a quick way to *see* the distortion: the grid lines are perfectly straight,
so any real straight edge that diverges from them is showing you the barrel
effect.

---

## `measured_grid_viewer.py`

**Use it for:** rough real-world measurements. Same grid, but labelled in
centimetres and metres instead of pixels.

```bash
python grid/measured_grid_viewer.py                                  # built-in defaults
python grid/measured_grid_viewer.py --frame-width-cm 60 --frame-height-cm 30
```

You tell it the physical span of the **whole frame** — measure it by hand with a
tape measure across what the camera actually sees. Defaults are 20 cm (X) ×
35 cm (Y), editable at the top of the file or via the flags above.

**Hover readout:**

```
cell (row=3, col=5)
px:  (810,364) -> (972,486)
X: 12.50cm -> 15.00cm  (w=2.50cm / 0.0250m)
Y: 13.13cm -> 17.50cm  (h=4.37cm / 0.0437m)
```

> **Caveat that matters.** The cm conversion is a straight linear scaling, which
> assumes an ideal flat projection. The raw fisheye is nothing of the sort —
> centimetres per pixel grows sharply toward the edges, so readings away from
> the centre will come out short. Numbers near the frame edge are effectively
> meaningless until the feed is both undistorted *and* properly calibrated.

---

## `undistorted_viewer.py`

**Use it for:** the corrected live preview, and for tuning the lens model by eye.
This is the main camera tool.

```bash
python camera/undistorted_viewer.py                                   # defaults
python camera/undistorted_viewer.py --hq                              # sharpest
python camera/undistorted_viewer.py --output-fov 140 --output-scale 1.5
python camera/undistorted_viewer.py --backend v4l2 --device /dev/video0
```

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

### The HUD

```
PROFILE: ESTIMATED (uncalibrated)          ← amber until real calibration exists
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
that was never captured, so the corners will look soft no matter what. The HUD's
`SAMPLE` line reports both numbers live, so the cost of a parameter change is
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
| `config/lens_profile.json` | Lens parameters. Committed — it is tuning worth keeping. |
| `captures/` | Snapshots from `s`. Git-ignored. Corrected images are filename-tagged with the parameters that produced them, so several tuning attempts stay comparable. |

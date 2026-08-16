# Tool Guide

What every Python file is for, when to reach for it, and how to run it.

Setup instructions are in [README.md](README.md) — do that first. All commands
below assume you are in the `python/` directory with the venv active.

---

## Quick reference

| I want to… | Use |
| --- | --- |
| Check the camera is connected and working | [`camera_viewer.py`](#camera_viewerpy) |
| Read pixel coordinates off the image | [`grid_viewer.py`](#grid_viewerpy) |
| Estimate real-world sizes in centimetres | [`measured_grid_viewer.py`](#measured_grid_viewerpy) |
| Remove the fisheye distortion / tune the lens model | [`undistorted_viewer.py`](#undistorted_viewerpy) |

All four exit on `q` or `Esc`, or when you close the window.

---

## `camera_viewer.py`

**Use it for:** confirming the camera is alive. Raw feed, zero processing — the
first thing to run after touching wiring, and the tool to use when adjusting
focus, exposure or physical framing.

```bash
python camera_viewer.py                    # auto-detect the camera
python camera_viewer.py --backend v4l2     # force the /dev/video* picker
python camera_viewer.py --device /dev/video0
python camera_viewer.py --width 640 --height 480
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
python grid_viewer.py
python grid_viewer.py --rows 6 --cols 12   # any grid size
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
python measured_grid_viewer.py                                  # built-in defaults
python measured_grid_viewer.py --frame-width-cm 60 --frame-height-cm 30
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
python undistorted_viewer.py                                   # defaults
python undistorted_viewer.py --output-fov 140 --output-scale 1.5
python undistorted_viewer.py --backend v4l2 --device /dev/video0
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
in 1296x972   28.4 fps  view CORRECTED
```

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

### Why the output FOV defaults to 120°, not 160°

Rectilinear projection stretches by 1/cos, so rendering the full 160° would
smear the corners enormously and shrink the centre to about 25% scale. At 120°
the centre sits at 0.81× and the corners stay usable.

This is a *projection extent* choice, not a crop to the workspace — nothing is
being trimmed to make the picture look tidy. To keep more field:

```bash
python undistorted_viewer.py --output-fov 150 --output-scale 1.5
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

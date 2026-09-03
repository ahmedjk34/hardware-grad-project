# Python — Camera & Vision

Camera capture, fisheye lens correction, and preview/measurement tools for the
Raspberry Pi 5 + OV5647 160° fisheye setup.

For a detailed walkthrough of every tool — what each is for, when to reach for
it, and how to read its output — see **[GUIDE.md](GUIDE.md)**. This file covers
setup and layout.

## Layout

```
python/
├── rig_console.py              type commands at the Arduino over USB
├── grid/                       tools that draw a measurement grid
│   ├── undistorted_grid_viewer.py  correction + grid  ← the main tool
│   ├── grid_viewer.py              grid overlay labelled in pixels
│   └── measured_grid_viewer.py     grid overlay labelled in centimetres
├── camera/                     configured preview, grid calibration and build UI
│   ├── camera_feed.py              config-driven runtime feed ← the main camera script
│   ├── gridded_camera_feed.py      same feed + calibrated physical machine grid
│   ├── rig_build_v1.py             select camera-grid cell + confirm Arduino build
│   ├── color_grid_check.py         prove the printed calibration sheet is detected
│   ├── camera_studio.py            tune EVERY setting, save them to JSON
│   ├── camera_viewer.py            raw preview — "is the camera alive?"
│   └── undistorted_viewer.py       live fisheye-corrected preview
├── config/
│   ├── lens_profile.json       lens parameters (currently estimated)
│   └── camera_settings.json    camera_studio.py writes; camera_feed.py reads
├── rig/                        importable library — the Arduino side
│   ├── config.py               loads config/rig.json
│   ├── grid.py                 the machine's cells, and which way round they sit
│   ├── build_controller.py     selection/confirmation outcome safety state
│   ├── build_job.py            runs one build off the UI thread, one at a time
│   ├── link.py                 the serial link: send a command, wait for the answer
│   └── build_log.py            append-only logs/{build,serial}.log for a web run
├── tests/
│   ├── test_block_detector.py  block detection against the committed captures
│   ├── test_build_controller.py camera-build confirmation and lockout rules
│   ├── test_build_job.py       the build worker thread and its one-at-a-time rule
│   ├── test_camera_frame_pump.py stale-camera UI isolation without a camera
│   ├── test_color_correction.py the colour transform and Studio's COLOUR section
│   ├── test_color_grid.py      the printed sheet, on synthetic and real captures
│   ├── test_grid.py            the cell numbering, against the firmware's own map
│   └── test_link.py            link.py against a fake board — no rig needed
└── vision/                     importable library — no windows, no argv, no prints
    ├── camera_source.py        Picamera2 on the Pi, V4L2 elsewhere
    ├── block_detector.py       colour + contour block detection and geometry
    ├── commands.py             the typed-command engine the viewers share
    ├── devices.py              /dev/video* enumeration and picker
    ├── fisheye.py              the fisheye → rectilinear correction
    ├── color_correction.py     the saved colour transform, and how to solve one
    ├── color_grid.py           find the printed calibration sheet, fit a grid to it
    ├── color_grid_overlay.py   draw that fitted sheet and the envelope it implies
    └── overlays.py             shared OpenCV drawing helpers
```

`grid/` and `camera/` hold the things you run. `camera/camera_feed.py` is the
main camera script and the foundation for the future vision pipeline. It loads
`config/camera_settings.json`, opens the configured source, applies the saved
sensor controls and orientation, renders the saved correction and framing, and
detects the current blocks with colour-coded edges, rotated boxes, centres and
hover coordinates. Press `s` to save an annotated frame and JSON geometry.
Touching blocks are decomposed as known-size four-sided rectangles, including
L, U, side-by-side and end-to-end arrangements, instead of being treated as one
colour blob.
Future robot-coordinate code should consume these detections rather than
opening the camera independently.

`camera/gridded_camera_feed.py` reuses that feed and adds the machine grid from
the repository-level `config/rig.json`. Positive block rectangles are
`2.2 × 6.0 cm`, separated by real gaps (`1.6 cm` along X, `0.8 cm` along Y)
rather than stretched to fill pitch-sized cells. Press `c`, then click the four prompted corners of the
complete 24.3×40 cm holder-motion envelope in this physical order:
home/home, far-X/home-Y, far-X/far-Y, home-X/far-Y. During calibration the UI
shows the next named corner, numbered saved clicks, solid straight edges between
them, and a live line from the last click to the cursor. After the fourth click,
inspect the closed outline and press Enter to save; press `u` to undo a
misplaced corner or `x` to cancel without replacing the old map. Cyan edges are
screen-horizontal, magenta edges screen-vertical, and orange edges diagonal
(within a 2-pixel click tolerance). It saves the generated map to
`config/workspace_map.json`; until then the amber full-frame grid is explicitly
an approximation. Hovering a calibrated cell shows its `[col,row]`, physical
centre and matching `G` command.

There are two grids, and which one is live decides every coordinate. The
`vertical` grid is `6 × 5` (blocks standing, `6 × (2.2 + 1.6) = 22.8 cm` by
`5 × (6.0 + 0.8) = 34 cm`); the `horizontal` grid is `2 × 10` (blocks lying,
`2 × (6.0 + 1.6) = 15.2 cm` by `10 × (2.2 + 0.8) = 30 cm`). Vertical ships at
`trim 0`; horizontal at `trim_x = trim_y = +1.9 cm` (pickup-cell registration).
Both fit inside the travel with far-end slack. Including
coordinate zero, commands span col `0..cols` and row `0..rows`: `[0,0]` home,
`[col,0]` X-only, and `[0,row]` Y-only. `MachineGrid.from_config(mode=...)`
gives you either; `rig.json`'s `grid.active_mode` picks the default.

A calibration is per mode and never transfers between them. The generated
`config/workspace_map.json` stores both entries under `modes.vertical` and
`modes.horizontal`; recalibrating one preserves the other, and a legacy flat
map migrates as vertical only.

`camera/rig_build_v1.py` adds the serial link and is the first camera UI allowed
to move hardware. Its approximate grid works immediately; a saved calibration
refines the mapping but is optional. A click selects one cell, shows the exact
`B` command, and sends it only after `b`/Enter. The firmware wait happens on a
worker thread (`rig/build_job.py`) and capture happens on a separate frame
worker, so a blocked CSI read leaves the UI responsive and visibly marks the
image stale rather than silently freezing it. Every key and click that would change the build state is refused
until the firmware reports placed/rejected/aborted. An unknown or aborted state
locks the session for human inspection.

`grid/undistorted_grid_viewer.py` is the combined measurement tool and is what
you normally want when checking the machine grid. The smaller viewers beside it
are kept because each is small enough to read in one sitting when you want to
know what one stage does on its own.

`camera/camera_studio.py` sits beside the runtime feed as its settings editor. It
is not the pipeline entry point: every lens, sensor, zoom, crop and orientation
setting is adjustable live — through real Tk entries, dropdowns and buttons
below a separate camera viewport, or as a typed command — and `save` writes the
lot to `config/camera_settings.json`, which `camera_feed.py` reads at startup.
See [GUIDE.md](GUIDE.md#camera_studiopy).

They can be launched from anywhere — each puts `python/` on the import path
itself, so both `python grid/grid_viewer.py` (from `python/`) and
`python python/grid/grid_viewer.py` (from the repo root) work.

`vision/` is the library they share — it deliberately contains no UI, so the
later block-detection and robot-coordinate stages can import it without dragging
a preview along.

`tests/` is one file with plain asserts and no pytest. It exists because
`rig/link.py` decides whether a build succeeded, and none of that logic can be
exercised on the desktop where there is no rig — so it runs against a fake board
built from transcripts:

    cd python
    ../.venv/bin/python tests/test_link.py
    ../.venv/bin/python tests/test_grid.py
    ../.venv/bin/python tests/test_block_detector.py
    ../.venv/bin/python tests/test_build_controller.py
    ../.venv/bin/python tests/test_build_job.py

It proves the parsing and the cell numbering, not the machine. The other half of the testing is
flashing the firmware and watching it.

## Push captures to GitHub

The `python/captures/` directory is ignored by default because camera captures
can be large and are normally generated files. To deliberately publish selected
captures, run these commands from the repository root:

```bash
cd ~/hardware-grad-project
git status --short --ignored python/captures/
git add -f python/captures/
git diff --cached --stat
git commit -m "Add camera captures"
git push origin main
```

Replace `main` with the branch you use. Review `git diff --cached` before
committing and remove unwanted files with `git restore --staged` if necessary.
For very large images or videos, use Git LFS instead of committing them
directly. The `-f` is required because `.gitignore` contains
`python/captures/`.

## `python` or `python3`?

The two machines disagree, and it only matters once.

| Machine | Interpreter that creates the venv |
| --- | --- |
| Raspberry Pi 5 | `python` |
| x86 dev desktop | `python3` |

**After the venv exists, the difference goes away.** A venv always provides
`bin/python`, on every machine — so every command below the venv line uses
`.venv/bin/python` (or plain `python` once the venv is activated) and is
identical on both. `scripts/flash.sh` works this out for itself.

## Setup — Raspberry Pi 5

The Pi 5's CSI camera is reachable **only** through libcamera/Picamera2. Its
`/dev/video*` nodes carry raw Bayer sensor data, so `cv2.VideoCapture` cannot
read the OV5647 there at all.

```bash
# 1. The two things that MUST come from apt, because picamera2 is compiled
#    against the system numpy and the pip wheels would shadow it.
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv python3-numpy python3-tk

# 2. The venv, which can see them thanks to --system-site-packages.
#    On the Pi the interpreter is `python`; on the x86 desktop it is `python3`.
cd ~/hardware-grad-project
python -m venv --system-site-packages .venv

# 3. Everything else, into the venv like normal.
.venv/bin/pip install -r requirements.txt

# 4. Check both halves work.
.venv/bin/python -c "import cv2, picamera2, serial; print('opencv', cv2.__version__)"
```

> **Never `pip install opencv-python` or `numpy` on the Pi.** The apt
> `python3-picamera2` is compiled against the system numpy; a pip wheel pulls a
> newer numpy into the venv, shadows the system one, and breaks
> `import picamera2` with an ABI error.
>
> That restriction is narrower than it looks. `requirements.txt` holds only
> pure-Python packages with no numpy dependency, so it is safe to pip install
> into this venv — and that is where those packages belong. The packages that
> are *not* safe live in `requirements-dev.txt`, which is for the x86 machine.

`--system-site-packages` is what lets the venv see the apt-installed `cv2` and
`picamera2`. Without it, a plain venv sees neither.

**A display is required.** The OpenCV viewers and Camera Studio's Tk window need
a desktop session, so run them on the Pi's own screen or over VNC. Plain `ssh`
has no display; `ssh -X` works but is slow at 1296×972. Camera Studio also needs
the apt-installed `python3-tk` shown above; do not replace its stdlib PPM image
bridge with Pillow.

## Setup — x86 dev machine

No Picamera2 here, so the tools fall back to V4L2 and a USB webcam. Everything
except the CSI capture path can be developed and tested this way.

```bash
python3 -m venv .venv          # `python` on the Pi — see the note below
.venv/bin/pip install -r requirements-dev.txt

.venv/bin/python -c "import cv2, serial; print('opencv', cv2.__version__)"
```

A plain venv here — no `--system-site-packages`, because there is no apt
picamera2 to see. `requirements-dev.txt` pulls in `requirements.txt` as well,
so this one command gets everything.

## Running

```bash
cd ~/hardware-grad-project
python -m venv --system-site-packages .venv
source .venv/bin/activate
cd python
python camera/camera_feed.py
python camera/gridded_camera_feed.py
python camera/rig_build_v1.py
```

Every tool takes `--help`. The lower-level camera viewers share these flags:

| Flag                              | Meaning                                                                  |
| --------------------------------- | ------------------------------------------------------------------------ |
| `--backend {auto,picamera2,v4l2}` | `auto` tries Picamera2 then falls back                                   |
| `--device /dev/video0`            | V4L2 path; skips the interactive picker                                  |
| `--width` / `--height`            | capture resolution (default 1296×972)                                    |
| `--hq`                            | capture the full 2592×1944 sensor readout (the undistorting tools and `camera_studio.py`) |

If you see `Picamera2 unavailable (...); falling back to V4L2` **on the Pi**,
that message is the real error — the fallback will not produce a usable image
from the CSI camera.

To use a different saved setup, pass it explicitly:

```bash
python camera/camera_feed.py --settings ../config/my_camera.json
```

## About the lens correction

The standalone lens viewers read parameters from
[config/lens_profile.json](config/lens_profile.json). The main
`camera_feed.py` reads the matching `lens` block from
`config/camera_settings.json`; `camera_studio.py` keeps the two generated
artefacts together when its `lens` command is used. The parameters are
**estimated, not calibrated**. They come from the vendor's "160°" FOV number
plus an assumed ideal projection curve; the principal point is assumed to be the
exact image centre and tangential distortion is assumed to be zero.

That is enough to make straight edges look substantially straight, and nowhere
near enough to measure with. `undistorted_viewer.py` shows `ESTIMATED` in amber
on the HUD until real calibration data replaces it.

When the quoted FOV alone will not straighten an edge — typically it goes
straight in the middle of the frame but still bends in the last fifth —
`camera_studio.py` adds four hand-tunable trims on top of the ideal model:
`k1`/`k2` reshape the radial curve (zero on the optical axis, growing toward the
edge, which is the shape the FOV number cannot make), and `centre_dx`/`centre_dy`
move the assumed optical axis for a sensor that is not quite centred behind the
lens. All four default to zero, which is an exact no-op.

The default capture mode is 1296×972 — the OV5647's binned readout, which is the
widest 4:3 mode and so preserves the full 160° field. The 1920×1080 mode is a
sensor **centre crop**, not a downscale, and is deliberately never selected.

## About sharpness

Rectilinear correction magnifies the edges of the frame about 3× and slightly
shrinks the centre, so the corrected image is inherently softer at the edges
than the raw one. The HUD's `SAMPLE` line reports this as source pixels per
output pixel; `edge 0.34` means each output pixel there was interpolated from a
third of a source pixel.

`--hq` is the fix that adds real detail rather than redistributing it: it
captures the full 2592×1944 sensor readout instead of the 2×2-binned 1296×972
one and renders the same output size from it, roughly doubling the detail at the
edges at the cost of running at ~15 fps.

If the _raw_ image (press `u`) is soft too, the problem is upstream of all of
this — check the lens focus ring and the light level. See
[GUIDE.md](GUIDE.md#why-the-corrected-image-looks-soft) for the full rundown.

### After checkerboard calibration

Write real `camera_matrix`, `dist_coeffs` and `calibration_size` from
`cv2.fisheye.calibrate` into the same JSON. `vision/fisheye.py` detects them and
switches to the OpenCV fisheye model automatically — output geometry, camera
source and tools all stay unchanged, and the HUD flips to `CALIBRATED`.

## Verification

The correction geometry was checked numerically by tracing output pixels back to
the ground plane and measuring deviation from a straight ground line:

- assumptions exactly right → **0.003 cm** residual (numerical noise; the mapping is exact)
- FOV really 160° but assumed 150° → **~1.7 cm** bow
- FOV really 160° but assumed 140° → **~5.0 cm** bow
- lens really equisolid, assumed equidistant → **~0.09 cm**
- lens really orthographic, assumed equidistant → **~0.9 cm**

The FOV number dominates, which is why it is the primary tuning knob. The
Picamera2 capture path has **not** been verified on real hardware — it was
written on an x86 machine with no CSI camera.

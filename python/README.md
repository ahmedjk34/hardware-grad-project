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
├── camera/                     tools that are just a preview
│   ├── camera_studio.py            tune EVERY setting, save them to JSON
│   ├── camera_viewer.py            raw preview — "is the camera alive?"
│   └── undistorted_viewer.py       live fisheye-corrected preview
├── config/
│   ├── lens_profile.json       lens parameters (currently estimated)
│   └── camera_settings.json    camera_studio.py reads this at startup
├── rig/                        importable library — the Arduino side
│   ├── config.py               loads config/rig.json
│   ├── grid.py                 the machine's cells, and which way round they sit
│   └── link.py                 the serial link: send a command, wait for the answer
├── tests/
│   ├── test_grid.py            the cell numbering, against the firmware's own map
│   └── test_link.py            link.py against a fake board — no rig needed
└── vision/                     importable library — no windows, no argv, no prints
    ├── camera_source.py        Picamera2 on the Pi, V4L2 elsewhere
    ├── commands.py             the typed-command engine the viewers share
    ├── devices.py              /dev/video* enumeration and picker
    ├── fisheye.py              the fisheye → rectilinear correction
    └── overlays.py             shared OpenCV drawing helpers
```

`grid/` and `camera/` hold the things you run. `grid/undistorted_grid_viewer.py`
is the combined one and is what you normally want; the four single-purpose
viewers beside it are kept because each is small enough to read in one sitting
when you want to know what one stage does on its own.

`camera/camera_studio.py` sits apart from all of them: it is not for *using* the
camera but for *deciding what its settings should be*. Every lens, sensor, zoom,
crop and orientation setting is adjustable live — as a labelled text field in a
panel under the image, or as a typed command — and `save` writes the lot to
`config/camera_settings.json`, which it also reads back at startup. The
committed default in that file reproduces `undistorted_viewer.py` exactly, so it
opens on a known picture. See [GUIDE.md](GUIDE.md#camera_studiopy).

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

It proves the parsing and the cell numbering, not the machine. The other half of the testing is
flashing the firmware and watching it.

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
sudo apt install -y python3-picamera2 python3-opencv python3-numpy

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

**A display is required.** `cv2.imshow` needs a desktop session, so run these on
the Pi's own screen or over VNC. Plain `ssh` has no display; `ssh -X` works but
is slow at 1296×972.

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
python camera/undistorted_viewer.py
```

Every tool takes `--help`, and they share these flags:

| Flag                              | Meaning                                                                  |
| --------------------------------- | ------------------------------------------------------------------------ |
| `--backend {auto,picamera2,v4l2}` | `auto` tries Picamera2 then falls back                                   |
| `--device /dev/video0`            | V4L2 path; skips the interactive picker                                  |
| `--width` / `--height`            | capture resolution (default 1296×972)                                    |
| `--hq`                            | capture the full 2592×1944 sensor readout (the undistorting tools and `camera_studio.py`) |

If you see `Picamera2 unavailable (...); falling back to V4L2` **on the Pi**,
that message is the real error — the fallback will not produce a usable image
from the CSI camera.

## About the lens correction

Parameters live in [config/lens_profile.json](config/lens_profile.json) and are
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

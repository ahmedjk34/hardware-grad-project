# Hardware Grad Project

A gantry rig that places blocks on a flat working surface, with an overhead
camera watching the work area.

The repository is split by platform:

| Directory | What it holds |
| --- | --- |
| [arduino/](arduino/) | Firmware sketches for the motion rig — stepper positioning, Z axis, servo, step counting |
| [python/](python/) | Everything on the Raspberry Pi: the config-driven camera feed, lens correction, preview and measurement tools |

## Hardware

- **Controller:** Raspberry Pi 5
- **Motion:** Arduino-driven gantry (X / Y / Z, plus servo)
- **Camera:** DORHEA Raspberry Pi Camera Module — OV5647 sensor, 5 MP, 160° fisheye lens
- **Mounting:** camera ~50 cm above the surface, pointing straight down, roughly centred
- **Workspace:** ~60 cm × 30 cm planar area

## Getting started

- What we are building next → **[plans/](plans/)**
- Rules for editing shared config → **[AGENTS.md](AGENTS.md)**
- Python tools, setup and usage → **[python/README.md](python/README.md)**
- Per-tool walkthrough → **[python/GUIDE.md](python/GUIDE.md)**
- Firmware → open the relevant sketch in `arduino/` with the Arduino IDE

## Main camera feed

[`python/camera/camera_feed.py`](python/camera/camera_feed.py) is the main
camera script. It loads `python/config/camera_settings.json`, applies the saved
capture and sensor settings, detects the visible blocks, and shows the
configured corrected/framed feed with colour-coded edges, centres and hover
coordinates. Press `s` to save an annotated image and detection JSON. Build
future vision stages from this feed so the camera is opened and configured in
one place. Use `camera_studio.py` to tune the settings and save them before
running the feed:

```bash
cd python
../.venv/bin/python camera/camera_studio.py
../.venv/bin/python camera/camera_feed.py
```

## Status

The camera pipeline now includes live block detection with colour-coded edges,
rotated boxes, centres and hover coordinates. Homography, workspace mapping and
robot-coordinate output are not implemented yet. Lens correction runs on
**estimated** parameters — no checkerboard calibration has been performed, so
the image is visually straightened but not measurement-grade. See
[python/README.md](python/README.md) for what that means in practice.

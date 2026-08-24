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
- **Controlled holder displacement:** 24.3 cm X × 40 cm Y
- **Observed build displacement:** 24.3 cm X × 43 cm Y; extra Y reach is not yet modelled
- **Current block grid:** 9 × 5 positive cells; coordinates include col 0..9 and row 0..5
- **Block/gap:** 2.2 cm X × 7.5 cm Y × 1.5 cm Z, with 0.5 cm between cells

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

To see the physical 9×5 positive-cell grid on that same feed, run
`camera/gridded_camera_feed.py`. It shows an amber approximation initially;
press `c` and click the four prompted 24.3×40 cm holder-envelope corners to save
the calibrated overlay.

Calibrating by eye is optional. A printed green/magenta sheet at the rig's own
cell geometry (7.5 × 2.2 cm cells, 0.5 cm inner margins) can be measured
instead: press `p` to overlay it and `k` to calibrate from it, in either
`gridded_camera_feed.py` or `rig_build_v1.py`, and check the detection first
with `camera/color_grid_check.py`. See
[plans/printed-color-grid.md](plans/printed-color-grid.md).

`camera/rig_build_v1.py` connects that view to the Mega and can build from the
initial approximate grid without calibration. Click a cell, choose the
block-stack level, then press `b` or Enter to confirm the displayed Arduino
`B` command. Press `c` only when you want to refine the camera mapping.

## Status

The camera pipeline now includes live block detection, four-corner homography,
physical workspace mapping, cell selection and confirmed serial build commands.
Autonomous block-to-target decisions are not implemented. Lens correction runs on
**estimated** parameters — no checkerboard calibration has been performed, so
the image is visually straightened but not measurement-grade. See
[python/README.md](python/README.md) for what that means in practice.

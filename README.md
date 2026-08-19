# Hardware Grad Project

A gantry rig that places blocks on a flat working surface, with an overhead
camera watching the work area.

The repository is split by platform:

| Directory | What it holds |
| --- | --- |
| [arduino/](arduino/) | Firmware sketches for the motion rig — stepper positioning, Z axis, servo, step counting |
| [python/](python/) | Everything on the Raspberry Pi: camera capture, lens correction, preview and measurement tools |

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

## Status

The camera pipeline currently ends at a corrected live preview. Block detection,
homography, workspace mapping and robot-coordinate output are not implemented
yet. Lens correction runs on **estimated** parameters — no checkerboard
calibration has been performed, so the image is visually straightened but not
measurement-grade. See [python/README.md](python/README.md) for what that means
in practice.

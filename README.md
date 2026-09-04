# Hardware Grad Project

**Vision-Assisted Cartesian Robotic System for 3D Block Construction**

A robotic cell that stacks wooden blocks into 3D structures with no human
placing a single block by hand. Blocks live in a hopper; a feeder stage doses
them one at a time onto a belt and stages each one at a fixed pickup point; a
Cartesian gantry with a rotating claw picks each block up and places it at a
commanded grid cell; an overhead camera watches the build surface throughout
and verifies what actually landed. A human designs the structure in a browser
in 3D — the system compiles that design into the build program and runs it.

Three controllers, one brain:

| Controller | Owns | Talks to the Pi over |
| --- | --- | --- |
| **Raspberry Pi 5** | vision, web server/Studio, orchestration — **the master** | — |
| **Arduino MEGA 2560** | the gantry: X/Y/Z motion, claw, rotation, placement | serial (built, in daily use) |
| **Arduino Uno** | the feeder module: container, belt, alignment | serial (firmware prototype; not integrated — see [Status](#status)) |

## The end-to-end flow

1. **Feed.** The Pi tells the Uno to release a block. The container opens in
   two stages so blocks queue and drop one at a time. An ultrasonic sensor at
   the container's exit confirms a block actually left the container onto the
   belt — not just that the container is open.
2. **Stage.** The belt carries the block toward the pickup area. A second
   servo nudges it square as it arrives. A second ultrasonic sensor at the
   pickup area detects the block is in position and stops the belt. The Uno
   reports "block ready" back to the Pi. This closes the loop at both ends of
   the feed path instead of guessing on a timer.
3. **Place.** The Pi hands off to the Mega. The claw picks the staged block up
   from the fixed pickup point (grid cell `[0,0]`), optionally rotates 90° if
   the build needs the block laid the other way round, moves to the target
   `[col, row, level]`, and releases it. The Mega narrates every phase of the
   ~14-step build back over serial so the Pi always knows exactly where the
   build is, never guesses from a timeout.
4. **See.** An overhead fisheye camera on the Pi watches the whole surface.
   Colour-corrected block detection maps camera pixels to physical
   centimetres to grid cells, calibrated either from a printed reference sheet
   or by having the rig place its own blocks and measuring the lattice from
   them. The camera verifies each placement against what was actually
   commanded.
5. **Design & run.** A human designs the structure ahead of time in the
   browser-based **3D Build Studio**: place blocks in a live 3D scene, get
   immediate physics feedback (support, collisions, toppling), and compile the
   finished design into an ordered pick/place/rotate program. A **digital
   twin**, synced to the real build's serial telemetry, mirrors the physical
   rig live in the browser while it runs. Running the program repeats steps
   1–4 once per block until the structure is complete.

Autonomous "which block goes where" planning is not part of this project —
the human designs the structure; the system is responsible for building
exactly that design reliably, with closed-loop feedback at every stage instead
of open-loop timing.

## Hardware

- **Controllers:** Raspberry Pi 5 (master) + Arduino MEGA 2560 (gantry) +
  Arduino Uno (feeder, prototype)
- **Motion:** gantry X / Y / Z, plus a claw servo and an auxiliary rotation
  stepper, driven by the Mega
- **Feed:** A4988-driven belt, container and alignment servos, and two HC-SR04
  ultrasonic sensors, driven by the Uno
- **Camera:** DORHEA Raspberry Pi Camera Module — OV5647 sensor, 5 MP, 160°
  fisheye lens, mounted ~50 cm above the surface, pointing straight down
- **Controlled holder displacement:** 24.3 cm X × 40 cm Y
- **Observed build displacement:** 24.3 cm X × 43 cm Y; extra Y reach is not
  yet modelled
- **Block:** 2.2 × 6.0 × 1.5 cm, placeable either way round — which is why
  there are two calibrated grids, not one:
  - **vertical** (2.2 X × 6.0 Y cm block): 6 × 5 positive cells
  - **horizontal** (6.0 X × 2.2 Y cm block): 2 × 10 positive cells

## Repository layout

| Directory | What it holds |
| --- | --- |
| [arduino/](arduino/) | Firmware. `build_test_v1/` is the gantry sketch that matters; `belt_v1/` and `container_servo_test/` are the feeder-module prototypes |
| [python/](python/) | Everything on the Raspberry Pi: camera feed, lens/colour correction, block detection and grid calibration, the serial link to the Mega, the FastAPI web server |
| [web/](web/) | The React PWA: the operator console (click-to-build) and the 3D Build Studio (design, validate, compile, run, digital twin) |
| [docs/](docs/) | Living reference docs — how the console and Studio actually work, grid/calibration geometry, block vision internals, the server guide, the visual design language |
| [plans/](plans/) | Historical/archived plans only; anything built has been folded into `docs/` — see [plans/README.md](plans/README.md) |

## Status

| Module | State |
| --- | --- |
| Gantry motion + pick/place (Mega) | **built**, in daily use — two grid orientations, acknowledged 14-phase build protocol |
| Camera vision + grid calibration (Pi) | **built** — block detection, colour correction, multiple calibration routes (printed sheet, self-calibration from placed blocks) |
| Web operator console | **built** — all ten build steps (see [docs/CONSOLE.md](docs/CONSOLE.md)) |
| 3D Build Studio (design/validate/compile/twin/run) | **built** through Milestone 7 (see [docs/STUDIO.md](docs/STUDIO.md)); Milestone 8 ("wow pass") not started |
| Placement supervision (verify placements, notice human interference) | **designed, not started** — full design at [docs/feature-ideas.md](docs/feature-ideas.md) Appendix A |
| Feeder module — container + belt + dual ultrasonic staging (Uno) | **firmware prototype complete.** `belt_v1.ino` implements two-stage container release, exit confirmation, sensor-stopped belt staging, alignment, timeouts, and structured serial results. It is not yet wired to the Pi or Mega; no orchestration doc yet |
| Feeder ↔ Pi ↔ Mega orchestration | **not started** — the Pi does not yet talk to a second serial device, and the Studio's runner assumes a block is already staged at `[0,0]` |
| Autonomous block-to-target planning | **not implemented**, and out of scope — the human designs the structure |

## Getting started

- Rules for editing shared config (the Pi/Mega contract) → **[AGENTS.md](AGENTS.md)**
- Python tools, setup and usage → **[python/README.md](python/README.md)**
- Per-tool walkthrough → **[python/GUIDE.md](python/GUIDE.md)**
- Firmware → **[arduino/README.md](arduino/README.md)**, open the relevant sketch in `arduino/` with the Arduino IDE
- Uno feeder hardware, state machine and serial protocol → **[docs/feeder-controller.md](docs/feeder-controller.md)**
- Web operator console — how to run it → **[docs/server-guide.md](docs/server-guide.md)**, how it's built → **[docs/CONSOLE.md](docs/CONSOLE.md)**
- 3D Build Studio, current state → **[docs/STUDIO.md](docs/STUDIO.md)**
- What's designed but not yet built → **[docs/feature-ideas.md](docs/feature-ideas.md)**

## Running the camera pipeline

[`python/camera/camera_feed.py`](python/camera/camera_feed.py) is the main
camera script. It loads `python/config/camera_settings.json`, applies the
saved capture and sensor settings, detects the visible blocks, and shows the
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

To see the physical 6×5 (or 2×10) positive-cell grid on that same feed, run
`camera/gridded_camera_feed.py`. It shows an amber approximation initially;
press `c` and click the four prompted 24.3×40 cm holder-envelope corners to save
the calibrated overlay.

`camera/camera_studio.py` also owns the camera's **colour**. Its COLOUR section
white-balances the feed against the printed sheet's paper (`wb`), or matches the
camera to a phone photograph of the same sheet (`colourcal`), and saves the
result so every other tool inherits it. That matters: the rig's cast has been
strong enough to make the sheet's green ink invisible to the grid detector.

Calibrating by eye is optional. Print the canonical
[combined A2 target](docs/assets/combined-calibration-grid.svg) at 100% / actual
size (never "fit to page"). The green/magenta/beige target
carries both block orientations on one page. Align the physical page's
lower-left corner with holder home, press `p` to overlay its detected 8×10
fiducial lattice, and press `k` to calibrate the active mode in either
`gridded_camera_feed.py` or `rig_build_v1.py`, and check the detection first
with `camera/color_grid_check.py`. See
[docs/printed-color-grid.md](docs/printed-color-grid.md).

The two older mode-specific sheets remain detectable as a fallback. The
combined target always uses the `firmware` home convention; it measures one
physical holder plane, while `workspace_map.json` still stores separate
vertical and horizontal entries with their own grid geometry.

When the gantry hides only interior sheet cells, use the non-moving gridded
feed's **Evidence-Assisted Printed-Grid Calibration**: `e` starts a session,
Space accepts each useful safe gantry position, and `k` saves only after the
dashboard reports `READY TO SAVE`. It requires physical evidence around every
workspace boundary and only virtualises missing interior cells. See
[the operator guide](docs/evidence-assisted-printed-grid-calibration.md).

`camera/rig_build_v1.py` connects that view to the Mega and can build from the
initial approximate grid without calibration. Click a cell, choose the
block-stack level, then press `b` or Enter to confirm the displayed Arduino
`B` command. Press `c` only when you want to refine the camera mapping.

Lens correction runs on **estimated** parameters — no checkerboard calibration
has been performed, so the image is visually straightened but not
measurement-grade. See [python/README.md](python/README.md) for what that
means in practice.

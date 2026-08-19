# Plan 1 — Get the cable working

> **ARCHIVED — superseded by [plan-2-click-to-build.md](../plan-2-click-to-build.md).**
> All four steps were built. Steps 1 and 2 are verified; steps 3 and 4 need the
> Pi and the board to confirm. Kept as the record of how the link was set up.

**Goal.** The Pi can flash the Arduino and talk to it. Nothing about cameras,
clicking, or grids. When this is done, the Arduino IDE is no longer needed and
the Pi is in charge.

**Not in this plan:** click-to-build, homography, image mapping, protocol
parsing, firmware edits. Those are Plan 2, written after this lands.

**Frozen:** `arduino/build_test_v1/build_test_v1.ino` is the sketch. USB cable,
Pi USB-A → Mega USB-B. Baud stays 9600 (what the sketch already uses).

---

## Step 1 — Archive the old sketches

Six sketches in `arduino/` and only one is real. Move the rest out of the way so
nobody flashes the wrong one.

```bash
mkdir -p arduino/archive
git mv arduino/build_test_v2 arduino/archive/
git mv arduino/build_test_v1_soft_z_backup arduino/archive/
git mv arduino/position_test_with_always_origin arduino/archive/
git mv arduino/position_test_with_servo arduino/archive/
git mv arduino/position_test_with_z_axis arduino/archive/
git mv arduino/step_counter arduino/archive/
```

Then a short `arduino/README.md` saying v1 is the one on the rig.

**Done when:** `ls arduino/` shows `build_test_v1/`, `archive/`, `README.md`.

---

## Step 2 — One config file

Right now the numbers live in four places: `lens_profile.json`, hardcoded
constants in `undistorted_grid_viewer.py`, argparse defaults, and the firmware.
This step fixes the Python half only.

Create `config/rig.json`:

```json
{
  "serial": {
    "port": "/dev/ttyACM0",
    "baud": 9600
  },
  "grid": {
    "cols": 10,
    "rows": 20
  },
  "frame": {
    "width_cm": 20.0,
    "height_cm": 35.0
  }
}
```

Create `python/rig/config.py` — about 20 lines. Reads the JSON, returns a dict.
That is all it does for now.

Then delete `FRAME_WIDTH_CM` and `FRAME_HEIGHT_CM` from
`undistorted_grid_viewer.py:117-119` and read them from the config instead.

`lens_profile.json` stays exactly where it is. It is written by the viewer's
`save` command, so it is a different kind of file — leave it alone.

**Done when:** `undistorted_grid_viewer.py` still runs, and changing
`frame.width_cm` in `rig.json` changes what the viewer shows.

---

## Step 3 — Upload to the Arduino from the Pi

This is the real test of the cable. If this works, the port, the permissions and
the wiring are all proven.

Install `arduino-cli` on the Pi (one time):

```bash
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
sudo mv bin/arduino-cli /usr/local/bin/

arduino-cli config init
arduino-cli core update-index
arduino-cli core install arduino:avr
```

Give yourself serial permission (one time, needs a logout to take effect):

```bash
sudo usermod -aG dialout $USER
```

Plug the cable in and check the Pi sees the board:

```bash
./scripts/flash.sh boards
```

You want a line showing `/dev/ttyACM0` and a Mega. If it says `/dev/ttyUSB0`
instead, the board is a clone with a CH340 chip — that is fine, put that port in
`config/rig.json` and everything else follows.

Compile, then upload:

```bash
./scripts/flash.sh
```

`scripts/flash.sh` reads the port, the board FQBN and the sketch path from
`config/rig.json`. Run `./scripts/flash.sh compile` for a syntax check without
touching the board.

Two things to know:

- Compiling is also a **syntax check**. Right now there is no way to verify a
  firmware edit without the Arduino IDE. After this step there is.
- You cannot upload while something else has the port open. Close any serial
  monitor first.

**Done when:** `./scripts/flash.sh` succeeds from the Pi and the rig's lights
behave as they do after an IDE upload.

---

## Step 4 — Talk to it from Python

A single script. Type a line, it goes to the Arduino; whatever the Arduino says
comes back on screen. No parsing, no cleverness.

Install pyserial into the venv, on either machine:

```bash
.venv/bin/pip install -r requirements.txt
```

This is safe on the Pi despite the usual pip warning: `pyserial` is pure Python
with no dependencies, so there is no numpy for it to shadow. Only `numpy` and
`opencv-python` have to come from apt there — see `python/README.md`.

Write `python/rig_console.py`, roughly 40 lines:

- open the port from `rig.json`
- wait ~2 seconds (opening the port reboots the Mega and it prints a long
  startup banner — this is normal, let it come)
- one background thread printing everything received
- main loop reading your typed lines and sending them with a `\n`

Run it on the Pi:

```bash
cd python
../.venv/bin/python rig_console.py
```

Then test it against the commands the sketch already has:

| Type this | Expect |
| --- | --- |
| `5` | the full machine report |
| `9` | the ASCII grid map |
| `?` | the help text |
| `0` | X and Y home into their switches |
| `B 3 5 0` | one full pick-and-place cycle |

**Done when:** you type `B 3 5 0` in `rig_console.py` on the Pi and a block gets
placed.

---

## That is Plan 1

Four steps. No camera involved in any of them, so all of it can be worked on at
a desk with the Mega on a USB cable.

Once step 4 works, we write **Plan 2**: turning `rig_console.py` into something
the camera viewer can call, and mapping a click on the image to a `col row`.

Notes and research for that — the exact strings the firmware prints, the GPIO
pin situation, the timing constraints — are parked in `plan-2-research-notes.md`, beside this file. Ignore
it for now.

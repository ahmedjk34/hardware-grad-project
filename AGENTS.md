# AGENTS.md

Rules for anyone — human or agent — editing this repo.

The rig is two machines that have to agree with each other: a Raspberry Pi 5
running Python, and an Arduino MEGA 2560 running compiled C++. **The Arduino
cannot read `config/rig.json`.** It has no filesystem. Its numbers are baked in
at flash time. So a handful of values genuinely exist in two places, and this
file is the list of them.

**If you change one of these, change its partner in the same commit.**

---

## The shared values

### 1. Serial baud — must match exactly or nothing works

| Where | What |
| --- | --- |
| `config/rig.json` → `serial.baud` | what the Pi opens the port at |
| `arduino/build_test_v1/build_test_v1.ino:898` | `Serial.begin(9600)` |
| `arduino/README.md` | states the baud in prose |

A mismatch does not error. You get garbage bytes or silence, which reads like a
dead cable. Change all three together.

### 2. Serial port and board — single source, keep it that way

| Where | What |
| --- | --- |
| `config/rig.json` → `serial.port` | what the Pi opens, **and** what `scripts/flash.sh` uploads to |
| `config/rig.json` → `board.fqbn` / `board.sketch` | what `scripts/flash.sh` compiles |

These are deliberately in one place only. `scripts/flash.sh` reads them, so do
not paste an `arduino-cli` command with a literal `-p /dev/ttyACM0` into a
README or a script — that is how the duplicate comes back.

A genuine Mega enumerates as `/dev/ttyACM0`; a CH340 clone as `/dev/ttyUSB0`.
Switching boards is then a one-line edit to `rig.json`.

### 3. Grid dimensions — the one the firmware forgets

| Where | What |
| --- | --- |
| `config/rig.json` → `grid.cols` / `grid.rows` | **authoritative at runtime** |
| `build_test_v1.ino:515-516` | `GRID_COLS` / `GRID_ROWS` — the compiled default |

The sketch uses no EEPROM, so nothing survives a reset — and opening the USB
port resets the board. Every session therefore starts at the compiled default,
and the Pi pushes `S <cols> <rows>` on connect to overwrite it.

The firmware default should still be kept equal to the config, so that a manual
Arduino Serial Monitor session behaves the same as a Pi-driven one. Editing only
the sketch is the trap: the Pi will silently overwrite it on the next connect.

### 4. Frame span in centimetres

| Where | What |
| --- | --- |
| `config/rig.json` → `frame` | the only copy |
| `undistorted_grid_viewer.py`, `measured_grid_viewer.py` | read it via `rig.config.load()` |

Already centralised. The rule here is: **do not reintroduce a module-level
constant.** Both viewers used to carry their own copy and drifted.

### 5. Firmware command vocabulary

The sketch's commands (`B`, `G`, `S`, `0`, `0+`, `5`, `9`, `Z`, `U`, `D`, `O`,
`C`, `R`, `RR`) are the contract between the two machines.

If you rename a command, change its arguments, or change the text it prints on
success or failure, **grep `python/` for the old form first.** The Pi detects
completion by matching the firmware's own output — there are no status codes.

---

## What must NOT be copied into `config/rig.json`

These are physical facts about the machine. Nothing can push them over serial,
so a copy in the JSON would be a lie that nobody notices until the rig crashes
into something.

- envelope: `5050 × 8500` steps, and the soft limits that define it
- `Z_TRAVEL_CM`, `Z_TRAVEL_STEPS`, `BLOCK_HEIGHT_CM`, build ceiling
- pin assignments, servo angles, motor direction polarity

The firmware owns all of it. If the Pi needs one of these numbers, it parses the
`5` report — it does not keep its own copy.

**The dividing line:** `rig.json` owns what can change without reflashing. The
firmware owns what cannot.

## `config/lens_profile.json` is not config

It is a *generated artefact*. The viewer writes it with its `save` command, and
one day a checkerboard calibration will. Never merge it into `rig.json` — a
calibration run would then be able to silently rewrite your serial port. It is
referenced by path, not by value.

---

## Environment rules that will bite you

**On the Pi, install with `apt`, never `pip`.** The venv is built with
`--system-site-packages` so it can see the apt `python3-picamera2` and
`python3-opencv`. A `pip install` pulls a newer numpy into the venv and breaks
`import picamera2` with an ABI error. This applies to every new dependency —
`pyserial` is `sudo apt install python3-serial`.

**There is no Arduino toolchain on the dev desktop.** `arduino-cli compile` runs
on the Pi and is the only real syntax check. Locally, a `.ino` edit can be
checked with a stub-Arduino g++ harness — that proves it parses, not that it
builds for AVR and definitely not that it behaves.

**A clean compile is not a test.** Anything touching motion, limits or Z has to
be flashed and watched on the physical rig.

**Camera code cannot be verified on the desktop.** The Pi 5's CSI camera is
reachable only through Picamera2. Keep the V4L2 fallback working, and say
plainly which paths are untested when handing work over.

---

## `arduino/archive/` is dead code

Do not flash it, do not fix bugs in it, do not update it to match a change made
in `build_test_v1`. Several archived sketches disagree with the live one about
limit switches and Z travel. `build_test_v1` is the only sketch that matters.

---

## Adding a new shared value

If you add something that has to exist on both sides, **add a row to this file
in the same commit.** A shared value that is not listed here is a shared value
that will drift.

# Plan — Click-to-Build: Raspberry Pi → Arduino

**Goal.** Click a cell in the undistorted camera view on the Pi; the rig places a
block in the corresponding machine cell.

**Frozen decisions**

| Decision | Value | Why |
| --- | --- | --- |
| Canonical firmware | `arduino/build_test_v1/build_test_v1.ino` | Chosen as the freeze target. v2 stays as reference only. |
| Transport | USB cable, Pi USB-A → Mega USB-B | No wiring, no level shifting, no risk. Same path the Arduino IDE uses. |
| Port | `/dev/ttyACM0` (config-driven) | Genuine Mega enumerates as ACM; CH340 clones as `/dev/ttyUSB0`. |
| Baud | 9600 now, 115200 after Phase 6 | 9600 is what v1 ships with; changing it is a one-line firmware edit best done once the link is proven. |
| Grid ownership | Pi config is source of truth, pushed via `S <cols> <rows>` on connect | Avoids hand-syncing a number that lives in two languages. |

**Definition of done for v1 of this feature**

1. Viewer is running, connected, and shows rig status.
2. Operator clicks a cell on the corrected image.
3. Viewer resolves it to `(col, row)`, shows a confirm prompt.
4. On confirm, Pi sends `B <col> <row> <level>` and blocks further clicks.
5. Viewer reports `PLACED` / `REJECTED` / `ABORTED` from the firmware's own output.

---

## 1. Current state

### Firmware — mature, already speaks a line protocol

`build_test_v1.ino` (4071 lines) already implements everything the rig needs to
do. The Pi does not have to invent motion control; it has to drive an existing
command language.

Relevant commands:

| Command | Meaning | Needs newline |
| --- | --- | --- |
| `B <col> <row> <level> [R\|RR\|NR]` | one full pick-and-place cycle | yes |
| `G <col> <row>` | go to cell centre, no pick-and-place | yes |
| `S <cols> <rows>` | change grid divisions live | yes |
| `0` | home X/Y | no |
| `0+` | full reset: Z to bottom, Z to top, home X/Y | yes (or 50 ms idle) |
| `5` | full machine report | no |
| `9` | ASCII grid map + current cell | no |
| `Z` | Z / build calibration table | yes |
| `U` / `D` | jog Z+ / Z− | yes |
| `O` / `C` | servo open / close | yes |
| `R` / `RR` | aux stepper ±180° | yes |
| `?` | reprint help | yes |

Machine geometry as frozen in v1:

- Envelope `5050 × 8500` steps; `X ∈ [-5050, 0]`, `Y ∈ [0, +8500]`
- `GRID_COLS = 10`, `GRID_ROWS = 20` (SECTION 6C) → `505 × 425` step cells
- col 1 = nearest the X switch, row 1 = nearest the Y switch
- `Z_TRAVEL_CM = 26.5`, `BLOCK_HEIGHT_CM = 1.5`, `Z_TRAVEL_STEPS = 1350`
- `BUILD_PARK_AFTER_PLACE = true` — the rig returns to origin after every build
- `B` homes everything itself, including Z. No pre-homing needed from the Pi.

### Python — clean, but the link does not exist

`python/` is ~2.1k lines and stops at a corrected live preview.
**There is no serial code anywhere in the repo.** No pyserial, no `/dev/tty*`.

What is reusable as-is:

- `vision/commands.py` — the typed-command engine (parse, dispatch, edit buffer,
  message log). Pure, no cv2. The rig console and the viewer both reuse it.
- `vision/camera_source.py` — Picamera2 on the Pi, V4L2 elsewhere.
- `vision/fisheye.py` — correction maps, `LensProfile` load/save.
- `vision/overlays.py` — grid drawing, hover cell, text panels.
- `undistorted_grid_viewer.py` — the main tool; already has mouse click handling
  for measurement points, so the click plumbing exists.

### Config is scattered across four places

| Where | What lives there |
| --- | --- |
| `python/config/lens_profile.json` | lens FOV, model, output FOV — written live by the viewer's `save` |
| `undistorted_grid_viewer.py:117-119` | `FRAME_WIDTH_CM = 20.0`, `FRAME_HEIGHT_CM = 35.0` |
| argparse defaults | `--rows 8 --cols 8`, capture size, backend, display scale |
| firmware C++ consts | envelope, grid, Z levels, pins, servo angles |

Two live mismatches:

- Viewer frame is `20 × 35 cm`; root README says the workspace is `~60 × 30 cm`.
- Viewer grid defaults to 8×8 image cells, unrelated to the firmware's 10×20
  machine cells.

---

## 2. The three constraints that shape the design

### 2.1 The firmware talks prose, not protocol

There is no ack, no command ID, no status code. Completion has to be detected by
matching the firmware's own output. These are the exact v1 strings:

| Outcome | Marker | Rig state |
| --- | --- | --- |
| Success | `BUILD COMPLETE - block placed at [<col>,<row>] level <n> (<cm> cm)` | Parked at origin, safe |
| Rejected before motion | `  BUILD REJECTED - <why>` followed by `  Nothing moved.` | Untouched, safe |
| Aborted mid-cycle | `*** BUILD ABORTED - <why>` followed by `*** The claw may still be holding a block.` | **Unknown, possibly gripping a block** |
| Placed but parking failed | `!! BLOCK IS PLACED, BUT PARKING FAILED - see above.` | Block down, position unknown |
| Bad arguments | `  ERROR - use:  B <col> <row> <level> [R\|RR\|NR]` | Untouched, safe |

The distinction between REJECTED and ABORTED matters and must survive into the
UI: rejected is a typo, aborted needs a human to walk over to the rig.

A successful build ends with a `======================================` line,
which is the cleanest end-of-transaction sentinel available.

### 2.2 `buildBlock()` blocks for the entire cycle

Homing, Z travel, servo actuation — all synchronous inside one call. The Arduino
does not read serial during a build. The hardware RX buffer is 64 bytes and
`LINE_BUF_SIZE = 32`.

Consequences the Pi must respect:

- **Strictly one command in flight.** Never pipeline, never queue.
- **Clicks during a build are rejected in the UI**, not buffered.
- **Hard timeout** on every transaction, generous for `B` (a full cycle includes
  two homing passes plus full Z travel — measure it, then budget 3× that).
- Keep every line under 31 characters. `B 10 20 5 RR` is 12, so this is only a
  concern if a future command grows.

### 2.3 Opening the port resets the Mega

USB DTR toggling reboots the board. `setup()` then does `Serial.begin(9600)`,
`delay(1000)`, and prints a multi-screen banner: instructions, limit status, soft
limit status, grid config, servo status, aux stepper status, build config.

The connect sequence must therefore be:

1. Open port, wait ~2 s for the bootloader and `delay(1000)`.
2. Read and discard until the last banner line:
   `>> Z+ is a HARDWARE end stop (pin 29), not a soft limit.`
3. Send `S <cols> <rows>` from config.
4. Send `0+` to establish a known physical state.
5. Only then accept user commands.

---

## 3. Target architecture

```
config/
  rig.json                    NEW — hand-edited intent, single source of truth
  workspace_map.json          NEW — generated by the corner calibration
python/
  rig_console.py              NEW — terminal REPL, no camera (Phase 2 milestone)
  undistorted_grid_viewer.py  existing — gains click-to-build in Phase 5
  config/
    lens_profile.json         existing — generated artifact, stays separate
  rig/                        NEW package
    __init__.py
    config.py                 loads config/rig.json
    serial_link.py            transport: open, banner sync, send line, read until
    protocol.py               typed commands + result parsing
    fake_rig.py               pty-backed firmware simulator for offline testing
    mapping.py                image px → (col, row) via homography
  vision/                     existing, unchanged except config wiring
```

**Why `rig/` is separate from `vision/`.** `vision/` is deliberately UI-free so
later stages can import it. `rig/` gets the same treatment: no cv2, no argv, no
prints. That is what makes `rig_console.py` and `fake_rig.py` possible.

### `config/rig.json` — proposed shape

```json
{
  "serial": {
    "port": "/dev/ttyACM0",
    "baud": 9600,
    "connect_timeout_s": 5.0,
    "command_timeout_s": 10.0,
    "build_timeout_s": 180.0,
    "banner_sentinel": ">> Z+ is a HARDWARE end stop"
  },
  "grid": {
    "cols": 10,
    "rows": 20,
    "push_on_connect": true
  },
  "workspace": {
    "width_cm": 60.0,
    "height_cm": 30.0
  },
  "build": {
    "default_level": 0,
    "default_rotation": "NR",
    "require_confirm": true
  },
  "camera": {
    "backend": "auto",
    "width": 1296,
    "height": 972,
    "hq": false,
    "display_scale": 1.0,
    "lens_profile": "python/config/lens_profile.json"
  }
}
```

**`lens_profile.json` stays separate on purpose.** It is a *generated artifact* —
the viewer writes it with the `save` command and will eventually be written by a
checkerboard calibration. `rig.json` is hand-edited intent. Mixing the two means
a calibration run silently rewrites your serial port. `rig.json` references the
profile by path instead.

Precedence everywhere: **CLI flag > `rig.json` > code default.**

---

## 4. Phases

### Phase 0 — Freeze and tidy

| # | Task | Acceptance |
| --- | --- | --- |
| 0.1 | `git mv` v2, the soft-z backup, and the older position/step sketches into `arduino/archive/` | Only `build_test_v1/` remains at the top of `arduino/` |
| 0.2 | Note in `arduino/README.md` (new) that v1 is canonical and why | A reader knows which sketch is on the rig |
| 0.3 | Flash v1 to the Mega, confirm the banner and a manual `B 3 5 0` in the Arduino Serial Monitor | Known-good baseline before any Pi code exists |

Task 0.3 is not optional. Everything downstream assumes the rig behaves as the
source says it does.

### Phase 1 — Centralized config

| # | Task | Acceptance |
| --- | --- | --- |
| 1.1 | Create `config/rig.json` per the shape above | File exists, committed |
| 1.2 | `python/rig/config.py` — load, validate, typed access, clear error on a missing/malformed file | `Config.load()` returns a usable object |
| 1.3 | Migrate `FRAME_WIDTH_CM` / `FRAME_HEIGHT_CM` out of `undistorted_grid_viewer.py` into `workspace` | Constants gone from the module |
| 1.4 | Migrate `--rows` / `--cols` / capture size / backend defaults to read from config | `argparse` defaults come from config, flags still override |
| 1.5 | Fix the `20 × 35` vs `60 × 30` mismatch by measuring the real frame span and recording it | One number, one place, correct |

### Phase 2 — The link (**testable on the desktop with the Mega plugged in**)

This is the phase that de-risks everything. It needs no camera, so unlike the
vision code it can be fully verified off the Pi.

| # | Task | Acceptance |
| --- | --- | --- |
| 2.1 | Add pyserial. On the Pi it must be `apt install python3-serial`, **not** pip — the existing "don't pip into the venv" rule applies | Import works on both machines |
| 2.2 | `rig/serial_link.py` — `open()`, banner drain to sentinel, `send_line()`, `read_until(markers, timeout)`, `close()`, reconnect | Connects, drains, returns cleanly |
| 2.3 | `rig/fake_rig.py` — pty-backed simulator replaying v1's banner and the five outcome shapes, with a settable fake build duration | Whole stack runs with no hardware |
| 2.4 | `python/rig_console.py` — terminal REPL reusing `vision/commands.py`. Commands: `connect`, `home`, `reset`, `goto`, `build`, `grid`, `report`, `raw`, `quit` | Typing `build 3 5 0` places a block |

> **Milestone.** Task 2.4 working against real hardware proves the entire hard
> part of this project. Everything after it is mapping and UI.

### Phase 3 — Protocol layer

| # | Task | Acceptance |
| --- | --- | --- |
| 3.1 | `rig/protocol.py` — `home()`, `full_reset()`, `goto(col,row)`, `build(col,row,level,rot)`, `set_grid(cols,rows)`, `report()` | Each returns a typed result |
| 3.2 | Result type distinguishing `PLACED` / `REJECTED` / `ABORTED` / `PLACED_NOT_PARKED` / `TIMEOUT`, carrying the firmware's `why` string verbatim | The UI can colour these differently |
| 3.3 | Single-in-flight lock; a second command while busy raises rather than writing to the port | Concurrent calls cannot interleave |
| 3.4 | Connect sequence: drain banner → `S <cols> <rows>` → `0+` → ready | Rig is in a known state before any user command |
| 3.5 | Client-side bounds check against config grid and `level` before sending | Obvious typos never reach the wire |
| 3.6 | Log every byte sent and received to a rotating file | Post-mortem on a failed build is possible |

**Unknown to resolve here:** whether a `PLACED_NOT_PARKED` or `ABORTED` result
should force an automatic `0+` recovery, or stop and demand a human. Default to
**stop and demand a human** — the firmware itself says the claw may still be
holding a block.

### Phase 4 — Image → machine mapping

| # | Task | Acceptance |
| --- | --- | --- |
| 4.1 | Calibration mode in the viewer: click the four workspace corners on the **corrected** image, in a prompted order | Four points captured, drawn, re-clickable |
| 4.2 | Compute a homography from image quad to machine cell space; save to `config/workspace_map.json` with the grid size it was made for | File written, reload works |
| 4.3 | `rig/mapping.py` — `image_px_to_cell(x, y) -> (col, row) | None`, returning `None` outside the workspace | Clicking outside the quad is a no-op |
| 4.4 | Invalidate the map when grid dimensions change; warn loudly rather than silently mis-mapping | Stale map cannot be used by accident |

**Why a homography and not arithmetic.** The camera's orientation and mirroring
relative to the rig is arbitrary, and the firmware's axes have opposite signs
(`X ∈ [-5050, 0]`, `Y ∈ [0, +8500]`). Four clicked corners absorb rotation,
mirroring, sign, and mild perspective in one step, with no sign reasoning by
hand. The lens profile is still *estimated*, so the corrected image is not
metrically exact — but the homography is fitted to the corrected image as it
actually is, which means cell-level accuracy does not depend on the lens
calibration being right. That is the main reason this ordering works.

### Phase 5 — Click to build in the viewer

| # | Task | Acceptance |
| --- | --- | --- |
| 5.1 | Replace the 8×8 image grid with the **machine** grid from config, labelled with machine col/row | Labels match what `9` prints on the rig |
| 5.2 | Rig status in the HUD: disconnected / connected / homing / busy / last result, reusing `MessageLog` | State is always visible |
| 5.3 | Click → resolve cell → **confirm gate** (`arm` toggle or explicit y/n). A click alone must never move a machine | Two deliberate actions required |
| 5.4 | Clicks while busy are refused with a visible message, never queued | Cannot stack builds |
| 5.5 | `build`, `goto`, `home`, `connect`, `level`, `rot` commands added to the viewer's `CommandSet` | Keyboard path parity with the mouse path |
| 5.6 | Level and rotation selectable in the UI, defaulting from config | `B 3 5 2 R` reachable without typing |

### Phase 6 — Hardening

| # | Task | Acceptance |
| --- | --- | --- |
| 6.1 | Firmware: baud 9600 → 115200, config updated to match | Banner readable at the new rate |
| 6.2 | Firmware: emit one machine-readable line beside the human output — `OK B <col> <row> <level>` / `ERR B <why>` | Parser stops depending on prose |
| 6.3 | Simplify `protocol.py` to prefer the machine line, keeping prose parsing as fallback | Both paths tested against `fake_rig` |
| 6.4 | `requirements.txt` / `pyproject.toml`, with the Pi apt caveat documented | Fresh checkout is reproducible |
| 6.5 | Unit tests for `protocol.py` parsing and `mapping.py` against `fake_rig` | CI-able without hardware |

Firmware edits in 6.1 and 6.2 are the only ones this plan makes. There is no
local Arduino toolchain, so they get syntax-checked with a stub-Arduino g++
harness and then must be **flashed and verified on the rig** — the harness proves
they compile, not that they work.

---

## 5. GPIO UART — deferred, documented

Not needed for this plan; recorded so the decision does not have to be re-derived.

- Pi 5: physical **pin 8 = GPIO14 = TXD**, **pin 10 = GPIO15 = RXD**. Use
  `/dev/serial0`. Needs `enable_uart=1` in `/boot/firmware/config.txt` and the
  serial *console* disabled via `raspi-config` (login shell off, hardware on).
- Arduino Mega: **do not use pins 0/1**. They are `Serial`, physically tied to
  the USB chip, and will fight every flash and Serial Monitor session. Use
  **`Serial1` (pin 18 = TX1, pin 19 = RX1)** and keep USB free for debugging.
  This means changing `Serial` to `Serial1` throughout the sketch — non-trivial
  in a 4071-line file, another reason to defer.
- **Level shifting is mandatory.** Arduino TX is 5 V; Pi GPIO is 3.3 V and not
  5 V tolerant. Arduino pin 18 → Pi pin 10 needs a level shifter or a 1k/2k
  divider. Pi TX 3.3 V → Arduino RX is fine as-is. Common ground required.

Because the port lives in `rig.json`, switching later is a config edit plus the
firmware `Serial1` change.

---

## 6. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| `ABORTED` leaves the claw gripping a block at an unknown position | Physical damage on the next command | Stop and demand a human; never auto-retry. Phase 3.2 keeps this distinguishable. |
| Click-to-move with no confirm | A stray click drives a gantry | Confirm gate is Phase 5.3, non-negotiable |
| Lens profile is estimated, not calibrated | Cell boundaries drift toward frame edges | Homography is fitted to the corrected image as-is, so cell accuracy is decoupled from lens accuracy. Revisit if edge cells mis-resolve. |
| Grid changed on the rig via `S` behind the Pi's back | Pi and rig disagree about what cell 3,5 is | Pi pushes `S` on connect and owns the number |
| Mega auto-reset mid-session (cable knock, EMI) | Silent loss of homing reference | Detect the banner appearing unexpectedly; drop to disconnected and force a `0+` |
| Build timeout too tight | False failure on a slow cycle | Measure a real `B` cycle in Phase 0.3, budget 3× |
| 9600 baud + verbose firmware output | Slow transactions, near-full buffers | Phase 6.1 raises it once the link is proven |

---

## 7. Open questions

1. **Build cycle duration** — needs measuring in Phase 0.3 to set `build_timeout_s`.
2. **Max build level** — `maxBuildLevel()` is computed from `MAX_BUILD_HEIGHT_CM`
   and `BLOCK_HEIGHT_CM` at runtime. The Pi should read it from the `Z` table on
   connect rather than duplicating the formula. Confirm the `Z` output is stable
   enough to parse.
3. **Does the Pi need `G` at all**, or is `B` sufficient? `G` is useful for
   dry-running a click without placing a block — worth having as a "preview this
   cell" action in Phase 5.
4. **Recovery policy** after `ABORTED` — plan assumes stop-and-ask. Confirm.
5. **Where does the block feeder sit?** `B` picks from the origin every cycle. If
   the feeder is ever relocated, the mapping calibration is unaffected but the
   build sequence is not.

---

## 8. Suggested order of work

Phase 0 → 1 → 2 in strict order; **stop at task 2.4 and confirm a block is
placed from the terminal.** Then 3, then 4 and 5 (which can overlap), then 6.

Phases 0–3 need only a desktop and a USB cable. Only Phases 4–5 need the Pi, the
camera, and the rig assembled together.

# Plan 2 — Click a cell, place a block

**Goal.** Click a spot on the camera image; the rig places a block there.

**Not in this plan:** block detection, checkerboard lens calibration, stacking
logic, anything autonomous. One click, one block, a human watching.

---

## Where we are

Plan 1 built the cable. What exists now:

| Thing | Where | What it does |
| --- | --- | --- |
| One config file | `config/rig.json` | serial port, baud, board, grid, frame cm |
| Config loader | `python/rig/config.py` | `load()` — used by the viewers already |
| Flash script | `scripts/flash.sh` | compile + upload, reads the config |
| Serial console | `python/rig_console.py` | type a line, the rig gets it |
| Firmware, frozen | `arduino/build_test_v1/` | everything else is in `arduino/archive/` |
| Machine acks | `build_test_v1.ino` SECTION 7C | `@` lines beside the prose. **Written, never flashed** |

**Precondition.** This plan assumes Plan 1 steps 3 and 4 have actually been run
on the Pi with the board attached — `./scripts/flash.sh` succeeded, and
`B 3 5 0` typed into `rig_console.py` placed a block. If that has not happened
yet, do it first. Everything below is built on the assumption that the rig
behaves the way its source code says it does.

## The one thing to understand before starting

**The firmware does not answer questions.** It has no status codes and no
acknowledgements — it prints English prose at you and that is all. So "did the
build work?" is answered by reading its output for one of these:

| What it prints | What it means |
| --- | --- |
| `BUILD COMPLETE - block placed at [3,5] level 0` | worked, rig parked at origin, safe |
| `BUILD REJECTED - <why>` then `Nothing moved.` | bad input, nothing moved, safe |
| `*** BUILD ABORTED - <why>` | **failed halfway. The claw may still be gripping a block. Go look at the rig.** |

That last row is why none of this can be fully automatic yet. REJECTED is a
typo. ABORTED needs a human.

Two more facts that shape every step:

- **The rig goes deaf during a build.** `buildBlock()` runs homing, Z travel and
  the servo all inside one function, and does not read serial while it does. So:
  one command at a time, never queue a second one.
- **Opening the port reboots the board.** That is normal USB serial behaviour.
  It also means the rig forgets everything — including its grid size — every
  time you connect.

---

## Step 1 — Make the console reusable

`rig_console.py` opens the port and prints in a loop. The camera viewer cannot
use that; it needs to *call* something.

Move the port handling into `python/rig/link.py` as a small class:

```python
rig = Rig()          # reads config/rig.json
rig.connect()        # opens port, waits out the reboot banner
rig.send("5")        # sends a line
```

`rig_console.py` then becomes a thin wrapper around it and behaves exactly as
before.

**Done when:** `rig_console.py` works as it did, and the three lines above work
in a Python REPL.

---

## Step 2 — Know when a build has finished

The firmware now also prints a machine-readable line beside each of those prose
messages — `@3 OK col=3 row=5 level=0`, `@3 SAFE ...`, `@3 HELD ...`. Read those
instead of the prose: they are a fixed token in a fixed position.

**Flash the firmware and eyeball those lines in `rig_console.py` before writing
any parser.** They are compile-verified but have never run on the board.

Keep prose matching as a fallback and log when it fires. Delete the fallback
once it has not fired in a while. Details and the full kind list are in
[ack-protocol.md](ack-protocol.md).

Teach `link.py` to send a command and then wait for one terminal outcome, with a
timeout.

While you are there, do the connect sequence properly:

1. open the port and read until `@0 READY` — that line is the end of the banner,
   so no more guessing by wording
2. send `S <cols> <rows>` from `config/rig.json` — the board forgot its grid
3. send `0+` to put the rig in a known state

An unexpected `@0 BOOT` at any other time means the board reset underneath you.
Treat it as a disconnect: the rig has forgotten its grid and its homing.

Refuse to send a second command while one is in flight. Not a nicety: the rig is
not listening, so the second command sits in a 64-byte buffer and arrives late.

**Done when:** `rig.build(3, 5, 0)` returns `placed` / `rejected` / `aborted`
instead of you reading the screen to find out.

---

## Step 3 — Put the machine's grid on the picture

**Implemented in `camera/gridded_camera_feed.py`.**

The viewer draws an 8×8 straightness ruler over the image. The rig thinks in a
9×5 positive block grid with explicit coordinate-zero axes and 0.5 cm gaps.
These are unrelated, which is the core mismatch to fix.

The gridded canonical feed draws the grid from `config/rig.json` and labels the
cells with the machine col/row.

**Done when:** the labels on screen match what `9` prints on the rig.

---

## Step 4 — Turn a click into a cell

**Calibration and hover mapping implemented; sending `G` remains a deliberate
manual verification step.**

Click the four corners of the complete 24.3×40 cm holder envelope once, in a
prompted order. Save them under the active grid mode in
`config/workspace_map.json`; vertical and horizontal calibrations coexist and
never substitute for one another. From those four
points, compute the mapping from image pixel through physical centimetres to a
machine cell. It must preserve every 0.5 cm inter-cell gap instead of drawing
touching pitch-sized rectangles.

**Why four clicks instead of arithmetic.** The camera's rotation and mirroring
relative to the rig is arbitrary, and the machine's axes run in opposite
directions (`X` from 0 to `−4750`, `Y` from 0 to `+8250`). The measured holder
displacements are 24.3 × 40 cm, so scales derive as `4750/24.3` and `8250/40`.
The grid math is exact: X pitch `2.2 + 0.5 = 2.7`, nine pitches = 24.3 cm;
Y pitch `7.5 + 0.5 = 8`, five pitches = 40 cm. Four clicked corners absorb
camera rotation and perspective with no sign-juggling. It also means cell accuracy does not
depend on the lens numbers being correct — and they are still estimates, not a
calibration.

`[0,0]` is the feeder-block centre. Active trims are `+1.1 cm` X (half a
feeder width) and `+3.75 cm` Y (half a feeder length), so positive column
centres are `2.7..24.3 cm` and row centres are `8, 16, 24, 32, 40 cm` from
that centre. The last held block reaches `25.4 × 43.75 cm` far edges, but its
holder centre remains inside the `24.3 × 40 cm` software-travel cap.

**Done when:** clicking a cell prints the right col/row, and sending that cell
with `G <col> <row>` drives the claw to the spot you clicked.

Use `G`, not `B`, for this step. It moves without picking anything up, so a
wrong mapping costs you nothing.

---

## Step 5 — Click to build

**Implemented as the manually confirmed `camera/rig_build_v1.py` V1.**

Wire it together: click → cell → confirm → `B <col> <row> <level>`.

Three rules, all of them safety rather than polish:

- **A click alone must never move the machine.** Click selects; a second
  deliberate action confirms.
- **Clicks during a build are refused, not queued.** Say so on screen.
- **After ABORTED, stop.** Do not auto-retry, do not auto-home. The firmware
  itself says the claw may still be holding a block.

Show the connection state and the last result on the frame, so it is never a
mystery whether the thing is listening.

**Done when:** you click a spot, confirm, and a block lands there.

---

## Later, not now

- **The rest of the ack protocol** — `RECV`, `BUSY`, `RUN` progress events and
  a watchdog. The safety-critical subset is already in the firmware; the rest
  waits for a reason to exist. `RUN` in particular buys a progress bar, not
  safety — the firmware bounds its own motions and reports its own failures.
  See [ack-protocol.md](ack-protocol.md).
- **Baud 9600 → 115200.** One line each side. Worth doing once the link is
  boring, not before.
- **Checkerboard lens calibration.** The corrected image is straightened, not
  measurement-grade. Step 4 is built so this does not block it.
- **GPIO UART instead of USB.** Pi pins 8/10, Arduino `Serial1` on pins 18/19,
  and a level shifter because the Mega's 5 V would damage the Pi. Notes in
  [archive/plan-2-research-notes.md](archive/plan-2-research-notes.md). No reason to bother while USB works.

## Order

1 → 2 in order. Stop after Step 2 and confirm `rig.build(3, 5, 0)` returns
`placed` from a REPL — that is the halfway point and everything after it is
about pictures, not hardware.

Steps 1 and 2 need the board on USB. Steps 3, 4 and 5 need the Pi, the camera
and the rig together.

# Flashing the two Arduinos, from zero

You have never flashed either board on this rig. This is the walkthrough:
what to install, what order to do things in, how to tell each step actually
worked, and what to do when it doesn't. It is deliberately more hand-holding
than `arduino/README.md` (the firmware reference) or
`docs/feeder-controller.md` (the Uno's full protocol and commissioning
checklist) — read this first, then those when you need the detail this
skips.

**Read [AGENTS.md](../AGENTS.md) before changing any number in either
sketch.** A handful of calibration values live in both the firmware and
`config/rig.json`, and editing only one side is the most common way to make
this rig quietly wrong.

## The two boards, in one sentence each

| Board | Sketch | Job | Port field in `config/rig.json` |
| --- | --- | --- | --- |
| Arduino **MEGA 2560** | `arduino/build_test_v1/` | gantry: X/Y/Z motion, claw, rotation, placement | `serial.port` |
| Arduino **Uno** | `arduino/belt_v1/` | feeder: hopper, belt, alignment, staging | `feeder.port` |

They never talk to each other — there is no wire between them. The
Raspberry Pi holds one independent USB serial connection to each and is the
only thing that has ever seen both. Flashing one has no effect on the other,
so you can do this one board at a time.

## 0. Install `arduino-cli` (once per machine)

```bash
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
sudo mv bin/arduino-cli /usr/local/bin/
arduino-cli config init
arduino-cli core update-index
arduino-cli core install arduino:avr
```

Everything below goes through `./scripts/flash.sh`, which wraps
`arduino-cli` and reads the board, sketch path, and port for both roles out
of `config/rig.json` — so you never type a raw `arduino-cli` command with a
literal `-p /dev/ttyACM0` in it. If you ever see that in a README or a
script, it's wrong; fix it there instead of copying it.

## 1. Plug in one board at a time and find its stable path

Plug in **only the Mega first** (unplug the Uno, or don't plug it in yet —
this avoids guessing which `/dev/ttyACM*` is which):

```bash
./scripts/flash.sh boards
```

You'll see something like:

```
Port         Protocol Type              Board Name        FQBN
/dev/ttyACM0 serial   Serial Port (USB) Arduino Mega 2560  arduino:avr:mega
```

A genuine Mega enumerates as `/dev/ttyACM0`; a CH340 clone shows up as
`/dev/ttyUSB0`. Either is fine, but **don't write `/dev/ttyACM0` into
`config/rig.json`** — that path can flip to `ttyACM1` the next time you plug
something else in, and then the Pi silently opens the wrong board. Instead:

```bash
ls -l /dev/serial/by-id/
```

Copy the full stable path it prints (something like
`/dev/serial/by-id/usb-www.Arduino.cc_Arduino_14011-if00`) into
`config/rig.json` → `serial.port`.

Now unplug the Mega, plug in **only the Uno**, and repeat:

```bash
./scripts/flash.sh boards
ls -l /dev/serial/by-id/
```

Copy the Uno's stable path into `config/rig.json` → `feeder.port`. It ships
as an empty string on purpose — the repo refuses to guess a machine-specific
device name for you, and the Pi will refuse to start production until this
is filled in.

Once both paths are recorded you can leave both boards plugged in for
everything that follows. **Never use `/dev/ttyACM0`/`ttyACM1` ordering to
tell the two boards apart** — if they ever come up swapped, that ordering
will lie to you.

## 2. Compile-only first — a syntax check, not proof it works

Before touching real hardware, make sure each sketch actually compiles for
its board:

```bash
./scripts/flash.sh all compile     # syntax-checks both, uploads neither
```

If this fails, fix the sketch before going further — there is no local
Arduino IDE on the dev machine, so this compile *is* your syntax check.
**A clean compile means it builds, not that it behaves.** Anything that
touches motion still has to be flashed and watched on the real rig.

## 3. Flash the Mega (gantry)

```bash
./scripts/flash.sh gantry upload
# or just: ./scripts/flash.sh
```

If the upload fails with a port-busy error, something else has the port
open — almost always a leftover `rig_console.py`, `feeder_console.py`, or
the web server (`python/web/app.py`) still running. Close it and retry; do
not `sudo kill -9` your way past it as a first move.

Watch it come back up. Opening the port **resets the board** — that's just
how USB serial works on a Mega — so on success you should see it reboot and
print its startup banner ending in something like:

```
@0 READY grid=6x5 mode=vertical
```

That `@0 READY` line is the thing every Python client waits for; if you
never see it, the flash technically succeeded but the board isn't talking
(wrong baud is the common cause — it must be 9600 everywhere, see
`AGENTS.md` §1).

**Bench-check it stand-alone, no web server involved:**

```bash
cd python
python rig_console.py
```

This is a dumb terminal: it prints what the board says and sends whatever
you type. Once connected, try:

```
9        # ASCII grid map + current position
5        # full machine report
0        # home X/Y
```

Do **not** send `B <col> <row> <level>` here yet unless you're deliberately
testing motion with the pickup area clear and someone watching — a real
build is real physical motion. `quit` (or Ctrl-D) leaves.

## 4. Flash the Uno (feeder)

```bash
./scripts/flash.sh feeder upload
```

Same port-busy caveat as above. On success, watch for the Uno's boot line:

```
@0 READY firmware=belt_v1 protocol=3 board=uno
```

`firmware=belt_v1` and `protocol=3` are not decorative — `config/rig.json`'s
`feeder.firmware` / `feeder.protocol` must match this **exactly**, or the Pi
will refuse to connect at all (on purpose: better a loud refusal at startup
than talking to the wrong device). If you ever bump the protocol number in
the sketch, update `config/rig.json` in the same commit.

**Bench-check it stand-alone**, with the belt unloaded and nothing near the
sensors yet:

```bash
cd python
python feeder_console.py status
```

You should get a structured status line back with both IR sensors reading
`detected=0` with nothing in front of them. Then work through the full
checklist in [feeder-controller.md §Commissioning](feeder-controller.md) —
direction check, container travel, a single `feed`, and deliberately
triggering each failure case (stage occupied, empty hopper, obstructed
belt) — **before** trusting it near a running gantry. That checklist exists
because a feeder that silently double-loads or stages crooked is a much
worse day than a compile error.

## 5. Only after both pass on their own: run them together

Do not skip ahead to this step. Once both boards have individually shown a
clean boot banner and passed their bench checks:

```bash
cd python
python web/app.py --mock       # first: no hardware, sanity-check the server itself
python web/app.py              # then: the real thing, both ports live
```

Open the web UI and watch the operator log. A real build should show, in
order:

```
[UNO/FEEDER ...]   FEED 1 → ... → @1 OK state=block_ready result=staged
[MEGA/GANTRY ...]  RECV cmd=B ... → fourteen STEP lines → @n OK
```

If you ever see a Mega `B` command go out *before* the matching Uno `OK`,
something is badly wrong — stop and re-read
[docs/mega-pi-communication-audit.md](mega-pi-communication-audit.md); that
ordering is supposed to be structurally impossible, not just usually true.

## Troubleshooting quick table

| Symptom | Likely cause |
| --- | --- |
| `arduino-cli upload` fails, port busy | Something else has the port open — close `rig_console.py` / `feeder_console.py` / the web server and retry |
| No `@0 READY` after upload, garbage instead | Baud mismatch — must be 9600 in the sketch, `config/rig.json`, and `arduino/README.md`, all three |
| Board enumerates but wrong sketch's behavior | You flashed the wrong sketch to the wrong FQBN — double check `config/rig.json` → `board.sketch` / `feeder.sketch` before uploading |
| Pi refuses to connect to the Uno at startup | `feeder.firmware` / `feeder.protocol` in `config/rig.json` don't match the `@0 READY` banner the Uno actually prints |
| Port path keeps changing between reboots | You used `/dev/ttyACM0` instead of the `/dev/serial/by-id/...` path — fix it once, never revisit |
| Build "landed in the wrong place" after a fresh flash | Don't touch a calibration constant yet — read [AGENTS.md's calibration knob reference](../AGENTS.md#the-calibration-knobs--the-complete-reference) first; there are several similar-looking knobs and picking the wrong one hides the real bug |
| Second `FEED`/`B` seems to get ignored or errors immediately | Correct — the rig refuses to queue a second physical operation while one is in flight. Wait for the terminal result, don't retry into the silence |

## What to read next

- [`arduino/README.md`](../arduino/README.md) — the firmware command
  reference for both sketches: every command, every wire, every printed
  line.
- [`docs/feeder-controller.md`](feeder-controller.md) — the Uno's full
  protocol and the complete physical commissioning checklist.
- [`docs/ack-protocol.md`](ack-protocol.md) — the Mega's `@n ACK/STEP/OK`
  protocol, field by field.
- [`docs/mega-pi-communication-audit.md`](mega-pi-communication-audit.md) —
  how the Pi orchestrates both boards as one indivisible operation, and what
  happens when either one fails mid-transaction.
- [`AGENTS.md`](../AGENTS.md) — every calibration number that exists in both
  the firmware and `config/rig.json`, and the one sign convention they all
  share. Required reading before changing any of them.

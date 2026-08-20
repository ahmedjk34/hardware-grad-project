#!/usr/bin/env python3
"""Talk to the rig over the USB cable. Type a line, it goes to the Arduino.

    cd python
    python rig_console.py
    python rig_console.py --home      # run 0+ on connect as well

This is deliberately dumb. It sends what you type and prints what comes back —
no parsing, no waiting for completion, no idea what any command means. The
layer that DOES know is `rig/link.py`, and this file is now a thin wrapper
around it: `Rig` owns the port, the reader thread and the reboot handling, and
this owns the keyboard.

What the firmware understands (build_test_v1)
---------------------------------------------
    5             full machine report
    9             ASCII grid map + current cell
    ?             reprint the help text
    0             home X/Y into their switches
    0+            full reset: Z down, Z up, then home X/Y
    G <col> <row> go to a grid cell, e.g.  G 3 5
    B <col> <row> <level> [R|RR|NR]        one full pick-and-place cycle
    Z             the Z / block-level calibration table
    U / D         jog Z up / down
    O / C         gripper open / close
    R / RR        aux stepper +/-90 degrees

Type `quit` (or Ctrl-D, or Ctrl-C) to leave.

Two things that look like bugs and are not
------------------------------------------
1. Opening the port RESETS the Arduino. That is how USB serial works on a Mega:
   the DTR line toggles and the board reboots. So every launch replays the
   sketch's whole startup banner — several screens of it. `connect()` waits for
   the `@0 READY` at the end of it, then pushes the grid size from
   config/rig.json, because the reset wiped the board's copy.

2. A build takes a long time and the firmware does not read serial while it
   runs. `buildBlock()` is synchronous: homing, Z travel and the servo all
   happen inside one call. So after `B` the rig goes quiet, then prints
   everything at once. Do not send a second command into that silence — this
   console will let you, because it does not track what is in flight. Use
   `Rig.build()` from `rig/link.py` if you want that refused for you.

The `@` lines
-------------
Anything starting with `@` is for the Pi, not for you — `@3 OK col=3 row=5`
beside the prose that says the same thing. They are printed here unchanged so
you can eyeball them. See plans/ack-protocol.md.
"""

import argparse
import sys

from rig.link import Rig, RigError


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--home",
        action="store_true",
        help="send 0+ after connecting. Off by default: opening a console "
             "should not make the machine move on its own.",
    )
    args = parser.parse_args()

    # print() straight from the reader thread, exactly as before. The rig is
    # the only writer, so there is nothing to interleave with.
    def complain(message):
        print(f"\n!! {message}")

    rig = Rig(on_line=print, on_error=complain)

    print(f">> {rig.port_name} @ {rig.baud} — the board is rebooting, banner follows")
    try:
        rig.connect(home=args.home)
    except RigError as exc:
        raise SystemExit(str(exc))

    print(f"\n>> connected. grid pushed: {rig.cols} cols x {rig.rows} rows")
    print(">> type a command and press Enter. 'quit' to leave.\n")

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if line.lower() in ("quit", "exit"):
                break
            rig.send(line)
    except KeyboardInterrupt:
        pass
    finally:
        rig.close()
        print("\n>> closed")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Talk to the rig over the USB cable. Type a line, it goes to the Arduino.

    cd python
    python rig_console.py

This is deliberately dumb. It sends what you type and prints what comes back —
no parsing, no waiting for completion, no idea what any command means. That
belongs in a later layer; this one exists to prove the cable works and to drive
the rig by hand while it does not.

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
    R / RR        aux stepper +/-180 degrees

Type `quit` (or Ctrl-D, or Ctrl-C) to leave.

Two things that look like bugs and are not
------------------------------------------
1. Opening the port RESETS the Arduino. That is how USB serial works on a Mega:
   the DTR line toggles and the board reboots. So every launch replays the
   sketch's whole startup banner — several screens of it. Wait for it to stop.

2. A build takes a long time and the firmware does not read serial while it
   runs. `buildBlock()` is synchronous: homing, Z travel and the servo all
   happen inside one call. So after `B` the rig goes quiet, then prints
   everything at once. Do not send a second command into that silence.
"""

import sys
import threading

import serial

from rig.config import load


def reader(port, stopping):
    """Print everything the rig says, on its own thread, until told to stop.

    Decoding is lenient because a reset mid-line can hand us a partial UTF-8
    sequence, and a garbled character is not worth a traceback.

    `stopping` is what separates "the user typed quit" from "the cable fell
    out". Closing the port under a blocked readline() raises, and without the
    flag every clean exit would end with a false alarm about the hardware.
    """
    while not stopping.is_set():
        try:
            line = port.readline()
        # TypeError is in there because pyserial sets its file descriptor to
        # None on close, and a readline() already blocked on that fd then fails
        # inside os.read rather than raising anything serial-shaped.
        except (serial.SerialException, OSError, TypeError):
            if not stopping.is_set():
                print("\n!! serial port went away — cable unplugged?")
            return
        if line:
            print(line.decode("utf-8", errors="replace").rstrip())


def main():
    cfg = load()["serial"]
    port_name, baud = cfg["port"], cfg["baud"]

    try:
        port = serial.Serial(port_name, baud, timeout=0.2)
    except serial.SerialException as exc:
        # The two failures worth naming: no board, and no permission.
        raise SystemExit(
            f"Cannot open {port_name} at {baud}: {exc}\n"
            "  - board plugged in?    ./scripts/flash.sh boards\n"
            "  - permission denied?   sudo usermod -aG dialout $USER, then log out\n"
            "  - wrong port?          a CH340 clone is /dev/ttyUSB0, set it in "
            "config/rig.json"
        )

    print(f">> {port_name} @ {baud} — the board is rebooting, banner follows")
    print(">> type a command and press Enter. 'quit' to leave.\n")

    stopping = threading.Event()
    listener = threading.Thread(target=reader, args=(port, stopping), daemon=True)
    listener.start()

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if line.lower() in ("quit", "exit"):
                break
            # Every multi-character command in the sketch needs a newline, and
            # the single-character ones tolerate one, so always send it.
            port.write((line + "\n").encode())
    except KeyboardInterrupt:
        pass
    finally:
        # Order matters: flag first, then close, then let the listener notice.
        # Closing while it is still printing can kill the interpreter mid-write.
        stopping.set()
        port.close()
        listener.join(timeout=1.0)
        print("\n>> closed")


if __name__ == "__main__":
    main()

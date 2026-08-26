#!/usr/bin/env python3
"""Interactive arbitrary-angle test for the gripper servo.

The Arduino firmware must be flashed with support for ``V <angle>`` first.
Opening the serial port resets the Mega, so this tool waits for the startup
banner before accepting angles.
"""

from __future__ import annotations

import argparse
import time

import serial

from rig.config import load, serial_port_candidates


def read_available(port) -> list[str]:
    lines = []
    while port.in_waiting:
        line = port.readline().decode("utf-8", errors="replace").strip()
        if line:
            lines.append(line)
    return lines


def main() -> int:
    cfg = load()
    serial_cfg = cfg["serial"]

    parser = argparse.ArgumentParser(description="Test the gripper servo at any angle")
    parser.add_argument("--port", default=serial_cfg["port"],
                        help=f"serial port (default: {serial_cfg['port']})")
    parser.add_argument("--baud", type=int, default=serial_cfg["baud"],
                        help=f"baud rate (default: {serial_cfg['baud']})")
    args = parser.parse_args()

    candidates = serial_port_candidates(args.port)
    print(f"Trying {', '.join(candidates)} at {args.baud} baud; the Mega will reset.")
    try:
        port = None
        last_error = None
        for candidate in candidates:
            try:
                port = serial.Serial(candidate, args.baud, timeout=0.1, write_timeout=1)
                print(f"Connected on {candidate}.")
                break
            except serial.SerialException as exc:
                last_error = exc
        if port is None:
            raise last_error
        with port:
            time.sleep(2.0)
            for line in read_available(port):
                print(line)

            print("Enter an integer angle from 0 to 180 degrees, or q to quit.")
            while True:
                try:
                    raw = input("Servo angle> ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if raw in {"q", "quit", "exit"}:
                    break
                try:
                    angle = int(raw)
                except ValueError:
                    print("Please enter a whole-number angle from 0 to 180.")
                    continue
                if not 0 <= angle <= 180:
                    print("Angle must be between 0 and 180 degrees.")
                    continue

                port.write(f"V {angle}\n".encode("ascii"))
                port.flush()
                time.sleep(0.15)
                for line in read_available(port):
                    print(line)
    except serial.SerialException as exc:
        print(f"Could not open or use the serial port: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

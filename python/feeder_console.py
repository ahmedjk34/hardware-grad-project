#!/usr/bin/env python3
"""Commission the Uno through the same Feeder client used by the web server."""

from __future__ import annotations

import argparse
import time

from rig.feeder import Feeder, FeederError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "feed", "stop", "reset",
                                             "open", "close", "on", "off",
                                             "forward", "reverse", "sensors",
                                             "speed", "manual"))
    parser.add_argument("value", nargs="?",
                        help="steps/s for speed, or a quoted commissioning command")
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()
    feeder = Feeder(on_line=lambda line: print(f"[UNO/FEEDER RX] {line}"))
    try:
        feeder.connect()
        if args.command == "feed":
            result = feeder.feed(timeout=args.timeout)
            print(f"staged: transaction={result.request_id} state={result.state}")
        elif args.command == "reset":
            feeder.close()
            time.sleep(0.5)
            feeder.connect()
            print("reset observed: READY identity validated")
        elif args.command == "stop":
            feeder.stop()
            time.sleep(0.3)
        elif args.command == "status":
            feeder.status()
            time.sleep(0.3)
        else:
            command = {"open": "OPEN", "close": "CLOSE", "on": "ON",
                       "off": "OFF", "forward": "F", "reverse": "B",
                       "sensors": "US", "speed": f"S {args.value or ''}",
                       "manual": args.value or ""}[args.command]
            if not command.strip() or (args.command == "speed" and not args.value):
                parser.error(f"{args.command} requires a value")
            feeder.manual(command)
            time.sleep(0.6)
    except FeederError as exc:
        print(f"feeder failed: {exc}")
        return 1
    finally:
        feeder.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

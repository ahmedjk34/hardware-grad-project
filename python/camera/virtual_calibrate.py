#!/usr/bin/env python3
"""Derive one grid mode's workspace map from the other's - no camera, no rig.

    ../.venv/bin/python camera/virtual_calibrate.py --from vertical --to horizontal

``config/workspace_map.json``'s four corners describe the holder-travel
envelope, which is the same for both grid modes (same camera, same lens, same
holder travel - a block lying down does not move a limit switch). So a
calibrated ``vertical`` map already holds what a ``horizontal`` map's corners
need; this pairs them with horizontal's ``config/rig.json`` lattice - its
``+1.9 cm`` pickup-cell registration included - and writes the horizontal entry,
leaving the vertical entry untouched.

It measures nothing. See ``docs/STUDIO.md`` for what that costs: the derived map
is exactly as accurate as the source map and assumes the target mode's firmware
motion compensations land a block on the ideal lattice.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rig.calibration_transfer import (                              # noqa: E402
    CalibrationTransferError,
    transfer_workspace_map,
)
from rig.workspace import WORKSPACE_MAP_PATH                         # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="source", default="vertical",
                        help="the already-calibrated source mode "
                             "(default: vertical)")
    parser.add_argument("--to", dest="target", default="horizontal",
                        help="the mode to derive (default: horizontal)")
    parser.add_argument("--path", type=Path, default=WORKSPACE_MAP_PATH,
                        help="workspace map file "
                             "(default: config/workspace_map.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be written, change nothing")
    args = parser.parse_args(argv)

    try:
        _, report = transfer_workspace_map(
            args.source, args.target, path=args.path, save=not args.dry_run)
    except CalibrationTransferError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(report.describe())
    print()
    print(f"  corners (normalized): {report.corners_normalized}")
    print(f"  target lattice:       {report.target_cols}x{report.target_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
